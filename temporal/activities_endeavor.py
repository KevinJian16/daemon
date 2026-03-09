"""Temporal activities: endeavor-layer routines."""
from __future__ import annotations

import json
from typing import Any


def _normalize_passage_summary_row(row: dict) -> dict:
    out = dict(row or {})
    passage_status = str(out.get("passage_status") or "").strip()
    if passage_status:
        out["passage_status"] = passage_status
    return out


def _normalize_endeavor_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    out = dict(manifest or {})
    endeavor_status = str(out.get("endeavor_status") or "").strip()
    endeavor_phase = str(out.get("endeavor_phase") or "").strip()
    if endeavor_status:
        out["endeavor_status"] = endeavor_status
    if endeavor_phase:
        out["endeavor_phase"] = endeavor_phase
    rows = out.get("passages")
    if isinstance(rows, list):
        out["passages"] = [_normalize_passage_summary_row(row) for row in rows if isinstance(row, dict)]
    endeavor_context = out.get("endeavor_context")
    if isinstance(endeavor_context, list):
        out["endeavor_context"] = [row for row in endeavor_context if isinstance(row, dict)]
    else:
        out["endeavor_context"] = []
    return out


async def run_endeavor_bootstrap(self, deed_root: str, plan: dict) -> dict:
    deed_id = str(plan.get("deed_id") or deed_root.split("/")[-1] or "")
    endeavor_id = str(plan.get("endeavor_id") or f"edv_{deed_id}")
    endeavor_dir = self._home / "state" / "endeavors" / endeavor_id
    endeavor_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = endeavor_dir / "manifest.json"

    moves = self._normalized_moves(plan)
    passages = self._derive_endeavor_passages(plan, moves)
    resume_from = int(plan.get("endeavor_resume_from") or 0)
    resume_from = max(0, min(resume_from, len(passages)))

    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            old = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(old, dict):
                manifest = old
        except Exception:
            manifest = {}
    manifest = _normalize_endeavor_manifest(manifest)

    passage_summaries = []
    for i, m in enumerate(passages):
        row = {
            "passage_id": str(m.get("passage_id") or f"m{i + 1:02d}"),
            "title": str(m.get("title") or f"Passage {i + 1}"),
            "expected_output": str(m.get("expected_output") or ""),
            "input_dependencies": m.get("input_dependencies") if isinstance(m.get("input_dependencies"), list) else [],
            "move_ids": [str(s.get("id") or "") for s in (m.get("moves") or []) if isinstance(s, dict)],
            "passage_status": "pending",
        }
        old_rows = manifest.get("passages") if isinstance(manifest.get("passages"), list) else []
        if i < len(old_rows) and isinstance(old_rows[i], dict):
            row["passage_status"] = str(old_rows[i].get("passage_status") or row["passage_status"])
            if old_rows[i].get("objective_score") is not None:
                row["objective_score"] = old_rows[i].get("objective_score")
            if old_rows[i].get("attempts") is not None:
                row["attempts"] = old_rows[i].get("attempts")
        passage_summaries.append(row)

    endeavor_status = str(manifest.get("endeavor_status") or "running")
    endeavor_phase = str(manifest.get("endeavor_phase") or "phase0_planning")

    endeavor_context = (
        manifest.get("endeavor_context")
        if isinstance(manifest.get("endeavor_context"), list)
        else plan.get("endeavor_context")
        if isinstance(plan.get("endeavor_context"), list)
        else []
    )

    manifest.update(
        {
            "endeavor_id": endeavor_id,
            "deed_id": deed_id,
            "title": str(plan.get("title") or deed_id),
            "endeavor_status": endeavor_status,
            "endeavor_phase": endeavor_phase,
            "current_passage_index": resume_from,
            "workflow_id": str(plan.get("_workflow_id") or manifest.get("workflow_id") or ""),
            "deed_root": deed_root,
            "plan": plan,
            "passages": passage_summaries,
            "endeavor_context": endeavor_context[-32:],
            "total_passages": len(passage_summaries),
            "updated_utc": self._utc(),
            "created_utc": str(manifest.get("created_utc") or self._utc()),
        }
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    historical_move_results: list[dict] = []
    for i in range(0, resume_from):
        result_path = endeavor_dir / "passages" / str(i + 1) / "result.json"
        if not result_path.exists():
            continue
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows = payload.get("move_results") if isinstance(payload.get("move_results"), list) else []
        for row in rows:
            if isinstance(row, dict):
                historical_move_results.append(row)

    return {
        "endeavor_id": endeavor_id,
        "passages": passages,
        "next_passage_index": resume_from,
        "manifest_path": str(manifest_path),
        "historical_move_results": historical_move_results,
        "endeavor_context": endeavor_context[-32:],
    }


async def run_endeavor_record_passage(self, endeavor_id: str, passage_index: int, result: dict) -> dict:
    endeavor_dir = self._home / "state" / "endeavors" / endeavor_id
    endeavor_dir.mkdir(parents=True, exist_ok=True)
    passages_dir = endeavor_dir / "passages" / str(max(1, int(passage_index) + 1))
    passages_dir.mkdir(parents=True, exist_ok=True)

    payload = dict(result or {})
    payload["passage_index"] = int(passage_index)
    payload["recorded_utc"] = self._utc()
    result_path = passages_dir / "result.json"
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = endeavor_dir / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                manifest = data
        except Exception:
            manifest = {}
    manifest = _normalize_endeavor_manifest(manifest)
    rows = manifest.get("passages") if isinstance(manifest.get("passages"), list) else []
    rows = [_normalize_passage_summary_row(row) for row in rows if isinstance(row, dict)]
    idx = int(passage_index)
    passage_status = str(payload.get("passage_status") or "")
    if 0 <= idx < len(rows) and isinstance(rows[idx], dict):
        rows[idx]["passage_status"] = passage_status or str(rows[idx].get("passage_status") or "")
        rows[idx]["objective_score"] = payload.get("objective_score")
        rows[idx]["attempts"] = int(payload.get("attempts") or 0)
        if payload.get("child_workflow_id"):
            rows[idx]["child_workflow_id"] = str(payload.get("child_workflow_id") or "")
    manifest["passages"] = rows
    manifest["current_passage_index"] = idx + 1 if passage_status == "passed" else idx
    if passage_status == "passed" and isinstance(payload.get("context_entry"), dict):
        context = manifest.get("endeavor_context") if isinstance(manifest.get("endeavor_context"), list) else []
        context.append(payload.get("context_entry"))
        manifest["endeavor_context"] = context[-32:]
    manifest["updated_utc"] = self._utc()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    self._ether.emit(
        "endeavor_passage_recorded",
        {
            "endeavor_id": endeavor_id,
            "passage_index": int(passage_index),
            "passage_status": passage_status,
            "objective_score": payload.get("objective_score"),
            "attempts": int(payload.get("attempts") or 0),
            "title": str(payload.get("title") or ""),
        },
    )
    return {"ok": True, "endeavor_id": endeavor_id, "result_path": str(result_path)}


async def run_endeavor_set_status(
    self,
    endeavor_id: str,
    endeavor_status: str,
    endeavor_phase: str,
    extra: dict | None = None,
) -> dict:
    endeavor_dir = self._home / "state" / "endeavors" / endeavor_id
    endeavor_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = endeavor_dir / "manifest.json"
    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                manifest = data
        except Exception:
            manifest = {}
    manifest = _normalize_endeavor_manifest(manifest)
    endeavor_status = str(endeavor_status or manifest.get("endeavor_status") or "")
    endeavor_phase = str(endeavor_phase or manifest.get("endeavor_phase") or "")
    manifest["endeavor_id"] = endeavor_id
    manifest["endeavor_status"] = endeavor_status
    manifest["endeavor_phase"] = endeavor_phase
    manifest["updated_utc"] = self._utc()
    if isinstance(extra, dict) and extra:
        meta = manifest.get("meta") if isinstance(manifest.get("meta"), dict) else {}
        meta.update(extra)
        manifest["meta"] = meta
        if "current_passage_index" in extra:
            try:
                manifest["current_passage_index"] = int(extra.get("current_passage_index"))
            except Exception:
                pass
        if "workflow_id" in extra:
            manifest["workflow_id"] = str(extra.get("workflow_id") or "")
        if "current_child_workflow_id" in extra:
            manifest["current_child_workflow_id"] = str(extra.get("current_child_workflow_id") or "")
        if isinstance(extra.get("endeavor_context"), list):
            manifest["endeavor_context"] = [x for x in extra.get("endeavor_context") if isinstance(x, dict)][-32:]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    self._ether.emit(
        "endeavor_status_changed",
        {
            "endeavor_id": endeavor_id,
            "endeavor_status": str(manifest.get("endeavor_status") or ""),
            "endeavor_phase": str(manifest.get("endeavor_phase") or ""),
            "current_passage_index": int(manifest.get("current_passage_index") or 0),
        },
    )
    return {
        "ok": True,
        "endeavor_id": endeavor_id,
        "endeavor_status": manifest.get("endeavor_status", ""),
        "endeavor_phase": manifest.get("endeavor_phase", ""),
    }
