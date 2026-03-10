"""Temporal activities: herald-layer routines (pure logistics)."""
from __future__ import annotations

from typing import Any


async def run_finalize_herald(self, deed_root: str, plan: dict, move_results: list[dict]) -> dict:
    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    scribe_path = self._find_scribe_output(deed_root, move_results)
    if not scribe_path:
        return {
            "ok": False,
            "error_code": "scribe_output_missing",
            "detail": "No scribe output found",
        }

    quality_check = self._quality_floor_check(deed_root, plan, scribe_path, move_results)
    plan["_quality_check"] = quality_check
    if not quality_check.get("ok"):
        return {
            "ok": False,
            "error_code": str(quality_check.get("reason") or "quality_floor_not_met"),
            "detail": "Offering quality floor not met",
            "quality": quality_check,
        }

    offering_root = self._resolve_offering_root()
    offering_path = self._archive_offering(deed_root, plan, scribe_path, move_results, offering_root=offering_root)
    self._update_offering_index(offering_path, plan, offering_root=offering_root)

    self._update_deed_status(
        deed_root,
        plan,
        "completed",
        offering_path=str(offering_path),
    )

    feedback_survey: dict[str, Any] | None = None
    try:
        feedback_survey = self._generate_feedback_survey(plan=plan, offering_path=offering_path)
        self._write_feedback_survey(feedback_survey)
        self._ether.emit("feedback_survey_generated", feedback_survey)
    except Exception as exc:
        from temporalio import activity
        activity.logger.warning("Failed to generate feedback survey for deed %s: %s", plan.get("deed_id", ""), exc)

    deed_id = str(plan.get("deed_id") or "")
    herald_payload = {
        "deed_id": deed_id,
        "deed_title": str(plan.get("slip_title") or plan.get("deed_title") or plan.get("title") or deed_id),
        "slip_id": str(plan.get("slip_id") or metadata.get("slip_id") or ""),
        "folio_id": str(plan.get("folio_id") or metadata.get("folio_id") or ""),
        "writ_id": str(plan.get("writ_id") or metadata.get("writ_id") or ""),
        "plan": plan,
        "move_results": move_results,
        "quality": quality_check,
        "offering": {
            "ok": True,
            "offering_path": str(offering_path),
        },
    }
    if feedback_survey:
        herald_payload["feedback_survey"] = feedback_survey
    self._ether.emit("herald_completed", herald_payload)
    self._ether.emit("deed_completed", herald_payload)
    from temporalio import activity
    activity.logger.info("Herald completed for deed %s; ether events emitted", deed_id)

    return {
        "ok": True,
        "offering_path": str(offering_path),
        "deed_id": deed_id,
        "quality": quality_check,
        "delivered_utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
        "feedback_survey": feedback_survey or {},
    }


async def run_update_deed_status(self, deed_root: str, plan: dict, deed_status: str) -> dict:
    deed_status = str(deed_status or "")
    self._update_deed_status(deed_root, plan, deed_status)
    if deed_status in {"failed", "cancelled"}:
        deed_id = str(plan.get("deed_id") or "")
        payload = {
            "deed_id": deed_id,
            "deed_title": str(plan.get("deed_title") or plan.get("title") or deed_id),
            "plan": plan,
            "move_results": [],
            "offering": {
                "ok": False,
                "deed_status": deed_status,
                "error": plan.get("last_error", ""),
            },
            "error": str(plan.get("last_error") or ""),
        }
        if deed_status == "failed":
            self._ether.emit("deed_failed", payload)
            if "rework_exhausted" in str(plan.get("last_error") or ""):
                self._ether.emit("deed_rework_exhausted", payload)
        self._ether.emit("deed_completed", payload)
    return {"ok": True, "deed_status": deed_status}
