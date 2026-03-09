"""Temporal activities: execution-layer routines."""
from __future__ import annotations

import asyncio
import json
import time
import uuid

from temporalio import activity
from temporalio.exceptions import CancelledError as TemporalCancelledError


async def run_openclaw_move(self, deed_root: str, plan: dict, move: dict) -> dict:
    if not self._openclaw:
        raise RuntimeError("OpenClawAdapter unavailable (OPENCLAW_HOME missing or openclaw.json invalid)")

    agent_role = str(move.get("agent") or "").strip()
    move_id = str(move.get("id") or "move").strip()
    deed_id = str(plan.get("deed_id") or deed_root.split("/")[-1] or uuid.uuid4().hex[:8])

    # Resolve agent role -> retinue instance if allocations exist
    retinue_allocations = plan.get("retinue_allocations") or {}
    agent_id = str(retinue_allocations.get(agent_role, agent_role))

    session_key = self._openclaw.session_key(agent_id, deed_id, move_id)
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
    await asyncio.to_thread(self._openclaw.send, session_key, composed_message, agent_id)
    activity.heartbeat({"deed_id": deed_id, "move_id": move_id, "phase": "sent"})
    _emit_progress("waiting")

    deadline = time.time() + timeout_s
    poll_interval = 5
    last_content = ""

    try:
        while time.time() < deadline:
            await asyncio.sleep(poll_interval)
            activity.heartbeat({"deed_id": deed_id, "move_id": move_id, "phase": "poll"})
            try:
                messages = await asyncio.to_thread(self._openclaw.history, session_key, 8)
            except Exception as exc:
                activity.logger.warning("history poll failed for %s: %s", session_key, exc)
                poll_interval = min(poll_interval * 1.2, 30)
                continue
            if not isinstance(messages, list):
                messages = []

            newest_assistant = None
            for msg in reversed(messages):
                if not isinstance(msg, dict):
                    continue
                role = str(msg.get("role") or "").strip().lower()
                if role != "assistant":
                    continue
                content = str(msg.get("content") or msg.get("text") or "").strip()
                if not content:
                    continue
                newest_assistant = msg
                break

            # Q3.7(c): Check abortedLastRun to detect circuit breaker termination.
            if self._openclaw:
                try:
                    sess_status = await asyncio.to_thread(self._openclaw.session_status, session_key)
                    if sess_status.get("abortedLastRun"):
                        activity.logger.warning(
                            "Move %s aborted by circuit breaker (agent=%s)", move_id, agent_id
                        )
                        partial_content = last_content or ""
                        if partial_content:
                            self._write_move_output(deed_root, move_id, partial_content)
                        result = {
                            "status": "circuit_breaker",
                            "move_id": move_id,
                            "agent": agent_id,
                            "session_key": session_key,
                            "error": "aborted_by_loop_detection",
                            "partial_content": partial_content[:500],
                        }
                        self._write_move_checkpoint(deed_root, move_id, result)
                        _emit_progress("degraded", error=result["error"])
                        return result
                except Exception as exc:
                    activity.logger.warning("session_status check failed for %s: %s", session_key, exc)

            if newest_assistant:
                content = str(newest_assistant.get("content") or newest_assistant.get("text") or "").strip()
                if content:
                    raw = newest_assistant.get("raw") if isinstance(newest_assistant.get("raw"), dict) else {}
                    stop_reason = str(raw.get("stopReason") or "").strip().lower()
                    has_done_signal = any(
                        signal in content.lower()
                        for signal in ["[done]", "[complete]", "run complete", "completed successfully"]
                    )
                    if content != last_content:
                        last_content = content
                    if has_done_signal or stop_reason in {"stop", "end_turn"}:
                        output_path = self._write_move_output(deed_root, move_id, content)
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

            poll_interval = min(poll_interval * 1.2, 30)
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

    activity.logger.warning("Move %s timed out after %ss — marking degraded", move_id, timeout_s)
    result = {
        "status": "degraded",
        "move_id": move_id,
        "agent": agent_id,
        "session_key": session_key,
        "error": f"timeout_after_{timeout_s}s",
        "degraded": True,
    }
    self._write_move_checkpoint(deed_root, move_id, result)
    _emit_progress("degraded", error=result["error"])
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
    memory = MemoryPsyche(state / "memory.db")
    lore = LorePsyche(state / "lore.db")
    instinct = InstinctPsyche(state / "instinct.db")
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
