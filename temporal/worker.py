"""Daemon Worker — Temporal worker process entry point."""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from temporalio.client import Client
from temporalio.worker import Worker

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daemon_env import load_daemon_env
from temporal.workflows import GraphDispatchWorkflow
from temporal.campaign_workflow import CampaignWorkflow
from temporal.activities import DaemonActivities

logger = logging.getLogger(__name__)


async def start_worker(
    host: str = "127.0.0.1",
    port: int = 7233,
    namespace: str = "default",
    queue: str = "daemon-queue",
    max_concurrent_activities: int = 10,
) -> None:
    client = await Client.connect(f"{host}:{port}", namespace=namespace)
    activities = DaemonActivities()

    worker = Worker(
        client,
        task_queue=queue,
        workflows=[GraphDispatchWorkflow, CampaignWorkflow],
        activities=[
            activities.activity_openclaw_step,
            activities.activity_spine_routine,
            activities.activity_finalize_delivery,
            activities.activity_update_run_status,
            activities.activity_campaign_bootstrap,
            activities.activity_campaign_record_milestone,
            activities.activity_campaign_set_status,
        ],
        max_concurrent_activities=max_concurrent_activities,
    )

    logger.info(f"Daemon Worker started — queue={queue} host={host}:{port}")

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
    load_daemon_env(ROOT)
    host = os.environ.get("TEMPORAL_HOST", "127.0.0.1")
    port = int(os.environ.get("TEMPORAL_PORT", "7233"))
    namespace = os.environ.get("TEMPORAL_NAMESPACE", "default")
    queue = os.environ.get("TEMPORAL_QUEUE", "daemon-queue")
    max_concurrent = int(os.environ.get("TEMPORAL_MAX_CONCURRENT_ACTIVITIES", "10") or 10)
    asyncio.run(
        start_worker(
            host=host,
            port=port,
            namespace=namespace,
            queue=queue,
            max_concurrent_activities=max_concurrent,
        )
    )
