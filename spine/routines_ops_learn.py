"""Spine witness/distill/learn/judge/focus implementations."""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def run_witness(self) -> dict:
    with self.tracer.span("spine.witness", trigger="cron") as ctx:
        mem_stats = self.memory.stats()
        pb_stats = self.playbook.stats()
        unanalyzed = self.playbook.unanalyzed_evaluations(limit=50)
        openclaw_obs = self._collect_openclaw_observations()
        interface_obs = self._collect_interface_observations()
        router_patterns = self._read_router_patterns(limit=30)
        trace_obs = self._collect_trace_observations(limit=200)
        cortex_usage = self.cortex.recent_traces(limit=200)
        ctx.step(
            "data_collected",
            {
                "mem_units": mem_stats["total_active"],
                "unanalyzed_evals": len(unanalyzed),
                "session_files": openclaw_obs.get("session_files", 0),
                "portal_events": interface_obs.get("portal_events", 0),
                "telegram_events": interface_obs.get("telegram_events", 0),
                "router_patterns": len(router_patterns),
                "trace_records": trace_obs.get("total_traces", 0),
                "cortex_calls": len(cortex_usage),
            },
        )

        if len(unanalyzed) < 3:
            ctx.step("skip", "not enough unanalyzed evaluations")
            result = {"skipped": True, "reason": "insufficient_data"}
            ctx.set_result(result)
            return result

        by_outcome: dict[str, int] = {}
        for ev in unanalyzed:
            o = ev.get("outcome", "unknown")
            by_outcome[o] = by_outcome.get(o, 0) + 1
        success_rate = by_outcome.get("success", 0) / max(len(unanalyzed), 1)
        ctx.step("stats_computed", {"success_rate": round(success_rate, 3), "by_outcome": by_outcome})

        def _llm_analysis() -> dict:
            summary = json.dumps({
                "memory_stats": mem_stats,
                "playbook_stats": pb_stats,
                "recent_evals": unanalyzed[:10],
                "success_rate": success_rate,
                "openclaw_observations": openclaw_obs,
                "interface_observations": interface_obs,
                "router_patterns": router_patterns[:10],
                "trace_observations": trace_obs,
                "cortex_recent_usage": cortex_usage[-50:],
            }, ensure_ascii=False)
            return self.cortex.structured(
                f"Analyze these system performance metrics and identify patterns:\n{summary}\n\n"
                "Identify: (1) concerning trends, (2) improvement opportunities, (3) attention signals.",
                schema={
                    "observations": ["string"],
                    "attention_signals": [{"domain": "string", "trend": "string", "severity": "normal|high|critical"}],
                },
                model="analysis",
            )

        def _stats_fallback() -> dict:
            ctx.mark_degraded("Cortex unavailable; stats_only mode")
            signals = []
            if success_rate < 0.5:
                signals.append({"domain": "system", "trend": f"low success rate: {success_rate:.1%}", "severity": "high"})
            if int(trace_obs.get("error_traces", 0)) >= 3:
                signals.append({"domain": "spine", "trend": f"trace errors: {trace_obs.get('error_traces', 0)}", "severity": "high"})
            return {"observations": [f"Success rate: {success_rate:.1%}"], "attention_signals": signals}

        analysis = self.cortex.try_or_degrade(_llm_analysis, _stats_fallback)
        ctx.step("analysis_done", {"observations": len(analysis.get("observations", []))})

        critical_signals = 0
        for sig in analysis.get("attention_signals", []):
            sid = self.compass.add_signal(
                domain=sig.get("domain", "system"),
                trend=sig.get("trend", ""),
                severity=sig.get("severity", "normal"),
            )
            if sig.get("severity") == "critical":
                critical_signals += 1
                self.nerve.emit("attention_critical", {"signal_id": sid, "domain": sig["domain"]})

        self.playbook.mark_analyzed([ev["eval_id"] for ev in unanalyzed])

        result = {
            "analyzed": len(unanalyzed),
            "observations": len(analysis.get("observations", [])),
            "signals_added": len(analysis.get("attention_signals", [])),
            "critical_signals": critical_signals,
            "openclaw_sessions_seen": openclaw_obs.get("session_files", 0),
            "portal_events_seen": interface_obs.get("portal_events", 0),
            "telegram_events_seen": interface_obs.get("telegram_events", 0),
            "router_patterns_seen": len(router_patterns),
            "trace_records_seen": trace_obs.get("total_traces", 0),
            "trace_errors_seen": trace_obs.get("error_traces", 0),
            "degraded": ctx._degraded,
        }
        ctx.set_result(result)
    return result


def run_distill(self) -> dict:
    with self.tracer.span("spine.distill", trigger="cron") as ctx:
        units = self.memory.query(limit=200)
        snapshot_path = self._write_tmp_snapshot("distill", {"units": units})
        ctx.step("snapshot_written", str(snapshot_path))
        try:
            units_snapshot = units
            try:
                snap_raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
                if isinstance(snap_raw, dict) and isinstance(snap_raw.get("units"), list):
                    units_snapshot = [u for u in snap_raw.get("units", []) if isinstance(u, dict)]
            except Exception:
                units_snapshot = units
            ctx.step("units_loaded", len(units_snapshot))

            if not units_snapshot:
                result = {"units_processed": 0, "links_created": 0, "archived": 0}
                ctx.set_result(result)
                return result

            def _llm_distill() -> dict:
                titles = [{"unit_id": u["unit_id"], "title": u["title"], "domain": u["domain"]} for u in units_snapshot[:50]]
                return self.cortex.structured(
                    f"Find semantic duplicates and relationships among these knowledge units:\n"
                    f"{json.dumps(titles, ensure_ascii=False)}\n\n"
                    "Return duplicates to merge and semantic links to create.",
                    schema={
                        "duplicates": [{"keep": "unit_id", "merge_from": ["unit_id"]}],
                        "links": [{"from_id": "unit_id", "to_id": "unit_id", "relation": "supports|contradicts|extends"}],
                    },
                    model="analysis",
                )

            def _string_fallback() -> dict:
                ctx.mark_degraded("Cortex unavailable; string_match_only mode")
                seen_titles: dict[str, str] = {}
                duplicates = []
                for u in units_snapshot:
                    t = str(u.get("title") or "").lower().strip()
                    uid = str(u.get("unit_id") or "")
                    if not uid:
                        continue
                    if t in seen_titles:
                        duplicates.append({"keep": seen_titles[t], "merge_from": [uid]})
                    else:
                        seen_titles[t] = uid
                return {"duplicates": duplicates, "links": []}

            analysis = self.cortex.try_or_degrade(_llm_distill, _string_fallback)

            links_created = 0
            for link in analysis.get("links", []):
                from_id = str(link.get("from_id") or "")
                to_id = str(link.get("to_id") or "")
                relation = str(link.get("relation") or "")
                if not from_id or not to_id or not relation:
                    continue
                self.memory.link(from_id, to_id, relation)
                links_created += 1

            unit_by_id = {
                str(u.get("unit_id") or ""): u
                for u in units_snapshot
                if str(u.get("unit_id") or "")
            }
            archived = 0
            archived_ids: set[str] = set()
            for dup in analysis.get("duplicates", []):
                keep_hint = str(dup.get("keep") or "")
                merge_from = [str(x) for x in (dup.get("merge_from") or []) if str(x)]
                ids = [x for x in [keep_hint, *merge_from] if x in unit_by_id]
                if len(ids) <= 1:
                    continue
                keep_id = self._best_duplicate_keep(ids, unit_by_id)
                for uid in ids:
                    if uid == keep_id or uid in archived_ids:
                        continue
                    self.memory.distill(uid, {"status": "archived"})
                    archived_ids.add(uid)
                    archived += 1

            ctx.step("distill_done", {"links": links_created, "archived": archived})
            result = {
                "units_processed": len(units_snapshot),
                "links_created": links_created,
                "archived": archived,
                "degraded": ctx._degraded,
            }
            ctx.set_result(result)
            return result
        finally:
            self._cleanup_tmp_snapshot(snapshot_path, ctx)


def run_learn(self) -> dict:
    with self.tracer.span("spine.learn", trigger="cron") as ctx:
        active_methods = self.playbook.consult()
        recent_traces = self.tracer.recent(limit=100)
        mem_stats = self.memory.stats()
        router_patterns = self._read_router_patterns(limit=30)
        snapshot_data = {
            "active_methods": active_methods,
            "recent_traces": recent_traces,
            "memory_stats": mem_stats,
            "router_patterns": router_patterns,
        }
        snapshot_path = self._write_tmp_snapshot("learn", snapshot_data)
        ctx.step("snapshot_written", str(snapshot_path))
        ctx.step(
            "data_collected",
            {"methods": len(active_methods), "traces": len(recent_traces), "router_patterns": len(router_patterns)},
        )
        try:
            learn_ctx = snapshot_data
            try:
                snap_raw = json.loads(snapshot_path.read_text(encoding="utf-8"))
                if isinstance(snap_raw, dict):
                    learn_ctx = snap_raw
            except Exception:
                learn_ctx = snapshot_data

            methods_ctx = learn_ctx.get("active_methods") if isinstance(learn_ctx.get("active_methods"), list) else active_methods
            traces_ctx = learn_ctx.get("recent_traces") if isinstance(learn_ctx.get("recent_traces"), list) else recent_traces
            mem_stats_ctx = learn_ctx.get("memory_stats") if isinstance(learn_ctx.get("memory_stats"), dict) else mem_stats
            router_ctx = learn_ctx.get("router_patterns") if isinstance(learn_ctx.get("router_patterns"), list) else router_patterns

            def _llm_learn() -> dict:
                context = {
                    "active_methods": [{"name": m["name"], "success_rate": m.get("success_rate"), "total_runs": m.get("total_runs")} for m in methods_ctx],
                    "recent_traces": [{"routine": t.get("routine"), "status": t.get("status"), "elapsed_s": t.get("elapsed_s")} for t in traces_ctx[:20]],
                    "memory_stats": mem_stats_ctx,
                    "router_patterns": router_ctx,
                }
                return self.cortex.structured(
                    f"Analyze system execution history and identify improvements:\n{json.dumps(context, ensure_ascii=False)}\n\n"
                    "Suggest new method candidates or improvements to existing ones.",
                    schema={
                        "new_candidates": [{"name": "string", "category": "string", "description": "string", "rationale": "string"}],
                        "skill_evolution_proposals": [{"skill": "string", "proposed_change": "string", "evidence": "string"}],
                    },
                    model="analysis",
                )

            def _skip_fallback() -> dict:
                ctx.mark_degraded("Cortex unavailable; skipping learn this cycle")
                return {"new_candidates": [], "skill_evolution_proposals": []}

            analysis = self.cortex.try_or_degrade(_llm_learn, _skip_fallback)

            candidates_added = 0
            for cand in analysis.get("new_candidates", []):
                name = cand.get("name", "").strip()
                if not name or any(m["name"] == name for m in methods_ctx):
                    continue
                self.playbook.register(
                    name=name,
                    category=cand.get("category", "dag_pattern"),
                    spec={"rationale": cand.get("rationale", ""), "steps_template": []},
                    description=cand.get("description", ""),
                    status="candidate",
                )
                candidates_added += 1

            proposals = analysis.get("skill_evolution_proposals", [])
            digest_result = {"sent": 0, "skipped": True, "reason": "no_proposals"}
            if proposals:
                proposals_path = self.state_dir / "skill_evolution_proposals.json"
                existing: list = []
                if proposals_path.exists():
                    try:
                        existing = json.loads(proposals_path.read_text())
                    except Exception as exc:
                        logger.warning("Failed to parse %s: %s", proposals_path, exc)
                        existing = []
                existing.extend(proposals)
                merged = existing[-100:]
                proposals_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2))
                digest_result = self._notify_skill_evolution_digest(merged)
            ctx.step("skill_evolution_digest", digest_result)

            ctx.step("learn_done", {"candidates_added": candidates_added, "proposals": len(proposals)})
            result = {
                "candidates_added": candidates_added,
                "proposals": len(proposals),
                "digest_sent": digest_result.get("sent", 0),
                "degraded": ctx._degraded,
            }
            ctx.set_result(result)
            return result
        finally:
            self._cleanup_tmp_snapshot(snapshot_path, ctx)


def run_judge(self) -> dict:
    with self.tracer.span("spine.judge", trigger="cron") as ctx:
        method_result = self.playbook.judge()
        strategy_result = self._judge_strategies()
        result = {**method_result, "strategy": strategy_result}
        ctx.step("judge_done", result)
        ctx.set_result(result)
    return result


def run_focus(self) -> dict:
    with self.tracer.span("spine.focus", trigger="cron") as ctx:
        signals = self.compass.active_signals()
        priorities = self.compass.get_priorities()
        mem_stats = self.memory.stats()
        ctx.step("data_collected", {"signals": len(signals), "priorities": len(priorities)})

        if not signals:
            result = {"adjusted": 0, "skipped": True}
            ctx.set_result(result)
            return result

        def _llm_focus() -> dict:
            context = {
                "current_priorities": priorities,
                "signals": signals,
                "memory_by_domain": mem_stats.get("by_domain", {}),
            }
            return self.cortex.structured(
                f"Based on these attention signals and current priorities, suggest priority adjustments:\n"
                f"{json.dumps(context, ensure_ascii=False)}\n",
                schema={
                    "adjustments": [{"domain": "string", "new_weight": 0.5, "reason": "string"}],
                },
                model="analysis",
            )

        def _no_adjustment_fallback() -> dict:
            ctx.mark_degraded("Cortex unavailable; no_adjustment mode")
            return {"adjustments": []}

        analysis = self.cortex.try_or_degrade(_llm_focus, _no_adjustment_fallback)

        adjusted = 0
        for adj in analysis.get("adjustments", []):
            domain = adj.get("domain", "")
            weight = float(adj.get("new_weight", 1.0))
            if domain and 0.1 <= weight <= 3.0:
                self.compass.set_priority(domain, weight, adj.get("reason", ""), source="spine.focus", changed_by="spine.focus")
                adjusted += 1
                ctx.step("priority_adjusted", {"domain": domain, "weight": weight})

        result = {"signals_analyzed": len(signals), "adjusted": adjusted, "degraded": ctx._degraded}
        ctx.set_result(result)
    return result
