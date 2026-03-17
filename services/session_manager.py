"""L1 Session Manager — persistent OC sessions for 4 scene agents.

Each scene (copilot, instructor, navigator, autopilot) has one persistent OC session
running in the API process. The daemon manages session compression when
context usage exceeds 70%.

4-layer conversation compression:
  Layer 1: conversation_messages (raw messages, PG)
  Layer 2: conversation_digests (time-range summaries, PG)
  Layer 3: conversation_decisions (key decisions, PG)
  Layer 4: Mem0 (long-term semantic memory)

Reference: SYSTEM_DESIGN.md §2.3, §5.1, TODO.md Phase 5.3
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from services.store import Store
from services.event_bus import EventBus

logger = logging.getLogger(__name__)

# The 4 L1 scene agents
L1_SCENES = ("copilot", "instructor", "navigator", "autopilot")

COMPRESSION_THRESHOLD = 0.70  # Trigger compression at 70% context usage


class SessionManager:
    """Manages persistent L1 OC sessions for all 4 scenes.

    Each session is an OC persistent full session. The SessionManager:
    - Creates sessions on startup
    - Routes user messages to the correct scene
    - Monitors context token usage
    - Triggers compression when threshold exceeded
    - Stores messages/digests/decisions in PG
    """

    def __init__(
        self,
        openclaw_adapter: Any,
        store: Store,
        event_bus: EventBus,
        mem0: Any | None = None,
        langfuse: Any | None = None,
    ) -> None:
        self._oc = openclaw_adapter
        self._store = store
        self._event_bus = event_bus
        self._mem0 = mem0
        self._langfuse = langfuse  # §10.43: Langfuse tracing for L1 session LLM calls
        self._sessions: dict[str, str] = {}  # scene -> session_key
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Initialize L1 sessions for all scenes."""
        if not self._oc:
            logger.warning("SessionManager: OpenClawAdapter unavailable, sessions disabled")
            return

        for scene in L1_SCENES:
            # OC session key format: agent:<agentId>:main (persistent full session)
            session_key = self._oc.main_session_key(scene)
            self._sessions[scene] = session_key
            logger.info("L1 session initialized: %s → %s", scene, session_key)

    async def stop(self) -> None:
        """Cleanup sessions."""
        self._sessions.clear()
        logger.info("SessionManager stopped")

    async def send_message(
        self, scene: str, content: str, *, timeout_s: int = 120,
        metadata: dict | None = None,
        task_id: str | None = None,
    ) -> dict:
        """Send a user message to a scene's L1 agent and return the response.

        Flow:
          1. Save user message to PG (with source metadata for §4.10 sync)
          2. Augment content with re-execution intent context if task_id supplied (§3.5)
          3. Send to OC session
          4. Save assistant response to PG
          5. Check context usage, trigger compression if needed
          6. Return response
        """
        if scene not in L1_SCENES:
            return {"ok": False, "error": f"unknown scene: {scene}"}

        session_key = self._sessions.get(scene)
        if not session_key or not self._oc:
            return {"ok": False, "error": "session not available"}

        # Save user message with source tracking (§4.10 Telegram ↔ desktop sync)
        source = (metadata or {}).get("source", "desktop")
        await self._store.save_message(scene, "user", content, source=source)

        # §3.5 Re-execution intent: if a task_id is provided (caller knows which task
        # this message is about), classify the intent and inject context for L1 routing.
        composed_content = content
        reexec_context: dict | None = None
        if task_id:
            intent_type = self._classify_reexecution_intent(content)
            try:
                from uuid import UUID
                t_uuid = UUID(task_id)
                jobs = await self._store.list_jobs_for_task(t_uuid)
                active_jobs = [
                    j for j in jobs
                    if str(j.get("status") or "") not in ("closed", "failed", "cancelled")
                ]
            except Exception:
                active_jobs = []

            reexec_context = {
                "task_id": task_id,
                "re_execution_intent": intent_type,
                "active_job_count": len(active_jobs),
                "active_job_ids": [str(j.get("job_id") or "") for j in active_jobs[:3]],
            }
            # Inject as a non-intrusive annotation at the end of the message
            import json as _json
            composed_content = (
                f"{content}\n\n"
                f"[ROUTING_CONTEXT: {_json.dumps(reexec_context, ensure_ascii=False)}]"
            )

        # §10.43: create Langfuse trace for this L1 session LLM call
        lf_trace = None
        if self._langfuse:
            try:
                lf_trace = self._langfuse.trace(
                    name=f"l1_session:{scene}",
                    metadata={"scene": scene, "source": source},
                    input={"content": composed_content[:500]},
                )
            except Exception:
                pass

        # Send to OC session
        try:
            resp = await asyncio.get_running_loop().run_in_executor(
                None, self._oc.send_to_session, session_key, composed_content, timeout_s,
            )
        except Exception as exc:
            logger.error("L1 session %s send failed: %s", scene, exc)
            if lf_trace:
                try:
                    lf_trace.update(output={"error": str(exc)[:200]})
                except Exception:
                    pass
            return {"ok": False, "error": str(exc)[:200]}

        reply = str(
            resp.get("reply") or resp.get("text") or resp.get("content") or ""
        ).strip()
        status = str(resp.get("status") or "").strip().lower()

        if status in {"error", "failed"}:
            if lf_trace:
                try:
                    lf_trace.update(output={"error": str(resp.get("error") or status)})
                except Exception:
                    pass
            return {
                "ok": False,
                "error": str(resp.get("error") or status),
            }

        if lf_trace:
            try:
                lf_trace.update(output={"reply": reply[:500]})
            except Exception:
                pass

        # Save assistant response
        await self._store.save_message(scene, "assistant", reply)

        # Check context usage and compress if needed
        context_tokens = resp.get("context_tokens") or resp.get("usage", {}).get("total_tokens")
        context_window = resp.get("context_window") or 128000
        if context_tokens and context_window:
            usage_ratio = int(context_tokens) / int(context_window)
            if usage_ratio >= COMPRESSION_THRESHOLD:
                asyncio.create_task(self._compress(scene))

        # Check for structured action (L1 → L2 dispatch)
        action = self._extract_action(reply)

        result: dict = {
            "ok": True,
            "scene": scene,
            "reply": reply,
            "action": action,
        }
        if reexec_context:
            result["reexec_context"] = reexec_context
        return result

    async def get_panel_data(self, scene: str) -> dict:
        """Get scene panel data: recent messages + active jobs."""
        if scene not in L1_SCENES:
            return {"error": f"unknown scene: {scene}"}

        messages = await self._store.get_recent_messages(scene, limit=20)
        digests = await self._store.get_recent_digests(scene, limit=5)
        decisions = await self._store.get_recent_decisions(scene, limit=10)

        return {
            "scene": scene,
            "messages": messages,
            "digests": digests,
            "decisions": decisions,
        }

    def _extract_action(self, reply: str) -> dict | None:
        """Extract structured routing decision from L1 reply (§3.1).

        L1 agents output routing decisions as JSON blocks:
          {"intent": "...", "route": "direct|task|project", ...}

        Schema validation ensures required fields are present.
        """
        import re

        # Look for JSON block in code fence
        pattern = r"```json\s*(\{[^`]*\})\s*```"
        match = re.search(pattern, reply, re.DOTALL)
        parsed = None
        if match:
            try:
                parsed = json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Also check for inline JSON at end of reply
        if not parsed:
            lines = reply.strip().split("\n")
            for line in reversed(lines[-5:]):
                line = line.strip()
                if line.startswith("{") and ('"route"' in line or '"action"' in line):
                    try:
                        parsed = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        pass

        if not parsed:
            return None

        return self._validate_routing_decision(parsed)

    def _validate_routing_decision(self, raw: dict) -> dict | None:
        """Validate routing decision against the §3.1 schema.

        Required fields:
          - intent: str (user's actual intent)
          - route: "direct" | "task" | "project"

        Optional fields:
          - model: "fast" | "analysis" | "creative" (model hint)
          - task: str (goal description for direct route)
          - tasks: list[dict] (DAG for project route)
          - agent_id: str (for direct route)
          - steps: list[dict] (for task route)
        """
        VALID_ROUTES = {"direct", "task", "project"}

        # Support legacy "action" field mapped to "route"
        if "action" in raw and "route" not in raw:
            action = raw["action"]
            if action == "create_job":
                raw["route"] = "task"
            elif action == "direct_response":
                raw["route"] = "direct"
            else:
                raw["route"] = action

        route = str(raw.get("route") or "").strip().lower()
        if route not in VALID_ROUTES:
            logger.warning("Invalid route in routing decision: %s", route)
            return None

        intent = str(raw.get("intent") or raw.get("task") or raw.get("goal") or "")
        if not intent:
            # For legacy format or minimal decisions, derive intent from steps
            steps = raw.get("steps") or raw.get("tasks") or []
            if steps and isinstance(steps, list) and isinstance(steps[0], dict):
                intent = str(steps[0].get("goal") or steps[0].get("task") or "task execution")
            else:
                intent = route  # Fallback: use route name as intent

        result: dict = {
            "intent": intent,
            "route": route,
        }

        # Optional model hint
        model = raw.get("model")
        if model and str(model) in ("fast", "analysis", "creative"):
            result["model"] = str(model)

        # Route-specific fields
        if route == "direct":
            result["agent_id"] = str(raw.get("agent_id") or raw.get("agent") or "")
            result["task"] = intent
        elif route == "task":
            steps = raw.get("steps") or []
            if isinstance(steps, list):
                result["steps"] = steps
        elif route == "project":
            tasks = raw.get("tasks") or []
            if isinstance(tasks, list):
                result["tasks"] = tasks

        return result

    def _classify_reexecution_intent(self, message: str) -> str:
        """Classify re-execution intent when a Task already has a Job (§3.5).

        Returns one of:
          - 'denial': user is rejecting/cancelling previous result
          - 'exploration': user wants to explore alternative approaches
          - 'refinement': user wants to refine/improve the existing result

        Uses simple keyword heuristics. L1 agent can override this classification
        in its routing decision.
        """
        msg = message.lower().strip()

        # Denial keywords — user rejects previous work
        denial_kw = [
            "不要", "取消", "撤回", "不对", "错了", "重来", "废弃",
            "cancel", "reject", "wrong", "undo", "discard", "scrap", "no good",
            "不行", "不满意", "重新做",
        ]
        for kw in denial_kw:
            if kw in msg:
                return "denial"

        # Exploration keywords — user wants alternatives
        exploration_kw = [
            "另一个", "其他方案", "换个", "试试", "有没有别的", "alternative",
            "different approach", "another way", "what if", "explore",
            "换一种", "也许可以",
        ]
        for kw in exploration_kw:
            if kw in msg:
                return "exploration"

        # Default: refinement — user wants to improve existing result
        return "refinement"

    async def ask_l1_failure_judgment(
        self, scene: str, step_info: dict, error: str,
    ) -> str:
        """After retries exhausted, ask L1 whether to skip/replace/terminate (§3.8).

        Returns one of: 'skip', 'replace', 'terminate'.
        Falls back to 'terminate' on any error.
        """
        if not self._oc:
            return "terminate"

        prompt = (
            "A Step in your current Job has failed after all retries.\n\n"
            f"Step: {step_info.get('goal', 'unknown')[:200]}\n"
            f"Agent: {step_info.get('agent_id', 'unknown')}\n"
            f"Error: {error[:300]}\n\n"
            "What should we do? Respond with exactly one word:\n"
            "- skip: skip this step and continue with remaining steps\n"
            "- replace: replace with an alternative approach\n"
            "- terminate: stop the entire Job\n"
        )

        try:
            # Try local LLM first (simple classification task)
            reply = ""
            try:
                from services.llm_local import generate, resolve_task_model
                alias = resolve_task_model("l1_failure_judgment")
                reply = await generate(alias, prompt, temperature=0.0, max_tokens=16, timeout_s=15)
                reply = reply.strip().lower()
            except Exception as local_exc:
                logger.debug("L1 failure judgment local LLM unavailable: %s", local_exc)

            if not reply:
                session_key = self._sessions.get(scene)
                if not session_key:
                    session_key = self._sessions.get("copilot", "")
                if not session_key:
                    return "terminate"
                import asyncio
                resp = await asyncio.get_running_loop().run_in_executor(
                    None, self._oc.send_to_session, session_key, prompt, 30,
                )
                reply = str(resp.get("reply") or resp.get("text") or "").strip().lower()

            for choice in ("skip", "replace", "terminate"):
                if choice in reply:
                    return choice

            return "terminate"
        except Exception as exc:
            logger.warning("L1 failure judgment failed: %s", exc)
            return "terminate"

    async def _compress(self, scene: str) -> None:
        """Trigger 4-layer compression for a scene.

        Layer 1→2: Recent messages → digest (time-range summary)
        Layer 2→3: Old digests → decisions (key decision extractions)
        Layer 3→4: Old decisions → Mem0 (long-term semantic memory)
        """
        async with self._lock:
            try:
                await self._compress_messages_to_digest(scene)
                await self._compress_digests_to_decisions(scene)
                await self._compress_decisions_to_mem0(scene)
                logger.info("Compression completed for scene %s", scene)
            except Exception as exc:
                logger.warning("Compression failed for scene %s: %s", scene, exc)

    async def _compress_messages_to_digest(self, scene: str) -> None:
        """Layer 1→2: Summarize oldest messages into a digest."""
        messages = await self._store.get_recent_messages(scene, limit=100)
        if len(messages) < 20:
            return

        # Take the oldest 50% of messages for compression
        to_compress = messages[: len(messages) // 2]
        if not to_compress:
            return

        # Build summary using OC (lightweight call)
        texts = []
        for msg in to_compress:
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "")[:500]
            texts.append(f"[{role}] {content}")

        summary_prompt = (
            "Summarize this conversation segment into a concise digest "
            "(2-3 paragraphs). Preserve key decisions, action items, and "
            "important context.\n\n" + "\n".join(texts[:20])
        )

        # Try local LLM first for compression (saves API tokens)
        summary = ""
        try:
            from services.llm_local import chat, resolve_task_model
            alias = resolve_task_model("session_compress")
            summary = await chat(
                alias,
                [{"role": "user", "content": summary_prompt}],
                temperature=0.1,
                max_tokens=1024,
                timeout_s=90,
            )
            summary = summary.strip()
        except Exception as local_exc:
            logger.debug("Compression local LLM unavailable: %s", local_exc)

        if not summary and self._oc:
            try:
                session_key = f"compress:{scene}:{int(time.time())}"
                resp = await asyncio.get_running_loop().run_in_executor(
                    None, self._oc.send_to_session, session_key, summary_prompt, 60,
                )
                summary = str(
                    resp.get("reply") or resp.get("text") or ""
                ).strip()
            except Exception as exc:
                logger.warning("Digest compression OC fallback failed for %s: %s", scene, exc)

        if summary:
            # §10.40: validate compression digest output through guardrails
            try:
                from config.guardrails.actions import validate_output
                summary, digest_warnings = validate_output(summary)
                if digest_warnings:
                    logger.debug(
                        "Compression digest warnings for %s: %s", scene, digest_warnings
                    )
            except Exception as exc:
                logger.debug("Guardrails validation skipped for digest: %s", exc)

            if summary:
                from datetime import datetime
                start = datetime.fromisoformat(
                    str(to_compress[0].get("created_at") or "2026-01-01")
                    .replace("Z", "+00:00")
                )
                end = datetime.fromisoformat(
                    str(to_compress[-1].get("created_at") or "2026-01-01")
                    .replace("Z", "+00:00")
                )
                await self._store.save_digest(
                    scene, start, end, summary,
                    source_message_count=len(to_compress),
                )

    async def _compress_digests_to_decisions(self, scene: str) -> None:
        """Layer 2→3: Extract key decisions from old digests."""
        digests = await self._store.get_recent_digests(scene, limit=50)
        if len(digests) < 10:
            return

        # Take the oldest half
        to_compress = digests[: len(digests) // 2]

        texts = []
        for d in to_compress:
            summary = str(d.get("summary") or "")[:500]
            texts.append(summary)

        prompt = (
            "Extract key decisions, commitments, and action items from these "
            "conversation digests. Output each decision on its own line, prefixed "
            "with its type (DECISION / COMMITMENT / ACTION / PREFERENCE).\n\n"
            + "\n---\n".join(texts[:10])
        )

        # Try local LLM first for decision extraction
        output = ""
        try:
            from services.llm_local import chat, resolve_task_model
            alias = resolve_task_model("session_compress")
            output = await chat(
                alias,
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=1024,
                timeout_s=90,
            )
            output = output.strip()
        except Exception as local_exc:
            logger.debug("Decision extraction local LLM unavailable: %s", local_exc)

        if not output and self._oc:
            try:
                session_key = f"compress_d2d:{scene}:{int(time.time())}"
                resp = await asyncio.get_running_loop().run_in_executor(
                    None, self._oc.send_to_session, session_key, prompt, 60,
                )
                output = str(resp.get("reply") or resp.get("text") or "").strip()
            except Exception as exc:
                logger.warning("Decision extraction OC fallback failed: %s", exc)

        if not output:
            return

        # §10.40: validate compression decision output through guardrails
        try:
            from config.guardrails.actions import validate_output
            output, decision_warnings = validate_output(output)
            if decision_warnings:
                logger.debug(
                    "Compression decision warnings for %s: %s", scene, decision_warnings
                )
        except Exception as exc:
            logger.debug("Guardrails validation skipped for decisions: %s", exc)
        if not output:
            return

        # Parse decisions (one per line)
        for line in output.strip().split("\n"):
            line = line.strip()
            if not line or len(line) < 5:
                continue
            # Detect decision type from prefix
            decision_type = "general"
            for dtype in ("DECISION", "COMMITMENT", "ACTION", "PREFERENCE"):
                if line.upper().startswith(dtype):
                    decision_type = dtype.lower()
                    line = line[len(dtype):].lstrip(":- ").strip()
                    break
            if line:
                await self._store.save_decision(
                    scene, decision_type, line,
                    context_summary=f"Extracted from {len(to_compress)} digests",
                )

    def _extract_feedback_candidates(self, messages: list[dict]) -> list[dict]:
        """Extract persona taste/feedback candidates from conversation (§5.4).

        Scans recent messages for feedback signals:
          - Explicit preferences ("I prefer...", "I like...", "don't...")
          - Style corrections ("make it more...", "too formal", "less...")
          - Quality judgments ("this is good", "not what I wanted")

        Returns list of candidate dicts:
          [{"type": "preference|correction|judgment", "content": str, "source_message": str}]

        These candidates are presented to the user for confirmation before
        being validated by NeMo and written to Mem0.
        """
        import re

        candidates: list[dict] = []

        PREFERENCE_PATTERNS = [
            re.compile(r'\b(?:I\s+(?:prefer|like|want|need|love))\b.*', re.IGNORECASE),
            re.compile(r"\b(?:don'?t|do\s+not|never|avoid|stop)\b.*", re.IGNORECASE),
            re.compile(r'\b(?:always|make\s+sure|remember\s+to)\b.*', re.IGNORECASE),
        ]
        CORRECTION_PATTERNS = [
            re.compile(r'\b(?:too\s+(?:formal|casual|long|short|verbose|brief))\b', re.IGNORECASE),
            re.compile(r'\b(?:make\s+it\s+(?:more|less))\b.*', re.IGNORECASE),
            re.compile(r'\b(?:should\s+be\s+(?:more|less))\b.*', re.IGNORECASE),
        ]
        JUDGMENT_PATTERNS = [
            re.compile(r'\b(?:(?:this|that|it)\s+is\s+(?:good|great|perfect|exactly))\b', re.IGNORECASE),
            re.compile(r'\b(?:not\s+(?:what|how)\s+I\s+(?:wanted|expected|meant))\b', re.IGNORECASE),
        ]

        for msg in messages:
            role = str(msg.get("role") or "")
            content = str(msg.get("content") or "")
            if role != "user" or len(content) < 10:
                continue

            sentences = re.split(r'[.!?。！？\n]+', content)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) < 8:
                    continue

                matched = False
                for pat in PREFERENCE_PATTERNS:
                    if pat.search(sentence):
                        candidates.append({
                            "type": "preference",
                            "content": sentence[:500],
                            "source_message": content[:200],
                        })
                        matched = True
                        break
                if matched:
                    continue

                for pat in CORRECTION_PATTERNS:
                    if pat.search(sentence):
                        candidates.append({
                            "type": "correction",
                            "content": sentence[:500],
                            "source_message": content[:200],
                        })
                        matched = True
                        break
                if matched:
                    continue

                for pat in JUDGMENT_PATTERNS:
                    if pat.search(sentence):
                        candidates.append({
                            "type": "judgment",
                            "content": sentence[:500],
                            "source_message": content[:200],
                        })
                        break

        # Deduplicate by content
        seen: set[str] = set()
        unique: list[dict] = []
        for c in candidates:
            key = c["content"].lower().strip()
            if key not in seen:
                seen.add(key)
                unique.append(c)

        return unique[:20]

    async def apply_confirmed_feedback(
        self, scene: str, feedback: list[dict]
    ) -> dict:
        """Write user-confirmed feedback to Mem0 after NeMo validation (§5.4).

        Called after user confirms feedback candidates extracted by
        _extract_feedback_candidates(). Each confirmed item is validated
        by NeMo guardrails before writing to Mem0.
        """
        if not self._mem0:
            return {"ok": False, "reason": "mem0_unavailable"}

        from config.guardrails.actions import validate_output

        written = 0
        for item in feedback:
            content = str(item.get("content") or "").strip()
            ftype = str(item.get("type") or "preference")
            if not content:
                continue

            cleaned, warnings = validate_output(content)
            if not cleaned:
                logger.info("Feedback blocked by NeMo: %s", warnings)
                continue

            try:
                self._mem0.add(
                    f"[{scene}:taste:{ftype}] {cleaned}",
                    user_id="user_persona",
                    metadata={
                        "scene": scene,
                        "feedback_type": ftype,
                        "source": "persona_taste_update",
                    },
                )
                written += 1
            except Exception as exc:
                logger.warning("Mem0 write failed for feedback: %s", exc)
                break

        logger.info(
            "Persona taste update: %d/%d items written for %s",
            written, len(feedback), scene,
        )
        return {"ok": True, "written": written, "total": len(feedback)}

    async def _compress_decisions_to_mem0(self, scene: str) -> None:
        """Layer 3→4: Push old decisions to Mem0 long-term memory."""
        if not self._mem0:
            return

        decisions = await self._store.get_recent_decisions(scene, limit=100)
        if len(decisions) < 20:
            return

        # Push the oldest half to Mem0
        to_archive = decisions[: len(decisions) // 2]

        for d in to_archive:
            content = str(d.get("content") or "")
            dtype = str(d.get("decision_type") or "general")
            if not content:
                continue
            try:
                self._mem0.add(
                    f"[{scene}:{dtype}] {content}",
                    user_id="user_persona",
                    metadata={"scene": scene, "decision_type": dtype, "source": "compression"},
                )
            except Exception as exc:
                logger.debug("Mem0 add failed for decision: %s", exc)
                break  # Stop on first failure to avoid flooding
