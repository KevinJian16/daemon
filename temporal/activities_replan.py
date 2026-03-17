"""Temporal activities: Replan Gate.

After a Job closes, the L1 agent evaluates whether the outcome aligns with
the original Task goal. If deviation is detected, L1 replans the remaining
Task DAG.

Flow:
  1. Job closed -> Replan Gate activity fires
  2. L1 lightweight check (~200 tokens): "did the Job outcome match the goal?"
  3. If aligned -> trigger next downstream Task (if any)
  4. If deviated -> L1 full replan (~800 tokens): output revised Task DAG diff
  5. Apply diff to daemon PG (replace unstarted Tasks) + sync to Plane

Reference: SYSTEM_DESIGN.md §3.7, §3.9, TODO.md Phase 3.5.5-3.5.6
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import UUID

from temporalio import activity

logger = logging.getLogger(__name__)


def _load_model_id(alias: str, fallback: str) -> str:
    """Load model_id for the given alias from config/model_registry.json (§10.15/§10.45).

    Falls back to `fallback` if the registry is missing or the alias is not found.
    """
    try:
        registry_path = Path(__file__).parent.parent / "config" / "model_registry.json"
        data = json.loads(registry_path.read_text())
        for entry in data.get("models", []):
            if entry.get("alias") == alias:
                provider = entry.get("provider", "")
                model_id = entry.get("model_id", "")
                if provider and model_id:
                    return f"{provider}/{model_id}"
                if model_id:
                    return model_id
    except Exception as exc:
        logger.warning("Failed to load model_registry.json for alias %r: %s", alias, exc)
    return fallback


async def run_replan_gate(self, job_id: str, job_result: dict) -> dict:
    """Evaluate completed Job and decide whether to replan.

    Args:
        self: DaemonActivities instance (bound by Temporal)
        job_id: UUID of the completed Job
        job_result: Result dict from JobWorkflow

    Returns:
        dict with 'action' key:
          - "continue": proceed to next downstream Task
          - "replan": L1 generated a revised plan (operations[] applied)
          - "done": no further action needed
          - "failed": replan gate itself failed
    """
    # ── Langfuse: create trace for replan gate (§10.43) ──────────
    lf_trace = None
    langfuse = getattr(self, "_langfuse", None)
    if langfuse:
        try:
            lf_trace = langfuse.trace(
                name=f"replan_gate:{job_id}",
                metadata={"job_id": job_id},
                input={"step_count": len(job_result.get("step_results") or [])},
            )
        except Exception:
            pass

    if not self._openclaw:
        logger.warning("Replan gate skipped -- OpenClawAdapter unavailable")
        if lf_trace:
            try:
                lf_trace.update(output={"action": "continue", "reason": "oc_unavailable"})
            except Exception:
                pass
        return {"action": "continue", "reason": "oc_unavailable"}

    step_results = job_result.get("step_results") or []
    ok_count = sum(
        1 for r in step_results
        if isinstance(r, dict) and str(r.get("status") or "") == "completed"
    )
    total_count = len(step_results)

    # If all steps completed, do lightweight alignment check
    if ok_count == total_count and total_count > 0:
        result = await _lightweight_check(self, job_id, job_result)
        if lf_trace:
            try:
                lf_trace.update(output=result)
            except Exception:
                pass
        return result

    # If some steps failed, report without replanning
    failed = [
        r for r in step_results
        if isinstance(r, dict) and str(r.get("status") or "") != "completed"
    ]
    gate_result = {
        "action": "failed",
        "reason": f"{len(failed)}/{total_count} steps failed",
        "failed_steps": [str(r.get("step_id") or "") for r in failed[:5]],
    }
    if lf_trace:
        try:
            lf_trace.update(output=gate_result)
        except Exception:
            pass
    return gate_result


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
        "Respond with JSON only. Use this schema:\n"
        '{"aligned": true/false, "reason": "brief explanation", '
        '"operations": [...]}\n\n'
        "If aligned, set operations to empty [].\n"
        "If NOT aligned, provide operations array with objects like:\n"
        '  {"op": "add", "task": {"title": "...", "goal": "..."}}\n'
        '  {"op": "remove", "task_id": "..."}\n'
        '  {"op": "update", "task_id": "...", "changes": {"title": "..."}}\n'
        '  {"op": "reorder", "task_ids": ["...", "..."]}\n'
    )

    try:
        # Try local LLM first (task_model_map: replan_gate → local-heavy), fall back to OC
        reply = ""
        try:
            from services.llm_local import chat, resolve_task_model
            alias = resolve_task_model("replan_gate")
            reply = await chat(
                alias,
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1024,
                timeout_s=60,
            )
        except Exception as local_exc:
            logger.info("Replan gate local LLM failed (%s), falling back to OC", local_exc)

        if not reply and self._openclaw:
            analysis_model = _load_model_id("analysis", fallback="deepseek/deepseek-reasoner")
            session_key = f"replan_gate:{job_id}"
            resp = self._openclaw.send_to_session(
                session_key, prompt, timeout_s=60,
                model=analysis_model,
            )
            reply = str(resp.get("reply") or resp.get("text") or "").strip()

        # §10.40: validate LLM output through guardrails before acting on it
        try:
            from config.guardrails.actions import validate_input, validate_output
            _, input_warnings = validate_input(prompt)
            if input_warnings:
                logger.debug("Replan check: input warnings: %s", input_warnings)
            reply, output_warnings = validate_output(reply)
            if output_warnings:
                logger.debug("Replan check: output warnings: %s", output_warnings)
        except Exception as exc:
            logger.debug("Guardrails validation skipped for replan check: %s", exc)

        # Parse JSON response
        start = reply.find("{")
        end = reply.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(reply[start : end + 1])
            aligned = bool(parsed.get("aligned", True))
            reason = str(parsed.get("reason") or "")
            operations = parsed.get("operations") or []

            if aligned:
                return {"action": "continue", "reason": reason}
            else:
                # Validate operations schema (§3.9)
                valid_ops = _validate_operations(operations)
                if valid_ops:
                    # Apply replan diff with batch writes (§3.9)
                    await _apply_replan_batch(self, job_id, valid_ops)
                return {
                    "action": "replan",
                    "reason": reason,
                    "operations": valid_ops,
                }

        # If we can't parse, assume aligned
        return {"action": "continue", "reason": "parse_fallback"}

    except Exception as exc:
        logger.warning("Replan gate check failed for job %s: %s", job_id, exc)
        return {"action": "continue", "reason": f"check_failed: {str(exc)[:100]}"}


def _validate_operations(operations: list) -> list[dict]:
    """Validate and normalize replan operations (§3.9).

    Each operation must have:
      - op: "add" | "remove" | "update" | "reorder"
      - Appropriate payload fields depending on op type
    """
    VALID_OPS = {"add", "remove", "update", "reorder"}
    valid: list[dict] = []

    if not isinstance(operations, list):
        return valid

    for op_raw in operations:
        if not isinstance(op_raw, dict):
            continue
        op_type = str(op_raw.get("op") or "").strip().lower()
        if op_type not in VALID_OPS:
            continue

        normalized: dict = {"op": op_type}

        if op_type == "add":
            task_data = op_raw.get("task")
            if isinstance(task_data, dict):
                normalized["task"] = {
                    "title": str(task_data.get("title") or ""),
                    "goal": str(task_data.get("goal") or ""),
                    "agent_id": str(task_data.get("agent_id") or ""),
                    "steps": task_data.get("steps") if isinstance(task_data.get("steps"), list) else [],
                }
                valid.append(normalized)

        elif op_type == "remove":
            task_id = op_raw.get("task_id")
            if task_id:
                normalized["task_id"] = str(task_id)
                valid.append(normalized)

        elif op_type == "update":
            task_id = op_raw.get("task_id")
            changes = op_raw.get("changes")
            if task_id and isinstance(changes, dict):
                normalized["task_id"] = str(task_id)
                normalized["changes"] = changes
                valid.append(normalized)

        elif op_type == "reorder":
            task_ids = op_raw.get("task_ids")
            if isinstance(task_ids, list):
                normalized["task_ids"] = [str(tid) for tid in task_ids]
                valid.append(normalized)

    return valid


async def _apply_replan_batch(self, job_id: str, operations: list[dict]) -> None:
    """Apply replan operations to PG in a single transaction (§3.9).

    Uses a single connection with transaction for atomicity.
    If any operation fails, the entire batch is rolled back (compensation).
    """
    store = getattr(self, "_store", None)
    if not store or not operations:
        return

    try:
        job_uuid = UUID(job_id)
        job = await store.get_job(job_uuid)
        if not job:
            logger.warning("Replan batch: job %s not found", job_id)
            return

        task_id = job.get("task_id")
        if not task_id:
            return

        task = await store.get_task(task_id)
        if not task:
            return

        project_id = task.get("project_id")

        async with store._pool.acquire() as conn:
            async with conn.transaction():
                for op in operations:
                    op_type = op["op"]

                    if op_type == "add" and project_id:
                        task_data = op.get("task", {})
                        await conn.execute(
                            """
                            INSERT INTO daemon_tasks (title, project_id, trigger_type, dag)
                            VALUES ($1, $2, 'chain', $3)
                            """,
                            task_data.get("title", ""),
                            project_id,
                            json.dumps({
                                "goal": task_data.get("goal", ""),
                                "steps": task_data.get("steps", []),
                            }),
                        )

                    elif op_type == "remove":
                        remove_id = op.get("task_id")
                        if remove_id:
                            try:
                                remove_uuid = UUID(remove_id)
                                # Only remove tasks that don't have running jobs
                                await conn.execute(
                                    """
                                    DELETE FROM daemon_tasks
                                    WHERE task_id = $1
                                      AND NOT EXISTS (
                                        SELECT 1 FROM jobs
                                        WHERE task_id = $1 AND status != 'closed'
                                      )
                                    """,
                                    remove_uuid,
                                )
                            except (ValueError, TypeError):
                                pass

                    elif op_type == "update":
                        update_id = op.get("task_id")
                        changes = op.get("changes", {})
                        if update_id and changes:
                            try:
                                update_uuid = UUID(update_id)
                                # Only update title and dag for now
                                if "title" in changes:
                                    await conn.execute(
                                        "UPDATE daemon_tasks SET title = $1 WHERE task_id = $2",
                                        str(changes["title"]),
                                        update_uuid,
                                    )
                                if "dag" in changes and isinstance(changes["dag"], dict):
                                    await conn.execute(
                                        "UPDATE daemon_tasks SET dag = $1 WHERE task_id = $2",
                                        json.dumps(changes["dag"]),
                                        update_uuid,
                                    )
                            except (ValueError, TypeError):
                                pass

                    elif op_type == "reorder":
                        # Reorder is tracked in the DAG snapshot, not in task records
                        # Log for now; actual ordering is handled by chain_source_task_id
                        logger.info(
                            "Replan reorder for job %s: %s",
                            job_id, op.get("task_ids", []),
                        )

        logger.info(
            "Replan batch applied for job %s: %d operations",
            job_id, len(operations),
        )

    except Exception as exc:
        logger.warning("Replan batch failed for job %s: %s", job_id, exc)
        # Transaction auto-rolled back on exception


async def minimize_redo_scope(self, job_id: str, plan: dict) -> dict:
    """Re-run minimize redo scope (§3.6.2).

    When replanning, mark already-completed steps as skip-able if their
    outputs are still valid. Returns modified plan with skip annotations.
    """
    store = getattr(self, "_store", None)
    if not store:
        return plan

    try:
        job_uuid = UUID(job_id)
        existing_steps = await store.get_steps_for_job(job_uuid)

        # Build set of completed step indexes with valid output
        completed_indexes: set[int] = set()
        for step in existing_steps:
            if (
                str(step.get("status") or "") == "completed"
                and step.get("output_summary")
            ):
                completed_indexes.add(int(step.get("step_index", -1)))

        if not completed_indexes:
            return plan

        # Mark steps in plan that can be skipped
        steps = plan.get("steps") or []
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            step_index = int(step.get("step_index", i))
            if step_index in completed_indexes:
                step["_skip_rerun"] = True
                step["_prior_output_valid"] = True

        logger.info(
            "Minimize redo scope for job %s: %d/%d steps can be skipped",
            job_id, len(completed_indexes), len(steps),
        )

    except Exception as exc:
        logger.debug("Minimize redo scope failed for job %s: %s", job_id, exc)

    return plan
