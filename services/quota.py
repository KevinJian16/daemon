"""Three-layer token quota enforcement (§5.8).

Layers:
  1. Per-session: handled by OC (contextTokens limit)
  2. Per-Job: checked in activities_exec.py heartbeat loop
  3. Daily system: global daily limit across all Jobs

Storage: PG table `token_usage` (created via migration or on first use).

Reference: SYSTEM_DESIGN.md §5.8, TODO.md Phase HIGH Knowledge & Learning
"""
from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

# Default quotas (override via env vars)
DEFAULT_JOB_TOKEN_LIMIT = int(os.environ.get("DAEMON_JOB_TOKEN_LIMIT", "500000"))
DEFAULT_DAILY_TOKEN_LIMIT = int(os.environ.get("DAEMON_DAILY_TOKEN_LIMIT", "5000000"))

# SQL to ensure token_usage table exists
_ENSURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS token_usage (
    id BIGSERIAL PRIMARY KEY,
    job_id UUID NOT NULL,
    step_id TEXT NOT NULL DEFAULT '',
    tokens_used INT NOT NULL DEFAULT 0,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_token_usage_job ON token_usage (job_id);
CREATE INDEX IF NOT EXISTS idx_token_usage_date ON token_usage (recorded_at);
"""


class QuotaManager:
    """Token quota enforcement across three layers.

    Layer 1 (per-session): OC handles via contextTokens config.
    Layer 2 (per-Job): check_quota(job_id) called in heartbeat loop.
    Layer 3 (daily system): check_quota(job_id) also checks daily total.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        job_token_limit: int = DEFAULT_JOB_TOKEN_LIMIT,
        daily_token_limit: int = DEFAULT_DAILY_TOKEN_LIMIT,
    ) -> None:
        self._pool = pool
        self._job_limit = job_token_limit
        self._daily_limit = daily_token_limit
        self._table_ensured = False

    async def _ensure_table(self) -> None:
        """Create token_usage table if it doesn't exist."""
        if self._table_ensured:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(_ENSURE_TABLE_SQL)
            self._table_ensured = True
        except Exception as exc:
            logger.warning("Failed to ensure token_usage table: %s", exc)

    async def record_usage(
        self,
        job_id: str,
        tokens: int,
        *,
        step_id: str = "",
    ) -> dict[str, Any]:
        """Record token usage for a job step.

        Args:
            job_id: Job UUID string.
            tokens: Number of tokens used.
            step_id: Optional step identifier.

        Returns:
            Dict with recorded usage info.
        """
        await self._ensure_table()
        try:
            job_uuid = UUID(job_id)
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO token_usage (job_id, step_id, tokens_used)
                    VALUES ($1, $2, $3)
                    """,
                    job_uuid,
                    step_id,
                    tokens,
                )
            return {"ok": True, "job_id": job_id, "tokens": tokens}
        except Exception as exc:
            logger.warning("Failed to record token usage: %s", exc)
            return {"ok": False, "error": str(exc)[:200]}

    async def check_quota(self, job_id: str) -> dict[str, Any]:
        """Check if a Job is within both per-Job and daily token quotas.

        Returns:
            Dict with:
              - allowed: bool
              - job_used: int (tokens used by this Job)
              - job_limit: int
              - daily_used: int (tokens used today, all Jobs)
              - daily_limit: int
              - reason: str (if not allowed)
        """
        await self._ensure_table()
        try:
            job_uuid = UUID(job_id)
            async with self._pool.acquire() as conn:
                # Per-Job usage
                job_row = await conn.fetchrow(
                    "SELECT COALESCE(SUM(tokens_used), 0) AS total FROM token_usage WHERE job_id = $1",
                    job_uuid,
                )
                job_used = int(job_row["total"]) if job_row else 0

                # Daily system usage (all Jobs today)
                daily_row = await conn.fetchrow(
                    """
                    SELECT COALESCE(SUM(tokens_used), 0) AS total
                    FROM token_usage
                    WHERE recorded_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
                    """,
                )
                daily_used = int(daily_row["total"]) if daily_row else 0

            result: dict[str, Any] = {
                "allowed": True,
                "job_used": job_used,
                "job_limit": self._job_limit,
                "daily_used": daily_used,
                "daily_limit": self._daily_limit,
            }

            if job_used >= self._job_limit:
                result["allowed"] = False
                result["reason"] = f"Job token limit exceeded: {job_used}/{self._job_limit}"
                logger.warning("Job %s exceeded token quota: %d/%d", job_id, job_used, self._job_limit)

            elif daily_used >= self._daily_limit:
                result["allowed"] = False
                result["reason"] = f"Daily system token limit exceeded: {daily_used}/{self._daily_limit}"
                logger.warning("Daily token quota exceeded: %d/%d", daily_used, self._daily_limit)

            return result

        except Exception as exc:
            logger.warning("Quota check failed (allowing): %s", exc)
            # Fail open: allow execution if quota check fails
            return {
                "allowed": True,
                "job_used": 0,
                "job_limit": self._job_limit,
                "daily_used": 0,
                "daily_limit": self._daily_limit,
                "warning": f"quota_check_failed: {str(exc)[:100]}",
            }

    async def get_daily_usage(self) -> dict[str, Any]:
        """Get aggregated daily token usage (for admin dashboard)."""
        await self._ensure_table()
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT job_id, SUM(tokens_used) AS total_tokens,
                           COUNT(*) AS step_count
                    FROM token_usage
                    WHERE recorded_at >= date_trunc('day', now() AT TIME ZONE 'UTC')
                    GROUP BY job_id
                    ORDER BY total_tokens DESC
                    """,
                )
            jobs = [
                {"job_id": str(r["job_id"]), "tokens": int(r["total_tokens"]), "steps": int(r["step_count"])}
                for r in rows
            ]
            total = sum(j["tokens"] for j in jobs)
            return {
                "ok": True,
                "date": datetime.now(UTC).strftime("%Y-%m-%d"),
                "total_tokens": total,
                "daily_limit": self._daily_limit,
                "jobs": jobs,
            }
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:200]}
