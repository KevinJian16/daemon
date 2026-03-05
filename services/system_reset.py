"""System reset manager: clean runtime state and rebuild bootstrap baseline."""
from __future__ import annotations

import calendar
import json
import logging
import os
import random
import shlex
import shutil
import signal
import socket
import string
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bootstrap import bootstrap
from daemon_env import load_daemon_env
from runtime.drive_accounts import DriveAccountRegistry

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _iso_ts(v: str) -> float | None:
    try:
        return float(calendar.timegm(time.strptime(v, "%Y-%m-%dT%H:%M:%SZ")))
    except Exception:
        return None


def _is_local_host(host: str | None) -> bool:
    h = str(host or "").strip()
    if not h:
        return False
    if h in {"127.0.0.1", "::1", "localhost"}:
        return True
    return h.startswith("127.")


@dataclass
class ResetTarget:
    name: str
    signatures: list[str]
    ports: list[int]


class SystemResetManager:
    """Performs safe runtime reset with local challenge-confirm guard."""

    def __init__(self, daemon_home: Path) -> None:
        self.home = daemon_home
        load_daemon_env(self.home)
        self.state = self.home / "state"
        self.openclaw_home = self.home / "openclaw"
        self.challenge_path = self.state / "reset_challenge.json"
        self.report_path = self.state / "reset_last_report.json"
        self._drive_registry = DriveAccountRegistry(self.state)
        self._challenge_cache: dict[str, Any] | None = None

    # ── Challenge gate ─────────────────────────────────────────────────────

    def issue_challenge(self, mode: str = "strict", restart: bool = False, ttl_seconds: int = 180) -> dict[str, Any]:
        mode = self._normalize_mode(mode)
        challenge_id = f"rst_{int(time.time())}_{random.randint(1000, 9999)}"
        confirm_code = "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(8))
        payload = {
            "challenge_id": challenge_id,
            "confirm_code": confirm_code,
            "mode": mode,
            "restart": bool(restart),
            "issued_utc": _utc(),
            "expires_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + max(30, int(ttl_seconds)))),
            "used": False,
        }
        self.challenge_path.parent.mkdir(parents=True, exist_ok=True)
        self.challenge_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._challenge_cache = payload
        return payload

    def validate_and_consume_challenge(
        self,
        *,
        challenge_id: str,
        confirm_code: str,
        requester_host: str,
        mode: str | None = None,
        restart: bool | None = None,
    ) -> dict[str, Any]:
        if not _is_local_host(requester_host):
            raise PermissionError("reset_confirm_requires_localhost")
        record = self._read_challenge()
        if not record:
            raise ValueError("reset_challenge_missing")
        if bool(record.get("used")):
            raise ValueError("reset_challenge_already_used")
        if str(record.get("challenge_id") or "") != str(challenge_id or ""):
            raise ValueError("reset_challenge_mismatch")
        if str(record.get("confirm_code") or "") != str(confirm_code or ""):
            raise ValueError("reset_confirm_code_invalid")
        expires = _iso_ts(str(record.get("expires_utc") or ""))
        if expires is None or time.time() > expires:
            raise ValueError("reset_challenge_expired")

        if mode:
            record["mode"] = self._normalize_mode(mode)
        if restart is not None:
            record["restart"] = bool(restart)

        record["used"] = True
        record["confirmed_utc"] = _utc()
        self.challenge_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        self._challenge_cache = record
        return record

    def launch_detached_reset(self, mode: str, restart: bool, reason: str = "api_confirm") -> dict[str, Any]:
        py = self._python_bin()
        script = self.home / "scripts" / "state_reset.py"
        cmd = [str(py), str(script), "--mode", self._normalize_mode(mode)]
        if restart:
            cmd.append("--restart")
        cmd.extend(["--reason", reason, "--from-api"])

        log_path = self.state / "service_logs" / "system_reset.out.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"\n[{_utc()}] launch: {' '.join(shlex.quote(x) for x in cmd)}\n")
            proc = subprocess.Popen(  # noqa: S603,S607
                cmd,
                cwd=str(self.home),
                stdout=f,
                stderr=f,
                start_new_session=True,
                env={**os.environ, "DAEMON_HOME": str(self.home)},
            )
        return {"ok": True, "pid": proc.pid, "command": cmd, "log": str(log_path)}

    def last_report(self) -> dict[str, Any]:
        if not self.report_path.exists():
            return {}
        try:
            data = json.loads(self.report_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # ── Execution ─────────────────────────────────────────────────────────

    def execute(self, mode: str = "strict", restart: bool = False, reason: str = "manual") -> dict[str, Any]:
        mode = self._normalize_mode(mode)
        started = _utc()
        report: dict[str, Any] = {
            "ok": False,
            "mode": mode,
            "restart": bool(restart),
            "reason": reason,
            "started_utc": started,
            "stopped": {},
            "cleaned": {},
            "bootstrap": {},
            "errors": [],
        }

        try:
            report["stopped"] = self._stop_daemon_processes(order=("telegram", "api", "worker", "temporal", "gateway"))
            report["cleaned"] = self._clean_runtime_state(mode)
            report["bootstrap"] = bootstrap(daemon_home=self.home, openclaw_home=self.openclaw_home, force=True)
            if restart:
                report["restarted"] = self._restart_daemon_processes()
            report["ok"] = True
        except Exception as exc:
            logger.exception("System reset failed: %s", exc)
            report["errors"].append(str(exc))
        finally:
            report["finished_utc"] = _utc()
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return report

    # ── Internal: process control ─────────────────────────────────────────

    def _python_bin(self) -> Path:
        venv_py = self.home / ".venv" / "bin" / "python"
        if venv_py.exists():
            return venv_py
        return Path(sys.executable)

    def _targets(self) -> dict[str, ResetTarget]:
        gw_port = self._openclaw_port()
        tg_port = int(os.environ.get("TELEGRAM_ADAPTER_PORT", "8001") or 8001)
        temporal_port = int(os.environ.get("TEMPORAL_PORT", "7233") or 7233)
        temporal_db = str(self.home / "state" / "temporal_dev.db")
        return {
            "telegram": ResetTarget(
                name="telegram",
                signatures=["interfaces/telegram/adapter.py", "TELEGRAM_ADAPTER_PORT"],
                ports=[tg_port],
            ),
            "api": ResetTarget(
                name="api",
                signatures=["uvicorn services.api:create_app", "services.api:create_app"],
                ports=[8000],
            ),
            "worker": ResetTarget(
                name="worker",
                signatures=["temporal/worker.py", "Daemon Worker"],
                ports=[],
            ),
            "temporal": ResetTarget(
                name="temporal",
                signatures=["temporal server start-dev", temporal_db],
                ports=[temporal_port],
            ),
            "gateway": ResetTarget(
                name="gateway",
                signatures=["openclaw gateway run", "node_modules/.bin/openclaw"],
                ports=[gw_port],
            ),
        }

    def _openclaw_port(self) -> int:
        cfg = self.openclaw_home / "openclaw.json"
        if not cfg.exists():
            return 18790
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return int(data.get("gateway", {}).get("port", 18790))
        except Exception:
            return 18790

    def _scan_processes(self) -> list[tuple[int, str]]:
        try:
            out = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)  # noqa: S603,S607
        except Exception:
            return []
        rows: list[tuple[int, str]] = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(None, 1)
            if not parts:
                continue
            try:
                pid = int(parts[0])
            except Exception:
                continue
            cmd = parts[1] if len(parts) > 1 else ""
            rows.append((pid, cmd))
        return rows

    def _pids_by_port(self, port: int) -> set[int]:
        if port <= 0:
            return set()
        try:
            out = subprocess.check_output(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                text=True,
            )  # noqa: S603,S607
        except Exception:
            return set()
        pids: set[int] = set()
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pids.add(int(line))
            except Exception:
                continue
        return pids

    def _match_target_pids(self, target: ResetTarget, proc_rows: list[tuple[int, str]]) -> list[int]:
        hits: set[int] = set()
        for pid, cmd in proc_rows:
            low = cmd.lower()
            if any(sig.lower() in low for sig in target.signatures):
                hits.add(pid)
        if target.ports:
            for p in target.ports:
                port_pids = self._pids_by_port(p)
                for pid, cmd in proc_rows:
                    if pid not in port_pids:
                        continue
                    low = cmd.lower()
                    if any(sig.lower() in low for sig in target.signatures):
                        hits.add(pid)
        return sorted(hits)

    def _wait_pids_exit(self, pids: list[int], timeout_s: float) -> list[int]:
        deadline = time.time() + timeout_s
        alive = set(int(p) for p in pids)
        while alive and time.time() < deadline:
            keep: set[int] = set()
            for pid in alive:
                try:
                    os.kill(pid, 0)
                    keep.add(pid)
                except ProcessLookupError:
                    continue
                except PermissionError:
                    keep.add(pid)
            alive = keep
            if alive:
                time.sleep(0.2)
        return sorted(alive)

    def _port_ready(self, host: str, port: int, timeout_s: float = 1.0) -> bool:
        if port <= 0:
            return False
        deadline = time.time() + max(0.2, timeout_s)
        while time.time() < deadline:
            try:
                with socket.create_connection((host, port), timeout=0.5):
                    return True
            except Exception:
                time.sleep(0.2)
        return False

    def _stop_daemon_processes(self, order: tuple[str, ...]) -> dict[str, Any]:
        report: dict[str, Any] = {}
        targets = self._targets()
        for name in order:
            tgt = targets.get(name)
            if not tgt:
                continue
            matched: list[int] = []
            terminated: list[int] = []
            killed: list[int] = []
            # If launchd restarts a process quickly, kill it again for a few rounds.
            for _ in range(4):
                proc_rows = self._scan_processes()
                pids = self._match_target_pids(tgt, proc_rows)
                pids = [pid for pid in pids if pid not in matched]
                if not pids:
                    break
                matched.extend(pids)
                for pid in pids:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        terminated.append(pid)
                    except ProcessLookupError:
                        continue
                    except Exception as exc:
                        logger.warning("Failed to SIGTERM pid=%s (%s): %s", pid, name, exc)
                alive = self._wait_pids_exit(pids, timeout_s=4.0)
                for pid in alive:
                    try:
                        os.kill(pid, signal.SIGKILL)
                        killed.append(pid)
                    except ProcessLookupError:
                        continue
                    except Exception as exc:
                        logger.warning("Failed to SIGKILL pid=%s (%s): %s", pid, name, exc)
                time.sleep(0.2)
            report[name] = {"matched": sorted(matched), "terminated": sorted(set(terminated)), "killed": sorted(set(killed))}
        return report

    def _restart_daemon_processes(self) -> dict[str, Any]:
        py = self._python_bin()
        openclaw_cfg = self.openclaw_home / "openclaw.json"
        gw_port = 18790
        gw_token = ""
        if openclaw_cfg.exists():
            try:
                cfg = json.loads(openclaw_cfg.read_text(encoding="utf-8"))
                gw_port = int(cfg.get("gateway", {}).get("port", 18790))
                gw_token = str(cfg.get("gateway", {}).get("auth", {}).get("token", ""))
            except Exception:
                pass

        logs = self.state / "service_logs"
        logs.mkdir(parents=True, exist_ok=True)
        procs: dict[str, Any] = {}

        def _spawn(name: str, cmd: list[str], log_name: str) -> None:
            lp = logs / log_name
            f = lp.open("a", encoding="utf-8")
            f.write(f"\n[{_utc()}] start: {' '.join(shlex.quote(x) for x in cmd)}\n")
            proc = subprocess.Popen(  # noqa: S603,S607
                cmd,
                cwd=str(self.home),
                stdout=f,
                stderr=f,
                start_new_session=True,
                env={**os.environ, "DAEMON_HOME": str(self.home), "OPENCLAW_HOME": str(self.openclaw_home)},
            )
            procs[name] = {"pid": proc.pid, "cmd": cmd, "log": str(lp)}

        temporal_bin = shutil.which("temporal") or "/opt/homebrew/opt/temporal/bin/temporal"
        temporal_host = os.environ.get("TEMPORAL_HOST", "127.0.0.1")
        temporal_port_i = int(os.environ.get("TEMPORAL_PORT", "7233") or 7233)
        temporal_port = str(temporal_port_i)
        targets = self._targets()

        def _already_running(name: str) -> dict[str, Any] | None:
            tgt = targets.get(name)
            if not tgt:
                return None
            rows = self._scan_processes()
            pids = self._match_target_pids(tgt, rows)
            if not pids:
                return None
            return {"status": "already_running", "pids": pids}

        if self._port_ready(temporal_host, temporal_port_i, timeout_s=0.6):
            procs["temporal"] = {
                "status": "already_running",
                "host": temporal_host,
                "port": temporal_port_i,
            }
        elif temporal_bin and Path(temporal_bin).exists():
            temporal_ui_ip = os.environ.get("TEMPORAL_UI_HOST", "127.0.0.1")
            temporal_ui_port = str(int(os.environ.get("TEMPORAL_UI_PORT", "8233") or 8233))
            temporal_namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
            temporal_db = str(self.home / "state" / "temporal_dev.db")
            temporal_cmd = [
                temporal_bin,
                "server",
                "start-dev",
                "--ip",
                temporal_host,
                "--port",
                temporal_port,
                "--ui-ip",
                temporal_ui_ip,
                "--ui-port",
                temporal_ui_port,
                "--db-filename",
                temporal_db,
                "--namespace",
                temporal_namespace,
            ]
            _spawn("temporal", temporal_cmd, "temporal.out.log")
            self._port_ready(temporal_host, temporal_port_i, timeout_s=12.0)
        else:
            procs["temporal"] = {"status": "missing_binary", "binary": temporal_bin}

        running = _already_running("gateway")
        if running:
            procs["gateway"] = running
        else:
            gateway_cmd = [
                str(self.home / "node_modules" / ".bin" / "openclaw"),
                "gateway",
                "run",
                "--port",
                str(gw_port),
                "--bind",
                "loopback",
            ]
            if gw_token:
                gateway_cmd.extend(["--token", gw_token])
            _spawn("gateway", gateway_cmd, "openclaw_gateway.out.log")

        running = _already_running("worker")
        if running:
            procs["worker"] = running
        elif self._port_ready(temporal_host, temporal_port_i, timeout_s=5.0):
            _spawn("worker", [str(py), str(self.home / "temporal" / "worker.py")], "worker.out.log")
        else:
            procs["worker"] = {
                "status": "skipped_temporal_unready",
                "host": temporal_host,
                "port": temporal_port_i,
            }

        running = _already_running("api")
        if running:
            procs["api"] = running
        elif self._port_ready("127.0.0.1", 8000, timeout_s=0.6):
            procs["api"] = {"status": "already_running", "host": "127.0.0.1", "port": 8000}
        else:
            _spawn(
                "api",
                [str(py), "-m", "uvicorn", "services.api:create_app", "--factory", "--host", "127.0.0.1", "--port", "8000"],
                "api.out.log",
            )

        tg_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        if tg_token:
            missing: list[str] = []
            if not str(os.environ.get("TELEGRAM_WEBHOOK_SECRET", "") or "").strip():
                missing.append("TELEGRAM_WEBHOOK_SECRET")
            if not str(os.environ.get("TELEGRAM_ALLOWED_USERS", "") or "").strip():
                missing.append("TELEGRAM_ALLOWED_USERS")
            if missing:
                procs["telegram"] = {
                    "status": "skipped_insecure_config",
                    "missing": missing,
                }
            else:
                running = _already_running("telegram")
                if running:
                    procs["telegram"] = running
                else:
                    _spawn(
                        "telegram",
                        [str(py), str(self.home / "interfaces" / "telegram" / "adapter.py")],
                        "telegram.out.log",
                    )

        return procs

    # ── Internal: cleanup ─────────────────────────────────────────────────

    def _normalize_mode(self, mode: str) -> str:
        m = str(mode or "strict").strip().lower()
        if m not in {"strict", "light"}:
            raise ValueError("reset_mode_invalid")
        return m

    def _clean_runtime_state(self, mode: str) -> dict[str, Any]:
        cleaned: dict[str, Any] = {"mode": mode, "removed": [], "truncated": []}

        def _rm(path: Path) -> None:
            if not path.exists() and not path.is_symlink():
                return
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
                cleaned["removed"].append(str(path))
                return
            shutil.rmtree(path, ignore_errors=True)
            cleaned["removed"].append(str(path))

        def _reset_array_file(path: Path) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("[]", encoding="utf-8")
            cleaned["truncated"].append(str(path))

        def _reset_gate(path: Path) -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "status": "GREEN",
                        "services": {},
                        "degraded_services": [],
                        "reasons": [],
                        "updated_utc": _utc(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            cleaned["truncated"].append(str(path))

        # Common runtime artifacts.
        for rel in [
            "state/runs",
            "state/runs_shadow",
            "state/telemetry",
            "state/traces",
            "state/snapshots",
            "state/tmp",
            "state/campaigns",
            "state/feedback_surveys",
            "state/archive",
            "state/nerve_bridge",
            "state/service_logs",
            "outcome/manual",
            "outcome/scheduled",
            "openclaw/runs",
        ]:
            _rm(self.home / rel)

        # Session logs under openclaw agents.
        agents_dir = self.openclaw_home / "agents"
        if agents_dir.exists():
            for sess_dir in agents_dir.glob("*/sessions"):
                if not sess_dir.is_dir():
                    continue
                _rm(sess_dir)
                sess_dir.mkdir(parents=True, exist_ok=True)
                cleaned["truncated"].append(str(sess_dir))

        # Always reset small state files.
        for rel in ("state/skill_evolution_proposals.json", "state/skill_evolution_queue.json"):
            _rm(self.home / rel)
        for p in (self.home / "state").glob("skill_evolution_*.json"):
            _rm(p)
        _rm(self.home / "state" / "tasks.json")
        _rm(self.home / "state" / "schedule_history.json")
        _rm(self.home / "state" / "gate.json")
        _rm(self.home / "outcome" / "index.json")

        if mode == "strict":
            # Drop runtime sqlite files (including temporal_dev.db).
            for db in (self.home / "state").glob("*.db"):
                db.unlink(missing_ok=True)
                cleaned["removed"].append(str(db))
            _rm(self.home / "state" / "reset_challenge.json")
            _rm(self.home / "state" / "reset_last_report.json")

        # Recreate required empty dirs for deterministic baseline.
        for rel in [
            "state",
            "state/runs",
            "state/runs_shadow",
            "state/telemetry",
            "state/traces",
            "state/tmp",
            "state/campaigns",
            "state/feedback_surveys",
            "state/snapshots",
            "state/nerve_bridge/cursors",
            "state/service_logs",
            "outcome/manual",
            "outcome/scheduled",
            "openclaw/runs",
        ]:
            (self.home / rel).mkdir(parents=True, exist_ok=True)

        # Force empty files that are frequently consumed.
        _reset_array_file(self.home / "state" / "tasks.json")
        _reset_array_file(self.home / "state" / "schedule_history.json")
        _reset_array_file(self.home / "state" / "skill_evolution_proposals.json")
        _reset_array_file(self.home / "state" / "skill_evolution_queue.json")
        _reset_array_file(self.home / "outcome" / "index.json")
        _reset_gate(self.home / "state" / "gate.json")
        self._clean_managed_outcome_root(cleaned)

        return cleaned

    def _clean_managed_outcome_root(self, cleaned: dict[str, Any]) -> None:
        """Reset managed drive outcome tree with hard scope guard.

        Only clears:
        - <daemon_root>/outcome/manual
        - <daemon_root>/outcome/scheduled
        - <daemon_root>/outcome/index.json
        """
        cleaned.setdefault("external", [])
        try:
            status = self._drive_registry.integration_status()
            if not status.get("ok"):
                cleaned["external"].append(
                    {
                        "target": "managed_outcome_root",
                        "action": "skip",
                        "reason": str(status.get("error") or "drive_unavailable"),
                    }
                )
                return

            daemon_root = Path(str(status.get("daemon_root") or "")).expanduser().resolve()
            outcome_root = Path(str(status.get("outcome_root") or "")).expanduser().resolve()
            outcome_root.relative_to(daemon_root)
            if outcome_root.name != "outcome":
                raise ValueError("managed_outcome_root_name_invalid")

            removed: list[str] = []
            for child in ("manual", "scheduled"):
                p = outcome_root / child
                if p.exists():
                    shutil.rmtree(p, ignore_errors=True)
                    removed.append(str(p))
                p.mkdir(parents=True, exist_ok=True)
            idx = outcome_root / "index.json"
            idx.parent.mkdir(parents=True, exist_ok=True)
            idx.write_text("[]", encoding="utf-8")
            removed.append(str(idx))
            cleaned["external"].append(
                {
                    "target": str(outcome_root),
                    "action": "reset",
                    "removed": removed,
                }
            )
        except Exception as exc:
            cleaned["external"].append(
                {
                    "target": "managed_outcome_root",
                    "action": "error",
                    "error": str(exc),
                }
            )

    def _read_challenge(self) -> dict[str, Any] | None:
        if self._challenge_cache:
            return self._challenge_cache
        if not self.challenge_path.exists():
            return None
        try:
            data = json.loads(self.challenge_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._challenge_cache = data
                return data
        except Exception:
            return None
        return None


__all__ = ["SystemResetManager", "_is_local_host"]
