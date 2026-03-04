"""Daemon API — FastAPI application with Portal and Console routes."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from fabric.memory import MemoryFabric
from fabric.playbook import PlaybookFabric
from fabric.compass import CompassFabric
from spine.nerve import Nerve
from spine.trace import Tracer
from spine.registry import SpineRegistry
from spine.routines import SpineRoutines
from runtime.cortex import Cortex
from services.dispatch import Dispatch
from services.delivery import DeliveryService
from services.dialog import DialogService
from services.scheduler import Scheduler


def _daemon_home() -> Path:
    return Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))


def _openclaw_home() -> Path:
    v = os.environ.get("OPENCLAW_HOME")
    return Path(v) if v else _daemon_home() / "openclaw"


def create_app() -> FastAPI:
    home = _daemon_home()
    oc_home = _openclaw_home()
    state = home / "state"

    # Initialize Fabric.
    memory = MemoryFabric(state / "memory.db")
    playbook = PlaybookFabric(state / "playbook.db")
    compass = CompassFabric(state / "compass.db")

    # Initialize infrastructure.
    cortex = Cortex(compass)
    nerve = Nerve()
    tracer = Tracer(state / "traces")

    # Initialize Spine.
    registry_path = home / "config" / "spine_registry.json"
    registry = SpineRegistry(registry_path)
    routines = SpineRoutines(
        memory=memory, playbook=playbook, compass=compass,
        cortex=cortex, nerve=nerve, tracer=tracer,
        daemon_home=home, openclaw_home=oc_home,
    )
    scheduler = Scheduler(registry, routines, compass, nerve, state)

    # Initialize Services.
    dispatch = Dispatch(playbook, compass, nerve, state)
    delivery = DeliveryService(compass, nerve, home)
    dialog = DialogService(compass, oc_home)

    app = FastAPI(title="Daemon API", version="0.1.0")

    @app.on_event("startup")
    async def _startup():
        await scheduler.start()

    @app.on_event("shutdown")
    async def _shutdown():
        await scheduler.stop()

    # ── Health ────────────────────────────────────────────────────────────────

    @app.get("/health")
    def health():
        gate_path = state / "gate.json"
        gate = {"status": "GREEN"}
        if gate_path.exists():
            try:
                gate = json.loads(gate_path.read_text())
            except Exception as exc:
                logger.warning("Failed to read gate.json: %s", exc)
        return {"ok": True, "gate": gate["status"]}

    # ── Task submission (Portal) ───────────────────────────────────────────────

    @app.post("/submit")
    async def submit_task(request: Request):
        plan = await request.json()
        result = await dispatch.submit(plan)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result

    @app.get("/tasks")
    def list_tasks(status: str | None = None, limit: int = 50):
        tasks_path = state / "tasks.json"
        if not tasks_path.exists():
            return []
        try:
            tasks = json.loads(tasks_path.read_text())
        except Exception as exc:
            logger.warning("Failed to read tasks.json: %s", exc)
            return []
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        return tasks[-limit:]

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str):
        tasks_path = state / "tasks.json"
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read tasks.json: %s", exc)
            tasks = []
        for t in tasks:
            if t.get("task_id") == task_id:
                return t
        raise HTTPException(status_code=404, detail="task not found")

    # ── Chat (Portal) ─────────────────────────────────────────────────────────

    @app.post("/chat/session")
    def new_chat_session():
        sid = dialog.new_session()
        return {"session_id": sid}

    @app.post("/chat/{session_id}")
    async def chat(session_id: str, request: Request):
        body = await request.json()
        message = str(body.get("message") or "")
        if not message:
            raise HTTPException(status_code=400, detail="message required")
        result = dialog.chat(session_id, message)
        if not result.get("ok"):
            raise HTTPException(status_code=502, detail=result.get("error"))
        return result

    # ── Outcome (Portal) ──────────────────────────────────────────────────────

    @app.get("/outcome")
    def list_outcomes(limit: int = 50):
        index_path = home / "outcome" / "index.json"
        try:
            index = json.loads(index_path.read_text()) if index_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read outcome index: %s", exc)
            index = []
        return list(reversed(index))[:limit]

    @app.get("/outcome/{path:path}")
    def get_outcome_file(path: str):
        full = home / "outcome" / path
        if not full.exists():
            raise HTTPException(status_code=404)
        return FileResponse(full)

    # ── Console — System overview ──────────────────────────────────────────────

    @app.get("/console/overview")
    def console_overview():
        gate_path = state / "gate.json"
        gate = {"status": "GREEN"}
        if gate_path.exists():
            try:
                gate = json.loads(gate_path.read_text())
            except Exception as exc:
                logger.warning("Failed to read gate.json: %s", exc)
        tasks_path = state / "tasks.json"
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read tasks.json: %s", exc)
            tasks = []
        running = [t for t in tasks if t.get("status") == "running"]
        return {
            "gate": gate,
            "running_tasks": len(running),
            "memory": memory.stats(),
            "playbook": playbook.stats(),
            "compass": compass.stats(),
            "cortex_usage": cortex.usage_today(),
        }

    # ── Console — Spine ───────────────────────────────────────────────────────

    @app.get("/console/spine/status")
    def spine_status():
        return scheduler.status()

    @app.post("/console/spine/{routine}/trigger")
    async def spine_trigger(routine: str):
        full_name = routine if routine.startswith("spine.") else f"spine.{routine}"
        result = await scheduler.trigger(full_name)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result

    @app.get("/console/spine/nerve/events")
    def nerve_events(limit: int = 50):
        return nerve.recent(limit)

    # ── Console — Fabric ──────────────────────────────────────────────────────

    @app.get("/console/fabric/memory")
    def fabric_memory(domain: str | None = None, tier: str | None = None, since: str | None = None, keyword: str | None = None, limit: int = 50):
        return memory.query(domain=domain, tier=tier, since=since, keyword=keyword, limit=limit)

    @app.get("/console/fabric/memory/{unit_id}")
    def fabric_memory_unit(unit_id: str):
        unit = memory.get(unit_id)
        if not unit:
            raise HTTPException(status_code=404)
        return unit

    @app.get("/console/fabric/playbook")
    def fabric_playbook(status: str | None = None, category: str = "dag_pattern"):
        if status == "active":
            return playbook.consult(category=category)
        return playbook.consult(category=category)

    @app.get("/console/fabric/playbook/{method_id}")
    def fabric_playbook_method(method_id: str):
        m = playbook.get(method_id)
        if not m:
            raise HTTPException(status_code=404)
        return m

    @app.get("/console/fabric/compass/priorities")
    def compass_priorities():
        return compass.get_priorities()

    @app.get("/console/fabric/compass/budgets")
    def compass_budgets():
        return compass.all_budgets()

    @app.get("/console/fabric/compass/signals")
    def compass_signals():
        return compass.active_signals()

    # ── Console — Policy ─────────────────────────────────────────────────────

    @app.get("/console/policy/{policy_name}")
    def get_policy(policy_name: str):
        profile = compass.get_quality_profile(policy_name)
        return {"policy": policy_name, "rules": profile}

    @app.put("/console/policy/{policy_name}")
    async def set_policy(policy_name: str, request: Request):
        body = await request.json()
        rules = body.get("rules") or body
        compass.set_quality_profile(policy_name, rules, changed_by="console")
        nerve.emit("fabric_updated", {"fabric": "compass", "key": f"quality.{policy_name}"})
        return {"ok": True}

    @app.get("/console/policy/{policy_name}/versions")
    def policy_versions(policy_name: str):
        return compass.versions(f"quality.{policy_name}")

    @app.post("/console/policy/{policy_name}/rollback/{version}")
    def policy_rollback(policy_name: str, version: int):
        ok = compass.rollback(f"quality.{policy_name}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        nerve.emit("fabric_updated", {"fabric": "compass", "key": f"quality.{policy_name}"})
        return {"ok": True}

    # ── Console — Traces ──────────────────────────────────────────────────────

    @app.get("/console/traces")
    def list_traces(routine: str | None = None, status: str | None = None, degraded: bool | None = None, limit: int = 50):
        return tracer.query(routine=routine, status=status, degraded=degraded, limit=limit)

    @app.get("/console/traces/{trace_id}")
    def get_trace(trace_id: str):
        for t in tracer.recent(500):
            if t.get("trace_id") == trace_id:
                return t
        raise HTTPException(status_code=404)

    # ── Console — Cortex usage ────────────────────────────────────────────────

    @app.get("/console/cortex/usage")
    def cortex_usage():
        return cortex.usage_today()

    # ── Console — Schedules ───────────────────────────────────────────────────

    @app.get("/console/schedules")
    def list_schedules():
        return scheduler.status()

    @app.post("/console/schedules/{routine}/trigger")
    async def trigger_schedule(routine: str):
        return await spine_trigger(routine)

    # ── Console — Agent manager ───────────────────────────────────────────────

    @app.get("/console/agents")
    def list_agents():
        cfg_path = oc_home / "openclaw.json"
        if not cfg_path.exists():
            return []
        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception as exc:
            logger.warning("Failed to read openclaw.json: %s", exc)
            return []
        agents = cfg.get("agents", {}).get("list", [])
        result = []
        for agent in agents:
            agent_id = agent.get("id", "")
            workspace = oc_home / "workspace" / agent_id
            skills_dir = workspace / "skills"
            skills_count = len(list(skills_dir.glob("*.json"))) if skills_dir.exists() else 0
            result.append({
                "id": agent_id,
                "workspace_exists": workspace.exists(),
                "skills_count": skills_count,
            })
        return result

    # ── Console — Priority management ─────────────────────────────────────────

    @app.put("/console/fabric/compass/priorities/{domain}")
    async def set_priority(domain: str, request: Request):
        body = await request.json()
        weight = float(body.get("weight") or 1.0)
        reason = str(body.get("reason") or "")
        compass.set_priority(domain, weight, reason, changed_by="console")
        nerve.emit("fabric_updated", {"fabric": "compass", "key": f"priority.{domain}"})
        return {"ok": True}

    # ── Serve static interfaces ────────────────────────────────────────────────

    portal_dir = home / "interfaces" / "portal"
    console_dir = home / "interfaces" / "console"
    if portal_dir.exists():
        app.mount("/portal", StaticFiles(directory=portal_dir, html=True), name="portal")
    if console_dir.exists():
        app.mount("/console", StaticFiles(directory=console_dir, html=True), name="console")

    return app
