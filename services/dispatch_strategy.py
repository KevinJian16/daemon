"""Dispatch strategy/shadow helpers."""
from __future__ import annotations

import logging
import random
import uuid

from services.dispatch_model import apply_model_routing

logger = logging.getLogger(__name__)


def apply_strategy(dispatch, plan: dict) -> dict:
    cluster_id = str(plan.get("cluster_id") or "")
    if not cluster_id:
        raise ValueError("missing_cluster_id")

    champion = dispatch._playbook.get_champion(cluster_id) or {}
    if not champion:
        try:
            dispatch._playbook.seed_clusters([{"cluster_id": cluster_id, "display_name": cluster_id}])
            champion = dispatch._playbook.get_champion(cluster_id) or {}
        except Exception as exc:
            logger.warning("Failed to auto-seed champion for cluster=%s: %s", cluster_id, exc)
    if not champion:
        raise ValueError(f"no_champion_strategy_for_cluster:{cluster_id}")

    plan["strategy_id"] = champion.get("strategy_id", "")
    plan["strategy_stage"] = champion.get("strategy_stage", "champion")
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

    apply_model_routing(dispatch, plan, spec if isinstance(spec, dict) else {})
    return plan


def shadow_ratio(dispatch) -> float:
    raw = dispatch._compass.get_pref("strategy_shadow_ratio", "0.10")
    try:
        ratio = float(raw)
    except Exception:
        return 0.10
    return max(0.0, min(1.0, ratio))


def pick_shadow_candidate(dispatch, cluster_id: str, champion_strategy_id: str) -> dict | None:
    if not cluster_id:
        return None
    all_rows = dispatch._playbook.list_strategies(cluster_id=cluster_id)
    if not all_rows:
        return None
    preferred = [
        r
        for r in all_rows
        if str(r.get("strategy_id") or "") != champion_strategy_id
        and str(r.get("strategy_stage") or "") in {"shadow", "challenger"}
    ]
    fallback = [
        r
        for r in all_rows
        if str(r.get("strategy_id") or "") != champion_strategy_id
        and str(r.get("strategy_stage") or "") in {"candidate"}
    ]
    candidates = preferred or fallback
    if not candidates:
        seeded = dispatch._playbook.spawn_candidate_from_champion(cluster_id=cluster_id, strategy_stage="candidate")
        if not seeded:
            return None
        return seeded
    best = sorted(
        candidates,
        key=lambda x: (float(x.get("global_score") or 0.0), int(x.get("sample_n") or 0)),
        reverse=True,
    )[0]
    if str(best.get("strategy_stage") or "") == "candidate":
        try:
            dispatch._playbook.promote_strategy(
                strategy_id=str(best.get("strategy_id") or ""),
                decision="enter_shadow_auto",
                prev_strategy_stage="candidate",
                next_strategy_stage="shadow",
                reason="selected_for_shadow_execution",
                decided_by="dispatch",
            )
            refreshed = dispatch._playbook.get_strategy(str(best.get("strategy_id") or ""))
            if refreshed:
                return refreshed
        except Exception as exc:
            logger.warning("Failed to transition candidate to shadow: %s", exc)
    return best


async def maybe_submit_shadow(dispatch, plan: dict, parent_run_id: str) -> None:
    if plan.get("is_shadow"):
        return
    if not dispatch._temporal:
        return
    ratio = shadow_ratio(dispatch)
    if ratio <= 0:
        return
    if random.random() > ratio:
        return

    cluster_id = str(plan.get("cluster_id") or "")
    champion_strategy_id = str(plan.get("strategy_id") or "")
    candidate = pick_shadow_candidate(dispatch, cluster_id, champion_strategy_id)
    if not candidate:
        return

    shadow_run_id = f"{parent_run_id}_shadow_{uuid.uuid4().hex[:6]}"
    shadow_plan = dict(plan)
    shadow_plan["run_id"] = shadow_run_id
    shadow_plan["is_shadow"] = True
    shadow_plan["shadow_of"] = parent_run_id
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

    run_root = dispatch._make_run_root(shadow_run_id, is_shadow=True)
    dispatch._record_run(shadow_plan, "running_shadow", run_root)
    try:
        workflow_id = f"daemon-shadow-{shadow_run_id}"
        await dispatch._temporal.submit(workflow_id, shadow_plan, run_root)
    except Exception as exc:
        logger.warning("Shadow submit failed for %s: %s", shadow_run_id, exc)
        dispatch._record_run({**shadow_plan, "last_error": str(exc)[:300]}, "failed_submission", run_root)
        return

    dispatch._nerve.emit(
        "shadow_submitted",
        {
            "run_id": shadow_run_id,
            "shadow_of": parent_run_id,
            "strategy_id": shadow_plan.get("strategy_id", ""),
            "cluster_id": cluster_id,
        },
    )
    strategy_stage = str(shadow_plan.get("strategy_stage") or "shadow")
    try:
        dispatch._playbook.record_release_execution(
            strategy_id=str(shadow_plan.get("strategy_id") or ""),
            cluster_id=cluster_id,
            strategy_stage=strategy_stage,
            mode="shadow",
            run_id=shadow_run_id,
            actor="dispatch",
            reason="shadow_submission",
            shadow_of=str(parent_run_id or ""),
        )
    except Exception as exc:
        logger.warning("Failed to record shadow release execution for %s: %s", shadow_run_id, exc)
