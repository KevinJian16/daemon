"""Voice Service — Counsel Agent conversation management."""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from psyche.instinct import InstinctPsyche


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class VoiceService:
    """Manages conversational sessions with the Counsel Agent via OpenClaw Gateway."""

    def __init__(self, instinct: "InstinctPsyche", openclaw_home: Path | None = None) -> None:
        self._instinct = instinct
        self._oc_home = openclaw_home
        self._oc_cfg: dict | None = None
        self._sessions: dict[str, dict] = {}
        if openclaw_home:
            cfg_path = openclaw_home / "openclaw.json"
            if cfg_path.exists():
                try:
                    self._oc_cfg = json.loads(cfg_path.read_text())
                except Exception as exc:
                    logger.warning("Failed to load openclaw config from %s: %s", cfg_path, exc)

    def new_session(self, user_id: str = "default") -> str:
        session_id = f"voice_{uuid.uuid4().hex[:10]}"
        self._sessions[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "created_utc": _utc(),
            "messages": [],
        }
        return session_id

    def chat(self, session_id: str, message: str) -> dict:
        """Send a message to the Counsel Agent and return its response."""
        if session_id not in self._sessions:
            return {"ok": False, "error": "session_not_found"}

        session = self._sessions[session_id]
        session["messages"].append({"role": "user", "content": message, "timestamp": _utc()})

        if not self._oc_cfg:
            return {"ok": False, "error": "OpenClaw not configured"}

        # Keep daemon-only fallback to avoid accidentally binding old MAS defaults.
        gw_port = self._oc_cfg.get("gateway", {}).get("port", 18790)
        gw_token = self._oc_cfg.get("gateway", {}).get("auth", {}).get("token", "")
        gw_url = f"http://127.0.0.1:{gw_port}"
        headers = {"Authorization": f"Bearer {gw_token}", "Content-Type": "application/json"}

        # Build session key for counsel.
        oc_session_key = f"agent:counsel:voice:{session_id}"

        try:
            resp = httpx.post(
                f"{gw_url}/tools/invoke",
                json={
                    "tool": "sessions_send",
                    "args": {"sessionKey": oc_session_key, "agentId": "counsel", "message": message},
                },
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            send_result = resp.json().get("result") or {}
            send_details = send_result.get("details") or {}
            send_status = str(send_details.get("status") or "").strip().lower()
            if send_status in {"error", "forbidden", "failed"}:
                err = str(send_details.get("error") or send_details.get("message") or send_status)
                return {"ok": False, "error": err}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

        # Poll for response (up to 60s for voice).
        deadline = time.time() + 60
        last_content = ""
        while time.time() < deadline:
            time.sleep(2)
            try:
                hist = httpx.post(
                    f"{gw_url}/tools/invoke",
                    json={"tool": "sessions_history", "args": {"sessionKey": oc_session_key, "limit": 1}},
                    headers=headers,
                    timeout=15,
                )
                hist.raise_for_status()
                data = hist.json()
                result = data.get("result") or {}
                details = result.get("details") or {}
                status = str(details.get("status") or "").strip().lower()
                if status in {"error", "forbidden", "failed"}:
                    continue
                messages = details.get("messages") or result.get("messages") or []
                latest = messages[-1] if messages else {}
                content = self._extract_message_text(latest)
                if latest.get("role") == "assistant" and content and content != last_content:
                    last_content = content
                    session["messages"].append({"role": "assistant", "content": content, "timestamp": _utc()})

                    # Check for plan extraction.
                    plan = self._extract_plan(content)
                    return {"ok": True, "content": content, "session_id": session_id, "plan": plan}
            except Exception as exc:
                logger.error("Voice chat error for session %s: %s", session_id, exc)

        return {"ok": False, "error": "voice_timeout", "session_id": session_id}

    def get_session(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)

    def _extract_plan(self, content: str) -> dict | None:
        """Try to extract a structured plan from Counsel response and validate convergence."""
        if "```json" not in content:
            return None
        try:
            start = content.index("```json") + 7
            end = content.index("```", start)
            raw = content[start:end].strip()
            plan = json.loads(raw)
            if not isinstance(plan, dict) or not plan.get("moves"):
                return None
            # Convergence validation: DAG must be valid before surfacing.
            valid, err = self._validate_plan_convergence(plan)
            if not valid:
                logger.info("Voice plan failed convergence: %s", err)
                plan["_convergence_error"] = err
            else:
                plan["_convergence_validated"] = True
            return plan
        except Exception as exc:
            logger.debug("_extract_plan: failed to parse JSON plan: %s", exc)
        return None

    @staticmethod
    def _validate_plan_convergence(plan: dict) -> tuple[bool, str]:
        """Validate plan DAG for convergence: no cycles, valid agents, terminal moves."""
        moves = plan.get("moves") or []
        if not isinstance(moves, list) or not moves:
            return False, "empty moves"
        valid_agents = {"scout", "sage", "artificer", "arbiter", "scribe", "envoy", "counsel", "spine"}
        ids: set[str] = set()
        for i, st in enumerate(moves):
            if not isinstance(st, dict):
                return False, f"move {i} not a dict"
            sid = str(st.get("id") or f"move_{i}")
            if sid in ids:
                return False, f"duplicate id: {sid}"
            ids.add(sid)
            agent = str(st.get("agent") or "")
            if agent and agent not in valid_agents:
                return False, f"unknown agent: {agent}"
            for dep in st.get("depends_on") or []:
                if dep not in ids:
                    return False, f"move {sid} depends on unknown {dep}"
        brief = plan.get("brief") or {}
        ration = int(brief.get("move_ration") or 999)
        if len(moves) > ration:
            return False, f"moves {len(moves)} > ration {ration}"
        terminal = [s for s in moves if not any(
            str(s.get("id") or "") in (other.get("depends_on") or [])
            for other in moves if other is not s
        )]
        if not terminal:
            return False, "no terminal moves (possible cycle)"
        return True, ""

    def _extract_message_text(self, msg: dict) -> str:
        raw = msg.get("content")
        if isinstance(raw, str):
            return raw
        if isinstance(raw, list):
            chunks = []
            for item in raw:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        chunks.append(text)
            if chunks:
                return "\n".join(chunks).strip()
        text = msg.get("text")
        if isinstance(text, str):
            return text
        err = msg.get("errorMessage")
        if isinstance(err, str):
            return err
        return ""
