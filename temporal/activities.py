"""Daemon Activities — Temporal activity implementations for Job Steps.

Current architecture (7th draft):
  Jobs/Steps stored in PG via Store.
  EventBus (PG LISTEN/NOTIFY) for step/job events.
  OC native sessions for L2 agent execution.
  Mem0 + NeMo Guardrails for memory and safety.
  Publisher agent handles delivery.

Reference: SYSTEM_DESIGN.md §3, TODO.md Phase 3.1
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
from temporalio import activity

from runtime.openclaw import OpenClawAdapter
from runtime.mcp_dispatch import MCPDispatcher
from services.store import Store
from services.event_bus import EventBus
from services.ragflow_client import RAGFlowClient
from services.minio_client import MinIOClient
from temporal.activities_exec import (
    run_openclaw_step as _run_openclaw_step_impl,
    run_direct_step as _run_direct_step_impl,
    run_cc_step as _run_cc_step_impl,
)
from temporal.activities_replan import (
    run_replan_gate as _run_replan_gate_impl,
    minimize_redo_scope as _minimize_redo_scope_impl,
)
from temporal.activities_maintenance import run_maintenance as _run_maintenance_impl
from config.mem0_config import init_mem0, retrieve_agent_context, retrieve_user_preferences
from services.quota import QuotaManager

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _daemon_home() -> Path:
    return Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))


def _openclaw_home() -> Path:
    v = os.environ.get("OPENCLAW_HOME")
    return Path(v) if v else _daemon_home() / "openclaw"


class DaemonActivities:
    """All Temporal activities. Instantiated once per Worker process.

    Requires an asyncpg pool and EventBus instance, both created at
    Worker startup and shared across all activities.
    """

    def __init__(self, pool: asyncpg.Pool, event_bus: EventBus) -> None:
        self._home = _daemon_home()
        self._oc_home = _openclaw_home()
        self._store = Store(pool)
        self._event_bus = event_bus
        self._openclaw: OpenClawAdapter | None = None
        self._mcp = MCPDispatcher(self._home / "config" / "mcp_servers.json")
        self._langfuse = None

        try:
            self._openclaw = OpenClawAdapter(self._oc_home)
        except Exception as exc:
            activity.logger.warning(
                "Failed to initialize OpenClawAdapter from %s: %s", self._oc_home, exc
            )

        # Mem0 memory (§4.3) — semantic memory backed by PG + pgvector
        self._mem0 = init_mem0()

        # Token quota enforcement (§5.8)
        self._quota = QuotaManager(pool)

        # RAGFlow knowledge retrieval (§5.6)
        self._ragflow = RAGFlowClient()

        # MinIO artifact storage (§3.7.1)
        try:
            self._minio = MinIOClient()
            self._minio.ensure_bucket()
            logger.info("MinIO artifact storage initialized")
        except Exception as exc:
            self._minio = None
            logger.warning("MinIO init failed (artifact storage disabled): %s", exc)

        # Langfuse tracing (§3.4)
        try:
            from langfuse import Langfuse
            lf_host = os.environ.get("LANGFUSE_HOST", "")
            lf_pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
            lf_sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
            if lf_host and lf_pk and lf_sk:
                self._langfuse = Langfuse(
                    public_key=lf_pk, secret_key=lf_sk, host=lf_host,
                )
                logger.info("Langfuse tracing enabled: %s", lf_host)
            else:
                logger.info("Langfuse tracing: disabled (missing LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY)")
        except ImportError:
            logger.info("Langfuse tracing: disabled (langfuse package not installed)")
        except Exception as exc:
            logger.warning("Langfuse tracing init failed: %s", exc)

    # ── Step execution (OC agent session) ──────────────────────────────────

    @activity.defn(name="activity_execute_step")
    async def activity_execute_step(self, job_id: str, plan: dict, step: dict) -> dict:
        """Execute one DAG step via OC persistent session.

        Session key: {agent_id}:{job_id}:{step_id} (SYSTEM_DESIGN.md §3.4)
        """
        return await _run_openclaw_step_impl(self, job_id, plan, step)

    # ── Direct step (MCP / Python, zero LLM) ──────────────────────────────

    @activity.defn(name="activity_direct_step")
    async def activity_direct_step(self, job_id: str, plan: dict, step: dict) -> dict:
        """Execute a direct step via MCP tool — zero LLM tokens."""
        return await _run_direct_step_impl(self, job_id, plan, step)

    # ── CC/Codex step (CLI, bypasses OC) ─────────────────────────────────

    @activity.defn(name="activity_cc_step")
    async def activity_cc_step(self, job_id: str, plan: dict, step: dict) -> dict:
        """Execute a step via Claude Code or Codex CLI — bypasses OC Gateway."""
        return await _run_cc_step_impl(self, job_id, plan, step)

    # ── Job status ─────────────────────────────────────────────────────────

    @activity.defn(name="activity_update_job_status")
    async def activity_update_job_status(
        self, job_id: str, status: str, sub_status: str = "", error: str = ""
    ) -> dict:
        """Update job status in PG and emit event."""
        try:
            job_uuid = UUID(job_id)
            extra: dict[str, Any] = {}
            if error:
                extra["error_message"] = error
            await self._store.update_job_status(job_uuid, status, sub_status, **extra)
        except Exception as exc:
            activity.logger.warning("Failed to update job %s status: %s", job_id, exc)

        await self._event_bus.publish("job_events", f"job_{status}", {
            "job_id": job_id,
            "status": status,
            "sub_status": sub_status,
            "error": error,
            "updated_utc": _utc(),
        })

        return {"ok": True, "job_id": job_id, "status": status}

    # ── Step status ────────────────────────────────────────────────────────

    @activity.defn(name="activity_update_step_status")
    async def activity_update_step_status(
        self, step_id: str, status: str, **extra: Any
    ) -> dict:
        """Update step status in PG."""
        try:
            step_uuid = UUID(step_id)
            await self._store.update_step_status(step_uuid, status, **extra)
        except Exception as exc:
            activity.logger.warning("Failed to update step %s status: %s", step_id, exc)
        return {"ok": True, "step_id": step_id, "status": status}

    # ── Replan Gate (Phase 3.5) ────────────────────────────────────────────

    @activity.defn(name="activity_replan_gate")
    async def activity_replan_gate(self, job_id: str, job_result: dict) -> dict:
        """Evaluate completed Job outcome and decide whether to replan.

        Reference: SYSTEM_DESIGN.md §3.7
        """
        return await _run_replan_gate_impl(self, job_id, job_result)

    # ── Minimize redo scope (§3.6.2) ─────────────────────────────────────

    @activity.defn(name="activity_minimize_redo_scope")
    async def activity_minimize_redo_scope(self, job_id: str, plan: dict) -> dict:
        """For re-run jobs, annotate already-completed steps with _skip_rerun=True.

        Called by JobWorkflow when plan carries a 'rerun_job_id'.
        Returns the modified plan dict with _skip_rerun annotations.

        Reference: SYSTEM_DESIGN.md §3.6.2
        """
        return await _minimize_redo_scope_impl(self, job_id, plan)

    # ── Plane writeback (§6.6, D.5) ────────────────────────────────────────

    @activity.defn(name="activity_plane_writeback")
    async def activity_plane_writeback(self, job_id: str, sub_status: str) -> dict:
        """Write Job status back to corresponding Plane Issue.

        Mapping (D.5):
          completed/succeeded → Plane 'completed'
          failed              → Plane 'started' (don't auto-complete on failure)
          cancelled           → Plane 'cancelled'

        Retried 5x with exponential backoff by Temporal RetryPolicy.
        If all retries fail, marks plane_sync_failed=True in PG.
        """
        PLANE_STATE_MAP = {
            "queued": "started",
            "executing": "started",
            "paused": "started",
            "retrying": "started",
            "completed": "completed",
            "succeeded": "completed",
            "failed": "started",
            "cancelled": "cancelled",
        }
        plane_state = PLANE_STATE_MAP.get(sub_status, "started")

        try:
            job_uuid = UUID(job_id)
            job = await self._store.get_job(job_uuid)
            if not job:
                return {"ok": False, "error": "job_not_found"}

            task_id = job.get("task_id")
            if not task_id:
                return {"ok": False, "error": "no_task_id"}

            task = await self._store.get_task(task_id)
            if not task:
                return {"ok": False, "error": "task_not_found"}

            plane_issue_id = task.get("plane_issue_id")
            if not plane_issue_id:
                return {"ok": True, "skipped": True, "reason": "no_plane_issue"}

            plane_api_url = os.environ.get("PLANE_API_URL", "http://localhost:8001")
            plane_api_token = os.environ.get("PLANE_API_TOKEN", "")
            plane_workspace = os.environ.get("PLANE_WORKSPACE_SLUG", "daemon")

            if not plane_api_token:
                return {"ok": False, "error": "no_plane_api_token"}

            from services.plane_client import PlaneClient
            client = PlaneClient(
                api_url=plane_api_url,
                api_token=plane_api_token,
                workspace_slug=plane_workspace,
            )
            try:
                project_id = str(task.get("project_id") or os.environ.get("PLANE_PROJECT_ID", ""))
                if not project_id:
                    return {"ok": False, "error": "no_project_id"}

                await client.update_issue(
                    project_id=project_id,
                    issue_id=str(plane_issue_id),
                    data={"state_group": plane_state},
                )

                # §7.6: Write back job results (not just status) as comments
                if sub_status in ("completed", "succeeded"):
                    comment_parts = [f"**Job {job_id[:8]} completed successfully.**\n"]
                    try:
                        steps = await self._store.get_steps_for_job(job_uuid)
                        completed_steps = [
                            s for s in steps
                            if str(s.get("status") or "") == "completed"
                        ]
                        if completed_steps:
                            comment_parts.append(
                                f"**Steps completed:** {len(completed_steps)}\n"
                            )
                            for s in completed_steps[:10]:
                                agent = str(s.get("agent_id") or "?")
                                summary = str(s.get("output_summary") or "")[:300]
                                step_id_short = str(s.get("step_id") or "")[:8]
                                if summary:
                                    comment_parts.append(
                                        f"- **[{agent}]** (step {step_id_short}): {summary}"
                                    )
                                else:
                                    comment_parts.append(
                                        f"- **[{agent}]** (step {step_id_short}): completed"
                                    )
                    except Exception as exc:
                        activity.logger.debug(
                            "Could not fetch steps for writeback comment: %s", exc
                        )
                    await client.add_comment(
                        project_id=project_id,
                        issue_id=str(plane_issue_id),
                        comment="\n".join(comment_parts),
                    )
                elif sub_status == "failed":
                    await client.add_comment(
                        project_id=project_id,
                        issue_id=str(plane_issue_id),
                        comment=f"**Job {job_id[:8]} failed.** Check Temporal for details.",
                    )
            finally:
                await client.close()

            return {"ok": True, "plane_state": plane_state}

        except Exception as exc:
            # Mark plane_sync_failed on error
            try:
                await self._store.update_job_status(
                    UUID(job_id), "closed", sub_status, plane_sync_failed=True,
                )
            except Exception:
                pass
            raise  # Let Temporal retry

    # ── Chain trigger (§3.10) ──────────────────────────────────────────────

    @activity.defn(name="activity_trigger_chain")
    async def activity_trigger_chain(self, job_id: str) -> dict:
        """Trigger downstream chain Tasks after Job closes (§3.10).

        Looks for Tasks with trigger_type='chain' and
        chain_source_task_id matching this Job's Task.
        """
        try:
            job_uuid = UUID(job_id)
            job = await self._store.get_job(job_uuid)
            if not job:
                return {"ok": False, "error": "job_not_found"}

            task_id = job.get("task_id")
            if not task_id:
                return {"ok": True, "triggered": 0}

            # Find downstream chain Tasks
            async with self._store._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT task_id, title, dag FROM daemon_tasks
                    WHERE chain_source_task_id = $1
                      AND trigger_type = 'chain'
                    """,
                    task_id,
                )

            # §3.7.1: Get predecessor task's final artifact for injection
            predecessor_artifact = await self._store.get_last_final_artifact_for_task(task_id)
            artifact_summary = None
            if predecessor_artifact:
                artifact_summary = {
                    "title": str(predecessor_artifact.get("title") or ""),
                    "summary": str(predecessor_artifact.get("summary") or "")[:1000],
                    "artifact_type": str(predecessor_artifact.get("artifact_type") or ""),
                    "minio_path": str(predecessor_artifact.get("minio_path") or ""),
                }

            triggered = 0
            for row in rows:
                downstream_task_id = row["task_id"]

                # Skip if already has running Job (§3.5)
                if await self._store.has_active_job_for_task(downstream_task_id):
                    activity.logger.info(
                        "Skip chain trigger for task %s: active job exists",
                        downstream_task_id,
                    )
                    continue

                # §3.7.1: Task->Task artifact chain injection
                event_payload = {
                    "source_job_id": job_id,
                    "source_task_id": str(task_id),
                    "downstream_task_id": str(downstream_task_id),
                    "title": row["title"],
                }
                if artifact_summary:
                    event_payload["predecessor_artifact"] = artifact_summary

                await self._event_bus.publish("job_events", "chain_triggered", event_payload)
                triggered += 1

            return {"ok": True, "triggered": triggered}

        except Exception as exc:
            activity.logger.warning("Chain trigger failed for job %s: %s", job_id, exc)
            return {"ok": False, "error": str(exc)[:200]}

    # ── Post-Job learning (§8.1-8.2) ────────────────────────────────────────

    @activity.defn(name="activity_post_job_learn")
    async def activity_post_job_learn(self, job_id: str, job_result: dict) -> dict:
        """Extract planning experience from a successful Job into Mem0.

        After Job completion, reads:
          - completed Job plan (DAG structure)
          - step results (agent choices, ordering, outputs)
        Extracts what worked and writes to Mem0 with
        agent_id="planning_experience" for future copilot/scene agent retrieval.

        Reference: SYSTEM_DESIGN.md §8.1-§8.2
        """
        if not self._mem0:
            return {"ok": False, "reason": "mem0_unavailable"}

        try:
            job_uuid = UUID(job_id)
            job = await self._store.get_job(job_uuid)
            if not job:
                return {"ok": False, "reason": "job_not_found"}

            # Retrieve steps for this Job
            steps = await self._store.get_steps_for_job(job_uuid)

            # Build a summary of what worked
            step_results = job_result.get("step_results") or []
            completed_steps = [
                sr for sr in step_results
                if isinstance(sr, dict) and sr.get("status") == "completed"
            ]

            if not completed_steps:
                return {"ok": True, "skipped": True, "reason": "no_completed_steps"}

            # Extract planning patterns
            dag_snapshot = job.get("dag_snapshot")
            if isinstance(dag_snapshot, str):
                import json
                try:
                    dag_snapshot = json.loads(dag_snapshot)
                except Exception:
                    dag_snapshot = {}

            # Build experience summary
            agents_used = [str(s.get("agent_id") or "") for s in completed_steps if s.get("agent_id")]
            step_count = len(completed_steps)
            task_title = ""
            if isinstance(dag_snapshot, dict):
                task_title = str(dag_snapshot.get("task_title") or dag_snapshot.get("title") or "")

            experience_parts = []
            if task_title:
                experience_parts.append(f"Task: {task_title}")
            experience_parts.append(f"Steps: {step_count} completed successfully")
            if agents_used:
                experience_parts.append(f"Agents: {', '.join(dict.fromkeys(agents_used))}")

            # Include DAG structure summary
            if isinstance(dag_snapshot, dict) and dag_snapshot.get("steps"):
                dag_steps = dag_snapshot["steps"]
                if isinstance(dag_steps, list):
                    dag_summary = []
                    for i, ds in enumerate(dag_steps[:10]):
                        if isinstance(ds, dict):
                            agent = str(ds.get("agent_id") or ds.get("agent") or "?")
                            goal = str(ds.get("goal") or "")[:100]
                            deps = ds.get("depends_on") or []
                            dag_summary.append(
                                f"  Step {i}: [{agent}] {goal}"
                                + (f" (depends: {deps})" if deps else "")
                            )
                    if dag_summary:
                        experience_parts.append("DAG structure:\n" + "\n".join(dag_summary))

            experience_text = "\n".join(experience_parts)

            # Write to Mem0 as procedural memory
            self._mem0.add(
                experience_text,
                user_id="planning_experience",
                metadata={
                    "type": "planning_experience",
                    "job_id": job_id,
                    "step_count": step_count,
                    "agents": agents_used,
                    "source": "post_job_learn",
                },
            )

            logger.info(
                "Post-Job learning: stored experience for job %s (%d steps)",
                job_id[:8], step_count,
            )
            return {"ok": True, "job_id": job_id, "experience_length": len(experience_text)}

        except Exception as exc:
            logger.warning("Post-Job learning failed for %s: %s", job_id, exc)
            return {"ok": False, "error": str(exc)[:200]}

    # ── L1 failure judgment (§3.8) ───────────────────────────────────────

    @activity.defn(name="activity_l1_failure_judgment")
    async def activity_l1_failure_judgment(
        self, job_id: str, step_info: dict, error: str,
    ) -> dict:
        """After retries exhausted, ask L1 whether to skip/replace/terminate (§3.8).

        Returns dict with 'decision' key: 'skip', 'replace', or 'terminate'.
        """
        if not self._openclaw:
            return {"decision": "terminate", "reason": "oc_unavailable"}

        prompt = (
            "A Step in a Job has failed after all retries.\n\n"
            f"Job ID: {job_id}\n"
            f"Step goal: {str(step_info.get('goal', 'unknown'))[:200]}\n"
            f"Agent: {step_info.get('agent_id', 'unknown')}\n"
            f"Error: {error[:300]}\n\n"
            "What should we do? Respond with JSON only:\n"
            '{"decision": "skip|replace|terminate", "reason": "brief explanation"}\n'
        )

        # §10.40: validate input through guardrails before sending to LLM
        from config.guardrails.actions import validate_input, validate_output
        try:
            filtered_prompt, input_warnings = validate_input(prompt)
            if input_warnings:
                logger.debug("L1 failure judgment: input warnings: %s", input_warnings)
            if not filtered_prompt:
                return {"decision": "terminate", "reason": "input_blocked_by_guardrails"}
        except Exception as exc:
            filtered_prompt = prompt
            logger.debug("Guardrails input validation skipped: %s", exc)

        # §10.43: create Langfuse trace for this LLM call
        lf_trace = None
        if self._langfuse:
            try:
                lf_trace = self._langfuse.trace(
                    name=f"l1_failure_judgment:{job_id}",
                    metadata={"job_id": job_id, "agent_id": step_info.get("agent_id", "")},
                    input={"prompt": filtered_prompt[:500]},
                )
            except Exception:
                pass

        try:
            session_key = f"failure_judgment:{job_id}"
            resp = self._openclaw.send_to_session(session_key, filtered_prompt, timeout_s=30)
            reply = str(resp.get("reply") or resp.get("text") or "").strip()

            # §10.40: validate LLM output through guardrails
            try:
                reply, output_warnings = validate_output(reply)
                if output_warnings:
                    logger.debug("L1 failure judgment: output warnings: %s", output_warnings)
            except Exception as exc:
                logger.debug("Guardrails output validation skipped: %s", exc)

            import json as _json
            start = reply.find("{")
            end = reply.rfind("}")
            if start >= 0 and end > start:
                parsed = _json.loads(reply[start : end + 1])
                decision = str(parsed.get("decision") or "terminate").lower()
                if decision in ("skip", "replace", "terminate"):
                    result = {
                        "decision": decision,
                        "reason": str(parsed.get("reason") or ""),
                    }
                    if lf_trace:
                        try:
                            lf_trace.update(output=result)
                        except Exception:
                            pass
                    return result

            if lf_trace:
                try:
                    lf_trace.update(output={"decision": "terminate", "reason": "parse_fallback"})
                except Exception:
                    pass
            return {"decision": "terminate", "reason": "parse_fallback"}

        except Exception as exc:
            logger.warning("L1 failure judgment failed for job %s: %s", job_id, exc)
            if lf_trace:
                try:
                    lf_trace.update(output={"decision": "terminate", "reason": str(exc)[:100]})
                except Exception:
                    pass
            return {"decision": "terminate", "reason": f"error: {str(exc)[:100]}"}

    # ── Persona taste update (§5.4) ────────────────────────────────────────

    @activity.defn(name="activity_persona_taste_update")
    async def activity_persona_taste_update(self, job_id: str, job_result: dict) -> dict:
        """Extract style/preference feedback from job results and store in Mem0 (§5.4).

        Flow:
          1. Gather recent scene conversation messages (last 50 user messages)
          2. Extract feedback candidates via SessionManager._extract_feedback_candidates
          3. Validate each candidate through NeMo guardrails (zero token)
          4. Write validated candidates to Mem0 as user preferences

        Note: this runs asynchronously after job close — does not block job completion.
        Only stores candidates with high confidence (no user confirmation step since this
        runs server-side; candidates that require confirmation are emitted as events for
        Telegram/desktop to surface to user).

        Reference: SYSTEM_DESIGN.md §5.4
        """
        if not self._mem0:
            return {"ok": False, "reason": "mem0_unavailable"}

        try:
            job_uuid = UUID(job_id)
            job = await self._store.get_job(job_uuid)
            if not job:
                return {"ok": False, "reason": "job_not_found"}

            # Only run on successful jobs
            sub_status = str(job.get("sub_status") or "")
            if sub_status not in ("completed", "succeeded"):
                return {"ok": True, "skipped": True, "reason": "job_not_successful"}

            # Determine source scene from task
            task_id = job.get("task_id")
            scene = "copilot"  # default
            if task_id:
                task = await self._store.get_task(task_id)
                if task:
                    src = str(task.get("source") or "")
                    # source format: "scene:<scene_name>" or "scene:<scene_name>:direct"
                    if src.startswith("scene:"):
                        parts = src.split(":")
                        if len(parts) >= 2 and parts[1] in ("copilot", "instructor", "navigator", "autopilot"):
                            scene = parts[1]

            # Gather recent user messages for this scene
            messages = await self._store.get_recent_messages(scene, limit=50)
            if not messages:
                return {"ok": True, "skipped": True, "reason": "no_messages"}

            # Extract feedback candidates using the same logic as SessionManager
            from services.session_manager import SessionManager
            candidates = SessionManager._extract_feedback_candidates(None, messages)

            if not candidates:
                return {"ok": True, "written": 0, "reason": "no_candidates"}

            # §10.21: ALL taste candidates (preference, correction, judgment) must be held
            # for user confirmation before writing to Mem0.  Nothing is written here —
            # writes happen only in activity_persona_taste_confirm (or via
            # SessionManager.apply_confirmed_feedback) after the user confirms.
            # Pre-validate through NeMo guardrails so blocked candidates are dropped early.
            from config.guardrails.actions import validate_output

            pending_confirmation: list[dict] = []

            for item in candidates:
                content = str(item.get("content") or "").strip()
                if not content:
                    continue

                cleaned, warnings = validate_output(content)
                if not cleaned:
                    logger.debug("Persona taste: candidate blocked by NeMo: %s", warnings)
                    continue

                # Attach cleaned content back so the confirm activity can use it as-is
                pending_confirmation.append({**item, "content": cleaned})

            # Emit ALL candidates as a taste_candidates_pending event for Telegram/desktop.
            # The user's confirmation triggers the actual Mem0 write.
            if pending_confirmation:
                try:
                    await self._event_bus.publish("persona_events", "taste_candidates_pending", {
                        "job_id": job_id,
                        "scene": scene,
                        "candidates": pending_confirmation[:10],
                        "count": len(pending_confirmation),
                    })
                except Exception as exc:
                    logger.debug("Failed to emit taste_candidates_pending event: %s", exc)

            logger.info(
                "Persona taste update: %d pending confirmation (job %s, scene %s)",
                len(pending_confirmation), job_id[:8], scene,
            )
            return {
                "ok": True,
                "job_id": job_id,
                "scene": scene,
                "written": 0,  # writes deferred to confirmation step (§10.21)
                "pending_confirmation": len(pending_confirmation),
            }

        except Exception as exc:
            logger.warning("Persona taste update failed for job %s: %s", job_id, exc)
            return {"ok": False, "error": str(exc)[:200]}

    # ── Scheduled maintenance (Phase 4.17) ─────────────────────────────────

    @activity.defn(name="activity_maintenance")
    async def activity_maintenance(self) -> dict:
        """Run periodic maintenance (replaces old Spine routines).

        Scheduled via Temporal Schedule, typically every 6 hours.
        """
        return await _run_maintenance_impl(self)
