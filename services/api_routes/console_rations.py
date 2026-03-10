"""Console ration routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_rations_routes(app: FastAPI, *, ctx: Any) -> None:
    @app.get("/console/rations")
    def get_rations():
        return ctx.instinct.all_rations()

    @app.get("/console/rations/{resource_type}")
    def get_ration(resource_type: str):
        ration = ctx.instinct.get_ration(resource_type)
        if not ration:
            raise HTTPException(status_code=404, detail="ration_not_found")
        return ration

    @app.put("/console/rations/{resource_type}")
    async def set_ration(resource_type: str, request: Request):
        body = await request.json()
        raw = body.get("daily_limit") if isinstance(body, dict) else body
        try:
            daily_limit = float(raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="daily_limit_must_be_numeric") from exc
        before = ctx.instinct.get_ration(resource_type)
        ctx.instinct.set_ration(resource_type, daily_limit, changed_by="console")
        ctx.nerve.emit("psyche_updated", {"psyche": "instinct", "key": f"ration.{resource_type}"})
        ctx.audit_console("update", f"ration:{resource_type}", before or {}, {"daily_limit": daily_limit})
        return {"ok": True, "resource_type": resource_type, "daily_limit": daily_limit}

    @app.get("/console/rations/{resource_type}/versions")
    def ration_versions(resource_type: str):
        return ctx.instinct.versions(f"ration.{resource_type}")

    @app.post("/console/rations/{resource_type}/rollback/{version}")
    def ration_rollback(resource_type: str, version: int):
        before = ctx.instinct.get_ration(resource_type)
        ok = ctx.instinct.rollback(f"ration.{resource_type}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version_not_found")
        ctx.nerve.emit("psyche_updated", {"psyche": "instinct", "key": f"ration.{resource_type}"})
        ctx.audit_console("rollback", f"ration:{resource_type}", before or {}, ctx.instinct.get_ration(resource_type) or {})
        return {"ok": True}
