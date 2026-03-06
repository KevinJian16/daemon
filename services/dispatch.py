"""Dispatch — semantic routing, plan validation, Playbook strategy, Temporal submission."""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.semantic import SemanticSpec, SemanticGenerator, SemanticMappingError
from services.dispatch_model import (
    apply_model_routing as _apply_model_routing_impl,
    load_model_policy as _load_model_policy_impl,
    load_model_registry as _load_model_registry_impl,
)
from services.dispatch_replay import (
    replay as _replay_impl,
    update_replay_state as _update_replay_state_impl,
)
from services.dispatch_semantic import (
    annotate_capability_graph as _annotate_capability_graph_impl,
    resolve_semantic as _resolve_semantic_impl,
)
from services.dispatch_steps import (
    apply_complexity_probe,
    pick_alias_for_provider,
    preflight_provider_budget,
)
from services.dispatch_strategy import (
    apply_strategy as _apply_strategy_impl,
    maybe_submit_shadow as _maybe_submit_shadow_impl,
    pick_shadow_candidate as _pick_shadow_candidate_impl,
    shadow_ratio as _shadow_ratio_impl,
)
from services.state_store import StateStore

if TYPE_CHECKING:
    from fabric.playbook import PlaybookFabric
    from fabric.compass import CompassFabric
    from runtime.cortex import Cortex
    from spine.nerve import Nerve


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


logger = logging.getLogger(__name__)


class Dispatch:
    def __init__(
        self,
        playbook: "PlaybookFabric",
        compass: "CompassFabric",
        nerve: "Nerve",
        state_dir: Path,
        temporal_client=None,
        temporal_queue: str = "daemon-queue",
        cortex: "Cortex | None" = None,
    ) -> None:
        self._playbook = playbook
        self._compass = compass
        self._nerve = nerve
        self._state = state_dir
        self._store = StateStore(state_dir)
        self._logger = logger
        self._temporal = temporal_client
        self._temporal_queue = temporal_queue
        self._cortex = cortex
        self._semantic = SemanticGenerator(cortex=cortex)
        self._agent_defaults = self._load_agent_defaults()
        self._model_policy_path = self._state.parent / "config" / "model_policy.json"
        self._model_registry_path = self._state.parent / "config" / "model_registry.json"

    def set_temporal_client(self, temporal_client) -> None:
        self._temporal = temporal_client

    def reload_semantic_configs(self) -> None:
        """Reload semantic catalog/rules from config files without restarting API."""
        self._semantic = SemanticGenerator(cortex=self._cortex)

    def validate(self, plan: dict) -> tuple[bool, str]:
        """Validate a plan before submission. Returns (ok, error_message)."""
        steps = plan.get("steps") or plan.get("graph", {}).get("steps") or []
        if not isinstance(steps, list) or not steps:
            return False, "plan must contain a non-empty steps list"

        ids: set[str] = set()
        for i, st in enumerate(steps):
            if not isinstance(st, dict):
                return False, f"step {i} is not an object"
            sid = str(st.get("id") or f"step_{i}")
            if sid in ids:
                return False, f"duplicate step id: {sid}"
            ids.add(sid)
            for dep in st.get("depends_on") or []:
                if dep not in ids:
                    return False, f"step {sid}: depends_on unknown step {dep!r} (must appear before it)"

        return True, ""

    def enrich(self, plan: dict) -> dict:
        """Apply Playbook parameters (timeouts, retry policy) into plan."""
        plan = dict(plan)
        plan.pop("queued", None)
        plan.pop("queue_reason", None)
        plan.pop("run_status", None)

        run_type = str(plan.get("run_type") or "research_report")
        plan.setdefault("run_type", run_type)
        plan.setdefault("run_id", _new_run_id())

        agent_defaults = self._agent_defaults_from_compass() or dict(self._agent_defaults)
        plan.setdefault("agent_concurrency_defaults", dict(agent_defaults))
        plan.setdefault("agent_concurrency", dict(agent_defaults))

        if not str(plan.get("cluster_id") or "").strip():
            try:
                fp = self._semantic.from_run_type(run_type, title=str(plan.get("title") or ""))
                plan["cluster_id"] = fp.cluster_id
                plan.setdefault("semantic_spec", fp.to_dict())
                self._annotate_capability_graph(plan, fp.cluster_id)
            except Exception as exc:
                logger.warning("Failed to derive cluster_id from run_type=%s: %s", run_type, exc)

        methods = self._playbook.consult(category="dag_pattern")
        best = None
        for m in methods:
            if m["name"] == run_type or not best:
                best = m
                if m["name"] == run_type:
                    break

        if best:
            spec: dict = best.get("spec") or {}
            plan.setdefault("rework_budget", spec.get("rework_budget", 2))
            plan.setdefault("rework_strategy", spec.get("rework_strategy", "error_code_based"))
            if isinstance(spec.get("concurrency"), dict):
                existing = plan.get("concurrency") if isinstance(plan.get("concurrency"), dict) else {}
                plan["concurrency"] = {**spec.get("concurrency", {}), **existing}
            if isinstance(spec.get("timeout_hints"), dict):
                existing_hints = plan.get("timeout_hints") if isinstance(plan.get("timeout_hints"), dict) else {}
                plan["timeout_hints"] = {**spec.get("timeout_hints", {}), **existing_hints}
            plan["method_id"] = best["method_id"]

        quality = self._compass.get_quality_profile(run_type)
        plan.setdefault("quality_profile", quality)
        default_timeout = int(self._compass.get_pref("default_step_timeout_s", "480") or 480)
        plan.setdefault("default_step_timeout_s", default_timeout)
        plan.setdefault("model_primary", self._compass.get_pref("model_primary", ""))
        plan.setdefault("resource_budgets", self._compass.all_budgets())

        plan = self._apply_strategy(plan)
        plan = self._apply_complexity_probe(plan)
        if not str(plan.get("work_scale") or "").strip():
            plan["work_scale"] = "thread"
        plan = self._preflight_provider_budget(plan)

        gate = self._read_gate()
        if not plan.get("queued"):
            if gate.get("status") == "RED":
                plan["queued"] = True
                plan["queue_reason"] = "gate_red"
            elif gate.get("status") == "YELLOW":
                priority = int(plan.get("priority") or 5)
                if priority > 5:
                    plan["queued"] = True
                    plan["queue_reason"] = "gate_yellow_low_priority"

        return plan

    def _apply_strategy(self, plan: dict) -> dict:
        return _apply_strategy_impl(self, plan)

    def _load_model_policy(self) -> dict:
        return _load_model_policy_impl(self)

    def _load_model_registry(self) -> dict[str, dict]:
        return _load_model_registry_impl(self)

    def _resolve_capability_key(self, step: dict) -> str:
        from services.dispatch_model import resolve_capability_key

        return resolve_capability_key(step)

    def _apply_model_routing(self, plan: dict, strategy_spec: dict) -> None:
        _apply_model_routing_impl(self, plan, strategy_spec)

    def _agent_defaults_from_compass(self) -> dict[str, int]:
        raw = self._compass.get_pref("agent_concurrency_defaults_json", "")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except Exception as exc:
            logger.warning("Invalid agent_concurrency_defaults_json in Compass: %s", exc)
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, int] = {}
        for k, v in data.items():
            try:
                out[str(k)] = int(v)
            except Exception:
                continue
        return out

    def _load_agent_defaults(self) -> dict[str, int]:
        cfg_path = self._state.parent / "config" / "system.json"
        if not cfg_path.exists():
            return {
                "collect": 8,
                "analyze": 4,
                "review": 2,
                "render": 2,
                "apply": 1,
                "spine": 2,
                "router": 1,
                "build": 2,
            }
        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception as exc:
            logger.warning("Failed to read system defaults from %s: %s", cfg_path, exc)
            return {
                "collect": 8,
                "analyze": 4,
                "review": 2,
                "render": 2,
                "apply": 1,
                "spine": 2,
                "router": 1,
                "build": 2,
            }
        defaults = cfg.get("agent_concurrency_defaults", {})
        if not isinstance(defaults, dict):
            return {}
        out: dict[str, int] = {}
        for k, v in defaults.items():
            try:
                out[str(k)] = int(v)
            except Exception:
                continue
        return out

    def resolve_semantic(self, request: dict) -> "SemanticSpec":
        """Resolve semantic spec by explicit input or run_type mapping."""
        return _resolve_semantic_impl(self, request)

    async def submit(self, plan: dict) -> dict:
        try:
            spec = self.resolve_semantic(plan)
        except SemanticMappingError as exc:
            return {"ok": False, "error": str(exc), "error_code": "semantic_mapping_failed"}
        except Exception as exc:
            logger.error("Semantic resolution internal error: %s", exc)
            return {"ok": False, "error": f"semantic_resolution_internal_error:{str(exc)[:240]}", "error_code": "semantic_mapping_failed"}

        plan = dict(plan)
        plan["semantic_spec"] = spec.to_dict()
        plan.setdefault("cluster_id", spec.cluster_id)
        self._annotate_capability_graph(plan, spec.cluster_id)

        ok, err = self.validate(plan)
        if not ok:
            return {"ok": False, "error": err, "error_code": "invalid_plan"}

        try:
            plan = self.enrich(plan)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "error_code": "strategy_guard_blocked"}

        run_id = str(plan["run_id"])
        plan.setdefault("trace_id", f"tr_run_{run_id}")

        if plan.get("queued"):
            self._queue_run(plan)
            out = {
                "ok": True,
                "run_id": run_id,
                "run_status": "queued",
                "reason": plan.get("queue_reason"),
                "work_scale": str(plan.get("work_scale") or "thread"),
            }
            if str(plan.get("queue_reason") or "") == "provider_budget_insufficient":
                out["error_code"] = "provider_budget_insufficient"
                out["provider_routing"] = (
                    plan.get("provider_routing") if isinstance(plan.get("provider_routing"), dict) else {}
                )
                self._nerve.emit(
                    "provider_budget_insufficient",
                    {"run_id": run_id, "provider_routing": out["provider_routing"]},
                )
            return out

        if str(plan.get("work_scale") or "").strip().lower() == "campaign":
            return await self._submit_campaign(plan)

        if not self._temporal:
            self._record_run(plan, "failed_submission", "")
            return {
                "ok": False,
                "run_id": run_id,
                "error_code": "temporal_unavailable",
                "error": "Temporal client unavailable; submission rejected",
            }

        run_root = self._make_run_root(run_id)
        self._record_run(plan, "running", run_root)

        try:
            workflow_id = f"daemon-{run_id}"
            await self._temporal.submit(workflow_id, plan, run_root)
        except Exception as exc:
            logger.error("Temporal submit failed for run %s: %s", run_id, exc)
            self._record_run({**plan, "last_error": str(exc)[:300]}, "failed_submission", run_root)
            return {
                "ok": False,
                "run_id": run_id,
                "error_code": "temporal_submit_failed",
                "error": str(exc)[:400],
            }

        try:
            self._playbook.record_release_execution(
                strategy_id=str(plan.get("strategy_id") or ""),
                cluster_id=str(plan.get("cluster_id") or ""),
                strategy_stage=str(plan.get("strategy_stage") or "champion"),
                mode="production",
                run_id=run_id,
                actor="dispatch",
                reason="primary_submission",
            )
        except Exception as exc:
            logger.warning("Failed to record production release execution for %s: %s", run_id, exc)

        self._nerve.emit("run_submitted", {"run_id": run_id, "run_root": run_root})
        self._notify_run_started(plan)
        await self._maybe_submit_shadow(plan, parent_run_id=run_id)
        return {
            "ok": True,
            "run_id": run_id,
            "run_status": "running",
            "work_scale": str(plan.get("work_scale") or "thread"),
            "run_root": run_root,
        }

    async def _submit_campaign(self, plan: dict) -> dict:
        run_id = str(plan.get("run_id") or _new_run_id())
        plan = dict(plan)
        plan["run_id"] = run_id
        plan.setdefault("work_scale", "campaign")
        plan.setdefault("campaign_id", f"cmp_{run_id}")
        campaign_id = str(plan.get("campaign_id") or f"cmp_{run_id}")
        workflow_id = f"daemon-campaign-{campaign_id}"
        plan["_workflow_id"] = workflow_id
        plan.setdefault("campaign_resume_from", 0)
        plan.setdefault("campaign_run_index", 0)

        if not self._temporal:
            self._record_run(plan, "failed_submission", "")
            return {
                "ok": False,
                "run_id": run_id,
                "campaign_id": campaign_id,
                "error_code": "temporal_unavailable",
                "error": "Temporal client unavailable; campaign submission rejected",
            }

        run_root = self._make_run_root(run_id)
        self._record_run(plan, "running", run_root)

        try:
            await self._temporal.submit(
                workflow_id=workflow_id,
                plan=plan,
                run_root=run_root,
                workflow_name="CampaignWorkflow",
            )
        except Exception as exc:
            logger.error("Campaign submit failed for run %s: %s", run_id, exc)
            self._record_run({**plan, "last_error": str(exc)[:300]}, "failed_submission", run_root)
            return {
                "ok": False,
                "run_id": run_id,
                "campaign_id": campaign_id,
                "error_code": "temporal_submit_failed",
                "error": str(exc)[:400],
            }

        self._nerve.emit(
            "campaign_submitted",
            {
                "run_id": run_id,
                "campaign_id": campaign_id,
                "workflow_id": workflow_id,
                "run_root": run_root,
            },
        )
        return {
            "ok": True,
            "run_id": run_id,
            "campaign_id": campaign_id,
            "workflow_id": workflow_id,
            "work_scale": "campaign",
            "run_status": "running",
            "run_root": run_root,
        }

    async def submit_sandbox(self, plan: dict, strategy_id: str) -> dict:
        try:
            spec = self.resolve_semantic(plan)
        except SemanticMappingError as exc:
            return {"ok": False, "error": str(exc), "error_code": "semantic_mapping_failed"}
        except Exception as exc:
            logger.error("Semantic resolution internal error (sandbox): %s", exc)
            return {"ok": False, "error": f"semantic_resolution_internal_error:{str(exc)[:240]}", "error_code": "semantic_mapping_failed"}

        plan = dict(plan)
        plan["semantic_spec"] = spec.to_dict()
        plan.setdefault("cluster_id", spec.cluster_id)
        self._annotate_capability_graph(plan, spec.cluster_id)

        ok, err = self.validate(plan)
        if not ok:
            return {"ok": False, "error": err, "error_code": "invalid_plan"}

        try:
            plan = self.enrich(plan)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "error_code": "strategy_guard_blocked"}

        strategy = self._playbook.get_strategy(strategy_id)
        if not strategy:
            return {"ok": False, "error": f"unknown_strategy:{strategy_id}", "error_code": "strategy_not_found"}
        strategy_stage = str(strategy.get("strategy_stage") or "")
        if strategy_stage not in {"candidate", "shadow", "challenger"}:
            return {"ok": False, "error": f"sandbox_stage_invalid:{strategy_stage}", "error_code": "strategy_guard_blocked"}

        cluster_id = str(plan.get("cluster_id") or "")
        if cluster_id and str(strategy.get("cluster_id") or "") != cluster_id:
            return {"ok": False, "error": "strategy_cluster_mismatch", "error_code": "strategy_guard_blocked"}

        run_id = str(plan.get("run_id") or _new_run_id())
        plan["run_id"] = run_id
        plan.setdefault("trace_id", f"tr_run_{run_id}")

        champion = self._playbook.get_champion(cluster_id) if cluster_id else None
        champion_id = str(champion.get("strategy_id") or "") if champion else ""
        plan["is_shadow"] = True
        plan["delivery_mode"] = "sandbox"
        plan["shadow_of"] = f"sandbox:{run_id}"
        plan["strategy_id"] = strategy_id
        plan["strategy_stage"] = strategy_stage
        plan["shadow_champion_strategy_id"] = champion_id

        spec = strategy.get("spec") if isinstance(strategy.get("spec"), dict) else {}
        if spec:
            if isinstance(spec.get("concurrency"), dict):
                current = plan.get("concurrency") if isinstance(plan.get("concurrency"), dict) else {}
                plan["concurrency"] = {**spec.get("concurrency", {}), **current}
            if isinstance(spec.get("timeout_hints"), dict):
                current_hints = plan.get("timeout_hints") if isinstance(plan.get("timeout_hints"), dict) else {}
                plan["timeout_hints"] = {**spec.get("timeout_hints", {}), **current_hints}

        if not self._temporal:
            self._record_run(plan, "failed_submission", "")
            return {
                "ok": False,
                "run_id": run_id,
                "error_code": "temporal_unavailable",
                "error": "Temporal client unavailable; submission rejected",
            }

        run_root = self._make_run_root(run_id, is_shadow=True)
        self._record_run(plan, "running_shadow", run_root)

        try:
            workflow_id = f"daemon-sandbox-{run_id}"
            await self._temporal.submit(workflow_id, plan, run_root)
        except Exception as exc:
            logger.error("Temporal sandbox submit failed for run %s: %s", run_id, exc)
            self._record_run({**plan, "last_error": str(exc)[:300]}, "failed_submission", run_root)
            return {
                "ok": False,
                "run_id": run_id,
                "error_code": "temporal_submit_failed",
                "error": str(exc)[:400],
            }

        try:
            self._playbook.record_release_execution(
                strategy_id=str(strategy_id or ""),
                cluster_id=cluster_id,
                strategy_stage=strategy_stage,
                mode="sandbox",
                run_id=run_id,
                actor="dispatch",
                reason="sandbox_submission",
                shadow_of=str(plan.get("shadow_of") or ""),
            )
        except Exception as exc:
            logger.warning("Failed to record sandbox release execution for %s: %s", run_id, exc)

        self._nerve.emit(
            "sandbox_submitted",
            {
                "run_id": run_id,
                "strategy_id": strategy_id,
                "cluster_id": cluster_id,
                "strategy_stage": strategy_stage,
                "run_root": run_root,
            },
        )
        return {
            "ok": True,
            "run_id": run_id,
            "run_status": "running_shadow",
            "run_root": run_root,
            "strategy_id": strategy_id,
            "strategy_stage": strategy_stage,
        }

    async def _maybe_submit_shadow(self, plan: dict, parent_run_id: str) -> None:
        await _maybe_submit_shadow_impl(self, plan, parent_run_id)

    def _shadow_ratio(self) -> float:
        return _shadow_ratio_impl(self)

    def _pick_shadow_candidate(self, cluster_id: str, champion_strategy_id: str) -> dict | None:
        return _pick_shadow_candidate_impl(self, cluster_id, champion_strategy_id)

    def _apply_complexity_probe(self, plan: dict) -> dict:
        return apply_complexity_probe(plan)

    def _preflight_provider_budget(self, plan: dict) -> dict:
        return preflight_provider_budget(plan, compass=self._compass, registry=self._load_model_registry())

    def _pick_alias_for_provider(
        self,
        provider: str,
        registry: dict[str, dict],
        *,
        prefer_alias: str = "",
    ) -> tuple[str, str]:
        return pick_alias_for_provider(provider, registry, prefer_alias=prefer_alias)

    def _annotate_capability_graph(self, plan: dict, cluster_id: str) -> None:
        _annotate_capability_graph_impl(plan, cluster_id)

    async def replay(self, run_id: str, plan: dict) -> dict:
        return await _replay_impl(self, run_id, plan)

    def _update_replay_state(
        self,
        run_id: str,
        runs: list,
        run_status: str,
        attempts: int | None = None,
        next_replay_utc: str | None = None,
        reason: str | None = None,
    ) -> None:
        _update_replay_state_impl(
            self,
            run_id,
            runs,
            run_status,
            attempts=attempts,
            next_replay_utc=next_replay_utc,
            reason=reason,
        )

    def _notify_run_started(self, plan: dict) -> None:
        import os as _os

        prefs = {}
        try:
            prefs = self._compass.all_prefs() if self._compass else {}
        except Exception:
            pass
        if prefs.get("telegram_enabled") != "true":
            return

        adapter_url = _os.environ.get("TELEGRAM_ADAPTER_URL", "http://127.0.0.1:8001")
        try:
            import httpx as _httpx

            _httpx.post(
                f"{adapter_url}/notify",
                json={
                    "event": "run_started",
                    "payload": {
                        "run_id": str(plan.get("run_id") or ""),
                        "title": str(plan.get("title") or plan.get("run_type") or "运行"),
                        "work_scale": str(plan.get("work_scale") or "thread"),
                        "run_type": str(plan.get("run_type") or ""),
                    },
                },
                timeout=5,
            )
        except Exception as exc:
            logger.warning("Telegram notify run_started failed: %s", exc)

    def _make_run_root(self, run_id: str, is_shadow: bool = False) -> str:
        runs_dir = (self._state / "runs_shadow" / run_id) if is_shadow else (self._state / "runs" / run_id)
        runs_dir.mkdir(parents=True, exist_ok=True)
        return str(runs_dir)

    def _record_run(self, plan: dict, run_status: str, run_root: str) -> None:
        runs = self._store.load_runs()
        run_id = str(plan.get("run_id") or "")
        work_scale = str(plan.get("work_scale") or "")
        for row in runs:
            if str(row.get("run_id") or "") != run_id:
                continue
            row["run_status"] = run_status
            row["updated_utc"] = _utc()
            if work_scale:
                row["work_scale"] = work_scale
            if plan.get("campaign_id"):
                row["campaign_id"] = str(plan.get("campaign_id") or "")
            if plan.get("last_error"):
                row["last_error"] = plan.get("last_error")
            if run_root:
                row["run_root"] = run_root
            if "cluster_id" in plan:
                row["semantic_cluster"] = plan.get("cluster_id", "")
            if "strategy_id" in plan:
                row["strategy_id"] = plan.get("strategy_id", "")
            if "strategy_stage" in plan:
                row["strategy_stage"] = plan.get("strategy_stage", "")
            if "global_score_components" in plan:
                row["global_score_components"] = plan.get("global_score_components") or {}
            break
        else:
            runs.append(
                {
                    "run_id": run_id,
                    "title": plan.get("title", ""),
                    "run_type": plan.get("run_type", ""),
                    "work_scale": work_scale or "thread",
                    "campaign_id": str(plan.get("campaign_id") or ""),
                    "run_status": run_status,
                    "run_root": run_root,
                    "submitted_utc": _utc(),
                    "updated_utc": _utc(),
                    "priority": plan.get("priority", 5),
                    "semantic_cluster": plan.get("cluster_id", ""),
                    "strategy_id": plan.get("strategy_id", ""),
                    "strategy_stage": plan.get("strategy_stage", ""),
                    "global_score_components": plan.get("global_score_components") or {},
                    "plan": plan,
                    "last_error": plan.get("last_error", ""),
                }
            )
        self._store.save_runs(runs)

    def _queue_run(self, plan: dict) -> None:
        plan_copy = dict(plan)
        plan_copy["run_status"] = "queued"
        plan_copy["queued_utc"] = _utc()
        self._record_run(plan_copy, "queued", "")

    def _read_gate(self) -> dict:
        return self._store.load_gate()


def _new_run_id() -> str:
    ts = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    return f"run_{ts}_{uuid.uuid4().hex[:6]}"
