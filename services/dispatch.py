"""Dispatch — semantic routing, plan validation, Playbook strategy, Temporal submission."""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.semantic import SemanticFingerprint, SemanticGenerator, SemanticMappingError

if TYPE_CHECKING:
    from fabric.playbook import PlaybookFabric
    from fabric.compass import CompassFabric
    from runtime.cortex import Cortex
    from spine.nerve import Nerve

# Replay backoff schedule in seconds (capped at 4h).
_REPLAY_BACKOFF = [60, 300, 900, 3600, 14400]
_REPLAY_MAX_ATTEMPTS = 5


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


logger = logging.getLogger(__name__)


class Dispatch:
    def __init__(
        self,
        playbook: "PlaybookFabric",
        compass: "CompassFabric",
        nerve: "Nerve",
        state_dir: Path,
        temporal_client=None,
        task_queue: str = "daemon-queue",
        cortex: "Cortex | None" = None,
    ) -> None:
        self._playbook = playbook
        self._compass = compass
        self._nerve = nerve
        self._state = state_dir
        self._temporal = temporal_client
        self._task_queue = task_queue
        self._cortex = cortex
        self._semantic = SemanticGenerator(cortex=cortex)
        self._agent_defaults = self._load_agent_defaults()

    def set_temporal_client(self, temporal_client) -> None:
        self._temporal = temporal_client

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
        # Clear stale queue markers before re-evaluating gate policy (important for replay).
        plan.pop("queued", None)
        plan.pop("queue_reason", None)
        plan.pop("status", None)
        task_type = str(plan.get("task_type") or plan.get("method") or "research_report")
        plan.setdefault("task_id", _new_task_id())
        agent_defaults = self._agent_defaults_from_compass() or dict(self._agent_defaults)
        plan.setdefault("agent_concurrency_defaults", dict(agent_defaults))
        plan.setdefault("agent_concurrency", dict(agent_defaults))

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
            if isinstance(spec.get("concurrency"), dict):
                existing = plan.get("concurrency") if isinstance(plan.get("concurrency"), dict) else {}
                plan["concurrency"] = {**spec.get("concurrency", {}), **existing}
            if isinstance(spec.get("timeout_hints"), dict):
                existing_hints = plan.get("timeout_hints") if isinstance(plan.get("timeout_hints"), dict) else {}
                plan["timeout_hints"] = {**spec.get("timeout_hints", {}), **existing_hints}
            plan["method_id"] = best["method_id"]

        # Apply Compass quality profile as timeout hint.
        quality = self._compass.get_quality_profile(task_type)
        plan.setdefault("quality_profile", quality)
        default_timeout = int(self._compass.get_pref("default_step_timeout_s", "480") or 480)
        plan.setdefault("default_step_timeout_s", default_timeout)
        plan.setdefault("model_primary", self._compass.get_pref("model_primary", ""))
        plan.setdefault("resource_budgets", self._compass.all_budgets())

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

    def _agent_defaults_from_compass(self) -> dict[str, int]:
        raw = self._compass.get_pref("agent_concurrency_defaults_json", "")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except Exception as exc:
            logger.warning("Invalid agent_concurrency_defaults_json in Compass: %s", exc)
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, int] = {}
        for k, v in data.items():
            try:
                out[str(k)] = int(v)
            except Exception:
                continue
        return out

    def _load_agent_defaults(self) -> dict[str, int]:
        cfg_path = self._state.parent / "config" / "system.json"
        if not cfg_path.exists():
            return {
                "collect": 8,
                "analyze": 4,
                "review": 2,
                "render": 2,
                "apply": 1,
                "spine": 2,
                "router": 1,
                "build": 2,
            }
        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception as exc:
            logger.warning("Failed to read system defaults from %s: %s", cfg_path, exc)
            return {
                "collect": 8,
                "analyze": 4,
                "review": 2,
                "render": 2,
                "apply": 1,
                "spine": 2,
                "router": 1,
                "build": 2,
            }
        defaults = cfg.get("agent_concurrency_defaults", {})
        if not isinstance(defaults, dict):
            return {}
        out: dict[str, int] = {}
        for k, v in defaults.items():
            try:
                out[str(k)] = int(v)
            except Exception:
                continue
        return out

    def resolve_semantic(self, request: dict) -> "SemanticFingerprint":
        """Four-path semantic resolution (decision §1). Raises SemanticMappingError on failure.

        Path 1: caller provides semantic_fingerprint dict → validate cluster_id.
        Path 2: caller provides intent_contract dict → generate fingerprint.
        Path 3: caller provides task_type string → compat cluster mapping.
        Path 4: none of the above → SemanticMappingError (fail-closed, 400).
        """
        if fp_raw := request.get("semantic_fingerprint"):
            if isinstance(fp_raw, dict):
                return self._semantic.from_fingerprint_dict(fp_raw)

        if ic_raw := request.get("intent_contract"):
            if isinstance(ic_raw, dict):
                return self._semantic.from_intent_contract(ic_raw, cortex=self._cortex)

        if task_type := str(request.get("task_type") or "").strip():
            return self._semantic.from_task_type(task_type, title=str(request.get("title") or ""))

        raise SemanticMappingError("semantic_input_missing: provide semantic_fingerprint, intent_contract, or task_type")

    async def submit(self, plan: dict) -> dict:
        """Semantic resolve → validate → enrich → Temporal submit."""
        # Step 1: Semantic resolution (fail-closed).
        try:
            fingerprint = self.resolve_semantic(plan)
        except SemanticMappingError as exc:
            return {"ok": False, "error": str(exc), "error_code": "semantic_mapping_failed"}

        # Attach resolved fingerprint to plan.
        plan = dict(plan)
        plan["semantic_fingerprint"] = fingerprint.to_dict()
        plan.setdefault("cluster_id", fingerprint.cluster_id)

        ok, err = self.validate(plan)
        if not ok:
            return {"ok": False, "error": err, "error_code": "invalid_plan"}

        plan = self.enrich(plan)
        task_id = plan["task_id"]

        if plan.get("queued"):
            self._queue_task(plan)
            return {"ok": True, "task_id": task_id, "status": "queued", "reason": plan.get("queue_reason")}

        if not self._temporal:
            self._record_task(plan, "failed_submission", "")
            return {
                "ok": False,
                "task_id": task_id,
                "error_code": "temporal_unavailable",
                "error": "Temporal client unavailable; submission rejected",
            }

        run_root = self._make_run_root(task_id)
        self._record_task(plan, "running", run_root)

        try:
            workflow_id = f"daemon-{task_id}"
            await self._temporal.submit(workflow_id, plan, run_root)
        except Exception as exc:
            logger.error("Temporal submit failed for task %s: %s", task_id, exc)
            self._record_task({**plan, "last_error": str(exc)[:300]}, "failed_submission", run_root)
            return {
                "ok": False,
                "task_id": task_id,
                "error_code": "temporal_submit_failed",
                "error": str(exc)[:400],
            }

        self._nerve.emit("task_submitted", {"task_id": task_id, "run_root": run_root})
        return {"ok": True, "task_id": task_id, "status": "running", "run_root": run_root}

    async def replay(self, task_id: str, plan: dict) -> dict:
        """Replay a queued task with backoff enforcement (decision §7)."""
        tasks_path = self._state / "tasks.json"
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to read tasks.json for replay: %s", exc)
            tasks = []

        task_record: dict | None = next((t for t in tasks if t.get("task_id") == task_id), None)

        if task_record:
            attempts = int(task_record.get("replay_attempts", 0))
            next_replay_utc = str(task_record.get("next_replay_utc") or "")
            if attempts >= _REPLAY_MAX_ATTEMPTS:
                self._update_replay_state(task_id, tasks, tasks_path, status="replay_exhausted",
                                          reason=f"exceeded max_attempts={_REPLAY_MAX_ATTEMPTS}")
                return {"ok": False, "task_id": task_id, "error_code": "replay_exhausted",
                        "error": f"Max replay attempts ({_REPLAY_MAX_ATTEMPTS}) exceeded"}
            if next_replay_utc and next_replay_utc > _utc():
                return {"ok": False, "task_id": task_id, "error_code": "replay_too_soon",
                        "error": f"Next replay not due until {next_replay_utc}"}

        replay_plan = dict(plan)
        replay_plan["task_id"] = task_id
        replay_plan.pop("queued", None)
        replay_plan.pop("queue_reason", None)
        replay_plan.pop("status", None)
        replay_plan["replay_token"] = f"rpl_{uuid.uuid4().hex[:12]}"

        result = await self.submit(replay_plan)

        if task_record:
            attempts = int(task_record.get("replay_attempts", 0)) + 1
            backoff_s = _REPLAY_BACKOFF[min(attempts - 1, len(_REPLAY_BACKOFF) - 1)]
            next_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + backoff_s))
            self._update_replay_state(task_id, tasks, tasks_path,
                                      status="running" if result.get("ok") else "queued",
                                      attempts=attempts, next_replay_utc=next_utc)

        return result

    def _update_replay_state(
        self,
        task_id: str,
        tasks: list,
        tasks_path: Path,
        status: str,
        attempts: int | None = None,
        next_replay_utc: str | None = None,
        reason: str | None = None,
    ) -> None:
        for t in tasks:
            if t.get("task_id") == task_id:
                t["status"] = status
                t["updated_utc"] = _utc()
                if attempts is not None:
                    t["replay_attempts"] = attempts
                if next_replay_utc is not None:
                    t["next_replay_utc"] = next_replay_utc
                if reason:
                    t["replay_exhausted_reason"] = reason
                break
        try:
            tmp = tasks_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
            tmp.replace(tasks_path)
        except Exception as exc:
            logger.warning("Failed to update replay state for %s: %s", task_id, exc)

    def _make_run_root(self, task_id: str) -> str:
        runs_dir = self._state / "runs" / task_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        return str(runs_dir)

    def _record_task(self, plan: dict, status: str, run_root: str) -> None:
        tasks_path = self._state / "tasks.json"
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception as exc:
            logger.warning("Failed to parse tasks.json at %s: %s", tasks_path, exc)
            tasks = []
        task_id = plan.get("task_id", "")
        for t in tasks:
            if t.get("task_id") == task_id:
                t["status"] = status
                t["updated_utc"] = _utc()
                if plan.get("last_error"):
                    t["last_error"] = plan.get("last_error")
                if run_root:
                    t["run_root"] = run_root
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
                "last_error": plan.get("last_error", ""),
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
        except Exception as exc:
            logger.warning("Failed to parse gate file %s: %s", gate_path, exc)
            return {"status": "GREEN"}


def _new_task_id() -> str:
    ts = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    return f"task_{ts}_{uuid.uuid4().hex[:6]}"
