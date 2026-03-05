"""Temporal activities: execution-layer routines."""
from __future__ import annotations

import asyncio
import json
import time
import uuid

from temporalio import activity


async def run_openclaw_step(self, run_root: str, plan: dict, step: dict) -> dict:
    if not self._openclaw:
        raise RuntimeError("OpenClawAdapter unavailable (OPENCLAW_HOME missing or openclaw.json invalid)")

    agent_id = str(step.get("agent") or "").strip()
    step_id = str(step.get("id") or "step").strip()
    task_id = str(plan.get("task_id") or run_root.split("/")[-1] or uuid.uuid4().hex[:8])
    session_key = self._openclaw.session_key(agent_id, task_id, step_id)
    instruction = str(step.get("instruction") or step.get("message") or "").strip()
    timeout_s = int(step.get("timeout_s") or plan.get("default_step_timeout_s") or 480)

    checkpoint = self._read_step_checkpoint(run_root, step_id)
    if checkpoint and str(checkpoint.get("status") or "") in {"ok", "degraded"}:
        checkpoint["restored_from_checkpoint"] = True
        return checkpoint

    context_payload = self._build_step_context(run_root, plan, step)
    context_payload = self._apply_context_window_precheck(
        run_root=run_root,
        plan=plan,
        step=step,
        instruction=instruction,
        context=context_payload,
    )

    composed_message = (
        f"{instruction}\n\n{json.dumps(context_payload, ensure_ascii=False)}"
        if context_payload
        else instruction
    )
    await asyncio.to_thread(self._openclaw.send, session_key, composed_message, agent_id)

    deadline = time.time() + timeout_s
    poll_interval = 5
    last_content = ""

    while time.time() < deadline:
        await asyncio.sleep(poll_interval)
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

        if newest_assistant:
            content = str(newest_assistant.get("content") or newest_assistant.get("text") or "").strip()
            if content:
                raw = newest_assistant.get("raw") if isinstance(newest_assistant.get("raw"), dict) else {}
                stop_reason = str(raw.get("stopReason") or "").strip().lower()
                has_done_signal = any(
                    signal in content.lower()
                    for signal in ["[done]", "[complete]", "task complete", "completed successfully"]
                )
                if content != last_content:
                    last_content = content
                if has_done_signal or stop_reason in {"stop", "end_turn"}:
                    output_path = self._write_step_output(run_root, step_id, content)
                    result = {
                        "status": "ok",
                        "step_id": step_id,
                        "agent": agent_id,
                        "session_key": session_key,
                        "output_path": output_path,
                    }
                    self._write_step_checkpoint(run_root, step_id, result)
                    return result

        poll_interval = min(poll_interval * 1.2, 30)

    activity.logger.warning("Step %s timed out after %ss — marking degraded", step_id, timeout_s)
    result = {
        "status": "degraded",
        "step_id": step_id,
        "agent": agent_id,
        "session_key": session_key,
        "error": f"timeout_after_{timeout_s}s",
        "degraded": True,
    }
    self._write_step_checkpoint(run_root, step_id, result)
    return result


async def run_spine_routine(self, run_root: str, plan: dict, routine_name: str) -> dict:
    from fabric.memory import MemoryFabric
    from fabric.playbook import PlaybookFabric
    from fabric.compass import CompassFabric
    from runtime.cortex import Cortex
    from spine.nerve import Nerve
    from spine.trace import Tracer
    from spine.routines import SpineRoutines

    home = self._home
    state = home / "state"
    memory = MemoryFabric(state / "memory.db")
    playbook = PlaybookFabric(state / "playbook.db")
    compass = CompassFabric(state / "compass.db")
    cortex = Cortex(compass)
    nerve = Nerve()
    tracer = Tracer(state / "traces")

    routines = SpineRoutines(
        memory=memory, playbook=playbook, compass=compass,
        cortex=cortex, nerve=nerve, tracer=tracer,
        daemon_home=home, openclaw_home=self._oc_home,
    )

    method = getattr(routines, routine_name.replace("spine.", ""), None)
    if not callable(method):
        raise ValueError(f"Unknown spine routine: {routine_name}")
    result = method()
    return {"status": "ok", "routine": routine_name, "result": result}
