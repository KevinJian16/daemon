"""Ledger — unified state file access for daemon runtime metadata."""
from __future__ import annotations

import fcntl
import json
import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Ledger:
    """Centralized read/write helpers for state JSON files."""

    _locks_guard = threading.Lock()
    _locks: dict[str, threading.Lock] = {}

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.deeds_path = self.state_dir / "deeds.json"
        self.ward_path = self.state_dir / "ward.json"
        self.schedule_history_path = self.state_dir / "schedule_history.json"

    @classmethod
    def _lock_for(cls, path: Path) -> threading.Lock:
        key = str(path)
        with cls._locks_guard:
            lk = cls._locks.get(key)
            if lk is None:
                lk = threading.Lock()
                cls._locks[key] = lk
            return lk

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read state file %s: %s", path, exc)
            return default
        return data

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex[:8]}")
        lock = self._lock_for(path)
        with lock:
            lock_path = path.with_suffix(path.suffix + ".lock")
            with open(lock_path, "a+") as fd:
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                    tmp.replace(path)
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)

    def _locked_rw(self, path: Path, default: Any, transform: Callable[[Any], Any]) -> Any:
        """Read-transform-write under both threading.Lock and cross-process fcntl.flock.

        ``transform`` receives the current data and must return the new data to write.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = self._lock_for(path)
        with lock:
            lock_path = path.with_suffix(path.suffix + ".lock")
            with open(lock_path, "a+") as fd:
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    data = self._read_json(path, default)
                    result = transform(data)
                    tmp = path.with_suffix(path.suffix + f".tmp.{uuid.uuid4().hex[:8]}")
                    tmp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                    tmp.replace(path)
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)
        return result

    # ── Deeds ──────────────────────────────────────────────────────────────

    @staticmethod
    def _normalize_deed_row(row: dict) -> dict:
        out = dict(row)
        deed_status = str(out.get("deed_status") or "").strip()
        if deed_status:
            out["deed_status"] = deed_status
        return out

    def load_deeds(self) -> list[dict]:
        data = self._read_json(self.deeds_path, [])
        if not isinstance(data, list):
            return []
        return [self._normalize_deed_row(row) for row in data if isinstance(row, dict)]

    def save_deeds(self, deeds: list[dict]) -> None:
        clean = [self._normalize_deed_row(row) for row in deeds if isinstance(row, dict)]
        self._write_json(self.deeds_path, clean)

    def mutate_deeds(self, mutator: Callable[[list[dict]], None]) -> list[dict]:
        """Atomically read-modify-write deeds.json with cross-process locking."""
        def _transform(data: Any) -> list[dict]:
            deeds = data if isinstance(data, list) else []
            mutator(deeds)
            return [self._normalize_deed_row(r) for r in deeds if isinstance(r, dict)]
        return self._locked_rw(self.deeds_path, [], _transform)

    def get_deed(self, deed_id: str) -> dict | None:
        key = str(deed_id or "")
        if not key:
            return None
        for row in self.load_deeds():
            if str(row.get("deed_id") or "") == key:
                return row
        return None

    def upsert_deed(self, deed_id: str, default_row: dict | None = None, *, updated_utc: str | None = None) -> dict:
        key = str(deed_id or "")
        if not key:
            raise ValueError("deed_id_required")
        row_out: dict[str, Any] = {}

        def _mutate(deeds: list[dict]) -> None:
            nonlocal row_out
            for row in deeds:
                if str(row.get("deed_id") or "") == key:
                    row_out = row
                    break
            else:
                row_out = dict(default_row or {})
                row_out.setdefault("deed_id", key)
                deeds.append(row_out)
            row_out["updated_utc"] = str(updated_utc or _utc())

        self.mutate_deeds(_mutate)
        return row_out

    # ── Ward ──────────────────────────────────────────────────────────────

    def load_ward(self) -> dict:
        data = self._read_json(self.ward_path, {"status": "GREEN"})
        if not isinstance(data, dict):
            return {"status": "GREEN"}
        status = str(data.get("status") or "GREEN").upper()
        data["status"] = status
        return data

    def save_ward(self, ward: dict) -> None:
        payload = dict(ward or {})
        payload["status"] = str(payload.get("status") or "GREEN").upper()
        payload.setdefault("updated_utc", _utc())
        self._write_json(self.ward_path, payload)

    # ── System status ─────────────────────────────────────────────────────

    def load_system_status(self) -> str:
        """Return current system status string (running/paused/shutdown/etc)."""
        data = self._read_json(self.state_dir / "system_status.json", {})
        if not isinstance(data, dict):
            return "running"
        return str(data.get("status") or "running").strip().lower()

    # ── Schedule history ───────────────────────────────────────────────────

    def load_schedule_history(self) -> list[dict]:
        data = self._read_json(self.schedule_history_path, [])
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def save_schedule_history(self, rows: list[dict], *, max_items: int = 2000) -> None:
        clean = [row for row in rows if isinstance(row, dict)]
        self._write_json(self.schedule_history_path, clean[-max(1, int(max_items)):])

    # ── Herald log (JSONL, append-only) ──────────────────────────────────────

    @property
    def herald_log_path(self) -> Path:
        return self.state_dir / "herald_log.jsonl"

    def append_herald_log(self, entry: dict) -> None:
        """Append a single herald record to the JSONL log (cross-process safe)."""
        path = self.herald_log_path
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        lock = self._lock_for(path)
        with lock:
            lock_path = path.with_suffix(".lock")
            with open(lock_path, "a+") as fd:
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(line)
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)

    def load_herald_log(self, *, max_items: int = 2000) -> list[dict]:
        """Read the herald log, returning the most recent entries."""
        path = self.herald_log_path
        if not path.exists():
            return []
        rows: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(obj)
                except json.JSONDecodeError:
                    continue
        except Exception as exc:
            logger.warning("Failed to read herald log %s: %s", path, exc)
        return rows[-max(1, max_items):]

    # ── Notification failure queue (JSONL, append-only) ─────────────────────

    @property
    def notify_queue_path(self) -> Path:
        return self.state_dir / "notify_queue.jsonl"

    def enqueue_failed_notification(self, entry: dict) -> None:
        """Persist a failed notification for later retry."""
        path = self.notify_queue_path
        path.parent.mkdir(parents=True, exist_ok=True)
        row = dict(entry)
        row.setdefault("queued_utc", _utc())
        row.setdefault("retry_count", 0)
        line = json.dumps(row, ensure_ascii=False) + "\n"
        lock = self._lock_for(path)
        with lock:
            lock_path = path.with_suffix(".lock")
            with open(lock_path, "a+") as fd:
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write(line)
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)

    def load_notify_queue(self) -> list[dict]:
        """Read all pending failed notifications."""
        path = self.notify_queue_path
        if not path.exists():
            return []
        rows: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        rows.append(obj)
                except json.JSONDecodeError:
                    continue
        except Exception as exc:
            logger.warning("Failed to read notify queue %s: %s", path, exc)
        return rows

    def clear_notify_queue(self) -> None:
        """Clear the notification failure queue after successful retry."""
        path = self.notify_queue_path
        if path.exists():
            path.write_text("", encoding="utf-8")

    def rewrite_notify_queue(self, remaining: list[dict]) -> None:
        """Rewrite queue with only the entries that still need retry."""
        path = self.notify_queue_path
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = self._lock_for(path)
        with lock:
            lock_path = path.with_suffix(".lock")
            with open(lock_path, "a+") as fd:
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    lines = [json.dumps(r, ensure_ascii=False) + "\n" for r in remaining if isinstance(r, dict)]
                    path.write_text("".join(lines), encoding="utf-8")
                finally:
                    fcntl.flock(fd, fcntl.LOCK_UN)

    # ── Generic JSON ──────────────────────────────────────────────────────

    def load_json(self, filename: str, default: Any = None) -> Any:
        return self._read_json(self.state_dir / filename, default if default is not None else {})

    def save_json(self, filename: str, data: Any) -> None:
        self._write_json(self.state_dir / filename, data)
