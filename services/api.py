"""Daemon API — FastAPI application with Portal and Console routes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from psyche.config import PsycheConfig
from psyche.ledger_stats import LedgerStats
from psyche.instinct_engine import InstinctEngine
from spine.nerve import Nerve
from spine.trail import Trail
from spine.canon import SpineCanon
from spine.routines import SpineRoutines
from runtime.retinue import Retinue
from runtime.cortex import Cortex
from runtime.ether import Ether
from runtime.temporal import TemporalClient
from runtime.brief import SINGLE_SLIP_DEFAULTS
from services.will import Will
from services.voice import VoiceService
from services.api_routes.basic import register_basic_routes
from services.api_routes.chat import register_chat_routes
from services.api_routes.feedback import register_feedback_routes
from services.api_routes.submit import register_submit_route
from services.api_routes.system import register_system_routes
from services.api_routes.portal_shell import register_portal_shell_routes
from services.api_routes.console_admin import register_console_admin_routes
from services.api_routes.console_agents_skill import register_console_agents_skill_routes
from services.api_routes.console_observe import register_console_observe_routes
from services.api_routes.console_rations import register_console_rations_routes
from services.api_routes.console_runtime import register_console_runtime_routes
from services.api_routes.console_psyche import register_console_psyche_routes
from services.api_routes.console_spine import register_console_spine_routes
from services.cadence import Cadence
from services.ledger import Ledger
from services.folio_writ import FolioWritManager
from services.api_routes.folio_writ_routes import register_folio_writ_routes
from services.system_reset import SystemResetManager
from services.storage_paths import resolve_offering_root
from daemon_env import load_daemon_env
from bootstrap import normalize_openclaw_config


def _daemon_home() -> Path:
    return Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))


def _openclaw_home() -> Path:
    v = os.environ.get("OPENCLAW_HOME")
    return Path(v) if v else _daemon_home() / "openclaw"


def _temporal_config() -> dict[str, Any]:
    system_path = _daemon_home() / "config" / "system.json"
    cfg: dict[str, Any] = {}
    if system_path.exists():
        try:
            cfg = json.loads(system_path.read_text())
        except Exception as exc:
            logger.warning("Failed to read system config %s: %s", system_path, exc)
            cfg = {}

    host = os.environ.get("TEMPORAL_HOST", "127.0.0.1")
    port = int(os.environ.get("TEMPORAL_PORT", "7233"))
    namespace = os.environ.get("TEMPORAL_NAMESPACE") or cfg.get("temporal", {}).get("namespace", "default")
    queue = os.environ.get("TEMPORAL_QUEUE") or cfg.get("temporal", {}).get("queue", "daemon-queue")
    return {"host": host, "port": port, "namespace": namespace, "queue": queue}


class WebSocketHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


class _CompatMemory:
    def search_by_tags(self, tags: list[str], *, limit: int = 10, folio_id: str | None = None) -> list[dict[str, Any]]:
        del tags, limit, folio_id
        return []

    def add(self, *, content: str, tags: list[str] | None = None, folio_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        del content, tags, folio_id, metadata


class _CompatLore:
    def list_records(self, *, folio_id: str | None = None, writ_id: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        del folio_id, writ_id, limit
        return []


class _CompatInstinct:
    def __init__(self, psyche_dir: Path) -> None:
        self._versions_path = psyche_dir / "config_versions.jsonl"
        self._rations_path = psyche_dir / "rations_compat.json"

    def _load_versions(self) -> list[dict[str, Any]]:
        if not self._versions_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        for line in self._versions_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _save_versions(self, rows: list[dict[str, Any]]) -> None:
        self._versions_path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(f"{json.dumps(row, ensure_ascii=False)}\n" for row in rows)
        self._versions_path.write_text(text, encoding="utf-8")

    def _load_rations(self) -> dict[str, dict[str, Any]]:
        if not self._rations_path.exists():
            return {}
        try:
            data = json.loads(self._rations_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _save_rations(self, payload: dict[str, dict[str, Any]]) -> None:
        self._rations_path.parent.mkdir(parents=True, exist_ok=True)
        self._rations_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def record_config_version(self, target: str, payload: dict[str, Any], *, changed_by: str = "", reason: str = "") -> dict[str, Any]:
        rows = self._load_versions()
        target_rows = [row for row in rows if str(row.get("target") or "") == target]
        version = max((int(row.get("version") or 0) for row in target_rows), default=0) + 1
        row = {
            "target": target,
            "version": version,
            "value_json": json.dumps(payload, ensure_ascii=False),
            "changed_by": changed_by,
            "reason": reason,
            "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        rows.append(row)
        self._save_versions(rows)
        return row

    def versions(self, target: str, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = [row for row in self._load_versions() if str(row.get("target") or "") == target]
        rows.sort(key=lambda row: int(row.get("version") or 0), reverse=True)
        return rows[: max(1, limit)]

    def all_rations(self) -> list[dict[str, Any]]:
        payload = self._load_rations()
        return [{"resource_type": key, **value} for key, value in sorted(payload.items())]

    def get_ration(self, resource_type: str) -> dict[str, Any]:
        payload = self._load_rations()
        row = payload.get(resource_type)
        if not isinstance(row, dict):
            return {}
        return {"resource_type": resource_type, **row}

    def set_ration(self, resource_type: str, daily_limit: int, *, changed_by: str = "") -> dict[str, Any]:
        payload = self._load_rations()
        row = {
            "daily_limit": int(daily_limit),
            "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "changed_by": changed_by,
        }
        payload[resource_type] = row
        self._save_rations(payload)
        self.record_config_version(f"ration.{resource_type}", row, changed_by=changed_by, reason="set_ration")
        return {"resource_type": resource_type, **row}

    def rollback(self, target: str, version: int, *, changed_by: str = "") -> bool:
        row = next((item for item in self.versions(target, limit=500) if int(item.get("version") or 0) == int(version)), None)
        if not row:
            return False
        if target.startswith("ration."):
            resource_type = target.split(".", 1)[1]
            try:
                payload = json.loads(str(row.get("value_json") or "{}"))
            except Exception:
                return False
            if not isinstance(payload, dict):
                return False
            current = self._load_rations()
            payload["updated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            payload["changed_by"] = changed_by
            current[resource_type] = payload
            self._save_rations(current)
            self.record_config_version(target, payload, changed_by=changed_by, reason=f"rollback_to_v{version}")
            return True
        return False



def create_app() -> FastAPI:
    # Ensure runtime entrypoint can read .env without relying on shell exports.
    load_daemon_env(_daemon_home())
    home = _daemon_home()
    oc_home = _openclaw_home()
    state = home / "state"
    ledger = Ledger(state)

    # Initialize Psyche (new architecture: PsycheConfig + LedgerStats + InstinctEngine).
    psyche_dir = state / "psyche"
    psyche_dir.mkdir(parents=True, exist_ok=True)
    psyche_config = PsycheConfig(home / "psyche")
    ledger_stats = LedgerStats(psyche_dir / "ledger.db")
    instinct_engine = InstinctEngine(home / "psyche" / "instinct.md")
    memory = _CompatMemory()
    lore = _CompatLore()
    instinct = _CompatInstinct(psyche_dir)

    # Initialize infrastructure.
    cortex = Cortex(psyche_config)
    nerve = Nerve()
    trail = Trail(state / "trails")
    if not str(psyche_config.get_pref("eval_window_hours", "") or "").strip():
        psyche_config.set_pref("eval_window_hours", "48", source="system", changed_by="bootstrap")

    # Initialize Spine.
    registry_path = home / "config" / "spine_registry.json"
    canon = SpineCanon(registry_path)
    routines = SpineRoutines(
        psyche_config=psyche_config, ledger_stats=ledger_stats, instinct_engine=instinct_engine,
        cortex=cortex, nerve=nerve, trail=trail,
        daemon_home=home, openclaw_home=oc_home,
    )
    # Initialize Services.
    folio_writ = FolioWritManager(state_dir=state, nerve=nerve, ledger=ledger)
    will = Will(psyche_config, nerve, state, cortex=cortex, folio_writ_manager=folio_writ)
    cadence = Cadence(canon, routines, psyche_config, nerve, state, will=will)
    voice = VoiceService(psyche_config, oc_home, folio_writ_manager=folio_writ, cortex=cortex)
    reset_manager = SystemResetManager(home)
    ether = Ether(state, source="api")
    telemetry_dir = state / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    portal_events_path = telemetry_dir / "portal_events.jsonl"
    skill_proposals_path = state / "skill_evolution_proposals.json"
    skill_queue_path = state / "skill_evolution_queue.json"
    feedback_surveys_dir = state / "feedback_surveys"
    feedback_surveys_dir.mkdir(parents=True, exist_ok=True)
    model_policy_path = home / "config" / "model_policy.json"
    model_registry_path = home / "config" / "model_registry.json"
    app_started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    ws_hub = WebSocketHub()

    app = FastAPI(title="Daemon API", version="0.1.0")

    # ── Access token guard (Tailscale Funnel protection) ──────────────────
    _access_token = os.environ.get("DAEMON_ACCESS_TOKEN", "").strip()
    _TOKEN_COOKIE = "daemon_token"
    _LOGIN_HTML = """<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Daemon — Login</title>
<style>
:root{
  --bg:#faf9f7;
  --surface:#f0ece3;
  --border:#e2ddd5;
  --text:#1c1917;
  --muted:#78716c;
  --accent:#c96940;
  --error:#b91c1c;
}
*{box-sizing:border-box}
body{
  margin:0;
  min-height:100dvh;
  background:var(--bg);
  color:var(--text);
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
  display:flex;
  justify-content:center;
  align-items:flex-start;
  padding:clamp(36px,10vh,96px) 16px 24px;
}
form{
  width:min(420px,100%);
  display:flex;
  flex-direction:column;
  gap:12px;
  background:var(--surface);
  border:1px solid var(--border);
  border-radius:14px;
  padding:20px;
  box-shadow:0 10px 28px rgba(28,25,23,.06);
}
h2{
  margin:0;
  font-size:21px;
  letter-spacing:-.02em;
}
.sub{
  margin:0;
  color:var(--muted);
  font-size:13px;
  line-height:1.45;
}
input{
  width:100%;
  border:1px solid var(--border);
  border-radius:10px;
  background:var(--bg);
  color:var(--text);
  font-size:15px;
  padding:11px 12px;
  outline:none;
}
input:focus{
  border-color:var(--accent);
}
button{
  margin-top:2px;
  border:none;
  border-radius:10px;
  background:var(--accent);
  color:#fff;
  padding:11px 12px;
  font-size:14px;
  font-weight:600;
  cursor:pointer;
}
button:hover{opacity:.92}
p{
  margin:0;
  color:var(--error);
  font-size:13px;
  line-height:1.4;
}
</style></head>
<body><form method=post action=/_login>
<h2>Daemon</h2>
<p class=sub>Enter your access token to continue.</p>
{error}
<input type=password name=token placeholder="Access token" autofocus>
<button type=submit>Enter</button>
</form></body></html>"""

    @app.post("/_login", include_in_schema=False)
    async def _do_login(request: Request):
        from fastapi.responses import HTMLResponse, RedirectResponse
        if not _access_token:
            return RedirectResponse("/portal/", status_code=302)
        form = await request.form()
        submitted = str(form.get("token") or "").strip()
        if not secrets.compare_digest(submitted, _access_token):
            html = _LOGIN_HTML.replace("{error}", "<p>Token incorrect.</p>")
            return HTMLResponse(html, status_code=401)
        resp = RedirectResponse(str(request.query_params.get("next") or "/portal/"), status_code=302)
        resp.set_cookie(_TOKEN_COOKIE, _access_token, httponly=True, samesite="lax", max_age=60*60*24*30)
        return resp

    @app.middleware("http")
    async def _auth_middleware(request: Request, call_next):
        from fastapi.responses import HTMLResponse, RedirectResponse
        # Skip auth if no token configured or request is from localhost
        if not _access_token:
            return await call_next(request)
        client_host = request.client.host if request.client else "127.0.0.1"
        if client_host in ("127.0.0.1", "::1"):
            return await call_next(request)
        # Allow login endpoint through
        if request.url.path == "/_login":
            return await call_next(request)
        # Check cookie
        cookie_val = request.cookies.get(_TOKEN_COOKIE, "")
        if secrets.compare_digest(cookie_val, _access_token):
            return await call_next(request)
        # Show login page
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            html = _LOGIN_HTML.replace("{error}", "")
            return HTMLResponse(html, status_code=401)
        return HTMLResponse("Unauthorized", status_code=401)
    # ─────────────────────────────────────────────────────────────────────

    temporal_client: TemporalClient | None = None
    ether_task: asyncio.Task | None = None
    ether_running = True
    runtime_loop: asyncio.AbstractEventLoop | None = None

    async def _ensure_temporal_client(retries: int = 1, delay_s: float = 0.5) -> bool:
        nonlocal temporal_client
        if temporal_client is not None:
            return True
        tc = _temporal_config()
        attempts = max(1, int(retries))
        last_err: Exception | None = None
        for idx in range(attempts):
            try:
                temporal_client = await TemporalClient.connect(
                    host=tc["host"],
                    port=tc["port"],
                    namespace=tc["namespace"],
                    queue=tc["queue"],
                )
                will.set_temporal_client(temporal_client)
                logger.info(
                    "Temporal client connected host=%s port=%s namespace=%s queue=%s",
                    tc["host"], tc["port"], tc["namespace"], tc["queue"],
                )
                return True
            except Exception as exc:
                last_err = exc
                if idx < attempts - 1:
                    await asyncio.sleep(max(0.1, float(delay_s)))
        if last_err is not None:
            logger.error("Temporal client connection failed: %s", last_err)
        return False

    @app.on_event("startup")
    async def _startup():
        nonlocal ether_task, ether_running, runtime_loop
        runtime_loop = asyncio.get_running_loop()
        # Keep OpenClaw on daemon canonical topology (no legacy main default).
        norm = normalize_openclaw_config(oc_home)
        if norm.get("updated"):
            logger.info("OpenClaw config normalized on startup: %s", norm.get("changes"))
        if norm.get("warnings"):
            for warn in norm.get("warnings") or []:
                logger.warning("OpenClaw config warning: %s", warn)
        # Recover orphaned retinue instances from previous unclean shutdown.
        try:
            retinue = Retinue(home, oc_home)
            recovery = retinue.recover_on_startup()
            if recovery.get("count", 0) > 0:
                logger.info("Retinue recovery: %d instances recovered", recovery["count"])
        except Exception as exc:
            logger.warning("Retinue recovery failed: %s", exc)
        await _ensure_temporal_client(retries=20, delay_s=0.5)
        trigger_count = folio_writ.register_all_triggers()
        if trigger_count:
            logger.info("Registered %d active Writ triggers", trigger_count)
        _register_runtime_handlers()
        await cadence.start()
        ether_running = True
        ether_task = asyncio.create_task(_ether_loop())

    @app.on_event("shutdown")
    async def _shutdown():
        nonlocal ether_running, ether_task
        ether_running = False
        if ether_task:
            ether_task.cancel()
            try:
                await ether_task
            except asyncio.CancelledError:
                pass
        await cadence.stop()

    async def _ether_loop() -> None:
        while ether_running:
            try:
                events = await asyncio.to_thread(ether.consume, "api", 200)
                if events:
                    for evt in events:
                        payload = evt.get("payload") if isinstance(evt.get("payload"), dict) else {}
                        event_name = str(evt.get("event") or "")
                        if event_name in {
                            "deed_settling",
                            "deed_closed",
                            "deed_failed",
                            "deed_rework_exhausted",
                            "eval_expiring",
                            "ward_changed",
                            "folio_progress_update",
                            "folio_goal_candidate_completed",
                        }:
                            try:
                                await _notify_via_adapter(event_name, payload)
                            except Exception as exc:
                                logger.warning("Telegram notify error event=%s: %s", event_name, exc)
                        payload = {**payload, "_ether_event_id": evt.get("event_id"), "_ether_event": event_name}
                        nerve.emit(event_name, payload)
                        await asyncio.to_thread(
                            ether.acknowledge,
                            str(evt.get("event_id") or ""),
                            event_name,
                            payload,
                            "api",
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Ether loop error: %s", exc)
            await asyncio.sleep(2)

    def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _utc() -> str:
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _utc_from_ts(ts: float) -> str:
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts)))

    def _schedule_task(coro) -> None:
        if runtime_loop is None:
            return
        runtime_loop.call_soon_threadsafe(asyncio.create_task, coro)

    def _message_log_path(deed_id: str) -> Path:
        return state / "deeds" / deed_id / "messages.jsonl"

    def _append_deed_message(
        deed_id: str,
        *,
        role: str,
        content: str,
        event: str = "",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "deed_id": deed_id,
            "role": role,
            "content": content,
            "event": event,
            "created_utc": _utc(),
            "meta": meta or {},
        }
        ledger.append_jsonl(_message_log_path(deed_id), row)
        return row

    def _load_deed_messages(deed_id: str, limit: int = 200) -> list[dict]:
        return ledger.load_jsonl(_message_log_path(deed_id), max_items=max(1, min(limit, 1000)))

    async def _broadcast_event(event: str, payload: dict[str, Any]) -> None:
        await ws_hub.broadcast({"event": event, "payload": payload, "created_utc": _utc()})

    def _progress_text(event: str, payload: dict[str, Any]) -> str:
        move_label = str(payload.get("move_label") or payload.get("move_id") or "").strip()
        if event == "deed_progress":
            phase = str(payload.get("phase") or "").strip()
            if phase == "started":
                return f"开始处理：{move_label or '当前 Move'}"
            if phase == "waiting":
                return f"正在等待结果：{move_label or '当前 Move'}"
            if phase == "move_completed":
                return f"已完成：{move_label or '当前 Move'}"
            if phase == "degraded":
                return f"遇到异常，已降级处理：{move_label or '当前 Move'}"
        if event in {"deed_settling", "deed_closed"}:
            return str(payload.get("summary") or "任务已完成。")
        if event == "deed_failed":
            return f"任务失败：{str(payload.get('error') or payload.get('last_error') or '未知错误')[:180]}"
        if event == "folio_progress_update":
            summary = str(payload.get("summary") or "").strip()
            return summary or "卷中有新的推进。"
        return ""

    def _record_ws_message(event: str, payload: dict[str, Any]) -> None:
        deed_id = str(payload.get("deed_id") or "").strip()
        if not deed_id:
            return
        content = _progress_text(event, payload)
        if not content:
            return
        row = _append_deed_message(deed_id, role="assistant", content=content, event=event, meta=payload)
        _schedule_task(_broadcast_event("deed_message", row))

    def _audit_console(action: str, target: str, before: Any, after: Any) -> None:
        ledger.append_console_audit(
            {
                "action": action,
                "target": target,
                "before": before,
                "after": after,
                "actor": "console",
            }
        )

    def _log_portal_event(event: str, payload: dict[str, Any], request: Request | None = None) -> None:
        rec = {
            "event": event,
            "payload": payload,
            "source": "portal",
            "created_utc": _utc(),
        }
        if request is not None:
            rec["client"] = {
                "host": request.client.host if request.client else "",
                "ua": request.headers.get("user-agent", ""),
                "path": request.url.path,
            }
        try:
            _append_jsonl(portal_events_path, rec)
        except Exception as exc:
            logger.warning("Failed to write portal telemetry: %s", exc)

    def _read_json_list(path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
        return []

    def _deed_view(deed: dict) -> dict:
        out = dict(deed)
        plan = out.get("plan") if isinstance(out.get("plan"), dict) else {}
        brief = plan.get("brief") or {}
        deed_id = str(out.get("deed_id") or out.get("run_id") or "")
        deed_status = str(out.get("deed_status") or out.get("run_status") or "")
        deed_title = str(
            out.get("deed_title") or out.get("title")
            or out.get("run_title")
            or plan.get("deed_title") or plan.get("title") or plan.get("run_title")
            or brief.get("objective", "")
            or deed_id
        )
        phase = str(out.get("phase") or "").strip().lower()
        if phase not in {"running", "settling", "history"}:
            status_lower = deed_status.lower()
            if status_lower == "running":
                phase = "running"
            elif status_lower == "settling":
                phase = "settling"
            else:
                phase = "history"
        out.setdefault("deed_id", deed_id)
        if deed_status:
            out["deed_status"] = deed_status
        out["phase"] = phase
        out["deed_title"] = deed_title
        out["title"] = deed_title
        if plan and not isinstance(plan.get("plan_display"), dict):
            steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
            if steps:
                plan["plan_display"] = {
                    "mode": "slip",
                    "show_timeline": True,
                    "timeline": [
                        {
                            "id": str(step.get("id") or ""),
                            "agent": str(step.get("agent") or ""),
                            "label": str(step.get("instruction") or step.get("message") or "")[:80],
                        }
                        for step in steps
                        if isinstance(step, dict)
                    ],
                }
                out["plan"] = plan
        out.setdefault("global_score_components", plan.get("global_score_components") or {})
        out.setdefault("eval_window_hours", plan.get("eval_window_hours", 48))
        out.setdefault("exec_completed_utc", out.get("exec_completed_utc", ""))
        out.setdefault("eval_deadline_utc", out.get("eval_deadline_utc", ""))
        folio_id = str(out.get("folio_id") or plan.get("folio_id") or "")
        if folio_id:
            folio = folio_writ.get_folio(folio_id)
            if folio:
                out["group_label"] = str(folio.get("title") or deed_title)
        else:
            out.setdefault("group_label", "Independent")
        return out

    def _write_json_list(path: Path, items: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2))

    def _require_offering_root() -> Path:
        return resolve_offering_root(state)

    def _feedback_survey_path(deed_id: str) -> Path:
        return feedback_surveys_dir / f"{deed_id}.json"

    def _load_feedback_survey(deed_id: str) -> dict | None:
        path = _feedback_survey_path(deed_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _save_feedback_survey(deed_id: str, payload: dict) -> None:
        path = _feedback_survey_path(deed_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _feedback_history(survey: dict | None) -> list[dict]:
        if not isinstance(survey, dict):
            return []
        rows = survey.get("history")
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict)]

    def _feedback_state(deed_id: str) -> dict:
        survey = _load_feedback_survey(deed_id) or {}
        history = _feedback_history(survey)
        response = survey.get("response") if isinstance(survey.get("response"), dict) else {}
        return {
            "deed_id": str(survey.get("deed_id") or deed_id),
            "status": str(survey.get("status") or ""),
            "submitted_utc": str(survey.get("submitted_utc") or ""),
            "handled_channel": str(survey.get("handled_channel") or ""),
            "telegram_reminder_suppressed": bool(survey.get("telegram_reminder_suppressed", False)),
            "response": response,
            "history": history[-50:],
        }

    def _pending_feedback_surveys(limit: int = 100) -> list[dict]:
        rows: list[dict] = []
        for p in feedback_surveys_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if str(data.get("status") or "") != "pending":
                continue
            rows.append(data)
        rows.sort(key=lambda x: str(x.get("created_utc") or ""), reverse=True)
        return rows[: max(1, min(limit, 500))]

    def _offering_entry_for_deed(deed_id: str) -> dict | None:
        for entry in reversed(ledger.load_herald_log()):
            if str(entry.get("deed_id") or "") == str(deed_id or ""):
                return entry
        return None

    async def _notify_via_adapter(event: str, payload: dict) -> dict:
        adapter_url = os.environ.get("TELEGRAM_ADAPTER_URL", "http://127.0.0.1:8001").strip()
        if not adapter_url:
            return {"sent": 0, "skipped": True, "reason": "adapter_url_missing"}
        try:
            import httpx

            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.post(
                    f"{adapter_url}/notify",
                    json={"event": event, "payload": payload},
                )
            if resp.status_code >= 300:
                return {"sent": 0, "skipped": True, "reason": f"adapter_http_{resp.status_code}"}
            data = resp.json() if resp.content else {}
            if not isinstance(data, dict):
                data = {}
            if not data.get("ok"):
                return {"sent": 0, "skipped": True, "reason": str(data.get("error") or "adapter_rejected")}
            return {"sent": 1, "event": event}
        except Exception as exc:
            logger.warning("Telegram adapter notify failed event=%s: %s", event, exc)
            return {"sent": 0, "skipped": True, "reason": f"adapter_error:{str(exc)[:120]}"}

    def _render_template_value(value: Any, ctx: dict[str, Any]) -> Any:
        if isinstance(value, str):
            class _SafeDict(dict):
                def __missing__(self, key):
                    return "{" + key + "}"
            try:
                return value.format_map(_SafeDict(ctx))
            except Exception:
                return value
        if isinstance(value, list):
            return [_render_template_value(item, ctx) for item in value]
        if isinstance(value, dict):
            return {str(k): _render_template_value(v, ctx) for k, v in value.items()}
        return value

    def _build_writ_context(payload: dict[str, Any]) -> dict[str, Any]:
        writ_id = str(payload.get("writ_id") or "")
        folio_id = str(payload.get("folio_id") or "")
        brief_template = payload.get("brief_template") if isinstance(payload.get("brief_template"), dict) else {}
        trigger_payload = payload.get("trigger_payload") if isinstance(payload.get("trigger_payload"), dict) else {}
        trigger_utc = str(trigger_payload.get("tick_utc") or _utc())
        objective_text = str(brief_template.get("objective") or "")
        memory_hits = memory.search_by_tags(
            [f"folio_id:{folio_id}", f"writ_id:{writ_id}"],
            limit=3,
            folio_id=folio_id or None,
        )
        lore_hits = lore.list_records(folio_id=folio_id or None, writ_id=writ_id or None, limit=3)
        recent_deeds = folio_writ.recent_deed_summaries(writ_id, limit=3) if writ_id else []
        folio = folio_writ.get_folio(folio_id) if folio_id else None
        return {
            "date": trigger_utc[:10],
            "tick_utc": trigger_utc,
            "trigger_event": str(payload.get("trigger_event") or ""),
            "folio_title": str((folio or {}).get("title") or ""),
            "recent_titles": " / ".join(str(row.get("title") or "") for row in recent_deeds if row.get("title")),
            "recent_summary": "\n".join(
                f"- {row.get('title') or row.get('deed_id')}: {row.get('status') or ''}"
                for row in recent_deeds
            ),
            "memory_summary": "\n".join(str(row.get("content") or "")[:240] for row in memory_hits),
            "lore_summary": "\n".join(str(row.get("objective_text") or "")[:160] for row in lore_hits),
            "writ_id": writ_id,
            "folio_id": folio_id,
            "objective": objective_text,
        }

    async def _consume_writ_trigger(payload: dict[str, Any]) -> None:
        action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
        action_type = str(action.get("type") or "spawn_deed").strip()
        writ_id = str(payload.get("writ_id") or "")
        folio_id = str(payload.get("folio_id") or "")

        try:
            if action_type == "spawn_deed":
                await _writ_action_spawn_deed(payload, action, writ_id, folio_id)
            elif action_type == "create_draft":
                _writ_action_create_draft(action, writ_id, folio_id)
            elif action_type == "crystallize_draft":
                _writ_action_crystallize_draft(action, writ_id)
            elif action_type == "advance_slip":
                _writ_action_advance_slip(action, writ_id)
            elif action_type == "park_slip":
                _writ_action_update_slip_status(action, {"status": "active", "sub_status": "parked"}, writ_id)
            elif action_type == "archive_slip":
                _writ_action_update_slip_status(action, {"status": "archived"}, writ_id)
            elif action_type == "attach_slip_to_folio":
                _writ_action_attach_slip(action, writ_id)
            elif action_type == "create_folio":
                _writ_action_create_folio(action, writ_id)
            else:
                logger.warning("Writ %s: unknown action type %r", writ_id, action_type)
        except Exception as exc:
            logger.warning("Writ %s action %s failed: %s", writ_id, action_type, exc)

    async def _writ_action_spawn_deed(payload: dict, action: dict, writ_id: str, folio_id: str) -> None:
        brief_template = action.get("brief_template") if isinstance(action.get("brief_template"), dict) else (
            payload.get("brief_template") if isinstance(payload.get("brief_template"), dict) else {}
        )
        ctx = _build_writ_context(payload)
        rendered = _render_template_value(brief_template, ctx)
        objective = str(rendered.get("objective") or brief_template.get("objective") or "").strip()
        if not objective:
            objective = f"Writ {writ_id}"
        slip_id = str(action.get("slip_id") or payload.get("slip_id") or "")
        plan = {
            "brief": {
                "objective": objective,
                "language": str(rendered.get("language") or "bilingual"),
                "format": str(rendered.get("format") or "markdown"),
                "depth": str(rendered.get("depth") or "study"),
                "dag_budget": int(rendered.get("dag_budget") or SINGLE_SLIP_DEFAULTS["dag_budget"]),
                "fit_confidence": str(rendered.get("fit_confidence") or "medium"),
                "references": rendered.get("references") if isinstance(rendered.get("references"), list) else [],
                "quality_hints": rendered.get("quality_hints") if isinstance(rendered.get("quality_hints"), list) else [],
            },
            "moves": rendered.get("moves") if isinstance(rendered.get("moves"), list) else [
                {"id": "scout_auto", "agent": "scout", "instruction": objective},
                {"id": "sage_auto", "agent": "sage", "depends_on": ["scout_auto"], "instruction": f"Analyze and synthesize: {objective}"},
                {"id": "scribe_auto", "agent": "scribe", "depends_on": ["sage_auto"], "instruction": f"Write the final offering: {objective}"},
            ],
            "metadata": {
                "source": "writ_trigger",
                "writ_id": writ_id,
                "folio_id": folio_id,
                "slip_id": slip_id,
                "trigger_event": str(payload.get("trigger_event") or ""),
            },
        }
        if slip_id:
            plan["slip_id"] = slip_id
        result = await will.submit(plan)
        if result.get("ok") and result.get("deed_id"):
            folio_writ.record_writ_triggered(writ_id, str(result.get("deed_id") or ""))
        else:
            logger.warning("Writ spawn_deed failed for %s: %s", writ_id, result)

    def _writ_action_create_draft(action: dict, writ_id: str, folio_id: str) -> None:
        draft = folio_writ.create_draft(
            source="writ",
            folio_id=folio_id or str(action.get("folio_id") or ""),
            intent_snapshot=str(action.get("intent") or action.get("objective") or ""),
        )
        folio_writ.record_writ_triggered(writ_id, str(draft.get("draft_id") or ""))

    def _writ_action_crystallize_draft(action: dict, writ_id: str) -> None:
        draft_id = str(action.get("draft_id") or "")
        if not draft_id:
            logger.warning("Writ %s crystallize_draft: missing draft_id", writ_id)
            return
        draft = folio_writ.get_draft(draft_id)
        if not draft:
            logger.warning("Writ %s crystallize_draft: draft %s not found", writ_id, draft_id)
            return
        candidate_brief = draft.get("candidate_brief") if isinstance(draft.get("candidate_brief"), dict) else {}
        candidate_design = draft.get("candidate_design") if isinstance(draft.get("candidate_design"), dict) else {}
        result = folio_writ.crystallize_draft(
            draft_id,
            title=str(action.get("title") or draft.get("intent_snapshot") or ""),
            objective=str(draft.get("intent_snapshot") or ""),
            brief=candidate_brief,
            design=candidate_design,
            folio_id=str(action.get("folio_id") or draft.get("folio_id") or "") or None,
            standing=bool(action.get("standing") or candidate_brief.get("standing")),
        )
        if result:
            folio_writ.record_writ_triggered(writ_id, str(result.get("slip_id") or draft_id))

    def _writ_action_advance_slip(action: dict, writ_id: str) -> None:
        slip_id = str(action.get("slip_id") or "")
        new_status = str(action.get("status") or "active")
        if not slip_id:
            logger.warning("Writ %s advance_slip: missing slip_id", writ_id)
            return
        folio_writ.update_slip(slip_id, {"status": new_status})
        folio_writ.record_writ_triggered(writ_id, slip_id)

    def _writ_action_update_slip_status(action: dict, updates: dict, writ_id: str) -> None:
        slip_id = str(action.get("slip_id") or "")
        if not slip_id:
            logger.warning("Writ %s update_slip: missing slip_id", writ_id)
            return
        folio_writ.update_slip(slip_id, updates)
        folio_writ.record_writ_triggered(writ_id, slip_id)

    def _writ_action_attach_slip(action: dict, writ_id: str) -> None:
        slip_id = str(action.get("slip_id") or "")
        target_folio_id = str(action.get("folio_id") or "")
        if not slip_id or not target_folio_id:
            logger.warning("Writ %s attach_slip: missing slip_id or folio_id", writ_id)
            return
        folio_writ.attach_slip_to_folio(slip_id, target_folio_id)
        folio_writ.record_writ_triggered(writ_id, slip_id)

    def _writ_action_create_folio(action: dict, writ_id: str) -> None:
        title = str(action.get("title") or "自动开卷")
        summary = str(action.get("summary") or "")
        result = folio_writ.create_folio(title=title, summary=summary)
        folio_writ.record_writ_triggered(writ_id, str(result.get("folio_id") or ""))

    def _register_runtime_handlers() -> None:
        ws_events = {
            "deed_settling",
            "deed_closed",
            "deed_failed",
            "deed_progress",
            "deed_message",
            "ward_changed",
            "eval_expiring",
            "folio_progress_update",
            "folio_goal_candidate_completed",
        }

        def _make_ws_handler(event_name: str):
            def _handler(payload: dict) -> None:
                row = payload if isinstance(payload, dict) else {}
                _schedule_task(_broadcast_event(event_name, row))
                _record_ws_message(event_name, row)
            return _handler

        for event_name in ws_events:
            nerve.on(event_name, _make_ws_handler(event_name))

        def _writ_handler(payload: dict) -> None:
            _schedule_task(_consume_writ_trigger(payload if isinstance(payload, dict) else {}))

        nerve.on("writ_trigger_ready", _writ_handler)

        def _deed_submitted_handler(payload: dict) -> None:
            # Refresh Psyche snapshots so retinue pool instances get fresh memory.
            try:
                cadence.trigger("spine.relay", payload if isinstance(payload, dict) else {})
            except Exception as exc:
                logger.warning("relay trigger on deed_submitted failed: %s", exc)

        nerve.on("deed_submitted", _deed_submitted_handler)

    def _proposal_id(item: dict) -> str:
        raw = f"{item.get('skill','')}|{item.get('proposed_change','')}|{item.get('evidence','')}"
        return "sev_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _proposal_type(item: dict) -> str:
        if str(item.get("config_target") or "").strip() or isinstance(item.get("config_payload"), dict):
            return "config"
        skill = str(item.get("skill") or "").lower()
        change = str(item.get("proposed_change") or "").lower()
        evidence = str(item.get("evidence") or "").lower()
        merged = " ".join([skill, change, evidence])
        if ".py" in merged or "python" in merged:
            return "python"
        if "config/" in merged or ".json" in merged:
            return "config"
        return "skill"

    def _sync_instinct_provider_rations_from_policy(policy: dict, *, overwrite: bool) -> dict:
        """Sync model_policy budget_limits into Instinct provider rations."""
        limits = policy.get("budget_limits") if isinstance(policy.get("budget_limits"), dict) else {}
        touched: list[dict] = []
        for key, raw in limits.items():
            if not str(key).endswith("_tokens_per_day"):
                continue
            provider = str(key).replace("_tokens_per_day", "").strip()
            if not provider:
                continue
            resource_type = f"{provider}_tokens"
            try:
                daily_limit = float(raw)
            except (TypeError, ValueError):
                continue
            if daily_limit <= 0:
                continue
            current = instinct.get_ration(resource_type)
            if current and not overwrite:
                try:
                    if float(current.get("daily_limit") or 0) >= daily_limit:
                        continue
                except (TypeError, ValueError):
                    pass
            instinct.set_ration(resource_type, daily_limit, changed_by="model_policy")
            touched.append({"resource_type": resource_type, "daily_limit": daily_limit})
        if touched:
            nerve.emit("psyche_updated", {"psyche": "instinct", "key": "ration_limits_from_model_policy", "count": len(touched)})
        return {"updated": touched}

    def _model_target_spec(target: str) -> tuple[str, Path]:
        t = str(target or "").strip().lower()
        if t in {"model-policy", "model_policy"}:
            return "model_policy", model_policy_path
        if t in {"registry", "model-registry", "model_registry"}:
            return "model_registry", model_registry_path
        raise ValueError(f"unknown_model_target:{target}")

    def _model_registry_aliases(payload: dict) -> set[str]:
        models = payload.get("models") if isinstance(payload.get("models"), list) else []
        aliases: set[str] = set()
        for row in models:
            if not isinstance(row, dict):
                continue
            alias = str(row.get("alias") or "").strip()
            if alias:
                aliases.add(alias)
        return aliases

    def _validate_model_registry(payload: dict) -> None:
        models = payload.get("models") if isinstance(payload.get("models"), list) else None
        if models is None:
            raise ValueError("model_registry.models must be a list")
        if not models:
            raise ValueError("model_registry.models must not be empty")
        aliases: set[str] = set()
        for i, row in enumerate(models):
            if not isinstance(row, dict):
                raise ValueError(f"model_registry.models[{i}] must be an object")
            alias = str(row.get("alias") or "").strip()
            provider = str(row.get("provider") or "").strip()
            model_id = str(row.get("model_id") or "").strip()
            if not alias:
                raise ValueError(f"model_registry.models[{i}].alias is required")
            if alias in aliases:
                raise ValueError(f"model_registry duplicate alias: {alias}")
            aliases.add(alias)
            if not provider:
                raise ValueError(f"model_registry.models[{i}].provider is required")
            if not model_id:
                raise ValueError(f"model_registry.models[{i}].model_id is required")

    def _validate_model_policy(payload: dict, aliases: set[str]) -> None:
        if not aliases:
            raise ValueError("model_registry_aliases_empty")
        default_alias = str(payload.get("default_alias") or "").strip()
        if default_alias and default_alias not in aliases:
            raise ValueError(f"model_policy.default_alias not found in registry: {default_alias}")
        agent_model_map = payload.get("agent_model_map") if isinstance(payload.get("agent_model_map"), dict) else {}
        for agent, alias in agent_model_map.items():
            if str(agent).startswith("_"):
                continue
            alias = str(alias or "").strip()
            if alias and alias not in aliases:
                raise ValueError(f"model_policy.agent_model_map[{agent}] alias not found: {alias}")

    def _sync_skill_proposals() -> list[dict]:
        source = _read_json_list(skill_proposals_path)
        queue = _read_json_list(skill_queue_path)
        by_id = {str(item.get("proposal_id") or ""): item for item in queue}

        changed = False
        for row in source:
            pid = _proposal_id(row)
            if pid in by_id:
                continue
            by_id[pid] = {
                "proposal_id": pid,
                "skill": str(row.get("skill") or ""),
                "proposed_change": str(row.get("proposed_change") or ""),
                "evidence": str(row.get("evidence") or ""),
                "proposal_type": _proposal_type(row),
                "config_target": str(row.get("config_target") or ""),
                "config_payload": row.get("config_payload") if isinstance(row.get("config_payload"), dict) else None,
                "status": "pending",
                "created_utc": _utc(),
                "reviewed_utc": "",
                "reviewed_by": "",
                "review_note": "",
                "applied_utc": "",
                "apply_error": "",
            }
            changed = True

        merged = list(by_id.values())
        merged.sort(key=lambda x: x.get("created_utc", ""), reverse=True)
        if changed or not skill_queue_path.exists():
            _write_json_list(skill_queue_path, merged)
        return merged

    def _find_skill_files(skill_name: str) -> list[Path]:
        if not skill_name.strip():
            return []
        root = oc_home / "workspace"
        if not root.exists():
            return []
        return sorted(root.glob(f"*/skills/{skill_name}/SKILL.md"))

    def _apply_skill_proposal(proposal: dict) -> tuple[bool, str]:
        pid = str(proposal.get("proposal_id") or "")
        skill_name = str(proposal.get("skill") or "").strip()
        change = str(proposal.get("proposed_change") or "").strip()
        evidence = str(proposal.get("evidence") or "").strip()
        files = _find_skill_files(skill_name)
        if not files:
            return False, f"skill_not_found:{skill_name}"
        if len(files) > 1:
            return False, f"skill_ambiguous:{skill_name}"
        skill_path = files[0]
        try:
            content = skill_path.read_text(encoding="utf-8")
        except Exception as exc:
            return False, f"read_failed:{exc}"

        marker = f"<!-- {pid} -->"
        if marker in content:
            return True, "already_applied"

        block = (
            "\n\n## Evolution Notes\n"
            f"{marker}\n"
            f"- Proposal: {pid}\n"
            f"- Applied UTC: {_utc()}\n"
            f"- Change: {change}\n"
            f"- Evidence: {evidence}\n"
        )
        try:
            skill_path.write_text(content.rstrip() + block + "\n", encoding="utf-8")
        except Exception as exc:
            return False, f"write_failed:{exc}"
        return True, ""

    def _sandbox_ward_open() -> bool:
        v = str(instinct.get_pref("skill_evolution.sandbox_ward", "open") or "open").strip().lower()
        return v in {"1", "true", "open", "on", "enabled"}

    def _extract_json_payload(text: str) -> dict | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            pass
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(raw[start:end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _apply_config_proposal(proposal: dict) -> tuple[bool, str]:
        target = str(proposal.get("config_target") or proposal.get("skill") or "").strip()
        payload = proposal.get("config_payload")
        if not isinstance(payload, dict):
            payload = _extract_json_payload(str(proposal.get("proposed_change") or ""))
        if not isinstance(payload, dict):
            return False, "config_payload_missing_or_invalid"

        target_norm = target.lower()
        try:
            if target_norm in {"model_policy", "model-policy"}:
                aliases = _model_registry_aliases(json.loads(model_registry_path.read_text(encoding="utf-8")) if model_registry_path.exists() else {})
                _validate_model_policy(payload, aliases)
                payload["_updated"] = _utc()[:10]
                model_policy_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                instinct.record_config_version("model_policy", payload, changed_by="skill_evolution", reason="auto_adopt_config_proposal")
                nerve.emit("psyche_updated", {"psyche": "model_policy", "path": str(model_policy_path)})
                return True, ""
            if target_norm in {"model_registry", "registry", "model-registry"}:
                _validate_model_registry(payload)
                payload["_updated"] = _utc()[:10]
                model_registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                instinct.record_config_version("model_registry", payload, changed_by="skill_evolution", reason="auto_adopt_config_proposal")
                nerve.emit("psyche_updated", {"psyche": "model_registry", "path": str(model_registry_path)})
                return True, ""
            return False, f"unknown_config_target:{target}"
        except Exception as exc:
            return False, f"config_apply_failed:{str(exc)[:300]}"

    def _apply_evolution_proposal(proposal: dict) -> tuple[bool, str]:
        proposal_type = str(proposal.get("proposal_type") or "skill")
        if proposal_type == "config":
            return _apply_config_proposal(proposal)
        return _apply_skill_proposal(proposal)

    register_basic_routes(
        app,
        app_started_utc=app_started_utc,
        ensure_temporal_client=_ensure_temporal_client,
        get_temporal_client=lambda: temporal_client,
        ledger=ledger,
        will=will,
        cortex=cortex,
        model_policy_path=model_policy_path,
        model_registry_path=model_registry_path,
        openclaw_home=oc_home,
        validate_model_registry=_validate_model_registry,
        deed_view=_deed_view,
        log_portal_event=_log_portal_event,
        require_offering_root=_require_offering_root,
        memory=memory,
        lore=lore,
        instinct=instinct,
        folio_writ=folio_writ,
        append_deed_message=_append_deed_message,
        load_deed_messages=_load_deed_messages,
        schedule_broadcast=lambda event, payload: _schedule_task(_broadcast_event(event, payload)),
    )

    def _require_localhost(request: Request) -> str:
        host = request.client.host if request.client else ""
        if not host or (host not in {"127.0.0.1", "::1", "localhost"} and not host.startswith("127.")):
            raise HTTPException(status_code=403, detail="localhost_only")
        return host

    register_system_routes(
        app,
        require_localhost=_require_localhost,
        reset_manager=reset_manager,
        log_portal_event=_log_portal_event,
        state_dir=state,
    )

    register_submit_route(
        app,
        ensure_temporal_client=_ensure_temporal_client,
        will=will,
        log_portal_event=_log_portal_event,
    )

    register_chat_routes(app, voice=voice, log_portal_event=_log_portal_event)
    register_folio_writ_routes(app, folio_writ)

    route_ctx = SimpleNamespace(
        state=state,
        ledger=ledger,
        folio_writ=folio_writ,
        will=will,
        trail=trail,
        cadence=cadence,
        canon=canon,
        nerve=nerve,
        cortex=cortex,
        instinct=instinct,
        psyche_config=psyche_config,
        ledger_stats=ledger_stats,
        oc_home=oc_home,
        logger=logger,
        model_policy_path=model_policy_path,
        model_registry_path=model_registry_path,
        lexicon_path=home / "config" / "lexicon.json",
        utc=_utc,
        utc_from_ts=_utc_from_ts,
        deed_view=_deed_view,
        log_portal_event=_log_portal_event,
        append_deed_message=_append_deed_message,
        load_deed_messages=_load_deed_messages,
        feedback_state=_feedback_state,
        submit_feedback_internal=lambda *args, **kwargs: _submit_feedback_internal(*args, **kwargs),
        require_offering_root=_require_offering_root,
        offering_entry_for_deed=_offering_entry_for_deed,
        ensure_temporal_client=_ensure_temporal_client,
        get_temporal_client=lambda: temporal_client,
        audit_console=_audit_console,
        sync_skill_proposals=_sync_skill_proposals,
        write_json_list=_write_json_list,
        skill_queue_path=skill_queue_path,
        sandbox_ward_open=_sandbox_ward_open,
        apply_evolution_proposal=_apply_evolution_proposal,
        validate_model_policy=_validate_model_policy,
        validate_model_registry=_validate_model_registry,
        model_registry_aliases=_model_registry_aliases,
        sync_instinct_provider_rations_from_policy=_sync_instinct_provider_rations_from_policy,
    )
    register_portal_shell_routes(app, ctx=route_ctx)
    register_console_runtime_routes(app, ctx=route_ctx)
    register_console_admin_routes(app, ctx=route_ctx)
    register_console_observe_routes(app, ctx=route_ctx)
    register_console_agents_skill_routes(app, ctx=route_ctx)
    register_console_rations_routes(app, ctx=route_ctx)
    register_console_psyche_routes(app, ctx=route_ctx)
    register_console_spine_routes(app, ctx=route_ctx)

    @app.websocket("/ws")
    async def websocket_events(ws: WebSocket):
        await ws_hub.connect(ws)
        try:
            await ws.send_json({"event": "connected", "payload": {"app_started_utc": app_started_utc}, "created_utc": _utc()})
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive_text(), timeout=20)
                    if msg == "ping":
                        await ws.send_json({"event": "pong", "payload": {}, "created_utc": _utc()})
                except asyncio.TimeoutError:
                    await ws.send_json({"event": "ping", "payload": {}, "created_utc": _utc()})
        except WebSocketDisconnect:
            pass
        finally:
            ws_hub.disconnect(ws)

    # ── User feedback (Portal) ────────────────────────────────────────────────

    async def _submit_feedback_internal(deed_id: str, body: dict, request: Request | None = None) -> dict:
        source = str(body.get("source") or "portal")
        fb_type = str(body.get("type") or "quick").strip().lower()
        if fb_type not in {"quick", "deep", "append"}:
            fb_type = "quick"
        comment = str(body.get("comment") or "")[:1000].strip()
        aspects = body.get("aspects") if isinstance(body.get("aspects"), dict) else {}
        answers = body.get("answers") if isinstance(body.get("answers"), dict) else {}
        rating_raw = body.get("rating")
        rating: int | None = None
        if rating_raw is not None and str(rating_raw).strip() != "":
            try:
                rating = int(rating_raw)
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail="rating must be an integer 1-5")
            if not (1 <= rating <= 5):
                raise HTTPException(status_code=400, detail="rating must be 1-5")

        is_append = fb_type == "append"
        if is_append and not comment:
            raise HTTPException(status_code=400, detail="append_comment_required")
        if not is_append:
            has_partial = bool(comment or aspects or answers)
            if fb_type == "quick" and rating is None and not has_partial:
                raise HTTPException(status_code=400, detail="quick_feedback_requires_rating")
            if fb_type == "deep" and rating is None and not has_partial:
                raise HTTPException(status_code=400, detail="deep_feedback_requires_comment_or_rating")

        # Find deed record to derive slip-level feedback hints.
        deed_record = ledger.get_deed(deed_id)

        slip_id = ""
        if deed_record:
            plan = deed_record.get("plan") if isinstance(deed_record.get("plan"), dict) else {}
            metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
            slip_id = str(deed_record.get("slip_id") or metadata.get("slip_id") or plan.get("slip_id") or "")

        survey = _load_feedback_survey(deed_id) or {"deed_id": deed_id}
        prev_response = survey.get("response") if isinstance(survey.get("response"), dict) else {}
        prev_rating = prev_response.get("rating")
        first_scored_feedback = bool(rating is not None and prev_rating in (None, ""))

        prev_score: float | None = None
        try:
            if prev_response.get("score") is not None and str(prev_response.get("score")).strip() != "":
                prev_score = float(prev_response.get("score"))
        except (TypeError, ValueError):
            prev_score = None
        score: float | None = float(rating / 5.0) if rating is not None else prev_score
        main_rating: int | None = rating
        if main_rating is None and prev_rating is not None and str(prev_rating).strip() != "":
            try:
                main_rating = int(prev_rating)
            except (TypeError, ValueError):
                main_rating = None

        # Primary score feedback updates lore exactly once per deed.
        if first_scored_feedback:
            try:
                lore.update_feedback(
                    deed_id=deed_id,
                    user_feedback={
                        "rating": rating,
                        "score": score,
                        "comment": comment,
                        "aspects": aspects,
                        "source": "user_feedback",
                        "feedback_type": fb_type,
                    },
                )
            except Exception as exc:
                logger.warning("Failed to update lore feedback for %s: %s", deed_id, exc)

        if first_scored_feedback:
            summary_zh = (
                f"签札用户反馈：rating={rating}/5；comment={comment or '无'}；"
                f"aspects={json.dumps(aspects, ensure_ascii=False)}"
            )
            summary_en = (
                f"Slip feedback: rating={rating}/5; comment={comment or 'n/a'}; "
                f"aspects={json.dumps(aspects, ensure_ascii=False)}"
            )
            try:
                memory.add(
                    content=f"{summary_zh}\n\n{summary_en}",
                    tags=[
                        "domain:user_feedback",
                        "tier:deep",
                        "source_type:human",
                        "source_agent:user",
                        f"deed_id:{deed_id}",
                        f"slip_id:{slip_id}",
                    ],
                    source=f"{source}.feedback",
                )
            except Exception as exc:
                logger.warning("Failed to store slip feedback into memory: %s", exc)

        # Persist feedback aspects as Instinct prefs for the learning system.
        if aspects:
            for aspect_key, aspect_val in aspects.items():
                try:
                    v = float(aspect_val)
                    if 0.0 <= v <= 1.0:
                        instinct.set_pref(
                            f"feedback.slip.{aspect_key}",
                            str(round(v, 4)),
                            source="user_feedback",
                            changed_by="user",
                        )
                except (TypeError, ValueError):
                    pass

        now = _utc()
        history = _feedback_history(survey)
        history.append(
            {
                "type": "append" if is_append else fb_type,
                "source": source,
                "rating": rating,
                "comment": comment,
                "aspects": aspects if isinstance(aspects, dict) else {},
                "answers": answers if isinstance(answers, dict) else {},
                "created_utc": now,
            }
        )
        survey["history"] = history[-200:]
        if not is_append:
            survey["response"] = {
                "rating": main_rating,
                "score": score,
                "comment": comment,
                "aspects": aspects if isinstance(aspects, dict) else {},
                "answers": answers if isinstance(answers, dict) else {},
                "source": source,
                "type": fb_type,
            }
        survey["status"] = "submitted"
        survey["submitted_utc"] = now
        survey["deed_id"] = str(survey.get("deed_id") or deed_id)
        if source == "portal":
            survey["handled_channel"] = "portal"
            survey["telegram_reminder_suppressed"] = True
        _save_feedback_survey(deed_id, survey)

        # Write to feedback JSONL.
        feedback_path = telemetry_dir / "offering_feedback.jsonl"
        _append_jsonl(
            feedback_path,
            {
                "deed_id": deed_id,
                "type": "append" if is_append else fb_type,
                "source": source,
                "rating": rating,
                "score": score,
                "comment": comment,
                "aspects": aspects,
                "answers": answers,
                "slip_id": slip_id,
                "created_utc": now,
            },
        )

        # Eval window closes immediately once any feedback is submitted.
        if not is_append and deed_record:
            def _close_eval(deeds: list[dict]) -> None:
                for row in deeds:
                    if str(row.get("deed_id") or "") != deed_id:
                        continue
                    status = str(row.get("deed_status") or "").strip().lower()
                    if status == "settling":
                        row["deed_status"] = "closed"
                        row["deed_sub_status"] = "succeeded"
                        row["phase"] = "history"
                        row["updated_utc"] = now
                        row["eval_submitted_utc"] = now
                        row["feedback_expired"] = False
                        row.pop("eval_deadline_utc", None)
                    break

            ledger.mutate_deeds(_close_eval)
            nerve.emit("deed_closed", {"deed_id": deed_id, "sub_status": "succeeded", "source": "feedback_submitted"})

        # Flow feedback to Writ trigger statistics (P5: feedback→Writ learning).
        if first_scored_feedback and deed_record:
            plan = deed_record.get("plan") if isinstance(deed_record.get("plan"), dict) else {}
            metadata_fb = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
            writ_id_fb = str(deed_record.get("writ_id") or metadata_fb.get("writ_id") or "")
            if writ_id_fb:
                try:
                    writ = folio_writ.get_writ(writ_id_fb)
                    if writ:
                        stats = writ.get("trigger_stats") if isinstance(writ.get("trigger_stats"), dict) else {}
                        stats["total_triggered"] = int(stats.get("total_triggered") or 0) + 0  # already counted
                        stats["total_feedback"] = int(stats.get("total_feedback") or 0) + 1
                        stats["avg_rating"] = round(
                            (float(stats.get("avg_rating") or 0) * max(0, int(stats.get("total_feedback") or 1) - 1) + (rating or 3))
                            / max(1, int(stats.get("total_feedback") or 1)),
                            2,
                        )
                        if score is not None and score < 0.4:
                            stats["misfire_count"] = int(stats.get("misfire_count") or 0) + 1
                        folio_writ.update_writ(writ_id_fb, {"trigger_stats": stats})
                except Exception as exc:
                    logger.warning("Failed to update Writ trigger stats for %s: %s", writ_id_fb, exc)

        if rating is not None:
            nerve.emit("user_feedback_received", {"deed_id": deed_id, "rating": rating, "score": score})
        nerve.emit(
            "deed_feedback_submitted" if not is_append else "deed_feedback_appended",
            {
                "deed_id": deed_id,
                "source": source,
                "type": "append" if is_append else fb_type,
                "rating": rating,
            },
        )
        if request is not None:
            _log_portal_event(
                "feedback_submitted" if not is_append else "feedback_appended",
                {"deed_id": deed_id, "rating": rating, "source": source},
                request,
            )
        return {
            "ok": True,
            "deed_id": deed_id,
            "score": score,
            "status": str(survey.get("status") or ""),
            "type": "append" if is_append else fb_type,
            "history_count": len(survey.get("history") or []),
        }

    feedback_ctx = type("FeedbackRouteContext", (), {})()
    feedback_ctx.pending_feedback_surveys = _pending_feedback_surveys
    feedback_ctx.feedback_state = _feedback_state
    feedback_ctx.submit_feedback_internal = _submit_feedback_internal
    register_feedback_routes(app, ctx=feedback_ctx)

    # ── Startup sync (model policy -> Instinct provider rations) ────────────

    if model_policy_path.exists():
        try:
            policy = json.loads(model_policy_path.read_text(encoding="utf-8"))
            if isinstance(policy, dict):
                _sync_instinct_provider_rations_from_policy(policy, overwrite=False)
        except Exception as exc:
            logger.warning("Failed to sync provider rations from model policy on startup: %s", exc)

    # ── Serve static interfaces ────────────────────────────────────────────────

    @app.get("/", include_in_schema=False)
    async def _root_redirect():
        from fastapi.responses import RedirectResponse
        return RedirectResponse("/portal/", status_code=302)

    portal_dir = home / "interfaces" / "portal"
    portal_build_dir = portal_dir / "compiled"
    console_dir = home / "interfaces" / "console"
    if portal_dir.exists():
        from starlette.responses import FileResponse as _FileResponse

        _portal_static_dir = portal_build_dir if portal_build_dir.exists() else portal_dir
        _portal_index = _portal_static_dir / "index.html"

        @app.get("/portal", include_in_schema=False)
        @app.get("/portal/", include_in_schema=False)
        async def _serve_portal_index():
            return _FileResponse(_portal_index, media_type="text/html")

        @app.get("/portal/folios/{folio_slug}", include_in_schema=False)
        async def _serve_portal_folio(folio_slug: str):
            return _FileResponse(_portal_index, media_type="text/html")

        @app.get("/portal/slips/{slip_slug}", include_in_schema=False)
        async def _serve_portal_slip(slip_slug: str):
            return _FileResponse(_portal_index, media_type="text/html")

        @app.get("/portal/slips/{slip_slug}/deeds/{deed_id}", include_in_schema=False)
        async def _serve_portal_slip_deed(slip_slug: str, deed_id: str):
            return _FileResponse(_portal_index, media_type="text/html")

        app.mount("/_portal", StaticFiles(directory=_portal_static_dir), name="portal_static")
    if console_dir.exists():
        from starlette.responses import FileResponse as _FileResponse

        _console_index = console_dir / "index.html"

        @app.get("/console", include_in_schema=False)
        @app.get("/console/", include_in_schema=False)
        async def _serve_console_index():
            return _FileResponse(_console_index, media_type="text/html")

        app.mount("/_console", StaticFiles(directory=console_dir), name="console_static")

    return app
