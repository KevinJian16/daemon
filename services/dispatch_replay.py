"""Dispatch replay helpers."""
from __future__ import annotations

import time
import uuid

# Replay backoff schedule in seconds (capped at 4h).
REPLAY_BACKOFF = [60, 300, 900, 3600, 14400]
REPLAY_MAX_ATTEMPTS = 5


def utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def replay(dispatch, run_id: str, plan: dict) -> dict:
    runs = dispatch._store.load_runs()

    run_record: dict | None = next((r for r in runs if r.get("run_id") == run_id), None)

    if run_record:
        attempts = int(run_record.get("replay_attempts", 0))
        next_replay_utc = str(run_record.get("next_replay_utc") or "")
        if attempts >= REPLAY_MAX_ATTEMPTS:
            update_replay_state(dispatch, run_id, runs, run_status="replay_exhausted",
                                reason=f"exceeded max_attempts={REPLAY_MAX_ATTEMPTS}")
            return {"ok": False, "run_id": run_id, "error_code": "replay_exhausted",
                    "error": f"Max replay attempts ({REPLAY_MAX_ATTEMPTS}) exceeded"}
        if next_replay_utc and next_replay_utc > utc():
            return {"ok": False, "run_id": run_id, "error_code": "replay_too_soon",
                    "error": f"Next replay not due until {next_replay_utc}"}

    replay_plan = dict(plan)
    replay_plan["run_id"] = run_id
    replay_plan.pop("queued", None)
    replay_plan.pop("queue_reason", None)
    replay_plan.pop("run_status", None)
    replay_plan["replay_token"] = f"rpl_{uuid.uuid4().hex[:12]}"

    result = await dispatch.submit(replay_plan)

    if run_record:
        attempts = int(run_record.get("replay_attempts", 0)) + 1
        backoff_s = REPLAY_BACKOFF[min(attempts - 1, len(REPLAY_BACKOFF) - 1)]
        next_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + backoff_s))
        update_replay_state(
            dispatch,
            run_id,
            runs,
            run_status="running" if result.get("ok") else "queued",
            attempts=attempts,
            next_replay_utc=next_utc,
        )

    return result


def update_replay_state(
    dispatch,
    run_id: str,
    runs: list,
    run_status: str,
    attempts: int | None = None,
    next_replay_utc: str | None = None,
    reason: str | None = None,
) -> None:
    for row in runs:
        if row.get("run_id") == run_id:
            row["run_status"] = run_status
            row["updated_utc"] = utc()
            if attempts is not None:
                row["replay_attempts"] = attempts
            if next_replay_utc is not None:
                row["next_replay_utc"] = next_replay_utc
            if reason:
                row["replay_exhausted_reason"] = reason
            break
    try:
        dispatch._store.save_runs(runs)
    except Exception as exc:
        dispatch_logger = getattr(dispatch, "_logger", None)
        if dispatch_logger:
            dispatch_logger.warning("Failed to update replay state for %s: %s", run_id, exc)
