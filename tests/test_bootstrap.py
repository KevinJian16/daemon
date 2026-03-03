"""Tests for cold-start bootstrap."""
import json
import pytest
from pathlib import Path
from bootstrap import bootstrap, _validate_openclaw


class TestBootstrap:
    def test_bootstrap_creates_dbs(self, tmp_path):
        rep = bootstrap(daemon_home=tmp_path)
        assert (tmp_path / "state" / "memory.db").exists()
        assert (tmp_path / "state" / "playbook.db").exists()
        assert (tmp_path / "state" / "compass.db").exists()

    def test_bootstrap_creates_gate(self, tmp_path):
        bootstrap(daemon_home=tmp_path)
        gate = json.loads((tmp_path / "state" / "gate.json").read_text())
        assert gate["status"] == "GREEN"

    def test_bootstrap_creates_outcome_index(self, tmp_path):
        bootstrap(daemon_home=tmp_path)
        index = json.loads((tmp_path / "outcome" / "index.json").read_text())
        assert index == []

    def test_bootstrap_seeds_playbook(self, tmp_path):
        rep = bootstrap(daemon_home=tmp_path)
        assert rep["fabric"]["playbook"]["methods_seeded"] == 4

    def test_bootstrap_idempotent(self, tmp_path):
        rep1 = bootstrap(daemon_home=tmp_path)
        rep2 = bootstrap(daemon_home=tmp_path)
        # Second run: new=False, no re-seeding.
        assert rep1["fabric"]["playbook"]["methods_seeded"] == 4
        assert rep2["fabric"]["playbook"]["methods_seeded"] == 0

    def test_bootstrap_no_openclaw(self, tmp_path):
        rep = bootstrap(daemon_home=tmp_path, openclaw_home=None)
        assert rep["openclaw_validation"].get("skipped") is True

    def test_validate_openclaw_missing_config(self, tmp_path):
        result = _validate_openclaw(tmp_path)
        assert result["ok"] is False
        assert any("openclaw.json" in w for w in result["warnings"])

    def test_validate_openclaw_missing_agents(self, tmp_path):
        cfg = {
            "agents": {"list": [{"id": "router"}, {"id": "collect"}]},
            "gateway": {"port": 18789, "auth": {"token": "test"}},
        }
        (tmp_path / "openclaw.json").write_text(json.dumps(cfg))
        result = _validate_openclaw(tmp_path)
        assert any("missing" in w.lower() for w in result["warnings"])
        assert "build" in result["missing_agents"]

    def test_validate_openclaw_all_agents_present(self, tmp_path):
        agents = ["router", "collect", "analyze", "build", "review", "render", "apply"]
        cfg = {"agents": {"list": [{"id": a} for a in agents]}, "gateway": {"port": 18789, "auth": {"token": "t"}}}
        (tmp_path / "openclaw.json").write_text(json.dumps(cfg))
        for a in agents:
            (tmp_path / "workspace" / a).mkdir(parents=True)
        (tmp_path / "defaults").mkdir()
        result = _validate_openclaw(tmp_path)
        assert result["missing_agents"] == []
