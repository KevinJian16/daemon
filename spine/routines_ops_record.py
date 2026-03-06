"""Spine record routine implementation."""
from __future__ import annotations

from typing import Any


def run_record(self, run_id: str, plan: dict, step_results: list[dict], outcome: dict) -> dict:
    with self.tracer.span("spine.record", trigger="nerve:run_completed") as ctx:
        recipe_name = plan.get("run_type") or "research_report"
        status = "success" if outcome.get("ok") else "failure"
        score = float(outcome.get("score", 1.0 if outcome.get("ok") else 0.0))

        method_id: str | None = None
        plan_method_id = str(plan.get("method_id") or "").strip()
        if plan_method_id:
            method_row = self.playbook.get(plan_method_id)
            if method_row:
                method_id = plan_method_id

        if not method_id:
            methods = self.playbook.consult(category="dag_pattern")
            for m in methods:
                if m["name"] == recipe_name:
                    method_id = m["method_id"]
                    break

        if method_id:
            eval_detail = {
                "run_id": run_id,
                "steps": len(step_results),
                "failed_steps": sum(1 for r in step_results if r.get("status") == "error"),
                "plan_title": str(plan.get("run_title") or plan.get("title") or "")[:100],
            }
            self.playbook.evaluate(method_id, run_id, status, score, eval_detail)
            ctx.step("playbook_eval", {"method_id": method_id, "outcome": status})

        used_unit_ids: list[str] = plan.get("evidence_unit_ids") or []
        for uid in used_unit_ids:
            self.memory.record_usage(uid, run_id, method_id, status)
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
                run_id=run_id,
                cluster_id=cluster_id,
                score_components=strategy_components,
                global_score=strategy_global_score,
                outcome=status,
                is_shadow=bool(plan.get("is_shadow", False)),
            )
            self._update_run_strategy(
                run_id=run_id,
                semantic_cluster=cluster_id,
                strategy_id=strategy_id,
                strategy_stage=strategy_stage or "champion",
                global_score_components=strategy_components,
                global_score=strategy_global_score,
                trace_id=ctx.trace_id,
            )
            if bool(plan.get("is_shadow")):
                self._write_shadow_comparison(
                    run_id=run_id,
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
            "run_id": run_id,
            "outcome": status,
            "method_id": method_id,
            "strategy_id": strategy_id,
            "semantic_cluster": cluster_id,
            "global_score": round(strategy_global_score, 4) if strategy_global_score is not None else None,
        }
        ctx.set_result(result)
    return result
