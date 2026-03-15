"""Temporal activities: Replan Gate.

After a Job closes, the L1 agent evaluates whether the outcome aligns with
the original Task goal. If deviation is detected, L1 replans the remaining
Task DAG.

Flow:
  1. Job closed → Replan Gate activity fires
  2. L1 lightweight check (~200 tokens): "did the Job outcome match the goal?"
  3. If aligned → trigger next downstream Task (if any)
  4. If deviated → L1 full replan (~800 tokens): output revised Task DAG diff
  5. Apply diff to daemon PG (replace unstarted Tasks) + sync to Plane

Reference: SYSTEM_DESIGN.md §3.7, TODO.md Phase 3.5.5-3.5.6
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from temporalio import activity

logger = logging.getLogger(__name__)


async def run_replan_gate(self, job_id: str, job_result: dict) -> dict:
    """Evaluate completed Job and decide whether to replan.

    Args:
        self: DaemonActivities instance (bound by Temporal)
        job_id: UUID of the completed Job
        job_result: Result dict from JobWorkflow

    Returns:
        dict with 'action' key:
          - "continue": proceed to next downstream Task
          - "replan": L1 generated a revised plan
          - "done": no further action needed
          - "failed": replan gate itself failed
    """
    if not self._openclaw:
        logger.warning("Replan gate skipped — OpenClawAdapter unavailable")
        return {"action": "continue", "reason": "oc_unavailable"}

    step_results = job_result.get("step_results") or []
    ok_count = sum(
        1 for r in step_results
        if isinstance(r, dict) and str(r.get("status") or "") == "completed"
    )
    total_count = len(step_results)

    # If all steps completed, do lightweight alignment check
    if ok_count == total_count and total_count > 0:
        return await _lightweight_check(self, job_id, job_result)

    # If some steps failed, report without replanning
    failed = [
        r for r in step_results
        if isinstance(r, dict) and str(r.get("status") or "") != "completed"
    ]
    return {
        "action": "failed",
        "reason": f"{len(failed)}/{total_count} steps failed",
        "failed_steps": [str(r.get("step_id") or "") for r in failed[:5]],
    }


async def _lightweight_check(self, job_id: str, job_result: dict) -> dict:
    """L1 lightweight alignment check (~200 tokens).

    Asks L1: "Given the Job result, does the outcome align with the Task goal?"
    """
    step_results = job_result.get("step_results") or []
    # Build concise summary of step outputs
    summaries = []
    for r in step_results:
        if not isinstance(r, dict):
            continue
        output = str(r.get("output") or "")[:500]
        summaries.append(f"- Step {r.get('step_id', '?')}: {output[:200]}")

    prompt = (
        "You are evaluating whether a completed Job's output aligns with "
        "the original Task goal.\n\n"
        f"Job ID: {job_id}\n"
        f"Step summaries:\n{''.join(summaries[:8])}\n\n"
        "Respond with JSON only: "
        '{"aligned": true/false, "reason": "brief explanation"}\n'
        "If aligned, the next downstream Task will proceed. "
        "If not aligned, a full replan will be triggered."
    )

    try:
        # Use a lightweight session for the check
        session_key = f"replan_gate:{job_id}"
        resp = self._openclaw.send_to_session(session_key, prompt, timeout_s=60)
        reply = str(resp.get("reply") or resp.get("text") or "").strip()

        # Parse JSON response
        start = reply.find("{")
        end = reply.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(reply[start : end + 1])
            aligned = bool(parsed.get("aligned", True))
            reason = str(parsed.get("reason") or "")

            if aligned:
                return {"action": "continue", "reason": reason}
            else:
                return {"action": "replan", "reason": reason}

        # If we can't parse, assume aligned
        return {"action": "continue", "reason": "parse_fallback"}

    except Exception as exc:
        logger.warning("Replan gate check failed for job %s: %s", job_id, exc)
        return {"action": "continue", "reason": f"check_failed: {str(exc)[:100]}"}
