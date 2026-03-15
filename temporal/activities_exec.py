"""Temporal activities: Step execution routines.

Terminology: deed→job, move→step, folio→project, writ→task
Dependencies: EventBus (PG) replaces Ether (JSONL), Store (PG) replaces Ledger (JSON)

Reference: SYSTEM_DESIGN.md §3.3-§3.4, TODO.md Phase 3.1
"""
from __future__ import annotations

import asyncio
import json
import time

from temporalio import activity
from temporalio.exceptions import CancelledError as TemporalCancelledError

from config.guardrails.actions import validate_input, validate_output
from config.mem0_config import retrieve_agent_context, retrieve_user_preferences


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def run_openclaw_step(self, job_id: str, plan: dict, step: dict) -> dict:
    """Execute a single step via OC spawn_session (1 Step = 1 Session).

    Each step gets an isolated session that loads MEMORY.md + tools.
    This avoids lane contention from shared main sessions.

    Reference: SYSTEM_DESIGN.md §3.4
    """
    if not self._openclaw:
        raise RuntimeError(
            "OpenClawAdapter unavailable (OPENCLAW_HOME missing or openclaw.json invalid)"
        )

    agent_id = str(step.get("agent_id") or step.get("agent") or "").strip()
    raw_index = step.get("step_index")
    step_index = int(raw_index) if raw_index is not None else 0
    step_id = str(step.get("step_id") or step.get("id") or f"step_{step_index}")

    goal = str(step.get("goal") or step.get("instruction") or "").strip()
    timeout_s = int(step.get("timeout_s") or plan.get("default_step_timeout_s") or 600)
    execution_type = str(step.get("execution_type") or "agent").strip()
    step_label = str(step.get("label") or goal[:80] or step_id)

    async def _emit(phase: str, **extra) -> None:
        await self._event_bus.publish("step_events", f"step_{phase}", {
            "job_id": job_id,
            "step_id": step_id,
            "step_index": step_index,
            "step_label": step_label,
            "agent_id": agent_id,
            "phase": phase,
            **extra,
        })

    # Build composed message with brief context
    context_payload: dict = {}
    brief = plan.get("brief")
    if isinstance(brief, dict):
        context_payload["brief"] = brief
    task_title = str(plan.get("task_title") or plan.get("title") or "")
    if task_title:
        context_payload["task_title"] = task_title

    # Upstream step outputs: include completed step summaries for context
    upstream = plan.get("_step_results")
    if isinstance(upstream, list) and upstream:
        context_payload["upstream_steps"] = [
            {
                "step_id": str(r.get("step_id") or ""),
                "agent_id": str(r.get("agent_id") or ""),
                "output": str(r.get("output") or "")[:2000],
            }
            for r in upstream
            if isinstance(r, dict) and str(r.get("status") or "") == "completed"
        ][:10]

    # ── Mem0: inject agent memory + user preferences (~50-200 tokens) ──
    mem0 = getattr(self, "_mem0", None)
    agent_memory = retrieve_agent_context(mem0, agent_id, limit=5)
    user_prefs = retrieve_user_preferences(mem0, limit=3)
    if agent_memory:
        context_payload["agent_memory"] = agent_memory
    if user_prefs:
        context_payload["user_preferences"] = user_prefs

    composed_message = (
        f"{goal}\n\n{json.dumps(context_payload, ensure_ascii=False)}"
        if context_payload
        else goal
    )

    # ── Guardrails: input validation (zero token) ────────────────
    filtered_message, input_warnings = validate_input(composed_message)
    if input_warnings:
        activity.logger.info("Guardrails input warnings for step %s: %s", step_id, input_warnings)
    if not filtered_message:
        # Input was blocked by guardrails
        result = {
            "status": "failed",
            "step_id": step_id,
            "step_index": step_index,
            "agent_id": agent_id,
            "error": f"Input blocked by guardrails: {'; '.join(input_warnings)}",
        }
        await _emit("failed", error=result["error"])
        return result
    composed_message = filtered_message

    await _emit("started")

    # ── Langfuse: create trace for this step ─────────────────────
    lf_trace = None
    langfuse = getattr(self, "_langfuse", None)
    if langfuse:
        try:
            lf_trace = langfuse.trace(
                name=f"step:{step_id}",
                metadata={
                    "job_id": job_id, "agent_id": agent_id,
                    "execution_type": execution_type, "step_index": step_index,
                },
                input={"goal": goal[:500]},
            )
        except Exception:
            pass

    # Spawn isolated session (1 Step = 1 Session, no lane contention)
    spawn_label = f"{job_id[:8]}:{step_id}"
    spawn_future = asyncio.get_running_loop().run_in_executor(
        None,
        lambda: self._openclaw.spawn_session(
            agent_id, composed_message,
            label=spawn_label, timeout_s=timeout_s, cleanup="delete",
        ),
    )
    heartbeat_interval = 30

    try:
        while True:
            try:
                resp = await asyncio.wait_for(
                    asyncio.shield(spawn_future), timeout=heartbeat_interval
                )
                break
            except asyncio.TimeoutError:
                activity.heartbeat({
                    "job_id": job_id, "step_id": step_id, "phase": "waiting"
                })
    except (TemporalCancelledError, asyncio.CancelledError):
        await _emit("cancelled")
        raise
    except Exception as exc:
        error_msg = str(exc)[:200]
        activity.logger.warning("Step %s failed: %s", step_id, error_msg)
        result = {
            "status": "failed",
            "step_id": step_id,
            "step_index": step_index,
            "agent_id": agent_id,
            "error": error_msg,
        }
        if lf_trace:
            try:
                lf_trace.update(output={"status": "failed", "error": error_msg})
            except Exception:
                pass
        await _emit("failed", error=error_msg)
        return result

    # Extract reply from spawn_session response
    reply = str(
        resp.get("reply") or resp.get("text") or resp.get("content") or ""
    ).strip()
    status = str(resp.get("status") or "").strip().lower()

    if status in {"error", "failed", "aborted", "timeout"}:
        result = {
            "status": "failed",
            "step_id": step_id,
            "step_index": step_index,
            "agent_id": agent_id,
            "error": str(resp.get("error") or status),
        }
        await _emit("failed", error=result["error"])
        return result

    # ── Guardrails: output validation (zero token) ───────────────
    if reply:
        cleaned_reply, output_warnings = validate_output(reply)
        if output_warnings:
            activity.logger.info("Guardrails output warnings for step %s: %s", step_id, output_warnings)
        reply = cleaned_reply

    result = {
        "status": "completed",
        "step_id": step_id,
        "step_index": step_index,
        "agent_id": agent_id,
        "output": reply[:10000] if reply else "",
    }

    # ── Langfuse: finalize trace ──────────────────────────────────
    if lf_trace:
        try:
            lf_trace.update(output={"status": "completed", "output_len": len(reply)})
        except Exception:
            pass

    await _emit("completed")
    return result


async def run_cc_step(self, job_id: str, plan: dict, step: dict) -> dict:
    """Execute a step via Claude Code or Codex CLI — bypasses OC.

    Injects MEMORY.md + skill context into the prompt, then runs
    `claude` or `codex` CLI in a subprocess.

    Reference: SYSTEM_DESIGN.md §3.3 (execution_type: claude_code / codex)
    """
    import asyncio
    import subprocess
    import tempfile

    raw_index = step.get("step_index")
    step_index = int(raw_index) if raw_index is not None else 0
    step_id = str(step.get("step_id") or step.get("id") or f"step_{step_index}")
    agent_id = str(step.get("agent_id") or step.get("agent") or "engineer").strip()
    execution_type = str(step.get("execution_type") or "claude_code").strip()
    goal = str(step.get("goal") or step.get("instruction") or "").strip()
    timeout_s = int(step.get("timeout_s") or plan.get("default_step_timeout_s") or 600)

    await self._event_bus.publish("step_events", "step_started", {
        "job_id": job_id, "step_id": step_id,
        "execution_type": execution_type, "agent_id": agent_id,
    })

    # Inject Mem0 context
    mem0 = getattr(self, "_mem0", None)
    agent_memory = retrieve_agent_context(mem0, agent_id, limit=5)
    user_prefs = retrieve_user_preferences(mem0, limit=3)

    context_parts = [goal]
    if agent_memory:
        context_parts.append(f"\n{agent_memory}")
    if user_prefs:
        context_parts.append(f"\n{user_prefs}")

    # Inject MEMORY.md if it exists
    import os
    from pathlib import Path
    oc_home = Path(os.environ.get("OPENCLAW_HOME", "")) / "workspace" / agent_id / "MEMORY.md"
    if oc_home.exists():
        try:
            memory_text = oc_home.read_text(encoding="utf-8")[:2000]
            context_parts.append(f"\n[MEMORY.md]\n{memory_text}")
        except Exception:
            pass

    prompt = "\n".join(context_parts)

    # Find CLI binary
    def _find_cli(name: str) -> str | None:
        import shutil
        return shutil.which(name)

    if execution_type == "claude_code":
        cli = _find_cli("claude")
        if not cli:
            return {"status": "failed", "step_id": step_id, "step_index": step_index,
                    "error": "'claude' CLI not found in PATH"}
        cmd = [cli, "--print", "--output-format", "text", prompt]
    else:  # codex
        cli = _find_cli("codex")
        if not cli:
            return {"status": "failed", "step_id": step_id, "step_index": step_index,
                    "error": "'codex' CLI not found in PATH"}
        cmd = [cli, "--quiet", "--approval-mode", "auto-edit", prompt]

    # Run CLI in subprocess with heartbeats
    loop = asyncio.get_running_loop()

    def _run_cli():
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s,
            cwd=str(Path(os.environ.get("DAEMON_HOME", ".")).resolve()),
        )
        return result.stdout, result.stderr, result.returncode

    heartbeat_interval = 30
    future = loop.run_in_executor(None, _run_cli)

    try:
        while True:
            try:
                stdout, stderr, returncode = await asyncio.wait_for(
                    asyncio.shield(future), timeout=heartbeat_interval,
                )
                break
            except asyncio.TimeoutError:
                activity.heartbeat({
                    "job_id": job_id, "step_id": step_id, "phase": "running_cli",
                })
    except Exception as exc:
        error_msg = str(exc)[:200]
        await self._event_bus.publish("step_events", "step_failed", {
            "job_id": job_id, "step_id": step_id, "error": error_msg,
        })
        return {"status": "failed", "step_id": step_id, "step_index": step_index,
                "agent_id": agent_id, "error": error_msg}

    output = (stdout or "").strip()
    if returncode != 0 and not output:
        output = (stderr or "").strip()

    if returncode != 0:
        await self._event_bus.publish("step_events", "step_failed", {
            "job_id": job_id, "step_id": step_id, "error": f"exit_code={returncode}",
        })
        return {"status": "failed", "step_id": step_id, "step_index": step_index,
                "agent_id": agent_id, "error": f"CLI exited with code {returncode}: {output[:500]}"}

    # Guardrails: output validation
    cleaned_output, output_warnings = validate_output(output)
    if output_warnings:
        activity.logger.info("Guardrails output warnings for cc step %s: %s", step_id, output_warnings)

    await self._event_bus.publish("step_events", "step_completed", {
        "job_id": job_id, "step_id": step_id, "execution_type": execution_type,
    })
    return {"status": "completed", "step_id": step_id, "step_index": step_index,
            "agent_id": agent_id, "output": cleaned_output[:10000]}


async def run_direct_step(self, job_id: str, plan: dict, step: dict) -> dict:
    """Execute a direct step via MCP tool or Python callable — zero LLM tokens.

    Direct steps bypass OC agent sessions entirely. They execute mechanical
    operations (Telegram, PDF, git, etc.) through registered MCP servers.

    Reference: SYSTEM_DESIGN.md §3.3 (execution_type: direct)
    """
    raw_index = step.get("step_index")
    step_index = int(raw_index) if raw_index is not None else 0
    step_id = str(step.get("step_id") or step.get("id") or f"step_{step_index}")
    tool_name = str(step.get("tool") or step.get("mcp_tool") or "").strip()
    tool_args = step.get("tool_args") if isinstance(step.get("tool_args"), dict) else {}

    if not tool_name:
        return {
            "status": "failed",
            "step_id": step_id,
            "step_index": step_index,
            "error": "direct step requires 'tool' or 'mcp_tool' field",
        }

    await self._event_bus.publish("step_events", "step_started", {
        "job_id": job_id,
        "step_id": step_id,
        "execution_type": "direct",
    })

    if not self._mcp or not self._mcp.available:
        return {
            "status": "failed",
            "step_id": step_id,
            "step_index": step_index,
            "tool": tool_name,
            "error": "No MCP servers configured (config/mcp_servers.json)",
        }

    timeout_s = int(step.get("timeout_s") or plan.get("default_step_timeout_s") or 120)

    try:
        result = await self._mcp.call_tool(tool_name, tool_args, timeout_s=timeout_s)
        output = ""
        if isinstance(result, dict) and result.get("output"):
            output = str(result["output"])[:10000]

        await self._event_bus.publish("step_events", "step_completed", {
            "job_id": job_id,
            "step_id": step_id,
            "execution_type": "direct",
        })

        return {
            "status": "completed",
            "step_id": step_id,
            "step_index": step_index,
            "tool": tool_name,
            "output": output,
            "result": result if isinstance(result, dict) else {"output": str(result)},
        }
    except Exception as exc:
        error_msg = str(exc)[:200]
        activity.logger.warning("Direct step %s failed: %s", step_id, error_msg)
        return {
            "status": "failed",
            "step_id": step_id,
            "step_index": step_index,
            "tool": tool_name,
            "error": error_msg,
        }
