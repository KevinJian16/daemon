"""Console norm routes."""
from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_norm_routes(app: FastAPI, *, ctx: Any) -> None:
    def _quality_profiles() -> dict:
        return ctx.ledger.load_json("norm_quality.json", {
            "default": {
                "min_sections": 3,
                "min_word_count": 800,
                "forbidden_markers": ["[DONE]", "[COMPLETE]", "<system>", "[INTERNAL]"],
                "language_consistency": True,
                "format_compliance": True,
                "academic_format": False,
            },
            "errand": {
                "min_sections": 1,
                "min_word_count": 200,
                "forbidden_markers": ["[DONE]", "[COMPLETE]", "<system>", "[INTERNAL]"],
                "language_consistency": True,
                "format_compliance": True,
                "academic_format": False,
            },
            "charge": {
                "min_sections": 3,
                "min_word_count": 800,
                "forbidden_markers": ["[DONE]", "[COMPLETE]", "<system>", "[INTERNAL]"],
                "language_consistency": True,
                "format_compliance": True,
                "academic_format": False,
            },
            "endeavor": {
                "min_sections": 4,
                "min_word_count": 1200,
                "forbidden_markers": ["[DONE]", "[COMPLETE]", "<system>", "[INTERNAL]"],
                "language_consistency": True,
                "format_compliance": True,
                "academic_format": False,
            },
        })

    @app.get("/console/norm/quality/{profile_key}")
    def get_quality_profile(profile_key: str):
        profiles = _quality_profiles()
        if profile_key not in profiles:
            raise HTTPException(status_code=404, detail="quality_profile_not_found")
        return {"profile_key": profile_key, "rules": profiles[profile_key]}

    @app.put("/console/norm/quality/{profile_key}")
    async def set_quality_profile(profile_key: str, request: Request):
        body = await request.json()
        rules = body.get("rules") if isinstance(body, dict) else None
        if not isinstance(rules, dict):
            raise HTTPException(status_code=400, detail="rules_must_be_object")
        profiles = _quality_profiles()
        before = profiles.get(profile_key, {})
        profiles[profile_key] = rules
        ctx.ledger.save_json("norm_quality.json", profiles)
        ctx.instinct.record_config_version(f"quality.{profile_key}", rules, changed_by="console", reason="console_update")
        ctx.nerve.emit("psyche_updated", {"psyche": "quality", "key": profile_key})
        ctx.audit_console("update", f"quality:{profile_key}", before, rules)
        return {"ok": True, "profile_key": profile_key, "rules": rules}

    @app.get("/console/norm/quality/{profile_key}/versions")
    def quality_versions(profile_key: str):
        return ctx.instinct.versions(f"quality.{profile_key}")

    @app.post("/console/norm/quality/{profile_key}/rollback/{version}")
    def quality_rollback(profile_key: str, version: int):
        versions = ctx.instinct.versions(f"quality.{profile_key}", limit=500)
        row = next((item for item in versions if int(item.get("version") or 0) == int(version)), None)
        if not row:
            raise HTTPException(status_code=404, detail="version_not_found")
        try:
            rules = json.loads(row.get("value_json") or "{}")
        except Exception:
            rules = {}
        profiles = _quality_profiles()
        before = profiles.get(profile_key, {})
        profiles[profile_key] = rules
        ctx.ledger.save_json("norm_quality.json", profiles)
        ctx.instinct.record_config_version(f"quality.{profile_key}", rules, changed_by="console", reason=f"rollback_to_v{version}")
        ctx.nerve.emit("psyche_updated", {"psyche": "quality", "key": profile_key})
        ctx.audit_console("rollback", f"quality:{profile_key}", before, rules)
        return {"ok": True, "profile_key": profile_key, "version": version}

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
        before = ctx.instinct.get_pref(pref_key, "")
        ctx.instinct.set_pref(pref_key, value, source="console", changed_by="console")
        ctx.nerve.emit("psyche_updated", {"psyche": "instinct", "key": f"pref.{pref_key}"})
        ctx.audit_console("update", f"preference:{pref_key}", {"value": before}, {"value": value})
        return {"ok": True, "pref_key": pref_key, "value": value}

    @app.get("/console/norm/preferences/{pref_key}/versions")
    def preference_versions(pref_key: str):
        return ctx.instinct.versions(f"pref.{pref_key}")

    @app.post("/console/norm/preferences/{pref_key}/rollback/{version}")
    def preference_rollback(pref_key: str, version: int):
        before = ctx.instinct.get_pref(pref_key, "")
        ok = ctx.instinct.rollback(f"pref.{pref_key}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        ctx.nerve.emit("psyche_updated", {"psyche": "instinct", "key": f"pref.{pref_key}"})
        ctx.audit_console("rollback", f"preference:{pref_key}", {"value": before}, {"value": ctx.instinct.get_pref(pref_key, "")})
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
        before = ctx.instinct.get_ration(resource_type)
        ctx.instinct.set_ration(resource_type, daily_limit, changed_by="console")
        ctx.nerve.emit("psyche_updated", {"psyche": "instinct", "key": f"ration.{resource_type}"})
        ctx.audit_console("update", f"ration:{resource_type}", before or {}, {"daily_limit": daily_limit})
        return {"ok": True, "resource_type": resource_type, "daily_limit": daily_limit}

    @app.get("/console/norm/rations/{resource_type}/versions")
    def ration_versions(resource_type: str):
        return ctx.instinct.versions(f"ration.{resource_type}")

    @app.post("/console/norm/rations/{resource_type}/rollback/{version}")
    def ration_rollback(resource_type: str, version: int):
        before = ctx.instinct.get_ration(resource_type)
        ok = ctx.instinct.rollback(f"ration.{resource_type}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        ctx.nerve.emit("psyche_updated", {"psyche": "instinct", "key": f"ration.{resource_type}"})
        ctx.audit_console("rollback", f"ration:{resource_type}", before or {}, ctx.instinct.get_ration(resource_type) or {})
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
