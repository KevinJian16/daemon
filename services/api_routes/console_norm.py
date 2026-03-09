"""Console norm routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_norm_routes(app: FastAPI, *, ctx: Any) -> None:
    @app.get("/console/norm/preferences")
    def get_preferences():
        prefs = ctx.instinct.all_prefs()
        return [{"pref_key": k, "value": v} for k, v in sorted(prefs.items())]

    @app.get("/console/norm/preferences/{pref_key}")
    def get_preference(pref_key: str):
        prefs = ctx.instinct.all_prefs()
        if pref_key not in prefs:
            raise HTTPException(status_code=404, detail="preference not found")
        return {"pref_key": pref_key, "value": prefs[pref_key]}

    @app.put("/console/norm/preferences/{pref_key}")
    async def set_preference(pref_key: str, request: Request):
        body = await request.json()
        value = str(body.get("value") if isinstance(body, dict) and "value" in body else body)
        ctx.instinct.set_pref(pref_key, value, source="console", changed_by="console")
        ctx.nerve.emit("psyche_updated", {"psyche": "instinct", "key": f"pref.{pref_key}"})
        return {"ok": True, "pref_key": pref_key, "value": value}

    @app.get("/console/norm/preferences/{pref_key}/versions")
    def preference_versions(pref_key: str):
        return ctx.instinct.versions(f"pref.{pref_key}")

    @app.post("/console/norm/preferences/{pref_key}/rollback/{version}")
    def preference_rollback(pref_key: str, version: int):
        ok = ctx.instinct.rollback(f"pref.{pref_key}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        ctx.nerve.emit("psyche_updated", {"psyche": "instinct", "key": f"pref.{pref_key}"})
        return {"ok": True}

    @app.get("/console/norm/rations")
    def get_rations():
        return ctx.instinct.all_rations()

    @app.get("/console/norm/rations/{resource_type}")
    def get_ration(resource_type: str):
        ration = ctx.instinct.get_ration(resource_type)
        if not ration:
            raise HTTPException(status_code=404, detail="ration not found")
        return ration

    @app.put("/console/norm/rations/{resource_type}")
    async def set_ration(resource_type: str, request: Request):
        body = await request.json()
        if isinstance(body, dict):
            raw = body.get("daily_limit")
        else:
            raw = body
        try:
            daily_limit = float(raw)
        except Exception:
            raise HTTPException(status_code=400, detail="daily_limit must be numeric")
        ctx.instinct.set_ration(resource_type, daily_limit, changed_by="console")
        ctx.nerve.emit("psyche_updated", {"psyche": "instinct", "key": f"ration.{resource_type}"})
        return {"ok": True, "resource_type": resource_type, "daily_limit": daily_limit}

    @app.get("/console/norm/rations/{resource_type}/versions")
    def ration_versions(resource_type: str):
        return ctx.instinct.versions(f"ration.{resource_type}")

    @app.post("/console/norm/rations/{resource_type}/rollback/{version}")
    def ration_rollback(resource_type: str, version: int):
        ok = ctx.instinct.rollback(f"ration.{resource_type}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        ctx.nerve.emit("psyche_updated", {"psyche": "instinct", "key": f"ration.{resource_type}"})
        return {"ok": True}

    @app.get("/console/norm/config/{config_key}/versions")
    def config_versions(config_key: str):
        return ctx.instinct.versions(config_key)

    @app.post("/console/norm/config/{config_key}/rollback/{version}")
    def config_rollback(config_key: str, version: int):
        ok = ctx.instinct.rollback(config_key, version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        ctx.nerve.emit("psyche_updated", {"psyche": "instinct", "key": config_key})
        return {"ok": True}
