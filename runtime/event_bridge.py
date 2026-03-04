"""Cross-process event bridge backed by append-only JSONL files."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class EventBridge:
    """File-based event bridge for communication between API and Worker processes."""

    def __init__(self, state_dir: Path, source: str) -> None:
        self._source = source
        self._root = state_dir / "nerve_bridge"
        self._events_path = self._root / "events.jsonl"
        self._cursor_dir = self._root / "cursors"
        self._root.mkdir(parents=True, exist_ok=True)
        self._cursor_dir.mkdir(parents=True, exist_ok=True)
        if not self._events_path.exists():
            self._events_path.write_text("")

    def _cursor_path(self, consumer: str) -> Path:
        return self._cursor_dir / f"{consumer}.cursor"

    def _load_cursor(self, consumer: str) -> dict[str, Any]:
        path = self._cursor_path(consumer)
        if not path.exists():
            return {"offset": 0, "pending": [], "acked": []}
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {"offset": 0, "pending": [], "acked": []}

        # Backward compatibility with the old "offset-only" cursor format.
        try:
            return {"offset": int(raw), "pending": [], "acked": []}
        except ValueError:
            pass

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {"offset": 0, "pending": [], "acked": []}
        if not isinstance(data, dict):
            return {"offset": 0, "pending": [], "acked": []}

        offset = data.get("offset", 0)
        pending = data.get("pending", [])
        acked = data.get("acked", [])
        if not isinstance(offset, int) or offset < 0:
            offset = 0
        if not isinstance(pending, list):
            pending = []
        if not isinstance(acked, list):
            acked = []
        pending = [x for x in pending if isinstance(x, dict) and x.get("event_id")]
        acked = [str(x) for x in acked if x]
        return {"offset": offset, "pending": pending, "acked": acked}

    def _save_cursor(self, consumer: str, state: dict[str, Any]) -> None:
        path = self._cursor_path(consumer)
        payload = {
            "offset": int(state.get("offset", 0)),
            "pending": state.get("pending", []),
            "acked": state.get("acked", []),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False))

    def emit(self, event: str, payload: dict[str, Any] | None = None) -> str:
        event_id = f"evb_{uuid.uuid4().hex[:12]}"
        record = {
            "event_id": event_id,
            "event": event,
            "payload": payload or {},
            "source": self._source,
            "created_utc": _utc(),
            "consumed_utc": None,
            "status": "new",
        }
        with self._events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return event_id

    def consume(self, consumer: str, limit: int = 100) -> list[dict]:
        """Read unconsumed events for this consumer.

        Cursor state persists both file offset and in-flight events. This avoids event loss
        when a process crashes after consume() but before acknowledge().
        """
        limit = max(1, min(int(limit), 1000))
        state = self._load_cursor(consumer)
        offset = int(state.get("offset", 0))
        pending: list[dict] = list(state.get("pending", []))
        acked: list[str] = list(state.get("acked", []))
        pending_ids = {str(item.get("event_id")) for item in pending if item.get("event_id")}
        acked_ids = set(acked)

        with self._events_path.open("r", encoding="utf-8") as f:
            f.seek(offset)
            while True:
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                if record.get("status") != "new":
                    continue
                if str(record.get("source") or "") == consumer:
                    continue
                event_id = str(record.get("event_id") or "")
                if not event_id or event_id in pending_ids or event_id in acked_ids:
                    continue
                pending.append(record)
                pending_ids.add(event_id)
            state["offset"] = f.tell()

        # Keep bounded history per consumer.
        if len(acked) > 5000:
            acked = acked[-5000:]
        if len(pending) > 5000:
            pending = pending[-5000:]
        state["pending"] = pending
        state["acked"] = acked
        self._save_cursor(consumer, state)
        return pending[:limit]

    def acknowledge(self, event_id: str, event: str, payload: dict[str, Any], consumer: str) -> None:
        """Acknowledge one event and append a consumed marker for auditability."""
        state = self._load_cursor(consumer)
        pending = [x for x in state.get("pending", []) if str(x.get("event_id") or "") != str(event_id)]
        acked = [str(x) for x in state.get("acked", []) if x]
        if event_id not in acked:
            acked.append(str(event_id))
        if len(acked) > 5000:
            acked = acked[-5000:]
        state["pending"] = pending
        state["acked"] = acked
        self._save_cursor(consumer, state)

        marker = {
            "event_id": event_id,
            "event": event,
            "payload": payload,
            "source": consumer,
            "created_utc": _utc(),
            "consumed_utc": _utc(),
            "status": "consumed",
        }
        with self._events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(marker, ensure_ascii=False) + "\n")

    def recent(self, limit: int = 100) -> list[dict]:
        try:
            lines = self._events_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        out: list[dict] = []
        for line in lines[-limit:]:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
