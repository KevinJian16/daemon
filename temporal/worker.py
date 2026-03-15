"""Daemon Worker — Temporal worker process entry point.

Registers all workflows and activities with the Temporal task queue.

Reference: SYSTEM_DESIGN.md §2.2, §6.9
"""
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
from temporal.workflows import (
    JobWorkflow,
    HealthCheckWorkflow,
    SelfHealWorkflow,
    MaintenanceWorkflow,
    BackupWorkflow,
)
from temporal.activities import DaemonActivities
from temporal.activities_health import (
    activity_health_check_infrastructure,
    activity_health_check_quality,
    activity_health_check_frontier,
    activity_health_report,
    activity_self_heal_diagnose,
    activity_self_heal_fix,
    activity_self_heal_restart,
    activity_self_heal_verify,
    activity_self_heal_notify_failure,
    activity_backup,
)

logger = logging.getLogger(__name__)


async def _create_pool():
    """Create asyncpg connection pool."""
    import asyncpg
    pg_url = os.environ.get(
        "DATABASE_URL",
        f"postgresql://{os.environ.get('POSTGRES_USER', 'daemon')}:"
        f"{os.environ.get('POSTGRES_PASSWORD', 'daemon')}@"
        f"{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:"
        f"{os.environ.get('POSTGRES_PORT', '5432')}/"
        f"{os.environ.get('POSTGRES_DB', 'daemon')}"
    )
    return await asyncpg.create_pool(pg_url, min_size=2, max_size=10)


async def _register_schedules(client: Client, queue: str) -> None:
    """Register Temporal Schedules for periodic workflows.

    Replaces old Cadence/Spine routines (§3.2, §7.7).
    Idempotent — creates schedules only if they don't exist.
    """
    from temporalio.client import Schedule, ScheduleActionStartWorkflow, ScheduleSpec, ScheduleIntervalSpec
    from datetime import timedelta

    schedules = [
        {
            "id": "daemon-maintenance",
            "workflow": "MaintenanceWorkflow",
            "interval": timedelta(hours=6),
            "args": [{}],
        },
        {
            "id": "daemon-health-check",
            "workflow": "HealthCheckWorkflow",
            "interval": timedelta(days=7),
            "args": [{}],
        },
        {
            "id": "daemon-backup",
            "workflow": "BackupWorkflow",
            "interval": timedelta(days=1),
            "args": [{}],
        },
    ]

    for sched in schedules:
        try:
            # Check if schedule already exists
            try:
                await client.get_schedule_handle(sched["id"]).describe()
                logger.info("Schedule %s already exists, skipping", sched["id"])
                continue
            except Exception:
                pass

            await client.create_schedule(
                sched["id"],
                Schedule(
                    action=ScheduleActionStartWorkflow(
                        sched["workflow"],
                        args=sched["args"],
                        id=f"{sched['id']}-run",
                        task_queue=queue,
                    ),
                    spec=ScheduleSpec(
                        intervals=[ScheduleIntervalSpec(every=sched["interval"])],
                    ),
                ),
            )
            logger.info("Schedule registered: %s (every %s)", sched["id"], sched["interval"])
        except Exception as exc:
            logger.warning("Failed to register schedule %s: %s", sched["id"], exc)


async def start_worker(
    host: str = "127.0.0.1",
    port: int = 7233,
    namespace: str = "default",
    queue: str = "daemon-queue",
    max_concurrent_activities: int = 10,
) -> None:
    client = await Client.connect(f"{host}:{port}", namespace=namespace)

    # Create shared resources
    from services.event_bus import EventBus
    pool = await _create_pool()
    pg_url = os.environ.get(
        "DATABASE_URL",
        f"postgresql://{os.environ.get('POSTGRES_USER', 'daemon')}:"
        f"{os.environ.get('POSTGRES_PASSWORD', 'daemon')}@"
        f"{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:"
        f"{os.environ.get('POSTGRES_PORT', '5432')}/"
        f"{os.environ.get('POSTGRES_DB', 'daemon')}"
    )
    event_bus = EventBus(pg_url)
    await event_bus.connect(pool)

    # Instantiate activity classes
    daemon_activities = DaemonActivities(pool, event_bus)

    # All activities: class methods + standalone functions
    activities = [
        # DaemonActivities (class methods)
        daemon_activities.activity_execute_step,
        daemon_activities.activity_direct_step,
        daemon_activities.activity_cc_step,
        daemon_activities.activity_update_job_status,
        daemon_activities.activity_update_step_status,
        daemon_activities.activity_replan_gate,
        daemon_activities.activity_maintenance,
        # Health check activities (standalone)
        activity_health_check_infrastructure,
        activity_health_check_quality,
        activity_health_check_frontier,
        activity_health_report,
        # Self-heal activities (standalone)
        activity_self_heal_diagnose,
        activity_self_heal_fix,
        activity_self_heal_restart,
        activity_self_heal_verify,
        activity_self_heal_notify_failure,
        # Backup activity (standalone)
        activity_backup,
    ]

    worker = Worker(
        client,
        task_queue=queue,
        workflows=[
            JobWorkflow,
            HealthCheckWorkflow,
            SelfHealWorkflow,
            MaintenanceWorkflow,
            BackupWorkflow,
        ],
        activities=activities,
        max_concurrent_activities=max_concurrent_activities,
    )

    logger.info("Daemon Worker started — queue=%s host=%s:%s", queue, host, port)

    # Register Temporal Schedules (replaces Cadence/Spine routines)
    await _register_schedules(client, queue)

    loop = asyncio.get_event_loop()
    stop = asyncio.Event()

    def _shutdown(sig: int) -> None:
        logger.info("Received signal %s, shutting down worker...", sig)
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown, sig)

    try:
        async with worker:
            await stop.wait()
    finally:
        await event_bus.close()
        await pool.close()

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
