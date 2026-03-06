"""Campaign routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_campaign_routes(app: FastAPI, *, ctx: Any) -> None:
    def _campaign_status(manifest: dict) -> str:
        return str(manifest.get("campaign_status") or "")

    def _campaign_phase(manifest: dict) -> str:
        return str(manifest.get("campaign_phase") or "")

    def _set_campaign_state(manifest: dict, *, campaign_status: str | None = None, campaign_phase: str | None = None) -> None:
        if campaign_status is not None:
            manifest["campaign_status"] = str(campaign_status)
        if campaign_phase is not None:
            manifest["campaign_phase"] = str(campaign_phase)

    @app.get("/campaigns")
    def list_campaigns(limit: int = 200):
        return ctx.campaign_summaries(limit=limit)

    @app.get("/campaigns/{campaign_id}")
    def get_campaign(campaign_id: str, result_limit: int = 200):
        manifest = ctx.load_campaign_manifest(campaign_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="campaign not found")
        _set_campaign_state(
            manifest,
            campaign_status=_campaign_status(manifest),
            campaign_phase=_campaign_phase(manifest),
        )
        return {
            "manifest": manifest,
            "milestone_results": ctx.campaign_result_rows(campaign_id, limit=result_limit),
        }

    @app.post("/campaigns/{campaign_id}/resume")
    async def resume_campaign(campaign_id: str, request: Request):
        manifest = ctx.load_campaign_manifest(campaign_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="campaign not found")

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        campaign_status = _campaign_status(manifest).lower()
        if campaign_status in {"completed", "cancelled"}:
            raise HTTPException(status_code=409, detail={"ok": False, "error": f"campaign_not_resumable:{campaign_status}"})

        current_idx = int(manifest.get("current_milestone_index") or 0)
        resume_from = int(body.get("resume_from") or current_idx)
        resume_from = max(0, min(resume_from, int(manifest.get("total_milestones") or current_idx)))
        campaign_phase = _campaign_phase(manifest).strip().lower()
        confirmed = bool(body.get("confirmed") or body.get("campaign_confirmed"))
        if campaign_phase == "phase0_waiting_confirmation" and not confirmed:
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error": "campaign_confirmation_required", "campaign_phase": campaign_phase},
            )

        feedback = body.get("feedback")
        decision_payload: dict[str, Any] | None = None
        if isinstance(feedback, dict):
            ctx.append_campaign_feedback(campaign_id, current_idx, feedback)
            decision_payload = ctx.apply_campaign_feedback_decision(campaign_id, current_idx, feedback, source="resume_api")

        if campaign_phase == "milestone_waiting_feedback":
            result_payload = ctx.campaign_result_payload(campaign_id, current_idx)
            decision_row = result_payload.get("user_feedback_decision") if isinstance(result_payload.get("user_feedback_decision"), dict) else {}
            if decision_payload and bool(decision_payload.get("accepted")):
                decision_row = decision_payload.get("decision") if isinstance(decision_payload.get("decision"), dict) else decision_row
            if not isinstance(decision_row, dict) or not decision_row:
                raise HTTPException(
                    status_code=409,
                    detail={"ok": False, "error": "campaign_milestone_feedback_required", "milestone_index": current_idx},
                )
            decision_feedback = decision_row.get("feedback") if isinstance(decision_row.get("feedback"), dict) else {}
            if ctx.feedback_satisfied(decision_feedback):
                resume_from = max(resume_from, current_idx + 1)
            else:
                resume_from = current_idx

        base_plan = manifest.get("plan") if isinstance(manifest.get("plan"), dict) else {}
        if not base_plan:
            raise HTTPException(status_code=409, detail={"ok": False, "error": "campaign_plan_missing"})
        await ctx.ensure_temporal_client(retries=3, delay_s=0.4)
        temporal_client = ctx.get_temporal_client()
        if not temporal_client:
            raise HTTPException(status_code=503, detail={"ok": False, "error_code": "temporal_unavailable"})

        run_id = str(body.get("run_id") or f"{manifest.get('run_id', 'run')}_resume_{int(ctx.time_time())}")
        run_root = str(ctx.state / "runs" / run_id)
        run_index = int(manifest.get("run_index") or 0) + 1
        workflow_id = f"daemon-campaign-{campaign_id}-r{run_index}"

        plan = dict(base_plan)
        plan["run_id"] = run_id
        plan["campaign_id"] = campaign_id
        plan["campaign_resume_from"] = resume_from
        plan["campaign_run_index"] = run_index
        plan["_workflow_id"] = workflow_id
        plan["work_scale"] = "campaign"
        plan["campaign_confirmed"] = True

        if campaign_phase == "milestone_waiting_feedback":
            result_payload = ctx.campaign_result_payload(campaign_id, current_idx)
            decision_row = result_payload.get("user_feedback_decision") if isinstance(result_payload.get("user_feedback_decision"), dict) else {}
            decision_feedback = decision_row.get("feedback") if isinstance(decision_row.get("feedback"), dict) else {}
            satisfied = ctx.feedback_satisfied(decision_feedback)
            plan["campaign_feedback_milestone_index"] = current_idx
            plan["campaign_feedback_satisfied"] = satisfied
            plan["campaign_feedback_comment"] = str(decision_feedback.get("comment") or "")
            plan["campaign_force_user_rework"] = not satisfied

        ctx.dispatch._record_run(plan, "running", run_root)
        try:
            await temporal_client.submit(
                workflow_id=workflow_id,
                plan=plan,
                run_root=run_root,
                workflow_name="CampaignWorkflow",
            )
        except Exception as exc:
            ctx.dispatch._record_run({**plan, "last_error": str(exc)[:300]}, "failed_submission", run_root)
            raise HTTPException(
                status_code=503,
                detail={"ok": False, "error_code": "temporal_submit_failed", "error": str(exc)[:300]},
            )

        _set_campaign_state(manifest, campaign_status="running", campaign_phase="resume_requested")
        manifest["current_milestone_index"] = resume_from
        manifest["workflow_id"] = workflow_id
        manifest["run_index"] = run_index
        if campaign_phase == "phase0_waiting_confirmation":
            manifest["confirmed_utc"] = ctx.utc()
        manifest["updated_utc"] = ctx.utc()
        ctx.save_campaign_manifest(campaign_id, manifest)
        return {
            "ok": True,
            "campaign_id": campaign_id,
            "workflow_id": workflow_id,
            "run_id": run_id,
            "resume_from": resume_from,
        }

    @app.post("/campaigns/{campaign_id}/confirm")
    async def confirm_campaign(campaign_id: str):
        manifest = ctx.load_campaign_manifest(campaign_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="campaign not found")
        campaign_phase = _campaign_phase(manifest).strip().lower()
        if campaign_phase != "phase0_waiting_confirmation":
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error": f"campaign_confirm_not_allowed_in_campaign_phase:{campaign_phase}"},
            )

        class _Req:
            async def json(self):
                return {"confirmed": True}

        return await resume_campaign(campaign_id, _Req())  # type: ignore[arg-type]

    @app.post("/campaigns/{campaign_id}/milestones/{milestone_index}/feedback")
    async def campaign_milestone_feedback(campaign_id: str, milestone_index: int, request: Request):
        manifest = ctx.load_campaign_manifest(campaign_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="campaign not found")
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        source = str(body.get("source") or "portal")
        feedback = body.get("feedback") if isinstance(body.get("feedback"), dict) else {
            "rating": body.get("rating"),
            "satisfied": body.get("satisfied"),
            "comment": str(body.get("comment") or ""),
        }
        result = ctx.apply_campaign_feedback_decision(
            campaign_id,
            int(milestone_index),
            feedback,
            source=source,
        )
        ctx.append_jsonl(
            ctx.telemetry_dir / "campaign_feedback.jsonl",
            {
                "campaign_id": campaign_id,
                "milestone_index": int(milestone_index),
                "source": source,
                "accepted": bool(result.get("accepted")),
                "feedback": feedback,
                "created_utc": ctx.utc(),
            },
        )
        return {
            "ok": True,
            "campaign_id": campaign_id,
            "milestone_index": int(milestone_index),
            "accepted": bool(result.get("accepted")),
            "decision": result.get("decision", {}),
        }

    @app.post("/campaigns/{campaign_id}/cancel")
    async def cancel_campaign(campaign_id: str):
        manifest = ctx.load_campaign_manifest(campaign_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="campaign not found")
        workflow_id = str(manifest.get("workflow_id") or "")
        await ctx.ensure_temporal_client(retries=2, delay_s=0.3)
        temporal_client = ctx.get_temporal_client()
        if temporal_client and workflow_id:
            try:
                await temporal_client.cancel(workflow_id)
            except Exception as exc:
                ctx.logger.warning("Campaign cancel failed workflow_id=%s: %s", workflow_id, exc)
        _set_campaign_state(manifest, campaign_status="cancelled", campaign_phase="cancelled")
        manifest["updated_utc"] = ctx.utc()
        ctx.save_campaign_manifest(campaign_id, manifest)
        return {
            "ok": True,
            "campaign_id": campaign_id,
            "workflow_id": workflow_id,
            "campaign_status": "cancelled",
        }
