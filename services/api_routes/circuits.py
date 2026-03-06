"""Recurring user Circuit routes — CRUD + manual trigger."""
from __future__ import annotations

from fastapi import HTTPException, Request


def register_circuit_routes(app, ctx) -> None:
    @app.get("/circuits")
    def list_circuits():
        return ctx.scheduler.list_circuits()

    @app.post("/circuits")
    async def create_circuit(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "request body must be a JSON object")
        name = str(body.get("name") or "").strip()
        prompt = str(body.get("prompt") or "").strip()
        run_type = str(body.get("run_type") or "research_report").strip()
        cron = str(body.get("cron") or "").strip()
        tz = str(body.get("tz") or "UTC").strip()
        if not name or not prompt or not cron:
            raise HTTPException(400, "name, prompt, and cron are required")
        result = ctx.scheduler.create_circuit(name, prompt, run_type, cron, tz)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error"))
        return result["circuit"]

    @app.put("/circuits/{circuit_id}")
    async def update_circuit(circuit_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "request body must be a JSON object")
        result = ctx.scheduler.update_circuit(circuit_id, body)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error"))
        return result["circuit"]

    @app.delete("/circuits/{circuit_id}")
    def cancel_circuit(circuit_id: str):
        result = ctx.scheduler.cancel_circuit(circuit_id)
        if not result.get("ok"):
            raise HTTPException(404, result.get("error"))
        return result

    @app.post("/circuits/{circuit_id}/trigger")
    def trigger_circuit(circuit_id: str):
        result = ctx.scheduler.trigger_circuit(circuit_id)
        if not result.get("ok"):
            raise HTTPException(400, result.get("error"))
        return result
