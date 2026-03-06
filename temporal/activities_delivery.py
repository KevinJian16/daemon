"""Temporal activities: quality and delivery-layer routines."""
from __future__ import annotations

from typing import Any


async def run_finalize_delivery(self, run_root: str, plan: dict, step_results: list[dict]) -> dict:
    from fabric.compass import CompassFabric

    home = self._home
    state = home / "state"
    compass = CompassFabric(state / "compass.db")
    is_shadow = bool(plan.get("is_shadow", False))

    run_type = str(plan.get("run_type") or "default").strip()
    cluster_id = str(plan.get("cluster_id") or "").strip()
    profile = compass.get_quality_profile(run_type)
    contract = self._load_quality_contract(cluster_id, run_type)

    render_path = self._find_render_output(run_root, step_results)
    if not render_path:
        return {
            "ok": False,
            "error_code": "render_output_missing",
            "detail": "No render output found",
            **self._failure_meta(plan),
        }

    content = render_path.read_text()

    check_result = self._structural_check(content, profile)
    if not check_result["ok"]:
        return {
            "ok": False,
            "error_code": check_result["error_code"],
            "detail": check_result["detail"],
            **self._failure_meta(plan),
        }

    quality_score, score_components = self._quality_score(content, plan, step_results, contract, profile)
    min_quality = float(contract.get("min_quality_score") or profile.get("min_quality_score") or 0.60)
    if quality_score < min_quality:
        return {
            "ok": False,
            "error_code": "quality_gate_failed",
            "detail": f"quality_score={round(quality_score,4)} below min_quality_score={round(min_quality,4)}",
            "quality_score": round(quality_score, 4),
            "min_quality_score": min_quality,
            "global_score_components": score_components,
            **self._failure_meta(plan),
        }

    drift = self._quality_drift_check(plan, quality_score, contract)
    if drift.get("blocked"):
        return {
            "ok": False,
            "error_code": "quality_drift_detected",
            "detail": str(drift.get("detail") or "quality drift detected"),
            "quality_score": round(quality_score, 4),
            "drift": drift,
            "global_score_components": score_components,
            **self._failure_meta(plan),
        }
    self._append_quality_score(plan, quality_score, score_components, drift)

    if is_shadow:
        outcome_path = self._archive_shadow_outcome(run_root, plan, render_path, step_results)
    else:
        outcome_root = self._resolve_outcome_root()
        outcome_path = self._archive_outcome(run_root, plan, render_path, step_results, outcome_root=outcome_root)
        self._update_outcome_index(outcome_path, plan, outcome_root=outcome_root)

    self._update_run_status(
        run_root,
        plan,
        "completed_shadow" if is_shadow else "completed",
        outcome_path=str(outcome_path),
    )

    feedback_survey: dict[str, Any] | None = None
    if not is_shadow:
        try:
            feedback_survey = self._generate_feedback_survey(plan=plan, outcome_path=outcome_path)
            self._write_feedback_survey(feedback_survey)
            self._event_bridge.emit("feedback_survey_generated", feedback_survey)
        except Exception as exc:
            from temporalio import activity
            activity.logger.warning("Failed to generate feedback survey for run %s: %s", plan.get("run_id", ""), exc)

    run_id = str(plan.get("run_id") or "")
    delivery_payload = {
        "run_id": run_id,
        "plan": plan,
        "step_results": step_results,
        "outcome": {
            "ok": True,
            "score": round(quality_score, 4),
            "outcome_path": str(outcome_path),
            "is_shadow": is_shadow,
            "global_score_components": score_components,
        },
    }
    if feedback_survey:
        delivery_payload["feedback_survey"] = feedback_survey
    if not is_shadow:
        self._event_bridge.emit("delivery_completed", delivery_payload)
    self._event_bridge.emit("run_completed", delivery_payload)
    from temporalio import activity
    activity.logger.info("Delivery completed for run %s; bridge events emitted", run_id)

    return {
        "ok": True,
        "outcome_path": str(outcome_path),
        "run_id": run_id,
        "delivered_utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
        "is_shadow": is_shadow,
        "quality_score": round(quality_score, 4),
        "global_score_components": score_components,
        "feedback_survey": feedback_survey or {},
    }


async def run_update_run_status(self, run_root: str, plan: dict, run_status: str) -> dict:
    run_status = str(run_status or "")
    self._update_run_status(run_root, plan, run_status)
    if run_status in {"failed", "cancelled"}:
        run_id = str(plan.get("run_id") or "")
        self._event_bridge.emit(
            "run_completed",
            {
                "run_id": run_id,
                "plan": plan,
                "step_results": [],
                "outcome": {
                    "ok": False,
                    "score": 0.0,
                    "run_status": run_status,
                    "error": plan.get("last_error", ""),
                    **self._failure_meta(plan),
                },
            },
        )
    return {"ok": True, "run_status": run_status}
