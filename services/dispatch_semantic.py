"""Dispatch semantic resolution and capability annotation."""
from __future__ import annotations

from runtime.semantic import SemanticSpec, SemanticMappingError


def resolve_semantic(dispatch, request: dict) -> SemanticSpec:
    if fp_raw := request.get("semantic_spec"):
        if isinstance(fp_raw, dict):
            return dispatch._semantic.from_spec_dict(fp_raw)

    if ic_raw := request.get("intent_contract"):
        if isinstance(ic_raw, dict):
            return dispatch._semantic.from_intent_contract(ic_raw, cortex=dispatch._cortex)

    if run_type := str(request.get("run_type") or "").strip():
        return dispatch._semantic.from_run_type(run_type, title=str(request.get("title") or ""))

    raise SemanticMappingError("semantic_input_missing: provide semantic_spec, intent_contract, or run_type")


def annotate_capability_graph(plan: dict, cluster_id: str) -> None:
    steps = plan.get("steps") or plan.get("graph", {}).get("steps") or []
    if not isinstance(steps, list):
        return
    contract_id = str(plan.get("run_type") or "default")
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id") or step.get("step_id") or f"step_{i}")
        step.setdefault("capability_id", f"{cluster_id}:{sid}")
        step.setdefault("quality_contract_id", contract_id)
