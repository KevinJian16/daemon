"""Spine witness/distill/learn/focus implementations (V2 aligned)."""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
        review_user_conflicts = 0
        for r in records:
            fb = r.get("user_feedback") if isinstance(r.get("user_feedback"), dict) else {}
            oq = r.get("offering_quality") if isinstance(r.get("offering_quality"), dict) else {}
            try:
                user_score = float(fb.get("score")) if fb.get("score") is not None else None
            except Exception:
                user_score = None
            dims = [float(v) for v in oq.values() if isinstance(v, (int, float))]
            qa_score = (sum(dims) / len(dims)) if dims else None
            if user_score is not None and qa_score is not None and user_score <= 0.4 and qa_score >= 0.8:
                review_user_conflicts += 1
        ctx.step("stats_computed", {
            "success_rate": round(success_rate, 3),
            "rework_rate": round(rework_rate, 3),
            "avg_quality": round(avg_quality, 3),
            "feedback_dist": feedback_dist,
            "review_user_conflicts": review_user_conflicts,
        })

        folio_stats: dict[str, dict] = {}
        for r in records:
            folio_id = str(r.get("folio_id") or "").strip()
            if not folio_id:
                continue
            row = folio_stats.setdefault(
                folio_id,
                {"count": 0, "success": 0, "quality_sum": 0.0, "quality_n": 0, "latest_deed_id": "", "latest_objective": ""},
            )
            row["count"] += 1
            if r.get("success"):
                row["success"] += 1
            oq = r.get("offering_quality") if isinstance(r.get("offering_quality"), dict) else {}
            dims = [float(v) for v in oq.values() if isinstance(v, (int, float))]
            if dims:
                row["quality_sum"] += sum(dims) / len(dims)
                row["quality_n"] += 1
            deed_id = str(r.get("deed_id") or "")
            if deed_id:
                row["latest_deed_id"] = deed_id
            objective = str(r.get("objective_text") or "")
            if objective:
                row["latest_objective"] = objective[:240]

        health = {
            "success_rate": round(success_rate, 4),
            "rework_rate": round(rework_rate, 4),
            "avg_quality": round(avg_quality, 4),
            "feedback_distribution": feedback_dist,
            "review_user_conflicts": review_user_conflicts,
            "sample_size": len(records),
            "folios": {
                folio_id: {
                    "count": row["count"],
                    "success_rate": round(row["success"] / max(row["count"], 1), 4),
                    "avg_quality": round(row["quality_sum"] / max(row["quality_n"], 1), 4) if row["quality_n"] else 0.0,
                }
                for folio_id, row in folio_stats.items()
            },
        }
        self._store.save_json("system_health.json", health)
        ctx.step("health_written", True)

        if success_rate < 0.5:
            self.instinct.observe_pref("default_depth", "scrutiny")
        if avg_quality > 0.8 and success_rate > 0.8:
            self.instinct.observe_pref("default_depth", "study")

        folios = self._store.load_json("folios.json", [])
        if isinstance(folios, list) and folio_stats:
            changed = False
            progress_updates = 0
            completion_candidates = 0
            for folio in folios:
                if not isinstance(folio, dict):
                    continue
                folio_id = str(folio.get("folio_id") or "").strip()
                if folio_id not in folio_stats:
                    continue
                stats = folio_stats[folio_id]
                progress_notes = folio.get("progress_notes") if isinstance(folio.get("progress_notes"), list) else []
                latest_deed_id = str(stats.get("latest_deed_id") or "")
                if latest_deed_id and not any(str(note.get("deed_id") or "") == latest_deed_id for note in progress_notes if isinstance(note, dict)):
                    avg = round(stats["quality_sum"] / max(stats["quality_n"], 1), 3) if stats["quality_n"] else 0.0
                    note = {
                        "deed_id": latest_deed_id,
                        "created_utc": self._store.load_ward().get("updated_utc") or "",
                        "summary": f"Recent progress: {stats['latest_objective']} (quality={avg})".strip(),
                    }
                    progress_notes.append(note)
                    folio["progress_notes"] = progress_notes[-100:]
                    folio["updated_utc"] = _utc()
                    changed = True
                    progress_updates += 1
                    try:
                        self.nerve.emit(
                            "folio_progress_update",
                            {
                                "folio_id": folio_id,
                                "deed_id": latest_deed_id,
                                "summary": note["summary"],
                            },
                        )
                    except Exception:
                        pass
                if (
                    str(folio.get("status") or "").strip() == "active"
                    and stats["count"] >= 3
                    and stats["success"] >= max(2, stats["count"] - 1)
                    and (stats["quality_sum"] / max(stats["quality_n"], 1) if stats["quality_n"] else 0.0) >= 0.85
                ):
                    completion_candidates += 1
                    try:
                        self.nerve.emit(
                            "folio_goal_candidate_completed",
                            {
                                "folio_id": folio_id,
                                "objective": str(folio.get("title") or folio.get("objective") or ""),
                            },
                        )
                    except Exception:
                        pass
            if changed:
                self._store.save_json("folios.json", folios)
            ctx.step("folio_progress", {"updated": progress_updates, "completion_candidates": completion_candidates})

        result = {
            "analyzed": len(records),
            "success_rate": round(success_rate, 3),
            "rework_rate": round(rework_rate, 3),
            "avg_quality": round(avg_quality, 3),
            "feedback_dist": feedback_dist,
            "review_user_conflicts": review_user_conflicts,
            "folios": len(folio_stats),
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
            "merged": distill_result.get("merged", 0),
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

        move_outputs = list(deed_root.glob("moves/*/output/output.md"))
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
        upgraded = 0
        for entry in analysis.get("entries", []):
            content = str(entry.get("content") or "").strip()
            if not content or len(content) < 10:
                continue
            tags = [str(t) for t in (entry.get("tags") or []) if str(t).strip()]
            # Ensure tier:working tag for newly extracted knowledge.
            if not any(t.startswith("tier:") for t in tags):
                tags.append("tier:working")

            embedding = None
            try:
                embedding = self.cortex.embed(content)
            except Exception:
                pass

            result_info = self.memory.upsert(
                content=content, tags=tags, embedding=embedding, source=f"learn:{deed_id}",
            )
            extracted += 1

            # If upsert found a duplicate (updated existing entry), upgrade tier to deep.
            # This means the same fact was extracted from multiple Deeds — high confidence.
            if result_info.get("action") == "updated":
                self._upgrade_tier(result_info["entry_id"], "deep")
                upgraded += 1

        ctx.step("learn_done", {"extracted": extracted, "upgraded_to_deep": upgraded})
        result = {
            "deed_id": deed_id,
            "extracted": extracted,
            "upgraded_to_deep": upgraded,
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

        folios = self._store.load_json("folios.json", [])
        active_folios = [
            row for row in folios
            if isinstance(row, dict) and str(row.get("status") or "").strip() == "active"
        ]

        result = {
            "total_entries": mem_stats.get("total_entries", 0),
            "with_embedding": mem_stats.get("with_embedding", 0),
            "active_folios": len(active_folios),
        }
        ctx.set_result(result)
    return result
