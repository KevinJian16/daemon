"""Temporal client wrapper — thin facade over temporalio SDK."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from temporalio.client import Client, WorkflowHandle
from temporalio.common import RetryPolicy


class TemporalClient:
    """Thin facade over temporalio.client.Client for workflow submission and querying."""

    def __init__(self, client: Client, queue: str) -> None:
        self._client = client
        self._queue = queue

    @classmethod
    async def connect(cls, host: str = "127.0.0.1", port: int = 7233, namespace: str = "default", queue: str = "daemon-queue") -> "TemporalClient":
        client = await Client.connect(f"{host}:{port}", namespace=namespace)
        return cls(client, queue)

    async def submit(
        self,
        workflow_id: str,
        plan: dict,
        run_root: str,
        workflow_name: str = "GraphDispatchWorkflow",
    ) -> str:
        """Submit a workflow and return the run_id.

        Temporal dev server may report transient shard/timeout errors right after
        startup; retry a few times before surfacing a hard failure.
        """
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                handle: WorkflowHandle = await self._client.start_workflow(
                    workflow_name,
                    args=[{"plan": plan, "run_root": run_root}],
                    id=workflow_id,
                    task_queue=self._queue,
                )
                return handle.result_run_id or workflow_id
            except Exception as exc:
                last_err = exc
                msg = str(exc).lower()
                if "already started" in msg:
                    return workflow_id
                if attempt >= 3:
                    break
                await asyncio.sleep(0.8 + attempt * 0.8)
        if last_err is not None:
            raise last_err
        raise RuntimeError("temporal_submit_failed_without_exception")

    async def cancel(self, workflow_id: str) -> None:
        handle = self._client.get_workflow_handle(workflow_id)
        await handle.cancel()

    async def signal(self, workflow_id: str, signal_name: str, payload: dict | None = None) -> None:
        handle = self._client.get_workflow_handle(workflow_id)
        await handle.signal(signal_name, payload or {})

    async def status(self, workflow_id: str) -> str:
        try:
            handle = self._client.get_workflow_handle(workflow_id)
            desc = await handle.describe()
            return str(desc.status.name).lower() if desc.status else "unknown"
        except Exception as e:
            return f"error: {str(e)[:60]}"

    def health_check(self) -> str:
        """Synchronous check: attempt TCP connection to Temporal server."""
        import socket
        try:
            host, port_str = self._client.service_client.config.target_host.rsplit(":", 1)
            port = int(port_str)
            sock = socket.create_connection((host, port), timeout=3)
            sock.close()
            return "ok"
        except Exception as e:
            return f"unreachable: {str(e)[:60]}"
