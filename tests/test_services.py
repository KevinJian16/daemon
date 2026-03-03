"""Tests for services: Dispatch, Delivery, Scheduler."""
import json
import os
import time
import pytest
from pathlib import Path

from fabric.playbook import PlaybookFabric, BOOTSTRAP_METHODS
from fabric.compass import CompassFabric, BOOTSTRAP_PRIORITIES, BOOTSTRAP_QUALITY_PROFILES
from fabric.memory import MemoryFabric
from spine.nerve import Nerve
from spine.trace import Tracer
from spine.registry import SpineRegistry
from spine.routines import SpineRoutines
from runtime.cortex import Cortex
from services.dispatch import Dispatch, _new_task_id
from services.delivery import DeliveryService
from services.scheduler import Scheduler


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir(exist_ok=True)
    (d / "gate.json").write_text(json.dumps({"status": "GREEN"}))
    return d


@pytest.fixture
def playbook(tmp_path):
    pb = PlaybookFabric(tmp_path / "state" / "playbook.db")
    for m in BOOTSTRAP_METHODS:
        pb.register(m["name"], m["category"], m["spec"], m["description"], "active")
    return pb


@pytest.fixture
def compass(tmp_path):
    cp = CompassFabric(tmp_path / "state" / "compass.db")
    for p in BOOTSTRAP_PRIORITIES:
        cp.set_priority(p["domain"], p["weight"], source="bootstrap")
    for q in BOOTSTRAP_QUALITY_PROFILES:
        cp.set_quality_profile(q["task_type"], q["rules"])
    return cp


@pytest.fixture
def nerve():
    return Nerve()


# ── Dispatch ──────────────────────────────────────────────────────────────────

class TestDispatch:
    def _make_dispatch(self, playbook, compass, nerve, state_dir):
        return Dispatch(playbook, compass, nerve, state_dir)

    def test_validate_valid_plan(self, playbook, compass, nerve, state_dir):
        d = self._make_dispatch(playbook, compass, nerve, state_dir)
        plan = {"steps": [{"id": "collect", "agent": "collect", "depends_on": []}]}
        ok, err = d.validate(plan)
        assert ok is True

    def test_validate_empty_steps(self, playbook, compass, nerve, state_dir):
        d = self._make_dispatch(playbook, compass, nerve, state_dir)
        ok, err = d.validate({"steps": []})
        assert ok is False
        assert "steps" in err

    def test_validate_duplicate_step_id(self, playbook, compass, nerve, state_dir):
        d = self._make_dispatch(playbook, compass, nerve, state_dir)
        plan = {"steps": [{"id": "a"}, {"id": "a"}]}
        ok, err = d.validate(plan)
        assert ok is False
        assert "duplicate" in err

    def test_validate_unknown_dep(self, playbook, compass, nerve, state_dir):
        d = self._make_dispatch(playbook, compass, nerve, state_dir)
        plan = {"steps": [{"id": "b", "depends_on": ["a"]}]}
        ok, err = d.validate(plan)
        assert ok is False
        assert "unknown" in err

    def test_enrich_assigns_task_id(self, playbook, compass, nerve, state_dir):
        d = self._make_dispatch(playbook, compass, nerve, state_dir)
        plan = {"steps": [{"id": "s1"}], "task_type": "research_report"}
        enriched = d.enrich(plan)
        assert "task_id" in enriched
        assert enriched["task_id"].startswith("task_")

    def test_enrich_applies_quality_profile(self, playbook, compass, nerve, state_dir):
        d = self._make_dispatch(playbook, compass, nerve, state_dir)
        plan = {"steps": [{"id": "s1"}], "task_type": "research_report"}
        enriched = d.enrich(plan)
        assert "quality_profile" in enriched

    def test_enrich_gate_yellow_queues_low_priority(self, playbook, compass, nerve, state_dir):
        (state_dir / "gate.json").write_text(json.dumps({"status": "YELLOW"}))
        d = self._make_dispatch(playbook, compass, nerve, state_dir)
        plan = {"steps": [{"id": "s1"}], "priority": 8}
        enriched = d.enrich(plan)
        assert enriched.get("queued") is True

    def test_enrich_gate_yellow_does_not_queue_high_priority(self, playbook, compass, nerve, state_dir):
        (state_dir / "gate.json").write_text(json.dumps({"status": "YELLOW"}))
        d = self._make_dispatch(playbook, compass, nerve, state_dir)
        plan = {"steps": [{"id": "s1"}], "priority": 1}
        enriched = d.enrich(plan)
        assert not enriched.get("queued")

    @pytest.mark.asyncio
    async def test_submit_invalid_plan(self, playbook, compass, nerve, state_dir):
        d = self._make_dispatch(playbook, compass, nerve, state_dir)
        result = await d.submit({"steps": []})
        assert result["ok"] is False

    @pytest.mark.asyncio
    async def test_submit_valid_plan_no_temporal(self, playbook, compass, nerve, state_dir, tmp_path):
        os.environ["DAEMON_HOME"] = str(tmp_path)
        d = self._make_dispatch(playbook, compass, nerve, state_dir)
        plan = {"steps": [{"id": "collect", "agent": "collect", "depends_on": []}], "task_type": "research_report"}
        result = await d.submit(plan)
        assert result["ok"] is True
        assert "task_id" in result

    def test_new_task_id_format(self):
        tid = _new_task_id()
        assert tid.startswith("task_")
        parts = tid.split("_")
        assert len(parts) == 3


# ── Delivery ──────────────────────────────────────────────────────────────────

class TestDeliveryService:
    def _make_delivery(self, compass, nerve, tmp_path):
        (tmp_path / "outcome").mkdir(exist_ok=True)
        (tmp_path / "outcome" / "index.json").write_text("[]")
        return DeliveryService(compass, nerve, tmp_path)

    def test_quality_gate_passes(self, compass, nerve, tmp_path):
        d = self._make_delivery(compass, nerve, tmp_path)
        profile = {"min_word_count": 5, "forbidden_markers": ["[INTERNAL]"]}
        result = d._quality_gate("This is sufficient content here yes.", profile)
        assert result["ok"] is True

    def test_quality_gate_forbidden_marker(self, compass, nerve, tmp_path):
        d = self._make_delivery(compass, nerve, tmp_path)
        profile = {"forbidden_markers": ["[INTERNAL]"]}
        result = d._quality_gate("Content [INTERNAL] marker here.", profile)
        assert result["ok"] is False
        assert result["error_code"] == "forbidden_marker"

    def test_quality_gate_word_count(self, compass, nerve, tmp_path):
        d = self._make_delivery(compass, nerve, tmp_path)
        profile = {"min_word_count": 100}
        result = d._quality_gate("Too short.", profile)
        assert result["ok"] is False

    def test_quality_gate_sections(self, compass, nerve, tmp_path):
        d = self._make_delivery(compass, nerve, tmp_path)
        profile = {"min_sections": 2}
        result = d._quality_gate("# Section 1\nContent here.", profile)
        assert result["ok"] is False
        assert result["error_code"] == "sections_too_few"

    def test_archive_creates_files(self, compass, nerve, tmp_path):
        d = self._make_delivery(compass, nerve, tmp_path)
        render_file = tmp_path / "report.md"
        render_file.write_text("# Report\n\nContent here.")
        plan = {"task_id": "t1", "title": "Test Report", "task_type": "manual"}
        dest = d._archive("run_001", plan, render_file)
        assert (dest / "report.md").exists()
        assert (dest / "manifest.json").exists()

    def test_update_index(self, compass, nerve, tmp_path):
        d = self._make_delivery(compass, nerve, tmp_path)
        dest = tmp_path / "outcome" / "manual" / "test"
        dest.mkdir(parents=True)
        plan = {"task_id": "t1", "title": "T", "task_type": "manual"}
        d._update_index(dest, plan)
        index = json.loads((tmp_path / "outcome" / "index.json").read_text())
        assert len(index) == 1

    def test_deliver_no_render_output(self, compass, nerve, tmp_path):
        d = self._make_delivery(compass, nerve, tmp_path)
        result = d.deliver("run_999", {"task_type": "manual"}, [])
        assert result["ok"] is False
        assert result["error_code"] == "render_output_missing"

    def test_deliver_full_pipeline(self, compass, nerve, tmp_path):
        d = self._make_delivery(compass, nerve, tmp_path)
        # Create fake render output.
        run_root = tmp_path / "runs" / "run_001"
        render_dir = run_root / "steps" / "render_1" / "output"
        render_dir.mkdir(parents=True)
        (render_dir / "output.md").write_text("# Report\n\n" + "Content word. " * 120)
        plan = {"task_id": "t1", "title": "Test", "task_type": "manual"}
        result = d.deliver(str(run_root), plan, [{"step_id": "render_1", "status": "ok"}])
        assert result["ok"] is True
        assert "outcome_path" in result


# ── Scheduler helpers ─────────────────────────────────────────────────────────

class TestScheduler:
    def test_parse_cron_every_10_min(self):
        assert Scheduler._parse_cron_simple("*/10 * * * *") == 600

    def test_parse_cron_daily(self):
        assert Scheduler._parse_cron_simple("0 3 * * *") == 86400

    def test_parse_duration_hours(self):
        assert Scheduler._parse_duration("4h") == 4 * 3600

    def test_parse_duration_minutes(self):
        assert Scheduler._parse_duration("30m") == 1800

    def test_parse_duration_mixed(self):
        assert Scheduler._parse_duration("2h30m") == 2 * 3600 + 30 * 60

    def test_parse_duration_invalid(self):
        assert Scheduler._parse_duration("abc") is None
