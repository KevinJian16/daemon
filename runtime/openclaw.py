"""OpenClaw Gateway adapter — HTTP-based bridge to Agent sessions and file system."""
from __future__ import annotations

import json
import logging
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
        self._load_config()

    def _load_config(self) -> None:
        cfg_path = self._home / "openclaw.json"
        if not cfg_path.exists():
            raise OpenClawError(f"openclaw.json not found at {cfg_path}")
        self._cfg = json.loads(cfg_path.read_text())
        # Keep daemon-only fallback to avoid accidentally binding old MAS defaults.
        port = self._cfg.get("gateway", {}).get("port", 18790)
        self._gateway_url = f"http://127.0.0.1:{port}"
        self._token = self._cfg.get("gateway", {}).get("auth", {}).get("token", "")

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

    def send(self, session_key: str, message: str) -> dict:
        """Send a message to an Agent session."""
        return self._invoke("sessions_send", {"session_key": session_key, "message": message})

    def history(self, session_key: str, limit: int = 1) -> list[dict]:
        """Read recent messages from an Agent session."""
        result = self._invoke("sessions_history", {"session_key": session_key, "limit": limit})
        return result.get("messages") or result.get("history") or []

    def session_key(self, agent_id: str, task_id: str, step_id: str) -> str:
        return f"agent:{agent_id}:task:{task_id}:{step_id}"

    def _invoke(self, tool: str, args: dict) -> dict:
        resp = httpx.post(
            f"{self._gateway_url}/tools/invoke",
            json={"tool": tool, "args": args},
            headers=self._headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if not data.get("ok") and data.get("error"):
            raise OpenClawError(f"Gateway tool error [{tool}]: {data['error']}")
        return data.get("result") or data

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
