"""Tests for Spine components: Nerve, Tracer, Registry, Routines."""
import json
import pytest
from pathlib import Path

from spine.nerve import Nerve
from spine.trace import Tracer
from spine.registry import SpineRegistry
from fabric.memory import MemoryFabric
from fabric.playbook import PlaybookFabric, BOOTSTRAP_METHODS
from fabric.compass import CompassFabric, BOOTSTRAP_PRIORITIES, BOOTSTRAP_QUALITY_PROFILES
from runtime.cortex import Cortex
from spine.routines import SpineRoutines


# ── Nerve ─────────────────────────────────────────────────────────────────────

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


# ── Tracer ────────────────────────────────────────────────────────────────────

class TestTracer:
    def test_span_ok(self, tmp_path):
        tracer = Tracer(tmp_path / "traces")
        with tracer.span("spine.test", "manual") as ctx:
            ctx.step("step1", "detail1")
            ctx.set_result({"ok": True})

        recent = tracer.recent(10)
        assert len(recent) == 1
        assert recent[0]["status"] == "ok"
        assert recent[0]["routine"] == "spine.test"

    def test_span_error_recorded(self, tmp_path):
        tracer = Tracer(tmp_path / "traces")
        with pytest.raises(ValueError):
            with tracer.span("spine.test", "manual"):
                raise ValueError("something went wrong")
        recent = tracer.recent(10)
        assert recent[0]["status"] == "error"
        assert "ValueError" in recent[0]["error"]

    def test_span_degraded(self, tmp_path):
        tracer = Tracer(tmp_path / "traces")
        with tracer.span("spine.test") as ctx:
            ctx.mark_degraded("Cortex down")
        assert tracer.recent(1)[0]["degraded"] is True

    def test_persistence_to_file(self, tmp_path):
        traces_dir = tmp_path / "traces"
        tracer = Tracer(traces_dir)
        with tracer.span("spine.test") as ctx:
            ctx.set_result({"written": True})
        files = list(traces_dir.glob("*.jsonl"))
        assert len(files) == 1
        lines = files[0].read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["routine"] == "spine.test"

    def test_query_filter(self, tmp_path):
        tracer = Tracer(tmp_path / "traces")
        with tracer.span("spine.pulse") as ctx:
            ctx.set_result({"gate": "GREEN"})
        with tracer.span("spine.intake") as ctx:
            ctx.set_result({})

        pulse_only = tracer.query(routine="spine.pulse")
        assert len(pulse_only) == 1
        assert pulse_only[0]["routine"] == "spine.pulse"


# ── Registry ──────────────────────────────────────────────────────────────────

class TestSpineRegistry:
    def test_loads_all_routines(self, tmp_path):
        reg_path = Path(__file__).parent.parent / "config" / "spine_registry.json"
        reg = SpineRegistry(reg_path)
        names = reg.all_names()
        assert "spine.pulse" in names
        assert "spine.record" in names
        assert len(names) == 10

    def test_get_routine(self, tmp_path):
        reg_path = Path(__file__).parent.parent / "config" / "spine_registry.json"
        reg = SpineRegistry(reg_path)
        pulse = reg.get("spine.pulse")
        assert pulse is not None
        assert pulse.is_deterministic
        assert not pulse.is_hybrid

    def test_hybrid_routines(self):
        reg_path = Path(__file__).parent.parent / "config" / "spine_registry.json"
        reg = SpineRegistry(reg_path)
        hybrids = [r.name for r in reg.all() if r.is_hybrid]
        assert set(hybrids) == {"spine.witness", "spine.distill", "spine.learn", "spine.focus"}

    def test_by_trigger(self):
        reg_path = Path(__file__).parent.parent / "config" / "spine_registry.json"
        reg = SpineRegistry(reg_path)
        triggered = reg.by_trigger("collect_completed")
        assert any(r.name == "spine.intake" for r in triggered)


# ── Spine Routines ────────────────────────────────────────────────────────────

@pytest.fixture
def spine_ctx(tmp_path):
    memory = MemoryFabric(tmp_path / "memory.db")
    playbook = PlaybookFabric(tmp_path / "playbook.db")
    compass = CompassFabric(tmp_path / "compass.db")
    cortex = Cortex(compass)  # No API keys in test — is_available() == False
    nerve = Nerve()
    tracer = Tracer(tmp_path / "traces")

    # Seed bootstrap data.
    for m in BOOTSTRAP_METHODS:
        playbook.register(m["name"], m["category"], m["spec"], m["description"], "active")
    for p in BOOTSTRAP_PRIORITIES:
        compass.set_priority(p["domain"], p["weight"], source="bootstrap")

    routines = SpineRoutines(
        memory=memory,
        playbook=playbook,
        compass=compass,
        cortex=cortex,
        nerve=nerve,
        tracer=tracer,
        daemon_home=tmp_path,
        openclaw_home=None,
    )
    return routines


class TestSpineRoutines:
    def test_pulse_no_openclaw(self, spine_ctx):
        result = spine_ctx.pulse()
        assert "gate" in result
        assert result["gate"] in ("GREEN", "YELLOW", "RED")
        # Gate file written.
        gate_path = spine_ctx.state_dir / "gate.json"
        assert gate_path.exists()

    def test_pulse_writes_gate_file(self, spine_ctx, tmp_path):
        spine_ctx.pulse()
        gate = json.loads((tmp_path / "state" / "gate.json").read_text())
        assert gate["status"] in ("GREEN", "YELLOW", "RED")

    def test_intake_no_openclaw(self, spine_ctx):
        result = spine_ctx.intake()
        assert result["inserted"] == 0
        assert result["files"] == 0

    def test_intake_with_signals(self, spine_ctx, tmp_path):
        signals_dir = tmp_path / "openclaw" / "runs" / "run_001" / "steps" / "collect_1" / "internal"
        signals_dir.mkdir(parents=True)
        signals = [{"title": "Signal A", "domain": "ai_research", "provider": "hn"}]
        (signals_dir / "signals_prepare.json").write_text(json.dumps(signals))
        spine_ctx.openclaw_home = tmp_path / "openclaw"
        result = spine_ctx.intake()
        assert result["inserted"] == 1

    def test_record(self, spine_ctx):
        result = spine_ctx.record(
            task_id="task_001",
            plan={"method": "research_report", "title": "Test"},
            step_results=[{"status": "ok"}],
            outcome={"ok": True, "score": 0.9},
        )
        assert result["task_id"] == "task_001"
        assert result["outcome"] == "success"

    def test_witness_insufficient_data(self, spine_ctx):
        result = spine_ctx.witness()
        assert result.get("skipped") is True

    def test_witness_with_data_degrades_gracefully(self, spine_ctx):
        mid = spine_ctx.playbook.consult()[0]["method_id"]
        for i in range(5):
            spine_ctx.playbook.evaluate(mid, f"t{i}", "success", 1.0)
        # Cortex unavailable → should degrade to stats_only.
        result = spine_ctx.witness()
        # Either ran (degraded) or skipped (< 3 unanalyzed if bootstrap evals counted).
        assert "degraded" in result or result.get("skipped")

    def test_distill_empty_memory(self, spine_ctx):
        result = spine_ctx.distill()
        assert result["units_processed"] == 0

    def test_distill_degrades_gracefully(self, spine_ctx):
        spine_ctx.memory.intake([
            {"title": "Unit A", "domain": "ai", "provider": "x"},
            {"title": "Unit A", "domain": "ai", "provider": "y"},  # Same title.
        ])
        result = spine_ctx.distill()
        assert "units_processed" in result
        # String fallback should have found duplicate.
        assert result["archived"] >= 1 or result.get("degraded")

    def test_judge(self, spine_ctx):
        result = spine_ctx.judge()
        assert "checked" in result
        assert "promoted" in result
        assert "retired" in result

    def test_relay_no_openclaw(self, spine_ctx, tmp_path):
        result = spine_ctx.relay()
        assert result["snapshots"] == 3
        assert (tmp_path / "state" / "snapshots" / "memory_snapshot.json").exists()
        assert (tmp_path / "state" / "snapshots" / "playbook_snapshot.json").exists()
        assert (tmp_path / "state" / "snapshots" / "compass_snapshot.json").exists()

    def test_tend(self, spine_ctx):
        result = spine_ctx.tend()
        assert "memory_archived" in result
        assert "tasks_replayed" in result

    def test_nerve_integration(self, spine_ctx):
        events = []
        spine_ctx.nerve.on("intake_completed", lambda p: events.append(p))
        spine_ctx.intake()
        assert len(events) == 1
