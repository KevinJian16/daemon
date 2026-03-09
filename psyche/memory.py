"""Memory Psyche — factual knowledge storage with embedding-based retrieval."""
from __future__ import annotations

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
    return f"mem_{uuid.uuid4().hex[:12]}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    entry_id        TEXT PRIMARY KEY,
    content         TEXT NOT NULL,
    tags            TEXT NOT NULL DEFAULT '[]',
    embedding       BLOB,
    relevance_score REAL NOT NULL DEFAULT 1.0,
    source          TEXT NOT NULL DEFAULT 'system',
    created_utc     TEXT NOT NULL,
    updated_utc     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entries_relevance ON entries(relevance_score);
CREATE INDEX IF NOT EXISTS idx_entries_updated   ON entries(updated_utc);
"""

CAPACITY_LIMIT = 2000
DECAY_FACTOR = 0.95
SIMILARITY_THRESHOLD = 0.7
MERGE_SIMILARITY_THRESHOLD = 0.92


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


class MemoryPsyche:
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

    def add(
        self,
        content: str,
        tags: list[str] | None = None,
        embedding: list[float] | None = None,
        source: str = "system",
    ) -> str:
        entry_id = _new_id()
        now = _utc()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO entries (entry_id, content, tags, embedding, relevance_score, source, created_utc, updated_utc) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (entry_id, content, json.dumps(tags or []), _serialize_embedding(embedding), 1.0, source, now, now),
            )
        return entry_id

    def upsert(
        self,
        content: str,
        tags: list[str] | None = None,
        embedding: list[float] | None = None,
        source: str = "system",
    ) -> dict:
        """Insert or overwrite conflicting entry (same content match by embedding similarity)."""
        if embedding:
            matches = self.search_by_embedding(embedding, top_k=1, threshold=MERGE_SIMILARITY_THRESHOLD)
            if matches:
                existing = matches[0]
                entry_id = existing["entry_id"]
                now = _utc()
                with self._conn() as conn:
                    conn.execute(
                        "UPDATE entries SET content=?, tags=?, embedding=?, relevance_score=1.0, source=?, updated_utc=? "
                        "WHERE entry_id=?",
                        (content, json.dumps(tags or []), _serialize_embedding(embedding), source, now, entry_id),
                    )
                return {"action": "updated", "entry_id": entry_id}

        entry_id = self.add(content, tags=tags, embedding=embedding, source=source)
        return {"action": "inserted", "entry_id": entry_id}

    def get(self, entry_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM entries WHERE entry_id=?", (entry_id,)).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def delete(self, entry_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM entries WHERE entry_id=?", (entry_id,))
        return cur.rowcount > 0

    def search_by_embedding(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        threshold: float = SIMILARITY_THRESHOLD,
    ) -> list[dict]:
        """Retrieve entries by embedding cosine similarity."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM entries WHERE embedding IS NOT NULL").fetchall()

        scored = []
        for row in rows:
            emb = _deserialize_embedding(row["embedding"])
            if emb is None:
                continue
            sim = _cosine_similarity(query_embedding, emb)
            if sim >= threshold:
                entry = self._row_to_dict(row)
                entry["similarity"] = round(sim, 4)
                scored.append(entry)

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]

    def search_by_tags(self, tags: list[str], limit: int = 50) -> list[dict]:
        """Retrieve entries that contain any of the given tags."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM entries ORDER BY relevance_score DESC, updated_utc DESC LIMIT ?",
                (limit * 3,),
            ).fetchall()

        results = []
        tag_set = set(tags)
        for row in rows:
            entry_tags = json.loads(row["tags"] or "[]")
            if tag_set & set(entry_tags):
                results.append(self._row_to_dict(row))
                if len(results) >= limit:
                    break
        return results

    def touch(self, entry_id: str) -> None:
        """Bump relevance when an entry is referenced."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE entries SET relevance_score = MIN(relevance_score + 0.1, 1.0), updated_utc=? WHERE entry_id=?",
                (_utc(), entry_id),
            )

    def decay_all(self) -> int:
        """Apply relevance decay to all entries. Returns count of decayed entries."""
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE entries SET relevance_score = relevance_score * ? WHERE relevance_score > 0.01",
                (DECAY_FACTOR,),
            )
        return cur.rowcount

    def enforce_capacity(self) -> int:
        """Evict lowest-relevance entries when over capacity limit. Returns evicted count."""
        evicted = 0
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            if total <= CAPACITY_LIMIT:
                return 0
            excess = total - CAPACITY_LIMIT
            rows = conn.execute(
                "SELECT entry_id FROM entries ORDER BY relevance_score ASC, updated_utc ASC LIMIT ?",
                (excess,),
            ).fetchall()
            for row in rows:
                conn.execute("DELETE FROM entries WHERE entry_id=?", (row["entry_id"],))
                evicted += 1
        return evicted

    def distill(self) -> dict:
        """Run decay + capacity enforcement. Called by distill routine."""
        decayed = self.decay_all()
        evicted = self.enforce_capacity()
        return {"decayed": decayed, "evicted": evicted}

    def snapshot(self) -> dict:
        """Export entries for agent consumption (relay routine)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT entry_id, content, tags, relevance_score FROM entries "
                "ORDER BY relevance_score DESC, updated_utc DESC LIMIT 500"
            ).fetchall()
        entries = []
        for r in rows:
            entries.append({
                "entry_id": r["entry_id"],
                "content": r["content"],
                "tags": json.loads(r["tags"] or "[]"),
                "relevance_score": round(float(r["relevance_score"]), 4),
            })
        return {"entries": entries, "exported_utc": _utc()}

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            with_embedding = conn.execute("SELECT COUNT(*) FROM entries WHERE embedding IS NOT NULL").fetchone()[0]
            avg_relevance = conn.execute("SELECT AVG(relevance_score) FROM entries").fetchone()[0]
        return {
            "total_entries": total,
            "with_embedding": with_embedding,
            "avg_relevance": round(float(avg_relevance or 0), 4),
            "capacity_limit": CAPACITY_LIMIT,
        }

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["tags"] = json.loads(d.get("tags") or "[]")
        d.pop("embedding", None)
        return d
