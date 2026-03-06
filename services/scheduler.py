"""Scheduler — Spine Routine trigger management (cron + nerve + adaptive)."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from spine.contracts import ContractError, check_contract
from services.state_store import StateStore

if TYPE_CHECKING:
    from fabric.compass import CompassFabric
    from services.dispatch import Dispatch
    from spine.nerve import Nerve
    from spine.registry import SpineRegistry
    from spine.routines import SpineRoutines

logger = logging.getLogger(__name__)


class Scheduler:
    """Cron-based scheduler with nerve-triggered execution and contract enforcement."""

    def __init__(
        self,
        registry: "SpineRegistry",
        routines: "SpineRoutines",
        compass: "CompassFabric",
        nerve: "Nerve",
        state_dir: Path,
        dispatch: "Dispatch | None" = None,
    ) -> None:
        self._registry = registry
        self._routines = routines
        self._compass = compass
        self._nerve = nerve
        self._state = state_dir
        self._dispatch = dispatch
        self._store = StateStore(state_dir)
        self._last_run: dict[str, float] = {}
        self._next_run: dict[str, float] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._handlers_registered = False
        self._overrides_path = self._state / "schedules.json"
        self._overrides = self._load_overrides()
        self._history = self._load_history()
        self._circuits_lock = threading.Lock()
        self._migrate_circuits_data()

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._register_nerve_handlers()
        self._recompute_all_next_runs()
        self._running = True
        self._task = asyncio.create_task(self._loop_main())
        logger.info("Scheduler started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler stopped")

    async def trigger(self, routine_name: str) -> dict:
        """Manually trigger a Spine Routine by name."""
        return await asyncio.to_thread(self._run_routine, routine_name, None, "manual")

    def update_schedule(self, routine_name: str, schedule: str | None = None, enabled: bool | None = None) -> dict:
        full_name = routine_name if routine_name.startswith("spine.") else f"spine.{routine_name}"
        if not self._registry.get(full_name):
            return {"ok": False, "error": f"Unknown routine: {full_name}"}

        override = dict(self._overrides.get(full_name, {}))
        if schedule is not None:
            if schedule and not self._is_supported_schedule(schedule):
                return {"ok": False, "error": f"Unsupported schedule: {schedule}"}
            override["schedule"] = schedule
        if enabled is not None:
            override["enabled"] = bool(enabled)
        self._overrides[full_name] = override
        self._save_overrides()
        self._recompute_next_run(full_name)
        return {"ok": True, "routine": full_name, "override": override}

    def _run_routine(self, routine_name: str, payload: dict | None = None, trigger: str = "manual") -> dict:
        rdef = self._registry.get(routine_name)
        if not rdef:
            return {"ok": False, "error": f"Unknown routine: {routine_name}"}

        routine_method_name = routine_name.replace("spine.", "")
        routine_method = getattr(self._routines, routine_method_name, None)
        if not callable(routine_method):
            return {"ok": False, "error": f"Routine function not found: {routine_method_name}"}

        try:
            context = self._contract_context()
            for resource in rdef.reads:
                check_contract(routine_name, "pre", resource, context)
            result = self._invoke_method(routine_method_name, routine_method, payload)
            for resource in rdef.writes:
                check_contract(routine_name, "post", resource, context)

            now = time.time()
            self._last_run[routine_name] = now
            self._recompute_next_run(routine_name)
            self._append_history(routine_name, trigger, "ok", result)
            logger.info("Routine %s completed trigger=%s result=%s", routine_name, trigger, result)
            return {"ok": True, "routine": routine_name, "trigger": trigger, "result": result}
        except ContractError as exc:
            self._append_history(routine_name, trigger, "contract_failed", {"error": str(exc)})
            logger.error("Routine %s contract failed trigger=%s: %s", routine_name, trigger, exc)
            return {"ok": False, "routine": routine_name, "trigger": trigger, "error": str(exc), "error_code": "contract_failed"}
        except Exception as exc:
            self._append_history(routine_name, trigger, "error", {"error": str(exc)[:400]})
            logger.error("Routine %s failed trigger=%s: %s", routine_name, trigger, exc, exc_info=True)
            return {"ok": False, "routine": routine_name, "trigger": trigger, "error": str(exc)[:400]}

    def _invoke_method(self, routine_method_name: str, routine_method: Any, payload: dict | None) -> dict:
        if routine_method_name == "record":
            payload = payload or {}
            if payload.get("_bridge_event") == "delivery_completed":
                return {"skipped": True, "reason": "record_on_run_completed_only"}
            run_id = str(payload.get("run_id") or "")
            plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
            step_results = payload.get("step_results") if isinstance(payload.get("step_results"), list) else []
            outcome = payload.get("outcome") if isinstance(payload.get("outcome"), dict) else {}
            if not run_id or not plan:
                return {
                    "skipped": True,
                    "reason": "missing_run_context",
                    "run_id": run_id,
                }
            return routine_method(run_id=run_id, plan=plan, step_results=step_results, outcome=outcome)
        return routine_method()

    async def _loop_main(self) -> None:
        """Main scheduling loop."""
        while self._running:
            now = time.time()
            for rdef in self._registry.all():
                schedule = self._effective_schedule(rdef.name, rdef.schedule)
                if not self._is_enabled(rdef.name) or not schedule:
                    continue
                if schedule.startswith("adaptive:"):
                    continue
                next_run = self._next_run.get(rdef.name)
                if next_run is None:
                    self._recompute_next_run(rdef.name)
                    next_run = self._next_run.get(rdef.name)
                if next_run is not None and now >= next_run:
                    logger.info("Scheduler: triggering %s (cron due)", rdef.name)
                    await asyncio.to_thread(self._run_routine, rdef.name, None, "cron")
            await self._check_adaptive_routines()
            await asyncio.to_thread(self._tick_user_circuits)
            await asyncio.to_thread(self._tick_eval_windows)
            await asyncio.sleep(30)

    async def _check_adaptive_routines(self) -> None:
        """Check adaptive routines using Compass rhythm + routine offset semantics."""
        now = time.time()
        gate_status = self._gate_status()
        for rdef in self._registry.all():
            routine_name = rdef.name
            schedule = self._effective_schedule(routine_name, rdef.schedule)
            if not self._is_enabled(routine_name) or not schedule or not schedule.startswith("adaptive:"):
                continue
            if gate_status != "GREEN":
                # Gate closed: pause adaptive routines until recovery.
                self._next_run[routine_name] = None
                continue
            if self._next_run.get(routine_name) is None:
                # Gate recovered: reset baseline interval from "now".
                self._last_run[routine_name] = now
            interval = self._adaptive_interval(routine_name, schedule)
            last = self._last_run.get(routine_name, 0)
            elapsed = now - last
            if elapsed >= interval:
                await asyncio.to_thread(self._run_routine, routine_name, None, "adaptive")
                now = time.time()
            self._next_run[routine_name] = max(last, now) + interval

    def _register_nerve_handlers(self) -> None:
        if self._handlers_registered:
            return
        for rdef in self._registry.all():
            for event in rdef.nerve_triggers:
                self._nerve.on(
                    event,
                    lambda payload, routine_name=rdef.name, ev=event: self._run_routine(
                        routine_name, payload if isinstance(payload, dict) else {}, f"nerve:{ev}"
                    ),
                )
        self._nerve.on("run_replay", self._handle_run_replay)
        self._handlers_registered = True

    def _handle_run_replay(self, payload: dict) -> None:
        if not self._dispatch:
            logger.warning("Received run_replay but dispatch is not configured")
            return
        run_id = str(payload.get("run_id") or "")
        plan = payload.get("plan")
        if not run_id or not isinstance(plan, dict):
            logger.warning("Invalid run_replay payload: %s", payload)
            return

        def _runner() -> None:
            try:
                result = asyncio.run(self._dispatch.replay(run_id, plan))
                logger.info("run_replay submitted run_id=%s result=%s", run_id, result)
            except Exception as exc:
                logger.error("run_replay failed for run_id=%s: %s", run_id, exc, exc_info=True)

        threading.Thread(target=_runner, daemon=True).start()

    def _contract_context(self) -> dict[str, Any]:
        return {
            "daemon_home": self._state.parent,
            "state_dir": self._state,
            "fabric": {
                "memory": getattr(self._routines, "memory", None),
                "playbook": getattr(self._routines, "playbook", None),
                "compass": getattr(self._routines, "compass", None),
            },
        }

    def _load_overrides(self) -> dict[str, dict]:
        if not self._overrides_path.exists():
            return {}
        try:
            data = json.loads(self._overrides_path.read_text())
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Failed to load schedule overrides: %s", exc)
            return {}

    def _save_overrides(self) -> None:
        self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
        self._overrides_path.write_text(json.dumps(self._overrides, ensure_ascii=False, indent=2))

    def _load_history(self) -> list[dict]:
        return self._store.load_schedule_history()

    def _save_history(self) -> None:
        self._store.save_schedule_history(self._history, max_items=2000)

    def _append_history(self, routine_name: str, trigger: str, status: str, detail: dict | None = None) -> None:
        self._history.append(
            {
                "routine": routine_name,
                "trigger": trigger,
                "status": status,
                "detail": detail or {},
                "run_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        if len(self._history) > 2000:
            self._history = self._history[-2000:]
        self._save_history()

    def _effective_schedule(self, routine_name: str, default: str | None) -> str | None:
        override = self._overrides.get(routine_name, {})
        if "schedule" in override:
            return override.get("schedule")
        return default

    def _is_enabled(self, routine_name: str) -> bool:
        override = self._overrides.get(routine_name, {})
        if "enabled" in override:
            return bool(override["enabled"])
        return True

    def _recompute_all_next_runs(self) -> None:
        for rdef in self._registry.all():
            self._recompute_next_run(rdef.name)

    def _recompute_next_run(self, routine_name: str) -> None:
        rdef = self._registry.get(routine_name)
        if not rdef:
            return
        if not self._is_enabled(routine_name):
            self._next_run[routine_name] = None
            return

        schedule = self._effective_schedule(routine_name, rdef.schedule)
        if not schedule:
            self._next_run[routine_name] = None
            return
        if schedule.startswith("adaptive:"):
            interval = self._adaptive_interval(routine_name, schedule)
            base = self._last_run.get(routine_name, time.time())
            self._next_run[routine_name] = base + interval
            return

        next_dt = self._next_cron_occurrence(schedule, datetime.now(timezone.utc))
        self._next_run[routine_name] = next_dt.timestamp() if next_dt else None

    @staticmethod
    def _parse_duration(s: str) -> int | None:
        s = s.strip().lower()
        total = 0
        import re
        for match in re.finditer(r"(\d+)([hm])", s):
            val, unit = int(match.group(1)), match.group(2)
            total += val * 3600 if unit == "h" else val * 60
        return total if total else None

    @staticmethod
    def _parse_cron_simple(schedule: str) -> int | None:
        """Compatibility helper for simple cron cadence estimation."""
        parts = schedule.split()
        if len(parts) != 5:
            return None
        minute, hour, dom, month, dow = parts
        if minute.startswith("*/") and hour == "*" and dom == "*" and month == "*" and dow == "*":
            try:
                step = int(minute[2:])
                if step > 0:
                    return step * 60
            except Exception:
                return None
        if minute.isdigit() and hour.isdigit() and dom == "*" and month == "*" and dow == "*":
            return 24 * 3600
        return None

    @classmethod
    def _parse_adaptive_schedule(cls, schedule: str) -> tuple[int | None, int | None, int | None]:
        # Format: adaptive:<base>[:<min>-<max>]
        # Example: adaptive:4h:2h-12h / adaptive:4h30m:2h30m-12h30m
        parts = schedule.split(":")
        if not parts or parts[0] != "adaptive":
            return None, None, None
        base_s = cls._parse_duration(parts[1]) if len(parts) > 1 else None
        min_s = None
        max_s = None
        if len(parts) > 2 and "-" in parts[2]:
            left, right = parts[2].split("-", 1)
            min_s = cls._parse_duration(left)
            max_s = cls._parse_duration(right)
        return base_s, min_s, max_s

    def _adaptive_interval(self, routine_name: str, schedule: str) -> int:
        """Resolve adaptive interval in seconds.

        `learning_rhythm` is the witness baseline. Other adaptive routines inherit
        the same rhythm while keeping their registry-defined offset vs witness.
        """
        del routine_name  # reserved for future per-routine heuristics
        rhythm_raw = self._compass.get_pref("learning_rhythm", "4h")
        rhythm_s = self._parse_duration(rhythm_raw) or 4 * 3600
        base_s, min_s, max_s = self._parse_adaptive_schedule(schedule)

        witness_base_s = 4 * 3600
        witness_def = self._registry.get("spine.witness")
        if witness_def and witness_def.schedule and witness_def.schedule.startswith("adaptive:"):
            w_base, _, _ = self._parse_adaptive_schedule(witness_def.schedule)
            if w_base:
                witness_base_s = w_base

        if base_s:
            interval = rhythm_s + (base_s - witness_base_s)
        else:
            interval = rhythm_s
        interval = max(60, interval)

        # Queue-depth adaptive tuning: idle -> shorter interval, busy -> longer interval.
        running_count = self._running_runs_count()
        if running_count <= 0:
            interval = int(interval * 0.6)
        elif running_count > 3:
            interval = int(interval * 1.5)

        if min_s:
            interval = max(interval, min_s)
        if max_s:
            interval = min(interval, max_s)
        return interval

    def _gate_status(self) -> str:
        data = self._store.load_gate()
        return str(data.get("status") or "GREEN").upper()

    def _running_runs_count(self) -> int:
        rows = self._store.load_runs()
        return sum(
            1
            for row in rows
            if isinstance(row, dict)
            and str(row.get("run_status") or "") in {"running", "running_shadow"}
        )

    @staticmethod
    def _is_supported_schedule(schedule: str) -> bool:
        if schedule.startswith("adaptive:"):
            return True
        parts = schedule.split()
        if len(parts) != 5:
            return False
        try:
            Scheduler._parse_cron_field(parts[0], 0, 59)
            Scheduler._parse_cron_field(parts[1], 0, 23)
            Scheduler._parse_cron_field(parts[2], 1, 31)
            Scheduler._parse_cron_field(parts[3], 1, 12)
            Scheduler._parse_cron_field(parts[4], 0, 7, is_dow=True)
        except ValueError:
            return False
        return True

    @staticmethod
    def _parse_cron_field(field: str, minimum: int, maximum: int, is_dow: bool = False) -> set[int]:
        values: set[int] = set()
        for part in field.split(","):
            part = part.strip()
            if not part:
                raise ValueError("empty cron field part")
            if part == "*":
                values.update(range(minimum, maximum + 1))
                continue
            if part.startswith("*/"):
                step = int(part[2:])
                if step <= 0:
                    raise ValueError("invalid step")
                values.update(range(minimum, maximum + 1, step))
                continue
            if "-" in part:
                left, right = part.split("-", 1)
                start = int(left)
                end = int(right)
                if start > end:
                    raise ValueError("invalid range")
                values.update(range(start, end + 1))
                continue
            values.add(int(part))

        normalized: set[int] = set()
        for val in values:
            if is_dow and val == 7:
                val = 0
            if val < minimum or val > maximum:
                raise ValueError("cron value out of range")
            normalized.add(val)
        return normalized

    @staticmethod
    def _next_cron_occurrence(schedule: str, now_utc: datetime) -> datetime | None:
        parts = schedule.split()
        if len(parts) != 5:
            return None

        minutes = Scheduler._parse_cron_field(parts[0], 0, 59)
        hours = Scheduler._parse_cron_field(parts[1], 0, 23)
        dom = Scheduler._parse_cron_field(parts[2], 1, 31)
        months = Scheduler._parse_cron_field(parts[3], 1, 12)
        dows = Scheduler._parse_cron_field(parts[4], 0, 7, is_dow=True)
        dom_any = parts[2].strip() == "*"
        dow_any = parts[4].strip() == "*"

        cursor = now_utc.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(60 * 24 * 14):
            cron_dow = (cursor.weekday() + 1) % 7  # Mon=1 ... Sun=0
            if dom_any and dow_any:
                day_match = True
            elif dom_any:
                day_match = cron_dow in dows
            elif dow_any:
                day_match = cursor.day in dom
            else:
                # Vixie cron semantics: when both fields are restricted, either may match.
                day_match = cursor.day in dom or cron_dow in dows
            if (
                cursor.minute in minutes
                and cursor.hour in hours
                and cursor.month in months
                and day_match
            ):
                return cursor
            cursor += timedelta(minutes=1)
        return None

    def status(self) -> list[dict]:
        rows = []
        for rdef in self._registry.all():
            name = rdef.name
            schedule = self._effective_schedule(name, rdef.schedule)
            last = self._last_run.get(name)
            next_run = self._next_run.get(name)
            rows.append(
                {
                    "routine": name,
                    "mode": rdef.mode,
                    "schedule": schedule,
                    "enabled": self._is_enabled(name),
                    "last_run_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last)) if last else None,
                    "next_run_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(next_run)) if next_run else None,
                    "running": False,
                }
            )
        return rows

    def history(self, routine: str | None = None, limit: int = 100) -> list[dict]:
        rows = self._history
        if routine:
            full = routine if routine.startswith("spine.") else f"spine.{routine}"
            rows = [r for r in rows if str(r.get("routine") or "") == full]
        return list(reversed(rows))[: max(1, min(limit, 500))]

    # ── Recurring User Circuits ──────────────────────────────────────────────

    @property
    def _circuits_path(self) -> Path:
        return self._state / "circuits.json"

    @property
    def _legacy_circuits_path(self) -> Path:
        return self._state / "recurring_circuits.json"

    @staticmethod
    def _utc_now_iso() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    @staticmethod
    def _parse_utc_iso(value: str) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None

    def _tick_eval_windows(self) -> None:
        runs = self._store.load_runs()
        now = datetime.now(timezone.utc)
        changed = False
        expired: list[dict] = []
        for row in runs:
            status = str(row.get("run_status") or "").strip().lower()
            if status not in {"awaiting_eval", "pending_review"}:
                continue
            deadline = self._parse_utc_iso(str(row.get("eval_deadline_utc") or ""))
            if deadline is None:
                continue
            if deadline > now:
                continue
            row["run_status"] = "completed"
            row["phase"] = "history"
            row["updated_utc"] = self._utc_now_iso()
            row["eval_expired_utc"] = row["updated_utc"]
            row.pop("eval_deadline_utc", None)
            expired.append(dict(row))
            changed = True
        if changed:
            self._store.save_runs(runs)
        for row in expired:
            try:
                self._nerve.emit(
                    "run_eval_expired",
                    {
                        "run_id": str(row.get("run_id") or ""),
                        "work_scale": str(row.get("work_scale") or ""),
                        "campaign_id": str(row.get("campaign_id") or ""),
                    },
                )
            except Exception:
                continue

    @staticmethod
    def _normalize_tz(tz: str | None) -> str | None:
        value = str(tz or "UTC").strip() or "UTC"
        try:
            ZoneInfo(value)
            return value
        except Exception:
            return None

    def _load_circuits_unlocked(self) -> list[dict]:
        if not self._circuits_path.exists():
            return []
        try:
            data = json.loads(self._circuits_path.read_text())
            if not isinstance(data, list):
                return []
            return [self._normalize_circuit_row(row) for row in data if isinstance(row, dict)]
        except Exception as exc:
            logger.warning("Failed to load circuits.json: %s", exc)
            return []

    def _load_circuits(self) -> list[dict]:
        with self._circuits_lock:
            return self._load_circuits_unlocked()

    def _save_circuits_unlocked(self, circuits: list[dict]) -> None:
        self._circuits_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._circuits_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(circuits, ensure_ascii=False, indent=2))
        tmp.replace(self._circuits_path)

    def _save_circuits(self, circuits: list[dict]) -> None:
        with self._circuits_lock:
            self._save_circuits_unlocked(circuits)

    def _normalize_circuit_row(self, row: dict) -> dict:
        trigger = row.get("trigger") if isinstance(row.get("trigger"), dict) else {}
        circuit_id = str(row.get("circuit_id") or "").strip()
        if not circuit_id:
            circuit_id = f"circuit_{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
        name = str(row.get("name") or row.get("run_title") or row.get("title") or "").strip()
        run_type = str(row.get("run_type") or "research_report").strip()
        cron = str(row.get("cron") or trigger.get("cron") or "").strip()
        tz = self._normalize_tz(str(row.get("tz") or trigger.get("tz") or "UTC")) or "UTC"
        status = str(row.get("status") or "").strip().lower()
        enabled = bool(row.get("enabled", True))
        if status not in {"active", "paused", "cancelled"}:
            status = "active" if enabled else "paused"
        out = {
            "circuit_id": circuit_id,
            "name": name or circuit_id,
            "run_title": name or circuit_id,
            "prompt": str(row.get("prompt") or row.get("message") or "").strip(),
            "run_type": run_type or "research_report",
            "cron": cron,
            "tz": tz,
            "enabled": enabled,
            "status": status,
            "created_utc": str(row.get("created_utc") or self._utc_now_iso()),
            "last_triggered_utc": str(row.get("last_triggered_utc") or ""),
            "last_run_id": str(row.get("last_run_id") or ""),
            "run_count": int(row.get("run_count") or 0),
            "consecutive_failures": int(row.get("consecutive_failures") or 0),
            "last_error": str(row.get("last_error") or ""),
            "last_error_utc": str(row.get("last_error_utc") or ""),
            "next_retry_utc": str(row.get("next_retry_utc") or ""),
        }
        return out

    def _migrate_circuits_data(self) -> None:
        with self._circuits_lock:
            source = self._circuits_path
            if not source.exists() and self._legacy_circuits_path.exists():
                source = self._legacy_circuits_path
            if not source.exists():
                return
            try:
                raw = json.loads(source.read_text(encoding="utf-8"))
            except Exception:
                return
            if not isinstance(raw, list):
                return
            migrated = [self._normalize_circuit_row(row) for row in raw if isinstance(row, dict)]
            self._save_circuits_unlocked(migrated)
            if source == self._legacy_circuits_path and self._legacy_circuits_path.exists():
                try:
                    self._legacy_circuits_path.unlink()
                except Exception:
                    pass

    def _patch_circuit_runtime(self, circuit_id: str, mutator: Any) -> dict | None:
        with self._circuits_lock:
            circuits = self._load_circuits_unlocked()
            for circuit in circuits:
                if str(circuit.get("circuit_id") or "") != circuit_id:
                    continue
                mutator(circuit)
                self._save_circuits_unlocked(circuits)
                return dict(circuit)
        return None

    def _mark_circuit_trigger_success(self, circuit_id: str, run_id: str) -> dict | None:
        now_iso = self._utc_now_iso()

        def _mutate(circuit: dict) -> None:
            circuit["last_triggered_utc"] = now_iso
            circuit["last_run_id"] = run_id
            circuit["run_count"] = int(circuit.get("run_count") or 0) + 1
            circuit["consecutive_failures"] = 0
            circuit["last_error"] = ""
            circuit["last_error_utc"] = ""
            circuit["next_retry_utc"] = ""

        return self._patch_circuit_runtime(circuit_id, _mutate)

    def _mark_circuit_trigger_failure(self, circuit_id: str, error: str) -> dict | None:
        now = datetime.now(timezone.utc)
        now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        def _mutate(circuit: dict) -> None:
            failures = int(circuit.get("consecutive_failures") or 0) + 1
            # Exponential backoff (60s -> 120s -> ... -> 30m max).
            backoff_seconds = min(1800, 60 * (2 ** min(failures - 1, 5)))
            circuit["consecutive_failures"] = failures
            circuit["last_error"] = str(error or "")[:200]
            circuit["last_error_utc"] = now_iso
            circuit["next_retry_utc"] = (now + timedelta(seconds=backoff_seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")

        return self._patch_circuit_runtime(circuit_id, _mutate)

    def list_circuits(self) -> list[dict]:
        return self._load_circuits()

    def create_circuit(self, name: str, prompt: str, run_type: str, cron: str, tz: str = "UTC") -> dict:
        if not self._is_supported_schedule(cron):
            return {"ok": False, "error": f"Invalid cron expression: {cron}"}
        tz_norm = self._normalize_tz(tz)
        if not tz_norm:
            return {"ok": False, "error": f"Invalid timezone: {tz}"}

        with self._circuits_lock:
            circuits = self._load_circuits_unlocked()
            now_iso = self._utc_now_iso()
            circuit_id = f"circuit_{time.strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"
            circuit: dict = {
                "circuit_id": circuit_id,
                "name": name,
                "run_title": name,
                "prompt": prompt,
                "run_type": run_type,
                "cron": cron,
                "tz": tz_norm,
                "enabled": True,
                "status": "active",
                "created_utc": now_iso,
                # Prevent immediate trigger on create; first run is next cron slot.
                "last_triggered_utc": now_iso,
                "last_run_id": "",
                "run_count": 0,
                "consecutive_failures": 0,
                "last_error": "",
                "last_error_utc": "",
                "next_retry_utc": "",
            }
            circuits.append(circuit)
            self._save_circuits_unlocked(circuits)
        return {"ok": True, "circuit": circuit}

    def update_circuit(self, circuit_id: str, patch: dict) -> dict:
        with self._circuits_lock:
            circuits = self._load_circuits_unlocked()
            for circuit in circuits:
                if circuit.get("circuit_id") == circuit_id:
                    allowed = {"name", "prompt", "run_type", "cron", "tz", "enabled"}
                    for k, v in patch.items():
                        if k not in allowed:
                            continue
                        if k == "cron" and not self._is_supported_schedule(str(v)):
                            return {"ok": False, "error": f"Invalid cron expression: {v}"}
                        if k == "tz":
                            tz_norm = self._normalize_tz(str(v))
                            if not tz_norm:
                                return {"ok": False, "error": f"Invalid timezone: {v}"}
                            circuit[k] = tz_norm
                            continue
                        if k == "enabled":
                            enabled = bool(v)
                            circuit["enabled"] = enabled
                            if str(circuit.get("status") or "") != "cancelled":
                                circuit["status"] = "active" if enabled else "paused"
                            continue
                        circuit[k] = v
                        if k == "name":
                            circuit["run_title"] = str(v)
                    self._save_circuits_unlocked(circuits)
                    return {"ok": True, "circuit": circuit}
        return {"ok": False, "error": f"Circuit not found: {circuit_id}"}

    def cancel_circuit(self, circuit_id: str) -> dict:
        with self._circuits_lock:
            circuits = self._load_circuits_unlocked()
            for circuit in circuits:
                if circuit.get("circuit_id") == circuit_id:
                    circuit["status"] = "cancelled"
                    circuit["enabled"] = False
                    self._save_circuits_unlocked(circuits)
                    return {"ok": True, "circuit_id": circuit_id}
        return {"ok": False, "error": f"Circuit not found: {circuit_id}"}

    def trigger_circuit(self, circuit_id: str) -> dict:
        with self._circuits_lock:
            circuits = self._load_circuits_unlocked()
            circuit = next((c for c in circuits if str(c.get("circuit_id") or "") == circuit_id), None)
        if circuit:
            result = self._submit_circuit_run(circuit)
            if result.get("ok"):
                self._mark_circuit_trigger_success(circuit_id, str(result.get("run_id") or ""))
            else:
                self._mark_circuit_trigger_failure(circuit_id, str(result.get("error") or "submit_failed"))
            return result
        return {"ok": False, "error": f"Circuit not found: {circuit_id}"}

    def _submit_circuit_run(self, circuit: dict) -> dict:
        if not self._dispatch:
            logger.warning("Circuit trigger skipped: dispatch not configured")
            return {"ok": False, "error": "dispatch_not_configured"}
        run_type = str(circuit.get("run_type") or "research_report")
        prompt = str(circuit.get("prompt") or "").strip()
        cluster_by_run_type = {
            "research_report": "clst_research_report",
            "knowledge_synthesis": "clst_knowledge_synthesis",
            "dev_project": "clst_dev_project",
            "personal_plan": "clst_personal_plan",
        }
        cluster_id = cluster_by_run_type.get(run_type, "clst_dev_project")
        plan = {
            "title": circuit["name"],
            "run_title": str(circuit.get("run_title") or circuit.get("name") or "Circuit Run"),
            "prompt": prompt,
            "run_type": run_type,
            "circuit_id": circuit["circuit_id"],
            "circuit_name": circuit["name"],
            "work_scale": "thread",
            "rework_budget": 0,
            "retry_max_attempts": 1,
            "default_step_timeout_s": 180,
            "steps": self._build_circuit_steps(run_type=run_type, prompt=prompt),
            "semantic_spec": {
                "cluster_id": cluster_id,
                "objective": str(circuit.get("name") or run_type),
                "artifact_types": ["report"],
                "constraints": [],
                "temporal_scope": "immediate",
                "risk_level": "low",
                "language": "zh",
                "semantic_confidence": "high",
            },
        }
        try:
            import asyncio as _asyncio
            loop = self._loop
            if loop and loop.is_running():
                future = _asyncio.run_coroutine_threadsafe(self._dispatch.submit(plan), loop)
                return future.result(timeout=30)
            return _asyncio.run(self._dispatch.submit(plan))
        except Exception as exc:
            logger.error("Circuit %s submit failed: %s", circuit.get("circuit_id"), exc, exc_info=True)
            return {"ok": False, "error": str(exc)[:200]}

    def _build_circuit_steps(self, *, run_type: str, prompt: str) -> list[dict]:
        # Circuit is a scheduler primitive: each trigger should produce one
        # deterministic runnable step instead of replaying complex method DAGs.
        base_prompt = prompt or f"请执行一次 {run_type} 类型的例行任务并给出结果。"
        return [
            {
                "id": "step1",
                "agent": "router",
                "instruction": f"{base_prompt}\n\n最后一行输出 [DONE]。",
                "timeout_s": 180,
            }
        ]

    def _tick_user_circuits(self) -> None:
        """Check and trigger due recurring user circuits."""
        circuits = self._load_circuits()
        now_utc = datetime.now(timezone.utc)
        for circuit in circuits:
            if circuit.get("status") != "active" or not circuit.get("enabled"):
                continue
            cron = str(circuit.get("cron") or "").strip()
            if not cron or not self._is_supported_schedule(cron):
                continue
            retry_dt = self._parse_utc_iso(str(circuit.get("next_retry_utc") or ""))
            if retry_dt and retry_dt > now_utc:
                continue

            tz_name = self._normalize_tz(str(circuit.get("tz") or "UTC")) or "UTC"
            last_dt = self._parse_utc_iso(str(circuit.get("last_triggered_utc") or "")) or datetime.fromtimestamp(0, tz=timezone.utc)
            # Find the most recent occurrence that should have already fired
            next_after_last = self._next_cron_occurrence_tz(cron, last_dt, tz_name)
            if next_after_last is None or next_after_last > now_utc:
                continue
            logger.info("Circuit %s (%s) is due, triggering", circuit.get("circuit_id"), circuit.get("name"))
            result = self._submit_circuit_run(circuit)
            if result.get("ok"):
                self._mark_circuit_trigger_success(str(circuit.get("circuit_id") or ""), str(result.get("run_id") or ""))
            else:
                logger.warning("Circuit %s trigger failed: %s", circuit.get("circuit_id"), result.get("error"))
                self._mark_circuit_trigger_failure(str(circuit.get("circuit_id") or ""), str(result.get("error") or "submit_failed"))

    @staticmethod
    def _next_cron_occurrence_tz(schedule: str, now_utc: datetime, tz_name: str) -> datetime | None:
        parts = schedule.split()
        if len(parts) != 5:
            return None

        minutes = Scheduler._parse_cron_field(parts[0], 0, 59)
        hours = Scheduler._parse_cron_field(parts[1], 0, 23)
        dom = Scheduler._parse_cron_field(parts[2], 1, 31)
        months = Scheduler._parse_cron_field(parts[3], 1, 12)
        dows = Scheduler._parse_cron_field(parts[4], 0, 7, is_dow=True)
        dom_any = parts[2].strip() == "*"
        dow_any = parts[4].strip() == "*"

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = timezone.utc

        cursor = now_utc.astimezone(tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(60 * 24 * 14):
            cron_dow = (cursor.weekday() + 1) % 7  # Mon=1 ... Sun=0
            if dom_any and dow_any:
                day_match = True
            elif dom_any:
                day_match = cron_dow in dows
            elif dow_any:
                day_match = cursor.day in dom
            else:
                day_match = cursor.day in dom or cron_dow in dows
            if (
                cursor.minute in minutes
                and cursor.hour in hours
                and cursor.month in months
                and day_match
            ):
                return cursor.astimezone(timezone.utc)
            cursor += timedelta(minutes=1)
        return None
