"""Spine Routines — 10 deterministic and hybrid governance routines."""
from __future__ import annotations

import json
import logging
import time
import calendar
import math
import os
import shutil
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.drive_accounts import DriveAccountRegistry

if TYPE_CHECKING:
    from fabric.memory import MemoryFabric
    from fabric.playbook import PlaybookFabric
    from fabric.compass import CompassFabric
    from runtime.cortex import Cortex
    from spine.nerve import Nerve
    from spine.trace import Tracer


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


logger = logging.getLogger(__name__)
_SOURCE_PRIORITY = {"human": 0, "empirical": 1, "synthetic": 2, "collected": 3}


class SpineRoutines:
    """Container for all 11 Spine Routines. Each routine returns a result dict."""

    def __init__(
        self,
        memory: "MemoryFabric",
        playbook: "PlaybookFabric",
        compass: "CompassFabric",
        cortex: "Cortex",
        nerve: "Nerve",
        tracer: "Tracer",
        daemon_home: Path,
        openclaw_home: Path | None = None,
    ) -> None:
        self.memory = memory
        self.playbook = playbook
        self.compass = compass
        self.cortex = cortex
        self.nerve = nerve
        self.tracer = tracer
        self.daemon_home = daemon_home
        self.openclaw_home = openclaw_home
        self.state_dir = daemon_home / "state"

    # ── 1. pulse ─────────────────────────────────────────────────────────────

    def pulse(self) -> dict:
        """Probe infrastructure health; write gate.json."""
        with self.tracer.span("spine.pulse", trigger="cron") as ctx:
            services: dict[str, str] = {}
            degraded: list[str] = []
            reasons: list[str] = []

            # OpenClaw Gateway health check using new 2026.3 endpoint.
            gw_status = self._probe_gateway()
            services["gateway"] = gw_status
            if gw_status != "ok":
                degraded.append("gateway")
                reasons.append(f"gateway: {gw_status}")
            ctx.step("gateway_probe", gw_status)

            # Temporal health (basic: check if can reach server).
            temporal_status = self._probe_temporal()
            services["temporal"] = temporal_status
            if temporal_status != "ok":
                degraded.append("temporal")
                reasons.append(f"temporal: {temporal_status}")
            ctx.step("temporal_probe", temporal_status)

            # LLM availability.
            llm_status = "ok" if self.cortex.is_available() else "unavailable"
            services["llm"] = llm_status
            if llm_status != "ok":
                degraded.append("llm")
                reasons.append("no LLM providers configured")
            ctx.step("llm_probe", llm_status)

            # Determine gate level.
            if "gateway" in degraded or "temporal" in degraded:
                gate_status = "RED" if len(degraded) >= 2 else "YELLOW"
            elif "llm" in degraded:
                gate_status = "YELLOW"
            else:
                gate_status = "GREEN"

            prev_gate = self._read_gate().get("status", "GREEN")
            gate = {
                "status": gate_status,
                "services": services,
                "degraded_services": degraded,
                "reasons": reasons,
                "updated_utc": _utc(),
            }
            self._write_gate(gate)
            ctx.step("gate_written", gate_status)

            if prev_gate != gate_status:
                self.nerve.emit("gate_changed", {"prev": prev_gate, "current": gate_status})

            result = {"gate": gate_status, "services": services}
            ctx.set_result(result)
        return result

    # ── 2. intake ─────────────────────────────────────────────────────────────

    def intake(self) -> dict:
        """Read collect agent output from OpenClaw runs; write to Memory."""
        with self.tracer.span("spine.intake", trigger="cron") as ctx:
            signals_files = self._find_signals_files()
            ctx.step("signals_found", len(signals_files))

            total_inserted = 0
            total_skipped = 0
            for sf in signals_files:
                try:
                    raw_signals = json.loads(sf.read_text())
                    if not isinstance(raw_signals, list):
                        raw_signals = [raw_signals]
                    result = self.memory.intake(
                        raw_signals,
                        actor="spine.intake",
                        source_type="collected",
                        source_agent="collect",
                    )
                    total_inserted += result["inserted"]
                    total_skipped += result["skipped"]
                except Exception as e:
                    ctx.step("signals_error", {"file": str(sf), "error": str(e)[:200]})

            ctx.step("intake_done", {"inserted": total_inserted, "skipped": total_skipped})
            self.nerve.emit("intake_completed", {"inserted": total_inserted})
            result = {"inserted": total_inserted, "skipped": total_skipped, "files": len(signals_files)}
            ctx.set_result(result)
        return result

    # ── 3. record ─────────────────────────────────────────────────────────────

    def record(self, task_id: str, plan: dict, step_results: list[dict], outcome: dict) -> dict:
        """Record completed task: write Playbook evaluation, Memory usage, trace summary."""
        with self.tracer.span("spine.record", trigger="nerve:task_completed") as ctx:
            method_name = plan.get("method") or plan.get("task_type") or "research_report"
            status = "success" if outcome.get("ok") else "failure"
            score = float(outcome.get("score", 1.0 if outcome.get("ok") else 0.0))

            method_id: str | None = None
            plan_method_id = str(plan.get("method_id") or "").strip()
            if plan_method_id:
                method_row = self.playbook.get(plan_method_id)
                if method_row:
                    method_id = plan_method_id

            # Fallback: resolve by active method name.
            if not method_id:
                methods = self.playbook.consult(category="dag_pattern")
                for m in methods:
                    if m["name"] == method_name:
                        method_id = m["method_id"]
                        break

            if method_id:
                eval_detail = {
                    "task_id": task_id,
                    "steps": len(step_results),
                    "failed_steps": sum(1 for r in step_results if r.get("status") == "error"),
                    "plan_title": plan.get("title", "")[:100],
                }
                self.playbook.evaluate(method_id, task_id, status, score, eval_detail)
                ctx.step("playbook_eval", {"method_id": method_id, "outcome": status})

            # Record evidence usage from plan.
            used_unit_ids: list[str] = plan.get("evidence_unit_ids") or []
            for uid in used_unit_ids:
                self.memory.record_usage(uid, task_id, method_id, status)
            ctx.step("usage_recorded", len(used_unit_ids))

            strategy_id = str(plan.get("strategy_id") or "")
            cluster_id = str(plan.get("cluster_id") or "")
            strategy_stage = str(plan.get("strategy_stage") or "")
            strategy_components: dict[str, Any] = {}
            strategy_global_score: float | None = None
            if strategy_id and cluster_id:
                strategy_components = self._build_global_score_components(step_results, outcome, plan)
                strategy_global_score = (
                    0.45 * float(strategy_components.get("quality", 0.0))
                    + 0.35 * float(strategy_components.get("stability", 0.0))
                    + 0.10 * float(strategy_components.get("latency", 0.0))
                    + 0.10 * float(strategy_components.get("cost", 0.0))
                )
                self.playbook.record_experiment(
                    strategy_id=strategy_id,
                    task_id=task_id,
                    cluster_id=cluster_id,
                    score_components=strategy_components,
                    global_score=strategy_global_score,
                    outcome=status,
                    is_shadow=bool(plan.get("is_shadow", False)),
                )
                self._update_task_strategy(
                    task_id=task_id,
                    semantic_cluster=cluster_id,
                    strategy_id=strategy_id,
                    strategy_stage=strategy_stage or "champion",
                    global_score_components=strategy_components,
                    global_score=strategy_global_score,
                    trace_id=ctx.trace_id,
                )
                if bool(plan.get("is_shadow")):
                    self._write_shadow_comparison(
                        task_id=task_id,
                        shadow_of=str(plan.get("shadow_of") or ""),
                        cluster_id=cluster_id,
                        strategy_id=strategy_id,
                        champion_strategy_id=str(plan.get("shadow_champion_strategy_id") or ""),
                        global_score=strategy_global_score,
                        global_components=strategy_components,
                    )
                ctx.step(
                    "strategy_recorded",
                    {
                        "strategy_id": strategy_id,
                        "cluster_id": cluster_id,
                        "global_score": round(strategy_global_score, 4),
                    },
                )

            result = {
                "task_id": task_id,
                "outcome": status,
                "method_id": method_id,
                "strategy_id": strategy_id,
                "semantic_cluster": cluster_id,
                "global_score": round(strategy_global_score, 4) if strategy_global_score is not None else None,
            }
            ctx.set_result(result)
        return result

    # ── 4. witness ────────────────────────────────────────────────────────────

    def witness(self) -> dict:
        """Analyze recent records; extract observations and attention signals (hybrid)."""
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

            # Deterministic stats analysis (always runs).
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

            # Write attention signals to Compass.
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

            # Mark evaluations as analyzed.
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

    # ── 5. distill ────────────────────────────────────────────────────────────

    def distill(self) -> dict:
        """Semantic dedup and link discovery in Memory (hybrid)."""
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
                    # Simple title-based dedup: exact match.
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

                # Apply links.
                links_created = 0
                for link in analysis.get("links", []):
                    from_id = str(link.get("from_id") or "")
                    to_id = str(link.get("to_id") or "")
                    relation = str(link.get("relation") or "")
                    if not from_id or not to_id or not relation:
                        continue
                    self.memory.link(from_id, to_id, relation)
                    links_created += 1

                # Resolve duplicate winner by source priority: human > empirical > synthetic > collected.
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

    # ── 6. learn ──────────────────────────────────────────────────────────────

    def learn(self) -> dict:
        """Extract DAG patterns from evaluations; register Playbook candidates (hybrid)."""
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

                # Write skill evolution proposals to state.
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

    # ── 7. judge ──────────────────────────────────────────────────────────────

    def judge(self) -> dict:
        """Promote/retire Playbook methods based on statistical thresholds."""
        with self.tracer.span("spine.judge", trigger="cron") as ctx:
            method_result = self.playbook.judge()
            strategy_result = self._judge_strategies()
            result = {**method_result, "strategy": strategy_result}
            ctx.step("judge_done", result)
            ctx.set_result(result)
        return result

    # ── 8. focus ──────────────────────────────────────────────────────────────

    def focus(self) -> dict:
        """Adjust Compass domain priorities based on attention signals (hybrid)."""
        with self.tracer.span("spine.focus", trigger="cron") as ctx:
            signals = self.compass.active_signals()
            priorities = self.compass.get_priorities()
            mem_stats = self.memory.stats()
            pb_stats = self.playbook.stats()
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

    # ── 9. relay ──────────────────────────────────────────────────────────────

    def relay(self) -> dict:
        """Export Fabric snapshots; refresh skill_index.json in OpenClaw workspace."""
        with self.tracer.span("spine.relay", trigger="cron") as ctx:
            snapshots_dir = self.state_dir / "snapshots"
            snapshots_dir.mkdir(parents=True, exist_ok=True)

            # Export Fabric snapshots.
            mem_snap = self.memory.snapshot()
            pb_snap = self.playbook.snapshot()
            cp_snap = self.compass.snapshot()
            semantic_snap = self._build_semantic_snapshot()
            strategy_snap = self._build_strategy_snapshot()
            model_registry_snap = self._build_model_registry_snapshot()

            (snapshots_dir / "memory_snapshot.json").write_text(json.dumps(mem_snap, ensure_ascii=False, indent=2))
            (snapshots_dir / "playbook_snapshot.json").write_text(json.dumps(pb_snap, ensure_ascii=False, indent=2))
            (snapshots_dir / "compass_snapshot.json").write_text(json.dumps(cp_snap, ensure_ascii=False, indent=2))
            (snapshots_dir / "semantic_snapshot.json").write_text(json.dumps(semantic_snap, ensure_ascii=False, indent=2))
            (snapshots_dir / "strategy_snapshot.json").write_text(json.dumps(strategy_snap, ensure_ascii=False, indent=2))
            (snapshots_dir / "model_registry_snapshot.json").write_text(json.dumps(model_registry_snap, ensure_ascii=False, indent=2))
            ctx.step("snapshots_written", 6)

            # Generate model_policy_snapshot.json — single source of truth for OpenClaw.
            policy_snapshot = self._build_model_policy_snapshot()
            snap_path = snapshots_dir / "model_policy_snapshot.json"
            snap_path.write_text(json.dumps(policy_snapshot, ensure_ascii=False, indent=2))
            ctx.step("model_policy_snapshot_written", True)

            # Write skill_index.json to router workspace if OpenClaw home is configured.
            skill_index = self._build_skill_index()
            index_written = False
            if self.openclaw_home:
                router_mem = self.openclaw_home / "workspace" / "router" / "memory"
                router_mem.mkdir(parents=True, exist_ok=True)
                (router_mem / "skill_index.json").write_text(json.dumps(skill_index, ensure_ascii=False, indent=2))
                index_written = True
            ctx.step("skill_index_written", index_written)

            # Also write compass snapshot and model policy into OpenClaw workspace for agents.
            if self.openclaw_home:
                policy_json = json.dumps(policy_snapshot, ensure_ascii=False, indent=2)
                registry_json = json.dumps(model_registry_snap, ensure_ascii=False, indent=2)
                for agent in ["router", "collect", "analyze", "build", "review", "render", "apply"]:
                    agent_mem = self.openclaw_home / "workspace" / agent / "memory"
                    agent_mem.mkdir(parents=True, exist_ok=True)
                    (agent_mem / "compass_snapshot.json").write_text(json.dumps(cp_snap, ensure_ascii=False, indent=2))
                    (agent_mem / "model_policy_snapshot.json").write_text(policy_json)
                    (agent_mem / "model_registry_snapshot.json").write_text(registry_json)
                    if agent == "router":
                        (agent_mem / "semantic_snapshot.json").write_text(json.dumps(semantic_snap, ensure_ascii=False, indent=2))
                        (agent_mem / "strategy_snapshot.json").write_text(json.dumps(strategy_snap, ensure_ascii=False, indent=2))

                router_mem = self.openclaw_home / "workspace" / "router" / "memory"
                router_mem.mkdir(parents=True, exist_ok=True)
                hints = self._build_runtime_hints(mem_snap, pb_snap, cp_snap)
                (router_mem / "runtime_hints.txt").write_text(hints)
                ctx.step("runtime_hints_written", True)

                # Write weave_patterns/index.json and structured runtime_hints.json.
                weave_dir = router_mem / "weave_patterns"
                weave_dir.mkdir(parents=True, exist_ok=True)
                weave_index = self._build_weave_index(weave_dir)
                (weave_dir / "index.json").write_text(
                    json.dumps(weave_index, ensure_ascii=False, indent=2)
                )
                hints_json = self._build_runtime_hints_json(mem_snap, pb_snap, cp_snap, weave_index)
                (router_mem / "runtime_hints.json").write_text(
                    json.dumps(hints_json, ensure_ascii=False, indent=2)
                )
                ctx.step("weave_index_written", weave_index.get("total_patterns", 0))

            result = {"snapshots": 6, "skill_index": index_written, "model_policy_snapshot": True, "model_registry_snapshot": True}
            ctx.set_result(result)
        return result

    # ── 10. tend ──────────────────────────────────────────────────────────────

    def tend(self) -> dict:
        """Housekeeping: expire old data, clean orphaned sessions, replay queued tasks."""
        with self.tracer.span("spine.tend", trigger="cron") as ctx:
            # Expire memory units past their TTL.
            mem_result = self.memory.expire()
            ctx.step("memory_expire", mem_result)
            source_policy = self.memory.apply_source_ttl_policy(actor="spine.tend")
            ctx.step("memory_source_policy_expire", source_policy)

            # Capacity pressure signal.
            mem_stats = self.memory.stats()
            total_units = int(mem_stats.get("total_active") or 0)
            total_units_cap = int(self.compass.get_pref("total_units_cap", "10000") or 10000)
            memory_pressure = total_units > total_units_cap
            if memory_pressure:
                self.nerve.emit(
                    "memory_pressure",
                    {"total_units": total_units, "total_units_cap": total_units_cap, "source": "spine.tend"},
                )
            ctx.step("memory_pressure", {"active": total_units, "cap": total_units_cap, "triggered": memory_pressure})

            # Expire stale attention signals.
            signals_removed = self.compass.expire_signals()
            ctx.step("signals_expire", signals_removed)

            # Reset resource budgets if past reset_utc.
            self._maybe_reset_budgets()
            ctx.step("budgets_checked")

            # Check for queued tasks and replay if gate is GREEN.
            gate = self._read_gate()
            replayed = 0
            if gate.get("status") == "GREEN":
                replayed = self._replay_queued_tasks()
            ctx.step("replay", replayed)

            # Clean orphaned state files older than 7 days.
            cleaned = self._clean_old_traces(max_age_days=7)
            ctx.step("traces_cleaned", cleaned)

            # Check Weave pattern pressure; emit nerve event if over threshold.
            weave_count = self._check_weave_pressure()
            if weave_count is not None:
                ctx.step("weave_pressure_checked", weave_count)

            result = {
                "memory_archived": mem_result.get("archived", 0) + source_policy.get("archived", 0),
                "memory_archived_ttl": mem_result.get("archived", 0),
                "memory_archived_source_policy": source_policy.get("archived", 0),
                "memory_pressure_triggered": memory_pressure,
                "memory_total_active": total_units,
                "memory_total_cap": total_units_cap,
                "signals_removed": signals_removed,
                "tasks_replayed": replayed,
                "traces_cleaned": cleaned,
                "weave_pattern_count": weave_count,
            }
            ctx.set_result(result)
        return result

    # ── 11. librarian ─────────────────────────────────────────────────────────

    def librarian(self) -> dict:
        """Cache governance: recompute method tiers, prune stale Weave patterns, merge cold duplicates."""
        with self.tracer.span("spine.librarian", trigger="cron") as ctx:
            # Recompute value_score and reassign tiers by re-running judge().
            judge_result = self.playbook.judge()
            tiered = judge_result.get("tiered", {})
            ctx.step("tiers_refreshed", tiered)

            # Prune cold Weave patterns (archive >90 days, delete >180 days).
            prune_result = self._prune_weave_patterns()
            ctx.step("weave_pruned", prune_result)

            # Merge cold-tier duplicate methods.
            merge_result = self._librarian_merge_methods()
            ctx.step("methods_merged", merge_result)

            # Cold memory export and external archive upload (best-effort).
            export_result = self._cold_export_memory()
            ctx.step("memory_cold_export", export_result)
            upload_result = self._upload_to_drive(export_result.get("files", []))
            ctx.step("memory_archive_upload", upload_result)
            cleanup_result = self._cleanup_local_jsonl()
            ctx.step("memory_archive_cleanup", cleanup_result)

            result = {
                "hot": tiered.get("hot", 0),
                "warm": tiered.get("warm", 0),
                "cold": tiered.get("cold", 0),
                "weave_patterns_archived": prune_result.get("archived", 0),
                "weave_patterns_deleted": prune_result.get("deleted", 0),
                "methods_merged": merge_result.get("merged", 0),
                "memory_exported": export_result.get("exported", 0),
                "memory_deleted": export_result.get("deleted", 0),
                "archive_files": len(export_result.get("files", [])),
                "archive_uploaded": upload_result.get("uploaded", 0),
                "archive_upload_failed": upload_result.get("failed", 0),
                "archive_local_cleaned": cleanup_result.get("deleted", 0),
            }
            ctx.set_result(result)
        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _write_tmp_snapshot(self, routine: str, payload: dict[str, Any]) -> Path:
        tmp_dir = self.state_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        token = f"{int(time.time())}_{abs(hash(routine)) % 10000:04d}"
        path = tmp_dir / f"spine_{routine}_{token}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _cleanup_tmp_snapshot(self, path: Path | None, ctx: Any) -> None:
        if not path:
            return
        try:
            path.unlink(missing_ok=True)
            ctx.step("snapshot_cleaned", str(path))
        except Exception as exc:
            logger.warning("Failed to cleanup snapshot %s: %s", path, exc)

    def _source_rank(self, source_type: str) -> int:
        st = str(source_type or "").strip().lower()
        return _SOURCE_PRIORITY.get(st, 99)

    def _best_duplicate_keep(self, candidate_ids: list[str], units: dict[str, dict]) -> str:
        def _sort_key(uid: str) -> tuple[int, str]:
            row = units.get(uid) or {}
            rank = self._source_rank(str(row.get("source_type") or ""))
            return (rank, str(row.get("created_utc") or ""))

        sorted_ids = sorted(candidate_ids, key=_sort_key)
        return sorted_ids[0] if sorted_ids else (candidate_ids[0] if candidate_ids else "")

    def _probe_gateway(self) -> str:
        if not self.openclaw_home:
            return "not_configured"
        try:
            import httpx
            cfg = self._read_openclaw_config()
            if not cfg:
                return "config_missing"
            port = cfg.get("gateway", {}).get("port", 18789)
            token = cfg.get("gateway", {}).get("auth", {}).get("token", "")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            resp = httpx.get(
                f"http://127.0.0.1:{port}/health",
                headers=headers,
                timeout=5,
            )
            if resp.status_code < 300:
                return "ok"

            # OpenClaw 2026.3 can return 503 on /health when control UI assets are absent
            # while the tool RPC path remains fully available; probe tool path as fallback.
            rpc = httpx.post(
                f"http://127.0.0.1:{port}/tools/invoke",
                json={
                    "tool": "sessions_history",
                    "args": {"sessionKey": "agent:collect:task:probe:gateway", "limit": 1},
                },
                headers={**headers, "Content-Type": "application/json"},
                timeout=5,
            )
            if rpc.status_code < 300:
                return "ok"
            return f"http_{resp.status_code}|rpc_{rpc.status_code}"
        except Exception as e:
            return f"error: {str(e)[:80]}"

    def _judge_strategies(self) -> dict:
        min_samples = int(self.compass.get_pref("strategy_min_samples", "20") or 20)
        promote_delta = float(self.compass.get_pref("strategy_promote_delta", "0.03") or 0.03)
        rollback_delta = float(self.compass.get_pref("strategy_rollback_delta", "0.08") or 0.08)
        conf_threshold = float(self.compass.get_pref("strategy_confidence_threshold", "0.95") or 0.95)
        window_size = int(self.compass.get_pref("strategy_eval_window", "5") or 5)

        clusters = self.playbook.list_clusters()
        strategies = self.playbook.list_strategies()
        by_cluster: dict[str, list[dict]] = {}
        for row in strategies:
            cid = str(row.get("cluster_id") or "")
            by_cluster.setdefault(cid, []).append(row)

        promotions = 0
        rollbacks = 0
        confidence_blocked = 0
        checked = 0

        for c in clusters:
            cluster_id = str(c.get("cluster_id") or "")
            rows = by_cluster.get(cluster_id, [])
            if not rows:
                continue
            checked += 1
            metrics = self._strategy_cluster_metrics(cluster_id)

            champions = [r for r in rows if str(r.get("stage") or "") == "champion"]
            champion = sorted(champions, key=lambda x: str(x.get("updated_utc") or ""), reverse=True)[0] if champions else None
            candidates = [
                r for r in rows
                if str(r.get("stage") or "") in {"shadow", "challenger", "candidate"}
                and int((metrics.get(str(r.get("strategy_id") or ""), {}) or {}).get("n", 0)) >= min_samples
            ]
            if not candidates:
                continue
            best = sorted(
                candidates,
                key=lambda x: float((metrics.get(str(x.get("strategy_id") or ""), {}) or {}).get("mean", 0.0)),
                reverse=True,
            )[0]

            if not champion:
                ok_promote = self._promote_with_guard(
                    strategy_id=str(best.get("strategy_id") or ""),
                    decision="promote_auto",
                    prev_stage=str(best.get("stage") or "candidate"),
                    next_stage="champion",
                    reason="no_champion_present",
                    decided_by="spine.judge",
                    cluster_id=cluster_id,
                )
                if ok_promote:
                    promotions += 1
                continue

            champion_id = str(champion.get("strategy_id") or "")
            best_id = str(best.get("strategy_id") or "")
            if not champion_id or not best_id or champion_id == best_id:
                continue
            m_ch = metrics.get(champion_id, {})
            m_best = metrics.get(best_id, {})
            if int(m_ch.get("n", 0)) < min_samples:
                continue

            mean_ch = float(m_ch.get("mean", 0.0))
            mean_best = float(m_best.get("mean", 0.0))
            var_ch = float(m_ch.get("var", 0.0))
            var_best = float(m_best.get("var", 0.0))
            n_ch = int(m_ch.get("n", 0))
            n_best = int(m_best.get("n", 0))
            se = math.sqrt(max((var_best / max(n_best, 1)) + (var_ch / max(n_ch, 1)), 1e-9))
            z = (mean_best - mean_ch) / se if se > 0 else 0.0
            confidence = self._normal_cdf(z)

            comp_ch = m_ch.get("components", {})
            comp_best = m_best.get("components", {})
            quality_ok = float(comp_best.get("quality", 0.0)) >= float(comp_ch.get("quality", 0.0)) + 0.03
            stability_ok = float(comp_best.get("stability", 0.0)) >= float(comp_ch.get("stability", 0.0)) - 0.01
            latency_ok = float(comp_best.get("latency", 0.0)) >= float(comp_ch.get("latency", 0.0)) - 0.20
            cost_ok = float(comp_best.get("cost", 0.0)) >= float(comp_ch.get("cost", 0.0)) - 0.25

            if confidence < conf_threshold:
                confidence_blocked += 1
                self.playbook._append_strategy_event(
                    "promotion_guard_blocked",
                    {
                        "cluster_id": cluster_id,
                        "champion": champion_id,
                        "candidate": best_id,
                        "reason": "promotion_confidence_low",
                        "confidence": round(confidence, 4),
                    },
                )

            champion_scores = list(m_ch.get("scores", []))
            degraded = self._is_window_degraded(champion_scores, window_size, rollback_delta)
            if degraded and mean_ch - mean_best >= rollback_delta and confidence >= conf_threshold:
                ok_promote = self._promote_with_guard(
                    strategy_id=best_id,
                    decision="rollback_auto",
                    prev_stage=str(best.get("stage") or "candidate"),
                    next_stage="champion",
                    reason=f"champion_two_window_degradation;replace:{champion_id}",
                    decided_by="spine.judge",
                    cluster_id=cluster_id,
                )
                if ok_promote:
                    rollbacks += 1
                continue

            promote_ok = (
                mean_best >= mean_ch + promote_delta
                and quality_ok and stability_ok and latency_ok and cost_ok
                and confidence >= conf_threshold
            )
            if promote_ok:
                ok_promote = self._promote_with_guard(
                    strategy_id=best_id,
                    decision="promote_auto",
                    prev_stage=str(best.get("stage") or "candidate"),
                    next_stage="champion",
                    reason=f"global_delta={round(mean_best - mean_ch, 4)},confidence={round(confidence, 4)}",
                    decided_by="spine.judge",
                    cluster_id=cluster_id,
                )
                if ok_promote:
                    promotions += 1

        return {
            "clusters_checked": checked,
            "promotions": promotions,
            "rollbacks": rollbacks,
            "confidence_blocked": confidence_blocked,
            "min_samples": min_samples,
            "promote_delta": promote_delta,
            "rollback_delta": rollback_delta,
            "confidence_threshold": conf_threshold,
            "window_size": window_size,
        }

    def _promote_with_guard(
        self,
        *,
        strategy_id: str,
        decision: str,
        prev_stage: str,
        next_stage: str,
        reason: str,
        decided_by: str,
        cluster_id: str,
    ) -> bool:
        try:
            self.playbook.promote_strategy(
                strategy_id=strategy_id,
                decision=decision,
                prev_stage=prev_stage,
                next_stage=next_stage,
                reason=reason,
                decided_by=decided_by,
            )
            return True
        except Exception as exc:
            self.playbook._append_strategy_event(
                "promotion_failed",
                {
                    "strategy_id": strategy_id,
                    "cluster_id": cluster_id,
                    "decision": decision,
                    "prev_stage": prev_stage,
                    "next_stage": next_stage,
                    "reason": reason,
                    "error": str(exc)[:300],
                },
            )
            return False

    def _strategy_cluster_metrics(self, cluster_id: str) -> dict[str, dict]:
        rows = self.playbook.list_experiments(cluster_id=cluster_id, limit=2000)
        by_sid: dict[str, dict[str, Any]] = {}
        for row in rows:
            sid = str(row.get("strategy_id") or "")
            if not sid:
                continue
            rec = by_sid.setdefault(
                sid,
                {"scores": [], "quality": [], "stability": [], "latency": [], "cost": []},
            )
            rec["scores"].append(float(row.get("global_score") or 0.0))
            comp = row.get("score_components") if isinstance(row.get("score_components"), dict) else {}
            rec["quality"].append(float(comp.get("quality", 0.0)))
            rec["stability"].append(float(comp.get("stability", 0.0)))
            rec["latency"].append(float(comp.get("latency", 0.0)))
            rec["cost"].append(float(comp.get("cost", 0.0)))

        out: dict[str, dict] = {}
        for sid, vals in by_sid.items():
            scores = vals.get("scores", [])
            if not scores:
                continue
            n = len(scores)
            mean = sum(scores) / max(n, 1)
            var = sum((x - mean) ** 2 for x in scores) / max(n - 1, 1)
            out[sid] = {
                "n": n,
                "mean": mean,
                "var": var,
                "scores": scores,
                "components": {
                    "quality": sum(vals.get("quality", [])) / max(len(vals.get("quality", [])), 1),
                    "stability": sum(vals.get("stability", [])) / max(len(vals.get("stability", [])), 1),
                    "latency": sum(vals.get("latency", [])) / max(len(vals.get("latency", [])), 1),
                    "cost": sum(vals.get("cost", [])) / max(len(vals.get("cost", [])), 1),
                },
            }
        return out

    def _is_window_degraded(self, scores: list[float], window_size: int, delta: float) -> bool:
        if len(scores) < max(window_size * 2, 2):
            return False
        # scores are newest first from list_experiments; convert to chronological for stable windows.
        ordered = list(reversed(scores))
        prev = ordered[-2 * window_size:-window_size]
        curr = ordered[-window_size:]
        if not prev or not curr:
            return False
        prev_mean = sum(prev) / len(prev)
        curr_mean = sum(curr) / len(curr)
        return (prev_mean - curr_mean) >= delta

    def _normal_cdf(self, z: float) -> float:
        return 0.5 * (1.0 + math.erf(float(z) / math.sqrt(2.0)))

    def _probe_temporal(self) -> str:
        try:
            import socket
            sock = socket.create_connection(("127.0.0.1", 7233), timeout=3)
            sock.close()
            return "ok"
        except Exception as e:
            return f"unreachable: {str(e)[:60]}"

    def _read_openclaw_config(self) -> dict | None:
        if not self.openclaw_home:
            return None
        cfg_path = self.openclaw_home / "openclaw.json"
        if not cfg_path.exists():
            return None
        try:
            return json.loads(cfg_path.read_text())
        except Exception as exc:
            logger.warning("Failed to parse OpenClaw config %s: %s", cfg_path, exc)
            return None

    def _find_signals_files(self) -> list[Path]:
        """Find signals_prepare.json files in OpenClaw runs."""
        if not self.openclaw_home:
            return []
        runs_dir = self.openclaw_home / "runs"
        if not runs_dir.exists():
            return []
        return list(runs_dir.glob("**/signals_prepare.json"))

    def _read_gate(self) -> dict:
        gate_path = self.state_dir / "gate.json"
        if not gate_path.exists():
            return {"status": "GREEN"}
        try:
            return json.loads(gate_path.read_text())
        except Exception as exc:
            logger.warning("Failed to parse gate file %s: %s", gate_path, exc)
            return {"status": "GREEN"}

    def _write_gate(self, gate: dict) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2))

    def _build_skill_index(self) -> dict:
        """Build a skill name+description index from OpenClaw workspace skills."""
        index: dict[str, list[dict]] = {}
        if not self.openclaw_home:
            return index
        workspace = self.openclaw_home / "workspace"
        if not workspace.exists():
            return index
        for agent_dir in workspace.iterdir():
            if not agent_dir.is_dir():
                continue
            skills_dir = agent_dir / "skills"
            if not skills_dir.exists():
                continue
            agent_skills = []
            for skill_dir in skills_dir.iterdir():
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue
                content = skill_md.read_text()
                name = skill_dir.name
                desc = ""
                for line in content.splitlines():
                    if line.startswith("##") and not desc:
                        desc = line.lstrip("#").strip()
                    elif line.strip() and not line.startswith("#") and not desc:
                        desc = line.strip()[:120]
                agent_skills.append({"skill": name, "description": desc})
            if agent_skills:
                index[agent_dir.name] = agent_skills
        return index

    def _build_runtime_hints(self, mem_snap: dict, pb_snap: dict, cp_snap: dict) -> str:
        top_methods = pb_snap.get("methods", [])[:5]
        top_priorities = cp_snap.get("priorities", [])[:5]
        lines = [
            f"# Runtime Hints ({_utc()})",
            "",
            "## Top Priorities",
        ]
        for p in top_priorities:
            lines.append(f"- {p.get('domain')}: weight={p.get('weight')}")
        lines.append("")
        lines.append("## Best Methods")
        for m in top_methods:
            lines.append(f"- {m.get('name')} (success_rate={m.get('success_rate')}, runs={m.get('total_runs')})")
        lines.append("")
        lines.append(f"## Memory Snapshot")
        lines.append(f"- active_units={len(mem_snap.get('units', []))}")
        lines.append(f"- links={len(mem_snap.get('links', []))}")
        return "\n".join(lines).strip() + "\n"

    def _build_semantic_snapshot(self) -> dict:
        cfg_root = self.daemon_home / "config" / "semantics"
        catalog_path = cfg_root / "capability_catalog.json"
        rules_path = cfg_root / "mapping_rules.json"
        catalog: dict[str, Any] = {}
        rules: dict[str, Any] = {}
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load semantic catalog: %s", exc)
        try:
            rules = json.loads(rules_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load semantic mapping rules: %s", exc)
        return {
            "generated_utc": _utc(),
            "clusters": catalog.get("clusters", []) if isinstance(catalog, dict) else [],
            "rules": rules.get("rules", []) if isinstance(rules, dict) else [],
            "confidence_thresholds": rules.get("confidence_thresholds", {}) if isinstance(rules, dict) else {},
        }

    def _build_strategy_snapshot(self) -> dict:
        strategies = self.playbook.list_strategies()
        champions: dict[str, dict] = {}
        for row in strategies:
            cid = str(row.get("cluster_id") or "")
            if not cid:
                continue
            if row.get("stage") == "champion":
                champions[cid] = {
                    "strategy_id": row.get("strategy_id"),
                    "global_score": row.get("global_score"),
                    "sample_n": row.get("sample_n"),
                    "updated_utc": row.get("updated_utc"),
                }
        promotions = self.playbook.list_promotions(limit=200)
        return {
            "generated_utc": _utc(),
            "champions": champions,
            "strategies": strategies,
            "recent_promotions": promotions[:50],
        }

    def _build_model_policy_snapshot(self) -> dict:
        """Read config/model_policy.json and annotate with generated_utc."""
        policy_path = self.daemon_home / "config" / "model_policy.json"
        try:
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load model_policy.json: %s", exc)
            policy = {}
        policy["generated_utc"] = _utc()
        return policy

    def _build_model_registry_snapshot(self) -> dict:
        """Read config/model_registry.json and annotate with generated_utc."""
        reg_path = self.daemon_home / "config" / "model_registry.json"
        try:
            registry = json.loads(reg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load model_registry.json: %s", exc)
            registry = {}
        if isinstance(registry, dict):
            registry["generated_utc"] = _utc()
        else:
            registry = {"generated_utc": _utc(), "models": []}
        return registry

    def _build_global_score_components(self, step_results: list[dict], outcome: dict, plan: dict) -> dict:
        quality = float(outcome.get("quality_score", outcome.get("score", 1.0 if outcome.get("ok") else 0.0)) or 0.0)
        quality = max(0.0, min(1.0, quality))

        total_steps = len(step_results) if isinstance(step_results, list) else 0
        if total_steps <= 0:
            stability = 1.0 if outcome.get("ok") else 0.0
        else:
            unstable = 0
            for r in step_results:
                st = str(r.get("status") or "").lower()
                if st in {"error", "failed", "degraded"}:
                    unstable += 1
            stability = max(0.0, min(1.0, 1.0 - (unstable / total_steps)))

        latency = 1.0
        if any("timeout" in str((r.get("error") or "")).lower() for r in step_results):
            latency = 0.6
        elif not outcome.get("ok"):
            latency = 0.75

        cost = 1.0
        budgets = plan.get("resource_budgets")
        if isinstance(budgets, list) and budgets:
            over = 0
            total = 0
            for b in budgets:
                try:
                    total += 1
                    used = float(b.get("current_usage", 0))
                    lim = float(b.get("daily_limit", 0))
                    if lim > 0 and used > lim * 0.9:
                        over += 1
                except Exception:
                    continue
            if total:
                cost = max(0.0, 1.0 - (over / total) * 0.5)

        return {
            "quality": round(quality, 4),
            "stability": round(stability, 4),
            "latency": round(latency, 4),
            "cost": round(cost, 4),
        }

    def _update_task_strategy(
        self,
        task_id: str,
        semantic_cluster: str,
        strategy_id: str,
        strategy_stage: str,
        global_score_components: dict,
        global_score: float,
        trace_id: str,
    ) -> None:
        tasks_path = self.state_dir / "tasks.json"
        if not tasks_path.exists():
            return
        try:
            tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read task file %s: %s", tasks_path, exc)
            return
        updated = False
        for row in tasks if isinstance(tasks, list) else []:
            if str(row.get("task_id") or "") != task_id:
                continue
            row["semantic_cluster"] = semantic_cluster
            row["strategy_id"] = strategy_id
            row["strategy_stage"] = strategy_stage
            row["global_score_components"] = global_score_components
            row["global_score"] = round(float(global_score or 0.0), 4)
            row["trace_id"] = trace_id
            row["updated_utc"] = _utc()
            updated = True
            break
        if not updated:
            return
        try:
            tmp = tasks_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
            tmp.replace(tasks_path)
        except Exception as exc:
            logger.warning("Failed to write strategy updates to tasks.json: %s", exc)

    def _write_shadow_comparison(
        self,
        task_id: str,
        shadow_of: str,
        cluster_id: str,
        strategy_id: str,
        champion_strategy_id: str,
        global_score: float,
        global_components: dict,
    ) -> None:
        champion = self.playbook.get_strategy(champion_strategy_id) if champion_strategy_id else None
        champion_score = float(champion.get("global_score") or 0.0) if champion else 0.0
        champion_components = champion.get("score_components", {}) if champion and isinstance(champion.get("score_components"), dict) else {}
        row = {
            "created_utc": _utc(),
            "task_id": task_id,
            "shadow_of": shadow_of,
            "cluster_id": cluster_id,
            "shadow_strategy_id": strategy_id,
            "champion_strategy_id": champion_strategy_id,
            "shadow_global_score": round(float(global_score or 0.0), 4),
            "champion_global_score": round(champion_score, 4),
            "delta_global_score": round(float(global_score or 0.0) - champion_score, 4),
            "shadow_components": global_components,
            "champion_components": champion_components,
        }
        path = self.state_dir / "telemetry" / "shadow_comparisons.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed to write shadow comparison row: %s", exc)

    def _collect_openclaw_observations(self) -> dict:
        if not self.openclaw_home:
            return {"session_files": 0, "signals_files": 0, "session_errors": 0}

        session_files = list(self.openclaw_home.glob("agents/*/sessions/**/*.jsonl"))
        signal_files = list(self.openclaw_home.glob("runs/**/signals_prepare.json"))
        session_errors = 0
        for session_file in session_files[:50]:
            try:
                lines = session_file.read_text(encoding="utf-8").splitlines()
            except Exception as exc:
                logger.warning("Failed to read session file %s: %s", session_file, exc)
                continue
            for line in lines[-40:]:
                low = line.lower()
                if "error" in low or "timeout" in low:
                    session_errors += 1

        return {
            "session_files": len(session_files),
            "signals_files": len(signal_files),
            "session_errors": session_errors,
        }

    def _read_router_patterns(self, limit: int = 30) -> list[dict]:
        if not self.openclaw_home:
            return []
        root = self.openclaw_home / "workspace" / "router" / "memory" / "weave_patterns"
        if not root.exists():
            return []
        out: list[dict] = []
        for p in sorted(root.glob("**/*")):
            if not p.is_file():
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning("Failed to read router pattern %s: %s", p, exc)
                continue
            out.append({"path": str(p.relative_to(root)), "snippet": text[:1000]})
            if len(out) >= limit:
                break
        return out

    def _collect_interface_observations(self) -> dict:
        telemetry_dir = self.state_dir / "telemetry"
        portal_path = telemetry_dir / "portal_events.jsonl"
        telegram_path = telemetry_dir / "telegram_events.jsonl"

        def _read(path: Path, max_lines: int = 500) -> list[dict]:
            if not path.exists():
                return []
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except Exception as exc:
                logger.warning("Failed to read interface telemetry %s: %s", path, exc)
                return []
            out: list[dict] = []
            for line in lines[-max_lines:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    if isinstance(row, dict):
                        out.append(row)
                except json.JSONDecodeError:
                    continue
            return out

        portal_rows = _read(portal_path)
        telegram_rows = _read(telegram_path)
        portal_errors = sum(1 for r in portal_rows if "fail" in str(r.get("event", "")).lower() or "error" in str(r.get("event", "")).lower())
        telegram_errors = sum(1 for r in telegram_rows if "fail" in str(r.get("event", "")).lower() or "error" in str(r.get("event", "")).lower())
        return {
            "portal_events": len(portal_rows),
            "telegram_events": len(telegram_rows),
            "portal_error_events": portal_errors,
            "telegram_error_events": telegram_errors,
            "recent_portal_events": [r.get("event", "") for r in portal_rows[-20:]],
            "recent_telegram_events": [r.get("event", "") for r in telegram_rows[-20:]],
        }

    def _collect_trace_observations(self, limit: int = 200) -> dict:
        traces = self.tracer.recent(limit=limit)
        if not traces:
            return {
                "total_traces": 0,
                "error_traces": 0,
                "degraded_traces": 0,
                "routines": [],
                "slow_traces": [],
            }

        by_routine: dict[str, dict[str, Any]] = {}
        error_traces = 0
        degraded_traces = 0
        slow_traces: list[dict] = []

        for t in traces:
            routine = str(t.get("routine") or "unknown")
            status = str(t.get("status") or "unknown")
            degraded = bool(t.get("degraded"))
            elapsed = float(t.get("elapsed_s") or 0.0)
            row = by_routine.setdefault(
                routine,
                {"routine": routine, "calls": 0, "errors": 0, "degraded": 0, "avg_elapsed_s": 0.0, "max_elapsed_s": 0.0},
            )
            row["calls"] += 1
            row["avg_elapsed_s"] += elapsed
            row["max_elapsed_s"] = max(float(row["max_elapsed_s"]), elapsed)
            if status == "error":
                row["errors"] += 1
                error_traces += 1
            if degraded:
                row["degraded"] += 1
                degraded_traces += 1
            if elapsed >= 30:
                slow_traces.append(
                    {
                        "trace_id": t.get("trace_id", ""),
                        "routine": routine,
                        "elapsed_s": elapsed,
                        "status": status,
                    }
                )

        routines = []
        for row in by_routine.values():
            calls = int(row["calls"] or 1)
            row["avg_elapsed_s"] = round(float(row["avg_elapsed_s"]) / calls, 3)
            routines.append(row)
        routines.sort(key=lambda x: (int(x.get("errors", 0)), int(x.get("degraded", 0)), float(x.get("avg_elapsed_s", 0))), reverse=True)
        slow_traces.sort(key=lambda x: float(x.get("elapsed_s", 0)), reverse=True)

        return {
            "total_traces": len(traces),
            "error_traces": error_traces,
            "degraded_traces": degraded_traces,
            "routines": routines[:20],
            "slow_traces": slow_traces[:20],
        }

    def _maybe_reset_budgets(self) -> None:
        budgets = self.compass.all_budgets()
        now = _utc()
        for b in budgets:
            reset_utc = b.get("reset_utc", "")
            if reset_utc and reset_utc <= now:
                self.compass.reset_budgets()
                break

    def _replay_queued_tasks(self) -> int:
        """Find queued tasks eligible for replay (backoff respected). Returns count."""
        tasks_path = self.state_dir / "tasks.json"
        if not tasks_path.exists():
            return 0
        try:
            tasks = json.loads(tasks_path.read_text())
        except Exception as exc:
            logger.warning("Failed to parse queued tasks file %s: %s", tasks_path, exc)
            return 0
        now = _utc()
        window_hours = int(self.compass.get_pref("replay_window_hours", "24") or 24)
        replay_window_s = max(1, window_hours) * 3600
        changed = False
        eligible = []
        for t in tasks:
            if t.get("status") not in ("queued",):
                continue
            if t.get("status") == "replay_exhausted":
                continue
            queued_utc = str(t.get("queued_utc") or t.get("submitted_utc") or "")
            queued_ts = self._iso_to_ts(queued_utc)
            if queued_ts and (time.time() - queued_ts) > replay_window_s:
                t["status"] = "expired"
                t["updated_utc"] = now
                t["expired_reason"] = "replay_window_exceeded"
                changed = True
                continue
            next_replay = str(t.get("next_replay_utc") or "")
            if next_replay and next_replay > now:
                continue  # Backoff not elapsed yet.
            eligible.append(t)

        replayed = 0
        for task in sorted(eligible, key=lambda t: int(t.get("priority", 5)))[:10]:
            self.nerve.emit("task_replay", {"task_id": task.get("task_id"), "plan": task.get("plan")})
            replayed += 1
        if changed:
            try:
                tmp = tasks_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
                tmp.replace(tasks_path)
            except Exception as exc:
                logger.warning("Failed to persist expired replay tasks: %s", exc)
        return replayed

    def _iso_to_ts(self, v: str) -> float | None:
        if not v:
            return None
        try:
            return float(calendar.timegm(time.strptime(v, "%Y-%m-%dT%H:%M:%SZ")))
        except Exception:
            return None

    def _clean_old_traces(self, max_age_days: int = 7) -> int:
        traces_dir = self.state_dir / "traces"
        if not traces_dir.exists():
            return 0
        cutoff = time.time() - max_age_days * 86400
        cleaned = 0
        for f in traces_dir.glob("*.jsonl"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                cleaned += 1
        return cleaned

    def _check_weave_pressure(self) -> int | None:
        """Count Weave patterns; emit weave_pressure nerve event if over threshold (200)."""
        if not self.openclaw_home:
            return None
        PRESSURE_THRESHOLD = 200
        weave_dir = self.openclaw_home / "workspace" / "router" / "memory" / "weave_patterns"
        if not weave_dir.exists():
            return None
        count = sum(1 for p in weave_dir.glob("*") if p.is_file() and p.name != "index.json")
        if count >= PRESSURE_THRESHOLD:
            self.nerve.emit("weave_pressure", {"pattern_count": count, "threshold": PRESSURE_THRESHOLD})
        return count

    def _prune_weave_patterns(self) -> dict:
        """Archive cold Weave patterns (>90 days) and delete archived ones (>180 days)."""
        if not self.openclaw_home:
            return {"skipped": True, "archived": 0, "deleted": 0}
        weave_dir = self.openclaw_home / "workspace" / "router" / "memory" / "weave_patterns"
        if not weave_dir.exists():
            return {"skipped": True, "archived": 0, "deleted": 0}
        archive_dir = weave_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        now_ts = time.time()
        archived = 0
        deleted = 0
        for p in weave_dir.glob("*"):
            if not p.is_file() or p.name in ("index.json",):
                continue
            age_days = (now_ts - p.stat().st_mtime) / 86400.0
            if age_days >= 90:
                dest = archive_dir / p.name
                try:
                    p.rename(dest)
                    archived += 1
                except Exception as exc:
                    logger.warning("Failed to archive weave pattern %s: %s", p, exc)
        for p in archive_dir.glob("*"):
            if not p.is_file():
                continue
            age_days = (now_ts - p.stat().st_mtime) / 86400.0
            if age_days >= 180:
                try:
                    p.unlink()
                    deleted += 1
                except Exception as exc:
                    logger.warning("Failed to delete archived pattern %s: %s", p, exc)
        return {"archived": archived, "deleted": deleted}

    def _build_weave_index(self, weave_dir: Path) -> dict:
        """Build an index.json summarising all files in the weave_patterns directory."""
        patterns: list[dict] = []
        now_ts = time.time()
        for p in sorted(weave_dir.glob("*")):
            if not p.is_file() or p.name == "index.json":
                continue
            stat = p.stat()
            age_days = (now_ts - stat.st_mtime) / 86400.0
            mtime_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime))
            tier = "hot" if age_days < 14 else ("warm" if age_days < 60 else "cold")
            patterns.append({
                "path": p.name,
                "size_bytes": stat.st_size,
                "mtime_utc": mtime_utc,
                "age_days": round(age_days, 1),
                "tier": tier,
            })
        by_tier: dict[str, int] = {"hot": 0, "warm": 0, "cold": 0}
        for pt in patterns:
            by_tier[pt["tier"]] = by_tier.get(pt["tier"], 0) + 1
        return {
            "generated_utc": _utc(),
            "total_patterns": len(patterns),
            "by_tier": by_tier,
            "patterns": patterns,
        }

    def _build_runtime_hints_json(self, mem_snap: dict, pb_snap: dict, cp_snap: dict, weave_index: dict) -> dict:
        """Structured JSON runtime hints for router agent (supplements runtime_hints.txt)."""
        top_methods = pb_snap.get("methods", [])[:5]
        top_priorities = cp_snap.get("priorities", [])[:5]
        hot_patterns = [p for p in weave_index.get("patterns", []) if p.get("tier") == "hot"][:10]
        return {
            "generated_utc": _utc(),
            "top_priorities": [
                {"domain": p.get("domain"), "weight": p.get("weight")} for p in top_priorities
            ],
            "best_methods": [
                {"name": m.get("name"), "success_rate": m.get("success_rate"), "runs": m.get("total_runs")}
                for m in top_methods
            ],
            "memory_summary": {
                "active_units": len(mem_snap.get("units", [])),
                "links": len(mem_snap.get("links", [])),
            },
            "weave_summary": {
                "total_patterns": weave_index.get("total_patterns", 0),
                "by_tier": weave_index.get("by_tier", {}),
            },
            "weave_hot_patterns": hot_patterns,
        }

    def _librarian_merge_methods(self) -> dict:
        """Identify and merge cold-tier duplicate methods."""
        candidates = self.playbook.merge_candidates()
        if not candidates:
            return {"merged": 0, "candidates": 0, "skipped": True}
        merged = 0
        for pair in candidates:
            a = pair.get("method_a", {})
            b = pair.get("method_b", {})
            if a.get("tier") != "cold" or b.get("tier") != "cold":
                continue
            keep_id = str(pair.get("suggested_keep") or "")
            merge_id = a["method_id"] if keep_id == b["method_id"] else b["method_id"]
            if not keep_id or not merge_id:
                continue
            try:
                self.playbook.merge(keep_id, [merge_id])
                merged += 1
            except Exception as exc:
                logger.warning("Failed to merge methods %s←%s: %s", keep_id, merge_id, exc)
        return {"merged": merged, "candidates": len(candidates)}

    def _notify_skill_evolution_digest(self, proposals: list[dict], *, threshold: int = 5) -> dict:
        total = len(proposals)
        if total < threshold:
            return {"sent": 0, "skipped": True, "reason": "below_threshold", "total": total}
        try:
            last = int(self.compass.get_pref("skill_evolution.digest_last_total", "0") or 0)
        except Exception:
            last = 0
        if total <= last:
            return {"sent": 0, "skipped": True, "reason": "already_notified", "total": total, "last": last}

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        users = [int(x.strip()) for x in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",") if x.strip().isdigit()]
        if not token or not users:
            return {"sent": 0, "skipped": True, "reason": "telegram_not_configured", "total": total}

        lines = []
        for row in proposals[-threshold:]:
            skill = str(row.get("skill") or "").strip() or "unknown"
            change = str(row.get("proposed_change") or "").strip().replace("\n", " ")[:120]
            lines.append(f"- {skill}: {change}")
        message = (
            "🧠 Daemon Skill Evolution Digest\n\n"
            f"累计提案数: {total}\n"
            "最近提案:\n"
            + "\n".join(lines)
            + "\n\n请在 Console 审批。"
        )

        sent = 0
        try:
            import httpx

            with httpx.Client(timeout=10) as client:
                for uid in users:
                    try:
                        resp = client.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": uid, "text": message},
                        )
                        if resp.status_code < 300:
                            sent += 1
                    except Exception as exc:
                        logger.warning("Skill evolution digest notify failed user=%s: %s", uid, exc)
        except Exception as exc:
            return {"sent": 0, "skipped": True, "reason": f"telegram_send_failed:{str(exc)[:120]}", "total": total}

        if sent > 0:
            self.compass.set_pref("skill_evolution.digest_last_total", str(total), source="spine.learn", changed_by="spine.learn")
        return {"sent": sent, "total": total, "users": len(users)}

    def _cold_export_memory(self, *, archive_after_days: int = 7, batch_limit: int = 2000) -> dict:
        """Export archived+unreferenced memory units to JSONL, then delete from local DB."""
        db_path = self.state_dir / "memory.db"
        if not db_path.exists():
            return {"exported": 0, "deleted": 0, "files": [], "skipped": True, "reason": "memory_db_missing"}

        cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - max(1, archive_after_days) * 86400))
        rows: list[dict[str, Any]] = []
        unit_ids: list[str] = []

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            rows_raw = conn.execute(
                """
                SELECT u.*
                FROM units u
                WHERE u.status='archived'
                  AND COALESCE(u.updated_utc, u.created_utc) <= ?
                  AND NOT EXISTS (SELECT 1 FROM usage ug WHERE ug.unit_id=u.unit_id)
                  AND NOT EXISTS (SELECT 1 FROM links l WHERE l.from_id=u.unit_id OR l.to_id=u.unit_id)
                ORDER BY COALESCE(u.updated_utc, u.created_utc) ASC
                LIMIT ?
                """,
                (cutoff, int(max(1, batch_limit))),
            ).fetchall()
            if not rows_raw:
                return {"exported": 0, "deleted": 0, "files": []}

            for row in rows_raw:
                unit_id = str(row["unit_id"] or "")
                if not unit_id:
                    continue
                unit_ids.append(unit_id)
                row_dict = dict(row)
                src_rows = conn.execute(
                    "SELECT provider,url,tier,raw_hash FROM sources WHERE unit_id=?",
                    (unit_id,),
                ).fetchall()
                row_dict["sources"] = [dict(s) for s in src_rows]
                rows.append(row_dict)

            now = time.gmtime()
            year = time.strftime("%Y", now)
            month = time.strftime("%m", now)
            ts = time.strftime("%Y%m%dT%H%M%SZ", now)
            archive_dir = self.state_dir / "archive" / "memory" / year / month
            archive_dir.mkdir(parents=True, exist_ok=True)
            out_path = archive_dir / f"units_{ts}.jsonl"
            with out_path.open("w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")

            for uid in unit_ids:
                conn.execute("DELETE FROM sources WHERE unit_id=?", (uid,))
                conn.execute("DELETE FROM usage WHERE unit_id=?", (uid,))
                conn.execute("DELETE FROM links WHERE from_id=? OR to_id=?", (uid, uid))
                conn.execute("DELETE FROM units WHERE unit_id=?", (uid,))
            conn.commit()

            return {
                "exported": len(rows),
                "deleted": len(unit_ids),
                "files": [str(out_path)],
                "cutoff_utc": cutoff,
            }
        except Exception as exc:
            conn.rollback()
            logger.warning("Cold export memory failed: %s", exc)
            return {"exported": 0, "deleted": 0, "files": [], "error": str(exc)[:300]}
        finally:
            conn.close()

    def _cleanup_local_jsonl(self, *, older_than_days: int = 30) -> dict:
        root = self.state_dir / "archive"
        if not root.exists():
            return {"deleted": 0, "skipped": True, "reason": "archive_root_missing"}
        cutoff = time.time() - max(1, older_than_days) * 86400
        deleted = 0
        for p in root.glob("**/*.jsonl"):
            if not p.is_file():
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    deleted += 1
            except Exception as exc:
                logger.warning("Failed to cleanup archive jsonl %s: %s", p, exc)
        return {"deleted": deleted}

    def _upload_to_drive(self, files: list[str]) -> dict:
        targets = [Path(x) for x in files if str(x).strip()]
        if not targets:
            return {"uploaded": 0, "failed": 0, "skipped": True, "reason": "no_files"}

        drive_registry = DriveAccountRegistry(self.state_dir)
        resolved = drive_registry.resolve_upload_target()
        if not resolved.get("ok"):
            msg = str(resolved.get("error") or "drive_local_sync_not_configured")
            self.nerve.emit("archive_upload_failed", {"reason": msg, "files": [str(p) for p in targets]})
            return {"uploaded": 0, "failed": len(targets), "skipped": True, "reason": msg}
        source = str(resolved.get("source") or "unknown")
        if source != "local_sync":
            msg = f"unsupported_drive_upload_source:{source}"
            self.nerve.emit("archive_upload_failed", {"reason": msg, "files": [str(p) for p in targets]})
            return {"uploaded": 0, "failed": len(targets), "skipped": True, "reason": msg}

        archive_root = str(resolved.get("archive_root") or "").strip()
        if not archive_root:
            msg = "archive_root_missing"
            self.nerve.emit("archive_upload_failed", {"reason": msg, "files": [str(p) for p in targets]})
            return {"uploaded": 0, "failed": len(targets), "skipped": True, "reason": msg}
        root = Path(archive_root)
        if not root.exists() or not root.is_dir():
            msg = "archive_root_not_found"
            self.nerve.emit("archive_upload_failed", {"reason": msg, "files": [str(p) for p in targets]})
            return {"uploaded": 0, "failed": len(targets), "skipped": True, "reason": msg}
        uploaded = 0
        failed = 0
        rows: list[dict[str, Any]] = []
        for path in targets:
            try:
                year = path.parent.parent.name if path.parent.parent.name.isdigit() else time.strftime("%Y", time.gmtime())
                month = path.parent.name if path.parent.name.isdigit() else time.strftime("%m", time.gmtime())
                dest_dir = root / year / month
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / path.name
                if dest.exists():
                    stem = dest.stem
                    suf = dest.suffix
                    dest = dest_dir / f"{stem}_{int(time.time())}{suf}"
                shutil.copy2(path, dest)
                uploaded += 1
                rows.append({"path": str(path), "local_path": str(dest), "source": source})
            except Exception as exc:
                failed += 1
                self.nerve.emit("archive_upload_failed", {"reason": str(exc)[:300], "path": str(path)})
        return {"uploaded": uploaded, "failed": failed, "files": rows, "source": source}
