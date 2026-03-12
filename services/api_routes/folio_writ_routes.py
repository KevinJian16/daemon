"""Folio / Writ / Slip / Draft CRUD routes."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException


def register_folio_writ_routes(app: FastAPI, folio_writ) -> None:
    @app.get("/folios")
    def list_folios():
        return folio_writ.list_folios()

    @app.post("/folios")
    def create_folio(payload: dict):
        title = str(payload.get("title") or "").strip()
        if not title:
            raise HTTPException(400, "title required")
        return folio_writ.create_folio(title=title, summary=str(payload.get("summary") or ""))

    @app.get("/folios/{folio_id}")
    def get_folio(folio_id: str):
        row = folio_writ.get_folio(folio_id)
        if not row:
            raise HTTPException(404, "folio not found")
        return row

    @app.put("/folios/{folio_id}")
    def update_folio(folio_id: str, payload: dict):
        row = folio_writ.update_folio(folio_id, payload if isinstance(payload, dict) else {})
        if not row:
            raise HTTPException(404, "folio not found or invalid update")
        return row

    @app.delete("/folios/{folio_id}")
    def delete_folio(folio_id: str):
        if not folio_writ.delete_folio(folio_id):
            raise HTTPException(404, "folio not found")
        return {"ok": True}

    @app.get("/slips")
    def list_slips(folio_id: str | None = None):
        return folio_writ.list_slips(folio_id=folio_id)

    @app.get("/slips/{slip_id}")
    def get_slip(slip_id: str):
        row = folio_writ.get_slip(slip_id)
        if not row:
            raise HTTPException(404, "slip not found")
        return row

    @app.put("/slips/{slip_id}")
    def update_slip(slip_id: str, payload: dict):
        row = folio_writ.update_slip(slip_id, payload if isinstance(payload, dict) else {})
        if not row:
            raise HTTPException(404, "slip not found or invalid update")
        return row

    @app.get("/drafts")
    def list_drafts():
        return folio_writ.list_drafts()

    @app.get("/drafts/{draft_id}")
    def get_draft(draft_id: str):
        row = folio_writ.get_draft(draft_id)
        if not row:
            raise HTTPException(404, "draft not found")
        return row

    @app.put("/drafts/{draft_id}")
    def update_draft(draft_id: str, payload: dict):
        row = folio_writ.update_draft(draft_id, payload if isinstance(payload, dict) else {})
        if not row:
            raise HTTPException(404, "draft not found or invalid update")
        return row

    @app.post("/drafts/{draft_id}/crystallize")
    def crystallize_draft(draft_id: str, payload: dict):
        body = payload if isinstance(payload, dict) else {}
        title = str(body.get("title") or "").strip()
        objective = str(body.get("objective") or "").strip()
        if not title:
            raise HTTPException(400, "title required")
        if not objective:
            raise HTTPException(400, "objective required")
        try:
            return folio_writ.crystallize_draft(
                draft_id,
                title=title,
                objective=objective,
                brief=body.get("brief") if isinstance(body.get("brief"), dict) else {},
                design=body.get("design") if isinstance(body.get("design"), dict) else {},
                folio_id=str(body.get("folio_id") or "").strip() or None,
                standing=bool(body.get("standing")),
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    @app.get("/writs")
    def list_writs(folio_id: str | None = None):
        return folio_writ.list_writs(folio_id=folio_id)

    @app.post("/writs")
    def create_writ(payload: dict):
        folio_id = str(payload.get("folio_id") or "").strip()
        title = str(payload.get("title") or "").strip()
        if not folio_id:
            raise HTTPException(400, "folio_id required")
        if not title:
            raise HTTPException(400, "title required")
        return folio_writ.create_writ(
            folio_id=folio_id,
            title=title,
            match=payload.get("match") if isinstance(payload.get("match"), dict) else {},
            action=payload.get("action") if isinstance(payload.get("action"), dict) else {},
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        )

    @app.get("/writs/{writ_id}")
    def get_writ(writ_id: str):
        row = folio_writ.get_writ(writ_id)
        if not row:
            raise HTTPException(404, "writ not found")
        return row

    @app.put("/writs/{writ_id}")
    def update_writ(writ_id: str, payload: dict):
        row = folio_writ.update_writ(writ_id, payload if isinstance(payload, dict) else {})
        if not row:
            raise HTTPException(404, "writ not found or invalid update")
        return row

    @app.delete("/writs/{writ_id}")
    def delete_writ(writ_id: str):
        if not folio_writ.delete_writ(writ_id):
            raise HTTPException(404, "writ not found")
        return {"ok": True}

    @app.post("/events/ingest")
    def ingest_event(payload: dict):
        event_name = str(payload.get("event") or "").strip()
        data = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        if not event_name:
            raise HTTPException(400, "event required")
        folio_writ._nerve.emit(event_name, data)
        return {"ok": True}
