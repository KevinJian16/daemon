"""System and integration routes extracted from monolithic services.api."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request


def register_system_routes(
    app: FastAPI,
    *,
    require_localhost: Callable[[Request], str],
    reset_manager: Any,
    drive_accounts: Any,
    log_portal_event: Callable[[str, dict[str, Any], Request | None], None],
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
        require_localhost(request)
        return reset_manager.last_report()

    @app.get("/portal/integrations/drive/status")
    def drive_status():
        return drive_accounts.integration_status()

    @app.get("/portal/integrations/drive/files")
    def drive_files(kind: str = "archive", subpath: str = "", limit: int = 200):
        result = drive_accounts.list_files(kind=kind, subpath=subpath, limit=limit)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result)
        return result

    @app.post("/portal/integrations/drive/files/delete")
    async def drive_delete_file(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        kind = str(body.get("kind") or "archive")
        path = str(body.get("path") or "").strip()
        result = drive_accounts.delete_file(kind=kind, rel_path=path)
        if not result.get("ok"):
            log_portal_event(
                "drive_file_delete_failed",
                {"kind": kind, "path": path, "error": str(result.get("error") or "")},
                request,
            )
            raise HTTPException(status_code=400, detail=result)
        log_portal_event(
            "drive_file_deleted",
            {"kind": kind, "path": path},
            request,
        )
        return result

    @app.get("/console/system/storage")
    def console_storage_status(request: Request):
        require_localhost(request)
        return drive_accounts.integration_status()

    @app.put("/console/system/storage")
    async def console_storage_update(request: Request):
        require_localhost(request)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        daemon_dir_name = str(body.get("daemon_dir_name") or "").strip()
        if not daemon_dir_name:
            raise HTTPException(status_code=400, detail="daemon_dir_name_required")
        result = drive_accounts.set_daemon_dir_name(daemon_dir_name)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result)
        return result
