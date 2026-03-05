"""Dispatch model policy/registry routing helpers."""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def load_model_policy(dispatch) -> dict:
    if not dispatch._model_policy_path.exists():
        return {}
    try:
        data = json.loads(dispatch._model_policy_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Failed to load model policy: %s", exc)
        return {}


def load_model_registry(dispatch) -> dict[str, dict]:
    if not dispatch._model_registry_path.exists():
        return {}
    try:
        data = json.loads(dispatch._model_registry_path.read_text(encoding="utf-8"))
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


def resolve_capability_key(step: dict) -> str:
    capability_id = str(step.get("capability_id") or "")
    if not capability_id:
        return ""
    if capability_id in {"intake", "record", "tend", "pulse", "judge", "relay", "witness", "learn", "distill", "focus"}:
        return capability_id
    if ":" in capability_id:
        return capability_id.split(":")[-1].strip().lower()
    return capability_id.strip().lower()


def apply_model_routing(dispatch, plan: dict, strategy_spec: dict) -> None:
    policy = load_model_policy(dispatch)
    registry = load_model_registry(dispatch)
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
            cap_key = resolve_capability_key(step)
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
