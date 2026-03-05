"""Unified state file access for daemon runtime metadata."""
from __future__ import annotations

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


class StateStore:
    """Centralized read/write helpers for state JSON files."""

    _locks_guard = threading.Lock()
    _locks: dict[str, threading.Lock] = {}

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_path = self.state_dir / "tasks.json"
        self.gate_path = self.state_dir / "gate.json"
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
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)

    # ── Tasks ──────────────────────────────────────────────────────────────

    def load_tasks(self) -> list[dict]:
        data = self._read_json(self.tasks_path, [])
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def save_tasks(self, tasks: list[dict]) -> None:
        clean = [row for row in tasks if isinstance(row, dict)]
        self._write_json(self.tasks_path, clean)

    def mutate_tasks(self, mutator: Callable[[list[dict]], None]) -> list[dict]:
        tasks = self.load_tasks()
        mutator(tasks)
        self.save_tasks(tasks)
        return tasks

    def get_task(self, task_id: str) -> dict | None:
        key = str(task_id or "")
        if not key:
            return None
        for row in self.load_tasks():
            if str(row.get("task_id") or "") == key:
                return row
        return None

    def upsert_task(self, task_id: str, default_row: dict | None = None, *, updated_utc: str | None = None) -> dict:
        key = str(task_id or "")
        if not key:
            raise ValueError("task_id_required")
        row_out: dict[str, Any] = {}

        def _mutate(tasks: list[dict]) -> None:
            nonlocal row_out
            for row in tasks:
                if str(row.get("task_id") or "") == key:
                    row_out = row
                    break
            else:
                row_out = dict(default_row or {})
                row_out.setdefault("task_id", key)
                tasks.append(row_out)
            row_out["updated_utc"] = str(updated_utc or _utc())

        self.mutate_tasks(_mutate)
        return row_out

    # ── Gate ───────────────────────────────────────────────────────────────

    def load_gate(self) -> dict:
        data = self._read_json(self.gate_path, {"status": "GREEN"})
        if not isinstance(data, dict):
            return {"status": "GREEN"}
        status = str(data.get("status") or "GREEN").upper()
        data["status"] = status
        return data

    def save_gate(self, gate: dict) -> None:
        payload = dict(gate or {})
        payload["status"] = str(payload.get("status") or "GREEN").upper()
        payload.setdefault("updated_utc", _utc())
        self._write_json(self.gate_path, payload)

    # ── Schedule history ───────────────────────────────────────────────────

    def load_schedule_history(self) -> list[dict]:
        data = self._read_json(self.schedule_history_path, [])
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def save_schedule_history(self, rows: list[dict], *, max_items: int = 2000) -> None:
        clean = [row for row in rows if isinstance(row, dict)]
        self._write_json(self.schedule_history_path, clean[-max(1, int(max_items)):])

    # ── Outcome index ──────────────────────────────────────────────────────

    def load_outcome_index(self, outcome_root: Path) -> list[dict]:
        path = outcome_root / "index.json"
        data = self._read_json(path, [])
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def save_outcome_index(self, outcome_root: Path, rows: list[dict], *, max_items: int = 1000) -> None:
        path = outcome_root / "index.json"
        clean = [row for row in rows if isinstance(row, dict)]
        self._write_json(path, clean[-max(1, int(max_items)):])
