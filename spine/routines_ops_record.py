"""Spine record routine — merge accepted deed into dag_templates (replaces Lore recording)."""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run_record(self, deed_id: str, plan: dict, move_results: list[dict],
               offering: dict, eval_chain: list[str] | None = None,
               accepted: bool | None = None) -> dict:
    """Merge accepted deed into dag_templates. Zero LLM cost (except one embed call)."""
    with self.trail.span("spine.record", trigger="nerve:deed_closed") as ctx:
        # Determine acceptance from offering if not explicit
        if accepted is None:
            accepted = bool(offering.get("ok"))

        if not accepted:
            result = {"deed_id": deed_id, "recorded": False, "reason": "not_accepted"}
            ctx.set_result(result)
            return result

        brief = plan.get("brief") or {}
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        objective = str(
            brief.get("objective")
            or plan.get("deed_title")
            or plan.get("title")
            or ""
        )
        dag_structure = plan.get("design") or plan.get("moves") or {}

        # Aggregate stats from move results
        tokens: dict[str, int] = {}
        duration = 0.0
        rework_count = 0
        for m in move_results:
            if not isinstance(m, dict):
                continue
            # Token consumption
            t = m.get("token_consumption") if isinstance(m.get("token_consumption"), dict) else {}
            for k, v in t.items():
                tokens[k] = tokens.get(k, 0) + int(v or 0)
            # Also check provider/tokens_used format
            provider = str(m.get("provider") or "unknown")
            tokens_used = int(m.get("tokens_used") or 0)
            if tokens_used > 0:
                tokens[provider] = tokens.get(provider, 0) + tokens_used
            # Duration
            duration += float(m.get("duration_s") or m.get("elapsed_s") or 0)
            # Rework detection
            if m.get("is_rework"):
                rework_count += 1

        ctx.step("stats_aggregated", {
            "total_tokens": sum(tokens.values()),
            "duration_s": round(duration, 1),
            "rework_count": rework_count,
        })

        # Embedding for similarity matching (one cheap embed call)
        emb = None
        try:
            emb = self.cortex.try_or_degrade(
                lambda: self.cortex.embed(objective[:500]),
                lambda: None,
            )
        except Exception as exc:
            logger.warning("Embedding failed for deed %s: %s", deed_id, exc)

        # Merge into dag_templates
        eval_text = "\n".join(eval_chain) if eval_chain else ""
        template_id = self.ledger_stats.merge_dag_template(
            objective_text=objective[:500],
            objective_emb=emb,
            dag_structure=dag_structure,
            eval_summary=eval_text,
            total_tokens=sum(tokens.values()),
            total_duration_s=duration,
            rework_count=rework_count,
        )
        ctx.step("dag_template_merged", {"template_id": template_id})

        # Update skill and agent stats
        self.ledger_stats.update_skill_stats(plan, accepted=True)
        self.ledger_stats.update_agent_stats(move_results, accepted=True)
        ctx.step("stats_updated")

        result = {
            "deed_id": deed_id,
            "recorded": True,
            "merged_to_template": True,
            "template_id": template_id,
        }
        ctx.set_result(result)
    return result
