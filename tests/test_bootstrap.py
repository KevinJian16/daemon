"""Tests for cold-start bootstrap."""
import json
import pytest
from pathlib import Path
from bootstrap import bootstrap, _validate_openclaw


class TestBootstrap:
    def test_bootstrap_creates_dbs(self, tmp_path):
        rep = bootstrap(daemon_home=tmp_path)
        assert (tmp_path / "state" / "psyche" / "memory.db").exists()
        assert (tmp_path / "state" / "psyche" / "lore.db").exists()
        assert (tmp_path / "state" / "psyche" / "instinct.db").exists()

    def test_bootstrap_creates_ward(self, tmp_path):
        bootstrap(daemon_home=tmp_path)
        ward = json.loads((tmp_path / "state" / "ward.json").read_text())
        assert ward["status"] == "GREEN"

    def test_bootstrap_creates_herald_log(self, tmp_path):
        bootstrap(daemon_home=tmp_path)
        log_path = tmp_path / "state" / "herald_log.jsonl"
        assert log_path.exists()
        assert log_path.read_text() == ""

    def test_bootstrap_idempotent(self, tmp_path):
        rep1 = bootstrap(daemon_home=tmp_path)
        rep2 = bootstrap(daemon_home=tmp_path)
        assert rep1["psyche"]["lore"]["new"] is True
        assert rep2["psyche"]["lore"]["new"] is False

    def test_bootstrap_no_openclaw(self, tmp_path):
        rep = bootstrap(daemon_home=tmp_path, openclaw_home=None)
        assert rep["openclaw_validation"].get("skipped") is True

    def test_validate_openclaw_missing_config(self, tmp_path):
        result = _validate_openclaw(tmp_path)
        assert result["ok"] is False
        assert any("openclaw.json" in w for w in result["warnings"])

    def test_validate_openclaw_missing_agents(self, tmp_path):
        cfg = {
            "agents": {"list": [{"id": "counsel"}, {"id": "scout"}]},
            "gateway": {"port": 18789, "auth": {"token": "test"}},
        }
        (tmp_path / "openclaw.json").write_text(json.dumps(cfg))
        result = _validate_openclaw(tmp_path)
        assert any("missing" in w.lower() for w in result["warnings"])
        assert "artificer" in result["missing_agents"]

    def test_validate_openclaw_all_agents_present(self, tmp_path):
        agents = ["counsel", "scout", "sage", "artificer", "arbiter", "scribe", "envoy"]
        cfg = {"agents": {"list": [{"id": a} for a in agents]}, "gateway": {"port": 18789, "auth": {"token": "t"}}}
        (tmp_path / "openclaw.json").write_text(json.dumps(cfg))
        for a in agents:
            (tmp_path / "workspace" / a).mkdir(parents=True)
        (tmp_path / "defaults").mkdir()
        result = _validate_openclaw(tmp_path)
        assert result["missing_agents"] == []
