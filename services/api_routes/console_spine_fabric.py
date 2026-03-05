"""Console Spine/Fabric routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_spine_fabric_routes(app: FastAPI, *, ctx: Any) -> None:
    # ── Console — Spine ───────────────────────────────────────────────────────

    @app.get("/console/spine/status")
    def spine_status():
        return ctx.scheduler.status()

    @app.get("/console/spine/dependencies")
    def spine_dependencies():
        out = []
        for rdef in ctx.registry.all():
            out.append(
                {
                    "routine": rdef.name,
                    "depends_on": list(rdef.depends_on or []),
                    "reads": list(rdef.reads or []),
                    "writes": list(rdef.writes or []),
                    "mode": rdef.mode,
                }
            )
        return out

    @app.post("/console/spine/{routine}/trigger")
    async def spine_trigger(routine: str):
        full_name = routine if routine.startswith("spine.") else f"spine.{routine}"
        result = await ctx.scheduler.trigger(full_name)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result

    @app.get("/console/spine/nerve/events")
    def nerve_events(limit: int = 50):
        return ctx.nerve.recent(limit)

    # ── Console — Fabric ──────────────────────────────────────────────────────

    @app.get("/console/fabric/memory")
    def fabric_memory(
        domain: str | None = None,
        tier: str | None = None,
        since: str | None = None,
        keyword: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
    ):
        return ctx.memory.query(domain=domain, tier=tier, since=since, keyword=keyword, source_type=source_type, limit=limit)

    @app.get("/console/fabric/memory/{unit_id}")
    def fabric_memory_unit(unit_id: str):
        unit = ctx.memory.get(unit_id)
        if not unit:
            raise HTTPException(status_code=404)
        return unit

    @app.get("/console/fabric/playbook")
    def fabric_playbook(status: str | None = None, category: str = "dag_pattern"):
        return ctx.playbook.list_methods(status=status, category=category, limit=200)

    @app.get("/console/fabric/playbook/{method_id}")
    def fabric_playbook_method(method_id: str):
        m = ctx.playbook.get(method_id)
        if not m:
            raise HTTPException(status_code=404)
        return m

    @app.get("/console/fabric/compass/priorities")
    def compass_priorities():
        return ctx.compass.get_priorities()

    @app.get("/console/fabric/compass/budgets")
    def compass_budgets():
        return ctx.compass.all_budgets()

    @app.get("/console/fabric/compass/signals")
    def compass_signals():
        return ctx.compass.active_signals()

    # ── Console — Priority management ─────────────────────────────────────────

    @app.put("/console/fabric/compass/priorities/{domain}")
    async def set_priority(domain: str, request: Request):
        body = await request.json()
        weight = float(body.get("weight") or 1.0)
        reason = str(body.get("reason") or "")
        ctx.compass.set_priority(domain, weight, reason, changed_by="console")
        ctx.nerve.emit("fabric_updated", {"fabric": "compass", "key": f"priority.{domain}"})
        return {"ok": True}
