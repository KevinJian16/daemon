"""Instinct Psyche — global preferences, resource rations, and configuration versioning."""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id(prefix: str = "c") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS preferences (
    pref_key      TEXT PRIMARY KEY,
    value         TEXT NOT NULL,
    confidence    REAL NOT NULL DEFAULT 0.0,
    sample_count  INTEGER NOT NULL DEFAULT 0,
    updated_utc   TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT 'default'
);

CREATE TABLE IF NOT EXISTS resource_rations (
    resource_type TEXT PRIMARY KEY,
    daily_limit   REAL NOT NULL,
    current_usage REAL NOT NULL DEFAULT 0,
    reset_utc     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config_versions (
    cv_id       TEXT PRIMARY KEY,
    config_key  TEXT NOT NULL,
    version     INTEGER NOT NULL,
    value_json  TEXT NOT NULL,
    changed_utc TEXT NOT NULL,
    changed_by  TEXT NOT NULL DEFAULT 'system',
    reason      TEXT
);

CREATE INDEX IF NOT EXISTS idx_cv_key ON config_versions(config_key);
"""

CONFIDENCE_THRESHOLD = 10

BOOTSTRAP_PREFERENCES: list[dict] = [
    {"pref_key": "require_bilingual",    "value": "true",     "source": "default"},
    {"pref_key": "default_depth",        "value": "study",    "source": "default"},
    {"pref_key": "default_format",       "value": "markdown", "source": "default"},
    {"pref_key": "default_language",     "value": "bilingual","source": "default"},
    {"pref_key": "retinue_size_n",       "value": "24",       "source": "default"},
    {"pref_key": "provider_daily_limits","value": "{\"minimax\":20000000,\"qwen\":10000000,\"zhipu\":5000000,\"deepseek\":5000000}", "source": "default"},
    {"pref_key": "deed_ration_ratio",    "value": "0.75",     "source": "default"},
    {"pref_key": "output_languages",     "value": "[\"zh\",\"en\"]", "source": "default"},
    {"pref_key": "telegram_enabled",     "value": "true",     "source": "default"},
    {"pref_key": "pdf_enabled",          "value": "true",     "source": "default"},
]

BOOTSTRAP_RATIONS: list[dict] = [
    {"resource_type": "minimax_tokens",    "daily_limit": 20_000_000},
    {"resource_type": "qwen_tokens",       "daily_limit": 10_000_000},
    {"resource_type": "zhipu_tokens",      "daily_limit": 5_000_000},
    {"resource_type": "deepseek_tokens",   "daily_limit": 5_000_000},
    {"resource_type": "concurrent_deeds",  "daily_limit": 10},
]


class InstinctPsyche:
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
            self._seed_defaults(conn)

    def _seed_defaults(self, conn: sqlite3.Connection) -> None:
        now = _utc()
        for p in BOOTSTRAP_PREFERENCES:
            conn.execute(
                "INSERT OR IGNORE INTO preferences (pref_key, value, confidence, sample_count, updated_utc, source) "
                "VALUES (?,?,0.0,0,?,?)",
                (p["pref_key"], str(p["value"]), now, str(p.get("source", "default"))),
            )
        legacy_pool = conn.execute(
            "SELECT value FROM preferences WHERE pref_key='pool_size_n'"
        ).fetchone()
        retinue_size = conn.execute(
            "SELECT value FROM preferences WHERE pref_key='retinue_size_n'"
        ).fetchone()
        if legacy_pool and not retinue_size:
            conn.execute(
                "INSERT OR IGNORE INTO preferences (pref_key, value, confidence, sample_count, updated_utc, source) "
                "VALUES (?,?,0.0,0,?,?)",
                ("retinue_size_n", str(legacy_pool["value"]), now, "migration"),
            )
        tomorrow = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
        for b in BOOTSTRAP_RATIONS:
            conn.execute(
                "INSERT OR IGNORE INTO resource_rations (resource_type, daily_limit, current_usage, reset_utc) "
                "VALUES (?,?,0,?)",
                (b["resource_type"], float(b["daily_limit"]), tomorrow),
            )

    def _version(self, conn: sqlite3.Connection, key: str, value: Any, changed_by: str, reason: str | None) -> int:
        cur_ver = conn.execute(
            "SELECT MAX(version) FROM config_versions WHERE config_key=?", (key,)
        ).fetchone()[0]
        next_ver = int(cur_ver or 0) + 1
        conn.execute(
            "INSERT INTO config_versions VALUES (?,?,?,?,?,?,?)",
            (_new_id("cv"), key, next_ver, json.dumps(value), _utc(), changed_by, reason),
        )
        return next_ver

    # ── Preferences ───────────────────────────────────────────────────────────

    def get_pref(self, key: str, default: str = "") -> str:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM preferences WHERE pref_key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_pref(self, key: str, value: str, source: str = "user", changed_by: str = "user") -> None:
        now = _utc()
        with self._conn() as conn:
            existing = conn.execute("SELECT sample_count FROM preferences WHERE pref_key=?", (key,)).fetchone()
            sample_count = int(existing["sample_count"] or 0) + 1 if existing else 1
            confidence = min(sample_count / CONFIDENCE_THRESHOLD, 1.0)
            conn.execute(
                "INSERT INTO preferences VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(pref_key) DO UPDATE SET value=excluded.value, confidence=excluded.confidence, "
                "sample_count=excluded.sample_count, updated_utc=excluded.updated_utc, source=excluded.source",
                (key, value, confidence, sample_count, now, source),
            )
            self._version(conn, f"pref.{key}", {"value": value}, changed_by, None)

    def observe_pref(self, key: str, observed_value: str) -> None:
        """Record an observation that updates confidence without changing the value directly."""
        with self._conn() as conn:
            row = conn.execute("SELECT value, sample_count FROM preferences WHERE pref_key=?", (key,)).fetchone()
            if not row:
                return
            sample_count = int(row["sample_count"] or 0) + 1
            confidence = min(sample_count / CONFIDENCE_THRESHOLD, 1.0)
            conn.execute(
                "UPDATE preferences SET sample_count=?, confidence=?, updated_utc=? WHERE pref_key=?",
                (sample_count, confidence, _utc(), key),
            )

    def get_pref_with_confidence(self, key: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM preferences WHERE pref_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def all_prefs(self) -> dict[str, str]:
        with self._conn() as conn:
            rows = conn.execute("SELECT pref_key, value FROM preferences").fetchall()
        return {r["pref_key"]: r["value"] for r in rows}

    def all_prefs_detailed(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM preferences ORDER BY pref_key").fetchall()
        return [dict(r) for r in rows]

    # ── Resource rations ─────────────────────────────────────────────────────

    def get_ration(self, resource_type: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM resource_rations WHERE resource_type=?", (resource_type,)).fetchone()
        return dict(row) if row else None

    def consume_ration(self, resource_type: str, amount: float) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM resource_rations WHERE resource_type=?", (resource_type,)).fetchone()
            if not row:
                return True
            if float(row["current_usage"]) + amount > float(row["daily_limit"]):
                return False
            conn.execute(
                "UPDATE resource_rations SET current_usage = current_usage + ? WHERE resource_type=?",
                (amount, resource_type),
            )
        return True

    def reset_rations(self) -> None:
        tomorrow = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
        with self._conn() as conn:
            conn.execute("UPDATE resource_rations SET current_usage=0, reset_utc=?", (tomorrow,))

    def all_rations(self) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM resource_rations").fetchall()]

    def set_ration(self, resource_type: str, daily_limit: float, changed_by: str = "console") -> None:
        now = _utc()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT current_usage, reset_utc FROM resource_rations WHERE resource_type=?",
                (resource_type,),
            ).fetchone()
            if row:
                current_usage = float(row["current_usage"] or 0)
                reset_utc = str(row["reset_utc"] or now)
            else:
                current_usage = 0.0
                reset_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))

            conn.execute(
                "INSERT INTO resource_rations VALUES (?,?,?,?) "
                "ON CONFLICT(resource_type) DO UPDATE SET daily_limit=excluded.daily_limit, reset_utc=excluded.reset_utc",
                (resource_type, float(daily_limit), current_usage, reset_utc),
            )
            self._version(conn, f"ration.{resource_type}", {"daily_limit": float(daily_limit)}, changed_by, None)

    # ── Config version history ────────────────────────────────────────────────

    def versions(self, config_key: str, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM config_versions WHERE config_key=? ORDER BY version DESC LIMIT ?",
                (config_key, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def record_config_version(self, config_key: str, value: Any, changed_by: str = "system", reason: str | None = None) -> int:
        with self._conn() as conn:
            return self._version(conn, config_key, value, changed_by, reason)

    def rollback(self, config_key: str, version: int, changed_by: str = "console") -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value_json FROM config_versions WHERE config_key=? AND version=?",
                (config_key, version),
            ).fetchone()
            if not row:
                return False
            old_value = json.loads(row["value_json"])

        key_parts = config_key.split(".", 1)
        kind = key_parts[0]
        sub = key_parts[1] if len(key_parts) > 1 else ""

        if kind == "pref":
            self.set_pref(sub, old_value["value"], changed_by=changed_by)
        elif kind == "ration":
            self.set_ration(sub, float(old_value.get("daily_limit", 0)), changed_by=changed_by)
        else:
            return False
        return True

    # ── Snapshot & Stats ──────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "preferences": self.all_prefs(),
            "rations": self.all_rations(),
            "exported_utc": _utc(),
        }

    def stats(self) -> dict:
        with self._conn() as conn:
            pref_count = conn.execute("SELECT COUNT(*) FROM preferences").fetchone()[0]
            ration_count = conn.execute("SELECT COUNT(*) FROM resource_rations").fetchone()[0]
        return {
            "preference_count": pref_count,
            "ration_count": ration_count,
        }
