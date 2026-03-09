"""Tests for services: Will, Herald, Cadence."""
import json
import os
import time
import pytest
from pathlib import Path

from psyche.lore import LorePsyche
from psyche.instinct import InstinctPsyche
from psyche.memory import MemoryPsyche
from spine.nerve import Nerve
from spine.trail import Trail
from runtime.cortex import Cortex
from services.will import Will, _new_deed_id
from services.herald import HeraldService
from services.cadence import Cadence


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir(exist_ok=True)
    (d / "ward.json").write_text(json.dumps({"status": "GREEN"}))
    return d


@pytest.fixture
def lore(tmp_path):
    return LorePsyche(tmp_path / "state" / "lore.db")


@pytest.fixture
def instinct(tmp_path):
    return InstinctPsyche(tmp_path / "state" / "instinct.db")


@pytest.fixture
def nerve():
    return Nerve()


# -- Will ----------------------------------------------------------------------

class TestWill:
    def _make_will(self, lore, instinct, nerve, state_dir):
        return Will(lore, instinct, nerve, state_dir)

    def test_validate_valid_plan(self, lore, instinct, nerve, state_dir):
        d = self._make_will(lore, instinct, nerve, state_dir)
        plan = {"moves": [{"id": "scout", "agent": "scout", "depends_on": []}]}
        ok, err = d.validate(plan)
        assert ok is True

    def test_validate_empty_moves(self, lore, instinct, nerve, state_dir):
        d = self._make_will(lore, instinct, nerve, state_dir)
        ok, err = d.validate({"moves": []})
        assert ok is False
        assert "moves" in err

    def test_validate_duplicate_move_id(self, lore, instinct, nerve, state_dir):
        d = self._make_will(lore, instinct, nerve, state_dir)
        plan = {"moves": [{"id": "a"}, {"id": "a"}]}
        ok, err = d.validate(plan)
        assert ok is False
        assert "duplicate" in err

    def test_validate_unknown_dep(self, lore, instinct, nerve, state_dir):
        d = self._make_will(lore, instinct, nerve, state_dir)
        plan = {"moves": [{"id": "b", "depends_on": ["a"]}]}
        ok, err = d.validate(plan)
        assert ok is False
        assert "unknown" in err

    def test_enrich_assigns_deed_id(self, lore, instinct, nerve, state_dir):
        d = self._make_will(lore, instinct, nerve, state_dir)
        plan = {"moves": [{"id": "s1"}], "brief": {"complexity": "charge"}}
        enriched = d.enrich(plan)
        assert "deed_id" in enriched
        assert enriched["deed_id"].startswith("deed_")

    def test_enrich_sets_complexity(self, lore, instinct, nerve, state_dir):
        d = self._make_will(lore, instinct, nerve, state_dir)
        plan = {"moves": [{"id": "s1"}], "brief": {"complexity": "errand"}}
        enriched = d.enrich(plan)
        assert enriched["complexity"] == "errand"

    def test_enrich_ward_red_queues(self, lore, instinct, nerve, state_dir):
        (state_dir / "ward.json").write_text(json.dumps({"status": "RED"}))
        d = self._make_will(lore, instinct, nerve, state_dir)
        plan = {"moves": [{"id": "s1"}]}
        enriched = d.enrich(plan)
        assert enriched.get("queued") is True

    def test_enrich_ward_yellow_queues_endeavor(self, lore, instinct, nerve, state_dir):
        (state_dir / "ward.json").write_text(json.dumps({"status": "YELLOW"}))
        d = self._make_will(lore, instinct, nerve, state_dir)
        plan = {"moves": [{"id": "s1"}], "brief": {"complexity": "endeavor"}}
        enriched = d.enrich(plan)
        assert enriched.get("queued") is True

    def test_enrich_ward_yellow_does_not_queue_charge(self, lore, instinct, nerve, state_dir):
        (state_dir / "ward.json").write_text(json.dumps({"status": "YELLOW"}))
        d = self._make_will(lore, instinct, nerve, state_dir)
        plan = {"moves": [{"id": "s1"}], "brief": {"complexity": "charge"}}
        enriched = d.enrich(plan)
        assert not enriched.get("queued")

    @pytest.mark.asyncio
    async def test_submit_invalid_plan(self, lore, instinct, nerve, state_dir):
        d = self._make_will(lore, instinct, nerve, state_dir)
        result = await d.submit({"moves": []})
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_submit_valid_plan_no_temporal(self, lore, instinct, nerve, state_dir, tmp_path):
        os.environ["DAEMON_HOME"] = str(tmp_path)
        d = self._make_will(lore, instinct, nerve, state_dir)
        plan = {
            "moves": [{"id": "scout", "agent": "scout", "depends_on": []}],
            "brief": {"complexity": "charge"},
        }
        result = await d.submit(plan)
        assert result["ok"] is False
        assert result["error_code"] == "temporal_unavailable"
        assert "deed_id" in result

    def test_new_deed_id_format(self):
        tid = _new_deed_id()
        assert tid.startswith("deed_")
        parts = tid.split("_")
        assert len(parts) == 3


# -- Herald --------------------------------------------------------------------

class TestHeraldService:
    def _make_herald(self, instinct, nerve, tmp_path):
        (tmp_path / "offerings").mkdir(exist_ok=True)
        (tmp_path / "state").mkdir(exist_ok=True)
        return HeraldService(instinct, nerve, tmp_path)

    def test_deliver_no_scribe_output(self, instinct, nerve, tmp_path):
        d = self._make_herald(instinct, nerve, tmp_path)
        result = d.deliver("deed_999", {"complexity": "charge"}, [])
        assert result["ok"] is False
        assert result["error_code"] == "scribe_output_missing"

    def test_deliver_full_pipeline(self, instinct, nerve, tmp_path):
        d = self._make_herald(instinct, nerve, tmp_path)
        # Create fake scribe output.
        deed_root = tmp_path / "deeds" / "deed_001"
        scribe_dir = deed_root / "moves" / "scribe_1" / "output"
        scribe_dir.mkdir(parents=True)
        (scribe_dir / "output.md").write_text("# Report\n\n" + "Content word. " * 120)
        plan = {"deed_id": "t1", "title": "Test", "complexity": "charge"}
        result = d.deliver(str(deed_root), plan, [{"move_id": "scribe_1", "status": "ok"}])
        assert result["ok"] is True
        assert "offering_path" in result

    def test_vault_creates_files(self, instinct, nerve, tmp_path):
        d = self._make_herald(instinct, nerve, tmp_path)
        scribe_file = tmp_path / "report.md"
        scribe_file.write_text("# Report\n\nContent here.")
        plan = {"deed_id": "t1", "title": "Test Report", "complexity": "charge"}
        dest = d._vault("deed_001", plan, scribe_file)
        # Vault copies scribe file, no manifest.json
        assert any(dest.glob("*.md"))

    def test_update_index(self, instinct, nerve, tmp_path):
        d = self._make_herald(instinct, nerve, tmp_path)
        dest = tmp_path / "offerings" / "2026-03" / "test"
        dest.mkdir(parents=True)
        plan = {"deed_id": "t1", "title": "T", "complexity": "charge"}
        d._update_index(dest, plan)
        log = d._ledger.load_herald_log()
        assert len(log) == 1
        assert log[0]["complexity"] == "charge"


# -- Cadence helpers -----------------------------------------------------------

class TestCadence:
    def test_parse_cron_every_10_min(self):
        assert Cadence._parse_cron_simple("*/10 * * * *") == 600

    def test_parse_cron_daily(self):
        assert Cadence._parse_cron_simple("0 3 * * *") == 86400

    def test_parse_duration_hours(self):
        assert Cadence._parse_duration("4h") == 4 * 3600

    def test_parse_duration_minutes(self):
        assert Cadence._parse_duration("30m") == 1800

    def test_parse_duration_mixed(self):
        assert Cadence._parse_duration("2h30m") == 2 * 3600 + 30 * 60

    def test_parse_duration_invalid(self):
        assert Cadence._parse_duration("abc") is None
