"""Playbook Fabric — procedural knowledge: DAG methods, strategies, evaluations."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id(prefix: str = "m") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS methods (
    method_id    TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    category     TEXT NOT NULL DEFAULT 'dag_pattern',
    description  TEXT,
    spec_json    TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'candidate',
    version      INTEGER NOT NULL DEFAULT 1,
    success_rate REAL,
    total_runs   INTEGER NOT NULL DEFAULT 0,
    created_utc      TEXT NOT NULL,
    promoted_utc     TEXT,
    retired_utc      TEXT
);

CREATE TABLE IF NOT EXISTS versions (
    version_id    TEXT PRIMARY KEY,
    method_id     TEXT NOT NULL REFERENCES methods(method_id),
    version       INTEGER NOT NULL,
    spec_json     TEXT NOT NULL,
    created_utc   TEXT NOT NULL,
    change_reason TEXT
);

CREATE TABLE IF NOT EXISTS evaluations (
    eval_id      TEXT PRIMARY KEY,
    method_id    TEXT NOT NULL REFERENCES methods(method_id),
    task_id      TEXT,
    outcome      TEXT NOT NULL,
    score        REAL,
    detail_json  TEXT,
    analyzed     INTEGER NOT NULL DEFAULT 0,
    evaluated_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_methods_status   ON methods(status);
CREATE INDEX IF NOT EXISTS idx_methods_category ON methods(category);
CREATE INDEX IF NOT EXISTS idx_evals_method     ON evaluations(method_id);
CREATE INDEX IF NOT EXISTS idx_evals_analyzed   ON evaluations(analyzed);
CREATE INDEX IF NOT EXISTS idx_evals_outcome    ON evaluations(outcome);

-- V2 Strategy Layer tables.

CREATE TABLE IF NOT EXISTS semantic_clusters (
    cluster_id       TEXT PRIMARY KEY,
    display_name     TEXT NOT NULL,
    task_type_compat TEXT,
    created_utc      TEXT NOT NULL,
    updated_utc      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_candidates (
    strategy_id      TEXT PRIMARY KEY,
    cluster_id       TEXT NOT NULL REFERENCES semantic_clusters(cluster_id),
    stage            TEXT NOT NULL DEFAULT 'candidate',
    spec_json        TEXT NOT NULL,
    global_score     REAL,
    score_components TEXT,
    sample_n         INTEGER NOT NULL DEFAULT 0,
    created_utc      TEXT NOT NULL,
    updated_utc      TEXT NOT NULL,
    promoted_utc     TEXT,
    retired_utc      TEXT
);

CREATE TABLE IF NOT EXISTS strategy_experiments (
    experiment_id    TEXT PRIMARY KEY,
    strategy_id      TEXT NOT NULL REFERENCES strategy_candidates(strategy_id),
    task_id          TEXT NOT NULL,
    cluster_id       TEXT NOT NULL,
    is_shadow        INTEGER NOT NULL DEFAULT 0,
    score_components TEXT,
    global_score     REAL,
    outcome          TEXT,
    created_utc      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_promotions (
    promotion_id     TEXT PRIMARY KEY,
    strategy_id      TEXT NOT NULL REFERENCES strategy_candidates(strategy_id),
    cluster_id       TEXT NOT NULL,
    decision         TEXT NOT NULL,
    prev_stage       TEXT NOT NULL,
    next_stage       TEXT NOT NULL,
    reason           TEXT,
    decided_by       TEXT NOT NULL DEFAULT 'auto',
    decided_utc      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sc_cluster  ON strategy_candidates(cluster_id);
CREATE INDEX IF NOT EXISTS idx_sc_stage    ON strategy_candidates(stage);
CREATE INDEX IF NOT EXISTS idx_se_strategy ON strategy_experiments(strategy_id);
CREATE INDEX IF NOT EXISTS idx_se_cluster  ON strategy_experiments(cluster_id);
CREATE INDEX IF NOT EXISTS idx_sp_strategy ON strategy_promotions(strategy_id);
"""

# Bootstrap DAG templates registered as active methods on first run.
BOOTSTRAP_METHODS: list[dict] = [
    {
        "name": "research_report",
        "category": "dag_pattern",
        "description": "Full research pipeline: collect → analyze → review → render",
        "spec": {
            "steps_template": [
                {"id": "collect", "agent": "collect", "depends_on": []},
                {"id": "analyze", "agent": "analyze", "depends_on": ["collect"]},
                {"id": "review",  "agent": "review",  "depends_on": ["analyze"]},
                {"id": "render",  "agent": "render",  "depends_on": ["review"]},
                {"id": "apply",   "agent": "apply",   "depends_on": ["render"]},
            ],
            "concurrency": {"max_parallel_steps": 4},
            "rework_budget": 2,
            "rework_strategy": "error_code_based",
        },
    },
    {
        "name": "knowledge_synthesis",
        "category": "dag_pattern",
        "description": "Synthesize existing memory into structured knowledge",
        "spec": {
            "steps_template": [
                {"id": "collect",  "agent": "collect",  "depends_on": []},
                {"id": "analyze1", "agent": "analyze",  "depends_on": ["collect"]},
                {"id": "analyze2", "agent": "analyze",  "depends_on": ["collect"]},
                {"id": "build",    "agent": "build",    "depends_on": ["analyze1", "analyze2"]},
                {"id": "review",   "agent": "review",   "depends_on": ["build"]},
                {"id": "render",   "agent": "render",   "depends_on": ["review"]},
                {"id": "apply",    "agent": "apply",    "depends_on": ["render"]},
            ],
            "concurrency": {"max_parallel_steps": 4},
            "rework_budget": 1,
            "rework_strategy": "error_code_based",
        },
    },
    {
        "name": "dev_project",
        "category": "dag_pattern",
        "description": "Software development: plan → build → review → apply",
        "spec": {
            "steps_template": [
                {"id": "plan",   "agent": "router",  "depends_on": []},
                {"id": "build",  "agent": "build",   "depends_on": ["plan"]},
                {"id": "review", "agent": "review",  "depends_on": ["build"]},
                {"id": "apply",  "agent": "apply",   "depends_on": ["review"]},
            ],
            "concurrency": {"max_parallel_steps": 2},
            "rework_budget": 2,
            "rework_strategy": "error_code_based",
        },
    },
    {
        "name": "personal_plan",
        "category": "dag_pattern",
        "description": "Personal planning and task management",
        "spec": {
            "steps_template": [
                {"id": "collect", "agent": "collect", "depends_on": []},
                {"id": "analyze", "agent": "analyze", "depends_on": ["collect"]},
                {"id": "render",  "agent": "render",  "depends_on": ["analyze"]},
                {"id": "apply",   "agent": "apply",   "depends_on": ["render"]},
            ],
            "concurrency": {"max_parallel_steps": 2},
            "rework_budget": 1,
            "rework_strategy": "error_code_based",
        },
    },
]


class PlaybookFabric:
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

    def register(self, name: str, category: str, spec: dict, description: str = "", status: str = "candidate") -> str:
        """Register a new method or bump version if name already exists."""
        now = _utc()
        with self._connect() as conn:
            existing = conn.execute("SELECT method_id, version FROM methods WHERE name=?", (name,)).fetchone()
            if existing:
                mid = existing["method_id"]
                new_ver = int(existing["version"]) + 1
                conn.execute(
                    "UPDATE methods SET spec_json=?, version=?, description=? WHERE method_id=?",
                    (json.dumps(spec), new_ver, description, mid),
                )
                conn.execute(
                    "INSERT INTO versions VALUES (?,?,?,?,?,?)",
                    (_new_id("v"), mid, new_ver, json.dumps(spec), now, "re-registered"),
                )
                return mid

            mid = _new_id("m")
            conn.execute(
                """INSERT INTO methods
                   (method_id, name, category, description, spec_json, status, version, total_runs, created_utc)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (mid, name, category, description, json.dumps(spec), status, 1, 0, now),
            )
            conn.execute(
                "INSERT INTO versions VALUES (?,?,?,?,?,?)",
                (_new_id("v"), mid, 1, json.dumps(spec), now, "initial"),
            )
        return mid

    def evaluate(self, method_id: str, task_id: str | None, outcome: str, score: float | None = None, detail: dict | None = None) -> str:
        """Record one execution result for a method."""
        eid = _new_id("e")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO evaluations VALUES (?,?,?,?,?,?,?,?)",
                (eid, method_id, task_id, outcome, score, json.dumps(detail) if detail else None, 0, _utc()),
            )
            conn.execute(
                "UPDATE methods SET total_runs = total_runs + 1 WHERE method_id=?", (method_id,)
            )
        return eid

    def consult(self, task_type: str | None = None, category: str = "dag_pattern") -> list[dict]:
        """Return active methods sorted by success_rate for planning."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT method_id, name, category, description, spec_json, success_rate, total_runs, version
                   FROM methods WHERE status='active' AND category=?
                   ORDER BY COALESCE(success_rate, 0.5) DESC, total_runs DESC
                   LIMIT 10""",
                (category,),
            ).fetchall()
        results = []
        for r in rows:
            m = dict(r)
            m["spec"] = json.loads(m.pop("spec_json"))
            results.append(m)
        return results

    def list_methods(self, status: str | None = None, category: str | None = None, limit: int = 100) -> list[dict]:
        clauses = []
        params: list[Any] = []
        if status:
            clauses.append("status=?")
            params.append(status)
        if category:
            clauses.append("category=?")
            params.append(category)

        sql = "SELECT method_id, name, category, description, spec_json, status, success_rate, total_runs, version FROM methods"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY COALESCE(success_rate, 0.0) DESC, total_runs DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["spec"] = json.loads(item.pop("spec_json"))
            out.append(item)
        return out

    def get(self, method_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM methods WHERE method_id=?", (method_id,)).fetchone()
            if not row:
                return None
            m = dict(row)
            m["spec"] = json.loads(m.pop("spec_json"))
            m["evaluations"] = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM evaluations WHERE method_id=? ORDER BY evaluated_utc DESC LIMIT 50",
                    (method_id,),
                ).fetchall()
            ]
            m["versions"] = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM versions WHERE method_id=? ORDER BY version DESC",
                    (method_id,),
                ).fetchall()
            ]
        return m

    def promote(self, method_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE methods SET status='active', promoted_utc=?, retired_utc=NULL WHERE method_id=? AND status='candidate'",
                (_utc(), method_id),
            )
        return cur.rowcount > 0

    def retire(self, method_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE methods SET status='retired', retired_utc=? WHERE method_id=? AND status='active'",
                (_utc(), method_id),
            )
        return cur.rowcount > 0

    def judge(self) -> dict:
        """Promote/retire methods based on deterministic evaluation thresholds."""
        PROMOTE_MIN_RUNS = 6
        PROMOTE_MIN_RATE = 0.70
        RETIRE_MIN_RUNS = 8
        RETIRE_MAX_RATE = 0.35
        RETIRE_FAIL_STREAK = 4

        promoted: list[str] = []
        retired: list[str] = []
        refreshed: list[str] = []
        now = _utc()

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT method_id, status FROM methods WHERE category='dag_pattern' AND status IN ('candidate','active')"
            ).fetchall()

            for row in rows:
                mid = row["method_id"]
                status = row["status"]

                stats_row = conn.execute(
                    """SELECT
                         COUNT(*) as runs,
                         AVG(CASE WHEN outcome='success' THEN 1.0 ELSE 0.0 END) as sr,
                         SUM(CASE WHEN outcome != 'success' THEN 1 ELSE 0 END) as fails
                       FROM (SELECT outcome FROM evaluations WHERE method_id=? ORDER BY evaluated_utc DESC LIMIT 240)""",
                    (mid,),
                ).fetchone()
                runs = int(stats_row["runs"] or 0)
                sr = stats_row["sr"]
                # Consecutive fail streak from most recent.
                streak_rows = conn.execute(
                    "SELECT outcome FROM evaluations WHERE method_id=? ORDER BY evaluated_utc DESC LIMIT 20",
                    (mid,),
                ).fetchall()
                fail_streak = 0
                for sr_row in streak_rows:
                    if sr_row["outcome"] != "success":
                        fail_streak += 1
                    else:
                        break

                if sr is not None and runs > 0:
                    conn.execute(
                        "UPDATE methods SET success_rate=?, total_runs=? WHERE method_id=?",
                        (float(sr), runs, mid),
                    )
                    refreshed.append(mid)

                if status == "candidate" and runs >= PROMOTE_MIN_RUNS and sr is not None and float(sr) >= PROMOTE_MIN_RATE:
                    conn.execute(
                        "UPDATE methods SET status='active', promoted_utc=?, retired_utc=NULL WHERE method_id=?",
                        (now, mid),
                    )
                    promoted.append(mid)
                    continue

                should_retire = (
                    status == "active"
                    and runs >= RETIRE_MIN_RUNS
                    and (
                        (sr is not None and float(sr) <= RETIRE_MAX_RATE)
                        or fail_streak >= RETIRE_FAIL_STREAK
                    )
                )
                if should_retire:
                    conn.execute(
                        "UPDATE methods SET status='retired', retired_utc=? WHERE method_id=?",
                        (now, mid),
                    )
                    retired.append(mid)

        return {
            "checked": len(rows),
            "refreshed": refreshed,
            "promoted": promoted,
            "retired": retired,
        }

    def unanalyzed_evaluations(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM evaluations WHERE analyzed=0 ORDER BY evaluated_utc ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_analyzed(self, eval_ids: list[str]) -> None:
        if not eval_ids:
            return
        with self._connect() as conn:
            conn.executemany(
                "UPDATE evaluations SET analyzed=1 WHERE eval_id=?",
                [(eid,) for eid in eval_ids],
            )

    def snapshot(self) -> dict:
        """Export active methods as a read-only snapshot."""
        methods = self.consult()
        return {"methods": methods, "exported_utc": _utc()}

    # ── V2 Strategy Layer ─────────────────────────────────────────────────────

    def seed_clusters(self, clusters: list[dict]) -> int:
        """Insert semantic clusters from capability_catalog.json if not already present."""
        inserted = 0
        now = _utc()
        with self._connect() as conn:
            for c in clusters:
                cid = str(c.get("cluster_id") or "")
                if not cid:
                    continue
                existing = conn.execute(
                    "SELECT 1 FROM semantic_clusters WHERE cluster_id=?", (cid,)
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    "INSERT INTO semantic_clusters(cluster_id,display_name,task_type_compat,created_utc,updated_utc) VALUES(?,?,?,?,?)",
                    (cid, str(c.get("display_name") or cid), c.get("task_type_compat"), now, now),
                )
                # Seed a champion strategy candidate per cluster.
                sid = _new_id("strat")
                default_spec = {"source": "seed", "cluster_id": cid}
                conn.execute(
                    "INSERT INTO strategy_candidates(strategy_id,cluster_id,stage,spec_json,sample_n,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?)",
                    (sid, cid, "champion", json.dumps(default_spec), 0, now, now),
                )
                inserted += 1
        return inserted

    def get_champion(self, cluster_id: str) -> dict | None:
        """Return the current champion strategy for a cluster."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM strategy_candidates WHERE cluster_id=? AND stage='champion' ORDER BY updated_utc DESC LIMIT 1",
                (cluster_id,),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["spec"] = json.loads(d.pop("spec_json", "{}") or "{}")
        d["score_components"] = json.loads(d.get("score_components") or "{}")
        return d

    def get_strategy(self, strategy_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM strategy_candidates WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["spec"] = json.loads(d.pop("spec_json", "{}") or "{}")
        d["score_components"] = json.loads(d.get("score_components") or "{}")
        return d

    def list_clusters(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT cluster_id, display_name, task_type_compat, created_utc, updated_utc FROM semantic_clusters ORDER BY cluster_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def record_experiment(
        self,
        strategy_id: str,
        task_id: str,
        cluster_id: str,
        score_components: dict,
        global_score: float,
        outcome: str,
        is_shadow: bool = False,
    ) -> str:
        """Record an experiment result and update candidate aggregate score."""
        eid = _new_id("exp")
        now = _utc()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO strategy_experiments(experiment_id,strategy_id,task_id,cluster_id,is_shadow,score_components,global_score,outcome,created_utc) VALUES(?,?,?,?,?,?,?,?,?)",
                (eid, strategy_id, task_id, cluster_id, 1 if is_shadow else 0,
                 json.dumps(score_components, ensure_ascii=False), round(global_score, 4), outcome, now),
            )
            # Update aggregate on candidate.
            agg = conn.execute(
                "SELECT AVG(global_score) as avg_score, COUNT(*) as n FROM strategy_experiments WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()
            conn.execute(
                "UPDATE strategy_candidates SET global_score=?, score_components=?, sample_n=?, updated_utc=? WHERE strategy_id=?",
                (
                    round(float(agg["avg_score"] or 0), 4),
                    json.dumps(score_components, ensure_ascii=False),
                    int(agg["n"]),
                    now,
                    strategy_id,
                ),
            )
        # Emit to telemetry JSONL.
        self._append_strategy_event("experiment_recorded", {
            "experiment_id": eid, "strategy_id": strategy_id,
            "cluster_id": cluster_id, "global_score": round(global_score, 4),
        })
        return eid

    def promote_strategy(
        self,
        strategy_id: str,
        decision: str,
        prev_stage: str,
        next_stage: str,
        reason: str = "",
        decided_by: str = "auto",
    ) -> str:
        """Record a promotion/rollback decision and update stage."""
        pid = _new_id("prom")
        now = _utc()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cluster_id FROM strategy_candidates WHERE strategy_id=?", (strategy_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Unknown strategy_id: {strategy_id}")
            cluster_id = row["cluster_id"]
            if next_stage == "champion":
                conn.execute(
                    "UPDATE strategy_candidates SET stage='challenger', updated_utc=? WHERE cluster_id=? AND stage='champion' AND strategy_id<>?",
                    (now, cluster_id, strategy_id),
                )
            conn.execute(
                "UPDATE strategy_candidates SET stage=?, updated_utc=?, promoted_utc=? WHERE strategy_id=?",
                (next_stage, now, now if next_stage in ("champion", "shadow", "challenger") else None, strategy_id),
            )
            conn.execute(
                "INSERT INTO strategy_promotions(promotion_id,strategy_id,cluster_id,decision,prev_stage,next_stage,reason,decided_by,decided_utc) VALUES(?,?,?,?,?,?,?,?,?)",
                (pid, strategy_id, cluster_id, decision, prev_stage, next_stage, reason, decided_by, now),
            )
        self._append_strategy_event("promotion_decision", {
            "promotion_id": pid, "strategy_id": strategy_id, "cluster_id": cluster_id,
            "decision": decision, "prev_stage": prev_stage, "next_stage": next_stage,
            "reason": reason, "decided_by": decided_by,
        })
        return pid

    def spawn_candidate_from_champion(self, cluster_id: str, stage: str = "candidate") -> dict | None:
        """Clone current champion as a new candidate/shadow strategy for exploration."""
        champion = self.get_champion(cluster_id)
        if not champion:
            return None
        now = _utc()
        sid = _new_id("strat")
        base_spec = champion.get("spec") if isinstance(champion.get("spec"), dict) else {}
        new_spec = {
            **base_spec,
            "source": "auto_spawn",
            "parent_strategy_id": champion.get("strategy_id", ""),
            "cluster_id": cluster_id,
        }
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO strategy_candidates(strategy_id,cluster_id,stage,spec_json,sample_n,created_utc,updated_utc) VALUES(?,?,?,?,?,?,?)",
                (sid, cluster_id, stage, json.dumps(new_spec, ensure_ascii=False), 0, now, now),
            )
        self._append_strategy_event(
            "candidate_spawned",
            {
                "strategy_id": sid,
                "cluster_id": cluster_id,
                "stage": stage,
                "parent_strategy_id": champion.get("strategy_id", ""),
            },
        )
        return self.get_strategy(sid)

    def list_strategies(self, cluster_id: str | None = None, stage: str | None = None) -> list[dict]:
        """List strategy candidates, optionally filtered."""
        q = "SELECT * FROM strategy_candidates WHERE 1=1"
        params: list = []
        if cluster_id:
            q += " AND cluster_id=?"
            params.append(cluster_id)
        if stage:
            q += " AND stage=?"
            params.append(stage)
        q += " ORDER BY updated_utc DESC"
        with self._connect() as conn:
            rows = conn.execute(q, params).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["spec"] = json.loads(d.pop("spec_json", "{}") or "{}")
            d["score_components"] = json.loads(d.get("score_components") or "{}")
            result.append(d)
        return result

    def list_promotions(self, strategy_id: str | None = None, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM strategy_promotions"
        params: list[Any] = []
        if strategy_id:
            sql += " WHERE strategy_id=?"
            params.append(strategy_id)
        sql += " ORDER BY decided_utc DESC LIMIT ?"
        params.append(max(1, min(limit, 2000)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def list_experiments(
        self,
        strategy_id: str | None = None,
        cluster_id: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        sql = "SELECT * FROM strategy_experiments WHERE 1=1"
        params: list[Any] = []
        if strategy_id:
            sql += " AND strategy_id=?"
            params.append(strategy_id)
        if cluster_id:
            sql += " AND cluster_id=?"
            params.append(cluster_id)
        sql += " ORDER BY created_utc DESC LIMIT ?"
        params.append(max(1, min(limit, 5000)))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        out: list[dict] = []
        for row in rows:
            d = dict(row)
            try:
                d["score_components"] = json.loads(d.get("score_components") or "{}")
            except Exception:
                d["score_components"] = {}
            out.append(d)
        return out

    def _append_strategy_event(self, event: str, payload: dict) -> None:
        """Append to state/telemetry/strategy_events.jsonl (mandatory audit log)."""
        import os
        daemon_home = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
        telemetry_dir = daemon_home / "state" / "telemetry"
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        entry = {"event": event, "payload": payload, "created_utc": _utc()}
        try:
            with (telemetry_dir / "strategy_events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to write strategy event: %s", exc)

    def stats(self) -> dict:
        with self._connect() as conn:
            by_status = {
                r["status"]: r["cnt"]
                for r in conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM methods GROUP BY status"
                ).fetchall()
            }
            eval_count = conn.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0]
            unanalyzed = conn.execute("SELECT COUNT(*) FROM evaluations WHERE analyzed=0").fetchone()[0]
            best = conn.execute(
                "SELECT name, success_rate FROM methods WHERE status='active' ORDER BY success_rate DESC NULLS LAST LIMIT 1"
            ).fetchone()
        return {
            "by_status": by_status,
            "total_evaluations": eval_count,
            "unanalyzed": unanalyzed,
            "best_method": dict(best) if best else None,
        }
