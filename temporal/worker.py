"""Daemon Worker — Temporal worker process entry point."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from temporalio.client import Client
from temporalio.worker import Worker

from temporal.workflows import GraphDispatchWorkflow
from temporal.activities import DaemonActivities

logger = logging.getLogger(__name__)


async def start_worker(
    host: str = "127.0.0.1",
    port: int = 7233,
    namespace: str = "default",
    task_queue: str = "daemon-queue",
    max_concurrent_activities: int = 10,
) -> None:
    client = await Client.connect(f"{host}:{port}", namespace=namespace)
    activities = DaemonActivities()

    worker = Worker(
        client,
        task_queue=task_queue,
        workflows=[GraphDispatchWorkflow],
        activities=[
            activities.activity_openclaw_step,
            activities.activity_spine_routine,
            activities.activity_finalize_delivery,
            activities.activity_update_task_status,
        ],
        max_concurrent_activities=max_concurrent_activities,
    )

    logger.info(f"Daemon Worker started — task_queue={task_queue} host={host}:{port}")

    loop = asyncio.get_event_loop()
    stop = asyncio.Event()

    def _shutdown(sig: int) -> None:
        logger.info(f"Received signal {sig}, shutting down worker...")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    async with worker:
        await stop.wait()

    logger.info("Daemon Worker stopped.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    host = os.environ.get("TEMPORAL_HOST", "127.0.0.1")
    port = int(os.environ.get("TEMPORAL_PORT", "7233"))
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "daemon-queue")
    asyncio.run(start_worker(host=host, port=port, namespace=namespace, task_queue=task_queue))
