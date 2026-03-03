"""Memory Fabric — structured storage for factual knowledge (signals, events, knowledge units)."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


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


class MemoryFabric:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _audit(self, conn: sqlite3.Connection, action: str, actor: str, detail: Any = None) -> None:
        conn.execute(
            "INSERT INTO audit VALUES (?,?,?,?,?)",
            (_new_id("a"), action, actor, _utc(), json.dumps(detail) if detail is not None else None),
        )

    def intake(self, units: list[dict], actor: str = "spine.intake") -> dict:
        """Batch-write raw knowledge units. Skips duplicates by raw_hash."""
        inserted = []
        skipped = []
        now = _utc()
        with self._connect() as conn:
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
                    expires = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ",
                        time.gmtime(time.time() + ttl * 86400),
                    )

                uid = _new_id("u")
                conn.execute(
                    """INSERT INTO units
                       (unit_id, title, domain, tier, confidence, summary_zh, summary_en,
                        status, created_utc, updated_utc, expires_utc)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (uid, title, domain, tier,
                     float(raw.get("confidence", 1.0)),
                     summary_zh, summary_en, "active", now, now, expires),
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
        params.append(limit)

        sql = f"""
            SELECT u.*, GROUP_CONCAT(s.provider, ',') AS providers
            FROM units u
            LEFT JOIN sources s ON s.unit_id = u.unit_id
            WHERE {' AND '.join(clauses)}
            GROUP BY u.unit_id
            ORDER BY u.created_utc DESC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get(self, unit_id: str) -> dict | None:
        with self._connect() as conn:
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
        return unit

    def distill(self, unit_id: str, updates: dict, actor: str = "spine.distill") -> bool:
        """Update a unit's content after semantic distillation."""
        allowed = {"title", "summary_zh", "summary_en", "confidence", "status", "tier"}
        fields = {k: v for k, v in updates.items() if k in allowed}
        if not fields:
            return False
        fields["updated_utc"] = _utc()
        set_clause = ", ".join(f"{k}=?" for k in fields)
        with self._connect() as conn:
            conn.execute(f"UPDATE units SET {set_clause} WHERE unit_id=?", [*fields.values(), unit_id])
            self._audit(conn, "distill", actor, {"unit_id": unit_id, "fields": list(fields.keys())})
        return True

    def link(self, from_id: str, to_id: str, relation: str, confidence: float = 1.0) -> str:
        """Create a semantic link between two units."""
        lid = _new_id("l")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO links VALUES (?,?,?,?,?,?)",
                (lid, from_id, to_id, relation, confidence, _utc()),
            )
        return lid

    def record_usage(self, unit_id: str, task_id: str, playbook_id: str | None, outcome: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO usage VALUES (?,?,?,?,?,?)",
                (_new_id("ug"), unit_id, task_id, playbook_id, outcome, _utc()),
            )

    def expire(self) -> dict:
        """Mark expired units as archived."""
        now = _utc()
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE units SET status='archived', updated_utc=? WHERE expires_utc IS NOT NULL AND expires_utc < ? AND status='active'",
                (now, now),
            )
            count = cur.rowcount
            if count:
                self._audit(conn, "expire", "spine.tend", {"archived": count})
        return {"archived": count}

    def snapshot(self) -> dict:
        """Export a read-only snapshot for Agent consumption."""
        with self._connect() as conn:
            units = [dict(r) for r in conn.execute(
                "SELECT unit_id, title, domain, tier, confidence, summary_zh, summary_en FROM units WHERE status='active' ORDER BY created_utc DESC LIMIT 500"
            ).fetchall()]
            links = [dict(r) for r in conn.execute(
                "SELECT from_id, to_id, relation, confidence FROM links LIMIT 2000"
            ).fetchall()]
        return {"units": units, "links": links, "exported_utc": _utc()}

    def stats(self) -> dict:
        with self._connect() as conn:
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
            usage_count = conn.execute("SELECT COUNT(*) FROM usage").fetchone()[0]
            link_count = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
        return {
            "total_active": total,
            "by_domain": by_domain,
            "by_tier": by_tier,
            "usage_records": usage_count,
            "link_count": link_count,
        }
