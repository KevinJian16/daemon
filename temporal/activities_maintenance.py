"""Temporal activities: scheduled maintenance.

Single cleanup activity replacing the old 7 Spine routines:
  pulse, record, witness, focus, relay, tend, curate

Runs on a Temporal Schedule (e.g., every 6 hours).

Tasks:
  1. Clean up expired knowledge_cache entries
  2. Clean up old closed jobs (>30 days)
  3. Clean up old conversation messages (>90 days)
  4. Emit health check event

Reference: TODO.md Phase 4.17
"""
from __future__ import annotations

import logging
import time
from typing import Any

from temporalio import activity

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def run_maintenance(self) -> dict:
    """Run periodic maintenance tasks.

    This replaces the old Spine routines (pulse, record, witness, focus,
    relay, tend, curate) with a single, simpler activity.
    """
    results: dict[str, Any] = {"started_utc": _utc()}

    # 1. Clean expired knowledge cache
    try:
        expired_count = await self._store.cleanup_expired_knowledge()
        results["knowledge_cleanup"] = {"ok": True, "expired_count": expired_count}
    except Exception as exc:
        results["knowledge_cleanup"] = {"ok": False, "error": str(exc)[:200]}
        activity.logger.warning("Knowledge cleanup failed: %s", exc)

    # 2. Clean up old closed jobs (>30 days retention)
    try:
        job_count = await self._store.cleanup_old_jobs(retention_days=30)
        results["job_cleanup"] = {"ok": True, "deleted_count": job_count}
    except Exception as exc:
        results["job_cleanup"] = {"ok": False, "error": str(exc)[:200]}
        activity.logger.warning("Job cleanup failed: %s", exc)

    # 3. Clean up old conversation messages (>90 days retention)
    try:
        msg_count = await self._store.cleanup_old_messages(retention_days=90)
        results["message_cleanup"] = {"ok": True, "deleted_count": msg_count}
    except Exception as exc:
        results["message_cleanup"] = {"ok": False, "error": str(exc)[:200]}
        activity.logger.warning("Message cleanup failed: %s", exc)

    # 4. Emit health check event
    try:
        await self._event_bus.publish("system_events", "maintenance_completed", {
            "status": "ok",
            "checked_utc": _utc(),
            "maintenance_results": results,
        })
        results["health_event"] = {"ok": True}
    except Exception as exc:
        results["health_event"] = {"ok": False, "error": str(exc)[:200]}

    results["completed_utc"] = _utc()
    return results
