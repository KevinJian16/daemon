"""Submission route extracted from monolithic services.api."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request


def register_submit_route(
    app: FastAPI,
    *,
    ensure_temporal_client: Callable[..., Awaitable[bool]],
    dispatch: Any,
    log_portal_event: Callable[[str, dict[str, Any], Request | None], None],
) -> None:
    @app.post("/submit")
    async def submit_run(request: Request):
        await ensure_temporal_client(retries=3, delay_s=0.4)
        plan = await request.json()
        log_portal_event(
            "submit_requested",
            {
                "run_type": plan.get("run_type", ""),
                "run_title": str(plan.get("run_title") or plan.get("title") or "")[:120],
                "priority": plan.get("priority"),
            },
            request,
        )
        result = await dispatch.submit(plan)
        if not result.get("ok"):
            code = str(result.get("error_code") or "")
            log_portal_event("submit_failed", {"error_code": code, "run_id": result.get("run_id", "")}, request)
            if code.startswith("temporal_"):
                raise HTTPException(status_code=503, detail=result)
            if code in {"invalid_plan", "semantic_mapping_failed", "strategy_guard_blocked"}:
                raise HTTPException(status_code=400, detail=result)
            raise HTTPException(status_code=500, detail=result)
        log_portal_event(
            "submit_ok",
            {
                "run_id": result.get("run_id", ""),
                "run_status": result.get("run_status", ""),
            },
            request,
        )
        return result
