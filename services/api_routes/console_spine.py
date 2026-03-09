"""Console Spine routes (Cadence status, Canon dependencies, Nerve events)."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException


def register_console_spine_routes(app: FastAPI, *, ctx: Any) -> None:
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
                    "timeout_s": getattr(rdef, "timeout_s", None),
                    "degraded_mode": rdef.degraded_mode,
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
