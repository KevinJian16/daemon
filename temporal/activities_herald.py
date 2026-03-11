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

    # Quality judgment is Arbiter's responsibility (SPEC §9.4, QA §6.3).
    # Herald only handles logistics: archive offering, update index, emit events.
    quality_check = {"ok": True, "source": "arbiter_upstream"}

    offering_root = self._resolve_offering_root()
    offering_path = self._archive_offering(deed_root, plan, scribe_path, move_results, offering_root=offering_root)
    self._update_offering_index(offering_path, plan, offering_root=offering_root)

    self._update_deed_status(
        deed_root,
        {**plan, "deed_sub_status": "reviewing"},
        "settling",
        offering_path=str(offering_path),
        result_summary=str(quality_check.get("summary") or ""),
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
    self._ether.emit("deed_settling", herald_payload)
    from temporalio import activity

    # ── Lore recording ────────────────────────────────────────────────────
    if self._lore:
        try:
            brief = plan.get("brief") if isinstance(plan.get("brief"), dict) else {}
            objective = str(brief.get("objective") or plan.get("deed_title") or plan.get("title") or "")
            dag_budget = int(brief.get("dag_budget") or plan.get("dag_budget") or 6)
            agents_used = [str(m.get("agent") or m.get("role") or "") for m in move_results if isinstance(m, dict)]
            total_tokens = {}
            for mr in move_results:
                if not isinstance(mr, dict):
                    continue
                t = mr.get("token_consumption") if isinstance(mr.get("token_consumption"), dict) else {}
                for k, v in t.items():
                    total_tokens[k] = total_tokens.get(k, 0) + (int(v) if isinstance(v, (int, float)) else 0)
            duration_s = 0.0
            for mr in move_results:
                if isinstance(mr, dict):
                    duration_s += float(mr.get("duration_s") or 0)
            self._lore.record(
                deed_id=deed_id,
                objective_text=objective[:500],
                dag_budget=dag_budget,
                move_count=len(move_results),
                plan_structure={"agents": agents_used, "dag_budget": dag_budget},
                offering_quality=quality_check,
                token_consumption=total_tokens,
                success=True,
                duration_s=duration_s,
                folio_id=str(plan.get("folio_id") or metadata.get("folio_id") or ""),
                slip_id=str(plan.get("slip_id") or metadata.get("slip_id") or ""),
                writ_id=str(plan.get("writ_id") or metadata.get("writ_id") or ""),
            )
            activity.logger.info("Lore recorded for deed %s", deed_id)
        except Exception as exc:
            activity.logger.warning("Lore recording failed for deed %s: %s", deed_id, exc)

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
    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    deed_status = str(deed_status or "")
    self._update_deed_status(deed_root, plan, deed_status)
    deed_sub_status = str(plan.get("deed_sub_status") or "").strip()
    if deed_status == "closed" and deed_sub_status in {"failed", "cancelled"}:
        deed_id = str(plan.get("deed_id") or "")
        payload = {
            "deed_id": deed_id,
            "deed_title": str(plan.get("deed_title") or plan.get("title") or deed_id),
            "plan": plan,
            "move_results": [],
            "offering": {
                "ok": False,
                "deed_status": deed_status,
                "deed_sub_status": deed_sub_status,
                "error": plan.get("last_error", ""),
            },
            "error": str(plan.get("last_error") or ""),
        }
        if deed_sub_status == "failed":
            self._ether.emit("deed_failed", payload)
            if "rework_exhausted" in str(plan.get("last_error") or ""):
                self._ether.emit("deed_rework_exhausted", payload)
        self._ether.emit("deed_closed", payload)

        # Record failure in Lore so future planning can learn from it.
        if self._lore:
            try:
                brief = plan.get("brief") if isinstance(plan.get("brief"), dict) else {}
                objective = str(brief.get("objective") or plan.get("deed_title") or plan.get("title") or "")
                dag_budget = int(brief.get("dag_budget") or plan.get("dag_budget") or 6)
                self._lore.record(
                    deed_id=deed_id,
                    objective_text=objective[:500],
                    dag_budget=dag_budget,
                    move_count=0,
                    plan_structure={},
                    offering_quality={},
                    token_consumption={},
                    success=False,
                    duration_s=0.0,
                    folio_id=str(plan.get("folio_id") or metadata.get("folio_id") or ""),
                    slip_id=str(plan.get("slip_id") or metadata.get("slip_id") or ""),
                    writ_id=str(plan.get("writ_id") or metadata.get("writ_id") or ""),
                )
            except Exception as exc:
                from temporalio import activity as _act
                _act.logger.warning("Lore recording (failure) for deed %s: %s", deed_id, exc)

    return {"ok": True, "deed_status": deed_status}
