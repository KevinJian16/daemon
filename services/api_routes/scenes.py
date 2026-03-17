"""Scene API endpoints — L1 agent interaction.

Endpoints:
  POST /scenes/{scene}/chat     — Send message to L1 agent
  GET  /scenes/{scene}/chat/stream — WebSocket real-time chat
  GET  /scenes/{scene}/panel    — Scene panel data (messages, digests, decisions)

Scenes: copilot, mentor, coach, operator

Reference: SYSTEM_DESIGN.md §5.1, TODO.md Phase 5.8
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from services.api_routes.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scenes", tags=["scenes"])

# Session manager will be injected at startup
_session_manager = None
_store = None
_temporal_client = None
_plane_client = None


def configure(
    session_manager: Any,
    store: Any = None,
    temporal_client: Any = None,
    plane_client: Any = None,
) -> None:
    """Inject dependencies at startup."""
    global _session_manager, _store, _temporal_client, _plane_client
    _session_manager = session_manager
    _store = store
    _temporal_client = temporal_client
    _plane_client = plane_client


# ── Models ────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    content: str
    metadata: dict[str, Any] | None = None
    user_id: str | None = None  # optional caller identity for workflow ID prefix (§6.13.2)


class ChatResponse(BaseModel):
    ok: bool
    scene: str = ""
    reply: str = ""
    action: dict | None = None
    job_id: str | None = None
    error: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post("/{scene}/chat", response_model=ChatResponse)
async def scene_chat(scene: str, req: ChatRequest, _user: dict = Depends(get_current_user)) -> ChatResponse:
    """Send a message to a scene's L1 agent.

    The L1 agent may:
    - Reply directly (action: null or action.type == "direct_response")
    - Create a Job (action.type == "create_job") → submitted to Temporal
    - Create a Task (action.type == "create_task") → creates Plane Issue + Job

    No blocking UX (§0.9): internal errors are caught and returned as
    user-friendly messages. Stack traces never reach the client.
    """
    try:
        if not _session_manager:
            raise HTTPException(status_code=503, detail="Session manager not initialized")

        result = await _session_manager.send_message(
            scene, req.content, metadata=req.metadata,
        )

        if not result.get("ok"):
            return ChatResponse(
                ok=False,
                scene=scene,
                error=str(result.get("error") or "unknown error"),
            )

        action = result.get("action")
        job_id = None

        # If L1 output contains a structured action, dispatch by routing decision (§3.1)
        # Three routes: direct (single step) / task (multi-step Job) / project (Task DAG)
        if action and _store and _temporal_client and isinstance(action, dict):
            action_type = str(action.get("action") or action.get("route") or "").strip()
            caller_user_id = req.user_id or "system"
            try:
                if action_type in ("create_job", "task", "project"):
                    job_id = await _submit_job(action, scene, req.content, user_id=caller_user_id)
                elif action_type == "direct":
                    job_id = await _submit_direct_job(action, scene, req.content, user_id=caller_user_id)
            except Exception as exc:
                logger.warning("Job submission from scene %s failed: %s", scene, exc)
                # Job submission failure is non-fatal — reply still reaches user

        return ChatResponse(
            ok=True,
            scene=scene,
            reply=result.get("reply", ""),
            action=action,
            job_id=job_id,
        )

    except HTTPException:
        raise
    except Exception as exc:
        # No blocking UX (§0.9): swallow internal errors, never expose stack traces
        logger.exception("Unexpected error in scene_chat for scene %s", scene)
        return ChatResponse(
            ok=False,
            scene=scene,
            error="Something went wrong. Please try again.",
        )


@router.websocket("/{scene}/chat/stream")
async def scene_chat_stream(ws: WebSocket, scene: str) -> None:
    """WebSocket endpoint for real-time L1 chat.

    Protocol:
      Client sends: {"content": "user message"}
      Server sends: {"type": "reply", "content": "..."}
      Server sends: {"type": "action", "action": {...}}
      Server sends: {"type": "error", "error": "..."}
    """
    await ws.accept()

    if not _session_manager:
        await ws.send_json({"type": "error", "error": "session manager not initialized"})
        await ws.close()
        return

    try:
        while True:
            data = await ws.receive_json()
            content = str(data.get("content") or "").strip()
            if not content:
                await ws.send_json({"type": "error", "error": "empty message"})
                continue

            # No blocking UX (§0.9): catch per-message errors so one failure
            # doesn't kill the whole WebSocket session.
            try:
                result = await _session_manager.send_message(scene, content)

                if not result.get("ok"):
                    await ws.send_json({
                        "type": "error",
                        "error": str(result.get("error") or "unknown"),
                    })
                    continue

                await ws.send_json({
                    "type": "reply",
                    "content": result.get("reply", ""),
                    "scene": scene,
                })

                action = result.get("action")
                if action:
                    await ws.send_json({
                        "type": "action",
                        "action": action,
                    })
            except Exception as msg_exc:
                logger.exception("Error processing WS message for scene %s", scene)
                try:
                    await ws.send_json({
                        "type": "error",
                        "error": "Something went wrong. Please try again.",
                    })
                except Exception:
                    pass

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for scene %s", scene)
    except Exception as exc:
        logger.warning("WebSocket error for scene %s: %s", scene, exc)
        try:
            await ws.close()
        except Exception:
            pass


@router.get("/{scene}/panel")
async def scene_panel(scene: str, _user: dict = Depends(get_current_user)) -> dict:
    """Get scene panel data: recent messages, digests, decisions, plus per-scene
    structured data (§4.2).

    Per-scene structured data:
      copilot  → recent projects + active tasks summary
      mentor   → learning plans + assignment progress
      coach    → execution rates + performance metrics
      operator → platform status + system health

    No blocking UX (§0.9): internal errors return empty panel rather than
    exposing stack traces.
    """
    try:
        if not _session_manager:
            raise HTTPException(status_code=503, detail="Session manager not initialized")

        base = await _session_manager.get_panel_data(scene)

        # Enrich with per-scene structured data (§4.2)
        structured = await _get_scene_structured_data(scene)
        if structured:
            base["structured"] = structured

        return base

    except HTTPException:
        raise
    except Exception:
        logger.exception("Error fetching panel data for scene %s", scene)
        return {"messages": [], "digests": [], "decisions": [], "error": "Panel data temporarily unavailable."}


async def _get_scene_structured_data(scene: str) -> dict:
    """Return per-scene structured panel data (§4.2).

    copilot:  recent projects + active tasks summary
    mentor:   learning plans + assignment progress
    coach:    execution rates + performance metrics
    operator: platform status + system health
    """
    if not _store:
        return {}

    try:
        if scene == "copilot":
            return await _copilot_structured()
        elif scene == "mentor":
            return await _mentor_structured()
        elif scene == "coach":
            return await _coach_structured()
        elif scene == "operator":
            return await _operator_structured()
    except Exception as exc:
        logger.warning("Structured data for scene %s failed: %s", scene, exc)

    return {}


async def _copilot_structured() -> dict:
    """copilot panel: recent projects + active tasks summary."""
    recent_projects: list[dict] = []
    active_tasks: list[dict] = []

    try:
        # Recent projects (last 5)
        if hasattr(_store, "list_projects"):
            projects = await _store.list_projects(limit=5)
            recent_projects = [
                {
                    "project_id": str(p.get("project_id") or ""),
                    "title": str(p.get("title") or p.get("name") or ""),
                    "status": str(p.get("status") or ""),
                    "updated_at": str(p.get("updated_at") or ""),
                }
                for p in (projects or [])
                if isinstance(p, dict)
            ]
    except Exception as exc:
        logger.debug("copilot projects fetch failed: %s", exc)

    try:
        # Active tasks (not closed/cancelled, limit 10)
        if hasattr(_store, "list_active_tasks"):
            tasks = await _store.list_active_tasks(limit=10)
            active_tasks = [
                {
                    "task_id": str(t.get("task_id") or ""),
                    "title": str(t.get("title") or ""),
                    "status": str(t.get("status") or ""),
                    "source": str(t.get("source") or ""),
                }
                for t in (tasks or [])
                if isinstance(t, dict)
            ]
    except Exception as exc:
        logger.debug("copilot tasks fetch failed: %s", exc)

    return {
        "recent_projects": recent_projects,
        "active_tasks": active_tasks,
        "active_task_count": len(active_tasks),
    }


async def _mentor_structured() -> dict:
    """mentor panel: learning plans + assignment progress."""
    learning_plans: list[dict] = []
    assignment_progress: list[dict] = []

    try:
        # Learning plans: tasks tagged with source = "scene:mentor"
        if hasattr(_store, "list_tasks_by_source"):
            tasks = await _store.list_tasks_by_source("scene:mentor", limit=10)
            learning_plans = [
                {
                    "task_id": str(t.get("task_id") or ""),
                    "title": str(t.get("title") or ""),
                    "status": str(t.get("status") or ""),
                }
                for t in (tasks or [])
                if isinstance(t, dict)
            ]
    except Exception as exc:
        logger.debug("mentor learning plans fetch failed: %s", exc)

    try:
        # Assignment progress: jobs sourced from mentor scene (last 10)
        if hasattr(_store, "list_jobs_by_source"):
            jobs = await _store.list_jobs_by_source("scene:mentor", limit=10)
            assignment_progress = [
                {
                    "job_id": str(j.get("job_id") or ""),
                    "status": str(j.get("status") or ""),
                    "created_at": str(j.get("created_at") or ""),
                    "closed_at": str(j.get("closed_at") or ""),
                }
                for j in (jobs or [])
                if isinstance(j, dict)
            ]
    except Exception as exc:
        logger.debug("mentor assignment progress fetch failed: %s", exc)

    return {
        "learning_plans": learning_plans,
        "assignment_progress": assignment_progress,
        "plan_count": len(learning_plans),
        "in_progress_count": len(
            [j for j in assignment_progress if str(j.get("status") or "") == "running"]
        ),
    }


async def _coach_structured() -> dict:
    """coach panel: execution rates + performance metrics."""
    metrics: dict = {
        "total_jobs": 0,
        "completed_jobs": 0,
        "failed_jobs": 0,
        "completion_rate": 0.0,
        "avg_step_count": 0.0,
    }

    try:
        if hasattr(_store, "get_job_metrics"):
            raw = await _store.get_job_metrics()
            if isinstance(raw, dict):
                total = int(raw.get("total") or 0)
                completed = int(raw.get("completed") or 0)
                failed = int(raw.get("failed") or 0)
                metrics["total_jobs"] = total
                metrics["completed_jobs"] = completed
                metrics["failed_jobs"] = failed
                metrics["completion_rate"] = round(completed / total, 3) if total else 0.0
                metrics["avg_step_count"] = float(raw.get("avg_step_count") or 0)
    except Exception as exc:
        logger.debug("coach metrics fetch failed: %s", exc)

    return {"performance_metrics": metrics}


async def _operator_structured() -> dict:
    """operator panel: platform status + system health."""
    import urllib.request

    def _http_ok(url: str, timeout: int = 5) -> bool:
        try:
            r = urllib.request.urlopen(url, timeout=timeout)
            return r.status < 400
        except Exception:
            return False

    # Check key platform endpoints
    platform_status = {
        "plane": _http_ok("http://localhost:3000", timeout=3),
        "langfuse": _http_ok("http://localhost:3001", timeout=3),
        "temporal_ui": _http_ok("http://localhost:8080", timeout=3),
        "minio": _http_ok("http://localhost:9001", timeout=3),
    }
    healthy_count = sum(1 for v in platform_status.values() if v)
    total_count = len(platform_status)

    system_health: dict = {
        "overall": "green" if healthy_count == total_count
                   else "yellow" if healthy_count >= total_count // 2
                   else "red",
        "healthy_services": healthy_count,
        "total_services": total_count,
    }

    return {
        "platform_status": platform_status,
        "system_health": system_health,
    }


# ── Job submission helper ────────────────────────────────────────────────

async def _submit_job(action: dict, scene: str, user_content: str, *, user_id: str = "system") -> str | None:
    """Submit a Job to Temporal from an L1 scene action.

    Flow (§4.3 Draft workflow):
      1. Create Plane Draft (DraftIssue) — gives user a chance to review
      2. Convert Draft → Issue (Task in our model)
      3. Create PG task + job records
      4. Start JobWorkflow via Temporal

    workflow_id format: user-{user_id}-job-{uuid4()} (§6.13.2)

    Returns the job_id string or None on failure.
    """
    from uuid import uuid4
    import os

    steps = action.get("steps") or []
    if not steps:
        return None

    title = str(action.get("title") or user_content[:100]).strip()
    description = str(action.get("intent") or user_content[:500]).strip()

    # §4.3: Create Plane Draft first, then convert to Issue
    plane_issue_id = None
    if _plane_client:
        project_id = os.environ.get("PLANE_PROJECT_ID", "")
        if project_id:
            try:
                draft = await _plane_client.create_draft(
                    project_id=project_id,
                    name=title,
                    description=f"<p>{description}</p>",
                )
                draft_id = str(draft.get("id") or "")
                if draft_id:
                    issue = await _plane_client.convert_draft_to_issue(
                        project_id=project_id,
                        draft_id=draft_id,
                    )
                    plane_issue_id = str(issue.get("id") or "")
                    logger.info(
                        "Draft %s → Issue %s for scene %s",
                        draft_id, plane_issue_id, scene,
                    )
            except Exception as exc:
                logger.warning(
                    "Plane Draft creation failed for scene %s: %s (proceeding without Plane)",
                    scene, exc,
                )

    # Create a task record (every job belongs to a task)
    task = await _store.create_task(
        title=title,
        source=f"scene:{scene}",
    )
    task_id = task["task_id"]

    # §3.5: Same Task max 1 non-closed Job
    if await _store.has_active_job_for_task(task_id):
        logger.warning("Task %s already has an active job, skipping submission", task_id)
        return None

    plan = {
        "steps": steps,
        "title": title,
        "source": f"scene:{scene}",
        "brief": action.get("brief") or {},
        "concurrency": action.get("concurrency", 2),
    }
    if plane_issue_id:
        plan["plane_issue_id"] = plane_issue_id

    # §6.13.2: workflow_id includes user_id prefix for traceability
    workflow_id = f"user-{user_id}-job-{uuid4()}"
    job = await _store.create_job(
        task_id=task_id,
        workflow_id=workflow_id,
        dag_snapshot=plan,
    )
    job_id = str(job["job_id"])
    plan["job_id"] = job_id

    from temporal.workflows import JobInput
    await _temporal_client.start_job_workflow(
        workflow_id=workflow_id,
        plan=plan,
    )

    logger.info("Job submitted from scene %s: %s (workflow=%s)", scene, job_id, workflow_id)
    return job_id


async def _submit_direct_job(action: dict, scene: str, user_content: str, *, user_id: str = "system") -> str | None:
    """Submit a single-step direct Job — lightweight path for simple tasks.

    Route: direct (§3.1) — skips Task overhead, creates a single-step Job.
    workflow_id format: user-{user_id}-job-{uuid4()} (§6.13.2)
    """
    from uuid import uuid4

    goal = str(action.get("goal") or user_content[:200]).strip()
    agent_id = str(action.get("agent") or action.get("agent_id") or "engineer").strip()
    title = str(action.get("title") or goal[:100]).strip()

    steps = [{
        "id": "step_0",
        "step_index": 0,
        "goal": goal,
        "agent_id": agent_id,
        "execution_type": action.get("execution_type", "agent"),
        "depends_on": [],
    }]

    task = await _store.create_task(title=title, source=f"scene:{scene}:direct")
    task_id = task["task_id"]

    # §3.5: Same Task max 1 non-closed Job
    if await _store.has_active_job_for_task(task_id):
        logger.warning("Task %s already has an active job, skipping direct submission", task_id)
        return None

    plan = {
        "steps": steps,
        "title": title,
        "source": f"scene:{scene}:direct",
        "concurrency": 1,
    }

    # §6.13.2: workflow_id includes user_id prefix for traceability
    workflow_id = f"user-{user_id}-job-{uuid4()}"
    job = await _store.create_job(
        task_id=task_id, workflow_id=workflow_id, dag_snapshot=plan,
        is_ephemeral=True,  # §3.1: direct jobs are ephemeral
    )
    job_id = str(job["job_id"])
    plan["job_id"] = job_id

    await _temporal_client.start_job_workflow(workflow_id=workflow_id, plan=plan)
    logger.info("Direct job submitted from scene %s: %s (workflow=%s)", scene, job_id, workflow_id)
    return job_id
