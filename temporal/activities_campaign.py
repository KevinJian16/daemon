"""Temporal activities: campaign-layer routines."""
from __future__ import annotations

import json
from typing import Any


async def run_campaign_bootstrap(self, run_root: str, plan: dict) -> dict:
    task_id = str(plan.get("task_id") or run_root.split("/")[-1] or "")
    campaign_id = str(plan.get("campaign_id") or f"cmp_{task_id}")
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

    milestone_summaries = []
    for i, m in enumerate(milestones):
        row = {
            "milestone_id": str(m.get("milestone_id") or f"m{i + 1:02d}"),
            "title": str(m.get("title") or f"Milestone {i + 1}"),
            "expected_output": str(m.get("expected_output") or ""),
            "input_dependencies": m.get("input_dependencies") if isinstance(m.get("input_dependencies"), list) else [],
            "step_ids": [str(s.get("id") or "") for s in (m.get("steps") or []) if isinstance(s, dict)],
            "status": "pending",
        }
        old_rows = manifest.get("milestones") if isinstance(manifest.get("milestones"), list) else []
        if i < len(old_rows) and isinstance(old_rows[i], dict):
            row["status"] = str(old_rows[i].get("status") or row["status"])
            if old_rows[i].get("objective_score") is not None:
                row["objective_score"] = old_rows[i].get("objective_score")
            if old_rows[i].get("attempts") is not None:
                row["attempts"] = old_rows[i].get("attempts")
        milestone_summaries.append(row)

    manifest.update(
        {
            "campaign_id": campaign_id,
            "task_id": task_id,
            "title": str(plan.get("title") or task_id),
            "status": str(manifest.get("status") or "running"),
            "current_phase": str(manifest.get("current_phase") or "phase0_planning"),
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
    rows = manifest.get("milestones") if isinstance(manifest.get("milestones"), list) else []
    idx = int(milestone_index)
    if 0 <= idx < len(rows) and isinstance(rows[idx], dict):
        rows[idx]["status"] = str(payload.get("status") or rows[idx].get("status") or "")
        rows[idx]["objective_score"] = payload.get("objective_score")
        rows[idx]["attempts"] = int(payload.get("attempts") or 0)
    manifest["milestones"] = rows
    manifest["current_milestone_index"] = idx + 1 if str(payload.get("status") or "") == "passed" else idx
    manifest["updated_utc"] = self._utc()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    self._event_bridge.emit(
        "campaign_milestone_recorded",
        {
            "campaign_id": campaign_id,
            "milestone_index": int(milestone_index),
            "status": str(payload.get("status") or ""),
            "objective_score": payload.get("objective_score"),
            "attempts": int(payload.get("attempts") or 0),
            "title": str(payload.get("title") or ""),
        },
    )
    return {"ok": True, "campaign_id": campaign_id, "result_path": str(result_path)}


async def run_campaign_set_status(self, campaign_id: str, status: str, phase: str, extra: dict | None = None) -> dict:
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
    manifest["campaign_id"] = campaign_id
    manifest["status"] = str(status or manifest.get("status") or "")
    manifest["current_phase"] = str(phase or manifest.get("current_phase") or "")
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
            "status": str(manifest.get("status") or ""),
            "phase": str(manifest.get("current_phase") or ""),
            "current_milestone_index": int(manifest.get("current_milestone_index") or 0),
        },
    )
    return {"ok": True, "campaign_id": campaign_id, "status": manifest.get("status"), "phase": manifest.get("current_phase")}
