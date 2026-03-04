"""Dispatch — semantic routing, plan validation, Playbook strategy, Temporal submission."""
from __future__ import annotations

import json
import logging
import random
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.semantic import SemanticFingerprint, SemanticGenerator, SemanticMappingError

if TYPE_CHECKING:
    from fabric.playbook import PlaybookFabric
    from fabric.compass import CompassFabric
    from runtime.cortex import Cortex
    from spine.nerve import Nerve

# Replay backoff schedule in seconds (capped at 4h).
_REPLAY_BACKOFF = [60, 300, 900, 3600, 14400]
_REPLAY_MAX_ATTEMPTS = 5


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
        task_queue: str = "daemon-queue",
        cortex: "Cortex | None" = None,
    ) -> None:
        self._playbook = playbook
        self._compass = compass
        self._nerve = nerve
        self._state = state_dir
        self._temporal = temporal_client
        self._task_queue = task_queue
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
        # Clear stale queue markers before re-evaluating gate policy (important for replay).
        plan.pop("queued", None)
        plan.pop("queue_reason", None)
        plan.pop("status", None)
        task_type = str(plan.get("task_type") or plan.get("method") or "research_report")
        plan.setdefault("task_type", task_type)
        plan.setdefault("task_id", _new_task_id())
        agent_defaults = self._agent_defaults_from_compass() or dict(self._agent_defaults)
        plan.setdefault("agent_concurrency_defaults", dict(agent_defaults))
        plan.setdefault("agent_concurrency", dict(agent_defaults))

        # Compatibility path: enrich() may be called directly without prior semantic resolution.
        if not str(plan.get("cluster_id") or "").strip():
            try:
                fp = self._semantic.from_task_type(task_type, title=str(plan.get("title") or ""))
                plan["cluster_id"] = fp.cluster_id
                plan.setdefault("semantic_fingerprint", fp.to_dict())
                self._annotate_capability_graph(plan, fp.cluster_id)
            except Exception as exc:
                logger.warning("Failed to derive cluster_id from task_type=%s: %s", task_type, exc)

        # Consult Playbook for best matching method.
        methods = self._playbook.consult(category="dag_pattern")
        best = None
        for m in methods:
            if m["name"] == task_type or not best:
                best = m
                if m["name"] == task_type:
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

        # Apply Compass quality profile as timeout hint.
        quality = self._compass.get_quality_profile(task_type)
        plan.setdefault("quality_profile", quality)
        default_timeout = int(self._compass.get_pref("default_step_timeout_s", "480") or 480)
        plan.setdefault("default_step_timeout_s", default_timeout)
        plan.setdefault("model_primary", self._compass.get_pref("model_primary", ""))
        plan.setdefault("resource_budgets", self._compass.all_budgets())
        plan = self._apply_strategy(plan)

        # Gate check — apply priority to queued vs immediate.
        gate = self._read_gate()
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
        """Inject champion strategy parameters for the resolved semantic cluster."""
        cluster_id = str(plan.get("cluster_id") or "")
        if not cluster_id:
            raise ValueError("missing_cluster_id")

        champion = self._playbook.get_champion(cluster_id)
        if not champion:
            # Cold-start resilience: ensure cluster has a seeded champion strategy.
            try:
                self._playbook.seed_clusters([{"cluster_id": cluster_id, "display_name": cluster_id}])
                champion = self._playbook.get_champion(cluster_id)
            except Exception as exc:
                logger.warning("Failed to auto-seed champion for cluster=%s: %s", cluster_id, exc)
        if not champion:
            raise ValueError(f"no_champion_strategy_for_cluster:{cluster_id}")

        plan["strategy_id"] = champion.get("strategy_id", "")
        plan["strategy_stage"] = champion.get("stage", "champion")
        if isinstance(champion.get("score_components"), dict):
            plan.setdefault("global_score_components", champion.get("score_components") or {})

        spec = champion.get("spec") if isinstance(champion.get("spec"), dict) else {}
        if spec:
            if isinstance(spec.get("concurrency"), dict):
                existing = plan.get("concurrency") if isinstance(plan.get("concurrency"), dict) else {}
                plan["concurrency"] = {**spec.get("concurrency", {}), **existing}
            if isinstance(spec.get("timeout_hints"), dict):
                existing_hints = plan.get("timeout_hints") if isinstance(plan.get("timeout_hints"), dict) else {}
                plan["timeout_hints"] = {**spec.get("timeout_hints", {}), **existing_hints}
            if isinstance(spec.get("agent_concurrency"), dict):
                existing_agent = plan.get("agent_concurrency") if isinstance(plan.get("agent_concurrency"), dict) else {}
                plan["agent_concurrency"] = {**spec.get("agent_concurrency", {}), **existing_agent}
            if "rework_budget" in spec:
                plan.setdefault("rework_budget", int(spec.get("rework_budget") or 2))
            if "rework_strategy" in spec:
                plan.setdefault("rework_strategy", str(spec.get("rework_strategy") or "error_code_based"))
            if "model_alias" in spec:
                plan.setdefault("model_alias", str(spec.get("model_alias") or ""))

        self._apply_model_routing(plan, spec if isinstance(spec, dict) else {})

        return plan

    def _load_model_policy(self) -> dict:
        if not self._model_policy_path.exists():
            return {}
        try:
            data = json.loads(self._model_policy_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as exc:
            logger.warning("Failed to load model policy: %s", exc)
            return {}

    def _load_model_registry(self) -> dict[str, dict]:
        if not self._model_registry_path.exists():
            return {}
        try:
            data = json.loads(self._model_registry_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load model registry: %s", exc)
            return {}
        models = data.get("models") if isinstance(data.get("models"), list) else []
        out: dict[str, dict] = {}
        for m in models:
            if not isinstance(m, dict):
                continue
            alias = str(m.get("alias") or "").strip()
            if not alias:
                continue
            if alias in out:
                logger.warning("Duplicate alias in model registry ignored: %s", alias)
                continue
            out[alias] = m
        return out

    def _resolve_capability_key(self, step: dict) -> str:
        capability_id = str(step.get("capability_id") or "")
        if not capability_id:
            return ""
        if capability_id in {"intake", "record", "tend", "pulse", "judge", "relay", "witness", "learn", "distill", "focus"}:
            return capability_id
        # capability_id usually looks like clst_xxx:step_id
        if ":" in capability_id:
            return capability_id.split(":")[-1].strip().lower()
        return capability_id.strip().lower()

    def _apply_model_routing(self, plan: dict, strategy_spec: dict) -> None:
        policy = self._load_model_policy()
        registry = self._load_model_registry()
        if not policy or not registry:
            return

        fp = plan.get("semantic_fingerprint") if isinstance(plan.get("semantic_fingerprint"), dict) else {}
        risk = str(fp.get("risk_level") or "").strip().lower()
        cluster_id = str(plan.get("cluster_id") or "").strip()

        by_risk = policy.get("by_risk_level") if isinstance(policy.get("by_risk_level"), dict) else {}
        by_cluster = policy.get("by_semantic_cluster") if isinstance(policy.get("by_semantic_cluster"), dict) else {}
        by_cap = policy.get("by_capability") if isinstance(policy.get("by_capability"), dict) else {}
        default_alias = str(policy.get("default_alias") or "").strip()

        strategy_alias = str(strategy_spec.get("model_alias") or plan.get("model_alias") or "").strip()
        selected_alias = strategy_alias
        selected_source = "strategy_spec" if strategy_alias else ""
        if not selected_alias and risk and str(by_risk.get(risk) or "").strip():
            selected_alias = str(by_risk.get(risk) or "").strip()
            selected_source = f"by_risk_level:{risk}"
        if not selected_alias and cluster_id and str(by_cluster.get(cluster_id) or "").strip():
            selected_alias = str(by_cluster.get(cluster_id) or "").strip()
            selected_source = f"by_semantic_cluster:{cluster_id}"
        if not selected_alias and default_alias:
            selected_alias = default_alias
            selected_source = "default_alias"

        if selected_alias:
            entry = registry.get(selected_alias)
            if not entry:
                raise ValueError(f"invalid_model_alias:{selected_alias}")
            plan["model_alias"] = selected_alias
            plan["model_provider"] = str(entry.get("provider") or "")
            plan["model_id"] = str(entry.get("model_id") or "")

        steps = plan.get("steps") or plan.get("graph", {}).get("steps") or []
        step_aliases: dict[str, str] = {}
        if isinstance(steps, list):
            for i, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                sid = str(step.get("id") or step.get("step_id") or f"step_{i}")
                cap_key = self._resolve_capability_key(step)
                alias = str(by_cap.get(cap_key) or "").strip() if cap_key else ""
                if not alias:
                    continue
                entry = registry.get(alias)
                if not entry:
                    raise ValueError(f"invalid_model_alias:{alias}")
                step["model_alias"] = alias
                step["model_provider"] = str(entry.get("provider") or "")
                step["model_id"] = str(entry.get("model_id") or "")
                step_aliases[sid] = alias

        plan["model_routing"] = {
            "policy_version": str(policy.get("_version") or ""),
            "selected_alias": selected_alias,
            "selected_source": selected_source,
            "step_aliases": step_aliases,
        }

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

    def resolve_semantic(self, request: dict) -> "SemanticFingerprint":
        """Four-path semantic resolution (decision §1). Raises SemanticMappingError on failure.

        Path 1: caller provides semantic_fingerprint dict → validate cluster_id.
        Path 2: caller provides intent_contract dict → generate fingerprint.
        Path 3: caller provides task_type string → compat cluster mapping.
        Path 4: none of the above → SemanticMappingError (fail-closed, 400).
        """
        if fp_raw := request.get("semantic_fingerprint"):
            if isinstance(fp_raw, dict):
                return self._semantic.from_fingerprint_dict(fp_raw)

        if ic_raw := request.get("intent_contract"):
            if isinstance(ic_raw, dict):
                return self._semantic.from_intent_contract(ic_raw, cortex=self._cortex)

        if task_type := str(request.get("task_type") or "").strip():
            return self._semantic.from_task_type(task_type, title=str(request.get("title") or ""))

        raise SemanticMappingError("semantic_input_missing: provide semantic_fingerprint, intent_contract, or task_type")

    async def submit(self, plan: dict) -> dict:
        """Semantic resolve → validate → enrich → Temporal submit."""
        # Step 1: Semantic resolution (fail-closed).
        try:
            fingerprint = self.resolve_semantic(plan)
        except SemanticMappingError as exc:
            return {"ok": False, "error": str(exc), "error_code": "semantic_mapping_failed"}

        # Attach resolved fingerprint to plan.
        plan = dict(plan)
        plan["semantic_fingerprint"] = fingerprint.to_dict()
        plan.setdefault("cluster_id", fingerprint.cluster_id)
        self._annotate_capability_graph(plan, fingerprint.cluster_id)

        ok, err = self.validate(plan)
        if not ok:
            return {"ok": False, "error": err, "error_code": "invalid_plan"}

        try:
            plan = self.enrich(plan)
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "error_code": "strategy_guard_blocked"}

        task_id = plan["task_id"]
        plan.setdefault("trace_id", f"tr_task_{task_id}")

        if plan.get("queued"):
            self._queue_task(plan)
            return {"ok": True, "task_id": task_id, "status": "queued", "reason": plan.get("queue_reason")}

        if not self._temporal:
            self._record_task(plan, "failed_submission", "")
            return {
                "ok": False,
                "task_id": task_id,
                "error_code": "temporal_unavailable",
                "error": "Temporal client unavailable; submission rejected",
            }

        run_root = self._make_run_root(task_id)
        self._record_task(plan, "running", run_root)

        try:
            workflow_id = f"daemon-{task_id}"
            await self._temporal.submit(workflow_id, plan, run_root)
        except Exception as exc:
            logger.error("Temporal submit failed for task %s: %s", task_id, exc)
            self._record_task({**plan, "last_error": str(exc)[:300]}, "failed_submission", run_root)
            return {
                "ok": False,
                "task_id": task_id,
                "error_code": "temporal_submit_failed",
                "error": str(exc)[:400],
            }

        self._nerve.emit("task_submitted", {"task_id": task_id, "run_root": run_root})
        await self._maybe_submit_shadow(plan, parent_task_id=task_id)
        return {"ok": True, "task_id": task_id, "status": "running", "run_root": run_root}

    async def submit_sandbox(self, plan: dict, strategy_id: str) -> dict:
        """Submit an isolated sandbox run for candidate/shadow/challenger strategy."""
        try:
            fingerprint = self.resolve_semantic(plan)
        except SemanticMappingError as exc:
            return {"ok": False, "error": str(exc), "error_code": "semantic_mapping_failed"}

        plan = dict(plan)
        plan["semantic_fingerprint"] = fingerprint.to_dict()
        plan.setdefault("cluster_id", fingerprint.cluster_id)
        self._annotate_capability_graph(plan, fingerprint.cluster_id)

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
        stage = str(strategy.get("stage") or "")
        if stage not in {"candidate", "shadow", "challenger"}:
            return {"ok": False, "error": f"sandbox_stage_invalid:{stage}", "error_code": "strategy_guard_blocked"}
        cluster_id = str(plan.get("cluster_id") or "")
        if cluster_id and str(strategy.get("cluster_id") or "") != cluster_id:
            return {"ok": False, "error": "strategy_cluster_mismatch", "error_code": "strategy_guard_blocked"}

        task_id = str(plan.get("task_id") or _new_task_id())
        plan["task_id"] = task_id
        plan.setdefault("trace_id", f"tr_task_{task_id}")
        champion = self._playbook.get_champion(cluster_id) if cluster_id else None
        champion_id = str(champion.get("strategy_id") or "") if champion else ""
        plan["is_shadow"] = True
        plan["delivery_mode"] = "sandbox"
        plan["shadow_of"] = f"sandbox:{task_id}"
        plan["strategy_id"] = strategy_id
        plan["strategy_stage"] = stage
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
            self._record_task(plan, "failed_submission", "")
            return {
                "ok": False,
                "task_id": task_id,
                "error_code": "temporal_unavailable",
                "error": "Temporal client unavailable; submission rejected",
            }

        run_root = self._make_run_root(task_id, is_shadow=True)
        self._record_task(plan, "running_shadow", run_root)
        try:
            workflow_id = f"daemon-sandbox-{task_id}"
            await self._temporal.submit(workflow_id, plan, run_root)
        except Exception as exc:
            logger.error("Temporal sandbox submit failed for task %s: %s", task_id, exc)
            self._record_task({**plan, "last_error": str(exc)[:300]}, "failed_submission", run_root)
            return {
                "ok": False,
                "task_id": task_id,
                "error_code": "temporal_submit_failed",
                "error": str(exc)[:400],
            }

        self._nerve.emit(
            "sandbox_submitted",
            {
                "task_id": task_id,
                "strategy_id": strategy_id,
                "cluster_id": cluster_id,
                "stage": stage,
                "run_root": run_root,
            },
        )
        return {
            "ok": True,
            "task_id": task_id,
            "status": "running_shadow",
            "run_root": run_root,
            "strategy_id": strategy_id,
            "strategy_stage": stage,
        }

    async def _maybe_submit_shadow(self, plan: dict, parent_task_id: str) -> None:
        """Submit a shadow run on a non-champion strategy without impacting primary delivery."""
        if plan.get("is_shadow"):
            return
        if not self._temporal:
            return
        ratio = self._shadow_ratio()
        if ratio <= 0:
            return
        if random.random() > ratio:
            return

        cluster_id = str(plan.get("cluster_id") or "")
        champion_strategy_id = str(plan.get("strategy_id") or "")
        candidate = self._pick_shadow_candidate(cluster_id, champion_strategy_id)
        if not candidate:
            return

        shadow_task_id = f"{parent_task_id}_shadow_{uuid.uuid4().hex[:6]}"
        shadow_plan = dict(plan)
        shadow_plan["task_id"] = shadow_task_id
        shadow_plan["is_shadow"] = True
        shadow_plan["shadow_of"] = parent_task_id
        shadow_plan["strategy_id"] = candidate.get("strategy_id", "")
        shadow_plan["strategy_stage"] = "shadow"
        shadow_plan["shadow_champion_strategy_id"] = champion_strategy_id
        shadow_plan["delivery_mode"] = "shadow"

        spec = candidate.get("spec") if isinstance(candidate.get("spec"), dict) else {}
        if spec:
            if isinstance(spec.get("concurrency"), dict):
                current = shadow_plan.get("concurrency") if isinstance(shadow_plan.get("concurrency"), dict) else {}
                shadow_plan["concurrency"] = {**spec.get("concurrency", {}), **current}
            if isinstance(spec.get("timeout_hints"), dict):
                current_hints = shadow_plan.get("timeout_hints") if isinstance(shadow_plan.get("timeout_hints"), dict) else {}
                shadow_plan["timeout_hints"] = {**spec.get("timeout_hints", {}), **current_hints}

        run_root = self._make_run_root(shadow_task_id, is_shadow=True)
        self._record_task(shadow_plan, "running_shadow", run_root)
        try:
            workflow_id = f"daemon-shadow-{shadow_task_id}"
            await self._temporal.submit(workflow_id, shadow_plan, run_root)
        except Exception as exc:
            logger.warning("Shadow submit failed for %s: %s", shadow_task_id, exc)
            self._record_task({**shadow_plan, "last_error": str(exc)[:300]}, "failed_submission", run_root)
            return

        self._nerve.emit(
            "shadow_submitted",
            {
                "task_id": shadow_task_id,
                "shadow_of": parent_task_id,
                "strategy_id": shadow_plan.get("strategy_id", ""),
                "cluster_id": cluster_id,
            },
        )

    def _shadow_ratio(self) -> float:
        raw = self._compass.get_pref("strategy_shadow_ratio", "0.10")
        try:
            ratio = float(raw)
        except Exception:
            return 0.10
        return max(0.0, min(1.0, ratio))

    def _pick_shadow_candidate(self, cluster_id: str, champion_strategy_id: str) -> dict | None:
        if not cluster_id:
            return None
        all_rows = self._playbook.list_strategies(cluster_id=cluster_id)
        if not all_rows:
            return None
        preferred = [
            r
            for r in all_rows
            if str(r.get("strategy_id") or "") != champion_strategy_id
            and str(r.get("stage") or "") in {"shadow", "challenger"}
        ]
        fallback = [
            r
            for r in all_rows
            if str(r.get("strategy_id") or "") != champion_strategy_id
            and str(r.get("stage") or "") in {"candidate"}
        ]
        candidates = preferred or fallback
        if not candidates:
            seeded = self._playbook.spawn_candidate_from_champion(cluster_id=cluster_id, stage="candidate")
            if not seeded:
                return None
            return seeded
        best = sorted(
            candidates,
            key=lambda x: (float(x.get("global_score") or 0.0), int(x.get("sample_n") or 0)),
            reverse=True,
        )[0]
        if str(best.get("stage") or "") == "candidate":
            try:
                self._playbook.promote_strategy(
                    strategy_id=str(best.get("strategy_id") or ""),
                    decision="enter_shadow_auto",
                    prev_stage="candidate",
                    next_stage="shadow",
                    reason="selected_for_shadow_execution",
                    decided_by="dispatch",
                )
                refreshed = self._playbook.get_strategy(str(best.get("strategy_id") or ""))
                if refreshed:
                    return refreshed
            except Exception as exc:
                logger.warning("Failed to transition candidate to shadow: %s", exc)
        return best

    def _annotate_capability_graph(self, plan: dict, cluster_id: str) -> None:
        """Ensure each DAG node carries capability_id + quality_contract_id."""
        steps = plan.get("steps") or plan.get("graph", {}).get("steps") or []
        if not isinstance(steps, list):
            return
        contract_id = str(plan.get("task_type") or "default")
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                continue
            sid = str(step.get("id") or step.get("step_id") or f"step_{i}")
            step.setdefault("capability_id", f"{cluster_id}:{sid}")
            step.setdefault("quality_contract_id", contract_id)

    async def replay(self, task_id: str, plan: dict) -> dict:
        """Replay a queued task with backoff enforcement (decision §7)."""
        tasks_path = self._state / "tasks.json"
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read tasks.json for replay: %s", exc)
            tasks = []

        task_record: dict | None = next((t for t in tasks if t.get("task_id") == task_id), None)

        if task_record:
            attempts = int(task_record.get("replay_attempts", 0))
            next_replay_utc = str(task_record.get("next_replay_utc") or "")
            if attempts >= _REPLAY_MAX_ATTEMPTS:
                self._update_replay_state(task_id, tasks, tasks_path, status="replay_exhausted",
                                          reason=f"exceeded max_attempts={_REPLAY_MAX_ATTEMPTS}")
                return {"ok": False, "task_id": task_id, "error_code": "replay_exhausted",
                        "error": f"Max replay attempts ({_REPLAY_MAX_ATTEMPTS}) exceeded"}
            if next_replay_utc and next_replay_utc > _utc():
                return {"ok": False, "task_id": task_id, "error_code": "replay_too_soon",
                        "error": f"Next replay not due until {next_replay_utc}"}

        replay_plan = dict(plan)
        replay_plan["task_id"] = task_id
        replay_plan.pop("queued", None)
        replay_plan.pop("queue_reason", None)
        replay_plan.pop("status", None)
        replay_plan["replay_token"] = f"rpl_{uuid.uuid4().hex[:12]}"

        result = await self.submit(replay_plan)

        if task_record:
            attempts = int(task_record.get("replay_attempts", 0)) + 1
            backoff_s = _REPLAY_BACKOFF[min(attempts - 1, len(_REPLAY_BACKOFF) - 1)]
            next_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + backoff_s))
            self._update_replay_state(task_id, tasks, tasks_path,
                                      status="running" if result.get("ok") else "queued",
                                      attempts=attempts, next_replay_utc=next_utc)

        return result

    def _update_replay_state(
        self,
        task_id: str,
        tasks: list,
        tasks_path: Path,
        status: str,
        attempts: int | None = None,
        next_replay_utc: str | None = None,
        reason: str | None = None,
    ) -> None:
        for t in tasks:
            if t.get("task_id") == task_id:
                t["status"] = status
                t["updated_utc"] = _utc()
                if attempts is not None:
                    t["replay_attempts"] = attempts
                if next_replay_utc is not None:
                    t["next_replay_utc"] = next_replay_utc
                if reason:
                    t["replay_exhausted_reason"] = reason
                break
        try:
            tmp = tasks_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
            tmp.replace(tasks_path)
        except Exception as exc:
            logger.warning("Failed to update replay state for %s: %s", task_id, exc)

    def _make_run_root(self, task_id: str, is_shadow: bool = False) -> str:
        runs_dir = (self._state / "runs_shadow" / task_id) if is_shadow else (self._state / "runs" / task_id)
        runs_dir.mkdir(parents=True, exist_ok=True)
        return str(runs_dir)

    def _record_task(self, plan: dict, status: str, run_root: str) -> None:
        tasks_path = self._state / "tasks.json"
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to parse tasks.json at %s: %s", tasks_path, exc)
            tasks = []
        task_id = plan.get("task_id", "")
        for t in tasks:
            if t.get("task_id") == task_id:
                t["status"] = status
                t["updated_utc"] = _utc()
                if plan.get("last_error"):
                    t["last_error"] = plan.get("last_error")
                if run_root:
                    t["run_root"] = run_root
                if "cluster_id" in plan:
                    t["semantic_cluster"] = plan.get("cluster_id", "")
                if "strategy_id" in plan:
                    t["strategy_id"] = plan.get("strategy_id", "")
                if "strategy_stage" in plan:
                    t["strategy_stage"] = plan.get("strategy_stage", "")
                if "global_score_components" in plan:
                    t["global_score_components"] = plan.get("global_score_components") or {}
                break
        else:
            tasks.append({
                "task_id": task_id,
                "title": plan.get("title", ""),
                "task_type": plan.get("task_type", ""),
                "status": status,
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
            })
        tmp = tasks_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
        tmp.replace(tasks_path)

    def _queue_task(self, plan: dict) -> None:
        plan_copy = dict(plan)
        plan_copy["status"] = "queued"
        plan_copy["queued_utc"] = _utc()
        self._record_task(plan_copy, "queued", "")

    def _read_gate(self) -> dict:
        gate_path = self._state / "gate.json"
        if not gate_path.exists():
            return {"status": "GREEN"}
        try:
            return json.loads(gate_path.read_text())
        except Exception as exc:
            logger.warning("Failed to parse gate file %s: %s", gate_path, exc)
            return {"status": "GREEN"}


def _new_task_id() -> str:
    ts = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    return f"task_{ts}_{uuid.uuid4().hex[:6]}"
