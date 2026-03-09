"""EndeavorWorkflow — multi-passage orchestration for complexity=endeavor."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


@dataclass
class EndeavorInput:
    plan: dict
    deed_root: str
    deed_id: str = ""


@workflow.defn(name="EndeavorWorkflow")
class EndeavorWorkflow:
    """Runs endeavor passages with child workflow execution and recoverable wards."""

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
    async def run(self, inp: EndeavorInput) -> dict:
        plan = inp.plan or {}
        deed_root = inp.deed_root
        endeavor_id = str(plan.get("endeavor_id") or "")
        try:
            bootstrap = await workflow.execute_activity(
                "activity_endeavor_bootstrap",
                args=[deed_root, plan],
                start_to_close_timeout=timedelta(seconds=30),
                schedule_to_close_timeout=timedelta(seconds=45),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            endeavor_id = str(bootstrap.get("endeavor_id") or endeavor_id or plan.get("endeavor_id") or "")
            passages = bootstrap.get("passages") if isinstance(bootstrap.get("passages"), list) else []
            start_idx = int(bootstrap.get("next_passage_index") or 0)
            endeavor_context = (
                bootstrap.get("endeavor_context")
                if isinstance(bootstrap.get("endeavor_context"), list)
                else []
            )
            if not passages:
                await self._mark_deed_status(deed_root, plan, "failed", "endeavor_passages_missing")
                raise ApplicationError("endeavor_passages_missing", non_retryable=True)

            # Phase0 ward: endeavor must be explicitly confirmed before execution.
            confirmed = bool(plan.get("endeavor_confirmed"))
            if not confirmed:
                await workflow.execute_activity(
                    "activity_endeavor_set_status",
                    args=[
                        endeavor_id,
                        "paused",
                        "phase0_waiting_confirmation",
                        {"current_passage_index": start_idx, "confirmation_required": True, "endeavor_context": endeavor_context},
                    ],
                    start_to_close_timeout=timedelta(seconds=20),
                    schedule_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                await self._mark_deed_status(deed_root, plan, "paused", "endeavor_waiting_user_confirmation")
                return {
                    "ok": False,
                    "endeavor_id": endeavor_id,
                    "endeavor_status": "paused",
                    "wait_type": "phase0_confirmation_required",
                    "current_passage_index": start_idx,
                }

            await workflow.execute_activity(
                "activity_endeavor_set_status",
                args=[
                    endeavor_id,
                    "running",
                    "phase1_execute",
                    {"current_passage_index": start_idx, "endeavor_context": endeavor_context},
                ],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            historical = (
                bootstrap.get("historical_move_results")
                if isinstance(bootstrap.get("historical_move_results"), list)
                else []
            )
            all_move_results: list[dict] = [r for r in historical if isinstance(r, dict)]
            for idx in range(start_idx, len(passages)):
                passage = passages[idx] if isinstance(passages[idx], dict) else {}
                passage_id = str(passage.get("passage_id") or f"m{idx + 1:02d}")
                moves = passage.get("moves") if isinstance(passage.get("moves"), list) else []
                if not moves:
                    await workflow.execute_activity(
                        "activity_endeavor_record_passage",
                        args=[
                            endeavor_id,
                            idx,
                            {
                                "passage_id": passage_id,
                                "title": str(passage.get("title") or ""),
                                "passage_status": "skipped",
                                "objective_pass": True,
                                "objective_score": 1.0,
                                "attempts": 0,
                                "move_results": [],
                            },
                        ],
                        start_to_close_timeout=timedelta(seconds=20),
                        schedule_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                    continue

                max_rework = int(
                    passage.get("objective_rework_ration")
                    or plan.get("endeavor_objective_rework_ration")
                    or 2
                )
                feedback_idx = int(plan.get("endeavor_feedback_passage_index") or -1)
                feedback_satisfied = plan.get("endeavor_feedback_satisfied")
                feedback_hint = str(plan.get("endeavor_feedback_comment") or "").strip()
                user_forced_rework = (
                    bool(plan.get("endeavor_force_user_rework"))
                    and feedback_idx == idx
                    and feedback_satisfied is False
                )
                if user_forced_rework:
                    max_rework = min(max_rework, 1)
                    if feedback_hint:
                        moves = [self._with_user_hint(st, feedback_hint, passage_id) for st in moves]

                attempts = 0
                objective_pass = False
                last_attempt_results: list[dict] = []
                child_workflow_id = ""

                while attempts <= max_rework and not objective_pass:
                    attempts += 1
                    if attempts == 1:
                        child_workflow_id = f"daemon-endeavor-{endeavor_id}-m{idx + 1}"
                    else:
                        child_workflow_id = f"daemon-endeavor-{endeavor_id}-m{idx + 1}-r{attempts}"
                    child_deed_root = f"{deed_root}/passages/{idx + 1}/attempt_{attempts}"
                    child_plan = self._build_child_plan(
                        base_plan=plan,
                        passage=passage,
                        endeavor_context=endeavor_context,
                        passage_index=idx,
                        attempt=attempts,
                    )

                    await workflow.execute_activity(
                        "activity_endeavor_set_status",
                        args=[
                            endeavor_id,
                            "running",
                            "passage_running",
                            {
                                "current_passage_index": idx,
                                "passage_id": passage_id,
                                "current_child_workflow_id": child_workflow_id,
                                "endeavor_context": endeavor_context,
                            },
                        ],
                        start_to_close_timeout=timedelta(seconds=20),
                        schedule_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )

                    try:
                        child_result = await workflow.execute_child_workflow(
                            "GraphWillWorkflow",
                            {"plan": child_plan, "deed_root": child_deed_root, "deed_id": child_plan.get("deed_id", "")},
                            id=child_workflow_id,
                            task_queue=workflow.info().task_queue,
                            retry_policy=RetryPolicy(maximum_attempts=1),
                        )
                    except Exception as exc:
                        child_result = {"ok": False, "error": str(exc)[:300], "move_results": []}

                    attempt_results = (
                        child_result.get("move_results")
                        if isinstance(child_result, dict) and isinstance(child_result.get("move_results"), list)
                        else []
                    )
                    if not attempt_results:
                        attempt_results = [
                            {
                                "status": "error",
                                "move_id": f"{passage_id}_child",
                                "error": str((child_result or {}).get("error") or "child_workflow_failed"),
                            }
                        ]
                    last_attempt_results = attempt_results
                    all_move_results.extend(attempt_results)
                    objective_pass = all(str(r.get("status") or "") in {"ok", "degraded"} for r in attempt_results)

                objective_score = self._objective_score(last_attempt_results)
                context_entry = self._build_context_entry(
                    passage_id=passage_id,
                    title=str(passage.get("title") or f"Passage {idx + 1}"),
                    passage_index=idx,
                    objective_score=objective_score,
                    move_results=last_attempt_results,
                )
                await workflow.execute_activity(
                    "activity_endeavor_record_passage",
                    args=[
                        endeavor_id,
                        idx,
                        {
                            "passage_id": passage_id,
                            "title": str(passage.get("title") or f"Passage {idx + 1}"),
                            "passage_status": "passed" if objective_pass else "failed",
                            "objective_pass": objective_pass,
                            "objective_score": objective_score,
                            "attempts": attempts,
                            "objective_rework_ration": max_rework,
                            "move_results": last_attempt_results,
                            "expected_output": str(passage.get("expected_output") or ""),
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
                        "activity_endeavor_set_status",
                        args=[
                            endeavor_id,
                            "awaiting_intervention",
                            "passage_failed",
                            {
                                "current_passage_index": idx,
                                "passage_id": passage_id,
                                "reason": "objective_rework_exhausted",
                                "current_child_workflow_id": child_workflow_id,
                                "endeavor_context": endeavor_context,
                            },
                        ],
                        start_to_close_timeout=timedelta(seconds=20),
                        schedule_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                    await self._mark_deed_status(deed_root, plan, "paused", f"endeavor_passage_failed:{passage_id}")
                    return {
                        "ok": False,
                        "endeavor_id": endeavor_id,
                        "endeavor_status": "awaiting_intervention",
                        "failed_passage": passage_id,
                        "passage_index": idx,
                    }

                endeavor_context.append(context_entry)
                if len(endeavor_context) > 32:
                    endeavor_context = endeavor_context[-32:]

                # Keep existing resume-based feedback ward behavior.
                await workflow.execute_activity(
                    "activity_endeavor_set_status",
                    args=[
                        endeavor_id,
                        "paused",
                        "passage_waiting_feedback",
                        {
                            "current_passage_index": idx,
                            "passage_id": passage_id,
                            "next_passage_index": idx + 1,
                            "feedback_required": True,
                            "endeavor_context": endeavor_context,
                        },
                    ],
                    start_to_close_timeout=timedelta(seconds=20),
                    schedule_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                await self._mark_deed_status(deed_root, plan, "paused", f"endeavor_waiting_feedback:{passage_id}")
                return {
                    "ok": False,
                    "endeavor_id": endeavor_id,
                    "endeavor_status": "paused",
                    "wait_type": "passage_feedback_required",
                    "passage_id": passage_id,
                    "passage_index": idx,
                    "next_passage_index": idx + 1,
                }

            await workflow.execute_activity(
                "activity_endeavor_set_status",
                args=[
                    endeavor_id,
                    "running",
                    "phase_n_plus_1_synthesis",
                    {"current_passage_index": len(passages), "endeavor_context": endeavor_context},
                ],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            herald = await workflow.execute_activity(
                "activity_finalize_herald",
                args=[deed_root, {**plan, "endeavor_context": endeavor_context}, all_move_results],
                start_to_close_timeout=timedelta(minutes=6),
                schedule_to_close_timeout=timedelta(minutes=8),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )

            if isinstance(herald, dict) and herald.get("ok"):
                await workflow.execute_activity(
                    "activity_endeavor_set_status",
                    args=[endeavor_id, "completed", "finished", {"herald": herald, "endeavor_context": endeavor_context}],
                    start_to_close_timeout=timedelta(seconds=20),
                    schedule_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                await self._mark_deed_status(deed_root, plan, "completed", "")
                return {
                    "ok": True,
                    "endeavor_id": endeavor_id,
                    "endeavor_status": "completed",
                    "herald": herald,
                }

            error_code = str((herald or {}).get("error_code") or "endeavor_herald_failed")
            await workflow.execute_activity(
                "activity_endeavor_set_status",
                args=[endeavor_id, "failed", "herald_failed", {"herald": herald, "error_code": error_code}],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
            await self._mark_deed_status(deed_root, plan, "failed", error_code[:200])
            return {
                "ok": False,
                "endeavor_id": endeavor_id,
                "endeavor_status": "failed",
                "error_code": error_code,
                "herald": herald,
            }
        except asyncio.CancelledError:
            if endeavor_id:
                try:
                    await workflow.execute_activity(
                        "activity_endeavor_set_status",
                        args=[endeavor_id, "cancelled", "cancelled", {"reason": "cancelled_by_request"}],
                        start_to_close_timeout=timedelta(seconds=20),
                        schedule_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                except Exception:
                    pass
            await self._mark_deed_status(deed_root, plan, "cancelled", "cancelled_by_request")
            raise

    def _objective_score(self, move_results: list[dict]) -> float:
        if not move_results:
            return 1.0
        total = len(move_results)
        ok = sum(1 for r in move_results if str(r.get("status") or "") in {"ok", "degraded"})
        return round(ok / max(total, 1), 4)

    def _with_user_hint(self, move: dict, hint: str, passage_id: str) -> dict:
        out = dict(move or {})
        base = str(out.get("instruction") or out.get("message") or "").strip()
        out["instruction"] = (
            f"{base}\n\n"
            f"User rework hint for passage {passage_id}:\n"
            f"{hint}\n\n"
            "Address this feedback directly while preserving objective quality ward requirements."
        ).strip()
        return out

    def _with_requirements(self, move: dict) -> dict:
        if not self._pending_requirements:
            return dict(move)
        out = dict(move or {})
        base = str(out.get("instruction") or out.get("message") or "").strip()
        req_lines = [f"{i + 1}. {v}" for i, v in enumerate(self._pending_requirements[-10:]) if str(v).strip()]
        if not req_lines:
            return out
        out["instruction"] = (
            f"{base}\n\n"
            "Additional endeavor requirements received during execution:\n"
            + "\n".join(req_lines)
        ).strip()
        return out

    def _with_endeavor_context(self, move: dict, endeavor_context: list[dict]) -> dict:
        if not endeavor_context:
            return dict(move)
        out = dict(move or {})
        base = str(out.get("instruction") or out.get("message") or "").strip()
        ctx_lines: list[str] = []
        for row in endeavor_context[-5:]:
            if not isinstance(row, dict):
                continue
            mid = str(row.get("passage_id") or "")
            title = str(row.get("title") or "")
            summary = str(row.get("summary") or "")
            if not summary:
                continue
            ctx_lines.append(f"- {mid} {title}: {summary}")
        if not ctx_lines:
            return out
        out["instruction"] = (
            f"{base}\n\n"
            "Endeavor context from completed passages:\n"
            + "\n".join(ctx_lines)
        ).strip()
        return out

    def _build_child_plan(
        self,
        *,
        base_plan: dict,
        passage: dict,
        endeavor_context: list[dict],
        passage_index: int,
        attempt: int,
    ) -> dict:
        child_moves = []
        for st in (passage.get("moves") or []):
            if not isinstance(st, dict):
                continue
            out = self._with_requirements(st)
            out = self._with_endeavor_context(out, endeavor_context)
            child_moves.append(out)
        child_plan = {
            **base_plan,
            "endeavor_child": True,
            "moves": child_moves,
            "complexity": "charge",
            "deed_id": f"{str(base_plan.get('deed_id') or 'deed')}_m{passage_index + 1:02d}_a{attempt}",
            "endeavor_context": endeavor_context,
            "endeavor_passage_id": str(passage.get("passage_id") or f"m{passage_index + 1:02d}"),
        }
        return child_plan

    def _build_context_entry(
        self,
        *,
        passage_id: str,
        title: str,
        passage_index: int,
        objective_score: float,
        move_results: list[dict],
    ) -> dict:
        ok_moves = sum(1 for r in move_results if str(r.get("status") or "") in {"ok", "degraded"})
        total_moves = max(1, len(move_results))
        return {
            "passage_id": passage_id,
            "title": title,
            "passage_index": int(passage_index),
            "summary": f"{ok_moves}/{total_moves} moves passed; objective_score={objective_score}",
            "objective_score": objective_score,
            "completed_utc": workflow.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    async def _mark_deed_status(self, deed_root: str, plan: dict, deed_status: str, error: str) -> None:
        try:
            await workflow.execute_activity(
                "activity_update_deed_status",
                args=[deed_root, {**plan, "last_error": error}, deed_status],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            workflow.logger.warning("Failed to update deed status for endeavor deed %s: %s", deed_root, exc)
