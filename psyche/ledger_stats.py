"""LedgerStats — mechanical statistics for DAG/Folio templates, skill stats, agent stats."""
from __future__ import annotations

import json
import logging
import sqlite3
import struct
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id(prefix: str = "tpl") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _serialize_embedding(emb: list[float] | None) -> bytes | None:
    if emb is None:
        return None
    return struct.pack(f"{len(emb)}f", *emb)


def _deserialize_embedding(blob: bytes | None) -> list[float] | None:
    if blob is None:
        return None
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS dag_templates (
    template_id     TEXT PRIMARY KEY,
    objective_text  TEXT,
    objective_emb   BLOB,
    dag_structure   TEXT,
    eval_summary    TEXT,
    times_validated INTEGER DEFAULT 1,
    avg_tokens      REAL,
    avg_duration_s  REAL,
    avg_rework      REAL,
    last_updated    TEXT
);

CREATE TABLE IF NOT EXISTS folio_templates (
    template_id     TEXT PRIMARY KEY,
    objective_text  TEXT,
    objective_emb   BLOB,
    structure       TEXT,
    slip_count      INTEGER,
    times_validated INTEGER DEFAULT 1,
    last_updated    TEXT
);

CREATE TABLE IF NOT EXISTS skill_stats (
    skill_name      TEXT PRIMARY KEY,
    invocations     INTEGER DEFAULT 0,
    accepted        INTEGER DEFAULT 0,
    rejected        INTEGER DEFAULT 0,
    avg_tokens      REAL DEFAULT 0,
    reject_feedback TEXT,
    updated_utc     TEXT
);

CREATE TABLE IF NOT EXISTS agent_stats (
    agent_role      TEXT,
    task_cluster_id TEXT,
    invocations     INTEGER DEFAULT 0,
    accepted        INTEGER DEFAULT 0,
    avg_tokens      REAL DEFAULT 0,
    avg_duration_s  REAL DEFAULT 0,
    updated_utc     TEXT,
    PRIMARY KEY (agent_role, task_cluster_id)
);
"""

# Default planning templates for cold-start
DEFAULT_PLANNING_TEMPLATES = {
    "research": {"moves": ["scout", "sage", "scribe"], "est_tokens": 4000},
    "code": {"moves": ["scout", "artificer"], "est_tokens": 3000},
    "writing": {"moves": ["scout", "scribe"], "est_tokens": 3500},
    "analysis": {"moves": ["scout", "sage", "arbiter", "scribe"], "est_tokens": 5000},
}

_SIMILARITY_THRESHOLD = 0.85


class LedgerStats:
    """Mechanical statistics — zero LLM cost. All learning is SQL aggregation."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── DAG Templates ─────────────────────────────────────────────────────────

    def merge_dag_template(
        self,
        *,
        objective_text: str,
        objective_emb: list[float] | None,
        dag_structure: dict | Any,
        eval_summary: str,
        total_tokens: int,
        total_duration_s: float,
        rework_count: int,
    ) -> str:
        """Merge an accepted deed into dag_templates. Returns template_id."""
        existing = self._find_similar_dag(objective_emb)
        now = _utc()

        if existing:
            row = existing
            tid = row["template_id"]
            n = row["times_validated"]
            # Rolling average update
            new_avg_tokens = (row["avg_tokens"] * n + total_tokens) / (n + 1)
            new_avg_duration = (row["avg_duration_s"] * n + total_duration_s) / (n + 1)
            new_avg_rework = (row["avg_rework"] * n + rework_count) / (n + 1)
            # Append eval summary
            old_eval = row["eval_summary"] or ""
            combined_eval = f"{old_eval}\n---\n{eval_summary}".strip() if old_eval else eval_summary
            # Keep eval bounded
            if len(combined_eval) > 2000:
                combined_eval = combined_eval[-2000:]

            with self._conn() as conn:
                conn.execute(
                    """UPDATE dag_templates SET
                        times_validated = times_validated + 1,
                        avg_tokens = ?, avg_duration_s = ?, avg_rework = ?,
                        eval_summary = ?, dag_structure = ?, last_updated = ?
                    WHERE template_id = ?""",
                    (new_avg_tokens, new_avg_duration, new_avg_rework,
                     combined_eval, json.dumps(dag_structure, ensure_ascii=False),
                     now, tid),
                )
            return tid
        else:
            tid = _new_id("dag")
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO dag_templates
                        (template_id, objective_text, objective_emb, dag_structure,
                         eval_summary, times_validated, avg_tokens, avg_duration_s,
                         avg_rework, last_updated)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)""",
                    (tid, objective_text[:500], _serialize_embedding(objective_emb),
                     json.dumps(dag_structure, ensure_ascii=False),
                     eval_summary, float(total_tokens), total_duration_s,
                     float(rework_count), now),
                )
            return tid

    def _find_similar_dag(self, query_emb: list[float] | None) -> dict | None:
        if query_emb is None:
            return None
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM dag_templates WHERE objective_emb IS NOT NULL"
            ).fetchall()
        best_sim = 0.0
        best_row = None
        for row in rows:
            emb = _deserialize_embedding(row["objective_emb"])
            if emb is None:
                continue
            sim = _cosine_similarity(query_emb, emb)
            if sim > best_sim:
                best_sim = sim
                best_row = dict(row)
        if best_sim >= _SIMILARITY_THRESHOLD and best_row:
            return best_row
        return None

    def similar_dag_templates(self, objective_embedding: list[float], top_k: int = 3) -> list[dict]:
        """Find most similar DAG templates for planning."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM dag_templates WHERE objective_emb IS NOT NULL"
            ).fetchall()
        scored: list[tuple[float, dict]] = []
        for row in rows:
            emb = _deserialize_embedding(row["objective_emb"])
            if emb is None:
                continue
            sim = _cosine_similarity(objective_embedding, emb)
            if sim >= _SIMILARITY_THRESHOLD:
                scored.append((sim, dict(row)))
        scored.sort(key=lambda x: (-x[0], -x[1].get("times_validated", 0)))
        results = []
        for sim, row in scored[:top_k]:
            row.pop("objective_emb", None)
            row["similarity"] = round(sim, 4)
            try:
                row["dag_structure"] = json.loads(row["dag_structure"]) if isinstance(row["dag_structure"], str) else row["dag_structure"]
            except Exception:
                pass
            results.append(row)
        return results

    # ── Folio Templates ───────────────────────────────────────────────────────

    def merge_folio_template(
        self,
        *,
        objective_text: str,
        objective_emb: list[float] | None,
        structure: dict | Any,
        slip_count: int,
    ) -> str:
        """Merge an archived folio into folio_templates. Returns template_id."""
        existing = self._find_similar_folio(objective_emb)
        now = _utc()

        if existing:
            tid = existing["template_id"]
            with self._conn() as conn:
                conn.execute(
                    """UPDATE folio_templates SET
                        times_validated = times_validated + 1,
                        structure = ?, slip_count = ?, last_updated = ?
                    WHERE template_id = ?""",
                    (json.dumps(structure, ensure_ascii=False), slip_count, now, tid),
                )
            return tid
        else:
            tid = _new_id("fol")
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO folio_templates
                        (template_id, objective_text, objective_emb, structure,
                         slip_count, times_validated, last_updated)
                    VALUES (?, ?, ?, ?, ?, 1, ?)""",
                    (tid, objective_text[:500], _serialize_embedding(objective_emb),
                     json.dumps(structure, ensure_ascii=False), slip_count, now),
                )
            return tid

    def _find_similar_folio(self, query_emb: list[float] | None) -> dict | None:
        if query_emb is None:
            return None
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM folio_templates WHERE objective_emb IS NOT NULL"
            ).fetchall()
        best_sim = 0.0
        best_row = None
        for row in rows:
            emb = _deserialize_embedding(row["objective_emb"])
            if emb is None:
                continue
            sim = _cosine_similarity(query_emb, emb)
            if sim > best_sim:
                best_sim = sim
                best_row = dict(row)
        if best_sim >= _SIMILARITY_THRESHOLD and best_row:
            return best_row
        return None

    def similar_folio_templates(self, objective_embedding: list[float], top_k: int = 3) -> list[dict]:
        """Find most similar Folio templates."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM folio_templates WHERE objective_emb IS NOT NULL"
            ).fetchall()
        scored: list[tuple[float, dict]] = []
        for row in rows:
            emb = _deserialize_embedding(row["objective_emb"])
            if emb is None:
                continue
            sim = _cosine_similarity(objective_embedding, emb)
            if sim >= _SIMILARITY_THRESHOLD:
                scored.append((sim, dict(row)))
        scored.sort(key=lambda x: (-x[0], -x[1].get("times_validated", 0)))
        results = []
        for sim, row in scored[:top_k]:
            row.pop("objective_emb", None)
            row["similarity"] = round(sim, 4)
            try:
                row["structure"] = json.loads(row["structure"]) if isinstance(row["structure"], str) else row["structure"]
            except Exception:
                pass
            results.append(row)
        return results

    # ── Skill Stats ───────────────────────────────────────────────────────────

    def update_skill_stats(self, plan: dict, *, accepted: bool) -> None:
        """Update skill invocation stats from a deed's plan."""
        moves = plan.get("moves") or plan.get("graph", {}).get("moves") or []
        skills_used: set[str] = set()
        for move in moves:
            if not isinstance(move, dict):
                continue
            skill = str(move.get("skill") or move.get("tool") or "").strip()
            if skill:
                skills_used.add(skill)
        now = _utc()
        with self._conn() as conn:
            for skill in skills_used:
                conn.execute(
                    """INSERT INTO skill_stats (skill_name, invocations, accepted, rejected, updated_utc)
                    VALUES (?, 1, ?, ?, ?)
                    ON CONFLICT(skill_name) DO UPDATE SET
                        invocations = invocations + 1,
                        accepted = accepted + ?,
                        rejected = rejected + ?,
                        updated_utc = ?""",
                    (skill, int(accepted), int(not accepted), now,
                     int(accepted), int(not accepted), now),
                )

    def update_agent_stats(self, move_results: list[dict], *, accepted: bool) -> None:
        """Update per-agent stats from move results."""
        now = _utc()
        with self._conn() as conn:
            for mr in move_results:
                if not isinstance(mr, dict):
                    continue
                role = str(mr.get("agent") or mr.get("role") or "").strip()
                if not role:
                    continue
                tokens = int(mr.get("tokens_used") or 0)
                duration = float(mr.get("duration_s") or mr.get("elapsed_s") or 0)
                cluster = "general"  # Default cluster; refined by embedding later
                conn.execute(
                    """INSERT INTO agent_stats
                        (agent_role, task_cluster_id, invocations, accepted, avg_tokens, avg_duration_s, updated_utc)
                    VALUES (?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(agent_role, task_cluster_id) DO UPDATE SET
                        invocations = invocations + 1,
                        accepted = accepted + ?,
                        avg_tokens = (avg_tokens * (invocations - 1) + ?) / invocations,
                        avg_duration_s = (avg_duration_s * (invocations - 1) + ?) / invocations,
                        updated_utc = ?""",
                    (role, cluster, int(accepted), float(tokens), duration, now,
                     int(accepted), float(tokens), duration, now),
                )

    # ── Planning queries ──────────────────────────────────────────────────────

    def agent_performance(self, agent_role: str, cluster_id: str | None = None) -> dict:
        with self._conn() as conn:
            if cluster_id:
                row = conn.execute(
                    "SELECT * FROM agent_stats WHERE agent_role=? AND task_cluster_id=?",
                    (agent_role, cluster_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """SELECT agent_role, '' as task_cluster_id,
                        SUM(invocations) as invocations, SUM(accepted) as accepted,
                        AVG(avg_tokens) as avg_tokens, AVG(avg_duration_s) as avg_duration_s,
                        MAX(updated_utc) as updated_utc
                    FROM agent_stats WHERE agent_role=?""",
                    (agent_role,),
                ).fetchone()
        if not row or not row["invocations"]:
            return {"agent_role": agent_role, "invocations": 0}
        return {
            "agent_role": agent_role,
            "invocations": row["invocations"],
            "success_rate": round(row["accepted"] / max(row["invocations"], 1), 3),
            "avg_tokens": round(row["avg_tokens"] or 0, 1),
            "avg_duration_s": round(row["avg_duration_s"] or 0, 1),
        }

    def skill_health(self, skill_name: str) -> dict:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM skill_stats WHERE skill_name=?", (skill_name,)).fetchone()
        if not row:
            return {"skill_name": skill_name, "invocations": 0}
        inv = row["invocations"]
        rej = row["rejected"]
        needs_review = bool(inv >= 5 and rej / max(inv, 1) > 0.20)
        return {
            "skill_name": skill_name,
            "invocations": inv,
            "accept_rate": round(row["accepted"] / max(inv, 1), 3),
            "needs_review": needs_review,
            "recent_rejections": json.loads(row["reject_feedback"]) if row["reject_feedback"] else [],
        }

    def skills_needing_review(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM skill_stats
                WHERE invocations >= 5 AND CAST(rejected AS REAL) / invocations > 0.20"""
            ).fetchall()
        return [
            {
                "skill_name": row["skill_name"],
                "invocations": row["invocations"],
                "rejected": row["rejected"],
                "reject_rate": round(row["rejected"] / max(row["invocations"], 1), 3),
            }
            for row in rows
        ]

    def planning_hints(self, objective_embedding: list[float]) -> dict:
        """Comprehensive planning query for counsel."""
        dag_templates = self.similar_dag_templates(objective_embedding, top_k=3)
        folio_templates = self.similar_folio_templates(objective_embedding, top_k=2)

        est_tokens = 0
        est_duration = 0.0
        confidence = 0.0
        if dag_templates:
            best = dag_templates[0]
            est_tokens = int(best.get("avg_tokens") or 0)
            est_duration = float(best.get("avg_duration_s") or 0)
            confidence = min(1.0, best.get("times_validated", 0) / 10)

        return {
            "dag_templates": dag_templates,
            "folio_templates": folio_templates,
            "est_tokens": est_tokens,
            "est_duration": round(est_duration, 1),
            "confidence": round(confidence, 2),
        }

    def global_planning_hints(self) -> dict:
        """Global summary for relay snapshot (no embedding needed)."""
        with self._conn() as conn:
            dag_count = conn.execute("SELECT COUNT(*) FROM dag_templates").fetchone()[0]
            folio_count = conn.execute("SELECT COUNT(*) FROM folio_templates").fetchone()[0]
            top_dags = conn.execute(
                "SELECT template_id, objective_text, times_validated, avg_tokens FROM dag_templates ORDER BY times_validated DESC LIMIT 5"
            ).fetchall()
        return {
            "dag_template_count": dag_count,
            "folio_template_count": folio_count,
            "top_dag_templates": [dict(r) for r in top_dags],
            "generated_utc": _utc(),
        }

    # ── Aggregate queries for witness ─────────────────────────────────────────

    def recent_deeds(self, days: int = 7) -> list[dict]:
        """Return recent dag_templates updates as proxy for deed history."""
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - days * 86400),
        )
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM dag_templates WHERE last_updated >= ? ORDER BY last_updated DESC",
                (cutoff,),
            ).fetchall()
        return [
            {
                "template_id": row["template_id"],
                "objective_text": row["objective_text"],
                "times_validated": row["times_validated"],
                "avg_tokens": row["avg_tokens"],
                "avg_duration_s": row["avg_duration_s"],
                "total_tokens_sum": int((row["avg_tokens"] or 0) * (row["times_validated"] or 1)),
                "total_duration_s": float((row["avg_duration_s"] or 0) * (row["times_validated"] or 1)),
                "accepted": True,
            }
            for row in rows
        ]

    def agent_summary(self, days: int = 7) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT agent_role,
                    SUM(invocations) as total_inv, SUM(accepted) as total_acc,
                    AVG(avg_tokens) as avg_tok, AVG(avg_duration_s) as avg_dur
                FROM agent_stats GROUP BY agent_role"""
            ).fetchall()
        return [
            {
                "agent_role": row["agent_role"],
                "invocations": row["total_inv"],
                "success_rate": round(row["total_acc"] / max(row["total_inv"], 1), 3),
                "avg_tokens": round(row["avg_tok"] or 0, 1),
                "avg_duration_s": round(row["avg_dur"] or 0, 1),
            }
            for row in rows
        ]
