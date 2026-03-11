"""Tests for Spine components: Nerve, Trail, Canon, Routines."""
import json
import pytest
from pathlib import Path

from spine.nerve import Nerve
from spine.trail import Trail
from spine.canon import SpineCanon
from psyche.memory import MemoryPsyche
from psyche.lore import LorePsyche
from psyche.instinct import InstinctPsyche
from runtime.cortex import Cortex
from spine.routines import SpineRoutines


# -- Nerve ---------------------------------------------------------------------

class TestNerve:
    def test_emit_and_recent(self):
        nerve = Nerve()
        nerve.emit("test_event", {"value": 1})
        recent = nerve.recent(10)
        assert len(recent) == 1
        assert recent[0]["event"] == "test_event"
        assert recent[0]["payload"]["value"] == 1

    def test_handler_called(self):
        nerve = Nerve()
        received = []
        nerve.on("my_event", lambda p: received.append(p))
        nerve.emit("my_event", {"x": 42})
        assert received == [{"x": 42}]

    def test_handler_error_does_not_propagate(self):
        nerve = Nerve()
        def bad_handler(p):
            raise RuntimeError("oops")
        nerve.on("ev", bad_handler)
        eid = nerve.emit("ev", {})
        record = nerve.recent(1)[0]
        assert len(record["handler_errors"]) == 1
        assert "oops" in record["handler_errors"][0]["error"]

    def test_history_limit(self):
        nerve = Nerve(history_size=5)
        for i in range(10):
            nerve.emit("ev", {"i": i})
        assert len(nerve.recent(100)) == 5

    def test_event_count(self):
        nerve = Nerve()
        nerve.emit("a", {})
        nerve.emit("a", {})
        nerve.emit("b", {})
        counts = nerve.event_count()
        assert counts["a"] == 2
        assert counts["b"] == 1


# -- Trail ---------------------------------------------------------------------

class TestTrail:
    def test_span_ok(self, tmp_path):
        trail = Trail(tmp_path / "traces")
        with trail.span("spine.test", "manual") as ctx:
            ctx.step("step1", "detail1")
            ctx.set_result({"ok": True})

        recent = trail.recent(10)
        assert len(recent) == 1
        assert recent[0]["status"] == "ok"
        assert recent[0]["routine"] == "spine.test"

    def test_span_error_recorded(self, tmp_path):
        trail = Trail(tmp_path / "traces")
        with pytest.raises(ValueError):
            with trail.span("spine.test", "manual"):
                raise ValueError("something went wrong")
        recent = trail.recent(10)
        assert recent[0]["status"] == "error"
        assert "ValueError" in recent[0]["error"]

    def test_span_degraded(self, tmp_path):
        trail = Trail(tmp_path / "traces")
        with trail.span("spine.test") as ctx:
            ctx.mark_degraded("Cortex down")
        assert trail.recent(1)[0]["degraded"] is True

    def test_persistence_to_file(self, tmp_path):
        traces_dir = tmp_path / "traces"
        trail = Trail(traces_dir)
        with trail.span("spine.test") as ctx:
            ctx.set_result({"written": True})
        files = list(traces_dir.glob("*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["routine"] == "spine.test"

    def test_query_filter(self, tmp_path):
        trail = Trail(tmp_path / "traces")
        with trail.span("spine.pulse") as ctx:
            ctx.set_result({"ward": "GREEN"})
        with trail.span("spine.learn") as ctx:
            ctx.set_result({})

        pulse_only = trail.query(routine="spine.pulse")
        assert len(pulse_only) == 1
        assert pulse_only[0]["routine"] == "spine.pulse"


# -- Canon ---------------------------------------------------------------------

class TestSpineCanon:
    def test_loads_all_routines(self, tmp_path):
        reg_path = Path(__file__).parent.parent / "config" / "spine_registry.json"
        canon = SpineCanon(reg_path)
        names = canon.all_names()
        assert "spine.pulse" in names
        assert "spine.record" in names
        assert "spine.curate" in names
        assert len(names) >= 9

    def test_get_routine(self, tmp_path):
        reg_path = Path(__file__).parent.parent / "config" / "spine_registry.json"
        canon = SpineCanon(reg_path)
        pulse = canon.get("spine.pulse")
        assert pulse is not None
        assert pulse.is_deterministic
        assert not pulse.is_hybrid

    def test_hybrid_routines(self):
        reg_path = Path(__file__).parent.parent / "config" / "spine_registry.json"
        canon = SpineCanon(reg_path)
        hybrids = [r.name for r in canon.all() if r.is_hybrid]
        assert set(hybrids) == {"spine.witness", "spine.distill", "spine.learn", "spine.focus"}

    def test_by_trigger(self):
        reg_path = Path(__file__).parent.parent / "config" / "spine_registry.json"
        canon = SpineCanon(reg_path)
        triggered = canon.by_trigger("deed_closed")
        assert any(r.name == "spine.record" for r in triggered)


# -- Spine Routines ------------------------------------------------------------

@pytest.fixture
def spine_ctx(tmp_path):
    memory = MemoryPsyche(tmp_path / "memory.db")
    lore = LorePsyche(tmp_path / "lore.db")
    instinct = InstinctPsyche(tmp_path / "instinct.db")
    cortex = Cortex(instinct)  # No API keys in test -- is_available() == False
    nerve = Nerve()
    trail = Trail(tmp_path / "traces")

    routines = SpineRoutines(
        memory=memory,
        lore=lore,
        instinct=instinct,
        cortex=cortex,
        nerve=nerve,
        trail=trail,
        daemon_home=tmp_path,
        openclaw_home=None,
    )
    return routines


class TestSpineRoutines:
    def test_pulse_no_openclaw(self, spine_ctx):
        result = spine_ctx.pulse()
        assert "ward" in result
        assert result["ward"] in ("GREEN", "YELLOW", "RED")
        ward_path = spine_ctx.state_dir / "ward.json"
        assert ward_path.exists()

    def test_pulse_writes_ward_file(self, spine_ctx, tmp_path):
        spine_ctx.pulse()
        ward = json.loads((tmp_path / "state" / "ward.json").read_text())
        assert ward["status"] in ("GREEN", "YELLOW", "RED")

    def test_record(self, spine_ctx):
        result = spine_ctx.record(
            deed_id="deed_001",
            plan={"brief": {"objective": "Test"}, "title": "Test"},
            move_results=[{"status": "ok", "provider": "minimax", "tokens_used": 1000, "elapsed_s": 10}],
            offering={"ok": True, "score": 0.9},
        )
        assert result["deed_id"] == "deed_001"
        assert result["offering"] == "success"

    def test_witness_insufficient_data(self, spine_ctx):
        result = spine_ctx.witness()
        assert result.get("skipped") is True

    def test_witness_with_sufficient_records(self, spine_ctx):
        for i in range(5):
            spine_ctx.lore.record(
                deed_id=f"deed_w{i}",
                objective_text=f"Task {i}",
                dag_budget=6,
                move_count=3,
                plan_structure={"moves": ["scout", "sage", "scribe"]},
                offering_quality={"quality_score": 0.85},
                token_consumption={"minimax": 5000},
                success=True,
                duration_s=200.0,
            )
        result = spine_ctx.witness()
        assert "analyzed" in result
        assert result["analyzed"] >= 3

    def test_learn_no_deed_id(self, spine_ctx):
        result = spine_ctx.learn()
        assert result.get("skipped") is True

    def test_distill(self, spine_ctx):
        result = spine_ctx.distill()
        assert "decayed" in result
        assert "evicted" in result

    def test_focus(self, spine_ctx):
        result = spine_ctx.focus()
        assert "total_entries" in result

    def test_relay_no_openclaw(self, spine_ctx, tmp_path):
        result = spine_ctx.relay()
        assert result["snapshots"] == 5
        assert (tmp_path / "state" / "snapshots" / "memory_snapshot.json").exists()
        assert (tmp_path / "state" / "snapshots" / "lore_snapshot.json").exists()
        assert (tmp_path / "state" / "snapshots" / "instinct_snapshot.json").exists()
        assert (tmp_path / "state" / "snapshots" / "model_policy_snapshot.json").exists()

    def test_tend(self, spine_ctx):
        result = spine_ctx.tend()
        assert "traces_cleaned" in result
        assert "rations_checked" in result

    def test_nerve_integration(self, spine_ctx):
        events = []
        spine_ctx.nerve.on("ward_changed", lambda p: events.append(p))
        spine_ctx.pulse()
        # Ward starts unset (defaults GREEN) -> pulse may or may not emit event
        # Just verify no crash and pulse completes.
