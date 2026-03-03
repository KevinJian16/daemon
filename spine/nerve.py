"""Nerve — lightweight in-process event bus with trace recording."""
from __future__ import annotations

import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Nerve:
    """Synchronous in-process event bus. Handlers run inline; all events are traced."""

    def __init__(self, history_size: int = 200) -> None:
        self._handlers: dict[str, list[Callable]] = {}
        self._history: deque[dict] = deque(maxlen=history_size)

    def on(self, event: str, handler: Callable[[dict], None]) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, payload: dict | None = None) -> str:
        event_id = f"ev_{uuid.uuid4().hex[:10]}"
        record: dict[str, Any] = {
            "event_id": event_id,
            "event": event,
            "payload": payload or {},
            "timestamp": _utc(),
            "handler_errors": [],
        }
        for handler in self._handlers.get(event, []):
            try:
                handler(payload or {})
            except Exception as e:
                record["handler_errors"].append({"handler": getattr(handler, "__name__", "?"), "error": str(e)[:200]})
        self._history.append(record)
        return event_id

    def recent(self, limit: int = 50) -> list[dict]:
        items = list(self._history)
        return items[-limit:]

    def event_count(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self._history:
            counts[item["event"]] = counts.get(item["event"], 0) + 1
        return counts
