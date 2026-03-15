"""PG data layer — replaces Ledger JSON file I/O.

Reference: SYSTEM_DESIGN_REFERENCE.md Appendix C
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


class Store:
    """Async PostgreSQL data access layer for daemon tables.

    All methods operate on the 'daemon' database.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # daemon_tasks
    # ------------------------------------------------------------------

    async def create_task(
        self,
        plane_issue_id: UUID | None = None,
        *,
        title: str | None = None,
        project_id: UUID | None = None,
        trigger_type: str = "manual",
        schedule_id: str | None = None,
        chain_source_task_id: UUID | None = None,
        dag: dict | None = None,
        source: str | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO daemon_tasks
                    (plane_issue_id, title, project_id, trigger_type, schedule_id,
                     chain_source_task_id, dag)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING *
                """,
                plane_issue_id,
                title,
                project_id,
                trigger_type,
                schedule_id,
                chain_source_task_id,
                json.dumps(dag) if dag else None,
            )
            return dict(row)

    async def get_task(self, task_id: UUID) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM daemon_tasks WHERE task_id = $1", task_id
            )
            return dict(row) if row else None

    async def get_task_by_plane_issue(self, plane_issue_id: UUID) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM daemon_tasks WHERE plane_issue_id = $1",
                plane_issue_id,
            )
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # jobs
    # ------------------------------------------------------------------

    async def create_job(
        self,
        task_id: UUID,
        workflow_id: str,
        dag_snapshot: dict,
        *,
        is_ephemeral: bool = False,
        requires_review: bool = False,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO jobs
                    (task_id, workflow_id, dag_snapshot, is_ephemeral, requires_review)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                task_id,
                workflow_id,
                json.dumps(dag_snapshot),
                is_ephemeral,
                requires_review,
            )
            return dict(row)

    async def get_job(self, job_id: UUID) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM jobs WHERE job_id = $1", job_id)
            return dict(row) if row else None

    async def update_job_status(
        self,
        job_id: UUID,
        status: str,
        sub_status: str,
        **extra: Any,
    ) -> dict:
        sets = ["status = $2", "sub_status = $3"]
        params: list[Any] = [job_id, status, sub_status]
        idx = 4

        if status == "running" and sub_status == "executing" and "started_at" not in extra:
            extra["started_at"] = datetime.now(UTC)
        if status == "closed" and "closed_at" not in extra:
            extra["closed_at"] = datetime.now(UTC)

        for k, v in extra.items():
            sets.append(f"{k} = ${idx}")
            params.append(v)
            idx += 1

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = $1 RETURNING *",
                *params,
            )
            return dict(row) if row else {}

    async def list_jobs_for_task(self, task_id: UUID) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM jobs WHERE task_id = $1 ORDER BY created_at",
                task_id,
            )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # job_steps
    # ------------------------------------------------------------------

    async def create_step(
        self,
        job_id: UUID,
        step_index: int,
        goal: str,
        *,
        agent_id: str | None = None,
        execution_type: str = "agent",
        model_hint: str | None = None,
        depends_on: list[int] | None = None,
        input_artifacts: list[str] | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO job_steps
                    (job_id, step_index, goal, agent_id, execution_type,
                     model_hint, depends_on, input_artifacts)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING *
                """,
                job_id,
                step_index,
                goal,
                agent_id,
                execution_type,
                model_hint,
                depends_on or [],
                input_artifacts or [],
            )
            return dict(row)

    async def update_step_status(
        self, step_id: UUID, status: str, **extra: Any
    ) -> dict:
        sets = ["status = $2"]
        params: list[Any] = [step_id, status]
        idx = 3

        for k, v in extra.items():
            sets.append(f"{k} = ${idx}")
            params.append(v)
            idx += 1

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"UPDATE job_steps SET {', '.join(sets)} WHERE step_id = $1 RETURNING *",
                *params,
            )
            return dict(row) if row else {}

    async def get_steps_for_job(self, job_id: UUID) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM job_steps WHERE job_id = $1 ORDER BY step_index",
                job_id,
            )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # job_artifacts
    # ------------------------------------------------------------------

    async def create_artifact(
        self,
        job_id: UUID,
        minio_path: str,
        artifact_type: str,
        *,
        step_id: UUID | None = None,
        title: str | None = None,
        summary: str | None = None,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        source_markers: dict | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO job_artifacts
                    (job_id, step_id, artifact_type, title, summary,
                     minio_path, mime_type, size_bytes, source_markers)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING *
                """,
                job_id,
                step_id,
                artifact_type,
                title,
                summary,
                minio_path,
                mime_type,
                size_bytes,
                json.dumps(source_markers) if source_markers else None,
            )
            return dict(row)

    async def get_artifacts_for_job(self, job_id: UUID) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM job_artifacts WHERE job_id = $1 ORDER BY created_at",
                job_id,
            )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # conversation_messages (L1 — layer 1)
    # ------------------------------------------------------------------

    async def save_message(
        self, scene: str, role: str, content: str, token_count: int | None = None
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO conversation_messages (scene, role, content, token_count)
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                scene,
                role,
                content,
                token_count,
            )
            return dict(row)

    async def get_recent_messages(
        self, scene: str, limit: int = 50
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM conversation_messages
                WHERE scene = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                scene,
                limit,
            )
            return [dict(r) for r in reversed(rows)]

    # ------------------------------------------------------------------
    # conversation_digests (L1 — layer 2)
    # ------------------------------------------------------------------

    async def save_digest(
        self,
        scene: str,
        time_range_start: datetime,
        time_range_end: datetime,
        summary: str,
        token_count: int | None = None,
        source_message_count: int | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO conversation_digests
                    (scene, time_range_start, time_range_end, summary,
                     token_count, source_message_count)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                scene,
                time_range_start,
                time_range_end,
                summary,
                token_count,
                source_message_count,
            )
            return dict(row)

    async def get_recent_digests(
        self, scene: str, limit: int = 10
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM conversation_digests
                WHERE scene = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                scene,
                limit,
            )
            return [dict(r) for r in reversed(rows)]

    # ------------------------------------------------------------------
    # conversation_decisions (L1 — layer 3)
    # ------------------------------------------------------------------

    async def save_decision(
        self,
        scene: str,
        decision_type: str,
        content: str,
        context_summary: str | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO conversation_decisions
                    (scene, decision_type, content, context_summary)
                VALUES ($1, $2, $3, $4)
                RETURNING *
                """,
                scene,
                decision_type,
                content,
                context_summary,
            )
            return dict(row)

    async def get_recent_decisions(
        self, scene: str, limit: int = 20
    ) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM conversation_decisions
                WHERE scene = $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                scene,
                limit,
            )
            return [dict(r) for r in reversed(rows)]

    # ------------------------------------------------------------------
    # knowledge_cache
    # ------------------------------------------------------------------

    async def upsert_knowledge(
        self,
        source_url: str,
        source_tier: str,
        expires_at: datetime,
        *,
        project_id: UUID | None = None,
        title: str | None = None,
        content_summary: str | None = None,
        ragflow_doc_id: str | None = None,
        embedding: list[float] | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO knowledge_cache
                    (source_url, source_tier, project_id, title,
                     content_summary, ragflow_doc_id, embedding, expires_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (source_url) DO UPDATE SET
                    source_tier = EXCLUDED.source_tier,
                    title = EXCLUDED.title,
                    content_summary = EXCLUDED.content_summary,
                    ragflow_doc_id = EXCLUDED.ragflow_doc_id,
                    embedding = EXCLUDED.embedding,
                    expires_at = EXCLUDED.expires_at
                RETURNING *
                """,
                source_url,
                source_tier,
                project_id,
                title,
                content_summary,
                ragflow_doc_id,
                str(embedding) if embedding else None,
                expires_at,
            )
            return dict(row)

    async def cleanup_expired_knowledge(self) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM knowledge_cache WHERE expires_at < now()"
            )
            count = int(result.split()[-1])
            logger.info("Cleaned up %d expired knowledge_cache entries", count)
            return count

    async def cleanup_old_jobs(self, retention_days: int = 30) -> int:
        """Delete closed jobs (and their steps/artifacts) older than retention period."""
        async with self._pool.acquire() as conn:
            # Steps and artifacts cascade-delete via FK, but let's be explicit
            result = await conn.execute(
                """
                DELETE FROM jobs
                WHERE status = 'closed'
                  AND closed_at IS NOT NULL
                  AND closed_at < now() - make_interval(days => $1)
                """,
                retention_days,
            )
            count = int(result.split()[-1])
            logger.info("Cleaned up %d old closed jobs (>%d days)", count, retention_days)
            return count

    async def cleanup_old_messages(self, retention_days: int = 90) -> int:
        """Delete old conversation messages beyond retention period."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM conversation_messages
                WHERE created_at < now() - make_interval(days => $1)
                """,
                retention_days,
            )
            count = int(result.split()[-1])
            logger.info("Cleaned up %d old conversation messages (>%d days)", count, retention_days)
            return count

    # ------------------------------------------------------------------
    # Query helpers (API endpoints)
    # ------------------------------------------------------------------

    async def list_jobs(self, status: str = "", limit: int = 20) -> list[dict]:
        async with self._pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    "SELECT * FROM jobs WHERE status = $1 ORDER BY created_at DESC LIMIT $2",
                    status, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT $1",
                    limit,
                )
            return [dict(r) for r in rows]

    async def get_task_activity(self, task_id: UUID, limit: int = 50) -> list[dict]:
        """Get activity feed for a task: jobs + steps ordered by time."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    js.step_id, js.step_index, js.goal, js.agent_id,
                    js.status, js.output_summary, js.started_at, js.completed_at,
                    j.job_id, j.workflow_id, j.status AS job_status
                FROM job_steps js
                JOIN jobs j ON j.job_id = js.job_id
                WHERE j.task_id = $1
                ORDER BY js.created_at DESC
                LIMIT $2
                """,
                task_id, limit,
            )
            return [dict(r) for r in rows]
