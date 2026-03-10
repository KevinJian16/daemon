"""Health, deed, and offering routes for the Draft/Slip/Folio backend."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from services.ledger import Ledger

logger = logging.getLogger(__name__)


def register_basic_routes(
    app: FastAPI,
    *,
    app_started_utc: str,
    ensure_temporal_client: Callable[..., Awaitable[bool]],
    get_temporal_client: Callable[[], Any],
    ledger: Ledger,
    will: Any,
    cortex: Any,
    model_policy_path: Path,
    model_registry_path: Path,
    openclaw_home: Path,
    validate_model_registry: Callable[[dict], None],
    deed_view: Callable[[dict], dict],
    log_portal_event: Callable[[str, dict[str, Any], Request | None], None],
    require_offering_root: Callable[[], Path],
    memory: Any,
    lore: Any,
    instinct: Any,
    folio_writ: Any,
    append_deed_message: Callable[..., dict[str, Any]],
    load_deed_messages: Callable[[str, int], list[dict]],
    schedule_broadcast: Callable[[str, dict[str, Any]], None],
) -> None:
    del memory, lore, instinct, folio_writ  # reserved for later expansion

    def _utc() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _deed_status(row: dict) -> str:
        return str(row.get("deed_status") or "").strip()

    def _workflow_ids_for_row(deed_id: str, row: dict) -> list[str]:
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else {}
        workflow_ids: list[str] = []
        for candidate in [
            plan.get("_workflow_id"),
            row.get("workflow_id"),
            f"daemon-{deed_id}",
        ]:
            wid = str(candidate or "").strip()
            if wid and wid not in workflow_ids:
                workflow_ids.append(wid)
        return workflow_ids

    def _sort_deeds(rows: list[dict]) -> list[dict]:
        def _ts(row: dict) -> float:
            for key in ("updated_utc", "started_utc", "created_utc"):
                raw = str(row.get(key) or "").strip()
                if not raw:
                    continue
                try:
                    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except Exception:
                    continue
            return 0.0

        return sorted(rows, key=_ts, reverse=True)

    def _phase_of(row: dict) -> str:
        explicit = str(row.get("phase") or "").strip().lower()
        if explicit in {"running", "awaiting_eval", "history"}:
            return explicit
        deed_st = _deed_status(row).lower()
        if deed_st in {"running", "queued", "paused", "cancel_requested", "cancelling"}:
            return "running"
        if deed_st == "awaiting_eval":
            return "awaiting_eval"
        return "history"

    def _filter_rows(rows: list[dict], deed_status: str | None, phase: str | None) -> list[dict]:
        out = rows
        if deed_status:
            target = str(deed_status).strip().lower()
            out = [row for row in out if _deed_status(row).lower() == target]
        if phase:
            target_phase = str(phase).strip().lower()
            if target_phase in {"running", "awaiting_eval", "history"}:
                out = [row for row in out if _phase_of(row) == target_phase]
        return out

    def _expire_eval_windows(rows: list[dict]) -> bool:
        now = datetime.now(timezone.utc)
        changed = False
        for row in rows:
            status = _deed_status(row).lower()
            if status != "awaiting_eval":
                continue
            raw = str(row.get("eval_deadline_utc") or "").strip()
            if not raw:
                continue
            try:
                deadline = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                deadline = deadline.astimezone(timezone.utc)
            except Exception:
                continue
            if deadline > now:
                continue
            row["deed_status"] = "completed"
            row["phase"] = "history"
            row["updated_utc"] = _utc()
            row["eval_expired_utc"] = row["updated_utc"]
            row["feedback_expired"] = True
            row.pop("eval_deadline_utc", None)
            changed = True
        return changed

    def _load_deeds() -> list[dict]:
        def _mutate(deeds: list[dict]) -> None:
            _expire_eval_windows(deeds)

        return ledger.mutate_deeds(_mutate)

    async def _signal_workflow(
        deed_id: str,
        row: dict,
        *,
        signal_name: str,
        payload: dict | None = None,
    ) -> str:
        await ensure_temporal_client(retries=2, delay_s=0.3)
        temporal_client = get_temporal_client()
        if not temporal_client:
            raise HTTPException(status_code=503, detail="temporal_unavailable")
        workflow_ids = _workflow_ids_for_row(deed_id, row)
        if not workflow_ids:
            raise HTTPException(status_code=409, detail="workflow_id_missing")

        last_error = ""
        for workflow_id in workflow_ids:
            try:
                await temporal_client.signal(workflow_id, signal_name, payload or {})
                return workflow_id
            except Exception as exc:
                last_error = str(exc)[:240]
        raise HTTPException(status_code=409, detail={"ok": False, "error": f"deed_signal_failed:{last_error}"})

    @app.get("/health")
    async def health():
        temporal_connected = bool(await ensure_temporal_client(retries=1, delay_s=0.1))
        ward = ledger.load_ward()
        model_registry_valid = False
        if model_registry_path.exists():
            try:
                reg = json.loads(model_registry_path.read_text(encoding="utf-8"))
                if isinstance(reg, dict):
                    validate_model_registry(reg)
                    model_registry_valid = True
            except Exception:
                model_registry_valid = False
        dependencies = {
            "temporal_connected": temporal_connected,
            "cortex_available": bool(cortex and cortex.is_available()),
            "model_policy_exists": model_policy_path.exists(),
            "model_registry_exists": model_registry_path.exists(),
            "model_registry_valid": model_registry_valid,
            "openclaw_config_exists": (openclaw_home / "openclaw.json").exists(),
        }
        dependencies_ready = (
            dependencies["cortex_available"]
            and dependencies["model_policy_exists"]
            and dependencies["model_registry_exists"]
            and dependencies["model_registry_valid"]
        )
        return {
            "ok": True,
            "ward": ward["status"],
            "app_started_utc": app_started_utc,
            "dependencies": dependencies,
            "dependencies_ready": dependencies_ready,
        }

    @app.get("/deeds")
    def list_deeds(
        request: Request,
        deed_status: str | None = None,
        status: str | None = None,
        phase: str | None = None,
        limit: int = 50,
    ):
        rows = _filter_rows(_load_deeds(), deed_status if deed_status is not None else status, phase)
        result = [deed_view(row) for row in _sort_deeds(rows)[: max(1, min(limit, 500))]]
        log_portal_event("deeds_list", {"deed_status": deed_status or status, "phase": phase, "count": len(result)}, request)
        return result

    @app.get("/deeds/{deed_id}")
    def get_deed(deed_id: str, request: Request):
        for row in _load_deeds():
            if str(row.get("deed_id") or "") == deed_id:
                log_portal_event("deed_get", {"deed_id": deed_id, "deed_status": _deed_status(row)}, request)
                return deed_view(row)
        log_portal_event("deed_not_found", {"deed_id": deed_id}, request)
        raise HTTPException(status_code=404, detail="deed not found")

    @app.post("/deeds/{deed_id}/retry")
    async def retry_deed(deed_id: str, request: Request):
        row = ledger.get_deed(deed_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="deed not found")
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else {}
        if not plan:
            raise HTTPException(status_code=409, detail="deed_plan_missing")
        if _deed_status(row).lower() not in {"failed", "failed_submission", "expired", "replay_exhausted"}:
            raise HTTPException(status_code=409, detail="retry_not_allowed_for_current_deed_status")
        result = await will.submit(plan)
        log_portal_event("deed_retry", {"deed_id": deed_id, "result_ok": bool(result.get("ok"))}, request)
        return result

    @app.post("/deeds/{deed_id}/cancel")
    async def cancel_deed(deed_id: str, request: Request):
        row = ledger.get_deed(deed_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="deed not found")
        cur_status = _deed_status(row).lower()
        if cur_status in {"completed", "awaiting_eval", "cancelled", "failed"}:
            raise HTTPException(status_code=409, detail=f"cancel_not_allowed_for_deed_status:{cur_status}")

        await ensure_temporal_client(retries=2, delay_s=0.3)
        temporal_client = get_temporal_client()
        cancel_error = ""
        cancel_requested = False
        if temporal_client:
            for workflow_id in _workflow_ids_for_row(deed_id, row):
                try:
                    await temporal_client.cancel(workflow_id)
                    cancel_requested = True
                    break
                except Exception as exc:
                    cancel_error = str(exc)[:240]

        now = _utc()
        new_status = "cancelling" if cancel_requested else "cancelled"
        new_phase = "running" if cancel_requested else "history"

        def _mutate(deeds: list[dict]) -> None:
            for item in deeds:
                if str(item.get("deed_id") or "") != deed_id:
                    continue
                item["deed_status"] = new_status
                item["phase"] = new_phase
                item["updated_utc"] = now
                if cancel_error:
                    item["last_error"] = cancel_error
                break

        ledger.mutate_deeds(_mutate)
        log_portal_event("deed_cancel", {"deed_id": deed_id, "cancel_error": cancel_error}, request)
        return {"ok": True, "deed_id": deed_id, "deed_status": new_status, "cancel_error": cancel_error}

    async def _append_requirement(deed_id: str, requirement: str, source: str = "portal") -> dict:
        row = ledger.get_deed(deed_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="deed not found")
        workflow_id = await _signal_workflow(
            deed_id,
            row,
            signal_name="append_requirement",
            payload={"text": requirement, "source": source, "appended_at": _utc()},
        )
        return {"ok": True, "deed_id": deed_id, "workflow_id": workflow_id, "accepted": True}

    @app.post("/deeds/{deed_id}/append")
    async def append_deed_requirement(deed_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        requirement = str(body.get("requirement") or body.get("text") or "").strip()
        if not requirement:
            raise HTTPException(status_code=400, detail="requirement_required")
        result = await _append_requirement(deed_id, requirement, source=str(body.get("source") or "portal"))
        log_portal_event("deed_append", {"deed_id": deed_id, "workflow_id": result.get("workflow_id", ""), "requirement_len": len(requirement)}, request)
        return result

    @app.get("/deeds/{deed_id}/messages")
    def get_deed_messages(deed_id: str, request: Request, limit: int = 200):
        row = ledger.get_deed(deed_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="deed not found")
        messages = load_deed_messages(deed_id, limit)
        log_portal_event("deed_messages", {"deed_id": deed_id, "count": len(messages)}, request)
        return messages

    @app.post("/deeds/{deed_id}/message")
    async def post_deed_message(deed_id: str, request: Request):
        row = ledger.get_deed(deed_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="deed not found")
        body = await request.json()
        if not isinstance(body, dict):
            body = {}
        text = str(body.get("text") or body.get("message") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="message_required")
        append_deed_message(deed_id, role="user", content=text, event="user_message", meta={"source": str(body.get("source") or "portal")})

        deed_status = _deed_status(row).lower()
        workflow_id = ""
        paused = False
        if deed_status in {"running", "queued"}:
            workflow_id = await _signal_workflow(deed_id, row, signal_name="pause_execution", payload={"source": "portal_message"})
            paused = True
            await _append_requirement(deed_id, text, source=str(body.get("source") or "portal_message"))

        payload = {"deed_id": deed_id, "content": text, "paused": paused, "workflow_id": workflow_id}
        schedule_broadcast("deed_message", {"deed_id": deed_id, "role": "user", "content": text, "created_utc": _utc()})
        log_portal_event("deed_message", payload, request)
        return {"ok": True, **payload}

    @app.post("/deeds/{deed_id}/pause")
    async def pause_deed(deed_id: str, request: Request):
        row = ledger.get_deed(deed_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="deed not found")
        status = _deed_status(row).lower()
        if status in {"completed", "cancelled", "failed", "awaiting_eval"}:
            raise HTTPException(status_code=409, detail=f"pause_not_allowed_for_deed_status:{status}")
        workflow_id = await _signal_workflow(deed_id, row, signal_name="pause_execution", payload={"source": "api"})
        now = _utc()

        def _mutate(deeds: list[dict]) -> None:
            for item in deeds:
                if str(item.get("deed_id") or "") != deed_id:
                    continue
                item["deed_status"] = "paused"
                item["phase"] = "running"
                item["updated_utc"] = now
                break

        ledger.mutate_deeds(_mutate)
        log_portal_event("deed_pause", {"deed_id": deed_id, "workflow_id": workflow_id}, request)
        return {"ok": True, "deed_id": deed_id, "deed_status": "paused", "workflow_id": workflow_id}

    @app.post("/deeds/{deed_id}/resume")
    async def resume_deed(deed_id: str, request: Request):
        row = ledger.get_deed(deed_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="deed not found")
        workflow_id = await _signal_workflow(deed_id, row, signal_name="resume_execution", payload={"source": "api"})
        now = _utc()

        def _mutate(deeds: list[dict]) -> None:
            for item in deeds:
                if str(item.get("deed_id") or "") != deed_id:
                    continue
                item["deed_status"] = "running"
                item["phase"] = "running"
                item["updated_utc"] = now
                break

        ledger.mutate_deeds(_mutate)
        log_portal_event("deed_resume", {"deed_id": deed_id, "workflow_id": workflow_id}, request)
        return {"ok": True, "deed_id": deed_id, "deed_status": "running", "workflow_id": workflow_id}

    @app.get("/offerings")
    def list_offerings(request: Request, limit: int = 50):
        index = ledger.load_herald_log()
        log_portal_event("offering_list", {"limit": limit, "count": min(len(index), limit)}, request)
        return list(reversed(index))[:limit]

    def _offering_entry_for_deed(deed_id: str) -> dict | None:
        for entry in reversed(ledger.load_herald_log()):
            if str(entry.get("deed_id") or "") == deed_id:
                return entry
        return None

    def _offering_files_payload(offering_path: Path, offering_root: Path, *, deed_id: str = "") -> list[dict]:
        items: list[dict] = []
        for file_path in sorted(offering_path.rglob("*")):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(offering_path))
            ext = file_path.suffix.lower()
            preview_type = "text"
            if ext == ".pdf":
                preview_type = "pdf"
            elif ext in {".html", ".htm"}:
                preview_type = "html"
            elif ext in {".py", ".ts", ".tsx", ".js", ".jsx", ".diff"}:
                preview_type = "code"
            download_path = f"/offerings/{deed_id}/files/{rel}" if deed_id else f"/offerings/{str(file_path.relative_to(offering_root))}"
            items.append(
                {
                    "name": file_path.name,
                    "relative_path": rel,
                    "preview_type": preview_type,
                    "size_bytes": int(file_path.stat().st_size),
                    "download_path": download_path,
                }
            )
        return items

    @app.get("/offerings/{deed_id}/files")
    def deed_offering_files(deed_id: str, request: Request):
        offering_root = require_offering_root()
        entry = _offering_entry_for_deed(deed_id)
        if not entry:
            raise HTTPException(status_code=404, detail="offering not found")
        offering_path = offering_root / str(entry.get("path") or "")
        if not offering_path.exists():
            raise HTTPException(status_code=404, detail="offering_path_missing")
        files = _offering_files_payload(offering_path, offering_root, deed_id=deed_id)
        log_portal_event("offering_files", {"deed_id": deed_id, "count": len(files)}, request)
        return {"deed_id": deed_id, "offering_path": str(entry.get("path") or ""), "files": files}

    @app.get("/offerings/{deed_id}/files/{filename:path}")
    def deed_offering_file(deed_id: str, filename: str, request: Request):
        offering_root = require_offering_root()
        entry = _offering_entry_for_deed(deed_id)
        if not entry:
            raise HTTPException(status_code=404, detail="offering not found")
        base = offering_root / str(entry.get("path") or "")
        full = base / filename
        try:
            full.resolve().relative_to(base.resolve())
        except Exception:
            raise HTTPException(status_code=400, detail="path_outside_offering_root")
        if not full.exists():
            raise HTTPException(status_code=404, detail="offering_file_not_found")
        log_portal_event("offering_file_access", {"deed_id": deed_id, "filename": filename}, request)
        return FileResponse(full)

    @app.get("/offerings/timeline")
    def offering_timeline(request: Request, days: int = 30, limit_per_day: int = 50):
        index = ledger.load_herald_log()
        limit_days = max(1, min(days, 365))
        per_day = max(1, min(limit_per_day, 200))

        entries: list[dict[str, Any]] = []
        for item in index:
            ts = str(item.get("delivered_utc") or "")
            day_key = ts[:10] if len(ts) >= 10 else "unknown"
            entries.append(
                {
                    "path": item.get("path", ""),
                    "title": item.get("title", ""),
                    "deed_id": item.get("deed_id", ""),
                    "slip_id": item.get("slip_id", ""),
                    "folio_id": item.get("folio_id", ""),
                    "delivered_utc": ts,
                    "day": day_key,
                }
            )
        entries.sort(key=lambda x: x.get("delivered_utc", ""), reverse=True)

        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            day = str(entry.get("day") or "unknown")
            grouped.setdefault(day, [])
            if len(grouped[day]) < per_day:
                grouped[day].append(entry)

        days_sorted = sorted(grouped.keys(), reverse=True)[:limit_days]
        out = [{"day": day, "count": len(grouped.get(day, [])), "items": grouped.get(day, [])} for day in days_sorted]
        log_portal_event("offering_timeline", {"days": limit_days, "groups": len(out)}, request)
        return {"days": out}

    @app.get("/offerings/{path:path}")
    def get_offering_file(path: str, request: Request):
        offering_root = require_offering_root()
        full = offering_root / path
        try:
            full.resolve().relative_to(offering_root.resolve())
        except Exception:
            raise HTTPException(status_code=400, detail="path_outside_offering_root")
        if not full.exists():
            log_portal_event("offering_file_missing", {"path": path}, request)
            raise HTTPException(status_code=404, detail="offering_not_found")
        log_portal_event("offering_file_access", {"path": path}, request)
        return FileResponse(full)
