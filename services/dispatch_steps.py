"""Reusable dispatch pipeline steps."""
from __future__ import annotations

import time
from typing import Any


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def apply_complexity_probe(plan: dict) -> dict:
    out = dict(plan)
    steps = out.get("steps") or out.get("graph", {}).get("steps") or []
    if not isinstance(steps, list):
        steps = []
    n_steps = len([s for s in steps if isinstance(s, dict)])
    probe = out.get("complexity_probe") if isinstance(out.get("complexity_probe"), dict) else {}
    estimated_phases = int(probe.get("estimated_phases") or out.get("estimated_phases") or max(1, n_steps or 1))
    estimated_hours = float(probe.get("estimated_hours") or out.get("estimated_hours") or max(0.5, n_steps * 0.75))
    requires_campaign = bool(
        probe.get("requires_campaign")
        or out.get("requires_campaign")
        or estimated_phases > 4
        or estimated_hours > 4.0
    )
    if requires_campaign:
        task_scale = "campaign"
    elif estimated_phases <= 2 and estimated_hours <= 1.0:
        task_scale = "pulse"
    else:
        task_scale = "thread"
    out["complexity_probe"] = {
        "estimated_phases": estimated_phases,
        "estimated_hours": round(estimated_hours, 2),
        "requires_campaign": requires_campaign,
    }
    out["task_scale"] = task_scale
    return out


def pick_alias_for_provider(
    provider: str,
    registry: dict[str, dict],
    *,
    prefer_alias: str = "",
) -> tuple[str, str]:
    provider = str(provider or "").strip().lower()
    if prefer_alias:
        row = registry.get(prefer_alias)
        if row and str(row.get("provider") or "").strip().lower() == provider:
            return prefer_alias, str(row.get("model_id") or "")

    for alias in ("fast", "analysis", "review", "qwen", "glm", "fallback"):
        row = registry.get(alias)
        if not row:
            continue
        if str(row.get("provider") or "").strip().lower() == provider:
            return alias, str(row.get("model_id") or "")

    for alias, row in registry.items():
        if str(row.get("provider") or "").strip().lower() == provider:
            return alias, str(row.get("model_id") or "")
    return "", ""


def preflight_provider_budget(plan: dict, *, compass: Any, registry: dict[str, dict]) -> dict:
    out = dict(plan)
    current_alias = str(out.get("model_alias") or "").strip()
    current_provider = str(out.get("model_provider") or "").strip().lower()
    if current_alias and not current_provider and current_alias in registry:
        current_provider = str(registry[current_alias].get("provider") or "").strip().lower()
        out["model_provider"] = current_provider
        out["model_id"] = str(registry[current_alias].get("model_id") or "")

    chain = []
    if current_provider:
        chain.append(current_provider)
    for p in ("minimax", "qwen", "zhipu", "deepseek"):
        if p not in chain:
            chain.append(p)

    scale = str(out.get("task_scale") or "thread")
    default_budget_probe = {"pulse": 20_000, "thread": 80_000, "campaign": 160_000}
    est_tokens = int(out.get("estimated_tokens") or default_budget_probe.get(scale, 80_000))
    checks: list[dict[str, Any]] = []
    selected_provider = ""
    selected_alias = ""
    selected_model_id = ""
    for provider in chain:
        budget = compass.get_budget(f"{provider}_tokens")
        if not budget:
            checks.append(
                {
                    "provider": provider,
                    "resource_type": f"{provider}_tokens",
                    "daily_limit": None,
                    "current_usage": None,
                    "remaining": None,
                    "admit": False,
                    "reason": "budget_not_configured",
                }
            )
            continue
        daily_limit = float(budget.get("daily_limit") or 0.0)
        current_usage = float(budget.get("current_usage") or 0.0)
        remaining = max(0.0, daily_limit - current_usage)
        admit = remaining >= float(est_tokens)
        checks.append(
            {
                "provider": provider,
                "resource_type": f"{provider}_tokens",
                "daily_limit": daily_limit,
                "current_usage": current_usage,
                "remaining": remaining,
                "admit": admit,
                "reason": "ok" if admit else "insufficient_budget",
            }
        )
        if admit and not selected_provider:
            selected_provider = provider

    if selected_provider:
        alias, model_id = pick_alias_for_provider(selected_provider, registry, prefer_alias=current_alias)
        selected_alias = alias
        selected_model_id = model_id
        if selected_alias:
            out["model_alias"] = selected_alias
        out["model_provider"] = selected_provider
        if selected_model_id:
            out["model_id"] = selected_model_id
    else:
        out["queued"] = True
        out["queue_reason"] = "provider_budget_insufficient"

    out["provider_routing"] = {
        "estimated_tokens": est_tokens,
        "fallback_chain": chain,
        "selected_provider": selected_provider,
        "selected_alias": selected_alias,
        "selected_model_id": selected_model_id,
        "checks": checks,
        "checked_utc": _utc(),
    }
    return out
