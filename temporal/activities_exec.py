"""Temporal activities: Step execution routines.

Current architecture: Jobs/Steps in PG (Store), events via EventBus (PG LISTEN/NOTIFY).

Reference: SYSTEM_DESIGN.md §3.3-§3.4, TODO.md Phase 3.1
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from uuid import UUID

from temporalio import activity
from temporalio.exceptions import CancelledError as TemporalCancelledError

from config.guardrails.actions import validate_input, validate_output
from config.mem0_config import retrieve_agent_context, retrieve_user_preferences

_exec_logger = logging.getLogger(__name__)

# ── Token budget constants (§3.4) ─────────────────────────────────────────

# Default per-step token budget (§3.4 default ceiling)
_DEFAULT_STEP_TOKEN_BUDGET = 4000

# ── L2 context injection token limit (§3.3.2) ─────────────────────────────

# Max tokens for injected L2 context (Mem0 + upstream). Truncation priority:
#   upstream context > Mem0 > skill graph
_L2_CONTEXT_TOKEN_LIMIT = 800
_CHARS_PER_TOKEN = 4  # rough 1 token ≈ 4 chars estimate

# ── Langfuse alerting threshold (§3.4) ────────────────────────────────────

# Alert when a single step uses more than this many tokens
_TOKEN_ALERT_THRESHOLD = 3000


def _count_tokens_approx(text: str) -> int:
    """Approximate token count: 1 token ≈ 4 characters."""
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Source markers (§8.3, §10.42) ────────────────────────────────────────

import re as _re

_URL_PATTERN = _re.compile(
    r'(?<!\[EXT:)'   # not already marked
    r'(https?://[^\s\]\)>]{8,})',  # bare URL
)

# Canonical L1/L2 agent names (§1.1) — used for [INT:] source marker tagging.
# Legacy role names kept for backward compatibility with older agent outputs
# that may still reference them.
_INTERNAL_AGENTS = {
    # L1 scene agents
    "copilot", "instructor", "navigator", "autopilot",
    # L2 execution agents
    "researcher", "writer", "reviewer", "publisher",
    "engineer", "admin",
    # Legacy names (pre-6th-draft) — kept for output marker compatibility
    "counsel", "scholar", "artificer", "scribe",
    "arbiter", "envoy", "steward",
    # Legacy L1 scene names — kept for output marker compatibility
    "mentor", "coach", "operator",
}

_AGENT_MENTION_PATTERN = _re.compile(
    r'(?<!\[INT:)(?<!\[EXT:)'
    r'\b(' + '|'.join(_INTERNAL_AGENTS) + r')\b',
    _re.IGNORECASE,
)


def _apply_source_markers(text: str) -> str:
    """Post-process step output to add source markers (§8.3).

    - External URLs: [EXT:url]
    - Internal agent/persona references: [INT:persona]

    Idempotent: already-marked references are not double-marked.
    """
    if not text:
        return text

    # Mark external URLs
    def _mark_url(m: _re.Match) -> str:
        url = m.group(1)
        return f"[EXT:{url}]"

    result = _URL_PATTERN.sub(_mark_url, text)

    # Mark internal agent references (only first occurrence of each)
    marked_agents: set[str] = set()

    def _mark_agent(m: _re.Match) -> str:
        agent = m.group(1).lower()
        if agent in marked_agents:
            return m.group(0)  # skip duplicates
        marked_agents.add(agent)
        return f"[INT:{agent}]"

    result = _AGENT_MENTION_PATTERN.sub(_mark_agent, result)

    return result


async def _assemble_job_context(self, job_id: str, plan: dict) -> dict:
    """Assemble structured context for first Job DAG execution (§3.6, §3.6.1).

    Gathers:
      - Plane Issue description (from task)
      - Mem0 planning experience
      - Project-level context (goal + completed task summaries) if applicable
      - Prior Job artifact chain (§3.7.1)
    """
    context: dict = {}
    store = getattr(self, "_store", None)
    if not store:
        return context

    try:
        job_uuid = UUID(job_id)
        job = await store.get_job(job_uuid)
        if not job:
            return context

        task_id = job.get("task_id")
        if task_id:
            task = await store.get_task(task_id)
            if task:
                # Plane Issue description
                if task.get("title"):
                    context["task_title"] = str(task["title"])
                if task.get("dag"):
                    dag = task["dag"] if isinstance(task["dag"], dict) else {}
                    if dag.get("description"):
                        context["task_description"] = str(dag["description"])[:2000]

                # Project-level context (§3.6.1)
                project_id = task.get("project_id")
                if project_id:
                    project_goal = await store.get_project_goal(project_id)
                    if project_goal:
                        context["project_goal"] = project_goal

                    completed = await store.get_completed_tasks_for_project(project_id)
                    if completed:
                        context["completed_task_summaries"] = [
                            {"title": str(t.get("title") or ""), "task_id": str(t["task_id"])}
                            for t in completed[:10]
                        ]

                # Prior Job artifact chain (§3.7.1)
                prior_artifact = await store.get_last_final_artifact_for_task(task_id)
                if prior_artifact:
                    context["prior_job_artifact"] = {
                        "title": str(prior_artifact.get("title") or ""),
                        "summary": str(prior_artifact.get("summary") or "")[:1000],
                        "artifact_type": str(prior_artifact.get("artifact_type") or ""),
                        "minio_path": str(prior_artifact.get("minio_path") or ""),
                    }

        # Mem0 planning experience
        mem0 = getattr(self, "_mem0", None)
        if mem0:
            try:
                planning_ctx = retrieve_agent_context(mem0, "copilot", limit=3)
                if planning_ctx:
                    context["planning_experience"] = planning_ctx
            except Exception:
                pass

        # RAGFlow knowledge retrieval (§5.6): search for relevant chunks
        ragflow = getattr(self, "_ragflow", None)
        if ragflow:
            try:
                query_parts = []
                if context.get("task_title"):
                    query_parts.append(context["task_title"])
                if context.get("task_description"):
                    query_parts.append(context["task_description"][:200])
                query = " ".join(query_parts).strip()
                if query:
                    rf_result = await ragflow.search(query, top_k=5)
                    chunks = rf_result.get("chunks") or []
                    if chunks:
                        context["knowledge_chunks"] = [
                            {
                                "content": str(c.get("content") or c.get("text") or "")[:1000],
                                "score": float(c.get("similarity") or c.get("score") or 0),
                                "source": str(c.get("document_name") or c.get("source") or ""),
                            }
                            for c in chunks
                            if isinstance(c, dict)
                        ]
            except Exception as exc:
                _exec_logger.debug("RAGFlow search failed (non-fatal): %s", exc)

    except Exception as exc:
        _exec_logger.debug("Job context assembly partial failure: %s", exc)

    return context


def _apply_reviewer_trigger(step: dict, result: dict) -> dict:
    """Apply 3-tier reviewer trigger strategy (§3.8.1).

    Tier 1: NeMo output rail on all Steps (already done in validate_output)
    Tier 2: requires_review steps → mark for reviewer
    Tier 3: publish-type steps → mandatory reviewer

    Modifies result dict in-place with reviewer metadata.
    """
    if result.get("status") != "completed":
        return result

    step_type = str(step.get("type") or step.get("step_type") or "").lower()
    agent_id = str(step.get("agent_id") or step.get("agent") or "").lower()

    # Tier 3: publish steps → mandatory review
    if step_type == "publish" or agent_id == "publisher":
        result["requires_review"] = True
        result["review_tier"] = "mandatory"
        result["review_reason"] = "publish step requires mandatory review"
        return result

    # Tier 2: explicit requires_review
    if step.get("requires_review"):
        result["requires_review"] = True
        result["review_tier"] = "flagged"
        result["review_reason"] = "step marked requires_review"
        return result

    # Tier 1: NeMo output rail already applied (no additional marking needed)
    return result


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

    # ── Model hint override (§1.4.3) ──────────────────────────────
    model_hint = step.get("model_hint") or step.get("model") or None

    # ── Knowledge hierarchy (§1.5): guardrails run FIRST on raw goal ──
    # Priority: guardrails always win. Validate the goal before spending any
    # effort on context assembly or Mem0 retrieval. If guardrails block the
    # goal, fail immediately — Mem0 context cannot override guardrails.
    _goal_filtered, _goal_warnings = validate_input(goal)
    if _goal_warnings:
        activity.logger.info("Guardrails pre-check warnings for step %s: %s", step_id, _goal_warnings)
    if not _goal_filtered:
        _block_result = {
            "status": "failed",
            "step_id": step_id,
            "step_index": step_index,
            "agent_id": agent_id,
            "error": f"Goal blocked by guardrails: {'; '.join(_goal_warnings)}",
        }
        await _emit("failed", error=_block_result["error"])
        return _block_result
    # Use the guardrail-cleaned goal going forward
    goal = _goal_filtered

    # Build composed message with brief context
    context_payload: dict = {}
    brief = plan.get("brief")
    if isinstance(brief, dict):
        context_payload["brief"] = brief
    task_title = str(plan.get("task_title") or plan.get("title") or "")
    if task_title:
        context_payload["task_title"] = task_title

    # ── Job-level context assembly (§3.6, §3.6.1, §3.7.1) ──────
    job_context = await _assemble_job_context(self, job_id, plan)
    if job_context:
        context_payload["job_context"] = job_context

    # ── Mem0 + upstream context: inject with ≤800 token cap (§3.3.2) ──
    # Truncation priority: upstream context > Mem0 > skill graph.
    # NOTE: Mem0 retrieval runs AFTER guardrails pre-check (§1.5).
    # Guardrails always win — if the goal was blocked above, we never reach
    # this point. Mem0 context is supplementary and lower priority than
    # guardrails. Conflicts are resolved by guardrails at compose time below.
    _l2_token_budget = _L2_CONTEXT_TOKEN_LIMIT  # 800 tokens remaining

    # 1. Upstream step context (highest priority within L2 budget)
    # Include artifact presigned URL when available so agents can fetch full output.
    upstream = plan.get("_step_results")
    if isinstance(upstream, list) and upstream:
        _upstream_items = [
            {
                "step_id": str(r.get("step_id") or ""),
                "agent_id": str(r.get("agent_id") or ""),
                "output": str(r.get("output") or "")[:2000],
                **(
                    {"artifact_url": str(r["artifact_presigned_url"])}
                    if r.get("artifact_presigned_url")
                    else {}
                ),
            }
            for r in upstream
            if isinstance(r, dict) and str(r.get("status") or "") == "completed"
        ][:10]
        if _upstream_items:
            _upstream_text = json.dumps(_upstream_items, ensure_ascii=False)
            _upstream_tokens = _count_tokens_approx(_upstream_text)
            if _upstream_tokens > _l2_token_budget:
                # Truncate each output proportionally
                _chars_each = max(100, (_l2_token_budget * _CHARS_PER_TOKEN) // max(1, len(_upstream_items)))
                _upstream_items = [
                    {**item, "output": item["output"][:_chars_each]}
                    for item in _upstream_items
                ]
                _exec_logger.debug(
                    "Upstream context truncated to %d chars/item to fit ≤800 token budget",
                    _chars_each,
                )
            _l2_token_budget -= min(_upstream_tokens, _l2_token_budget)
            context_payload["upstream_steps"] = _upstream_items

    # 2. Mem0: agent memory + user preferences (second priority)
    mem0 = getattr(self, "_mem0", None)
    agent_memory = retrieve_agent_context(mem0, agent_id, limit=5)
    user_prefs = retrieve_user_preferences(mem0, limit=3)
    _mem0_text = (str(agent_memory or "") + " " + str(user_prefs or "")).strip()
    _mem0_tokens = _count_tokens_approx(_mem0_text) if _mem0_text else 0
    if _mem0_tokens <= _l2_token_budget:
        if agent_memory:
            context_payload["agent_memory"] = agent_memory
        if user_prefs:
            context_payload["user_preferences"] = user_prefs
        _l2_token_budget -= _mem0_tokens
    else:
        # Truncate to fit budget
        _mem0_max_chars = _l2_token_budget * _CHARS_PER_TOKEN
        if agent_memory:
            _am_text = str(agent_memory)
            context_payload["agent_memory"] = _am_text[:_mem0_max_chars]
        _l2_token_budget = 0
        _exec_logger.debug("Mem0 context truncated to fit ≤800 token L2 budget")

    # 3. Skill Graph (lowest priority, injected only if budget allows)
    #
    # NOTE (§0.11): Per-scene SOUL.md and per-agent SKILL.md files are loaded
    # by OpenClaw automatically at session spawn time — the Python layer does
    # NOT need to read or inject them. OC handles SOUL.md → system prompt and
    # SKILL.md → tool/knowledge injection. The Python layer is responsible only
    # for the SKILL_GRAPH.md neighbor hint injected here.
    import os as _os
    from pathlib import Path as _Path
    _oc_home = _Path(_os.environ.get("OPENCLAW_HOME", ""))
    _skill_graph_path = _oc_home / "workspace" / agent_id / "SKILL_GRAPH.md"
    if _skill_graph_path.exists() and _l2_token_budget > 50:
        try:
            _skill_graph_text = _skill_graph_path.read_text(encoding="utf-8")
            # Extract step skill from goal or step label for neighbor matching
            _current_skill = str(step.get("skill") or step.get("type") or "").strip()
            # Parse edges to find neighbors of the current skill
            _neighbors: list[str] = []
            for _line in _skill_graph_text.splitlines():
                _line_stripped = _line.strip()
                # Edge lines: "skill_a → skill_b (reason)"
                if "→" in _line_stripped and _current_skill:
                    _parts = _line_stripped.split("→")
                    if len(_parts) >= 2:
                        _from = _parts[0].strip().split()[-1] if _parts[0].strip() else ""
                        _to = _parts[1].strip().split("(")[0].strip()
                        if _from == _current_skill:
                            _neighbors.append(_to)
                        elif _to == _current_skill:
                            _neighbors.append(_from)
            # Fit skill graph into remaining budget
            _sg_max_chars = _l2_token_budget * _CHARS_PER_TOKEN
            context_payload["skill_graph"] = {
                "current_skill": _current_skill or None,
                "neighbors": _neighbors,
                "full": _skill_graph_text[:min(1500, _sg_max_chars)],
            }
        except Exception as _sg_exc:
            _exec_logger.debug("Skill graph injection failed: %s", _sg_exc)

    # ── Token budget declaration in goal (§3.4) ───────────────────
    # Inject the per-step token budget so the agent knows its ceiling.
    _step_token_budget = int(
        step.get("token_budget") or plan.get("step_token_budget") or _DEFAULT_STEP_TOKEN_BUDGET
    )
    _goal_with_budget = (
        f"{goal}\n\n[Token budget for this step: {_step_token_budget} tokens]"
    )

    composed_message = (
        f"{_goal_with_budget}\n\n{json.dumps(context_payload, ensure_ascii=False)}"
        if context_payload
        else _goal_with_budget
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
    # Session key: {agent_id}:{job_id}:{step_id} (§3.3.2)
    spawn_label = f"{agent_id}:{job_id}:{step_id}"
    spawn_kwargs: dict = {
        "label": spawn_label,
        "timeout_s": timeout_s,
        "cleanup": "delete",
    }
    # Pass model_hint to OC spawn if set (§1.4.3)
    if model_hint:
        spawn_kwargs["model"] = str(model_hint)
    spawn_future = asyncio.get_running_loop().run_in_executor(
        None,
        lambda: self._openclaw.spawn_session(
            agent_id, composed_message, **spawn_kwargs,
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
                # ── Per-Job quota check during heartbeat (§5.8) ──
                _hb_quota = getattr(self, "_quota", None)
                if _hb_quota:
                    try:
                        _qr = await _hb_quota.check_quota(job_id)
                        if not _qr.get("allowed"):
                            raise RuntimeError(
                                f"Quota exceeded: {_qr.get('reason', 'unknown')}"
                            )
                    except RuntimeError:
                        raise
                    except Exception:
                        pass  # quota check failure is non-fatal
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

    # ── Source markers (§8.3, §10.42) ─────────────────────────────
    if reply:
        reply = _apply_source_markers(reply)

    # ── Quota: record token usage (§5.8) ──────────────────────────
    _token_count = resp.get("token_count") or resp.get("usage", {}).get("total_tokens") or 0
    if _token_count:
        _quota_mgr = getattr(self, "_quota", None)
        if _quota_mgr:
            try:
                await _quota_mgr.record_usage(job_id, int(_token_count), step_id=step_id)
            except Exception as _qexc:
                activity.logger.debug("Quota record failed: %s", _qexc)

    # ── Langfuse alerting: emit alert if token usage exceeds threshold (§3.4) ─
    if _token_count and int(_token_count) > _TOKEN_ALERT_THRESHOLD:
        _alert_msg = (
            f"Step {step_id} (agent={agent_id}, job={job_id}) used "
            f"{_token_count} tokens, exceeding threshold {_TOKEN_ALERT_THRESHOLD}"
        )
        activity.logger.warning("TOKEN_ALERT: %s", _alert_msg)
        try:
            await self._event_bus.publish("alert_events", "token_threshold_exceeded", {
                "job_id": job_id,
                "step_id": step_id,
                "agent_id": agent_id,
                "token_count": int(_token_count),
                "threshold": _TOKEN_ALERT_THRESHOLD,
                "alert": _alert_msg,
                "utc": _utc(),
            })
        except Exception as _alert_exc:
            activity.logger.debug("Token alert event publish failed: %s", _alert_exc)

    result = {
        "status": "completed",
        "step_id": step_id,
        "step_index": step_index,
        "agent_id": agent_id,
        "output": reply[:10000] if reply else "",
    }

    # ── MinIO artifact storage (§3.7.1) ──────────────────────────
    # If the step produces non-trivial output, store it as a MinIO artifact.
    # Subsequent steps receive a presigned URL in their upstream_steps context.
    if reply and len(reply) > 200:
        _minio = getattr(self, "_minio", None)
        if _minio:
            try:
                import uuid as _uuid_mod
                _artifact_path = f"{job_id}/{step_id}/output.txt"
                _artifact_bytes = reply.encode("utf-8")
                _minio.upload_bytes(_artifact_path, _artifact_bytes, content_type="text/plain")
                _presigned_url = _minio.presigned_url(_artifact_path, expires_hours=24)
                result["artifact_minio_path"] = _artifact_path
                result["artifact_presigned_url"] = _presigned_url
                activity.logger.info(
                    "Step %s artifact stored at %s", step_id, _artifact_path
                )
            except Exception as _minio_exc:
                activity.logger.debug("MinIO artifact upload failed: %s", _minio_exc)

    # ── Reviewer trigger strategy (§3.8.1, 3 tiers) ──────────────
    result = _apply_reviewer_trigger(step, result)

    # ── Langfuse: finalize trace ──────────────────────────────────
    if lf_trace:
        try:
            lf_trace.update(output={
                "status": "completed",
                "output_len": len(reply),
                "token_count": _token_count,
                "artifact_path": result.get("artifact_minio_path"),
            })
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

    # ── Langfuse: create trace for CC/Codex step (§10.43) ────────
    lf_trace_cc = None
    langfuse = getattr(self, "_langfuse", None)
    if langfuse:
        try:
            lf_trace_cc = langfuse.trace(
                name=f"cc_step:{step_id}",
                metadata={
                    "job_id": job_id, "agent_id": agent_id,
                    "execution_type": execution_type, "step_index": step_index,
                },
                input={"goal": goal[:500]},
            )
        except Exception:
            pass

    # Inject Mem0 context
    mem0 = getattr(self, "_mem0", None)
    agent_memory = retrieve_agent_context(mem0, agent_id, limit=5)
    user_prefs = retrieve_user_preferences(mem0, limit=3)

    context_parts = [goal]
    if agent_memory:
        context_parts.append(f"\n{agent_memory}")
    if user_prefs:
        context_parts.append(f"\n{user_prefs}")

    # Inject MEMORY.md if it exists — validate ≤300 tokens (§3.3.3)
    import os
    from pathlib import Path
    oc_home = Path(os.environ.get("OPENCLAW_HOME", "")) / "workspace" / agent_id / "MEMORY.md"
    if oc_home.exists():
        try:
            memory_text = oc_home.read_text(encoding="utf-8")
            # Approximate token count: 1 token ≈ 4 characters (rough estimate)
            _MAX_MEMORY_TOKENS = 300
            _CHARS_PER_TOKEN = 4
            _max_chars = _MAX_MEMORY_TOKENS * _CHARS_PER_TOKEN
            if len(memory_text) > _max_chars:
                _exec_logger.warning(
                    "MEMORY.md for agent %s exceeds 300 tokens (~%d chars), "
                    "truncating to %d chars (§3.3.3)",
                    agent_id, len(memory_text), _max_chars,
                )
                memory_text = memory_text[:_max_chars]
            context_parts.append(f"\n[MEMORY.md]\n{memory_text}")
        except Exception:
            pass

    prompt = "\n".join(context_parts)

    # ── Handoff context files (§3.12): generate CLAUDE.md for CC/Codex ──
    import tempfile
    handoff_dir = None
    try:
        # Assemble context for handoff file
        job_context = await _assemble_job_context(self, job_id, plan)
        handoff_parts = ["# Handoff Context\n"]
        if job_context.get("task_title"):
            handoff_parts.append(f"## Task: {job_context['task_title']}\n")
        if job_context.get("task_description"):
            handoff_parts.append(f"## Description\n{job_context['task_description']}\n")
        if job_context.get("prior_job_artifact"):
            art = job_context["prior_job_artifact"]
            handoff_parts.append(
                f"## Prior Artifact\n- Title: {art.get('title', '')}\n"
                f"- Summary: {art.get('summary', '')[:500]}\n"
            )
        if job_context.get("project_goal"):
            handoff_parts.append(f"## Project Goal\n{job_context['project_goal']}\n")
        if job_context.get("completed_task_summaries"):
            handoff_parts.append("## Completed Tasks\n")
            for ts in job_context["completed_task_summaries"]:
                handoff_parts.append(f"- {ts.get('title', '')}\n")

        # Upstream step results
        upstream = plan.get("_step_results")
        if isinstance(upstream, list) and upstream:
            handoff_parts.append("## Upstream Step Results\n")
            for r in upstream[:5]:
                if isinstance(r, dict) and str(r.get("status") or "") == "completed":
                    handoff_parts.append(
                        f"- Step {r.get('step_id', '?')}: {str(r.get('output', ''))[:500]}\n"
                    )

        handoff_content = "\n".join(handoff_parts)

        if len(handoff_content) > 50:  # Only write if there's meaningful content
            handoff_dir = tempfile.mkdtemp(prefix="daemon_handoff_")
            # CLAUDE.md: read by `claude` CLI automatically (§3.12)
            claude_md_path = os.path.join(handoff_dir, "CLAUDE.md")
            with open(claude_md_path, "w", encoding="utf-8") as f:
                f.write(handoff_content)
            # AGENTS.md: read by `codex` CLI automatically (§3.12)
            agents_md_path = os.path.join(handoff_dir, "AGENTS.md")
            with open(agents_md_path, "w", encoding="utf-8") as f:
                f.write(handoff_content)
    except Exception as exc:
        _exec_logger.debug("Handoff context generation failed: %s", exc)

    # Find CLI binary
    def _find_cli(name: str) -> str | None:
        import shutil
        return shutil.which(name)

    # Model hint override (§1.4.3)
    model_hint = step.get("model_hint") or step.get("model") or None

    if execution_type == "claude_code":
        cli = _find_cli("claude")
        if not cli:
            return {"status": "failed", "step_id": step_id, "step_index": step_index,
                    "error": "'claude' CLI not found in PATH"}
        cmd = [cli, "--print", "--output-format", "text"]
        if model_hint:
            cmd.extend(["--model", str(model_hint)])
        cmd.append(prompt)
    else:  # codex
        cli = _find_cli("codex")
        if not cli:
            return {"status": "failed", "step_id": step_id, "step_index": step_index,
                    "error": "'codex' CLI not found in PATH"}
        cmd = [cli, "--quiet", "--approval-mode", "auto-edit"]
        if model_hint:
            cmd.extend(["--model", str(model_hint)])
        cmd.append(prompt)

    # Run CLI in subprocess with heartbeats
    loop = asyncio.get_running_loop()
    # Use handoff dir as cwd if available (§3.12), otherwise DAEMON_HOME
    cwd_path = handoff_dir if handoff_dir else str(Path(os.environ.get("DAEMON_HOME", ".")).resolve())

    def _run_cli():
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout_s,
            cwd=cwd_path,
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
        if lf_trace_cc:
            try:
                lf_trace_cc.update(output={"status": "failed", "error": error_msg})
            except Exception:
                pass
        return {"status": "failed", "step_id": step_id, "step_index": step_index,
                "agent_id": agent_id, "error": error_msg}

    output = (stdout or "").strip()
    if returncode != 0 and not output:
        output = (stderr or "").strip()

    if returncode != 0:
        _cc_err = f"CLI exited with code {returncode}: {output[:500]}"
        await self._event_bus.publish("step_events", "step_failed", {
            "job_id": job_id, "step_id": step_id, "error": f"exit_code={returncode}",
        })
        if lf_trace_cc:
            try:
                lf_trace_cc.update(output={"status": "failed", "error": _cc_err})
            except Exception:
                pass
        return {"status": "failed", "step_id": step_id, "step_index": step_index,
                "agent_id": agent_id, "error": _cc_err}

    # Guardrails: output validation
    cleaned_output, output_warnings = validate_output(output)
    if output_warnings:
        activity.logger.info("Guardrails output warnings for cc step %s: %s", step_id, output_warnings)

    # ── Source markers (§8.3, §10.42) ─────────────────────────────
    cleaned_output = _apply_source_markers(cleaned_output)

    # Cleanup handoff dir (§3.12)
    if handoff_dir:
        try:
            import shutil
            shutil.rmtree(handoff_dir, ignore_errors=True)
        except Exception:
            pass

    await self._event_bus.publish("step_events", "step_completed", {
        "job_id": job_id, "step_id": step_id, "execution_type": execution_type,
    })
    cc_result = {"status": "completed", "step_id": step_id, "step_index": step_index,
            "agent_id": agent_id, "output": cleaned_output[:10000]}

    # ── Reviewer trigger strategy (§3.8.1, 3 tiers) ──────────────
    cc_result = _apply_reviewer_trigger(step, cc_result)

    # ── Langfuse: finalize CC/Codex trace (§10.43) ───────────────
    if lf_trace_cc:
        try:
            lf_trace_cc.update(
                output={"status": "completed", "output_len": len(cleaned_output)}
            )
        except Exception:
            pass

    return cc_result


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
