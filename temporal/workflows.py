"""Temporal Workflows — Job execution, health check, self-heal.

Workflows:
  - JobWorkflow: DAG-based multi-step Job orchestration
  - HealthCheckWorkflow: Weekly system health check (§7.7)
  - SelfHealWorkflow: 4-activity self-healing (§7.8)
  - MaintenanceWorkflow: Periodic cleanup (6h schedule)
  - BackupWorkflow: Daily PG + MinIO backup

Reference: SYSTEM_DESIGN.md §3, §7, TODO.md Phase 3
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


@dataclass
class JobInput:
    """Input to JobWorkflow."""
    plan: dict
    job_id: str = ""


@workflow.defn(name="JobWorkflow")
class JobWorkflow:
    """Executes a DAG of Steps with Kahn topological ordering.

    Each step = 1 OC session (agent type) or 1 MCP call (direct type).
    Steps declare depends_on for parallel execution within a layer.
    """

    def __init__(self) -> None:
        self._pause_requested: bool = False
        self._confirmation_result: dict | None = None

    @workflow.signal(name="pause_execution")
    def pause_execution(self, payload: dict | None = None) -> None:
        _ = payload
        self._pause_requested = True

    @workflow.signal(name="resume_execution")
    def resume_execution(self, payload: dict | None = None) -> None:
        _ = payload
        self._pause_requested = False

    @workflow.signal(name="confirmation_received")
    def confirmation_received(self, payload: dict | None = None) -> None:
        """User confirmed a pending_confirmation step (§3.5, D.2)."""
        self._confirmation_result = {"confirmed": True, **(payload or {})}

    @workflow.signal(name="confirmation_rejected")
    def confirmation_rejected(self, payload: dict | None = None) -> None:
        """User rejected a pending_confirmation step (§3.5, D.2)."""
        self._confirmation_result = {"confirmed": False, **(payload or {})}

    @workflow.run
    async def run(self, inp: JobInput) -> dict:
        plan = inp.plan or {}
        job_id = inp.job_id or str(plan.get("job_id", ""))

        async def _mark_failure(message: str) -> None:
            await self._mark_job_status(job_id, "closed", "failed", message[:200])

        # Extract steps from plan
        steps = plan.get("steps") or []
        if not isinstance(steps, list) or not steps:
            await _mark_failure("missing steps")
            raise ApplicationError("missing steps", non_retryable=True)

        max_parallel = max(1, min(64, int(plan.get("concurrency") or 2)))

        # Build normalized step map and validate IDs
        step_list: list[dict] = []
        id_set: set[str] = set()
        for i, st in enumerate(steps):
            if not isinstance(st, dict):
                await _mark_failure(f"invalid step at index {i}")
                raise ApplicationError(f"invalid step at index {i}", non_retryable=True)
            sid = self._step_id(st, i)
            if sid in id_set:
                await _mark_failure(f"duplicate step id: {sid}")
                raise ApplicationError(f"duplicate step id: {sid}", non_retryable=True)
            id_set.add(sid)
            step_list.append({**st, "id": sid})

        step_by_id = {st["id"]: st for st in step_list}
        id_list = [st["id"] for st in step_list]

        # Build dependency graph
        deps: dict[str, set[str]] = {}
        rev: dict[str, set[str]] = {sid: set() for sid in step_by_id}
        for sid, st in step_by_id.items():
            ds = set(self._deps(st))
            if sid in ds:
                await _mark_failure(f"step {sid} depends on itself")
                raise ApplicationError(
                    f"step {sid} depends on itself", non_retryable=True
                )
            unknown = [d for d in ds if d not in step_by_id]
            if unknown:
                await _mark_failure(f"step {sid}: unknown deps {unknown}")
                raise ApplicationError(
                    f"step {sid}: unknown deps {unknown}", non_retryable=True
                )
            deps[sid] = ds
            for d in ds:
                rev[d].add(sid)

        # Kahn cycle detection
        indeg = {sid: len(d) for sid, d in deps.items()}
        q = [sid for sid, n in indeg.items() if n == 0]
        seen = 0
        idx = 0
        while idx < len(q):
            cur = q[idx]
            idx += 1
            seen += 1
            for nxt in rev.get(cur, set()):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    q.append(nxt)
        if seen != len(step_by_id):
            await _mark_failure("cycle detected in DAG")
            raise ApplicationError("cycle detected in DAG", non_retryable=True)

        # §3.6.2 Re-run minimize redo scope: if this is a re-run, skip already-completed steps.
        # The plan carries a "rerun_job_id" field referencing the previous Job; the activity
        # annotates steps with _skip_rerun=True for those whose prior outputs are still valid.
        rerun_job_id = str(plan.get("rerun_job_id") or "").strip()
        if rerun_job_id:
            try:
                plan = await workflow.execute_activity(
                    "activity_minimize_redo_scope",
                    args=[rerun_job_id, plan],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                # Rebuild step_list and maps since plan steps may have been annotated
                steps = plan.get("steps") or steps
                step_list = [{**st, "id": self._step_id(st, i)} for i, st in enumerate(steps)]
                step_by_id = {st["id"]: st for st in step_list}
                id_list = [st["id"] for st in step_list]
            except Exception as exc:
                workflow.logger.warning(
                    "minimize_redo_scope failed for rerun_job_id %s: %s", rerun_job_id, exc,
                )

        # Pre-skip steps annotated by minimize_redo_scope (_skip_rerun=True)
        pre_skipped: set[str] = {
            st["id"] for st in step_list if st.get("_skip_rerun")
        }

        # Mark job as running
        await self._mark_job_status(job_id, "running", "executing")

        # DAG execution loop
        results_by_id: dict[str, dict] = {}
        # Pre-populate results for skipped steps so downstream dependents can proceed
        for sid in pre_skipped:
            results_by_id[sid] = {
                "status": "skipped",
                "step_id": sid,
                "skipped_reason": "prior run completed — minimize redo scope §3.6.2",
            }
        running: dict[str, workflow.ActivityHandle] = {}
        completed: set[str] = set(pre_skipped)
        errors: list[dict] = []
        pending = set(step_by_id.keys()) - pre_skipped
        pause_state_marked = False

        try:
            while pending or running:
                # Handle pause
                if self._pause_requested and not running:
                    if not pause_state_marked:
                        await self._mark_job_status(job_id, "running", "paused")
                        pause_state_marked = True
                    await workflow.wait_condition(lambda: not self._pause_requested)
                    if pause_state_marked:
                        await self._mark_job_status(job_id, "running", "executing")
                    pause_state_marked = False
                    continue

                # Start ready steps up to concurrency limits
                made_progress = True
                while (
                    not self._pause_requested
                    and made_progress
                    and pending
                    and len(running) < max_parallel
                ):
                    made_progress = False
                    ready = [
                        sid
                        for sid in sorted(pending)
                        if deps.get(sid, set()).issubset(completed)
                    ]
                    if not ready:
                        break

                    for sid in ready:
                        if self._pause_requested or len(running) >= max_parallel:
                            break
                        # Inject upstream results into plan for context
                        enriched_plan = {
                            **plan,
                            "_step_results": [
                                results_by_id[cid]
                                for cid in id_list
                                if cid in results_by_id
                            ],
                        }
                        pending.discard(sid)
                        running[sid] = self._start_step(
                            sid, step_by_id[sid], job_id, enriched_plan
                        )
                        made_progress = True

                if not running:
                    raise ApplicationError(
                        "deadlock: no runnable steps", non_retryable=True
                    )

                done, _ = await workflow.wait(
                    list(running.values()), return_when="FIRST_COMPLETED"
                )
                done_ids = [sid for sid, h in list(running.items()) if h in done]
                for sid in done_ids:
                    h = running.pop(sid)
                    try:
                        res = await h
                        if not isinstance(res, dict):
                            res = {
                                "status": "error",
                                "step_id": sid,
                                "error": "invalid_result",
                            }
                    except Exception as e:
                        res = {
                            "status": "error",
                            "step_id": sid,
                            "error": str(e)[:400],
                        }
                        # ── §3.8 L1 failure judgment after retry exhaustion ──
                        step_info = step_by_id.get(sid, {})
                        try:
                            judgment = await workflow.execute_activity(
                                "activity_l1_failure_judgment",
                                args=[job_id, step_info, str(e)[:300]],
                                start_to_close_timeout=timedelta(seconds=45),
                                retry_policy=RetryPolicy(maximum_attempts=1),
                            )
                            decision = str(judgment.get("decision") or "terminate").lower()
                            workflow.logger.info(
                                "L1 failure judgment for step %s: %s (reason: %s)",
                                sid, decision, judgment.get("reason", ""),
                            )
                        except Exception as jexc:
                            workflow.logger.warning(
                                "L1 failure judgment call failed for step %s: %s", sid, jexc,
                            )
                            decision = "terminate"

                        if decision == "skip":
                            res["status"] = "skipped"
                            res["skipped_reason"] = "L1 judgment: skip"
                            results_by_id[sid] = res
                            completed.add(sid)
                            continue
                        elif decision == "replace":
                            # Replace requested: mark failed with flag for replan gate
                            res["status"] = "failed"
                            res["replace_requested"] = True
                            errors.append(res)
                        else:
                            # terminate
                            errors.append(res)

                    # Check if activity returned a failure result (non-exception path)
                    if isinstance(res, dict) and res.get("status") in ("failed", "error"):
                        if res not in errors:
                            errors.append(res)

                    # ── §3.8.1 Reviewer trigger (3 tiers) ──────────────────
                    # Tier 1: NeMo output rail applied in activity (no workflow action needed).
                    # Tier 2/3: step result has requires_review=True (set by _apply_reviewer_trigger).
                    # Pause and wait for human confirmation.
                    #
                    # §10.34 compliance note: requires_review is NON-BLOCKING for the user.
                    # Temporal signals (confirmation_received / confirmation_rejected) are
                    # delivered asynchronously from the user's conversation, so the user can
                    # continue interacting with daemon while this workflow step awaits.
                    # Only the *workflow execution* is paused; the user's session is unaffected.
                    if (
                        isinstance(res, dict)
                        and res.get("status") == "completed"
                        and res.get("requires_review")
                    ):
                        review_tier = str(res.get("review_tier") or "flagged")
                        workflow.logger.info(
                            "Reviewer triggered for step %s (tier=%s)", sid, review_tier,
                        )
                        await self._mark_job_status(job_id, "running", "paused")
                        self._confirmation_result = None
                        confirm_timeout = int(
                            step_by_id.get(sid, {}).get("confirmation_timeout_s")
                            or plan.get("confirmation_timeout_s")
                            or 86400  # 24h default
                        )
                        try:
                            await workflow.wait_condition(
                                lambda: self._confirmation_result is not None,
                                timeout=timedelta(seconds=confirm_timeout),
                            )
                        except asyncio.TimeoutError:
                            pass

                        if self._confirmation_result and self._confirmation_result.get("confirmed"):
                            await self._mark_job_status(job_id, "running", "executing")
                        else:
                            reason = "timeout" if not self._confirmation_result else "rejected"
                            res = {
                                "status": "failed",
                                "step_id": sid,
                                "step_index": res.get("step_index", 0),
                                "agent_id": res.get("agent_id", ""),
                                "error": f"Reviewer {reason} for step {sid} (tier={review_tier})",
                            }
                            errors.append(res)
                            await self._mark_job_status(job_id, "running", "executing")

                    # ── plan-level requires_review: wait for confirmation (§3.5, D.2) ──
                    # Only triggered if the step plan has requires_review=True but the
                    # reviewer-tier check above did NOT already handle it.
                    # §10.34 compliance note: same as above — the Temporal signal
                    # mechanism means the user's conversation is non-blocking; only
                    # the workflow execution step is paused awaiting their signal.
                    st = step_by_id.get(sid, {})
                    if (
                        st.get("requires_review")
                        and not res.get("requires_review")
                        and isinstance(res, dict)
                        and res.get("status") == "completed"
                    ):
                        await self._mark_job_status(job_id, "running", "paused")
                        self._confirmation_result = None
                        confirm_timeout = int(
                            st.get("confirmation_timeout_s")
                            or plan.get("confirmation_timeout_s")
                            or 86400  # 24h default
                        )
                        try:
                            await workflow.wait_condition(
                                lambda: self._confirmation_result is not None,
                                timeout=timedelta(seconds=confirm_timeout),
                            )
                        except asyncio.TimeoutError:
                            pass

                        if self._confirmation_result and self._confirmation_result.get("confirmed"):
                            await self._mark_job_status(job_id, "running", "executing")
                        else:
                            reason = "timeout" if not self._confirmation_result else "rejected"
                            res = {
                                "status": "failed",
                                "step_id": sid,
                                "step_index": res.get("step_index", 0),
                                "agent_id": res.get("agent_id", ""),
                                "error": f"Confirmation {reason} for step {sid}",
                            }
                            errors.append(res)
                            await self._mark_job_status(job_id, "running", "executing")

                    results_by_id[sid] = res
                    completed.add(sid)

        except asyncio.CancelledError:
            await self._mark_job_status(job_id, "closed", "cancelled")
            raise
        except ApplicationError:
            if errors:
                await _mark_failure(str(errors[0]["error"])[:200])
            raise
        except Exception as e:
            await _mark_failure(str(e)[:200])
            raise ApplicationError(
                f"workflow_exception: {str(e)[:200]}", non_retryable=True
            ) from e

        # Collect ordered results
        ordered: list[dict] = [
            results_by_id.get(sid)
            or {"status": "error", "step_id": sid, "error": "missing_result"}
            for sid in id_list
        ]

        if errors:
            await _mark_failure(f"{len(errors)} step(s) failed")
            await self._plane_writeback(job_id, "failed")
            raise ApplicationError(
                f"{len(errors)} step(s) failed", non_retryable=True
            )

        # Job completed successfully
        await self._mark_job_status(job_id, "closed", "completed")

        job_result = {
            "ok": True,
            "job_id": job_id,
            "step_results": ordered,
            "completed_utc": workflow.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        # ── Plane writeback (§6.6, D.5) ─────────────────────────────
        await self._plane_writeback(job_id, "completed")

        # ── Post-Job learning (§8.1-8.2) ─────────────────────────────
        try:
            await workflow.execute_activity(
                "activity_post_job_learn",
                args=[job_id, job_result],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception as exc:
            workflow.logger.warning(
                "Post-Job learning failed for job %s: %s", job_id, exc,
            )

        # ── Persona taste update (§5.4) ───────────────────────────────
        try:
            await workflow.execute_activity(
                "activity_persona_taste_update",
                args=[job_id, job_result],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            workflow.logger.warning(
                "Persona taste update failed for job %s: %s", job_id, exc,
            )

        # ── Replan Gate + Chain Trigger (§3.9, §3.10) ────────────────
        try:
            gate_result = await workflow.execute_activity(
                "activity_replan_gate",
                args=[job_id, job_result],
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            action = gate_result.get("action", "continue")

            if action == "continue":
                # Trigger downstream chain Tasks
                await self._trigger_chain(job_id)
            elif action == "replan":
                workflow.logger.info(
                    "Replan gate: replanning for job %s — %s",
                    job_id, gate_result.get("reason", ""),
                )
                # Replan diff applied by the activity; chain continues from new plan
                await self._trigger_chain(job_id)
        except Exception as exc:
            workflow.logger.warning("Replan gate failed for job %s: %s", job_id, exc)
            # On gate failure, still trigger chain (fail-open)
            await self._trigger_chain(job_id)

        return job_result

    # -- Helpers -------------------------------------------------------------------

    def _step_id(self, st: dict, index: int) -> str:
        return str(
            st.get("id") or st.get("step_id") or f"step_{index}"
        ).strip()

    def _deps(self, st: dict) -> list[str]:
        d = st.get("depends_on") or st.get("dependencies") or []
        return [str(x) for x in d] if isinstance(d, list) else []

    def _agent(self, st: dict) -> str:
        return str(st.get("agent_id") or st.get("agent") or "").strip()

    def _start_step(
        self, sid: str, st: dict, job_id: str, plan: dict
    ) -> workflow.ActivityHandle:
        execution_type = str(st.get("execution_type") or "agent").strip()
        st_to, sc_to = self._timeouts(plan, st)
        max_attempts = int(plan.get("retry_max_attempts") or 3)
        retry = RetryPolicy(maximum_attempts=max_attempts)

        if execution_type == "direct":
            return workflow.start_activity(
                "activity_direct_step",
                args=[job_id, plan, st],
                start_to_close_timeout=st_to,
                schedule_to_close_timeout=sc_to,
                retry_policy=retry,
            )

        if execution_type in ("claude_code", "codex"):
            return workflow.start_activity(
                "activity_cc_step",
                args=[job_id, plan, st],
                start_to_close_timeout=st_to,
                schedule_to_close_timeout=sc_to,
                heartbeat_timeout=timedelta(seconds=90),
                retry_policy=retry,
            )

        return workflow.start_activity(
            "activity_execute_step",
            args=[job_id, plan, st],
            start_to_close_timeout=st_to,
            schedule_to_close_timeout=sc_to,
            heartbeat_timeout=timedelta(seconds=90),
            retry_policy=retry,
        )

    # Per-type step timeouts (§3.4, Appendix B.1)
    _STEP_TYPE_TIMEOUTS: dict[str, int] = {
        "search": 60,
        "writing": 180,
        "review": 90,
    }
    _DEFAULT_STEP_TIMEOUT: int = 120

    def _timeouts(self, plan: dict, st: dict) -> tuple[timedelta, timedelta]:
        step_override = int(st.get("timeout_s") or 0)
        if step_override:
            start_to_close_s = step_override
        else:
            # Per-type timeout (§3.4, Appendix B.1)
            step_type = str(st.get("type") or st.get("step_type") or "").lower()
            if step_type in self._STEP_TYPE_TIMEOUTS:
                start_to_close_s = self._STEP_TYPE_TIMEOUTS[step_type]
            elif plan.get("default_step_timeout_s"):
                start_to_close_s = int(plan["default_step_timeout_s"])
            else:
                start_to_close_s = self._DEFAULT_STEP_TIMEOUT
        return (
            timedelta(seconds=start_to_close_s),
            timedelta(seconds=start_to_close_s + 30),
        )

    async def _plane_writeback(
        self, job_id: str, sub_status: str,
    ) -> None:
        """Write Job status back to Plane Issue (§6.6, D.5)."""
        try:
            await workflow.execute_activity(
                "activity_plane_writeback",
                args=[job_id, sub_status],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=RetryPolicy(
                    maximum_attempts=5,
                    initial_interval=timedelta(seconds=2),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=60),
                ),
            )
        except Exception as exc:
            workflow.logger.warning(
                "Plane writeback failed for job %s (will be compensated): %s",
                job_id, exc,
            )

    async def _trigger_chain(self, job_id: str) -> None:
        """Trigger downstream chain Tasks after successful Job close (§3.10)."""
        try:
            await workflow.execute_activity(
                "activity_trigger_chain",
                args=[job_id],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception as exc:
            workflow.logger.warning(
                "Chain trigger failed for job %s: %s", job_id, exc,
            )

    async def _mark_job_status(
        self,
        job_id: str,
        status: str,
        sub_status: str,
        error: str = "",
    ) -> None:
        try:
            await workflow.execute_activity(
                "activity_update_job_status",
                args=[job_id, status, sub_status, error],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            workflow.logger.warning(
                "Failed to update job status for %s: %s", job_id, exc
            )


# ══════════════════════════════════════════════════════════════════════════
# HealthCheckWorkflow — Weekly system health check (§7.7)
# ══════════════════════════════════════════════════════════════════════════


@workflow.defn(name="HealthCheckWorkflow")
class HealthCheckWorkflow:
    """Weekly automated health check.

    3-layer detection:
      1. Infrastructure: 17 data link verification (scripts/verify.py)
      2. Quality: baseline task suite (admin evaluates)
      3. Frontier scan: researcher checks for improvements

    Results → state/health_reports/YYYY-MM-DD.json
    Status → GREEN/YELLOW/RED → Telegram notification
    """

    @workflow.run
    async def run(self, config: dict | None = None) -> dict:
        config = config or {}

        # Activity 1: Infrastructure check (runs scripts/verify.py --links)
        infra_result = await workflow.execute_activity(
            "activity_health_check_infrastructure",
            args=[],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # Activity 2: Quality baseline check (admin-driven)
        quality_result = await workflow.execute_activity(
            "activity_health_check_quality",
            args=[infra_result],
            start_to_close_timeout=timedelta(hours=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        # Activity 3: Frontier scan (researcher-driven)
        frontier_result = await workflow.execute_activity(
            "activity_health_check_frontier",
            args=[quality_result],
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        # Activity 4: Generate report + notify
        report = await workflow.execute_activity(
            "activity_health_report",
            args=[infra_result, quality_result, frontier_result],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        return report


# ══════════════════════════════════════════════════════════════════════════
# SelfHealWorkflow — 4-activity self-healing (§7.8)
# ══════════════════════════════════════════════════════════════════════════


@workflow.defn(name="SelfHealWorkflow")
class SelfHealWorkflow:
    """Self-healing workflow: 4 activities, crash-safe.

    Activity 1: admin generates issue file (state/issues/YYYY-MM-DD-HHMM.md)
    Activity 2: CC/Codex reads issue → applies fix (only files/config)
    Activity 3: scripts/start.py (restart, may kill Worker → Temporal retries)
    Activity 4: scripts/verify.py --issue ID (verify + Telegram notify)

    Reference: SYSTEM_DESIGN.md §7.8
    """

    @workflow.run
    async def run(self, trigger: dict) -> dict:
        issue_id = trigger.get("issue_id", "")

        # Activity 1: Generate issue file
        if not issue_id:
            issue_result = await workflow.execute_activity(
                "activity_self_heal_diagnose",
                args=[trigger],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            issue_id = issue_result.get("issue_id", "")

        if not issue_id:
            return {"ok": False, "error": "failed_to_generate_issue"}

        # Activity 2: Apply fix (CC/Codex reads issue file, applies changes)
        fix_result = await workflow.execute_activity(
            "activity_self_heal_fix",
            args=[issue_id],
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if not fix_result.get("ok"):
            # Layer 3: notify user
            await workflow.execute_activity(
                "activity_self_heal_notify_failure",
                args=[issue_id, fix_result],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return {"ok": False, "issue_id": issue_id, "layer": 3, "error": "fix_failed"}

        # Activity 3: Restart services (may crash Worker — Temporal recovers)
        restart_result = await workflow.execute_activity(
            "activity_self_heal_restart",
            args=[],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=10),
            ),
        )

        # Activity 4: Verify fix
        verify_result = await workflow.execute_activity(
            "activity_self_heal_verify",
            args=[issue_id],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if verify_result.get("overall") == "GREEN":
            return {"ok": True, "issue_id": issue_id, "layer": 2}
        else:
            # Layer 3 fallback
            await workflow.execute_activity(
                "activity_self_heal_notify_failure",
                args=[issue_id, verify_result],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return {"ok": False, "issue_id": issue_id, "layer": 3, "error": "verify_failed"}


# ══════════════════════════════════════════════════════════════════════════
# MaintenanceWorkflow — Periodic cleanup (every 6h)
# ══════════════════════════════════════════════════════════════════════════


@workflow.defn(name="MaintenanceWorkflow")
class MaintenanceWorkflow:
    """Wraps the single maintenance activity for Temporal Schedule."""

    @workflow.run
    async def run(self, config: dict | None = None) -> dict:
        return await workflow.execute_activity(
            "activity_maintenance",
            args=[],
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


# ══════════════════════════════════════════════════════════════════════════
# BackupWorkflow — Daily incremental backup
# ══════════════════════════════════════════════════════════════════════════


@workflow.defn(name="BackupWorkflow")
class BackupWorkflow:
    """Daily incremental backup of PG + MinIO."""

    @workflow.run
    async def run(self, config: dict | None = None) -> dict:
        return await workflow.execute_activity(
            "activity_backup",
            args=[config or {}],
            start_to_close_timeout=timedelta(minutes=60),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
