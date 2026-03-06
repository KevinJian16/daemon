"""Health/Run/Outcome/Overview routes extracted from services.api."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from services.state_store import StateStore

logger = logging.getLogger(__name__)


def register_basic_routes(
    app: FastAPI,
    *,
    app_started_utc: str,
    ensure_temporal_client: Callable[..., Awaitable[bool]],
    get_temporal_client: Callable[[], Any],
    store: StateStore,
    dispatch: Any,
    cortex: Any,
    model_policy_path: Path,
    model_registry_path: Path,
    openclaw_home: Path,
    validate_model_registry: Callable[[dict], None],
    run_view: Callable[[dict], dict],
    log_portal_event: Callable[[str, dict[str, Any], Request | None], None],
    require_outcome_root: Callable[[], Path],
    memory: Any,
    playbook: Any,
    compass: Any,
) -> None:
    def _run_status(row: dict) -> str:
        return str(row.get("run_status") or "").strip()

    def _filter_rows_by_run_status(rows: list[dict], run_status: str | None) -> list[dict]:
        if not run_status:
            return rows
        target = str(run_status).strip().lower()
        if not target:
            return rows
        out: list[dict] = []
        for row in rows:
            cur = _run_status(row).lower()
            if cur == target:
                out.append(row)
        return out

    @app.get("/health")
    async def health():
        temporal_connected = bool(await ensure_temporal_client(retries=1, delay_s=0.1))
        gate = store.load_gate()
        model_registry_valid = False
        if model_registry_path.exists():
            try:
                reg = json.loads(model_registry_path.read_text(encoding="utf-8"))
                if isinstance(reg, dict):
                    validate_model_registry(reg)
                    model_registry_valid = True
            except Exception:
                model_registry_valid = False
        dependencies = {
            "temporal_connected": temporal_connected,
            "cortex_available": bool(cortex and cortex.is_available()),
            "model_policy_exists": model_policy_path.exists(),
            "model_registry_exists": model_registry_path.exists(),
            "model_registry_valid": model_registry_valid,
            "openclaw_config_exists": (openclaw_home / "openclaw.json").exists(),
        }
        dependencies_ready = (
            dependencies["cortex_available"]
            and dependencies["model_policy_exists"]
            and dependencies["model_registry_exists"]
            and dependencies["model_registry_valid"]
        )
        return {
            "ok": True,
            "gate": gate["status"],
            "app_started_utc": app_started_utc,
            "dependencies": dependencies,
            "dependencies_ready": dependencies_ready,
        }

    @app.get("/runs")
    def list_runs(request: Request, run_status: str | None = None, limit: int = 50):
        rows = _filter_rows_by_run_status(store.load_runs(), run_status)
        result = [run_view(row) for row in rows[-limit:]]
        log_portal_event("runs_list", {"run_status": run_status, "count": len(result)}, request)
        return result

    @app.get("/runs/{run_id}")
    def get_run(run_id: str, request: Request):
        rows = store.load_runs()
        for row in rows:
            if str(row.get("run_id") or "") == run_id:
                log_portal_event("run_get", {"run_id": run_id, "run_status": _run_status(row)}, request)
                return run_view(row)
        log_portal_event("run_not_found", {"run_id": run_id}, request)
        raise HTTPException(status_code=404, detail="run not found")

    @app.post("/runs/{run_id}/retry")
    async def retry_run(run_id: str, request: Request):
        rows = store.load_runs()
        row = next((r for r in rows if str(r.get("run_id") or "") == run_id), None)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="run not found")
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else {}
        if not plan:
            raise HTTPException(status_code=409, detail="run_plan_missing")
        run_status = _run_status(row).lower()
        if run_status not in {"failed", "failed_submission", "queued", "expired", "replay_exhausted"}:
            raise HTTPException(status_code=409, detail=f"retry_not_allowed_for_run_status:{run_status}")
        result = await dispatch.replay(run_id, plan)
        log_portal_event("run_retry", {"run_id": run_id, "result_ok": bool(result.get("ok"))}, request)
        return result

    @app.post("/runs/{run_id}/cancel")
    async def cancel_run(run_id: str, request: Request):
        rows = store.load_runs()
        row = next((r for r in rows if str(r.get("run_id") or "") == run_id), None)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="run not found")

        await ensure_temporal_client(retries=2, delay_s=0.3)
        temporal_client = get_temporal_client()
        workflow_ids = []
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else {}
        campaign_id = str(row.get("campaign_id") or plan.get("campaign_id") or "")
        if campaign_id:
            workflow_ids.append(str(plan.get("_workflow_id") or f"daemon-campaign-{campaign_id}"))
        workflow_ids.append(str(plan.get("_workflow_id") or f"daemon-{run_id}"))

        cancel_error = ""
        if temporal_client:
            for workflow_id in workflow_ids:
                workflow_id = str(workflow_id or "").strip()
                if not workflow_id:
                    continue
                try:
                    await temporal_client.cancel(workflow_id)
                    cancel_error = ""
                    break
                except Exception as exc:
                    cancel_error = str(exc)[:240]

        now = __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime())
        for item in rows:
            if str(item.get("run_id") or "") != run_id:
                continue
            item["run_status"] = "cancelled"
            item["updated_utc"] = now
            if cancel_error:
                item["last_error"] = cancel_error
            break
        store.save_runs(rows)
        log_portal_event("run_cancel", {"run_id": run_id, "cancel_error": cancel_error}, request)
        return {
            "ok": True,
            "run_id": run_id,
            "run_status": "cancelled",
            "cancel_error": cancel_error,
        }

    @app.post("/runs/{run_id}/pause")
    async def pause_run(run_id: str, request: Request):
        # Pause requires workflow-level signal support; current workflows do not expose pause signals yet.
        log_portal_event("run_pause_unsupported", {"run_id": run_id}, request)
        raise HTTPException(status_code=501, detail="run_pause_not_supported")

    @app.post("/runs/{run_id}/redirect")
    async def redirect_run(run_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        instruction = str(body.get("instruction") or "").strip()
        if not instruction:
            raise HTTPException(status_code=400, detail="instruction_required")
        rows = store.load_runs()
        row = next((r for r in rows if str(r.get("run_id") or "") == run_id), None)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="run not found")
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else {}
        redirect_log = plan.get("redirect_log") if isinstance(plan.get("redirect_log"), list) else []
        now = __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime())
        redirect_log.append({"instruction": instruction, "created_utc": now, "source": "portal"})
        plan["redirect_log"] = redirect_log[-50:]
        row["plan"] = plan
        row["updated_utc"] = now
        store.save_runs(rows)
        log_portal_event("run_redirect", {"run_id": run_id, "instruction_len": len(instruction)}, request)
        return {"ok": True, "run_id": run_id, "accepted": True}

    @app.get("/outcome")
    def list_outcomes(request: Request, limit: int = 50):
        outcome_root = require_outcome_root()
        index = store.load_outcome_index(outcome_root)
        log_portal_event("outcome_list", {"limit": limit, "count": min(len(index), limit)}, request)
        return list(reversed(index))[:limit]

    @app.get("/outcome/timeline")
    def outcome_timeline(request: Request, days: int = 30, limit_per_day: int = 50):
        outcome_root = require_outcome_root()
        index = store.load_outcome_index(outcome_root)

        limit_days = max(1, min(days, 365))
        per_day = max(1, min(limit_per_day, 200))

        entries = []
        for item in index:
            ts = str(item.get("delivered_utc") or "")
            day_key = ts[:10] if len(ts) >= 10 else "unknown"
            entries.append(
                {
                    "path": item.get("path", ""),
                    "title": item.get("title", ""),
                    "run_type": item.get("run_type", ""),
                    "run_id": item.get("run_id", ""),
                    "work_scale": item.get("work_scale", ""),
                    "delivered_utc": ts,
                    "day": day_key,
                }
            )
        entries.sort(key=lambda x: x.get("delivered_utc", ""), reverse=True)

        grouped: dict[str, list[dict]] = {}
        for entry in entries:
            day = str(entry.get("day") or "unknown")
            grouped.setdefault(day, [])
            if len(grouped[day]) < per_day:
                grouped[day].append(entry)

        days_sorted = sorted(grouped.keys(), reverse=True)[:limit_days]
        out = [{"day": day, "count": len(grouped.get(day, [])), "items": grouped.get(day, [])} for day in days_sorted]
        log_portal_event("outcome_timeline", {"days": limit_days, "groups": len(out)}, request)
        return {"days": out}

    @app.get("/outcome/{path:path}")
    def get_outcome_file(path: str, request: Request):
        outcome_root = require_outcome_root()
        full = outcome_root / path
        try:
            full.resolve().relative_to(outcome_root.resolve())
        except Exception:
            raise HTTPException(status_code=400, detail="path_outside_outcome_root")
        if not full.exists():
            log_portal_event("outcome_file_missing", {"path": path}, request)
            raise HTTPException(status_code=404)
        log_portal_event("outcome_file_access", {"path": path}, request)
        return FileResponse(full)

    @app.get("/console/overview")
    def console_overview():
        gate = store.load_gate()
        runs = store.load_runs()
        running = [row for row in runs if _run_status(row) == "running"]
        return {
            "gate": gate,
            "running_runs": len(running),
            "memory": memory.stats(),
            "playbook": playbook.stats(),
            "compass": compass.stats(),
            "cortex_usage": cortex.usage_today(),
        }
