"""Plane REST API thin client.

Reference: SYSTEM_DESIGN.md §2, TODO.md Phase 2.3
Plane API docs: https://developers.plane.so/
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class PlaneAPIError(Exception):
    """Plane API returned a non-2xx response."""

    def __init__(self, status: int, body: Any, method: str, path: str):
        self.status = status
        self.body = body
        self.method = method
        self.path = path
        super().__init__(f"Plane API {method} {path} → {status}: {body}")


@dataclass
class PlaneClient:
    """Async Plane REST API client.

    Initialise once at API process startup, reuse across requests.
    """

    api_url: str
    api_token: str
    workspace_slug: str
    _client: httpx.AsyncClient = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.api_url.rstrip("/"),
            headers={
                "X-API-Key": self.api_token,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> Any:
        resp = await self._client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            raise PlaneAPIError(resp.status_code, body, method, path)
        if resp.status_code == 204:
            return None
        return resp.json()

    def _ws(self) -> str:
        return f"/api/v1/workspaces/{self.workspace_slug}"

    def _proj(self, project_id: str) -> str:
        return f"{self._ws()}/projects/{project_id}"

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    async def create_project(
        self, name: str, description: str = "", **extra: Any
    ) -> dict:
        return await self._request(
            "POST",
            f"{self._ws()}/projects/",
            json={"name": name, "description": description, **extra},
        )

    async def get_project(self, project_id: str) -> dict:
        return await self._request("GET", f"{self._proj(project_id)}/")

    async def list_projects(self) -> list[dict]:
        data = await self._request("GET", f"{self._ws()}/projects/")
        return data.get("results", data) if isinstance(data, dict) else data

    # ------------------------------------------------------------------
    # Issues (= Tasks)
    # ------------------------------------------------------------------

    async def create_issue(
        self, project_id: str, name: str, description: str = "", **extra: Any
    ) -> dict:
        return await self._request(
            "POST",
            f"{self._proj(project_id)}/issues/",
            json={"name": name, "description_html": description, **extra},
        )

    async def get_issue(self, project_id: str, issue_id: str) -> dict:
        return await self._request(
            "GET", f"{self._proj(project_id)}/issues/{issue_id}/"
        )

    async def update_issue(
        self, project_id: str, issue_id: str, **fields: Any
    ) -> dict:
        return await self._request(
            "PATCH",
            f"{self._proj(project_id)}/issues/{issue_id}/",
            json=fields,
        )

    async def list_issues(
        self, project_id: str, filters: dict | None = None
    ) -> list[dict]:
        params = filters or {}
        data = await self._request(
            "GET", f"{self._proj(project_id)}/issues/", params=params
        )
        return data.get("results", data) if isinstance(data, dict) else data

    # ------------------------------------------------------------------
    # Draft Issues
    # ------------------------------------------------------------------

    async def create_draft(
        self, project_id: str, name: str, description: str = ""
    ) -> dict:
        return await self._request(
            "POST",
            f"{self._proj(project_id)}/draft-issues/",
            json={"name": name, "description_html": description},
        )

    async def list_drafts(self, project_id: str) -> list[dict]:
        data = await self._request(
            "GET", f"{self._proj(project_id)}/draft-issues/"
        )
        return data.get("results", data) if isinstance(data, dict) else data

    async def convert_draft_to_issue(
        self, project_id: str, draft_id: str
    ) -> dict:
        return await self._request(
            "POST",
            f"{self._proj(project_id)}/draft-issues/{draft_id}/convert/",
        )

    # ------------------------------------------------------------------
    # Issue Relations (Task dependencies)
    # ------------------------------------------------------------------

    async def create_relation(
        self,
        project_id: str,
        issue_id: str,
        related_issue_id: str,
        relation_type: str = "blocked_by",
    ) -> dict:
        return await self._request(
            "POST",
            f"{self._proj(project_id)}/issues/{issue_id}/relation/",
            json={
                "related_list": [related_issue_id],
                "relation_type": relation_type,
            },
        )

    async def list_relations(
        self, project_id: str, issue_id: str
    ) -> list[dict]:
        data = await self._request(
            "GET", f"{self._proj(project_id)}/issues/{issue_id}/relation/"
        )
        return data if isinstance(data, list) else data.get("results", [])

    # ------------------------------------------------------------------
    # Issue Comments (activity flow)
    # ------------------------------------------------------------------

    async def add_comment(
        self, project_id: str, issue_id: str, body: str
    ) -> dict:
        return await self._request(
            "POST",
            f"{self._proj(project_id)}/issues/{issue_id}/comments/",
            json={"comment_html": body},
        )

    async def list_comments(
        self, project_id: str, issue_id: str
    ) -> list[dict]:
        data = await self._request(
            "GET", f"{self._proj(project_id)}/issues/{issue_id}/comments/"
        )
        return data.get("results", data) if isinstance(data, dict) else data

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------

    async def list_webhooks(self) -> list[dict]:
        """List all webhooks for the workspace."""
        data = await self._request("GET", f"{self._ws()}/webhooks/")
        return data if isinstance(data, list) else data.get("results", [])

    async def create_webhook(
        self, url: str, events: list[str] | None = None
    ) -> dict:
        payload: dict[str, Any] = {"url": url}
        if events:
            # Plane webhook supports event filtering
            for evt in events:
                payload[evt] = True
        return await self._request(
            "POST", f"{self._ws()}/webhooks/", json=payload
        )

    # ------------------------------------------------------------------
    # Webhook signature verification (static)
    # ------------------------------------------------------------------

    @staticmethod
    def verify_webhook_signature(
        payload_body: bytes, signature: str, secret: str
    ) -> bool:
        """Verify Plane webhook HMAC-SHA256 signature."""
        expected = hmac.new(
            secret.encode(), payload_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)
