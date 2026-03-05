"""Scheduler — Spine Routine trigger management (cron + nerve + adaptive)."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

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

        method_name = routine_name.replace("spine.", "")
        method = getattr(self._routines, method_name, None)
        if not callable(method):
            return {"ok": False, "error": f"Routine method not found: {method_name}"}

        try:
            context = self._contract_context()
            for resource in rdef.reads:
                check_contract(routine_name, "pre", resource, context)
            result = self._invoke_method(method_name, method, payload)
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

    def _invoke_method(self, method_name: str, method: Any, payload: dict | None) -> dict:
        if method_name == "record":
            payload = payload or {}
            if payload.get("_bridge_event") == "delivery_completed":
                return {"skipped": True, "reason": "record_on_task_completed_only"}
            task_id = str(payload.get("task_id") or "")
            plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
            step_results = payload.get("step_results") if isinstance(payload.get("step_results"), list) else []
            outcome = payload.get("outcome") if isinstance(payload.get("outcome"), dict) else {}
            if not task_id or not plan:
                return {
                    "skipped": True,
                    "reason": "missing_task_context",
                    "task_id": task_id,
                }
            return method(task_id=task_id, plan=plan, step_results=step_results, outcome=outcome)
        return method()

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
        self._nerve.on("task_replay", self._handle_task_replay)
        self._handlers_registered = True

    def _handle_task_replay(self, payload: dict) -> None:
        if not self._dispatch:
            logger.warning("Received task_replay but dispatch is not configured")
            return
        task_id = str(payload.get("task_id") or "")
        plan = payload.get("plan")
        if not task_id or not isinstance(plan, dict):
            logger.warning("Invalid task_replay payload: %s", payload)
            return

        def _runner() -> None:
            try:
                result = asyncio.run(self._dispatch.replay(task_id, plan))
                logger.info("task_replay submitted task_id=%s result=%s", task_id, result)
            except Exception as exc:
                logger.error("task_replay failed for task_id=%s: %s", task_id, exc, exc_info=True)

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
        running_count = self._running_tasks_count()
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

    def _running_tasks_count(self) -> int:
        rows = self._store.load_tasks()
        return sum(1 for row in rows if isinstance(row, dict) and str(row.get("status") or "") in {"running", "running_shadow"})

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
