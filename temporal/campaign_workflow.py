"""CampaignWorkflow — multi-milestone orchestration for task_scale=campaign."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


@dataclass
class CampaignInput:
    plan: dict
    run_root: str
    task_id: str = ""


@workflow.defn(name="CampaignWorkflow")
class CampaignWorkflow:
    """Runs campaign milestones with objective rework loops and state snapshots."""

    @workflow.run
    async def run(self, inp: CampaignInput) -> dict:
        plan = inp.plan or {}
        run_root = inp.run_root

        bootstrap = await workflow.execute_activity(
            "activity_campaign_bootstrap",
            args=[run_root, plan],
            start_to_close_timeout=timedelta(seconds=30),
            schedule_to_close_timeout=timedelta(seconds=45),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        campaign_id = str(bootstrap.get("campaign_id") or plan.get("campaign_id") or "")
        milestones = bootstrap.get("milestones") if isinstance(bootstrap.get("milestones"), list) else []
        start_idx = int(bootstrap.get("next_milestone_index") or 0)
        if not milestones:
            await self._mark_task_status(run_root, plan, "failed", "campaign_milestones_missing")
            raise ApplicationError("campaign_milestones_missing", non_retryable=True)

        # Phase0 gate: campaign must be explicitly confirmed before execution.
        confirmed = bool(plan.get("campaign_confirmed"))
        if not confirmed:
            await workflow.execute_activity(
                "activity_campaign_set_status",
                args=[
                    campaign_id,
                    "paused",
                    "phase0_waiting_confirmation",
                    {"current_milestone_index": start_idx, "confirmation_required": True},
                ],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            await self._mark_task_status(run_root, plan, "paused", "campaign_waiting_user_confirmation")
            return {
                "ok": False,
                "campaign_id": campaign_id,
                "status": "paused",
                "wait_type": "phase0_confirmation_required",
                "current_milestone_index": start_idx,
            }

        await workflow.execute_activity(
            "activity_campaign_set_status",
            args=[campaign_id, "running", "phase1_execute", {"current_milestone_index": start_idx}],
            start_to_close_timeout=timedelta(seconds=20),
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        historical = bootstrap.get("historical_step_results") if isinstance(bootstrap.get("historical_step_results"), list) else []
        all_step_results: list[dict] = [r for r in historical if isinstance(r, dict)]
        for idx in range(start_idx, len(milestones)):
            milestone = milestones[idx] if isinstance(milestones[idx], dict) else {}
            milestone_id = str(milestone.get("milestone_id") or f"m{idx + 1:02d}")
            steps = milestone.get("steps") if isinstance(milestone.get("steps"), list) else []
            if not steps:
                await workflow.execute_activity(
                    "activity_campaign_record_milestone",
                    args=[
                        campaign_id,
                        idx,
                        {
                            "milestone_id": milestone_id,
                            "title": str(milestone.get("title") or ""),
                            "status": "skipped",
                            "objective_pass": True,
                            "objective_score": 1.0,
                            "attempts": 0,
                            "step_results": [],
                        },
                    ],
                    start_to_close_timeout=timedelta(seconds=20),
                    schedule_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                continue

            max_rework = int(milestone.get("objective_rework_budget") or plan.get("campaign_objective_rework_budget") or 2)
            feedback_idx = int(plan.get("campaign_feedback_milestone_index") or -1)
            feedback_satisfied = plan.get("campaign_feedback_satisfied")
            feedback_hint = str(plan.get("campaign_feedback_comment") or "").strip()
            user_forced_rework = bool(plan.get("campaign_force_user_rework")) and feedback_idx == idx and feedback_satisfied is False
            if user_forced_rework:
                max_rework = min(max_rework, 1)
                if feedback_hint:
                    steps = [self._with_user_hint(st, feedback_hint, milestone_id) for st in steps]
            attempts = 0
            objective_pass = False
            last_attempt_results: list[dict] = []

            await workflow.execute_activity(
                "activity_campaign_set_status",
                args=[
                    campaign_id,
                    "running",
                    "milestone_running",
                    {"current_milestone_index": idx, "milestone_id": milestone_id},
                ],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            while attempts <= max_rework and not objective_pass:
                attempts += 1
                attempt_results: list[dict] = []
                for step in steps:
                    st = step if isinstance(step, dict) else {}
                    step_id = str(st.get("id") or f"ms{idx + 1}_step")
                    st_to, sc_to = self._timeouts(plan, st)
                    res = await workflow.execute_activity(
                        "activity_openclaw_step",
                        args=[run_root, plan, st],
                        start_to_close_timeout=st_to,
                        schedule_to_close_timeout=sc_to,
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                    if not isinstance(res, dict):
                        res = {"status": "error", "step_id": step_id, "error": "invalid_step_result"}
                    attempt_results.append(res)
                    all_step_results.append(res)
                    if str(res.get("status") or "") == "error":
                        break

                last_attempt_results = attempt_results
                objective_pass = all(str(r.get("status") or "") in {"ok", "degraded"} for r in attempt_results)

            objective_score = self._objective_score(last_attempt_results)
            await workflow.execute_activity(
                "activity_campaign_record_milestone",
                args=[
                    campaign_id,
                    idx,
                    {
                        "milestone_id": milestone_id,
                        "title": str(milestone.get("title") or f"Milestone {idx + 1}"),
                        "status": "passed" if objective_pass else "failed",
                        "objective_pass": objective_pass,
                        "objective_score": objective_score,
                        "attempts": attempts,
                        "objective_rework_budget": max_rework,
                        "step_results": last_attempt_results,
                        "expected_output": str(milestone.get("expected_output") or ""),
                    },
                ],
                start_to_close_timeout=timedelta(seconds=30),
                schedule_to_close_timeout=timedelta(seconds=45),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            if not objective_pass:
                await workflow.execute_activity(
                    "activity_campaign_set_status",
                    args=[
                        campaign_id,
                        "paused",
                        "milestone_failed",
                        {
                            "current_milestone_index": idx,
                            "milestone_id": milestone_id,
                            "reason": "objective_rework_exhausted",
                        },
                    ],
                    start_to_close_timeout=timedelta(seconds=20),
                    schedule_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                await self._mark_task_status(run_root, plan, "paused", f"campaign_milestone_failed:{milestone_id}")
                return {
                    "ok": False,
                    "campaign_id": campaign_id,
                    "status": "paused",
                    "failed_milestone": milestone_id,
                    "milestone_index": idx,
                }

            # Milestone finished; require explicit user feedback before next milestone.
            await workflow.execute_activity(
                "activity_campaign_set_status",
                args=[
                    campaign_id,
                    "paused",
                    "milestone_waiting_feedback",
                    {
                        "current_milestone_index": idx,
                        "milestone_id": milestone_id,
                        "next_milestone_index": idx + 1,
                        "feedback_required": True,
                    },
                ],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            await self._mark_task_status(run_root, plan, "paused", f"campaign_waiting_feedback:{milestone_id}")
            return {
                "ok": False,
                "campaign_id": campaign_id,
                "status": "paused",
                "wait_type": "milestone_feedback_required",
                "milestone_id": milestone_id,
                "milestone_index": idx,
                "next_milestone_index": idx + 1,
            }

        await workflow.execute_activity(
            "activity_campaign_set_status",
            args=[campaign_id, "running", "phase_n_plus_1_synthesis", {"current_milestone_index": len(milestones)}],
            start_to_close_timeout=timedelta(seconds=20),
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        delivery = await workflow.execute_activity(
            "activity_finalize_delivery",
            args=[run_root, plan, all_step_results],
            start_to_close_timeout=timedelta(minutes=6),
            schedule_to_close_timeout=timedelta(minutes=8),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        if isinstance(delivery, dict) and delivery.get("ok"):
            await workflow.execute_activity(
                "activity_campaign_set_status",
                args=[campaign_id, "completed", "finished", {"delivery": delivery}],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            await self._mark_task_status(run_root, plan, "completed", "")
            return {"ok": True, "campaign_id": campaign_id, "status": "completed", "delivery": delivery}

        error_code = str((delivery or {}).get("error_code") or "campaign_delivery_failed")
        await workflow.execute_activity(
            "activity_campaign_set_status",
            args=[campaign_id, "failed", "delivery_failed", {"delivery": delivery, "error_code": error_code}],
            start_to_close_timeout=timedelta(seconds=20),
            schedule_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        await self._mark_task_status(run_root, plan, "failed", error_code[:200])
        return {
            "ok": False,
            "campaign_id": campaign_id,
            "status": "failed",
            "error_code": error_code,
            "delivery": delivery,
        }

    def _timeouts(self, plan: dict, st: dict) -> tuple[timedelta, timedelta]:
        hints: dict = plan.get("timeout_hints") or {}
        agent = str(st.get("agent") or "").strip()
        step_override = int(st.get("timeout_s") or 0)
        agent_hint = int(hints.get(agent) or 0)
        default = int(plan.get("default_step_timeout_s") or 480)
        start_to_close_s = step_override or agent_hint or default
        return timedelta(seconds=start_to_close_s), timedelta(seconds=start_to_close_s + 30)

    def _objective_score(self, step_results: list[dict]) -> float:
        if not step_results:
            return 1.0
        total = len(step_results)
        ok = sum(1 for r in step_results if str(r.get("status") or "") in {"ok", "degraded"})
        return round(ok / max(total, 1), 4)

    def _with_user_hint(self, step: dict, hint: str, milestone_id: str) -> dict:
        out = dict(step or {})
        base = str(out.get("instruction") or out.get("message") or "").strip()
        out["instruction"] = (
            f"{base}\n\n"
            f"User rework hint for milestone {milestone_id}:\n"
            f"{hint}\n\n"
            "Address this feedback directly while preserving objective quality gate requirements."
        ).strip()
        return out

    async def _mark_task_status(self, run_root: str, plan: dict, status: str, error: str) -> None:
        try:
            await workflow.execute_activity(
                "activity_update_task_status",
                args=[run_root, {**plan, "last_error": error}, status],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            workflow.logger.warning("Failed to update task status for campaign run %s: %s", run_root, exc)
