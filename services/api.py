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
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from psyche.memory import MemoryPsyche
from psyche.lore import LorePsyche
from psyche.instinct import InstinctPsyche
from spine.nerve import Nerve
from spine.trail import Trail
from spine.canon import SpineCanon
from spine.routines import SpineRoutines
from runtime.retinue import Retinue
from runtime.cortex import Cortex
from runtime.ether import Ether
from runtime.temporal import TemporalClient
from services.will import Will
from services.voice import VoiceService
from services.api_routes.basic import register_basic_routes
from services.api_routes.endeavors import register_endeavor_routes
from services.api_routes.chat import register_chat_routes
from services.api_routes.console_agents_skill import register_console_agents_skill_routes
from services.api_routes.console_observe import register_console_observe_routes
from services.api_routes.console_norm import register_console_norm_routes
from services.api_routes.console_admin import register_console_admin_routes
from services.api_routes.console_spine_psyche import register_console_spine_psyche_routes
from services.api_routes.feedback import register_feedback_routes
from services.api_routes.submit import register_submit_route
from services.api_routes.system import register_system_routes
from services.cadence import Cadence
from services.ledger import Ledger
from services.dominion_writ import DominionWritManager
from services.api_routes.tracks import register_track_routes
from services.system_reset import SystemResetManager
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



def create_app() -> FastAPI:
    # Ensure runtime entrypoint can read .env without relying on shell exports.
    load_daemon_env(_daemon_home())
    home = _daemon_home()
    oc_home = _openclaw_home()
    state = home / "state"
    ledger = Ledger(state)

    # Initialize Psyche.
    memory = MemoryPsyche(state / "memory.db")
    lore = LorePsyche(state / "lore.db")
    instinct = InstinctPsyche(state / "instinct.db")

    # Initialize infrastructure.
    cortex = Cortex(instinct)
    nerve = Nerve()
    trail = Trail(state / "trails")
    if not str(instinct.get_pref("eval_window_hours", "") or "").strip():
        instinct.set_pref("eval_window_hours", "48", source="system", changed_by="bootstrap")

    # Initialize Spine.
    registry_path = home / "config" / "spine_registry.json"
    canon = SpineCanon(registry_path)
    routines = SpineRoutines(
        memory=memory, lore=lore, instinct=instinct,
        cortex=cortex, nerve=nerve, trail=trail,
        daemon_home=home, openclaw_home=oc_home,
    )
    # Initialize Services.
    dominion_writ = DominionWritManager(state_dir=state, nerve=nerve, ledger=ledger)
    will = Will(lore, instinct, nerve, state, cortex=cortex, dominion_writ_manager=dominion_writ)
    cadence = Cadence(canon, routines, instinct, nerve, state, will=will)
    voice = VoiceService(instinct, oc_home, dominion_writ_manager=dominion_writ, cortex=cortex)
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
    bridge_task: asyncio.Task | None = None
    bridge_running = True
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
        nonlocal bridge_task, bridge_running, runtime_loop
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
        trigger_count = dominion_writ.register_all_triggers()
        if trigger_count:
            logger.info("Registered %d active Writ triggers", trigger_count)
        _register_runtime_handlers()
        await cadence.start()
        bridge_running = True
        bridge_task = asyncio.create_task(_bridge_loop())

    @app.on_event("shutdown")
    async def _shutdown():
        nonlocal bridge_running, bridge_task
        bridge_running = False
        if bridge_task:
            bridge_task.cancel()
            try:
                await bridge_task
            except asyncio.CancelledError:
                pass
        await cadence.stop()

    async def _bridge_loop() -> None:
        while bridge_running:
            try:
                events = await asyncio.to_thread(ether.consume, "api", 200)
                if events:
                    for evt in events:
                        payload = evt.get("payload") if isinstance(evt.get("payload"), dict) else {}
                        event_name = str(evt.get("event") or "")
                        if event_name == "feedback_survey_generated":
                            deed_id = str(payload.get("deed_id") or "")
                            if deed_id:
                                survey = dict(payload)
                                survey.setdefault("status", "pending")
                                survey.setdefault("created_utc", _utc())
                                _save_feedback_survey(deed_id, survey)
                                _append_jsonl(
                                    telemetry_dir / "feedback_surveys.jsonl",
                                    {"deed_id": deed_id, "event": "generated", "payload": survey, "created_utc": _utc()},
                                )
                                try:
                                    notify_result = await _notify_feedback_survey_telegram(survey)
                                    _append_jsonl(
                                        telemetry_dir / "feedback_surveys.jsonl",
                                        {
                                            "deed_id": deed_id,
                                            "event": "telegram_notified",
                                            "result": notify_result,
                                            "created_utc": _utc(),
                                        },
                                    )
                                except Exception as exc:
                                    logger.warning("Feedback survey telegram notify error: %s", exc)
                        if event_name == "endeavor_passage_recorded":
                            _append_jsonl(
                                telemetry_dir / "endeavor_progress.jsonl",
                                {"event": event_name, "payload": payload, "created_utc": _utc()},
                            )
                            try:
                                notify = await _notify_endeavor_progress_telegram(payload)
                                _append_jsonl(
                                    telemetry_dir / "endeavor_progress.jsonl",
                                    {
                                        "event": "endeavor_progress_telegram_notified",
                                        "payload": payload,
                                        "result": notify,
                                        "created_utc": _utc(),
                                    },
                                )
                            except Exception as exc:
                                logger.warning("Endeavor passage telegram notify error: %s", exc)
                            passage_payload = {
                                "endeavor_id": str(payload.get("endeavor_id") or ""),
                                "deed_id": str(payload.get("deed_id") or ""),
                                "passage_idx": int(payload.get("passage_index") or 0) + 1,
                                "passage_status": str(payload.get("passage_status") or ""),
                                "summary": str(payload.get("summary") or ""),
                                "next_passage_title": str(payload.get("next_passage_title") or ""),
                                "deed_title": str(payload.get("title") or payload.get("endeavor_id") or ""),
                            }
                            nerve.emit("passage_completed", passage_payload)
                        if event_name == "endeavor_status_changed":
                            _append_jsonl(
                                telemetry_dir / "endeavor_progress.jsonl",
                                {"event": event_name, "payload": payload, "created_utc": _utc()},
                            )
                            endeavor_phase = str(payload.get("endeavor_phase") or "")
                            if endeavor_phase in {"phase0_waiting_confirmation", "passage_waiting_feedback", "passage_failed", "herald_failed"}:
                                try:
                                    notify = await _notify_endeavor_status_telegram(payload)
                                    _append_jsonl(
                                        telemetry_dir / "endeavor_progress.jsonl",
                                        {
                                            "event": "endeavor_status_telegram_notified",
                                            "payload": payload,
                                            "result": notify,
                                            "created_utc": _utc(),
                                        },
                                    )
                                except Exception as exc:
                                    logger.warning("Endeavor status telegram notify error: %s", exc)
                        if event_name in {
                            "deed_completed",
                            "deed_failed",
                            "deed_rework_exhausted",
                            "eval_expiring",
                            "ward_changed",
                            "dominion_progress_update",
                            "dominion_goal_candidate_completed",
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
        move_label = str(payload.get("move_label") or payload.get("move_id") or payload.get("passage_title") or "").strip()
        if event == "deed_progress":
            phase = str(payload.get("phase") or "").strip()
            if phase == "started":
                return f"开始处理：{move_label or '当前 Move'}"
            if phase == "waiting":
                return f"正在等待结果：{move_label or '当前 Move'}"
            if phase == "completed":
                return f"已完成：{move_label or '当前 Move'}"
            if phase == "degraded":
                return f"遇到异常，已降级处理：{move_label or '当前 Move'}"
        if event == "deed_completed":
            return str(payload.get("summary") or "任务已完成。")
        if event == "deed_failed":
            return f"任务失败：{str(payload.get('error') or payload.get('last_error') or '未知错误')[:180]}"
        if event == "passage_completed":
            summary = str(payload.get("summary") or "").strip()
            next_step = str(payload.get("next_passage_title") or "").strip()
            text = summary or f"Passage {int(payload.get('passage_idx') or 0)} 已完成。"
            if next_step:
                text += f"\n下一阶段：{next_step}"
            return text
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
        deed_id = str(out.get("deed_id") or "")
        deed_status = str(out.get("deed_status") or "")
        complexity = str(out.get("complexity") or plan.get("complexity") or brief.get("complexity") or "charge")
        endeavor_id = str(out.get("endeavor_id") or plan.get("endeavor_id") or "")
        deed_title = str(
            out.get("deed_title") or out.get("title")
            or plan.get("deed_title") or plan.get("title")
            or brief.get("objective", "")
            or deed_id
        )
        phase = str(out.get("phase") or "").strip().lower()
        if phase not in {"running", "awaiting_eval", "history"}:
            status_lower = deed_status.lower()
            if status_lower in {"running", "queued", "paused", "cancel_requested", "cancelling"}:
                phase = "running"
            elif status_lower in {"awaiting_eval", "pending_review"}:
                phase = "awaiting_eval"
            else:
                phase = "history"
        out.setdefault("deed_id", deed_id)
        if deed_status:
            out["deed_status"] = deed_status
        out["phase"] = phase
        out["deed_title"] = deed_title
        out["title"] = deed_title
        out["complexity"] = complexity
        if endeavor_id:
            out.setdefault("endeavor_id", endeavor_id)
        out.setdefault("global_score_components", plan.get("global_score_components") or {})
        out.setdefault("eval_window_hours", plan.get("eval_window_hours", 48))
        out.setdefault("exec_completed_utc", out.get("exec_completed_utc", ""))
        out.setdefault("eval_deadline_utc", out.get("eval_deadline_utc", ""))
        dominion_id = str(out.get("dominion_id") or plan.get("dominion_id") or "")
        if dominion_id:
            dominion = dominion_writ.get_dominion(dominion_id)
            if dominion:
                out["group_label"] = str(dominion.get("objective") or deed_title)
        else:
            out.setdefault("group_label", "Independent")
        return out

    def _write_json_list(path: Path, items: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2))

    def _require_offering_root() -> Path:
        p = home / "offerings"
        p.mkdir(parents=True, exist_ok=True)
        return p

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

    async def _notify_feedback_survey_telegram(payload: dict) -> dict:
        if os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() == "":
            return {"sent": 0, "skipped": True}
        deed_id = str(payload.get("deed_id") or "")
        if deed_id:
            survey = _load_feedback_survey(deed_id)
            if isinstance(survey, dict):
                if str(survey.get("status") or "") == "submitted" and str(survey.get("handled_channel") or "") == "portal":
                    return {"sent": 0, "skipped": True, "reason": "handled_by_portal"}
        return await _notify_via_adapter(
            "feedback_survey",
            {
                "deed_id": deed_id,
                "deed_title": str(payload.get("title") or deed_id),
                "complexity": str(payload.get("complexity") or ""),
            },
        )

    async def _notify_endeavor_progress_telegram(payload: dict) -> dict:
        if os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() == "":
            return {"sent": 0, "skipped": True}
        return await _notify_via_adapter(
            "passage_completed",
            {
                "endeavor_id": str(payload.get("endeavor_id") or ""),
                "passage_idx": int(payload.get("passage_index") or 0) + 1,
                "deed_title": str(payload.get("title") or payload.get("endeavor_id") or ""),
                "passage_status": str(payload.get("passage_status") or ""),
            },
        )

    async def _notify_endeavor_status_telegram(payload: dict) -> dict:
        if os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() == "":
            return {"sent": 0, "skipped": True}
        return await _notify_via_adapter(
            "endeavor_status",
            {
                "endeavor_id": str(payload.get("endeavor_id") or ""),
                "deed_title": str(payload.get("endeavor_id") or ""),
                "endeavor_status": str(payload.get("endeavor_status") or ""),
                "endeavor_phase": str(payload.get("endeavor_phase") or ""),
                "current_passage_index": int(payload.get("current_passage_index") or 0),
            },
        )

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
        dominion_id = str(payload.get("dominion_id") or "")
        brief_template = payload.get("brief_template") if isinstance(payload.get("brief_template"), dict) else {}
        trigger_payload = payload.get("trigger_payload") if isinstance(payload.get("trigger_payload"), dict) else {}
        trigger_utc = str(trigger_payload.get("tick_utc") or _utc())
        objective_text = str(brief_template.get("objective") or "")
        memory_hits = memory.search_by_tags(
            [f"dominion_id:{dominion_id}", f"writ_id:{writ_id}"],
            limit=3,
            dominion_id=dominion_id or None,
        )
        lore_hits = lore.list_records(dominion_id=dominion_id or None, writ_id=writ_id or None, limit=3)
        recent_deeds = dominion_writ.recent_deed_summaries(writ_id, limit=3) if writ_id else []
        dominion = dominion_writ.get_dominion(dominion_id) if dominion_id else None
        return {
            "date": trigger_utc[:10],
            "tick_utc": trigger_utc,
            "trigger_event": str(payload.get("trigger_event") or ""),
            "dominion_objective": str((dominion or {}).get("objective") or ""),
            "recent_titles": " / ".join(str(row.get("title") or "") for row in recent_deeds if row.get("title")),
            "recent_summary": "\n".join(
                f"- {row.get('title') or row.get('deed_id')}: {row.get('status') or ''}"
                for row in recent_deeds
            ),
            "memory_summary": "\n".join(str(row.get("content") or "")[:240] for row in memory_hits),
            "lore_summary": "\n".join(str(row.get("objective_text") or "")[:160] for row in lore_hits),
            "writ_id": writ_id,
            "dominion_id": dominion_id,
            "objective": objective_text,
        }

    async def _consume_writ_trigger(payload: dict[str, Any]) -> None:
        brief_template = payload.get("brief_template") if isinstance(payload.get("brief_template"), dict) else {}
        ctx = _build_writ_context(payload)
        rendered = _render_template_value(brief_template, ctx)
        objective = str(rendered.get("objective") or brief_template.get("objective") or "").strip()
        if not objective:
            objective = f"Writ {str(payload.get('writ_id') or '')}"
        plan = {
            "brief": {
                "objective": objective,
                "complexity": str(rendered.get("complexity") or "charge"),
                "language": str(rendered.get("language") or "bilingual"),
                "format": str(rendered.get("format") or "markdown"),
                "depth": str(rendered.get("depth") or "study"),
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
                "writ_id": str(payload.get("writ_id") or ""),
                "dominion_id": str(payload.get("dominion_id") or ""),
                "trigger_event": str(payload.get("trigger_event") or ""),
            },
        }
        result = await will.submit(plan)
        if result.get("ok") and result.get("deed_id"):
            dominion_writ.record_writ_triggered(str(payload.get("writ_id") or ""), str(result.get("deed_id") or ""))
        else:
            logger.warning("Writ trigger submit failed for %s: %s", payload.get("writ_id"), result)

    def _register_runtime_handlers() -> None:
        ws_events = {
            "deed_completed",
            "deed_failed",
            "deed_progress",
            "deed_message",
            "passage_completed",
            "ward_changed",
            "eval_expiring",
            "dominion_progress_update",
            "dominion_goal_candidate_completed",
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

    def _endeavor_root(endeavor_id: str | None = None) -> Path:
        root = state / "endeavors"
        return root / endeavor_id if endeavor_id else root

    def _normalize_endeavor_passage_row(row: dict) -> dict:
        item = dict(row or {})
        passage_status = str(item.get("passage_status") or "").strip()
        if passage_status:
            item["passage_status"] = passage_status
        return item

    def _normalize_endeavor_manifest(manifest: dict) -> dict:
        out = dict(manifest or {})
        endeavor_status = str(out.get("endeavor_status") or "").strip()
        endeavor_phase = str(out.get("endeavor_phase") or "").strip()
        if endeavor_status:
            out["endeavor_status"] = endeavor_status
        if endeavor_phase:
            out["endeavor_phase"] = endeavor_phase
        passages = out.get("passages")
        if isinstance(passages, list):
            normalized: list[dict] = []
            for row in passages:
                if not isinstance(row, dict):
                    continue
                normalized.append(_normalize_endeavor_passage_row(row))
            out["passages"] = normalized
        return out

    def _load_endeavor_manifest(endeavor_id: str) -> dict | None:
        path = _endeavor_root(endeavor_id) / "manifest.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return _normalize_endeavor_manifest(data) if isinstance(data, dict) else None

    def _save_endeavor_manifest(endeavor_id: str, manifest: dict) -> None:
        path = _endeavor_root(endeavor_id) / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _normalize_endeavor_manifest(manifest if isinstance(manifest, dict) else {})
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _endeavor_summaries(limit: int = 200) -> list[dict]:
        root = _endeavor_root()
        if not root.exists():
            return []
        rows: list[dict] = []
        for p in root.glob("*/manifest.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            normalized = _normalize_endeavor_manifest(data)
            endeavor_status = str(normalized.get("endeavor_status") or "")
            endeavor_phase = str(normalized.get("endeavor_phase") or "")
            rows.append(
                {
                    "endeavor_id": str(normalized.get("endeavor_id") or p.parent.name),
                    "deed_id": str(normalized.get("deed_id") or ""),
                    "title": str(normalized.get("title") or ""),
                    "endeavor_status": endeavor_status,
                    "endeavor_phase": endeavor_phase,
                    "current_passage_index": int(normalized.get("current_passage_index") or 0),
                    "total_passages": int(normalized.get("total_passages") or len(normalized.get("passages") or [])),
                    "updated_utc": str(normalized.get("updated_utc") or ""),
                    "workflow_id": str(normalized.get("workflow_id") or ""),
                }
            )
        rows.sort(key=lambda x: str(x.get("updated_utc") or ""), reverse=True)
        return rows[: max(1, min(limit, 1000))]

    def _endeavor_result_rows(endeavor_id: str, limit: int = 200) -> list[dict]:
        passages_dir = _endeavor_root(endeavor_id) / "passages"
        if not passages_dir.exists():
            return []
        rows: list[dict] = []
        for p in sorted(passages_dir.glob("*/result.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict):
                rows.append(_normalize_endeavor_passage_row(data))
        return rows[: max(1, min(limit, 2000))]

    def _append_endeavor_feedback(endeavor_id: str, passage_index: int, feedback: dict) -> None:
        result_path = _endeavor_root(endeavor_id) / "passages" / str(max(1, int(passage_index) + 1)) / "result.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if result_path.exists():
            try:
                old = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(old, dict):
                    data = old
            except Exception:
                data = {}
        logs = data.get("user_feedback_log") if isinstance(data.get("user_feedback_log"), list) else []
        logs.append({**feedback, "created_utc": _utc()})
        data["user_feedback_log"] = logs[-100:]
        result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _endeavor_result_payload(endeavor_id: str, passage_index: int) -> dict:
        result_path = _endeavor_root(endeavor_id) / "passages" / str(max(1, int(passage_index) + 1)) / "result.json"
        if not result_path.exists():
            return {}
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return _normalize_endeavor_passage_row(data)

    def _feedback_satisfied(feedback: dict) -> bool:
        if not isinstance(feedback, dict):
            return False
        if "satisfied" in feedback:
            return bool(feedback.get("satisfied"))
        try:
            rating = int(feedback.get("rating"))
            return rating >= 3
        except Exception:
            pass
        verdict = str(feedback.get("verdict") or feedback.get("decision") or "").strip().lower()
        return verdict in {"yes", "y", "ok", "pass", "satisfied", "满意"}

    def _apply_endeavor_feedback_decision(
        endeavor_id: str,
        passage_index: int,
        feedback: dict,
        *,
        source: str,
    ) -> dict:
        result_path = _endeavor_root(endeavor_id) / "passages" / str(max(1, int(passage_index) + 1)) / "result.json"
        result_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        if result_path.exists():
            try:
                old = json.loads(result_path.read_text(encoding="utf-8"))
                if isinstance(old, dict):
                    data = old
            except Exception:
                data = {}

        decision = data.get("user_feedback_decision") if isinstance(data.get("user_feedback_decision"), dict) else None
        row = {
            "source": str(source or "unknown"),
            "feedback": feedback,
            "created_utc": _utc(),
        }
        accepted = False
        if not decision:
            data["user_feedback_decision"] = row
            accepted = True
        else:
            late = data.get("user_feedback_late") if isinstance(data.get("user_feedback_late"), list) else []
            late.append(row)
            data["user_feedback_late"] = late[-100:]
        logs = data.get("user_feedback_log") if isinstance(data.get("user_feedback_log"), list) else []
        logs.append(row)
        data["user_feedback_log"] = logs[-200:]
        result_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "accepted": accepted,
            "decision": data.get("user_feedback_decision") if isinstance(data.get("user_feedback_decision"), dict) else {},
            "result_path": str(result_path),
        }

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
        dominion_writ=dominion_writ,
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

    console_ctx = type("ConsoleRouteContext", (), {})()
    console_ctx.logger = logger
    console_ctx.state = state
    console_ctx.oc_home = oc_home
    console_ctx.cadence = cadence
    console_ctx.canon = canon
    console_ctx.nerve = nerve
    console_ctx.memory = memory
    console_ctx.lore = lore
    console_ctx.instinct = instinct
    console_ctx.cortex = cortex
    console_ctx.trail = trail
    console_ctx.ledger = ledger
    console_ctx.will = will
    console_ctx.skill_queue_path = skill_queue_path
    console_ctx.utc = _utc
    console_ctx.sync_skill_proposals = _sync_skill_proposals
    console_ctx.write_json_list = _write_json_list
    console_ctx.sandbox_ward_open = _sandbox_ward_open
    console_ctx.apply_evolution_proposal = _apply_evolution_proposal
    console_ctx.model_policy_path = model_policy_path
    console_ctx.model_registry_path = model_registry_path
    console_ctx.validate_model_registry = _validate_model_registry
    console_ctx.validate_model_policy = _validate_model_policy
    console_ctx.model_registry_aliases = _model_registry_aliases
    console_ctx.sync_instinct_provider_rations_from_policy = _sync_instinct_provider_rations_from_policy
    console_ctx.audit_console = _audit_console

    register_console_admin_routes(app, ctx=console_ctx)
    register_console_spine_psyche_routes(app, ctx=console_ctx)
    register_console_norm_routes(app, ctx=console_ctx)
    register_console_observe_routes(app, ctx=console_ctx)
    register_console_agents_skill_routes(app, ctx=console_ctx)

    endeavor_ctx = type("EndeavorRouteContext", (), {})()
    endeavor_ctx.logger = logger
    endeavor_ctx.state = state
    endeavor_ctx.will = will
    endeavor_ctx.telemetry_dir = telemetry_dir
    endeavor_ctx.time_time = time.time
    endeavor_ctx.utc = _utc
    endeavor_ctx.ensure_temporal_client = _ensure_temporal_client
    endeavor_ctx.get_temporal_client = lambda: temporal_client
    endeavor_ctx.endeavor_summaries = _endeavor_summaries
    endeavor_ctx.load_endeavor_manifest = _load_endeavor_manifest
    endeavor_ctx.save_endeavor_manifest = _save_endeavor_manifest
    endeavor_ctx.endeavor_result_rows = _endeavor_result_rows
    endeavor_ctx.append_endeavor_feedback = _append_endeavor_feedback
    endeavor_ctx.apply_endeavor_feedback_decision = _apply_endeavor_feedback_decision
    endeavor_ctx.endeavor_result_payload = _endeavor_result_payload
    endeavor_ctx.feedback_satisfied = _feedback_satisfied
    endeavor_ctx.append_jsonl = _append_jsonl

    register_endeavor_routes(app, ctx=endeavor_ctx)
    register_chat_routes(app, voice=voice, log_portal_event=_log_portal_event)
    register_track_routes(app, dominion_writ)

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

    async def _get_feedback_questions(deed_id: str):
        """Generate deed-specific feedback questions via Cortex (LLM).
        Falls back to a minimal default set if Cortex is unavailable.
        """
        # Load deed context.
        deed_record: dict = {}
        try:
            deed_record = ledger.get_deed(deed_id) or {}
        except Exception:
            pass

        plan = deed_record.get("plan") or {}
        brief = plan.get("brief") or {}
        title = str(plan.get("title") or brief.get("objective", "") or deed_id)
        complexity = str(plan.get("complexity") or brief.get("complexity") or "charge")

        # Load offering content snippet.
        content_snippet = ""
        try:
            offering_root = _require_offering_root()
            index = ledger.load_herald_log()
            entry = next((e for e in reversed(index) if e.get("deed_id") == deed_id), None)
            if entry:
                out_path = offering_root / str(entry["path"])
                for fname in ("report.md", "report.html"):
                    p = out_path / fname
                    if p.exists():
                        raw = p.read_text(encoding="utf-8", errors="ignore")
                        if fname.endswith(".html"):
                            import re as _re
                            raw = _re.sub(r"<[^>]+>", " ", raw)
                        content_snippet = raw[:800].strip()
                        break
        except Exception:
            pass

        _DEFAULT_QUESTIONS = [
            {
                "key": "overall", "isRating": True,
                "q": "整体来看，这份产出如何？",
                "opts": [
                    {"label": "非常满意", "val": 5, "desc": "超出预期，可以直接使用"},
                    {"label": "基本满意", "val": 4, "desc": "符合需求，稍作打磨即可"},
                    {"label": "一般",     "val": 3, "desc": "方向正确，但内容有待改进"},
                    {"label": "不满意",   "val": 1, "desc": "与预期差距较大，需要重做"},
                ],
            },
            {
                "key": "depth",
                "q": "内容深度如何？",
                "opts": [
                    {"label": "深度恰当",   "val": 1.0, "desc": "详略得当，信息密度合适"},
                    {"label": "太浅",       "val": 0.2, "desc": "缺少分析或细节"},
                    {"label": "太冗长",     "val": 0.6, "desc": "内容偏多，核心不突出"},
                ],
            },
            {
                "key": "relevance",
                "q": "内容是否切合你的实际需求？",
                "opts": [
                    {"label": "非常切合", "val": 1.0, "desc": "准确理解并回应了我的意图"},
                    {"label": "部分偏差", "val": 0.5, "desc": "主干对路，但细节有偏离"},
                    {"label": "理解有误", "val": 0.1, "desc": "没有抓住我真正想要的"},
                ],
            },
        ]

        if not cortex or not cortex.is_available():
            return _DEFAULT_QUESTIONS

        prompt = (
            "你是一个AI产出评估专家。根据以下运行信息，生成3-4个针对性反馈问题。\n\n"
            f"复杂度: {complexity}\n"
            f"运行标题: {title}\n"
        )
        if content_snippet:
            prompt += f"内容摘要（前800字）:\n{content_snippet}\n\n"
        prompt += (
            "要求：\n"
            "1. 第一个问题必须是整体满意度（key=\"overall\", isRating=true），选项val为整数1-5\n"
            "2. 其余2-3个问题根据这份产出的具体内容和运行类型量身定制，不要用泛泛的通用问题\n"
            "3. 每个问题3-4个选项，其余问题val为0.0-1.0的小数\n"
            "4. 所有问题和选项必须用中文\n"
            "5. 仅返回JSON数组，不要解释或其他内容\n\n"
            "格式：\n"
            '[{"key":"overall","isRating":true,"q":"...","opts":[{"label":"...","val":5,"desc":"..."},...]},'
            '{"key":"unique_key","q":"...","opts":[{"label":"...","val":1.0,"desc":"..."},...]}]'
        )

        try:
            raw = (cortex.complete(prompt, max_tokens=800) or "").strip()
            # Extract JSON array from response.
            import re as _re
            m = _re.search(r"\[[\s\S]*\]", raw)
            if m:
                questions = json.loads(m.group(0))
                # Validate minimal structure.
                if isinstance(questions, list) and questions:
                    return questions
        except Exception as exc:
            logger.warning("Feedback question generation failed: %s", exc)

        return _DEFAULT_QUESTIONS

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

        # Find deed record to get complexity.
        deed_record = ledger.get_deed(deed_id)

        complexity = ""
        if deed_record:
            plan = deed_record.get("plan") if isinstance(deed_record.get("plan"), dict) else {}
            brief = plan.get("brief") or {}
            complexity = str(brief.get("complexity") or plan.get("complexity") or "")

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

        if first_scored_feedback and complexity == "endeavor":
            summary_zh = (
                f"Endeavor 用户反馈：rating={rating}/5；comment={comment or '无'}；"
                f"aspects={json.dumps(aspects, ensure_ascii=False)}"
            )
            summary_en = (
                f"Endeavor final feedback: rating={rating}/5; comment={comment or 'n/a'}; "
                f"aspects={json.dumps(aspects, ensure_ascii=False)}"
            )
            try:
                memory.add(
                    content=f"{summary_zh}\n\n{summary_en}",
                    tags=["domain:user_feedback", "tier:deep", "source_type:human", "source_agent:user", f"deed_id:{deed_id}"],
                    source=f"{source}.feedback",
                )
            except Exception as exc:
                logger.warning("Failed to store endeavor feedback into memory: %s", exc)

        # Persist feedback aspects as Instinct prefs for the learning system.
        if aspects and complexity:
            for aspect_key, aspect_val in aspects.items():
                try:
                    v = float(aspect_val)
                    if 0.0 <= v <= 1.0:
                        instinct.set_pref(
                            f"feedback.{complexity}.{aspect_key}",
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
                "complexity": complexity,
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
                    if status in {"awaiting_eval", "pending_review"}:
                        row["deed_status"] = "completed"
                        row["phase"] = "history"
                        row["updated_utc"] = now
                        row["eval_submitted_utc"] = now
                        row["feedback_expired"] = False
                        row.pop("eval_deadline_utc", None)
                    break

            ledger.mutate_deeds(_close_eval)

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
    feedback_ctx.get_feedback_questions = _get_feedback_questions
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
    console_dir = home / "interfaces" / "console"
    if portal_dir.exists():
        app.mount("/portal", StaticFiles(directory=portal_dir, html=True), name="portal")
    if console_dir.exists():
        app.mount("/console", StaticFiles(directory=console_dir, html=True), name="console")

    return app
