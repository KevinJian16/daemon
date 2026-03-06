"""Temporal activities: campaign-layer routines."""
from __future__ import annotations

import json
from typing import Any


def _normalize_milestone_summary_row(row: dict) -> dict:
    out = dict(row or {})
    milestone_status = str(out.get("milestone_status") or "").strip()
    if milestone_status:
        out["milestone_status"] = milestone_status
    return out


def _normalize_campaign_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    out = dict(manifest or {})
    campaign_status = str(out.get("campaign_status") or "").strip()
    campaign_phase = str(out.get("campaign_phase") or "").strip()
    if campaign_status:
        out["campaign_status"] = campaign_status
    if campaign_phase:
        out["campaign_phase"] = campaign_phase
    rows = out.get("milestones")
    if isinstance(rows, list):
        out["milestones"] = [_normalize_milestone_summary_row(row) for row in rows if isinstance(row, dict)]
    return out


async def run_campaign_bootstrap(self, run_root: str, plan: dict) -> dict:
    run_id = str(plan.get("run_id") or run_root.split("/")[-1] or "")
    campaign_id = str(plan.get("campaign_id") or f"cmp_{run_id}")
    campaign_dir = self._home / "state" / "campaigns" / campaign_id
    campaign_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = campaign_dir / "manifest.json"

    steps = self._normalized_steps(plan)
    milestones = self._derive_campaign_milestones(plan, steps)
    resume_from = int(plan.get("campaign_resume_from") or 0)
    resume_from = max(0, min(resume_from, len(milestones)))

    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(old, dict):
                manifest = old
        except Exception:
            manifest = {}
    manifest = _normalize_campaign_manifest(manifest)

    milestone_summaries = []
    for i, m in enumerate(milestones):
        row = {
            "milestone_id": str(m.get("milestone_id") or f"m{i + 1:02d}"),
            "title": str(m.get("title") or f"Milestone {i + 1}"),
            "expected_output": str(m.get("expected_output") or ""),
            "input_dependencies": m.get("input_dependencies") if isinstance(m.get("input_dependencies"), list) else [],
            "step_ids": [str(s.get("id") or "") for s in (m.get("steps") or []) if isinstance(s, dict)],
            "milestone_status": "pending",
        }
        old_rows = manifest.get("milestones") if isinstance(manifest.get("milestones"), list) else []
        if i < len(old_rows) and isinstance(old_rows[i], dict):
            row["milestone_status"] = str(old_rows[i].get("milestone_status") or row["milestone_status"])
            if old_rows[i].get("objective_score") is not None:
                row["objective_score"] = old_rows[i].get("objective_score")
            if old_rows[i].get("attempts") is not None:
                row["attempts"] = old_rows[i].get("attempts")
        milestone_summaries.append(row)

    campaign_status = str(manifest.get("campaign_status") or "running")
    campaign_phase = str(manifest.get("campaign_phase") or "phase0_planning")

    manifest.update(
        {
            "campaign_id": campaign_id,
            "run_id": run_id,
            "title": str(plan.get("title") or run_id),
            "campaign_status": campaign_status,
            "campaign_phase": campaign_phase,
            "current_milestone_index": resume_from,
            "workflow_id": str(plan.get("_workflow_id") or manifest.get("workflow_id") or ""),
            "run_root": run_root,
            "plan": plan,
            "milestones": milestone_summaries,
            "total_milestones": len(milestone_summaries),
            "updated_utc": self._utc(),
            "created_utc": str(manifest.get("created_utc") or self._utc()),
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    historical_step_results: list[dict] = []
    for i in range(0, resume_from):
        result_path = campaign_dir / "milestones" / str(i + 1) / "result.json"
        if not result_path.exists():
            continue
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = payload.get("step_results") if isinstance(payload.get("step_results"), list) else []
        for row in rows:
            if isinstance(row, dict):
                historical_step_results.append(row)

    return {
        "campaign_id": campaign_id,
        "milestones": milestones,
        "next_milestone_index": resume_from,
        "manifest_path": str(manifest_path),
        "historical_step_results": historical_step_results,
    }


async def run_campaign_record_milestone(self, campaign_id: str, milestone_index: int, result: dict) -> dict:
    campaign_dir = self._home / "state" / "campaigns" / campaign_id
    campaign_dir.mkdir(parents=True, exist_ok=True)
    milestones_dir = campaign_dir / "milestones" / str(max(1, int(milestone_index) + 1))
    milestones_dir.mkdir(parents=True, exist_ok=True)

    payload = dict(result or {})
    payload["milestone_index"] = int(milestone_index)
    payload["recorded_utc"] = self._utc()
    result_path = milestones_dir / "result.json"
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = campaign_dir / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                manifest = data
        except Exception:
            manifest = {}
    manifest = _normalize_campaign_manifest(manifest)
    rows = manifest.get("milestones") if isinstance(manifest.get("milestones"), list) else []
    rows = [_normalize_milestone_summary_row(row) for row in rows if isinstance(row, dict)]
    idx = int(milestone_index)
    milestone_status = str(payload.get("milestone_status") or "")
    if 0 <= idx < len(rows) and isinstance(rows[idx], dict):
        rows[idx]["milestone_status"] = milestone_status or str(rows[idx].get("milestone_status") or "")
        rows[idx]["objective_score"] = payload.get("objective_score")
        rows[idx]["attempts"] = int(payload.get("attempts") or 0)
    manifest["milestones"] = rows
    manifest["current_milestone_index"] = idx + 1 if milestone_status == "passed" else idx
    manifest["updated_utc"] = self._utc()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    self._event_bridge.emit(
        "campaign_milestone_recorded",
        {
            "campaign_id": campaign_id,
            "milestone_index": int(milestone_index),
            "milestone_status": milestone_status,
            "objective_score": payload.get("objective_score"),
            "attempts": int(payload.get("attempts") or 0),
            "title": str(payload.get("title") or ""),
        },
    )
    return {"ok": True, "campaign_id": campaign_id, "result_path": str(result_path)}


async def run_campaign_set_status(
    self,
    campaign_id: str,
    campaign_status: str,
    campaign_phase: str,
    extra: dict | None = None,
) -> dict:
    campaign_dir = self._home / "state" / "campaigns" / campaign_id
    campaign_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = campaign_dir / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                manifest = data
        except Exception:
            manifest = {}
    manifest = _normalize_campaign_manifest(manifest)
    campaign_status = str(campaign_status or manifest.get("campaign_status") or "")
    campaign_phase = str(campaign_phase or manifest.get("campaign_phase") or "")
    manifest["campaign_id"] = campaign_id
    manifest["campaign_status"] = campaign_status
    manifest["campaign_phase"] = campaign_phase
    manifest["updated_utc"] = self._utc()
    if isinstance(extra, dict) and extra:
        meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
        meta.update(extra)
        manifest["meta"] = meta
        if "current_milestone_index" in extra:
            try:
                manifest["current_milestone_index"] = int(extra.get("current_milestone_index"))
            except Exception:
                pass
        if "workflow_id" in extra:
            manifest["workflow_id"] = str(extra.get("workflow_id") or "")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    self._event_bridge.emit(
        "campaign_status_changed",
        {
            "campaign_id": campaign_id,
            "campaign_status": str(manifest.get("campaign_status") or ""),
            "campaign_phase": str(manifest.get("campaign_phase") or ""),
            "current_milestone_index": int(manifest.get("current_milestone_index") or 0),
        },
    )
    return {
        "ok": True,
        "campaign_id": campaign_id,
        "campaign_status": manifest.get("campaign_status", ""),
        "campaign_phase": manifest.get("campaign_phase", ""),
    }
