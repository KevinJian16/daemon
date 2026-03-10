"""Portal shell routes for Slip / Folio views."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse


ACTIVE_DEED_STATUSES = {"running", "queued", "paused", "cancelling", "awaiting_eval"}


def register_portal_shell_routes(app: FastAPI, *, ctx: Any) -> None:
    def _utc() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _parse_ts(text: str) -> float:
        raw = str(text or "").strip()
        if not raw:
            return 0.0
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return 0.0

    def _workflow_ids_for_row(deed_id: str, row: dict) -> list[str]:
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else {}
        workflow_ids: list[str] = []
        for candidate in [plan.get("_workflow_id"), row.get("workflow_id"), f"daemon-{deed_id}"]:
            workflow_id = str(candidate or "").strip()
            if workflow_id and workflow_id not in workflow_ids:
                workflow_ids.append(workflow_id)
        return workflow_ids

    def _all_deeds() -> list[dict]:
        return [row for row in ctx.ledger.load_deeds() if isinstance(row, dict)]

    def _folio_ref(folio_id: str) -> dict | None:
        folio = ctx.folio_writ.get_folio(folio_id)
        if not isinstance(folio, dict):
            return None
        return {
            "id": str(folio.get("folio_id") or ""),
            "slug": str(folio.get("slug") or ""),
            "canonical_slug": str(folio.get("slug") or ""),
            "title": str(folio.get("title") or "新卷"),
            "summary": str(folio.get("summary") or ""),
            "status": str(folio.get("status") or "active"),
        }

    def _slip_rows() -> list[dict]:
        return [row for row in ctx.folio_writ.list_slips() if isinstance(row, dict)]

    def _folio_rows() -> list[dict]:
        return [row for row in ctx.folio_writ.list_folios() if isinstance(row, dict)]

    def _deeds_for_slip(slip: dict) -> list[dict]:
        slip_id = str(slip.get("slip_id") or "")
        rows = [row for row in _all_deeds() if str(row.get("slip_id") or "") == slip_id]
        rows.sort(key=lambda row: _parse_ts(str(row.get("updated_utc") or row.get("created_utc") or "")), reverse=True)
        return rows

    def _latest_deed_for_slip(slip: dict) -> dict | None:
        rows = _deeds_for_slip(slip)
        return rows[0] if rows else None

    def _active_deed_for_slip(slip: dict) -> dict | None:
        for row in _deeds_for_slip(slip):
            if str(row.get("deed_status") or "").lower() in ACTIVE_DEED_STATUSES:
                return row
        return None

    def _feedback_state_for_slip(slip: dict) -> dict:
        deed = _active_deed_for_slip(slip) or _latest_deed_for_slip(slip)
        if not isinstance(deed, dict):
            return {}
        deed_id = str(deed.get("deed_id") or "")
        return ctx.feedback_state(deed_id) if deed_id else {}

    def _result_entry_for_slip(slip: dict) -> tuple[str, Path] | tuple[None, None]:
        deed = _latest_deed_for_slip(slip)
        if not isinstance(deed, dict):
            return None, None
        deed_id = str(deed.get("deed_id") or "")
        if not deed_id:
            return None, None
        entry = ctx.offering_entry_for_deed(deed_id)
        if not isinstance(entry, dict):
            return None, None
        root = ctx.require_offering_root() / str(entry.get("path") or "")
        if not root.exists():
            return None, None
        return deed_id, root

    def _timeline_for_slip(slip: dict, deed: dict | None) -> list[dict]:
        rows: list[dict] = []
        if isinstance(deed, dict):
            plan = deed.get("plan") if isinstance(deed.get("plan"), dict) else {}
            display = plan.get("plan_display") if isinstance(plan.get("plan_display"), dict) else {}
            timeline = display.get("timeline") if isinstance(display.get("timeline"), list) else []
            if timeline:
                for index, item in enumerate(timeline):
                    if not isinstance(item, dict):
                        continue
                    rows.append(
                        {
                            "id": str(item.get("id") or f"step_{index + 1}"),
                            "label": str(item.get("label") or item.get("instruction") or item.get("title") or f"步骤 {index + 1}"),
                        }
                    )
        if rows:
            return rows
        design = slip.get("design") if isinstance(slip.get("design"), dict) else {}
        moves = design.get("moves") if isinstance(design.get("moves"), list) else []
        for index, move in enumerate(moves):
            if not isinstance(move, dict):
                continue
            rows.append(
                {
                    "id": str(move.get("id") or f"move_{index + 1}"),
                    "label": str(move.get("instruction") or move.get("message") or move.get("title") or f"步骤 {index + 1}"),
                }
            )
        return rows

    def _deed_status(deed: dict | None) -> str:
        return str((deed or {}).get("deed_status") or "").strip().lower()

    def _slip_summary(slip: dict) -> dict:
        active_deed = _active_deed_for_slip(slip)
        latest_deed = _latest_deed_for_slip(slip)
        deed = active_deed or latest_deed
        folio = _folio_ref(str(slip.get("folio_id") or ""))
        stance = str(slip.get("status") or "active")
        deed_status = _deed_status(deed)
        result_ready = bool(ctx.offering_entry_for_deed(str((deed or {}).get("deed_id") or ""))) if deed else False
        return {
            "id": str(slip.get("slip_id") or ""),
            "slug": str(slip.get("slug") or ""),
            "canonical_slug": str(slip.get("slug") or ""),
            "title": str(slip.get("title") or "新签札"),
            "objective": str(slip.get("objective") or ""),
            "stance": stance,
            "standing": bool(slip.get("standing")),
            "folio": folio,
            "deed": {
                "id": str((deed or {}).get("deed_id") or ""),
                "status": deed_status,
                "created_utc": str((deed or {}).get("created_utc") or ""),
                "updated_utc": str((deed or {}).get("updated_utc") or ""),
            },
            "updated_utc": str((deed or {}).get("updated_utc") or slip.get("updated_utc") or ""),
            "created_utc": str(slip.get("created_utc") or ""),
            "result_ready": result_ready,
            "message_count": len(ctx.load_deed_messages(str((deed or {}).get("deed_id") or ""), 500)) if deed else 0,
            "plan": {
                "timeline": _timeline_for_slip(slip, deed),
            },
        }

    def _bucket_for_slip(summary: dict) -> str:
        deed_status = str(((summary.get("deed") or {}).get("status") or "")).lower()
        if deed_status in {"awaiting_eval"}:
            return "review"
        if deed_status in {"running", "queued", "paused", "cancelling"}:
            return "live"
        return "recent"

    def _folio_summary(folio: dict) -> dict:
        slips = [row for row in _slip_rows() if str(row.get("folio_id") or "") == str(folio.get("folio_id") or "")]
        slip_summaries = [_slip_summary(row) for row in slips]
        writs = ctx.folio_writ.list_writs(folio_id=str(folio.get("folio_id") or ""))
        updated_utc = str(folio.get("updated_utc") or "")
        for row in slip_summaries:
            if _parse_ts(str(row.get("updated_utc") or "")) > _parse_ts(updated_utc):
                updated_utc = str(row.get("updated_utc") or "")
        return {
            "id": str(folio.get("folio_id") or ""),
            "slug": str(folio.get("slug") or ""),
            "canonical_slug": str(folio.get("slug") or ""),
            "title": str(folio.get("title") or "新卷"),
            "summary": str(folio.get("summary") or ""),
            "status": str(folio.get("status") or "active"),
            "updated_utc": updated_utc,
            "slip_count": len(slip_summaries),
            "live_slip_count": sum(1 for row in slip_summaries if _bucket_for_slip(row) == "live"),
            "review_slip_count": sum(1 for row in slip_summaries if _bucket_for_slip(row) == "review"),
            "writ_count": len(writs),
            "recent_slips": sorted(
                slip_summaries,
                key=lambda row: _parse_ts(str(row.get("updated_utc") or "")),
                reverse=True,
            )[:4],
        }

    def _recent_results_for_folio(folio: dict, *, limit: int = 6) -> list[dict]:
        rows: list[dict] = []
        folio_id = str(folio.get("folio_id") or "")
        for slip in [row for row in _slip_rows() if str(row.get("folio_id") or "") == folio_id]:
            latest_deed = _latest_deed_for_slip(slip)
            if not isinstance(latest_deed, dict):
                continue
            deed_id = str(latest_deed.get("deed_id") or "")
            if not deed_id:
                continue
            entry = ctx.offering_entry_for_deed(deed_id)
            if not isinstance(entry, dict):
                continue
            rows.append(
                {
                    "deed_id": deed_id,
                    "slip_id": str(slip.get("slip_id") or ""),
                    "slip_slug": str(slip.get("slug") or ""),
                    "slip_title": str(slip.get("title") or "新签札"),
                    "title": str(entry.get("title") or slip.get("title") or latest_deed.get("deed_title") or "最近结果"),
                    "updated_utc": str(latest_deed.get("updated_utc") or latest_deed.get("created_utc") or ""),
                }
            )
        rows.sort(key=lambda row: _parse_ts(str(row.get("updated_utc") or "")), reverse=True)
        return rows[: max(1, limit)]

    def _resolve_slip(slip_slug: str) -> dict:
        row = ctx.folio_writ.get_slip_by_slug(slip_slug)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="slip_not_found")
        return row

    def _resolve_folio(folio_slug: str) -> dict:
        row = ctx.folio_writ.get_folio_by_slug(folio_slug)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="folio_not_found")
        return row

    async def _signal_deed(deed_id: str, row: dict, *, signal_name: str, payload: dict | None = None) -> str:
        await ctx.ensure_temporal_client(retries=2, delay_s=0.3)
        temporal_client = ctx.get_temporal_client()
        if not temporal_client:
            raise HTTPException(status_code=503, detail="temporal_unavailable")
        last_error = ""
        for workflow_id in _workflow_ids_for_row(deed_id, row):
            try:
                await temporal_client.signal(workflow_id, signal_name, payload or {})
                return workflow_id
            except Exception as exc:
                last_error = str(exc)[:240]
        raise HTTPException(status_code=409, detail=f"deed_signal_failed:{last_error}")

    async def _cancel_deed(deed_id: str, row: dict) -> tuple[bool, str]:
        await ctx.ensure_temporal_client(retries=2, delay_s=0.3)
        temporal_client = ctx.get_temporal_client()
        if not temporal_client:
            return False, "temporal_unavailable"
        last_error = ""
        for workflow_id in _workflow_ids_for_row(deed_id, row):
            try:
                await temporal_client.cancel(workflow_id)
                return True, workflow_id
            except Exception as exc:
                last_error = str(exc)[:240]
        return False, last_error

    def _spawn_plan_for_slip(slip: dict, *, extra_text: str = "") -> dict:
        brief = dict(slip.get("brief") if isinstance(slip.get("brief"), dict) else {})
        design = dict(slip.get("design") if isinstance(slip.get("design"), dict) else {})
        moves = design.get("moves") if isinstance(design.get("moves"), list) else []
        if not moves:
            latest_deed = _latest_deed_for_slip(slip)
            latest_plan = latest_deed.get("plan") if isinstance((latest_deed or {}).get("plan"), dict) else {}
            moves = latest_plan.get("moves") if isinstance(latest_plan.get("moves"), list) else []
        if not moves:
            raise HTTPException(status_code=409, detail="slip_has_no_design")
        title = str(slip.get("title") or "新签札")
        objective = str(brief.get("objective") or slip.get("objective") or title).strip()
        if extra_text:
            objective = f"{objective}\n\n补记：{extra_text.strip()}"
            brief["objective"] = objective
        return {
            "title": title,
            "slip_title": title,
            "brief": brief,
            "moves": moves,
            "slip_id": str(slip.get("slip_id") or ""),
            "folio_id": str(slip.get("folio_id") or "") or None,
            "metadata": {
                "source": "portal",
                "slip_id": str(slip.get("slip_id") or ""),
                "folio_id": str(slip.get("folio_id") or "") or None,
            },
        }

    def _folio_title_from_slips(source: dict, target: dict) -> str:
        source_title = str(source.get("title") or "").strip()
        target_title = str(target.get("title") or "").strip()
        source_tokens = [token for token in source_title.replace("／", "/").replace("-", " ").split() if token]
        target_tokens = [token for token in target_title.replace("／", "/").replace("-", " ").split() if token]
        shared = [token for token in source_tokens if token in target_tokens]
        if shared:
            return " ".join(shared[:4])
        if source_title and target_title:
            return f"{target_title} / {source_title}"
        return source_title or target_title or "新卷"

    @app.get("/portal-api/sidebar")
    def portal_sidebar(request: Request):
        slips = [_slip_summary(row) for row in _slip_rows()]
        folios = [_folio_summary(row) for row in _folio_rows()]
        review = [row for row in slips if _bucket_for_slip(row) == "review"]
        live = [row for row in slips if _bucket_for_slip(row) == "live"]
        recent = [row for row in slips if _bucket_for_slip(row) == "recent" and not row.get("folio")]
        payload = {
            "pending": sorted(review, key=lambda row: _parse_ts(str(row.get("updated_utc") or "")), reverse=True)[:40],
            "live": sorted(live, key=lambda row: _parse_ts(str(row.get("updated_utc") or "")), reverse=True)[:60],
            "folios": sorted(folios, key=lambda row: _parse_ts(str(row.get("updated_utc") or "")), reverse=True)[:80],
            "recent": sorted(recent, key=lambda row: _parse_ts(str(row.get("updated_utc") or "")), reverse=True)[:80],
        }
        ctx.log_portal_event("portal_sidebar", {"folios": len(payload["folios"]), "slips": len(slips)}, request)
        return payload

    @app.get("/portal-api/slips/by-deed/{deed_id}")
    def portal_slip_by_deed(deed_id: str):
        row = ctx.ledger.get_deed(deed_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="deed_not_found")
        slip_id = str(row.get("slip_id") or "")
        slip = ctx.folio_writ.get_slip(slip_id) if slip_id else None
        if not isinstance(slip, dict):
            raise HTTPException(status_code=404, detail="slip_not_found")
        return {"slip_id": slip_id, "slug": str(slip.get("slug") or ""), "canonical_slug": str(slip.get("slug") or "")}

    @app.get("/portal-api/slips/{slip_slug}")
    def portal_get_slip(slip_slug: str, request: Request):
        slip = _resolve_slip(slip_slug)
        active_deed = _active_deed_for_slip(slip)
        latest_deed = _latest_deed_for_slip(slip)
        current_deed = active_deed or latest_deed
        payload = _slip_summary(slip)
        payload["folio"] = _folio_ref(str(slip.get("folio_id") or ""))
        payload["feedback"] = _feedback_state_for_slip(slip)
        payload["current_deed"] = {
            "id": str((current_deed or {}).get("deed_id") or ""),
            "status": _deed_status(current_deed),
            "created_utc": str((current_deed or {}).get("created_utc") or ""),
            "updated_utc": str((current_deed or {}).get("updated_utc") or ""),
        }
        payload["recent_deeds"] = [
            {
                "id": str(row.get("deed_id") or ""),
                "status": str(row.get("deed_status") or ""),
                "created_utc": str(row.get("created_utc") or ""),
                "updated_utc": str(row.get("updated_utc") or ""),
            }
            for row in _deeds_for_slip(slip)[:6]
        ]
        ctx.log_portal_event("portal_get_slip", {"slip_id": payload["id"]}, request)
        return payload

    @app.get("/portal-api/slips/{slip_slug}/messages")
    def portal_slip_messages(slip_slug: str, request: Request, limit: int = 300):
        slip = _resolve_slip(slip_slug)
        deed = _active_deed_for_slip(slip) or _latest_deed_for_slip(slip)
        if not isinstance(deed, dict):
            return []
        deed_id = str(deed.get("deed_id") or "")
        rows = ctx.load_deed_messages(deed_id, max(1, min(limit, 500)))
        ctx.log_portal_event("portal_slip_messages", {"slip_id": slip.get("slip_id"), "count": len(rows)}, request)
        return rows

    @app.post("/portal-api/slips/{slip_slug}/message")
    async def portal_slip_message(slip_slug: str, request: Request):
        slip = _resolve_slip(slip_slug)
        body = await request.json()
        text = str(body.get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="message_required")
        deed = _active_deed_for_slip(slip)
        if isinstance(deed, dict):
            deed_id = str(deed.get("deed_id") or "")
            ctx.append_deed_message(deed_id, role="user", content=text, event="user_message", meta={"source": "portal"})
            workflow_id = ""
            if _deed_status(deed) in {"running", "queued", "cancelling"}:
                workflow_id = await _signal_deed(deed_id, deed, signal_name="pause_execution", payload={"source": "portal_message"})
            ctx.log_portal_event("portal_slip_message", {"slip_id": slip.get("slip_id"), "deed_id": deed_id, "workflow_id": workflow_id}, request)
            return {"ok": True, "slip_id": slip.get("slip_id"), "deed_id": deed_id, "workflow_id": workflow_id}

        plan = _spawn_plan_for_slip(slip, extra_text=text)
        result = await ctx.will.submit(plan)
        if not result.get("ok"):
            raise HTTPException(status_code=409, detail=result.get("error_code") or result.get("error") or "slip_submit_failed")
        ctx.log_portal_event("portal_slip_respawn", {"slip_id": slip.get("slip_id"), "deed_id": result.get("deed_id")}, request)
        return result

    @app.post("/portal-api/slips/{slip_slug}/stance")
    async def portal_slip_stance(slip_slug: str, request: Request):
        slip = _resolve_slip(slip_slug)
        body = await request.json()
        target = str(body.get("target") or "").strip().lower()
        if target not in {"continue", "park", "archive"}:
            raise HTTPException(status_code=400, detail="invalid_stance_target")
        deed = _active_deed_for_slip(slip)
        if target == "continue":
            ctx.folio_writ.update_slip(str(slip.get("slip_id") or ""), {"status": "active"})
            if isinstance(deed, dict) and _deed_status(deed) == "paused":
                workflow_id = await _signal_deed(str(deed.get("deed_id") or ""), deed, signal_name="resume_execution", payload={"source": "portal"})
                return {"ok": True, "slip_id": slip.get("slip_id"), "deed_id": deed.get("deed_id"), "workflow_id": workflow_id}
            result = await ctx.will.submit(_spawn_plan_for_slip(slip))
            if not result.get("ok"):
                raise HTTPException(status_code=409, detail=result.get("error_code") or result.get("error") or "slip_resume_failed")
            return result
        if target == "park":
            ctx.folio_writ.update_slip(str(slip.get("slip_id") or ""), {"status": "parked"})
            if isinstance(deed, dict) and _deed_status(deed) in {"running", "queued", "cancelling"}:
                workflow_id = await _signal_deed(str(deed.get("deed_id") or ""), deed, signal_name="pause_execution", payload={"source": "portal"})
                return {"ok": True, "slip_id": slip.get("slip_id"), "deed_id": deed.get("deed_id"), "workflow_id": workflow_id}
            return {"ok": True, "slip_id": slip.get("slip_id"), "status": "parked"}

        ctx.folio_writ.update_slip(str(slip.get("slip_id") or ""), {"status": "archived"})
        if isinstance(deed, dict) and _deed_status(deed) in {"running", "queued", "paused", "cancelling"}:
            cancelled, detail = await _cancel_deed(str(deed.get("deed_id") or ""), deed)
            return {"ok": cancelled, "slip_id": slip.get("slip_id"), "deed_id": deed.get("deed_id"), "detail": detail}
        return {"ok": True, "slip_id": slip.get("slip_id"), "status": "archived"}

    @app.post("/portal-api/slips/{slip_slug}/rerun")
    async def portal_slip_rerun(slip_slug: str, request: Request):
        slip = _resolve_slip(slip_slug)
        result = await ctx.will.submit(_spawn_plan_for_slip(slip))
        if not result.get("ok"):
            raise HTTPException(status_code=409, detail=result.get("error_code") or result.get("error") or "slip_rerun_failed")
        ctx.log_portal_event("portal_slip_rerun", {"slip_id": slip.get("slip_id"), "deed_id": result.get("deed_id")}, request)
        return result

    @app.get("/portal-api/slips/{slip_slug}/feedback/state")
    def portal_slip_feedback_state(slip_slug: str):
        slip = _resolve_slip(slip_slug)
        return _feedback_state_for_slip(slip)

    @app.post("/portal-api/slips/{slip_slug}/feedback")
    async def portal_slip_feedback(slip_slug: str, request: Request):
        slip = _resolve_slip(slip_slug)
        deed = _active_deed_for_slip(slip) or _latest_deed_for_slip(slip)
        if not isinstance(deed, dict):
            raise HTTPException(status_code=409, detail="slip_has_no_deed_for_feedback")
        return await ctx.submit_feedback_internal(str(deed.get("deed_id") or ""), await request.json(), request=request)

    @app.post("/portal-api/slips/{slip_slug}/feedback/append")
    async def portal_slip_feedback_append(slip_slug: str, request: Request):
        slip = _resolve_slip(slip_slug)
        deed = _active_deed_for_slip(slip) or _latest_deed_for_slip(slip)
        if not isinstance(deed, dict):
            raise HTTPException(status_code=409, detail="slip_has_no_deed_for_feedback")
        return await ctx.submit_feedback_internal(str(deed.get("deed_id") or ""), await request.json(), request=request)

    @app.get("/portal-api/slips/{slip_slug}/result/files")
    def portal_slip_result_files(slip_slug: str, request: Request):
        slip = _resolve_slip(slip_slug)
        deed_id, result_root = _result_entry_for_slip(slip)
        if not deed_id or not result_root:
            return {"slip_id": str(slip.get("slip_id") or ""), "files": []}
        offering_root = ctx.require_offering_root()
        files = []
        for file_path in sorted(result_root.rglob("*")):
            if not file_path.is_file():
                continue
            rel = str(file_path.relative_to(result_root)).replace("\\", "/")
            files.append(
                {
                    "name": file_path.name,
                    "relative_path": rel,
                    "download": f"/portal-api/slips/{slip_slug}/result/files/{rel}",
                }
            )
        ctx.log_portal_event("portal_slip_result_files", {"slip_id": slip.get("slip_id"), "count": len(files)}, request)
        return {"slip_id": str(slip.get("slip_id") or ""), "deed_id": deed_id, "files": files}

    @app.get("/portal-api/slips/{slip_slug}/result/files/{filename:path}")
    def portal_slip_result_file(slip_slug: str, filename: str, request: Request):
        slip = _resolve_slip(slip_slug)
        _, result_root = _result_entry_for_slip(slip)
        if not result_root:
            raise HTTPException(status_code=404, detail="slip_result_missing")
        candidate = (result_root / filename).resolve()
        try:
            candidate.relative_to(result_root.resolve())
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid_file_path") from exc
        if not candidate.exists() or not candidate.is_file():
            raise HTTPException(status_code=404, detail="result_file_not_found")
        ctx.log_portal_event("portal_slip_result_file", {"slip_id": slip.get("slip_id"), "filename": filename}, request)
        return FileResponse(candidate)

    @app.get("/portal-api/folios/{folio_slug}")
    def portal_get_folio(folio_slug: str, request: Request):
        folio = _resolve_folio(folio_slug)
        slips = [_slip_summary(row) for row in _slip_rows() if str(row.get("folio_id") or "") == str(folio.get("folio_id") or "")]
        slips.sort(key=lambda row: _parse_ts(str(row.get("updated_utc") or "")), reverse=True)
        writs = []
        for writ in ctx.folio_writ.list_writs(folio_id=str(folio.get("folio_id") or "")):
            if not isinstance(writ, dict):
                continue
            writs.append(
                {
                    "id": str(writ.get("writ_id") or ""),
                    "title": str(writ.get("title") or "新成文"),
                    "status": str(writ.get("status") or "active"),
                    "last_triggered_utc": str(writ.get("last_triggered_utc") or ""),
                    "recent_deeds": ctx.folio_writ.recent_deed_summaries(str(writ.get("writ_id") or ""), limit=3),
                }
            )
        payload = _folio_summary(folio)
        payload["slips"] = slips
        payload["writs"] = writs
        payload["recent_results"] = _recent_results_for_folio(folio)
        ctx.log_portal_event("portal_get_folio", {"folio_id": payload["id"]}, request)
        return payload

    @app.post("/portal-api/folios/{folio_slug}/adopt")
    async def portal_folio_adopt(folio_slug: str, request: Request):
        folio = _resolve_folio(folio_slug)
        body = await request.json()
        slip_slug = str(body.get("slip_slug") or "").strip()
        if not slip_slug:
            raise HTTPException(status_code=400, detail="slip_slug_required")
        slip = _resolve_slip(slip_slug)
        ctx.folio_writ.update_slip(str(slip.get("slip_id") or ""), {"folio_id": str(folio.get("folio_id") or "")})
        return {
            "ok": True,
            "folio": _folio_summary(ctx.folio_writ.get_folio(str(folio.get("folio_id") or "")) or folio),
            "slip": _slip_summary(ctx.folio_writ.get_slip(str(slip.get("slip_id") or "")) or slip),
        }

    @app.post("/portal-api/folios/from-slips")
    async def portal_folio_from_slips(request: Request):
        body = await request.json()
        source = _resolve_slip(str(body.get("source_slug") or "").strip())
        target = _resolve_slip(str(body.get("target_slug") or "").strip())
        source_folio_id = str(source.get("folio_id") or "")
        target_folio_id = str(target.get("folio_id") or "")
        if source_folio_id and target_folio_id and source_folio_id != target_folio_id:
            raise HTTPException(status_code=409, detail="slips_in_different_folios")
        if target_folio_id and not source_folio_id:
            ctx.folio_writ.update_slip(str(source.get("slip_id") or ""), {"folio_id": target_folio_id})
            folio = ctx.folio_writ.get_folio(target_folio_id)
            return {"ok": True, "folio": _folio_summary(folio or {})}
        if source_folio_id and source_folio_id == target_folio_id:
            folio = ctx.folio_writ.get_folio(source_folio_id)
            return {"ok": True, "folio": _folio_summary(folio or {})}
        folio = ctx.folio_writ.create_folio(title=_folio_title_from_slips(source, target))
        folio_id = str(folio.get("folio_id") or "")
        ctx.folio_writ.update_slip(str(source.get("slip_id") or ""), {"folio_id": folio_id})
        ctx.folio_writ.update_slip(str(target.get("slip_id") or ""), {"folio_id": folio_id})
        return {"ok": True, "folio": _folio_summary(ctx.folio_writ.get_folio(folio_id) or folio)}
