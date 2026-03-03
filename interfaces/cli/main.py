"""Daemon CLI — command-line interface to the Daemon API."""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx

API_URL = os.environ.get("DAEMON_API_URL", "http://127.0.0.1:8000")


# ── HTTP helpers ──────────────────────────────────────────────────────────────

def _get(path: str) -> Any:
    r = httpx.get(f"{API_URL}{path}", timeout=30)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict | None = None) -> Any:
    r = httpx.post(f"{API_URL}{path}", json=body or {}, timeout=60)
    r.raise_for_status()
    return r.json()


def _put(path: str, body: dict) -> Any:
    r = httpx.put(f"{API_URL}{path}", json=body, timeout=30)
    r.raise_for_status()
    return r.json()


# ── Formatting ────────────────────────────────────────────────────────────────

def _fmt_status(s: str) -> str:
    colors = {
        "ok": "\033[32m", "running": "\033[34m", "queued": "\033[33m",
        "completed": "\033[32m", "failed": "\033[31m", "degraded": "\033[33m",
        "GREEN": "\033[32m", "YELLOW": "\033[33m", "RED": "\033[31m",
    }
    reset = "\033[0m"
    return f"{colors.get(s, '')}{s}{reset}"


def _table(rows: list[list[str]], headers: list[str]) -> None:
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
  health                    Show system health and gate status
  submit <plan.json>        Submit a task plan from file
  tasks [--status STATUS]   List tasks
  task <task_id>            Show task details
  outcomes [--limit N]      List recent outcomes
  chat                      Start interactive chat session
  spine status              Show Spine routine status
  spine trigger <routine>   Manually trigger a Spine routine
  fabric memory             Show Memory Fabric stats
  fabric playbook           Show active Playbook methods
  fabric compass            Show Compass priorities + budgets
  policy get <name>         Show a quality profile
  policy set <name>         Set quality profile (reads JSON from stdin)
  traces [--routine R]      Show recent traces

Examples:
  daemon health
  daemon submit plan.json
  daemon tasks --status running
  daemon task task_20260304_a1b2c3
  daemon outcomes --limit 10
  daemon chat
  daemon spine trigger pulse
  daemon policy get research_report
""".strip())


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_health() -> None:
    d = _get("/health")
    gate = d.get("gate", "?")
    print(f"Gate: {_fmt_status(gate)}")
    print(f"API:  ok")


def cmd_submit(args: list[str]) -> None:
    if not args:
        _die("Usage: daemon submit <plan.json>")
    path = args[0]
    try:
        with open(path) as f:
            plan = json.load(f)
    except FileNotFoundError:
        _die(f"File not found: {path}")
    except json.JSONDecodeError as e:
        _die(f"Invalid JSON: {e}")

    result = _post("/submit", plan)
    if result.get("ok"):
        print(f"✓ Submitted: {result.get('task_id')}")
        if result.get("queued"):
            print("  (queued — Gate is not GREEN)")
    else:
        _die(result.get("error") or "submission failed")


def cmd_tasks(args: list[str]) -> None:
    status = ""
    limit = 50
    i = 0
    while i < len(args):
        if args[i] == "--status" and i + 1 < len(args):
            status = args[i + 1]; i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        else:
            i += 1

    url = f"/tasks?limit={limit}"
    if status:
        url += f"&status={status}"
    tasks = _get(url)
    if not tasks:
        print("No tasks found.")
        return
    rows = [
        [t.get("task_id", ""), t.get("task_type", ""), t.get("title", "")[:40],
         _fmt_status(t.get("status", "")), str(t.get("priority", ""))]
        for t in reversed(tasks)
    ]
    _table(rows, ["Task ID", "Type", "Title", "Status", "Pri"])


def cmd_task(args: list[str]) -> None:
    if not args:
        _die("Usage: daemon task <task_id>")
    task = _get(f"/tasks/{args[0]}")
    for k, v in task.items():
        print(f"  {k}: {v}")


def cmd_outcomes(args: list[str]) -> None:
    limit = 20
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        else:
            i += 1

    items = _get(f"/outcome?limit={limit}")
    if not items:
        print("No outcomes found.")
        return
    rows = [
        [o.get("task_id", ""), o.get("title", "")[:50],
         o.get("task_type", ""), (o.get("archived_utc") or "")[:19]]
        for o in items
    ]
    _table(rows, ["Task ID", "Title", "Type", "Archived"])


def cmd_chat() -> None:
    """Interactive chat session with the Router Agent."""
    try:
        d = _post("/chat/session")
    except Exception as e:
        _die(f"Cannot create session: {e}")

    sid = d["session_id"]
    print(f"Chat session: {sid}")
    print("Type your message and press Enter. Empty line to quit.\n")

    while True:
        try:
            msg = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting chat.")
            break
        if not msg:
            break

        try:
            result = _post(f"/chat/{sid}", {"message": msg})
            content = result.get("content") or "(no response)"
            print(f"\nRouter: {content}\n")

            plan = result.get("plan")
            if plan:
                print(f"\033[33m[Plan detected]\033[0m")
                print(json.dumps(plan, ensure_ascii=False, indent=2))
                ans = input("Submit this plan? [y/N] ").strip().lower()
                if ans == "y":
                    sub = _post("/submit", plan)
                    if sub.get("ok"):
                        print(f"✓ Submitted: {sub.get('task_id')}\n")
                    else:
                        print(f"✗ Submit failed: {sub.get('error')}\n")
        except Exception as e:
            print(f"\033[31mError:\033[0m {e}\n")


def cmd_spine(args: list[str]) -> None:
    if not args:
        _die("Usage: daemon spine <status|trigger> [routine]")
    sub = args[0]
    if sub == "status":
        routines = _get("/console/spine/status")
        rows = [
            [r.get("routine", ""), r.get("mode", ""), r.get("schedule", ""),
             (r.get("last_run_utc") or "never")[:19]]
            for r in routines
        ]
        _table(rows, ["Routine", "Mode", "Schedule", "Last Run"])
    elif sub == "trigger":
        if len(args) < 2:
            _die("Usage: daemon spine trigger <routine>")
        name = args[1]
        result = _post(f"/console/spine/{name}/trigger")
        if result.get("ok"):
            print(f"✓ Triggered: {name}")
            if result.get("result"):
                print(json.dumps(result["result"], indent=2))
        else:
            _die(result.get("error") or "trigger failed")
    else:
        _die(f"Unknown spine subcommand: {sub}")


def cmd_fabric(args: list[str]) -> None:
    if not args:
        _die("Usage: daemon fabric <memory|playbook|compass>")
    sub = args[0]
    if sub == "memory":
        units = _get("/console/fabric/memory?limit=20")
        rows = [
            [u.get("unit_id", "")[:12], u.get("title", "")[:40],
             u.get("domain", ""), u.get("tier", ""),
             f"{(u.get('confidence',0)*100):.0f}%"]
            for u in units
        ]
        _table(rows, ["ID", "Title", "Domain", "Tier", "Conf"])
    elif sub == "playbook":
        methods = _get("/console/fabric/playbook")
        rows = [
            [m.get("name", ""), m.get("category", ""),
             f"{(m.get('success_rate') or 0)*100:.1f}%" if m.get('success_rate') is not None else "—",
             str(m.get("total_runs", 0)), f"v{m.get('version', 1)}"]
            for m in methods
        ]
        _table(rows, ["Name", "Category", "Success", "Runs", "Ver"])
    elif sub == "compass":
        prios = _get("/console/fabric/compass/priorities")
        print("=== Priorities ===")
        rows = [[p.get("domain", ""), str(p.get("weight", "")), p.get("source", "")] for p in prios]
        _table(rows, ["Domain", "Weight", "Source"])
        print()
        budgets = _get("/console/fabric/compass/budgets")
        print("=== Resource Budgets ===")
        brows = [
            [b.get("resource_type", ""),
             f"{b.get('daily_limit', 0):,}", f"{b.get('current_usage', 0):,}"]
            for b in budgets
        ]
        _table(brows, ["Resource", "Daily Limit", "Used Today"])
    else:
        _die(f"Unknown fabric subcommand: {sub}")


def cmd_policy(args: list[str]) -> None:
    if len(args) < 2:
        _die("Usage: daemon policy <get|set> <name>")
    sub, name = args[0], args[1]
    if sub == "get":
        d = _get(f"/console/policy/{name}")
        print(json.dumps(d.get("rules") or d, indent=2, ensure_ascii=False))
    elif sub == "set":
        print(f"Enter JSON rules for '{name}' (then Ctrl+D):")
        raw = sys.stdin.read()
        try:
            rules = json.loads(raw)
        except json.JSONDecodeError as e:
            _die(f"Invalid JSON: {e}")
        result = _put(f"/console/policy/{name}", {"rules": rules})
        print(f"✓ Policy '{name}' updated" if result.get("ok") else f"✗ {result}")
    else:
        _die(f"Unknown policy subcommand: {sub}")


def cmd_traces(args: list[str]) -> None:
    routine = ""
    status = ""
    limit = 20
    i = 0
    while i < len(args):
        if args[i] == "--routine" and i + 1 < len(args):
            routine = args[i + 1]; i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            status = args[i + 1]; i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        else:
            i += 1

    url = f"/console/traces?limit={limit}"
    if routine:
        url += f"&routine={routine}"
    if status:
        url += f"&status={status}"
    traces = _get(url)
    if not traces:
        print("No traces found.")
        return
    rows = [
        [t.get("trace_id", "")[:16], t.get("routine", ""),
         _fmt_status(t.get("status", "")),
         "yes" if t.get("degraded") else "—",
         str(t.get("elapsed_s", ""))]
        for t in traces
    ]
    _table(rows, ["Trace ID", "Routine", "Status", "Degraded", "Elapsed(s)"])


# ── Entry point ───────────────────────────────────────────────────────────────

COMMANDS = {
    "health": (cmd_health, 0),
    "submit": (cmd_submit, 1),
    "tasks": (cmd_tasks, 0),
    "task": (cmd_task, 1),
    "outcomes": (cmd_outcomes, 0),
    "chat": (cmd_chat, 0),
    "spine": (cmd_spine, 1),
    "fabric": (cmd_fabric, 1),
    "policy": (cmd_policy, 2),
    "traces": (cmd_traces, 0),
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
