"""Health/Task/Outcome/Overview routes extracted from monolithic services.api."""
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
    store: StateStore,
    cortex: Any,
    model_policy_path: Path,
    model_registry_path: Path,
    openclaw_home: Path,
    validate_model_registry: Callable[[dict], None],
    task_view: Callable[[dict], dict],
    log_portal_event: Callable[[str, dict[str, Any], Request | None], None],
    require_outcome_root: Callable[[], Path],
    memory: Any,
    playbook: Any,
    compass: Any,
) -> None:
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

    @app.get("/tasks")
    def list_tasks(request: Request, status: str | None = None, limit: int = 50):
        tasks = store.load_tasks()
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        result = [task_view(t) for t in tasks[-limit:]]
        log_portal_event("tasks_list", {"status": status, "count": len(result)}, request)
        return result

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str, request: Request):
        tasks = store.load_tasks()
        for t in tasks:
            if t.get("task_id") == task_id:
                log_portal_event("task_get", {"task_id": task_id, "status": t.get("status", "")}, request)
                return task_view(t)
        log_portal_event("task_not_found", {"task_id": task_id}, request)
        raise HTTPException(status_code=404, detail="task not found")

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
            ts = str(item.get("delivered_utc") or item.get("archived_utc") or "")
            day_key = ts[:10] if len(ts) >= 10 else "unknown"
            entries.append(
                {
                    "path": item.get("path", ""),
                    "title": item.get("title", ""),
                    "task_type": item.get("task_type", ""),
                    "task_id": item.get("task_id", ""),
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
        tasks = store.load_tasks()
        running = [t for t in tasks if t.get("status") == "running"]
        return {
            "gate": gate,
            "running_tasks": len(running),
            "memory": memory.stats(),
            "playbook": playbook.stats(),
            "compass": compass.stats(),
            "cortex_usage": cortex.usage_today(),
        }
