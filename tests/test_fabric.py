"""Tests for all three Fabric components using in-memory SQLite."""
import pytest
from pathlib import Path
from fabric.memory import MemoryFabric
from fabric.playbook import PlaybookFabric, BOOTSTRAP_METHODS
from fabric.compass import CompassFabric, BOOTSTRAP_PRIORITIES


@pytest.fixture
def memory(tmp_path):
    return MemoryFabric(tmp_path / "memory.db")


@pytest.fixture
def playbook(tmp_path):
    return PlaybookFabric(tmp_path / "playbook.db")


@pytest.fixture
def compass(tmp_path):
    return CompassFabric(tmp_path / "compass.db")


# ── Memory Fabric ─────────────────────────────────────────────────────────────

class TestMemoryFabric:
    def test_intake_basic(self, memory):
        result = memory.intake([
            {"title": "Test Unit", "domain": "ai_research", "tier": "standard", "provider": "test"}
        ])
        assert result["inserted"] == 1
        assert result["skipped"] == 0
        assert len(result["unit_ids"]) == 1

    def test_intake_dedup_by_hash(self, memory):
        unit = {"title": "Duplicate", "domain": "general", "provider": "test"}
        r1 = memory.intake([unit])
        r2 = memory.intake([unit])
        assert r1["inserted"] == 1
        assert r2["inserted"] == 0
        assert r2["skipped"] == 1

    def test_intake_invalid_tier_defaults(self, memory):
        memory.intake([{"title": "T", "domain": "d", "tier": "invalid_tier", "provider": "x"}])
        units = memory.query()
        assert units[0]["tier"] == "standard"

    def test_query_by_domain(self, memory):
        memory.intake([
            {"title": "AI Unit", "domain": "ai_research", "provider": "x"},
            {"title": "Finance Unit", "domain": "finance", "provider": "x"},
        ])
        ai_units = memory.query(domain="ai_research")
        assert len(ai_units) == 1
        assert ai_units[0]["domain"] == "ai_research"

    def test_query_by_keyword(self, memory):
        memory.intake([
            {"title": "Deep Learning Advances", "domain": "ai_research", "provider": "x"},
            {"title": "Stock Market News", "domain": "finance", "provider": "x"},
        ])
        results = memory.query(keyword="Learning")
        assert len(results) == 1
        assert "Learning" in results[0]["title"]

    def test_get_unit_with_details(self, memory):
        r = memory.intake([{"title": "T", "domain": "d", "provider": "x"}])
        uid = r["unit_ids"][0]
        unit = memory.get(uid)
        assert unit is not None
        assert unit["unit_id"] == uid
        assert "sources" in unit
        assert "usage" in unit
        assert "links_out" in unit

    def test_distill_update(self, memory):
        r = memory.intake([{"title": "Old Title", "domain": "ai", "provider": "x"}])
        uid = r["unit_ids"][0]
        memory.distill(uid, {"title": "New Title", "confidence": 0.9})
        unit = memory.get(uid)
        assert unit["title"] == "New Title"
        assert unit["confidence"] == 0.9

    def test_link(self, memory):
        r = memory.intake([
            {"title": "A", "domain": "d", "provider": "x"},
            {"title": "B", "domain": "d", "provider": "x"},
        ])
        a, b = r["unit_ids"]
        lid = memory.link(a, b, "supports")
        assert lid.startswith("l_")
        unit_a = memory.get(a)
        assert len(unit_a["links_out"]) == 1
        assert unit_a["links_out"][0]["relation"] == "supports"

    def test_usage_tracking(self, memory):
        r = memory.intake([{"title": "T", "domain": "d", "provider": "x"}])
        uid = r["unit_ids"][0]
        memory.record_usage(uid, "task_001", "method_001", "success")
        unit = memory.get(uid)
        assert len(unit["usage"]) == 1
        assert unit["usage"][0]["outcome"] == "success"

    def test_expire(self, memory):
        # Manually insert an already-expired unit.
        import sqlite3, time
        with memory._connect() as conn:
            conn.execute(
                "INSERT INTO units VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("u_exp", "Expired", "d", "breaking", 1.0, None, None, "active",
                 "2020-01-01T00:00:00Z", "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"),
            )
        result = memory.expire()
        assert result["archived"] >= 1

    def test_snapshot_structure(self, memory):
        memory.intake([{"title": "T", "domain": "d", "provider": "x"}])
        snap = memory.snapshot()
        assert "units" in snap
        assert "links" in snap
        assert "exported_utc" in snap

    def test_stats(self, memory):
        memory.intake([{"title": "T", "domain": "ai_research", "provider": "x"}])
        stats = memory.stats()
        assert stats["total_active"] == 1
        assert "ai_research" in stats["by_domain"]


# ── Playbook Fabric ───────────────────────────────────────────────────────────

class TestPlaybookFabric:
    def test_register_method(self, playbook):
        mid = playbook.register(
            name="test_dag",
            category="dag_pattern",
            spec={"steps_template": []},
            status="candidate",
        )
        assert mid.startswith("m_")

    def test_register_duplicate_bumps_version(self, playbook):
        mid1 = playbook.register("dag_a", "dag_pattern", {"v": 1}, status="active")
        mid2 = playbook.register("dag_a", "dag_pattern", {"v": 2}, status="active")
        assert mid1 == mid2
        m = playbook.get(mid1)
        assert m["version"] == 2
        assert len(m["versions"]) == 2

    def test_evaluate_and_consult(self, playbook):
        mid = playbook.register("dag_b", "dag_pattern", {}, status="active")
        playbook.evaluate(mid, "task_1", "success", 1.0)
        playbook.evaluate(mid, "task_2", "success", 0.9)
        methods = playbook.consult()
        assert any(m["method_id"] == mid for m in methods)

    def test_judge_promotes_candidate(self, playbook):
        mid = playbook.register("dag_c", "dag_pattern", {}, status="candidate")
        for i in range(6):
            playbook.evaluate(mid, f"t_{i}", "success", 1.0)
        result = playbook.judge()
        assert mid in result["promoted"]

    def test_judge_retires_active(self, playbook):
        mid = playbook.register("dag_d", "dag_pattern", {}, status="active")
        for i in range(8):
            playbook.evaluate(mid, f"t_{i}", "failure", 0.0)
        result = playbook.judge()
        assert mid in result["retired"]

    def test_unanalyzed_and_mark(self, playbook):
        mid = playbook.register("dag_e", "dag_pattern", {}, status="active")
        playbook.evaluate(mid, "t1", "success")
        playbook.evaluate(mid, "t2", "failure")
        unanalyzed = playbook.unanalyzed_evaluations()
        assert len(unanalyzed) == 2
        playbook.mark_analyzed([u["eval_id"] for u in unanalyzed])
        assert len(playbook.unanalyzed_evaluations()) == 0

    def test_bootstrap_methods(self, playbook):
        for m in BOOTSTRAP_METHODS:
            playbook.register(m["name"], m["category"], m["spec"], m["description"], "active")
        methods = playbook.consult()
        assert len(methods) == len(BOOTSTRAP_METHODS)

    def test_stats(self, playbook):
        playbook.register("dag_f", "dag_pattern", {}, status="active")
        stats = playbook.stats()
        assert "by_status" in stats
        assert "active" in stats["by_status"]


# ── Compass Fabric ────────────────────────────────────────────────────────────

class TestCompassFabric:
    def test_set_get_priority(self, compass):
        compass.set_priority("ai_research", 1.5, "Important domain")
        priorities = compass.get_priorities()
        ai = next((p for p in priorities if p["domain"] == "ai_research"), None)
        assert ai is not None
        assert ai["weight"] == 1.5

    def test_priority_upsert(self, compass):
        compass.set_priority("ai_research", 1.0)
        compass.set_priority("ai_research", 2.0, "Updated")
        priorities = compass.get_priorities()
        ai = next(p for p in priorities if p["domain"] == "ai_research")
        assert ai["weight"] == 2.0

    def test_quality_profile(self, compass):
        rules = {"min_sections": 3, "min_word_count": 500}
        compass.set_quality_profile("research_report", rules)
        fetched = compass.get_quality_profile("research_report")
        assert fetched["min_sections"] == 3

    def test_quality_profile_fallback_to_default(self, compass):
        compass.set_quality_profile("default", {"min_sections": 1})
        fetched = compass.get_quality_profile("nonexistent_type")
        assert fetched["min_sections"] == 1

    def test_budget_consume(self, compass):
        import time
        tomorrow = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
        with compass._connect() as conn:
            conn.execute("INSERT INTO resource_budgets VALUES (?,?,?,?)", ("openai_tokens", 1000, 0, tomorrow))
        assert compass.consume_budget("openai_tokens", 500) is True
        assert compass.consume_budget("openai_tokens", 600) is False  # Would exceed

    def test_budget_unknown_resource(self, compass):
        assert compass.consume_budget("nonexistent", 999) is True

    def test_preferences(self, compass):
        compass.set_pref("output_language", "zh")
        assert compass.get_pref("output_language") == "zh"
        assert compass.get_pref("missing_key", "default") == "default"

    def test_attention_signals(self, compass):
        sid = compass.add_signal("ai_research", "rising interest", severity="high")
        signals = compass.active_signals()
        assert any(s["signal_id"] == sid for s in signals)

    def test_signal_expiry(self, compass):
        # Add already-expired signal.
        with compass._connect() as conn:
            conn.execute(
                "INSERT INTO attention_signals VALUES (?,?,?,?,?,?)",
                ("sig_old", "old_domain", "old trend", "normal", "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z"),
            )
        removed = compass.expire_signals()
        assert removed >= 1
        signals = compass.active_signals()
        assert not any(s["signal_id"] == "sig_old" for s in signals)

    def test_config_versioning(self, compass):
        compass.set_priority("domain_x", 1.0, "v1")
        compass.set_priority("domain_x", 1.5, "v2")
        versions = compass.versions("priority.domain_x")
        assert len(versions) == 2

    def test_rollback(self, compass):
        compass.set_priority("domain_y", 1.0, "initial")
        compass.set_priority("domain_y", 2.0, "updated")
        compass.rollback("priority.domain_y", 1, changed_by="test")
        priorities = compass.get_priorities()
        dy = next(p for p in priorities if p["domain"] == "domain_y")
        assert dy["weight"] == 1.0

    def test_bootstrap_priorities(self, compass):
        for p in BOOTSTRAP_PRIORITIES:
            compass.set_priority(p["domain"], p["weight"], p.get("reason", ""), source="bootstrap")
        prios = compass.get_priorities()
        assert len(prios) == len(BOOTSTRAP_PRIORITIES)

    def test_snapshot(self, compass):
        compass.set_priority("d", 1.0)
        snap = compass.snapshot()
        assert "priorities" in snap
        assert "preferences" in snap
        assert "exported_utc" in snap
