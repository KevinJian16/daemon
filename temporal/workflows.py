"""GraphDispatchWorkflow — DAG-based multi-agent run orchestration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


@dataclass
class RunInput:
    plan: dict
    run_root: str
    run_id: str = ""


@workflow.defn(name="GraphDispatchWorkflow")
class GraphDispatchWorkflow:
    """Executes a DAG of Agent steps with Kahn topological ordering and per-agent concurrency limits."""

    def __init__(self) -> None:
        self._active_requirements: list[dict[str, str]] = []
        self._pause_requested: bool = False

    @workflow.signal(name="append_requirement")
    def append_requirement(self, payload: dict | None = None) -> None:
        row = payload if isinstance(payload, dict) else {}
        text = str(row.get("text") or row.get("requirement") or "").strip()
        if not text:
            return
        self._active_requirements.append(
            {
                "text": text,
                "source": str(row.get("source") or "user"),
                "appended_at": str(row.get("appended_at") or workflow.now().strftime("%Y-%m-%dT%H:%M:%SZ")),
            }
        )
        if len(self._active_requirements) > 20:
            self._active_requirements = self._active_requirements[-20:]

    @workflow.signal(name="pause_execution")
    def pause_execution(self, payload: dict | None = None) -> None:
        _ = payload
        self._pause_requested = True

    @workflow.signal(name="resume_execution")
    def resume_execution(self, payload: dict | None = None) -> None:
        _ = payload
        self._pause_requested = False

    @workflow.run
    async def run(self, inp: RunInput) -> dict:
        plan = inp.plan or {}
        campaign_child = bool(plan.get("campaign_child"))
        work_scale = str(plan.get("work_scale") or "").strip().lower()

        async def _mark_failure(message: str) -> None:
            if not campaign_child:
                await self._mark_run_status(inp.run_root, plan, "failed", message[:200])

        steps = plan.get("steps") or plan.get("graph", {}).get("steps") or []
        if not isinstance(steps, list) or not steps:
            await _mark_failure("missing steps")
            raise ApplicationError("missing steps", non_retryable=True)

        concurrency = plan.get("concurrency") or {}
        max_parallel = max(1, min(64, int(concurrency.get("max_parallel_steps") or 16)))
        agent_limits = self._agent_limits(plan)

        # Build normalized step map and validate IDs.
        step_list: list[dict] = []
        id_set: set[str] = set()
        for i, st in enumerate(steps):
            if not isinstance(st, dict):
                await _mark_failure(f"invalid step at index {i}")
                raise ApplicationError(f"invalid step at index {i}", non_retryable=True)
            sid = self._step_id(st, i)
            if sid in id_set:
                await _mark_failure(f"duplicate step id: {sid}")
                raise ApplicationError(f"duplicate step id: {sid}", non_retryable=True)
            id_set.add(sid)
            step_list.append({**st, "id": sid})

        step_by_id = {st["id"]: st for st in step_list}
        id_list = [st["id"] for st in step_list]

        # Build dependency graph.
        deps: dict[str, set[str]] = {}
        rev: dict[str, set[str]] = {sid: set() for sid in step_by_id}
        for sid, st in step_by_id.items():
            ds = set(self._deps(st))
            if sid in ds:
                await _mark_failure(f"step {sid} depends on itself")
                raise ApplicationError(f"step {sid} depends on itself", non_retryable=True)
            unknown = [d for d in ds if d not in step_by_id]
            if unknown:
                await _mark_failure(f"step {sid}: unknown deps {unknown}")
                raise ApplicationError(f"step {sid}: unknown deps {unknown}", non_retryable=True)
            deps[sid] = ds
            for d in ds:
                rev[d].add(sid)

        # Kahn cycle detection.
        indeg = {sid: len(d) for sid, d in deps.items()}
        q = [sid for sid, n in indeg.items() if n == 0]
        seen = 0
        idx = 0
        while idx < len(q):
            cur = q[idx]
            idx += 1
            seen += 1
            for nxt in rev.get(cur, set()):
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    q.append(nxt)
        if seen != len(step_by_id):
            await _mark_failure("cycle detected in DAG")
            raise ApplicationError("cycle detected in DAG", non_retryable=True)

        # Execution loop.
        results_by_id: dict[str, dict] = {}
        running: dict[str, workflow.ActivityHandle] = {}
        completed: set[str] = set()
        errors: list[dict] = []
        pending = set(step_by_id.keys())
        pause_state_marked = False

        try:
            while pending or running:
                if self._pause_requested and not running:
                    if not campaign_child and not pause_state_marked:
                        await self._mark_run_status(inp.run_root, plan, "paused", "paused_by_request")
                        pause_state_marked = True
                    await workflow.wait_condition(lambda: not self._pause_requested)
                    if not campaign_child and pause_state_marked:
                        await self._mark_run_status(inp.run_root, plan, "running", "")
                    pause_state_marked = False
                    continue

                # Start ready steps up to concurrency limits.
                made_progress = True
                while (not self._pause_requested) and made_progress and pending and len(running) < max_parallel:
                    made_progress = False
                    ready = [sid for sid in sorted(pending) if deps.get(sid, set()).issubset(completed)]
                    if not ready:
                        break
                    agent_running: dict[str, int] = {}
                    for rsid in running:
                        ag = self._agent(step_by_id.get(rsid, {}))
                        if ag:
                            agent_running[ag] = agent_running.get(ag, 0) + 1
                    for sid in ready:
                        if self._pause_requested:
                            break
                        if len(running) >= max_parallel:
                            break
                        base_step = step_by_id.get(sid, {})
                        injected_step = self._inject_requirements(base_step, work_scale=work_scale)
                        ag = self._agent(injected_step)
                        if ag:
                            cur_count = agent_running.get(ag, 0)
                            limit = int(agent_limits.get(ag, max_parallel))
                            if cur_count >= limit:
                                continue
                        pending.discard(sid)
                        running[sid] = self._start(sid, injected_step, inp.run_root, plan)
                        if ag:
                            agent_running[ag] = agent_running.get(ag, 0) + 1
                        made_progress = True

                if not running:
                    raise ApplicationError("deadlock: no runnable steps", non_retryable=True)

                done, _ = await workflow.wait(list(running.values()), return_when="FIRST_COMPLETED")
                done_ids = [sid for sid, h in list(running.items()) if h in done]
                for sid in done_ids:
                    h = running.pop(sid)
                    try:
                        res = await h
                        if not isinstance(res, dict):
                            res = {"status": "error", "step_id": sid, "error": "invalid_result"}
                    except Exception as e:
                        res = {"status": "error", "step_id": sid, "error": str(e)[:400]}
                        errors.append(res)
                    results_by_id[sid] = res
                    completed.add(sid)

        except asyncio.CancelledError:
            if not campaign_child:
                await self._mark_run_status(inp.run_root, plan, "cancelled", "cancelled_by_request")
            raise
        except ApplicationError as e:
            await _mark_failure(str(e)[:200])
            raise
        except Exception as e:
            await _mark_failure(str(e)[:200])
            raise ApplicationError(f"workflow_exception: {str(e)[:200]}", non_retryable=True) from e

        ordered: list[dict] = [
            results_by_id.get(sid) or {"status": "error", "step_id": sid, "error": "missing_result"}
            for sid in id_list
        ]

        if errors:
            await _mark_failure(f"{len(errors)} step(s) failed")
            raise ApplicationError(f"{len(errors)} step(s) failed", non_retryable=True)

        if campaign_child:
            return {
                "ok": True,
                "campaign_child": True,
                "step_results": ordered,
            }

        # Delivery handoff.
        delivery = await workflow.execute_activity(
            "activity_finalize_delivery",
            args=[inp.run_root, plan, ordered],
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(minutes=6),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        # Rework loop for quality failures.
        if not (isinstance(delivery, dict) and delivery.get("ok")):
            budget = int(plan.get("rework_budget") or 2)
            for attempt in range(1, budget + 1):
                error_code = str((delivery or {}).get("error_code") or "quality_gate_failed")
                rework_steps = self._rework_steps(step_list, error_code, attempt)
                if not rework_steps:
                    break
                for st in rework_steps:
                    st_to, sc_to = self._timeouts(plan, st)
                    res = await workflow.execute_activity(
                        "activity_openclaw_step",
                        args=[inp.run_root, plan, st],
                        start_to_close_timeout=st_to,
                        schedule_to_close_timeout=sc_to,
                        heartbeat_timeout=timedelta(seconds=90),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                    if not isinstance(res, dict):
                        res = {"status": "error", "step_id": st["id"], "error": "invalid_rework_result"}
                    ordered.append(res)
                delivery = await workflow.execute_activity(
                    "activity_finalize_delivery",
                    args=[inp.run_root, plan, ordered],
                    start_to_close_timeout=timedelta(minutes=5),
                    schedule_to_close_timeout=timedelta(minutes=6),
                    retry_policy=RetryPolicy(maximum_attempts=1),
                )
                if isinstance(delivery, dict) and delivery.get("ok"):
                    break

        if not (isinstance(delivery, dict) and delivery.get("ok")):
            err_msg = str((delivery or {}).get("error_code") or (delivery or {}).get("detail") or "delivery_failed")
            await _mark_failure(err_msg[:200])

        return delivery or {}

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _step_id(self, st: dict, index: int) -> str:
        return str(st.get("id") or st.get("step_id") or f"step_{index}").strip()

    def _deps(self, st: dict) -> list[str]:
        d = st.get("depends_on") or st.get("dependencies") or []
        return [str(x) for x in d] if isinstance(d, list) else []

    def _agent(self, st: dict) -> str:
        return str(st.get("agent") or "").strip()

    def _agent_limits(self, plan: dict) -> dict[str, int]:
        # Prefer plan-level overrides; fall back to defaults injected by Dispatch.
        system_defaults = plan.get("agent_concurrency_defaults") or {
            "collect": 8, "analyze": 4, "review": 2,
            "render": 2, "apply": 1, "spine": 2, "router": 1, "build": 2,
        }
        overrides: dict = plan.get("agent_concurrency") or {}
        return {**system_defaults, **overrides}

    def _inject_requirements(self, step: dict, *, work_scale: str) -> dict:
        if work_scale == "pulse":
            return dict(step)
        if not self._active_requirements:
            return dict(step)
        out = dict(step)
        base = str(out.get("instruction") or out.get("message") or "").strip()
        req_lines = []
        for idx, req in enumerate(self._active_requirements[-10:], start=1):
            text = str(req.get("text") or "").strip()
            if not text:
                continue
            req_lines.append(f"{idx}. {text}")
        if not req_lines:
            return out
        appendix = (
            "\n\nAdditional requirements received during run:\n"
            + "\n".join(req_lines)
            + "\n\nHonor these requirements while preserving original quality constraints."
        )
        out["instruction"] = (base + appendix).strip()
        return out

    def _start(self, sid: str, st: dict, run_root: str, plan: dict) -> workflow.ActivityHandle:
        ag = self._agent(st)
        st_to, sc_to = self._timeouts(plan, st)
        max_attempts = int(plan.get("retry_max_attempts") or 3)
        retry = RetryPolicy(maximum_attempts=max_attempts)

        if ag == "spine":
            routine = str(st.get("routine") or st.get("instruction") or "").strip()
            return workflow.start_activity(
                "activity_spine_routine",
                args=[run_root, plan, routine],
                start_to_close_timeout=st_to,
                schedule_to_close_timeout=sc_to,
                retry_policy=retry,
            )
        return workflow.start_activity(
            "activity_openclaw_step",
            args=[run_root, plan, st],
            start_to_close_timeout=st_to,
            schedule_to_close_timeout=sc_to,
            heartbeat_timeout=timedelta(seconds=90),
            retry_policy=retry,
        )

    def _timeouts(self, plan: dict, st: dict) -> tuple[timedelta, timedelta]:
        """Resolve step timeouts from Playbook hints embedded in plan."""
        hints: dict = plan.get("timeout_hints") or {}
        ag = self._agent(st)
        step_override = int(st.get("timeout_s") or 0)
        agent_hint = int(hints.get(ag) or 0)
        default = int(plan.get("default_step_timeout_s") or 480)
        start_to_close_s = step_override or agent_hint or default
        return timedelta(seconds=start_to_close_s), timedelta(seconds=start_to_close_s + 30)

    def _rework_steps(self, step_list: list[dict], error_code: str, attempt: int) -> list[dict]:
        """Select steps to rework based on structured error code (not string matching)."""
        COLLECTION_CODES = {"brief_items_too_few", "brief_domain_coverage_too_low", "contract_references_too_few"}
        is_collection_issue = error_code in COLLECTION_CODES

        def _last_by_agent(agent: str) -> dict | None:
            for st in reversed(step_list):
                if self._agent(st) == agent:
                    return dict(st)
            return None

        selected: list[dict] = []
        if is_collection_issue:
            for ag in ("collect", "analyze", "render"):
                st = _last_by_agent(ag)
                if st:
                    selected.append(st)
        else:
            for ag in ("review", "render"):
                st = _last_by_agent(ag)
                if st:
                    selected.append(st)

        for i, st in enumerate(selected):
            base_id = str(st.get("id") or f"rework_{i}").strip()
            st["id"] = f"{base_id}_rework_{attempt}"
            base_ins = str(st.get("instruction") or "").strip()
            if is_collection_issue:
                st["instruction"] = (
                    f"{base_ins}\n\nRework: collection insufficient ({error_code}). "
                    "Expand source coverage and retry with alternative sources."
                )
            else:
                st["instruction"] = (
                    f"{base_ins}\n\nRework: quality gate failed ({error_code}). "
                    "Rewrite to professional standard; no internal system markers; "
                    "bilingual runs must output separate _zh and _en documents."
                )
        return selected

    async def _mark_run_status(self, run_root: str, plan: dict, run_status: str, error: str) -> None:
        try:
            await workflow.execute_activity(
                "activity_update_run_status",
                args=[run_root, {**plan, "last_error": error}, run_status],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            workflow.logger.warning("Failed to update run status for %s: %s", run_root, exc)
