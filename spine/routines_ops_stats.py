"""Spine witness/focus implementations — Ledger-based (replaces Lore/Memory versions)."""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run_witness(self) -> dict:
    """Analyze Ledger stats, generate system health report. Zero LLM cost."""
    with self.trail.span("spine.witness", trigger="adaptive") as ctx:
        recent = self.ledger_stats.recent_deeds(days=7)
        ctx.step("data_collected", {"templates_active": len(recent)})

        if not recent:
            result = {"skipped": True, "reason": "no_recent_data"}
            ctx.set_result(result)
            return result

        # Basic statistics from dag_templates recent activity
        total_tokens = sum(int(d.get("total_tokens_sum") or 0) for d in recent)
        total_duration = sum(float(d.get("total_duration_s") or 0) for d in recent)
        avg_tokens = total_tokens / max(len(recent), 1)
        avg_duration = total_duration / max(len(recent), 1)

        # Per-agent statistics
        agent_stats = self.ledger_stats.agent_summary(days=7)
        ctx.step("agent_stats", {"agents": len(agent_stats)})

        # Skills needing review
        skills_needing_review = self.ledger_stats.skills_needing_review()
        ctx.step("skill_review", {"needs_review": len(skills_needing_review)})

        # Folio progress tracking (from folios.json, not from Lore)
        folios = self._store.load_json("folios.json", [])
        active_folios = [
            f for f in folios
            if isinstance(f, dict) and str(f.get("status") or "").strip() == "active"
        ]

        health = {
            "period": "7d",
            "template_count": len(recent),
            "avg_tokens": int(avg_tokens),
            "avg_duration_s": round(avg_duration, 1),
            "agent_stats": agent_stats,
            "skills_needing_review": skills_needing_review,
            "active_folios": len(active_folios),
            "generated_utc": _utc(),
        }
        self._store.save_json("system_health.json", health)
        ctx.step("health_written", True)

        result = {
            "templates_analyzed": len(recent),
            "avg_tokens": int(avg_tokens),
            "avg_duration_s": round(avg_duration, 1),
            "agents": len(agent_stats),
            "skills_needing_review": len(skills_needing_review),
            "active_folios": len(active_folios),
        }
        ctx.set_result(result)
    return result


def run_focus(self) -> dict:
    """Active folios statistics. Simplified from old Memory-based version."""
    with self.trail.span("spine.focus", trigger="adaptive") as ctx:
        folios = self._store.load_json("folios.json", [])
        active_folios = [
            row for row in folios
            if isinstance(row, dict) and str(row.get("status") or "").strip() == "active"
        ]

        # Ledger global stats
        hints = self.ledger_stats.global_planning_hints()

        result = {
            "active_folios": len(active_folios),
            "dag_template_count": hints.get("dag_template_count", 0),
            "folio_template_count": hints.get("folio_template_count", 0),
        }
        ctx.set_result(result)
    return result
