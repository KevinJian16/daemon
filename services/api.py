"""Daemon API — FastAPI application with Portal and Console routes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from fabric.memory import MemoryFabric
from fabric.playbook import PlaybookFabric
from fabric.compass import CompassFabric
from spine.nerve import Nerve
from spine.trace import Tracer
from spine.registry import SpineRegistry
from spine.routines import SpineRoutines
from runtime.cortex import Cortex
from runtime.drive_accounts import DriveAccountRegistry
from runtime.event_bridge import EventBridge
from runtime.temporal import TemporalClient
from services.dispatch import Dispatch
from services.dialog import DialogService
from services.api_routes.basic import register_basic_routes
from services.api_routes.campaigns import register_campaign_routes
from services.api_routes.chat import register_chat_routes
from services.api_routes.console_agents_skill import register_console_agents_skill_routes
from services.api_routes.console_observe import register_console_observe_routes
from services.api_routes.console_norm import register_console_norm_routes
from services.api_routes.console_spine_fabric import register_console_spine_fabric_routes
from services.api_routes.console_strategy_model import register_console_strategy_model_routes
from services.api_routes.circuits import register_circuit_routes
from services.api_routes.feedback import register_feedback_routes
from services.api_routes.submit import register_submit_route
from services.api_routes.system import register_system_routes
from services.scheduler import Scheduler
from services.state_store import StateStore
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


def _validate_semantic_config(home: Path) -> None:
    """Hard error on startup if capability_catalog.json or mapping_rules.json is missing."""
    catalog = home / "config" / "semantics" / "capability_catalog.json"
    rules = home / "config" / "semantics" / "mapping_rules.json"
    missing = [str(p) for p in (catalog, rules) if not p.exists()]
    if missing:
        raise RuntimeError(
            f"Missing required semantic config files (daemon cannot start): {missing}. "
            "Create config/semantics/capability_catalog.json and mapping_rules.json."
        )


def _bootstrap_clusters(home: Path, playbook) -> None:
    """Seed semantic_clusters table from capability_catalog.json (idempotent)."""
    catalog_path = home / "config" / "semantics" / "capability_catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read capability_catalog.json for bootstrap: %s", exc)
        return
    clusters = catalog.get("clusters") or []
    if clusters:
        try:
            playbook.seed_clusters(clusters)
            logger.info("Bootstrapped %d semantic clusters into Playbook DB.", len(clusters))
        except Exception as exc:
            logger.warning("Failed to seed semantic clusters: %s", exc)


def create_app() -> FastAPI:
    # Ensure runtime entrypoint can read .env without relying on shell exports.
    load_daemon_env(_daemon_home())
    home = _daemon_home()
    oc_home = _openclaw_home()
    state = home / "state"
    store = StateStore(state)

    # Initialize Fabric.
    memory = MemoryFabric(state / "memory.db")
    playbook = PlaybookFabric(state / "playbook.db")
    compass = CompassFabric(state / "compass.db")

    # Initialize infrastructure.
    cortex = Cortex(compass)
    nerve = Nerve()
    tracer = Tracer(state / "traces")

    # Initialize Spine.
    registry_path = home / "config" / "spine_registry.json"
    registry = SpineRegistry(registry_path)
    routines = SpineRoutines(
        memory=memory, playbook=playbook, compass=compass,
        cortex=cortex, nerve=nerve, tracer=tracer,
        daemon_home=home, openclaw_home=oc_home,
    )
    # Initialize Services.
    dispatch = Dispatch(playbook, compass, nerve, state, cortex=cortex)
    scheduler = Scheduler(registry, routines, compass, nerve, state, dispatch=dispatch)
    dialog = DialogService(compass, oc_home)
    reset_manager = SystemResetManager(home)
    bridge = EventBridge(state, source="api")
    drive_accounts = DriveAccountRegistry(state)
    telemetry_dir = state / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    portal_events_path = telemetry_dir / "portal_events.jsonl"
    skill_proposals_path = state / "skill_evolution_proposals.json"
    skill_queue_path = state / "skill_evolution_queue.json"
    feedback_surveys_dir = state / "feedback_surveys"
    feedback_surveys_dir.mkdir(parents=True, exist_ok=True)
    semantic_catalog_path = home / "config" / "semantics" / "capability_catalog.json"
    semantic_rules_path = home / "config" / "semantics" / "mapping_rules.json"
    model_policy_path = home / "config" / "model_policy.json"
    model_registry_path = home / "config" / "model_registry.json"
    app_started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

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
                dispatch.set_temporal_client(temporal_client)
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
        nonlocal bridge_task, bridge_running
        # Keep OpenClaw on daemon canonical topology (no legacy main default).
        norm = normalize_openclaw_config(oc_home)
        if norm.get("updated"):
            logger.info("OpenClaw config normalized on startup: %s", norm.get("changes"))
        if norm.get("warnings"):
            for warn in norm.get("warnings") or []:
                logger.warning("OpenClaw config warning: %s", warn)
        # Validate required semantic config files — hard error if missing.
        _validate_semantic_config(home)
        # Bootstrap semantic clusters into Playbook DB.
        _bootstrap_clusters(home, playbook)

        await _ensure_temporal_client(retries=20, delay_s=0.5)
        await scheduler.start()
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
        await scheduler.stop()

    async def _bridge_loop() -> None:
        while bridge_running:
            try:
                events = await asyncio.to_thread(bridge.consume, "api", 200)
                if events:
                    for evt in events:
                        payload = evt.get("payload") if isinstance(evt.get("payload"), dict) else {}
                        event_name = str(evt.get("event") or "")
                        if event_name == "feedback_survey_generated":
                            run_id = str(payload.get("run_id") or "")
                            if run_id:
                                survey = dict(payload)
                                survey.setdefault("status", "pending")
                                survey.setdefault("created_utc", _utc())
                                _save_feedback_survey(run_id, survey)
                                _append_jsonl(
                                    telemetry_dir / "feedback_surveys.jsonl",
                                    {"run_id": run_id, "event": "generated", "payload": survey, "created_utc": _utc()},
                                )
                                try:
                                    notify_result = await _notify_feedback_survey_telegram(survey)
                                    _append_jsonl(
                                        telemetry_dir / "feedback_surveys.jsonl",
                                        {
                                            "run_id": run_id,
                                            "event": "telegram_notified",
                                            "result": notify_result,
                                            "created_utc": _utc(),
                                        },
                                    )
                                except Exception as exc:
                                    logger.warning("Feedback survey telegram notify error: %s", exc)
                        if event_name == "campaign_milestone_recorded":
                            _append_jsonl(
                                telemetry_dir / "campaign_progress.jsonl",
                                {"event": event_name, "payload": payload, "created_utc": _utc()},
                            )
                            try:
                                notify = await _notify_campaign_progress_telegram(payload)
                                _append_jsonl(
                                    telemetry_dir / "campaign_progress.jsonl",
                                    {
                                        "event": "campaign_progress_telegram_notified",
                                        "payload": payload,
                                        "result": notify,
                                        "created_utc": _utc(),
                                    },
                                )
                            except Exception as exc:
                                logger.warning("Campaign milestone telegram notify error: %s", exc)
                        if event_name == "campaign_status_changed":
                            _append_jsonl(
                                telemetry_dir / "campaign_progress.jsonl",
                                {"event": event_name, "payload": payload, "created_utc": _utc()},
                            )
                            campaign_phase = str(payload.get("campaign_phase") or "")
                            if campaign_phase in {"phase0_waiting_confirmation", "milestone_waiting_feedback", "delivery_failed"}:
                                try:
                                    notify = await _notify_campaign_status_telegram(payload)
                                    _append_jsonl(
                                        telemetry_dir / "campaign_progress.jsonl",
                                        {
                                            "event": "campaign_status_telegram_notified",
                                            "payload": payload,
                                            "result": notify,
                                            "created_utc": _utc(),
                                        },
                                    )
                                except Exception as exc:
                                    logger.warning("Campaign status telegram notify error: %s", exc)
                        payload = {**payload, "_bridge_event_id": evt.get("event_id"), "_bridge_event": event_name}
                        nerve.emit(event_name, payload)
                        await asyncio.to_thread(
                            bridge.acknowledge,
                            str(evt.get("event_id") or ""),
                            event_name,
                            payload,
                            "api",
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Event bridge loop error: %s", exc)
            await asyncio.sleep(2)

    def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _utc() -> str:
        import time
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

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

    def _run_view(run: dict) -> dict:
        out = dict(run)
        plan = out.get("plan") if isinstance(out.get("plan"), dict) else {}
        run_id = str(out.get("run_id") or "")
        run_status = str(out.get("run_status") or "")
        work_scale = str(out.get("work_scale") or plan.get("work_scale") or "")
        campaign_id = str(out.get("campaign_id") or plan.get("campaign_id") or "")
        out.setdefault("run_id", run_id)
        if run_status:
            out["run_status"] = run_status
        if work_scale:
            out.setdefault("work_scale", work_scale)
        if campaign_id:
            out.setdefault("campaign_id", campaign_id)
        out.setdefault("semantic_cluster", plan.get("cluster_id", ""))
        out.setdefault("strategy_id", plan.get("strategy_id", ""))
        out.setdefault("strategy_stage", plan.get("strategy_stage", ""))
        out.setdefault("global_score_components", plan.get("global_score_components") or {})
        return out

    def _write_json_list(path: Path, items: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2))

    def _require_outcome_root() -> Path:
        resolved = drive_accounts.resolve_outcome_root()
        if not resolved.get("ok"):
            raise HTTPException(
                status_code=503,
                detail={"ok": False, "error_code": "drive_storage_unavailable", "error": resolved.get("error", "")},
            )
        p = Path(str(resolved.get("outcome_root") or ""))
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
        return p

    def _feedback_survey_path(run_id: str) -> Path:
        return feedback_surveys_dir / f"{run_id}.json"

    def _load_feedback_survey(run_id: str) -> dict | None:
        path = _feedback_survey_path(run_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _save_feedback_survey(run_id: str, payload: dict) -> None:
        path = _feedback_survey_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _feedback_history(survey: dict | None) -> list[dict]:
        if not isinstance(survey, dict):
            return []
        rows = survey.get("history")
        if not isinstance(rows, list):
            return []
        return [r for r in rows if isinstance(r, dict)]

    def _feedback_state(run_id: str) -> dict:
        survey = _load_feedback_survey(run_id) or {}
        history = _feedback_history(survey)
        response = survey.get("response") if isinstance(survey.get("response"), dict) else {}
        return {
            "run_id": str(survey.get("run_id") or run_id),
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

    def _telegram_user_ids() -> list[int]:
        raw = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
        out: list[int] = []
        for piece in raw.split(","):
            s = piece.strip()
            if s.isdigit():
                out.append(int(s))
        return out

    async def _notify_feedback_survey_telegram(payload: dict) -> dict:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        users = _telegram_user_ids()
        if not token or not users:
            return {"sent": 0, "skipped": True}
        run_id = str(payload.get("run_id") or "")
        if run_id:
            survey = _load_feedback_survey(run_id)
            if isinstance(survey, dict):
                if str(survey.get("status") or "") == "submitted" and str(survey.get("handled_channel") or "") == "portal":
                    return {"sent": 0, "skipped": True, "reason": "handled_by_portal"}
        title = str(payload.get("title") or run_id)
        prompt = str(payload.get("prompt") or "请反馈本次交付质量。")
        work_scale = str(payload.get("work_scale") or "")
        message = (
            "📝 Daemon Feedback Survey\n\n"
            f"运行: `{run_id}`\n"
            f"规模: `{work_scale}`\n"
            f"标题: {title}\n\n"
            f"{prompt}\n"
            "请在 Portal 打开该运行并提交反馈。"
        )
        sent = 0
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            for uid in users:
                try:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": uid, "text": message, "parse_mode": "Markdown"},
                    )
                    if resp.status_code < 300:
                        sent += 1
                except Exception as exc:
                    logger.warning("Feedback survey telegram notify failed user=%s: %s", uid, exc)
        return {"sent": sent, "total": len(users)}

    async def _notify_campaign_progress_telegram(payload: dict) -> dict:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        users = _telegram_user_ids()
        if not token or not users:
            return {"sent": 0, "skipped": True}
        campaign_id = str(payload.get("campaign_id") or "")
        milestone_index = int(payload.get("milestone_index") or 0)
        milestone_status = str(payload.get("milestone_status") or "")
        score = payload.get("objective_score")
        attempts = int(payload.get("attempts") or 0)
        title = str(payload.get("title") or "")
        msg = (
            "📈 Campaign Progress\n\n"
            f"campaign: `{campaign_id}`\n"
            f"milestone: `{milestone_index + 1}` {title}\n"
            f"milestone_status: `{milestone_status}`\n"
            f"objective_score: `{score}`\n"
            f"attempts: `{attempts}`"
        )
        sent = 0
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            for uid in users:
                try:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": uid, "text": msg, "parse_mode": "Markdown"},
                    )
                    if resp.status_code < 300:
                        sent += 1
                except Exception as exc:
                    logger.warning("Campaign progress telegram notify failed user=%s: %s", uid, exc)
        return {"sent": sent, "total": len(users)}

    async def _notify_campaign_status_telegram(payload: dict) -> dict:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        users = _telegram_user_ids()
        if not token or not users:
            return {"sent": 0, "skipped": True}
        campaign_id = str(payload.get("campaign_id") or "")
        campaign_status = str(payload.get("campaign_status") or "")
        campaign_phase = str(payload.get("campaign_phase") or "")
        cur = int(payload.get("current_milestone_index") or 0)
        msg = (
            "📌 Campaign Status Update\n\n"
            f"campaign: `{campaign_id}`\n"
            f"campaign_status: `{campaign_status}`\n"
            f"campaign_phase: `{campaign_phase}`\n"
            f"milestone_index: `{cur}`"
        )
        sent = 0
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            for uid in users:
                try:
                    resp = await client.post(
                        f"https://api.telegram.org/bot{token}/sendMessage",
                        json={"chat_id": uid, "text": msg, "parse_mode": "Markdown"},
                    )
                    if resp.status_code < 300:
                        sent += 1
                except Exception as exc:
                    logger.warning("Campaign status telegram notify failed user=%s: %s", uid, exc)
        return {"sent": sent, "total": len(users)}

    def _campaign_root(campaign_id: str | None = None) -> Path:
        root = state / "campaigns"
        return root / campaign_id if campaign_id else root

    def _normalize_campaign_milestone_row(row: dict) -> dict:
        item = dict(row or {})
        milestone_status = str(item.get("milestone_status") or "").strip()
        if milestone_status:
            item["milestone_status"] = milestone_status
        return item

    def _normalize_campaign_manifest(manifest: dict) -> dict:
        out = dict(manifest or {})
        campaign_status = str(out.get("campaign_status") or "").strip()
        campaign_phase = str(out.get("campaign_phase") or "").strip()
        if campaign_status:
            out["campaign_status"] = campaign_status
        if campaign_phase:
            out["campaign_phase"] = campaign_phase
        milestones = out.get("milestones")
        if isinstance(milestones, list):
            normalized: list[dict] = []
            for row in milestones:
                if not isinstance(row, dict):
                    continue
                normalized.append(_normalize_campaign_milestone_row(row))
            out["milestones"] = normalized
        return out

    def _load_campaign_manifest(campaign_id: str) -> dict | None:
        path = _campaign_root(campaign_id) / "manifest.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return _normalize_campaign_manifest(data) if isinstance(data, dict) else None

    def _save_campaign_manifest(campaign_id: str, manifest: dict) -> None:
        path = _campaign_root(campaign_id) / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _normalize_campaign_manifest(manifest if isinstance(manifest, dict) else {})
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _campaign_summaries(limit: int = 200) -> list[dict]:
        root = _campaign_root()
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
            normalized = _normalize_campaign_manifest(data)
            campaign_status = str(normalized.get("campaign_status") or "")
            campaign_phase = str(normalized.get("campaign_phase") or "")
            rows.append(
                {
                    "campaign_id": str(normalized.get("campaign_id") or p.parent.name),
                    "run_id": str(normalized.get("run_id") or ""),
                    "title": str(normalized.get("title") or ""),
                    "campaign_status": campaign_status,
                    "campaign_phase": campaign_phase,
                    "current_milestone_index": int(normalized.get("current_milestone_index") or 0),
                    "total_milestones": int(normalized.get("total_milestones") or len(normalized.get("milestones") or [])),
                    "updated_utc": str(normalized.get("updated_utc") or ""),
                    "workflow_id": str(normalized.get("workflow_id") or ""),
                }
            )
        rows.sort(key=lambda x: str(x.get("updated_utc") or ""), reverse=True)
        return rows[: max(1, min(limit, 1000))]

    def _campaign_result_rows(campaign_id: str, limit: int = 200) -> list[dict]:
        milestones_dir = _campaign_root(campaign_id) / "milestones"
        if not milestones_dir.exists():
            return []
        rows: list[dict] = []
        for p in sorted(milestones_dir.glob("*/result.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(data, dict):
                rows.append(_normalize_campaign_milestone_row(data))
        return rows[: max(1, min(limit, 2000))]

    def _append_campaign_feedback(campaign_id: str, milestone_index: int, feedback: dict) -> None:
        result_path = _campaign_root(campaign_id) / "milestones" / str(max(1, int(milestone_index) + 1)) / "result.json"
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

    def _campaign_result_payload(campaign_id: str, milestone_index: int) -> dict:
        result_path = _campaign_root(campaign_id) / "milestones" / str(max(1, int(milestone_index) + 1)) / "result.json"
        if not result_path.exists():
            return {}
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        return _normalize_campaign_milestone_row(data)

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

    def _apply_campaign_feedback_decision(
        campaign_id: str,
        milestone_index: int,
        feedback: dict,
        *,
        source: str,
    ) -> dict:
        result_path = _campaign_root(campaign_id) / "milestones" / str(max(1, int(milestone_index) + 1)) / "result.json"
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

    def _semantic_target_spec(target: str) -> tuple[str, Path]:
        t = str(target or "").strip().lower()
        if t in {"catalog", "capability_catalog"}:
            return "semantics.catalog", semantic_catalog_path
        if t in {"mapping_rules", "mapping-rules", "rules"}:
            return "semantics.mapping_rules", semantic_rules_path
        raise ValueError(f"unknown_semantic_target:{target}")

    def _sync_compass_provider_budgets_from_policy(policy: dict, *, overwrite: bool) -> dict:
        """Sync model_policy budget_limits into Compass provider budgets."""
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
            current = compass.get_budget(resource_type)
            if current and not overwrite:
                try:
                    if float(current.get("daily_limit") or 0) >= daily_limit:
                        continue
                except (TypeError, ValueError):
                    pass
            compass.set_budget(resource_type, daily_limit, changed_by="model_policy")
            touched.append({"resource_type": resource_type, "daily_limit": daily_limit})
        if touched:
            nerve.emit("fabric_updated", {"fabric": "compass", "key": "budget_limits_from_model_policy", "count": len(touched)})
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
        for key in ("by_capability", "by_semantic_cluster", "by_risk_level"):
            mapping = payload.get(key) if isinstance(payload.get(key), dict) else {}
            for k, v in mapping.items():
                alias = str(v or "").strip()
                if alias and alias not in aliases:
                    raise ValueError(f"model_policy.{key}[{k}] alias not found: {alias}")

    def _write_semantic_target(target: str, payload: dict, changed_by: str, reason: str) -> dict:
        cfg_key, path = _semantic_target_spec(target)
        if not isinstance(payload, dict):
            raise ValueError("payload_must_be_object")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        cv_version = compass.record_config_version(cfg_key, payload, changed_by=changed_by, reason=reason)
        # Keep runtime semantics consistent without restart.
        dispatch.reload_semantic_configs()
        if cfg_key == "semantics.catalog":
            clusters = payload.get("clusters") if isinstance(payload.get("clusters"), list) else []
            if clusters:
                playbook.seed_clusters(clusters)
        nerve.emit("fabric_updated", {"fabric": "semantics", "target": cfg_key, "path": str(path)})
        return {"ok": True, "target": cfg_key, "path": str(path), "config_version": cv_version}

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

    def _sandbox_gate_open() -> bool:
        v = str(compass.get_pref("skill_evolution.sandbox_gate", "open") or "open").strip().lower()
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
            if target_norm in {"catalog", "capability_catalog", "semantics.catalog"}:
                _write_semantic_target("catalog", payload, changed_by="skill_evolution", reason="auto_adopt_config_proposal")
                return True, ""
            if target_norm in {"mapping_rules", "rules", "semantics.mapping_rules"}:
                _write_semantic_target("mapping_rules", payload, changed_by="skill_evolution", reason="auto_adopt_config_proposal")
                return True, ""
            if target_norm in {"model_policy", "model-policy"}:
                aliases = _model_registry_aliases(json.loads(model_registry_path.read_text(encoding="utf-8")) if model_registry_path.exists() else {})
                _validate_model_policy(payload, aliases)
                payload["_updated"] = _utc()[:10]
                model_policy_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                compass.record_config_version("model_policy", payload, changed_by="skill_evolution", reason="auto_adopt_config_proposal")
                nerve.emit("fabric_updated", {"fabric": "model_policy", "path": str(model_policy_path)})
                return True, ""
            if target_norm in {"model_registry", "registry", "model-registry"}:
                _validate_model_registry(payload)
                payload["_updated"] = _utc()[:10]
                model_registry_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                compass.record_config_version("model_registry", payload, changed_by="skill_evolution", reason="auto_adopt_config_proposal")
                nerve.emit("fabric_updated", {"fabric": "model_registry", "path": str(model_registry_path)})
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
        store=store,
        dispatch=dispatch,
        cortex=cortex,
        model_policy_path=model_policy_path,
        model_registry_path=model_registry_path,
        openclaw_home=oc_home,
        validate_model_registry=_validate_model_registry,
        run_view=_run_view,
        log_portal_event=_log_portal_event,
        require_outcome_root=_require_outcome_root,
        memory=memory,
        playbook=playbook,
        compass=compass,
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
        drive_accounts=drive_accounts,
        log_portal_event=_log_portal_event,
    )

    register_submit_route(
        app,
        ensure_temporal_client=_ensure_temporal_client,
        dispatch=dispatch,
        log_portal_event=_log_portal_event,
    )

    console_ctx = type("ConsoleRouteContext", (), {})()
    console_ctx.logger = logger
    console_ctx.state = state
    console_ctx.oc_home = oc_home
    console_ctx.scheduler = scheduler
    console_ctx.registry = registry
    console_ctx.nerve = nerve
    console_ctx.memory = memory
    console_ctx.playbook = playbook
    console_ctx.compass = compass
    console_ctx.cortex = cortex
    console_ctx.tracer = tracer
    console_ctx.store = store
    console_ctx.dispatch = dispatch
    console_ctx.skill_queue_path = skill_queue_path
    console_ctx.utc = _utc
    console_ctx.sync_skill_proposals = _sync_skill_proposals
    console_ctx.write_json_list = _write_json_list
    console_ctx.sandbox_gate_open = _sandbox_gate_open
    console_ctx.apply_evolution_proposal = _apply_evolution_proposal
    console_ctx.semantic_catalog_path = semantic_catalog_path
    console_ctx.semantic_rules_path = semantic_rules_path
    console_ctx.model_policy_path = model_policy_path
    console_ctx.model_registry_path = model_registry_path
    console_ctx.semantic_target_spec = _semantic_target_spec
    console_ctx.write_semantic_target = _write_semantic_target
    console_ctx.validate_model_registry = _validate_model_registry
    console_ctx.validate_model_policy = _validate_model_policy
    console_ctx.model_registry_aliases = _model_registry_aliases
    console_ctx.sync_compass_provider_budgets_from_policy = _sync_compass_provider_budgets_from_policy

    register_console_spine_fabric_routes(app, ctx=console_ctx)
    register_console_strategy_model_routes(app, ctx=console_ctx)
    register_console_norm_routes(app, ctx=console_ctx)
    register_console_observe_routes(app, ctx=console_ctx)
    register_console_agents_skill_routes(app, ctx=console_ctx)

    campaign_ctx = type("CampaignRouteContext", (), {})()
    campaign_ctx.logger = logger
    campaign_ctx.state = state
    campaign_ctx.dispatch = dispatch
    campaign_ctx.telemetry_dir = telemetry_dir
    campaign_ctx.time_time = time.time
    campaign_ctx.utc = _utc
    campaign_ctx.ensure_temporal_client = _ensure_temporal_client
    campaign_ctx.get_temporal_client = lambda: temporal_client
    campaign_ctx.campaign_summaries = _campaign_summaries
    campaign_ctx.load_campaign_manifest = _load_campaign_manifest
    campaign_ctx.save_campaign_manifest = _save_campaign_manifest
    campaign_ctx.campaign_result_rows = _campaign_result_rows
    campaign_ctx.append_campaign_feedback = _append_campaign_feedback
    campaign_ctx.apply_campaign_feedback_decision = _apply_campaign_feedback_decision
    campaign_ctx.campaign_result_payload = _campaign_result_payload
    campaign_ctx.feedback_satisfied = _feedback_satisfied
    campaign_ctx.append_jsonl = _append_jsonl

    register_campaign_routes(app, ctx=campaign_ctx)
    register_chat_routes(app, dialog=dialog, log_portal_event=_log_portal_event)
    register_circuit_routes(app, ctx=console_ctx)

    # ── User feedback (Portal) ────────────────────────────────────────────────

    async def _get_feedback_questions(run_id: str):
        """Generate run-specific feedback questions via Cortex (LLM).
        Falls back to a minimal default set if Cortex is unavailable.
        """
        # Load run context.
        run_record: dict = {}
        try:
            runs = store.load_runs()
            run_record = next((r for r in runs if r.get("run_id") == run_id), {})
        except Exception:
            pass

        plan = run_record.get("plan") or {}
        title = str(plan.get("title") or run_id)
        run_type = str(plan.get("run_type") or "general")

        # Load outcome content snippet.
        content_snippet = ""
        try:
            outcome_root = _require_outcome_root()
            index = store.load_outcome_index(outcome_root)
            entry = next((e for e in reversed(index) if e.get("run_id") == run_id), None)
            if entry:
                out_path = outcome_root / str(entry["path"])
                for fname in ("report.md", "report.html"):
                    p = out_path / fname
                    if p.exists():
                        raw = p.read_text(encoding="utf-8", errors="ignore")
                        # Strip HTML tags if HTML.
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
            f"运行类型: {run_type}\n"
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

    async def _submit_feedback_internal(run_id: str, body: dict, request: Request | None = None) -> dict:
        source = str(body.get("source") or "portal")
        fb_type = str(body.get("type") or "quick").strip().lower()
        if fb_type not in {"quick", "deep", "append"}:
            fb_type = "quick"
        comment = str(body.get("comment") or "")[:1000].strip()
        aspects = body.get("aspects") if isinstance(body.get("aspects"), dict) else {}
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
            if fb_type == "quick" and rating is None:
                raise HTTPException(status_code=400, detail="quick_feedback_requires_rating")
            if fb_type == "deep" and rating is None and not comment:
                raise HTTPException(status_code=400, detail="deep_feedback_requires_comment_or_rating")

        # Find run record to get method_id and run_type.
        runs = store.load_runs()
        run_record = next((r for r in runs if r.get("run_id") == run_id), None)

        run_type = ""
        work_scale = ""
        method_id = ""
        if run_record:
            plan = run_record.get("plan") if isinstance(run_record.get("plan"), dict) else {}
            run_type = str(plan.get("run_type") or "")
            work_scale = str(plan.get("work_scale") or "")
            method_id = str(plan.get("method_id") or "")

        survey = _load_feedback_survey(run_id) or {"run_id": run_id}
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

        # Primary score feedback contributes to playbook exactly once per run.
        if first_scored_feedback and method_id:
            outcome = "success" if int(rating or 0) >= 3 else "failure"
            playbook.evaluate(
                method_id=method_id,
                run_id=run_id,
                outcome=outcome,
                score=score,
                detail={
                    "rating": rating,
                    "comment": comment,
                    "aspects": aspects,
                    "source": "user_feedback",
                    "feedback_type": fb_type,
                },
            )

        if first_scored_feedback and work_scale == "campaign":
            summary_zh = (
                f"Campaign运行用户反馈：rating={rating}/5；comment={comment or '无'}；"
                f"aspects={json.dumps(aspects, ensure_ascii=False)}"
            )
            summary_en = (
                f"Campaign final feedback: rating={rating}/5; comment={comment or 'n/a'}; "
                f"aspects={json.dumps(aspects, ensure_ascii=False)}"
            )
            try:
                memory.intake(
                    [
                        {
                            "title": f"Campaign feedback {run_id}",
                            "domain": "user_feedback",
                            "tier": "deep",
                            "confidence": 1.0,
                            "summary_zh": summary_zh,
                            "summary_en": summary_en,
                            "provider": "user",
                            "source_type": "human",
                            "source_agent": "user",
                        }
                    ],
                    actor=f"{source}.feedback",
                    source_type="human",
                    source_agent="user",
                )
            except Exception as exc:
                logger.warning("Failed to store campaign feedback into memory: %s", exc)

        # Persist feedback aspects as Compass prefs for the learning system.
        if aspects and run_type:
            for aspect_key, aspect_val in aspects.items():
                try:
                    v = float(aspect_val)
                    if 0.0 <= v <= 1.0:
                        compass.set_pref(
                            f"feedback.{run_type}.{aspect_key}",
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
                "source": source,
                "type": fb_type,
            }
        survey["status"] = "submitted"
        survey["submitted_utc"] = now
        survey["run_id"] = str(survey.get("run_id") or run_id)
        if source == "portal":
            survey["handled_channel"] = "portal"
            survey["telegram_reminder_suppressed"] = True
        _save_feedback_survey(run_id, survey)

        # Write to feedback JSONL.
        feedback_path = telemetry_dir / "outcome_feedback.jsonl"
        _append_jsonl(
            feedback_path,
            {
                "run_id": run_id,
                "type": "append" if is_append else fb_type,
                "source": source,
                "rating": rating,
                "score": score,
                "comment": comment,
                "aspects": aspects,
                "run_type": run_type,
                "work_scale": work_scale,
                "created_utc": now,
            },
        )

        if rating is not None:
            nerve.emit("user_feedback_received", {"run_id": run_id, "rating": rating, "score": score})
        if request is not None:
            _log_portal_event(
                "feedback_submitted" if not is_append else "feedback_appended",
                {"run_id": run_id, "rating": rating, "source": source},
                request,
            )
        return {
            "ok": True,
            "run_id": run_id,
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

    # ── Startup sync (model policy -> Compass provider budgets) ───────────────

    if model_policy_path.exists():
        try:
            policy = json.loads(model_policy_path.read_text(encoding="utf-8"))
            if isinstance(policy, dict):
                _sync_compass_provider_budgets_from_policy(policy, overwrite=False)
        except Exception as exc:
            logger.warning("Failed to sync provider budgets from model policy on startup: %s", exc)

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
