"""Portal/Telegram feedback routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_feedback_routes(app: FastAPI, *, ctx: Any) -> None:
    @app.get("/feedback/pending")
    def list_pending_feedback(limit: int = 100):
        return ctx.pending_feedback_surveys(limit=limit)

    @app.get("/feedback/{run_id}/state")
    def get_feedback_state(run_id: str):
        return ctx.feedback_state(run_id)

    @app.get("/feedback/{run_id}/questions")
    async def get_feedback_questions(run_id: str):
        return await ctx.get_feedback_questions(run_id)

    @app.post("/feedback/submit")
    async def submit_feedback_from_body(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        run_id = str(body.get("run_id") or "").strip()
        if not run_id:
            raise HTTPException(status_code=400, detail="run_id_required")
        return await ctx.submit_feedback_internal(run_id, body, request=request)

    @app.post("/feedback/{run_id}")
    async def submit_feedback(run_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        return await ctx.submit_feedback_internal(run_id, body, request=request)

    @app.post("/feedback/{run_id}/append")
    async def append_feedback(run_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        body["type"] = "append"
        return await ctx.submit_feedback_internal(run_id, body, request=request)

    @app.post("/runs/{run_id}/feedback")
    async def submit_run_feedback(run_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        if body.get("rating") is None and body.get("quick_rating") is not None:
            body["rating"] = body.get("quick_rating")
        if not str(body.get("type") or "").strip():
            body["type"] = "quick" if body.get("rating") is not None else "append"
        if not str(body.get("source") or "").strip():
            body["source"] = "telegram"
        return await ctx.submit_feedback_internal(run_id, body, request=request)
