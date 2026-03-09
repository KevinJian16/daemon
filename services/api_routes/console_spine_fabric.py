"""Console Spine/Psyche routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_spine_fabric_routes(app: FastAPI, *, ctx: Any) -> None:
    # ── Console — Spine ───────────────────────────────────────────────────────

    @app.get("/console/spine/status")
    def spine_status():
        return ctx.cadence.status()

    @app.get("/console/spine/dependencies")
    def spine_dependencies():
        out = []
        for rdef in ctx.canon.all():
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
        result = await ctx.cadence.trigger(full_name)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result

    @app.get("/console/spine/nerve/events")
    def nerve_events(limit: int = 50):
        return ctx.nerve.recent(limit)

    # ── Console — Psyche ──────────────────────────────────────────────────────

    @app.get("/console/psyche/memory")
    def psyche_memory(
        domain: str | None = None,
        tier: str | None = None,
        since: str | None = None,
        keyword: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
    ):
        return ctx.memory.query(domain=domain, tier=tier, since=since, keyword=keyword, source_type=source_type, limit=limit)

    @app.get("/console/psyche/memory/{unit_id}")
    def psyche_memory_unit(unit_id: str):
        unit = ctx.memory.get(unit_id)
        if not unit:
            raise HTTPException(status_code=404)
        return unit

    @app.get("/console/psyche/lore")
    def psyche_lore(complexity: str | None = None, limit: int = 50):
        return ctx.lore.consult(complexity=complexity, top_k=max(1, min(limit, 200)))

    @app.get("/console/psyche/lore/{method_id}")
    def psyche_lore_method(method_id: str):
        m = ctx.lore.get(method_id)
        if not m:
            raise HTTPException(status_code=404)
        return m

    @app.get("/console/psyche/instinct/rations")
    def instinct_rations():
        return ctx.instinct.all_rations()

    @app.get("/console/psyche/instinct/priorities")
    def instinct_priorities():
        return ctx.instinct.all_prefs_detailed()
