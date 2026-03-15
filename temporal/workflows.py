"""Temporal Workflows — Job execution, health check, self-heal.

Workflows:
  - JobWorkflow: DAG-based multi-step Job orchestration
  - HealthCheckWorkflow: Weekly system health check (§7.7)
  - SelfHealWorkflow: 4-activity self-healing (§7.8)
  - MaintenanceWorkflow: Periodic cleanup (6h schedule)
  - BackupWorkflow: Daily PG + MinIO backup

Reference: SYSTEM_DESIGN.md §3, §7, TODO.md Phase 3
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


@dataclass
class JobInput:
    """Input to JobWorkflow."""
    plan: dict
    job_id: str = ""


@workflow.defn(name="JobWorkflow")
class JobWorkflow:
    """Executes a DAG of Steps with Kahn topological ordering.

    Each step = 1 OC session (agent type) or 1 MCP call (direct type).
    Steps declare depends_on for parallel execution within a layer.
    """

    def __init__(self) -> None:
        self._pause_requested: bool = False

    @workflow.signal(name="pause_execution")
    def pause_execution(self, payload: dict | None = None) -> None:
        _ = payload
        self._pause_requested = True

    @workflow.signal(name="resume_execution")
    def resume_execution(self, payload: dict | None = None) -> None:
        _ = payload
        self._pause_requested = False

    @workflow.run
    async def run(self, inp: JobInput) -> dict:
        plan = inp.plan or {}
        job_id = inp.job_id or str(plan.get("job_id", ""))

        async def _mark_failure(message: str) -> None:
            await self._mark_job_status(job_id, "closed", "failed", message[:200])

        # Extract steps from plan
        steps = plan.get("steps") or []
        if not isinstance(steps, list) or not steps:
            await _mark_failure("missing steps")
            raise ApplicationError("missing steps", non_retryable=True)

        max_parallel = max(1, min(64, int(plan.get("concurrency") or 2)))

        # Build normalized step map and validate IDs
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

        # Build dependency graph
        deps: dict[str, set[str]] = {}
        rev: dict[str, set[str]] = {sid: set() for sid in step_by_id}
        for sid, st in step_by_id.items():
            ds = set(self._deps(st))
            if sid in ds:
                await _mark_failure(f"step {sid} depends on itself")
                raise ApplicationError(
                    f"step {sid} depends on itself", non_retryable=True
                )
            unknown = [d for d in ds if d not in step_by_id]
            if unknown:
                await _mark_failure(f"step {sid}: unknown deps {unknown}")
                raise ApplicationError(
                    f"step {sid}: unknown deps {unknown}", non_retryable=True
                )
            deps[sid] = ds
            for d in ds:
                rev[d].add(sid)

        # Kahn cycle detection
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

        # Mark job as running
        await self._mark_job_status(job_id, "running", "executing")

        # DAG execution loop
        results_by_id: dict[str, dict] = {}
        running: dict[str, workflow.ActivityHandle] = {}
        completed: set[str] = set()
        errors: list[dict] = []
        pending = set(step_by_id.keys())
        pause_state_marked = False

        try:
            while pending or running:
                # Handle pause
                if self._pause_requested and not running:
                    if not pause_state_marked:
                        await self._mark_job_status(job_id, "running", "paused")
                        pause_state_marked = True
                    await workflow.wait_condition(lambda: not self._pause_requested)
                    if pause_state_marked:
                        await self._mark_job_status(job_id, "running", "executing")
                    pause_state_marked = False
                    continue

                # Start ready steps up to concurrency limits
                made_progress = True
                while (
                    not self._pause_requested
                    and made_progress
                    and pending
                    and len(running) < max_parallel
                ):
                    made_progress = False
                    ready = [
                        sid
                        for sid in sorted(pending)
                        if deps.get(sid, set()).issubset(completed)
                    ]
                    if not ready:
                        break

                    for sid in ready:
                        if self._pause_requested or len(running) >= max_parallel:
                            break
                        # Inject upstream results into plan for context
                        enriched_plan = {
                            **plan,
                            "_step_results": [
                                results_by_id[cid]
                                for cid in id_list
                                if cid in results_by_id
                            ],
                        }
                        pending.discard(sid)
                        running[sid] = self._start_step(
                            sid, step_by_id[sid], job_id, enriched_plan
                        )
                        made_progress = True

                if not running:
                    raise ApplicationError(
                        "deadlock: no runnable steps", non_retryable=True
                    )

                done, _ = await workflow.wait(
                    list(running.values()), return_when="FIRST_COMPLETED"
                )
                done_ids = [sid for sid, h in list(running.items()) if h in done]
                for sid in done_ids:
                    h = running.pop(sid)
                    try:
                        res = await h
                        if not isinstance(res, dict):
                            res = {
                                "status": "error",
                                "step_id": sid,
                                "error": "invalid_result",
                            }
                    except Exception as e:
                        res = {
                            "status": "error",
                            "step_id": sid,
                            "error": str(e)[:400],
                        }
                        errors.append(res)
                    # Check if activity returned a failure result
                    if isinstance(res, dict) and res.get("status") in ("failed", "error"):
                        if res not in errors:
                            errors.append(res)
                    results_by_id[sid] = res
                    completed.add(sid)

        except asyncio.CancelledError:
            await self._mark_job_status(job_id, "closed", "cancelled")
            raise
        except ApplicationError:
            if errors:
                await _mark_failure(str(errors[0]["error"])[:200])
            raise
        except Exception as e:
            await _mark_failure(str(e)[:200])
            raise ApplicationError(
                f"workflow_exception: {str(e)[:200]}", non_retryable=True
            ) from e

        # Collect ordered results
        ordered: list[dict] = [
            results_by_id.get(sid)
            or {"status": "error", "step_id": sid, "error": "missing_result"}
            for sid in id_list
        ]

        if errors:
            await _mark_failure(f"{len(errors)} step(s) failed")
            raise ApplicationError(
                f"{len(errors)} step(s) failed", non_retryable=True
            )

        # Job completed successfully
        await self._mark_job_status(job_id, "closed", "completed")

        return {
            "ok": True,
            "job_id": job_id,
            "step_results": ordered,
            "completed_utc": workflow.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    # -- Helpers -------------------------------------------------------------------

    def _step_id(self, st: dict, index: int) -> str:
        return str(
            st.get("id") or st.get("step_id") or f"step_{index}"
        ).strip()

    def _deps(self, st: dict) -> list[str]:
        d = st.get("depends_on") or st.get("dependencies") or []
        return [str(x) for x in d] if isinstance(d, list) else []

    def _agent(self, st: dict) -> str:
        return str(st.get("agent_id") or st.get("agent") or "").strip()

    def _start_step(
        self, sid: str, st: dict, job_id: str, plan: dict
    ) -> workflow.ActivityHandle:
        execution_type = str(st.get("execution_type") or "agent").strip()
        st_to, sc_to = self._timeouts(plan, st)
        max_attempts = int(plan.get("retry_max_attempts") or 3)
        retry = RetryPolicy(maximum_attempts=max_attempts)

        if execution_type == "direct":
            return workflow.start_activity(
                "activity_direct_step",
                args=[job_id, plan, st],
                start_to_close_timeout=st_to,
                schedule_to_close_timeout=sc_to,
                retry_policy=retry,
            )

        if execution_type in ("claude_code", "codex"):
            return workflow.start_activity(
                "activity_cc_step",
                args=[job_id, plan, st],
                start_to_close_timeout=st_to,
                schedule_to_close_timeout=sc_to,
                heartbeat_timeout=timedelta(seconds=90),
                retry_policy=retry,
            )

        return workflow.start_activity(
            "activity_execute_step",
            args=[job_id, plan, st],
            start_to_close_timeout=st_to,
            schedule_to_close_timeout=sc_to,
            heartbeat_timeout=timedelta(seconds=90),
            retry_policy=retry,
        )

    def _timeouts(self, plan: dict, st: dict) -> tuple[timedelta, timedelta]:
        step_override = int(st.get("timeout_s") or 0)
        default = int(plan.get("default_step_timeout_s") or 600)
        start_to_close_s = step_override or default
        return (
            timedelta(seconds=start_to_close_s),
            timedelta(seconds=start_to_close_s + 30),
        )

    async def _mark_job_status(
        self,
        job_id: str,
        status: str,
        sub_status: str,
        error: str = "",
    ) -> None:
        try:
            await workflow.execute_activity(
                "activity_update_job_status",
                args=[job_id, status, sub_status, error],
                start_to_close_timeout=timedelta(seconds=20),
                schedule_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=1),
            )
        except Exception as exc:
            workflow.logger.warning(
                "Failed to update job status for %s: %s", job_id, exc
            )


# ══════════════════════════════════════════════════════════════════════════
# HealthCheckWorkflow — Weekly system health check (§7.7)
# ══════════════════════════════════════════════════════════════════════════


@workflow.defn(name="HealthCheckWorkflow")
class HealthCheckWorkflow:
    """Weekly automated health check.

    3-layer detection:
      1. Infrastructure: 17 data link verification (scripts/verify.py)
      2. Quality: baseline task suite (admin evaluates)
      3. Frontier scan: researcher checks for improvements

    Results → state/health_reports/YYYY-MM-DD.json
    Status → GREEN/YELLOW/RED → Telegram notification
    """

    @workflow.run
    async def run(self, config: dict | None = None) -> dict:
        config = config or {}

        # Activity 1: Infrastructure check (runs scripts/verify.py --links)
        infra_result = await workflow.execute_activity(
            "activity_health_check_infrastructure",
            args=[],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # Activity 2: Quality baseline check (admin-driven)
        quality_result = await workflow.execute_activity(
            "activity_health_check_quality",
            args=[infra_result],
            start_to_close_timeout=timedelta(hours=2),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        # Activity 3: Frontier scan (researcher-driven)
        frontier_result = await workflow.execute_activity(
            "activity_health_check_frontier",
            args=[quality_result],
            start_to_close_timeout=timedelta(hours=1),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )

        # Activity 4: Generate report + notify
        report = await workflow.execute_activity(
            "activity_health_report",
            args=[infra_result, quality_result, frontier_result],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        return report


# ══════════════════════════════════════════════════════════════════════════
# SelfHealWorkflow — 4-activity self-healing (§7.8)
# ══════════════════════════════════════════════════════════════════════════


@workflow.defn(name="SelfHealWorkflow")
class SelfHealWorkflow:
    """Self-healing workflow: 4 activities, crash-safe.

    Activity 1: admin generates issue file (state/issues/YYYY-MM-DD-HHMM.md)
    Activity 2: CC/Codex reads issue → applies fix (only files/config)
    Activity 3: scripts/start.py (restart, may kill Worker → Temporal retries)
    Activity 4: scripts/verify.py --issue ID (verify + Telegram notify)

    Reference: SYSTEM_DESIGN.md §7.8
    """

    @workflow.run
    async def run(self, trigger: dict) -> dict:
        issue_id = trigger.get("issue_id", "")

        # Activity 1: Generate issue file
        if not issue_id:
            issue_result = await workflow.execute_activity(
                "activity_self_heal_diagnose",
                args=[trigger],
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=RetryPolicy(maximum_attempts=2),
            )
            issue_id = issue_result.get("issue_id", "")

        if not issue_id:
            return {"ok": False, "error": "failed_to_generate_issue"}

        # Activity 2: Apply fix (CC/Codex reads issue file, applies changes)
        fix_result = await workflow.execute_activity(
            "activity_self_heal_fix",
            args=[issue_id],
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if not fix_result.get("ok"):
            # Layer 3: notify user
            await workflow.execute_activity(
                "activity_self_heal_notify_failure",
                args=[issue_id, fix_result],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return {"ok": False, "issue_id": issue_id, "layer": 3, "error": "fix_failed"}

        # Activity 3: Restart services (may crash Worker — Temporal recovers)
        restart_result = await workflow.execute_activity(
            "activity_self_heal_restart",
            args=[],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                maximum_attempts=3,
                initial_interval=timedelta(seconds=10),
            ),
        )

        # Activity 4: Verify fix
        verify_result = await workflow.execute_activity(
            "activity_self_heal_verify",
            args=[issue_id],
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if verify_result.get("overall") == "GREEN":
            return {"ok": True, "issue_id": issue_id, "layer": 2}
        else:
            # Layer 3 fallback
            await workflow.execute_activity(
                "activity_self_heal_notify_failure",
                args=[issue_id, verify_result],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return {"ok": False, "issue_id": issue_id, "layer": 3, "error": "verify_failed"}


# ══════════════════════════════════════════════════════════════════════════
# MaintenanceWorkflow — Periodic cleanup (every 6h)
# ══════════════════════════════════════════════════════════════════════════


@workflow.defn(name="MaintenanceWorkflow")
class MaintenanceWorkflow:
    """Wraps the single maintenance activity for Temporal Schedule."""

    @workflow.run
    async def run(self, config: dict | None = None) -> dict:
        return await workflow.execute_activity(
            "activity_maintenance",
            args=[],
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


# ══════════════════════════════════════════════════════════════════════════
# BackupWorkflow — Daily incremental backup
# ══════════════════════════════════════════════════════════════════════════


@workflow.defn(name="BackupWorkflow")
class BackupWorkflow:
    """Daily incremental backup of PG + MinIO."""

    @workflow.run
    async def run(self, config: dict | None = None) -> dict:
        return await workflow.execute_activity(
            "activity_backup",
            args=[config or {}],
            start_to_close_timeout=timedelta(minutes=60),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
