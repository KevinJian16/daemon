"""Dominion and Writ CRUD routes + /events/ingest endpoint."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


def register_track_routes(app, dominion_writ_manager) -> None:
    """Register Dominion/Writ API routes on the FastAPI app."""

    def _paths(prefix: str, suffix: str = "") -> list[str]:
        base = f"{prefix}{suffix}"
        console = f"/console{base}"
        return [base, console]

    for path in _paths("/dominions"):
        @app.get(path)
        async def list_dominions():
            return dominion_writ_manager.list_dominions()

    for path in _paths("/dominions"):
        @app.post(path)
        async def create_dominion(request: Request):
            body = await request.json()
            objective = body.get("objective", "")
            if not objective:
                raise HTTPException(400, "objective is required")
            return dominion_writ_manager.create_dominion(objective, metadata=body.get("metadata"))

    for path in _paths("/dominions/{dominion_id}"):
        @app.get(path)
        async def get_dominion(dominion_id: str):
            t = dominion_writ_manager.get_dominion(dominion_id)
            if not t:
                raise HTTPException(404, "Dominion not found")
            return t

    for path in _paths("/dominions/{dominion_id}"):
        @app.put(path)
        async def update_dominion(dominion_id: str, request: Request):
            body = await request.json()
            result = dominion_writ_manager.update_dominion(dominion_id, body)
            if not result:
                raise HTTPException(404, "Dominion not found or invalid update")
            return result

    for path in _paths("/dominions/{dominion_id}"):
        @app.delete(path)
        async def delete_dominion(dominion_id: str):
            if not dominion_writ_manager.delete_dominion(dominion_id):
                raise HTTPException(404, "Dominion not found")
            return {"ok": True}

    for path in _paths("/writs"):
        @app.get(path)
        async def list_writs(dominion_id: str | None = None):
            return dominion_writ_manager.list_writs(dominion_id=dominion_id)

    for path in _paths("/writs"):
        @app.post(path)
        async def create_writ(request: Request):
            body = await request.json()
            brief_template = body.get("brief_template", {})
            trigger = body.get("trigger", {})
            if not trigger.get("event") and not trigger.get("schedule"):
                raise HTTPException(400, "trigger.event or trigger.schedule is required")
            try:
                return dominion_writ_manager.create_writ(
                    brief_template=brief_template,
                    trigger=trigger,
                    dominion_id=body.get("dominion_id"),
                    label=body.get("label", ""),
                    depends_on_writ=body.get("depends_on_writ"),
                    metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else body,
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc))

    for path in _paths("/writs/{writ_id}"):
        @app.get(path)
        async def get_writ(writ_id: str):
            w = dominion_writ_manager.get_writ(writ_id)
            if not w:
                raise HTTPException(404, "Writ not found")
            return w

    for path in _paths("/writs/{writ_id}"):
        @app.put(path)
        async def update_writ(writ_id: str, request: Request):
            body = await request.json()
            result = dominion_writ_manager.update_writ(writ_id, body)
            if not result:
                raise HTTPException(404, "Writ not found or invalid update")
            return result

    for path in _paths("/writs/{writ_id}"):
        @app.delete(path)
        async def delete_writ(writ_id: str):
            if not dominion_writ_manager.delete_writ(writ_id):
                raise HTTPException(404, "Writ not found")
            return {"ok": True}

    @app.post("/console/writs/{writ_id}/split")
    async def split_writ(writ_id: str, request: Request):
        body = await request.json()
        splits = body.get("splits") if isinstance(body.get("splits"), list) else []
        try:
            return dominion_writ_manager.split_writ(writ_id, splits)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/console/writs/merge")
    async def merge_writs(request: Request):
        body = await request.json()
        writ_ids = body.get("writ_ids") if isinstance(body.get("writ_ids"), list) else []
        label = str(body.get("label") or "Merged Writ")
        brief_template = body.get("brief_template") if isinstance(body.get("brief_template"), dict) else {}
        trigger = body.get("trigger") if isinstance(body.get("trigger"), dict) else {}
        try:
            return dominion_writ_manager.merge_writs(writ_ids, label=label, brief_template=brief_template, trigger=trigger)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.post("/events/ingest")
    async def events_ingest(request: Request):
        """External adapter endpoint: normalize external signals into Nerve events.

        Body: {"event": "page_changed", "payload": {...}, "source": "crawler_adapter"}
        """
        body = await request.json()
        event = body.get("event")
        if not event:
            raise HTTPException(400, "event is required")
        payload = body.get("payload", {})
        payload["_source"] = body.get("source", "external")
        nerve = dominion_writ_manager._nerve
        nerve.emit(event, payload)
        return {"ok": True, "event": event}
