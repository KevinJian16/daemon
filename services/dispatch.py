"""Dispatch — validates plans, applies Playbook strategy, submits to Temporal."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fabric.playbook import PlaybookFabric
    from fabric.compass import CompassFabric
    from spine.nerve import Nerve


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Dispatch:
    def __init__(
        self,
        playbook: "PlaybookFabric",
        compass: "CompassFabric",
        nerve: "Nerve",
        state_dir: Path,
        temporal_client=None,
        task_queue: str = "daemon-queue",
    ) -> None:
        self._playbook = playbook
        self._compass = compass
        self._nerve = nerve
        self._state = state_dir
        self._temporal = temporal_client
        self._task_queue = task_queue

    def validate(self, plan: dict) -> tuple[bool, str]:
        """Validate a plan before submission. Returns (ok, error_message)."""
        steps = plan.get("steps") or plan.get("graph", {}).get("steps") or []
        if not isinstance(steps, list) or not steps:
            return False, "plan must contain a non-empty steps list"

        ids: set[str] = set()
        for i, st in enumerate(steps):
            if not isinstance(st, dict):
                return False, f"step {i} is not an object"
            sid = str(st.get("id") or f"step_{i}")
            if sid in ids:
                return False, f"duplicate step id: {sid}"
            ids.add(sid)
            for dep in st.get("depends_on") or []:
                if dep not in ids:
                    return False, f"step {sid}: depends_on unknown step {dep!r} (must appear before it)"

        return True, ""

    def enrich(self, plan: dict) -> dict:
        """Apply Playbook parameters (timeouts, retry policy) into plan."""
        plan = dict(plan)
        task_type = str(plan.get("task_type") or plan.get("method") or "research_report")
        plan.setdefault("task_id", _new_task_id())

        # Consult Playbook for best matching method.
        methods = self._playbook.consult(category="dag_pattern")
        best = None
        for m in methods:
            if m["name"] == task_type or not best:
                best = m
                if m["name"] == task_type:
                    break

        if best:
            spec: dict = best.get("spec") or {}
            plan.setdefault("rework_budget", spec.get("rework_budget", 2))
            plan.setdefault("rework_strategy", spec.get("rework_strategy", "error_code_based"))
            plan["method_id"] = best["method_id"]

        # Apply Compass quality profile as timeout hint.
        quality = self._compass.get_quality_profile(task_type)
        plan.setdefault("quality_profile", quality)
        plan.setdefault("default_step_timeout_s", 480)

        # Gate check — apply priority to queued vs immediate.
        gate = self._read_gate()
        if gate.get("status") == "RED":
            plan["queued"] = True
            plan["queue_reason"] = "gate_red"
        elif gate.get("status") == "YELLOW":
            priority = int(plan.get("priority") or 5)
            if priority > 5:
                plan["queued"] = True
                plan["queue_reason"] = "gate_yellow_low_priority"

        return plan

    async def submit(self, plan: dict) -> dict:
        """Validate, enrich, and submit plan to Temporal. Returns task record."""
        ok, err = self.validate(plan)
        if not ok:
            return {"ok": False, "error": err}

        plan = self.enrich(plan)
        task_id = plan["task_id"]

        if plan.get("queued"):
            self._queue_task(plan)
            return {"ok": True, "task_id": task_id, "status": "queued", "reason": plan.get("queue_reason")}

        run_root = self._make_run_root(task_id)
        self._record_task(plan, "running", run_root)

        if self._temporal:
            workflow_id = f"daemon-{task_id}"
            await self._temporal.submit(workflow_id, plan, run_root)
        else:
            # Temporal not connected — record as pending for manual testing.
            self._record_task(plan, "pending_temporal", run_root)

        self._nerve.emit("task_submitted", {"task_id": task_id, "run_root": run_root})
        return {"ok": True, "task_id": task_id, "status": "running", "run_root": run_root}

    def _make_run_root(self, task_id: str) -> str:
        runs_dir = self._state / "runs" / task_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        return str(runs_dir)

    def _record_task(self, plan: dict, status: str, run_root: str) -> None:
        tasks_path = self._state / "tasks.json"
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception:
            tasks = []
        task_id = plan.get("task_id", "")
        for t in tasks:
            if t.get("task_id") == task_id:
                t["status"] = status
                t["updated_utc"] = _utc()
                break
        else:
            tasks.append({
                "task_id": task_id,
                "title": plan.get("title", ""),
                "task_type": plan.get("task_type", ""),
                "status": status,
                "run_root": run_root,
                "submitted_utc": _utc(),
                "updated_utc": _utc(),
                "priority": plan.get("priority", 5),
                "plan": plan,
            })
        tmp = tasks_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
        tmp.replace(tasks_path)

    def _queue_task(self, plan: dict) -> None:
        plan_copy = dict(plan)
        plan_copy["status"] = "queued"
        plan_copy["queued_utc"] = _utc()
        self._record_task(plan_copy, "queued", "")

    def _read_gate(self) -> dict:
        gate_path = self._state / "gate.json"
        if not gate_path.exists():
            return {"status": "GREEN"}
        try:
            return json.loads(gate_path.read_text())
        except Exception:
            return {"status": "GREEN"}


def _new_task_id() -> str:
    ts = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    return f"task_{ts}_{uuid.uuid4().hex[:6]}"
