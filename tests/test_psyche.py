"""Tests for new Psyche components: PsycheConfig, LedgerStats, InstinctEngine, SourceCache."""
import json
import pytest
from pathlib import Path
from psyche.config import PsycheConfig
from psyche.ledger_stats import LedgerStats
from psyche.instinct_engine import InstinctEngine
from psyche.source_cache import SourceCache


@pytest.fixture
def psyche_dir(tmp_path):
    d = tmp_path / "psyche"
    d.mkdir()
    # Create minimal TOML files
    (d / "preferences.toml").write_text(
        '[general]\ndefault_depth = "study"\nrequire_bilingual = true\n\n'
        '[execution]\nretinue_size_n = 7\n'
    )
    (d / "rations.toml").write_text(
        '[daily_limits]\nminimax_tokens = 20000000\nqwen_tokens = 10000000\nconcurrent_deeds = 10\n\n'
        '[current_usage]\n'
    )
    return d


@pytest.fixture
def config(psyche_dir):
    return PsycheConfig(psyche_dir)


@pytest.fixture
def ledger(tmp_path):
    return LedgerStats(tmp_path / "ledger.db")


@pytest.fixture
def instinct_engine(psyche_dir):
    (psyche_dir / "instinct.md").write_text("# Test instinct rules\n")
    return InstinctEngine(psyche_dir)


@pytest.fixture
def source_cache(tmp_path):
    return SourceCache(tmp_path / "source_cache.db")


# -- PsycheConfig --------------------------------------------------------------

class TestPsycheConfig:
    def test_get_pref(self, config):
        assert config.get_pref("general.default_depth") == "study"

    def test_get_pref_flat_key(self, config):
        # Flat key lookup should search all sections
        assert config.get_pref("default_depth") == "study"

    def test_get_pref_default(self, config):
        assert config.get_pref("nonexistent", "fallback") == "fallback"

    def test_set_pref(self, config):
        config.set_pref("general.test_key", "test_val", source="test", changed_by="test")
        assert config.get_pref("general.test_key") == "test_val"

    def test_all_prefs(self, config):
        prefs = config.all_prefs()
        assert isinstance(prefs, dict)
        assert "require_bilingual" in prefs or "general.require_bilingual" in str(prefs)

    def test_get_ration(self, config):
        ration = config.get_ration("minimax_tokens")
        assert ration is not None

    def test_consume_ration(self, config):
        ok = config.consume_ration("minimax_tokens", 1000)
        assert ok is True

    def test_all_rations(self, config):
        rations = config.all_rations()
        assert isinstance(rations, list)

    def test_snapshot(self, config):
        snap = config.snapshot()
        assert "preferences" in snap or "prefs" in snap


# -- LedgerStats ---------------------------------------------------------------

class TestLedgerStats:
    def test_merge_dag_template(self, ledger):
        ledger.merge_dag_template(
            objective_text="Test research report",
            objective_emb=None,
            dag_structure={"agents": ["scout", "sage"], "dag_budget": 6},
            eval_summary="",
            total_tokens=1000,
            total_duration_s=10.0,
            rework_count=0,
        )
        hints = ledger.global_planning_hints()
        assert hints.get("dag_template_count", 0) >= 1

    def test_update_skill_stats(self, ledger):
        ledger.update_skill_stats("brave_search", success=True, tokens_used=500, elapsed_s=2.0)
        hints = ledger.global_planning_hints()
        assert hints is not None

    def test_update_agent_stats(self, ledger):
        ledger.update_agent_stats("scout", success=True, tokens_used=3000, elapsed_s=30.0)
        summary = ledger.agent_summary("scout")
        assert summary is not None

    def test_recent_deeds(self, ledger):
        deeds = ledger.recent_deeds(limit=10)
        assert isinstance(deeds, list)


# -- InstinctEngine ------------------------------------------------------------

class TestInstinctEngine:
    def test_prompt_fragment(self, instinct_engine):
        fragment = instinct_engine.prompt_fragment()
        assert isinstance(fragment, str)

    def test_check_outbound_query(self, instinct_engine):
        ok, reason = instinct_engine.check_outbound_query("normal research query")
        assert ok is True

    def test_check_output(self, instinct_engine):
        ok, reason = instinct_engine.check_output("normal output text")
        assert ok is True


# -- SourceCache ---------------------------------------------------------------

class TestSourceCache:
    def test_store_and_stats(self, source_cache):
        source_cache.store(
            source_url="https://example.com",
            content="Test content",
            tier="tier_a",
            embedding=[],
        )
        stats = source_cache.stats()
        assert stats.get("total", 0) >= 1

    def test_expire(self, source_cache):
        expired = source_cache.expire(max_age_days=0)
        assert isinstance(expired, int)
