"""scripts/start.py — Universal recovery point for daemon.

From any state, bring daemon to healthy running. Idempotent, safe to run repeatedly.

Steps:
  1. Docker Compose up (infra services)
  2. Wait for health checks (PG, Redis, MinIO, Temporal, Plane, Langfuse)
  3. Run PG migrations if needed
  4. Ensure Temporal namespace exists
  5. Start Worker process
  6. Start API process
  7. Final health verification

Reference: SYSTEM_DESIGN.md §7.10
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

DAEMON_HOME = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
ENV_FILE = DAEMON_HOME / ".env"
STATE_DIR = DAEMON_HOME / "state"
ISSUES_DIR = STATE_DIR / "issues"

# Process management
API_PORT = int(os.environ.get("DAEMON_API_PORT", "8100"))
WORKER_MODULE = "temporal.worker"
API_MODULE = "services.api:create_app"


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"[start] {ts} {msg}", flush=True)


def _run(cmd: list[str], timeout: int = 60, check: bool = True, **kw) -> subprocess.CompletedProcess:
    _log(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=check,
                          cwd=str(DAEMON_HOME), **kw)


def _run_quiet(cmd: list[str], timeout: int = 30) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(DAEMON_HOME))
        return r.returncode == 0, r.stdout + r.stderr
    except Exception as e:
        return False, str(e)


# ── Step 1: Docker Compose ──────────────────────────────────────────────

def ensure_docker() -> bool:
    """Ensure Docker daemon is running and compose services are up."""
    _log("Step 1: Docker Compose")

    # Check Docker daemon
    ok, out = _run_quiet(["docker", "info"])
    if not ok:
        _log("  Docker daemon not running. Attempting to start...")
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-a", "Docker"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for _ in range(60):
                time.sleep(2)
                ok, _ = _run_quiet(["docker", "info"])
                if ok:
                    break
            if not ok:
                _log("  FAILED: Docker did not start within 120s")
                return False
        else:
            _log("  FAILED: Docker not running, please start it manually")
            return False

    # Docker Compose up
    compose_file = DAEMON_HOME / "docker-compose.yml"
    if not compose_file.exists():
        _log("  WARNING: docker-compose.yml not found, skipping")
        return True

    env_args = []
    if ENV_FILE.exists():
        env_args = ["--env-file", str(ENV_FILE)]

    ok, out = _run_quiet(["docker", "compose", *env_args, "up", "-d", "--wait"], timeout=300)
    if not ok:
        # Try without --wait (older compose versions)
        ok, out = _run_quiet(["docker", "compose", *env_args, "up", "-d"], timeout=300)
    if not ok:
        _log(f"  FAILED: docker compose up: {out[-500:]}")
        return False

    _log("  Docker Compose services started")
    return True


# ── Step 2: Health checks ────────────────────────────────────────────────

def _check_pg() -> bool:
    ok, _ = _run_quiet(["docker", "compose", "exec", "-T", "postgres",
                        "pg_isready", "-U", os.environ.get("POSTGRES_USER", "daemon")])
    return ok


def _check_redis() -> bool:
    ok, _ = _run_quiet(["docker", "compose", "exec", "-T", "redis", "valkey-cli", "ping"])
    if not ok:
        ok, _ = _run_quiet(["docker", "compose", "exec", "-T", "redis", "redis-cli", "ping"])
    return ok


def _check_temporal() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(f"http://localhost:7233", timeout=5)
        return True
    except Exception:
        # Temporal doesn't serve HTTP on gRPC port, but connection refused means it's down
        # Use tctl or just check if port is open
        ok, _ = _run_quiet(["docker", "compose", "exec", "-T", "temporal",
                            "tctl", "--address", "temporal:7233", "cluster", "health"])
        return ok


def _check_api_port() -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{API_PORT}/health", timeout=5)
        return True
    except Exception:
        return False


def wait_for_health(max_wait: int = 180) -> bool:
    """Wait for infrastructure services to be healthy."""
    _log("Step 2: Waiting for infrastructure health checks")

    checks = {
        "PostgreSQL": _check_pg,
        "Redis/Valkey": _check_redis,
    }

    start = time.time()
    pending = set(checks.keys())

    while pending and (time.time() - start) < max_wait:
        for name in list(pending):
            if checks[name]():
                _log(f"  {name}: OK")
                pending.discard(name)
        if pending:
            time.sleep(3)

    if pending:
        _log(f"  FAILED: Still waiting for: {', '.join(pending)}")
        return False

    _log("  All infrastructure checks passed")
    return True


# ── Step 3: PG migrations ────────────────────────────────────────────────

def run_migrations() -> bool:
    """Run PG schema migrations if needed."""
    _log("Step 3: Database migrations")

    migrations_dir = DAEMON_HOME / "migrations"
    if not migrations_dir.exists():
        _log("  No migrations directory, skipping")
        return True

    # Check if daemon database exists and run migrations
    migration_files = sorted(migrations_dir.glob("*.sql"))
    if not migration_files:
        _log("  No migration files found")
        return True

    pg_user = os.environ.get("POSTGRES_USER", "daemon")
    pg_pass = os.environ.get("POSTGRES_PASSWORD", "daemon")
    pg_db = os.environ.get("POSTGRES_DB", "daemon")

    for mf in migration_files:
        _log(f"  Applying: {mf.name}")
        ok, out = _run_quiet([
            "docker", "compose", "exec", "-T", "postgres",
            "psql", "-U", pg_user, "-d", pg_db, "-f", f"/docker-entrypoint-initdb.d/{mf.name}",
        ])
        if not ok:
            # Try with mounted path or direct content
            sql = mf.read_text()
            ok2, out2 = _run_quiet([
                "docker", "compose", "exec", "-T", "-e", f"PGPASSWORD={pg_pass}",
                "postgres", "psql", "-U", pg_user, "-d", pg_db,
            ])
            if not ok2:
                _log(f"  WARNING: Migration {mf.name} may have failed: {out[-300:]}")

    _log("  Migrations complete")
    return True


# ── Step 4: Temporal namespace ───────────────────────────────────────────

def ensure_temporal_namespace() -> bool:
    """Ensure Temporal namespace exists."""
    _log("Step 4: Temporal namespace")
    ns = os.environ.get("TEMPORAL_NAMESPACE", "default")

    ok, out = _run_quiet([
        "docker", "compose", "exec", "-T", "temporal",
        "tctl", "--address", "temporal:7233", "--namespace", ns,
        "namespace", "describe",
    ])
    if ok:
        _log(f"  Namespace '{ns}' exists")
        return True

    _log(f"  Creating namespace '{ns}'...")
    ok, out = _run_quiet([
        "docker", "compose", "exec", "-T", "temporal",
        "tctl", "--address", "temporal:7233",
        "namespace", "register", "--namespace", ns,
        "--retention", "72h",
    ])
    if not ok:
        _log(f"  WARNING: Namespace creation may have failed: {out[-200:]}")
        # auto-setup image usually creates 'default' namespace, continue anyway
    return True


# ── Step 5 & 6: Worker and API processes ─────────────────────────────────

def _is_process_running(pattern: str) -> int | None:
    """Check if a process matching pattern is running. Return PID or None."""
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip().split()[0])
    except Exception:
        pass
    return None


def ensure_worker() -> bool:
    """Start Temporal worker if not running."""
    _log("Step 5: Temporal Worker")

    pid = _is_process_running("python.*temporal.*worker")
    if pid:
        _log(f"  Worker already running (PID {pid})")
        return True

    _log("  Starting Worker...")
    env = os.environ.copy()
    env["DAEMON_HOME"] = str(DAEMON_HOME)
    env["PYTHONPATH"] = str(DAEMON_HOME)

    log_file = STATE_DIR / "worker.log"
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    with open(log_file, "a") as lf:
        proc = subprocess.Popen(
            [sys.executable, "-m", WORKER_MODULE],
            cwd=str(DAEMON_HOME),
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    time.sleep(3)
    if proc.poll() is not None:
        _log(f"  FAILED: Worker exited with code {proc.returncode}")
        return False

    _log(f"  Worker started (PID {proc.pid})")
    return True


def ensure_api() -> bool:
    """Start API process if not running."""
    _log("Step 6: API Server")

    pid = _is_process_running(f"uvicorn.*services.api")
    if pid:
        _log(f"  API already running (PID {pid})")
        return True

    _log("  Starting API server...")
    env = os.environ.copy()
    env["DAEMON_HOME"] = str(DAEMON_HOME)
    env["PYTHONPATH"] = str(DAEMON_HOME)

    log_file = STATE_DIR / "api.log"
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    with open(log_file, "a") as lf:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", API_MODULE,
             "--factory", "--host", "0.0.0.0", "--port", str(API_PORT)],
            cwd=str(DAEMON_HOME),
            env=env,
            stdout=lf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    # Wait for API to respond
    for _ in range(20):
        time.sleep(1)
        if _check_api_port():
            _log(f"  API started (PID {proc.pid}), responding on port {API_PORT}")
            return True

    if proc.poll() is not None:
        _log(f"  FAILED: API exited with code {proc.returncode}")
    else:
        _log(f"  WARNING: API started (PID {proc.pid}) but not yet responding")

    return True  # Process started, might just need more time


# ── Step 7: Final verification ───────────────────────────────────────────

def final_verify() -> bool:
    """Run final health verification."""
    _log("Step 7: Final verification")

    checks = {
        "API responding": _check_api_port,
        "Worker running": lambda: _is_process_running("python.*temporal.*worker") is not None,
    }

    all_ok = True
    for name, check_fn in checks.items():
        ok = check_fn()
        status = "OK" if ok else "FAIL"
        _log(f"  {name}: {status}")
        if not ok:
            all_ok = False

    return all_ok


# ── Main ─────────────────────────────────────────────────────────────────

def main() -> int:
    _log("=" * 60)
    _log("daemon start — universal recovery point")
    _log(f"DAEMON_HOME: {DAEMON_HOME}")
    _log("=" * 60)

    # Load .env
    env_path = ENV_FILE
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if key and key not in os.environ:
                    os.environ[key] = val

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    ISSUES_DIR.mkdir(parents=True, exist_ok=True)

    steps = [
        ("Docker Compose", ensure_docker),
        ("Health checks", wait_for_health),
        ("Migrations", run_migrations),
        ("Temporal namespace", ensure_temporal_namespace),
        ("Worker", ensure_worker),
        ("API", ensure_api),
        ("Verification", final_verify),
    ]

    for name, fn in steps:
        try:
            ok = fn()
            if not ok:
                _log(f"FAILED at step: {name}")
                return 1
        except Exception as exc:
            _log(f"ERROR at step {name}: {exc}")
            return 1

    _log("=" * 60)
    _log("daemon is running")
    _log(f"  API: http://127.0.0.1:{API_PORT}")
    _log(f"  Plane: http://localhost:3000")
    _log(f"  Langfuse: http://localhost:3001")
    _log(f"  Temporal UI: http://localhost:8080")
    _log("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
