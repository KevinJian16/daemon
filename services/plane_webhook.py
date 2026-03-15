"""Plane webhook handler.

Reference: SYSTEM_DESIGN.md §2.4, TODO.md Phase 2.4
"""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request

from services.plane_client import PlaneClient

logger = logging.getLogger(__name__)

router = APIRouter()

# Injected at startup via configure()
_webhook_secret: str = ""
_store = None
_event_bus = None
_temporal_client = None


def configure(
    webhook_secret: str,
    store=None,
    event_bus=None,
    temporal_client=None,
) -> None:
    """Set dependencies for webhook processing."""
    global _webhook_secret, _store, _event_bus, _temporal_client
    _webhook_secret = webhook_secret
    _store = store
    _event_bus = event_bus
    _temporal_client = temporal_client


@router.post("/webhooks/plane")
async def handle_plane_webhook(
    request: Request,
    x_plane_signature: str = Header(default="", alias="X-Plane-Signature"),
    x_plane_delivery: str = Header(default="", alias="X-Plane-Delivery"),
) -> dict[str, str]:
    """Handle incoming Plane webhook events.

    Events processed:
      - issue.created: sync to daemon_tasks if not daemon-originated
      - issue.updated: emit event for state change tracking
      - issue.deleted: cleanup associated Jobs
    """
    body = await request.body()

    # Verify signature
    if _webhook_secret:
        if not PlaneClient.verify_webhook_signature(
            body, x_plane_signature, _webhook_secret
        ):
            raise HTTPException(status_code=403, detail="Invalid webhook signature")

    # Parse payload
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = payload.get("event", "")
    data = payload.get("data", {})

    logger.info(
        "Plane webhook: event=%s delivery=%s issue=%s",
        event,
        x_plane_delivery,
        data.get("id", "?"),
    )

    # Dispatch by event type
    if event == "issue":
        action = payload.get("action", "")
        if action == "created":
            await _on_issue_created(data)
        elif action == "updated":
            await _on_issue_updated(data, payload.get("changed_fields", {}))
        elif action == "deleted":
            await _on_issue_deleted(data)

    return {"status": "ok"}


async def _on_issue_created(data: dict) -> None:
    """Handle issue.created — sync to daemon_tasks if not daemon-originated.

    If the issue was created externally (via Plane UI), create a corresponding
    daemon_task record. If daemon created it, the task already exists — skip.
    """
    issue_id = data.get("id")
    if not issue_id or not _store:
        return

    try:
        issue_uuid = UUID(str(issue_id))
    except (ValueError, TypeError):
        logger.warning("Invalid issue ID from webhook: %s", issue_id)
        return

    # Check if daemon already has a task for this issue
    existing = await _store.get_task_by_plane_issue(issue_uuid)
    if existing:
        logger.debug("Issue %s already tracked as daemon task, skipping", issue_id)
        return

    # Create a daemon task for this externally-created issue
    project_id = data.get("project")
    task = await _store.create_task(
        plane_issue_id=issue_uuid,
        project_id=UUID(str(project_id)) if project_id else None,
        trigger_type="manual",
    )

    if _event_bus:
        await _event_bus.publish("webhook_events", "issue_created", {
            "plane_issue_id": str(issue_uuid),
            "task_id": str(task["task_id"]) if isinstance(task, dict) else str(task),
            "source": "plane_webhook",
        })

    logger.info("Created daemon task for external Plane issue %s", issue_id)


async def _on_issue_updated(data: dict, changed_fields: dict) -> None:
    """Handle issue.updated — emit event for downstream processing.

    State changes in Plane (e.g., priority change, assignee change) are
    forwarded as events. The L1 session manager or Temporal workflows can
    react to these events.
    """
    issue_id = data.get("id")
    if not issue_id:
        return

    logger.debug(
        "Plane issue.updated: %s changed=%s",
        issue_id,
        list(changed_fields.keys()),
    )

    if _event_bus and changed_fields:
        await _event_bus.publish("webhook_events", "issue_updated", {
            "plane_issue_id": str(issue_id),
            "changed_fields": list(changed_fields.keys()),
            "source": "plane_webhook",
        })


async def _on_issue_deleted(data: dict) -> None:
    """Handle issue.deleted — cleanup associated daemon data.

    When a Plane issue is deleted, cancel any running Jobs associated
    with the corresponding daemon task.
    """
    issue_id = data.get("id")
    if not issue_id:
        return

    logger.info("Plane issue.deleted: %s", issue_id)

    if _event_bus:
        await _event_bus.publish("webhook_events", "issue_deleted", {
            "plane_issue_id": str(issue_id),
            "source": "plane_webhook",
        })
