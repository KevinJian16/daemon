"""PG LISTEN/NOTIFY event bus — replaces Ether (JSONL append + file watcher).

Reference: SYSTEM_DESIGN.md §6.4, SYSTEM_DESIGN_REFERENCE.md Appendix D.3
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import asyncpg

logger = logging.getLogger(__name__)

# Type alias for event callbacks
EventCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class EventBus:
    """Async PG event bus using LISTEN/NOTIFY.

    Channels (see Appendix D.3):
      - job_events: job_created, job_closed, job_paused
      - step_events: step_started, step_completed, step_failed, step_pending_confirmation
      - webhook_events: plane_webhook_received
      - system_events: health_check_completed, schedule_fired

    Auto-reconnects LISTEN connection on failure with exponential backoff.
    """

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._conn: asyncpg.Connection | None = None
        self._callbacks: dict[str, list[EventCallback]] = {}
        self._pool: asyncpg.Pool | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._closed = False

    async def connect(self, pool: asyncpg.Pool | None = None) -> None:
        """Connect to PG for LISTEN. Optionally share a pool for NOTIFY."""
        self._pool = pool
        self._closed = False
        await self._connect_listener()
        logger.info("EventBus connected, listening on %d channels", len(self._callbacks))

    async def _connect_listener(self) -> None:
        """Establish LISTEN connection and register all channel listeners."""
        self._conn = await asyncpg.connect(self._dsn)
        self._conn.add_termination_listener(self._on_connection_lost)
        for channel in self._callbacks:
            await self._conn.add_listener(channel, self._dispatch)

    def _on_connection_lost(self, conn: asyncpg.Connection) -> None:
        """Called by asyncpg when the LISTEN connection drops."""
        if self._closed:
            return
        logger.warning("EventBus LISTEN connection lost, scheduling reconnect")
        self._conn = None
        if self._reconnect_task is None or self._reconnect_task.done():
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Reconnect with exponential backoff (1s → 2s → 4s → ... → 60s cap)."""
        delay = 1.0
        max_delay = 60.0
        while not self._closed:
            try:
                await self._connect_listener()
                logger.info("EventBus reconnected, listening on %d channels", len(self._callbacks))
                return
            except Exception as exc:
                logger.warning("EventBus reconnect failed (retry in %.0fs): %s", delay, exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

    async def close(self) -> None:
        self._closed = True
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            self._reconnect_task = None
        if self._conn:
            try:
                for channel in self._callbacks:
                    await self._conn.remove_listener(channel, self._dispatch)
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    def subscribe(self, channel: str, callback: EventCallback) -> None:
        """Register a callback for a channel. Call before connect()."""
        self._callbacks.setdefault(channel, []).append(callback)

    def unsubscribe(self, channel: str, callback: EventCallback | None = None) -> None:
        """Remove callback(s) for a channel."""
        if callback is None:
            self._callbacks.pop(channel, None)
        elif channel in self._callbacks:
            self._callbacks[channel] = [
                cb for cb in self._callbacks[channel] if cb is not callback
            ]

    async def publish(self, channel: str, event_type: str, payload: dict[str, Any]) -> None:
        """Publish an event: INSERT into event_log (trigger fires pg_notify)."""
        pool = self._pool
        if pool is None:
            raise RuntimeError("EventBus.publish() requires a pool — call connect(pool=...) first")

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO event_log (channel, event_type, payload)
                VALUES ($1, $2, $3)
                """,
                channel,
                event_type,
                json.dumps(payload),
            )

    def _dispatch(
        self,
        connection: asyncpg.Connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Internal: called by asyncpg when a NOTIFY arrives."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("EventBus: invalid JSON on channel %s: %s", channel, payload)
            return

        callbacks = self._callbacks.get(channel, [])
        for cb in callbacks:
            asyncio.create_task(self._safe_call(cb, data))

    @staticmethod
    async def _safe_call(cb: EventCallback, data: dict) -> None:
        try:
            await cb(data)
        except Exception:
            logger.exception("EventBus callback error")
