"""Dispatch replay helpers."""
from __future__ import annotations

import time
import uuid

# Replay backoff schedule in seconds (capped at 4h).
REPLAY_BACKOFF = [60, 300, 900, 3600, 14400]
REPLAY_MAX_ATTEMPTS = 5


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def replay(dispatch, task_id: str, plan: dict) -> dict:
    tasks = dispatch._store.load_tasks()

    task_record: dict | None = next((t for t in tasks if t.get("task_id") == task_id), None)

    if task_record:
        attempts = int(task_record.get("replay_attempts", 0))
        next_replay_utc = str(task_record.get("next_replay_utc") or "")
        if attempts >= REPLAY_MAX_ATTEMPTS:
            update_replay_state(dispatch, task_id, tasks, status="replay_exhausted",
                                reason=f"exceeded max_attempts={REPLAY_MAX_ATTEMPTS}")
            return {"ok": False, "task_id": task_id, "error_code": "replay_exhausted",
                    "error": f"Max replay attempts ({REPLAY_MAX_ATTEMPTS}) exceeded"}
        if next_replay_utc and next_replay_utc > utc():
            return {"ok": False, "task_id": task_id, "error_code": "replay_too_soon",
                    "error": f"Next replay not due until {next_replay_utc}"}

    replay_plan = dict(plan)
    replay_plan["task_id"] = task_id
    replay_plan.pop("queued", None)
    replay_plan.pop("queue_reason", None)
    replay_plan.pop("status", None)
    replay_plan["replay_token"] = f"rpl_{uuid.uuid4().hex[:12]}"

    result = await dispatch.submit(replay_plan)

    if task_record:
        attempts = int(task_record.get("replay_attempts", 0)) + 1
        backoff_s = REPLAY_BACKOFF[min(attempts - 1, len(REPLAY_BACKOFF) - 1)]
        next_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + backoff_s))
        update_replay_state(
            dispatch,
            task_id,
            tasks,
            status="running" if result.get("ok") else "queued",
            attempts=attempts,
            next_replay_utc=next_utc,
        )

    return result


def update_replay_state(
    dispatch,
    task_id: str,
    tasks: list,
    status: str,
    attempts: int | None = None,
    next_replay_utc: str | None = None,
    reason: str | None = None,
) -> None:
    for t in tasks:
        if t.get("task_id") == task_id:
            t["status"] = status
            t["updated_utc"] = utc()
            if attempts is not None:
                t["replay_attempts"] = attempts
            if next_replay_utc is not None:
                t["next_replay_utc"] = next_replay_utc
            if reason:
                t["replay_exhausted_reason"] = reason
            break
    try:
        dispatch._store.save_tasks(tasks)
    except Exception as exc:
        dispatch_logger = getattr(dispatch, "_logger", None)
        if dispatch_logger:
            dispatch_logger.warning("Failed to update replay state for %s: %s", task_id, exc)
