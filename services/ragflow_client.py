"""RAGFlow integration client — document upload, search, delete.

RAGFlow provides deep document parsing + chunking + retrieval for the
daemon knowledge layer. Runs at http://localhost:9380 by default.

Reference: SYSTEM_DESIGN.md §5.6, TODO.md Phase HIGH Knowledge & Learning
"""
from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "http://localhost:9380"
_DEFAULT_TIMEOUT = 30.0


class RAGFlowClient:
    """Minimal async client for RAGFlow HTTP API.

    Supports: upload document, search knowledge, delete document.
    Uses the RAGFlow v1 REST API with API-Key auth header.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        dataset_id: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = (
            base_url or os.environ.get("RAGFLOW_BASE_URL", _DEFAULT_BASE_URL)
        ).rstrip("/")
        self._api_key = api_key or os.environ.get("RAGFLOW_API_KEY", "")
        self._dataset_id = dataset_id or os.environ.get("RAGFLOW_DATASET_ID", "")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── Upload document ──────────────────────────────────────────────

    async def upload_document(
        self,
        file_path: str,
        *,
        dataset_id: str | None = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Upload a document to RAGFlow for parsing and indexing.

        Args:
            file_path: Local path to the file to upload.
            dataset_id: Override default dataset. Falls back to RAGFLOW_DATASET_ID.
            name: Display name for the document.

        Returns:
            RAGFlow response dict with document ID.
        """
        ds_id = dataset_id or self._dataset_id
        if not ds_id:
            return {"ok": False, "error": "no dataset_id configured"}

        client = await self._get_client()

        import os as _os
        filename = name or _os.path.basename(file_path)

        try:
            with open(file_path, "rb") as f:
                # RAGFlow upload endpoint uses multipart form
                resp = await client.post(
                    f"/api/v1/datasets/{ds_id}/documents",
                    files={"file": (filename, f)},
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=60.0,
                )
                resp.raise_for_status()
                data = resp.json()
                logger.info("RAGFlow: uploaded %s → %s", filename, data.get("data", {}).get("id", "?"))
                return {"ok": True, "data": data.get("data", data)}
        except httpx.HTTPStatusError as exc:
            error_msg = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.warning("RAGFlow upload failed: %s", error_msg)
            return {"ok": False, "error": error_msg}
        except Exception as exc:
            logger.warning("RAGFlow upload error: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    # ── Search knowledge ─────────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        dataset_ids: list[str] | None = None,
        top_k: int = 5,
        similarity_threshold: float = 0.2,
    ) -> dict[str, Any]:
        """Search for relevant knowledge chunks.

        Args:
            query: Natural language search query.
            dataset_ids: List of dataset IDs to search. Falls back to default.
            top_k: Maximum number of results.
            similarity_threshold: Minimum similarity score.

        Returns:
            Dict with 'chunks' list of matching results.
        """
        ds_ids = dataset_ids or ([self._dataset_id] if self._dataset_id else [])

        client = await self._get_client()

        try:
            payload = {
                "question": query,
                "dataset_ids": ds_ids,
                "top_k": top_k,
                "similarity_threshold": similarity_threshold,
            }
            resp = await client.post("/api/v1/retrieval", json=payload)
            resp.raise_for_status()
            data = resp.json()
            chunks = data.get("data", {}).get("chunks", [])
            logger.debug("RAGFlow search: %d chunks for query '%s'", len(chunks), query[:60])
            return {"ok": True, "chunks": chunks}
        except httpx.HTTPStatusError as exc:
            error_msg = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.warning("RAGFlow search failed: %s", error_msg)
            return {"ok": False, "error": error_msg, "chunks": []}
        except Exception as exc:
            logger.warning("RAGFlow search error: %s", exc)
            return {"ok": False, "error": str(exc)[:200], "chunks": []}

    # ── Delete document ──────────────────────────────────────────────

    async def delete_document(
        self,
        document_id: str,
        *,
        dataset_id: str | None = None,
    ) -> dict[str, Any]:
        """Delete a document from RAGFlow.

        Args:
            document_id: RAGFlow document ID to delete.
            dataset_id: Override default dataset.

        Returns:
            Success/failure dict.
        """
        ds_id = dataset_id or self._dataset_id
        if not ds_id:
            return {"ok": False, "error": "no dataset_id configured"}

        client = await self._get_client()

        try:
            resp = await client.delete(
                f"/api/v1/datasets/{ds_id}/documents",
                json={"ids": [document_id]},
            )
            resp.raise_for_status()
            logger.info("RAGFlow: deleted document %s from dataset %s", document_id, ds_id)
            return {"ok": True, "document_id": document_id}
        except httpx.HTTPStatusError as exc:
            error_msg = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
            logger.warning("RAGFlow delete failed: %s", error_msg)
            return {"ok": False, "error": error_msg}
        except Exception as exc:
            logger.warning("RAGFlow delete error: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    # ── Health check ─────────────────────────────────────────────────

    async def healthy(self) -> bool:
        """Check if RAGFlow is reachable."""
        try:
            client = await self._get_client()
            resp = await client.get("/api/v1/datasets", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False
