"""Lore Psyche — experience records from completed Deeds, with embedding-based retrieval."""
from __future__ import annotations

import calendar
import json
import logging
import math
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id() -> str:
    return f"pb_{uuid.uuid4().hex[:12]}"


def _days_since(iso_utc: str | None) -> float:
    if not iso_utc:
        return 999.0
    try:
        ts = calendar.timegm(time.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ"))
        return max(0.0, (time.time() - ts) / 86400.0)
    except Exception:
        return 999.0


SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    record_id           TEXT PRIMARY KEY,
    deed_id             TEXT NOT NULL UNIQUE,
    folio_id            TEXT,
    slip_id             TEXT,
    writ_id             TEXT,
    objective_text      TEXT NOT NULL,
    objective_embedding BLOB,
    dag_budget          INTEGER NOT NULL DEFAULT 6,
    move_count          INTEGER NOT NULL DEFAULT 0,
    plan_structure      TEXT NOT NULL DEFAULT '{}',
    offering_quality    TEXT NOT NULL DEFAULT '{}',
    token_consumption   TEXT NOT NULL DEFAULT '{}',
    success             INTEGER NOT NULL DEFAULT 0,
    duration_s          REAL NOT NULL DEFAULT 0.0,
    user_feedback       TEXT,
    rework_history      TEXT,
    created_utc         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_records_folio_id ON records(folio_id);
CREATE INDEX IF NOT EXISTS idx_records_slip_id ON records(slip_id);
CREATE INDEX IF NOT EXISTS idx_records_dag_budget ON records(dag_budget);
CREATE INDEX IF NOT EXISTS idx_records_success    ON records(success);
CREATE INDEX IF NOT EXISTS idx_records_created    ON records(created_utc);
"""

DECAY_HALFLIFE_DAYS = 90.0


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return dot / (na * nb)


def _serialize_embedding(emb: list[float] | None) -> bytes | None:
    if emb is None:
        return None
    import struct
    return struct.pack(f"{len(emb)}f", *emb)


def _deserialize_embedding(blob: bytes | None) -> list[float] | None:
    if blob is None:
        return None
    import struct
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _recency_score(created_utc: str | None) -> float:
    days = _days_since(created_utc)
    return math.exp(-days * math.log(2) / DECAY_HALFLIFE_DAYS)


def _quality_bonus(offering_quality: dict, success: bool) -> float:
    if not success:
        return 0.0
    scores = [float(v) for v in offering_quality.values() if isinstance(v, (int, float))]
    if not scores:
        return 0.5
    return sum(scores) / len(scores)


class LorePsyche:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            self._ensure_columns(conn)

    def _ensure_columns(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("PRAGMA table_info(records)").fetchall()
        cols = {str(row["name"]) for row in rows}
        if "folio_id" not in cols:
            conn.execute("ALTER TABLE records ADD COLUMN folio_id TEXT")
        if "slip_id" not in cols:
            conn.execute("ALTER TABLE records ADD COLUMN slip_id TEXT")
        if "writ_id" not in cols:
            conn.execute("ALTER TABLE records ADD COLUMN writ_id TEXT")
        if "dag_budget" not in cols:
            conn.execute("ALTER TABLE records ADD COLUMN dag_budget INTEGER NOT NULL DEFAULT 6")

    def record(
        self,
        deed_id: str,
        objective_text: str,
        dag_budget: int,
        move_count: int,
        plan_structure: dict,
        offering_quality: dict,
        token_consumption: dict,
        success: bool,
        duration_s: float,
        user_feedback: dict | None = None,
        rework_history: dict | None = None,
        objective_embedding: list[float] | None = None,
        folio_id: str | None = None,
        slip_id: str | None = None,
        writ_id: str | None = None,
    ) -> str:
        record_id = _new_id()
        now = _utc()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO records "
                "(record_id, deed_id, folio_id, slip_id, writ_id, objective_text, objective_embedding, dag_budget, move_count, "
                "plan_structure, offering_quality, token_consumption, success, duration_s, "
                "user_feedback, rework_history, created_utc) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record_id, deed_id, str(folio_id or ""), str(slip_id or ""), str(writ_id or ""), objective_text,
                    _serialize_embedding(objective_embedding),
                    max(1, int(dag_budget or 1)), move_count,
                    json.dumps(plan_structure, ensure_ascii=False),
                    json.dumps(offering_quality, ensure_ascii=False),
                    json.dumps(token_consumption, ensure_ascii=False),
                    1 if success else 0,
                    duration_s,
                    json.dumps(user_feedback, ensure_ascii=False) if user_feedback else None,
                    json.dumps(rework_history, ensure_ascii=False) if rework_history else None,
                    now,
                ),
            )
        return record_id

    def update_feedback(self, deed_id: str, user_feedback: dict) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE records SET user_feedback=? WHERE deed_id=?",
                (json.dumps(user_feedback, ensure_ascii=False), deed_id),
            )
        return cur.rowcount > 0

    def consult(
        self,
        query_embedding: list[float] | None = None,
        folio_id: str | None = None,
        slip_id: str | None = None,
        writ_id: str | None = None,
        dag_budget: int | None = None,
        top_k: int = 3,
    ) -> list[dict]:
        """Retrieve relevant experience records.

        Score = sim(embedding) * 0.6 + recency * 0.2 + quality_bonus * 0.2.
        """
        with self._conn() as conn:
            if dag_budget is not None:
                rows = conn.execute(
                    "SELECT * FROM records WHERE dag_budget=? ORDER BY created_utc DESC LIMIT 200",
                    (max(1, int(dag_budget)),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM records ORDER BY created_utc DESC LIMIT 200"
                ).fetchall()

        scored = []
        for row in rows:
            rec = self._row_to_dict(row)
            emb = _deserialize_embedding(row["objective_embedding"])

            if query_embedding and emb:
                sim = _cosine_similarity(query_embedding, emb)
            else:
                sim = 0.0

            recency = _recency_score(rec["created_utc"])
            quality = _quality_bonus(rec["offering_quality"], rec["success"])

            score = sim * 0.6 + recency * 0.2 + quality * 0.2
            if folio_id and str(rec.get("folio_id") or "") == str(folio_id):
                score += 0.1
            if slip_id and str(rec.get("slip_id") or "") == str(slip_id):
                score += 0.08
            if writ_id and str(rec.get("writ_id") or "") == str(writ_id):
                score += 0.05
            rec["relevance_score"] = round(score, 4)
            scored.append(rec)

        scored.sort(key=lambda x: x["relevance_score"], reverse=True)
        return scored[:top_k]

    def get(self, deed_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM records WHERE deed_id=?", (deed_id,)).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def delete(self, deed_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM records WHERE deed_id=?", (deed_id,))
        return cur.rowcount > 0

    def list_records(
        self,
        success_only: bool = False,
        folio_id: str | None = None,
        slip_id: str | None = None,
        writ_id: str | None = None,
        dag_budget: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        clauses = []
        params: list[Any] = []
        if dag_budget is not None:
            clauses.append("dag_budget=?")
            params.append(max(1, int(dag_budget)))
        if success_only:
            clauses.append("success=1")
        if folio_id:
            clauses.append("folio_id=?")
            params.append(folio_id)
        if slip_id:
            clauses.append("slip_id=?")
            params.append(slip_id)
        if writ_id:
            clauses.append("writ_id=?")
            params.append(writ_id)

        sql = "SELECT * FROM records"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_utc DESC LIMIT ?"
        params.append(limit)

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def decay(self, stale_days: int = 180) -> dict:
        """Prune stale, low-value records as Lore decay."""
        cutoff_days = max(30, int(stale_days))
        removed = 0
        scanned = 0
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT deed_id, created_utc, success, offering_quality, user_feedback FROM records"
            ).fetchall()
            for row in rows:
                scanned += 1
                age_days = _days_since(str(row["created_utc"] or ""))
                if age_days < cutoff_days:
                    continue
                success = bool(row["success"])
                try:
                    offering_quality = json.loads(row["offering_quality"] or "{}")
                except Exception:
                    offering_quality = {}
                try:
                    user_feedback = json.loads(row["user_feedback"]) if row["user_feedback"] else {}
                except Exception:
                    user_feedback = {}
                quality = _quality_bonus(offering_quality, success)
                feedback_score = float(user_feedback.get("score") or 0.0) if isinstance(user_feedback, dict) else 0.0
                if success and max(quality, feedback_score) >= 0.5:
                    continue
                conn.execute("DELETE FROM records WHERE deed_id=?", (str(row["deed_id"] or ""),))
                removed += 1
        return {"scanned": scanned, "removed": removed, "stale_days": cutoff_days}

    def snapshot(self) -> dict:
        """Export recent successful records for agent consumption."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT record_id, deed_id, folio_id, slip_id, writ_id, objective_text, dag_budget, move_count, success, "
                "offering_quality, duration_s, created_utc "
                "FROM records WHERE success=1 ORDER BY created_utc DESC LIMIT 50"
            ).fetchall()
        records = []
        for r in rows:
            rec = dict(r)
            rec["offering_quality"] = json.loads(rec.get("offering_quality") or "{}")
            records.append(rec)
        return {"records": records, "exported_utc": _utc()}

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
            successes = conn.execute("SELECT COUNT(*) FROM records WHERE success=1").fetchone()[0]
            by_dag_budget = {}
            for row in conn.execute(
                "SELECT dag_budget, COUNT(*) as cnt FROM records GROUP BY dag_budget"
            ).fetchall():
                by_dag_budget[str(row["dag_budget"])] = row["cnt"]
        return {
            "total_records": total,
            "success_count": successes,
            "success_rate": round(successes / max(total, 1), 4),
            "by_dag_budget": by_dag_budget,
        }

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        for json_field in ("plan_structure", "offering_quality", "token_consumption", "user_feedback", "rework_history"):
            val = d.get(json_field)
            if isinstance(val, str):
                try:
                    d[json_field] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    d[json_field] = None
        d["success"] = bool(d.get("success"))
        d.pop("objective_embedding", None)
        return d
