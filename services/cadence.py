"""Cadence — Spine Routine trigger management (cron + nerve + adaptive)."""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from spine.pact import PactError, check_pact
from services.ledger import Ledger

if TYPE_CHECKING:
    from psyche.instinct import InstinctPsyche
    from services.will import Will
    from spine.nerve import Nerve
    from spine.canon import SpineCanon
    from spine.routines import SpineRoutines

logger = logging.getLogger(__name__)


class Cadence:
    """Cron-based cadence with nerve-triggered execution and pact enforcement."""

    def __init__(
        self,
        canon: "SpineCanon",
        routines: "SpineRoutines",
        instinct: "InstinctPsyche",
        nerve: "Nerve",
        state_dir: Path,
        will: "Will | None" = None,
    ) -> None:
        self._canon = canon
        self._routines = routines
        self._instinct = instinct
        self._nerve = nerve
        self._state = state_dir
        self._will = will
        self._ledger = Ledger(state_dir)
        self._last_run: dict[str, float] = {}
        self._next_run: dict[str, float] = {}
        self._running = False
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._handlers_registered = False
        self._last_cadence_tick_minute = ""
        self._overrides_path = self._state / "schedules.json"
        self._overrides = self._load_overrides()
        self._history = self._load_history()

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._register_nerve_handlers()
        self._recompute_all_next_runs()
        self._running = True
        self._task = asyncio.create_task(self._loop_main())
        logger.info("Cadence started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Cadence stopped")

    async def trigger(self, routine_name: str) -> dict:
        """Manually trigger a Spine Routine by name."""
        return await asyncio.to_thread(self._run_routine, routine_name, None, "manual")

    def update_schedule(self, routine_name: str, schedule: str | None = None, enabled: bool | None = None) -> dict:
        full_name = routine_name if routine_name.startswith("spine.") else f"spine.{routine_name}"
        if not self._canon.get(full_name):
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
        rdef = self._canon.get(routine_name)
        if not rdef:
            return {"ok": False, "error": f"Unknown routine: {routine_name}"}

        routine_method_name = routine_name.replace("spine.", "")
        routine_method = getattr(self._routines, routine_method_name, None)
        if not callable(routine_method):
            return {"ok": False, "error": f"Routine function not found: {routine_method_name}"}

        # Check upstream dependencies: skip if upstream routine last run failed.
        dep_ok, dep_reason = self._check_upstream_deps(routine_name)
        if not dep_ok:
            logger.info("Routine %s skipped: %s", routine_name, dep_reason)
            return {"ok": False, "routine": routine_name, "trigger": trigger, "skipped": True, "reason": dep_reason}

        degrade_mode = self._resolve_degraded_mode(rdef)
        if degrade_mode == "skip":
            reason = "degraded_mode_skip"
            self._append_history(routine_name, trigger, "ok", {"skipped": True, "reason": reason})
            self._routines.log_execution(routine_method_name, "ok", {"skipped": True, "reason": reason}, 0)
            return {"ok": True, "routine": routine_name, "trigger": trigger, "result": {"skipped": True, "reason": reason}}

        try:
            context = self._pact_context()
            for resource in rdef.reads:
                check_pact(routine_name, "pre", resource, context)
            start_ts = time.time()
            call_payload = dict(payload or {})
            if degrade_mode:
                call_payload["_degraded_mode"] = degrade_mode
            timeout_s = self._resolve_timeout_s(rdef)
            result = self._invoke_with_timeout(
                routine_method_name,
                routine_method,
                call_payload or None,
                timeout_s=timeout_s,
            )
            duration = time.time() - start_ts
            for resource in rdef.writes:
                check_pact(routine_name, "post", resource, context)

            now = time.time()
            self._last_run[routine_name] = now
            self._recompute_next_run(routine_name)
            self._append_history(routine_name, trigger, "ok", result)
            self._routines.log_execution(routine_method_name, "ok", result, duration)
            logger.info("Routine %s completed trigger=%s result=%s", routine_name, trigger, result)
            return {"ok": True, "routine": routine_name, "trigger": trigger, "result": result}
        except PactError as exc:
            self._append_history(routine_name, trigger, "pact_failed", {"error": str(exc)})
            self._routines.log_execution(routine_method_name, "error", {"error": str(exc)[:200]}, 0)
            logger.error("Routine %s pact failed trigger=%s: %s", routine_name, trigger, exc)
            return {"ok": False, "routine": routine_name, "trigger": trigger, "error": str(exc), "error_code": "pact_failed"}
        except Exception as exc:
            self._append_history(routine_name, trigger, "error", {"error": str(exc)[:400]})
            self._routines.log_execution(routine_method_name, "error", {"error": str(exc)[:200]}, 0)
            logger.error("Routine %s failed trigger=%s: %s", routine_name, trigger, exc, exc_info=True)
            return {"ok": False, "routine": routine_name, "trigger": trigger, "error": str(exc)[:400]}

    def _invoke_method(self, routine_method_name: str, routine_method: Any, payload: dict | None) -> dict:
        if routine_method_name == "record":
            payload = payload or {}
            if payload.get("_bridge_event") == "herald_completed":
                return {"skipped": True, "reason": "record_on_deed_completed_only"}
            deed_id = str(payload.get("deed_id") or "")
            plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
            move_results = payload.get("move_results") if isinstance(payload.get("move_results"), list) else []
            offering = payload.get("offering") if isinstance(payload.get("offering"), dict) else {}
            if not deed_id or not plan:
                return {
                    "skipped": True,
                    "reason": "missing_deed_context",
                    "deed_id": deed_id,
                }
            return routine_method(deed_id=deed_id, plan=plan, move_results=move_results, offering=offering)
        if routine_method_name == "learn":
            payload = payload or {}
            return routine_method(deed_id=str(payload.get("deed_id") or "") or None)
        return routine_method()

    def _invoke_with_timeout(
        self,
        routine_method_name: str,
        routine_method: Any,
        payload: dict | None,
        *,
        timeout_s: int,
    ) -> dict:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            fut = executor.submit(self._invoke_method, routine_method_name, routine_method, payload)
            try:
                return fut.result(timeout=max(1, int(timeout_s)))
            except concurrent.futures.TimeoutError as exc:
                raise TimeoutError(f"routine_timeout_after_{timeout_s}s") from exc

    async def _loop_main(self) -> None:
        """Main cadence loop."""
        while self._running:
            now = time.time()
            self._emit_cadence_tick_if_due()
            for rdef in self._canon.all():
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
                    logger.info("Cadence: triggering %s (cron due)", rdef.name)
                    await asyncio.to_thread(self._run_routine, rdef.name, None, "cron")
            await self._check_adaptive_routines()
            await asyncio.to_thread(self._tick_eval_windows)
            await asyncio.to_thread(self._retry_failed_notifications)
            await asyncio.sleep(30)

    async def _check_adaptive_routines(self) -> None:
        """Check adaptive routines using Instinct rhythm + routine offset semantics."""
        now = time.time()
        ward_status = self._ward_status()
        for rdef in self._canon.all():
            routine_name = rdef.name
            schedule = self._effective_schedule(routine_name, rdef.schedule)
            if not self._is_enabled(routine_name) or not schedule or not schedule.startswith("adaptive:"):
                continue
            if ward_status != "GREEN":
                # Ward closed: pause adaptive routines until recovery.
                self._next_run[routine_name] = None
                continue
            if self._next_run.get(routine_name) is None:
                # Ward recovered: reset baseline interval from "now".
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
        for rdef in self._canon.all():
            for event in rdef.nerve_triggers:
                self._nerve.on(
                    event,
                    lambda payload, routine_name=rdef.name, ev=event: self._run_routine(
                        routine_name, payload if isinstance(payload, dict) else {}, f"nerve:{ev}"
                    ),
                )
        self._handlers_registered = True

    def _pact_context(self) -> dict[str, Any]:
        return {
            "daemon_home": self._state.parent,
            "state_dir": self._state,
            "psyche": {
                "memory": getattr(self._routines, "memory", None),
                "lore": getattr(self._routines, "lore", None),
                "instinct": getattr(self._routines, "instinct", None),
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
        return self._ledger.load_schedule_history()

    def _save_history(self) -> None:
        self._ledger.save_schedule_history(self._history, max_items=2000)

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
        for rdef in self._canon.all():
            self._recompute_next_run(rdef.name)

    def _recompute_next_run(self, routine_name: str) -> None:
        rdef = self._canon.get(routine_name)
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
        the same rhythm while keeping their canon-defined offset vs witness.
        """
        del routine_name  # reserved for future per-routine heuristics
        rhythm_raw = self._instinct.get_pref("learning_rhythm", "4h")
        rhythm_s = self._parse_duration(rhythm_raw) or 4 * 3600
        base_s, min_s, max_s = self._parse_adaptive_schedule(schedule)

        witness_base_s = 4 * 3600
        witness_def = self._canon.get("spine.witness")
        if witness_def and witness_def.schedule and witness_def.schedule.startswith("adaptive:"):
            w_base, _, _ = self._parse_adaptive_schedule(witness_def.schedule)
            if w_base:
                witness_base_s = w_base

        if base_s:
            interval = rhythm_s + (base_s - witness_base_s)
        else:
            interval = rhythm_s
        interval = max(60, interval)

        # Queue depth.
        running_count = self._running_deeds_count()
        if running_count <= 0:
            interval = int(interval * 0.6)
        elif running_count > 3:
            interval = int(interval * 1.5)

        # User activity: active portal usage shortens adaptive cycles.
        activity_score = self._recent_portal_activity_score()
        if activity_score >= 10:
            interval = int(interval * 0.75)
        elif activity_score <= 1:
            interval = int(interval * 1.15)

        # Recent quality trend: low quality increases witness/focus frequency.
        avg_quality = self._recent_avg_quality()
        if avg_quality and avg_quality < 0.65:
            interval = int(interval * 0.8)
        elif avg_quality and avg_quality > 0.85:
            interval = int(interval * 1.05)

        # Error rate: more routine failures => shorten the loop.
        error_rate = self._recent_schedule_error_rate()
        if error_rate >= 0.3:
            interval = int(interval * 0.7)
        elif error_rate >= 0.15:
            interval = int(interval * 0.85)

        # Time-of-day awareness: nights are slower when there is no user activity.
        hour = datetime.now(timezone.utc).hour
        if hour in {0, 1, 2, 3, 4, 5} and activity_score <= 2:
            interval = int(interval * 1.2)

        if min_s:
            interval = max(interval, min_s)
        if max_s:
            interval = min(interval, max_s)
        return interval

    def _check_upstream_deps(self, routine_name: str) -> tuple[bool, str]:
        """Check if all depends_on routines succeeded recently."""
        rdef = self._canon.get(routine_name)
        if not rdef or not rdef.depends_on:
            return True, ""
        log_path = self._state / "spine_log.jsonl"
        if not log_path.exists():
            return True, ""
        # Build latest status per routine from spine_log.jsonl
        latest: dict[str, str] = {}
        try:
            for line in log_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    name = str(entry.get("routine") or "")
                    if name:
                        latest[name] = str(entry.get("status") or "")
                except json.JSONDecodeError:
                    continue
        except Exception:
            return True, ""
        for dep in rdef.depends_on:
            dep_short = dep.replace("spine.", "")
            status = latest.get(dep_short) or latest.get(dep, "")
            if status == "error":
                return False, f"upstream {dep} last run failed"
        return True, ""

    def _ward_status(self) -> str:
        data = self._ledger.load_ward()
        return str(data.get("status") or "GREEN").upper()

    def _running_deeds_count(self) -> int:
        rows = self._ledger.load_deeds()
        return sum(
            1
            for row in rows
            if isinstance(row, dict)
            and str(row.get("deed_status") or "") == "running"
        )

    @staticmethod
    def _is_supported_schedule(schedule: str) -> bool:
        if schedule.startswith("adaptive:"):
            return True
        parts = schedule.split()
        if len(parts) != 5:
            return False
        try:
            Cadence._parse_cron_field(parts[0], 0, 59)
            Cadence._parse_cron_field(parts[1], 0, 23)
            Cadence._parse_cron_field(parts[2], 1, 31)
            Cadence._parse_cron_field(parts[3], 1, 12)
            Cadence._parse_cron_field(parts[4], 0, 7, is_dow=True)
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

        minutes = Cadence._parse_cron_field(parts[0], 0, 59)
        hours = Cadence._parse_cron_field(parts[1], 0, 23)
        dom = Cadence._parse_cron_field(parts[2], 1, 31)
        months = Cadence._parse_cron_field(parts[3], 1, 12)
        dows = Cadence._parse_cron_field(parts[4], 0, 7, is_dow=True)
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
        for rdef in self._canon.all():
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

    # ── Utility methods ─────────────────────────────────────────────────────

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

    def _retry_failed_notifications(self) -> None:
        """Retry queued failed notifications with exponential backoff and local fallbacks."""
        ledger = self._ledger
        queue = ledger.load_notify_queue()
        if not queue:
            return
        remaining: list[dict] = []
        now = datetime.now(timezone.utc)
        for entry in queue:
            retry_count = int(entry.get("retry_count") or 0)
            next_retry = self._parse_utc_iso(str(entry.get("next_retry_utc") or ""))
            if next_retry and next_retry > now:
                remaining.append(entry)
                continue
            if retry_count >= 3:
                logger.warning("Notification dropped after 3 retries: %s", entry.get("channel"))
                self._desktop_notify(str(entry.get("event") or "notification_failed"), entry.get("payload") or {})
                self._alert_log_notify("notification_failed", entry.get("payload") or {}, reason="retry_exhausted")
                continue
            channel = str(entry.get("channel") or "")
            if channel == "telegram":
                adapter_url = str(entry.get("adapter_url") or "http://127.0.0.1:8001")
                payload = entry.get("payload") or {}
                try:
                    import httpx
                    httpx.post(f"{adapter_url}/notify", json=payload, timeout=10)
                    logger.info("Notification retry succeeded for %s", entry.get("payload", {}).get("payload", {}).get("deed_id", ""))
                except Exception as exc:
                    next_count = retry_count + 1
                    delay_s = min(3600, 60 * (2 ** retry_count))
                    entry["retry_count"] = next_count
                    entry["last_retry_error"] = str(exc)[:200]
                    entry["next_retry_utc"] = datetime.fromtimestamp(
                        now.timestamp() + delay_s,
                        timezone.utc,
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                    remaining.append(entry)
            else:
                remaining.append(entry)
        ledger.rewrite_notify_queue(remaining)

    def _tick_eval_windows(self) -> None:
        now = datetime.now(timezone.utc)
        expired: list[dict] = []
        expiring: list[dict] = []

        def _mutate(deeds: list[dict]) -> None:
            for row in deeds:
                status = str(row.get("deed_status") or "").strip().lower()
                if status not in {"awaiting_eval", "pending_review"}:
                    continue
                deadline = self._parse_utc_iso(str(row.get("eval_deadline_utc") or ""))
                if deadline is None:
                    continue
                remaining_s = (deadline - now).total_seconds()
                if 0 < remaining_s <= 12 * 3600 and not row.get("eval_expiring_notified_utc"):
                    row["eval_expiring_notified_utc"] = self._utc_now_iso()
                    expiring.append(dict(row))
                if deadline > now:
                    continue
                row["deed_status"] = "completed"
                row["phase"] = "history"
                row["updated_utc"] = self._utc_now_iso()
                row["eval_expired_utc"] = row["updated_utc"]
                row["feedback_expired"] = True
                row.pop("eval_deadline_utc", None)
                expired.append(dict(row))

        self._ledger.mutate_deeds(_mutate)
        for row in expiring:
            try:
                self._nerve.emit(
                    "eval_expiring",
                    {
                        "deed_id": str(row.get("deed_id") or ""),
                        "slip_id": str(row.get("slip_id") or ""),
                        "folio_id": str(row.get("folio_id") or ""),
                        "deed_title": str(row.get("slip_title") or row.get("deed_title") or row.get("title") or ""),
                        "eval_deadline_utc": str(row.get("eval_deadline_utc") or ""),
                    },
                )
            except Exception:
                continue
        for row in expired:
            try:
                self._nerve.emit(
                    "deed_eval_expired",
                    {
                        "deed_id": str(row.get("deed_id") or ""),
                        "slip_id": str(row.get("slip_id") or ""),
                        "folio_id": str(row.get("folio_id") or ""),
                        "deed_title": str(row.get("slip_title") or row.get("deed_title") or row.get("title") or ""),
                        "feedback_expired": True,
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

    def _emit_cadence_tick_if_due(self) -> None:
        minute_key = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
        if minute_key == self._last_cadence_tick_minute:
            return
        self._last_cadence_tick_minute = minute_key
        self._nerve.emit(
            "cadence.tick",
            {
                "tick_utc": self._utc_now_iso(),
                "tick_minute": minute_key,
            },
        )

    def _resolve_timeout_s(self, rdef) -> int:
        raw = int(getattr(rdef, "timeout_s", 0) or 0)
        if raw > 0:
            return raw
        return 300 if getattr(rdef, "is_hybrid", False) else 120

    def _resolve_degraded_mode(self, rdef) -> str | None:
        mode = str(getattr(rdef, "degraded_mode", "") or "").strip()
        if not mode:
            return None
        ward = self._ward_status()
        cortex_ok = bool(getattr(self._routines, "cortex", None) and self._routines.cortex.is_available())
        if ward == "GREEN" and cortex_ok:
            return None
        return mode

    def _recent_portal_activity_score(self) -> int:
        path = self._state / "telemetry" / "portal_events.jsonl"
        rows = self._ledger.load_jsonl(path, max_items=500)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        score = 0
        for row in rows:
            ts = self._parse_utc_iso(str(row.get("created_utc") or ""))
            if not ts or ts < cutoff:
                continue
            event = str(row.get("event") or "")
            if event in {"voice_message", "submit_requested", "deed_message", "deed_append"}:
                score += 2
            else:
                score += 1
        return score

    def _recent_avg_quality(self) -> float:
        health = self._ledger.load_json("system_health.json", {})
        try:
            return float((health or {}).get("avg_quality") or 0.0)
        except Exception:
            return 0.0

    def _recent_schedule_error_rate(self) -> float:
        rows = self._history[-50:]
        if not rows:
            return 0.0
        errors = sum(1 for row in rows if str(row.get("status") or "") not in {"ok"})
        return errors / max(len(rows), 1)

    def _desktop_notify(self, event: str, payload: dict) -> None:
        title = "Daemon"
        message = f"{event}: {str((payload or {}).get('deed_title') or (payload or {}).get('deed_id') or '')}".strip(": ")
        try:
            subprocess.run(
                ["osascript", "-e", f'display notification "{message[:180]}" with title "{title}"'],
                check=False,
                capture_output=True,
                timeout=10,
            )
        except Exception:
            return

    def _alert_log_notify(self, event: str, payload: dict, *, reason: str) -> None:
        alerts_dir = self._state.parent / "alerts"
        alerts_dir.mkdir(parents=True, exist_ok=True)
        path = alerts_dir / "notification_fallback.log"
        record = {
            "event": event,
            "payload": payload,
            "reason": reason,
            "created_utc": self._utc_now_iso(),
        }
        self._ledger.append_jsonl(path, record)
