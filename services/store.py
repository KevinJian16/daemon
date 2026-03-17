"""PG data layer (Store) — asyncpg-based persistent storage for daemon objects.

Reference: SYSTEM_DESIGN_REFERENCE.md Appendix C
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
        # §3.5: Same Task max 1 non-closed Job constraint.
        # Enforce at the DB layer as a second gate (scenes.py also checks before calling).
        already_active = await self.has_active_job_for_task(task_id)
        if already_active:
            raise ValueError(
                f"Task {task_id} already has a non-closed Job. "
                "Cannot create a second Job until the existing one is closed, failed, or cancelled."
            )

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

    async def has_active_job_for_task(self, task_id: UUID) -> bool:
        """Check if a Task already has a non-closed (running) Job (§3.5).

        Returns True if there is at least one Job with status NOT IN
        ('closed', 'failed', 'cancelled').
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM jobs
                    WHERE task_id = $1
                      AND status NOT IN ('closed', 'failed', 'cancelled')
                )
                """,
                task_id,
            )
            return bool(row)

    async def get_last_final_artifact_for_task(self, task_id: UUID) -> dict | None:
        """Get the most recent final artifact across all Jobs for a Task (§3.7.1).

        Used for Job->Job artifact chain injection.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT a.* FROM job_artifacts a
                JOIN jobs j ON j.job_id = a.job_id
                WHERE j.task_id = $1 AND a.is_final = TRUE
                ORDER BY a.created_at DESC LIMIT 1
                """,
                task_id,
            )
            return dict(row) if row else None

    async def get_completed_tasks_for_project(self, project_id: UUID) -> list[dict]:
        """Get completed Tasks for a project — for project-level context assembly (§3.6.1)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT t.task_id, t.title, t.created_at
                FROM daemon_tasks t
                WHERE t.project_id = $1
                  AND EXISTS (
                    SELECT 1 FROM jobs j
                    WHERE j.task_id = t.task_id
                      AND j.status = 'closed'
                      AND j.sub_status IN ('completed', 'succeeded')
                  )
                ORDER BY t.created_at
                """,
                project_id,
            )
            return [dict(r) for r in rows]

    async def get_project_goal(self, project_id: UUID) -> str | None:
        """Get project goal/title from daemon_tasks or Plane (§3.6.1).

        For now, derives from the first task title in the project.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchval(
                """
                SELECT title FROM daemon_tasks
                WHERE project_id = $1
                ORDER BY created_at ASC LIMIT 1
                """,
                project_id,
            )
            return str(row) if row else None

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
        skill_used: str | None = None,
    ) -> dict:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO job_steps
                    (job_id, step_index, goal, agent_id, execution_type,
                     model_hint, depends_on, input_artifacts, skill_used)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
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
                skill_used,
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

    async def get_artifact(self, artifact_id: UUID) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM job_artifacts WHERE artifact_id = $1", artifact_id
            )
            return dict(row) if row else None

    async def get_final_artifact_for_job(self, job_id: UUID) -> dict | None:
        """Get the most recent final artifact for a Job."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM job_artifacts
                WHERE job_id = $1 AND is_final = TRUE
                ORDER BY created_at DESC LIMIT 1
                """,
                job_id,
            )
            return dict(row) if row else None

    async def mark_artifact_final(self, artifact_id: UUID) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE job_artifacts SET is_final = TRUE WHERE artifact_id = $1 RETURNING *",
                artifact_id,
            )
            return dict(row) if row else None

    async def mark_artifact_gdrive_synced(self, artifact_id: UUID) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE job_artifacts SET gdrive_synced = TRUE WHERE artifact_id = $1 RETURNING *",
                artifact_id,
            )
            return dict(row) if row else None

    async def mark_artifact_key(self, artifact_id: UUID) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE job_artifacts SET key_marked = TRUE WHERE artifact_id = $1 RETURNING *",
                artifact_id,
            )
            return dict(row) if row else None

    async def get_artifacts_for_task(self, task_id: UUID) -> list[dict]:
        """Get all artifacts across all Jobs for a Task."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT a.* FROM job_artifacts a
                JOIN jobs j ON j.job_id = a.job_id
                WHERE j.task_id = $1
                ORDER BY a.created_at
                """,
                task_id,
            )
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # conversation_messages (L1 — layer 1)
    # ------------------------------------------------------------------

    async def save_message(
        self, scene: str, role: str, content: str,
        token_count: int | None = None, source: str = "desktop",
    ) -> dict:
        """Save a conversation message with source tracking (§4.10 sync)."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO conversation_messages (scene, role, content, token_count, source)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                scene,
                role,
                content,
                token_count,
                source,
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

    @staticmethod
    def _ttl_for_tier(source_tier: str) -> timedelta:
        """Auto-compute TTL from source tier (§5.6.1).

        Reads TTL days from config/source_tiers.toml [ttl] section.
        Tier mapping:
          tier1 = 7 days  (web pages)
          tier2 = 30 days (docs)
          tier3 = 90 days (research)

        Falls back to hard-coded defaults if the file is missing or
        the section is absent.
        """
        # Default TTLs (days) if config is unavailable
        default_ttl: dict[str, int] = {"tier1": 7, "tier2": 30, "tier3": 90}

        tier_lower = source_tier.lower().strip()
        try:
            config_path = Path(__file__).parent.parent / "config" / "source_tiers.toml"
            if config_path.exists():
                try:
                    import tomllib  # Python 3.11+
                except ImportError:
                    try:
                        import tomli as tomllib  # type: ignore[no-redef]
                    except ImportError:
                        tomllib = None  # type: ignore[assignment]

                if tomllib is not None:
                    with config_path.open("rb") as f:
                        data = tomllib.load(f)
                    ttl_section = data.get("ttl", {})
                    if tier_lower in ttl_section:
                        return timedelta(days=int(ttl_section[tier_lower]))
        except Exception:
            pass

        days = default_ttl.get(tier_lower, 30)
        return timedelta(days=days)

    async def upsert_knowledge(
        self,
        source_url: str,
        source_tier: str,
        expires_at: datetime | None = None,
        *,
        project_id: UUID | None = None,
        title: str | None = None,
        content_summary: str | None = None,
        ragflow_doc_id: str | None = None,
        embedding: list[float] | None = None,
    ) -> dict:
        """Upsert a knowledge_cache entry.

        If expires_at is not provided, it is auto-computed from source_tier
        using the TTL tiers defined in config/source_tiers.toml (§5.6.1).
        """
        if expires_at is None:
            expires_at = datetime.now(UTC) + self._ttl_for_tier(source_tier)

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

    async def search_knowledge(
        self,
        query: str,
        *,
        project_id: UUID | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Search knowledge_cache with project_id-first fallback (§5.6.1).

        Priority:
          1. If project_id supplied: return project-scoped results first, then
             pad with global (project_id IS NULL) results up to `limit`.
          2. If no project_id: return global results only.

        Only non-expired entries are returned.
        """
        async with self._pool.acquire() as conn:
            if project_id is not None:
                # Project-scoped first
                project_rows = await conn.fetch(
                    """
                    SELECT * FROM knowledge_cache
                    WHERE project_id = $1
                      AND expires_at > now()
                      AND (title ILIKE $2 OR content_summary ILIKE $2)
                    ORDER BY expires_at DESC
                    LIMIT $3
                    """,
                    project_id,
                    f"%{query}%",
                    limit,
                )
                results = [dict(r) for r in project_rows]

                remaining = limit - len(results)
                if remaining > 0:
                    # Pad with global entries not already in results
                    existing_ids = {r["cache_id"] for r in results}
                    global_rows = await conn.fetch(
                        """
                        SELECT * FROM knowledge_cache
                        WHERE project_id IS NULL
                          AND expires_at > now()
                          AND (title ILIKE $1 OR content_summary ILIKE $1)
                        ORDER BY expires_at DESC
                        LIMIT $2
                        """,
                        f"%{query}%",
                        remaining + len(existing_ids),  # over-fetch, then filter
                    )
                    for r in global_rows:
                        d = dict(r)
                        if d["cache_id"] not in existing_ids:
                            results.append(d)
                            if len(results) >= limit:
                                break

                return results[:limit]

            else:
                # Global only
                rows = await conn.fetch(
                    """
                    SELECT * FROM knowledge_cache
                    WHERE project_id IS NULL
                      AND expires_at > now()
                      AND (title ILIKE $1 OR content_summary ILIKE $1)
                    ORDER BY expires_at DESC
                    LIMIT $2
                    """,
                    f"%{query}%",
                    limit,
                )
                return [dict(r) for r in rows]

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
    # Cross-scene decision query (§3.3.1)
    # ------------------------------------------------------------------

    async def search_decisions_cross_scene(
        self,
        query: str | None = None,
        *,
        project_id: UUID | None = None,
        tags: list[str] | None = None,
        scenes: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query conversation_decisions across multiple scenes (§3.3.1).

        Unlike get_recent_decisions() which is single-scene, this method
        searches all scenes (or the specified subset) and supports filtering
        by project_id and/or tags.

        Args:
            query:      Optional substring to match in content or context_summary.
            project_id: Limit to decisions attached to this project.
            tags:       Limit to decisions that contain ALL supplied tags.
            scenes:     Limit to these scene names (default: all 4 scenes).
            limit:      Max results to return (default 50).

        Returns:
            List of decision dicts ordered newest first.
        """
        clauses: list[str] = []
        params: list = []
        idx = 1

        if scenes:
            placeholders = ", ".join(f"${i}" for i in range(idx, idx + len(scenes)))
            clauses.append(f"scene IN ({placeholders})")
            params.extend(scenes)
            idx += len(scenes)

        if project_id is not None:
            clauses.append(f"project_id = ${idx}")
            params.append(project_id)
            idx += 1

        if tags:
            # All supplied tags must be present in the tags array column
            for tag in tags:
                clauses.append(f"${idx} = ANY(tags)")
                params.append(tag)
                idx += 1

        if query:
            clauses.append(f"(content ILIKE ${idx} OR context_summary ILIKE ${idx})")
            params.append(f"%{query}%")
            idx += 1

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        sql = f"""
        SELECT * FROM conversation_decisions
        {where}
        ORDER BY created_at DESC
        LIMIT ${idx}
        """

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]

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
        """Get activity feed for a task: jobs + steps in D.4 format (§4.5).

        Each record has:
          type: user_message | agent_result | job_boundary | step_status | action_record
          actor: agent_id or "system"
          job_id: UUID string of the owning Job
          metadata: additional context dict
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    js.step_id, js.step_index, js.goal, js.agent_id,
                    js.status, js.output_summary, js.started_at, js.completed_at,
                    j.job_id, j.workflow_id, j.status AS job_status,
                    j.sub_status AS job_sub_status
                FROM job_steps js
                JOIN jobs j ON j.job_id = js.job_id
                WHERE j.task_id = $1
                ORDER BY js.created_at DESC
                LIMIT $2
                """,
                task_id, limit,
            )
            records = []
            for r in rows:
                row = dict(r)
                job_id_str = str(row.get("job_id") or "")
                agent_id = str(row.get("agent_id") or "system")
                step_status = str(row.get("status") or "")
                job_status = str(row.get("job_status") or "")
                job_sub_status = str(row.get("job_sub_status") or "")

                # Determine D.4 record type
                if step_status in ("completed", "failed", "error"):
                    record_type = "agent_result"
                elif step_status in ("running", "started", "pending"):
                    record_type = "step_status"
                elif job_sub_status in ("completed", "failed", "cancelled"):
                    record_type = "job_boundary"
                else:
                    record_type = "step_status"

                records.append({
                    "type": record_type,
                    "actor": agent_id,
                    "job_id": job_id_str,
                    "step_id": str(row.get("step_id") or ""),
                    "step_index": row.get("step_index"),
                    "goal": str(row.get("goal") or ""),
                    "status": step_status,
                    "output_summary": str(row.get("output_summary") or ""),
                    "started_at": row.get("started_at").isoformat() if row.get("started_at") else None,
                    "completed_at": row.get("completed_at").isoformat() if row.get("completed_at") else None,
                    "metadata": {
                        "workflow_id": str(row.get("workflow_id") or ""),
                        "job_status": job_status,
                        "job_sub_status": job_sub_status,
                    },
                })
            return records
