"""Portal chat routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_chat_routes(app: FastAPI, *, dialog: Any, log_portal_event) -> None:
    @app.post("/chat/session")
    def new_chat_session(request: Request):
        sid = dialog.new_session()
        log_portal_event("chat_session_created", {"session_id": sid}, request)
        return {"session_id": sid}

    @app.post("/chat/{session_id}")
    async def chat(session_id: str, request: Request):
        body = await request.json()
        message = str(body.get("message") or "")
        if not message:
            raise HTTPException(status_code=400, detail="message required")
        log_portal_event("chat_message", {"session_id": session_id, "message_len": len(message)}, request)
        result = dialog.chat(session_id, message)
        if not result.get("ok"):
            log_portal_event("chat_failed", {"session_id": session_id, "error": result.get("error", "")}, request)
            raise HTTPException(status_code=502, detail=result.get("error"))
        log_portal_event(
            "chat_ok",
            {"session_id": session_id, "has_plan": bool(result.get("plan")), "response_len": len(str(result.get("content") or ""))},
            request,
        )
        return result
