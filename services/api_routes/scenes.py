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

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scenes", tags=["scenes"])

# Session manager will be injected at startup
_session_manager = None
_store = None
_temporal_client = None


def configure(session_manager: Any, store: Any = None, temporal_client: Any = None) -> None:
    """Inject dependencies at startup."""
    global _session_manager, _store, _temporal_client
    _session_manager = session_manager
    _store = store
    _temporal_client = temporal_client


# ── Models ────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    content: str
    metadata: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    ok: bool
    scene: str = ""
    reply: str = ""
    action: dict | None = None
    job_id: str | None = None
    error: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.post("/{scene}/chat", response_model=ChatResponse)
async def scene_chat(scene: str, req: ChatRequest) -> ChatResponse:
    """Send a message to a scene's L1 agent.

    The L1 agent may:
    - Reply directly (action: null or action.type == "direct_response")
    - Create a Job (action.type == "create_job") → submitted to Temporal
    - Create a Task (action.type == "create_task") → creates Plane Issue + Job
    """
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Session manager not initialized")

    result = await _session_manager.send_message(scene, req.content)

    if not result.get("ok"):
        return ChatResponse(
            ok=False,
            scene=scene,
            error=str(result.get("error") or "unknown error"),
        )

    action = result.get("action")
    job_id = None

    # If L1 output contains a structured action, dispatch by routing decision (§3.8)
    # Three routes: direct (single step) / task (multi-step Job) / project (Task DAG)
    if action and _store and _temporal_client and isinstance(action, dict):
        action_type = str(action.get("action") or action.get("route") or "").strip()
        try:
            if action_type in ("create_job", "task", "project"):
                job_id = await _submit_job(action, scene, req.content)
            elif action_type == "direct":
                job_id = await _submit_direct_job(action, scene, req.content)
        except Exception as exc:
            logger.warning("Job submission from scene %s failed: %s", scene, exc)

    return ChatResponse(
        ok=True,
        scene=scene,
        reply=result.get("reply", ""),
        action=action,
        job_id=job_id,
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

    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for scene %s", scene)
    except Exception as exc:
        logger.warning("WebSocket error for scene %s: %s", scene, exc)
        try:
            await ws.close()
        except Exception:
            pass


@router.get("/{scene}/panel")
async def scene_panel(scene: str) -> dict:
    """Get scene panel data: recent messages, digests, decisions."""
    if not _session_manager:
        raise HTTPException(status_code=503, detail="Session manager not initialized")

    return await _session_manager.get_panel_data(scene)


# ── Job submission helper ────────────────────────────────────────────────

async def _submit_job(action: dict, scene: str, user_content: str) -> str | None:
    """Submit a Job to Temporal from an L1 scene action.

    Creates a task + job record in PG, then starts a JobWorkflow.
    Returns the job_id string or None on failure.
    """
    from uuid import uuid4

    steps = action.get("steps") or []
    if not steps:
        return None

    title = str(action.get("title") or user_content[:100]).strip()

    # Create a task record (every job belongs to a task)
    task = await _store.create_task(
        title=title,
        source=f"scene:{scene}",
    )
    task_id = task["task_id"]

    plan = {
        "steps": steps,
        "title": title,
        "source": f"scene:{scene}",
        "brief": action.get("brief") or {},
        "concurrency": action.get("concurrency", 2),
    }

    workflow_id = f"job-{uuid4()}"
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


async def _submit_direct_job(action: dict, scene: str, user_content: str) -> str | None:
    """Submit a single-step direct Job — lightweight path for simple tasks.

    Route: direct (§3.8) — skips Task overhead, creates a single-step Job.
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

    plan = {
        "steps": steps,
        "title": title,
        "source": f"scene:{scene}:direct",
        "concurrency": 1,
    }

    workflow_id = f"job-{uuid4()}"
    job = await _store.create_job(task_id=task_id, workflow_id=workflow_id, dag_snapshot=plan)
    job_id = str(job["job_id"])
    plan["job_id"] = job_id

    await _temporal_client.start_job_workflow(workflow_id=workflow_id, plan=plan)
    logger.info("Direct job submitted from scene %s: %s", scene, job_id)
    return job_id
