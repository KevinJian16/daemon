"""Tests for Temporal workflow DAG logic (unit tests -- no Temporal server needed)."""
import pytest
from temporal.workflows import GraphWillWorkflow, DeedInput


class TestGraphWillWorkflow:
    """Test workflow helper methods that don't require Temporal runtime."""

    def setup_method(self):
        self.wf = GraphWillWorkflow()

    def test_move_id_from_id_field(self):
        assert self.wf._move_id({"id": "scout_1"}, 0) == "scout_1"

    def test_move_id_from_index(self):
        assert self.wf._move_id({}, 3) == "move_3"

    def test_deps_from_depends_on(self):
        assert self.wf._deps({"depends_on": ["a", "b"]}) == ["a", "b"]

    def test_deps_empty(self):
        assert self.wf._deps({}) == []

    def test_agent(self):
        assert self.wf._agent({"agent": "scout"}) == "scout"
        assert self.wf._agent({}) == ""

    def test_agent_limits_defaults(self):
        limits = self.wf._agent_limits({})
        assert limits["scout"] == 8
        assert limits["envoy"] == 1
        assert limits["artificer"] == 2

    def test_agent_limits_plan_override(self):
        limits = self.wf._agent_limits({"agent_concurrency": {"scout": 3}})
        assert limits["scout"] == 3
        assert limits["sage"] == 4  # default preserved

    def test_timeouts_default(self):
        st, sc = self.wf._timeouts({}, {})
        assert st.total_seconds() == 480
        assert sc.total_seconds() == 510

    def test_timeouts_move_override(self):
        st, sc = self.wf._timeouts({}, {"timeout_s": 300})
        assert st.total_seconds() == 300

    def test_timeouts_plan_hint(self):
        st, sc = self.wf._timeouts({"timeout_hints": {"scout": 600}}, {"agent": "scout"})
        assert st.total_seconds() == 600

    def test_rework_moves_arbiter_rejected(self):
        move_list = [
            {"id": "scout", "agent": "scout"},
            {"id": "sage", "agent": "sage"},
            {"id": "arbiter", "agent": "arbiter"},
            {"id": "scribe", "agent": "scribe"},
        ]
        moves = self.wf._rework_moves(move_list, "arbiter_rejected", 1)
        agents = [self.wf._agent(m) for m in moves]
        assert "arbiter" in agents
        assert "scribe" in agents

    def test_rework_moves_collection_failure(self):
        move_list = [
            {"id": "scout", "agent": "scout"},
            {"id": "sage", "agent": "sage"},
            {"id": "scribe", "agent": "scribe"},
        ]
        moves = self.wf._rework_moves(move_list, "glance_items_too_few", 1)
        agents = [self.wf._agent(m) for m in moves]
        assert "scout" in agents

    def test_rework_move_ids_get_suffix(self):
        move_list = [{"id": "scribe_1", "agent": "scribe"}]
        moves = self.wf._rework_moves(move_list, "arbiter_rejected", 2)
        assert moves[0]["id"] == "scribe_1_rework_2"

    def test_rework_instruction_appended(self):
        move_list = [{"id": "scribe_1", "agent": "scribe", "instruction": "Original"}]
        moves = self.wf._rework_moves(move_list, "arbiter_rejected", 1)
        assert "Original" in moves[0]["instruction"]
        assert "Rework" in moves[0]["instruction"]

    def test_rework_no_moves_for_empty_dag(self):
        moves = self.wf._rework_moves([], "arbiter_rejected", 1)
        assert moves == []

    def test_last_arbiter_result(self):
        results = [
            {"move_id": "scout_1", "status": "ok"},
            {"move_id": "arbiter_1", "status": "ok", "arbiter_verdict": "pass"},
        ]
        arbiter_result = self.wf._last_arbiter_result(results)
        assert arbiter_result is not None
        assert arbiter_result["move_id"] == "arbiter_1"

    def test_needs_rework_verdict(self):
        assert self.wf._needs_rework({"arbiter_verdict": "rework"}) is True
        assert self.wf._needs_rework({"arbiter_verdict": "pass"}) is False
        assert self.wf._needs_rework({"status": "rework"}) is True
        assert self.wf._needs_rework({"status": "ok"}) is False


class TestDaemonActivities:
    """Test activity helper logic that doesn't require Temporal runtime or OpenClaw."""

    def setup_method(self, tmp_path_factory):
        import os
        self.tmp = None

    def test_update_deed_status_creates_file(self, tmp_path):
        from temporal.activities import DaemonActivities
        import os, json
        os.environ["DAEMON_HOME"] = str(tmp_path)
        acts = DaemonActivities()
        acts._update_deed_status("deed_001", {"deed_id": "t1"}, "running")
        recent_deeds = json.loads((tmp_path / "state" / "deeds.json").read_text())
        assert any(t["deed_id"] == "t1" and t["deed_status"] == "running" for t in recent_deeds)

    def test_update_deed_status_atomic(self, tmp_path):
        """Verify no partial write: .tmp file cleaned up."""
        from temporal.activities import DaemonActivities
        import os
        os.environ["DAEMON_HOME"] = str(tmp_path)
        acts = DaemonActivities()
        acts._update_deed_status("deed_001", {"deed_id": "t1"}, "running")
        tmp_candidates = list((tmp_path / "state").glob("deeds.json.tmp*"))
        assert len(tmp_candidates) == 0

    def test_update_offering_index(self, tmp_path):
        from temporal.activities import DaemonActivities
        import os
        os.environ["DAEMON_HOME"] = str(tmp_path)
        (tmp_path / "offerings").mkdir()
        acts = DaemonActivities()
        acts._update_offering_index(tmp_path / "offerings" / "2026-03" / "deed1", {"title": "T", "complexity": "charge", "deed_id": "t1"})
        log = acts._ledger.load_herald_log()
        assert len(log) == 1
        assert log[0]["deed_id"] == "t1"
