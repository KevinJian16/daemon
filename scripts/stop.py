"""scripts/stop.py — Graceful shutdown for daemon.

Steps:
  1. Drain Worker (stop accepting new activities, wait for current ones)
  2. Stop API server
  3. Docker services stay running (only daemon processes are stopped)

Reference: SYSTEM_DESIGN.md §7.10
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

DAEMON_HOME = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))


def _log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    print(f"[stop] {ts} {msg}", flush=True)


def _find_pids(pattern: str) -> list[int]:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return [int(p) for p in r.stdout.strip().split()]
    except Exception:
        pass
    return []


def _stop_process(name: str, pattern: str, timeout: int = 15) -> None:
    pids = _find_pids(pattern)
    if not pids:
        _log(f"  {name}: not running")
        return

    _log(f"  {name}: sending SIGTERM to PID(s) {pids}")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    # Wait for graceful shutdown
    deadline = time.time() + timeout
    while time.time() < deadline:
        remaining = _find_pids(pattern)
        if not remaining:
            _log(f"  {name}: stopped")
            return
        time.sleep(1)

    # Force kill remaining
    remaining = _find_pids(pattern)
    if remaining:
        _log(f"  {name}: force killing PID(s) {remaining}")
        for pid in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def main() -> int:
    _log("daemon graceful shutdown")

    # 1. Stop Worker first (drain)
    _stop_process("Worker", "python.*temporal.*worker", timeout=30)

    # 2. Stop API
    _stop_process("API", "uvicorn.*services.api", timeout=15)

    # 3. Stop Telegram adapter if running
    _stop_process("Telegram adapter", "uvicorn.*telegram.*adapter", timeout=10)

    _log("daemon processes stopped (Docker services remain running)")
    _log("To stop Docker: docker compose down")
    return 0


if __name__ == "__main__":
    sys.exit(main())
