"""System routes extracted from monolithic services.api."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request

logger = logging.getLogger(__name__)

VALID_SYSTEM_STATUSES = {"running", "paused", "restarting", "resetting", "shutdown"}
VALID_ACTIONS = {"pause", "resume", "shutdown"}


def _read_system_status(state_dir: Path) -> dict:
    path = state_dir / "system_status.json"
    if not path.exists():
        return {"status": "running", "updated_utc": "unknown"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"status": "running", "updated_utc": "unknown"}


def _write_system_status(state_dir: Path, status: str, reason: str = "") -> dict:
    path = state_dir / "system_status.json"
    utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    data = {"status": status, "updated_utc": utc}
    if reason:
        data["reason"] = reason
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def register_system_routes(
    app: FastAPI,
    *,
    require_localhost: Callable[[Request], str],
    reset_manager: Any,
    log_portal_event: Callable[[str, dict[str, Any], Request | None], None],
    state_dir: Path | None = None,
) -> None:
    @app.post("/console/system/reset/challenge")
    async def system_reset_challenge(request: Request):
        host = require_localhost(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        mode = str(body.get("mode") or "strict")
        restart = bool(body.get("restart", False))
        ttl = int(body.get("ttl_seconds") or 180)
        payload = reset_manager.issue_challenge(mode=mode, restart=restart, ttl_seconds=ttl)
        return {
            "ok": True,
            "challenge_id": payload.get("challenge_id", ""),
            "confirm_code": payload.get("confirm_code", ""),
            "mode": payload.get("mode", "strict"),
            "restart": bool(payload.get("restart", False)),
            "expires_utc": payload.get("expires_utc", ""),
            "host": host,
        }

    @app.post("/console/system/reset/confirm")
    async def system_reset_confirm(request: Request):
        host = require_localhost(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        challenge_id = str(body.get("challenge_id") or "")
        confirm_code = str(body.get("confirm_code") or "")
        mode = body.get("mode")
        restart = body.get("restart")
        if not challenge_id or not confirm_code:
            raise HTTPException(status_code=400, detail="challenge_id_and_confirm_code_required")
        try:
            record = reset_manager.validate_and_consume_challenge(
                challenge_id=challenge_id,
                confirm_code=confirm_code,
                requester_host=host,
                mode=str(mode) if mode is not None else None,
                restart=bool(restart) if restart is not None else None,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        launch = reset_manager.launch_detached_reset(
            mode=str(record.get("mode") or "strict"),
            restart=bool(record.get("restart", False)),
            reason="api_confirm",
        )
        return {
            "ok": True,
            "accepted": True,
            "challenge_id": record.get("challenge_id", ""),
            "mode": record.get("mode", "strict"),
            "restart": bool(record.get("restart", False)),
            "launch": launch,
        }

    @app.get("/console/system/reset/last-report")
    def system_reset_last_report(request: Request):
        return reset_manager.last_report()

    # ── System lifecycle (§4.6) ────────────────────────────────────────────

    _state = state_dir

    @app.get("/system/status")
    async def system_status():
        if not _state:
            return {"status": "running", "updated_utc": "unknown"}
        return _read_system_status(_state)

    @app.post("/system/{action}")
    async def system_action(action: str, request: Request):
        require_localhost(request)
        if not _state:
            raise HTTPException(500, "state_dir not configured")
        if action not in VALID_ACTIONS:
            raise HTTPException(400, f"Invalid action: {action}. Valid: {sorted(VALID_ACTIONS)}")

        current = _read_system_status(_state)
        current_status = current.get("status", "running")

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        reason = str(body.get("reason") or action)

        if action == "pause":
            if current_status == "paused":
                return {"ok": True, "status": "paused", "note": "already paused"}
            if current_status != "running":
                raise HTTPException(409, f"Cannot pause from state '{current_status}'")
            result = _write_system_status(_state, "paused", reason)
            logger.info("System paused: %s", reason)

        elif action == "resume":
            if current_status == "running":
                return {"ok": True, "status": "running", "note": "already running"}
            if current_status not in {"paused", "restarting"}:
                raise HTTPException(409, f"Cannot resume from state '{current_status}'")
            result = _write_system_status(_state, "running", reason)
            logger.info("System resumed: %s", reason)

        elif action == "shutdown":
            result = _write_system_status(_state, "shutdown", reason)
            logger.info("System shutdown requested: %s", reason)

        else:
            raise HTTPException(400, f"Unhandled action: {action}")

        log_portal_event("system_action", {"action": action, "result": result}, request)
        return {"ok": True, **result}
