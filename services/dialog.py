"""Dialog Service — Router Agent conversation management."""
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
    from fabric.compass import CompassFabric


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class DialogService:
    """Manages conversational sessions with the Router Agent via OpenClaw Gateway."""

    def __init__(self, compass: "CompassFabric", openclaw_home: Path | None = None) -> None:
        self._compass = compass
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
        session_id = f"dialog_{uuid.uuid4().hex[:10]}"
        self._sessions[session_id] = {
            "session_id": session_id,
            "user_id": user_id,
            "created_utc": _utc(),
            "messages": [],
        }
        return session_id

    def chat(self, session_id: str, message: str) -> dict:
        """Send a message to the Router Agent and return its response."""
        if session_id not in self._sessions:
            return {"ok": False, "error": "session_not_found"}

        session = self._sessions[session_id]
        session["messages"].append({"role": "user", "content": message, "timestamp": _utc()})

        if not self._oc_cfg:
            return {"ok": False, "error": "OpenClaw not configured"}

        gw_port = self._oc_cfg.get("gateway", {}).get("port", 18789)
        gw_token = self._oc_cfg.get("gateway", {}).get("auth", {}).get("token", "")
        gw_url = f"http://127.0.0.1:{gw_port}"
        headers = {"Authorization": f"Bearer {gw_token}", "Content-Type": "application/json"}

        # Build session key for router.
        oc_session_key = f"agent:router:dialog:{session_id}"

        try:
            resp = httpx.post(
                f"{gw_url}/tools/invoke",
                json={"tool": "sessions_send", "args": {"session_key": oc_session_key, "message": message}},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

        # Poll for response (up to 60s for dialog).
        deadline = time.time() + 60
        last_content = ""
        while time.time() < deadline:
            time.sleep(2)
            try:
                hist = httpx.post(
                    f"{gw_url}/tools/invoke",
                    json={"tool": "sessions_history", "args": {"session_key": oc_session_key, "limit": 1}},
                    headers=headers,
                    timeout=15,
                )
                hist.raise_for_status()
                data = hist.json()
                messages = (data.get("result") or {}).get("messages") or []
                latest = messages[-1] if messages else {}
                content = latest.get("content") or ""
                if latest.get("role") == "assistant" and content and content != last_content:
                    last_content = content
                    session["messages"].append({"role": "assistant", "content": content, "timestamp": _utc()})

                    # Check for plan extraction.
                    plan = self._extract_plan(content)
                    return {"ok": True, "content": content, "session_id": session_id, "plan": plan}
            except Exception as exc:
                logger.error("Dialog chat error for session %s: %s", session_id, exc)

        return {"ok": False, "error": "dialog_timeout", "session_id": session_id}

    def get_session(self, session_id: str) -> dict | None:
        return self._sessions.get(session_id)

    def _extract_plan(self, content: str) -> dict | None:
        """Try to extract a structured plan from Router response."""
        if "```json" not in content:
            return None
        try:
            start = content.index("```json") + 7
            end = content.index("```", start)
            raw = content[start:end].strip()
            plan = json.loads(raw)
            if isinstance(plan, dict) and plan.get("steps"):
                return plan
        except Exception as exc:
            logger.debug("_extract_plan: failed to parse JSON plan: %s", exc)
        return None
