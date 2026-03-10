"""Submission route extracted from monolithic services.api."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request


def register_submit_route(
    app: FastAPI,
    *,
    ensure_temporal_client: Callable[..., Awaitable[bool]],
    will: Any,
    log_portal_event: Callable[[str, dict[str, Any], Request | None], None],
) -> None:
    @app.post("/submit")
    async def submit_deed(request: Request):
        await ensure_temporal_client(retries=3, delay_s=0.4)
        plan = await request.json()
        log_portal_event(
            "submit_requested",
            {
                "dag_budget": int((plan.get("brief") or {}).get("dag_budget") or plan.get("dag_budget") or 0),
                "slip_title": str(plan.get("slip_title") or plan.get("deed_title") or plan.get("title") or "")[:120],
                "priority": plan.get("priority"),
            },
            request,
        )
        result = await will.submit(plan)
        if not result.get("ok"):
            code = str(result.get("error_code") or "")
            log_portal_event("submit_failed", {"error_code": code, "deed_id": result.get("deed_id", "")}, request)
            if code.startswith("temporal_"):
                raise HTTPException(status_code=503, detail=result)
            if code in {"invalid_plan", "ward_blocked"}:
                raise HTTPException(status_code=400, detail=result)
            raise HTTPException(status_code=500, detail=result)
        log_portal_event(
            "submit_ok",
            {
                "deed_id": result.get("deed_id", ""),
                "deed_status": result.get("deed_status", ""),
            },
            request,
        )
        return result
