"""Console norm routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_norm_routes(app: FastAPI, *, ctx: Any) -> None:
    @app.get("/console/norm/preferences")
    def get_preferences():
        prefs = ctx.compass.all_prefs()
        return [{"pref_key": k, "value": v} for k, v in sorted(prefs.items())]

    @app.get("/console/norm/preferences/{pref_key}")
    def get_preference(pref_key: str):
        prefs = ctx.compass.all_prefs()
        if pref_key not in prefs:
            raise HTTPException(status_code=404, detail="preference not found")
        return {"pref_key": pref_key, "value": prefs[pref_key]}

    @app.put("/console/norm/preferences/{pref_key}")
    async def set_preference(pref_key: str, request: Request):
        body = await request.json()
        value = str(body.get("value") if isinstance(body, dict) and "value" in body else body)
        ctx.compass.set_pref(pref_key, value, source="console", changed_by="console")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"pref.{pref_key}"})
        return {"ok": True, "pref_key": pref_key, "value": value}

    @app.get("/console/norm/preferences/{pref_key}/versions")
    def preference_versions(pref_key: str):
        return ctx.compass.versions(f"pref.{pref_key}")

    @app.post("/console/norm/preferences/{pref_key}/rollback/{version}")
    def preference_rollback(pref_key: str, version: int):
        ok = ctx.compass.rollback(f"pref.{pref_key}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"pref.{pref_key}"})
        return {"ok": True}

    @app.get("/console/norm/budgets")
    def get_budgets():
        return ctx.compass.all_budgets()

    @app.get("/console/norm/budgets/{resource_type}")
    def get_budget(resource_type: str):
        budget = ctx.compass.get_budget(resource_type)
        if not budget:
            raise HTTPException(status_code=404, detail="budget not found")
        return budget

    @app.put("/console/norm/budgets/{resource_type}")
    async def set_budget(resource_type: str, request: Request):
        body = await request.json()
        if isinstance(body, dict):
            raw = body.get("daily_limit")
        else:
            raw = body
        try:
            daily_limit = float(raw)
        except Exception:
            raise HTTPException(status_code=400, detail="daily_limit must be numeric")
        ctx.compass.set_budget(resource_type, daily_limit, changed_by="console")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"budget.{resource_type}"})
        return {"ok": True, "resource_type": resource_type, "daily_limit": daily_limit}

    @app.get("/console/norm/budgets/{resource_type}/versions")
    def budget_versions(resource_type: str):
        return ctx.compass.versions(f"budget.{resource_type}")

    @app.post("/console/norm/budgets/{resource_type}/rollback/{version}")
    def budget_rollback(resource_type: str, version: int):
        ok = ctx.compass.rollback(f"budget.{resource_type}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"budget.{resource_type}"})
        return {"ok": True}

    @app.get("/console/norm/quality/{norm_name}")
    def get_norm_quality(norm_name: str):
        profile = ctx.compass.get_quality_profile(norm_name)
        return {"norm": norm_name, "rules": profile}

    @app.put("/console/norm/quality/{norm_name}")
    async def set_norm_quality(norm_name: str, request: Request):
        body = await request.json()
        rules = body.get("rules") or body
        ctx.compass.set_quality_profile(norm_name, rules, changed_by="console")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"quality.{norm_name}"})
        return {"ok": True}

    @app.get("/console/norm/quality/{norm_name}/versions")
    def norm_quality_versions(norm_name: str):
        return ctx.compass.versions(f"quality.{norm_name}")

    @app.post("/console/norm/quality/{norm_name}/rollback/{version}")
    def norm_quality_rollback(norm_name: str, version: int):
        ok = ctx.compass.rollback(f"quality.{norm_name}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"quality.{norm_name}"})
        return {"ok": True}

    @app.get("/console/norm/{norm_name}")
    def get_norm(norm_name: str):
        return get_norm_quality(norm_name)

    @app.put("/console/norm/{norm_name}")
    async def set_norm(norm_name: str, request: Request):
        return await set_norm_quality(norm_name, request)

    @app.get("/console/norm/{norm_name}/versions")
    def norm_versions(norm_name: str):
        return norm_quality_versions(norm_name)

    @app.post("/console/norm/{norm_name}/rollback/{version}")
    def norm_rollback(norm_name: str, version: int):
        return norm_quality_rollback(norm_name, version)
