"""Daemon API — FastAPI application with Portal and Console routes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
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
from services.scheduler import Scheduler
from services.system_reset import SystemResetManager
from daemon_env import load_daemon_env


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
    task_queue = os.environ.get("TEMPORAL_TASK_QUEUE") or cfg.get("temporal", {}).get("task_queue", "daemon-queue")
    return {"host": host, "port": port, "namespace": namespace, "task_queue": task_queue}


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

    app = FastAPI(title="Daemon API", version="0.1.0")
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
                    task_queue=tc["task_queue"],
                )
                dispatch.set_temporal_client(temporal_client)
                logger.info(
                    "Temporal client connected host=%s port=%s namespace=%s queue=%s",
                    tc["host"], tc["port"], tc["namespace"], tc["task_queue"],
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
                            task_id = str(payload.get("task_id") or "")
                            if task_id:
                                survey = dict(payload)
                                survey.setdefault("status", "pending")
                                survey.setdefault("created_utc", _utc())
                                _save_feedback_survey(task_id, survey)
                                _append_jsonl(
                                    telemetry_dir / "feedback_surveys.jsonl",
                                    {"task_id": task_id, "event": "generated", "payload": survey, "created_utc": _utc()},
                                )
                                try:
                                    notify_result = await _notify_feedback_survey_telegram(survey)
                                    _append_jsonl(
                                        telemetry_dir / "feedback_surveys.jsonl",
                                        {
                                            "task_id": task_id,
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
                            phase = str(payload.get("phase") or "")
                            if phase in {"phase0_waiting_confirmation", "milestone_waiting_feedback", "delivery_failed"}:
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

    def _task_view(task: dict) -> dict:
        out = dict(task)
        plan = out.get("plan") if isinstance(out.get("plan"), dict) else {}
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

    def _feedback_survey_path(task_id: str) -> Path:
        return feedback_surveys_dir / f"{task_id}.json"

    def _load_feedback_survey(task_id: str) -> dict | None:
        path = _feedback_survey_path(task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _save_feedback_survey(task_id: str, payload: dict) -> None:
        path = _feedback_survey_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

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
        task_id = str(payload.get("task_id") or "")
        title = str(payload.get("title") or task_id)
        prompt = str(payload.get("prompt") or "请反馈本次交付质量。")
        task_scale = str(payload.get("task_scale") or "")
        message = (
            "📝 Daemon Feedback Survey\n\n"
            f"任务: `{task_id}`\n"
            f"规模: `{task_scale}`\n"
            f"标题: {title}\n\n"
            f"{prompt}\n"
            "请在 Portal 打开该任务并提交反馈。"
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
        status = str(payload.get("status") or "")
        score = payload.get("objective_score")
        attempts = int(payload.get("attempts") or 0)
        title = str(payload.get("title") or "")
        msg = (
            "📈 Campaign Progress\n\n"
            f"campaign: `{campaign_id}`\n"
            f"milestone: `{milestone_index + 1}` {title}\n"
            f"status: `{status}`\n"
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
        status = str(payload.get("status") or "")
        phase = str(payload.get("phase") or "")
        cur = int(payload.get("current_milestone_index") or 0)
        msg = (
            "📌 Campaign Status Update\n\n"
            f"campaign: `{campaign_id}`\n"
            f"status: `{status}`\n"
            f"phase: `{phase}`\n"
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

    def _load_campaign_manifest(campaign_id: str) -> dict | None:
        path = _campaign_root(campaign_id) / "manifest.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _save_campaign_manifest(campaign_id: str, manifest: dict) -> None:
        path = _campaign_root(campaign_id) / "manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

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
            rows.append(
                {
                    "campaign_id": str(data.get("campaign_id") or p.parent.name),
                    "task_id": str(data.get("task_id") or ""),
                    "title": str(data.get("title") or ""),
                    "status": str(data.get("status") or ""),
                    "current_phase": str(data.get("current_phase") or ""),
                    "current_milestone_index": int(data.get("current_milestone_index") or 0),
                    "total_milestones": int(data.get("total_milestones") or len(data.get("milestones") or [])),
                    "updated_utc": str(data.get("updated_utc") or ""),
                    "workflow_id": str(data.get("workflow_id") or ""),
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
                rows.append(data)
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
        return data if isinstance(data, dict) else {}

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
        if t in {"mapping_rules", "rules"}:
            return "semantics.mapping_rules", semantic_rules_path
        raise ValueError(f"unknown_semantic_target:{target}")

    def _model_target_spec(target: str) -> tuple[str, Path]:
        t = str(target or "").strip().lower()
        if t in {"policy", "model-policy", "model_policy"}:
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
            if target_norm in {"model_policy", "policy", "model-policy"}:
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

    # ── Health ────────────────────────────────────────────────────────────────

    @app.get("/health")
    async def health():
        await _ensure_temporal_client(retries=1, delay_s=0.1)
        gate_path = state / "gate.json"
        gate = {"status": "GREEN"}
        if gate_path.exists():
            try:
                gate = json.loads(gate_path.read_text())
            except Exception as exc:
                logger.warning("Failed to read gate.json: %s", exc)
        model_registry_valid = False
        if model_registry_path.exists():
            try:
                reg = json.loads(model_registry_path.read_text(encoding="utf-8"))
                if isinstance(reg, dict):
                    _validate_model_registry(reg)
                    model_registry_valid = True
            except Exception:
                model_registry_valid = False
        dependencies = {
            "temporal_connected": temporal_client is not None,
            "cortex_available": bool(cortex and cortex.is_available()),
            "model_policy_exists": model_policy_path.exists(),
            "model_registry_exists": (home / "config" / "model_registry.json").exists(),
            "model_registry_valid": model_registry_valid,
            "openclaw_config_exists": (oc_home / "openclaw.json").exists(),
        }
        dependencies_ready = (
            dependencies["cortex_available"]
            and dependencies["model_policy_exists"]
            and dependencies["model_registry_exists"]
            and dependencies["model_registry_valid"]
        )
        return {
            "ok": True,
            "gate": gate["status"],
            "dependencies": dependencies,
            "dependencies_ready": dependencies_ready,
        }

    # ── Console — System Reset ──────────────────────────────────────────────

    def _require_localhost(request: Request) -> str:
        host = request.client.host if request.client else ""
        if not host or (host not in {"127.0.0.1", "::1", "localhost"} and not host.startswith("127.")):
            raise HTTPException(status_code=403, detail="localhost_only")
        return host

    @app.post("/console/system/reset/challenge")
    async def system_reset_challenge(request: Request):
        host = _require_localhost(request)
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
        host = _require_localhost(request)
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
        _require_localhost(request)
        return reset_manager.last_report()

    # ── Portal — Integrations (Drive) ───────────────────────────────────────

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
            _log_portal_event(
                "drive_file_delete_failed",
                {"kind": kind, "path": path, "error": str(result.get("error") or "")},
                request,
            )
            raise HTTPException(status_code=400, detail=result)
        _log_portal_event(
            "drive_file_deleted",
            {"kind": kind, "path": path},
            request,
        )
        return result

    @app.get("/console/system/storage")
    def console_storage_status(request: Request):
        _require_localhost(request)
        return drive_accounts.integration_status()

    @app.put("/console/system/storage")
    async def console_storage_update(request: Request):
        _require_localhost(request)
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

    # ── Task submission (Portal) ───────────────────────────────────────────────

    @app.post("/submit")
    async def submit_task(request: Request):
        await _ensure_temporal_client(retries=3, delay_s=0.4)
        plan = await request.json()
        _log_portal_event(
            "submit_requested",
            {
                "task_type": plan.get("task_type", ""),
                "title": str(plan.get("title", ""))[:120],
                "priority": plan.get("priority"),
            },
            request,
        )
        result = await dispatch.submit(plan)
        if not result.get("ok"):
            code = str(result.get("error_code") or "")
            _log_portal_event("submit_failed", {"error_code": code, "task_id": result.get("task_id", "")}, request)
            if code.startswith("temporal_"):
                raise HTTPException(status_code=503, detail=result)
            if code in {"invalid_plan", "semantic_mapping_failed", "strategy_guard_blocked"}:
                raise HTTPException(status_code=400, detail=result)
            raise HTTPException(status_code=500, detail=result)
        _log_portal_event("submit_ok", {"task_id": result.get("task_id", ""), "status": result.get("status", "")}, request)
        return result

    @app.get("/tasks")
    def list_tasks(request: Request, status: str | None = None, limit: int = 50):
        tasks_path = state / "tasks.json"
        if not tasks_path.exists():
            _log_portal_event("tasks_list", {"status": status, "count": 0}, request)
            return []
        try:
            tasks = json.loads(tasks_path.read_text())
        except Exception as exc:
            logger.warning("Failed to read tasks.json: %s", exc)
            return []
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        result = [_task_view(t) for t in tasks[-limit:]]
        _log_portal_event("tasks_list", {"status": status, "count": len(result)}, request)
        return result

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str, request: Request):
        tasks_path = state / "tasks.json"
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read tasks.json: %s", exc)
            tasks = []
        for t in tasks:
            if t.get("task_id") == task_id:
                _log_portal_event("task_get", {"task_id": task_id, "status": t.get("status", "")}, request)
                return _task_view(t)
        _log_portal_event("task_not_found", {"task_id": task_id}, request)
        raise HTTPException(status_code=404, detail="task not found")

    # ── Campaigns ────────────────────────────────────────────────────────────

    @app.get("/campaigns")
    def list_campaigns(limit: int = 200):
        return _campaign_summaries(limit=limit)

    @app.get("/campaigns/{campaign_id}")
    def get_campaign(campaign_id: str, result_limit: int = 200):
        manifest = _load_campaign_manifest(campaign_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="campaign not found")
        return {
            "manifest": manifest,
            "milestone_results": _campaign_result_rows(campaign_id, limit=result_limit),
        }

    @app.post("/campaigns/{campaign_id}/resume")
    async def resume_campaign(campaign_id: str, request: Request):
        manifest = _load_campaign_manifest(campaign_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="campaign not found")

        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        status = str(manifest.get("status") or "").lower()
        if status in {"completed", "cancelled"}:
            raise HTTPException(status_code=409, detail={"ok": False, "error": f"campaign_not_resumable:{status}"})

        current_idx = int(manifest.get("current_milestone_index") or 0)
        resume_from = int(body.get("resume_from") or current_idx)
        resume_from = max(0, min(resume_from, int(manifest.get("total_milestones") or current_idx)))
        phase = str(manifest.get("current_phase") or "").strip().lower()
        confirmed = bool(body.get("confirmed") or body.get("campaign_confirmed"))
        if phase == "phase0_waiting_confirmation" and not confirmed:
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error": "campaign_confirmation_required", "phase": phase},
            )

        feedback = body.get("feedback")
        decision_payload: dict[str, Any] | None = None
        if isinstance(feedback, dict):
            _append_campaign_feedback(campaign_id, current_idx, feedback)
            decision_payload = _apply_campaign_feedback_decision(campaign_id, current_idx, feedback, source="resume_api")

        # Milestone waiting feedback gate must have an accepted decision.
        if phase == "milestone_waiting_feedback":
            result_payload = _campaign_result_payload(campaign_id, current_idx)
            decision_row = result_payload.get("user_feedback_decision") if isinstance(result_payload.get("user_feedback_decision"), dict) else {}
            if decision_payload and bool(decision_payload.get("accepted")):
                decision_row = decision_payload.get("decision") if isinstance(decision_payload.get("decision"), dict) else decision_row
            if not isinstance(decision_row, dict) or not decision_row:
                raise HTTPException(
                    status_code=409,
                    detail={"ok": False, "error": "campaign_milestone_feedback_required", "milestone_index": current_idx},
                )
            decision_feedback = decision_row.get("feedback") if isinstance(decision_row.get("feedback"), dict) else {}
            if _feedback_satisfied(decision_feedback):
                resume_from = max(resume_from, current_idx + 1)
            else:
                resume_from = current_idx

        base_plan = manifest.get("plan") if isinstance(manifest.get("plan"), dict) else {}
        if not base_plan:
            raise HTTPException(status_code=409, detail={"ok": False, "error": "campaign_plan_missing"})
        await _ensure_temporal_client(retries=3, delay_s=0.4)
        if not temporal_client:
            raise HTTPException(status_code=503, detail={"ok": False, "error_code": "temporal_unavailable"})

        task_id = str(body.get("task_id") or f"{manifest.get('task_id', 'task')}_resume_{int(time.time())}")
        run_root = str(state / "runs" / task_id)
        run_index = int(manifest.get("run_index") or 0) + 1
        workflow_id = f"daemon-campaign-{campaign_id}-r{run_index}"

        plan = dict(base_plan)
        plan["task_id"] = task_id
        plan["campaign_id"] = campaign_id
        plan["campaign_resume_from"] = resume_from
        plan["campaign_run_index"] = run_index
        plan["_workflow_id"] = workflow_id
        plan["task_scale"] = "campaign"
        plan["campaign_confirmed"] = True

        if phase == "milestone_waiting_feedback":
            result_payload = _campaign_result_payload(campaign_id, current_idx)
            decision_row = result_payload.get("user_feedback_decision") if isinstance(result_payload.get("user_feedback_decision"), dict) else {}
            decision_feedback = decision_row.get("feedback") if isinstance(decision_row.get("feedback"), dict) else {}
            satisfied = _feedback_satisfied(decision_feedback)
            plan["campaign_feedback_milestone_index"] = current_idx
            plan["campaign_feedback_satisfied"] = satisfied
            plan["campaign_feedback_comment"] = str(decision_feedback.get("comment") or "")
            plan["campaign_force_user_rework"] = not satisfied

        dispatch._record_task(plan, "running", run_root)
        try:
            await temporal_client.submit(
                workflow_id=workflow_id,
                plan=plan,
                run_root=run_root,
                workflow_name="CampaignWorkflow",
            )
        except Exception as exc:
            dispatch._record_task({**plan, "last_error": str(exc)[:300]}, "failed_submission", run_root)
            raise HTTPException(
                status_code=503,
                detail={"ok": False, "error_code": "temporal_submit_failed", "error": str(exc)[:300]},
            )

        manifest["status"] = "running"
        manifest["current_phase"] = "resume_requested"
        manifest["current_milestone_index"] = resume_from
        manifest["workflow_id"] = workflow_id
        manifest["run_index"] = run_index
        if phase == "phase0_waiting_confirmation":
            manifest["confirmed_utc"] = _utc()
        manifest["updated_utc"] = _utc()
        _save_campaign_manifest(campaign_id, manifest)
        return {
            "ok": True,
            "campaign_id": campaign_id,
            "workflow_id": workflow_id,
            "task_id": task_id,
            "resume_from": resume_from,
        }

    @app.post("/campaigns/{campaign_id}/confirm")
    async def confirm_campaign(campaign_id: str):
        manifest = _load_campaign_manifest(campaign_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="campaign not found")
        phase = str(manifest.get("current_phase") or "").strip().lower()
        if phase != "phase0_waiting_confirmation":
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error": f"campaign_confirm_not_allowed_in_phase:{phase}"},
            )
        # Reuse resume endpoint semantics with explicit confirmation.
        class _Req:
            async def json(self):
                return {"confirmed": True}
        return await resume_campaign(campaign_id, _Req())  # type: ignore[arg-type]

    @app.post("/campaigns/{campaign_id}/milestones/{milestone_index}/feedback")
    async def campaign_milestone_feedback(campaign_id: str, milestone_index: int, request: Request):
        manifest = _load_campaign_manifest(campaign_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="campaign not found")
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}
        source = str(body.get("source") or "portal")
        feedback = body.get("feedback") if isinstance(body.get("feedback"), dict) else {
            "rating": body.get("rating"),
            "satisfied": body.get("satisfied"),
            "comment": str(body.get("comment") or ""),
        }
        result = _apply_campaign_feedback_decision(
            campaign_id,
            int(milestone_index),
            feedback,
            source=source,
        )
        _append_jsonl(
            telemetry_dir / "campaign_feedback.jsonl",
            {
                "campaign_id": campaign_id,
                "milestone_index": int(milestone_index),
                "source": source,
                "accepted": bool(result.get("accepted")),
                "feedback": feedback,
                "created_utc": _utc(),
            },
        )
        return {
            "ok": True,
            "campaign_id": campaign_id,
            "milestone_index": int(milestone_index),
            "accepted": bool(result.get("accepted")),
            "decision": result.get("decision", {}),
        }

    @app.post("/campaigns/{campaign_id}/cancel")
    async def cancel_campaign(campaign_id: str):
        manifest = _load_campaign_manifest(campaign_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="campaign not found")
        workflow_id = str(manifest.get("workflow_id") or "")
        await _ensure_temporal_client(retries=2, delay_s=0.3)
        if temporal_client and workflow_id:
            try:
                await temporal_client.cancel(workflow_id)
            except Exception as exc:
                logger.warning("Campaign cancel failed workflow_id=%s: %s", workflow_id, exc)
        manifest["status"] = "cancelled"
        manifest["current_phase"] = "cancelled"
        manifest["updated_utc"] = _utc()
        _save_campaign_manifest(campaign_id, manifest)
        return {"ok": True, "campaign_id": campaign_id, "workflow_id": workflow_id, "status": "cancelled"}

    # ── Chat (Portal) ─────────────────────────────────────────────────────────

    @app.post("/chat/session")
    def new_chat_session(request: Request):
        sid = dialog.new_session()
        _log_portal_event("chat_session_created", {"session_id": sid}, request)
        return {"session_id": sid}

    @app.post("/chat/{session_id}")
    async def chat(session_id: str, request: Request):
        body = await request.json()
        message = str(body.get("message") or "")
        if not message:
            raise HTTPException(status_code=400, detail="message required")
        _log_portal_event("chat_message", {"session_id": session_id, "message_len": len(message)}, request)
        result = dialog.chat(session_id, message)
        if not result.get("ok"):
            _log_portal_event("chat_failed", {"session_id": session_id, "error": result.get("error", "")}, request)
            raise HTTPException(status_code=502, detail=result.get("error"))
        _log_portal_event(
            "chat_ok",
            {"session_id": session_id, "has_plan": bool(result.get("plan")), "response_len": len(str(result.get("content") or ""))},
            request,
        )
        return result

    # ── Outcome (Portal) ──────────────────────────────────────────────────────

    @app.get("/outcome")
    def list_outcomes(request: Request, limit: int = 50):
        outcome_root = _require_outcome_root()
        index_path = outcome_root / "index.json"
        try:
            index = json.loads(index_path.read_text()) if index_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read outcome index: %s", exc)
            index = []
        _log_portal_event("outcome_list", {"limit": limit, "count": min(len(index), limit)}, request)
        return list(reversed(index))[:limit]

    @app.get("/outcome/timeline")
    def outcome_timeline(request: Request, days: int = 30, limit_per_day: int = 50):
        outcome_root = _require_outcome_root()
        index_path = outcome_root / "index.json"
        try:
            index = json.loads(index_path.read_text()) if index_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read outcome index for timeline: %s", exc)
            index = []

        limit_days = max(1, min(days, 365))
        per_day = max(1, min(limit_per_day, 200))

        # Sort by delivered timestamp descending.
        entries = []
        for item in index:
            ts = str(item.get("delivered_utc") or item.get("archived_utc") or "")
            day_key = ts[:10] if len(ts) >= 10 else "unknown"
            entries.append(
                {
                    "path": item.get("path", ""),
                    "title": item.get("title", ""),
                    "task_type": item.get("task_type", ""),
                    "task_id": item.get("task_id", ""),
                    "delivered_utc": ts,
                    "day": day_key,
                }
            )
        entries.sort(key=lambda x: x.get("delivered_utc", ""), reverse=True)

        grouped: dict[str, list[dict]] = {}
        for entry in entries:
            day = str(entry.get("day") or "unknown")
            grouped.setdefault(day, [])
            if len(grouped[day]) < per_day:
                grouped[day].append(entry)

        days_sorted = sorted(grouped.keys(), reverse=True)[:limit_days]
        out = [
            {
                "day": day,
                "count": len(grouped.get(day, [])),
                "items": grouped.get(day, []),
            }
            for day in days_sorted
        ]
        _log_portal_event("outcome_timeline", {"days": limit_days, "groups": len(out)}, request)
        return {"days": out}

    @app.get("/outcome/{path:path}")
    def get_outcome_file(path: str, request: Request):
        outcome_root = _require_outcome_root()
        full = outcome_root / path
        try:
            full.resolve().relative_to(outcome_root.resolve())
        except Exception:
            raise HTTPException(status_code=400, detail="path_outside_outcome_root")
        if not full.exists():
            _log_portal_event("outcome_file_missing", {"path": path}, request)
            raise HTTPException(status_code=404)
        _log_portal_event("outcome_file_access", {"path": path}, request)
        return FileResponse(full)

    # ── User feedback (Portal) ────────────────────────────────────────────────

    @app.get("/feedback/pending")
    def list_pending_feedback(limit: int = 100):
        return _pending_feedback_surveys(limit=limit)

    @app.get("/feedback/{task_id}/questions")
    async def get_feedback_questions(task_id: str):
        """Generate task-specific feedback questions via Cortex (LLM).
        Falls back to a minimal default set if Cortex is unavailable.
        """
        # Load task context.
        tasks_path = state / "tasks.json"
        task_record: dict = {}
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
            task_record = next((t for t in tasks if t.get("task_id") == task_id), {})
        except Exception:
            pass

        plan = task_record.get("plan") or {}
        title = str(plan.get("title") or task_id)
        task_type = str(plan.get("task_type") or "general")

        # Load outcome content snippet.
        content_snippet = ""
        try:
            outcome_root = _require_outcome_root()
            index_path = outcome_root / "index.json"
            index = json.loads(index_path.read_text()) if index_path.exists() else []
            entry = next((e for e in reversed(index) if e.get("task_id") == task_id), None)
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
            "你是一个AI产出评估专家。根据以下任务信息，生成3-4个针对性反馈问题。\n\n"
            f"任务类型: {task_type}\n"
            f"任务标题: {title}\n"
        )
        if content_snippet:
            prompt += f"内容摘要（前800字）:\n{content_snippet}\n\n"
        prompt += (
            "要求：\n"
            "1. 第一个问题必须是整体满意度（key=\"overall\", isRating=true），选项val为整数1-5\n"
            "2. 其余2-3个问题根据这份产出的具体内容和任务类型量身定制，不要用泛泛的通用问题\n"
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

    @app.post("/feedback/{task_id}")
    async def submit_feedback(task_id: str, request: Request):
        """Record user rating on a delivered outcome. Feeds back into Playbook evaluation."""
        body = await request.json()
        rating = body.get("rating")
        try:
            rating = int(rating)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="rating must be an integer 1-5")
        if not (1 <= rating <= 5):
            raise HTTPException(status_code=400, detail="rating must be 1-5")

        comment = str(body.get("comment") or "")[:500]
        aspects = body.get("aspects") or {}

        # Find task record to get method_id and task_type.
        tasks_path = state / "tasks.json"
        tasks = []
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read tasks.json for feedback: %s", exc)
        task_record = next((t for t in tasks if t.get("task_id") == task_id), None)

        score = rating / 5.0
        task_type = ""
        task_scale = ""
        if task_record:
            plan = task_record.get("plan") or {}
            task_type = str(plan.get("task_type") or "")
            task_scale = str(plan.get("task_scale") or "")
            method_id = plan.get("method_id")
            if method_id:
                outcome = "success" if rating >= 3 else "failure"
                playbook.evaluate(
                    method_id=method_id,
                    task_id=task_id,
                    outcome=outcome,
                    score=score,
                    detail={"rating": rating, "comment": comment, "aspects": aspects, "source": "user_feedback"},
                )

            if task_scale == "campaign":
                summary_zh = (
                    f"Campaign任务用户反馈：rating={rating}/5；comment={comment or '无'}；"
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
                                "title": f"Campaign feedback {task_id}",
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
                        actor="portal.feedback",
                        source_type="human",
                        source_agent="user",
                    )
                except Exception as exc:
                    logger.warning("Failed to store campaign feedback into memory: %s", exc)

        # Persist feedback aspects as Compass prefs for the learning system.
        if aspects and task_type:
            for aspect_key, aspect_val in aspects.items():
                try:
                    v = float(aspect_val)
                    if 0.0 <= v <= 1.0:
                        compass.set_pref(
                            f"feedback.{task_type}.{aspect_key}", str(round(v, 4)),
                            source="user_feedback", changed_by="user",
                        )
                except (TypeError, ValueError):
                    pass

        # Write to feedback JSONL.
        feedback_path = telemetry_dir / "outcome_feedback.jsonl"
        _append_jsonl(feedback_path, {
            "task_id": task_id,
            "rating": rating,
            "score": score,
            "comment": comment,
            "aspects": aspects,
            "task_type": task_type,
            "task_scale": task_scale,
            "created_utc": _utc(),
        })

        survey = _load_feedback_survey(task_id)
        if survey:
            survey["status"] = "submitted"
            survey["submitted_utc"] = _utc()
            survey["response"] = {
                "rating": rating,
                "score": score,
                "comment": comment,
                "aspects": aspects,
            }
            _save_feedback_survey(task_id, survey)

        nerve.emit("user_feedback_received", {"task_id": task_id, "rating": rating, "score": score})
        _log_portal_event("feedback_submitted", {"task_id": task_id, "rating": rating}, request)
        return {"ok": True, "task_id": task_id, "score": score}

    # ── Console — System overview ──────────────────────────────────────────────

    @app.get("/console/overview")
    def console_overview():
        gate_path = state / "gate.json"
        gate = {"status": "GREEN"}
        if gate_path.exists():
            try:
                gate = json.loads(gate_path.read_text())
            except Exception as exc:
                logger.warning("Failed to read gate.json: %s", exc)
        tasks_path = state / "tasks.json"
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read tasks.json: %s", exc)
            tasks = []
        running = [t for t in tasks if t.get("status") == "running"]
        return {
            "gate": gate,
            "running_tasks": len(running),
            "memory": memory.stats(),
            "playbook": playbook.stats(),
            "compass": compass.stats(),
            "cortex_usage": cortex.usage_today(),
        }

    # ── Console — Spine ───────────────────────────────────────────────────────

    @app.get("/console/spine/status")
    def spine_status():
        return scheduler.status()

    @app.get("/console/spine/dependencies")
    def spine_dependencies():
        out = []
        for rdef in registry.all():
            out.append(
                {
                    "routine": rdef.name,
                    "depends_on": list(rdef.depends_on or []),
                    "reads": list(rdef.reads or []),
                    "writes": list(rdef.writes or []),
                    "mode": rdef.mode,
                }
            )
        return out

    @app.post("/console/spine/{routine}/trigger")
    async def spine_trigger(routine: str):
        full_name = routine if routine.startswith("spine.") else f"spine.{routine}"
        result = await scheduler.trigger(full_name)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error"))
        return result

    @app.get("/console/spine/nerve/events")
    def nerve_events(limit: int = 50):
        return nerve.recent(limit)

    # ── Console — Fabric ──────────────────────────────────────────────────────

    @app.get("/console/fabric/memory")
    def fabric_memory(
        domain: str | None = None,
        tier: str | None = None,
        since: str | None = None,
        keyword: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
    ):
        return memory.query(domain=domain, tier=tier, since=since, keyword=keyword, source_type=source_type, limit=limit)

    @app.get("/console/fabric/memory/{unit_id}")
    def fabric_memory_unit(unit_id: str):
        unit = memory.get(unit_id)
        if not unit:
            raise HTTPException(status_code=404)
        return unit

    @app.get("/console/fabric/playbook")
    def fabric_playbook(status: str | None = None, category: str = "dag_pattern"):
        return playbook.list_methods(status=status, category=category, limit=200)

    @app.get("/console/fabric/playbook/{method_id}")
    def fabric_playbook_method(method_id: str):
        m = playbook.get(method_id)
        if not m:
            raise HTTPException(status_code=404)
        return m

    @app.get("/console/fabric/compass/priorities")
    def compass_priorities():
        return compass.get_priorities()

    @app.get("/console/fabric/compass/budgets")
    def compass_budgets():
        return compass.all_budgets()

    @app.get("/console/fabric/compass/signals")
    def compass_signals():
        return compass.active_signals()

    # ── Console — Strategy / Semantics / Model Control Plane ────────────────

    @app.get("/console/strategies")
    def list_strategies(cluster_id: str | None = None, stage: str | None = None):
        strategies = playbook.list_strategies(cluster_id=cluster_id, stage=stage)
        cluster_rows = {row.get("cluster_id", ""): row for row in playbook.list_clusters()}
        for row in strategies:
            cid = str(row.get("cluster_id") or "")
            cluster = cluster_rows.get(cid) or {}
            row["cluster_display_name"] = cluster.get("display_name", cid)
            row["task_type_compat"] = cluster.get("task_type_compat", "")
            sid = str(row.get("strategy_id") or "")
            if not sid:
                row["risk_level"] = "unknown"
                row["risk_reasons"] = []
                row["release_audit_closed"] = False
                continue
            try:
                audit = playbook.strategy_audit_status(sid)
            except Exception:
                row["risk_level"] = "high"
                row["risk_reasons"] = ["audit_lookup_failed"]
                row["release_audit_closed"] = False
                continue
            missing_checks = audit.get("missing_checks") if isinstance(audit.get("missing_checks"), list) else []
            missing_count = len(missing_checks)
            if missing_count == 0:
                risk_level = "low"
            elif missing_count <= 2:
                risk_level = "medium"
            else:
                risk_level = "high"
            row["release_audit_closed"] = bool(audit.get("release_audit_closed", False))
            row["risk_level"] = risk_level
            row["risk_reasons"] = missing_checks
        return strategies

    @app.get("/console/strategies/shadow-report")
    def shadow_report(limit: int = 200):
        path = state / "telemetry" / "shadow_comparisons.jsonl"
        if not path.exists():
            return []
        rows: list[dict] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception as exc:
            logger.warning("Failed to read shadow report file: %s", exc)
            return []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
            if len(rows) >= max(1, min(limit, 2000)):
                break
        return rows

    @app.post("/console/strategies/{strategy_id}/promote")
    async def promote_strategy(strategy_id: str, request: Request):
        body = await request.json()
        next_stage = str(body.get("next_stage") or "champion")
        reason = str(body.get("reason") or "")
        decided_by = str(body.get("decided_by") or "console")
        row = playbook.get_strategy(strategy_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy not found")
        prev_stage = str(row.get("stage") or "candidate")
        try:
            promotion_id = playbook.promote_strategy(
                strategy_id=strategy_id,
                decision="promote_manual",
                prev_stage=prev_stage,
                next_stage=next_stage,
                reason=reason,
                decided_by=decided_by,
            )
        except ValueError as exc:
            msg = str(exc)
            if msg.startswith("invalid_stage_transition:"):
                raise HTTPException(
                    status_code=409,
                    detail={"ok": False, "error_code": "invalid_stage_transition", "error": msg},
                )
            if msg.startswith("promotion_audit_incomplete:"):
                raise HTTPException(
                    status_code=409,
                    detail={"ok": False, "error_code": "strategy_guard_blocked", "error": msg},
                )
            raise HTTPException(status_code=400, detail={"ok": False, "error": msg})
        nerve.emit(
            "strategy_promoted",
            {"strategy_id": strategy_id, "prev_stage": prev_stage, "next_stage": next_stage, "promotion_id": promotion_id},
        )
        return {"ok": True, "strategy_id": strategy_id, "promotion_id": promotion_id, "prev_stage": prev_stage, "next_stage": next_stage}

    @app.post("/console/strategies/{strategy_id}/rollback")
    async def rollback_strategy(strategy_id: str, request: Request):
        body = await request.json()
        reason = str(body.get("reason") or "manual_rollback")
        decided_by = str(body.get("decided_by") or "console")
        row = playbook.get_strategy(strategy_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy not found")
        target = playbook.resolve_latest_rollback_target(strategy_id)
        if not target:
            raise HTTPException(
                status_code=409,
                detail={
                    "ok": False,
                    "error_code": "strategy_guard_blocked",
                    "error": "rollback_point_missing_or_previous_champion_unavailable",
                },
            )
        prev = target.get("previous_strategy") if isinstance(target.get("previous_strategy"), dict) else {}
        rollback_to_strategy_id = str(target.get("previous_champion_strategy_id") or "")
        prev_stage = str(prev.get("stage") or "unknown")
        if not rollback_to_strategy_id:
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error_code": "strategy_guard_blocked", "error": "rollback_target_missing"},
            )
        if prev_stage == "retired":
            raise HTTPException(
                status_code=409,
                detail={"ok": False, "error_code": "strategy_guard_blocked", "error": "rollback_target_retired"},
            )
        try:
            promotion_id = playbook.promote_strategy(
                strategy_id=rollback_to_strategy_id,
                decision="rollback_manual",
                prev_stage=prev_stage,
                next_stage="champion",
                reason=f"{reason};rollback_from:{strategy_id}",
                decided_by=decided_by,
            )
        except ValueError as exc:
            msg = str(exc)
            if msg.startswith("invalid_stage_transition:"):
                raise HTTPException(
                    status_code=409,
                    detail={"ok": False, "error_code": "invalid_stage_transition", "error": msg},
                )
            raise HTTPException(status_code=400, detail={"ok": False, "error": msg})
        nerve.emit(
            "strategy_rolled_back",
            {
                "from_strategy_id": strategy_id,
                "to_strategy_id": rollback_to_strategy_id,
                "prev_stage": prev_stage,
                "next_stage": "champion",
                "promotion_id": promotion_id,
            },
        )
        return {
            "ok": True,
            "strategy_id": strategy_id,
            "rollback_to_strategy_id": rollback_to_strategy_id,
            "promotion_id": promotion_id,
            "prev_stage": prev_stage,
            "next_stage": "champion",
        }

    @app.get("/console/strategies/{strategy_id}/experiments")
    def strategy_experiments(strategy_id: str, limit: int = 200):
        row = playbook.get_strategy(strategy_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy not found")
        return playbook.list_experiments(strategy_id=strategy_id, limit=limit)

    @app.get("/console/strategies/{strategy_id}/promotions")
    def strategy_promotions(strategy_id: str, limit: int = 200):
        row = playbook.get_strategy(strategy_id)
        if not row:
            raise HTTPException(status_code=404, detail="strategy not found")
        return playbook.list_promotions(strategy_id=strategy_id, limit=limit)

    @app.get("/console/strategies/{strategy_id}/audit")
    def strategy_audit(strategy_id: str):
        try:
            return playbook.strategy_audit_status(strategy_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="strategy not found")

    @app.get("/console/strategies/release-events")
    def strategy_release_events(strategy_id: str | None = None, cluster_id: str | None = None, limit: int = 500):
        return playbook.list_release_transitions(strategy_id=strategy_id, cluster_id=cluster_id, limit=limit)

    @app.get("/console/strategies/rollback-points")
    def strategy_rollback_points(cluster_id: str | None = None, limit: int = 200):
        return playbook.list_rollback_points(cluster_id=cluster_id, limit=limit)

    @app.post("/console/strategies/{strategy_id}/sandbox-submit")
    async def strategy_sandbox_submit(strategy_id: str, request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="sandbox plan body must be a JSON object")
        result = await dispatch.submit_sandbox(body, strategy_id=strategy_id)
        if not result.get("ok"):
            code = str(result.get("error_code") or "")
            if code in {"invalid_plan", "semantic_mapping_failed", "strategy_guard_blocked", "strategy_not_found"}:
                raise HTTPException(status_code=400, detail=result)
            if code.startswith("temporal_"):
                raise HTTPException(status_code=503, detail=result)
            raise HTTPException(status_code=500, detail=result)
        return result

    @app.get("/console/semantics")
    def console_semantics():
        catalog = {}
        rules = {}
        try:
            catalog = json.loads(semantic_catalog_path.read_text(encoding="utf-8")) if semantic_catalog_path.exists() else {}
        except Exception as exc:
            logger.warning("Failed to load semantic catalog: %s", exc)
        try:
            rules = json.loads(semantic_rules_path.read_text(encoding="utf-8")) if semantic_rules_path.exists() else {}
        except Exception as exc:
            logger.warning("Failed to load semantic mapping rules: %s", exc)
        return {
            "catalog": catalog,
            "mapping_rules": rules,
            "clusters_db": playbook.list_clusters(),
        }

    @app.put("/console/semantics/catalog")
    async def set_semantic_catalog(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="catalog body must be a JSON object")
        try:
            return _write_semantic_target("catalog", body, changed_by="console", reason="semantic_catalog_update")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})

    @app.put("/console/semantics/mapping-rules")
    async def set_semantic_rules(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="mapping rules body must be a JSON object")
        try:
            return _write_semantic_target("mapping_rules", body, changed_by="console", reason="semantic_mapping_rules_update")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})

    @app.get("/console/semantics/{target}/versions")
    def semantic_versions(target: str, limit: int = 50):
        try:
            cfg_key, _ = _semantic_target_spec(target)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return compass.versions(cfg_key, limit=max(1, min(limit, 200)))

    @app.post("/console/semantics/{target}/rollback/{version}")
    def semantic_rollback(target: str, version: int):
        try:
            cfg_key, _ = _semantic_target_spec(target)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        value = compass.version_value(cfg_key, version)
        if value is None or not isinstance(value, dict):
            raise HTTPException(status_code=404, detail="semantic config version not found")
        try:
            result = _write_semantic_target(target, value, changed_by="console", reason=f"rollback_to:{version}")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc)})
        result["rolled_back_to"] = version
        return result

    @app.get("/console/model-policy")
    def get_model_policy():
        if not model_policy_path.exists():
            return {}
        try:
            return json.loads(model_policy_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read model policy: %s", exc)
            raise HTTPException(status_code=500, detail="model policy parse failed")

    @app.get("/console/model-registry")
    def get_model_registry():
        if not model_registry_path.exists():
            return {}
        try:
            data = json.loads(model_registry_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _validate_model_registry(data)
            return data
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=f"model registry invalid: {exc}")
        except Exception as exc:
            logger.warning("Failed to read model registry: %s", exc)
            raise HTTPException(status_code=500, detail="model registry parse failed")

    @app.put("/console/model-policy")
    async def set_model_policy(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="policy body must be a JSON object")
        registry = {}
        if model_registry_path.exists():
            try:
                registry = json.loads(model_registry_path.read_text(encoding="utf-8"))
                if isinstance(registry, dict):
                    _validate_model_registry(registry)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail={"ok": False, "error": f"model_registry_invalid:{exc}"})
            except Exception as exc:
                raise HTTPException(status_code=400, detail={"ok": False, "error": f"model_registry_unreadable:{exc}"})
        aliases = _model_registry_aliases(registry if isinstance(registry, dict) else {})
        try:
            _validate_model_policy(body, aliases)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc), "error_code": "invalid_model_policy"})
        current = {}
        if model_policy_path.exists():
            try:
                current = json.loads(model_policy_path.read_text(encoding="utf-8"))
            except Exception:
                current = {}
        version = str(body.get("_version") or current.get("_version") or "1.0.0")
        body["_version"] = version
        body["_updated"] = _utc()[:10]
        model_policy_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        cv_version = compass.record_config_version("model_policy", body, changed_by="console", reason="model_policy_update")
        nerve.emit("fabric_updated", {"fabric": "model_policy", "path": str(model_policy_path)})
        return {"ok": True, "path": str(model_policy_path), "_version": version, "config_version": cv_version}

    @app.put("/console/model-registry")
    async def set_model_registry(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="registry body must be a JSON object")
        try:
            _validate_model_registry(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc), "error_code": "invalid_model_registry"})
        aliases = _model_registry_aliases(body)
        current_policy = {}
        if model_policy_path.exists():
            try:
                current_policy = json.loads(model_policy_path.read_text(encoding="utf-8"))
            except Exception:
                current_policy = {}
        if isinstance(current_policy, dict) and current_policy:
            try:
                _validate_model_policy(current_policy, aliases)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"ok": False, "error": str(exc), "error_code": "model_policy_incompatible_with_registry"},
                )
        body["_updated"] = _utc()[:10]
        model_registry_path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        cv_version = compass.record_config_version("model_registry", body, changed_by="console", reason="model_registry_update")
        nerve.emit("fabric_updated", {"fabric": "model_registry", "path": str(model_registry_path)})
        return {"ok": True, "path": str(model_registry_path), "config_version": cv_version}

    @app.get("/console/model-policy/versions")
    def model_policy_versions(limit: int = 50):
        return compass.versions("model_policy", limit=max(1, min(limit, 200)))

    @app.get("/console/model-registry/versions")
    def model_registry_versions(limit: int = 50):
        return compass.versions("model_registry", limit=max(1, min(limit, 200)))

    @app.post("/console/model-policy/rollback/{version}")
    def model_policy_rollback(version: int):
        value = compass.version_value("model_policy", version)
        if value is None or not isinstance(value, dict):
            raise HTTPException(status_code=404, detail="model policy version not found")
        registry = {}
        if model_registry_path.exists():
            try:
                registry = json.loads(model_registry_path.read_text(encoding="utf-8"))
                if isinstance(registry, dict):
                    _validate_model_registry(registry)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"model registry invalid: {exc}")
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"model registry unreadable: {exc}")
        aliases = _model_registry_aliases(registry if isinstance(registry, dict) else {})
        try:
            _validate_model_policy(value, aliases)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"ok": False, "error": str(exc), "error_code": "invalid_model_policy"},
            )
        value["_updated"] = _utc()[:10]
        model_policy_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        cv_version = compass.record_config_version("model_policy", value, changed_by="console", reason=f"rollback_to:{version}")
        nerve.emit("fabric_updated", {"fabric": "model_policy", "path": str(model_policy_path), "rollback_from_version": version})
        return {"ok": True, "rolled_back_to": version, "config_version": cv_version}

    @app.post("/console/model-registry/rollback/{version}")
    def model_registry_rollback(version: int):
        value = compass.version_value("model_registry", version)
        if value is None or not isinstance(value, dict):
            raise HTTPException(status_code=404, detail="model registry version not found")
        try:
            _validate_model_registry(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail={"ok": False, "error": str(exc), "error_code": "invalid_model_registry"})
        aliases = _model_registry_aliases(value)
        current_policy = {}
        if model_policy_path.exists():
            try:
                current_policy = json.loads(model_policy_path.read_text(encoding="utf-8"))
            except Exception:
                current_policy = {}
        if isinstance(current_policy, dict) and current_policy:
            try:
                _validate_model_policy(current_policy, aliases)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"ok": False, "error": str(exc), "error_code": "model_policy_incompatible_with_registry"},
                )
        value["_updated"] = _utc()[:10]
        model_registry_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        cv_version = compass.record_config_version("model_registry", value, changed_by="console", reason=f"rollback_to:{version}")
        nerve.emit("fabric_updated", {"fabric": "model_registry", "path": str(model_registry_path), "rollback_from_version": version})
        return {"ok": True, "rolled_back_to": version, "config_version": cv_version}

    @app.get("/console/model-usage")
    def model_usage(since: str | None = None, until: str | None = None, limit: int = 1000):
        records = cortex.usage_between(since=since, until=until, limit=limit)
        by_provider: dict[str, dict[str, int]] = {}
        by_model: dict[str, dict[str, int]] = {}
        by_routine: dict[str, dict[str, int]] = {}
        fallback_chain_hits: dict[str, int] = {}

        for row in records:
            provider = str(row.get("provider") or "unknown")
            model = str(row.get("model") or "unknown")
            routine = str(row.get("routine") or "unknown")
            in_t = int(row.get("in_tokens") or 0)
            out_t = int(row.get("out_tokens") or 0)
            success = bool(row.get("success"))

            p = by_provider.setdefault(provider, {"calls": 0, "errors": 0, "in_tokens": 0, "out_tokens": 0})
            p["calls"] += 1
            p["in_tokens"] += in_t
            p["out_tokens"] += out_t
            if not success:
                p["errors"] += 1

            m = by_model.setdefault(model, {"calls": 0, "errors": 0, "in_tokens": 0, "out_tokens": 0})
            m["calls"] += 1
            m["in_tokens"] += in_t
            m["out_tokens"] += out_t
            if not success:
                m["errors"] += 1

            r = by_routine.setdefault(routine, {"calls": 0, "errors": 0, "in_tokens": 0, "out_tokens": 0})
            r["calls"] += 1
            r["in_tokens"] += in_t
            r["out_tokens"] += out_t
            if not success:
                r["errors"] += 1
            chain = row.get("fallback_chain")
            if isinstance(chain, list) and chain:
                key = "->".join(str(x) for x in chain if str(x))
                if key:
                    fallback_chain_hits[key] = fallback_chain_hits.get(key, 0) + 1

        # Semantic-cluster aggregation (task-plane view, complements trace-plane usage).
        tasks_path = state / "tasks.json"
        try:
            task_rows = json.loads(tasks_path.read_text(encoding="utf-8")) if tasks_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read tasks for model usage cluster view: %s", exc)
            task_rows = []
        by_semantic_cluster: dict[str, int] = {}
        by_capability: dict[str, int] = {}
        by_risk_level: dict[str, int] = {}
        for row in task_rows if isinstance(task_rows, list) else []:
            plan_row = row.get("plan") if isinstance(row.get("plan"), dict) else {}
            cluster = str(
                row.get("semantic_cluster")
                or plan_row.get("cluster_id")
                or ""
            )
            if cluster:
                by_semantic_cluster[cluster] = by_semantic_cluster.get(cluster, 0) + 1
            fp = plan_row.get("semantic_fingerprint") if isinstance(plan_row.get("semantic_fingerprint"), dict) else {}
            risk = str(fp.get("risk_level") or "").strip().lower()
            if risk:
                by_risk_level[risk] = by_risk_level.get(risk, 0) + 1
            steps = plan_row.get("steps") or plan_row.get("graph", {}).get("steps") or []
            if isinstance(steps, list):
                for st in steps:
                    if not isinstance(st, dict):
                        continue
                    cid = str(st.get("capability_id") or "")
                    if cid:
                        by_capability[cid] = by_capability.get(cid, 0) + 1

        return {
            "records": records,
            "summary": {
                "by_provider": by_provider,
                "by_model": by_model,
                "by_routine": by_routine,
                "by_semantic_cluster": by_semantic_cluster,
                "by_capability": by_capability,
                "by_risk_level": by_risk_level,
                "fallback_chain_hits": fallback_chain_hits,
            },
        }

    # ── Console — Policy ─────────────────────────────────────────────────────

    @app.get("/console/policy/preferences")
    def get_preferences():
        prefs = compass.all_prefs()
        return [{"pref_key": k, "value": v} for k, v in sorted(prefs.items())]

    @app.get("/console/policy/preferences/{pref_key}")
    def get_preference(pref_key: str):
        prefs = compass.all_prefs()
        if pref_key not in prefs:
            raise HTTPException(status_code=404, detail="preference not found")
        return {"pref_key": pref_key, "value": prefs[pref_key]}

    @app.put("/console/policy/preferences/{pref_key}")
    async def set_preference(pref_key: str, request: Request):
        body = await request.json()
        value = str(body.get("value") if isinstance(body, dict) and "value" in body else body)
        compass.set_pref(pref_key, value, source="console", changed_by="console")
        nerve.emit("fabric_updated", {"fabric": "compass", "key": f"pref.{pref_key}"})
        return {"ok": True, "pref_key": pref_key, "value": value}

    @app.get("/console/policy/preferences/{pref_key}/versions")
    def preference_versions(pref_key: str):
        return compass.versions(f"pref.{pref_key}")

    @app.post("/console/policy/preferences/{pref_key}/rollback/{version}")
    def preference_rollback(pref_key: str, version: int):
        ok = compass.rollback(f"pref.{pref_key}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        nerve.emit("fabric_updated", {"fabric": "compass", "key": f"pref.{pref_key}"})
        return {"ok": True}

    @app.get("/console/policy/budgets")
    def get_budgets():
        return compass.all_budgets()

    @app.get("/console/policy/budgets/{resource_type}")
    def get_budget(resource_type: str):
        budget = compass.get_budget(resource_type)
        if not budget:
            raise HTTPException(status_code=404, detail="budget not found")
        return budget

    @app.put("/console/policy/budgets/{resource_type}")
    async def set_budget(resource_type: str, request: Request):
        body = await request.json()
        if isinstance(body, dict):
            raw = body.get("daily_limit")
        else:
            raw = body
        try:
            daily_limit = float(raw)
        except Exception:
            raise HTTPException(status_code=400, detail="daily_limit must be numeric")
        compass.set_budget(resource_type, daily_limit, changed_by="console")
        nerve.emit("fabric_updated", {"fabric": "compass", "key": f"budget.{resource_type}"})
        return {"ok": True, "resource_type": resource_type, "daily_limit": daily_limit}

    @app.get("/console/policy/budgets/{resource_type}/versions")
    def budget_versions(resource_type: str):
        return compass.versions(f"budget.{resource_type}")

    @app.post("/console/policy/budgets/{resource_type}/rollback/{version}")
    def budget_rollback(resource_type: str, version: int):
        ok = compass.rollback(f"budget.{resource_type}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        nerve.emit("fabric_updated", {"fabric": "compass", "key": f"budget.{resource_type}"})
        return {"ok": True}

    @app.get("/console/policy/quality/{policy_name}")
    def get_policy_quality(policy_name: str):
        profile = compass.get_quality_profile(policy_name)
        return {"policy": policy_name, "rules": profile}

    @app.put("/console/policy/quality/{policy_name}")
    async def set_policy_quality(policy_name: str, request: Request):
        body = await request.json()
        rules = body.get("rules") or body
        compass.set_quality_profile(policy_name, rules, changed_by="console")
        nerve.emit("fabric_updated", {"fabric": "compass", "key": f"quality.{policy_name}"})
        return {"ok": True}

    @app.get("/console/policy/quality/{policy_name}/versions")
    def policy_quality_versions(policy_name: str):
        return compass.versions(f"quality.{policy_name}")

    @app.post("/console/policy/quality/{policy_name}/rollback/{version}")
    def policy_quality_rollback(policy_name: str, version: int):
        ok = compass.rollback(f"quality.{policy_name}", version, changed_by="console")
        if not ok:
            raise HTTPException(status_code=404, detail="version not found")
        nerve.emit("fabric_updated", {"fabric": "compass", "key": f"quality.{policy_name}"})
        return {"ok": True}

    # Backward-compatible aliases.
    @app.get("/console/policy/{policy_name}")
    def get_policy(policy_name: str):
        return get_policy_quality(policy_name)

    @app.put("/console/policy/{policy_name}")
    async def set_policy(policy_name: str, request: Request):
        return await set_policy_quality(policy_name, request)

    @app.get("/console/policy/{policy_name}/versions")
    def policy_versions(policy_name: str):
        return policy_quality_versions(policy_name)

    @app.post("/console/policy/{policy_name}/rollback/{version}")
    def policy_rollback(policy_name: str, version: int):
        return policy_quality_rollback(policy_name, version)

    # ── Console — Traces ──────────────────────────────────────────────────────

    @app.get("/console/traces")
    def list_traces(
        routine: str | None = None,
        status: str | None = None,
        degraded: bool | None = None,
        since: str | None = None,
        limit: int = 50,
    ):
        return tracer.query(routine=routine, status=status, degraded=degraded, since=since, limit=limit)

    @app.get("/console/traces/{trace_id}")
    def get_trace(trace_id: str):
        trace = tracer.get(trace_id)
        if trace:
            rows = cortex.usage_for_trace(trace_id, limit=200)
            by_provider: dict[str, dict] = {}
            errors: list[dict] = []
            for r in rows:
                provider = str(r.get("provider") or "unknown")
                agg = by_provider.setdefault(
                    provider,
                    {"calls": 0, "in_tokens": 0, "out_tokens": 0, "errors": 0, "avg_elapsed_s": 0.0},
                )
                agg["calls"] += 1
                agg["in_tokens"] += int(r.get("in_tokens") or 0)
                agg["out_tokens"] += int(r.get("out_tokens") or 0)
                if not r.get("success"):
                    agg["errors"] += 1
                agg["avg_elapsed_s"] += float(r.get("elapsed_s") or 0)
                if r.get("error"):
                    errors.append(
                        {
                            "provider": provider,
                            "timestamp": r.get("timestamp", ""),
                            "error": str(r.get("error", ""))[:200],
                        }
                    )
            for agg in by_provider.values():
                if agg["calls"] > 0:
                    agg["avg_elapsed_s"] = round(agg["avg_elapsed_s"] / agg["calls"], 3)
            trace_out = dict(trace)
            trace_out["cortex_summary"] = {
                "total_calls": len(rows),
                "total_in_tokens": sum(int(r.get("in_tokens") or 0) for r in rows),
                "total_out_tokens": sum(int(r.get("out_tokens") or 0) for r in rows),
                "by_provider": by_provider,
                "latest_calls": rows[-5:],
                "errors": errors[-10:],
            }
            return trace_out
        raise HTTPException(status_code=404)

    # ── Console — Cortex usage ────────────────────────────────────────────────

    @app.get("/console/cortex/usage")
    def cortex_usage(since: str | None = None, until: str | None = None, limit: int = 500):
        return {
            "today": cortex.usage_today(),
            "records": cortex.usage_between(since=since, until=until, limit=limit),
        }

    # ── Console — Schedules ───────────────────────────────────────────────────

    @app.get("/console/schedules")
    def list_schedules():
        return scheduler.status()

    @app.get("/console/schedules/history")
    def list_schedule_history(routine: str | None = None, limit: int = 100):
        return scheduler.history(routine=routine, limit=limit)

    @app.put("/console/schedules/{job_id}")
    async def update_schedule(job_id: str, request: Request):
        body = await request.json()
        schedule = body.get("schedule") if "schedule" in body else None
        enabled = body.get("enabled") if "enabled" in body else None
        result = scheduler.update_schedule(job_id, schedule=schedule, enabled=enabled)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result)
        return result

    @app.post("/console/schedules/{routine}/trigger")
    async def trigger_schedule(routine: str):
        return await spine_trigger(routine)

    # ── Console — Agent manager ───────────────────────────────────────────────

    @app.get("/console/agents")
    def list_agents():
        cfg_path = oc_home / "openclaw.json"
        if not cfg_path.exists():
            return []
        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception as exc:
            logger.warning("Failed to read openclaw.json: %s", exc)
            return []
        agents = cfg.get("agents", {}).get("list", [])
        result = []
        for agent in agents:
            agent_id = agent.get("id", "")
            workspace = oc_home / "workspace" / agent_id
            skills_dir = workspace / "skills"
            skills_count = len(list(skills_dir.glob("*/SKILL.md"))) if skills_dir.exists() else 0
            result.append({
                "id": agent_id,
                "workspace_exists": workspace.exists(),
                "skills_count": skills_count,
            })
        return result

    @app.get("/console/agents/{agent}/skills")
    def get_agent_skills(agent: str):
        skills_dir = oc_home / "workspace" / agent / "skills"
        if not skills_dir.exists():
            return []
        out = []
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            skill_dir = skill_md.parent
            disabled = (skill_dir / ".disabled").exists()
            content = skill_md.read_text()
            out.append(
                {
                    "skill": skill_dir.name,
                    "enabled": not disabled,
                    "path": str(skill_md),
                    "content": content,
                }
            )
        return out

    @app.put("/console/agents/{agent}/skills/{skill}")
    async def update_agent_skill(agent: str, skill: str, request: Request):
        body = await request.json()
        content = str(body.get("content") or "")
        if not content.strip():
            raise HTTPException(status_code=400, detail="content required")
        skill_dir = oc_home / "workspace" / agent / "skills" / skill
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(content)
        return {"ok": True, "agent": agent, "skill": skill}

    @app.patch("/console/agents/{agent}/skills/{skill}/enabled")
    async def set_skill_enabled(agent: str, skill: str, request: Request):
        body = await request.json()
        enabled = bool(body.get("enabled"))
        skill_dir = oc_home / "workspace" / agent / "skills" / skill
        if not skill_dir.exists():
            raise HTTPException(status_code=404, detail="skill not found")
        marker = skill_dir / ".disabled"
        if enabled:
            if marker.exists():
                marker.unlink()
        else:
            marker.write_text("disabled")
        return {"ok": True, "agent": agent, "skill": skill, "enabled": enabled}

    # ── Console — Skill Evolution ────────────────────────────────────────────

    @app.get("/console/skill-evolution/proposals")
    def list_skill_evolution(status: str | None = None, limit: int = 100):
        proposals = _sync_skill_proposals()
        if status:
            proposals = [p for p in proposals if str(p.get("status", "")) == status]
        return proposals[: max(1, min(limit, 500))]

    @app.post("/console/skill-evolution/proposals/{proposal_id}/review")
    async def review_skill_evolution(proposal_id: str, request: Request):
        body = await request.json()
        decision = str(body.get("decision") or "").strip().lower()
        reviewer = str(body.get("reviewer") or "console")
        note = str(body.get("note") or "")
        auto_apply = bool(body.get("apply"))
        if decision not in {"approve", "reject"}:
            raise HTTPException(status_code=400, detail="decision must be approve|reject")

        proposals = _sync_skill_proposals()
        target = None
        for row in proposals:
            if str(row.get("proposal_id") or "") == proposal_id:
                target = row
                break
        if not target:
            raise HTTPException(status_code=404, detail="proposal not found")

        target["reviewed_utc"] = _utc()
        target["reviewed_by"] = reviewer
        target["review_note"] = note
        if decision == "reject":
            target["status"] = "rejected"
            target["apply_error"] = ""
            target["applied_utc"] = ""
            _write_json_list(skill_queue_path, proposals)
            return {"ok": True, "proposal_id": proposal_id, "status": target["status"]}

        target["status"] = "approved"
        target["apply_error"] = ""
        proposal_type = str(target.get("proposal_type") or "skill")
        if proposal_type == "python":
            target["status"] = "pending_human_review"
            target["apply_error"] = "python_change_requires_human_review"
        elif not _sandbox_gate_open():
            target["status"] = "sandbox_blocked"
            target["apply_error"] = "sandbox_gate_closed"
        elif auto_apply or proposal_type in {"skill", "config"}:
            ok, err = _apply_evolution_proposal(target)
            if ok:
                target["status"] = "applied"
                target["applied_utc"] = _utc()
                target["apply_error"] = ""
            else:
                target["status"] = "apply_failed"
                target["apply_error"] = err

        _write_json_list(skill_queue_path, proposals)
        return {"ok": True, "proposal_id": proposal_id, "status": target["status"], "apply_error": target.get("apply_error", "")}

    @app.post("/console/skill-evolution/proposals/{proposal_id}/apply")
    def apply_skill_evolution(proposal_id: str):
        proposals = _sync_skill_proposals()
        target = None
        for row in proposals:
            if str(row.get("proposal_id") or "") == proposal_id:
                target = row
                break
        if not target:
            raise HTTPException(status_code=404, detail="proposal not found")
        if str(target.get("status") or "") == "rejected":
            raise HTTPException(status_code=400, detail="proposal rejected")
        if str(target.get("proposal_type") or "") == "python":
            target["status"] = "pending_human_review"
            target["apply_error"] = "python_change_requires_human_review"
            _write_json_list(skill_queue_path, proposals)
            return {"ok": False, "proposal_id": proposal_id, "status": target["status"], "apply_error": target["apply_error"]}
        if not _sandbox_gate_open():
            target["status"] = "sandbox_blocked"
            target["apply_error"] = "sandbox_gate_closed"
            _write_json_list(skill_queue_path, proposals)
            return {"ok": False, "proposal_id": proposal_id, "status": target["status"], "apply_error": target["apply_error"]}

        ok, err = _apply_evolution_proposal(target)
        if ok:
            target["status"] = "applied"
            target["applied_utc"] = _utc()
            target["apply_error"] = ""
        else:
            target["status"] = "apply_failed"
            target["apply_error"] = err
        _write_json_list(skill_queue_path, proposals)
        return {"ok": ok, "proposal_id": proposal_id, "status": target["status"], "apply_error": target.get("apply_error", "")}

    # ── Console — Priority management ─────────────────────────────────────────

    @app.put("/console/fabric/compass/priorities/{domain}")
    async def set_priority(domain: str, request: Request):
        body = await request.json()
        weight = float(body.get("weight") or 1.0)
        reason = str(body.get("reason") or "")
        compass.set_priority(domain, weight, reason, changed_by="console")
        nerve.emit("fabric_updated", {"fabric": "compass", "key": f"priority.{domain}"})
        return {"ok": True}

    # ── Serve static interfaces ────────────────────────────────────────────────

    portal_dir = home / "interfaces" / "portal"
    console_dir = home / "interfaces" / "console"
    if portal_dir.exists():
        app.mount("/portal", StaticFiles(directory=portal_dir, html=True), name="portal")
    if console_dir.exists():
        app.mount("/console", StaticFiles(directory=console_dir, html=True), name="console")

    return app
