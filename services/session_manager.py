"""L1 Session Manager — persistent OC sessions for 4 scene agents.

Each scene (copilot, mentor, coach, operator) has one persistent OC session
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
L1_SCENES = ("copilot", "mentor", "coach", "operator")

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
    ) -> None:
        self._oc = openclaw_adapter
        self._store = store
        self._event_bus = event_bus
        self._mem0 = mem0
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
        self, scene: str, content: str, *, timeout_s: int = 120
    ) -> dict:
        """Send a user message to a scene's L1 agent and return the response.

        Flow:
          1. Save user message to PG
          2. Send to OC session
          3. Save assistant response to PG
          4. Check context usage, trigger compression if needed
          5. Return response
        """
        if scene not in L1_SCENES:
            return {"ok": False, "error": f"unknown scene: {scene}"}

        session_key = self._sessions.get(scene)
        if not session_key or not self._oc:
            return {"ok": False, "error": "session not available"}

        # Save user message
        await self._store.save_message(scene, "user", content)

        # Send to OC session
        try:
            resp = await asyncio.get_running_loop().run_in_executor(
                None, self._oc.send_to_session, session_key, content, timeout_s,
            )
        except Exception as exc:
            logger.error("L1 session %s send failed: %s", scene, exc)
            return {"ok": False, "error": str(exc)[:200]}

        reply = str(
            resp.get("reply") or resp.get("text") or resp.get("content") or ""
        ).strip()
        status = str(resp.get("status") or "").strip().lower()

        if status in {"error", "failed"}:
            return {
                "ok": False,
                "error": str(resp.get("error") or status),
            }

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

        return {
            "ok": True,
            "scene": scene,
            "reply": reply,
            "action": action,
        }

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
        """Extract structured action from L1 reply if present.

        L1 agents can output structured actions like:
          {"action": "create_job", "steps": [...]}
          {"action": "direct_response"}

        These are embedded in the reply as JSON blocks.
        """
        # Look for JSON action block in reply
        import re
        pattern = r"```json\s*(\{[^`]*\"action\"[^`]*\})\s*```"
        match = re.search(pattern, reply, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass

        # Also check for inline JSON at end of reply
        lines = reply.strip().split("\n")
        for line in reversed(lines[-3:]):
            line = line.strip()
            if line.startswith("{") and '"action"' in line:
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    pass

        return None

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

        if self._oc:
            try:
                session_key = f"compress:{scene}:{int(time.time())}"
                resp = await asyncio.get_running_loop().run_in_executor(
                    None, self._oc.send_to_session, session_key, summary_prompt, 60,
                )
                summary = str(
                    resp.get("reply") or resp.get("text") or ""
                ).strip()

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
            except Exception as exc:
                logger.warning("Digest compression failed for %s: %s", scene, exc)

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

        if not self._oc:
            return

        try:
            session_key = f"compress_d2d:{scene}:{int(time.time())}"
            resp = await asyncio.get_running_loop().run_in_executor(
                None, self._oc.send_to_session, session_key, prompt, 60,
            )
            output = str(resp.get("reply") or resp.get("text") or "").strip()
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
        except Exception as exc:
            logger.warning("Digest→decision compression failed for %s: %s", scene, exc)

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
