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
LOW_RELEVANCE_MERGE_CEILING = 0.35


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
        *,
        dominion_id: str | None = None,
    ) -> list[dict]:
        """Retrieve entries by embedding cosine similarity."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM entries WHERE embedding IS NOT NULL").fetchall()

        scored = []
        for row in rows:
            entry = self._row_to_dict(row)
            if dominion_id and self._tag_value(entry.get("tags") or [], "dominion_id") != dominion_id:
                continue
            emb = _deserialize_embedding(row["embedding"])
            if emb is None:
                continue
            sim = _cosine_similarity(query_embedding, emb)
            if sim >= threshold:
                entry["similarity"] = round(sim, 4)
                scored.append(entry)

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]

    def search_by_tags(self, tags: list[str], limit: int = 50, *, dominion_id: str | None = None) -> list[dict]:
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
            if dominion_id and self._tag_value(entry_tags, "dominion_id") != dominion_id:
                continue
            if tag_set & set(entry_tags):
                results.append(self._row_to_dict(row))
                if len(results) >= limit:
                    break
        return results

    def query(
        self,
        *,
        domain: str | None = None,
        tier: str | None = None,
        since: str | None = None,
        keyword: str | None = None,
        source_type: str | None = None,
        limit: int = 50,
        dominion_id: str | None = None,
    ) -> list[dict]:
        """Best-effort query facade for Console views.

        Memory rows stay schema-light; domain/tier/source_type/dominion_id are
        carried as tags using ``key:value`` pairs.
        """
        fetch = max(int(limit or 50) * 6, 300)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM entries ORDER BY relevance_score DESC, updated_utc DESC LIMIT ?",
                (fetch,),
            ).fetchall()

        keyword_text = str(keyword or "").strip().lower()
        out: list[dict] = []
        for row in rows:
            entry = self._row_to_dict(row)
            tags = entry.get("tags") or []
            if domain and self._tag_value(tags, "domain") != str(domain):
                continue
            if tier and self._tag_value(tags, "tier") != str(tier):
                continue
            if source_type and self._tag_value(tags, "source_type") != str(source_type):
                continue
            if dominion_id and self._tag_value(tags, "dominion_id") != str(dominion_id):
                continue
            if since:
                ts = str(entry.get("updated_utc") or entry.get("created_utc") or "")
                if ts and ts < str(since):
                    continue
            if keyword_text and keyword_text not in str(entry.get("content") or "").lower():
                continue
            out.append(entry)
            if len(out) >= max(1, int(limit or 50)):
                break
        return out

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
        merged = self._merge_similar_low_relevance_entries()
        evicted = self.enforce_capacity()
        return {"decayed": decayed, "merged": merged, "evicted": evicted}

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
        d.update(self._derived_fields(d))
        return d

    def _merge_similar_low_relevance_entries(self) -> int:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM entries WHERE embedding IS NOT NULL AND relevance_score <= ? "
                "ORDER BY relevance_score ASC, updated_utc ASC LIMIT 400",
                (LOW_RELEVANCE_MERGE_CEILING,),
            ).fetchall()
            candidates = [dict(r) for r in rows]
            merged = 0
            consumed: set[str] = set()
            for i, left in enumerate(candidates):
                left_id = str(left.get("entry_id") or "")
                if not left_id or left_id in consumed:
                    continue
                left_emb = _deserialize_embedding(left.get("embedding"))
                if not left_emb:
                    continue
                best_idx = -1
                best_sim = 0.0
                for j in range(i + 1, len(candidates)):
                    right = candidates[j]
                    right_id = str(right.get("entry_id") or "")
                    if not right_id or right_id in consumed:
                        continue
                    right_emb = _deserialize_embedding(right.get("embedding"))
                    if not right_emb:
                        continue
                    sim = _cosine_similarity(left_emb, right_emb)
                    if sim > MERGE_SIMILARITY_THRESHOLD and sim > best_sim:
                        best_sim = sim
                        best_idx = j
                if best_idx < 0:
                    continue
                right = candidates[best_idx]
                right_id = str(right.get("entry_id") or "")
                left_tags = json.loads(left.get("tags") or "[]")
                right_tags = json.loads(right.get("tags") or "[]")
                merged_tags = sorted({str(tag) for tag in left_tags + right_tags if str(tag).strip()})
                snippets = [
                    str(left.get("content") or "").strip(),
                    str(right.get("content") or "").strip(),
                ]
                merged_content = "\n".join(
                    part for part in [
                        "Merged memory summary:",
                        f"- {snippets[0][:240]}",
                        f"- {snippets[1][:240]}",
                    ]
                    if part
                ).strip()
                relevance = max(float(left.get("relevance_score") or 0.0), float(right.get("relevance_score") or 0.0))
                conn.execute(
                    "UPDATE entries SET content=?, tags=?, relevance_score=?, updated_utc=? WHERE entry_id=?",
                    (
                        merged_content,
                        json.dumps(merged_tags, ensure_ascii=False),
                        min(1.0, relevance + 0.05),
                        _utc(),
                        left_id,
                    ),
                )
                conn.execute("DELETE FROM entries WHERE entry_id=?", (right_id,))
                consumed.add(left_id)
                consumed.add(right_id)
                merged += 1
            return merged

    @staticmethod
    def _tag_value(tags: list[str], prefix: str) -> str:
        wanted = f"{prefix}:"
        for tag in tags:
            text = str(tag or "")
            if text.startswith(wanted):
                return text[len(wanted):]
        return ""

    def _derived_fields(self, entry: dict[str, Any]) -> dict[str, Any]:
        tags = entry.get("tags") if isinstance(entry.get("tags"), list) else []
        content = str(entry.get("content") or "")
        return {
            "unit_id": str(entry.get("entry_id") or ""),
            "title": content.splitlines()[0][:80] if content else "",
            "domain": self._tag_value(tags, "domain") or "general",
            "tier": self._tag_value(tags, "tier") or "working",
            "source_type": self._tag_value(tags, "source_type") or str(entry.get("source") or "system"),
            "confidence": round(float(entry.get("relevance_score") or 0.0), 4),
            "dominion_id": self._tag_value(tags, "dominion_id") or "",
        }
