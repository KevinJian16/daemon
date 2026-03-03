"""Tests for Temporal workflow DAG logic (unit tests — no Temporal server needed)."""
import pytest
from temporal.workflows import GraphDispatchWorkflow, RunInput


class TestGraphDispatchWorkflow:
    """Test workflow helper methods that don't require Temporal runtime."""

    def setup_method(self):
        self.wf = GraphDispatchWorkflow()

    def test_step_id_from_id_field(self):
        assert self.wf._step_id({"id": "collect_1"}, 0) == "collect_1"

    def test_step_id_from_index(self):
        assert self.wf._step_id({}, 3) == "step_3"

    def test_deps_from_depends_on(self):
        assert self.wf._deps({"depends_on": ["a", "b"]}) == ["a", "b"]

    def test_deps_empty(self):
        assert self.wf._deps({}) == []

    def test_agent(self):
        assert self.wf._agent({"agent": "collect"}) == "collect"
        assert self.wf._agent({}) == ""

    def test_agent_limits_defaults(self):
        limits = self.wf._agent_limits({})
        assert limits["collect"] == 8
        assert limits["apply"] == 1
        assert limits["build"] == 2

    def test_agent_limits_plan_override(self):
        limits = self.wf._agent_limits({"agent_concurrency": {"collect": 3}})
        assert limits["collect"] == 3
        assert limits["analyze"] == 4  # default preserved

    def test_timeouts_default(self):
        st, sc = self.wf._timeouts({}, {})
        assert st.total_seconds() == 480
        assert sc.total_seconds() == 510

    def test_timeouts_step_override(self):
        st, sc = self.wf._timeouts({}, {"timeout_s": 300})
        assert st.total_seconds() == 300

    def test_timeouts_plan_hint(self):
        st, sc = self.wf._timeouts({"timeout_hints": {"collect": 600}}, {"agent": "collect"})
        assert st.total_seconds() == 600

    def test_rework_steps_quality_failure(self):
        step_list = [
            {"id": "collect", "agent": "collect"},
            {"id": "analyze", "agent": "analyze"},
            {"id": "review", "agent": "review"},
            {"id": "render", "agent": "render"},
        ]
        steps = self.wf._rework_steps(step_list, "quality_gate_failed", 1)
        agents = [self.wf._agent(s) for s in steps]
        assert "review" in agents
        assert "render" in agents

    def test_rework_steps_collection_failure(self):
        step_list = [
            {"id": "collect", "agent": "collect"},
            {"id": "analyze", "agent": "analyze"},
            {"id": "render", "agent": "render"},
        ]
        steps = self.wf._rework_steps(step_list, "brief_items_too_few", 1)
        agents = [self.wf._agent(s) for s in steps]
        assert "collect" in agents

    def test_rework_step_ids_get_suffix(self):
        step_list = [{"id": "render_1", "agent": "render"}]
        steps = self.wf._rework_steps(step_list, "quality_gate_failed", 2)
        assert steps[0]["id"] == "render_1_rework_2"

    def test_rework_instruction_appended(self):
        step_list = [{"id": "render_1", "agent": "render", "instruction": "Original"}]
        steps = self.wf._rework_steps(step_list, "quality_gate_failed", 1)
        assert "Original" in steps[0]["instruction"]
        assert "Rework" in steps[0]["instruction"]

    def test_rework_no_steps_for_empty_dag(self):
        steps = self.wf._rework_steps([], "quality_gate_failed", 1)
        assert steps == []


class TestDaemonActivities:
    """Test activity helper logic that doesn't require Temporal runtime or OpenClaw."""

    def setup_method(self, tmp_path_factory):
        import os
        self.tmp = None  # Will use tmp_path from pytest where needed.

    def test_structural_check_passes(self, tmp_path):
        from temporal.activities import DaemonActivities
        import os
        os.environ["DAEMON_HOME"] = str(tmp_path)
        acts = DaemonActivities()
        profile = {"min_word_count": 5, "forbidden_markers": ["[INTERNAL]"]}
        result = acts._structural_check("This is a sufficient response here.", profile)
        assert result["ok"] is True

    def test_structural_check_forbidden_marker(self, tmp_path):
        from temporal.activities import DaemonActivities
        import os
        os.environ["DAEMON_HOME"] = str(tmp_path)
        acts = DaemonActivities()
        profile = {"forbidden_markers": ["[INTERNAL]"]}
        result = acts._structural_check("Some content [INTERNAL] here.", profile)
        assert result["ok"] is False
        assert result["error_code"] == "forbidden_marker"

    def test_structural_check_word_count_too_low(self, tmp_path):
        from temporal.activities import DaemonActivities
        import os
        os.environ["DAEMON_HOME"] = str(tmp_path)
        acts = DaemonActivities()
        profile = {"min_word_count": 100}
        result = acts._structural_check("Too short.", profile)
        assert result["ok"] is False
        assert result["error_code"] == "word_count_too_low"

    def test_update_task_status_creates_file(self, tmp_path):
        from temporal.activities import DaemonActivities
        import os, json
        os.environ["DAEMON_HOME"] = str(tmp_path)
        acts = DaemonActivities()
        acts._update_task_status("run_001", {"task_id": "t1"}, "completed")
        tasks = json.loads((tmp_path / "state" / "tasks.json").read_text())
        assert any(t["task_id"] == "t1" and t["status"] == "completed" for t in tasks)

    def test_update_task_status_atomic(self, tmp_path):
        """Verify no partial write: .tmp file cleaned up."""
        from temporal.activities import DaemonActivities
        import os
        os.environ["DAEMON_HOME"] = str(tmp_path)
        acts = DaemonActivities()
        acts._update_task_status("run_001", {"task_id": "t1"}, "completed")
        assert not (tmp_path / "state" / "tasks.tmp").exists()

    def test_update_outcome_index(self, tmp_path):
        from temporal.activities import DaemonActivities
        import os, json
        os.environ["DAEMON_HOME"] = str(tmp_path)
        (tmp_path / "outcome").mkdir()
        (tmp_path / "outcome" / "index.json").write_text("[]")
        acts = DaemonActivities()
        acts._update_outcome_index(tmp_path / "outcome" / "manual" / "task1", {"title": "T", "task_type": "manual", "task_id": "t1"})
        index = json.loads((tmp_path / "outcome" / "index.json").read_text())
        assert len(index) == 1
        assert index[0]["task_id"] == "t1"
