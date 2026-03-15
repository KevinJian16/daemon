"""CLI entrypoint for daemon runtime state reset.

New architecture: resets PG state via Store, cleans OC sessions, and
optionally restarts services.

Reference: SYSTEM_DESIGN.md §7.4 (self-healing)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daemon_env import load_daemon_env


def _daemon_home() -> Path:
    env = os.environ.get("DAEMON_HOME")
    if env:
        return Path(env)
    return ROOT


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def _reset(home: Path, mode: str, reason: str) -> dict:
    """Reset daemon runtime state."""
    report: dict = {
        "ok": True,
        "mode": mode,
        "reason": reason,
        "started_utc": _utc(),
        "actions": [],
    }

    # 1. Clean OC sessions
    oc_home_env = os.environ.get("OPENCLAW_HOME")
    oc_home = Path(oc_home_env) if oc_home_env else home / "openclaw"
    try:
        from runtime.openclaw import OpenClawAdapter
        oc = OpenClawAdapter(oc_home)
        cleaned = oc.cleanup_all_sessions()
        report["actions"].append({"action": "oc_sessions_cleaned", "count": cleaned})
    except Exception as exc:
        report["actions"].append({"action": "oc_sessions_clean_failed", "error": str(exc)[:200]})

    # 2. Clean state directory
    state_dir = home / "state"
    if state_dir.exists():
        for subdir in ["health_reports", "issues"]:
            target = state_dir / subdir
            if target.is_dir():
                count = 0
                for f in target.iterdir():
                    if f.is_file():
                        f.unlink()
                        count += 1
                report["actions"].append({"action": f"cleaned_{subdir}", "count": count})

    # 3. If strict mode, also truncate PG job/step tables
    if mode == "strict":
        database_url = os.environ.get(
            "DATABASE_URL",
            "postgresql://daemon:daemon@localhost:5432/daemon",
        )
        try:
            import asyncpg
            conn = await asyncpg.connect(database_url)
            for table in ["job_steps", "job_artifacts", "jobs"]:
                try:
                    count = await conn.fetchval(f"SELECT count(*) FROM {table}")
                    await conn.execute(f"TRUNCATE {table} CASCADE")
                    report["actions"].append({"action": f"truncated_{table}", "rows": count})
                except Exception as exc:
                    report["actions"].append({"action": f"truncate_{table}_failed", "error": str(exc)[:200]})
            await conn.close()
        except Exception as exc:
            report["actions"].append({"action": "pg_reset_failed", "error": str(exc)[:200]})
            report["ok"] = False

    report["completed_utc"] = _utc()
    return report


def main() -> int:
    load_daemon_env(ROOT)

    parser = argparse.ArgumentParser(description="Reset daemon runtime state to clean baseline")
    parser.add_argument("--mode", choices=["strict", "light"], default="light",
                        help="strict: also truncate PG job tables; light: only clean sessions/state files")
    parser.add_argument("--reason", default="cli_manual")
    args = parser.parse_args()

    home = _daemon_home()
    report = asyncio.run(_reset(home, mode=args.mode, reason=args.reason))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
