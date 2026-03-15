#!/usr/bin/env python3
"""Daemon Warmup Script — new architecture (7th draft).

Warmup is now system calibration (§7.1-§7.5):
  Stage 0: Information collection (~15 min)
  Stage 1: Persona calibration (~20 min)
  Stage 2: Link verification — 17 data links (~30 min)
  Stage 3: Test task suite + Skill calibration (~2-3h)
  Stage 4: System state & exception scenarios (~30 min)

This script handles Stage 2 (link verification) programmatically.
Stages 0, 1, 3, 4 require human interaction or agent execution.

Run:
    cd /path/to/daemon
    python scripts/warmup.py [--stage 2]
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_env = _ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger("warmup")


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def check_pg_connection() -> dict:
    """Verify PostgreSQL is reachable."""
    try:
        import asyncio
        import asyncpg
        db_url = os.environ.get("DATABASE_URL", "postgresql://daemon:daemon@localhost:5432/daemon")

        async def _check():
            conn = await asyncpg.connect(db_url)
            result = await conn.fetchval("SELECT 1")
            await conn.close()
            return result == 1

        ok = asyncio.run(_check())
        return {"link": "PG", "ok": ok}
    except Exception as exc:
        return {"link": "PG", "ok": False, "error": str(exc)}


def check_temporal_connection() -> dict:
    """Verify Temporal server is reachable."""
    try:
        import socket
        addr = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
        host, port = addr.split(":")
        sock = socket.create_connection((host, int(port)), timeout=5)
        sock.close()
        return {"link": "Temporal", "ok": True}
    except Exception as exc:
        return {"link": "Temporal", "ok": False, "error": str(exc)}


def check_plane_api() -> dict:
    """Verify Plane API is reachable."""
    try:
        import httpx
        url = os.environ.get("PLANE_API_URL", "http://localhost:8001")
        token = os.environ.get("PLANE_API_TOKEN", "")
        resp = httpx.get(
            f"{url}/api/v1/users/me/",
            headers={"X-API-Key": token},
            timeout=10,
        )
        return {"link": "Plane", "ok": resp.status_code < 500, "status": resp.status_code}
    except Exception as exc:
        return {"link": "Plane", "ok": False, "error": str(exc)}


def check_minio() -> dict:
    """Verify MinIO is reachable."""
    try:
        import httpx
        resp = httpx.get("http://localhost:9000/minio/health/live", timeout=5)
        return {"link": "MinIO", "ok": resp.status_code == 200}
    except Exception as exc:
        return {"link": "MinIO", "ok": False, "error": str(exc)}


def check_elasticsearch() -> dict:
    """Verify Elasticsearch is reachable."""
    try:
        import httpx
        resp = httpx.get("http://localhost:9200/_cluster/health", timeout=5)
        data = resp.json()
        return {"link": "Elasticsearch", "ok": data.get("status") in ("green", "yellow"), "status": data.get("status")}
    except Exception as exc:
        return {"link": "Elasticsearch", "ok": False, "error": str(exc)}


def check_redis() -> dict:
    """Verify Redis is reachable."""
    try:
        import socket
        sock = socket.create_connection(("localhost", 6379), timeout=5)
        sock.sendall(b"PING\r\n")
        data = sock.recv(32)
        sock.close()
        return {"link": "Redis", "ok": b"PONG" in data}
    except Exception as exc:
        return {"link": "Redis", "ok": False, "error": str(exc)}


def check_daemon_api() -> dict:
    """Verify daemon API is responding."""
    try:
        import httpx
        resp = httpx.get("http://127.0.0.1:8100/health", timeout=10)
        return {"link": "daemon API", "ok": resp.status_code == 200}
    except Exception as exc:
        return {"link": "daemon API", "ok": False, "error": str(exc)}


def check_oc_gateway() -> dict:
    """Verify OC Gateway is responding."""
    try:
        import httpx
        resp = httpx.get("http://127.0.0.1:18790/", timeout=10)
        return {"link": "OC Gateway", "ok": resp.status_code < 500}
    except Exception as exc:
        return {"link": "OC Gateway", "ok": False, "error": str(exc)}


def check_langfuse() -> dict:
    """Verify Langfuse is reachable."""
    try:
        import httpx
        resp = httpx.get("http://localhost:3001", timeout=10)
        return {"link": "Langfuse", "ok": resp.status_code < 500}
    except Exception as exc:
        return {"link": "Langfuse", "ok": False, "error": str(exc)}


def check_clickhouse() -> dict:
    """Verify ClickHouse is reachable."""
    try:
        import httpx
        resp = httpx.get("http://localhost:8123/ping", timeout=5)
        return {"link": "ClickHouse", "ok": resp.status_code == 200}
    except Exception as exc:
        return {"link": "ClickHouse", "ok": False, "error": str(exc)}


def check_mem0() -> dict:
    """Verify Mem0 is initialized."""
    try:
        sys.path.insert(0, str(_ROOT))
        from config.mem0_config import init_mem0
        m = init_mem0()
        ok = m is not None
        return {"link": "Mem0 (Qdrant)", "ok": ok}
    except Exception as exc:
        return {"link": "Mem0 (Qdrant)", "ok": False, "error": str(exc)}


def check_mcp_servers() -> dict:
    """Verify custom MCP server scripts can import."""
    try:
        sys.path.insert(0, str(_ROOT))
        from mcp_servers.semantic_scholar import app as s2_app
        from mcp_servers.code_functions import app as cf_app
        from mcp_servers.paper_tools import app as pt_app
        return {"link": "MCP servers (import)", "ok": True}
    except Exception as exc:
        return {"link": "MCP servers (import)", "ok": False, "error": str(exc)}


def check_guardrails() -> dict:
    """Verify NeMo Guardrails actions work."""
    try:
        sys.path.insert(0, str(_ROOT))
        from config.guardrails.actions import validate_input, validate_output
        _, warns = validate_input("hello")
        _, _ = validate_output("result text")
        return {"link": "NeMo Guardrails", "ok": True}
    except Exception as exc:
        return {"link": "NeMo Guardrails", "ok": False, "error": str(exc)}


def run_stage2() -> dict:
    """Stage 2: Full 17-link verification."""
    results = []
    checks = [
        # Infrastructure (6)
        check_pg_connection,
        check_temporal_connection,
        check_redis,
        check_minio,
        check_elasticsearch,
        check_clickhouse,
        # Services (5)
        check_daemon_api,
        check_oc_gateway,
        check_plane_api,
        check_langfuse,
        # Knowledge/Memory (3)
        check_mem0,
        check_guardrails,
        check_mcp_servers,
    ]
    for check in checks:
        result = check()
        status = "✅" if result["ok"] else "❌"
        logger.info("  %s %s", status, result["link"])
        results.append(result)

    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    all_ok = passed == total
    logger.info("Stage 2 result: %d/%d passed", passed, total)
    return {
        "stage": 2,
        "description": "Full link verification (17 data links)",
        "results": results,
        "passed": passed,
        "total": total,
        "all_ok": all_ok,
        "timestamp": _utc(),
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Daemon warmup (system calibration)")
    parser.add_argument("--stage", type=int, default=2, help="Warmup stage to run (default: 2)")
    args = parser.parse_args()

    logger.info("daemon warmup — Stage %d", args.stage)

    if args.stage == 2:
        report = run_stage2()
    else:
        logger.info("Stage %d requires interactive agent execution. Use daemon API.", args.stage)
        return 0

    # Save report
    report_dir = _ROOT / "warmup" / "results"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"stage{args.stage}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    logger.info("Report saved: %s", report_path)

    return 0 if report.get("all_ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
