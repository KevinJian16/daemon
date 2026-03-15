"""Daemon API — FastAPI application for the new two-layer agent architecture.

Routes:
  POST /scenes/{scene}/chat        — L1 agent scene chat (§4.9)
  WS   /scenes/{scene}/chat/stream — WebSocket real-time L1 chat (§4.9)
  GET  /scenes/{scene}/panel       — Scene panel data (§4.9)
  POST /webhooks/plane             — Plane webhook handler (§2.4)
  GET  /status                     — System status (§4.9)
  GET  /health                     — Health check

Reference: SYSTEM_DESIGN.md §2.2, §4.9, §6.2
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from runtime.temporal import TemporalClient
from services.api_routes.scenes import router as scenes_router, configure as configure_scenes
from services.plane_webhook import router as webhook_router, configure as configure_webhook
from daemon_env import load_daemon_env


def _daemon_home() -> Path:
    return Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))


def _openclaw_home() -> Path:
    v = os.environ.get("OPENCLAW_HOME")
    return Path(v) if v else _daemon_home() / "openclaw"


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    load_daemon_env()

    app = FastAPI(
        title="daemon API",
        description="Two-layer agent architecture API (7th draft)",
        version="2.0.0",
    )

    # CORS for desktop client and remote web access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Will be restricted in production via OAuth
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── State ────────────────────────────────────────────────────────────
    app.state.started_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    app.state.store = None
    app.state.event_bus = None
    app.state.plane_client = None
    app.state.session_manager = None
    app.state.temporal_client = None
    app.state.pool = None

    # ── Routes ───────────────────────────────────────────────────────────

    # Scene routes (L1 agent interaction)
    app.include_router(scenes_router)

    # Plane webhook handler
    app.include_router(webhook_router)

    # Status and health endpoints
    @app.get("/status")
    async def get_status():
        """System status for client status indicator (§4.9)."""
        return {
            "status": "running",
            "started_utc": app.state.started_utc,
            "scenes": ["copilot", "mentor", "coach", "operator"],
            "session_manager": app.state.session_manager is not None,
            "store": app.state.store is not None,
            "event_bus": app.state.event_bus is not None,
            "plane_client": app.state.plane_client is not None,
        }

    @app.get("/health")
    async def health_check():
        """Basic health check."""
        return {"ok": True, "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    # Jobs and Tasks endpoints (§4.9)
    @app.get("/jobs")
    async def list_jobs(status: str = "", limit: int = 20):
        """List Jobs, optionally filtered by status."""
        if not app.state.store:
            raise HTTPException(status_code=503, detail="Store not available")
        return await app.state.store.list_jobs(status=status, limit=limit)

    @app.get("/tasks/{task_id}")
    async def get_task(task_id: str):
        """Get Task details by ID."""
        if not app.state.store:
            raise HTTPException(status_code=503, detail="Store not available")
        from uuid import UUID
        try:
            task = await app.state.store.get_task(UUID(task_id))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid task_id format")
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

    @app.get("/tasks/{task_id}/activity")
    async def get_task_activity(task_id: str, limit: int = 50):
        """Get activity feed for a Task (§4.9)."""
        if not app.state.store:
            raise HTTPException(status_code=503, detail="Store not available")
        from uuid import UUID
        try:
            tid = UUID(task_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid task_id format")
        return await app.state.store.get_task_activity(tid, limit=limit)

    @app.post("/jobs/submit")
    async def submit_job(req: Request):
        """Submit a Job directly (for testing and admin use).

        Body: {"title": "...", "steps": [...], "concurrency": 2}
        Each step: {"goal": "...", "agent_id": "...", "execution_type": "agent|direct"}
        """
        if not app.state.store or not app.state.temporal_client:
            raise HTTPException(status_code=503, detail="Store or Temporal not available")
        body = await req.json()
        steps = body.get("steps") or []
        if not steps:
            raise HTTPException(status_code=400, detail="steps required")
        title = str(body.get("title") or "manual job")
        from uuid import uuid4
        task = await app.state.store.create_task(title=title, source="api")
        task_id = task["task_id"]
        plan = {
            "steps": steps,
            "title": title,
            "source": "api",
            "concurrency": body.get("concurrency", 2),
        }
        workflow_id = f"job-{uuid4()}"
        job = await app.state.store.create_job(
            task_id=task_id,
            workflow_id=workflow_id,
            dag_snapshot=plan,
        )
        job_id = str(job["job_id"])
        plan["job_id"] = job_id
        run_id = await app.state.temporal_client.start_job_workflow(
            workflow_id=workflow_id, plan=plan,
        )
        return {"ok": True, "job_id": job_id, "workflow_id": workflow_id, "run_id": run_id}

    # ── Static files (Portal UI) ─────────────────────────────────────────
    # Serve compiled portal from /portal; in production, also serve as fallback
    portal_dir = _daemon_home() / "interfaces" / "portal" / "compiled"
    if portal_dir.is_dir():
        app.mount("/portal", StaticFiles(directory=str(portal_dir), html=True), name="portal")
        logger.info("Portal mounted at /portal from %s", portal_dir)

    # ── Lifecycle ────────────────────────────────────────────────────────

    @app.on_event("startup")
    async def startup():
        await _startup(app)

    @app.on_event("shutdown")
    async def shutdown():
        await _shutdown(app)

    return app


async def _startup(app: FastAPI) -> None:
    """Initialize all services on startup."""
    home = _daemon_home()
    oc_home = _openclaw_home()

    # 1. PostgreSQL connection pool
    database_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://daemon:daemon@localhost:5432/daemon",
    )
    try:
        import asyncpg
        pool = await asyncpg.create_pool(database_url, min_size=2, max_size=10)
        app.state.pool = pool
        logger.info("PG pool created: %s", database_url.split("@")[-1])
    except Exception as exc:
        logger.warning("Failed to create PG pool: %s", exc)
        pool = None

    # 2. Store (PG data layer)
    if pool:
        from services.store import Store
        app.state.store = Store(pool)
        logger.info("Store initialized")

        # Run migrations if needed
        await _ensure_tables(pool)

    # 3. Event Bus (PG LISTEN/NOTIFY)
    if pool:
        from services.event_bus import EventBus
        event_bus = EventBus(database_url)
        try:
            await event_bus.connect(pool)
            app.state.event_bus = event_bus
            logger.info("EventBus connected")
        except Exception as exc:
            logger.warning("EventBus connect failed: %s", exc)

    # 4. Plane Client
    plane_api_url = os.environ.get("PLANE_API_URL", "http://localhost:8001")
    plane_api_token = os.environ.get("PLANE_API_TOKEN", "")
    plane_workspace = os.environ.get("PLANE_WORKSPACE_SLUG", "daemon")
    if plane_api_token:
        from services.plane_client import PlaneClient
        app.state.plane_client = PlaneClient(
            api_url=plane_api_url,
            api_token=plane_api_token,
            workspace_slug=plane_workspace,
        )
        logger.info("PlaneClient initialized: %s", plane_api_url)

    # 5. OpenClaw adapter (for L1 sessions)
    openclaw_adapter = None
    try:
        from runtime.openclaw import OpenClawAdapter
        openclaw_adapter = OpenClawAdapter(oc_home)
        logger.info("OpenClawAdapter initialized: %s", oc_home)
    except Exception as exc:
        logger.warning("OpenClawAdapter init failed: %s (L1 sessions disabled)", exc)

    # 6. Session Manager (L1 persistent sessions)
    if app.state.store:
        from services.session_manager import SessionManager
        session_manager = SessionManager(
            openclaw_adapter=openclaw_adapter,
            store=app.state.store,
            event_bus=app.state.event_bus,
        )
        await session_manager.start()
        app.state.session_manager = session_manager
        logger.info("SessionManager started (4 L1 scenes)")

    # 7. Temporal client (for submitting workflows from API)
    try:
        temporal_addr = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
        temporal_ns = os.environ.get("TEMPORAL_NAMESPACE", "default")
        host = temporal_addr.split(":")[0]
        port = int(temporal_addr.split(":")[-1])
        app.state.temporal_client = await TemporalClient.connect(
            host=host, port=port, namespace=temporal_ns,
        )
        logger.info("Temporal client connected: %s", temporal_addr)
    except Exception as exc:
        logger.warning("Temporal client init failed: %s", exc)

    # 8. Configure routes with dependencies
    configure_scenes(
        app.state.session_manager,
        store=app.state.store,
        temporal_client=app.state.temporal_client,
    )
    configure_webhook(
        webhook_secret=os.environ.get("PLANE_WEBHOOK_SECRET", ""),
        store=app.state.store,
        event_bus=app.state.event_bus,
        temporal_client=app.state.temporal_client,
    )

    # 9. Register Plane webhook (so Plane sends events to us)
    if app.state.plane_client:
        await _ensure_plane_webhook(app.state.plane_client)

    logger.info("daemon API startup complete")


async def _shutdown(app: FastAPI) -> None:
    """Cleanup on shutdown."""
    if app.state.session_manager:
        await app.state.session_manager.stop()

    if app.state.event_bus:
        await app.state.event_bus.close()

    if app.state.plane_client:
        await app.state.plane_client.close()

    if app.state.pool:
        await app.state.pool.close()

    logger.info("daemon API shutdown complete")


async def _ensure_plane_webhook(plane_client) -> None:
    """Register daemon webhook URL with Plane if not already registered.

    Uses DAEMON_API_URL env var to determine the callback URL.
    Plane returns a secret_key on creation — logged for operator to capture
    and set as PLANE_WEBHOOK_SECRET.
    """
    api_url = os.environ.get("DAEMON_API_URL", "http://localhost:8000")
    webhook_url = f"{api_url.rstrip('/')}/webhooks/plane"

    try:
        existing = await plane_client.list_webhooks()
        for wh in existing:
            if wh.get("url") == webhook_url:
                logger.info("Plane webhook already registered: %s", webhook_url)
                return

        result = await plane_client.create_webhook(
            url=webhook_url,
            events=["issue", "project"],
        )
        secret = result.get("secret_key", "")
        logger.info(
            "Plane webhook registered: %s (set PLANE_WEBHOOK_SECRET=%s)",
            webhook_url,
            secret[:8] + "..." if len(secret) > 8 else secret,
        )
    except Exception as exc:
        logger.warning("Plane webhook registration failed: %s", exc)


async def _ensure_tables(pool) -> None:
    """Create daemon tables if they don't exist."""
    async with pool.acquire() as conn:
        # Check if tables exist
        exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='daemon_tasks')"
        )
        if exists:
            logger.info("daemon tables already exist")
            return

        logger.info("Creating daemon tables...")
        await conn.execute(SCHEMA_SQL)
        logger.info("daemon tables created successfully")


# ── Schema SQL ───────────────────────────────────────────────────────────────

SCHEMA_SQL = """
-- Enable pgvector extension (if available)
CREATE EXTENSION IF NOT EXISTS vector;

-- daemon_tasks: Task metadata (mapped to Plane Issues)
CREATE TABLE IF NOT EXISTS daemon_tasks (
    task_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plane_issue_id UUID,
    title         TEXT,
    project_id    UUID,
    trigger_type  TEXT NOT NULL DEFAULT 'manual'
                  CHECK (trigger_type IN ('manual', 'timer', 'chain')),
    schedule_id   TEXT,
    chain_source_task_id UUID REFERENCES daemon_tasks(task_id),
    dag           JSONB,
    user_id       TEXT DEFAULT 'default',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- jobs: Job state machine (running → closed)
CREATE TABLE IF NOT EXISTS jobs (
    job_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id       UUID REFERENCES daemon_tasks(task_id),
    workflow_id   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running', 'closed')),
    sub_status    TEXT NOT NULL DEFAULT 'queued'
                  CHECK (sub_status IN ('queued', 'executing', 'paused', 'retrying',
                                         'succeeded', 'completed', 'failed', 'cancelled')),
    dag_snapshot  JSONB NOT NULL,
    is_ephemeral  BOOLEAN DEFAULT FALSE,
    requires_review BOOLEAN DEFAULT FALSE,
    plane_sync_failed BOOLEAN DEFAULT FALSE,
    error_message TEXT,
    user_id       TEXT DEFAULT 'default',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at     TIMESTAMPTZ
);

-- job_steps: Step records within a Job
CREATE TABLE IF NOT EXISTS job_steps (
    step_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id        UUID NOT NULL REFERENCES jobs(job_id),
    step_index    INTEGER NOT NULL,
    goal          TEXT NOT NULL,
    agent_id      TEXT,
    execution_type TEXT NOT NULL DEFAULT 'agent'
                  CHECK (execution_type IN ('agent', 'direct', 'claude_code', 'codex')),
    model_hint    TEXT,
    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'running', 'completed', 'failed',
                                     'skipped', 'pending_confirmation')),
    depends_on    INTEGER[] DEFAULT '{}',
    input_artifacts TEXT[] DEFAULT '{}',
    output_summary TEXT,
    token_count   INTEGER,
    error_message TEXT,
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- job_artifacts: Artifact metadata (files stored in MinIO)
CREATE TABLE IF NOT EXISTS job_artifacts (
    artifact_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id        UUID NOT NULL REFERENCES jobs(job_id),
    step_id       UUID REFERENCES job_steps(step_id),
    artifact_type TEXT NOT NULL,
    title         TEXT,
    summary       TEXT,
    minio_path    TEXT NOT NULL,
    mime_type     TEXT,
    size_bytes    BIGINT,
    is_final      BOOLEAN DEFAULT FALSE,
    gdrive_synced BOOLEAN DEFAULT FALSE,
    key_marked    BOOLEAN DEFAULT FALSE,
    source_markers JSONB,
    user_id       TEXT DEFAULT 'default',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- conversation_messages: L1 scene chat raw messages (layer 1)
CREATE TABLE IF NOT EXISTS conversation_messages (
    message_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene         TEXT NOT NULL CHECK (scene IN ('copilot', 'mentor', 'coach', 'operator')),
    role          TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content       TEXT NOT NULL,
    token_count   INTEGER,
    user_id       TEXT DEFAULT 'default',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- conversation_digests: L1 compressed summaries (layer 2)
CREATE TABLE IF NOT EXISTS conversation_digests (
    digest_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene         TEXT NOT NULL CHECK (scene IN ('copilot', 'mentor', 'coach', 'operator')),
    time_range_start TIMESTAMPTZ NOT NULL,
    time_range_end   TIMESTAMPTZ NOT NULL,
    summary       TEXT NOT NULL,
    token_count   INTEGER,
    source_message_count INTEGER,
    user_id       TEXT DEFAULT 'default',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- conversation_decisions: L1 key decisions (layer 3)
CREATE TABLE IF NOT EXISTS conversation_decisions (
    decision_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene         TEXT NOT NULL CHECK (scene IN ('copilot', 'mentor', 'coach', 'operator')),
    decision_type TEXT NOT NULL,
    content       TEXT NOT NULL,
    context_summary TEXT,
    project_id    UUID,
    tags          TEXT[],
    user_id       TEXT DEFAULT 'default',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- knowledge_cache: External knowledge TTL cache
CREATE TABLE IF NOT EXISTS knowledge_cache (
    cache_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url    TEXT NOT NULL UNIQUE,
    source_tier   TEXT NOT NULL CHECK (source_tier IN ('A', 'B', 'C')),
    project_id    UUID,
    title         TEXT,
    content_summary TEXT,
    ragflow_doc_id TEXT,
    embedding     vector(1536),
    user_id       TEXT DEFAULT 'default',
    expires_at    TIMESTAMPTZ NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- event_log: Persistent event log + NOTIFY trigger
CREATE TABLE IF NOT EXISTS event_log (
    event_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel       TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    payload       JSONB NOT NULL,
    consumed      BOOLEAN DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Trigger: auto-NOTIFY on event_log INSERT
CREATE OR REPLACE FUNCTION notify_event_log() RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(NEW.channel, row_to_json(NEW)::text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_event_log_notify ON event_log;
CREATE TRIGGER trg_event_log_notify
    AFTER INSERT ON event_log
    FOR EACH ROW
    EXECUTE FUNCTION notify_event_log();

-- Indexes
CREATE INDEX IF NOT EXISTS idx_daemon_tasks_plane_issue ON daemon_tasks(plane_issue_id);
CREATE INDEX IF NOT EXISTS idx_jobs_task_id ON jobs(task_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, sub_status);
CREATE INDEX IF NOT EXISTS idx_job_steps_job_id ON job_steps(job_id);
CREATE INDEX IF NOT EXISTS idx_job_artifacts_job_id ON job_artifacts(job_id);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_scene ON conversation_messages(scene, created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_digests_scene ON conversation_digests(scene, created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_decisions_scene ON conversation_decisions(scene, created_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_cache_expires ON knowledge_cache(expires_at);
CREATE INDEX IF NOT EXISTS idx_knowledge_cache_project ON knowledge_cache(project_id);
CREATE INDEX IF NOT EXISTS idx_event_log_consumed ON event_log(consumed, created_at);
"""


# ── Application instance ────────────────────────────────────────────────────

app = create_app()
