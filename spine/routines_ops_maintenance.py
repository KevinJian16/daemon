"""Spine relay/tend/librarian implementations."""
from __future__ import annotations

import json


def run_relay(self) -> dict:
    with self.tracer.span("spine.relay", trigger="cron") as ctx:
        snapshots_dir = self.state_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

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

        policy_snapshot = self._build_model_policy_snapshot()
        snap_path = snapshots_dir / "model_policy_snapshot.json"
        snap_path.write_text(json.dumps(policy_snapshot, ensure_ascii=False, indent=2))
        ctx.step("model_policy_snapshot_written", True)

        skill_index = self._build_skill_index()
        index_written = False
        if self.openclaw_home:
            router_mem = self.openclaw_home / "workspace" / "router" / "memory"
            router_mem.mkdir(parents=True, exist_ok=True)
            (router_mem / "skill_index.json").write_text(json.dumps(skill_index, ensure_ascii=False, indent=2))
            index_written = True
        ctx.step("skill_index_written", index_written)

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


def run_tend(self) -> dict:
    with self.tracer.span("spine.tend", trigger="cron") as ctx:
        mem_result = self.memory.expire()
        ctx.step("memory_expire", mem_result)
        source_policy = self.memory.apply_source_ttl_policy(actor="spine.tend")
        ctx.step("memory_source_policy_expire", source_policy)

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

        signals_removed = self.compass.expire_signals()
        ctx.step("signals_expire", signals_removed)

        self._maybe_reset_budgets()
        ctx.step("budgets_checked")

        gate = self._read_gate()
        replayed = 0
        if gate.get("status") == "GREEN":
            replayed = self._replay_queued_runs()
        ctx.step("replay", replayed)

        cleaned = self._clean_old_traces(max_age_days=7)
        ctx.step("traces_cleaned", cleaned)

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
            "runs_replayed": replayed,
            "traces_cleaned": cleaned,
            "weave_pattern_count": weave_count,
        }
        ctx.set_result(result)
    return result


def run_librarian(self) -> dict:
    with self.tracer.span("spine.librarian", trigger="cron") as ctx:
        judge_result = self.playbook.judge()
        tiered = judge_result.get("tiered", {})
        ctx.step("tiers_refreshed", tiered)

        prune_result = self._prune_weave_patterns()
        ctx.step("weave_pruned", prune_result)

        merge_result = self._librarian_merge_methods()
        ctx.step("methods_merged", merge_result)

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
