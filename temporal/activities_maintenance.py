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

    # 4. Drift detection — flag Mem0 memories not accessed in 90 days (§5.4.1)
    try:
        drift_result = await _detect_memory_drift(self)
        results["drift_detection"] = drift_result
    except Exception as exc:
        results["drift_detection"] = {"ok": False, "error": str(exc)[:200]}
        activity.logger.warning("Drift detection failed: %s", exc)

    # 5. Quota reset — reset daily token counters (§6.12.2)
    try:
        quota_result = await _reset_daily_quotas(self)
        results["quota_reset"] = quota_result
    except Exception as exc:
        results["quota_reset"] = {"ok": False, "error": str(exc)[:200]}
        activity.logger.warning("Quota reset failed: %s", exc)

    # 6. RAGFlow doc sync — delete orphaned docs (§6.12.2)
    try:
        ragflow_result = await _sync_ragflow_docs(self)
        results["ragflow_sync"] = ragflow_result
    except Exception as exc:
        results["ragflow_sync"] = {"ok": False, "error": str(exc)[:200]}
        activity.logger.warning("RAGFlow doc sync failed: %s", exc)

    # 7. Ephemeral job 7-day cleanup (§6.12.2)
    try:
        ephemeral_count = await _cleanup_ephemeral_jobs(self)
        results["ephemeral_job_cleanup"] = {"ok": True, "deleted_count": ephemeral_count}
    except Exception as exc:
        results["ephemeral_job_cleanup"] = {"ok": False, "error": str(exc)[:200]}
        activity.logger.warning("Ephemeral job cleanup failed: %s", exc)

    # 8. Consumed event log 7-day cleanup (§6.12.2)
    try:
        event_count = await _cleanup_consumed_events(self)
        results["event_log_cleanup"] = {"ok": True, "deleted_count": event_count}
    except Exception as exc:
        results["event_log_cleanup"] = {"ok": False, "error": str(exc)[:200]}
        activity.logger.warning("Event log cleanup failed: %s", exc)

    # 9. Emit health check event
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


async def _detect_memory_drift(self) -> dict:
    """Detect stale Mem0 memories not accessed in 90 days (§5.4.1).

    Queries Mem0 for all memories, checks their last access timestamp,
    and flags those older than 90 days for review/cleanup.

    Returns:
        Dict with flagged memory count and optional cleanup actions.
    """
    mem0 = getattr(self, "_mem0", None)
    if not mem0:
        return {"ok": False, "reason": "mem0_unavailable"}

    from datetime import datetime, timedelta, UTC

    cutoff = datetime.now(UTC) - timedelta(days=90)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    flagged: list[dict] = []
    deleted = 0

    # Check each memory category for stale entries
    for user_id in ("user_persona", "planning_experience"):
        try:
            all_memories = mem0.get_all(user_id=user_id)
            if not all_memories:
                continue

            results_list = []
            if isinstance(all_memories, dict):
                results_list = all_memories.get("results", [])
            elif isinstance(all_memories, list):
                results_list = all_memories

            for memory in results_list:
                if not isinstance(memory, dict):
                    continue

                mem_id = str(memory.get("id") or "")
                updated = str(
                    memory.get("updated_at")
                    or memory.get("created_at")
                    or ""
                )

                if not updated or not mem_id:
                    continue

                # Compare timestamps
                try:
                    mem_date = datetime.fromisoformat(
                        updated.replace("Z", "+00:00")
                    )
                    if mem_date < cutoff:
                        mem_text = str(memory.get("memory") or memory.get("text") or "")[:100]
                        flagged.append({
                            "id": mem_id,
                            "user_id": user_id,
                            "text_preview": mem_text,
                            "last_updated": updated,
                        })
                except (ValueError, TypeError):
                    pass

        except Exception as exc:
            activity.logger.debug("Drift check for %s failed: %s", user_id, exc)

    # Auto-delete planning_experience memories older than 90 days
    # (user_persona requires human review, so only flag those)
    for item in flagged:
        if item["user_id"] == "planning_experience":
            try:
                mem0.delete(item["id"])
                deleted += 1
            except Exception:
                pass

    if flagged:
        activity.logger.info(
            "Drift detection: %d stale memories found, %d auto-deleted",
            len(flagged), deleted,
        )

    return {
        "ok": True,
        "flagged_count": len(flagged),
        "auto_deleted": deleted,
        "flagged_for_review": [
            f for f in flagged if f["user_id"] != "planning_experience"
        ],
        "cutoff_date": cutoff_str,
    }


async def _reset_daily_quotas(self) -> dict:
    """Reset daily token counters in the quota table (§6.12.2).

    QuotaManager.reset_daily() zeros out daily_tokens for all users.
    """
    quota_mgr = getattr(self, "_quota", None)
    if not quota_mgr:
        return {"ok": False, "reason": "quota_manager_unavailable"}
    try:
        await quota_mgr.reset_daily()
        activity.logger.info("Daily quota counters reset")
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}


async def _sync_ragflow_docs(self) -> dict:
    """Delete orphaned RAGFlow docs whose source_url no longer exists in knowledge_cache (§6.12.2).

    For each doc registered in RAGFlow, check if a corresponding knowledge_cache
    row still exists. If not, delete the doc from RAGFlow.
    """
    ragflow = getattr(self, "_ragflow", None)
    store = getattr(self, "_store", None)
    if not ragflow or not store:
        return {"ok": False, "reason": "ragflow_or_store_unavailable"}

    deleted = 0
    errors = 0
    try:
        # List all docs in RAGFlow default dataset
        docs = await ragflow.list_docs()
        for doc in docs:
            doc_id = str(doc.get("id") or doc.get("doc_id") or "")
            if not doc_id:
                continue
            # Check if any knowledge_cache row references this doc
            async with store._pool.acquire() as conn:
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM knowledge_cache WHERE ragflow_doc_id = $1)",
                    doc_id,
                )
            if not exists:
                try:
                    await ragflow.delete_doc(doc_id)
                    deleted += 1
                    activity.logger.debug("Deleted orphaned RAGFlow doc: %s", doc_id)
                except Exception as exc:
                    errors += 1
                    activity.logger.debug("Failed to delete RAGFlow doc %s: %s", doc_id, exc)
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200]}

    activity.logger.info("RAGFlow doc sync: deleted %d orphans, %d errors", deleted, errors)
    return {"ok": True, "deleted": deleted, "errors": errors}


async def _cleanup_ephemeral_jobs(self) -> int:
    """Delete ephemeral jobs older than 7 days (§6.12.2).

    Removes jobs where is_ephemeral=True and closed_at < now() - 7 days.
    Steps and artifacts cascade-delete via FK constraints.
    """
    store = getattr(self, "_store", None)
    if not store:
        return 0
    async with store._pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM jobs
            WHERE is_ephemeral = TRUE
              AND closed_at IS NOT NULL
              AND closed_at < now() - interval '7 days'
            """
        )
    count = int(result.split()[-1])
    if count:
        activity.logger.info("Deleted %d stale ephemeral jobs (>7 days)", count)
    return count


async def _cleanup_consumed_events(self) -> int:
    """Delete consumed event_log rows older than 7 days (§6.12.2).

    consumed_at IS NOT NULL means the event was processed.
    """
    store = getattr(self, "_store", None)
    if not store:
        return 0
    async with store._pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM event_log
            WHERE consumed_at IS NOT NULL
              AND created_at < now() - interval '7 days'
            """
        )
    count = int(result.split()[-1])
    if count:
        activity.logger.info("Deleted %d consumed event_log rows (>7 days)", count)
    return count
