"""Spine record routine — write LoreRecord on deed completion."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_record(self, deed_id: str, plan: dict, move_results: list[dict], offering: dict) -> dict:
    """Record completed deed as a LoreRecord in Lore."""
    with self.trail.span("spine.record", trigger="nerve:deed_closed") as ctx:
        success = bool(offering.get("ok"))
        quality_score = float(offering.get("score", 1.0 if success else 0.0))

        brief = plan.get("brief") or {}
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        objective_text = str(brief.get("objective") or plan.get("objective") or plan.get("title") or "")
        dag_budget = int(
            brief.get("dag_budget")
            or metadata.get("dag_budget")
            or plan.get("dag_budget")
            or len(plan.get("moves") or [])
            or 1
        )

        plan_structure = {
            "moves": plan.get("moves", []),
            "slip_title": str(plan.get("slip_title") or plan.get("title") or ""),
        }
        offering_quality = offering.get("global_score_components") or {}
        if not offering_quality and quality_score > 0:
            offering_quality = {"overall": quality_score}

        token_consumption = {}
        for sr in move_results:
            provider = str(sr.get("provider") or "unknown")
            tokens = int(sr.get("tokens_used", 0))
            if tokens > 0:
                token_consumption[provider] = token_consumption.get(provider, 0) + tokens

        duration_s = 0.0
        for sr in move_results:
            duration_s += float(sr.get("elapsed_s", 0))

        user_feedback = offering.get("user_feedback") or plan.get("user_feedback")
        rework_history = plan.get("rework_history")

        objective_embedding = None
        try:
            objective_embedding = self.cortex.embed(objective_text)
        except Exception as exc:
            logger.warning("Failed to compute objective embedding for deed %s: %s", deed_id, exc)

        record_id = self.lore.record(
            deed_id=deed_id,
            objective_text=objective_text,
            dag_budget=dag_budget,
            move_count=len(move_results),
            plan_structure=plan_structure,
            offering_quality=offering_quality,
            token_consumption=token_consumption,
            success=success,
            duration_s=duration_s,
            user_feedback=user_feedback,
            rework_history=rework_history,
            objective_embedding=objective_embedding,
            folio_id=str(metadata.get("folio_id") or plan.get("folio_id") or ""),
            slip_id=str(metadata.get("slip_id") or plan.get("slip_id") or ""),
            writ_id=str(metadata.get("writ_id") or plan.get("writ_id") or ""),
        )
        ctx.step("lore_recorded", {"record_id": record_id, "success": success})

        result = {
            "deed_id": deed_id,
            "record_id": record_id,
            "offering": "success" if success else "failure",
            "quality_score": round(quality_score, 4),
        }
        ctx.set_result(result)
    return result
