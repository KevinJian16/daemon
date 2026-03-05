"""CLI entrypoint for daemon runtime state reset."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.system_reset import SystemResetManager


def _daemon_home() -> Path:
    env = os.environ.get("DAEMON_HOME")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset daemon runtime state to clean baseline")
    parser.add_argument("--mode", choices=["strict", "light"], default="strict")
    parser.add_argument("--restart", action="store_true", help="restart daemon services after reset")
    parser.add_argument("--reason", default="cli_manual")
    parser.add_argument("--from-api", action="store_true", help="started by API reset confirm")
    args = parser.parse_args()

    manager = SystemResetManager(_daemon_home())
    report = manager.execute(mode=args.mode, restart=args.restart, reason=args.reason)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
