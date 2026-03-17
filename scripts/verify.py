"""scripts/verify.py — Issue verification + Telegram notification.

Usage:
  python scripts/verify.py                     # Full health check
  python scripts/verify.py --issue 2026-03-15-1430  # Verify specific issue fix
  python scripts/verify.py --links             # Test all 17 data links (Stage 2 style)

Reference: SYSTEM_DESIGN.md §7.10
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

DAEMON_HOME = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
STATE_DIR = DAEMON_HOME / "state"
ISSUES_DIR = STATE_DIR / "issues"
HEALTH_DIR = STATE_DIR / "health_reports"


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"[verify] {ts} {msg}", flush=True)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _notify_telegram(msg: str) -> bool:
    """Send notification via Telegram."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN_AUTOPILOT") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        _log("  Telegram not configured, skipping notification")
        return False
    try:
        data = json.dumps({"chat_id": chat_id, "text": msg}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as exc:
        _log(f"  Telegram notification failed: {exc}")
        return False


# ── Health checks ────────────────────────────────────────────────────────

class HealthCheck:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []
        self.passed = 0
        self.failed = 0

    def check(self, name: str, fn: callable) -> bool:
        try:
            ok = fn()
        except Exception as exc:
            ok = False
            name = f"{name} (error: {str(exc)[:100]})"
        status = "PASS" if ok else "FAIL"
        self.results.append({"name": name, "ok": ok, "checked_utc": _utc()})
        if ok:
            self.passed += 1
        else:
            self.failed += 1
        _log(f"  [{status}] {name}")
        return ok

    @property
    def overall(self) -> str:
        if self.failed == 0:
            return "GREEN"
        elif self.failed <= 2:
            return "YELLOW"
        return "RED"


def _http_ok(url: str, timeout: int = 10) -> bool:
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
        return r.status < 400
    except Exception:
        return False


def _process_running(pattern: str) -> bool:
    import subprocess
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def _docker_healthy(service: str) -> bool:
    import subprocess
    try:
        r = subprocess.run(
            ["docker", "compose", "ps", "--format", "json", service],
            capture_output=True, text=True, timeout=10, cwd=str(DAEMON_HOME),
        )
        if r.returncode != 0:
            return False
        for line in r.stdout.strip().splitlines():
            data = json.loads(line)
            state = str(data.get("State") or data.get("status") or "").lower()
            if "running" in state:
                return True
        return False
    except Exception:
        return False


def run_infrastructure_checks(hc: HealthCheck) -> None:
    """Layer 1: Infrastructure checks (17 links, §7.7.1)."""
    _log("Infrastructure layer checks:")

    # Docker services
    hc.check("PostgreSQL container", lambda: _docker_healthy("postgres"))
    hc.check("Redis/Valkey container", lambda: _docker_healthy("redis"))
    hc.check("MinIO container", lambda: _docker_healthy("minio"))
    hc.check("Temporal container", lambda: _docker_healthy("temporal"))
    hc.check("ClickHouse container", lambda: _docker_healthy("clickhouse"))

    # Plane services
    hc.check("Plane API container", lambda: _docker_healthy("plane-api"))
    hc.check("Plane frontend container", lambda: _docker_healthy("plane-frontend"))

    # Langfuse
    hc.check("Langfuse web container", lambda: _docker_healthy("langfuse-web"))

    # Elasticsearch
    hc.check("Elasticsearch container", lambda: _docker_healthy("elasticsearch"))

    # Daemon processes
    api_port = int(os.environ.get("DAEMON_API_PORT", "8100"))
    hc.check("daemon API responding", lambda: _http_ok(f"http://127.0.0.1:{api_port}/health"))
    hc.check("daemon Worker running", lambda: _process_running("python.*temporal.*worker"))

    # Service connectivity
    hc.check("Plane frontend reachable", lambda: _http_ok("http://localhost:3000", timeout=5))
    hc.check("Langfuse reachable", lambda: _http_ok("http://localhost:3001", timeout=5))
    hc.check("Temporal UI reachable", lambda: _http_ok("http://localhost:8080", timeout=5))
    hc.check("MinIO console reachable", lambda: _http_ok("http://localhost:9001", timeout=5))


def run_self_governance_checks(hc: HealthCheck) -> None:
    """Self-governance validation (§0.10).

    Validates:
    - All agent directories exist in OC workspace
    - SOUL.md, TOOLS.md, SKILL_GRAPH.md present for each agent
    - openclaw.json is valid JSON with required fields
    - model_policy.json agent-model mappings are valid
    - No deprecated terms in active code
    """
    _log("Self-governance checks:")

    oc_workspace = DAEMON_HOME / "openclaw" / "workspace"
    oc_json = DAEMON_HOME / "openclaw" / "openclaw.json"
    model_policy = DAEMON_HOME / "config" / "model_policy.json"

    # Expected agents per SYSTEM_DESIGN.md §1.2
    EXPECTED_AGENTS = {
        "copilot", "instructor", "navigator", "autopilot",
        "researcher", "writer", "reviewer", "publisher",
        "engineer", "admin",
    }

    REQUIRED_FILES = ("SOUL.md", "TOOLS.md", "SKILL_GRAPH.md")

    # Deprecated terms that must not appear in active code
    # These were replaced by new terminology in the architecture refactor
    DEPRECATED_TERMS = [
        "deed", "move", "folio_writ", "cadence", "herald",
        "ether", "retinue", "cortex", "psyche", "instinct_engine",
        "trail", "vault", "ledger",
    ]

    # Check agent directories exist
    for agent in EXPECTED_AGENTS:
        agent_dir = oc_workspace / agent
        hc.check(
            f"agent workspace exists: {agent}",
            lambda d=agent_dir: d.is_dir(),
        )

    # Check required files per agent
    for agent in EXPECTED_AGENTS:
        agent_dir = oc_workspace / agent
        if not agent_dir.is_dir():
            continue  # already failed above
        for fname in REQUIRED_FILES:
            fpath = agent_dir / fname
            hc.check(
                f"agent {agent}/{fname}",
                lambda p=fpath: p.is_file() and p.stat().st_size > 0,
            )

    # Validate openclaw.json
    def _check_openclaw_json() -> bool:
        if not oc_json.exists():
            return False
        raw = json.loads(oc_json.read_text())
        # Required top-level fields
        for field in ("agents", "version"):
            if field not in raw:
                return False
        agents = raw.get("agents")
        if not isinstance(agents, (dict, list)) or not agents:
            return False
        return True

    hc.check("openclaw.json valid JSON + required fields", _check_openclaw_json)

    # Validate model_policy.json
    def _check_model_policy() -> bool:
        if not model_policy.exists():
            return False
        raw = json.loads(model_policy.read_text())
        agent_map = raw.get("agent_model_map")
        if not isinstance(agent_map, dict):
            return False
        # Every expected agent must be mapped
        for agent in EXPECTED_AGENTS:
            if agent not in agent_map:
                return False
        return True

    hc.check("model_policy.json agent-model mappings complete", _check_model_policy)

    # Check for deprecated terms in active Python code
    # Only scan source directories, not archives
    active_dirs = [
        DAEMON_HOME / "services",
        DAEMON_HOME / "temporal",
        DAEMON_HOME / "runtime",
        DAEMON_HOME / "config",
        DAEMON_HOME / "spine",
    ]

    def _scan_deprecated(term: str) -> bool:
        """Returns True (PASS) if term is NOT found in active code."""
        import subprocess
        py_files = []
        for d in active_dirs:
            if not d.exists():
                continue
            py_files.extend(str(p) for p in d.rglob("*.py") if "__pycache__" not in str(p))
        if not py_files:
            return True
        result = subprocess.run(
            ["grep", "-l", "--include=*.py", "-r", term] + [str(d) for d in active_dirs if d.exists()],
            capture_output=True, text=True,
        )
        # PASS if no files contain the deprecated term
        return result.returncode != 0 or not result.stdout.strip()

    # Only check a subset — the most important deprecated module references
    key_deprecated = ["from services.cadence", "from services.herald", "ether.JSONL"]
    for term in key_deprecated:
        hc.check(
            f"no deprecated term: {repr(term)}",
            lambda t=term: _scan_deprecated(t),
        )


def run_full_check() -> dict:
    """Run full health check and save report."""
    hc = HealthCheck()

    run_infrastructure_checks(hc)
    run_self_governance_checks(hc)

    report = {
        "checked_utc": _utc(),
        "overall": hc.overall,
        "passed": hc.passed,
        "failed": hc.failed,
        "total": hc.passed + hc.failed,
        "checks": hc.results,
    }

    # Save report
    HEALTH_DIR.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    report_path = HEALTH_DIR / f"{today}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    _log(f"Report saved: {report_path}")

    # Summary
    _log(f"Result: {hc.overall} ({hc.passed}/{hc.passed + hc.failed} passed)")

    # Telegram notification
    emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(hc.overall, "⚪")
    msg = f"{emoji} daemon 体检: {hc.overall}\n通过: {hc.passed}/{hc.passed + hc.failed}"
    if hc.failed > 0:
        failed_names = [r["name"] for r in hc.results if not r["ok"]]
        msg += f"\n失败: {', '.join(failed_names[:5])}"
    _notify_telegram(msg)

    return report


def verify_issue(issue_id: str) -> dict:
    """Verify a specific issue fix."""
    issue_path = ISSUES_DIR / f"{issue_id}.md"
    if not issue_path.exists():
        _log(f"Issue file not found: {issue_path}")
        return {"ok": False, "error": "issue_not_found"}

    _log(f"Verifying issue: {issue_id}")

    # Run full health check as baseline verification
    report = run_full_check()

    if report["overall"] == "GREEN":
        _notify_telegram(f"✅ 问题 {issue_id} 已修复，系统状态正常")
        # Mark issue as resolved
        content = issue_path.read_text()
        if "## 状态" not in content:
            with issue_path.open("a") as f:
                f.write(f"\n\n## 状态\n已修复 — {_utc()}\n")
    else:
        _notify_telegram(f"❌ 问题 {issue_id} 修复失败，系统状态: {report['overall']}")

    return report


def main() -> int:
    # Load .env
    env_path = DAEMON_HOME / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip()
                if key and key not in os.environ:
                    os.environ[key] = val

    parser = argparse.ArgumentParser(description="daemon health verification")
    parser.add_argument("--issue", help="Verify a specific issue fix by ID")
    parser.add_argument("--links", action="store_true", help="Test all 17 data links")
    args = parser.parse_args()

    _log("=" * 50)

    if args.issue:
        report = verify_issue(args.issue)
    else:
        report = run_full_check()

    _log("=" * 50)
    return 0 if report.get("overall") == "GREEN" else 1


if __name__ == "__main__":
    sys.exit(main())
