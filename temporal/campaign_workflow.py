"""CampaignWorkflow — multi-milestone orchestration for work_scale=campaign."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


@dataclass
class CampaignInput:
    plan: dict
    run_root: str
    run_id: str = ""


@workflow.defn(name="CampaignWorkflow")
class CampaignWorkflow:
    """Runs campaign milestones with child workflow execution and recoverable gates."""

    def __init__(self) -> None:
        self._pending_requirements: list[str] = []

    @workflow.signal(name="append_requirement")
    def append_requirement(self, payload: dict | None = None) -> None:
        row = payload if isinstance(payload, dict) else {}
        text = str(row.get("text") or row.get("requirement") or "").strip()
        if not text:
            return
        self._pending_requirements.append(text)
        if len(self._pending_requirements) > 20:
            self._pending_requirements = self._pending_requirements[-20:]

    @workflow.run
    async def run(self, inp: CampaignInput) -> dict:
        plan = inp.plan or {}
        run_root = inp.run_root
        campaign_id = str(plan.get("campaign_id") or "")
        try:
            bootstrap = await workflow.execute_activity(
                "activity_campaign_bootstrap",
                args=[run_root, plan],
                start_to_close_timeout=timedelta(seconds=30),
                schedule_to_close_timeout=timedelta(seconds=45),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            campaign_id = str(bootstrap.get("campaign_id") or campaign_id or plan.get("campaign_id") or "")
            milestones = bootstrap.get("milestones") if isinstance(bootstrap.get("milestones"), list) else []
            start_idx = int(bootstrap.get("next_milestone_index") or 0)
            campaign_context = (
                bootstrap.get("campaign_context")
                if isinstance(bootstrap.get("campaign_context"), list)
                else []
            )
            if not milestones:
                await self._mark_run_status(run_root, plan, "failed", "campaign_milestones_missing")
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
                        {"current_milestone_index": start_idx, "confirmation_required": True, "campaign_context": campaign_context},
                    ],
                    start_to_close_timeout=timedelta(seconds=20),
                    schedule_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                await self._mark_run_status(run_root, plan, "paused", "campaign_waiting_user_confirmation")
                return {
                    "ok": False,
                    "campaign_id": campaign_id,
                    "campaign_status": "paused",
                    "wait_type": "phase0_confirmation_required",
                    "current_milestone_index": start_idx,
                }

            await workflow.execute_activity(
                "activity_campaign_set_status",
                args=[
                    campaign_id,
                    "running",
                    "phase1_execute",
                    {"current_milestone_index": start_idx, "campaign_context": campaign_context},
                ],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            historical = (
                bootstrap.get("historical_step_results")
                if isinstance(bootstrap.get("historical_step_results"), list)
                else []
            )
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
                                "milestone_status": "skipped",
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

                max_rework = int(
                    milestone.get("objective_rework_budget")
                    or plan.get("campaign_objective_rework_budget")
                    or 2
                )
                feedback_idx = int(plan.get("campaign_feedback_milestone_index") or -1)
                feedback_satisfied = plan.get("campaign_feedback_satisfied")
                feedback_hint = str(plan.get("campaign_feedback_comment") or "").strip()
                user_forced_rework = (
                    bool(plan.get("campaign_force_user_rework"))
                    and feedback_idx == idx
                    and feedback_satisfied is False
                )
                if user_forced_rework:
                    max_rework = min(max_rework, 1)
                    if feedback_hint:
                        steps = [self._with_user_hint(st, feedback_hint, milestone_id) for st in steps]

                attempts = 0
                objective_pass = False
                last_attempt_results: list[dict] = []
                child_workflow_id = ""

                while attempts <= max_rework and not objective_pass:
                    attempts += 1
                    if attempts == 1:
                        child_workflow_id = f"daemon-campaign-{campaign_id}-m{idx + 1}"
                    else:
                        child_workflow_id = f"daemon-campaign-{campaign_id}-m{idx + 1}-r{attempts}"
                    child_run_root = f"{run_root}/milestones/{idx + 1}/attempt_{attempts}"
                    child_plan = self._build_child_plan(
                        base_plan=plan,
                        milestone=milestone,
                        campaign_context=campaign_context,
                        milestone_index=idx,
                        attempt=attempts,
                    )

                    await workflow.execute_activity(
                        "activity_campaign_set_status",
                        args=[
                            campaign_id,
                            "running",
                            "milestone_running",
                            {
                                "current_milestone_index": idx,
                                "milestone_id": milestone_id,
                                "current_child_workflow_id": child_workflow_id,
                                "campaign_context": campaign_context,
                            },
                        ],
                        start_to_close_timeout=timedelta(seconds=20),
                        schedule_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

                    try:
                        child_result = await workflow.execute_child_workflow(
                            "GraphDispatchWorkflow",
                            {"plan": child_plan, "run_root": child_run_root, "run_id": child_plan.get("run_id", "")},
                            id=child_workflow_id,
                            task_queue=workflow.info().task_queue,
                            retry_policy=RetryPolicy(maximum_attempts=1),
                        )
                    except Exception as exc:
                        child_result = {"ok": False, "error": str(exc)[:300], "step_results": []}

                    attempt_results = (
                        child_result.get("step_results")
                        if isinstance(child_result, dict) and isinstance(child_result.get("step_results"), list)
                        else []
                    )
                    if not attempt_results:
                        attempt_results = [
                            {
                                "status": "error",
                                "step_id": f"{milestone_id}_child",
                                "error": str((child_result or {}).get("error") or "child_workflow_failed"),
                            }
                        ]
                    last_attempt_results = attempt_results
                    all_step_results.extend(attempt_results)
                    objective_pass = all(str(r.get("status") or "") in {"ok", "degraded"} for r in attempt_results)

                objective_score = self._objective_score(last_attempt_results)
                context_entry = self._build_context_entry(
                    milestone_id=milestone_id,
                    title=str(milestone.get("title") or f"Milestone {idx + 1}"),
                    milestone_index=idx,
                    objective_score=objective_score,
                    step_results=last_attempt_results,
                )
                await workflow.execute_activity(
                    "activity_campaign_record_milestone",
                    args=[
                        campaign_id,
                        idx,
                        {
                            "milestone_id": milestone_id,
                            "title": str(milestone.get("title") or f"Milestone {idx + 1}"),
                            "milestone_status": "passed" if objective_pass else "failed",
                            "objective_pass": objective_pass,
                            "objective_score": objective_score,
                            "attempts": attempts,
                            "objective_rework_budget": max_rework,
                            "step_results": last_attempt_results,
                            "expected_output": str(milestone.get("expected_output") or ""),
                            "child_workflow_id": child_workflow_id,
                            "context_entry": context_entry,
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
                            "awaiting_intervention",
                            "milestone_failed",
                            {
                                "current_milestone_index": idx,
                                "milestone_id": milestone_id,
                                "reason": "objective_rework_exhausted",
                                "current_child_workflow_id": child_workflow_id,
                                "campaign_context": campaign_context,
                            },
                        ],
                        start_to_close_timeout=timedelta(seconds=20),
                        schedule_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                    await self._mark_run_status(run_root, plan, "paused", f"campaign_milestone_failed:{milestone_id}")
                    return {
                        "ok": False,
                        "campaign_id": campaign_id,
                        "campaign_status": "awaiting_intervention",
                        "failed_milestone": milestone_id,
                        "milestone_index": idx,
                    }

                campaign_context.append(context_entry)
                if len(campaign_context) > 32:
                    campaign_context = campaign_context[-32:]

                # Keep existing resume-based feedback gate behavior.
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
                            "campaign_context": campaign_context,
                        },
                    ],
                    start_to_close_timeout=timedelta(seconds=20),
                    schedule_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                await self._mark_run_status(run_root, plan, "paused", f"campaign_waiting_feedback:{milestone_id}")
                return {
                    "ok": False,
                    "campaign_id": campaign_id,
                    "campaign_status": "paused",
                    "wait_type": "milestone_feedback_required",
                    "milestone_id": milestone_id,
                    "milestone_index": idx,
                    "next_milestone_index": idx + 1,
                }

            await workflow.execute_activity(
                "activity_campaign_set_status",
                args=[
                    campaign_id,
                    "running",
                    "phase_n_plus_1_synthesis",
                    {"current_milestone_index": len(milestones), "campaign_context": campaign_context},
                ],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            delivery = await workflow.execute_activity(
                "activity_finalize_delivery",
                args=[run_root, {**plan, "campaign_context": campaign_context}, all_step_results],
                start_to_close_timeout=timedelta(minutes=6),
                schedule_to_close_timeout=timedelta(minutes=8),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            if isinstance(delivery, dict) and delivery.get("ok"):
                await workflow.execute_activity(
                    "activity_campaign_set_status",
                    args=[campaign_id, "completed", "finished", {"delivery": delivery, "campaign_context": campaign_context}],
                    start_to_close_timeout=timedelta(seconds=20),
                    schedule_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                await self._mark_run_status(run_root, plan, "completed", "")
                return {
                    "ok": True,
                    "campaign_id": campaign_id,
                    "campaign_status": "completed",
                    "delivery": delivery,
                }

            error_code = str((delivery or {}).get("error_code") or "campaign_delivery_failed")
            await workflow.execute_activity(
                "activity_campaign_set_status",
                args=[campaign_id, "failed", "delivery_failed", {"delivery": delivery, "error_code": error_code}],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            await self._mark_run_status(run_root, plan, "failed", error_code[:200])
            return {
                "ok": False,
                "campaign_id": campaign_id,
                "campaign_status": "failed",
                "error_code": error_code,
                "delivery": delivery,
            }
        except asyncio.CancelledError:
            if campaign_id:
                try:
                    await workflow.execute_activity(
                        "activity_campaign_set_status",
                        args=[campaign_id, "cancelled", "cancelled", {"reason": "cancelled_by_request"}],
                        start_to_close_timeout=timedelta(seconds=20),
                        schedule_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                except Exception:
                    pass
            await self._mark_run_status(run_root, plan, "cancelled", "cancelled_by_request")
            raise

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

    def _with_requirements(self, step: dict) -> dict:
        if not self._pending_requirements:
            return dict(step)
        out = dict(step or {})
        base = str(out.get("instruction") or out.get("message") or "").strip()
        req_lines = [f"{i + 1}. {v}" for i, v in enumerate(self._pending_requirements[-10:]) if str(v).strip()]
        if not req_lines:
            return out
        out["instruction"] = (
            f"{base}\n\n"
            "Additional campaign requirements received during execution:\n"
            + "\n".join(req_lines)
        ).strip()
        return out

    def _with_campaign_context(self, step: dict, campaign_context: list[dict]) -> dict:
        if not campaign_context:
            return dict(step)
        out = dict(step or {})
        base = str(out.get("instruction") or out.get("message") or "").strip()
        ctx_lines: list[str] = []
        for row in campaign_context[-5:]:
            if not isinstance(row, dict):
                continue
            mid = str(row.get("milestone_id") or "")
            title = str(row.get("title") or "")
            summary = str(row.get("summary") or "")
            if not summary:
                continue
            ctx_lines.append(f"- {mid} {title}: {summary}")
        if not ctx_lines:
            return out
        out["instruction"] = (
            f"{base}\n\n"
            "Campaign context from completed milestones:\n"
            + "\n".join(ctx_lines)
        ).strip()
        return out

    def _build_child_plan(
        self,
        *,
        base_plan: dict,
        milestone: dict,
        campaign_context: list[dict],
        milestone_index: int,
        attempt: int,
    ) -> dict:
        child_steps = []
        for st in (milestone.get("steps") or []):
            if not isinstance(st, dict):
                continue
            out = self._with_requirements(st)
            out = self._with_campaign_context(out, campaign_context)
            child_steps.append(out)
        child_plan = {
            **base_plan,
            "campaign_child": True,
            "steps": child_steps,
            "work_scale": "thread",
            "run_id": f"{str(base_plan.get('run_id') or 'run')}_m{milestone_index + 1:02d}_a{attempt}",
            "campaign_context": campaign_context,
            "campaign_milestone_id": str(milestone.get("milestone_id") or f"m{milestone_index + 1:02d}"),
        }
        return child_plan

    def _build_context_entry(
        self,
        *,
        milestone_id: str,
        title: str,
        milestone_index: int,
        objective_score: float,
        step_results: list[dict],
    ) -> dict:
        ok_steps = sum(1 for r in step_results if str(r.get("status") or "") in {"ok", "degraded"})
        total_steps = max(1, len(step_results))
        return {
            "milestone_id": milestone_id,
            "title": title,
            "milestone_index": int(milestone_index),
            "summary": f"{ok_steps}/{total_steps} steps passed; objective_score={objective_score}",
            "objective_score": objective_score,
            "completed_utc": workflow.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    async def _mark_run_status(self, run_root: str, plan: dict, run_status: str, error: str) -> None:
        try:
            await workflow.execute_activity(
                "activity_update_run_status",
                args=[run_root, {**plan, "last_error": error}, run_status],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            workflow.logger.warning("Failed to update run status for campaign run %s: %s", run_root, exc)
