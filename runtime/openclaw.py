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

    All Agent communication goes through the Gateway HTTP API.
    No CLI fallback — one channel, one source of truth.
    """

    def __init__(self, openclaw_home: Path) -> None:
        self._home = openclaw_home
        self._cfg: dict = {}
        self._gateway_url: str = ""
        self._token: str = ""
        self._session_alias: dict[str, str] = {}
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

    def send(self, session_key: str, message: str, agent_id: str | None = None) -> dict:
        """Spawn an isolated subagent execution for this step."""
        args: dict[str, Any] = {
            "task": message,
            "runtime": "subagent",
            "runTimeoutSeconds": 240,
            "cleanup": "keep",
        }
        if agent_id:
            args["agentId"] = agent_id
        result = self._invoke("sessions_spawn", args)
        details = self._extract_details(result)
        self._raise_on_status("sessions_spawn", details)
        child_session_key = str(details.get("childSessionKey") or "").strip()
        if child_session_key:
            self._session_alias[session_key] = child_session_key
            details["sessionKey"] = child_session_key
        else:
            # Fallback for older gateways that do not return childSessionKey.
            send_args: dict[str, Any] = {"sessionKey": session_key, "message": message}
            if agent_id:
                send_args["agentId"] = agent_id
            result = self._invoke("sessions_send", send_args)
            details = self._extract_details(result)
            self._raise_on_status("sessions_send", details)
        return details or result

    def history(self, session_key: str, limit: int = 1) -> list[dict]:
        """Read recent messages from an Agent session."""
        actual_key = self._session_alias.get(session_key, session_key)
        result = self._invoke("sessions_history", {"sessionKey": actual_key, "limit": limit})
        details = self._extract_details(result)
        self._raise_on_status("sessions_history", details)
        rows = (details or {}).get("messages") or (result or {}).get("messages") or []
        if not isinstance(rows, list):
            return []
        return [self._normalize_message(m) for m in rows if isinstance(m, dict)]

    def session_key(self, agent_id: str, run_id: str, step_id: str) -> str:
        return f"agent:{agent_id}:run:{run_id}:{step_id}"

    def _invoke(self, tool: str, args: dict) -> dict:
        resp = httpx.post(
            f"{self._gateway_url}/tools/invoke",
            json={"tool": tool, "args": args},
            headers=self._headers,
            timeout=120,
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

    # ── Snapshot relay ────────────────────────────────────────────────────────

    def write_snapshot(self, agent: str, filename: str, content: Any) -> None:
        """Write a Fabric snapshot file into an Agent's memory directory."""
        mem_dir = self._home / "workspace" / agent / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        path = mem_dir / filename
        if isinstance(content, (dict, list)):
            path.write_text(json.dumps(content, ensure_ascii=False, indent=2))
        else:
            path.write_text(str(content))

    def read_agent_output(self, run_path: Path, filename: str) -> Any:
        """Read a file from an Agent's run output directory."""
        target = run_path / filename
        if not target.exists():
            return None
        raw = target.read_text()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    def list_runs(self) -> list[Path]:
        runs_dir = self._home / "runs"
        if not runs_dir.exists():
            return []
        return sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)

    def cleanup_orphaned_sessions(self) -> int:
        """Remove session references that have no corresponding .jsonl file."""
        sessions_path = self._home / "sessions.json"
        if not sessions_path.exists():
            return 0
        try:
            sessions = json.loads(sessions_path.read_text())
        except Exception as exc:
            logger.warning("Failed to parse session index %s: %s", sessions_path, exc)
            return 0

        sessions_dir = self._home / "sessions"
        cleaned = 0
        valid = []
        for s in sessions if isinstance(sessions, list) else []:
            sid = s.get("sessionId") or s.get("id") or ""
            if sid and (sessions_dir / f"{sid}.jsonl").exists():
                valid.append(s)
            else:
                cleaned += 1

        if cleaned:
            sessions_path.write_text(json.dumps(valid, ensure_ascii=False, indent=2))
        return cleaned
