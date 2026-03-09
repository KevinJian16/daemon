"""Nerve — in-process event bus with file persistence."""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Nerve:
    """Synchronous in-process event bus with persistent events.jsonl log."""

    def __init__(self, state_dir: Path | None = None, history_size: int = 200) -> None:
        self._handlers: dict[str, list[Callable]] = {}
        self._history: deque[dict] = deque(maxlen=history_size)
        self._events_path = state_dir / "events.jsonl" if state_dir else None

    def on(self, event: str, handler: Callable[[dict], None]) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, payload: dict | None = None) -> str:
        event_id = f"ev_{uuid.uuid4().hex[:10]}"
        now = _utc()
        record: dict[str, Any] = {
            "event_id": event_id,
            "event": event,
            "payload": payload or {},
            "timestamp": now,
            "consumed_utc": None,
            "handler_errors": [],
        }
        for handler in self._handlers.get(event, []):
            try:
                handler(payload or {})
                record["consumed_utc"] = _utc()
            except Exception as e:
                record["handler_errors"].append({
                    "handler": getattr(handler, "__name__", "?"),
                    "error": str(e)[:200],
                })
        self._history.append(record)
        self._persist(record)
        return event_id

    def recent(self, limit: int = 50) -> list[dict]:
        items = list(self._history)
        return items[-limit:]

    def event_count(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self._history:
            counts[item["event"]] = counts.get(item["event"], 0) + 1
        return counts

    def replay_unconsumed(self) -> int:
        """Replay events from events.jsonl that have no consumed_utc. Called on startup."""
        if not self._events_path or not self._events_path.exists():
            return 0
        replayed = 0
        try:
            lines = self._events_path.read_text(encoding="utf-8").splitlines()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("consumed_utc"):
                    continue
                event = str(record.get("event") or "")
                payload = record.get("payload") or {}
                for handler in self._handlers.get(event, []):
                    try:
                        handler(payload)
                    except Exception as exc:
                        logger.warning("Replay handler error for %s: %s", event, exc)
                replayed += 1
        except Exception as exc:
            logger.warning("Failed to replay unconsumed events: %s", exc)
        return replayed

    def _persist(self, record: dict) -> None:
        if not self._events_path:
            return
        try:
            self._events_path.parent.mkdir(parents=True, exist_ok=True)
            with self._events_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed to persist event: %s", exc)
