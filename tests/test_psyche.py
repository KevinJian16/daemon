"""Tests for all three Psyche components using in-memory SQLite."""
import json
import pytest
from pathlib import Path
from psyche.memory import MemoryPsyche
from psyche.lore import LorePsyche
from psyche.instinct import InstinctPsyche


@pytest.fixture
def memory(tmp_path):
    return MemoryPsyche(tmp_path / "memory.db")


@pytest.fixture
def lore(tmp_path):
    return LorePsyche(tmp_path / "lore.db")


@pytest.fixture
def instinct(tmp_path):
    return InstinctPsyche(tmp_path / "instinct.db")


# -- Memory Psyche -------------------------------------------------------------

class TestMemoryPsyche:
    def test_add_basic(self, memory):
        entry_id = memory.add("Test knowledge entry", tags=["ai", "research"], source="test")
        assert entry_id  # Returns a valid ID

    def test_add_and_get(self, memory):
        entry_id = memory.add("Deep learning advances in 2026", tags=["ai"], source="test")
        entry = memory.get(entry_id)
        assert entry is not None
        assert entry["entry_id"] == entry_id
        assert entry["content"] == "Deep learning advances in 2026"
        assert "ai" in entry["tags"]

    def test_upsert_inserts_new(self, memory):
        result = memory.upsert(content="New knowledge", tags=["test"], source="test")
        assert result["action"] == "inserted"
        assert "entry_id" in result

    def test_delete(self, memory):
        entry_id = memory.add("To be deleted", source="test")
        assert memory.delete(entry_id) is True
        assert memory.get(entry_id) is None

    def test_search_by_tags(self, memory):
        memory.add("AI knowledge", tags=["ai", "ml"], source="test")
        memory.add("Finance knowledge", tags=["finance"], source="test")
        results = memory.search_by_tags(["ai"])
        assert len(results) == 1
        assert "ai" in results[0]["tags"]

    def test_touch_updates_relevance(self, memory):
        entry_id = memory.add("Touchable entry", source="test")
        memory.touch(entry_id)
        entry = memory.get(entry_id)
        assert entry is not None

    def test_decay_all(self, memory):
        memory.add("Entry 1", source="test")
        memory.add("Entry 2", source="test")
        decayed = memory.decay_all()
        assert decayed >= 0

    def test_distill(self, memory):
        memory.add("Entry for distill", source="test")
        result = memory.distill()
        assert "decayed" in result
        assert "evicted" in result

    def test_snapshot_structure(self, memory):
        memory.add("Snapshot entry", source="test")
        snap = memory.snapshot()
        assert "entries" in snap
        assert "exported_utc" in snap

    def test_stats(self, memory):
        memory.add("Stats entry", tags=["test"], source="test")
        stats = memory.stats()
        assert stats["total_entries"] >= 1
        assert "with_embedding" in stats
        assert "capacity_limit" in stats


# -- Lore Psyche ---------------------------------------------------------------

class TestLorePsyche:
    def test_record_basic(self, lore):
        record_id = lore.record(
            deed_id="deed_001",
            objective_text="Test research report",
            dag_budget=6,
            move_count=4,
            plan_structure={"moves": ["scout", "sage", "arbiter", "scribe"]},
            offering_quality={"quality_score": 0.85},
            token_consumption={"minimax": 5000},
            success=True,
            duration_s=300.0,
        )
        assert record_id.startswith("pb_") or record_id

    def test_record_and_get(self, lore):
        lore.record(
            deed_id="deed_002",
            objective_text="Deep analysis task",
            dag_budget=8,
            move_count=3,
            plan_structure={"moves": ["sage", "arbiter", "scribe"]},
            offering_quality={"quality_score": 0.90},
            token_consumption={},
            success=True,
            duration_s=200.0,
        )
        rec = lore.get("deed_002")
        assert rec is not None
        assert rec["objective_text"] == "Deep analysis task"
        assert rec["dag_budget"] == 8
        assert rec["success"] == 1 or rec["success"] is True

    def test_consult_returns_relevant(self, lore):
        for i in range(3):
            lore.record(
                deed_id=f"deed_c{i}",
                objective_text=f"Research topic {i}",
                dag_budget=6,
                move_count=4,
                plan_structure={"moves": ["scout", "sage"]},
                offering_quality={"quality_score": 0.80 + i * 0.05},
                token_consumption={},
                success=True,
                duration_s=300.0,
            )
        results = lore.consult(dag_budget=6, top_k=5)
        assert len(results) >= 1

    def test_consult_filters_by_dag_budget(self, lore):
        lore.record(
            deed_id="deed_small",
            objective_text="Quick task",
            dag_budget=3,
            move_count=1,
            plan_structure={"moves": ["scribe"]},
            offering_quality={"quality_score": 0.9},
            token_consumption={},
            success=True,
            duration_s=60.0,
        )
        lore.record(
            deed_id="deed_large",
            objective_text="Standard task",
            dag_budget=7,
            move_count=4,
            plan_structure={"moves": ["scout", "sage", "arbiter", "scribe"]},
            offering_quality={"quality_score": 0.85},
            token_consumption={},
            success=True,
            duration_s=300.0,
        )
        small_results = lore.consult(dag_budget=3, top_k=10)
        assert all(r.get("dag_budget") == 3 for r in small_results)

    def test_update_feedback(self, lore):
        lore.record(
            deed_id="deed_fb",
            objective_text="Feedback test",
            dag_budget=6,
            move_count=2,
            plan_structure={},
            offering_quality={},
            token_consumption={},
            success=True,
            duration_s=100.0,
        )
        updated = lore.update_feedback("deed_fb", {"rating": 5, "comment": "Great"})
        assert updated is True
        rec = lore.get("deed_fb")
        fb = json.loads(rec["user_feedback"]) if isinstance(rec["user_feedback"], str) else rec["user_feedback"]
        assert fb["rating"] == 5

    def test_snapshot(self, lore):
        lore.record(
            deed_id="deed_snap",
            objective_text="Snapshot test",
            dag_budget=2,
            move_count=1,
            plan_structure={},
            offering_quality={},
            token_consumption={},
            success=True,
            duration_s=50.0,
        )
        snap = lore.snapshot()
        assert "records" in snap
        assert "exported_utc" in snap

    def test_stats(self, lore):
        lore.record(
            deed_id="deed_st",
            objective_text="Stats test",
            dag_budget=6,
            move_count=3,
            plan_structure={},
            offering_quality={},
            token_consumption={},
            success=True,
            duration_s=200.0,
        )
        stats = lore.stats()
        assert stats["total_records"] >= 1
        assert stats["by_dag_budget"]["6"] >= 1


# -- Instinct Psyche -----------------------------------------------------------

class TestInstinctPsyche:
    def test_self_seeds_defaults(self, instinct):
        prefs = instinct.all_prefs()
        assert len(prefs) > 0
        assert "require_bilingual" in prefs

    def test_set_get_pref(self, instinct):
        instinct.set_pref("output_language", "zh", source="test", changed_by="test")
        assert instinct.get_pref("output_language") == "zh"
        assert instinct.get_pref("missing_key", "default") == "default"

    def test_pref_upsert(self, instinct):
        instinct.set_pref("test_key", "v1", changed_by="test")
        instinct.set_pref("test_key", "v2", changed_by="test")
        assert instinct.get_pref("test_key") == "v2"

    def test_all_prefs(self, instinct):
        instinct.set_pref("custom_pref", "value", changed_by="test")
        prefs = instinct.all_prefs()
        assert "custom_pref" in prefs
        assert prefs["custom_pref"] == "value"

    def test_all_prefs_detailed(self, instinct):
        instinct.set_pref("detail_key", "detail_val", changed_by="test")
        detailed = instinct.all_prefs_detailed()
        assert isinstance(detailed, list)
        assert any(p["pref_key"] == "detail_key" for p in detailed)

    def test_ration_consume(self, instinct):
        instinct.set_ration("openai_tokens", 1000, changed_by="test")
        assert instinct.consume_ration("openai_tokens", 500) is True
        assert instinct.consume_ration("openai_tokens", 600) is False  # Would exceed

    def test_ration_unknown_resource(self, instinct):
        assert instinct.consume_ration("nonexistent", 999) is True

    def test_all_rations(self, instinct):
        rations = instinct.all_rations()
        assert isinstance(rations, list)

    def test_set_ration(self, instinct):
        instinct.set_ration("test_tokens", 5000, changed_by="test")
        ration = instinct.get_ration("test_tokens")
        assert ration is not None
        assert ration["daily_limit"] == 5000

    def test_config_versioning(self, instinct):
        instinct.set_pref("versioned_key", "v1", changed_by="test")
        instinct.set_pref("versioned_key", "v2", changed_by="test")
        versions = instinct.versions("pref.versioned_key")
        assert len(versions) >= 2

    def test_rollback(self, instinct):
        instinct.set_pref("rollback_key", "initial", changed_by="test")
        instinct.set_pref("rollback_key", "updated", changed_by="test")
        instinct.rollback("pref.rollback_key", 1, changed_by="test")
        assert instinct.get_pref("rollback_key") == "initial"

    def test_snapshot(self, instinct):
        snap = instinct.snapshot()
        assert "preferences" in snap
        assert "rations" in snap
        assert "exported_utc" in snap
