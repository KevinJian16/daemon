"""Spine Routines — 10 deterministic and hybrid governance routines."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

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


class SpineRoutines:
    """Container for all 10 Spine Routines. Each routine returns a result dict."""

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
                    result = self.memory.intake(raw_signals)
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

            # Find matching method.
            methods = self.playbook.consult(category="dag_pattern")
            method_id: str | None = None
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

            result = {"task_id": task_id, "outcome": status, "method_id": method_id}
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
            ctx.step("units_loaded", len(units))

            if not units:
                result = {"units_processed": 0, "links_created": 0, "archived": 0}
                ctx.set_result(result)
                return result

            def _llm_distill() -> dict:
                titles = [{"unit_id": u["unit_id"], "title": u["title"], "domain": u["domain"]} for u in units[:50]]
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
                for u in units:
                    t = u["title"].lower().strip()
                    if t in seen_titles:
                        duplicates.append({"keep": seen_titles[t], "merge_from": [u["unit_id"]]})
                    else:
                        seen_titles[t] = u["unit_id"]
                return {"duplicates": duplicates, "links": []}

            analysis = self.cortex.try_or_degrade(_llm_distill, _string_fallback)

            # Apply links.
            links_created = 0
            for link in analysis.get("links", []):
                self.memory.link(link["from_id"], link["to_id"], link["relation"])
                links_created += 1

            # Mark duplicates as archived (keep winner, archive losers).
            archived = 0
            for dup in analysis.get("duplicates", []):
                for merge_id in dup.get("merge_from", []):
                    self.memory.distill(merge_id, {"status": "archived"})
                    archived += 1

            ctx.step("distill_done", {"links": links_created, "archived": archived})
            result = {"units_processed": len(units), "links_created": links_created, "archived": archived, "degraded": ctx._degraded}
            ctx.set_result(result)
        return result

    # ── 6. learn ──────────────────────────────────────────────────────────────

    def learn(self) -> dict:
        """Extract DAG patterns from evaluations; register Playbook candidates (hybrid)."""
        with self.tracer.span("spine.learn", trigger="cron") as ctx:
            active_methods = self.playbook.consult()
            recent_traces = self.tracer.recent(limit=100)
            mem_stats = self.memory.stats()
            router_patterns = self._read_router_patterns(limit=30)
            ctx.step(
                "data_collected",
                {"methods": len(active_methods), "traces": len(recent_traces), "router_patterns": len(router_patterns)},
            )

            def _llm_learn() -> dict:
                context = {
                    "active_methods": [{"name": m["name"], "success_rate": m.get("success_rate"), "total_runs": m.get("total_runs")} for m in active_methods],
                    "recent_traces": [{"routine": t.get("routine"), "status": t.get("status"), "elapsed_s": t.get("elapsed_s")} for t in recent_traces[:20]],
                    "memory_stats": mem_stats,
                    "router_patterns": router_patterns,
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
                if not name or any(m["name"] == name for m in active_methods):
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
                proposals_path.write_text(json.dumps(existing[-100:], ensure_ascii=False, indent=2))

            ctx.step("learn_done", {"candidates_added": candidates_added, "proposals": len(proposals)})
            result = {"candidates_added": candidates_added, "proposals": len(proposals), "degraded": ctx._degraded}
            ctx.set_result(result)
        return result

    # ── 7. judge ──────────────────────────────────────────────────────────────

    def judge(self) -> dict:
        """Promote/retire Playbook methods based on statistical thresholds."""
        with self.tracer.span("spine.judge", trigger="cron") as ctx:
            result = self.playbook.judge()
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

            # Export all three Fabric snapshots.
            mem_snap = self.memory.snapshot()
            pb_snap = self.playbook.snapshot()
            cp_snap = self.compass.snapshot()

            (snapshots_dir / "memory_snapshot.json").write_text(json.dumps(mem_snap, ensure_ascii=False, indent=2))
            (snapshots_dir / "playbook_snapshot.json").write_text(json.dumps(pb_snap, ensure_ascii=False, indent=2))
            (snapshots_dir / "compass_snapshot.json").write_text(json.dumps(cp_snap, ensure_ascii=False, indent=2))
            ctx.step("snapshots_written", 3)

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
                for agent in ["router", "collect", "analyze", "build", "review", "render", "apply"]:
                    agent_mem = self.openclaw_home / "workspace" / agent / "memory"
                    agent_mem.mkdir(parents=True, exist_ok=True)
                    (agent_mem / "compass_snapshot.json").write_text(json.dumps(cp_snap, ensure_ascii=False, indent=2))
                    (agent_mem / "model_policy_snapshot.json").write_text(policy_json)

                router_mem = self.openclaw_home / "workspace" / "router" / "memory"
                router_mem.mkdir(parents=True, exist_ok=True)
                hints = self._build_runtime_hints(mem_snap, pb_snap, cp_snap)
                (router_mem / "runtime_hints.txt").write_text(hints)
                ctx.step("runtime_hints_written", True)

            result = {"snapshots": 3, "skill_index": index_written, "model_policy_snapshot": True}
            ctx.set_result(result)
        return result

    # ── 10. tend ──────────────────────────────────────────────────────────────

    def tend(self) -> dict:
        """Housekeeping: expire old data, clean orphaned sessions, replay queued tasks."""
        with self.tracer.span("spine.tend", trigger="cron") as ctx:
            # Expire memory units past their TTL.
            mem_result = self.memory.expire()
            ctx.step("memory_expire", mem_result)

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

            result = {
                "memory_archived": mem_result.get("archived", 0),
                "signals_removed": signals_removed,
                "tasks_replayed": replayed,
                "traces_cleaned": cleaned,
            }
            ctx.set_result(result)
        return result

    # ── Helpers ───────────────────────────────────────────────────────────────

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
                    "args": {"session_key": "agent:collect:task:probe:gateway", "limit": 1},
                },
                headers={**headers, "Content-Type": "application/json"},
                timeout=5,
            )
            if rpc.status_code < 300:
                return "ok"
            return f"http_{resp.status_code}|rpc_{rpc.status_code}"
        except Exception as e:
            return f"error: {str(e)[:80]}"

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
        root = self.openclaw_home / "workspace" / "router" / "memory" / "langgraph_patterns"
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
        eligible = []
        for t in tasks:
            if t.get("status") not in ("queued",):
                continue
            if t.get("status") == "replay_exhausted":
                continue
            next_replay = str(t.get("next_replay_utc") or "")
            if next_replay and next_replay > now:
                continue  # Backoff not elapsed yet.
            eligible.append(t)

        replayed = 0
        for task in sorted(eligible, key=lambda t: int(t.get("priority", 5)))[:10]:
            self.nerve.emit("task_replay", {"task_id": task.get("task_id"), "plan": task.get("plan")})
            replayed += 1
        return replayed

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
