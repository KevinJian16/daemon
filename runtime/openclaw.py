"""OpenClaw Gateway adapter — HTTP-based bridge to Agent sessions and file system."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx


logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class OpenClawError(Exception):
    pass


class OpenClawAdapter:
    """Single-channel HTTP adapter for OpenClaw Gateway.

    All Agent communication goes through the Gateway HTTP API using
    persistent full sessions (not subagent spawn).  Each pool instance
    uses its main session (`agent:<id>:main`) so MEMORY.md is loaded
    and memory tools are available.
    """

    def __init__(self, openclaw_home: Path) -> None:
        self._home = openclaw_home
        self._cfg: dict = {}
        self._gateway_url: str = ""
        self._token: str = ""
        self._load_config()

    def _load_config(self) -> None:
        cfg_path = self._home / "openclaw.json"
        if not cfg_path.exists():
            raise OpenClawError(f"openclaw.json not found at {cfg_path}")
        self._cfg = json.loads(cfg_path.read_text())
        # Keep daemon-only fallback to avoid accidentally binding old MAS defaults.
        port = self._cfg.get("gateway", {}).get("port", 18790)
        self._gateway_url = f"http://127.0.0.1:{port}"
        self._token = os.environ.get(
            "OPENCLAW_GATEWAY_TOKEN",
            self._cfg.get("gateway", {}).get("auth", {}).get("token", ""),
        )

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def health_check(self) -> str:
        """Returns 'ok' or an error string."""
        try:
            resp = httpx.get(f"{self._gateway_url}/health", headers=self._headers, timeout=5)
            return "ok" if resp.status_code < 300 else f"http_{resp.status_code}"
        except Exception as e:
            return f"error: {str(e)[:80]}"

    def main_session_key(self, agent_id: str) -> str:
        """Return the main session key for a pool instance.

        Format follows OC's buildAgentMainSessionKey: ``agent:<agentId>:main``.
        Full sessions auto-load MEMORY.md and have memory_search/memory_get available.
        """
        return f"agent:{agent_id}:main"

    def send_to_session(self, session_key: str, message: str, timeout_s: int = 300) -> dict:
        """Send a message to a persistent full session and wait for completion.

        Uses ``sessions_send`` with synchronous wait.  The target session must
        be a main session (not subagent) so MEMORY.md is loaded and memory
        tools are available.

        Returns the raw response dict including ``status`` and ``reply``.
        Raises OpenClawError on hard failures.
        """
        result = self._invoke(
            "sessions_send",
            {
                "sessionKey": session_key,
                "message": message,
                "timeoutSeconds": max(1, timeout_s),
            },
            timeout=timeout_s + 30,
        )
        details = self._extract_details(result)
        status = str(details.get("status") or "").strip().lower()
        if status in {"error", "forbidden", "failed"}:
            raise OpenClawError(
                f"sessions_send failed [{status}]: {details.get('error', 'unknown')}"
            )
        return details or result

    def history(self, session_key: str, limit: int = 1) -> list[dict]:
        """Read recent messages from an Agent session."""
        result = self._invoke("sessions_history", {"sessionKey": session_key, "limit": limit})
        details = self._extract_details(result)
        self._raise_on_status("sessions_history", details)
        rows = (details or {}).get("messages") or (result or {}).get("messages") or []
        if not isinstance(rows, list):
            return []
        return [self._normalize_message(m) for m in rows if isinstance(m, dict)]

    def session_status(self, session_key: str) -> dict:
        """Check session status via sessions_list, returns abortedLastRun and token counts."""
        try:
            result = self._invoke("sessions_list", {"sessionKey": session_key})
            details = self._extract_details(result)
            sessions = details.get("sessions") or result.get("sessions") or []
            if isinstance(sessions, list):
                for s in sessions:
                    if not isinstance(s, dict):
                        continue
                    sk = str(s.get("sessionKey") or s.get("key") or "")
                    if sk == session_key or not sk:
                        return {
                            "abortedLastRun": bool(s.get("abortedLastRun")),
                            "contextTokens": int(s.get("contextTokens") or 0),
                            "totalTokens": int(s.get("totalTokens") or 0),
                        }
            return {"abortedLastRun": False, "contextTokens": 0, "totalTokens": 0}
        except Exception as exc:
            logger.warning("session_status check failed for %s: %s", session_key, exc)
            return {"abortedLastRun": False, "contextTokens": 0, "totalTokens": 0, "error": str(exc)[:100]}

    def spawn_session(
        self,
        agent_id: str,
        task: str,
        *,
        label: str = "",
        timeout_s: int = 300,
        cleanup: str = "delete",
    ) -> dict:
        """Spawn an isolated session for an agent (L2 step execution).

        Uses sessions_spawn (non-blocking) then polls session history for completion.
        This is the correct mechanism for 1 Step = 1 Session.

        Returns dict with keys: status, reply, runId, childSessionKey.
        """
        args: dict[str, Any] = {
            "task": task,
            "agentId": agent_id,
            "cleanup": cleanup,
        }
        if label:
            args["label"] = label
        if timeout_s > 0:
            args["runTimeoutSeconds"] = timeout_s

        result = self._invoke("sessions_spawn", args, timeout=timeout_s + 30)
        details = self._extract_details(result)

        run_id = str(details.get("runId") or result.get("runId") or "")
        child_key = str(details.get("childSessionKey") or result.get("childSessionKey") or "")

        if not run_id:
            raise OpenClawError(
                f"sessions_spawn returned no runId. "
                f"details={json.dumps(details, default=str)[:200]}, "
                f"result_keys={list(result.keys()) if isinstance(result, dict) else type(result).__name__}"
            )

        # Poll for completion
        deadline = time.time() + timeout_s
        poll_interval = 2.0

        while time.time() < deadline:
            time.sleep(poll_interval)
            try:
                history = self.history(child_key, limit=1)
                if history:
                    last = history[-1]
                    if last.get("role") == "assistant" and last.get("content"):
                        return {
                            "status": "ok",
                            "reply": last["content"],
                            "runId": run_id,
                            "childSessionKey": child_key,
                        }
            except Exception:
                pass
            try:
                status_info = self.session_status(child_key)
                if status_info.get("abortedLastRun"):
                    return {
                        "status": "error",
                        "error": "session aborted",
                        "runId": run_id,
                        "childSessionKey": child_key,
                    }
            except Exception:
                pass
            poll_interval = min(poll_interval * 1.5, 10.0)

        return {
            "status": "timeout",
            "error": f"session spawn timed out after {timeout_s}s",
            "runId": run_id,
            "childSessionKey": child_key,
        }

    def destroy_session(self, agent_id: str) -> None:
        """Destroy all sessions for a pool instance by removing session JSONL files.

        Next message to this agent creates a fresh session that reloads MEMORY.md.
        """
        sessions_dir = self._home / "agents" / agent_id / "sessions"
        if not sessions_dir.exists():
            return
        for f in sessions_dir.iterdir():
            if f.suffix == ".jsonl":
                try:
                    f.unlink()
                except Exception as exc:
                    logger.warning("Failed to delete session file %s: %s", f, exc)

    def _invoke(self, tool: str, args: dict, timeout: int = 120) -> dict:
        resp = httpx.post(
            f"{self._gateway_url}/tools/invoke",
            json={"tool": tool, "args": args},
            headers=self._headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok") and data.get("error"):
            raise OpenClawError(f"Gateway tool error [{tool}]: {data['error']}")
        return data.get("result") or data

    def _extract_details(self, result: dict | None) -> dict:
        if not isinstance(result, dict):
            return {}
        details = result.get("details")
        if isinstance(details, dict):
            return details
        return result

    def _raise_on_status(self, tool: str, details: dict) -> None:
        status = str(details.get("status") or "").strip().lower()
        if status in {"error", "forbidden", "failed"}:
            msg = str(details.get("error") or details.get("message") or status)
            raise OpenClawError(f"Gateway tool status error [{tool}]: {msg}")

    def _normalize_message(self, row: dict) -> dict:
        role = str(row.get("role") or "")
        content_text = self._content_text(row.get("content"))
        if not content_text:
            content_text = str(row.get("text") or row.get("errorMessage") or "")
        return {
            "role": role,
            "content": content_text,
            "text": content_text,
            "timestamp": row.get("timestamp"),
            "raw": row,
        }

    def _content_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    txt = item.get("text")
                    if isinstance(txt, str) and txt.strip():
                        parts.append(txt)
            return "\n".join(parts).strip()
        return ""


    def cleanup_all_sessions(self) -> int:
        """Remove all session JSONL files across all agents.

        Used during maintenance to ensure fresh sessions on next use.
        Returns total number of deleted session files.
        """
        agents_dir = self._home / "agents"
        if not agents_dir.exists():
            return 0
        cleaned = 0
        for agent_dir in agents_dir.iterdir():
            sessions_dir = agent_dir / "sessions"
            if not sessions_dir.is_dir():
                continue
            for f in sessions_dir.iterdir():
                if f.suffix == ".jsonl":
                    try:
                        f.unlink()
                        cleaned += 1
                    except Exception as exc:
                        logger.warning("Failed to delete session file %s: %s", f, exc)
        return cleaned
