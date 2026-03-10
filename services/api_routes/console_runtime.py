"""Console runtime routes for Draft / Slip / Folio / Writ / Deed."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException


ACTIVE_DEED_STATUSES = {"running", "queued", "paused", "cancelling", "awaiting_eval"}


def register_console_runtime_routes(app: FastAPI, *, ctx: Any) -> None:
    def _all_deeds() -> list[dict]:
        return [row for row in ctx.ledger.load_deeds() if isinstance(row, dict)]

    def _timeline_summary(row: dict) -> list[dict]:
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else {}
        display = plan.get("plan_display") if isinstance(plan.get("plan_display"), dict) else {}
        timeline = display.get("timeline") if isinstance(display.get("timeline"), list) else []
        if not timeline:
            moves = plan.get("moves") if isinstance(plan.get("moves"), list) else []
            timeline = [
                {
                    "id": str(move.get("id") or f"move_{index + 1}"),
                    "label": str(move.get("instruction") or move.get("message") or move.get("title") or f"步骤 {index + 1}"),
                    "agent": str(move.get("agent") or ""),
                }
                for index, move in enumerate(moves)
                if isinstance(move, dict)
            ]
        status = str(row.get("deed_status") or "").lower()
        active_index = 0 if status in {"running", "queued", "paused", "cancelling"} else len(timeline)
        out = []
        for index, item in enumerate(timeline):
            state = "pending"
            if index < active_index:
                state = "done"
            elif index == active_index and status in {"running", "paused", "cancelling"}:
                state = "active"
            elif status in {"completed", "awaiting_eval", "cancelled"}:
                state = "done"
            elif status == "failed" and index == active_index:
                state = "failed"
            out.append(
                {
                    "id": str(item.get("id") or f"step_{index + 1}"),
                    "label": str(item.get("label") or f"步骤 {index + 1}"),
                    "agent": str(item.get("agent") or ""),
                    "state": state,
                }
            )
        return out

    def _deed_row(row: dict) -> dict:
        plan = row.get("plan") if isinstance(row.get("plan"), dict) else {}
        brief = plan.get("brief") if isinstance(plan.get("brief"), dict) else {}
        moves = plan.get("moves") if isinstance(plan.get("moves"), list) else []
        return {
            "deed_id": str(row.get("deed_id") or ""),
            "deed_status": str(row.get("deed_status") or ""),
            "phase": str(row.get("phase") or ""),
            "title": str(row.get("deed_title") or row.get("title") or plan.get("title") or ""),
            "slip_id": str(row.get("slip_id") or plan.get("slip_id") or ""),
            "folio_id": str(row.get("folio_id") or plan.get("folio_id") or ""),
            "writ_id": str(row.get("writ_id") or plan.get("writ_id") or ""),
            "standing": bool(brief.get("standing", False)),
            "dag_budget": int(brief.get("dag_budget") or len(moves) or 0),
            "move_count": len(moves),
            "created_utc": str(row.get("created_utc") or ""),
            "updated_utc": str(row.get("updated_utc") or ""),
        }

    def _message_summaries(deed_id: str, *, limit: int = 60) -> list[dict]:
        rows: list[dict] = []
        for index, message in enumerate(ctx.load_deed_messages(deed_id, limit), start=1):
            if not isinstance(message, dict):
                continue
            content = str(message.get("content") or "")
            rows.append(
                {
                    "index": index,
                    "role": str(message.get("role") or "system"),
                    "created_utc": str(message.get("created_utc") or message.get("ts") or ""),
                    "char_count": len(content),
                }
            )
        return rows

    def _slip_row(row: dict) -> dict:
        deeds = [item for item in _all_deeds() if str(item.get("slip_id") or "") == str(row.get("slip_id") or "")]
        deeds.sort(key=lambda item: str(item.get("updated_utc") or item.get("created_utc") or ""), reverse=True)
        latest = deeds[0] if deeds else {}
        active = next((item for item in deeds if str(item.get("deed_status") or "") in ACTIVE_DEED_STATUSES), None)
        brief = row.get("brief") if isinstance(row.get("brief"), dict) else {}
        design = row.get("design") if isinstance(row.get("design"), dict) else {}
        return {
            "slip_id": str(row.get("slip_id") or ""),
            "folio_id": str(row.get("folio_id") or ""),
            "title": str(row.get("title") or "新签札"),
            "slug": str(row.get("slug") or ""),
            "status": str(row.get("status") or "active"),
            "standing": bool(row.get("standing")),
            "objective": str(row.get("objective") or ""),
            "dag_budget": int(brief.get("dag_budget") or len(design.get("moves") or []) or 0),
            "move_count": len(design.get("moves") or []),
            "latest_deed_id": str((active or latest or {}).get("deed_id") or row.get("latest_deed_id") or ""),
            "latest_deed_status": str((active or latest or {}).get("deed_status") or ""),
            "deed_count": len(deeds),
            "created_utc": str(row.get("created_utc") or ""),
            "updated_utc": str(row.get("updated_utc") or ""),
        }

    def _folio_row(row: dict) -> dict:
        slips = [item for item in ctx.folio_writ.list_slips(folio_id=str(row.get("folio_id") or "")) if isinstance(item, dict)]
        writs = [item for item in ctx.folio_writ.list_writs(folio_id=str(row.get("folio_id") or "")) if isinstance(item, dict)]
        deed_rows = [item for item in _all_deeds() if str(item.get("folio_id") or "") == str(row.get("folio_id") or "")]
        return {
            "folio_id": str(row.get("folio_id") or ""),
            "title": str(row.get("title") or "新卷"),
            "slug": str(row.get("slug") or ""),
            "summary": str(row.get("summary") or ""),
            "status": str(row.get("status") or "active"),
            "slip_count": len(slips),
            "active_slip_count": sum(1 for item in slips if str(item.get("status") or "") == "active"),
            "writ_count": len(writs),
            "active_writ_count": sum(1 for item in writs if str(item.get("status") or "") == "active"),
            "active_deed_count": sum(1 for item in deed_rows if str(item.get("deed_status") or "") in ACTIVE_DEED_STATUSES),
            "updated_utc": str(row.get("updated_utc") or ""),
        }

    @app.get("/console/drafts")
    def list_console_drafts(limit: int = 200):
        rows = [row for row in ctx.folio_writ.list_drafts() if isinstance(row, dict)]
        rows.sort(key=lambda row: str(row.get("updated_utc") or ""), reverse=True)
        return rows[: max(1, min(limit, 500))]

    @app.get("/console/drafts/{draft_id}")
    def get_console_draft(draft_id: str):
        row = ctx.folio_writ.get_draft(draft_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="draft_not_found")
        return row

    @app.get("/console/slips")
    def list_console_slips(status: str | None = None, folio_id: str | None = None, limit: int = 300):
        rows = [_slip_row(row) for row in ctx.folio_writ.list_slips(folio_id=folio_id) if isinstance(row, dict)]
        if status:
            rows = [row for row in rows if str(row.get("status") or "") == str(status)]
        rows.sort(key=lambda row: str(row.get("updated_utc") or ""), reverse=True)
        return rows[: max(1, min(limit, 500))]

    @app.get("/console/slips/{slip_id}")
    def get_console_slip(slip_id: str):
        row = ctx.folio_writ.get_slip(slip_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="slip_not_found")
        payload = _slip_row(row)
        payload["brief"] = row.get("brief") if isinstance(row.get("brief"), dict) else {}
        payload["design"] = row.get("design") if isinstance(row.get("design"), dict) else {}
        payload["deeds"] = [_deed_row(item) for item in _all_deeds() if str(item.get("slip_id") or "") == slip_id]
        return payload

    @app.post("/console/slips/{slip_id}/{action}")
    def mutate_console_slip(slip_id: str, action: str):
        action = str(action or "").strip().lower()
        if action == "activate":
            row = ctx.folio_writ.update_slip(slip_id, {"status": "active"})
        elif action == "park":
            row = ctx.folio_writ.update_slip(slip_id, {"status": "parked"})
        elif action == "archive":
            row = ctx.folio_writ.update_slip(slip_id, {"status": "archived"})
        else:
            raise HTTPException(status_code=400, detail="invalid_action")
        if not row:
            raise HTTPException(status_code=404, detail="slip_not_found")
        return row

    @app.get("/console/folios")
    def list_console_folios(limit: int = 200):
        rows = [_folio_row(row) for row in ctx.folio_writ.list_folios() if isinstance(row, dict)]
        rows.sort(key=lambda row: str(row.get("updated_utc") or ""), reverse=True)
        return rows[: max(1, min(limit, 500))]

    @app.get("/console/folios/{folio_id}")
    def get_console_folio(folio_id: str):
        row = ctx.folio_writ.get_folio(folio_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="folio_not_found")
        slips = [_slip_row(item) for item in ctx.folio_writ.list_slips(folio_id=folio_id) if isinstance(item, dict)]
        writs = []
        for item in ctx.folio_writ.list_writs(folio_id=folio_id):
            if not isinstance(item, dict):
                continue
            writs.append(
                {
                    "writ_id": str(item.get("writ_id") or ""),
                    "title": str(item.get("title") or "新成文"),
                    "status": str(item.get("status") or "active"),
                    "last_triggered_utc": str(item.get("last_triggered_utc") or ""),
                    "deed_history_count": len(item.get("deed_history") or []),
                }
            )
        payload = _folio_row(row)
        payload["slips"] = slips
        payload["writs"] = writs
        return payload

    @app.post("/console/folios/{folio_id}/{action}")
    def mutate_console_folio(folio_id: str, action: str):
        action = str(action or "").strip().lower()
        if action == "activate":
            row = ctx.folio_writ.update_folio(folio_id, {"status": "active"})
        elif action == "park":
            row = ctx.folio_writ.update_folio(folio_id, {"status": "parked"})
        elif action == "archive":
            row = ctx.folio_writ.update_folio(folio_id, {"status": "archived"})
        elif action == "dissolve":
            row = ctx.folio_writ.update_folio(folio_id, {"status": "dissolved"})
        elif action == "delete":
            ok = ctx.folio_writ.delete_folio(folio_id)
            if not ok:
                raise HTTPException(status_code=404, detail="folio_not_found")
            return {"ok": True, "folio_id": folio_id}
        else:
            raise HTTPException(status_code=400, detail="invalid_action")
        if not row:
            raise HTTPException(status_code=404, detail="folio_not_found")
        return row

    @app.get("/console/writs")
    def list_console_writs(folio_id: str | None = None, limit: int = 300):
        rows = [row for row in ctx.folio_writ.list_writs(folio_id=folio_id) if isinstance(row, dict)]
        rows.sort(key=lambda row: str(row.get("updated_utc") or ""), reverse=True)
        return rows[: max(1, min(limit, 500))]

    @app.get("/console/writs/{writ_id}")
    def get_console_writ(writ_id: str):
        row = ctx.folio_writ.get_writ(writ_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="writ_not_found")
        payload = dict(row)
        payload["recent_deeds"] = ctx.folio_writ.recent_deed_summaries(writ_id, limit=6)
        return payload

    @app.post("/console/writs/{writ_id}/{action}")
    def mutate_console_writ(writ_id: str, action: str):
        action = str(action or "").strip().lower()
        if action == "activate":
            row = ctx.folio_writ.update_writ(writ_id, {"status": "active"})
        elif action == "pause":
            row = ctx.folio_writ.update_writ(writ_id, {"status": "paused"})
        elif action == "disable":
            row = ctx.folio_writ.update_writ(writ_id, {"status": "disabled"})
        elif action == "delete":
            ok = ctx.folio_writ.delete_writ(writ_id)
            if not ok:
                raise HTTPException(status_code=404, detail="writ_not_found")
            return {"ok": True, "writ_id": writ_id}
        else:
            raise HTTPException(status_code=400, detail="invalid_action")
        if not row:
            raise HTTPException(status_code=404, detail="writ_not_found")
        return row

    @app.get("/console/deeds")
    def list_console_deeds(status: str | None = None, limit: int = 300):
        rows = [_deed_row(row) for row in _all_deeds()]
        if status:
            rows = [row for row in rows if str(row.get("deed_status") or "") == str(status)]
        rows.sort(key=lambda row: str(row.get("updated_utc") or ""), reverse=True)
        return rows[: max(1, min(limit, 500))]

    @app.get("/console/deeds/{deed_id}")
    def get_console_deed(deed_id: str):
        row = ctx.ledger.get_deed(deed_id)
        if not isinstance(row, dict):
            raise HTTPException(status_code=404, detail="deed_not_found")
        payload = _deed_row(row)
        payload["timeline"] = _timeline_summary(row)
        payload["messages"] = _message_summaries(deed_id, limit=60)
        return payload
