"""Temporal activities: execution-layer routines."""
from __future__ import annotations

import asyncio
import json
import time
import uuid

from temporalio import activity
from temporalio.exceptions import CancelledError as TemporalCancelledError


async def run_openclaw_move(self, deed_root: str, plan: dict, move: dict) -> dict:
    """Execute a single move via persistent full session (sessions_send).

    Uses the retinue instance's main session — MEMORY.md is loaded at session
    start and context accumulates across moves to the same agent.  The call
    blocks until the agent finishes (synchronous wait via timeoutSeconds).
    """
    if not self._openclaw:
        raise RuntimeError("OpenClawAdapter unavailable (OPENCLAW_HOME missing or openclaw.json invalid)")

    agent_role = str(move.get("agent") or "").strip()
    move_id = str(move.get("id") or "move").strip()
    deed_id = str(plan.get("deed_id") or deed_root.split("/")[-1] or uuid.uuid4().hex[:8])

    # Resolve agent role -> retinue instance
    retinue_allocations = plan.get("retinue_allocations") or {}
    agent_id = str(retinue_allocations.get(agent_role, agent_role))
    session_key = self._openclaw.main_session_key(agent_id)

    instruction = str(move.get("instruction") or move.get("message") or "").strip()
    timeout_s = int(move.get("timeout_s") or plan.get("default_move_timeout_s") or 480)
    move_label = str(move.get("label") or instruction[:80] or move_id)

    def _emit_progress(phase: str, **extra) -> None:
        self._ether.emit(
            "deed_progress",
            {
                "deed_id": deed_id,
                "move_id": move_id,
                "move_label": move_label,
                "agent": agent_role or agent_id,
                "phase": phase,
                **extra,
            },
        )

    checkpoint = self._read_move_checkpoint(deed_root, move_id)
    if checkpoint and str(checkpoint.get("status") or "") in {"ok", "degraded"}:
        checkpoint["restored_from_checkpoint"] = True
        return checkpoint

    context_payload = self._build_move_context(deed_root, plan, move)
    context_payload = self._apply_context_window_precheck(
        deed_root=deed_root,
        plan=plan,
        move=move,
        instruction=instruction,
        context=context_payload,
    )

    composed_message = (
        f"{instruction}\n\n{json.dumps(context_payload, ensure_ascii=False)}"
        if context_payload
        else instruction
    )

    _emit_progress("started")

    # Run send_to_session in a thread; heartbeat every 30s while waiting.
    send_future: asyncio.Future[dict] = asyncio.get_running_loop().run_in_executor(
        None, self._openclaw.send_to_session, session_key, composed_message, timeout_s,
    )
    heartbeat_interval = 30

    try:
        while True:
            try:
                resp = await asyncio.wait_for(asyncio.shield(send_future), timeout=heartbeat_interval)
                break  # send completed
            except asyncio.TimeoutError:
                activity.heartbeat({"deed_id": deed_id, "move_id": move_id, "phase": "waiting"})
    except (TemporalCancelledError, asyncio.CancelledError):
        result = {
            "status": "cancelled",
            "move_id": move_id,
            "agent": agent_id,
            "session_key": session_key,
            "error": "cancelled",
        }
        self._write_move_checkpoint(deed_root, move_id, result)
        try:
            self._update_deed_status(deed_root, plan, "cancelled")
        except Exception:
            pass
        raise
    except Exception as exc:
        error_msg = str(exc)[:200]
        # Check for circuit breaker / abort
        if "aborted" in error_msg.lower() or "circuit" in error_msg.lower():
            result = {
                "status": "circuit_breaker",
                "move_id": move_id,
                "agent": agent_id,
                "session_key": session_key,
                "error": error_msg,
            }
            self._write_move_checkpoint(deed_root, move_id, result)
            _emit_progress("degraded", error="circuit_breaker")
            return result
        activity.logger.warning("Move %s failed: %s", move_id, error_msg)
        result = {
            "status": "degraded",
            "move_id": move_id,
            "agent": agent_id,
            "session_key": session_key,
            "error": error_msg,
            "degraded": True,
        }
        self._write_move_checkpoint(deed_root, move_id, result)
        _emit_progress("degraded", error=error_msg)
        return result

    # Extract reply content from sessions_send response.
    reply = str(resp.get("reply") or resp.get("text") or resp.get("content") or "").strip()
    status = str(resp.get("status") or "").strip().lower()

    if status in {"error", "failed", "aborted"}:
        result = {
            "status": "degraded",
            "move_id": move_id,
            "agent": agent_id,
            "session_key": session_key,
            "error": str(resp.get("error") or status),
            "degraded": True,
        }
        self._write_move_checkpoint(deed_root, move_id, result)
        _emit_progress("degraded", error=result["error"])
        return result

    output_path = self._write_move_output(deed_root, move_id, reply) if reply else ""
    result = {
        "status": "ok",
        "move_id": move_id,
        "agent": agent_id,
        "session_key": session_key,
        "output_path": output_path,
    }
    self._write_move_checkpoint(deed_root, move_id, result)
    _emit_progress("completed", output_path=output_path)
    return result


async def run_spine_routine(self, deed_root: str, plan: dict, routine_name: str) -> dict:
    from psyche.memory import MemoryPsyche
    from psyche.lore import LorePsyche
    from psyche.instinct import InstinctPsyche
    from runtime.cortex import Cortex
    from spine.nerve import Nerve
    from spine.trail import Trail
    from spine.routines import SpineRoutines

    home = self._home
    state = home / "state"
    psyche_dir = state / "psyche"
    memory = MemoryPsyche(psyche_dir / "memory.db")
    lore = LorePsyche(psyche_dir / "lore.db")
    instinct = InstinctPsyche(psyche_dir / "instinct.db")
    cortex = Cortex(instinct)
    nerve = Nerve()
    trail = Trail(state / "trails")

    routines = SpineRoutines(
        memory=memory, lore=lore, instinct=instinct,
        cortex=cortex, nerve=nerve, trail=trail,
        daemon_home=home, openclaw_home=self._oc_home,
    )

    method_name = routine_name.replace("spine.", "")
    routine_method = getattr(routines, method_name, None)
    if not callable(routine_method):
        raise ValueError(f"Unknown spine routine: {routine_name}")
    start_ts = time.time()
    try:
        result = routine_method()
        routines.log_execution(method_name, "ok", result, time.time() - start_ts)
        return {"status": "ok", "routine": routine_name, "result": result}
    except Exception as exc:
        routines.log_execution(method_name, "error", {"error": str(exc)[:200]}, time.time() - start_ts)
        raise
