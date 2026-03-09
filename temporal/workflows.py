"""GraphWillWorkflow — DAG-based multi-agent deed orchestration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


@dataclass
class DeedInput:
    plan: dict
    deed_root: str
    deed_id: str = ""


@workflow.defn(name="GraphWillWorkflow")
class GraphWillWorkflow:
    """Executes a DAG of Agent moves with Kahn topological ordering and per-agent concurrency limits."""

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
    async def run(self, inp: DeedInput) -> dict:
        plan = inp.plan or {}
        endeavor_child = bool(plan.get("endeavor_child"))
        complexity = str(plan.get("complexity") or "charge").strip().lower()

        async def _mark_failure(message: str) -> None:
            if not endeavor_child:
                await self._mark_deed_status(inp.deed_root, plan, "failed", message[:200])

        moves = plan.get("moves") or plan.get("graph", {}).get("moves") or []
        if not isinstance(moves, list) or not moves:
            await _mark_failure("missing moves")
            raise ApplicationError("missing moves", non_retryable=True)

        max_parallel = max(1, min(64, int(plan.get("concurrency") or 2)))
        agent_limits = self._agent_limits(plan)

        # Build normalized move map and validate IDs.
        move_list: list[dict] = []
        id_set: set[str] = set()
        for i, st in enumerate(moves):
            if not isinstance(st, dict):
                await _mark_failure(f"invalid move at index {i}")
                raise ApplicationError(f"invalid move at index {i}", non_retryable=True)
            sid = self._move_id(st, i)
            if sid in id_set:
                await _mark_failure(f"duplicate move id: {sid}")
                raise ApplicationError(f"duplicate move id: {sid}", non_retryable=True)
            id_set.add(sid)
            move_list.append({**st, "id": sid})

        move_by_id = {st["id"]: st for st in move_list}
        id_list = [st["id"] for st in move_list]

        # Build dependency graph.
        deps: dict[str, set[str]] = {}
        rev: dict[str, set[str]] = {sid: set() for sid in move_by_id}
        for sid, st in move_by_id.items():
            ds = set(self._deps(st))
            if sid in ds:
                await _mark_failure(f"move {sid} depends on itself")
                raise ApplicationError(f"move {sid} depends on itself", non_retryable=True)
            unknown = [d for d in ds if d not in move_by_id]
            if unknown:
                await _mark_failure(f"move {sid}: unknown deps {unknown}")
                raise ApplicationError(f"move {sid}: unknown deps {unknown}", non_retryable=True)
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
        if seen != len(move_by_id):
            await _mark_failure("cycle detected in DAG")
            raise ApplicationError("cycle detected in DAG", non_retryable=True)

        # Allocate retinue instances for agent roles used in this deed.
        deed_id = inp.deed_id or str(plan.get("deed_id", ""))
        agent_roles = sorted({
            self._agent(st) for st in move_list
            if self._agent(st) and self._agent(st) not in {"spine", "counsel"}
        })
        retinue_allocations: dict[str, str] = {}
        if agent_roles:
            try:
                alloc_result = await workflow.execute_activity(
                    "activity_allocate_retinue",
                    args=[deed_id, agent_roles],
                    start_to_close_timeout=timedelta(seconds=30),
                    schedule_to_close_timeout=timedelta(seconds=40),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                if isinstance(alloc_result, dict):
                    retinue_allocations = alloc_result.get("retinue_allocations", {})
                    plan["retinue_allocations"] = retinue_allocations
            except Exception as exc:
                await _mark_failure(f"retinue_allocation_failed: {str(exc)[:100]}")
                raise ApplicationError("retinue_allocation_failed", non_retryable=True)

        # Execution loop.
        results_by_id: dict[str, dict] = {}
        running: dict[str, workflow.ActivityHandle] = {}
        completed: set[str] = set()
        errors: list[dict] = []
        pending = set(move_by_id.keys())
        pause_state_marked = False

        try:
            while pending or running:
                if self._pause_requested and not running:
                    if not endeavor_child and not pause_state_marked:
                        await self._mark_deed_status(inp.deed_root, plan, "paused", "paused_by_request")
                        pause_state_marked = True
                    await workflow.wait_condition(lambda: not self._pause_requested)
                    if not endeavor_child and pause_state_marked:
                        await self._mark_deed_status(inp.deed_root, plan, "running", "")
                    pause_state_marked = False
                    continue

                # Start ready moves up to concurrency limits.
                made_progress = True
                while (not self._pause_requested) and made_progress and pending and len(running) < max_parallel:
                    made_progress = False
                    ready = [sid for sid in sorted(pending) if deps.get(sid, set()).issubset(completed)]
                    if not ready:
                        break
                    agent_running: dict[str, int] = {}
                    for rsid in running:
                        ag = self._agent(move_by_id.get(rsid, {}))
                        if ag:
                            agent_running[ag] = agent_running.get(ag, 0) + 1
                    for sid in ready:
                        if self._pause_requested:
                            break
                        if len(running) >= max_parallel:
                            break
                        base_move = move_by_id.get(sid, {})
                        injected_move = self._inject_requirements(base_move, complexity=complexity)
                        ag = self._agent(injected_move)
                        if ag:
                            cur_count = agent_running.get(ag, 0)
                            limit = int(agent_limits.get(ag, max_parallel))
                            if cur_count >= limit:
                                continue
                        pending.discard(sid)
                        running[sid] = self._start(sid, injected_move, inp.deed_root, plan)
                        if ag:
                            agent_running[ag] = agent_running.get(ag, 0) + 1
                        made_progress = True

                if not running:
                    raise ApplicationError("deadlock: no runnable moves", non_retryable=True)

                done, _ = await workflow.wait(list(running.values()), return_when="FIRST_COMPLETED")
                done_ids = [sid for sid, h in list(running.items()) if h in done]
                for sid in done_ids:
                    h = running.pop(sid)
                    try:
                        res = await h
                        if not isinstance(res, dict):
                            res = {"status": "error", "move_id": sid, "error": "invalid_result"}
                    except Exception as e:
                        res = {"status": "error", "move_id": sid, "error": str(e)[:400]}
                        errors.append(res)
                    results_by_id[sid] = res
                    completed.add(sid)

        except asyncio.CancelledError:
            if not endeavor_child:
                await self._mark_deed_status(inp.deed_root, plan, "cancelled", "cancelled_by_request")
            await self._release_retinue_safe(deed_id, retinue_allocations)
            raise
        except ApplicationError as e:
            await _mark_failure(str(e)[:200])
            await self._release_retinue_safe(deed_id, retinue_allocations)
            raise
        except Exception as e:
            await _mark_failure(str(e)[:200])
            await self._release_retinue_safe(deed_id, retinue_allocations)
            raise ApplicationError(f"workflow_exception: {str(e)[:200]}", non_retryable=True) from e

        ordered: list[dict] = [
            results_by_id.get(sid) or {"status": "error", "move_id": sid, "error": "missing_result"}
            for sid in id_list
        ]

        if errors:
            await _mark_failure(f"{len(errors)} move(s) failed")
            await self._release_retinue_safe(deed_id, retinue_allocations)
            raise ApplicationError(f"{len(errors)} move(s) failed", non_retryable=True)

        if endeavor_child:
            await self._release_retinue_safe(deed_id, retinue_allocations)
            return {
                "ok": True,
                "endeavor_child": True,
                "move_results": ordered,
            }

        # Arbiter-driven rework loop: if the last arbiter move rejects, re-run selected moves.
        arbiter_result = self._last_arbiter_result(ordered)
        if arbiter_result and self._needs_rework(arbiter_result):
            ration = int(plan.get("rework_ration") or 2)
            for attempt in range(1, ration + 1):
                error_code = str(arbiter_result.get("rework_reason") or "arbiter_rejected")
                rework_moves = self._rework_moves(move_list, error_code, attempt)
                if not rework_moves:
                    break
                for st in rework_moves:
                    st_to, sc_to = self._timeouts(plan, st)
                    res = await workflow.execute_activity(
                        "activity_openclaw_move",
                        args=[inp.deed_root, plan, st],
                        start_to_close_timeout=st_to,
                        schedule_to_close_timeout=sc_to,
                        heartbeat_timeout=timedelta(seconds=90),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    )
                    if not isinstance(res, dict):
                        res = {"status": "error", "move_id": st["id"], "error": "invalid_rework_result"}
                    ordered.append(res)
                arbiter_result = self._last_arbiter_result(ordered)
                if not (arbiter_result and self._needs_rework(arbiter_result)):
                    break

        # Herald handoff (pure logistics — always succeeds if scribe output exists).
        herald = await workflow.execute_activity(
            "activity_finalize_herald",
            args=[inp.deed_root, plan, ordered],
            start_to_close_timeout=timedelta(minutes=5),
            schedule_to_close_timeout=timedelta(minutes=6),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        if not (isinstance(herald, dict) and herald.get("ok")):
            err_msg = str((herald or {}).get("error_code") or (herald or {}).get("detail") or "herald_failed")
            await _mark_failure(err_msg[:200])

        await self._release_retinue_safe(deed_id, retinue_allocations)
        return herald or {}

    # -- Helpers -------------------------------------------------------------------

    def _move_id(self, st: dict, index: int) -> str:
        return str(st.get("id") or st.get("move_id") or f"move_{index}").strip()

    def _deps(self, st: dict) -> list[str]:
        d = st.get("depends_on") or st.get("dependencies") or []
        return [str(x) for x in d] if isinstance(d, list) else []

    def _agent(self, st: dict) -> str:
        return str(st.get("agent") or "").strip()

    def _agent_limits(self, plan: dict) -> dict[str, int]:
        # Prefer plan-level overrides; fall back to defaults injected by Will.
        system_defaults = plan.get("agent_concurrency_defaults") or {
            "scout": 8, "sage": 4, "arbiter": 2,
            "scribe": 2, "envoy": 1, "spine": 2, "counsel": 1, "artificer": 2,
        }
        overrides: dict = plan.get("agent_concurrency") or {}
        return {**system_defaults, **overrides}

    def _inject_requirements(self, move: dict, *, complexity: str) -> dict:
        if complexity == "errand":
            return dict(move)
        if not self._active_requirements:
            return dict(move)
        out = dict(move)
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
            "\n\nAdditional requirements received during deed:\n"
            + "\n".join(req_lines)
            + "\n\nHonor these requirements while preserving original quality constraints."
        )
        out["instruction"] = (base + appendix).strip()
        return out

    def _start(self, sid: str, st: dict, deed_root: str, plan: dict) -> workflow.ActivityHandle:
        ag = self._agent(st)
        st_to, sc_to = self._timeouts(plan, st)
        max_attempts = int(plan.get("retry_max_attempts") or 3)
        retry = RetryPolicy(maximum_attempts=max_attempts)

        if ag == "spine":
            routine = str(st.get("routine") or st.get("instruction") or "").strip()
            return workflow.start_activity(
                "activity_spine_routine",
                args=[deed_root, plan, routine],
                start_to_close_timeout=st_to,
                schedule_to_close_timeout=sc_to,
                retry_policy=retry,
            )
        return workflow.start_activity(
            "activity_openclaw_move",
            args=[deed_root, plan, st],
            start_to_close_timeout=st_to,
            schedule_to_close_timeout=sc_to,
            heartbeat_timeout=timedelta(seconds=90),
            retry_policy=retry,
        )

    def _timeouts(self, plan: dict, st: dict) -> tuple[timedelta, timedelta]:
        """Resolve move timeouts from Lore hints embedded in plan."""
        hints: dict = plan.get("timeout_hints") or {}
        ag = self._agent(st)
        move_override = int(st.get("timeout_s") or 0)
        agent_hint = int(hints.get(ag) or 0)
        default = int(plan.get("default_move_timeout_s") or 480)
        start_to_close_s = move_override or agent_hint or default
        return timedelta(seconds=start_to_close_s), timedelta(seconds=start_to_close_s + 30)

    def _last_arbiter_result(self, move_results: list[dict]) -> dict | None:
        """Find the most recent arbiter move result."""
        for res in reversed(move_results):
            sid = str(res.get("move_id") or res.get("id") or "")
            agent = str(res.get("agent") or "")
            if "arbiter" in sid.lower() or agent == "arbiter":
                return res
        return None

    # Q7.1: depth-based rework thresholds for five arbiter dimensions.
    _REWORK_THRESHOLDS: dict[str, dict[str, float]] = {
        "glance":   {"coverage": 0.5, "depth": 0.4},
        "study":    {"coverage": 0.6, "depth": 0.6},
        "scrutiny": {"coverage": 0.7, "depth": 0.7},
    }

    def _needs_rework(self, arbiter_result: dict) -> bool:
        """Check if the arbiter move's verdict indicates rework is needed (Q7.1).

        Supports both explicit verdict strings and structured five-dimension scoring:
        coverage, depth, coherence, accuracy, format_compliance (0-1 float each).
        """
        verdict = str(arbiter_result.get("arbiter_verdict") or "").lower()
        if verdict == "rework":
            return True
        status = str(arbiter_result.get("status") or "").lower()
        if status == "rework":
            return True

        # Structured scoring: parse five dimensions from arbiter output.
        scores = arbiter_result.get("scores") or arbiter_result.get("arbiter_scores")
        if not isinstance(scores, dict):
            return False

        depth_level = str(arbiter_result.get("depth") or "study").strip().lower()
        thresholds = self._REWORK_THRESHOLDS.get(depth_level, self._REWORK_THRESHOLDS["study"])

        for dim, threshold in thresholds.items():
            score = scores.get(dim)
            if score is None:
                continue
            try:
                if float(score) < threshold:
                    arbiter_result["rework_reason"] = f"{dim}_below_threshold"
                    return True
            except (ValueError, TypeError):
                continue
        return False

    def _rework_moves(self, move_list: list[dict], error_code: str, attempt: int) -> list[dict]:
        """Select moves to rework based on structured error code (not string matching)."""
        COLLECTION_CODES = {
            "glance_items_too_few", "glance_domain_coverage_too_low",
            "contract_references_too_few", "coverage_below_threshold",
        }
        is_collection_issue = error_code in COLLECTION_CODES

        def _last_by_agent(agent: str) -> dict | None:
            for st in reversed(move_list):
                if self._agent(st) == agent:
                    return dict(st)
            return None

        selected: list[dict] = []
        if is_collection_issue:
            for ag in ("scout", "sage", "scribe"):
                st = _last_by_agent(ag)
                if st:
                    selected.append(st)
        else:
            for ag in ("arbiter", "scribe"):
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
                    f"{base_ins}\n\nRework: arbiter rejected ({error_code}). "
                    "Rewrite to professional standard; no internal system markers; "
                    "bilingual deeds must output separate _zh and _en documents."
                )
        return selected

    async def _mark_deed_status(self, deed_root: str, plan: dict, deed_status: str, error: str) -> None:
        try:
            await workflow.execute_activity(
                "activity_update_deed_status",
                args=[deed_root, {**plan, "last_error": error}, deed_status],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            workflow.logger.warning("Failed to update deed status for %s: %s", deed_root, exc)

    async def _release_retinue_safe(self, deed_id: str, retinue_allocations: dict[str, str]) -> None:
        """Best-effort release of retinue instances. Failures logged but not raised."""
        if not retinue_allocations:
            return
        try:
            await workflow.execute_activity(
                "activity_release_retinue",
                args=[deed_id, retinue_allocations],
                start_to_close_timeout=timedelta(seconds=30),
                schedule_to_close_timeout=timedelta(seconds=40),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
        except Exception as exc:
            workflow.logger.warning("Failed to release retinue for deed %s: %s", deed_id, exc)
