"""Console admin/config/model routes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from services.storage_paths import load_storage_roots, save_storage_roots, storage_status


def register_console_admin_routes(app: FastAPI, *, ctx: Any) -> None:
    def _is_within_24h(value: str) -> bool:
        raw = str(value or "").strip()
        if not raw:
            return False
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc) >= datetime.now(timezone.utc) - timedelta(hours=24)
        except Exception:
            return False

    @app.get("/console/dashboard")
    def console_dashboard():
        ward = ctx.ledger.load_ward()
        deeds = ctx.ledger.load_deeds()
        folios = ctx.folio_writ.list_folios() if getattr(ctx, "folio_writ", None) else []
        slips = ctx.folio_writ.list_slips() if getattr(ctx, "folio_writ", None) else []
        writs = ctx.folio_writ.list_writs() if getattr(ctx, "folio_writ", None) else []
        storage = storage_status(ctx.state)
        return {
            "ward": ward,
            "system_status": ctx.ledger.load_system_status(),
            "running_deeds": sum(1 for row in deeds if str(row.get("deed_status") or "") in {"running", "queued", "paused", "cancelling"}),
            "awaiting_eval": sum(1 for row in deeds if str(row.get("deed_status") or "") == "awaiting_eval"),
            "failed_24h": sum(1 for row in deeds if str(row.get("deed_status") or "") == "failed" and _is_within_24h(str(row.get("updated_utc") or row.get("failed_utc") or ""))),
            "active_folios": sum(1 for row in folios if str(row.get("status") or "") == "active"),
            "parked_folios": sum(1 for row in folios if str(row.get("status") or "") == "parked"),
            "active_slips": sum(1 for row in slips if str(row.get("status") or "") == "active"),
            "open_drafts": sum(1 for row in ctx.folio_writ.list_drafts() if str(row.get("status") or "") in {"open", "refining"}),
            "active_writs": sum(1 for row in writs if str(row.get("status") or "") == "active"),
            "storage_ready": bool(storage.get("ready")),
            "cortex_usage": ctx.cortex.usage_today(),
        }

    @app.get("/console/retinue")
    def console_retinue():
        path = ctx.state / "pool_status.json"
        data = ctx.ledger.load_json(path.name, {"instances": []})
        instances = data.get("instances") if isinstance(data, dict) and isinstance(data.get("instances"), list) else []
        occupied = sum(1 for row in instances if str(row.get("status") or "") == "occupied")
        return {
            "total": len(instances),
            "occupied": occupied,
            "idle": max(0, len(instances) - occupied),
            "instances": instances,
        }

    @app.get("/console/routines")
    def console_cadence():
        return ctx.cadence.status()

    @app.get("/console/routines/history")
    def console_cadence_history(routine: str | None = None, limit: int = 100):
        return ctx.cadence.history(routine=routine, limit=limit)

    @app.put("/console/routines/{job_id}")
    async def console_update_schedule(job_id: str, request: Request):
        body = await request.json()
        schedule = body.get("schedule") if isinstance(body, dict) and "schedule" in body else None
        enabled = body.get("enabled") if isinstance(body, dict) and "enabled" in body else None
        before = next((row for row in ctx.cadence.status() if str(row.get("routine") or "") == (job_id if job_id.startswith("spine.") else f"spine.{job_id}")), {})
        result = ctx.cadence.update_schedule(job_id, schedule=schedule, enabled=enabled)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result)
        ctx.audit_console("update", "cadence", before, result)
        return result

    @app.post("/console/routines/{routine}/trigger")
    async def console_trigger_schedule(routine: str):
        full_name = routine if routine.startswith("spine.") else f"spine.{routine}"
        result = await ctx.cadence.trigger(full_name)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result

    @app.get("/console/logs/{log_type}")
    def console_logs(log_type: str, limit: int = 200):
        mapping: dict[str, Path] = {
            "portal": ctx.state / "telemetry" / "portal_events.jsonl",
            "telegram": ctx.state / "telemetry" / "telegram_events.jsonl",
            "herald": ctx.state / "herald_log.jsonl",
            "console_audit": ctx.state / "console_audit.jsonl",
            "daily_stats": ctx.state / "daily_stats.jsonl",
            "events": ctx.state / "events.jsonl",
            "notify_queue": ctx.state / "notify_queue.jsonl",
            "spine": ctx.state / "spine_log.jsonl",
            "schedule_history": ctx.state / "schedule_history.json",
        }
        path = mapping.get(log_type)
        if not path:
            raise HTTPException(status_code=404, detail="unknown_log_type")
        if path.suffix == ".json":
            data = ctx.ledger.load_json(path.name, [])
            return data[-max(1, min(limit, 1000)):] if isinstance(data, list) else data
        return ctx.ledger.load_jsonl(path, max_items=max(1, min(limit, 1000)))

    @app.get("/console/config/{config_key}")
    def console_get_config(config_key: str):
        filename = f"{config_key}.json" if not str(config_key).endswith(".json") else config_key
        return ctx.ledger.load_json(filename, {})

    @app.put("/console/config/{config_key}")
    async def console_put_config(config_key: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="config_payload_must_be_object")
        filename = f"{config_key}.json" if not str(config_key).endswith(".json") else config_key
        before = ctx.ledger.load_json(filename, {})
        ctx.ledger.save_json(filename, body)
        ctx.audit_console("update", f"config:{filename}", before, body)
        return {"ok": True, "config_key": filename, "saved": True}

    @app.get("/console/model-usage")
    def console_model_usage(limit: int = 1000):
        records = ctx.cortex.usage_between(limit=max(1, min(limit, 5000)))
        by_provider: dict[str, dict] = {}
        by_model: dict[str, dict] = {}
        for row in records:
            provider = str(row.get("provider") or "unknown")
            model = str(row.get("model") or "unknown")
            provider_row = by_provider.setdefault(provider, {"calls": 0, "in_tokens": 0, "out_tokens": 0, "errors": 0})
            model_row = by_model.setdefault(model, {"calls": 0, "in_tokens": 0, "out_tokens": 0, "errors": 0})
            for target in (provider_row, model_row):
                target["calls"] += 1
                target["in_tokens"] += int(row.get("in_tokens") or 0)
                target["out_tokens"] += int(row.get("out_tokens") or 0)
                if not row.get("success"):
                    target["errors"] += 1
        return {"records": records, "summary": {"by_provider": by_provider, "by_model": by_model}}

    @app.get("/console/model-policy")
    def get_model_policy():
        return json.loads(ctx.model_policy_path.read_text(encoding="utf-8")) if ctx.model_policy_path.exists() else {}

    @app.put("/console/model-policy")
    async def put_model_policy(request: Request):
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="model_policy_must_be_object")
        registry = json.loads(ctx.model_registry_path.read_text(encoding="utf-8")) if ctx.model_registry_path.exists() else {}
        aliases = ctx.model_registry_aliases(registry if isinstance(registry, dict) else {})
        try:
            ctx.validate_model_policy(payload, aliases)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        before = json.loads(ctx.model_policy_path.read_text(encoding="utf-8")) if ctx.model_policy_path.exists() else {}
        ctx.model_policy_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        ctx.instinct.record_config_version("model_policy", payload, changed_by="console", reason="console_update")
        ctx.sync_instinct_provider_rations_from_policy(payload, overwrite=True)
        ctx.audit_console("update", "model_policy", before, payload)
        return {"ok": True}

    @app.get("/console/model-policy/versions")
    def model_policy_versions(limit: int = 50):
        return ctx.instinct.versions("model_policy", limit=limit)

    @app.post("/console/model-policy/rollback/{version}")
    def rollback_model_policy(version: int):
        versions = ctx.instinct.versions("model_policy", limit=500)
        row = next((item for item in versions if int(item.get("version") or 0) == int(version)), None)
        if not row:
            raise HTTPException(status_code=404, detail="version_not_found")
        payload = json.loads(row.get("value_json") or "{}")
        before = json.loads(ctx.model_policy_path.read_text(encoding="utf-8")) if ctx.model_policy_path.exists() else {}
        ctx.model_policy_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        ctx.instinct.record_config_version("model_policy", payload, changed_by="console", reason=f"rollback_to_v{version}")
        ctx.sync_instinct_provider_rations_from_policy(payload, overwrite=True)
        ctx.audit_console("rollback", "model_policy", before, payload)
        return {"ok": True, "version": version}

    @app.get("/console/model-canon")
    def get_model_canon():
        return json.loads(ctx.model_registry_path.read_text(encoding="utf-8")) if ctx.model_registry_path.exists() else {}

    @app.put("/console/model-canon")
    async def put_model_canon(request: Request):
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="model_registry_must_be_object")
        try:
            ctx.validate_model_registry(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        before = json.loads(ctx.model_registry_path.read_text(encoding="utf-8")) if ctx.model_registry_path.exists() else {}
        ctx.model_registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        ctx.instinct.record_config_version("model_registry", payload, changed_by="console", reason="console_update")
        ctx.audit_console("update", "model_registry", before, payload)
        return {"ok": True}

    @app.get("/console/model-canon/versions")
    def model_canon_versions(limit: int = 50):
        return ctx.instinct.versions("model_registry", limit=limit)

    @app.post("/console/model-canon/rollback/{version}")
    def rollback_model_canon(version: int):
        versions = ctx.instinct.versions("model_registry", limit=500)
        row = next((item for item in versions if int(item.get("version") or 0) == int(version)), None)
        if not row:
            raise HTTPException(status_code=404, detail="version_not_found")
        payload = json.loads(row.get("value_json") or "{}")
        before = json.loads(ctx.model_registry_path.read_text(encoding="utf-8")) if ctx.model_registry_path.exists() else {}
        ctx.model_registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        ctx.instinct.record_config_version("model_registry", payload, changed_by="console", reason=f"rollback_to_v{version}")
        ctx.audit_console("rollback", "model_registry", before, payload)
        return {"ok": True, "version": version}

    @app.get("/console/system/storage")
    def console_system_storage():
        cfg = load_storage_roots(ctx.state)
        status = storage_status(ctx.state)
        return {
            "vault_root": cfg["vault_root"],
            "offering_root": cfg["offering_root"],
            "ready": bool(status.get("ready")),
            "vault_ready": bool(status.get("vault_ready")),
            "offering_ready": bool(status.get("offering_ready")),
        }

    @app.put("/console/system/storage")
    async def console_put_system_storage(request: Request):
        body = await request.json()
        vault_root = str(body.get("vault_root") or "").strip()
        offering_root = str(body.get("offering_root") or "").strip()
        if not vault_root or not offering_root:
            raise HTTPException(status_code=400, detail="vault_root_and_offering_root_required")
        before = load_storage_roots(ctx.state)
        cfg = save_storage_roots(ctx.state, vault_root=vault_root, offering_root=offering_root, updated_utc=ctx.utc())
        Path(cfg["vault_root"]).expanduser().mkdir(parents=True, exist_ok=True)
        Path(cfg["offering_root"]).expanduser().mkdir(parents=True, exist_ok=True)
        ctx.audit_console("update", "managed_storage", before, cfg)
        return {
            **cfg,
            "ready": True,
            "vault_ready": True,
            "offering_ready": True,
        }
