"""Daemon API — FastAPI application with Portal and Console routes."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
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
from runtime.event_bridge import EventBridge
from runtime.temporal import TemporalClient
from services.dispatch import Dispatch
from services.dialog import DialogService
from services.scheduler import Scheduler


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
    bridge = EventBridge(state, source="api")
    telemetry_dir = state / "telemetry"
    telemetry_dir.mkdir(parents=True, exist_ok=True)
    portal_events_path = telemetry_dir / "portal_events.jsonl"
    skill_proposals_path = state / "skill_evolution_proposals.json"
    skill_queue_path = state / "skill_evolution_queue.json"

    app = FastAPI(title="Daemon API", version="0.1.0")
    temporal_client: TemporalClient | None = None
    bridge_task: asyncio.Task | None = None
    bridge_running = True

    @app.on_event("startup")
    async def _startup():
        nonlocal temporal_client, bridge_task, bridge_running
        # Validate required semantic config files — hard error if missing.
        _validate_semantic_config(home)
        # Bootstrap semantic clusters into Playbook DB.
        _bootstrap_clusters(home, playbook)

        tc = _temporal_config()
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
        except Exception as exc:
            logger.error("Temporal client connection failed: %s", exc)
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

    def _write_json_list(path: Path, items: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2))

    def _proposal_id(item: dict) -> str:
        raw = f"{item.get('skill','')}|{item.get('proposed_change','')}|{item.get('evidence','')}"
        return "sev_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

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

    # ── Health ────────────────────────────────────────────────────────────────

    @app.get("/health")
    def health():
        gate_path = state / "gate.json"
        gate = {"status": "GREEN"}
        if gate_path.exists():
            try:
                gate = json.loads(gate_path.read_text())
            except Exception as exc:
                logger.warning("Failed to read gate.json: %s", exc)
        return {"ok": True, "gate": gate["status"]}

    # ── Task submission (Portal) ───────────────────────────────────────────────

    @app.post("/submit")
    async def submit_task(request: Request):
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
            if code == "invalid_plan":
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
        result = tasks[-limit:]
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
                return t
        _log_portal_event("task_not_found", {"task_id": task_id}, request)
        raise HTTPException(status_code=404, detail="task not found")

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
        index_path = home / "outcome" / "index.json"
        try:
            index = json.loads(index_path.read_text()) if index_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read outcome index: %s", exc)
            index = []
        _log_portal_event("outcome_list", {"limit": limit, "count": min(len(index), limit)}, request)
        return list(reversed(index))[:limit]

    @app.get("/outcome/timeline")
    def outcome_timeline(request: Request, days: int = 30, limit_per_day: int = 50):
        index_path = home / "outcome" / "index.json"
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
        full = home / "outcome" / path
        if not full.exists():
            _log_portal_event("outcome_file_missing", {"path": path}, request)
            raise HTTPException(status_code=404)
        _log_portal_event("outcome_file_access", {"path": path}, request)
        return FileResponse(full)

    # ── User feedback (Portal) ────────────────────────────────────────────────

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
        if task_record:
            plan = task_record.get("plan") or {}
            task_type = str(plan.get("task_type") or "")
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
            "created_utc": _utc(),
        })

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
    def fabric_memory(domain: str | None = None, tier: str | None = None, since: str | None = None, keyword: str | None = None, limit: int = 50):
        return memory.query(domain=domain, tier=tier, since=since, keyword=keyword, limit=limit)

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
        if auto_apply:
            ok, err = _apply_skill_proposal(target)
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

        ok, err = _apply_skill_proposal(target)
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
