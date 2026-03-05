"""Memory Fabric — structured storage for factual knowledge (signals, events, knowledge units)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
import math
import calendar
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id(prefix: str = "u") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS units (
    unit_id      TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    domain       TEXT NOT NULL,
    tier         TEXT NOT NULL DEFAULT 'standard',
    confidence   REAL NOT NULL DEFAULT 1.0,
    summary_zh   TEXT,
    summary_en   TEXT,
    status       TEXT NOT NULL DEFAULT 'active',
    source_type  TEXT NOT NULL DEFAULT 'synthetic',
    source_agent TEXT,
    created_utc  TEXT NOT NULL,
    updated_utc  TEXT NOT NULL,
    expires_utc  TEXT
);

CREATE TABLE IF NOT EXISTS sources (
    source_id  TEXT PRIMARY KEY,
    unit_id    TEXT NOT NULL REFERENCES units(unit_id),
    provider   TEXT NOT NULL,
    url        TEXT,
    tier       TEXT,
    raw_hash   TEXT
);

CREATE TABLE IF NOT EXISTS audit (
    audit_id   TEXT PRIMARY KEY,
    action     TEXT NOT NULL,
    actor      TEXT NOT NULL DEFAULT 'system',
    timestamp  TEXT NOT NULL,
    detail     TEXT
);

CREATE TABLE IF NOT EXISTS usage (
    usage_id    TEXT PRIMARY KEY,
    unit_id     TEXT NOT NULL REFERENCES units(unit_id),
    task_id     TEXT,
    playbook_id TEXT,
    outcome     TEXT,
    used_utc    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS links (
    link_id     TEXT PRIMARY KEY,
    from_id     TEXT NOT NULL REFERENCES units(unit_id),
    to_id       TEXT NOT NULL REFERENCES units(unit_id),
    relation    TEXT NOT NULL,
    confidence  REAL NOT NULL DEFAULT 1.0,
    created_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_units_domain   ON units(domain);
CREATE INDEX IF NOT EXISTS idx_units_tier     ON units(tier);
CREATE INDEX IF NOT EXISTS idx_units_status   ON units(status);
CREATE INDEX IF NOT EXISTS idx_units_created  ON units(created_utc);
CREATE INDEX IF NOT EXISTS idx_sources_unit   ON sources(unit_id);
CREATE INDEX IF NOT EXISTS idx_usage_unit     ON usage(unit_id);
CREATE INDEX IF NOT EXISTS idx_links_from     ON links(from_id);
CREATE INDEX IF NOT EXISTS idx_links_to       ON links(to_id);
"""

TIER_TTL_DAYS: dict[str, int | None] = {
    "breaking": 7,
    "standard": 90,
    "deep": 365,
    "permanent": None,
}

SOURCE_TYPES = {"empirical", "synthetic", "collected", "human"}
SOURCE_PRIORITY = {"human": 0, "empirical": 1, "synthetic": 2, "collected": 3}


def _normalize_source_type(v: Any, fallback: str = "synthetic") -> str:
    s = str(v or "").strip().lower()
    if s in SOURCE_TYPES:
        return s
    return fallback if fallback in SOURCE_TYPES else "synthetic"


class MemoryFabric:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Backward-compatible alias for legacy callers/tests.
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        return self._conn()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            cols = {
                str(r["name"])
                for r in conn.execute("PRAGMA table_info(units)").fetchall()
            }
            if "source_type" not in cols:
                try:
                    conn.execute("ALTER TABLE units ADD COLUMN source_type TEXT NOT NULL DEFAULT 'synthetic'")
                except sqlite3.OperationalError:
                    pass
            if "source_agent" not in cols:
                try:
                    conn.execute("ALTER TABLE units ADD COLUMN source_agent TEXT")
                except sqlite3.OperationalError:
                    pass
            try:
                conn.execute("CREATE INDEX IF NOT EXISTS idx_units_source ON units(source_type)")
            except sqlite3.OperationalError:
                pass

    def _audit(self, conn: sqlite3.Connection, action: str, actor: str, detail: Any = None) -> None:
        conn.execute(
            "INSERT INTO audit VALUES (?,?,?,?,?)",
            (_new_id("a"), action, actor, _utc(), json.dumps(detail) if detail is not None else None),
        )

    def intake(
        self,
        units: list[dict],
        actor: str = "spine.intake",
        source_type: str | None = None,
        source_agent: str | None = None,
    ) -> dict:
        """Batch-write raw knowledge units. Skips duplicates by raw_hash."""
        inserted = []
        skipped = []
        now = _utc()
        default_source_type = _normalize_source_type(
            source_type,
            fallback="collected" if actor.startswith("spine.intake") else "synthetic",
        )
        default_source_agent = str(source_agent or ("collect" if actor.startswith("spine.intake") else actor)).strip()
        with self._conn() as conn:
            for raw in units:
                title = str(raw.get("title") or "").strip()
                domain = str(raw.get("domain") or "general").strip()
                tier = str(raw.get("tier") or "standard").strip()
                if tier not in TIER_TTL_DAYS:
                    tier = "standard"
                summary_zh = raw.get("summary_zh") or raw.get("summary")
                summary_en = raw.get("summary_en")
                provider = str(raw.get("provider") or "unknown")
                url = raw.get("url")
                unit_source_type = _normalize_source_type(raw.get("source_type"), fallback=default_source_type)
                unit_source_agent = str(raw.get("source_agent") or default_source_agent).strip()
                raw_content = json.dumps(raw, sort_keys=True)
                raw_hash = hashlib.sha256(raw_content.encode()).hexdigest()

                existing = conn.execute(
                    "SELECT unit_id FROM sources WHERE raw_hash=? LIMIT 1", (raw_hash,)
                ).fetchone()
                if existing:
                    skipped.append(raw_hash[:8])
                    continue

                ttl = TIER_TTL_DAYS.get(tier)
                expires = None
                if ttl is not None:
                    if unit_source_type == "collected":
                        ttl = max(1, int(math.ceil(ttl * 0.5)))
                    expires = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ",
                        time.gmtime(time.time() + ttl * 86400),
                    )

                uid = _new_id("u")
                conn.execute(
                    """INSERT INTO units
                       (unit_id, title, domain, tier, confidence, summary_zh, summary_en,
                        status, source_type, source_agent, created_utc, updated_utc, expires_utc)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (uid, title, domain, tier,
                     float(raw.get("confidence", 1.0)),
                     summary_zh, summary_en, "active", unit_source_type, unit_source_agent, now, now, expires),
                )
                conn.execute(
                    "INSERT INTO sources VALUES (?,?,?,?,?,?)",
                    (_new_id("s"), uid, provider, url, tier, raw_hash),
                )
                inserted.append(uid)
            self._audit(conn, "intake", actor, {"inserted": len(inserted), "skipped": len(skipped)})
        return {"inserted": len(inserted), "skipped": len(skipped), "unit_ids": inserted}

    def query(
        self,
        domain: str | None = None,
        tier: str | None = None,
        since: str | None = None,
        keyword: str | None = None,
        source_type: str | None = None,
        status: str = "active",
        limit: int = 100,
    ) -> list[dict]:
        clauses = ["u.status = ?"]
        params: list[Any] = [status]
        if domain:
            clauses.append("u.domain = ?")
            params.append(domain)
        if tier:
            clauses.append("u.tier = ?")
            params.append(tier)
        if since:
            clauses.append("u.created_utc >= ?")
            params.append(since)
        if keyword:
            clauses.append("(u.title LIKE ? OR u.summary_zh LIKE ? OR u.summary_en LIKE ?)")
            k = f"%{keyword}%"
            params.extend([k, k, k])
        if source_type:
            st = _normalize_source_type(source_type, fallback="")
            if st:
                clauses.append("u.source_type = ?")
                params.append(st)
        params.append(limit)

        sql = f"""
            SELECT u.*, GROUP_CONCAT(s.provider, ',') AS providers
            FROM units u
            LEFT JOIN sources s ON s.unit_id = u.unit_id
            WHERE {' AND '.join(clauses)}
            GROUP BY u.unit_id
            ORDER BY
                CASE COALESCE(u.source_type,'synthetic')
                    WHEN 'human' THEN 0
                    WHEN 'empirical' THEN 1
                    WHEN 'synthetic' THEN 2
                    WHEN 'collected' THEN 3
                    ELSE 4
                END,
                u.created_utc DESC
            LIMIT ?
        """
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get(self, unit_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM units WHERE unit_id=?", (unit_id,)).fetchone()
            if not row:
                return None
            unit = dict(row)
            unit["sources"] = [
                dict(r) for r in conn.execute("SELECT * FROM sources WHERE unit_id=?", (unit_id,)).fetchall()
            ]
            unit["usage"] = [
                dict(r) for r in conn.execute("SELECT * FROM usage WHERE unit_id=?", (unit_id,)).fetchall()
            ]
            unit["links_out"] = [
                dict(r) for r in conn.execute("SELECT * FROM links WHERE from_id=?", (unit_id,)).fetchall()
            ]
            unit["links_in"] = [
                dict(r) for r in conn.execute("SELECT * FROM links WHERE to_id=?", (unit_id,)).fetchall()
            ]
            unit["audit"] = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM audit WHERE detail LIKE ? ORDER BY timestamp DESC LIMIT 30",
                    (f"%{unit_id}%",),
                ).fetchall()
            ]
        return unit

    def distill(self, unit_id: str, updates: dict, actor: str = "spine.distill") -> bool:
        """Update a unit's content after semantic distillation."""
        allowed = {"title", "summary_zh", "summary_en", "confidence", "status", "tier"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return False
        fields["updated_utc"] = _utc()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        with self._conn() as conn:
            conn.execute(f"UPDATE units SET {set_clause} WHERE unit_id=?", [*fields.values(), unit_id])
            self._audit(conn, "distill", actor, {"unit_id": unit_id, "fields": list(fields.keys())})
        return True

    def link(self, from_id: str, to_id: str, relation: str, confidence: float = 1.0) -> str:
        """Create a semantic link between two units."""
        lid = _new_id("l")
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO links VALUES (?,?,?,?,?,?)",
                (lid, from_id, to_id, relation, confidence, _utc()),
            )
        return lid

    def record_usage(self, unit_id: str, task_id: str, playbook_id: str | None, outcome: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO usage VALUES (?,?,?,?,?,?)",
                (_new_id("ug"), unit_id, task_id, playbook_id, outcome, _utc()),
            )

    def expire(self) -> dict:
        """Mark expired units as archived."""
        now = _utc()
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE units SET status='archived', updated_utc=? WHERE expires_utc IS NOT NULL AND expires_utc < ? AND status='active'",
                (now, now),
            )
            count = cur.rowcount
            if count:
                self._audit(conn, "expire", "spine.tend", {"archived": count})
        return {"archived": count}

    def apply_source_ttl_policy(self, actor: str = "spine.tend") -> dict:
        """Archive collected units earlier (50% TTL window vs empirical)."""
        archived = 0
        now_ts = time.time()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT unit_id, source_type, tier, created_utc FROM units WHERE status='active'"
            ).fetchall()
            for row in rows:
                st = _normalize_source_type(row["source_type"], fallback="synthetic")
                if st != "collected":
                    continue
                tier = str(row["tier"] or "standard").strip()
                ttl_days = TIER_TTL_DAYS.get(tier)
                if ttl_days is None:
                    continue
                created = str(row["created_utc"] or "")
                try:
                    created_ts = float(calendar.timegm(time.strptime(created, "%Y-%m-%dT%H:%M:%SZ")))
                except Exception:
                    continue
                policy_ttl_s = max(1, int(math.ceil(ttl_days * 0.5 * 86400)))
                if now_ts - created_ts < policy_ttl_s:
                    continue
                conn.execute(
                    "UPDATE units SET status='archived', updated_utc=? WHERE unit_id=?",
                    (_utc(), row["unit_id"]),
                )
                archived += 1
            if archived:
                self._audit(conn, "expire_source_policy", actor, {"archived": archived, "source_type": "collected"})
        return {"archived": archived, "source_type": "collected"}

    def snapshot(self) -> dict:
        """Export a read-only snapshot for Agent consumption."""
        with self._conn() as conn:
            units = [dict(r) for r in conn.execute(
                "SELECT unit_id, title, domain, tier, confidence, summary_zh, summary_en, source_type, source_agent FROM units WHERE status='active' ORDER BY created_utc DESC LIMIT 500"
            ).fetchall()]
            links = [dict(r) for r in conn.execute(
                "SELECT from_id, to_id, relation, confidence FROM links LIMIT 2000"
            ).fetchall()]
        return {"units": units, "links": links, "exported_utc": _utc()}

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM units WHERE status='active'").fetchone()[0]
            by_domain = {
                r["domain"]: r["cnt"]
                for r in conn.execute(
                    "SELECT domain, COUNT(*) as cnt FROM units WHERE status='active' GROUP BY domain"
                ).fetchall()
            }
            by_tier = {
                r["tier"]: r["cnt"]
                for r in conn.execute(
                    "SELECT tier, COUNT(*) as cnt FROM units WHERE status='active' GROUP BY tier"
                ).fetchall()
            }
            by_source_type = {
                r["source_type"]: r["cnt"]
                for r in conn.execute(
                    "SELECT source_type, COUNT(*) as cnt FROM units WHERE status='active' GROUP BY source_type"
                ).fetchall()
            }
            usage_count = conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
            link_count = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        return {
            "total_active": total,
            "by_domain": by_domain,
            "by_tier": by_tier,
            "by_source_type": by_source_type,
            "usage_records": usage_count,
            "link_count": link_count,
        }
