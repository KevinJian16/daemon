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

    Session key format: {agent_id}:{deed_id}:{session_seq}
    Serial moves share session_seq 0; parallel moves get incrementing seqs.
    Rework appends to existing session (same key, context accumulates).
    """
    if not self._openclaw:
        raise RuntimeError("OpenClawAdapter unavailable (OPENCLAW_HOME missing or openclaw.json invalid)")

    agent_role = str(move.get("agent") or "").strip()
    move_id = str(move.get("id") or "move").strip()
    deed_id = str(plan.get("deed_id") or deed_root.split("/")[-1] or uuid.uuid4().hex[:8])

    # Resolve agent role -> retinue instance
    retinue_allocations = plan.get("retinue_allocations") or {}
    agent_id = str(retinue_allocations.get(agent_role, agent_role))
    # Session key: {agent_id}:{deed_id}:{session_seq} (§2.3)
    session_seq = int(move.get("session_seq") or 0)
    session_key = f"{agent_id}:{deed_id}:{session_seq}"

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

    rework_attempt = int(move.get("rework_attempt") or 0)
    rework_prefix = f"[Rework attempt {rework_attempt}]\n" if rework_attempt > 0 else ""
    composed_message = (
        f"{rework_prefix}{instruction}\n\n{json.dumps(context_payload, ensure_ascii=False)}"
        if context_payload
        else f"{rework_prefix}{instruction}"
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
    _emit_progress("move_completed", output_path=output_path)
    return result


async def run_direct_move(self, deed_root: str, plan: dict, move: dict) -> dict:
    """Execute a direct move via MCP tool or Python callable — zero LLM tokens (§3).

    Direct moves bypass OC agent sessions entirely. They execute mechanical
    operations (Telegram, PDF, git, etc.) through registered MCP servers or
    Python functions.
    """
    move_id = str(move.get("id") or "move").strip()
    deed_id = str(plan.get("deed_id") or deed_root.split("/")[-1] or uuid.uuid4().hex[:8])
    tool_name = str(move.get("tool") or move.get("mcp_tool") or "").strip()
    tool_args = move.get("tool_args") if isinstance(move.get("tool_args"), dict) else {}

    if not tool_name:
        return {
            "status": "degraded",
            "move_id": move_id,
            "error": "direct move requires 'tool' or 'mcp_tool' field",
        }

    self._ether.emit("deed_progress", {
        "deed_id": deed_id, "move_id": move_id,
        "phase": "started", "execution_type": "direct",
    })

    if not self._mcp or not self._mcp.available:
        return {
            "status": "degraded",
            "move_id": move_id,
            "tool": tool_name,
            "error": "No MCP servers configured (config/mcp_servers.json)",
        }

    timeout_s = int(move.get("timeout_s") or plan.get("default_move_timeout_s") or 120)

    try:
        result = await self._mcp.call_tool(tool_name, tool_args, timeout_s=timeout_s)
        output_path = ""
        if isinstance(result, dict) and result.get("output"):
            output_path = self._write_move_output(deed_root, move_id, str(result["output"]))
        checkpoint = {
            "status": "ok",
            "move_id": move_id,
            "tool": tool_name,
            "output_path": output_path,
            "result": result if isinstance(result, dict) else {"output": str(result)},
        }
        self._write_move_checkpoint(deed_root, move_id, checkpoint)
        self._ether.emit("deed_progress", {
            "deed_id": deed_id, "move_id": move_id,
            "phase": "move_completed", "execution_type": "direct",
        })
        return checkpoint
    except Exception as exc:
        error_msg = str(exc)[:200]
        activity.logger.warning("Direct move %s failed: %s", move_id, error_msg)
        checkpoint = {
            "status": "degraded",
            "move_id": move_id,
            "tool": tool_name,
            "error": error_msg,
        }
        self._write_move_checkpoint(deed_root, move_id, checkpoint)
        return checkpoint


async def run_spine_routine(self, deed_root: str, plan: dict, routine_name: str) -> dict:
    from psyche.config import PsycheConfig
    from psyche.ledger_stats import LedgerStats
    from psyche.instinct_engine import InstinctEngine
    from runtime.cortex import Cortex
    from spine.nerve import Nerve
    from spine.trail import Trail
    from spine.routines import SpineRoutines

    home = self._home
    state = home / "state"
    psyche_dir = state / "psyche"
    psyche_config = PsycheConfig(home / "psyche")
    ledger_stats = LedgerStats(psyche_dir / "ledger.db")
    instinct_engine = InstinctEngine(home / "psyche")
    cortex = Cortex(psyche_config)
    nerve = Nerve()
    trail = Trail(state / "trails")

    routines = SpineRoutines(
        psyche_config=psyche_config, ledger_stats=ledger_stats, instinct_engine=instinct_engine,
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
