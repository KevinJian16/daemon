"""Trail — structured execution trace for Spine Routines and workflow moves."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from runtime.trail_context import reset_current_trail, set_current_trail


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class TraceContext:
    """Context manager that records a structured trace entry on exit."""

    def __init__(self, trail: "Trail", routine: str, trigger: str, meta: dict | None = None) -> None:
        self._trail = trail
        self._routine = routine
        self._trigger = trigger
        self._meta = meta or {}
        self._trace_id = f"tr_{uuid.uuid4().hex[:12]}"
        self._started = time.time()
        self._steps: list[dict] = []
        self._degraded = False
        self._result: dict = {}
        self._trace_tokens = None

    @property
    def trace_id(self) -> str:
        return self._trace_id

    def step(self, name: str, detail: Any = None) -> None:
        self._steps.append({"name": name, "t": round(time.time() - self._started, 2), "detail": detail})

    def mark_degraded(self, reason: str) -> None:
        self._degraded = True
        self.step("degraded", reason)

    def set_result(self, result: dict) -> None:
        self._result = result

    def __enter__(self) -> "TraceContext":
        self._trace_tokens = set_current_trail(self._trace_id, self._routine)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        reset_current_trail(self._trace_tokens)
        elapsed = round(time.time() - self._started, 2)
        status = "error" if exc_type else "ok"
        entry: dict[str, Any] = {
            "trace_id": self._trace_id,
            "routine": self._routine,
            "trigger": self._trigger,
            "status": status,
            "degraded": self._degraded,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._started)),
            "elapsed_s": elapsed,
            "steps": self._steps,
            "result": self._result,
            **self._meta,
        }
        if exc_type:
            entry["error"] = f"{exc_type.__name__}: {str(exc_val)[:400]}"
        self._trail._write(entry)
        return False  # Do not suppress exceptions.


class Trail:
    def __init__(self, traces_dir: Path) -> None:
        self._dir = traces_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._recent: list[dict] = []

    def span(self, routine: str, trigger: str = "manual", meta: dict | None = None) -> TraceContext:
        return TraceContext(self, routine, trigger, meta)

    def _write(self, entry: dict) -> None:
        self._recent.append(entry)
        if len(self._recent) > 500:
            self._recent = self._recent[-500:]
        # Write to date-based file for persistence.
        date = entry["started_utc"][:10]
        path = self._dir / f"{date}.jsonl"
        with path.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def recent(self, limit: int = 50, routine: str | None = None) -> list[dict]:
        items = self._recent if not routine else [t for t in self._recent if t.get("routine") == routine]
        return items[-limit:]

    def get(self, trace_id: str) -> dict | None:
        for item in reversed(self._recent):
            if item.get("trace_id") == trace_id:
                return item
        for entry in self._iter_file_entries():
            if entry.get("trace_id") == trace_id:
                return entry
        return None

    def query(
        self,
        since: str | None = None,
        routine: str | None = None,
        status: str | None = None,
        degraded: bool | None = None,
        limit: int = 100,
    ) -> list[dict]:
        results: list[dict] = []
        seen: set[str] = set()

        # Prefer in-memory traces first for latest runtime data.
        for t in reversed(self._recent):
            if routine and t.get("routine") != routine:
                continue
            if status and t.get("status") != status:
                continue
            if degraded is not None and t.get("degraded") != degraded:
                continue
            if since and t.get("started_utc", "") < since:
                continue
            trace_id = str(t.get("trace_id") or "")
            if trace_id:
                seen.add(trace_id)
            results.append(t)
            if len(results) >= limit:
                break

        if len(results) >= limit:
            return results

        # Fallback to persisted traces so history survives process restarts.
        for t in self._iter_file_entries():
            if routine and t.get("routine") != routine:
                continue
            if status and t.get("status") != status:
                continue
            if degraded is not None and t.get("degraded") != degraded:
                continue
            if since and t.get("started_utc", "") < since:
                continue
            trace_id = str(t.get("trace_id") or "")
            if trace_id and trace_id in seen:
                continue
            if trace_id:
                seen.add(trace_id)
            results.append(t)
            if len(results) >= limit:
                break
        return results

    def _iter_file_entries(self):
        for path in sorted(self._dir.glob("*.jsonl"), reverse=True):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for line in reversed(lines):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
