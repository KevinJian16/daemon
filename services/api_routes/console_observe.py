"""Console trails, usage, schedules routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_observe_routes(app: FastAPI, *, ctx: Any) -> None:
    # ── Console — Trails ──────────────────────────────────────────────────────

    @app.get("/console/trails")
    def list_trails(
        routine: str | None = None,
        status: str | None = None,
        degraded: bool | None = None,
        since: str | None = None,
        limit: int = 50,
    ):
        return ctx.trail.query(routine=routine, status=status, degraded=degraded, since=since, limit=limit)

    @app.get("/console/trails/{trail_id}")
    def get_trail(trail_id: str):
        trail_record = ctx.trail.get(trail_id)
        if trail_record:
            rows = ctx.cortex.usage_for_trail(trail_id, limit=200)
            by_provider: dict[str, dict] = {}
            errors: list[dict] = []
            for r in rows:
                provider = str(r.get("provider") or "unknown")
                agg = by_provider.setdefault(
                    provider,
                    {"calls": 0, "in_tokens": 0, "out_tokens": 0, "errors": 0, "avg_elapsed_s": 0.0},
                )
                agg["calls"] += 1
                agg["in_tokens"] += int(r.get("in_tokens") or 0)
                agg["out_tokens"] += int(r.get("out_tokens") or 0)
                if not r.get("success"):
                    agg["errors"] += 1
                agg["avg_elapsed_s"] += float(r.get("elapsed_s") or 0)
                if r.get("error"):
                    errors.append(
                        {
                            "provider": provider,
                            "timestamp": r.get("timestamp", ""),
                            "error": str(r.get("error", ""))[:200],
                        }
                    )
            for agg in by_provider.values():
                if agg["calls"] > 0:
                    agg["avg_elapsed_s"] = round(agg["avg_elapsed_s"] / agg["calls"], 3)
            trace_out = dict(trail_record)
            trace_out["cortex_summary"] = {
                "total_calls": len(rows),
                "total_in_tokens": sum(int(r.get("in_tokens") or 0) for r in rows),
                "total_out_tokens": sum(int(r.get("out_tokens") or 0) for r in rows),
                "by_provider": by_provider,
                "latest_calls": rows[-5:],
                "errors": errors[-10:],
            }
            return trace_out
        raise HTTPException(status_code=404)

    # ── Console — Cortex usage ────────────────────────────────────────────────

    @app.get("/console/cortex/usage")
    def cortex_usage(since: str | None = None, until: str | None = None, limit: int = 500):
        return {
            "today": ctx.cortex.usage_today(),
            "records": ctx.cortex.usage_between(since=since, until=until, limit=limit),
        }

    # ── Console — Schedules ───────────────────────────────────────────────────

    @app.get("/console/schedules")
    def list_schedules():
        return ctx.cadence.status()

    @app.get("/console/schedules/history")
    def list_schedule_history(routine: str | None = None, limit: int = 100):
        return ctx.cadence.history(routine=routine, limit=limit)

    @app.put("/console/schedules/{job_id}")
    async def update_schedule(job_id: str, request: Request):
        body = await request.json()
        schedule = body.get("schedule") if "schedule" in body else None
        enabled = body.get("enabled") if "enabled" in body else None
        result = ctx.cadence.update_schedule(job_id, schedule=schedule, enabled=enabled)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result)
        return result

    @app.post("/console/schedules/{routine}/trigger")
    async def trigger_schedule(routine: str):
        full_name = routine if routine.startswith("spine.") else f"spine.{routine}"
        result = await ctx.cadence.trigger(full_name)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result
