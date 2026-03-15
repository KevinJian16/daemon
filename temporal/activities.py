"""Daemon Activities — Temporal activity implementations for Job Steps.

Replaces the old deed/move/folio/writ terminology:
  deed → job, move → step, folio → project, writ → task, slip → task

Dependencies replaced:
  Ether → EventBus (PG LISTEN/NOTIFY)
  Ledger → Store (PG asyncpg)
  Retinue → removed (OC native sessions)
  Psyche/Cortex/Instinct → removed (Phase 4: Mem0 + NeMo Guardrails)
  Herald → removed (publisher agent handles delivery)

Reference: SYSTEM_DESIGN.md §3, TODO.md Phase 3.1
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
from temporalio import activity

from runtime.openclaw import OpenClawAdapter
from runtime.mcp_dispatch import MCPDispatcher
from services.store import Store
from services.event_bus import EventBus
from temporal.activities_exec import (
    run_openclaw_step as _run_openclaw_step_impl,
    run_direct_step as _run_direct_step_impl,
    run_cc_step as _run_cc_step_impl,
)
from temporal.activities_replan import run_replan_gate as _run_replan_gate_impl
from temporal.activities_maintenance import run_maintenance as _run_maintenance_impl
from config.mem0_config import init_mem0, retrieve_agent_context, retrieve_user_preferences

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _daemon_home() -> Path:
    return Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))


def _openclaw_home() -> Path:
    v = os.environ.get("OPENCLAW_HOME")
    return Path(v) if v else _daemon_home() / "openclaw"


class DaemonActivities:
    """All Temporal activities. Instantiated once per Worker process.

    Requires an asyncpg pool and EventBus instance, both created at
    Worker startup and shared across all activities.
    """

    def __init__(self, pool: asyncpg.Pool, event_bus: EventBus) -> None:
        self._home = _daemon_home()
        self._oc_home = _openclaw_home()
        self._store = Store(pool)
        self._event_bus = event_bus
        self._openclaw: OpenClawAdapter | None = None
        self._mcp = MCPDispatcher(self._home / "config" / "mcp_servers.json")
        self._langfuse = None

        try:
            self._openclaw = OpenClawAdapter(self._oc_home)
        except Exception as exc:
            activity.logger.warning(
                "Failed to initialize OpenClawAdapter from %s: %s", self._oc_home, exc
            )

        # Mem0 memory (§4.3) — semantic memory backed by PG + pgvector
        self._mem0 = init_mem0()

        # Langfuse tracing (§3.4)
        try:
            from langfuse import Langfuse
            lf_host = os.environ.get("LANGFUSE_HOST", "")
            lf_pk = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
            lf_sk = os.environ.get("LANGFUSE_SECRET_KEY", "")
            if lf_host and lf_pk and lf_sk:
                self._langfuse = Langfuse(
                    public_key=lf_pk, secret_key=lf_sk, host=lf_host,
                )
                logger.info("Langfuse tracing enabled: %s", lf_host)
            else:
                logger.info("Langfuse tracing: disabled (missing LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY)")
        except ImportError:
            logger.info("Langfuse tracing: disabled (langfuse package not installed)")
        except Exception as exc:
            logger.warning("Langfuse tracing init failed: %s", exc)

    # ── Step execution (OC agent session) ──────────────────────────────────

    @activity.defn(name="activity_execute_step")
    async def activity_execute_step(self, job_id: str, plan: dict, step: dict) -> dict:
        """Execute one DAG step via OC persistent session.

        Session key: {agent_id}:{job_id}:{step_id} (SYSTEM_DESIGN.md §3.4)
        """
        return await _run_openclaw_step_impl(self, job_id, plan, step)

    # ── Direct step (MCP / Python, zero LLM) ──────────────────────────────

    @activity.defn(name="activity_direct_step")
    async def activity_direct_step(self, job_id: str, plan: dict, step: dict) -> dict:
        """Execute a direct step via MCP tool — zero LLM tokens."""
        return await _run_direct_step_impl(self, job_id, plan, step)

    # ── CC/Codex step (CLI, bypasses OC) ─────────────────────────────────

    @activity.defn(name="activity_cc_step")
    async def activity_cc_step(self, job_id: str, plan: dict, step: dict) -> dict:
        """Execute a step via Claude Code or Codex CLI — bypasses OC Gateway."""
        return await _run_cc_step_impl(self, job_id, plan, step)

    # ── Job status ─────────────────────────────────────────────────────────

    @activity.defn(name="activity_update_job_status")
    async def activity_update_job_status(
        self, job_id: str, status: str, sub_status: str = "", error: str = ""
    ) -> dict:
        """Update job status in PG and emit event."""
        try:
            job_uuid = UUID(job_id)
            extra: dict[str, Any] = {}
            if error:
                extra["error_message"] = error
            await self._store.update_job_status(job_uuid, status, sub_status, **extra)
        except Exception as exc:
            activity.logger.warning("Failed to update job %s status: %s", job_id, exc)

        await self._event_bus.publish("job_events", f"job_{status}", {
            "job_id": job_id,
            "status": status,
            "sub_status": sub_status,
            "error": error,
            "updated_utc": _utc(),
        })

        return {"ok": True, "job_id": job_id, "status": status}

    # ── Step status ────────────────────────────────────────────────────────

    @activity.defn(name="activity_update_step_status")
    async def activity_update_step_status(
        self, step_id: str, status: str, **extra: Any
    ) -> dict:
        """Update step status in PG."""
        try:
            step_uuid = UUID(step_id)
            await self._store.update_step_status(step_uuid, status, **extra)
        except Exception as exc:
            activity.logger.warning("Failed to update step %s status: %s", step_id, exc)
        return {"ok": True, "step_id": step_id, "status": status}

    # ── Replan Gate (Phase 3.5) ────────────────────────────────────────────

    @activity.defn(name="activity_replan_gate")
    async def activity_replan_gate(self, job_id: str, job_result: dict) -> dict:
        """Evaluate completed Job outcome and decide whether to replan.

        Reference: SYSTEM_DESIGN.md §3.7
        """
        return await _run_replan_gate_impl(self, job_id, job_result)

    # ── Scheduled maintenance (Phase 4.17) ─────────────────────────────────

    @activity.defn(name="activity_maintenance")
    async def activity_maintenance(self) -> dict:
        """Run periodic maintenance (replaces old Spine routines).

        Scheduled via Temporal Schedule, typically every 6 hours.
        """
        return await _run_maintenance_impl(self)
