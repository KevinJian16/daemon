"""Daemon CLI — command-line interface to the Daemon API.

New architecture (7th draft): 4 L1 scenes, Jobs/Steps, no Spine/Psyche/Ledger.

Reference: SYSTEM_DESIGN.md §4.9
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx

API_URL = os.environ.get("DAEMON_API_URL", "http://127.0.0.1:8100")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(path: str) -> Any:
    r = httpx.get(f"{API_URL}{path}", timeout=30)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict | None = None) -> Any:
    r = httpx.post(f"{API_URL}{path}", json=body or {}, timeout=60)
    r.raise_for_status()
    return r.json()


# ── Formatting ────────────────────────────────────────────────────────────────

def _fmt_status(s: str) -> str:
    colors = {
        "ok": "\033[32m", "running": "\033[34m", "completed": "\033[32m",
        "closed": "\033[32m", "failed": "\033[31m", "paused": "\033[33m",
        "GREEN": "\033[32m", "YELLOW": "\033[33m", "RED": "\033[31m",
    }
    reset = "\033[0m"
    return f"{colors.get(s, '')}{s}{reset}"


def _table(rows: list[list[str]], headers: list[str]) -> None:
    if not rows:
        return
    widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    sep = "  "
    print(sep.join(h.ljust(w) for h, w in zip(headers, widths)))
    print(sep.join("─" * w for w in widths))
    for row in rows:
        print(sep.join(str(c).ljust(w) for c, w in zip(row, widths)))


def _die(msg: str) -> None:
    print(f"\033[31mError:\033[0m {msg}", file=sys.stderr)
    sys.exit(1)


def _usage() -> None:
    print("""
Daemon CLI

Usage: daemon <command> [options]

Commands:
  status                      Show system status
  health                      Health check
  chat <scene> <message>      Send a message to an L1 scene
  panel <scene>               Show scene panel data

Scenes: copilot, mentor, coach, operator

Examples:
  daemon status
  daemon health
  daemon chat copilot "帮我看看今天的任务"
  daemon panel copilot
""".strip())


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_status(args: list[str]) -> None:
    del args
    d = _get("/status")
    print(f"Status: {_fmt_status(d.get('status', 'unknown'))}")
    print(f"Started: {d.get('started_utc', '?')}")
    scenes = d.get("scenes", [])
    print(f"Scenes: {', '.join(scenes)}")
    for key in ["session_manager", "store", "event_bus", "plane_client"]:
        val = d.get(key)
        if val is not None:
            icon = "✓" if val else "✗"
            print(f"  {key}: {icon}")


def cmd_health(args: list[str]) -> None:
    del args
    d = _get("/health")
    ok = d.get("ok", False)
    print(f"Health: {'ok' if ok else 'not ok'}")
    print(f"Time: {d.get('ts', '?')}")


def cmd_chat(args: list[str]) -> None:
    if len(args) < 2:
        _die("Usage: daemon chat <scene> <message>")
    scene = args[0]
    message = " ".join(args[1:])
    result = _post(f"/scenes/{scene}/chat", {"content": message})
    reply = result.get("reply") or result.get("content") or "(no response)"
    print(f"\n{scene}: {reply}\n")
    actions = result.get("actions")
    if actions:
        print("Actions:")
        for a in actions:
            print(f"  - {a.get('type', '?')}: {a.get('summary', '')}")


def cmd_panel(args: list[str]) -> None:
    if not args:
        _die("Usage: daemon panel <scene>")
    scene = args[0]
    d = _get(f"/scenes/{scene}/panel")
    print(json.dumps(d, indent=2, ensure_ascii=False))


# ── Entry point ───────────────────────────────────────────────────────────────

COMMANDS = {
    "status": (cmd_status, 0),
    "health": (cmd_health, 0),
    "chat": (cmd_chat, 2),
    "panel": (cmd_panel, 1),
}


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        _usage()
        return

    cmd = args[0]
    rest = args[1:]

    if cmd not in COMMANDS:
        _die(f"Unknown command: {cmd}. Run 'daemon help' for usage.")

    fn, _ = COMMANDS[cmd]
    try:
        fn(rest)
    except httpx.ConnectError:
        _die(f"Cannot connect to Daemon API at {API_URL}")
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.json().get("detail") or e.response.text[:200]
        except Exception:
            body = e.response.text[:200]
        _die(f"API error {e.response.status_code}: {body}")
    except KeyboardInterrupt:
        print("\nInterrupted.")


if __name__ == "__main__":
    main()
