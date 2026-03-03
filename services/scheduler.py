"""Scheduler — Spine Routine direct trigger + adaptive cron management."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fabric.compass import CompassFabric
    from spine.nerve import Nerve
    from spine.registry import SpineRegistry
    from spine.routines import SpineRoutines

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Scheduler:
    """Cron-based scheduler for Spine Routines. Bypasses LLM — direct execution."""

    def __init__(
        self,
        registry: "SpineRegistry",
        routines: "SpineRoutines",
        compass: "CompassFabric",
        nerve: "Nerve",
        state_dir: Path,
    ) -> None:
        self._registry = registry
        self._routines = routines
        self._compass = compass
        self._nerve = nerve
        self._state = state_dir
        self._last_run: dict[str, float] = {}
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())
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
        return await asyncio.to_thread(self._run_routine, routine_name)

    def _run_routine(self, routine_name: str) -> dict:
        rdef = self._registry.get(routine_name)
        if not rdef:
            return {"ok": False, "error": f"Unknown routine: {routine_name}"}

        method_name = routine_name.replace("spine.", "")
        method = getattr(self._routines, method_name, None)
        if not callable(method):
            return {"ok": False, "error": f"Routine method not found: {method_name}"}

        try:
            result = method()
            self._last_run[routine_name] = time.time()
            logger.info(f"Routine {routine_name} completed: {result}")
            return {"ok": True, "routine": routine_name, "result": result}
        except Exception as e:
            logger.error(f"Routine {routine_name} failed: {e}")
            return {"ok": False, "routine": routine_name, "error": str(e)[:400]}

    async def _loop(self) -> None:
        """Main scheduling loop — checks every 60 seconds."""
        while self._running:
            now = time.time()
            for rdef in self._registry.all():
                if not rdef.schedule or rdef.schedule.startswith("adaptive:"):
                    continue
                interval_s = self._parse_cron_simple(rdef.schedule)
                if interval_s and (now - self._last_run.get(rdef.name, 0)) >= interval_s:
                    logger.info(f"Scheduler: triggering {rdef.name}")
                    await asyncio.to_thread(self._run_routine, rdef.name)

            # Check adaptive routines (witness, learn).
            await self._check_adaptive_routines()
            await asyncio.sleep(60)

    async def _check_adaptive_routines(self) -> None:
        """Check adaptive-interval routines based on unanalyzed evaluation count."""
        rhythm = self._compass.get_pref("learning_rhythm", "4h")
        base_interval = self._parse_duration(rhythm) or 4 * 3600

        for routine_name in ("spine.witness", "spine.learn"):
            last = self._last_run.get(routine_name, 0)
            elapsed = time.time() - last
            if elapsed >= base_interval:
                await asyncio.to_thread(self._run_routine, routine_name)

    @staticmethod
    def _parse_cron_simple(schedule: str) -> int | None:
        """Minimal cron parser for fixed-interval schedules only."""
        if schedule.startswith("*/"):
            try:
                return int(schedule.split()[0][2:]) * 60
            except Exception:
                return None
        # Handle common patterns.
        parts = schedule.split()
        if len(parts) == 5:
            # e.g. "0 3 * * *" → daily at 3am → 86400s approximation.
            return 86400
        return None

    @staticmethod
    def _parse_duration(s: str) -> int | None:
        """Parse e.g. '4h', '30m', '2h30m' into seconds."""
        s = s.strip().lower()
        total = 0
        import re
        for match in re.finditer(r"(\d+)([hm])", s):
            val, unit = int(match.group(1)), match.group(2)
            total += val * 3600 if unit == "h" else val * 60
        return total if total else None

    def status(self) -> list[dict]:
        result = []
        for rdef in self._registry.all():
            last = self._last_run.get(rdef.name)
            result.append({
                "routine": rdef.name,
                "mode": rdef.mode,
                "schedule": rdef.schedule,
                "last_run_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last)) if last else None,
                "running": False,
            })
        return result
