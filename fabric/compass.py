"""Compass Fabric — meta-cognitive knowledge: priorities, quality profiles, resource budgets, preferences."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id(prefix: str = "c") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS priorities (
    domain      TEXT PRIMARY KEY,
    weight      REAL NOT NULL DEFAULT 1.0,
    reason      TEXT,
    updated_utc TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'system'
);

CREATE TABLE IF NOT EXISTS quality_profiles (
    task_type   TEXT PRIMARY KEY,
    rules_json  TEXT NOT NULL,
    updated_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resource_budgets (
    resource_type TEXT PRIMARY KEY,
    daily_limit   REAL NOT NULL,
    current_usage REAL NOT NULL DEFAULT 0,
    reset_utc     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    pref_key    TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_utc TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'user'
);

CREATE TABLE IF NOT EXISTS attention_signals (
    signal_id    TEXT PRIMARY KEY,
    domain       TEXT NOT NULL,
    trend        TEXT NOT NULL,
    severity     TEXT NOT NULL DEFAULT 'normal',
    observed_utc TEXT NOT NULL,
    expires_utc  TEXT
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

CREATE INDEX IF NOT EXISTS idx_signals_domain   ON attention_signals(domain);
CREATE INDEX IF NOT EXISTS idx_signals_severity ON attention_signals(severity);
CREATE INDEX IF NOT EXISTS idx_cv_key           ON config_versions(config_key);
"""

# Bootstrap seed data applied on first run.
BOOTSTRAP_PRIORITIES: list[dict] = [
    {"domain": "ai_research",      "weight": 1.5, "reason": "High relevance to system capability"},
    {"domain": "software_dev",     "weight": 1.3, "reason": "Core operational domain"},
    {"domain": "security",         "weight": 1.2, "reason": "Risk management priority"},
    {"domain": "science",          "weight": 1.0, "reason": "Default"},
    {"domain": "finance",          "weight": 0.9, "reason": "Default"},
    {"domain": "general",          "weight": 0.7, "reason": "Catch-all, lower priority"},
]

BOOTSTRAP_QUALITY_PROFILES: list[dict] = [
    {
        "task_type": "research_report",
        "rules": {
            "min_sections": 3,
            "min_word_count": 800,
            "require_bilingual": True,
            "forbidden_markers": ["<system>", "[INTERNAL]", "DRAFT"],
            "min_domain_coverage": 2,
        },
    },
    {
        "task_type": "daily_brief",
        "rules": {
            "min_sections": 2,
            "min_word_count": 400,
            "require_bilingual": True,
            "forbidden_markers": ["<system>", "[INTERNAL]"],
            "min_items": 5,
        },
    },
    {
        "task_type": "default",
        "rules": {
            "min_sections": 1,
            "min_word_count": 200,
            "require_bilingual": False,
            "forbidden_markers": ["<system>", "[INTERNAL]"],
        },
    },
]

BOOTSTRAP_BUDGETS: list[dict] = [
    {"resource_type": "openai_tokens",     "daily_limit": 500_000},
    {"resource_type": "anthropic_tokens",  "daily_limit": 200_000},
    {"resource_type": "deepseek_tokens",   "daily_limit": 1_000_000},
    {"resource_type": "minimax_tokens",    "daily_limit": 500_000},
    {"resource_type": "concurrent_tasks",  "daily_limit": 10},
]

BOOTSTRAP_PREFERENCES: list[dict] = [
    {"pref_key": "output_language",  "value": "zh",     "source": "default"},
    {"pref_key": "telegram_enabled", "value": "true",   "source": "default"},
    {"pref_key": "pdf_enabled",      "value": "true",   "source": "default"},
    {"pref_key": "learning_rhythm",  "value": "4h",     "source": "default"},
    {"pref_key": "model_primary",    "value": "deepseek", "source": "default"},
]


class CompassFabric:
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

    # ── Priorities ──────────────────────────────────────────────────────────

    def set_priority(self, domain: str, weight: float, reason: str = "", source: str = "system", changed_by: str = "system") -> None:
        now = _utc()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO priorities VALUES (?,?,?,?,?) ON CONFLICT(domain) DO UPDATE SET weight=excluded.weight, reason=excluded.reason, updated_utc=excluded.updated_utc, source=excluded.source",
                (domain, weight, reason, now, source),
            )
            self._version(conn, f"priority.{domain}", {"weight": weight, "reason": reason}, changed_by, reason)

    def get_priorities(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM priorities ORDER BY weight DESC").fetchall()]

    # ── Quality profiles ─────────────────────────────────────────────────────

    def set_quality_profile(self, task_type: str, rules: dict, changed_by: str = "system") -> None:
        now = _utc()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO quality_profiles VALUES (?,?,?) ON CONFLICT(task_type) DO UPDATE SET rules_json=excluded.rules_json, updated_utc=excluded.updated_utc",
                (task_type, json.dumps(rules), now),
            )
            self._version(conn, f"quality.{task_type}", rules, changed_by, None)

    def get_quality_profile(self, task_type: str) -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT rules_json FROM quality_profiles WHERE task_type=?", (task_type,)).fetchone()
            if not row:
                row = conn.execute("SELECT rules_json FROM quality_profiles WHERE task_type='default'").fetchone()
        return json.loads(row["rules_json"]) if row else {}

    # ── Resource budgets ─────────────────────────────────────────────────────

    def get_budget(self, resource_type: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM resource_budgets WHERE resource_type=?", (resource_type,)).fetchone()
        return dict(row) if row else None

    def consume_budget(self, resource_type: str, amount: float) -> bool:
        """Returns False if budget would be exceeded."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM resource_budgets WHERE resource_type=?", (resource_type,)).fetchone()
            if not row:
                return True
            if float(row["current_usage"]) + amount > float(row["daily_limit"]):
                return False
            conn.execute(
                "UPDATE resource_budgets SET current_usage = current_usage + ? WHERE resource_type=?",
                (amount, resource_type),
            )
        return True

    def reset_budgets(self) -> None:
        now = _utc()
        tomorrow = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
        with self._connect() as conn:
            conn.execute("UPDATE resource_budgets SET current_usage=0, reset_utc=?", (tomorrow,))

    def all_budgets(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM resource_budgets").fetchall()]

    def set_budget(self, resource_type: str, daily_limit: float, changed_by: str = "console") -> None:
        now = _utc()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT current_usage, reset_utc FROM resource_budgets WHERE resource_type=?",
                (resource_type,),
            ).fetchone()
            if row:
                current_usage = float(row["current_usage"] or 0)
                reset_utc = str(row["reset_utc"] or now)
            else:
                current_usage = 0.0
                reset_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))

            conn.execute(
                "INSERT INTO resource_budgets VALUES (?,?,?,?) "
                "ON CONFLICT(resource_type) DO UPDATE SET daily_limit=excluded.daily_limit, reset_utc=excluded.reset_utc",
                (resource_type, float(daily_limit), current_usage, reset_utc),
            )
            self._version(
                conn,
                f"budget.{resource_type}",
                {"daily_limit": float(daily_limit), "current_usage": current_usage, "reset_utc": reset_utc},
                changed_by,
                None,
            )

    # ── Preferences ───────────────────────────────────────────────────────────

    def get_pref(self, key: str, default: str = "") -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM preferences WHERE pref_key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_pref(self, key: str, value: str, source: str = "user", changed_by: str = "user") -> None:
        now = _utc()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO preferences VALUES (?,?,?,?) ON CONFLICT(pref_key) DO UPDATE SET value=excluded.value, updated_utc=excluded.updated_utc, source=excluded.source",
                (key, value, now, source),
            )
            self._version(conn, f"pref.{key}", {"value": value}, changed_by, None)

    def all_prefs(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT pref_key, value FROM preferences").fetchall()
        return {r["pref_key"]: r["value"] for r in rows}

    # ── Attention signals ─────────────────────────────────────────────────────

    def add_signal(self, domain: str, trend: str, severity: str = "normal", ttl_hours: int = 72) -> str:
        sid = _new_id("sig")
        now = _utc()
        expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + ttl_hours * 3600))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO attention_signals VALUES (?,?,?,?,?,?)",
                (sid, domain, trend, severity, now, expires),
            )
        return sid

    def active_signals(self) -> list[dict]:
        now = _utc()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM attention_signals WHERE expires_utc IS NULL OR expires_utc > ? ORDER BY observed_utc DESC",
                (now,),
            ).fetchall()
        return [dict(r) for r in rows]

    def expire_signals(self) -> int:
        now = _utc()
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM attention_signals WHERE expires_utc IS NOT NULL AND expires_utc < ?", (now,)
            )
        return cur.rowcount

    # ── Config version history ────────────────────────────────────────────────

    def versions(self, config_key: str, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM config_versions WHERE config_key=? ORDER BY version DESC LIMIT ?",
                (config_key, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def record_config_version(self, config_key: str, value: Any, changed_by: str = "system", reason: str | None = None) -> int:
        with self._connect() as conn:
            return self._version(conn, config_key, value, changed_by, reason)

    def version_value(self, config_key: str, version: int) -> Any | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM config_versions WHERE config_key=? AND version=?",
                (config_key, version),
            ).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["value_json"])
        except Exception:
            return None

    def rollback(self, config_key: str, version: int, changed_by: str = "console") -> bool:
        """Restore a config key to a specific historical version."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM config_versions WHERE config_key=? AND version=?",
                (config_key, version),
            ).fetchone()
            if not row:
                return False
            old_value = json.loads(row["value_json"])

        # Apply rollback based on key type prefix.
        key_parts = config_key.split(".", 1)
        kind = key_parts[0]
        sub = key_parts[1] if len(key_parts) > 1 else ""

        if kind == "priority":
            self.set_priority(sub, old_value["weight"], old_value.get("reason", ""), changed_by=changed_by)
        elif kind == "quality":
            self.set_quality_profile(sub, old_value, changed_by=changed_by)
        elif kind == "pref":
            self.set_pref(sub, old_value["value"], changed_by=changed_by)
        elif kind == "budget":
            self.set_budget(sub, float(old_value.get("daily_limit", 0)), changed_by=changed_by)
        else:
            return False
        return True

    def snapshot(self) -> dict:
        with self._connect() as conn:
            quality_profiles = {
                r["task_type"]: json.loads(r["rules_json"])
                for r in conn.execute("SELECT task_type, rules_json FROM quality_profiles").fetchall()
            }
        return {
            "priorities": self.get_priorities(),
            "quality_profiles": quality_profiles,
            "preferences": self.all_prefs(),
            "attention_signals": self.active_signals(),
            "exported_utc": _utc(),
        }

    def stats(self) -> dict:
        with self._connect() as conn:
            priority_count = conn.execute("SELECT COUNT(*) FROM priorities").fetchone()[0]
            signal_count = conn.execute(
                "SELECT COUNT(*) FROM attention_signals WHERE expires_utc IS NULL OR expires_utc > ?",
                (_utc(),),
            ).fetchone()[0]
            critical_count = conn.execute(
                "SELECT COUNT(*) FROM attention_signals WHERE severity='critical' AND (expires_utc IS NULL OR expires_utc > ?)",
                (_utc(),),
            ).fetchone()[0]
        return {
            "priority_domains": priority_count,
            "active_signals": signal_count,
            "critical_signals": critical_count,
        }
