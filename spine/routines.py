"""Spine Routines — governance routines for the daemon system (V2 aligned)."""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from services.ledger import Ledger
from spine.routines_ops_learn import run_distill, run_focus, run_learn, run_witness
from spine.routines_ops_maintenance import run_curate, run_relay, run_tend
from spine.routines_ops_record import run_record

if TYPE_CHECKING:
    from psyche.instinct import InstinctPsyche
    from psyche.memory import MemoryPsyche
    from psyche.lore import LorePsyche
    from runtime.cortex import Cortex
    from spine.nerve import Nerve
    from spine.trail import Trail


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


logger = logging.getLogger(__name__)


class SpineRoutines:
    """Container for all Spine Routines. Each routine returns a result dict."""

    def __init__(
        self,
        memory: "MemoryPsyche",
        lore: "LorePsyche",
        instinct: "InstinctPsyche",
        cortex: "Cortex",
        nerve: "Nerve",
        trail: "Trail",
        daemon_home: Path,
        openclaw_home: Path | None = None,
    ) -> None:
        self.memory = memory
        self.lore = lore
        self.instinct = instinct
        self.cortex = cortex
        self.nerve = nerve
        self.trail = trail
        self.daemon_home = daemon_home
        self.openclaw_home = openclaw_home
        self.state_dir = daemon_home / "state"
        self._store = Ledger(self.state_dir)

    # ── 1. pulse ─────────────────────────────────────────────────────────────

    def pulse(self) -> dict:
        """Probe infrastructure health; write ward.json."""
        with self.trail.span("spine.pulse", trigger="cron") as ctx:
            services: dict[str, str] = {}
            degraded: list[str] = []
            reasons: list[str] = []

            gw_status = self._probe_gateway()
            services["gateway"] = gw_status
            if gw_status != "ok":
                degraded.append("gateway")
                reasons.append(f"gateway: {gw_status}")
            ctx.step("gateway_probe", gw_status)

            temporal_status = self._probe_temporal()
            services["temporal"] = temporal_status
            if temporal_status != "ok":
                degraded.append("temporal")
                reasons.append(f"temporal: {temporal_status}")
            ctx.step("temporal_probe", temporal_status)

            llm_status = "ok" if self.cortex.is_available() else "unavailable"
            services["llm"] = llm_status
            if llm_status != "ok":
                degraded.append("llm")
                reasons.append("no LLM providers configured")
            ctx.step("llm_probe", llm_status)

            disk_status = self._probe_disk()
            services["disk"] = disk_status
            if disk_status != "ok":
                degraded.append("disk")
                reasons.append(f"disk: {disk_status}")
            ctx.step("disk_probe", disk_status)

            if "gateway" in degraded or "temporal" in degraded:
                ward_status = "RED" if len(degraded) >= 2 else "YELLOW"
            elif "disk" in degraded and disk_status.startswith("critical"):
                ward_status = "RED"
            elif "llm" in degraded or "disk" in degraded:
                ward_status = "YELLOW"
            else:
                ward_status = "GREEN"

            prev_ward = self._read_ward().get("status", "GREEN")
            ward = {
                "status": ward_status,
                "services": services,
                "degraded_services": degraded,
                "reasons": reasons,
                "updated_utc": _utc(),
            }
            self._write_ward(ward)
            ctx.step("ward_written", ward_status)

            if prev_ward != ward_status:
                self.nerve.emit("ward_changed", {"prev": prev_ward, "current": ward_status})

            # Q2.11: detect routines with 3+ consecutive failures and trigger auto-diagnosis.
            failing_routines = self._detect_consecutive_failures(threshold=3)
            diagnosis_results: list[dict] = []
            for routine_name in failing_routines:
                diag = self._run_auto_diagnosis(routine_name)
                diagnosis_results.append(diag)
            ctx.step("auto_diagnosis", {"checked": len(failing_routines), "results": diagnosis_results})

            result = {"ward": ward_status, "services": services, "diagnosis": diagnosis_results}
            ctx.set_result(result)
        return result

    # ── 2. record ─────────────────────────────────────────────────────────────

    def record(self, deed_id: str, plan: dict, move_results: list[dict], offering: dict) -> dict:
        """Record completed deed as LoreRecord."""
        return run_record(self, deed_id, plan, move_results, offering)

    # ── 3. witness ────────────────────────────────────────────────────────────

    def witness(self) -> dict:
        """Analyze Lore trends; update Instinct preferences and system health."""
        return run_witness(self)

    # ── 4. learn ──────────────────────────────────────────────────────────────

    def learn(self, deed_id: str | None = None) -> dict:
        """Extract knowledge from retinue instance workspace to Memory."""
        return run_learn(self, deed_id=deed_id)

    # ── 5. distill ────────────────────────────────────────────────────────────

    def distill(self) -> dict:
        """Memory decay + capacity enforcement."""
        return run_distill(self)

    # ── 6. focus ──────────────────────────────────────────────────────────────

    def focus(self) -> dict:
        """Embedding index maintenance."""
        return run_focus(self)

    # ── 7. relay ──────────────────────────────────────────────────────────────

    def relay(self) -> dict:
        """Export Psyche snapshots to state/snapshots/ and retinue instances."""
        return run_relay(self)

    # ── 8. tend ───────────────────────────────────────────────────────────────

    def tend(self) -> dict:
        """Housekeeping: state/ git commit, log cleanup, ration reset."""
        return run_tend(self)

    # ── 9. curate ─────────────────────────────────────────────────────────────

    def curate(self) -> dict:
        """deed_root → vault archival; vault 90-day expiry."""
        return run_curate(self)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _probe_gateway(self) -> str:
        if not self.openclaw_home:
            return "not_configured"
        try:
            import httpx
            cfg = self._read_openclaw_config()
            if not cfg:
                return "config_missing"
            port = cfg.get("gateway", {}).get("port", 18789)
            token = cfg.get("gateway", {}).get("auth", {}).get("token", "")
            if not token:
                import os
                token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            resp = httpx.get(f"http://127.0.0.1:{port}/health", headers=headers, timeout=5)
            if resp.status_code < 300:
                return "ok"
            rpc = httpx.post(
                f"http://127.0.0.1:{port}/tools/invoke",
                json={"tool": "sessions_history", "args": {"sessionKey": "agent:probe:gateway", "limit": 1}},
                headers={**headers, "Content-Type": "application/json"},
                timeout=5,
            )
            if rpc.status_code < 300:
                return "ok"
            return f"http_{resp.status_code}|rpc_{rpc.status_code}"
        except Exception as e:
            return f"error: {str(e)[:80]}"

    def _probe_disk(self) -> str:
        try:
            import shutil
            usage = shutil.disk_usage(str(self.daemon_home))
            free_gb = usage.free / (1024 ** 3)
            pct_free = usage.free / usage.total * 100 if usage.total else 0
            if free_gb < 1.0 or pct_free < 5:
                return f"critical: {free_gb:.1f}GB free ({pct_free:.0f}%)"
            if free_gb < 5.0 or pct_free < 15:
                return f"low: {free_gb:.1f}GB free ({pct_free:.0f}%)"
            return "ok"
        except Exception as e:
            return f"error: {str(e)[:60]}"

    def _probe_temporal(self) -> str:
        try:
            import socket
            sock = socket.create_connection(("127.0.0.1", 7233), timeout=3)
            sock.close()
            return "ok"
        except Exception as e:
            return f"unreachable: {str(e)[:60]}"

    def _read_openclaw_config(self) -> dict | None:
        if not self.openclaw_home:
            return None
        cfg_path = self.openclaw_home / "openclaw.json"
        if not cfg_path.exists():
            return None
        try:
            return json.loads(cfg_path.read_text())
        except Exception as exc:
            logger.warning("Failed to parse OpenClaw config %s: %s", cfg_path, exc)
            return None

    def _read_ward(self) -> dict:
        return self._store.load_ward()

    def _write_ward(self, ward: dict) -> None:
        self._store.save_ward(ward)

    def _build_model_policy_snapshot(self) -> dict:
        policy_path = self.daemon_home / "config" / "model_policy.json"
        try:
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load model_policy.json: %s", exc)
            policy = {}
        policy["generated_utc"] = _utc()
        return policy

    def _build_model_registry_snapshot(self) -> dict:
        reg_path = self.daemon_home / "config" / "model_registry.json"
        try:
            registry = json.loads(reg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load model_registry.json: %s", exc)
            registry = {}
        if isinstance(registry, dict):
            registry["generated_utc"] = _utc()
        else:
            registry = {"generated_utc": _utc()}
        return registry

    def _maybe_reset_rations(self) -> None:
        rations = self.instinct.all_rations()
        now = _utc()
        for b in rations:
            reset_utc = b.get("reset_utc", "")
            if reset_utc and reset_utc <= now:
                self.instinct.reset_rations()
                break

    def _clean_old_traces(self, max_age_days: int = 7) -> int:
        traces_dir = self.state_dir / "traces"
        if not traces_dir.exists():
            return 0
        cutoff = time.time() - max_age_days * 86400
        cleaned = 0
        for f in traces_dir.glob("*.jsonl"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                cleaned += 1
        return cleaned

    # ── Auto-diagnosis (Q2.11) ──────────────────────────────────────────────

    _DIAG_COOLDOWN_FILE = "auto_diagnosis_cooldown.json"
    _DIAG_TIMEOUT_S = 600  # 10 minutes
    _DIAG_MAX_PER_DAY = 3

    def _detect_consecutive_failures(self, threshold: int = 3) -> list[str]:
        """Scan spine_log.jsonl for routines with N consecutive failures."""
        log_path = self.state_dir / "spine_log.jsonl"
        if not log_path.exists():
            return []
        # Build per-routine recent status sequences.
        sequences: dict[str, list[str]] = {}
        try:
            for line in log_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                name = str(entry.get("routine") or "")
                status = str(entry.get("status") or "")
                if name and status:
                    sequences.setdefault(name, []).append(status)
        except Exception:
            return []
        failing: list[str] = []
        for name, statuses in sequences.items():
            if name == "pulse":
                continue  # pulse diagnosing itself would loop
            tail = statuses[-threshold:] if len(statuses) >= threshold else []
            if len(tail) == threshold and all(s == "error" for s in tail):
                if not self._is_diag_on_cooldown(name):
                    failing.append(name)
        return failing

    def _is_diag_on_cooldown(self, routine_name: str) -> bool:
        """Check if a routine has been diagnosed too recently (24h window, max 3/day)."""
        cooldown_path = self.state_dir / self._DIAG_COOLDOWN_FILE
        if not cooldown_path.exists():
            return False
        try:
            data = json.loads(cooldown_path.read_text(encoding="utf-8"))
        except Exception:
            return False
        entries = data.get(routine_name, [])
        if not isinstance(entries, list):
            return False
        cutoff = time.time() - 86400
        recent = [ts for ts in entries if isinstance(ts, (int, float)) and ts > cutoff]
        return len(recent) >= self._DIAG_MAX_PER_DAY

    def _record_diag_attempt(self, routine_name: str) -> None:
        """Record a diagnosis attempt for cooldown tracking."""
        cooldown_path = self.state_dir / self._DIAG_COOLDOWN_FILE
        try:
            data = json.loads(cooldown_path.read_text(encoding="utf-8")) if cooldown_path.exists() else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        entries = data.get(routine_name, [])
        if not isinstance(entries, list):
            entries = []
        entries.append(time.time())
        # Keep only last 24h entries.
        cutoff = time.time() - 86400
        entries = [ts for ts in entries if isinstance(ts, (int, float)) and ts > cutoff]
        data[routine_name] = entries
        try:
            cooldown_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to write diagnosis cooldown: %s", exc)

    def _run_auto_diagnosis(self, routine_name: str) -> dict:
        """Q2.11: Auto-diagnosis for a routine with consecutive failures.

        1. Mark routine as repairing
        2. Notify via Nerve
        3. Invoke Claude Code CLI for diagnosis
        4. Re-run routine to verify
        5. Report outcome via Nerve
        """
        self._record_diag_attempt(routine_name)
        try:
            status_path = self.state_dir / "schedules.json"
            current = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
            if not isinstance(current, dict):
                current = {}
            override = current.get(f"spine.{routine_name}", {}) if isinstance(current.get(f"spine.{routine_name}"), dict) else {}
            override["enabled"] = False
            current[f"spine.{routine_name}"] = override
            status_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to pause routine %s before auto-diagnosis: %s", routine_name, exc)
        self.nerve.emit("auto_diagnosis_started", {"routine": routine_name, "timestamp_utc": _utc()})

        # Gather failure context from spine_log.
        failure_context = self._gather_failure_context(routine_name, count=3)

        # Invoke Claude Code CLI for diagnosis.
        prompt = (
            f"The daemon spine routine '{routine_name}' has failed 3 consecutive times. "
            f"Recent errors:\n{json.dumps(failure_context, ensure_ascii=False, indent=2)}\n\n"
            f"Daemon home: {self.daemon_home}\n"
            f"Diagnose the root cause and fix it. "
            f"Focus on the routine implementation in spine/routines*.py and related modules. "
            f"After fixing, explain what you changed."
        )
        try:
            diag_result = subprocess.run(
                ["claude", "--print", "-p", prompt],
                capture_output=True,
                text=True,
                timeout=self._DIAG_TIMEOUT_S,
                cwd=str(self.daemon_home),
            )
            diagnosis_output = (diag_result.stdout or "")[:2000]
            diag_ok = diag_result.returncode == 0
        except subprocess.TimeoutExpired:
            diagnosis_output = "diagnosis_timeout"
            diag_ok = False
        except FileNotFoundError:
            diagnosis_output = "claude_cli_not_found"
            diag_ok = False
        except Exception as exc:
            diagnosis_output = f"diagnosis_error: {str(exc)[:200]}"
            diag_ok = False

        # Verify fix by re-running the routine.
        verified = False
        if diag_ok:
            routine_method = getattr(self, routine_name, None)
            if callable(routine_method):
                try:
                    routine_method()
                    verified = True
                except Exception as exc:
                    logger.warning("Post-diagnosis verification failed for %s: %s", routine_name, exc)

        status = "repair_ok" if verified else "repair_failed"
        result = {
            "routine": routine_name,
            "status": status,
            "diagnosis_output": diagnosis_output[:500],
            "verified": verified,
            "timestamp_utc": _utc(),
        }
        try:
            status_path = self.state_dir / "schedules.json"
            current = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
            if not isinstance(current, dict):
                current = {}
            override = current.get(f"spine.{routine_name}", {}) if isinstance(current.get(f"spine.{routine_name}"), dict) else {}
            override["enabled"] = True
            current[f"spine.{routine_name}"] = override
            status_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to resume routine %s after auto-diagnosis: %s", routine_name, exc)
        self.nerve.emit("auto_diagnosis_completed", result)
        logger.info("Auto-diagnosis for %s: %s (verified=%s)", routine_name, status, verified)
        return result

    def _gather_failure_context(self, routine_name: str, count: int = 3) -> list[dict]:
        """Extract recent failure entries for a routine from spine_log.jsonl."""
        log_path = self.state_dir / "spine_log.jsonl"
        if not log_path.exists():
            return []
        failures: list[dict] = []
        try:
            for line in log_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(entry.get("routine") or "") == routine_name and str(entry.get("status") or "") == "error":
                    failures.append(entry)
        except Exception:
            return []
        return failures[-count:]

    # ── Spine execution logging ──────────────────────────────────────────────

    def log_execution(self, routine_name: str, status: str, result: Any, duration_s: float) -> None:
        """Append routine execution record to spine_log.jsonl and update spine_status.json."""
        log_path = self.state_dir / "spine_log.jsonl"
        entry = {
            "routine": routine_name,
            "status": status,
            "duration_s": round(duration_s, 2),
            "timestamp_utc": _utc(),
        }
        if status != "ok" and isinstance(result, dict):
            entry["error"] = str(result.get("error", ""))[:200]
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed to write spine_log.jsonl: %s", exc)
        self._update_spine_status(routine_name, status)

    def _update_spine_status(self, routine_name: str, status: str) -> None:
        """Update spine_status.json with latest routine results and overall health."""
        status_path = self.state_dir / "spine_status.json"
        try:
            current = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
        except Exception:
            current = {}
        if not isinstance(current, dict):
            current = {}
        routines_map = current.get("routines", {})
        if not isinstance(routines_map, dict):
            routines_map = {}
        routines_map[routine_name] = {"status": status, "updated_utc": _utc()}
        # Determine overall health from individual routine statuses.
        statuses = [v.get("status", "ok") for v in routines_map.values()]
        error_count = sum(1 for s in statuses if s == "error")
        if error_count == 0:
            overall = "healthy"
        elif "pulse" in routines_map and routines_map["pulse"].get("status") == "error":
            overall = "critical"
        else:
            overall = "degraded"
        current["overall"] = overall
        current["routines"] = routines_map
        current["updated_utc"] = _utc()
        try:
            status_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to write spine_status.json: %s", exc)
