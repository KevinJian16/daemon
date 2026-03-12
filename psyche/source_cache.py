"""SourceCache — external knowledge cache with TTL and trust tiers."""
from __future__ import annotations

import json
import logging
import sqlite3
import struct
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


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
CREATE TABLE IF NOT EXISTS source_chunks (
    chunk_id    TEXT PRIMARY KEY,
    query       TEXT,
    source_url  TEXT,
    source_tier TEXT,
    title       TEXT,
    content     TEXT,
    embedding   BLOB,
    fetched_utc TEXT,
    ttl_hours   INTEGER DEFAULT 168,
    UNIQUE(source_url, chunk_id)
);
"""

# Default source tiers loaded from config/source_tiers.toml
_DEFAULT_TIERS = {
    "tier_a": {"verify_required": False},
    "tier_b": {"verify_required": "cross_check"},
    "tier_c": {"verify_required": "mandatory"},
}


class SourceCache:
    """Cache for external search results. Not a knowledge base — just cache with TTL."""

    CACHE_SIMILARITY_THRESHOLD = 0.9  # Very high: only return near-exact matches

    def __init__(self, db_path: Path, tiers_config: dict | None = None) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._tiers = tiers_config or _DEFAULT_TIERS
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

    def store(
        self,
        *,
        query: str,
        source_url: str,
        source_tier: str,
        title: str,
        content: str,
        embedding: list[float] | None = None,
        ttl_hours: int = 168,
    ) -> str:
        """Store a search result chunk. Returns chunk_id."""
        chunk_id = f"src_{uuid.uuid4().hex[:12]}"
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO source_chunks
                    (chunk_id, query, source_url, source_tier, title, content,
                     embedding, fetched_utc, ttl_hours)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (chunk_id, query, source_url, source_tier, title, content,
                 _serialize_embedding(embedding), _utc(), ttl_hours),
            )
        return chunk_id

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        """Find cached results by embedding similarity."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM source_chunks WHERE embedding IS NOT NULL"
            ).fetchall()
        scored: list[tuple[float, dict]] = []
        for row in rows:
            emb = _deserialize_embedding(row["embedding"])
            if emb is None:
                continue
            sim = _cosine_similarity(query_embedding, emb)
            if sim >= self.CACHE_SIMILARITY_THRESHOLD:
                scored.append((sim, dict(row)))
        scored.sort(key=lambda x: -x[0])
        results = []
        for sim, row in scored[:top_k]:
            row.pop("embedding", None)
            row["similarity"] = round(sim, 4)
            results.append(row)
        return results

    def expire(self) -> int:
        """Remove expired entries. Called by tend routine."""
        now_ts = time.time()
        with self._conn() as conn:
            rows = conn.execute("SELECT chunk_id, fetched_utc, ttl_hours FROM source_chunks").fetchall()
            expired_ids: list[str] = []
            for row in rows:
                fetched = row["fetched_utc"]
                ttl = int(row["ttl_hours"] or 168)
                try:
                    import calendar
                    ts = calendar.timegm(time.strptime(fetched, "%Y-%m-%dT%H:%M:%SZ"))
                    if ts + ttl * 3600 < now_ts:
                        expired_ids.append(row["chunk_id"])
                except Exception:
                    continue
            for cid in expired_ids:
                conn.execute("DELETE FROM source_chunks WHERE chunk_id=?", (cid,))
        return len(expired_ids)

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM source_chunks").fetchone()[0]
            with_emb = conn.execute("SELECT COUNT(*) FROM source_chunks WHERE embedding IS NOT NULL").fetchone()[0]
        return {"total_chunks": total, "with_embedding": with_emb}
