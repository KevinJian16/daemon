"""Console policy routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_policy_routes(app: FastAPI, *, ctx: Any) -> None:
    @app.get("/console/policy/preferences")
    def get_preferences():
        prefs = ctx.compass.all_prefs()
        return [{"pref_key": k, "value": v} for k, v in sorted(prefs.items())]

    @app.get("/console/policy/preferences/{pref_key}")
    def get_preference(pref_key: str):
        prefs = ctx.compass.all_prefs()
        if pref_key not in prefs:
            raise HTTPException(status_code=404, detail="preference not found")
        return {"pref_key": pref_key, "value": prefs[pref_key]}

    @app.put("/console/policy/preferences/{pref_key}")
    async def set_preference(pref_key: str, request: Request):
        body = await request.json()
        value = str(body.get("value") if isinstance(body, dict) and "value" in body else body)
        ctx.compass.set_pref(pref_key, value, source="console", changed_by="console")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"pref.{pref_key}"})
        return {"ok": True, "pref_key": pref_key, "value": value}

    @app.get("/console/policy/preferences/{pref_key}/versions")
    def preference_versions(pref_key: str):
        return ctx.compass.versions(f"pref.{pref_key}")

    @app.post("/console/policy/preferences/{pref_key}/rollback/{version}")
    def preference_rollback(pref_key: str, version: int):
        ok = ctx.compass.rollback(f"pref.{pref_key}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"pref.{pref_key}"})
        return {"ok": True}

    @app.get("/console/policy/budgets")
    def get_budgets():
        return ctx.compass.all_budgets()

    @app.get("/console/policy/budgets/{resource_type}")
    def get_budget(resource_type: str):
        budget = ctx.compass.get_budget(resource_type)
        if not budget:
            raise HTTPException(status_code=404, detail="budget not found")
        return budget

    @app.put("/console/policy/budgets/{resource_type}")
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

    @app.get("/console/policy/budgets/{resource_type}/versions")
    def budget_versions(resource_type: str):
        return ctx.compass.versions(f"budget.{resource_type}")

    @app.post("/console/policy/budgets/{resource_type}/rollback/{version}")
    def budget_rollback(resource_type: str, version: int):
        ok = ctx.compass.rollback(f"budget.{resource_type}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"budget.{resource_type}"})
        return {"ok": True}

    @app.get("/console/policy/quality/{policy_name}")
    def get_policy_quality(policy_name: str):
        profile = ctx.compass.get_quality_profile(policy_name)
        return {"policy": policy_name, "rules": profile}

    @app.put("/console/policy/quality/{policy_name}")
    async def set_policy_quality(policy_name: str, request: Request):
        body = await request.json()
        rules = body.get("rules") or body
        ctx.compass.set_quality_profile(policy_name, rules, changed_by="console")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"quality.{policy_name}"})
        return {"ok": True}

    @app.get("/console/policy/quality/{policy_name}/versions")
    def policy_quality_versions(policy_name: str):
        return ctx.compass.versions(f"quality.{policy_name}")

    @app.post("/console/policy/quality/{policy_name}/rollback/{version}")
    def policy_quality_rollback(policy_name: str, version: int):
        ok = ctx.compass.rollback(f"quality.{policy_name}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"quality.{policy_name}"})
        return {"ok": True}

    # Backward-compatible aliases.
    @app.get("/console/policy/{policy_name}")
    def get_policy(policy_name: str):
        return get_policy_quality(policy_name)

    @app.put("/console/policy/{policy_name}")
    async def set_policy(policy_name: str, request: Request):
        return await set_policy_quality(policy_name, request)

    @app.get("/console/policy/{policy_name}/versions")
    def policy_versions(policy_name: str):
        return policy_quality_versions(policy_name)

    @app.post("/console/policy/{policy_name}/rollback/{version}")
    def policy_rollback(policy_name: str, version: int):
        return policy_quality_rollback(policy_name, version)
