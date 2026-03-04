"""Playbook Fabric — procedural knowledge: DAG methods, strategies, evaluations."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id(prefix: str = "m") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


_STAGE_TRANSITIONS: dict[str, set[str]] = {
    "candidate": {"shadow", "retired"},
    "shadow": {"challenger", "retired"},
    "challenger": {"champion", "retired"},
    "champion": {"challenger", "retired"},
    "retired": set(),
}

_STAGE_PHASE: dict[str, str] = {
    "candidate": "sandbox",
    "shadow": "shadow",
    "challenger": "pre_production",
    "champion": "production",
    "retired": "retired",
}


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

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def register(self, name: str, category: str, spec: dict, description: str = "", status: str = "candidate") -> str:
        """Register a new method or bump version if name already exists."""
        now = _utc()
        with self._conn() as conn:
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
        with self._conn() as conn:
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
        with self._conn() as conn:
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

        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["spec"] = json.loads(item.pop("spec_json"))
            out.append(item)
        return out

    def get(self, method_id: str) -> dict | None:
        with self._conn() as conn:
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
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE methods SET status='active', promoted_utc=?, retired_utc=NULL WHERE method_id=? AND status='candidate'",
                (_utc(), method_id),
            )
        return cur.rowcount > 0

    def retire(self, method_id: str) -> bool:
        with self._conn() as conn:
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

        with self._conn() as conn:
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
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM evaluations WHERE analyzed=0 ORDER BY evaluated_utc ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_analyzed(self, eval_ids: list[str]) -> None:
        if not eval_ids:
            return
        with self._conn() as conn:
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
        seeded_strategy_ids: list[tuple[str, str]] = []
        with self._conn() as conn:
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
                seeded_strategy_ids.append((sid, cid))
        for sid, cid in seeded_strategy_ids:
            self._append_release_transition(
                strategy_id=sid,
                cluster_id=cid,
                prev_stage="none",
                next_stage="champion",
                action="seed_champion",
                actor="bootstrap",
                reason="cluster_seeded",
            )
        return inserted

    def get_champion(self, cluster_id: str) -> dict | None:
        """Return the current champion strategy for a cluster."""
        with self._conn() as conn:
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
        with self._conn() as conn:
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
        with self._conn() as conn:
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
        with self._conn() as conn:
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
        retired_ids: list[str] = []
        rollback_point: dict | None = None
        demoted_events: list[dict] = []
        retired_events: list[dict] = []
        cluster_id = ""
        current_stage = str(prev_stage or "")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT cluster_id, stage, sample_n FROM strategy_candidates WHERE strategy_id=?", (strategy_id,)
            ).fetchone()
            if not row:
                raise ValueError(f"Unknown strategy_id: {strategy_id}")
            cluster_id = row["cluster_id"]
            current_stage = str(row["stage"] or "")
            if current_stage != str(prev_stage or ""):
                # Preserve caller-provided stage for audit, but enforce truth from DB.
                prev_stage = current_stage

            if not self._is_transition_allowed(current_stage, next_stage):
                raise ValueError(f"invalid_stage_transition:{current_stage}->{next_stage}")

            # Production cutover gate: champion promotion requires audit completeness
            # except explicit rollback decisions.
            if next_stage == "champion" and decision not in {"rollback_manual", "rollback_auto"}:
                ok, reason_code = self._promotion_audit_ok(conn, strategy_id, cluster_id)
                if not ok:
                    raise ValueError(f"promotion_audit_incomplete:{reason_code}")

            previous_champion_rows = conn.execute(
                "SELECT strategy_id FROM strategy_candidates WHERE cluster_id=? AND stage='champion' AND strategy_id<>? ORDER BY updated_utc DESC",
                (cluster_id, strategy_id),
            ).fetchall()
            previous_champion = conn.execute(
                "SELECT strategy_id FROM strategy_candidates WHERE cluster_id=? AND stage='champion' ORDER BY updated_utc DESC LIMIT 1",
                (cluster_id,),
            ).fetchone()
            previous_champion_id = str(previous_champion["strategy_id"]) if previous_champion else ""

            if next_stage == "champion":
                conn.execute(
                    "UPDATE strategy_candidates SET stage='challenger', updated_utc=? WHERE cluster_id=? AND stage='champion' AND strategy_id<>?",
                    (now, cluster_id, strategy_id),
                )
                for item in previous_champion_rows:
                    old_id = str(item["strategy_id"] or "")
                    if not old_id:
                        continue
                    dem_pid = _new_id("prom")
                    demoted_events.append(
                        {
                            "promotion_id": dem_pid,
                            "strategy_id": old_id,
                            "cluster_id": cluster_id,
                            "decision": "demote_auto",
                            "prev_stage": "champion",
                            "next_stage": "challenger",
                            "reason": f"champion_replaced_by:{strategy_id}",
                            "decided_by": decided_by,
                            "decided_utc": now,
                        }
                    )
                    conn.execute(
                        "INSERT INTO strategy_promotions(promotion_id,strategy_id,cluster_id,decision,prev_stage,next_stage,reason,decided_by,decided_utc) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            dem_pid,
                            old_id,
                            cluster_id,
                            "demote_auto",
                            "champion",
                            "challenger",
                            f"champion_replaced_by:{strategy_id}",
                            decided_by,
                            now,
                        ),
                    )
                rollback_point = {
                    "rollback_point_id": _new_id("rbp"),
                    "cluster_id": cluster_id,
                    "new_champion_strategy_id": strategy_id,
                    "previous_champion_strategy_id": previous_champion_id,
                    "promotion_id": pid,
                    "created_utc": now,
                    "reason": reason or "",
                }

            retired_utc = now if next_stage == "retired" else None
            conn.execute(
                "UPDATE strategy_candidates SET stage=?, updated_utc=?, promoted_utc=?, retired_utc=? WHERE strategy_id=?",
                (
                    next_stage,
                    now,
                    now if next_stage in ("champion", "shadow", "challenger") else None,
                    retired_utc,
                    strategy_id,
                ),
            )

            # Enforce: each semantic cluster keeps at most 3 challengers.
            if next_stage in {"challenger", "champion"}:
                retired_ids = self._trim_challengers(conn, cluster_id, keep_limit=3)
                for rid in retired_ids:
                    retired_events.append(
                        {
                            "strategy_id": rid,
                            "cluster_id": cluster_id,
                            "prev_stage": "challenger",
                            "next_stage": "retired",
                            "reason": "challenger_cap_exceeded",
                        }
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
        self._append_release_transition(
            strategy_id=strategy_id,
            cluster_id=cluster_id,
            prev_stage=prev_stage,
            next_stage=next_stage,
            action=decision,
            actor=decided_by,
            reason=reason,
            promotion_id=pid,
        )
        for evt in demoted_events:
            self._append_strategy_event("promotion_decision", evt)
            self._append_release_transition(
                strategy_id=str(evt.get("strategy_id") or ""),
                cluster_id=str(evt.get("cluster_id") or cluster_id),
                prev_stage=str(evt.get("prev_stage") or "champion"),
                next_stage=str(evt.get("next_stage") or "challenger"),
                action=str(evt.get("decision") or "demote_auto"),
                actor=str(evt.get("decided_by") or decided_by),
                reason=str(evt.get("reason") or ""),
                promotion_id=str(evt.get("promotion_id") or ""),
            )
        for rid in retired_ids:
            self._append_strategy_event(
                "challenger_retired_by_limit",
                {"cluster_id": cluster_id, "strategy_id": rid, "keep_limit": 3, "reason": "challenger_cap_exceeded"},
            )
        for evt in retired_events:
            self._append_release_transition(
                strategy_id=str(evt.get("strategy_id") or ""),
                cluster_id=str(evt.get("cluster_id") or cluster_id),
                prev_stage=str(evt.get("prev_stage") or "challenger"),
                next_stage=str(evt.get("next_stage") or "retired"),
                action="retire_auto",
                actor=decided_by,
                reason=str(evt.get("reason") or "challenger_cap_exceeded"),
            )
        if rollback_point and rollback_point.get("previous_champion_strategy_id"):
            self._append_rollback_point(rollback_point)
            self._append_strategy_event("rollback_point_created", rollback_point)
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
        with self._conn() as conn:
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
        self._append_release_transition(
            strategy_id=sid,
            cluster_id=cluster_id,
            prev_stage="none",
            next_stage=stage,
            action="spawn_candidate",
            actor="playbook",
            reason=f"spawned_from:{champion.get('strategy_id', '')}",
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
        with self._conn() as conn:
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
        with self._conn() as conn:
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
        with self._conn() as conn:
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

    def strategy_audit_status(self, strategy_id: str) -> dict:
        """Return champion-promotion audit readiness for a strategy."""
        row = self.get_strategy(strategy_id)
        if not row:
            raise ValueError(f"Unknown strategy_id: {strategy_id}")
        cluster_id = str(row.get("cluster_id") or "")
        with self._conn() as conn:
            ok, reason_code = self._promotion_audit_ok(conn, strategy_id, cluster_id)
            total_exp = conn.execute(
                "SELECT COUNT(*) as n FROM strategy_experiments WHERE strategy_id=?",
                (strategy_id,),
            ).fetchone()["n"]
            shadow_exp = conn.execute(
                "SELECT COUNT(*) as n FROM strategy_experiments WHERE strategy_id=? AND is_shadow=1",
                (strategy_id,),
            ).fetchone()["n"]
        comparison_count = self._shadow_comparison_count(strategy_id)
        release_events = self.list_release_transitions(strategy_id=strategy_id, limit=200)
        has_execution_event = any(str(e.get("action") or "").startswith("execute_") for e in release_events)
        has_current_stage_transition = any(str(e.get("next_stage") or "") == str(row.get("stage") or "") for e in release_events)
        missing: list[str] = []
        if reason_code != "ok":
            missing.append(reason_code)
        if not release_events:
            missing.append("release_events_missing")
        if str(row.get("stage") or "") in {"shadow", "challenger", "champion"} and not has_execution_event:
            missing.append("release_execution_missing")
        if not has_current_stage_transition:
            missing.append("stage_transition_missing")
        return {
            "strategy_id": strategy_id,
            "cluster_id": cluster_id,
            "stage": str(row.get("stage") or ""),
            "sample_n": int(row.get("sample_n") or 0),
            "experiments_total": int(total_exp or 0),
            "experiments_shadow": int(shadow_exp or 0),
            "shadow_comparisons": int(comparison_count),
            "promotable_to_champion": bool(ok),
            "missing_checks": missing,
            "release_audit_closed": len(missing) == 0,
            "release_events_recent": release_events[:20],
        }

    def list_rollback_points(self, cluster_id: str | None = None, limit: int = 200) -> list[dict]:
        daemon_home = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
        path = daemon_home / "state" / "telemetry" / "strategy_rollback_points.jsonl"
        if not path.exists():
            return []
        rows: list[dict] = []
        try:
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
                if cluster_id and str(payload.get("cluster_id") or "") != cluster_id:
                    continue
                rows.append(row)
                if len(rows) >= max(1, min(limit, 2000)):
                    break
        except Exception:
            return []
        return rows

    def resolve_latest_rollback_target(self, current_strategy_id: str) -> dict | None:
        current = self.get_strategy(current_strategy_id)
        if not current:
            return None
        cluster_id = str(current.get("cluster_id") or "")
        if not cluster_id:
            return None
        points = self.list_rollback_points(cluster_id=cluster_id, limit=200)
        for row in points:
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if str(payload.get("new_champion_strategy_id") or "") != current_strategy_id:
                continue
            previous_id = str(payload.get("previous_champion_strategy_id") or "")
            if not previous_id:
                continue
            previous = self.get_strategy(previous_id)
            if not previous:
                continue
            return {
                "cluster_id": cluster_id,
                "current_strategy_id": current_strategy_id,
                "previous_champion_strategy_id": previous_id,
                "rollback_point": row,
                "previous_strategy": previous,
            }
        return None

    def list_release_transitions(
        self,
        strategy_id: str | None = None,
        cluster_id: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        daemon_home = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
        path = daemon_home / "state" / "telemetry" / "release_state_transitions.jsonl"
        if not path.exists():
            return []
        out: list[dict] = []
        try:
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if strategy_id and str(row.get("strategy_id") or "") != strategy_id:
                    continue
                if cluster_id and str(row.get("cluster_id") or "") != cluster_id:
                    continue
                out.append(row)
                if len(out) >= max(1, min(limit, 5000)):
                    break
        except Exception:
            return []
        return out

    def record_release_execution(
        self,
        *,
        strategy_id: str,
        cluster_id: str,
        stage: str,
        mode: str,
        task_id: str,
        actor: str,
        reason: str = "",
        shadow_of: str = "",
    ) -> None:
        payload = {
            "strategy_id": strategy_id,
            "cluster_id": cluster_id,
            "stage": stage,
            "mode": mode,
            "task_id": task_id,
            "actor": actor,
            "reason": reason,
            "shadow_of": shadow_of,
        }
        self._append_strategy_event("release_execution", payload)
        self._append_release_transition(
            strategy_id=strategy_id,
            cluster_id=cluster_id,
            prev_stage=stage,
            next_stage=stage,
            action=f"execute_{mode}",
            actor=actor,
            reason=reason,
            task_id=task_id,
            shadow_of=shadow_of,
        )

    def _append_strategy_event(self, event: str, payload: dict) -> None:
        """Append to state/telemetry/strategy_events.jsonl (mandatory audit log)."""
        daemon_home = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
        telemetry_dir = daemon_home / "state" / "telemetry"
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        entry = {"event_id": _new_id("evt"), "event": event, "payload": payload, "created_utc": _utc()}
        try:
            with (telemetry_dir / "strategy_events.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to write strategy event: %s", exc)

    def _append_release_transition(
        self,
        *,
        strategy_id: str,
        cluster_id: str,
        prev_stage: str,
        next_stage: str,
        action: str,
        actor: str,
        reason: str = "",
        promotion_id: str = "",
        task_id: str = "",
        shadow_of: str = "",
    ) -> None:
        daemon_home = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
        telemetry_dir = daemon_home / "state" / "telemetry"
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        stage = next_stage or prev_stage
        entry = {
            "event_id": _new_id("rel"),
            "strategy_id": strategy_id,
            "cluster_id": cluster_id,
            "prev_stage": prev_stage,
            "next_stage": next_stage,
            "phase": _STAGE_PHASE.get(stage, "unknown"),
            "action": action,
            "actor": actor,
            "reason": reason,
            "promotion_id": promotion_id,
            "task_id": task_id,
            "shadow_of": shadow_of,
            "created_utc": _utc(),
        }
        try:
            with (telemetry_dir / "release_state_transitions.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to write release transition: %s", exc)

    def _append_rollback_point(self, payload: dict) -> None:
        daemon_home = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
        telemetry_dir = daemon_home / "state" / "telemetry"
        telemetry_dir.mkdir(parents=True, exist_ok=True)
        entry = {"event_id": _new_id("rbp_evt"), "event": "rollback_point", "payload": payload, "created_utc": _utc()}
        try:
            with (telemetry_dir / "strategy_rollback_points.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Failed to write rollback point: %s", exc)

    def _is_transition_allowed(self, current_stage: str, next_stage: str) -> bool:
        allowed = _STAGE_TRANSITIONS.get(current_stage)
        if allowed is None:
            return False
        return next_stage in allowed

    def _promotion_audit_ok(self, conn: sqlite3.Connection, strategy_id: str, cluster_id: str) -> tuple[bool, str]:
        row = conn.execute(
            "SELECT sample_n, stage FROM strategy_candidates WHERE strategy_id=?",
            (strategy_id,),
        ).fetchone()
        if not row:
            return False, "strategy_not_found"
        sample_n = int(row["sample_n"] or 0)
        stage = str(row["stage"] or "")
        if sample_n <= 0:
            return False, "sample_n_insufficient"
        if stage not in {"challenger", "shadow"}:
            return False, "stage_not_promotable"
        shadow_exp = conn.execute(
            "SELECT COUNT(*) as n FROM strategy_experiments WHERE strategy_id=? AND is_shadow=1",
            (strategy_id,),
        ).fetchone()
        if int(shadow_exp["n"] or 0) <= 0:
            return False, "shadow_experiment_missing"
        if self._shadow_comparison_count(strategy_id) <= 0:
            return False, "shadow_comparison_missing"
        if not cluster_id:
            return False, "cluster_missing"
        return True, "ok"

    def _shadow_comparison_count(self, strategy_id: str) -> int:
        daemon_home = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
        path = daemon_home / "state" / "telemetry" / "shadow_comparisons.jsonl"
        if not path.exists():
            return 0
        count = 0
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(row.get("shadow_strategy_id") or "") == strategy_id:
                    count += 1
        except Exception:
            return 0
        return count

    def _trim_challengers(self, conn: sqlite3.Connection, cluster_id: str, keep_limit: int = 3) -> list[str]:
        rows = conn.execute(
            "SELECT strategy_id FROM strategy_candidates WHERE cluster_id=? AND stage='challenger' ORDER BY updated_utc DESC",
            (cluster_id,),
        ).fetchall()
        if len(rows) <= keep_limit:
            return []
        retire_rows = rows[keep_limit:]
        now = _utc()
        retired_ids = [str(r["strategy_id"]) for r in retire_rows]
        for rid in retired_ids:
            conn.execute(
                "UPDATE strategy_candidates SET stage='retired', updated_utc=?, retired_utc=? WHERE strategy_id=?",
                (now, now, rid),
            )
        return retired_ids

    def stats(self) -> dict:
        with self._conn() as conn:
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
