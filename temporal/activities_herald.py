"""Temporal activities: herald-layer routines (pure logistics)."""
from __future__ import annotations


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
    self._ether.emit("herald_completed", herald_payload)
    self._ether.emit("deed_settling", herald_payload)
    from temporalio import activity

    activity.logger.info("Herald completed for deed %s; ether events emitted", deed_id)

    return {
        "ok": True,
        "offering_path": str(offering_path),
        "deed_id": deed_id,
        "quality": quality_check,
        "delivered_utc": __import__("time").strftime("%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime()),
    }


async def run_update_deed_status(self, deed_root: str, plan: dict, deed_status: str) -> dict:
    metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
    deed_status = str(deed_status or "")
    self._update_deed_status(deed_root, plan, deed_status)
    deed_sub_status = str(plan.get("deed_sub_status") or "").strip()
    deed_id = str(plan.get("deed_id") or "")

    if deed_status == "closed" and deed_sub_status in {"failed", "cancelled"}:
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

    elif deed_status == "closed" and deed_sub_status not in {"failed", "cancelled"}:
        # Accepted close → merge into dag_templates (§11.3, §6.6.1)
        self._ether.emit("deed_closed", {
            "deed_id": deed_id,
            "deed_title": str(plan.get("deed_title") or plan.get("title") or deed_id),
            "plan": plan,
            "offering": {"ok": True},
        })
        if self._ledger_stats:
            try:
                brief = plan.get("brief") if isinstance(plan.get("brief"), dict) else {}
                objective = str(brief.get("objective") or plan.get("deed_title") or plan.get("title") or "")
                dag_structure = plan.get("design") or plan.get("moves") or {}
                emb = None
                if self._cortex and self._cortex.is_available():
                    try:
                        emb = self._cortex.embed(objective[:500])
                    except Exception:
                        pass
                self._ledger_stats.merge_dag_template(
                    objective_text=objective[:500],
                    objective_emb=emb,
                    dag_structure=dag_structure,
                    eval_summary="",
                    total_tokens=0,
                    total_duration_s=0.0,
                    rework_count=0,
                )
                from temporalio import activity as _act
                _act.logger.info("Merged dag_template for accepted deed %s", deed_id)
            except Exception as exc:
                from temporalio import activity as _act
                _act.logger.warning("Failed to merge dag_template for deed %s: %s", deed_id, exc)

    return {"ok": True, "deed_status": deed_status}
