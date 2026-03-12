"""Portal/Telegram feedback routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_feedback_routes(app: FastAPI, *, ctx: Any) -> None:
    @app.get("/feedback/pending")
    def list_pending_feedback(limit: int = 100):
        return ctx.pending_feedback_surveys(limit=limit)

    @app.get("/feedback/{deed_id}/state")
    def get_feedback_state(deed_id: str):
        return ctx.feedback_state(deed_id)

    @app.post("/feedback/submit")
    async def submit_feedback_from_body(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        deed_id = str(body.get("deed_id") or "").strip()
        if not deed_id:
            raise HTTPException(status_code=400, detail="deed_id_required")
        return await ctx.submit_feedback_internal(deed_id, body, request=request)

    @app.post("/feedback/{deed_id}")
    async def submit_feedback(deed_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        return await ctx.submit_feedback_internal(deed_id, body, request=request)

    @app.post("/feedback/{deed_id}/append")
    async def append_feedback(deed_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        body["type"] = "append"
        return await ctx.submit_feedback_internal(deed_id, body, request=request)

    @app.post("/deeds/{deed_id}/feedback")
    async def submit_deed_feedback(deed_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        if body.get("rating") is None and body.get("quick_rating") is not None:
            body["rating"] = body.get("quick_rating")
        if not str(body.get("type") or "").strip():
            body["type"] = "quick" if body.get("rating") is not None else "append"
        if not str(body.get("source") or "").strip():
            body["source"] = "portal"
        return await ctx.submit_feedback_internal(deed_id, body, request=request)

    @app.post("/deeds/{deed_id}/feedback/append")
    async def append_deed_feedback(deed_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        body["type"] = "append"
        if not str(body.get("source") or "").strip():
            body["source"] = "portal"
        return await ctx.submit_feedback_internal(deed_id, body, request=request)
