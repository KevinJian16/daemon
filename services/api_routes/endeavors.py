"""Endeavor routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_endeavor_routes(app: FastAPI, *, ctx: Any) -> None:
    def _endeavor_status(manifest: dict) -> str:
        return str(manifest.get("endeavor_status") or "")

    def _endeavor_phase(manifest: dict) -> str:
        return str(manifest.get("endeavor_phase") or "")

    def _set_endeavor_state(manifest: dict, *, endeavor_status: str | None = None, endeavor_phase: str | None = None) -> None:
        if endeavor_status is not None:
            manifest["endeavor_status"] = str(endeavor_status)
        if endeavor_phase is not None:
            manifest["endeavor_phase"] = str(endeavor_phase)

    @app.get("/endeavors")
    def list_endeavors(limit: int = 200):
        return ctx.endeavor_summaries(limit=limit)

    @app.get("/endeavors/{endeavor_id}")
    def get_endeavor(endeavor_id: str, result_limit: int = 200):
        manifest = ctx.load_endeavor_manifest(endeavor_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="endeavor not found")
        _set_endeavor_state(
            manifest,
            endeavor_status=_endeavor_status(manifest),
            endeavor_phase=_endeavor_phase(manifest),
        )
        return {
            "manifest": manifest,
            "passage_results": ctx.endeavor_result_rows(endeavor_id, limit=result_limit),
        }

    @app.post("/endeavors/{endeavor_id}/resume")
    async def resume_endeavor(endeavor_id: str, request: Request):
        manifest = ctx.load_endeavor_manifest(endeavor_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="endeavor not found")

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        endeavor_status = _endeavor_status(manifest).lower()
        if endeavor_status in {"completed", "cancelled"}:
            raise HTTPException(status_code=409, detail={"ok": False, "error": f"endeavor_not_resumable:{endeavor_status}"})

        current_idx = int(manifest.get("current_passage_index") or 0)
        resume_from = int(body.get("resume_from") or current_idx)
        resume_from = max(0, min(resume_from, int(manifest.get("total_passages") or current_idx)))
        endeavor_phase = _endeavor_phase(manifest).strip().lower()
        confirmed = bool(body.get("confirmed") or body.get("endeavor_confirmed"))
        if endeavor_phase == "phase0_waiting_confirmation" and not confirmed:
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error": "endeavor_confirmation_required", "endeavor_phase": endeavor_phase},
            )

        feedback = body.get("feedback")
        decision_payload: dict[str, Any] | None = None
        if isinstance(feedback, dict):
            ctx.append_endeavor_feedback(endeavor_id, current_idx, feedback)
            decision_payload = ctx.apply_endeavor_feedback_decision(endeavor_id, current_idx, feedback, source="resume_api")

        if endeavor_phase == "passage_waiting_feedback":
            result_payload = ctx.endeavor_result_payload(endeavor_id, current_idx)
            decision_row = result_payload.get("user_feedback_decision") if isinstance(result_payload.get("user_feedback_decision"), dict) else {}
            if decision_payload and bool(decision_payload.get("accepted")):
                decision_row = decision_payload.get("decision") if isinstance(decision_payload.get("decision"), dict) else decision_row
            if not isinstance(decision_row, dict) or not decision_row:
                raise HTTPException(
                    status_code=409,
                    detail={"ok": False, "error": "endeavor_passage_feedback_required", "passage_index": current_idx},
                )
            decision_feedback = decision_row.get("feedback") if isinstance(decision_row.get("feedback"), dict) else {}
            if ctx.feedback_satisfied(decision_feedback):
                resume_from = max(resume_from, current_idx + 1)
            else:
                resume_from = current_idx

        base_plan = manifest.get("plan") if isinstance(manifest.get("plan"), dict) else {}
        if not base_plan:
            raise HTTPException(status_code=409, detail={"ok": False, "error": "endeavor_plan_missing"})
        await ctx.ensure_temporal_client(retries=3, delay_s=0.4)
        temporal_client = ctx.get_temporal_client()
        if not temporal_client:
            raise HTTPException(status_code=503, detail={"ok": False, "error_code": "temporal_unavailable"})

        deed_id = str(body.get("deed_id") or f"{manifest.get('deed_id', 'deed')}_resume_{int(ctx.time_time())}")
        deed_root = str(ctx.state / "deeds" / deed_id)
        deed_index = int(manifest.get("deed_index") or 0) + 1
        workflow_id = f"daemon-endeavor-{endeavor_id}-r{deed_index}"

        plan = dict(base_plan)
        plan["deed_id"] = deed_id
        plan["endeavor_id"] = endeavor_id
        plan["endeavor_resume_from"] = resume_from
        plan["endeavor_deed_index"] = deed_index
        plan["_workflow_id"] = workflow_id
        plan["complexity"] = "endeavor"
        plan["endeavor_confirmed"] = True
        if isinstance(manifest.get("endeavor_context"), list):
            plan["endeavor_context"] = [x for x in manifest.get("endeavor_context") if isinstance(x, dict)][-32:]

        if endeavor_phase == "passage_waiting_feedback":
            result_payload = ctx.endeavor_result_payload(endeavor_id, current_idx)
            decision_row = result_payload.get("user_feedback_decision") if isinstance(result_payload.get("user_feedback_decision"), dict) else {}
            decision_feedback = decision_row.get("feedback") if isinstance(decision_row.get("feedback"), dict) else {}
            satisfied = ctx.feedback_satisfied(decision_feedback)
            plan["endeavor_feedback_passage_index"] = current_idx
            plan["endeavor_feedback_satisfied"] = satisfied
            plan["endeavor_feedback_comment"] = str(decision_feedback.get("comment") or "")
            plan["endeavor_force_user_rework"] = not satisfied

        ctx.will._record_deed(plan, "running", deed_root)
        try:
            await temporal_client.submit(
                workflow_id=workflow_id,
                plan=plan,
                deed_root=deed_root,
                workflow_name="EndeavorWorkflow",
            )
        except Exception as exc:
            ctx.will._record_deed({**plan, "last_error": str(exc)[:300]}, "failed_submission", deed_root)
            raise HTTPException(
                status_code=503,
                detail={"ok": False, "error_code": "temporal_submit_failed", "error": str(exc)[:300]},
            )

        _set_endeavor_state(manifest, endeavor_status="running", endeavor_phase="resume_requested")
        manifest["current_passage_index"] = resume_from
        manifest["workflow_id"] = workflow_id
        manifest["deed_index"] = deed_index
        if endeavor_phase == "phase0_waiting_confirmation":
            manifest["confirmed_utc"] = ctx.utc()
        manifest["updated_utc"] = ctx.utc()
        ctx.save_endeavor_manifest(endeavor_id, manifest)
        return {
            "ok": True,
            "endeavor_id": endeavor_id,
            "workflow_id": workflow_id,
            "deed_id": deed_id,
            "resume_from": resume_from,
        }

    @app.post("/endeavors/{endeavor_id}/confirm")
    async def confirm_endeavor(endeavor_id: str):
        manifest = ctx.load_endeavor_manifest(endeavor_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="endeavor not found")
        endeavor_phase = _endeavor_phase(manifest).strip().lower()
        if endeavor_phase != "phase0_waiting_confirmation":
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error": f"endeavor_confirm_not_allowed_in_phase:{endeavor_phase}"},
            )

        class _Req:
            async def json(self):
                return {"confirmed": True}

        return await resume_endeavor(endeavor_id, _Req())  # type: ignore[arg-type]

    @app.post("/endeavors/{endeavor_id}/passages/{passage_index}/feedback")
    async def endeavor_passage_feedback(endeavor_id: str, passage_index: int, request: Request):
        manifest = ctx.load_endeavor_manifest(endeavor_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="endeavor not found")
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
        result = ctx.apply_endeavor_feedback_decision(
            endeavor_id,
            int(passage_index),
            feedback,
            source=source,
        )
        ctx.append_jsonl(
            ctx.telemetry_dir / "endeavor_feedback.jsonl",
            {
                "endeavor_id": endeavor_id,
                "passage_index": int(passage_index),
                "source": source,
                "accepted": bool(result.get("accepted")),
                "feedback": feedback,
                "created_utc": ctx.utc(),
            },
        )
        return {
            "ok": True,
            "endeavor_id": endeavor_id,
            "passage_index": int(passage_index),
            "accepted": bool(result.get("accepted")),
            "decision": result.get("decision", {}),
        }

    @app.post("/endeavors/{endeavor_id}/passages/{passage_index}/retry")
    async def retry_endeavor_passage(endeavor_id: str, passage_index: int):
        manifest = ctx.load_endeavor_manifest(endeavor_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="endeavor not found")
        endeavor_phase = _endeavor_phase(manifest).strip().lower()
        endeavor_status = _endeavor_status(manifest).strip().lower()
        if endeavor_phase != "passage_failed" and endeavor_status != "awaiting_intervention":
            raise HTTPException(
                status_code=409,
                detail={
                    "ok": False,
                    "error": f"passage_retry_not_allowed_in_phase:{endeavor_phase}",
                    "endeavor_status": endeavor_status,
                },
            )

        class _Req:
            async def json(self):
                return {"resume_from": int(passage_index), "confirmed": True}

        return await resume_endeavor(endeavor_id, _Req())  # type: ignore[arg-type]

    @app.post("/endeavors/{endeavor_id}/cancel")
    async def cancel_endeavor(endeavor_id: str):
        manifest = ctx.load_endeavor_manifest(endeavor_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="endeavor not found")
        workflow_id = str(manifest.get("workflow_id") or "")
        child_workflow_id = str(manifest.get("current_child_workflow_id") or "")
        await ctx.ensure_temporal_client(retries=2, delay_s=0.3)
        temporal_client = ctx.get_temporal_client()
        if temporal_client:
            if workflow_id:
                try:
                    await temporal_client.cancel(workflow_id)
                except Exception as exc:
                    ctx.logger.warning("Endeavor cancel failed workflow_id=%s: %s", workflow_id, exc)
            if child_workflow_id:
                try:
                    await temporal_client.cancel(child_workflow_id)
                except Exception as exc:
                    ctx.logger.warning("Endeavor cancel failed child_workflow_id=%s: %s", child_workflow_id, exc)
        _set_endeavor_state(manifest, endeavor_status="cancelled", endeavor_phase="cancelled")
        manifest["updated_utc"] = ctx.utc()
        ctx.save_endeavor_manifest(endeavor_id, manifest)
        return {
            "ok": True,
            "endeavor_id": endeavor_id,
            "workflow_id": workflow_id,
            "child_workflow_id": child_workflow_id,
            "endeavor_status": "cancelled",
        }
