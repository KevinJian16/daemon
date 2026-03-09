"""Spine witness/distill/learn/focus implementations (V2 aligned)."""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def run_witness(self) -> dict:
    """Analyze recent Lore records; update Instinct preferences and system health."""
    with self.trail.span("spine.witness", trigger="adaptive") as ctx:
        records = self.lore.list_records(limit=20)
        ctx.step("data_collected", {"records": len(records)})

        if len(records) < 3:
            result = {"skipped": True, "reason": "insufficient_data"}
            ctx.set_result(result)
            return result

        success_count = sum(1 for r in records if r.get("success"))
        success_rate = success_count / max(len(records), 1)
        rework_count = sum(1 for r in records if r.get("rework_history"))
        rework_rate = rework_count / max(len(records), 1)

        feedback_dist: dict[str, int] = {}
        for r in records:
            fb = r.get("user_feedback")
            if isinstance(fb, dict) and fb.get("overall"):
                overall = str(fb["overall"])
                feedback_dist[overall] = feedback_dist.get(overall, 0) + 1

        quality_scores = []
        for r in records:
            oq = r.get("offering_quality")
            if isinstance(oq, dict):
                scores = [float(v) for v in oq.values() if isinstance(v, (int, float))]
                if scores:
                    quality_scores.append(sum(scores) / len(scores))

        avg_quality = sum(quality_scores) / max(len(quality_scores), 1) if quality_scores else 0.0
        ctx.step("stats_computed", {
            "success_rate": round(success_rate, 3),
            "rework_rate": round(rework_rate, 3),
            "avg_quality": round(avg_quality, 3),
            "feedback_dist": feedback_dist,
        })

        health = {
            "success_rate": round(success_rate, 4),
            "rework_rate": round(rework_rate, 4),
            "avg_quality": round(avg_quality, 4),
            "feedback_distribution": feedback_dist,
            "sample_size": len(records),
        }
        self._store.save_json("system_health.json", health)
        ctx.step("health_written", True)

        if success_rate < 0.5:
            self.instinct.observe_pref("default_depth", "scrutiny")
        if avg_quality > 0.8 and success_rate > 0.8:
            self.instinct.observe_pref("default_depth", "study")

        result = {
            "analyzed": len(records),
            "success_rate": round(success_rate, 3),
            "rework_rate": round(rework_rate, 3),
            "avg_quality": round(avg_quality, 3),
            "feedback_dist": feedback_dist,
        }
        ctx.set_result(result)
    return result


def run_distill(self) -> dict:
    """Memory decay + capacity enforcement."""
    with self.trail.span("spine.distill", trigger="daily") as ctx:
        distill_result = self.memory.distill()
        ctx.step("distill_done", distill_result)
        result = {
            "decayed": distill_result.get("decayed", 0),
            "evicted": distill_result.get("evicted", 0),
        }
        ctx.set_result(result)
    return result


def run_learn(self, deed_id: str | None = None) -> dict:
    """Extract knowledge from retinue instance workspace to Memory after deed completion."""
    with self.trail.span("spine.learn", trigger="nerve:deed_completed") as ctx:
        if not deed_id:
            result = {"skipped": True, "reason": "no_deed_id"}
            ctx.set_result(result)
            return result

        deed_root = self.state_dir / "deeds" / deed_id
        if not deed_root.exists():
            result = {"skipped": True, "reason": "deed_root_not_found"}
            ctx.set_result(result)
            return result

        move_outputs = list(deed_root.glob("moves/*/output.md"))
        ctx.step("move_outputs_found", len(move_outputs))

        if not move_outputs:
            result = {"extracted": 0, "reason": "no_move_outputs"}
            ctx.set_result(result)
            return result

        combined = ""
        for output_path in move_outputs[:10]:
            try:
                text = output_path.read_text(encoding="utf-8")[:2000]
                combined += f"\n--- {output_path.parent.name} ---\n{text}\n"
            except Exception as exc:
                logger.warning("Failed to read move output %s: %s", output_path, exc)

        def _llm_extract() -> dict:
            return self.cortex.structured(
                f"Extract generalizable knowledge from this deed execution:\n{combined[:4000]}\n\n"
                "Return factual knowledge entries (not task-specific details).",
                schema={
                    "entries": [{"content": "string", "tags": ["string"]}],
                },
                model="analysis",
            )

        def _skip_fallback() -> dict:
            ctx.mark_degraded("Cortex unavailable; skipping learn")
            return {"entries": []}

        analysis = self.cortex.try_or_degrade(_llm_extract, _skip_fallback)

        extracted = 0
        for entry in analysis.get("entries", []):
            content = str(entry.get("content") or "").strip()
            if not content or len(content) < 10:
                continue
            tags = entry.get("tags") or []

            embedding = None
            try:
                embedding = self.cortex.embed(content)
            except Exception:
                pass

            self.memory.upsert(content=content, tags=tags, embedding=embedding, source=f"learn:{deed_id}")
            extracted += 1

        ctx.step("learn_done", {"extracted": extracted})
        result = {
            "deed_id": deed_id,
            "extracted": extracted,
            "move_outputs": len(move_outputs),
            "degraded": ctx._degraded,
        }
        ctx.set_result(result)
    return result


def run_focus(self) -> dict:
    """Embedding index maintenance and attention adjustment."""
    with self.trail.span("spine.focus", trigger="adaptive") as ctx:
        mem_stats = self.memory.stats()
        ctx.step("memory_stats", mem_stats)

        result = {
            "total_entries": mem_stats.get("total_entries", 0),
            "with_embedding": mem_stats.get("with_embedding", 0),
        }
        ctx.set_result(result)
    return result
