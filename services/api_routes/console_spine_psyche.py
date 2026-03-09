"""Console Spine/Psyche routes."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException


def register_console_spine_psyche_routes(app: FastAPI, *, ctx: Any) -> None:
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

    @app.get("/console/psyche/memory")
    def psyche_memory(
        domain: str | None = None,
        tier: str | None = None,
        since: str | None = None,
        keyword: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
        dominion_id: str | None = None,
    ):
        return ctx.memory.query(
            domain=domain,
            tier=tier,
            since=since,
            keyword=keyword,
            source_type=source_type,
            limit=limit,
            dominion_id=dominion_id,
        )

    @app.get("/console/psyche/memory/{unit_id}")
    def psyche_memory_unit(unit_id: str):
        unit = ctx.memory.get(unit_id)
        if not unit:
            raise HTTPException(status_code=404)
        return unit

    @app.delete("/console/psyche/memory/{unit_id}")
    def delete_psyche_memory_unit(unit_id: str):
        if not ctx.memory.delete(unit_id):
            raise HTTPException(status_code=404, detail="memory_unit_not_found")
        ctx.audit_console("delete", "memory", {"unit_id": unit_id}, {})
        return {"ok": True, "unit_id": unit_id}

    @app.get("/console/psyche/lore")
    def psyche_lore(
        complexity: str | None = None,
        dominion_id: str | None = None,
        writ_id: str | None = None,
        limit: int = 50,
    ):
        return ctx.lore.list_records(
            complexity=complexity,
            dominion_id=dominion_id,
            writ_id=writ_id,
            limit=max(1, min(limit, 200)),
        )

    @app.get("/console/psyche/lore/{deed_id}")
    def psyche_lore_record(deed_id: str):
        row = ctx.lore.get(deed_id)
        if not row:
            raise HTTPException(status_code=404)
        return row

    @app.delete("/console/psyche/lore/{deed_id}")
    def delete_psyche_lore_record(deed_id: str):
        if not ctx.lore.delete(deed_id):
            raise HTTPException(status_code=404, detail="lore_record_not_found")
        ctx.audit_console("delete", "lore", {"deed_id": deed_id}, {})
        return {"ok": True, "deed_id": deed_id}

    @app.get("/console/psyche/instinct/rations")
    def instinct_rations():
        return ctx.instinct.all_rations()

    @app.get("/console/psyche/instinct/priorities")
    def instinct_priorities():
        rows = []
        health = ctx.ledger.load_json("system_health.json", {})
        dominions = (health.get("dominions") if isinstance(health, dict) else {}) or {}
        for dominion_id, stats in dominions.items():
            if not isinstance(stats, dict):
                continue
            rows.append(
                {
                    "domain": dominion_id,
                    "weight": round(float(stats.get("avg_quality") or 0.0), 3),
                    "source": "witness",
                    "updated_utc": str(health.get("updated_utc") or ""),
                }
            )
        if not rows:
            prefs = ctx.instinct.all_prefs_detailed()
            for pref in prefs[:20]:
                rows.append(
                    {
                        "domain": str(pref.get("pref_key") or ""),
                        "weight": round(float(pref.get("confidence") or 0.0), 3),
                        "source": str(pref.get("source") or "system"),
                        "updated_utc": str(pref.get("updated_utc") or ""),
                    }
                )
        return rows

    @app.get("/console/psyche/instinct/signals")
    def instinct_signals():
        health = ctx.ledger.load_json("system_health.json", {})
        rows = []
        now = str(health.get("updated_utc") or ctx.utc())
        avg_quality = float(health.get("avg_quality") or 0.0) if isinstance(health, dict) else 0.0
        if avg_quality and avg_quality < 0.65:
            rows.append({"domain": "quality", "trend": "avg_quality_below_target", "severity": "high", "observed_utc": now})
        success_rate = float(health.get("success_rate") or 0.0) if isinstance(health, dict) else 0.0
        if success_rate and success_rate < 0.7:
            rows.append({"domain": "delivery", "trend": "success_rate_declining", "severity": "critical", "observed_utc": now})
        conflicts = int(health.get("review_user_conflicts") or 0) if isinstance(health, dict) else 0
        if conflicts:
            rows.append({"domain": "feedback", "trend": f"review_user_conflicts={conflicts}", "severity": "high", "observed_utc": now})
        pending_feedback = len([row for row in ctx.ledger.load_deeds() if str(row.get("deed_status") or "") in {"awaiting_eval", "pending_review"}])
        if pending_feedback:
            rows.append({"domain": "feedback", "trend": f"awaiting_eval={pending_feedback}", "severity": "medium", "observed_utc": ctx.utc()})
        return rows
