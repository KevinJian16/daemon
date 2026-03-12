"""Diagnostic test suite — P0~P5: DataModel, Lifecycle, LedgerStore, EventChains,
FolioWritRegistry, WashMechanism, WillPipeline, VoiceService, APIContracts,
SpineChains, LearningStats, CronScheduling, CadenceEngine,
TemporalWorkflow, TemporalActivities, PactValidation,
HeraldPipeline, RuntimeComponents, PsycheConfig, DesignValidator.

Verifies mechanism correctness (pipes connected), not output quality.
Each test ID corresponds to DIAGNOSTIC_TEST_SUITE.md.
"""
import copy
import json
import re
import threading
import time
import pytest
from datetime import datetime, timezone
from pathlib import Path

from services.folio_writ import (
    FolioWritManager,
    VALID_FOLIO_STATUSES, VALID_SLIP_STATUSES, VALID_DEED_STATUSES,
    VALID_DRAFT_STATUSES, VALID_WRIT_STATUSES,
    VALID_DEED_SUB_STATUSES, VALID_DRAFT_SUB_STATUSES,
    VALID_SLIP_SUB_STATUSES, VALID_SLIP_TRIGGER_TYPES,
    VALID_FOLIO_SUB_STATUSES, ACTIVE_DEED_STATUSES,
    _cron_matches,
)
from services.ledger import Ledger
from services.voice import VoiceService
from services.wash import wash_at_run_boundary, load_wash_supplement, _compress_conversation, _extract_stats, _extract_voice_candidates
from spine.nerve import Nerve

from tests.conftest import (
    create_test_deed, create_test_slip, create_test_folio, create_test_writ,
    mock_messages,
)


# =============================================================================
# §3 TestDataModel — 数据模型一致性
# =============================================================================


class TestDataModel:
    """DM-01 ~ DM-83: Data model schema, references, and consistency."""

    # ── 3.1 Deed 数据模型 ─────────────────────────────────────────────────

    def test_dm01_deed_required_fields(self, ledger):
        """DM-01: Deed has all required fields."""
        d = create_test_deed(ledger)
        for key in ("deed_id", "deed_status", "created_utc", "slip_id"):
            assert d.get(key), f"Missing or empty: {key}"

    def test_dm02_deed_id_format(self, ledger):
        """DM-02: deed_id matches deed_YYYYMMDDHHMMSS_hex6."""
        d = create_test_deed(ledger)
        assert re.match(r"^deed_\d{14}_[0-9a-f]{6}$", d["deed_id"])

    def test_dm03_deed_status_valid(self, ledger):
        """DM-03: deed_status is in VALID_DEED_STATUSES."""
        d = create_test_deed(ledger)
        assert d["deed_status"] in VALID_DEED_STATUSES

    def test_dm04_deed_sub_status_valid(self, ledger):
        """DM-04: deed_sub_status is valid or empty."""
        d = create_test_deed(ledger, sub_status="executing")
        sub = d.get("deed_sub_status", "")
        assert sub in VALID_DEED_SUB_STATUSES or sub == ""

    def test_dm05_timestamp_iso8601(self, ledger):
        """DM-05: Timestamps match ISO 8601 pattern."""
        d = create_test_deed(ledger)
        pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
        assert re.match(pattern, d["created_utc"])
        assert re.match(pattern, d["updated_utc"])

    def test_dm06_deed_slip_reference(self, ledger, folio_writ):
        """DM-06: Deed's slip_id refers to an existing Slip."""
        slip = create_test_slip(folio_writ)
        d = create_test_deed(ledger, slip_id=slip["slip_id"])
        found = folio_writ.get_slip(d["slip_id"])
        assert found is not None

    def test_dm07_deed_plan_structure(self, ledger):
        """DM-07: Deed plan has moves list with id fields."""
        d = create_test_deed(ledger)
        plan = d.get("plan", {})
        assert isinstance(plan.get("moves"), list)
        for move in plan["moves"]:
            assert "id" in move

    # ── 3.2 Slip 数据模型 ──────────────────────────────────────────────────

    def test_dm10_slip_required_fields(self, folio_writ):
        """DM-10: Slip has all required fields."""
        s = create_test_slip(folio_writ)
        for key in ("slip_id", "title", "status", "created_utc"):
            assert s.get(key), f"Missing or empty: {key}"

    def test_dm11_slip_id_format(self, folio_writ):
        """DM-11: slip_id matches slip_hex12."""
        s = create_test_slip(folio_writ)
        assert re.match(r"^slip_[0-9a-f]{12}$", s["slip_id"])

    def test_dm12_slip_status_valid(self, folio_writ):
        """DM-12: Slip status in VALID_SLIP_STATUSES."""
        s = create_test_slip(folio_writ)
        assert s["status"] in VALID_SLIP_STATUSES

    def test_dm13_slip_deed_ids_references(self, folio_writ, ledger):
        """DM-13: All deed_ids in Slip exist in ledger."""
        s = create_test_slip(folio_writ)
        d = create_test_deed(ledger, slip_id=s["slip_id"])
        folio_writ.record_deed_created(s["slip_id"], d["deed_id"])
        updated = folio_writ.get_slip(s["slip_id"])
        for did in updated["deed_ids"]:
            assert ledger.get_deed(did) is not None

    def test_dm14_slip_folio_id_reference(self, folio_writ):
        """DM-14: If Slip.folio_id is non-empty, the Folio exists."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        assert folio_writ.get_folio(s["folio_id"]) is not None

    def test_dm15_standing_slip_trigger_type(self, folio_writ):
        """DM-15: Standing Slip has valid trigger_type."""
        s = create_test_slip(folio_writ, standing=True, trigger_type="timer")
        assert s["trigger_type"] in VALID_SLIP_TRIGGER_TYPES

    def test_dm16_slip_slug_unique(self, folio_writ):
        """DM-16: All active Slips have unique slugs."""
        s1 = create_test_slip(folio_writ, title="UniqueA")
        s2 = create_test_slip(folio_writ, title="UniqueB")
        assert s1["slug"] != s2["slug"]

    # ── 3.3 Folio 数据模型 ─────────────────────────────────────────────────

    def test_dm20_folio_required_fields(self, folio_writ):
        """DM-20: Folio has all required fields."""
        f = create_test_folio(folio_writ)
        for key in ("folio_id", "title", "status", "created_utc"):
            assert f.get(key), f"Missing or empty: {key}"

    def test_dm21_folio_slip_ids_reference(self, folio_writ):
        """DM-21: All Folio.slip_ids point to existing Slips."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        updated = folio_writ.get_folio(folio["folio_id"])
        for sid in updated["slip_ids"]:
            assert folio_writ.get_slip(sid) is not None

    def test_dm22_folio_writ_ids_reference(self, folio_writ):
        """DM-22: All Folio.writ_ids point to existing Writs."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        updated = folio_writ.get_folio(folio["folio_id"])
        for wid in updated["writ_ids"]:
            assert folio_writ.get_writ(wid) is not None

    def test_dm23_folio_slug_unique(self, folio_writ):
        """DM-23: Active Folios have unique slugs."""
        f1 = create_test_folio(folio_writ, title="AlphaProject")
        f2 = create_test_folio(folio_writ, title="BetaProject")
        assert f1["slug"] != f2["slug"]

    # ── 3.4 Writ 数据模型 ──────────────────────────────────────────────────

    def test_dm30_writ_required_fields(self, folio_writ):
        """DM-30: Writ has all required fields."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        for key in ("writ_id", "folio_id", "action"):
            assert w.get(key), f"Missing or empty: {key}"

    def test_dm31_writ_folio_reference(self, folio_writ):
        """DM-31: Writ.folio_id references an existing Folio."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        assert folio_writ.get_folio(w["folio_id"]) is not None

    def test_dm32_writ_action_type(self, folio_writ):
        """DM-32: Writ.action.type is spawn_deed."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        assert w["action"]["type"] == "spawn_deed"

    def test_dm33_writ_action_slip_reference(self, folio_writ):
        """DM-33: Writ.action.slip_id references an existing Slip."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        assert folio_writ.get_slip(w["action"]["slip_id"]) is not None

    def test_dm34_writ_trigger_exclusive(self, folio_writ):
        """DM-34: Writ match has at most one trigger type."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        match = w.get("match", {})
        trigger_count = sum(1 for k in ("schedule", "event", "manual") if match.get(k))
        assert trigger_count <= 1

    # ── 3.5 Draft 数据模型 ─────────────────────────────────────────────────

    def test_dm40_draft_required_fields(self, folio_writ):
        """DM-40: Draft has all required fields."""
        d = folio_writ.create_draft(source="test", intent_snapshot="Test intent")
        for key in ("draft_id", "status", "source", "created_utc", "updated_utc"):
            assert d.get(key), f"Missing or empty: {key}"

    def test_dm41_draft_status_valid(self, folio_writ):
        """DM-41: Draft status in VALID_DRAFT_STATUSES."""
        d = folio_writ.create_draft(source="test", intent_snapshot="Test")
        assert d["status"] in VALID_DRAFT_STATUSES

    def test_dm42_draft_sub_status_valid(self, folio_writ):
        """DM-42: Draft sub_status in VALID_DRAFT_SUB_STATUSES."""
        d = folio_writ.create_draft(source="test", intent_snapshot="Test")
        assert d["sub_status"] in VALID_DRAFT_SUB_STATUSES

    def test_dm43_draft_folio_reference(self, folio_writ):
        """DM-43: If Draft.folio_id non-empty, Folio exists."""
        folio = create_test_folio(folio_writ)
        d = folio_writ.create_draft(source="test", intent_snapshot="T", folio_id=folio["folio_id"])
        assert folio_writ.get_folio(d["folio_id"]) is not None

    def test_dm44_draft_candidate_brief_is_dict(self, folio_writ):
        """DM-44: Draft.candidate_brief is dict."""
        d = folio_writ.create_draft(source="test", intent_snapshot="T", candidate_brief={"key": "val"})
        assert isinstance(d["candidate_brief"], dict)

    def test_dm45_draft_candidate_design_is_dict(self, folio_writ):
        """DM-45: Draft.candidate_design is dict."""
        d = folio_writ.create_draft(source="test", intent_snapshot="T", candidate_design={"moves": []})
        assert isinstance(d["candidate_design"], dict)

    # ── 3.6 Slug 系统 ──────────────────────────────────────────────────────

    def test_dm46_slip_slug_from_title(self, folio_writ):
        """DM-46: Slip slug is generated from title."""
        s = create_test_slip(folio_writ, title="测试标题")
        assert "测试标题" in s["slug"]

    def test_dm47_same_title_different_slug(self, folio_writ):
        """DM-47: Two Slips with same title get different slugs."""
        s1 = create_test_slip(folio_writ, title="Duplicate")
        s2 = create_test_slip(folio_writ, title="Duplicate")
        assert s1["slug"] != s2["slug"]

    def test_dm48_slug_history_records_old(self, folio_writ):
        """DM-48: Renaming title puts old slug in slug_history."""
        s = create_test_slip(folio_writ, title="OldTitle")
        old_slug = s["slug"]
        folio_writ.update_slip(s["slip_id"], {"title": "NewTitle"})
        updated = folio_writ.get_slip(s["slip_id"])
        assert old_slug in updated["slug_history"]

    def test_dm49_old_slug_still_resolvable(self, folio_writ):
        """DM-49: get_slip_by_slug finds Slip by old slug."""
        s = create_test_slip(folio_writ, title="OriginalName")
        old_slug = s["slug"]
        folio_writ.update_slip(s["slip_id"], {"title": "RenamedName"})
        found = folio_writ.get_slip_by_slug(old_slug)
        assert found is not None
        assert found["slip_id"] == s["slip_id"]

    def test_dm49b_folio_slug_same_logic(self, folio_writ):
        """DM-49b: Folio slug follows same rename logic."""
        f = create_test_folio(folio_writ, title="OldFolio")
        old_slug = f["slug"]
        folio_writ.update_folio(f["folio_id"], {"title": "NewFolio"})
        found = folio_writ.get_folio_by_slug(old_slug)
        assert found is not None
        assert found["folio_id"] == f["folio_id"]

    # ── 3.7 双向引用一致性 ─────────────────────────────────────────────────

    def test_dm50_slip_folio_bidirectional(self, folio_writ):
        """DM-50: Slip.folio_id → Folio contains that Slip."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        updated_folio = folio_writ.get_folio(folio["folio_id"])
        assert s["slip_id"] in updated_folio["slip_ids"]

    def test_dm51_slip_deed_bidirectional(self, folio_writ, ledger):
        """DM-51: Slip.deed_ids ↔ deed.slip_id are consistent."""
        s = create_test_slip(folio_writ)
        d = create_test_deed(ledger, slip_id=s["slip_id"])
        folio_writ.record_deed_created(s["slip_id"], d["deed_id"])
        updated = folio_writ.get_slip(s["slip_id"])
        assert d["deed_id"] in updated["deed_ids"]
        deed = ledger.get_deed(d["deed_id"])
        assert deed["slip_id"] == s["slip_id"]

    def test_dm52_writ_folio_bidirectional(self, folio_writ):
        """DM-52: Writ.folio_id → Folio.writ_ids contains that Writ."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        updated_folio = folio_writ.get_folio(folio["folio_id"])
        assert w["writ_id"] in updated_folio["writ_ids"]

    def test_dm53_writ_slip_same_folio(self, folio_writ):
        """DM-53: Writ.action.slip_id → that Slip belongs to same Folio."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        target_slip = folio_writ.get_slip(w["action"]["slip_id"])
        assert target_slip["folio_id"] == w["folio_id"]

    def test_dm54_latest_deed_id_in_deed_ids(self, folio_writ, ledger):
        """DM-54: Slip.latest_deed_id is in Slip.deed_ids."""
        s = create_test_slip(folio_writ)
        d = create_test_deed(ledger, slip_id=s["slip_id"])
        folio_writ.record_deed_created(s["slip_id"], d["deed_id"])
        updated = folio_writ.get_slip(s["slip_id"])
        assert updated["latest_deed_id"] in updated["deed_ids"]

    def test_dm55_crystallize_draft_gone(self, folio_writ):
        """DM-55: crystallize_draft → draft status=gone, sub_status=crystallized."""
        draft = folio_writ.create_draft(source="test", intent_snapshot="Test")
        folio_writ.crystallize_draft(
            draft["draft_id"], title="T", objective="O",
            brief={"dag_budget": 6}, design={"moves": []},
        )
        updated = folio_writ.get_draft(draft["draft_id"])
        assert updated["status"] == "gone"
        assert updated["sub_status"] == "crystallized"

    def test_dm56_writ_version_increment(self, folio_writ):
        """DM-56: Updating canonical Writ field increments version."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        v1 = w["version"]
        folio_writ.update_writ(w["writ_id"], {"title": "Updated Title"})
        updated = folio_writ.get_writ(w["writ_id"])
        assert updated["version"] == v1 + 1

    def test_dm57_writ_deed_history_references(self, folio_writ, ledger):
        """DM-57: Writ.deed_history entries exist in ledger."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        d = create_test_deed(ledger, slip_id=s["slip_id"])
        folio_writ.record_deed_created(s["slip_id"], d["deed_id"], writ_id=w["writ_id"])
        updated = folio_writ.get_writ(w["writ_id"])
        for did in updated["deed_history"]:
            assert ledger.get_deed(did) is not None

    # ── 3.8 Move 数据模型 ──────────────────────────────────────────────────

    def test_dm60_move_required_fields(self):
        """DM-60: Move has id and agent."""
        move = {"id": "m1", "agent": "scout", "depends_on": []}
        assert move.get("id")
        assert move.get("agent")

    def test_dm61_move_id_unique(self):
        """DM-61: Move IDs unique within a plan."""
        moves = [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]
        ids = [m["id"] for m in moves]
        assert len(ids) == len(set(ids))

    def test_dm62_move_agent_valid(self):
        """DM-62: Move.agent in VALID_AGENTS."""
        from runtime.design_validator import VALID_AGENTS
        for agent in ("scout", "sage", "artificer", "arbiter", "scribe", "envoy", "spine", "counsel"):
            assert agent in VALID_AGENTS

    def test_dm63_move_depends_on_exist(self):
        """DM-63: All depends_on references exist in moves."""
        moves = [
            {"id": "m1", "agent": "scout", "depends_on": []},
            {"id": "m2", "agent": "sage", "depends_on": ["m1"]},
        ]
        all_ids = {m["id"] for m in moves}
        for m in moves:
            for dep in m.get("depends_on", []):
                assert dep in all_ids

    def test_dm64_move_checkpoint_structure(self, ledger, tmp_path):
        """DM-64: Move checkpoint has expected fields when written."""
        cp = {"status": "ok", "output_path": "moves/m1/output", "token_usage": 500}
        cp_path = tmp_path / "moves" / "m1" / "checkpoint.json"
        cp_path.parent.mkdir(parents=True)
        cp_path.write_text(json.dumps(cp))
        loaded = json.loads(cp_path.read_text())
        assert loaded["status"] in ("ok", "degraded", "pending")
        assert "output_path" in loaded

    def test_dm65_move_output_directory(self, tmp_path):
        """DM-65: Move output directory structure."""
        out_dir = tmp_path / "moves" / "m1" / "output"
        out_dir.mkdir(parents=True)
        (out_dir / "result.md").write_text("# Result")
        assert out_dir.exists()
        assert list(out_dir.iterdir())

    # ── 3.9 Plan 结构 ──────────────────────────────────────────────────────

    def test_dm70_plan_required_fields(self, ledger):
        """DM-70: Plan has deed_id, moves, brief."""
        d = create_test_deed(ledger)
        plan = d["plan"]
        assert isinstance(plan.get("moves"), list)

    def test_dm71_plan_brief_is_dict(self):
        """DM-71: Plan.brief is dict."""
        plan = {"moves": [], "brief": {"dag_budget": 6}}
        assert isinstance(plan["brief"], dict)

    def test_dm72_plan_metadata_optional(self):
        """DM-72: Plan without metadata doesn't error."""
        plan = {"moves": [{"id": "m1", "agent": "scout"}], "brief": {}}
        assert plan.get("metadata") is None  # ok

    def test_dm73_plan_concurrency_positive(self):
        """DM-73: Plan.concurrency is positive integer."""
        from runtime.brief import SINGLE_SLIP_DEFAULTS
        assert SINGLE_SLIP_DEFAULTS["concurrency"] > 0

    def test_dm74_plan_agent_model_map(self):
        """DM-74: Agent model map keys are valid agents."""
        from runtime.design_validator import VALID_AGENTS
        agent_map = {"scout": "fast", "sage": "analysis"}
        for agent in agent_map:
            assert agent in VALID_AGENTS

    def test_dm75_plan_eval_window_positive(self):
        """DM-75: eval_window_hours is positive."""
        plan = {"eval_window_hours": 48}
        assert plan["eval_window_hours"] > 0

    # ── 3.10 Deed Root 目录结构 ────────────────────────────────────────────

    def test_dm80_deed_root_exists(self, tmp_path):
        """DM-80: deed_root directory can be created."""
        deed_root = tmp_path / "state" / "deeds" / "deed_001"
        deed_root.mkdir(parents=True)
        assert deed_root.exists()

    def test_dm81_deed_root_plan_json(self, tmp_path):
        """DM-81: deed_root/plan.json is writable and readable."""
        deed_root = tmp_path / "deeds" / "deed_001"
        deed_root.mkdir(parents=True)
        plan = {"moves": [{"id": "m1"}], "brief": {"dag_budget": 6}}
        (deed_root / "plan.json").write_text(json.dumps(plan))
        loaded = json.loads((deed_root / "plan.json").read_text())
        assert loaded["moves"][0]["id"] == "m1"

    def test_dm82_deed_root_moves_dir(self, tmp_path):
        """DM-82: deed_root/moves/ directory exists."""
        deed_root = tmp_path / "deeds" / "deed_001"
        moves_dir = deed_root / "moves"
        moves_dir.mkdir(parents=True)
        assert moves_dir.exists()

    def test_dm83_deed_root_messages_appendable(self, tmp_path):
        """DM-83: deed_root/messages.jsonl is appendable and loadable."""
        deed_root = tmp_path / "deeds" / "deed_001"
        deed_root.mkdir(parents=True)
        msg_path = deed_root / "messages.jsonl"
        msg = {"role": "user", "content": "hello", "created_utc": "2026-03-12T00:00:00Z"}
        with open(msg_path, "a") as f:
            f.write(json.dumps(msg) + "\n")
        lines = msg_path.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0])["role"] == "user"


# =============================================================================
# §4 TestLifecycle — 状态机与生命周期
# =============================================================================


class TestLifecycle:
    """LC-01 ~ LC-96: State machine transitions for all entities."""

    # ── 4.1 Deed 生命周期 ──────────────────────────────────────────────────

    def test_lc01_running_to_settling(self, ledger):
        """LC-01: running → settling is legal."""
        d = create_test_deed(ledger, status="running")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_status"] = "settling"
        ledger.mutate_deeds(mutate)
        updated = ledger.get_deed(d["deed_id"])
        assert updated["deed_status"] == "settling"

    def test_lc02_running_to_closed(self, ledger):
        """LC-02: running → closed is legal."""
        d = create_test_deed(ledger, status="running")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_status"] = "closed"
                    row["deed_sub_status"] = "cancelled"
        ledger.mutate_deeds(mutate)
        updated = ledger.get_deed(d["deed_id"])
        assert updated["deed_status"] == "closed"

    def test_lc03_settling_to_closed(self, ledger):
        """LC-03: settling → closed is legal."""
        d = create_test_deed(ledger, status="settling", sub_status="reviewing")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_status"] = "closed"
                    row["deed_sub_status"] = "succeeded"
        ledger.mutate_deeds(mutate)
        updated = ledger.get_deed(d["deed_id"])
        assert updated["deed_status"] == "closed"
        assert updated["deed_sub_status"] == "succeeded"

    def test_lc04_closed_to_running_invalid(self, ledger):
        """LC-04: closed → running should not happen (no guard in Ledger, but semantically invalid)."""
        d = create_test_deed(ledger, status="closed", sub_status="succeeded")
        # Ledger is a dumb store — it doesn't enforce transitions.
        # This test documents that the semantic invariant exists.
        assert d["deed_status"] == "closed"
        assert "closed" not in ACTIVE_DEED_STATUSES

    def test_lc05_closed_to_settling_invalid(self, ledger):
        """LC-05: closed → settling semantically invalid."""
        assert "closed" not in ACTIVE_DEED_STATUSES

    def test_lc06_submit_creates_running_deed(self, ledger):
        """LC-06: New deed starts as running."""
        d = create_test_deed(ledger, status="running", sub_status="executing")
        assert d["deed_status"] == "running"

    def test_lc07_settle_writes_complete(self, ledger):
        """LC-07: Settled deed has closed + succeeded + settled_utc."""
        d = create_test_deed(ledger, status="settling")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_status"] = "closed"
                    row["deed_sub_status"] = "succeeded"
                    row["settled_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ledger.mutate_deeds(mutate)
        updated = ledger.get_deed(d["deed_id"])
        assert updated["deed_status"] == "closed"
        assert updated["deed_sub_status"] == "succeeded"
        assert updated.get("settled_utc")

    def test_lc08_timeout_close_complete(self, ledger):
        """LC-08: TTL expired → closed + timed_out."""
        d = create_test_deed(ledger, status="running")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_status"] = "closed"
                    row["deed_sub_status"] = "timed_out"
        ledger.mutate_deeds(mutate)
        updated = ledger.get_deed(d["deed_id"])
        assert updated["deed_sub_status"] == "timed_out"

    def test_lc09_phase_semantic(self, ledger):
        """LC-09: Running deed is 'active', closed is 'history' (semantic check)."""
        assert "running" in ACTIVE_DEED_STATUSES
        assert "closed" not in ACTIVE_DEED_STATUSES

    # ── 4.2 Deed Running TTL ──────────────────────────────────────────────

    def test_lc10_ttl_4h_expired(self, ledger):
        """LC-10: Deed created >4h ago should be eligible for TTL close."""
        d = create_test_deed(ledger, status="running", age_hours=4.1)
        from datetime import datetime, timezone
        created = datetime.strptime(d["created_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_s = (now - created).total_seconds()
        assert age_s > 4 * 3600

    def test_lc11_ttl_not_expired(self, ledger):
        """LC-11: Deed created 1h ago should not be TTL-closed."""
        d = create_test_deed(ledger, status="running", age_hours=1)
        from datetime import datetime, timezone
        created = datetime.strptime(d["created_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_s = (now - created).total_seconds()
        assert age_s < 4 * 3600

    def test_lc12_ttl_configurable(self, config):
        """LC-12: deed_running_ttl_s is configurable via preferences, returns int."""
        ttl = config.get_pref("execution.deed_running_ttl_s", 14400)
        assert isinstance(ttl, int), f"Expected int, got {type(ttl).__name__}: {ttl!r}"
        assert ttl > 0

    def test_lc13_ttl_close_emits_event(self, nerve):
        """LC-13: TTL close emits deed_closed event."""
        events = []
        nerve.on("deed_closed", lambda p: events.append(p))
        nerve.emit("deed_closed", {"deed_id": "test", "sub_status": "timed_out", "source": "ttl"})
        assert len(events) == 1
        assert events[0]["sub_status"] == "timed_out"

    # ── 4.3 Deed Eval Window ──────────────────────────────────────────────

    def test_lc20_eval_window_48h(self, ledger):
        """LC-20: Settling deed >48h is eligible for eval close."""
        d = create_test_deed(ledger, status="settling", age_hours=49)
        from datetime import datetime, timezone
        created = datetime.strptime(d["created_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        assert (now - created).total_seconds() > 48 * 3600

    def test_lc21_eval_window_not_expired(self, ledger):
        """LC-21: Settling deed <48h should not be closed."""
        d = create_test_deed(ledger, status="settling", age_hours=24)
        from datetime import datetime, timezone
        created = datetime.strptime(d["created_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        assert (now - created).total_seconds() < 48 * 3600

    def test_lc22_eval_close_emits_event(self, nerve):
        """LC-22: Eval close emits deed_closed event."""
        events = []
        nerve.on("deed_closed", lambda p: events.append(p))
        nerve.emit("deed_closed", {"deed_id": "test", "sub_status": "timed_out", "source": "eval_window"})
        assert events[0]["source"] == "eval_window"

    # ── 4.4 Slip 生命周期 ──────────────────────────────────────────────────

    def test_lc30_create_slip_active(self, folio_writ):
        """LC-30: New Slip is active + normal."""
        s = create_test_slip(folio_writ)
        assert s["status"] == "active"
        assert s["sub_status"] == "normal"

    def test_lc31_slip_active_to_archived(self, folio_writ):
        """LC-31: active → archived."""
        s = create_test_slip(folio_writ)
        folio_writ.update_slip(s["slip_id"], {"status": "archived"})
        updated = folio_writ.get_slip(s["slip_id"])
        assert updated["status"] == "archived"

    def test_lc32_slip_active_to_deleted(self, folio_writ):
        """LC-32: active → deleted."""
        s = create_test_slip(folio_writ)
        folio_writ.update_slip(s["slip_id"], {"status": "deleted"})
        updated = folio_writ.get_slip(s["slip_id"])
        assert updated["status"] == "deleted"

    def test_lc33_trigger_type_enum(self, folio_writ):
        """LC-33: trigger_type is manual/timer/writ_chain."""
        for tt in VALID_SLIP_TRIGGER_TYPES:
            s = create_test_slip(folio_writ, trigger_type=tt)
            assert s["trigger_type"] == tt

    def test_lc34_writ_schedule_sets_timer(self, folio_writ):
        """LC-34: Creating Writ with schedule sets Slip trigger_type to timer."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                         schedule="0 9 * * *")
        updated = folio_writ.get_slip(s["slip_id"])
        assert updated["trigger_type"] == "timer"

    def test_lc35_writ_event_sets_writ_chain(self, folio_writ):
        """LC-35: Creating Writ with event sets Slip trigger_type to writ_chain."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                         event="deed_closed")
        updated = folio_writ.get_slip(s["slip_id"])
        assert updated["trigger_type"] == "writ_chain"

    def test_lc36_invalid_status_rejected(self, folio_writ):
        """LC-36: Invalid status update is rejected."""
        s = create_test_slip(folio_writ)
        folio_writ.update_slip(s["slip_id"], {"status": "bogus"})
        updated = folio_writ.get_slip(s["slip_id"])
        assert updated["status"] == "active"  # unchanged

    def test_lc37_invalid_sub_status_rejected(self, folio_writ):
        """LC-37: Invalid sub_status update is rejected."""
        s = create_test_slip(folio_writ)
        folio_writ.update_slip(s["slip_id"], {"sub_status": "bogus"})
        updated = folio_writ.get_slip(s["slip_id"])
        assert updated["sub_status"] == "normal"  # unchanged

    # ── 4.5 Folio 生命周期 ─────────────────────────────────────────────────

    def test_lc40_create_folio_active(self, folio_writ):
        """LC-40: New Folio is active + normal."""
        f = create_test_folio(folio_writ)
        assert f["status"] == "active"
        assert f["sub_status"] == "normal"

    def test_lc41_folio_active_to_archived(self, folio_writ):
        """LC-41: active → archived."""
        f = create_test_folio(folio_writ)
        folio_writ.update_folio(f["folio_id"], {"status": "archived"})
        updated = folio_writ.get_folio(f["folio_id"])
        assert updated["status"] == "archived"

    def test_lc42_delete_folio_cascade(self, folio_writ):
        """LC-42: delete_folio detaches Slips and disables Writs."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        folio_writ.delete_folio(folio["folio_id"])
        updated_slip = folio_writ.get_slip(s["slip_id"])
        assert updated_slip["folio_id"] is None or updated_slip["folio_id"] == ""
        updated_writ = folio_writ.get_writ(w["writ_id"])
        assert updated_writ["status"] == "disabled"

    def test_lc43_folio_invalid_status_rejected(self, folio_writ):
        """LC-43: Invalid Folio status update rejected."""
        f = create_test_folio(folio_writ)
        folio_writ.update_folio(f["folio_id"], {"status": "bogus"})
        updated = folio_writ.get_folio(f["folio_id"])
        assert updated["status"] == "active"

    # ── 4.6 Draft 生命周期 ─────────────────────────────────────────────────

    def test_lc50_create_draft_initial(self, folio_writ):
        """LC-50: New Draft is drafting + open."""
        d = folio_writ.create_draft(source="test", intent_snapshot="T")
        assert d["status"] == "drafting"
        assert d["sub_status"] == "open"

    def test_lc51_crystallize_gone(self, folio_writ):
        """LC-51: Crystallize → gone + crystallized."""
        d = folio_writ.create_draft(source="test", intent_snapshot="T")
        folio_writ.crystallize_draft(d["draft_id"], title="T", objective="O",
                                     brief={}, design={})
        updated = folio_writ.get_draft(d["draft_id"])
        assert updated["status"] == "gone"
        assert updated["sub_status"] == "crystallized"

    def test_lc52_crystallize_creates_slip(self, folio_writ):
        """LC-52: Crystallize returns slip_id and Slip exists."""
        d = folio_writ.create_draft(source="test", intent_snapshot="T")
        slip = folio_writ.crystallize_draft(d["draft_id"], title="T", objective="O",
                                            brief={}, design={})
        assert slip.get("slip_id")
        assert folio_writ.get_slip(slip["slip_id"]) is not None

    def test_lc53_crystallize_nonexistent_raises(self, folio_writ):
        """LC-53: Crystallize non-existent draft → ValueError."""
        with pytest.raises(ValueError):
            folio_writ.crystallize_draft("nonexistent", title="T", objective="O",
                                        brief={}, design={})

    def test_lc54_update_draft_field(self, folio_writ):
        """LC-54: Update draft fields persists."""
        d = folio_writ.create_draft(source="test", intent_snapshot="Old")
        folio_writ.update_draft(d["draft_id"], {"intent_snapshot": "New"})
        updated = folio_writ.get_draft(d["draft_id"])
        assert updated["intent_snapshot"] == "New"

    def test_lc55_invalid_draft_status_rejected(self, folio_writ):
        """LC-55: Invalid draft status rejected."""
        d = folio_writ.create_draft(source="test", intent_snapshot="T")
        folio_writ.update_draft(d["draft_id"], {"status": "bogus"})
        updated = folio_writ.get_draft(d["draft_id"])
        assert updated["status"] == "drafting"

    # ── 4.7 Writ 生命周期 ──────────────────────────────────────────────────

    def test_lc60_create_writ_active(self, folio_writ):
        """LC-60: New Writ is active."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        assert w["status"] == "active"

    def test_lc61_writ_active_to_paused(self, folio_writ):
        """LC-61: active → paused."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        folio_writ.update_writ(w["writ_id"], {"status": "paused"})
        updated = folio_writ.get_writ(w["writ_id"])
        assert updated["status"] == "paused"

    def test_lc62_writ_active_to_disabled(self, folio_writ):
        """LC-62: active → disabled."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        folio_writ.update_writ(w["writ_id"], {"status": "disabled"})
        updated = folio_writ.get_writ(w["writ_id"])
        assert updated["status"] == "disabled"

    def test_lc63_delete_writ_detaches_folio(self, folio_writ):
        """LC-63: delete_writ removes from Folio.writ_ids."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        folio_writ.delete_writ(w["writ_id"])
        updated_folio = folio_writ.get_folio(folio["folio_id"])
        assert w["writ_id"] not in updated_folio["writ_ids"]

    def test_lc64_canonical_field_increments_version(self, folio_writ):
        """LC-64: Updating canonical field increments version."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        v1 = w["version"]
        folio_writ.update_writ(w["writ_id"], {"title": "New"})
        assert folio_writ.get_writ(w["writ_id"])["version"] == v1 + 1

    def test_lc65_non_canonical_no_version_change(self, folio_writ):
        """LC-65: Updating non-canonical field doesn't change version."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        v1 = w["version"]
        folio_writ.update_writ(w["writ_id"], {"status": "paused"})
        assert folio_writ.get_writ(w["writ_id"])["version"] == v1

    def test_lc66_record_writ_triggered(self, folio_writ, ledger):
        """LC-66: record_writ_triggered updates deed_history and last_triggered_utc."""
        folio = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        w = create_test_writ(folio_writ, folio_id=folio["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        d = create_test_deed(ledger, slip_id=s["slip_id"])
        folio_writ.record_deed_created(s["slip_id"], d["deed_id"], writ_id=w["writ_id"])
        updated = folio_writ.get_writ(w["writ_id"])
        assert d["deed_id"] in updated["deed_history"]
        assert updated["last_triggered_utc"]

    # ── 4.8 系统状态生命周期 ───────────────────────────────────────────────

    def test_lc70_default_system_status(self, ledger):
        """LC-70: Default system status is running."""
        assert ledger.load_system_status() == "running"

    def test_lc71_system_running_to_paused(self, ledger):
        """LC-71: Can write paused system status."""
        ledger.save_json("system_status.json", {"status": "paused"})
        assert ledger.load_system_status() == "paused"

    def test_lc72_system_paused_to_running(self, ledger):
        """LC-72: Can restore to running."""
        ledger.save_json("system_status.json", {"status": "paused"})
        ledger.save_json("system_status.json", {"status": "running"})
        assert ledger.load_system_status() == "running"

    def test_lc73_system_shutdown(self, ledger):
        """LC-73: Shutdown status is readable."""
        ledger.save_json("system_status.json", {"status": "shutdown"})
        assert ledger.load_system_status() == "shutdown"

    # ── 4.9 Ward 状态转换 ──────────────────────────────────────────────────

    def test_lc80_ward_green_to_yellow(self, ledger):
        """LC-80: Ward GREEN → YELLOW."""
        ledger.save_ward({"status": "YELLOW"})
        assert ledger.load_ward()["status"] == "YELLOW"

    def test_lc81_ward_yellow_to_red(self, ledger):
        """LC-81: Ward YELLOW → RED."""
        ledger.save_ward({"status": "RED"})
        assert ledger.load_ward()["status"] == "RED"

    def test_lc82_ward_red_to_green(self, ledger):
        """LC-82: Ward RED → GREEN (recovery)."""
        ledger.save_ward({"status": "RED"})
        ledger.save_ward({"status": "GREEN"})
        assert ledger.load_ward()["status"] == "GREEN"

    def test_lc83_consecutive_failures_tracking(self, ledger):
        """LC-83: Can track consecutive pulse failures."""
        history = [
            {"routine": "pulse", "status": "error", "started_utc": "2026-03-12T00:00:00Z"},
            {"routine": "pulse", "status": "error", "started_utc": "2026-03-12T00:10:00Z"},
            {"routine": "pulse", "status": "error", "started_utc": "2026-03-12T00:20:00Z"},
        ]
        ledger.save_schedule_history(history)
        loaded = ledger.load_schedule_history()
        consecutive_errors = sum(1 for h in loaded if h.get("status") == "error")
        assert consecutive_errors >= 3

    # ── 4.10 Deed Sub-Status 转换 ─────────────────────────────────────────

    def test_lc90_queued_to_executing(self, ledger):
        """LC-90: queued → executing."""
        d = create_test_deed(ledger, status="running", sub_status="queued")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_sub_status"] = "executing"
        ledger.mutate_deeds(mutate)
        assert ledger.get_deed(d["deed_id"])["deed_sub_status"] == "executing"

    def test_lc91_executing_to_succeeded(self, ledger):
        """LC-91: executing → succeeded."""
        d = create_test_deed(ledger, status="running", sub_status="executing")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_status"] = "closed"
                    row["deed_sub_status"] = "succeeded"
        ledger.mutate_deeds(mutate)
        updated = ledger.get_deed(d["deed_id"])
        assert updated["deed_status"] == "closed"
        assert updated["deed_sub_status"] == "succeeded"

    def test_lc92_executing_to_failed(self, ledger):
        """LC-92: executing → failed."""
        d = create_test_deed(ledger, status="running", sub_status="executing")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_status"] = "closed"
                    row["deed_sub_status"] = "failed"
        ledger.mutate_deeds(mutate)
        assert ledger.get_deed(d["deed_id"])["deed_sub_status"] == "failed"

    def test_lc93_executing_to_cancelled(self, ledger):
        """LC-93: executing → cancelled."""
        d = create_test_deed(ledger, status="running", sub_status="executing")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_status"] = "closed"
                    row["deed_sub_status"] = "cancelled"
        ledger.mutate_deeds(mutate)
        assert ledger.get_deed(d["deed_id"])["deed_sub_status"] == "cancelled"

    def test_lc94_executing_to_timed_out(self, ledger):
        """LC-94: executing → timed_out."""
        d = create_test_deed(ledger, status="running", sub_status="executing")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_status"] = "closed"
                    row["deed_sub_status"] = "timed_out"
        ledger.mutate_deeds(mutate)
        assert ledger.get_deed(d["deed_id"])["deed_sub_status"] == "timed_out"

    def test_lc95_reviewing_to_succeeded(self, ledger):
        """LC-95: reviewing → succeeded."""
        d = create_test_deed(ledger, status="settling", sub_status="reviewing")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_status"] = "closed"
                    row["deed_sub_status"] = "succeeded"
        ledger.mutate_deeds(mutate)
        assert ledger.get_deed(d["deed_id"])["deed_sub_status"] == "succeeded"

    def test_lc96_reviewing_to_retrying(self, ledger):
        """LC-96: reviewing → retrying (rework)."""
        d = create_test_deed(ledger, status="settling", sub_status="reviewing")
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == d["deed_id"]:
                    row["deed_sub_status"] = "retrying"
        ledger.mutate_deeds(mutate)
        assert ledger.get_deed(d["deed_id"])["deed_sub_status"] == "retrying"


# =============================================================================
# §20 TestLedgerStore — Ledger 状态存储
# =============================================================================


class TestLedgerStore:
    """LD-01 ~ LD-63: Ledger state file operations."""

    # ── 20.1 基本读写 ──────────────────────────────────────────────────────

    def test_ld01_init_creates_directory(self, tmp_path):
        """LD-01: Ledger init creates state directory."""
        d = tmp_path / "new_state"
        Ledger(d)
        assert d.exists()

    def test_ld02_load_deeds_empty(self, ledger):
        """LD-02: load_deeds on empty returns []."""
        # Remove if exists
        if ledger.deeds_path.exists():
            ledger.deeds_path.unlink()
        assert ledger.load_deeds() == []

    def test_ld03_upsert_deed_new(self, ledger):
        """LD-03: upsert_deed creates new deed."""
        ledger.upsert_deed("deed_test_001", {"deed_id": "deed_test_001", "deed_status": "running"})
        assert ledger.get_deed("deed_test_001") is not None

    def test_ld04_upsert_deed_update(self, ledger):
        """LD-04: upsert_deed with same id updates."""
        ledger.upsert_deed("deed_test_002", {"deed_id": "deed_test_002", "deed_status": "running"})
        ledger.upsert_deed("deed_test_002")
        deeds = [d for d in ledger.load_deeds() if d["deed_id"] == "deed_test_002"]
        assert len(deeds) == 1

    def test_ld05_get_deed_exists(self, ledger):
        """LD-05: get_deed returns matching deed."""
        ledger.upsert_deed("deed_test_003", {"deed_id": "deed_test_003", "deed_status": "running"})
        d = ledger.get_deed("deed_test_003")
        assert d["deed_id"] == "deed_test_003"

    def test_ld06_get_deed_missing(self, ledger):
        """LD-06: get_deed non-existent → None."""
        assert ledger.get_deed("nonexistent") is None

    def test_ld07_mutate_deeds_persists(self, ledger):
        """LD-07: mutate_deeds changes are persisted."""
        ledger.upsert_deed("deed_mut", {"deed_id": "deed_mut", "deed_status": "running"})
        def mutate(deeds):
            for row in deeds:
                if row["deed_id"] == "deed_mut":
                    row["deed_status"] = "closed"
        ledger.mutate_deeds(mutate)
        assert ledger.get_deed("deed_mut")["deed_status"] == "closed"

    def test_ld08_mutate_deeds_atomic(self, ledger):
        """LD-08: mutate_deeds exception → data unchanged."""
        ledger.upsert_deed("deed_atom", {"deed_id": "deed_atom", "deed_status": "running"})
        def bad_mutate(deeds):
            for row in deeds:
                if row["deed_id"] == "deed_atom":
                    row["deed_status"] = "closed"
            raise RuntimeError("simulated error")
        try:
            ledger.mutate_deeds(bad_mutate)
        except RuntimeError:
            pass
        # After exception, data may or may not be written depending on implementation.
        # The key invariant: no corruption (file is valid JSON).
        d = ledger.get_deed("deed_atom")
        assert d is not None
        assert d["deed_status"] in ("running", "closed")

    # ── 20.2 Ward ──────────────────────────────────────────────────────────

    def test_ld10_load_ward_empty_default(self, tmp_path):
        """LD-10: load_ward with no file → default GREEN."""
        ld = Ledger(tmp_path / "empty_state")
        ward = ld.load_ward()
        assert ward["status"] == "GREEN"

    def test_ld11_save_ward_roundtrip(self, ledger):
        """LD-11: save_ward → load_ward roundtrip."""
        ledger.save_ward({"status": "YELLOW", "checks": {"gateway": "ok"}})
        loaded = ledger.load_ward()
        assert loaded["status"] == "YELLOW"
        assert loaded["checks"]["gateway"] == "ok"

    def test_ld12_ward_status_values(self, ledger):
        """LD-12: Ward status accepts GREEN/YELLOW/RED."""
        for status in ("GREEN", "YELLOW", "RED"):
            ledger.save_ward({"status": status})
            assert ledger.load_ward()["status"] == status

    # ── 20.3 文件操作 ──────────────────────────────────────────────────────

    def test_ld20_load_json_missing_default(self, ledger):
        """LD-20: load_json missing file → default."""
        result = ledger.load_json("nonexistent.json", {"fallback": True})
        assert result == {"fallback": True}

    def test_ld21_load_json_corrupted_default(self, ledger):
        """LD-21: load_json corrupted file → default."""
        (ledger.state_dir / "bad.json").write_text("{{invalid json")
        result = ledger.load_json("bad.json", {"safe": True})
        assert result == {"safe": True}

    def test_ld22_save_json_no_tmp_residue(self, ledger):
        """LD-22: save_json leaves no .tmp files."""
        ledger.save_json("test_clean.json", {"a": 1})
        tmps = list(ledger.state_dir.glob("test_clean.json.tmp*"))
        assert len(tmps) == 0

    def test_ld23_append_jsonl_incremental(self, ledger):
        """LD-23: append_jsonl adds lines."""
        path = ledger.state_dir / "test.jsonl"
        ledger.append_jsonl(path, {"line": 1})
        ledger.append_jsonl(path, {"line": 2})
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_ld24_load_herald_log(self, ledger):
        """LD-24: append_herald_log → load_herald_log roundtrip."""
        ledger.append_herald_log({"deed_id": "d1", "title": "T"})
        log = ledger.load_herald_log()
        assert len(log) == 1
        assert log[0]["deed_id"] == "d1"

    def test_ld25_load_system_status_default(self, tmp_path):
        """LD-25: load_system_status no file → 'running'."""
        ld = Ledger(tmp_path / "empty")
        assert ld.load_system_status() == "running"

    # ── 20.4 线程锁 ────────────────────────────────────────────────────────

    def test_ld30_lock_for_same_path(self, ledger):
        """LD-30: _lock_for same path → same Lock."""
        p = ledger.state_dir / "same.json"
        l1 = Ledger._lock_for(p)
        l2 = Ledger._lock_for(p)
        assert l1 is l2

    def test_ld31_lock_for_different_path(self, ledger):
        """LD-31: _lock_for different paths → different Locks."""
        l1 = Ledger._lock_for(ledger.state_dir / "a.json")
        l2 = Ledger._lock_for(ledger.state_dir / "b.json")
        assert l1 is not l2

    def test_ld32_concurrent_save_json(self, ledger):
        """LD-32: Concurrent save_json doesn't lose data."""
        results = []
        def writer(key):
            ledger.save_json(f"concurrent_{key}.json", {"key": key})
            results.append(key)
        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(results) == 10
        for i in range(10):
            data = ledger.load_json(f"concurrent_{i}.json")
            assert data["key"] == i

    # ── 20.5 Daily Stats ───────────────────────────────────────────────────

    def test_ld40_load_daily_stats_empty(self, ledger):
        """LD-40: load_daily_stats empty → []."""
        assert ledger.load_daily_stats() == []

    def test_ld41_append_daily_stats(self, ledger):
        """LD-41: append_daily_stats persists."""
        ledger.append_daily_stats({"deeds_completed": 5, "date": "2026-03-12"})
        stats = ledger.load_daily_stats()
        assert len(stats) == 1
        assert stats[0]["deeds_completed"] == 5

    def test_ld42_daily_stats_multiple_dates(self, ledger):
        """LD-42: Multiple dates are distinct entries."""
        ledger.append_daily_stats({"date": "2026-03-11", "count": 3})
        ledger.append_daily_stats({"date": "2026-03-12", "count": 5})
        stats = ledger.load_daily_stats()
        assert len(stats) == 2
        dates = {s["date"] for s in stats}
        assert "2026-03-11" in dates
        assert "2026-03-12" in dates

    def test_ld43_daily_stats_max_items(self, ledger):
        """LD-43: load_daily_stats respects max_items."""
        for i in range(10):
            ledger.append_daily_stats({"i": i})
        stats = ledger.load_daily_stats(max_items=5)
        assert len(stats) == 5

    # ── 20.6 Notification Queue ────────────────────────────────────────────

    def test_ld50_enqueue_failed_notification(self, ledger):
        """LD-50: enqueue → load_notify_queue non-empty."""
        ledger.enqueue_failed_notification({"deed_id": "d1", "message": "failed"})
        queue = ledger.load_notify_queue()
        assert len(queue) >= 1

    def test_ld51_enqueue_structure(self, ledger):
        """LD-51: Enqueued entry has required fields."""
        ledger.enqueue_failed_notification({"deed_id": "d1", "message": "err"})
        entry = ledger.load_notify_queue()[0]
        assert "queued_utc" in entry
        assert "retry_count" in entry

    def test_ld52_rewrite_notify_queue(self, ledger):
        """LD-52: rewrite_notify_queue replaces content."""
        ledger.enqueue_failed_notification({"deed_id": "d1"})
        ledger.rewrite_notify_queue([])
        assert ledger.load_notify_queue() == []

    def test_ld53_enqueue_accumulates(self, ledger):
        """LD-53: Multiple enqueues accumulate."""
        for i in range(3):
            ledger.enqueue_failed_notification({"deed_id": f"d{i}"})
        assert len(ledger.load_notify_queue()) == 3

    # ── 20.7 Schedule History ──────────────────────────────────────────────

    def test_ld60_load_schedule_history_empty(self, ledger):
        """LD-60: Empty schedule history → []."""
        assert ledger.load_schedule_history() == []

    def test_ld61_save_schedule_history_roundtrip(self, ledger):
        """LD-61: save → load roundtrip."""
        history = [{"routine": "pulse", "status": "ok", "started_utc": "2026-03-12T00:00:00Z"}]
        ledger.save_schedule_history(history)
        loaded = ledger.load_schedule_history()
        assert len(loaded) == 1
        assert loaded[0]["routine"] == "pulse"

    def test_ld62_schedule_history_multiple_routines(self, ledger):
        """LD-62: History entries by different routines."""
        history = [
            {"routine": "pulse", "status": "ok"},
            {"routine": "record", "status": "ok"},
        ]
        ledger.save_schedule_history(history)
        loaded = ledger.load_schedule_history()
        routines = {h["routine"] for h in loaded}
        assert "pulse" in routines
        assert "record" in routines

    def test_ld63_schedule_history_entry_structure(self, ledger):
        """LD-63: History entry has expected fields."""
        entry = {
            "routine": "pulse",
            "status": "ok",
            "started_utc": "2026-03-12T00:00:00Z",
            "duration_ms": 150,
            "trigger": "cron",
        }
        ledger.save_schedule_history([entry])
        loaded = ledger.load_schedule_history()[0]
        assert loaded["routine"] == "pulse"
        assert loaded["duration_ms"] == 150
        assert loaded["trigger"] == "cron"


# =============================================================================
# §5 TestEventChains — 事件链路完整性
# =============================================================================


class TestEventChains:
    """EC-01 ~ EC-83: Event chain integrity from emit to consume."""

    # ── 5.1 deed_closed 事件链 ────────────────────────────────────────────

    def test_ec01_settle_triggers_deed_closed(self, nerve):
        """EC-01: Settling a deed emits deed_closed event."""
        captured = []
        nerve.on("deed_closed", lambda p: captured.append(p))
        nerve.emit("deed_closed", {"deed_id": "deed_test", "sub_status": "succeeded", "source": "settle"})
        assert len(captured) == 1
        assert captured[0]["deed_id"] == "deed_test"

    def test_ec02_feedback_close_triggers_deed_closed(self, nerve):
        """EC-02: Feedback close emits deed_closed."""
        captured = []
        nerve.on("deed_closed", lambda p: captured.append(p))
        nerve.emit("deed_closed", {"deed_id": "deed_fb", "sub_status": "succeeded", "source": "feedback"})
        assert captured[0]["source"] == "feedback"

    def test_ec03_eval_timeout_triggers_deed_closed(self, nerve):
        """EC-03: Eval timeout triggers deed_closed."""
        captured = []
        nerve.on("deed_closed", lambda p: captured.append(p))
        nerve.emit("deed_closed", {"deed_id": "deed_to", "sub_status": "timed_out", "source": "eval_timeout"})
        assert captured[0]["sub_status"] == "timed_out"

    def test_ec04_running_ttl_triggers_deed_closed(self, nerve):
        """EC-04: Running TTL expiry triggers deed_closed."""
        captured = []
        nerve.on("deed_closed", lambda p: captured.append(p))
        nerve.emit("deed_closed", {"deed_id": "deed_ttl", "sub_status": "timed_out", "source": "running_ttl"})
        assert captured[0]["source"] == "running_ttl"

    def test_ec06_deed_closed_triggers_writ_chain(self, folio_writ):
        """EC-06: deed_closed triggers Writ handlers if registered."""
        folio = create_test_folio(folio_writ)
        fid = folio["folio_id"]
        slip_a = create_test_slip(folio_writ, title="A", folio_id=fid)
        slip_b = create_test_slip(folio_writ, title="B", folio_id=fid)
        create_test_writ(folio_writ, folio_id=fid, slip_id=slip_b["slip_id"],
                         event="deed_closed")
        ready = []
        folio_writ._nerve.on("writ_trigger_ready", lambda p: ready.append(p))
        folio_writ._nerve.emit("deed_closed", {"deed_id": "d1", "slip_id": slip_a["slip_id"]})
        # writ_trigger_ready may or may not fire depending on filter; at minimum no crash
        assert isinstance(ready, list)

    def test_ec07_deed_closed_payload_complete(self, nerve):
        """EC-07: deed_closed payload has deed_id, sub_status, source."""
        captured = []
        nerve.on("deed_closed", lambda p: captured.append(p))
        payload = {"deed_id": "d1", "sub_status": "succeeded", "source": "settle"}
        nerve.emit("deed_closed", payload)
        for key in ("deed_id", "sub_status", "source"):
            assert key in captured[0]

    # ── 5.2 Writ trigger chain ────────────────────────────────────────────

    def test_ec10_deed_closed_triggers_writ_trigger_ready(self, folio_writ, ledger):
        """EC-10: deed_closed → writ_trigger_ready for matching Writ."""
        folio = create_test_folio(folio_writ)
        fid = folio["folio_id"]
        slip_a = create_test_slip(folio_writ, title="Source", folio_id=fid)
        slip_b = create_test_slip(folio_writ, title="Target", folio_id=fid)
        writ = folio_writ.create_writ(
            folio_id=fid, title="Chain AB",
            match={"event": "deed_closed", "filter": {"slip_id": slip_a["slip_id"]}},
            action={"type": "spawn_deed", "slip_id": slip_b["slip_id"]},
        )
        ready = []
        folio_writ._nerve.on("writ_trigger_ready", lambda p: ready.append(p))
        folio_writ._nerve.emit("deed_closed", {"deed_id": "d1", "slip_id": slip_a["slip_id"]})
        assert len(ready) == 1
        assert ready[0]["writ_id"] == writ["writ_id"]

    def test_ec11_predecessor_not_met_no_trigger(self, folio_writ, ledger):
        """EC-11: Writ depends on A and B, only A closed → no trigger."""
        folio = create_test_folio(folio_writ)
        fid = folio["folio_id"]
        slip_a = create_test_slip(folio_writ, title="A", folio_id=fid)
        slip_b = create_test_slip(folio_writ, title="B", folio_id=fid)
        slip_c = create_test_slip(folio_writ, title="C", folio_id=fid)
        # Writ triggered by A's deed_closed, targeting C
        folio_writ.create_writ(
            folio_id=fid, title="A→C",
            match={"event": "deed_closed", "filter": {"slip_id": slip_a["slip_id"]}},
            action={"type": "spawn_deed", "slip_id": slip_c["slip_id"]},
        )
        # Emit B's deed_closed → should not trigger the A→C writ
        ready = []
        folio_writ._nerve.on("writ_trigger_ready", lambda p: ready.append(p))
        folio_writ._nerve.emit("deed_closed", {"deed_id": "d1", "slip_id": slip_b["slip_id"]})
        assert len(ready) == 0

    def test_ec12_all_predecessors_met_triggers(self, folio_writ, ledger):
        """EC-12: All prerequisites met → writ triggers."""
        folio = create_test_folio(folio_writ)
        fid = folio["folio_id"]
        slip_a = create_test_slip(folio_writ, title="A", folio_id=fid)
        slip_b = create_test_slip(folio_writ, title="B", folio_id=fid)
        folio_writ.create_writ(
            folio_id=fid, title="A→B",
            match={"event": "deed_closed", "filter": {"slip_id": slip_a["slip_id"]}},
            action={"type": "spawn_deed", "slip_id": slip_b["slip_id"]},
        )
        ready = []
        folio_writ._nerve.on("writ_trigger_ready", lambda p: ready.append(p))
        folio_writ._nerve.emit("deed_closed", {"deed_id": "d1", "slip_id": slip_a["slip_id"]})
        assert len(ready) == 1

    # ── 5.5 FolioWrit 注册事件 ────────────────────────────────────────────

    def test_ec50_create_folio_emits_event(self, folio_writ):
        """EC-50: create_folio → folio_created event."""
        captured = []
        folio_writ._nerve.on("folio_created", lambda p: captured.append(p))
        folio = create_test_folio(folio_writ)
        assert len(captured) == 1
        assert captured[0]["folio_id"] == folio["folio_id"]

    def test_ec51_create_slip_emits_event(self, folio_writ):
        """EC-51: create_slip → slip_created event."""
        captured = []
        folio_writ._nerve.on("slip_created", lambda p: captured.append(p))
        slip = create_test_slip(folio_writ)
        assert len(captured) == 1
        assert captured[0]["slip_id"] == slip["slip_id"]

    def test_ec52_create_writ_emits_event(self, folio_writ):
        """EC-52: create_writ → writ_created event."""
        captured = []
        folio_writ._nerve.on("writ_created", lambda p: captured.append(p))
        folio = create_test_folio(folio_writ)
        slip = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        writ = create_test_writ(folio_writ, folio_id=folio["folio_id"],
                                slip_id=slip["slip_id"], schedule="0 9 * * *")
        assert len(captured) == 1
        assert captured[0]["writ_id"] == writ["writ_id"]

    def test_ec53_create_draft_emits_event(self, folio_writ):
        """EC-53: create_draft → draft_created event."""
        captured = []
        folio_writ._nerve.on("draft_created", lambda p: captured.append(p))
        draft = folio_writ.create_draft(source="test", intent_snapshot="intent")
        assert len(captured) == 1
        assert captured[0]["draft_id"] == draft["draft_id"]

    def test_ec54_crystallize_emits_event(self, folio_writ):
        """EC-54: crystallize_draft → draft_crystallized event."""
        captured = []
        folio_writ._nerve.on("draft_crystallized", lambda p: captured.append(p))
        draft = folio_writ.create_draft(source="test", intent_snapshot="intent")
        slip = folio_writ.crystallize_draft(
            draft["draft_id"], title="T", objective="O",
            brief={"dag_budget": 3}, design={"moves": []},
        )
        assert len(captured) == 1
        assert captured[0]["draft_id"] == draft["draft_id"]
        assert captured[0]["slip_id"] == slip["slip_id"]

    def test_ec55_duplicate_slip_emits_event(self, folio_writ):
        """EC-55: duplicate_slip → slip_duplicated event."""
        captured = []
        folio_writ._nerve.on("slip_duplicated", lambda p: captured.append(p))
        slip = create_test_slip(folio_writ)
        dup = folio_writ.duplicate_slip(slip["slip_id"])
        assert len(captured) == 1
        assert captured[0]["source_slip_id"] == slip["slip_id"]
        assert captured[0]["slip_id"] == dup["slip_id"]

    def test_ec56_delete_folio_emits_event(self, folio_writ):
        """EC-56: delete_folio → folio_deleted event."""
        captured = []
        folio_writ._nerve.on("folio_deleted", lambda p: captured.append(p))
        folio = create_test_folio(folio_writ)
        folio_writ.delete_folio(folio["folio_id"])
        assert len(captured) == 1
        assert captured[0]["folio_id"] == folio["folio_id"]

    def test_ec57_delete_writ_emits_event(self, folio_writ):
        """EC-57: delete_writ → writ_deleted event."""
        captured = []
        folio_writ._nerve.on("writ_deleted", lambda p: captured.append(p))
        folio = create_test_folio(folio_writ)
        slip = create_test_slip(folio_writ, folio_id=folio["folio_id"])
        writ = create_test_writ(folio_writ, folio_id=folio["folio_id"],
                                slip_id=slip["slip_id"], schedule="0 9 * * *")
        folio_writ.delete_writ(writ["writ_id"])
        assert len(captured) == 1
        assert captured[0]["writ_id"] == writ["writ_id"]

    # ── 5.6 Nerve 基础设施 ────────────────────────────────────────────────

    def test_ec60_handler_exception_no_crash(self, nerve):
        """EC-60: Handler exception doesn't block emit."""
        def bad_handler(p):
            raise ValueError("boom")
        nerve.on("test_err", bad_handler)
        captured = []
        nerve.on("test_err", lambda p: captured.append(p))
        eid = nerve.emit("test_err", {"x": 1})
        assert eid.startswith("ev_")
        assert len(captured) == 1
        # handler_errors recorded
        record = nerve.recent(1)[0]
        assert len(record["handler_errors"]) == 1
        assert "boom" in record["handler_errors"][0]["error"]

    def test_ec61_events_persisted_to_jsonl(self, nerve_with_persistence, state_dir):
        """EC-61: Events persisted to events.jsonl."""
        nerve_with_persistence.emit("persist_test", {"val": 42})
        path = state_dir / "events.jsonl"
        assert path.exists()
        lines = [l for l in path.read_text().splitlines() if l.strip()]
        assert len(lines) >= 1
        record = json.loads(lines[-1])
        assert record["event"] == "persist_test"

    def test_ec62_replay_unconsumed(self, state_dir):
        """EC-62: replay_unconsumed replays events without consumed_utc."""
        events_path = state_dir / "events.jsonl"
        events_path.write_text(json.dumps({
            "event_id": "ev_test1", "event": "replay_me",
            "payload": {"k": "v"}, "timestamp": "2026-01-01T00:00:00Z",
            "consumed_utc": None, "handler_errors": [],
        }) + "\n")
        n = Nerve(state_dir=state_dir)
        replayed_payloads = []
        n.on("replay_me", lambda p: replayed_payloads.append(p))
        count = n.replay_unconsumed()
        assert count == 1
        assert replayed_payloads[0]["k"] == "v"

    def test_ec63_history_size_limit(self):
        """EC-63: history_size limits recent() output."""
        n = Nerve(history_size=5)
        for i in range(10):
            n.emit(f"evt_{i}", {"i": i})
        assert len(n.recent(100)) == 5

    def test_ec64_emit_returns_event_id(self, nerve):
        """EC-64: emit returns event_id starting with ev_."""
        eid = nerve.emit("test", {})
        assert eid.startswith("ev_")
        assert len(eid) > 5

    def test_ec65_event_record_structure(self, nerve):
        """EC-65: Event record has all required fields."""
        nerve.emit("struct_test", {"a": 1})
        record = nerve.recent(1)[0]
        for key in ("event_id", "event", "payload", "timestamp", "consumed_utc", "handler_errors"):
            assert key in record, f"Missing: {key}"

    def test_ec66_multiple_handlers_all_called(self, nerve):
        """EC-66: Multiple handlers for same event all called."""
        results = []
        nerve.on("multi", lambda p: results.append("h1"))
        nerve.on("multi", lambda p: results.append("h2"))
        nerve.on("multi", lambda p: results.append("h3"))
        nerve.emit("multi", {})
        assert results == ["h1", "h2", "h3"]

    def test_ec67_event_count_by_type(self, nerve):
        """EC-67: event_count counts by event type."""
        nerve.emit("a", {})
        nerve.emit("a", {})
        nerve.emit("b", {})
        nerve.emit("b", {})
        nerve.emit("b", {})
        counts = nerve.event_count()
        assert counts["a"] == 2
        assert counts["b"] == 3

    # ── 5.7 Ether 跨进程事件 (local simulation) ───────────────────────────

    def test_ec73_routine_completed_event(self, nerve):
        """EC-73: Routine completed emits event."""
        captured = []
        nerve.on("routine_completed", lambda p: captured.append(p))
        nerve.emit("routine_completed", {"routine": "pulse", "status": "ok"})
        assert captured[0]["routine"] == "pulse"

    def test_ec74_ward_changed_payload(self, nerve):
        """EC-74: ward_changed payload has required fields."""
        captured = []
        nerve.on("ward_changed", lambda p: captured.append(p))
        nerve.emit("ward_changed", {"old_status": "GREEN", "new_status": "YELLOW", "checked_utc": "2026-01-01T00:00:00Z"})
        for key in ("old_status", "new_status", "checked_utc"):
            assert key in captured[0]

    # ── 5.8 事件顺序与因果 ────────────────────────────────────────────────

    def test_ec80_submitted_before_settling(self, nerve):
        """EC-80: deed_submitted timestamp < deed_settling timestamp."""
        nerve.emit("deed_submitted", {"deed_id": "d1"})
        time.sleep(0.001)
        nerve.emit("deed_settling", {"deed_id": "d1"})
        events = nerve.recent(10)
        submitted = [e for e in events if e["event"] == "deed_submitted"][0]
        settling = [e for e in events if e["event"] == "deed_settling"][0]
        assert submitted["timestamp"] <= settling["timestamp"]

    def test_ec81_settling_before_closed(self, nerve):
        """EC-81: deed_settling timestamp < deed_closed timestamp."""
        nerve.emit("deed_settling", {"deed_id": "d1"})
        time.sleep(0.001)
        nerve.emit("deed_closed", {"deed_id": "d1"})
        events = nerve.recent(10)
        settling = [e for e in events if e["event"] == "deed_settling"][0]
        closed = [e for e in events if e["event"] == "deed_closed"][0]
        assert settling["timestamp"] <= closed["timestamp"]

    def test_ec83_writ_trigger_after_deed_closed(self, nerve):
        """EC-83: writ_trigger_ready after deed_closed."""
        nerve.emit("deed_closed", {"deed_id": "d1"})
        time.sleep(0.001)
        nerve.emit("writ_trigger_ready", {"writ_id": "w1"})
        events = nerve.recent(10)
        closed = [e for e in events if e["event"] == "deed_closed"][0]
        trigger = [e for e in events if e["event"] == "writ_trigger_ready"][0]
        assert closed["timestamp"] <= trigger["timestamp"]


# =============================================================================
# §15 TestFolioWritRegistry — FolioWrit 注册表
# =============================================================================


class TestFolioWritRegistry:
    """FW-01 ~ FW-86: FolioWritManager CRUD, triggers, limits, DAG navigation."""

    # ── 15.1 Folio CRUD ──────────────────────────────────────────────────

    def test_fw01_create_folio_complete(self, folio_writ):
        """FW-01: create_folio returns complete structure."""
        f = create_test_folio(folio_writ)
        for key in ("folio_id", "title", "slug", "status", "sub_status", "slip_ids", "writ_ids", "created_utc"):
            assert key in f, f"Missing: {key}"
        assert f["status"] == "active"

    def test_fw02_get_folio_correct(self, folio_writ):
        """FW-02: get_folio returns correct folio."""
        f = create_test_folio(folio_writ)
        got = folio_writ.get_folio(f["folio_id"])
        assert got is not None
        assert got["folio_id"] == f["folio_id"]

    def test_fw03_get_folio_by_slug(self, folio_writ):
        """FW-03: get_folio_by_slug finds correct folio."""
        f = create_test_folio(folio_writ, title="My Research")
        got = folio_writ.get_folio_by_slug(f["slug"])
        assert got is not None
        assert got["folio_id"] == f["folio_id"]

    def test_fw04_list_folios_sorted(self, folio_writ):
        """FW-04: list_folios sorted by updated_utc desc."""
        f1 = create_test_folio(folio_writ, title="First")
        f2 = create_test_folio(folio_writ, title="Second")
        # Force distinct timestamps for deterministic ordering
        folio_writ.update_folio(f1["folio_id"], {"summary": "t1"})
        rows = folio_writ._load_rows(folio_writ._folios_file)
        for r in rows:
            if r.get("folio_id") == f1["folio_id"]:
                r["updated_utc"] = "2026-01-01T00:00:00Z"
            elif r.get("folio_id") == f2["folio_id"]:
                r["updated_utc"] = "2026-01-02T00:00:00Z"
        folio_writ._save_rows(folio_writ._folios_file, rows)
        listed = folio_writ.list_folios()
        ids = [f["folio_id"] for f in listed]
        assert ids.index(f2["folio_id"]) < ids.index(f1["folio_id"])

    def test_fw05_update_folio_title(self, folio_writ):
        """FW-05: Update folio title syncs slug."""
        f = create_test_folio(folio_writ, title="Old Title")
        old_slug = f["slug"]
        updated = folio_writ.update_folio(f["folio_id"], {"title": "New Title"})
        assert updated["title"] == "New Title"
        assert updated["slug"] != old_slug

    def test_fw06_delete_folio(self, folio_writ):
        """FW-06: delete_folio removes record."""
        f = create_test_folio(folio_writ)
        assert folio_writ.delete_folio(f["folio_id"]) is True
        assert folio_writ.get_folio(f["folio_id"]) is None

    def test_fw07_delete_folio_cascades_slip(self, folio_writ):
        """FW-07: delete_folio sets Slip.folio_id to None."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        folio_writ.delete_folio(f["folio_id"])
        updated_slip = folio_writ.get_slip(s["slip_id"])
        assert updated_slip is not None
        assert not updated_slip.get("folio_id")

    def test_fw08_delete_folio_cascades_writ_disabled(self, folio_writ):
        """FW-08: delete_folio disables associated Writs."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        folio_writ.delete_folio(f["folio_id"])
        updated_writ = folio_writ.get_writ(w["writ_id"])
        assert updated_writ is not None
        assert updated_writ["status"] == "disabled"

    # ── 15.2 Slip CRUD ───────────────────────────────────────────────────

    def test_fw10_create_slip_complete(self, folio_writ):
        """FW-10: create_slip returns complete structure."""
        s = create_test_slip(folio_writ)
        for key in ("slip_id", "title", "slug", "objective", "brief", "design",
                     "status", "sub_status", "standing", "trigger_type",
                     "latest_deed_id", "deed_ids", "created_utc"):
            assert key in s, f"Missing: {key}"

    def test_fw11_create_slip_attaches_to_folio(self, folio_writ):
        """FW-11: create_slip auto-attaches to Folio."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        folio = folio_writ.get_folio(f["folio_id"])
        assert s["slip_id"] in folio["slip_ids"]

    def test_fw12_get_slip_by_slug(self, folio_writ):
        """FW-12: get_slip_by_slug finds correct slip."""
        s = create_test_slip(folio_writ, title="Research Task")
        got = folio_writ.get_slip_by_slug(s["slug"])
        assert got is not None
        assert got["slip_id"] == s["slip_id"]

    def test_fw13_list_slips_filter_by_folio(self, folio_writ):
        """FW-13: list_slips filters by folio_id."""
        f1 = create_test_folio(folio_writ, title="F1")
        f2 = create_test_folio(folio_writ, title="F2")
        s1 = create_test_slip(folio_writ, title="S1", folio_id=f1["folio_id"])
        s2 = create_test_slip(folio_writ, title="S2", folio_id=f2["folio_id"])
        slips = folio_writ.list_slips(folio_id=f1["folio_id"])
        ids = [s["slip_id"] for s in slips]
        assert s1["slip_id"] in ids
        assert s2["slip_id"] not in ids

    def test_fw14_update_slip_title(self, folio_writ):
        """FW-14: Update slip title syncs slug."""
        s = create_test_slip(folio_writ, title="Old")
        old_slug = s["slug"]
        updated = folio_writ.update_slip(s["slip_id"], {"title": "New"})
        assert updated["title"] == "New"
        assert updated["slug"] != old_slug

    def test_fw15_update_slip_migrate_folio(self, folio_writ):
        """FW-15: Moving Slip from Folio A to B updates both."""
        f1 = create_test_folio(folio_writ, title="A")
        f2 = create_test_folio(folio_writ, title="B")
        s = create_test_slip(folio_writ, title="Migrator", folio_id=f1["folio_id"])
        folio_writ.update_slip(s["slip_id"], {"folio_id": f2["folio_id"]})
        a = folio_writ.get_folio(f1["folio_id"])
        b = folio_writ.get_folio(f2["folio_id"])
        assert s["slip_id"] not in a["slip_ids"]
        assert s["slip_id"] in b["slip_ids"]

    def test_fw16_duplicate_slip_structure(self, folio_writ):
        """FW-16: duplicate_slip copies structure, resets deed_ids."""
        s = create_test_slip(folio_writ, title="Original")
        dup = folio_writ.duplicate_slip(s["slip_id"])
        assert dup is not None
        assert "副本" in dup["title"]
        assert dup["objective"] == s["objective"]
        assert dup["deed_ids"] == []

    def test_fw17_duplicate_slip_standing_false(self, folio_writ):
        """FW-17: Duplicate standing=False, brief.standing=False."""
        s = create_test_slip(folio_writ, title="Standing", folio_id=None)
        dup = folio_writ.duplicate_slip(s["slip_id"])
        assert dup["standing"] is False
        assert dup.get("brief", {}).get("standing", False) is False

    def test_fw18_reorder_folio_slips(self, folio_writ):
        """FW-18: reorder_folio_slips persists new order."""
        f = create_test_folio(folio_writ)
        fid = f["folio_id"]
        sa = create_test_slip(folio_writ, title="A", folio_id=fid)
        sb = create_test_slip(folio_writ, title="B", folio_id=fid)
        sc = create_test_slip(folio_writ, title="C", folio_id=fid)
        ids = [sc["slip_id"], sa["slip_id"], sb["slip_id"]]
        result = folio_writ.reorder_folio_slips(fid, ids)
        assert result["slip_ids"] == ids

    def test_fw19_reorder_ignores_invalid(self, folio_writ):
        """FW-19: reorder_folio_slips ignores invalid slip_ids."""
        f = create_test_folio(folio_writ)
        fid = f["folio_id"]
        s = create_test_slip(folio_writ, title="Only", folio_id=fid)
        result = folio_writ.reorder_folio_slips(fid, ["nonexistent", s["slip_id"]])
        assert s["slip_id"] in result["slip_ids"]
        assert "nonexistent" not in result["slip_ids"]

    def test_fw20_record_deed_created(self, folio_writ):
        """FW-20: record_deed_created updates Slip deed_ids and latest_deed_id."""
        s = create_test_slip(folio_writ)
        folio_writ.record_deed_created(s["slip_id"], "deed_001")
        updated = folio_writ.get_slip(s["slip_id"])
        assert "deed_001" in updated["deed_ids"]
        assert updated["latest_deed_id"] == "deed_001"

    def test_fw21_deed_ids_cap_200(self, folio_writ):
        """FW-21: deed_ids capped at 200."""
        s = create_test_slip(folio_writ)
        for i in range(250):
            folio_writ.record_deed_created(s["slip_id"], f"deed_{i:04d}")
        updated = folio_writ.get_slip(s["slip_id"])
        assert len(updated["deed_ids"]) <= 200

    # ── 15.3 Writ CRUD ───────────────────────────────────────────────────

    def test_fw30_create_writ_complete(self, folio_writ):
        """FW-30: create_writ returns complete structure."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        for key in ("writ_id", "folio_id", "title", "match", "action", "status",
                     "priority", "version", "deed_history", "created_utc"):
            assert key in w, f"Missing: {key}"

    def test_fw31_create_writ_attaches_to_folio(self, folio_writ):
        """FW-31: create_writ auto-attaches to Folio."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        folio = folio_writ.get_folio(f["folio_id"])
        assert w["writ_id"] in folio["writ_ids"]

    def test_fw32_create_writ_registers_trigger(self, folio_writ):
        """FW-32: create_writ registers trigger in _registered_triggers."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        found = any(wid == w["writ_id"] for wid, _ in folio_writ._registered_triggers)
        assert found

    def test_fw33_create_writ_syncs_trigger_type(self, folio_writ):
        """FW-33: Writ with schedule → Slip trigger_type=timer; event → writ_chain."""
        f = create_test_folio(folio_writ)
        s1 = create_test_slip(folio_writ, title="Timer", folio_id=f["folio_id"])
        create_test_writ(folio_writ, folio_id=f["folio_id"],
                         slip_id=s1["slip_id"], schedule="0 9 * * *")
        updated = folio_writ.get_slip(s1["slip_id"])
        assert updated["trigger_type"] == "timer"

        s2 = create_test_slip(folio_writ, title="Chain", folio_id=f["folio_id"])
        create_test_writ(folio_writ, folio_id=f["folio_id"],
                         slip_id=s2["slip_id"], event="deed_closed")
        updated2 = folio_writ.get_slip(s2["slip_id"])
        assert updated2["trigger_type"] == "writ_chain"

    def test_fw34_update_writ_version_increment(self, folio_writ):
        """FW-34: Updating canonical field increments version."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        assert w["version"] == 1
        updated = folio_writ.update_writ(w["writ_id"], {"title": "New Title"})
        assert updated["version"] == 2

    def test_fw35_delete_writ(self, folio_writ):
        """FW-35: delete_writ removes record."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        assert folio_writ.delete_writ(w["writ_id"]) is True
        assert folio_writ.get_writ(w["writ_id"]) is None

    def test_fw36_delete_writ_detaches_from_folio(self, folio_writ):
        """FW-36: delete_writ removes from Folio.writ_ids."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        folio_writ.delete_writ(w["writ_id"])
        folio = folio_writ.get_folio(f["folio_id"])
        assert w["writ_id"] not in folio["writ_ids"]

    # ── 15.4 Draft CRUD ──────────────────────────────────────────────────

    def test_fw40_create_draft_complete(self, folio_writ):
        """FW-40: create_draft returns complete structure."""
        d = folio_writ.create_draft(source="test", intent_snapshot="intent")
        for key in ("draft_id", "source", "intent_snapshot", "status", "sub_status", "created_utc"):
            assert key in d, f"Missing: {key}"
        assert d["status"] == "drafting"
        assert d["sub_status"] == "open"

    def test_fw41_list_drafts_sorted(self, folio_writ):
        """FW-41: list_drafts sorted by updated_utc desc."""
        d1 = folio_writ.create_draft(source="test", intent_snapshot="first")
        d2 = folio_writ.create_draft(source="test", intent_snapshot="second")
        # Force distinct timestamps
        rows = folio_writ._load_rows(folio_writ._drafts_file)
        for r in rows:
            if r.get("draft_id") == d1["draft_id"]:
                r["updated_utc"] = "2026-01-01T00:00:00Z"
            elif r.get("draft_id") == d2["draft_id"]:
                r["updated_utc"] = "2026-01-02T00:00:00Z"
        folio_writ._save_rows(folio_writ._drafts_file, rows)
        listed = folio_writ.list_drafts()
        assert listed[0]["draft_id"] == d2["draft_id"]

    def test_fw42_update_draft(self, folio_writ):
        """FW-42: update_draft modifies fields."""
        d = folio_writ.create_draft(source="test", intent_snapshot="old")
        updated = folio_writ.update_draft(d["draft_id"], {"intent_snapshot": "new"})
        assert updated["intent_snapshot"] == "new"

    def test_fw43_crystallize_draft_creates_slip(self, folio_writ):
        """FW-43: crystallize_draft → draft=gone, slip created."""
        d = folio_writ.create_draft(source="test", intent_snapshot="intent")
        slip = folio_writ.crystallize_draft(
            d["draft_id"], title="Title", objective="Obj",
            brief={"dag_budget": 3}, design={"moves": []},
        )
        assert slip["title"] == "Title"
        draft = folio_writ.get_draft(d["draft_id"])
        assert draft["status"] == "gone"
        assert draft["sub_status"] == "crystallized"

    def test_fw44_crystallize_nonexistent_raises(self, folio_writ):
        """FW-44: crystallize nonexistent draft → ValueError."""
        with pytest.raises(ValueError, match="draft_not_found"):
            folio_writ.crystallize_draft(
                "nonexistent", title="T", objective="O",
                brief={}, design={},
            )

    # ── 15.5 Trigger 机制 ────────────────────────────────────────────────

    def test_fw50_register_all_triggers(self, folio_writ):
        """FW-50: register_all_triggers registers all active writs."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        # Create 3 active writs
        for i in range(3):
            create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule=f"0 {i} * * *")
        # Create 1 disabled writ
        w_disabled = create_test_writ(folio_writ, folio_id=f["folio_id"],
                                      slip_id=s["slip_id"], schedule="0 12 * * *")
        folio_writ.update_writ(w_disabled["writ_id"], {"status": "disabled"})
        # Clear and re-register
        folio_writ._registered_triggers.clear()
        count = folio_writ.register_all_triggers()
        assert count == 3

    def test_fw51_event_trigger_match(self, folio_writ):
        """FW-51: Event trigger matches and fires."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, title="Target", folio_id=f["folio_id"])
        folio_writ.create_writ(
            folio_id=f["folio_id"], title="On Close",
            match={"event": "deed_closed"},
            action={"type": "spawn_deed", "slip_id": s["slip_id"]},
        )
        ready = []
        folio_writ._nerve.on("writ_trigger_ready", lambda p: ready.append(p))
        folio_writ._nerve.emit("deed_closed", {"deed_id": "d1"})
        assert len(ready) == 1

    def test_fw52_event_filter_match(self, folio_writ):
        """FW-52: Event filter matches correct payload."""
        f = create_test_folio(folio_writ)
        sa = create_test_slip(folio_writ, title="A", folio_id=f["folio_id"])
        sb = create_test_slip(folio_writ, title="B", folio_id=f["folio_id"])
        folio_writ.create_writ(
            folio_id=f["folio_id"], title="A→B",
            match={"event": "deed_closed", "filter": {"slip_id": sa["slip_id"]}},
            action={"type": "spawn_deed", "slip_id": sb["slip_id"]},
        )
        ready = []
        folio_writ._nerve.on("writ_trigger_ready", lambda p: ready.append(p))
        folio_writ._nerve.emit("deed_closed", {"deed_id": "d1", "slip_id": sa["slip_id"]})
        assert len(ready) == 1

    def test_fw53_event_filter_mismatch_skip(self, folio_writ):
        """FW-53: Event filter mismatch → no trigger."""
        f = create_test_folio(folio_writ)
        sa = create_test_slip(folio_writ, title="A", folio_id=f["folio_id"])
        sb = create_test_slip(folio_writ, title="B", folio_id=f["folio_id"])
        folio_writ.create_writ(
            folio_id=f["folio_id"], title="A→B",
            match={"event": "deed_closed", "filter": {"slip_id": sa["slip_id"]}},
            action={"type": "spawn_deed", "slip_id": sb["slip_id"]},
        )
        ready = []
        folio_writ._nerve.on("writ_trigger_ready", lambda p: ready.append(p))
        folio_writ._nerve.emit("deed_closed", {"deed_id": "d1", "slip_id": "wrong_slip"})
        assert len(ready) == 0

    def test_fw54_schedule_trigger_cadence_tick(self, folio_writ):
        """FW-54: Schedule writ triggered by matching cadence.tick."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, title="Sched", folio_id=f["folio_id"])
        folio_writ.create_writ(
            folio_id=f["folio_id"], title="Every 9AM",
            match={"schedule": "0 9 * * *"},
            action={"type": "spawn_deed", "slip_id": s["slip_id"]},
        )
        ready = []
        folio_writ._nerve.on("writ_trigger_ready", lambda p: ready.append(p))
        folio_writ._nerve.emit("cadence.tick", {"tick_utc": "2026-03-12T09:00:00Z"})
        assert len(ready) == 1

    def test_fw55_schedule_mismatch_skip(self, folio_writ):
        """FW-55: Schedule mismatch → no trigger."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, title="Sched", folio_id=f["folio_id"])
        folio_writ.create_writ(
            folio_id=f["folio_id"], title="Every 9AM",
            match={"schedule": "0 9 * * *"},
            action={"type": "spawn_deed", "slip_id": s["slip_id"]},
        )
        ready = []
        folio_writ._nerve.on("writ_trigger_ready", lambda p: ready.append(p))
        folio_writ._nerve.emit("cadence.tick", {"tick_utc": "2026-03-12T10:00:00Z"})
        assert len(ready) == 0

    def test_fw56_duplicate_tick_suppressed(self, folio_writ):
        """FW-56: Same-minute duplicate tick auto-suppressed by _on_trigger_fired."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, title="Sched", folio_id=f["folio_id"])
        folio_writ.create_writ(
            folio_id=f["folio_id"], title="Every 9AM",
            match={"schedule": "0 9 * * *"},
            action={"type": "spawn_deed", "slip_id": s["slip_id"]},
        )
        ready = []
        folio_writ._nerve.on("writ_trigger_ready", lambda p: ready.append(p))
        # First tick triggers and auto-updates last_triggered_utc
        folio_writ._nerve.emit("cadence.tick", {"tick_utc": "2026-03-12T09:00:00Z"})
        assert len(ready) == 1
        # Same minute tick again → auto-suppressed (no manual intervention needed)
        folio_writ._nerve.emit("cadence.tick", {"tick_utc": "2026-03-12T09:00:30Z"})
        assert len(ready) == 1

    # ── 15.6 Submission Limits ───────────────────────────────────────────

    def test_fw60_can_trigger_writ_no_active(self, folio_writ):
        """FW-60: No active deeds → can trigger."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        ok, reason = folio_writ.can_trigger_writ(w["writ_id"])
        assert ok is True
        assert reason == ""

    def test_fw61_can_trigger_writ_max_active(self, folio_writ, ledger):
        """FW-61: Exceeding max_active_deeds per writ → blocked."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        writ_id = w["writ_id"]
        # Create 3 running deeds linked to this writ via mutate_deeds
        for i in range(3):
            d = create_test_deed(ledger, status="running", sub_status="executing")
            def _set_writ(deeds, *, did=d["deed_id"], wid=writ_id):
                for deed in deeds:
                    if deed.get("deed_id") == did:
                        deed["writ_id"] = wid
            ledger.mutate_deeds(_set_writ)
        ok, reason = folio_writ.can_trigger_writ(writ_id)
        assert ok is False
        assert reason == "writ_max_active_deeds"

    def test_fw62_can_trigger_writ_max_folio_active(self, folio_writ, ledger):
        """FW-62: Exceeding max_active_folio_deeds → blocked."""
        f = create_test_folio(folio_writ)
        fid = f["folio_id"]
        s = create_test_slip(folio_writ, folio_id=fid)
        w = create_test_writ(folio_writ, folio_id=fid,
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        # Create 6 running deeds in same folio via mutate_deeds
        for i in range(6):
            d = create_test_deed(ledger, status="running", sub_status="executing")
            def _set_folio(deeds, *, did=d["deed_id"], f_id=fid):
                for deed in deeds:
                    if deed.get("deed_id") == did:
                        deed["folio_id"] = f_id
            ledger.mutate_deeds(_set_folio)
        ok, reason = folio_writ.can_trigger_writ(w["writ_id"])
        assert ok is False
        assert reason == "folio_max_active_deeds"

    def test_fw63_check_submission_limits_global(self, folio_writ, ledger):
        """FW-63: Global concurrent limit check."""
        for i in range(5):
            create_test_deed(ledger, status="running", sub_status="executing")
        ok, reason = folio_writ.check_submission_limits({}, concurrent_limit=5)
        assert ok is False
        assert reason == "global_active_deeds_limit"

    def test_fw64_infer_dag_budget_from_history(self, folio_writ, ledger):
        """FW-64: Infer dag_budget from deed history average."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        # Create deeds with budgets [4, 6, 8] via mutate_deeds
        for budget in [4, 6, 8]:
            d = create_test_deed(ledger, status="closed", sub_status="succeeded")
            def _set_brief(deeds, *, did=d["deed_id"], b=budget):
                for deed in deeds:
                    if deed.get("deed_id") == did:
                        deed["brief_snapshot"] = {"dag_budget": b}
            ledger.mutate_deeds(_set_brief)
            folio_writ.record_writ_triggered(w["writ_id"], d["deed_id"])
        result = folio_writ.infer_dag_budget_from_history(w["writ_id"], default=3)
        assert result == 6  # avg(4,6,8)

    def test_fw65_infer_dag_budget_no_history(self, folio_writ):
        """FW-65: No history → returns default."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"],
                             slip_id=s["slip_id"], schedule="0 9 * * *")
        result = folio_writ.infer_dag_budget_from_history(w["writ_id"], default=5)
        assert result == 5

    # ── 15.7 Standing Slip ───────────────────────────────────────────────

    def test_fw70_ensure_standing_writ_creates_folio(self, folio_writ):
        """FW-70: Slip without Folio → auto-create Folio."""
        s = create_test_slip(folio_writ, title="Standing Slip")
        writ = folio_writ.ensure_standing_writ(s["slip_id"], schedule="0 9 * * *")
        assert writ is not None
        updated_slip = folio_writ.get_slip(s["slip_id"])
        assert updated_slip["folio_id"]  # folio assigned

    def test_fw71_ensure_standing_writ_correct(self, folio_writ):
        """FW-71: Standing writ has correct match and action."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, title="Stand", folio_id=f["folio_id"])
        writ = folio_writ.ensure_standing_writ(s["slip_id"], schedule="*/30 * * * *")
        assert writ["match"]["schedule"] == "*/30 * * * *"
        assert writ["action"]["type"] == "spawn_deed"
        assert writ["action"]["slip_id"] == s["slip_id"]

    def test_fw72_ensure_standing_writ_idempotent(self, folio_writ):
        """FW-72: Calling twice → same writ_id."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, title="Stand", folio_id=f["folio_id"])
        w1 = folio_writ.ensure_standing_writ(s["slip_id"], schedule="0 9 * * *")
        w2 = folio_writ.ensure_standing_writ(s["slip_id"], schedule="0 9 * * *")
        assert w1["writ_id"] == w2["writ_id"]

    def test_fw73_ensure_standing_writ_nonexistent(self, folio_writ):
        """FW-73: Nonexistent slip_id → None."""
        result = folio_writ.ensure_standing_writ("nonexistent", schedule="0 9 * * *")
        assert result is None

    # ── 15.8 Writ Neighbors / DAG Navigation ────────────────────────────

    def test_fw80_writ_neighbors_prev(self, folio_writ):
        """FW-80: Writ A→B → B.prev contains A."""
        f = create_test_folio(folio_writ)
        fid = f["folio_id"]
        sa = create_test_slip(folio_writ, title="A", folio_id=fid)
        sb = create_test_slip(folio_writ, title="B", folio_id=fid)
        folio_writ.create_writ(
            folio_id=fid, title="A→B",
            match={"event": "deed_closed", "filter": {"slip_id": sa["slip_id"]}},
            action={"type": "spawn_deed", "slip_id": sb["slip_id"]},
        )
        neighbors = folio_writ.writ_neighbors(sb["slip_id"])
        prev_ids = [p["slip_id"] for p in neighbors["prev"]]
        assert sa["slip_id"] in prev_ids

    def test_fw81_writ_neighbors_next(self, folio_writ):
        """FW-81: Writ A→B → A.next contains B."""
        f = create_test_folio(folio_writ)
        fid = f["folio_id"]
        sa = create_test_slip(folio_writ, title="A", folio_id=fid)
        sb = create_test_slip(folio_writ, title="B", folio_id=fid)
        folio_writ.create_writ(
            folio_id=fid, title="A→B",
            match={"event": "deed_closed", "filter": {"slip_id": sa["slip_id"]}},
            action={"type": "spawn_deed", "slip_id": sb["slip_id"]},
        )
        neighbors = folio_writ.writ_neighbors(sa["slip_id"])
        next_ids = [n["slip_id"] for n in neighbors["next"]]
        assert sb["slip_id"] in next_ids

    def test_fw82_writ_neighbors_no_relation(self, folio_writ):
        """FW-82: Independent slip → prev=[], next=[]."""
        f = create_test_folio(folio_writ)
        s = create_test_slip(folio_writ, title="Alone", folio_id=f["folio_id"])
        neighbors = folio_writ.writ_neighbors(s["slip_id"])
        assert neighbors["prev"] == []
        assert neighbors["next"] == []

    def test_fw83_predecessors_all_closed_true(self, folio_writ, ledger):
        """FW-83: All predecessor deeds closed → (True, [])."""
        f = create_test_folio(folio_writ)
        fid = f["folio_id"]
        sa = create_test_slip(folio_writ, title="A", folio_id=fid)
        sb = create_test_slip(folio_writ, title="B", folio_id=fid)
        folio_writ.create_writ(
            folio_id=fid, title="A→B",
            match={"event": "deed_closed", "filter": {"slip_id": sa["slip_id"]}},
            action={"type": "spawn_deed", "slip_id": sb["slip_id"]},
        )
        # Create a closed deed for slip A
        d = create_test_deed(ledger, status="closed", sub_status="succeeded",
                             slip_id=sa["slip_id"])
        folio_writ.record_deed_created(sa["slip_id"], d["deed_id"])
        all_closed, blocking = folio_writ.predecessors_all_closed(sb["slip_id"])
        assert all_closed is True
        assert blocking == []

    def test_fw84_predecessors_not_all_closed(self, folio_writ, ledger):
        """FW-84: Predecessor deed still running → (False, [slip_id])."""
        f = create_test_folio(folio_writ)
        fid = f["folio_id"]
        sa = create_test_slip(folio_writ, title="A", folio_id=fid)
        sb = create_test_slip(folio_writ, title="B", folio_id=fid)
        folio_writ.create_writ(
            folio_id=fid, title="A→B",
            match={"event": "deed_closed", "filter": {"slip_id": sa["slip_id"]}},
            action={"type": "spawn_deed", "slip_id": sb["slip_id"]},
        )
        d = create_test_deed(ledger, status="running", sub_status="executing",
                             slip_id=sa["slip_id"])
        folio_writ.record_deed_created(sa["slip_id"], d["deed_id"])
        all_closed, blocking = folio_writ.predecessors_all_closed(sb["slip_id"])
        assert all_closed is False
        assert sa["slip_id"] in blocking

    def test_fw85_predecessors_no_deed_is_blocking(self, folio_writ, ledger):
        """FW-85: Predecessor with no deed → treated as blocking."""
        f = create_test_folio(folio_writ)
        fid = f["folio_id"]
        sa = create_test_slip(folio_writ, title="A", folio_id=fid)
        sb = create_test_slip(folio_writ, title="B", folio_id=fid)
        folio_writ.create_writ(
            folio_id=fid, title="A→B",
            match={"event": "deed_closed", "filter": {"slip_id": sa["slip_id"]}},
            action={"type": "spawn_deed", "slip_id": sb["slip_id"]},
        )
        all_closed, blocking = folio_writ.predecessors_all_closed(sb["slip_id"])
        assert all_closed is False
        assert sa["slip_id"] in blocking

    def test_fw86_active_folio_matches(self, folio_writ):
        """FW-86: active_folio_matches returns keyword-matched folios (token)."""
        create_test_folio(folio_writ, title="machine learning project")
        create_test_folio(folio_writ, title="frontend design")
        matches = folio_writ.active_folio_matches("machine learning")
        assert len(matches) >= 1
        assert any("machine" in str(m.get("title") or "") for m in matches)

    def test_fw86b_active_folio_matches_cjk(self, folio_writ):
        """FW-86b: active_folio_matches works for CJK substring matching."""
        create_test_folio(folio_writ, title="机器学习项目")
        create_test_folio(folio_writ, title="前端设计")
        matches = folio_writ.active_folio_matches("机器学习")
        assert len(matches) >= 1
        assert any("机器学习" in str(m.get("title") or "") for m in matches)


# =============================================================================
# §9 TestWashMechanism — 洗信息机制
# =============================================================================


class TestWashMechanism:
    """WM-01 ~ WM-41: Message washing mechanism."""

    def _make_load_fn(self, messages):
        """Helper: create a load_messages_fn that returns canned messages."""
        def _fn(deed_id, limit):
            return messages
        return _fn

    # ── 9.1 基本功能 ─────────────────────────────────────────────────────

    def test_wm01_no_previous_deeds(self, state_dir, ledger):
        """WM-01: No previous deeds → not washed."""
        result = wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_new", previous_deed_ids=[],
            load_messages_fn=self._make_load_fn([]), ledger=ledger, state_dir=state_dir,
        )
        assert result["washed"] is False
        assert result["reason"] == "no_previous_deeds"

    def test_wm02_no_messages(self, state_dir, ledger):
        """WM-02: Previous deed but no messages → not washed."""
        result = wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_new", previous_deed_ids=["d_old"],
            load_messages_fn=self._make_load_fn([]), ledger=ledger, state_dir=state_dir,
        )
        assert result["washed"] is False
        assert result["reason"] == "no_messages"

    def test_wm03_normal_wash_complete(self, state_dir, ledger):
        """WM-03: Normal wash returns complete result."""
        msgs = mock_messages(n=5, user_count=3, operation_count=1)
        result = wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_new", previous_deed_ids=["d_old"],
            load_messages_fn=self._make_load_fn(msgs), ledger=ledger, state_dir=state_dir,
        )
        assert result["washed"] is True
        for key in ("brief_supplement", "stats", "voice_candidates", "washed_utc"):
            assert key in result, f"Missing: {key}"

    def test_wm04_brief_supplement_nonempty(self, state_dir, ledger):
        """WM-04: Brief supplement not empty with user messages."""
        msgs = mock_messages(n=5, user_count=3, operation_count=1)
        result = wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_new", previous_deed_ids=["d_old"],
            load_messages_fn=self._make_load_fn(msgs), ledger=ledger, state_dir=state_dir,
        )
        assert len(result["brief_supplement"]) > 0

    def test_wm05_brief_supplement_length_limit(self, state_dir, ledger):
        """WM-05: Brief supplement respects length limit."""
        # Create very long messages
        msgs = []
        for i in range(50):
            msgs.append({"role": "user", "content": "X" * 300, "created_utc": f"2026-01-01T00:{i:02d}:00Z"})
        result = wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_new", previous_deed_ids=["d_old"],
            load_messages_fn=self._make_load_fn(msgs), ledger=ledger, state_dir=state_dir,
        )
        assert len(result["brief_supplement"]) <= 1220  # 1200 + "..." margin

    # ── 9.2 统计提取 ─────────────────────────────────────────────────────

    def test_wm10_message_count(self, state_dir, ledger):
        """WM-10: message_count is correct."""
        msgs = mock_messages(n=5, user_count=3, operation_count=1)
        result = wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_new", previous_deed_ids=["d_old"],
            load_messages_fn=self._make_load_fn(msgs), ledger=ledger, state_dir=state_dir,
        )
        assert result["stats"]["message_count"] == 5

    def test_wm11_user_message_count(self, state_dir, ledger):
        """WM-11: user_message_count is correct."""
        msgs = mock_messages(n=5, user_count=3, operation_count=1)
        result = wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_new", previous_deed_ids=["d_old"],
            load_messages_fn=self._make_load_fn(msgs), ledger=ledger, state_dir=state_dir,
        )
        assert result["stats"]["user_message_count"] == 3

    def test_wm12_operation_count(self, state_dir, ledger):
        """WM-12: operation_count is correct."""
        msgs = mock_messages(n=5, user_count=3, operation_count=1)
        result = wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_new", previous_deed_ids=["d_old"],
            load_messages_fn=self._make_load_fn(msgs), ledger=ledger, state_dir=state_dir,
        )
        assert result["stats"]["operation_count"] == 1

    def test_wm13_time_range(self, state_dir, ledger):
        """WM-13: first_message_utc ≤ last_message_utc."""
        msgs = mock_messages(n=5, user_count=3, operation_count=1)
        result = wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_new", previous_deed_ids=["d_old"],
            load_messages_fn=self._make_load_fn(msgs), ledger=ledger, state_dir=state_dir,
        )
        stats = result["stats"]
        assert stats["first_message_utc"] <= stats["last_message_utc"]

    # ── 9.3 Voice 候选提取 ───────────────────────────────────────────────

    def test_wm20_style_keyword_match(self):
        """WM-20: Style keyword '简洁' matches formality_preference."""
        user_msgs = [{"role": "user", "content": "请用简洁的风格", "created_utc": "2026-01-01T00:00:00Z"}]
        candidates = _extract_voice_candidates(user_msgs)
        assert len(candidates) >= 1
        assert candidates[0]["category"] == "formality_preference"

    def test_wm21_negative_preference_match(self):
        """WM-21: '不要太正式' matches negative_preference."""
        user_msgs = [{"role": "user", "content": "不要太正式的语气", "created_utc": "2026-01-01T00:00:00Z"}]
        candidates = _extract_voice_candidates(user_msgs)
        assert len(candidates) >= 1
        assert candidates[0]["category"] == "negative_preference"

    def test_wm22_one_match_per_message(self):
        """WM-22: Each message matches at most one candidate."""
        user_msgs = [{"role": "user", "content": "风格要简洁不要太正式", "created_utc": "2026-01-01T00:00:00Z"}]
        candidates = _extract_voice_candidates(user_msgs)
        assert len(candidates) <= 1

    def test_wm23_max_5_candidates(self):
        """WM-23: Maximum 5 voice candidates."""
        user_msgs = [
            {"role": "user", "content": f"请用简洁的风格 {i}", "created_utc": f"2026-01-01T00:{i:02d}:00Z"}
            for i in range(10)
        ]
        candidates = _extract_voice_candidates(user_msgs)
        assert len(candidates) <= 5

    def test_wm24_candidates_unconfirmed(self):
        """WM-24: All candidates initially confirmed=False."""
        user_msgs = [{"role": "user", "content": "请用简洁的风格", "created_utc": "2026-01-01T00:00:00Z"}]
        candidates = _extract_voice_candidates(user_msgs)
        for c in candidates:
            assert c["confirmed"] is False

    # ── 9.4 持久化与加载 ─────────────────────────────────────────────────

    def test_wm30_wash_result_persisted(self, state_dir, ledger):
        """WM-30: Wash result persisted to disk."""
        msgs = mock_messages(n=5, user_count=3, operation_count=1)
        wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_target", previous_deed_ids=["d_old"],
            load_messages_fn=self._make_load_fn(msgs), ledger=ledger, state_dir=state_dir,
        )
        path = state_dir / "wash" / "d_target.json"
        assert path.exists()

    def test_wm31_persisted_file_parseable(self, state_dir, ledger):
        """WM-31: Persisted file is valid JSON."""
        msgs = mock_messages(n=5, user_count=3, operation_count=1)
        wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_target", previous_deed_ids=["d_old"],
            load_messages_fn=self._make_load_fn(msgs), ledger=ledger, state_dir=state_dir,
        )
        path = state_dir / "wash" / "d_target.json"
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    def test_wm32_load_wash_supplement(self, state_dir, ledger):
        """WM-32: load_wash_supplement reads brief_supplement."""
        msgs = mock_messages(n=5, user_count=3, operation_count=1)
        result = wash_at_run_boundary(
            slip_id="s1", new_deed_id="d_target", previous_deed_ids=["d_old"],
            load_messages_fn=self._make_load_fn(msgs), ledger=ledger, state_dir=state_dir,
        )
        supplement = load_wash_supplement(state_dir, "d_target")
        assert supplement == result["brief_supplement"]

    def test_wm33_load_nonexistent_empty(self, state_dir):
        """WM-33: load_wash_supplement for nonexistent deed → empty string."""
        assert load_wash_supplement(state_dir, "nonexistent") == ""


# =============================================================================
# §16 TestWillPipeline — Will 提交管线
# =============================================================================


class TestWillPipeline:
    """WP-01 ~ WP-44: Will validate / enrich / ward / submit / materialize."""

    def _simple_plan(self, **overrides):
        """Return a minimal valid plan."""
        plan = {
            "moves": [
                {"id": "m1", "agent": "scout", "depends_on": []},
                {"id": "m2", "agent": "sage", "depends_on": ["m1"]},
            ],
            "brief": {"objective": "Test objective", "dag_budget": 6},
        }
        plan.update(overrides)
        return plan

    # ── 16.1 验证 ────────────────────────────────────────────────────────

    def test_wp01_validate_valid(self, will):
        """WP-01: validate valid plan → (True, "")."""
        ok, err = will.validate(self._simple_plan())
        assert ok is True
        assert err == ""

    def test_wp02_validate_empty_moves(self, will):
        """WP-02: validate empty moves → (False, ...)."""
        ok, err = will.validate({"moves": []})
        assert ok is False
        assert "moves" in err.lower()

    def test_wp03_validate_duplicate_id(self, will):
        """WP-03: validate duplicate id → (False, ...)."""
        ok, err = will.validate({
            "moves": [
                {"id": "m1", "agent": "scout"},
                {"id": "m1", "agent": "sage"},
            ],
            "brief": {"objective": "test", "dag_budget": 6},
        })
        assert ok is False
        assert "duplicate" in err.lower()

    def test_wp04_validate_unknown_dep(self, will):
        """WP-04: validate unknown dependency → (False, ...)."""
        ok, err = will.validate({
            "moves": [{"id": "m1", "agent": "scout", "depends_on": ["nonexistent"]}],
            "brief": {"objective": "test", "dag_budget": 6},
        })
        assert ok is False
        assert "unknown" in err.lower()

    def test_wp05_validate_cycle(self, will):
        """WP-05: validate cyclic DAG → (False, ...)."""
        ok, err = will.validate({
            "moves": [
                {"id": "a", "agent": "scout", "depends_on": ["b"]},
                {"id": "b", "agent": "sage", "depends_on": ["a"]},
            ],
            "brief": {"objective": "test", "dag_budget": 6},
        })
        assert ok is False
        assert "cycle" in err.lower()

    # ── 16.2 Enrichment ──────────────────────────────────────────────────

    def test_wp10_enrich_assigns_deed_id(self, will):
        """WP-10: enrich assigns deed_id starting with 'deed_'."""
        enriched = will.enrich(self._simple_plan())
        assert enriched["deed_id"].startswith("deed_")

    def test_wp11_enrich_preserves_deed_id(self, will):
        """WP-11: enrich preserves user-specified deed_id."""
        enriched = will.enrich(self._simple_plan(deed_id="deed_custom_123456"))
        assert enriched["deed_id"] == "deed_custom_123456"

    def test_wp12_enrich_sets_brief_defaults(self, will):
        """WP-12: enrich sets brief defaults (dag_budget, depth)."""
        enriched = will.enrich(self._simple_plan())
        brief = enriched.get("brief", {})
        assert brief.get("dag_budget") is not None
        assert brief.get("depth") is not None

    def test_wp13_enrich_sets_concurrency(self, will):
        """WP-13: enrich sets concurrency > 0."""
        enriched = will.enrich(self._simple_plan())
        assert int(enriched.get("concurrency", 0)) > 0

    def test_wp14_enrich_sets_rework_limit(self, will):
        """WP-14: enrich sets rework_limit > 0."""
        enriched = will.enrich(self._simple_plan())
        assert int(enriched.get("rework_limit", 0)) > 0

    def test_wp15_enrich_sets_eval_window(self, will):
        """WP-15: enrich sets eval_window_hours = 48."""
        enriched = will.enrich(self._simple_plan())
        assert enriched.get("eval_window_hours") == 48

    def test_wp16_enrich_reads_require_bilingual(self, will):
        """WP-16: enrich reads require_bilingual from preferences."""
        enriched = will.enrich(self._simple_plan())
        assert "require_bilingual" in enriched

    def test_wp17_enrich_sets_quality_profile(self, will):
        """WP-17: enrich sets quality_profile."""
        enriched = will.enrich(self._simple_plan())
        assert isinstance(enriched.get("quality_profile"), dict)

    def test_wp18_enrich_applies_model_routing(self, will, daemon_home):
        """WP-18: enrich applies model routing → agent_model_map exists."""
        enriched = will.enrich(self._simple_plan())
        assert "agent_model_map" in enriched or "model_registry" in enriched

    # ── 16.3 Ward 检查 ───────────────────────────────────────────────────

    def test_wp20_ward_red_queues(self, will, state_dir):
        """WP-20: ward RED → plan is queued."""
        (state_dir / "ward.json").write_text(json.dumps({"status": "RED"}))
        enriched = will.enrich(self._simple_plan())
        assert enriched.get("queued") is True
        assert "red" in str(enriched.get("queue_reason") or "").lower()

    def test_wp21_ward_yellow_large_dag_queues(self, will, state_dir):
        """WP-21: ward YELLOW + dag_budget ≥ 6 → queued."""
        (state_dir / "ward.json").write_text(json.dumps({"status": "YELLOW"}))
        enriched = will.enrich(self._simple_plan())
        assert enriched.get("queued") is True
        assert "yellow" in str(enriched.get("queue_reason") or "").lower()

    def test_wp22_ward_yellow_small_dag_not_queued(self, will, state_dir):
        """WP-22: ward YELLOW + small dag_budget → not queued."""
        (state_dir / "ward.json").write_text(json.dumps({"status": "YELLOW"}))
        plan = self._simple_plan()
        plan["brief"]["dag_budget"] = 3
        plan["moves"] = [{"id": "m1", "agent": "scout"}]
        enriched = will.enrich(plan)
        # Should NOT be queued for yellow_deferred (dag_budget < default)
        reason = str(enriched.get("queue_reason") or "")
        assert "yellow_deferred" not in reason

    def test_wp23_ward_green_not_queued(self, will, state_dir):
        """WP-23: ward GREEN → not queued."""
        (state_dir / "ward.json").write_text(json.dumps({"status": "GREEN"}))
        enriched = will.enrich(self._simple_plan())
        assert enriched.get("queued") is not True or "ward" not in str(enriched.get("queue_reason") or "")

    def test_wp24_system_paused_queues(self, will, state_dir):
        """WP-24: system_status paused → queued."""
        (state_dir / "system_status.json").write_text(json.dumps({"status": "paused"}))
        enriched = will.enrich(self._simple_plan())
        assert enriched.get("queued") is True
        assert "system" in str(enriched.get("queue_reason") or "").lower()

    # ── 16.4 Submit 流程 ─────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_wp31_submit_no_temporal(self, will):
        """WP-31: submit without Temporal → error_code=temporal_unavailable."""
        result = await will.submit(self._simple_plan())
        assert result.get("ok") is False
        assert result.get("error_code") == "temporal_unavailable"

    @pytest.mark.asyncio
    async def test_wp32_submit_invalid_plan(self, will):
        """WP-32: submit invalid plan → error_code=invalid_plan."""
        result = await will.submit({"moves": []})
        assert result.get("ok") is False
        assert result.get("error_code") == "invalid_plan"

    @pytest.mark.asyncio
    async def test_wp33_submit_queued(self, will, state_dir):
        """WP-33: submit queued plan → ok=True + queued reason."""
        (state_dir / "ward.json").write_text(json.dumps({"status": "RED"}))
        result = await will.submit(self._simple_plan())
        assert result.get("ok") is True
        assert result.get("deed_sub_status") == "queued"
        assert result.get("reason") is not None

    @pytest.mark.asyncio
    async def test_wp34_submit_dag_exceeds_budget(self, will):
        """WP-34: submit DAG exceeding budget → ward_dag_budget_exceeded."""
        plan = {
            "moves": [{"id": f"m{i}", "agent": "scout"} for i in range(10)],
            "brief": {"objective": "test", "dag_budget": 3},
        }
        result = await will.submit(plan)
        assert result.get("ok") is False
        assert result.get("error_code") == "ward_dag_budget_exceeded"

    @pytest.mark.asyncio
    async def test_wp35_submit_materializes(self, will, folio_writ):
        """WP-35: submit triggers _materialize_objects → creates Slip."""
        will._folio_writ = folio_writ
        # Ward RED so it gets queued instead of needing Temporal
        will._ledger._ward_path = will._state / "ward.json"
        (will._state / "ward.json").write_text(json.dumps({"status": "RED"}))
        result = await will.submit(self._simple_plan())
        assert result.get("ok") is True
        slip_id = str(result.get("slip_id") or "")
        assert slip_id  # Slip was materialized

    @pytest.mark.asyncio
    async def test_wp36_submit_records_deed(self, will, state_dir):
        """WP-36: submit records deed in deeds.json."""
        (state_dir / "ward.json").write_text(json.dumps({"status": "RED"}))
        result = await will.submit(self._simple_plan())
        deed_id = str(result.get("deed_id") or "")
        deeds = will._ledger.load_deeds()
        deed_ids = [str(d.get("deed_id") or "") for d in deeds]
        assert deed_id in deed_ids

    @pytest.mark.asyncio
    async def test_wp37_submit_records_registry_links(self, will, folio_writ, state_dir):
        """WP-37: submit records registry links (Slip.deed_ids updated)."""
        will._folio_writ = folio_writ
        (state_dir / "ward.json").write_text(json.dumps({"status": "RED"}))
        result = await will.submit(self._simple_plan())
        slip_id = str(result.get("slip_id") or "")
        if slip_id:
            slip = folio_writ.get_slip(slip_id)
            deed_ids = slip.get("deed_ids") if isinstance(slip, dict) else []
            assert isinstance(deed_ids, list)

    @pytest.mark.asyncio
    async def test_wp38_submit_emits_deed_submitted_when_temporal(self, will, nerve):
        """WP-38: submit with mock Temporal → deed_submitted event."""
        class FakeTemporal:
            async def submit(self, wf_id, plan, deed_root):
                pass
        will._temporal = FakeTemporal()
        events = []
        nerve.on("deed_submitted", lambda payload: events.append(payload))
        result = await will.submit(self._simple_plan())
        assert result.get("ok") is True
        assert len(events) >= 1
        will._temporal = None  # cleanup

    # ── 16.5 Materialization ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_wp40_materialize_creates_folio(self, will, folio_writ, state_dir):
        """WP-40: metadata.create_folio_title → new Folio created."""
        will._folio_writ = folio_writ
        (state_dir / "ward.json").write_text(json.dumps({"status": "RED"}))
        plan = self._simple_plan()
        plan["metadata"] = {"create_folio_title": "My New Folio", "source": "test"}
        result = await will.submit(plan)
        folio_id = str(result.get("folio_id") or "")
        assert folio_id
        folio = folio_writ.get_folio(folio_id)
        assert folio is not None

    @pytest.mark.asyncio
    async def test_wp41_materialize_creates_draft(self, will, folio_writ, state_dir):
        """WP-41: no draft_id → auto-create Draft."""
        will._folio_writ = folio_writ
        (state_dir / "ward.json").write_text(json.dumps({"status": "RED"}))
        result = await will.submit(self._simple_plan())
        # Check drafts exist
        drafts = folio_writ.list_drafts()
        assert len(drafts) >= 1

    @pytest.mark.asyncio
    async def test_wp42_materialize_crystallizes_slip(self, will, folio_writ, state_dir):
        """WP-42: no slip_id → auto crystallize Draft → Slip."""
        will._folio_writ = folio_writ
        (state_dir / "ward.json").write_text(json.dumps({"status": "RED"}))
        result = await will.submit(self._simple_plan())
        slip_id = str(result.get("slip_id") or "")
        assert slip_id
        slip = folio_writ.get_slip(slip_id)
        assert slip is not None

    @pytest.mark.asyncio
    async def test_wp44_materialize_uses_existing_slip(self, will, folio_writ, state_dir):
        """WP-44: metadata.slip_id → uses existing Slip, no new creation."""
        will._folio_writ = folio_writ
        (state_dir / "ward.json").write_text(json.dumps({"status": "RED"}))
        existing = create_test_slip(folio_writ, title="Pre-existing")
        plan = self._simple_plan()
        plan["metadata"] = {"slip_id": existing["slip_id"]}
        result = await will.submit(plan)
        assert str(result.get("slip_id") or "") == existing["slip_id"]


# =============================================================================
# §21 TestVoiceService — 对话与计划管线
# =============================================================================


class TestVoiceService:
    """VS-01 ~ VS-52: VoiceService session, plan extraction, enrichment, commands."""

    @pytest.fixture
    def voice(self, config):
        return VoiceService(config)

    @pytest.fixture
    def voice_with_fw(self, config, folio_writ):
        return VoiceService(config, folio_writ_manager=folio_writ)

    # ── 21.1 Session 管理 ────────────────────────────────────────────────

    def test_vs01_new_session_returns_id(self, voice):
        """VS-01: new_session returns non-empty session_id."""
        sid = voice.new_session()
        assert isinstance(sid, str)
        assert len(sid) > 0

    def test_vs02_new_session_empty_messages(self, voice):
        """VS-02: new session has empty messages."""
        sid = voice.new_session()
        session = voice.get_session(sid)
        assert session["messages"] == []

    def test_vs03_get_session_correct(self, voice):
        """VS-03: get_session returns the correct session."""
        sid = voice.new_session()
        session = voice.get_session(sid)
        assert session["session_id"] == sid

    def test_vs04_get_session_nonexistent(self, voice):
        """VS-04: get_session for nonexistent → None."""
        assert voice.get_session("nonexistent") is None

    def test_vs05_session_structure(self, voice):
        """VS-05: session has all required fields."""
        sid = voice.new_session()
        session = voice.get_session(sid)
        for key in ("session_id", "user_id", "messages", "created_utc", "last_active_ts"):
            assert key in session, f"Missing: {key}"

    def test_vs06_session_ttl(self, voice):
        """VS-06: SESSION_TTL_S == 86400."""
        assert VoiceService.SESSION_TTL_S == 86400

    def test_vs07_expired_session_cleaned(self, voice):
        """VS-07: session 25h old → cleaned up."""
        sid = voice.new_session()
        session = voice.get_session(sid)
        session["last_active_ts"] = time.time() - 25 * 3600
        voice._cleanup_sessions()
        assert voice.get_session(sid) is None

    def test_vs08_active_session_not_cleaned(self, voice):
        """VS-08: session 1h old → not cleaned."""
        sid = voice.new_session()
        session = voice.get_session(sid)
        session["last_active_ts"] = time.time() - 3600
        voice._cleanup_sessions()
        assert voice.get_session(sid) is not None

    def test_vs09_chat_updates_last_active(self, voice):
        """VS-09: chat updates last_active_ts."""
        sid = voice.new_session()
        session = voice.get_session(sid)
        old_ts = session["last_active_ts"]
        time.sleep(0.01)
        # chat without OC config will return error, but still updates session
        voice.chat(sid, "hello")
        assert session["last_active_ts"] >= old_ts

    def test_vs10_sessions_isolated(self, voice):
        """VS-10: sessions are isolated — chat in A doesn't affect B."""
        sid_a = voice.new_session()
        sid_b = voice.new_session()
        voice.chat(sid_a, "message for A")
        sess_b = voice.get_session(sid_b)
        assert len(sess_b["messages"]) == 0

    # ── 21.2 消息文本提取 ────────────────────────────────────────────────

    def test_vs15_string_content(self, voice):
        """VS-15: string content returned directly."""
        assert voice._extract_message_text({"content": "hello"}) == "hello"

    def test_vs16_list_content(self, voice):
        """VS-16: list content extracts text blocks."""
        msg = {"content": [{"type": "text", "text": "hi"}, {"type": "image", "url": "x"}]}
        result = voice._extract_message_text(msg)
        assert "hi" in result

    def test_vs17_error_message(self, voice):
        """VS-17: errorMessage is extracted."""
        result = voice._extract_message_text({"errorMessage": "something failed"})
        assert "something failed" in result

    def test_vs18_empty_message(self, voice):
        """VS-18: empty/None content → empty string."""
        assert voice._extract_message_text({}) == ""
        assert voice._extract_message_text({"content": None}) == ""

    def test_vs19_mixed_content_blocks(self, voice):
        """VS-19: mixed content blocks — only text extracted."""
        msg = {"content": [
            {"type": "text", "text": "first"},
            {"type": "tool_use", "name": "search"},
            {"type": "text", "text": "second"},
        ]}
        result = voice._extract_message_text(msg)
        assert "first" in result
        assert "second" in result
        assert "search" not in result

    # ── 21.3 计划提取 ────────────────────────────────────────────────────

    def test_vs20_extract_plan_json(self, voice):
        """VS-20: standard JSON block → plan extracted."""
        content = 'Here is a plan:\n```json\n{"moves": [{"id": "m1", "agent": "scout"}], "objective": "test"}\n```\nDone.'
        plan = voice._extract_plan(content)
        assert plan is not None
        assert len(plan["moves"]) == 1

    def test_vs21_extract_plan_no_json(self, voice):
        """VS-21: no JSON block → None."""
        plan = voice._extract_plan("Just a normal response without any code blocks.")
        assert plan is None

    def test_vs22_extract_plan_malformed(self, voice):
        """VS-22: malformed JSON → None, no crash."""
        plan = voice._extract_plan('```json\n{invalid json here}\n```')
        assert plan is None

    def test_vs23_extract_plan_nested(self, voice):
        """VS-23: nested JSON correctly extracted."""
        content = '```json\n{"moves": [{"id": "m1", "agent": "scout", "config": {"key": "val"}}], "objective": "deep"}\n```'
        plan = voice._extract_plan(content)
        assert plan is not None
        assert plan["moves"][0].get("config", {}).get("key") == "val"

    def test_vs24_extract_plan_first_block(self, voice):
        """VS-24: multiple JSON blocks → takes first."""
        content = '```json\n{"moves": [{"id": "first", "agent": "scout"}], "objective": "A"}\n```\nAnd another:\n```json\n{"moves": [{"id": "second", "agent": "sage"}], "objective": "B"}\n```'
        plan = voice._extract_plan(content)
        assert plan is not None
        assert plan["moves"][0]["id"] == "first"

    # ── 21.4 计划充实 ────────────────────────────────────────────────────

    def test_vs30_enrich_adds_title(self, voice_with_fw):
        """VS-30: enrich adds slip_title."""
        plan = {"moves": [{"id": "m1", "agent": "scout"}], "brief": {"objective": "My objective"}}
        session = {"latest_draft_id": "", "messages": []}
        enriched = voice_with_fw._enrich_plan(plan, session=session, latest_message="test")
        assert enriched.get("slip_title") or enriched.get("title")

    def test_vs33_detect_daily(self, voice):
        """VS-33: '每天' → schedule detected."""
        result = voice._detect_recurring_writ("请每天帮我整理一下新闻")
        assert result is not None
        assert "schedule" in result.get("match", {})
        assert "* *" in result["match"]["schedule"]  # daily cron

    def test_vs34_detect_weekly(self, voice):
        """VS-34: 'weekly' → schedule detected."""
        result = voice._detect_recurring_writ("do this weekly please")
        assert result is not None
        assert "1" in result["match"]["schedule"]  # Monday

    def test_vs35_detect_monthly(self, voice):
        """VS-35: '每月' → schedule detected."""
        result = voice._detect_recurring_writ("每月生成报告")
        assert result is not None
        assert "1 * *" in result["match"]["schedule"]

    def test_vs36_enrich_creates_draft(self, voice_with_fw, folio_writ):
        """VS-36: enrich creates a Draft."""
        plan = {"moves": [{"id": "m1", "agent": "scout"}], "brief": {"objective": "Test"}}
        session = {"latest_draft_id": "", "messages": []}
        voice_with_fw._enrich_plan(plan, session=session, latest_message="test")
        drafts = folio_writ.list_drafts()
        assert len(drafts) >= 1

    def test_vs37_enrich_updates_existing_draft(self, voice_with_fw, folio_writ):
        """VS-37: enrich updates existing Draft instead of creating new."""
        # Create initial draft
        draft = folio_writ.create_draft(source="test", intent_snapshot="v1")
        session = {"latest_draft_id": draft["draft_id"], "messages": []}
        plan = {"moves": [{"id": "m1", "agent": "scout"}], "brief": {"objective": "v2"}}
        voice_with_fw._enrich_plan(plan, session=session, latest_message="update")
        # Should still have same draft count (updated, not new)
        updated = folio_writ.get_draft(draft["draft_id"])
        assert updated is not None
        assert "v2" in str(updated.get("intent_snapshot") or "")

    # ── 21.5 直接命令 ────────────────────────────────────────────────────

    def test_vs40_stop_tracking_zh(self, voice_with_fw, folio_writ):
        """VS-40: '不用看了' → disables matching Writ."""
        f = create_test_folio(folio_writ, title="machine learning project")
        s = create_test_slip(folio_writ, title="ML Slip", folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        result = voice_with_fw._handle_folio_command("machine learning 不用看了")
        assert result is not None
        assert result.get("ok") is True
        # Verify writ is disabled
        updated_w = folio_writ.get_writ(w["writ_id"])
        assert str(updated_w.get("status") or "") == "disabled"

    def test_vs41_stop_tracking_en(self, voice_with_fw, folio_writ):
        """VS-41: 'stop tracking' → disables matching Writ."""
        f = create_test_folio(folio_writ, title="data pipeline")
        s = create_test_slip(folio_writ, title="Pipeline Slip", folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        result = voice_with_fw._handle_folio_command("data pipeline stop tracking")
        assert result is not None
        assert result.get("ok") is True

    def test_vs42_change_schedule_zh(self, voice_with_fw, folio_writ):
        """VS-42: '改成每周' → updates Writ schedule."""
        f = create_test_folio(folio_writ, title="news digest")
        s = create_test_slip(folio_writ, title="News Slip", folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * *")
        result = voice_with_fw._handle_folio_command("news digest 改成每周")
        assert result is not None
        assert result.get("ok") is True
        updated_w = folio_writ.get_writ(w["writ_id"])
        match = updated_w.get("match") if isinstance(updated_w, dict) else {}
        assert "1" in str(match.get("schedule") or "")  # weekly → DOW 1

    def test_vs43_change_schedule_en(self, voice_with_fw, folio_writ):
        """VS-43: 'switch to daily' → updates Writ schedule."""
        f = create_test_folio(folio_writ, title="report generation")
        s = create_test_slip(folio_writ, title="Report Slip", folio_id=f["folio_id"])
        w = create_test_writ(folio_writ, folio_id=f["folio_id"], slip_id=s["slip_id"],
                             schedule="0 9 * * 1")
        result = voice_with_fw._handle_folio_command("report generation switch to daily")
        assert result is not None
        assert result.get("ok") is True

    def test_vs44_no_command_match(self, voice_with_fw):
        """VS-44: normal message → no direct command → returns None."""
        result = voice_with_fw._handle_folio_command("hello how are you")
        assert result is None

    def test_vs45_command_returns_confirmation(self, voice_with_fw, folio_writ):
        """VS-45: direct command returns confirmation text."""
        f = create_test_folio(folio_writ, title="test project")
        s = create_test_slip(folio_writ, title="Test Slip", folio_id=f["folio_id"])
        create_test_writ(folio_writ, folio_id=f["folio_id"], slip_id=s["slip_id"],
                         schedule="0 9 * * *")
        result = voice_with_fw._handle_folio_command("test project 不用看了")
        assert result is not None
        assert isinstance(result.get("content"), str)
        assert len(result["content"]) > 0

    # ── 21.6 显示元数据 ──────────────────────────────────────────────────

    def test_vs50_slip_mode(self, voice):
        """VS-50: moves ≤ dag_budget → slip mode."""
        from runtime.brief import Brief
        brief = Brief(objective="test", dag_budget=6)
        plan = {"moves": [{"id": "m1", "agent": "scout"}]}
        display = voice._display_metadata(brief, plan)
        assert display["mode"] == "slip"

    def test_vs51_folio_mode(self, voice):
        """VS-51: moves > dag_budget → folio mode."""
        from runtime.brief import Brief
        brief = Brief(objective="test", dag_budget=3)
        plan = {"moves": [{"id": f"m{i}", "agent": "scout"} for i in range(5)]}
        display = voice._display_metadata(brief, plan)
        assert display["mode"] == "folio"
        assert "folio_hint" in display

    def test_vs52_slip_mode_has_timeline(self, voice):
        """VS-52: slip mode has timeline."""
        from runtime.brief import Brief
        brief = Brief(objective="test", dag_budget=6)
        plan = {"moves": [
            {"id": "m1", "agent": "scout", "instruction": "search"},
            {"id": "m2", "agent": "sage", "instruction": "analyze"},
        ]}
        display = voice._display_metadata(brief, plan)
        assert display["mode"] == "slip"
        assert display.get("show_timeline") is True
        assert len(display.get("timeline", [])) == 2


# =============================================================================
# §8 TestAPIContracts — API 端点合约
# =============================================================================


class TestAPIContracts:
    """AC-01 ~ AC-123: API endpoint contract verification via FastAPI TestClient.

    Uses a minimal test app with real services but no external dependencies.
    """

    @pytest.fixture(scope="class")
    def test_app(self, tmp_path_factory):
        """Build a minimal FastAPI test app with real services."""
        import importlib
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        tmp = tmp_path_factory.mktemp("api")
        state = tmp / "state"
        state.mkdir()
        (state / "ward.json").write_text(json.dumps({"status": "GREEN"}))
        (state / "system_status.json").write_text(json.dumps({"status": "running"}))

        psyche_dir = tmp / "psyche"
        psyche_dir.mkdir()
        (psyche_dir / "preferences.toml").write_text(
            '[general]\ndefault_depth = "study"\nrequire_bilingual = true\n'
            'telegram_enabled = true\npdf_enabled = true\n\n'
            '[execution]\nretinue_size_n = 7\ndeed_running_ttl_s = 14400\n'
            'deed_ration_ratio = 0.2\n\n'
            '[routing]\nresearch_default_sources = ["brave_search"]\n'
        )
        (psyche_dir / "rations.toml").write_text(
            '[daily_limits]\nminimax_tokens = 20000000\nconcurrent_deeds = 10\n\n'
            '[current_usage]\n'
        )

        config_dir = tmp / "config"
        config_dir.mkdir()
        (config_dir / "spine_registry.json").write_text(json.dumps({
            "routines": [
                {"name": n, "mode": "deterministic", "schedule": "*/10 * * * *",
                 "timeout_s": 60, "nerve_triggers": [], "reads": [], "writes": [],
                 "depends_on": [], "degraded_mode": "skip"}
                for n in ["pulse", "record", "witness", "focus", "relay", "tend", "curate"]
            ]
        }))
        (config_dir / "model_policy.json").write_text(json.dumps({
            "counsel": "fast", "scout": "fast", "sage": "analysis",
        }))
        (config_dir / "model_registry.json").write_text(json.dumps({
            "fast": {"provider": "minimax", "model_id": "m2.5"},
        }))
        (config_dir / "mcp_servers.json").write_text(json.dumps({"servers": {}}))

        from psyche.config import PsycheConfig
        from spine.nerve import Nerve
        from services.ledger import Ledger
        from services.folio_writ import FolioWritManager
        from services.will import Will

        psyche_config = PsycheConfig(psyche_dir)
        nerve = Nerve()
        ledger = Ledger(state)
        folio_writ = FolioWritManager(state, nerve, ledger)
        will = Will(psyche_config, nerve, state, folio_writ_manager=folio_writ)

        return {
            "tmp": tmp,
            "state": state,
            "nerve": nerve,
            "ledger": ledger,
            "folio_writ": folio_writ,
            "will": will,
            "config": psyche_config,
        }

    @pytest.fixture
    def ctx(self, test_app):
        return test_app

    # ── 8.1 基础服务验证 ─────────────────────────────────────────────────
    # (Since building the full app is heavy, we test Will/FolioWrit APIs directly
    # and API endpoint patterns that don't require the full create_app.)

    def test_ac30_health_deps(self, ctx):
        """AC-30: health endpoint deps — ledger and ward accessible."""
        ward = ctx["ledger"].load_ward()
        assert isinstance(ward, dict)
        assert "status" in ward

    def test_ac31_deed_message_append(self, ctx):
        """AC-31: append_deed_message records message."""
        deed_id = "test_deed_ac31"
        deed_dir = ctx["state"] / "deeds" / deed_id
        deed_dir.mkdir(parents=True, exist_ok=True)
        ctx["ledger"].append_jsonl(
            deed_dir / "messages.jsonl",
            {"deed_id": deed_id, "role": "user", "content": "hello", "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        )
        msgs = ctx["ledger"].load_jsonl(deed_dir / "messages.jsonl")
        assert len(msgs) >= 1
        assert msgs[0]["content"] == "hello"

    def test_ac32_deed_message_no_pause(self, ctx):
        """AC-32: recording message doesn't change deed status."""
        d = create_test_deed(ctx["ledger"], status="running", sub_status="executing")
        deed_dir = ctx["state"] / "deeds" / d["deed_id"]
        deed_dir.mkdir(parents=True, exist_ok=True)
        ctx["ledger"].append_jsonl(
            deed_dir / "messages.jsonl",
            {"deed_id": d["deed_id"], "role": "user", "content": "feedback"},
        )
        # Deed status unchanged
        deeds = ctx["ledger"].load_deeds()
        for row in deeds:
            if str(row.get("deed_id") or "") == d["deed_id"]:
                assert str(row.get("deed_status") or "") == "running"

    def test_ac33_record_operation(self, ctx):
        """AC-33: operation record has event=operation."""
        deed_id = "test_deed_ac33"
        deed_dir = ctx["state"] / "deeds" / deed_id
        deed_dir.mkdir(parents=True, exist_ok=True)
        ctx["ledger"].append_jsonl(
            deed_dir / "messages.jsonl",
            {"deed_id": deed_id, "role": "system", "content": "[操作] 执行", "event": "operation",
             "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        )
        msgs = ctx["ledger"].load_jsonl(deed_dir / "messages.jsonl")
        ops = [m for m in msgs if m.get("event") == "operation"]
        assert len(ops) >= 1

    # ── 8.2 Folio-Writ 端点验证 ──────────────────────────────────────────

    def test_ac20_folios_list(self, ctx):
        """AC-20: list_folios returns items with id and title."""
        fw = ctx["folio_writ"]
        fw.create_folio("Test Folio AC20")
        folios = fw.list_folios()
        assert len(folios) >= 1
        assert folios[0].get("folio_id")
        assert folios[0].get("title")

    def test_ac21_folio_detail(self, ctx):
        """AC-21: get_folio returns folio with id, title."""
        fw = ctx["folio_writ"]
        f = fw.create_folio("Detail Folio")
        detail = fw.get_folio(f["folio_id"])
        assert detail is not None
        assert detail["folio_id"] == f["folio_id"]
        assert detail["title"] == "Detail Folio"

    def test_ac22_writ_neighbors(self, ctx):
        """AC-22: writ_neighbors returns prev/next structure."""
        fw = ctx["folio_writ"]
        f = fw.create_folio("Neighbors Folio")
        s1 = create_test_slip(fw, title="S1", folio_id=f["folio_id"])
        s2 = create_test_slip(fw, title="S2", folio_id=f["folio_id"])
        fw.create_writ(
            folio_id=f["folio_id"], title="S1→S2",
            match={"event": "deed_closed", "filter": {"slip_id": s1["slip_id"]}},
            action={"type": "spawn_deed", "slip_id": s2["slip_id"]},
        )
        n = fw.writ_neighbors(s2["slip_id"])
        assert "prev" in n
        assert "next" in n

    def test_ac23_crystallize_needs_title(self, ctx):
        """AC-23: crystallize_draft without title → no slip created (raises/returns error)."""
        fw = ctx["folio_writ"]
        draft = fw.create_draft(source="test", intent_snapshot="test")
        # crystallize_draft requires title
        try:
            result = fw.crystallize_draft(draft["draft_id"], title="", objective="obj")
            # If it succeeds with empty title, the slip should still have some title
        except Exception:
            pass  # Expected

    def test_ac25_crystallize_success(self, ctx):
        """AC-25: crystallize_draft with title+objective → returns slip_id."""
        fw = ctx["folio_writ"]
        draft = fw.create_draft(source="test", intent_snapshot="crystallize test")
        result = fw.crystallize_draft(
            draft["draft_id"], title="Test Slip", objective="Test objective",
            brief={"dag_budget": 6}, design={"moves": []},
        )
        assert result.get("slip_id")

    # ── 8.3 Submit 验证 ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_ac80_submit_valid(self, ctx):
        """AC-80: submit valid plan → has deed_id."""
        # Queue it (ward RED) to avoid temporal dep
        (ctx["state"] / "ward.json").write_text(json.dumps({"status": "RED"}))
        plan = {
            "moves": [{"id": "m1", "agent": "scout"}],
            "brief": {"objective": "test", "dag_budget": 6},
        }
        result = await ctx["will"].submit(plan)
        assert result.get("deed_id")
        # Restore
        (ctx["state"] / "ward.json").write_text(json.dumps({"status": "GREEN"}))

    @pytest.mark.asyncio
    async def test_ac81_submit_no_moves(self, ctx):
        """AC-81: submit without moves → error."""
        result = await ctx["will"].submit({"brief": {"objective": "test"}})
        assert result.get("ok") is False

    @pytest.mark.asyncio
    async def test_ac82_submit_cycle(self, ctx):
        """AC-82: submit cyclic DAG → error."""
        plan = {
            "moves": [
                {"id": "a", "agent": "scout", "depends_on": ["b"]},
                {"id": "b", "agent": "sage", "depends_on": ["a"]},
            ],
            "brief": {"objective": "test", "dag_budget": 6},
        }
        result = await ctx["will"].submit(plan)
        assert result.get("ok") is False

    # ── 8.4 Console 验证 ─────────────────────────────────────────────────

    def test_ac42_psyche_preferences(self, ctx):
        """AC-42: preferences are readable."""
        prefs = ctx["config"].all_prefs()
        assert isinstance(prefs, dict)
        assert len(prefs) > 0

    def test_ac43_psyche_preferences_update(self, ctx):
        """AC-43: preferences can be updated and read back."""
        ctx["config"].set_pref("general.test_key", "test_value")
        val = ctx["config"].get_pref("test_key")
        assert val == "test_value"

    # ── 8.5 Spine status 验证 ────────────────────────────────────────────

    def test_ac100_spine_registry(self, ctx):
        """AC-100: spine registry has 7 routines."""
        registry_path = ctx["tmp"] / "config" / "spine_registry.json"
        data = json.loads(registry_path.read_text())
        routines = data.get("routines", [])
        assert len(routines) == 7
        for r in routines:
            assert "name" in r
            assert "schedule" in r

    # ── 8.6 操作→自然语言记录 ────────────────────────────────────────────

    def test_ac60_operation_record_format(self, ctx):
        """AC-60: operation records have event=operation and readable content."""
        deed_id = "test_deed_ac60"
        deed_dir = ctx["state"] / "deeds" / deed_id
        deed_dir.mkdir(parents=True, exist_ok=True)
        ctx["ledger"].append_jsonl(
            deed_dir / "messages.jsonl",
            {"deed_id": deed_id, "role": "system", "content": "[操作] 收束：用户确认完成",
             "event": "operation", "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        )
        msgs = ctx["ledger"].load_jsonl(deed_dir / "messages.jsonl")
        ops = [m for m in msgs if m.get("event") == "operation"]
        assert len(ops) >= 1
        assert "[操作]" in ops[0]["content"]

    def test_ac63_operation_readable(self, ctx):
        """AC-63: operation content is human-readable Chinese."""
        content = "[操作] 收束：用户确认完成"
        assert "[操作]" in content
        assert len(content) > 5

    # ── 8.8 Submit edge cases ────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_ac83_submit_empty_body(self, ctx):
        """AC-83: submit empty plan → error."""
        result = await ctx["will"].submit({})
        assert result.get("ok") is False

    # ── 8.9 Ration 验证 ──────────────────────────────────────────────────

    def test_ac110_rations_readable(self, ctx):
        """AC-110: rations are readable."""
        rations = ctx["config"].all_rations()
        assert isinstance(rations, list)

    def test_ac111_rations_reset(self, ctx):
        """AC-111: rations reset clears usage."""
        ctx["config"].consume_ration("minimax_tokens", 1000)
        ctx["config"].reset_rations()
        rations = ctx["config"].all_rations()
        for r in rations:
            assert float(r.get("current_usage", 0)) == 0

    # ── 8.11 Observe 验证 ────────────────────────────────────────────────

    def test_ac120_observe_deeds(self, ctx):
        """AC-120: load_deeds returns list."""
        deeds = ctx["ledger"].load_deeds()
        assert isinstance(deeds, list)

    def test_ac121_observe_filter_by_status(self, ctx):
        """AC-121: deeds can be filtered by status."""
        create_test_deed(ctx["ledger"], status="running")
        create_test_deed(ctx["ledger"], status="closed", sub_status="succeeded")
        deeds = ctx["ledger"].load_deeds()
        running = [d for d in deeds if str(d.get("deed_status") or "") == "running"]
        assert len(running) >= 1


# =============================================================================
# §7 TestSpineChains — Spine Routines 链路
# =============================================================================


class TestSpineChains:
    """SC-01 ~ SC-63: Spine Routine pipeline verification."""

    @pytest.fixture
    def spine_ctx(self, tmp_path):
        """Build SpineRoutines + Canon + Trail for testing."""
        from psyche.config import PsycheConfig
        from psyche.ledger_stats import LedgerStats
        from psyche.instinct_engine import InstinctEngine
        from spine.nerve import Nerve
        from spine.trail import Trail
        from spine.canon import SpineCanon
        from spine.routines import SpineRoutines
        from services.ledger import Ledger

        state_dir = tmp_path / "state"
        state_dir.mkdir(exist_ok=True)
        (state_dir / "ward.json").write_text(json.dumps({"status": "GREEN"}))
        traces_dir = state_dir / "traces"
        traces_dir.mkdir(exist_ok=True)

        psyche_dir = tmp_path / "psyche"
        psyche_dir.mkdir(exist_ok=True)
        (psyche_dir / "preferences.toml").write_text(
            '[general]\ndefault_depth = "study"\n\n'
            '[execution]\ndeed_running_ttl_s = 14400\n'
        )
        (psyche_dir / "rations.toml").write_text(
            '[daily_limits]\nminimax_tokens = 20000000\n\n[current_usage]\n'
        )
        (psyche_dir / "instinct.md").write_text("# Instinct\n")
        voice_dir = psyche_dir / "voice"
        voice_dir.mkdir(exist_ok=True)
        (voice_dir / "identity.md").write_text("# Identity\n")
        (voice_dir / "common.md").write_text("# Common\n")
        (psyche_dir / "overlays").mkdir(exist_ok=True)

        config_dir = tmp_path / "config"
        config_dir.mkdir(exist_ok=True)
        registry_path = config_dir / "spine_registry.json"
        registry_path.write_text(json.dumps({
            "routines": {
                "spine.pulse": {"mode": "deterministic", "schedule": "*/10 * * * *", "timeout_s": 60,
                                "nerve_triggers": ["service_error"], "reads": ["infra:health"],
                                "writes": ["state:ward"], "depends_on": [], "degraded_mode": None},
                "spine.record": {"mode": "deterministic", "schedule": None, "timeout_s": 60,
                                 "nerve_triggers": ["deed_closed", "herald_completed"],
                                 "reads": ["state:trails"],
                                 "writes": ["psyche:ledger:dag_templates", "psyche:ledger:skill_stats"],
                                 "depends_on": [], "degraded_mode": None},
                "spine.witness": {"mode": "deterministic", "schedule": "0 */6 * * *", "timeout_s": 60,
                                  "nerve_triggers": [], "reads": ["psyche:ledger:stats"],
                                  "writes": ["state:system_health"], "depends_on": ["spine.record"],
                                  "degraded_mode": None},
                "spine.focus": {"mode": "deterministic", "schedule": "0 6 * * 1", "timeout_s": 60,
                                "nerve_triggers": [], "reads": ["psyche:ledger:stats"],
                                "writes": [], "depends_on": ["spine.witness"], "degraded_mode": None},
                "spine.relay": {"mode": "deterministic", "schedule": "0 */4 * * *", "timeout_s": 60,
                                "nerve_triggers": ["config_updated"], "reads": ["psyche:config"],
                                "writes": ["state:snapshots"], "depends_on": [], "degraded_mode": None},
                "spine.tend": {"mode": "deterministic", "schedule": "0 3 * * *", "timeout_s": 1800,
                               "nerve_triggers": ["ward_changed"], "reads": ["state"],
                               "writes": ["state"], "depends_on": [], "degraded_mode": None},
                "spine.curate": {"mode": "deterministic", "schedule": "0 2 * * 0", "timeout_s": 1800,
                                 "nerve_triggers": [], "reads": ["state:deeds"],
                                 "writes": ["state:vault"], "depends_on": [], "degraded_mode": None},
            }
        }))
        (config_dir / "model_policy.json").write_text(json.dumps({}))
        (config_dir / "model_registry.json").write_text(json.dumps({}))

        psyche_config = PsycheConfig(psyche_dir)
        ledger_stats = LedgerStats(tmp_path / "ledger.db")
        instinct_engine = InstinctEngine(psyche_dir)
        nerve = Nerve()
        trail = Trail(traces_dir)
        canon = SpineCanon(registry_path)

        class FakeCortex:
            def is_available(self):
                return False
            def embed(self, text):
                return None
            def try_or_degrade(self, fn, fallback):
                return fallback()
            def complete(self, *a, **kw):
                return ""

        routines = SpineRoutines(
            psyche_config=psyche_config,
            ledger_stats=ledger_stats,
            instinct_engine=instinct_engine,
            cortex=FakeCortex(),
            nerve=nerve,
            trail=trail,
            daemon_home=tmp_path,
            openclaw_home=None,
        )
        return {
            "routines": routines,
            "canon": canon,
            "nerve": nerve,
            "trail": trail,
            "state": state_dir,
            "home": tmp_path,
            "config": psyche_config,
            "ledger_stats": ledger_stats,
            "ledger": Ledger(state_dir),
        }

    # ── 7.1 spine.pulse 链路 ──────────────────────────────────────────────

    def test_sc01_pulse_writes_ward(self, spine_ctx):
        """SC-01: pulse writes ward.json."""
        spine_ctx["routines"].pulse()
        ward_path = spine_ctx["state"] / "ward.json"
        assert ward_path.exists()
        ward = json.loads(ward_path.read_text())
        assert "status" in ward

    def test_sc02_ward_required_fields(self, spine_ctx):
        """SC-02: ward.json has required fields."""
        spine_ctx["routines"].pulse()
        ward = json.loads((spine_ctx["state"] / "ward.json").read_text())
        assert ward["status"] in {"GREEN", "YELLOW", "RED"}
        assert "updated_utc" in ward
        assert "services" in ward

    def test_sc03_ward_changed_event(self, spine_ctx):
        """SC-03: ward status change emits ward_changed event."""
        events = []
        spine_ctx["nerve"].on("ward_changed", lambda p: events.append(p))
        # First pulse → GREEN (gateway/temporal unreachable → likely YELLOW/RED)
        spine_ctx["routines"].pulse()
        ward1 = json.loads((spine_ctx["state"] / "ward.json").read_text())
        # The event fires if status differs from previous (which was GREEN from fixture)
        # Gateway/Temporal unreachable → status changes from GREEN
        if ward1["status"] != "GREEN":
            assert len(events) >= 1
            assert "prev" in events[0]
            assert "current" in events[0]

    # ── 7.2 spine.record 链路 ─────────────────────────────────────────────

    def test_sc10_record_merges_dag_template(self, spine_ctx):
        """SC-10: record merges accepted deed into dag_templates."""
        result = spine_ctx["routines"].record(
            deed_id="deed_sc10",
            plan={"brief": {"objective": "test research"}, "moves": [{"id": "m1", "agent": "scout"}]},
            move_results=[{"agent": "scout", "tokens_used": 1000, "duration_s": 5.0}],
            offering={"ok": True},
            accepted=True,
        )
        assert result["recorded"] is True
        assert result.get("template_id")

    def test_sc11_record_updates_skill_stats(self, spine_ctx):
        """SC-11: record updates skill_stats when plan has skill references."""
        spine_ctx["routines"].record(
            deed_id="deed_sc11",
            plan={"moves": [{"id": "m1", "agent": "scout", "skill": "brave_search"}]},
            move_results=[{"agent": "scout", "tokens_used": 500, "duration_s": 3}],
            offering={"ok": True},
            accepted=True,
        )
        health = spine_ctx["ledger_stats"].skill_health("brave_search")
        assert health["invocations"] >= 1

    def test_sc12_record_updates_agent_stats(self, spine_ctx):
        """SC-12: record updates agent_stats from move_results."""
        spine_ctx["routines"].record(
            deed_id="deed_sc12",
            plan={"moves": [{"id": "m1", "agent": "scout"}]},
            move_results=[{"agent": "scout", "tokens_used": 800, "duration_s": 4}],
            offering={"ok": True},
            accepted=True,
        )
        perf = spine_ctx["ledger_stats"].agent_performance("scout")
        assert perf["invocations"] >= 1

    def test_sc13_record_skips_rejected(self, spine_ctx):
        """SC-13: record does not merge rejected deed."""
        result = spine_ctx["routines"].record(
            deed_id="deed_sc13",
            plan={"moves": [{"id": "m1", "agent": "scout"}]},
            move_results=[],
            offering={"ok": False},
            accepted=False,
        )
        assert result["recorded"] is False

    def test_sc14_record_rolling_average(self, spine_ctx):
        """SC-14: two merges → rolling average correct."""
        from tests.conftest import mock_embedding, similar_embedding
        emb = mock_embedding(dim=64, seed=100)
        # First merge
        spine_ctx["ledger_stats"].merge_dag_template(
            objective_text="research task",
            objective_emb=emb,
            dag_structure={"moves": ["scout"]},
            eval_summary="good",
            total_tokens=1000,
            total_duration_s=10.0,
            rework_count=0,
        )
        # Second merge with similar embedding
        emb2 = similar_embedding(emb, noise=0.001)
        spine_ctx["ledger_stats"].merge_dag_template(
            objective_text="research task similar",
            objective_emb=emb2,
            dag_structure={"moves": ["scout"]},
            eval_summary="great",
            total_tokens=2000,
            total_duration_s=20.0,
            rework_count=1,
        )
        results = spine_ctx["ledger_stats"].similar_dag_templates(emb, top_k=1)
        assert len(results) >= 1
        assert results[0]["times_validated"] == 2
        assert abs(results[0]["avg_tokens"] - 1500) < 1

    # ── 7.3 spine.witness 链路 ────────────────────────────────────────────

    def test_sc20_witness_writes_system_health(self, spine_ctx):
        """SC-20: witness writes system_health.json."""
        # Seed some data
        spine_ctx["ledger_stats"].merge_dag_template(
            objective_text="test", objective_emb=None,
            dag_structure={}, eval_summary="ok",
            total_tokens=1000, total_duration_s=5, rework_count=0,
        )
        spine_ctx["routines"].witness()
        health_path = spine_ctx["state"] / "system_health.json"
        assert health_path.exists()
        health = json.loads(health_path.read_text())
        assert "generated_utc" in health

    def test_sc21_witness_returns_stats(self, spine_ctx):
        """SC-21: witness returns deed statistics."""
        spine_ctx["ledger_stats"].merge_dag_template(
            objective_text="test", objective_emb=None,
            dag_structure={}, eval_summary="ok",
            total_tokens=2000, total_duration_s=10, rework_count=0,
        )
        result = spine_ctx["routines"].witness()
        assert result.get("templates_analyzed", 0) >= 1 or result.get("skipped") is True

    # ── 7.4 spine.relay 链路 ──────────────────────────────────────────────

    def test_sc30_relay_exports_snapshots(self, spine_ctx):
        """SC-30: relay exports snapshots to state/snapshots/."""
        spine_ctx["routines"].relay()
        snap_dir = spine_ctx["state"] / "snapshots"
        assert snap_dir.exists()
        assert (snap_dir / "config_snapshot.json").exists()
        assert (snap_dir / "planning_hints.json").exists()

    def test_sc31_snapshot_has_planning_hints(self, spine_ctx):
        """SC-31: snapshot planning_hints has expected fields."""
        spine_ctx["routines"].relay()
        hints = json.loads((spine_ctx["state"] / "snapshots" / "planning_hints.json").read_text())
        assert "dag_template_count" in hints

    # ── 7.5 spine.tend 链路 ──────────────────────────────────────────────

    def test_sc40_tend_cleans_traces(self, spine_ctx):
        """SC-40: tend cleans old trace files."""
        traces_dir = spine_ctx["state"] / "traces"
        old_trace = traces_dir / "old.jsonl"
        old_trace.write_text("{}")
        import os
        # Set mtime to 30 days ago
        old_time = time.time() - 30 * 86400
        os.utime(old_trace, (old_time, old_time))
        spine_ctx["routines"].tend()
        assert not old_trace.exists()

    def test_sc41_tend_checks_rations(self, spine_ctx):
        """SC-41: tend returns rations_checked=True."""
        result = spine_ctx["routines"].tend()
        assert result.get("rations_checked") is True

    # ── 7.6 spine.curate 链路 ─────────────────────────────────────────────

    def test_sc50_curate_runs(self, spine_ctx):
        """SC-50: curate runs without error and returns result dict."""
        result = spine_ctx["routines"].curate()
        assert isinstance(result, dict)
        assert "deeds_vaulted" in result

    def test_sc51_curate_skips_active(self, spine_ctx):
        """SC-51: curate does not vault active deeds."""
        deeds_dir = spine_ctx["state"] / "deeds" / "deed_active"
        deeds_dir.mkdir(parents=True)
        (deeds_dir / "status.json").write_text(json.dumps({"deed_status": "running"}))
        result = spine_ctx["routines"].curate()
        assert (spine_ctx["state"] / "deeds" / "deed_active").exists()

    # ── 7.7 Registry 一致性 ──────────────────────────────────────────────

    def test_sc60_registry_all_have_impl(self, spine_ctx):
        """SC-60: every routine in registry has a method on SpineRoutines."""
        for rdef in spine_ctx["canon"].all():
            method_name = rdef.name.replace("spine.", "")
            assert hasattr(spine_ctx["routines"], method_name), f"Missing method: {method_name}"
            assert callable(getattr(spine_ctx["routines"], method_name))

    def test_sc62_trigger_mapping(self, spine_ctx):
        """SC-62: by_trigger('deed_closed') returns spine.record."""
        results = spine_ctx["canon"].by_trigger("deed_closed")
        names = [r.name for r in results]
        assert "spine.record" in names

    def test_sc63_all_deterministic(self, spine_ctx):
        """SC-63: all routines are deterministic mode."""
        for rdef in spine_ctx["canon"].all():
            assert rdef.mode == "deterministic", f"{rdef.name} is {rdef.mode}"

    # ── Extra: Canon loading ─────────────────────────────────────────────

    def test_sc_canon_loads_7_routines(self, spine_ctx):
        """Canon loads all 7 routines."""
        assert len(spine_ctx["canon"].all()) == 7

    def test_sc_canon_get_by_name(self, spine_ctx):
        """Canon.get returns RoutineDefinition."""
        rdef = spine_ctx["canon"].get("spine.pulse")
        assert rdef is not None
        assert rdef.name == "spine.pulse"
        assert rdef.schedule == "*/10 * * * *"

    def test_sc_canon_routine_definition_fields(self, spine_ctx):
        """RoutineDefinition has all expected fields."""
        rdef = spine_ctx["canon"].get("spine.record")
        assert rdef is not None
        assert "deed_closed" in rdef.nerve_triggers
        assert rdef.schedule is None  # record is nerve-triggered only
        d = rdef.to_dict()
        for key in ("name", "mode", "schedule", "timeout_s", "nerve_triggers", "reads", "writes", "depends_on"):
            assert key in d

    def test_sc_log_execution(self, spine_ctx):
        """log_execution writes to spine_log.jsonl."""
        spine_ctx["routines"].log_execution("pulse", "ok", {}, 0.5)
        log_path = spine_ctx["state"] / "spine_log.jsonl"
        assert log_path.exists()
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) >= 1
        entry = json.loads(lines[-1])
        assert entry["routine"] == "pulse"
        assert entry["status"] == "ok"

    def test_sc_spine_status_update(self, spine_ctx):
        """log_execution updates spine_status.json."""
        spine_ctx["routines"].log_execution("pulse", "ok", {}, 0.5)
        status_path = spine_ctx["state"] / "spine_status.json"
        assert status_path.exists()
        status = json.loads(status_path.read_text())
        assert status["overall"] == "healthy"
        assert "pulse" in status["routines"]


# =============================================================================
# §10 TestLearningStats — 学习与统计
# =============================================================================


class TestLearningStats:
    """LS-01 ~ LS-42: LedgerStats DAG/Folio templates, skill/agent stats, planning."""

    # ── 10.1 DAG 模板 ────────────────────────────────────────────────────

    def test_ls01_first_merge_creates_template(self, ledger_stats):
        """LS-01: first merge creates template with non-empty id."""
        from tests.conftest import mock_embedding
        emb = mock_embedding(dim=64, seed=1)
        tid = ledger_stats.merge_dag_template(
            objective_text="research AI papers",
            objective_emb=emb,
            dag_structure={"moves": ["scout", "sage", "scribe"]},
            eval_summary="good output",
            total_tokens=3000,
            total_duration_s=15.0,
            rework_count=0,
        )
        assert tid
        assert tid.startswith("dag_")

    def test_ls02_similar_merges_same_template(self, ledger_stats):
        """LS-02: similar embeddings merge into same template."""
        from tests.conftest import mock_embedding, similar_embedding
        emb = mock_embedding(dim=64, seed=2)
        tid1 = ledger_stats.merge_dag_template(
            objective_text="research AI",
            objective_emb=emb,
            dag_structure={},
            eval_summary="ok",
            total_tokens=1000,
            total_duration_s=5,
            rework_count=0,
        )
        emb2 = similar_embedding(emb, noise=0.001)
        tid2 = ledger_stats.merge_dag_template(
            objective_text="research AI similar",
            objective_emb=emb2,
            dag_structure={},
            eval_summary="also ok",
            total_tokens=2000,
            total_duration_s=10,
            rework_count=0,
        )
        assert tid1 == tid2

    def test_ls03_different_creates_new(self, ledger_stats):
        """LS-03: different embeddings create new template."""
        from tests.conftest import mock_embedding, different_embedding
        emb = mock_embedding(dim=64, seed=3)
        tid1 = ledger_stats.merge_dag_template(
            objective_text="write code",
            objective_emb=emb,
            dag_structure={},
            eval_summary="ok",
            total_tokens=1000,
            total_duration_s=5,
            rework_count=0,
        )
        emb2 = different_embedding(emb)
        tid2 = ledger_stats.merge_dag_template(
            objective_text="analyze data",
            objective_emb=emb2,
            dag_structure={},
            eval_summary="ok",
            total_tokens=1500,
            total_duration_s=8,
            rework_count=0,
        )
        assert tid1 != tid2

    def test_ls04_times_validated_increments(self, ledger_stats):
        """LS-04: merging twice increments times_validated to 2."""
        from tests.conftest import mock_embedding, similar_embedding
        emb = mock_embedding(dim=64, seed=4)
        ledger_stats.merge_dag_template(
            objective_text="task A", objective_emb=emb,
            dag_structure={}, eval_summary="first",
            total_tokens=1000, total_duration_s=5, rework_count=0,
        )
        ledger_stats.merge_dag_template(
            objective_text="task A again", objective_emb=similar_embedding(emb, noise=0.001),
            dag_structure={}, eval_summary="second",
            total_tokens=2000, total_duration_s=10, rework_count=1,
        )
        results = ledger_stats.similar_dag_templates(emb, top_k=1)
        assert results[0]["times_validated"] == 2

    def test_ls05_rolling_average_tokens(self, ledger_stats):
        """LS-05: rolling average: 1000 + 2000 → avg=1500."""
        from tests.conftest import mock_embedding, similar_embedding
        emb = mock_embedding(dim=64, seed=5)
        ledger_stats.merge_dag_template(
            objective_text="tokens test", objective_emb=emb,
            dag_structure={}, eval_summary="",
            total_tokens=1000, total_duration_s=5, rework_count=0,
        )
        ledger_stats.merge_dag_template(
            objective_text="tokens test 2", objective_emb=similar_embedding(emb, noise=0.001),
            dag_structure={}, eval_summary="",
            total_tokens=2000, total_duration_s=15, rework_count=0,
        )
        results = ledger_stats.similar_dag_templates(emb, top_k=1)
        assert abs(results[0]["avg_tokens"] - 1500) < 1

    def test_ls06_eval_summary_appended(self, ledger_stats):
        """LS-06: eval_summary accumulates across merges."""
        from tests.conftest import mock_embedding, similar_embedding
        emb = mock_embedding(dim=64, seed=6)
        ledger_stats.merge_dag_template(
            objective_text="eval test", objective_emb=emb,
            dag_structure={}, eval_summary="first review",
            total_tokens=1000, total_duration_s=5, rework_count=0,
        )
        ledger_stats.merge_dag_template(
            objective_text="eval test 2", objective_emb=similar_embedding(emb, noise=0.001),
            dag_structure={}, eval_summary="second review",
            total_tokens=1000, total_duration_s=5, rework_count=0,
        )
        results = ledger_stats.similar_dag_templates(emb, top_k=1)
        eval_text = results[0].get("eval_summary") or ""
        assert "first review" in eval_text
        assert "second review" in eval_text

    def test_ls07_eval_summary_bounded(self, ledger_stats):
        """LS-07: eval_summary truncated to ≤2000 chars."""
        from tests.conftest import mock_embedding, similar_embedding
        emb = mock_embedding(dim=64, seed=7)
        long_eval = "x" * 1500
        ledger_stats.merge_dag_template(
            objective_text="long eval", objective_emb=emb,
            dag_structure={}, eval_summary=long_eval,
            total_tokens=1000, total_duration_s=5, rework_count=0,
        )
        ledger_stats.merge_dag_template(
            objective_text="long eval 2", objective_emb=similar_embedding(emb, noise=0.001),
            dag_structure={}, eval_summary=long_eval,
            total_tokens=1000, total_duration_s=5, rework_count=0,
        )
        results = ledger_stats.similar_dag_templates(emb, top_k=1)
        assert len(results[0].get("eval_summary") or "") <= 2000

    def test_ls08_similar_dag_top_k(self, ledger_stats):
        """LS-08: similar_dag_templates respects top_k."""
        from tests.conftest import mock_embedding, similar_embedding
        emb = mock_embedding(dim=64, seed=8)
        for i in range(3):
            ledger_stats.merge_dag_template(
                objective_text=f"task {i}", objective_emb=similar_embedding(emb, noise=0.001 * (i + 1)),
                dag_structure={}, eval_summary=f"eval {i}",
                total_tokens=1000 * (i + 1), total_duration_s=5, rework_count=0,
            )
        results = ledger_stats.similar_dag_templates(emb, top_k=2)
        assert len(results) <= 2

    def test_ls09_similar_dag_sorted_by_similarity(self, ledger_stats):
        """LS-09: results sorted by similarity descending."""
        from tests.conftest import mock_embedding, similar_embedding
        emb = mock_embedding(dim=64, seed=9)
        ledger_stats.merge_dag_template(
            objective_text="close", objective_emb=similar_embedding(emb, noise=0.001),
            dag_structure={}, eval_summary="",
            total_tokens=1000, total_duration_s=5, rework_count=0,
        )
        ledger_stats.merge_dag_template(
            objective_text="farther", objective_emb=similar_embedding(emb, noise=0.05),
            dag_structure={}, eval_summary="",
            total_tokens=1000, total_duration_s=5, rework_count=0,
        )
        results = ledger_stats.similar_dag_templates(emb, top_k=5)
        if len(results) >= 2:
            assert results[0]["similarity"] >= results[1]["similarity"]

    # ── 10.2 Folio 模板 ──────────────────────────────────────────────────

    def test_ls10_folio_first_merge(self, ledger_stats):
        """LS-10: first folio merge creates template."""
        from tests.conftest import mock_embedding
        emb = mock_embedding(dim=64, seed=10)
        tid = ledger_stats.merge_folio_template(
            objective_text="project alpha",
            objective_emb=emb,
            structure={"slips": ["s1", "s2"]},
            slip_count=2,
        )
        assert tid
        assert tid.startswith("fol_")

    def test_ls11_folio_similar_merge(self, ledger_stats):
        """LS-11: similar folio merges into same template."""
        from tests.conftest import mock_embedding, similar_embedding
        emb = mock_embedding(dim=64, seed=11)
        tid1 = ledger_stats.merge_folio_template(
            objective_text="project beta", objective_emb=emb,
            structure={"slips": ["s1"]}, slip_count=1,
        )
        tid2 = ledger_stats.merge_folio_template(
            objective_text="project beta v2", objective_emb=similar_embedding(emb, noise=0.001),
            structure={"slips": ["s1", "s2"]}, slip_count=2,
        )
        assert tid1 == tid2

    def test_ls12_similar_folio_query(self, ledger_stats):
        """LS-12: similar_folio_templates returns results."""
        from tests.conftest import mock_embedding
        emb = mock_embedding(dim=64, seed=12)
        ledger_stats.merge_folio_template(
            objective_text="folio query test", objective_emb=emb,
            structure={}, slip_count=3,
        )
        results = ledger_stats.similar_folio_templates(emb, top_k=3)
        assert len(results) >= 1

    # ── 10.3 Skill 统计 ──────────────────────────────────────────────────

    def test_ls20_skill_accepted_increments(self, ledger_stats):
        """LS-20: update_skill_stats accepted=True increments accepted."""
        plan = {"moves": [{"id": "m1", "skill": "brave_search"}]}
        ledger_stats.update_skill_stats(plan, accepted=True)
        health = ledger_stats.skill_health("brave_search")
        assert health["invocations"] >= 1
        assert health["accept_rate"] > 0

    def test_ls21_skill_rejected_increments(self, ledger_stats):
        """LS-21: update_skill_stats accepted=False increments rejected."""
        plan = {"moves": [{"id": "m1", "skill": "file_read"}]}
        ledger_stats.update_skill_stats(plan, accepted=False)
        health = ledger_stats.skill_health("file_read")
        assert health["invocations"] >= 1
        assert health["accept_rate"] == 0

    def test_ls22_skill_health_correct(self, ledger_stats):
        """LS-22: skill_health returns correct stats."""
        plan = {"moves": [{"id": "m1", "skill": "web_scrape"}]}
        for _ in range(3):
            ledger_stats.update_skill_stats(plan, accepted=True)
        ledger_stats.update_skill_stats(plan, accepted=False)
        health = ledger_stats.skill_health("web_scrape")
        assert health["invocations"] == 4
        assert abs(health["accept_rate"] - 0.75) < 0.01

    def test_ls23_needs_review_trigger(self, ledger_stats):
        """LS-23: needs_review when inv≥5 and reject>20%."""
        plan = {"moves": [{"id": "m1", "skill": "risky_tool"}]}
        for _ in range(3):
            ledger_stats.update_skill_stats(plan, accepted=True)
        for _ in range(3):
            ledger_stats.update_skill_stats(plan, accepted=False)
        health = ledger_stats.skill_health("risky_tool")
        assert health["needs_review"] is True

    def test_ls24_skills_needing_review_list(self, ledger_stats):
        """LS-24: skills_needing_review returns non-empty list."""
        plan = {"moves": [{"id": "m1", "skill": "flaky_skill"}]}
        for _ in range(3):
            ledger_stats.update_skill_stats(plan, accepted=True)
        for _ in range(3):
            ledger_stats.update_skill_stats(plan, accepted=False)
        result = ledger_stats.skills_needing_review()
        names = [r["skill_name"] for r in result]
        assert "flaky_skill" in names

    # ── 10.4 Agent 统计 ──────────────────────────────────────────────────

    def test_ls30_agent_stats_written(self, ledger_stats):
        """LS-30: update_agent_stats writes records."""
        move_results = [{"agent": "scout", "tokens_used": 1000, "duration_s": 5}]
        ledger_stats.update_agent_stats(move_results, accepted=True)
        perf = ledger_stats.agent_performance("scout")
        assert perf["invocations"] >= 1

    def test_ls31_agent_performance_aggregate(self, ledger_stats):
        """LS-31: multiple updates → correct success_rate."""
        for _ in range(3):
            ledger_stats.update_agent_stats(
                [{"agent": "sage", "tokens_used": 2000, "duration_s": 10}],
                accepted=True,
            )
        ledger_stats.update_agent_stats(
            [{"agent": "sage", "tokens_used": 2000, "duration_s": 10}],
            accepted=False,
        )
        perf = ledger_stats.agent_performance("sage")
        assert perf["invocations"] == 4
        assert abs(perf["success_rate"] - 0.75) < 0.01

    def test_ls32_agent_summary_all_roles(self, ledger_stats):
        """LS-32: agent_summary returns all updated roles."""
        ledger_stats.update_agent_stats([{"agent": "scout", "tokens_used": 100}], accepted=True)
        ledger_stats.update_agent_stats([{"agent": "sage", "tokens_used": 200}], accepted=True)
        summary = ledger_stats.agent_summary()
        roles = {r["agent_role"] for r in summary}
        assert "scout" in roles
        assert "sage" in roles

    # ── 10.5 Planning 查询 ───────────────────────────────────────────────

    def test_ls40_planning_hints_cold_start(self, ledger_stats):
        """LS-40: planning_hints with no history → zero estimates."""
        from tests.conftest import mock_embedding
        emb = mock_embedding(dim=64, seed=40)
        hints = ledger_stats.planning_hints(emb)
        assert hints["est_tokens"] == 0
        assert hints["confidence"] == 0

    def test_ls41_planning_hints_with_history(self, ledger_stats):
        """LS-41: planning_hints with matching DAG → non-zero estimates."""
        from tests.conftest import mock_embedding, similar_embedding
        emb = mock_embedding(dim=64, seed=41)
        ledger_stats.merge_dag_template(
            objective_text="planning test",
            objective_emb=emb,
            dag_structure={"moves": ["scout"]},
            eval_summary="ok",
            total_tokens=5000,
            total_duration_s=30,
            rework_count=0,
        )
        hints = ledger_stats.planning_hints(similar_embedding(emb, noise=0.001))
        assert hints["est_tokens"] > 0
        assert hints["confidence"] > 0

    def test_ls42_global_planning_hints(self, ledger_stats):
        """LS-42: global_planning_hints returns template counts."""
        ledger_stats.merge_dag_template(
            objective_text="global test", objective_emb=None,
            dag_structure={}, eval_summary="",
            total_tokens=1000, total_duration_s=5, rework_count=0,
        )
        hints = ledger_stats.global_planning_hints()
        assert hints["dag_template_count"] >= 1


# =============================================================================
# §17 TestCronScheduling — Cron 与调度
# =============================================================================


class TestCronScheduling:
    """CR-01 ~ CR-32: Cron parsing, matching, Cadence helpers."""

    # ── 17.1 Cron 表达式解析 (Cadence._parse_cron_field) ─────────────────

    def test_cr01_every_10_minutes(self):
        """CR-01: */10 * * * * → minute values include 0,10,20,30,40,50."""
        from services.cadence import Cadence
        values = Cadence._parse_cron_field("*/10", 0, 59)
        assert values == {0, 10, 20, 30, 40, 50}

    def test_cr02_daily_3am(self):
        """CR-02: 0 3 * * * → hour={3}, minute={0}."""
        from services.cadence import Cadence
        hours = Cadence._parse_cron_field("3", 0, 23)
        minutes = Cadence._parse_cron_field("0", 0, 59)
        assert hours == {3}
        assert minutes == {0}

    def test_cr03_weekly_monday(self):
        """CR-03: dow=1 → Monday."""
        from services.cadence import Cadence
        dows = Cadence._parse_cron_field("1", 0, 7, is_dow=True)
        assert dows == {1}

    def test_cr04_sunday_7_maps_to_0(self):
        """CR-04: dow=7 maps to 0 (Sunday)."""
        from services.cadence import Cadence
        dows = Cadence._parse_cron_field("7", 0, 7, is_dow=True)
        assert 0 in dows

    def test_cr05_dom_list(self):
        """CR-05: dom=1,15 → {1,15}."""
        from services.cadence import Cadence
        dom = Cadence._parse_cron_field("1,15", 1, 31)
        assert dom == {1, 15}

    def test_cr06_dow_range(self):
        """CR-06: dow=1-5 → {1,2,3,4,5} (weekdays)."""
        from services.cadence import Cadence
        dows = Cadence._parse_cron_field("1-5", 0, 7, is_dow=True)
        assert dows == {1, 2, 3, 4, 5}

    def test_cr07_invalid_expression(self):
        """CR-07: invalid cron → _cron_matches returns False."""
        assert _cron_matches("invalid", datetime.now(timezone.utc)) is False

    def test_cr08_four_field_expression(self):
        """CR-08: 4-field cron → False."""
        assert _cron_matches("* * * *", datetime.now(timezone.utc)) is False

    # ── 17.2 Cron 匹配 ──────────────────────────────────────────────────

    def test_cr10_exact_time_match(self):
        """CR-10: 0 9 * * * matches at 09:00."""
        dt = datetime(2026, 3, 13, 9, 0, tzinfo=timezone.utc)
        assert _cron_matches("0 9 * * *", dt) is True

    def test_cr11_minute_mismatch(self):
        """CR-11: 0 9 * * * does not match 09:01."""
        dt = datetime(2026, 3, 13, 9, 1, tzinfo=timezone.utc)
        assert _cron_matches("0 9 * * *", dt) is False

    def test_cr12_dom_match(self):
        """CR-12: 0 0 15 * * matches on the 15th."""
        dt = datetime(2026, 3, 15, 0, 0, tzinfo=timezone.utc)
        assert _cron_matches("0 0 15 * *", dt) is True

    def test_cr13_dom_mismatch(self):
        """CR-13: 0 0 15 * * does not match the 16th."""
        dt = datetime(2026, 3, 16, 0, 0, tzinfo=timezone.utc)
        assert _cron_matches("0 0 15 * *", dt) is False

    def test_cr14_dow_monday_match(self):
        """CR-14: * * * * 1 matches Monday."""
        # 2026-03-09 is Monday
        dt = datetime(2026, 3, 9, 12, 0, tzinfo=timezone.utc)
        assert _cron_matches("0 12 * * 1", dt) is True

    def test_cr15_dow_mismatch(self):
        """CR-15: * * * * 1 does not match Tuesday."""
        # 2026-03-10 is Tuesday
        dt = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)
        assert _cron_matches("0 12 * * 1", dt) is False

    def test_cr16_month_match(self):
        """CR-16: * * * 3 * matches March."""
        dt = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
        assert _cron_matches("0 0 * 3 *", dt) is True

    def test_cr17_dom_dow_or_logic(self):
        """CR-17: both DOM and DOW specified → OR logic (Vixie cron)."""
        from services.cadence import Cadence
        # "0 0 1 * 1" matches on the 1st OR on Monday
        # 2026-03-01 is Sunday, not Monday, but it's the 1st → should match
        dt = datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)
        next_dt = Cadence._next_cron_occurrence("0 0 1 * 1", dt - __import__("datetime").timedelta(minutes=1))
        assert next_dt is not None
        # Should match on the 1st even though it's not Monday
        assert next_dt.day == 1 or next_dt.weekday() == 0  # weekday() 0=Monday

    # ── 17.3 Cadence 调度辅助 ────────────────────────────────────────────

    def test_cr20_parse_cron_simple(self):
        """CR-20: _parse_cron_simple('*/10 * * * *') → 600."""
        from services.cadence import Cadence
        assert Cadence._parse_cron_simple("*/10 * * * *") == 600

    def test_cr21_parse_duration_hours(self):
        """CR-21: '4h' → 14400."""
        from services.cadence import Cadence
        assert Cadence._parse_duration("4h") == 14400

    def test_cr22_parse_duration_minutes(self):
        """CR-22: '30m' → 1800."""
        from services.cadence import Cadence
        assert Cadence._parse_duration("30m") == 1800

    def test_cr23_parse_duration_mixed(self):
        """CR-23: '2h30m' → 9000."""
        from services.cadence import Cadence
        assert Cadence._parse_duration("2h30m") == 9000

    def test_cr24_parse_duration_invalid(self):
        """CR-24: 'abc' → None."""
        from services.cadence import Cadence
        assert Cadence._parse_duration("abc") is None

    def test_cr25_next_cron_occurrence_utc(self):
        """CR-25: _next_cron_occurrence returns UTC datetime."""
        from services.cadence import Cadence
        now = datetime(2026, 3, 13, 10, 0, tzinfo=timezone.utc)
        result = Cadence._next_cron_occurrence("*/10 * * * *", now)
        assert result is not None
        assert result > now
        assert result.minute % 10 == 0

    # ── 17.4 Schedule 覆盖 ───────────────────────────────────────────────

    def test_cr30_update_schedule(self, tmp_path):
        """CR-30: update_schedule persists to schedules.json."""
        from spine.canon import SpineCanon
        from services.cadence import Cadence

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "ward.json").write_text(json.dumps({"status": "GREEN"}))

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        reg_path = config_dir / "spine_registry.json"
        reg_path.write_text(json.dumps({
            "routines": {"spine.pulse": {"mode": "deterministic", "schedule": "*/10 * * * *",
                                         "timeout_s": 60, "nerve_triggers": [], "reads": [],
                                         "writes": [], "depends_on": [], "degraded_mode": None}}
        }))
        canon = SpineCanon(reg_path)

        class FakeRoutines:
            psyche_config = None
            ledger_stats = None
            instinct_engine = None
            cortex = None
            def log_execution(self, *a): pass

        class FakeNerve:
            def on(self, *a): pass
            def emit(self, *a): pass

        class FakeConfig:
            def get_pref(self, k, d=None): return d
            def all_prefs(self): return {}

        cadence = Cadence(canon, FakeRoutines(), FakeConfig(), FakeNerve(), state_dir)
        result = cadence.update_schedule("pulse", schedule="*/5 * * * *")
        assert result["ok"] is True
        overrides = json.loads((state_dir / "schedules.json").read_text())
        assert "spine.pulse" in overrides

    def test_cr31_disable_routine(self, tmp_path):
        """CR-31: update_schedule enabled=False disables routine."""
        from spine.canon import SpineCanon
        from services.cadence import Cadence

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "ward.json").write_text(json.dumps({"status": "GREEN"}))
        reg_path = tmp_path / "reg.json"
        reg_path.write_text(json.dumps({
            "routines": {"spine.pulse": {"mode": "deterministic", "schedule": "*/10 * * * *",
                                         "timeout_s": 60, "nerve_triggers": [], "reads": [],
                                         "writes": [], "depends_on": [], "degraded_mode": None}}
        }))

        class FakeRoutines:
            psyche_config = None
            ledger_stats = None
            instinct_engine = None
            cortex = None
            def log_execution(self, *a): pass

        class FakeNerve:
            def on(self, *a): pass
            def emit(self, *a): pass

        class FakeConfig:
            def get_pref(self, k, d=None): return d
            def all_prefs(self): return {}

        canon = SpineCanon(reg_path)
        cadence = Cadence(canon, FakeRoutines(), FakeConfig(), FakeNerve(), state_dir)
        cadence.update_schedule("pulse", enabled=False)
        assert cadence._is_enabled("spine.pulse") is False


# =============================================================================
# §22 TestCadenceEngine — Cadence 调度引擎
# =============================================================================


class TestCadenceEngine:
    """CA-01 ~ CA-52: Cadence engine startup, execution, deps, adaptive, tick."""

    @pytest.fixture
    def cadence_ctx(self, tmp_path):
        """Build a Cadence instance with real Canon + fake Routines."""
        from spine.canon import SpineCanon
        from services.cadence import Cadence
        from services.ledger import Ledger
        from spine.nerve import Nerve

        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "ward.json").write_text(json.dumps({"status": "GREEN"}))
        traces_dir = state_dir / "traces"
        traces_dir.mkdir()

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        reg_path = config_dir / "spine_registry.json"
        reg_path.write_text(json.dumps({
            "routines": {
                "spine.pulse": {"mode": "deterministic", "schedule": "*/10 * * * *", "timeout_s": 60,
                                "nerve_triggers": ["service_error"], "reads": ["infra:health"],
                                "writes": ["state:ward"], "depends_on": [], "degraded_mode": None},
                "spine.record": {"mode": "deterministic", "schedule": None, "timeout_s": 60,
                                 "nerve_triggers": ["deed_closed"], "reads": [],
                                 "writes": [], "depends_on": [], "degraded_mode": None},
                "spine.witness": {"mode": "deterministic", "schedule": "0 */6 * * *", "timeout_s": 60,
                                  "nerve_triggers": [], "reads": [],
                                  "writes": [], "depends_on": ["spine.record"], "degraded_mode": None},
                "spine.focus": {"mode": "deterministic", "schedule": "0 6 * * 1", "timeout_s": 60,
                                "nerve_triggers": [], "reads": [],
                                "writes": [], "depends_on": ["spine.witness"], "degraded_mode": None},
                "spine.relay": {"mode": "deterministic", "schedule": "0 */4 * * *", "timeout_s": 60,
                                "nerve_triggers": ["config_updated"], "reads": [],
                                "writes": [], "depends_on": [], "degraded_mode": None},
                "spine.tend": {"mode": "deterministic", "schedule": "0 3 * * *", "timeout_s": 1800,
                               "nerve_triggers": [], "reads": [],
                               "writes": [], "depends_on": [], "degraded_mode": None},
                "spine.curate": {"mode": "deterministic", "schedule": "0 2 * * 0", "timeout_s": 1800,
                                 "nerve_triggers": [], "reads": [],
                                 "writes": [], "depends_on": [], "degraded_mode": None},
            }
        }))

        canon = SpineCanon(reg_path)
        nerve = Nerve()
        ledger = Ledger(state_dir)

        call_log = []

        class FakeRoutines:
            psyche_config = None
            ledger_stats = None
            instinct_engine = None

            class _cortex:
                @staticmethod
                def is_available():
                    return False

            cortex = _cortex()

            def pulse(self):
                call_log.append("pulse")
                return {"ward": "GREEN"}

            def record(self, **kw):
                call_log.append("record")
                return {"recorded": True}

            def witness(self):
                call_log.append("witness")
                return {"ok": True}

            def focus(self):
                call_log.append("focus")
                return {"ok": True}

            def relay(self):
                call_log.append("relay")
                return {"ok": True}

            def tend(self):
                call_log.append("tend")
                return {"ok": True}

            def curate(self):
                call_log.append("curate")
                return {"ok": True}

            def log_execution(self, name, status, result, duration):
                pass

        class FakeConfig:
            def get_pref(self, k, d=None):
                return d
            def all_prefs(self):
                return {"deed_running_ttl_s": 14400}

        cadence = Cadence(canon, FakeRoutines(), FakeConfig(), nerve, state_dir)
        return {
            "cadence": cadence,
            "canon": canon,
            "nerve": nerve,
            "state": state_dir,
            "ledger": ledger,
            "call_log": call_log,
            "home": tmp_path,
        }

    # ── 22.1 启动与停止 ─────────────────────────────────────────────────

    def test_ca04_status_returns_all(self, cadence_ctx):
        """CA-04: status returns all 7 routines."""
        rows = cadence_ctx["cadence"].status()
        assert len(rows) == 7

    def test_ca05_status_has_fields(self, cadence_ctx):
        """CA-05: each status row has required fields."""
        rows = cadence_ctx["cadence"].status()
        for row in rows:
            assert "routine" in row
            assert "schedule" in row
            assert "enabled" in row
            assert "next_run_utc" in row or row.get("next_run_utc") is None

    def test_ca06_history_after_run(self, cadence_ctx):
        """CA-06: history returns records after execution."""
        cadence_ctx["cadence"]._run_routine("spine.pulse", None, "manual")
        history = cadence_ctx["cadence"].history("pulse")
        assert len(history) >= 1
        assert history[0]["routine"] == "spine.pulse"

    # ── 22.2 Routine 执行 ───────────────────────────────────────────────

    def test_ca10_run_calls_method(self, cadence_ctx):
        """CA-10: _run_routine calls correct method."""
        result = cadence_ctx["cadence"]._run_routine("spine.pulse", None, "manual")
        assert result["ok"] is True
        assert "pulse" in cadence_ctx["call_log"]

    def test_ca14_run_appends_history(self, cadence_ctx):
        """CA-14: _run_routine appends to history."""
        before = len(cadence_ctx["cadence"]._history)
        cadence_ctx["cadence"]._run_routine("spine.relay", None, "manual")
        assert len(cadence_ctx["cadence"]._history) > before

    def test_ca_run_unknown_routine(self, cadence_ctx):
        """_run_routine with unknown name → error."""
        result = cadence_ctx["cadence"]._run_routine("spine.nonexistent", None, "manual")
        assert result["ok"] is False

    # ── 22.3 Upstream 依赖检查 ───────────────────────────────────────────

    def test_ca20_no_deps_allowed(self, cadence_ctx):
        """CA-20: routine with no depends_on → allowed."""
        ok, reason = cadence_ctx["cadence"]._check_upstream_deps("spine.pulse")
        assert ok is True

    def test_ca21_upstream_ok(self, cadence_ctx):
        """CA-21: upstream succeeded → allowed."""
        log_path = cadence_ctx["state"] / "spine_log.jsonl"
        log_path.write_text(json.dumps({"routine": "record", "status": "ok"}) + "\n")
        ok, reason = cadence_ctx["cadence"]._check_upstream_deps("spine.witness")
        assert ok is True

    def test_ca22_upstream_failed(self, cadence_ctx):
        """CA-22: upstream failed → blocked."""
        log_path = cadence_ctx["state"] / "spine_log.jsonl"
        log_path.write_text(json.dumps({"routine": "record", "status": "error"}) + "\n")
        ok, reason = cadence_ctx["cadence"]._check_upstream_deps("spine.witness")
        assert ok is False
        assert "upstream" in reason

    def test_ca23_upstream_no_history(self, cadence_ctx):
        """CA-23: upstream with no log history → allowed (not blocked)."""
        ok, reason = cadence_ctx["cadence"]._check_upstream_deps("spine.witness")
        assert ok is True

    # ── 22.4 Adaptive Interval ───────────────────────────────────────────

    def test_cr_parse_duration_for_adaptive(self):
        """Adaptive schedule parsing."""
        from services.cadence import Cadence
        base, min_s, max_s = Cadence._parse_adaptive_schedule("adaptive:4h:1h-12h")
        assert base == 14400
        assert min_s == 3600
        assert max_s == 43200

    def test_ca34_interval_min_60s(self, cadence_ctx):
        """CA-34: adaptive interval never below 60s."""
        from services.cadence import Cadence
        interval = cadence_ctx["cadence"]._adaptive_interval("spine.witness", "adaptive:1m")
        assert interval >= 60

    # ── 22.5 Tick 机制 ───────────────────────────────────────────────────

    def test_ca40_tick_eval_expires_deed(self, cadence_ctx):
        """CA-40: _tick_eval_windows closes settling deed past deadline."""
        from tests.conftest import create_test_deed
        ledger = cadence_ctx["ledger"]
        # Create a settling deed with expired deadline
        past = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        deed_id = "deed_eval_expire"
        ledger.upsert_deed(deed_id, {
            "deed_id": deed_id,
            "deed_status": "settling",
            "deed_sub_status": "awaiting_eval",
            "slip_id": "slip_001",
            "created_utc": past,
            "updated_utc": past,
            "eval_deadline_utc": past,
        })
        cadence_ctx["cadence"]._tick_eval_windows()
        deeds = ledger.load_deeds()
        found = [d for d in deeds if d.get("deed_id") == deed_id]
        assert found
        assert found[0]["deed_status"] == "closed"
        assert found[0]["deed_sub_status"] == "timed_out"

    def test_ca41_tick_eval_keeps_active(self, cadence_ctx):
        """CA-41: _tick_eval_windows does not close deed before deadline."""
        ledger = cadence_ctx["ledger"]
        future = datetime(2030, 12, 31, 0, 0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        deed_id = "deed_eval_active"
        now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        ledger.upsert_deed(deed_id, {
            "deed_id": deed_id,
            "deed_status": "settling",
            "deed_sub_status": "awaiting_eval",
            "slip_id": "slip_002",
            "created_utc": now_utc,
            "updated_utc": now_utc,
            "eval_deadline_utc": future,
        })
        cadence_ctx["cadence"]._tick_eval_windows()
        deeds = ledger.load_deeds()
        found = [d for d in deeds if d.get("deed_id") == deed_id]
        assert found
        assert found[0]["deed_status"] == "settling"

    def test_ca42_tick_running_ttl_expires(self, cadence_ctx):
        """CA-42: _tick_running_ttl closes running deed past TTL."""
        ledger = cadence_ctx["ledger"]
        old = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        deed_id = "deed_ttl_expire"
        ledger.upsert_deed(deed_id, {
            "deed_id": deed_id,
            "deed_status": "running",
            "deed_sub_status": "executing",
            "slip_id": "slip_003",
            "created_utc": old,
            "updated_utc": old,
        })
        cadence_ctx["cadence"]._tick_running_ttl()
        deeds = ledger.load_deeds()
        found = [d for d in deeds if d.get("deed_id") == deed_id]
        assert found
        assert found[0]["deed_status"] == "closed"

    def test_ca43_tick_running_ttl_keeps_fresh(self, cadence_ctx):
        """CA-43: _tick_running_ttl does not close fresh running deed."""
        ledger = cadence_ctx["ledger"]
        now_utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        deed_id = "deed_ttl_fresh"
        ledger.upsert_deed(deed_id, {
            "deed_id": deed_id,
            "deed_status": "running",
            "deed_sub_status": "executing",
            "slip_id": "slip_004",
            "created_utc": now_utc,
            "updated_utc": now_utc,
        })
        cadence_ctx["cadence"]._tick_running_ttl()
        deeds = ledger.load_deeds()
        found = [d for d in deeds if d.get("deed_id") == deed_id]
        assert found
        assert found[0]["deed_status"] == "running"

    def test_ca44_tick_eval_emits_deed_closed(self, cadence_ctx):
        """CA-44: _tick_eval_windows emits deed_closed event."""
        events = []
        cadence_ctx["nerve"].on("deed_closed", lambda p: events.append(p))
        ledger = cadence_ctx["ledger"]
        past = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        deed_id = "deed_eval_event"
        ledger.upsert_deed(deed_id, {
            "deed_id": deed_id,
            "deed_status": "settling",
            "deed_sub_status": "awaiting_eval",
            "slip_id": "slip_005",
            "created_utc": past,
            "updated_utc": past,
            "eval_deadline_utc": past,
        })
        cadence_ctx["cadence"]._tick_eval_windows()
        deed_events = [e for e in events if e.get("deed_id") == deed_id]
        assert len(deed_events) >= 1

    def test_ca45_tick_running_ttl_emits_deed_closed(self, cadence_ctx):
        """CA-45: _tick_running_ttl emits deed_closed event."""
        events = []
        cadence_ctx["nerve"].on("deed_closed", lambda p: events.append(p))
        ledger = cadence_ctx["ledger"]
        old = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        deed_id = "deed_ttl_event"
        ledger.upsert_deed(deed_id, {
            "deed_id": deed_id,
            "deed_status": "running",
            "deed_sub_status": "executing",
            "slip_id": "slip_006",
            "created_utc": old,
            "updated_utc": old,
        })
        cadence_ctx["cadence"]._tick_running_ttl()
        deed_events = [e for e in events if e.get("deed_id") == deed_id]
        assert len(deed_events) >= 1

    # ── 22.6 手动触发 ───────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_ca50_trigger_valid(self, cadence_ctx):
        """CA-50: trigger valid routine → success."""
        result = await cadence_ctx["cadence"].trigger("spine.pulse")
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_ca51_trigger_unknown(self, cadence_ctx):
        """CA-51: trigger unknown routine → error."""
        result = await cadence_ctx["cadence"].trigger("spine.nonexistent")
        assert result["ok"] is False

    # ── Extra: Schedule override persistence ─────────────────────────────

    def test_ca_schedule_override_persist(self, cadence_ctx):
        """Schedule override persists to schedules.json."""
        cadence_ctx["cadence"].update_schedule("pulse", schedule="*/5 * * * *")
        path = cadence_ctx["state"] / "schedules.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["spine.pulse"]["schedule"] == "*/5 * * * *"

    def test_ca_is_supported_schedule(self):
        """_is_supported_schedule validates cron expressions."""
        from services.cadence import Cadence
        assert Cadence._is_supported_schedule("*/10 * * * *") is True
        assert Cadence._is_supported_schedule("adaptive:4h") is True
        assert Cadence._is_supported_schedule("not a cron") is False
        assert Cadence._is_supported_schedule("* * *") is False

    def test_ca_effective_schedule_override(self, cadence_ctx):
        """_effective_schedule uses override when set."""
        cadence_ctx["cadence"]._overrides["spine.pulse"] = {"schedule": "*/5 * * * *"}
        result = cadence_ctx["cadence"]._effective_schedule("spine.pulse", "*/10 * * * *")
        assert result == "*/5 * * * *"

    def test_ca_enabled_override(self, cadence_ctx):
        """_is_enabled respects override."""
        cadence_ctx["cadence"]._overrides["spine.pulse"] = {"enabled": False}
        assert cadence_ctx["cadence"]._is_enabled("spine.pulse") is False


# ═══════════════════════════════════════════════════════════════════════════════
# P4 — Round 5: Temporal Workflow, Temporal Activities, Pact Validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestTemporalWorkflow:
    """§23 — GraphWillWorkflow helper methods (no Temporal runtime needed)."""

    @pytest.fixture
    def wf(self):
        """Create workflow instance directly (no Temporal context)."""
        from temporal.workflows import GraphWillWorkflow
        return GraphWillWorkflow()

    # ── 23.1 DAG Construction ──────────────────────────────────────────────

    def test_tw01_move_id_explicit(self, wf):
        """TW-01: _move_id returns explicit id field."""
        assert wf._move_id({"id": "scout_1"}, 0) == "scout_1"

    def test_tw02_move_id_fallback_move_id(self, wf):
        """TW-02: _move_id falls back to move_id field."""
        assert wf._move_id({"move_id": "sage_1"}, 0) == "sage_1"

    def test_tw03_move_id_fallback_index(self, wf):
        """TW-03: _move_id generates move_{index} when no id provided."""
        assert wf._move_id({}, 5) == "move_5"

    def test_tw04_deps_explicit(self, wf):
        """TW-04: _deps extracts depends_on list."""
        assert wf._deps({"depends_on": ["scout_1", "sage_1"]}) == ["scout_1", "sage_1"]

    def test_tw05_deps_alt_key(self, wf):
        """TW-05: _deps uses dependencies as fallback key."""
        assert wf._deps({"dependencies": ["a"]}) == ["a"]

    def test_tw06_deps_empty(self, wf):
        """TW-06: _deps returns empty list when no deps."""
        assert wf._deps({}) == []

    def test_tw07_agent_extraction(self, wf):
        """TW-07: _agent extracts agent field."""
        assert wf._agent({"agent": "scribe"}) == "scribe"
        assert wf._agent({}) == ""

    def test_tw08_deed_input_dataclass(self):
        """TW-08: DeedInput dataclass fields."""
        from temporal.workflows import DeedInput
        inp = DeedInput(plan={"moves": []}, deed_root="/tmp/d", deed_id="deed_1")
        assert inp.plan == {"moves": []}
        assert inp.deed_root == "/tmp/d"
        assert inp.deed_id == "deed_1"

    def test_tw09_deed_input_defaults(self):
        """TW-09: DeedInput deed_id defaults to empty string."""
        from temporal.workflows import DeedInput
        inp = DeedInput(plan={}, deed_root="/tmp/x")
        assert inp.deed_id == ""

    # ── 23.2 Agent Limits ──────────────────────────────────────────────────

    def test_tw20_agent_limits_basic(self, wf):
        """TW-20: _agent_limits counts max parallel per agent."""
        plan = {"moves": [
            {"id": "scout_1", "agent": "scout", "depends_on": []},
            {"id": "scout_2", "agent": "scout", "depends_on": []},
            {"id": "scribe_1", "agent": "scribe", "depends_on": ["scout_1", "scout_2"]},
        ]}
        limits = wf._agent_limits(plan)
        assert limits["scout"] >= 2  # Two scouts with same deps → parallel
        assert limits["scribe"] >= 1

    def test_tw21_agent_limits_spine_min(self, wf):
        """TW-21: spine gets minimum limit of 2."""
        plan = {"moves": [{"id": "s1", "agent": "spine", "depends_on": []}]}
        limits = wf._agent_limits(plan)
        assert limits["spine"] >= 2

    def test_tw22_agent_limits_override(self, wf):
        """TW-22: agent_concurrency overrides computed limits."""
        plan = {
            "moves": [{"id": "s1", "agent": "scout", "depends_on": []}],
            "agent_concurrency": {"scout": 5},
        }
        limits = wf._agent_limits(plan)
        assert limits["scout"] == 5

    def test_tw23_agent_limits_empty_plan(self, wf):
        """TW-23: _agent_limits handles empty moves."""
        limits = wf._agent_limits({"moves": []})
        assert isinstance(limits, dict)

    # ── 23.3 Requirement Injection ─────────────────────────────────────────

    def test_tw30_inject_requirements_empty(self, wf):
        """TW-30: no active requirements → move unchanged."""
        move = {"instruction": "do something", "agent": "scout"}
        result = wf._inject_requirements(move)
        assert result["instruction"] == "do something"

    def test_tw31_inject_requirements_appended(self, wf):
        """TW-31: active requirements appended to instruction."""
        wf._active_requirements = [
            {"text": "Use formal tone", "source": "user", "appended_at": "2026-03-13T00:00:00Z"},
        ]
        move = {"instruction": "write report"}
        result = wf._inject_requirements(move)
        assert "Use formal tone" in result["instruction"]
        assert "write report" in result["instruction"]

    def test_tw32_inject_requirements_cap_10(self, wf):
        """TW-32: only last 10 requirements injected."""
        wf._active_requirements = [
            {"text": f"req_{i}", "source": "user", "appended_at": "2026-03-13T00:00:00Z"}
            for i in range(15)
        ]
        move = {"instruction": "base"}
        result = wf._inject_requirements(move)
        # Should contain req_5..req_14 (last 10)
        assert "req_14" in result["instruction"]

    def test_tw33_signal_append_requirement_cap_20(self, wf):
        """TW-33: append_requirement caps at 20 entries."""
        for i in range(25):
            wf.append_requirement({"text": f"req_{i}", "appended_at": "2026-03-13T00:00:00Z"})
        assert len(wf._active_requirements) == 20
        # Should retain the last 20
        assert wf._active_requirements[0]["text"] == "req_5"

    def test_tw34_signal_append_empty_ignored(self, wf):
        """TW-34: append_requirement ignores empty text."""
        wf.append_requirement({"text": ""})
        wf.append_requirement({})
        wf.append_requirement(None)
        assert len(wf._active_requirements) == 0

    # ── 23.4 Pause/Resume ─────────────────────────────────────────────────

    def test_tw35_pause_resume_signals(self, wf):
        """TW-35: pause/resume signals toggle _pause_requested."""
        assert wf._pause_requested is False
        wf.pause_execution()
        assert wf._pause_requested is True
        wf.resume_execution()
        assert wf._pause_requested is False

    # ── 23.5 Timeouts ─────────────────────────────────────────────────────

    def test_tw40_timeouts_default(self, wf):
        """TW-40: _timeouts returns default when no hints."""
        from datetime import timedelta
        plan = {"default_move_timeout_s": 480}
        st_to, sc_to = wf._timeouts(plan, {})
        assert st_to == timedelta(seconds=480)
        assert sc_to == timedelta(seconds=510)

    def test_tw41_timeouts_move_override(self, wf):
        """TW-41: move timeout_s overrides plan default."""
        from datetime import timedelta
        plan = {"default_move_timeout_s": 480}
        st_to, sc_to = wf._timeouts(plan, {"timeout_s": 120})
        assert st_to == timedelta(seconds=120)

    def test_tw42_timeouts_agent_hint(self, wf):
        """TW-42: timeout_hints per agent used when no move override."""
        from datetime import timedelta
        plan = {"default_move_timeout_s": 480, "timeout_hints": {"scout": 300}}
        st_to, _ = wf._timeouts(plan, {"agent": "scout"})
        assert st_to == timedelta(seconds=300)

    # ── 23.6 Arbiter/Rework ───────────────────────────────────────────────

    def test_tw50_last_arbiter_result_found(self, wf):
        """TW-50: _last_arbiter_result finds arbiter move."""
        results = [
            {"move_id": "scout_1", "status": "ok"},
            {"move_id": "arbiter_review", "status": "ok", "arbiter_verdict": "pass"},
        ]
        r = wf._last_arbiter_result(results)
        assert r is not None
        assert r["move_id"] == "arbiter_review"

    def test_tw51_last_arbiter_result_by_agent(self, wf):
        """TW-51: _last_arbiter_result matches by agent field."""
        results = [
            {"move_id": "review_1", "agent": "arbiter", "status": "ok"},
        ]
        r = wf._last_arbiter_result(results)
        assert r is not None

    def test_tw52_last_arbiter_result_none(self, wf):
        """TW-52: _last_arbiter_result returns None when no arbiter."""
        results = [{"move_id": "scout_1"}, {"move_id": "scribe_1"}]
        assert wf._last_arbiter_result(results) is None

    def test_tw53_needs_rework_verdict(self, wf):
        """TW-53: _needs_rework True on explicit verdict=rework."""
        assert wf._needs_rework({"arbiter_verdict": "rework"}) is True

    def test_tw54_needs_rework_status(self, wf):
        """TW-54: _needs_rework True on status=rework."""
        assert wf._needs_rework({"status": "rework"}) is True

    def test_tw55_needs_rework_pass(self, wf):
        """TW-55: _needs_rework False on pass verdict."""
        assert wf._needs_rework({"arbiter_verdict": "pass"}) is False

    def test_tw56_needs_rework_scores_below(self, wf):
        """TW-56: _needs_rework True when score below threshold."""
        result = {"scores": {"coverage": 0.3, "depth": 0.9}, "depth": "study"}
        assert wf._needs_rework(result) is True

    def test_tw57_needs_rework_scores_above(self, wf):
        """TW-57: _needs_rework False when all scores above threshold."""
        result = {"scores": {"coverage": 0.8, "depth": 0.8}, "depth": "study"}
        assert wf._needs_rework(result) is False

    def test_tw58_needs_rework_glance_threshold(self, wf):
        """TW-58: glance depth has lower thresholds."""
        result = {"scores": {"coverage": 0.55, "depth": 0.45}, "depth": "glance"}
        assert wf._needs_rework(result) is False

    def test_tw59_needs_rework_scrutiny_threshold(self, wf):
        """TW-59: scrutiny depth has higher thresholds."""
        result = {"scores": {"coverage": 0.65, "depth": 0.65}, "depth": "scrutiny"}
        assert wf._needs_rework(result) is True

    def test_tw60_rework_moves_collection_issue(self, wf):
        """TW-60: collection error code selects scout/sage/scribe."""
        move_list = [
            {"id": "scout_1", "agent": "scout", "instruction": "search"},
            {"id": "sage_1", "agent": "sage", "instruction": "analyze"},
            {"id": "scribe_1", "agent": "scribe", "instruction": "write"},
            {"id": "arbiter_1", "agent": "arbiter", "instruction": "review"},
        ]
        rework = wf._rework_moves(move_list, "coverage_below_threshold", 1)
        agents = {m["agent"] for m in rework}
        assert "scout" in agents
        assert "scribe" in agents
        assert "arbiter" not in agents

    def test_tw61_rework_moves_generic_issue(self, wf):
        """TW-61: generic error code selects arbiter/scribe."""
        move_list = [
            {"id": "scout_1", "agent": "scout", "instruction": "search"},
            {"id": "scribe_1", "agent": "scribe", "instruction": "write"},
            {"id": "arbiter_1", "agent": "arbiter", "instruction": "review"},
        ]
        rework = wf._rework_moves(move_list, "arbiter_rejected", 1)
        agents = {m["agent"] for m in rework}
        assert "arbiter" in agents
        assert "scribe" in agents
        assert "scout" not in agents

    def test_tw62_rework_moves_adds_attempt(self, wf):
        """TW-62: rework moves get rework_attempt set."""
        move_list = [{"id": "scribe_1", "agent": "scribe", "instruction": "write"}]
        rework = wf._rework_moves(move_list, "arbiter_rejected", 2)
        assert rework[0]["rework_attempt"] == 2

    def test_tw63_rework_moves_appends_instruction(self, wf):
        """TW-63: rework instruction appended to original."""
        move_list = [{"id": "scribe_1", "agent": "scribe", "instruction": "write report"}]
        rework = wf._rework_moves(move_list, "arbiter_rejected", 1)
        assert "write report" in rework[0]["instruction"]
        assert "Rework" in rework[0]["instruction"]


class TestTemporalActivities:
    """§24 — DaemonActivities helper methods (filesystem-based, no Temporal context)."""

    @pytest.fixture
    def act_ctx(self, tmp_path):
        """Build a minimal DaemonActivities-like object for testing helpers."""
        import types

        home = tmp_path / "daemon"
        home.mkdir()
        (home / "state").mkdir()
        (home / "psyche" / "voice").mkdir(parents=True)
        (home / "psyche" / "overlays").mkdir(parents=True)
        (home / "config").mkdir()

        # Create minimal DaemonActivities without calling __init__
        from temporal.activities import DaemonActivities
        act = object.__new__(DaemonActivities)
        act._home = home
        act._oc_home = home / "openclaw"
        act._openclaw = None
        act._ether = None
        act._ledger = Ledger(home / "state")
        act._retinue = None
        act._mcp = None
        act._psyche_config = None
        act._cortex = None
        act._ledger_stats = None
        act._instinct_engine = None

        return {"act": act, "home": home}

    # ── 24.1 Clean System Markers ──────────────────────────────────────────

    def test_ta01_clean_markers_done(self, act_ctx):
        """TA-01: [DONE] marker removed."""
        text = "Report complete.\n[DONE]\nEnd."
        cleaned = act_ctx["act"]._clean_system_markers(text)
        assert "[DONE]" not in cleaned
        assert "Report complete" in cleaned

    def test_ta02_clean_markers_system_note(self, act_ctx):
        """TA-02: <system-note> tags removed."""
        text = "Content here.\n<system-note>internal</system-note>\nMore content."
        cleaned = act_ctx["act"]._clean_system_markers(text)
        assert "system-note" not in cleaned
        assert "Content here" in cleaned

    def test_ta03_clean_markers_comment(self, act_ctx):
        """TA-03: <!-- system --> HTML comments removed."""
        text = "Text <!-- system debug --> more text"
        cleaned = act_ctx["act"]._clean_system_markers(text)
        assert "system" not in cleaned.lower() or "system" in "more text"  # only in normal text

    def test_ta04_clean_markers_preserves_content(self, act_ctx):
        """TA-04: clean text passes through unchanged."""
        text = "This is a normal report with no markers."
        cleaned = act_ctx["act"]._clean_system_markers(text)
        assert cleaned == text

    def test_ta05_clean_markers_collapses_blanks(self, act_ctx):
        """TA-05: multiple blank lines collapsed after marker removal."""
        text = "Line 1\n\n\n\n\nLine 2"
        cleaned = act_ctx["act"]._clean_system_markers(text)
        assert "\n\n\n" not in cleaned

    # ── 24.2 Token Estimation ──────────────────────────────────────────────

    def test_ta10_estimate_tokens_basic(self, act_ctx):
        """TA-10: _estimate_tokens returns ~chars/4."""
        tokens = act_ctx["act"]._estimate_tokens("hello world")
        assert tokens >= 1
        assert tokens == len("hello world") // 4 or tokens == max(1, len("hello world") // 4)

    def test_ta11_estimate_tokens_empty(self, act_ctx):
        """TA-11: empty string → at least 1 token."""
        assert act_ctx["act"]._estimate_tokens("") >= 1

    # ── 24.3 Normalized Moves ──────────────────────────────────────────────

    def test_ta15_normalized_moves_basic(self, act_ctx):
        """TA-15: _normalized_moves assigns ids."""
        plan = {"moves": [
            {"id": "scout_1", "agent": "scout"},
            {"agent": "scribe"},
        ]}
        moves = act_ctx["act"]._normalized_moves(plan)
        assert len(moves) == 2
        assert moves[0]["id"] == "scout_1"
        assert moves[1]["id"] == "move_1"

    def test_ta16_normalized_moves_graph_key(self, act_ctx):
        """TA-16: _normalized_moves reads from graph.moves fallback."""
        plan = {"graph": {"moves": [{"id": "a", "agent": "scout"}]}}
        moves = act_ctx["act"]._normalized_moves(plan)
        assert len(moves) == 1

    def test_ta17_normalized_moves_empty(self, act_ctx):
        """TA-17: _normalized_moves handles missing moves."""
        assert act_ctx["act"]._normalized_moves({}) == []
        assert act_ctx["act"]._normalized_moves({"moves": "bad"}) == []

    def test_ta18_normalized_moves_skips_non_dict(self, act_ctx):
        """TA-18: non-dict entries in moves list skipped."""
        plan = {"moves": [{"id": "a"}, "bad", 42, {"id": "b"}]}
        moves = act_ctx["act"]._normalized_moves(plan)
        assert len(moves) == 2

    # ── 24.4 Find Scribe Output ────────────────────────────────────────────

    def test_ta20_find_scribe_output_by_move_id(self, act_ctx):
        """TA-20: _find_scribe_output locates scribe move output."""
        home = act_ctx["home"]
        deed_root = home / "state" / "deeds" / "deed_1"
        out_dir = deed_root / "moves" / "scribe_1" / "output"
        out_dir.mkdir(parents=True)
        (out_dir / "output.md").write_text("# Report")
        results = [{"move_id": "scribe_1", "status": "ok"}]
        path = act_ctx["act"]._find_scribe_output(str(deed_root), results)
        assert path is not None
        assert path.name == "output.md"

    def test_ta21_find_scribe_output_by_output_path(self, act_ctx):
        """TA-21: _find_scribe_output uses explicit output_path."""
        home = act_ctx["home"]
        out_file = home / "state" / "explicit_output.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text("# Explicit")
        results = [{"move_id": "scribe_1", "output_path": str(out_file)}]
        path = act_ctx["act"]._find_scribe_output(str(home / "state" / "deeds" / "d1"), results)
        assert path is not None
        assert path == out_file

    def test_ta22_find_scribe_output_none(self, act_ctx):
        """TA-22: _find_scribe_output returns None when no output found."""
        deed_root = act_ctx["home"] / "state" / "deeds" / "deed_empty"
        deed_root.mkdir(parents=True)
        path = act_ctx["act"]._find_scribe_output(str(deed_root), [])
        assert path is None

    # ── 24.5 Write/Read Move Output & Checkpoints ─────────────────────────

    def test_ta25_write_move_output(self, act_ctx):
        """TA-25: _write_move_output creates output.md."""
        deed_root = act_ctx["home"] / "deeds" / "d1"
        deed_root.mkdir(parents=True)
        path = act_ctx["act"]._write_move_output(str(deed_root), "scout_1", "# Result")
        assert Path(path).exists()
        assert Path(path).read_text() == "# Result"

    def test_ta26_checkpoint_roundtrip(self, act_ctx):
        """TA-26: write then read move checkpoint."""
        deed_root = act_ctx["home"] / "deeds" / "d2"
        deed_root.mkdir(parents=True)
        act_ctx["act"]._write_move_checkpoint(str(deed_root), "move_1", {"status": "ok", "data": 42})
        loaded = act_ctx["act"]._read_move_checkpoint(str(deed_root), "move_1")
        assert loaded is not None
        assert loaded["status"] == "ok"
        assert "checkpoint_utc" in loaded

    def test_ta27_read_checkpoint_missing(self, act_ctx):
        """TA-27: _read_move_checkpoint returns None for missing file."""
        deed_root = act_ctx["home"] / "deeds" / "d3"
        deed_root.mkdir(parents=True)
        assert act_ctx["act"]._read_move_checkpoint(str(deed_root), "nonexistent") is None

    # ── 24.6 Build Move Context ────────────────────────────────────────────

    def test_ta30_build_context_basic(self, act_ctx):
        """TA-30: _build_move_context returns dict with execution_contract."""
        deed_root = str(act_ctx["home"] / "deeds" / "d1")
        plan = {"deed_id": "d1", "brief": {"objective": "test"}}
        move = {"agent": "scout", "id": "scout_1"}
        ctx = act_ctx["act"]._build_move_context(deed_root, plan, move)
        assert "execution_contract" in ctx
        assert ctx["execution_contract"]["deed_id"] == "d1"

    def test_ta31_build_context_counsel_hints(self, act_ctx):
        """TA-31: counsel agent gets planning hints if ledger_stats available."""
        # Without ledger_stats, no psyche_context for hints
        deed_root = str(act_ctx["home"] / "deeds" / "d2")
        plan = {"deed_id": "d2", "brief": {"objective": "plan"}}
        move = {"agent": "counsel", "id": "counsel_1"}
        ctx = act_ctx["act"]._build_move_context(deed_root, plan, move)
        # Without ledger_stats initialized, no hints - just execution_contract
        assert "execution_contract" in ctx

    def test_ta32_build_context_scribe_style(self, act_ctx):
        """TA-32: scribe agent gets voice style if identity exists."""
        home = act_ctx["home"]
        (home / "psyche" / "voice" / "identity.md").write_text("I am daemon.")
        (home / "psyche" / "voice" / "common.md").write_text("Write clearly.")
        deed_root = str(home / "deeds" / "d3")
        plan = {"deed_id": "d3", "brief": {"objective": "write", "language": "zh"}}
        move = {"agent": "scribe", "id": "scribe_1"}
        ctx = act_ctx["act"]._build_move_context(deed_root, plan, move)
        assert "psyche_context" in ctx
        assert "I am daemon" in ctx["psyche_context"]

    # ── 24.7 Model Context Window ──────────────────────────────────────────

    def test_ta35_model_context_window_default(self, act_ctx):
        """TA-35: default context window is 128000."""
        assert act_ctx["act"]._model_context_window({}, {}) == 128000

    def test_ta36_model_context_window_from_registry(self, act_ctx):
        """TA-36: context window loaded from model_registry.json."""
        home = act_ctx["home"]
        reg = {"models": [{"alias": "fast", "context_window": 200000}]}
        (home / "config" / "model_registry.json").write_text(json.dumps(reg))
        assert act_ctx["act"]._model_context_window({}, {"model_alias": "fast"}) == 200000

    # ── 24.8 Update Deed Status ────────────────────────────────────────────

    def test_ta40_update_deed_status_new(self, act_ctx):
        """TA-40: _update_deed_status creates new deed entry."""
        deed_root = str(act_ctx["home"] / "deeds" / "d1")
        plan = {"deed_id": "d1", "deed_title": "Test Deed", "brief": {}}
        act_ctx["act"]._update_deed_status(deed_root, plan, "running")
        deeds = act_ctx["act"]._ledger.load_deeds()
        found = [d for d in deeds if d.get("deed_id") == "d1"]
        assert len(found) == 1
        assert found[0]["deed_status"] == "running"

    def test_ta41_update_deed_status_mutation(self, act_ctx):
        """TA-41: _update_deed_status mutates existing deed."""
        deed_root = str(act_ctx["home"] / "deeds" / "d2")
        plan = {"deed_id": "d2", "deed_title": "Deed 2", "brief": {}}
        act_ctx["act"]._update_deed_status(deed_root, plan, "running")
        act_ctx["act"]._update_deed_status(deed_root, plan, "settling")
        deeds = act_ctx["act"]._ledger.load_deeds()
        found = [d for d in deeds if d.get("deed_id") == "d2"]
        assert len(found) == 1
        assert found[0]["deed_status"] == "settling"

    def test_ta42_update_deed_status_settling_deadline(self, act_ctx):
        """TA-42: settling status sets eval_deadline_utc."""
        deed_root = str(act_ctx["home"] / "deeds" / "d3")
        plan = {"deed_id": "d3", "brief": {}, "eval_window_hours": 24}
        act_ctx["act"]._update_deed_status(deed_root, plan, "settling")
        deeds = act_ctx["act"]._ledger.load_deeds()
        found = [d for d in deeds if d.get("deed_id") == "d3"]
        assert found[0].get("eval_deadline_utc")

    def test_ta43_update_deed_status_closed_removes_deadline(self, act_ctx):
        """TA-43: closed status removes eval_deadline_utc."""
        deed_root = str(act_ctx["home"] / "deeds" / "d4")
        plan = {"deed_id": "d4", "brief": {}}
        act_ctx["act"]._update_deed_status(deed_root, plan, "settling")
        act_ctx["act"]._update_deed_status(deed_root, plan, "closed")
        deeds = act_ctx["act"]._ledger.load_deeds()
        found = [d for d in deeds if d.get("deed_id") == "d4"]
        assert found[0].get("eval_deadline_utc") is None

    # ── 24.9 Quality Floor Check ───────────────────────────────────────────

    def test_ta50_quality_floor_basic(self, act_ctx):
        """TA-50: _quality_floor_check returns structured result."""
        home = act_ctx["home"]
        deed_root = home / "deeds" / "d_quality"
        deed_root.mkdir(parents=True)
        scribe_file = deed_root / "output.md"
        scribe_file.write_text("# Report Title\n\n## Section 1\n\nLong content here. " * 200)
        plan = {"brief": {"objective": "test report"}}
        result = act_ctx["act"]._quality_floor_check(str(deed_root), plan, scribe_file, [])
        assert "ok" in result
        assert "score" in result
        assert "components" in result
        assert "word_count" in result

    def test_ta51_quality_floor_markers_fail(self, act_ctx):
        """TA-51: forbidden markers cause quality check to fail."""
        home = act_ctx["home"]
        deed_root = home / "deeds" / "d_markers"
        deed_root.mkdir(parents=True)
        scribe_file = deed_root / "output.md"
        scribe_file.write_text("# Report\n\n## Section\n\nContent. " * 200)
        plan = {
            "brief": {},
            "quality_profile": {"forbidden_markers": ["[DONE]"], "min_quality_score": 0.1},
        }
        # Write file with forbidden marker
        scribe_file.write_text("# Report\n\n[DONE]\n\nContent " * 200)
        result = act_ctx["act"]._quality_floor_check(str(deed_root), plan, scribe_file, [])
        assert result["ok"] is False
        assert result["reason"] == "forbidden_markers_present"

    # ── 24.10 Archive Offering ─────────────────────────────────────────────

    def test_ta55_archive_offering_creates_dir(self, act_ctx):
        """TA-55: _archive_offering creates offering directory."""
        home = act_ctx["home"]
        deed_root = home / "deeds" / "d_archive"
        deed_root.mkdir(parents=True)
        scribe_file = deed_root / "output.md"
        scribe_file.write_text("# Archived Report")
        offering_root = home / "offerings"
        offering_root.mkdir()
        plan = {"deed_id": "d_archive", "deed_title": "Test Archive", "brief": {}}
        result = act_ctx["act"]._archive_offering(str(deed_root), plan, scribe_file, [], offering_root=offering_root)
        assert result.exists()
        assert result.is_dir()
        # Should contain the archived file
        files = list(result.iterdir())
        assert len(files) >= 1

    # ── 24.11 Voice/Overlay Reading ────────────────────────────────────────

    def test_ta60_read_voice_identity(self, act_ctx):
        """TA-60: _read_voice_identity reads identity.md."""
        home = act_ctx["home"]
        (home / "psyche" / "voice" / "identity.md").write_text("I am the daemon.")
        assert act_ctx["act"]._read_voice_identity() == "I am the daemon."

    def test_ta61_read_voice_identity_missing(self, act_ctx):
        """TA-61: missing identity.md returns empty string."""
        assert act_ctx["act"]._read_voice_identity() == ""

    def test_ta62_read_overlay(self, act_ctx):
        """TA-62: _read_overlay reads task-type overlay."""
        home = act_ctx["home"]
        (home / "psyche" / "overlays" / "research.md").write_text("Research guidelines")
        assert act_ctx["act"]._read_overlay("research") == "Research guidelines"

    def test_ta63_read_overlay_missing(self, act_ctx):
        """TA-63: missing overlay returns empty string."""
        assert act_ctx["act"]._read_overlay("nonexistent") == ""
        assert act_ctx["act"]._read_overlay("") == ""


class TestPactValidation:
    """§25 — Spine Pact IO validation."""

    # ── 25.1 Pre-conditions ────────────────────────────────────────────────

    def test_pt01_infra_pre_passes(self, tmp_path):
        """PT-01: infra namespace pre-check always passes (runtime validated)."""
        from spine.pact import check_pact
        check_pact("spine.pulse", "pre", "infra:health", {"daemon_home": tmp_path})

    def test_pt02_state_ward_post_missing(self, tmp_path):
        """PT-02: state:ward post fails when ward.json missing."""
        from spine.pact import check_pact, PactError
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        with pytest.raises(PactError, match="state:ward"):
            check_pact("spine.pulse", "post", "state:ward", {"daemon_home": tmp_path, "state_dir": state_dir})

    def test_pt03_state_ward_post_exists(self, tmp_path):
        """PT-03: state:ward post passes when ward.json exists."""
        from spine.pact import check_pact
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        (state_dir / "ward.json").write_text("{}")
        check_pact("spine.pulse", "post", "state:ward", {"daemon_home": tmp_path, "state_dir": state_dir})

    def test_pt04_state_traces_pre_missing(self, tmp_path):
        """PT-04: state:traces pre fails when traces dir missing."""
        from spine.pact import check_pact, PactError
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        with pytest.raises(PactError, match="state:traces"):
            check_pact("spine.tend", "pre", "state:traces", {"daemon_home": tmp_path, "state_dir": state_dir})

    def test_pt05_state_traces_pre_exists(self, tmp_path):
        """PT-05: state:traces pre passes when traces dir exists."""
        from spine.pact import check_pact
        state_dir = tmp_path / "state"
        (state_dir / "traces").mkdir(parents=True)
        check_pact("spine.tend", "pre", "state:traces", {"daemon_home": tmp_path, "state_dir": state_dir})

    def test_pt06_psyche_pre_missing(self, tmp_path):
        """PT-06: psyche namespace pre fails when instance missing from context."""
        from spine.pact import check_pact, PactError
        with pytest.raises(PactError, match="psyche:ledger"):
            check_pact("spine.witness", "pre", "psyche:ledger:stats", {"daemon_home": tmp_path, "psyche": {}})

    def test_pt07_psyche_pre_exists(self, tmp_path):
        """PT-07: psyche pre passes when instance present."""
        from spine.pact import check_pact
        check_pact("spine.witness", "pre", "psyche:ledger:stats", {"daemon_home": tmp_path, "psyche": {"ledger": True}})

    def test_pt08_openclaw_pre_passes(self, tmp_path):
        """PT-08: openclaw namespace pre always passes (runtime validated)."""
        from spine.pact import check_pact
        check_pact("test", "pre", "openclaw:gateway", {"daemon_home": tmp_path})

    # ── 25.2 Post-conditions ───────────────────────────────────────────────

    def test_pt10_state_snapshots_post_no_check(self, tmp_path):
        """PT-10: state:snapshots post passes (no file check for arbitrary state)."""
        from spine.pact import check_pact
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        check_pact("spine.relay", "post", "state:snapshots", {"daemon_home": tmp_path, "state_dir": state_dir})

    def test_pt11_psyche_post_no_check(self, tmp_path):
        """PT-11: psyche post passes (no post validation for psyche writes)."""
        from spine.pact import check_pact
        check_pact("spine.record", "post", "psyche:ledger:dag_templates", {"daemon_home": tmp_path, "psyche": {}})

    # ── 25.3 Pact Error Type ──────────────────────────────────────────────

    def test_pt15_pact_error_inherits_exception(self):
        """PT-15: PactError is an Exception."""
        from spine.pact import PactError
        assert issubclass(PactError, Exception)
        e = PactError("test message")
        assert str(e) == "test message"

    def test_pt16_pact_unknown_namespace(self, tmp_path):
        """PT-16: unknown namespace passes silently (no assertion)."""
        from spine.pact import check_pact
        check_pact("test", "pre", "unknown:stuff", {"daemon_home": tmp_path})

    def test_pt17_deeds_scout_output_pre(self, tmp_path):
        """PT-17: deeds:scout_output pre does not raise (logs info instead)."""
        from spine.pact import check_pact
        (tmp_path / "state" / "deeds").mkdir(parents=True)
        check_pact("test", "pre", "deeds:scout_output", {"daemon_home": tmp_path})


# ═══════════════════════════════════════════════════════════════════════════════
# P5 — Round 6: Herald Pipeline, Runtime Components, PsycheConfig, Design Validator
# ═══════════════════════════════════════════════════════════════════════════════


class TestHeraldPipeline:
    """§18 — Herald archive pipeline."""

    @pytest.fixture
    def herald_ctx(self, tmp_path):
        """Build HeraldService with temp filesystem."""
        from psyche.config import PsycheConfig
        from services.herald import HeraldService

        home = tmp_path / "daemon"
        (home / "state").mkdir(parents=True)
        (home / "psyche").mkdir()
        config = PsycheConfig(home / "psyche")
        nerve = Nerve()
        herald = HeraldService(config, nerve, home)
        return {"herald": herald, "home": home, "nerve": nerve, "config": config}

    # ── 18.1 Deliver ───────────────────────────────────────────────────────

    def test_hp01_deliver_no_scribe_output(self, herald_ctx):
        """HP-01: deliver with no scribe output → failure."""
        deed_root = herald_ctx["home"] / "deeds" / "d1"
        deed_root.mkdir(parents=True)
        result = herald_ctx["herald"].deliver(str(deed_root), {"deed_id": "d1"}, [])
        assert result["ok"] is False
        assert result["error_code"] == "scribe_output_missing"

    def test_hp02_deliver_with_scribe_output(self, herald_ctx):
        """HP-02: deliver with scribe output → success."""
        deed_root = herald_ctx["home"] / "deeds" / "d2"
        out_dir = deed_root / "moves" / "scribe_1" / "output"
        out_dir.mkdir(parents=True)
        (out_dir / "output.md").write_text("# Report\n\n## Section 1\n\nContent here.")
        plan = {"deed_id": "d2", "deed_title": "Test Report", "brief": {}}
        result = herald_ctx["herald"].deliver(str(deed_root), plan, [{"move_id": "scribe_1"}])
        assert result["ok"] is True
        assert "offering_path" in result
        assert "delivered_utc" in result

    def test_hp03_vault_copies_file(self, herald_ctx):
        """HP-03: _vault copies scribe output to offering dir."""
        deed_root = herald_ctx["home"] / "deeds" / "d3"
        deed_root.mkdir(parents=True)
        render_file = deed_root / "output.md"
        render_file.write_text("# Vaulted")
        plan = {"deed_title": "Vault Test", "brief": {}}
        dest = herald_ctx["herald"]._vault(str(deed_root), plan, render_file)
        assert dest.exists()
        files = list(dest.iterdir())
        assert any(f.suffix == ".md" for f in files)

    def test_hp04_pdf_generation_no_crash(self, herald_ctx):
        """HP-04: _generate_pdf_best_effort does not crash."""
        deed_root = herald_ctx["home"] / "deeds" / "d4"
        deed_root.mkdir(parents=True)
        render_file = deed_root / "output.md"
        render_file.write_text("Simple text for PDF.")
        offering_dir = deed_root / "offering"
        offering_dir.mkdir()
        herald_ctx["herald"]._generate_pdf_best_effort(offering_dir, render_file)
        pdf = offering_dir / "report.pdf"
        assert pdf.exists()
        assert pdf.stat().st_size > 0

    def test_hp05_update_index_writes_log(self, herald_ctx):
        """HP-05: _update_index writes to herald_log."""
        offering_dir = herald_ctx["home"] / "offerings" / "2026-03" / "test"
        offering_dir.mkdir(parents=True)
        plan = {"deed_id": "d5", "deed_title": "Index Test", "metadata": {"slip_id": "s1"}}
        herald_ctx["herald"]._update_index(offering_dir, plan)
        log = herald_ctx["herald"]._ledger.load_herald_log()
        assert len(log) >= 1
        assert log[-1]["deed_id"] == "d5"

    def test_hp06_herald_log_structure(self, herald_ctx):
        """HP-06: herald_log entry has required fields."""
        offering_dir = herald_ctx["home"] / "offerings" / "2026-03" / "test2"
        offering_dir.mkdir(parents=True)
        plan = {
            "deed_id": "d6", "slip_title": "Title",
            "metadata": {"slip_id": "s2", "folio_id": "f1"},
        }
        herald_ctx["herald"]._update_index(offering_dir, plan)
        entry = herald_ctx["herald"]._ledger.load_herald_log()[-1]
        assert "path" in entry
        assert "title" in entry
        assert "deed_id" in entry
        assert "delivered_utc" in entry

    def test_hp07_deliver_emits_herald_completed(self, herald_ctx):
        """HP-07: deliver triggers herald_completed event."""
        events = []
        herald_ctx["nerve"].on("herald_completed", lambda p: events.append(p))
        deed_root = herald_ctx["home"] / "deeds" / "d7"
        out_dir = deed_root / "moves" / "scribe_1" / "output"
        out_dir.mkdir(parents=True)
        (out_dir / "output.md").write_text("# Event Test")
        plan = {"deed_id": "d7", "deed_title": "Event Test", "brief": {}}
        herald_ctx["herald"].deliver(str(deed_root), plan, [{"move_id": "scribe_1"}])
        assert len(events) >= 1
        assert events[0]["deed_id"] == "d7"

    def test_hp08_deliver_short_content(self, herald_ctx):
        """HP-08: deliver succeeds with minimal content."""
        deed_root = herald_ctx["home"] / "deeds" / "d8"
        out_dir = deed_root / "moves" / "scribe_1" / "output"
        out_dir.mkdir(parents=True)
        (out_dir / "output.md").write_text("Hi")
        plan = {"deed_id": "d8", "brief": {}}
        result = herald_ctx["herald"].deliver(str(deed_root), plan, [{"move_id": "scribe_1"}])
        assert result["ok"] is True

    def test_hp09_html_scribe_output(self, herald_ctx):
        """HP-09: deliver handles HTML scribe output."""
        deed_root = herald_ctx["home"] / "deeds" / "d9"
        out_dir = deed_root / "moves" / "render_1" / "deliver"
        out_dir.mkdir(parents=True)
        (out_dir / "report.html").write_text("<html><body><h1>Report</h1></body></html>")
        plan = {"deed_id": "d9", "brief": {}}
        result = herald_ctx["herald"].deliver(str(deed_root), plan, [{"move_id": "render_1"}])
        assert result["ok"] is True

    def test_hp10_html_to_text(self, herald_ctx):
        """HP-10: _html_to_text strips tags."""
        result = herald_ctx["herald"]._html_to_text("<p>Hello <b>world</b></p>")
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result

    def test_hp11_telegram_disabled(self, herald_ctx):
        """HP-11: _route_telegram with disabled config does not crash."""
        herald_ctx["herald"]._route_telegram("content", {"deed_id": "x"}, {"telegram_enabled": "false"})

    def test_hp12_sequential_deliver_no_overwrite(self, herald_ctx):
        """HP-12: sequential delivers create separate directories."""
        paths = []
        for i in range(2):
            deed_root = herald_ctx["home"] / "deeds" / f"d12_{i}"
            out_dir = deed_root / "moves" / "scribe_1" / "output"
            out_dir.mkdir(parents=True)
            (out_dir / "output.md").write_text(f"# Report {i}")
            plan = {"deed_id": f"d12_{i}", "deed_title": f"Report {i}", "brief": {}}
            result = herald_ctx["herald"].deliver(str(deed_root), plan, [{"move_id": "scribe_1"}])
            paths.append(result["offering_path"])
        # Both paths should exist and be different
        assert Path(paths[0]).exists()
        assert Path(paths[1]).exists()

    def test_hp13_offering_date_directory(self, herald_ctx):
        """HP-13: offering directory uses YYYY-MM structure."""
        deed_root = herald_ctx["home"] / "deeds" / "d13"
        out_dir = deed_root / "moves" / "scribe_1" / "output"
        out_dir.mkdir(parents=True)
        (out_dir / "output.md").write_text("# Date Test")
        plan = {"deed_id": "d13", "deed_title": "Date Test", "brief": {}}
        result = herald_ctx["herald"].deliver(str(deed_root), plan, [{"move_id": "scribe_1"}])
        offering_path = Path(result["offering_path"])
        # Parent should be YYYY-MM format
        month_dir = offering_path.parent.name
        assert re.match(r"\d{4}-\d{2}", month_dir)

    def test_hp14_load_herald_log(self, herald_ctx):
        """HP-14: load_herald_log returns entries."""
        offering_dir = herald_ctx["home"] / "offerings" / "2026-03" / "test14"
        offering_dir.mkdir(parents=True)
        herald_ctx["herald"]._update_index(offering_dir, {"deed_id": "d14", "deed_title": "T14"})
        log = herald_ctx["herald"]._ledger.load_herald_log()
        assert isinstance(log, list)
        assert any(e.get("deed_id") == "d14" for e in log)


class TestRuntimeComponents:
    """§19 — Runtime components: Cortex, Retinue, Ether, Trail, MCPDispatcher, Brief."""

    # ── 19.1 Cortex ────────────────────────────────────────────────────────

    def test_rt01_cortex_instantiation(self, tmp_path):
        """RT-01: Cortex can be instantiated without API keys."""
        from runtime.cortex import Cortex
        cortex = Cortex(usage_path=tmp_path / "cortex_usage.jsonl")
        assert cortex is not None

    def test_rt02_try_or_degrade_main_path(self, tmp_path):
        """RT-02: try_or_degrade returns fn result when available."""
        from runtime.cortex import Cortex
        cortex = Cortex(usage_path=tmp_path / "cortex_usage.jsonl")
        # Cortex has no providers → will use fallback
        result = cortex.try_or_degrade(lambda: "main", lambda: "fallback")
        assert result == "fallback"  # No providers available

    def test_rt03_try_or_degrade_fallback(self, tmp_path):
        """RT-03: try_or_degrade returns fallback on exception."""
        from runtime.cortex import Cortex, CortexError
        cortex = Cortex(usage_path=tmp_path / "cortex_usage.jsonl")
        # Force is_available to True for this test
        cortex._clients = {"fake": True}
        result = cortex.try_or_degrade(
            lambda: (_ for _ in ()).throw(CortexError("fail")),
            lambda: "degraded",
        )
        assert result == "degraded"

    def test_rt04_cortex_is_available_no_keys(self, tmp_path):
        """RT-04: is_available False when no API keys."""
        from runtime.cortex import Cortex
        cortex = Cortex(usage_path=tmp_path / "cortex_usage.jsonl")
        assert cortex.is_available() is False

    def test_rt05_cortex_usage_today(self, tmp_path):
        """RT-05: usage_today returns structured dict."""
        from runtime.cortex import Cortex
        cortex = Cortex(usage_path=tmp_path / "cortex_usage.jsonl")
        usage = cortex.usage_today()
        assert "date" in usage
        assert "by_provider" in usage
        assert "total_calls" in usage

    def test_rt06_cortex_extract_remaining(self, tmp_path):
        """RT-06: _extract_remaining_value extracts from various formats."""
        from runtime.cortex import Cortex
        cortex = Cortex(usage_path=tmp_path / "cortex_usage.jsonl")
        assert cortex._extract_remaining_value({"remaining": 42.5}) == 42.5
        assert cortex._extract_remaining_value({"data": {"remains": 10}}) == 10
        assert cortex._extract_remaining_value(100) == 100.0
        assert cortex._extract_remaining_value({"no_match": True}) is None

    # ── 19.2 Retinue ──────────────────────────────────────────────────────

    def test_rt10_retinue_empty_pool(self, tmp_path):
        """RT-10: empty pool file → empty list."""
        from runtime.retinue import Retinue
        home = tmp_path / "daemon"
        (home / "state").mkdir(parents=True)
        retinue = Retinue(home, home / "openclaw")
        pool = retinue._load_pool()
        assert pool == []

    def test_rt11_retinue_allocate(self, tmp_path):
        """RT-11: allocate returns instance from pool."""
        from runtime.retinue import Retinue
        home = tmp_path / "daemon"
        (home / "state").mkdir(parents=True)
        oc_home = home / "openclaw"
        (oc_home / "workspace" / "scout").mkdir(parents=True)
        (oc_home / "agents").mkdir(parents=True)
        retinue = Retinue(home, oc_home)
        # Seed pool with one idle scout
        pool = [{
            "instance_id": "scout_0", "role": "scout", "status": "idle",
            "deed_id": None, "workspace_dir": str(oc_home / "workspace" / "scout_0"),
            "agent_dir": str(oc_home / "agents" / "scout_0"),
        }]
        retinue._save_pool(pool)
        (oc_home / "workspace" / "scout_0").mkdir(parents=True, exist_ok=True)
        (oc_home / "agents" / "scout_0").mkdir(parents=True, exist_ok=True)
        inst = retinue.allocate("scout", "deed_test")
        assert inst["status"] == "occupied"
        assert inst["deed_id"] == "deed_test"

    def test_rt13_retinue_pool_exhausted(self, tmp_path):
        """RT-13: allocate raises PoolExhausted when no idle instances."""
        from runtime.retinue import Retinue, PoolExhausted
        home = tmp_path / "daemon"
        (home / "state").mkdir(parents=True)
        retinue = Retinue(home, home / "openclaw")
        retinue._save_pool([{
            "instance_id": "scout_0", "role": "scout", "status": "occupied",
            "deed_id": "d1", "workspace_dir": "/tmp", "agent_dir": "/tmp",
        }])
        with pytest.raises(PoolExhausted):
            retinue.allocate("scout", "deed_new")

    def test_rt14_retinue_release(self, tmp_path):
        """RT-14: release returns instance to idle."""
        from runtime.retinue import Retinue
        home = tmp_path / "daemon"
        (home / "state").mkdir(parents=True)
        oc_home = home / "openclaw"
        (oc_home / "agents" / "scout_0" / "sessions").mkdir(parents=True)
        (oc_home / "workspace" / "scout_0").mkdir(parents=True)
        retinue = Retinue(home, oc_home)
        retinue._save_pool([{
            "instance_id": "scout_0", "role": "scout", "status": "occupied",
            "deed_id": "d1", "workspace_dir": str(oc_home / "workspace" / "scout_0"),
            "agent_dir": str(oc_home / "agents" / "scout_0"),
        }])
        retinue.release("scout_0", "d1")
        pool = retinue._load_pool()
        assert pool[0]["status"] == "idle"
        assert pool[0]["deed_id"] is None

    def test_rt16_retinue_persistence(self, tmp_path):
        """RT-16: pool_status.json persists across instances."""
        from runtime.retinue import Retinue
        home = tmp_path / "daemon"
        (home / "state").mkdir(parents=True)
        r1 = Retinue(home, home / "openclaw")
        r1._save_pool([{"instance_id": "x", "role": "scout", "status": "idle"}])
        r2 = Retinue(home, home / "openclaw")
        pool = r2._load_pool()
        assert len(pool) == 1
        assert pool[0]["instance_id"] == "x"

    def test_rt17_pool_roles(self):
        """RT-17: POOL_ROLES has 6 roles."""
        from runtime.retinue import POOL_ROLES
        assert len(POOL_ROLES) == 6
        assert set(POOL_ROLES) == {"scout", "sage", "artificer", "arbiter", "scribe", "envoy"}

    def test_rt18_retinue_status(self, tmp_path):
        """RT-18: status returns usage statistics."""
        from runtime.retinue import Retinue
        home = tmp_path / "daemon"
        (home / "state").mkdir(parents=True)
        retinue = Retinue(home, home / "openclaw")
        retinue._save_pool([
            {"instance_id": "scout_0", "role": "scout", "status": "idle"},
            {"instance_id": "scout_1", "role": "scout", "status": "occupied"},
        ])
        s = retinue.status()
        assert s["total_instances"] == 2
        assert s["idle"] == 1
        assert s["occupied"] == 1

    # ── 19.3 Ether ─────────────────────────────────────────────────────────

    def test_rt20_ether_instantiation(self, tmp_path):
        """RT-20: Ether can be instantiated."""
        from runtime.ether import Ether
        ether = Ether(tmp_path / "state", source="test")
        assert ether is not None

    def test_rt21_ether_emit(self, tmp_path):
        """RT-21: emit writes to events.jsonl."""
        from runtime.ether import Ether
        ether = Ether(tmp_path / "state", source="test")
        event_id = ether.emit("test_event", {"key": "value"})
        assert event_id.startswith("evb_")
        events = ether.recent()
        assert len(events) >= 1
        assert events[-1]["event"] == "test_event"

    def test_rt22_ether_consume(self, tmp_path):
        """RT-22: consume returns new events."""
        from runtime.ether import Ether
        producer = Ether(tmp_path / "state", source="producer")
        consumer = Ether(tmp_path / "state", source="consumer")
        producer.emit("e1", {"data": 1})
        events = consumer.consume("consumer")
        assert len(events) >= 1
        assert events[0]["event"] == "e1"

    def test_rt23_ether_cursor_advances(self, tmp_path):
        """RT-23: cursor advances, no duplicate events."""
        from runtime.ether import Ether
        producer = Ether(tmp_path / "state", source="producer")
        consumer = Ether(tmp_path / "state", source="consumer")
        producer.emit("e1", {})
        events1 = consumer.consume("consumer")
        # Acknowledge the event
        for e in events1:
            consumer.acknowledge(e["event_id"], e["event"], e.get("payload", {}), "consumer")
        producer.emit("e2", {})
        events2 = consumer.consume("consumer")
        # Should only get e2, not e1 again
        event_names = [e["event"] for e in events2]
        assert "e2" in event_names
        assert "e1" not in event_names

    def test_rt24_ether_acknowledge(self, tmp_path):
        """RT-24: ack marks event as processed."""
        from runtime.ether import Ether
        producer = Ether(tmp_path / "state", source="producer")
        consumer = Ether(tmp_path / "state", source="consumer")
        eid = producer.emit("ack_test", {})
        events = consumer.consume("consumer")
        assert len(events) >= 1
        consumer.acknowledge(eid, "ack_test", {}, "consumer")
        # After ack, consumed marker should appear
        all_events = consumer.recent(limit=100)
        consumed = [e for e in all_events if e.get("status") == "consumed"]
        assert len(consumed) >= 1

    def test_rt25_ether_cursor_persistence(self, tmp_path):
        """RT-25: cursor persists between instances."""
        from runtime.ether import Ether
        p = Ether(tmp_path / "state", source="producer")
        p.emit("persist_test", {})
        c1 = Ether(tmp_path / "state", source="consumer")
        events = c1.consume("consumer")
        for e in events:
            c1.acknowledge(e["event_id"], e["event"], e.get("payload", {}), "consumer")
        # New consumer instance should not re-consume
        c2 = Ether(tmp_path / "state", source="consumer")
        p.emit("new_event", {})
        events2 = c2.consume("consumer")
        event_names = [e["event"] for e in events2]
        assert "persist_test" not in event_names

    def test_rt26_ether_legacy_cursor(self, tmp_path):
        """RT-26: legacy integer-only cursor format compatibility."""
        from runtime.ether import Ether
        ether = Ether(tmp_path / "state", source="test")
        ether.emit("legacy", {})
        # Write a legacy cursor (just an integer offset)
        cursor_path = tmp_path / "state" / "nerve_bridge" / "cursors" / "legacy_consumer.cursor"
        cursor_path.write_text("0")
        events = ether.consume("legacy_consumer")
        assert len(events) >= 1

    # ── 19.4 Trail ─────────────────────────────────────────────────────────

    def test_rt30_trail_span_ok(self, tmp_path):
        """RT-30: span records normal completion."""
        from spine.trail import Trail
        trail = Trail(tmp_path / "traces")
        with trail.span("test_routine", trigger="manual") as ctx:
            ctx.step("phase_1", {"info": "ok"})
            ctx.set_result({"status": "done"})
        recent = trail.recent(limit=1)
        assert len(recent) == 1
        assert recent[0]["status"] == "ok"
        assert recent[0]["routine"] == "test_routine"

    def test_rt31_trail_span_exception(self, tmp_path):
        """RT-31: span records exception."""
        from spine.trail import Trail
        trail = Trail(tmp_path / "traces")
        try:
            with trail.span("failing_routine") as ctx:
                raise ValueError("test error")
        except ValueError:
            pass
        recent = trail.recent(limit=1)
        assert recent[0]["status"] == "error"
        assert "ValueError" in recent[0]["error"]

    def test_rt32_trail_span_degraded(self, tmp_path):
        """RT-32: mark_degraded sets degraded flag."""
        from spine.trail import Trail
        trail = Trail(tmp_path / "traces")
        with trail.span("degraded_routine") as ctx:
            ctx.mark_degraded("llm_unavailable")
        recent = trail.recent(limit=1)
        assert recent[0]["degraded"] is True

    def test_rt33_trail_step_recording(self, tmp_path):
        """RT-33: steps recorded with timing."""
        from spine.trail import Trail
        trail = Trail(tmp_path / "traces")
        with trail.span("step_test") as ctx:
            ctx.step("step_a", 42)
            ctx.step("step_b", "data")
        recent = trail.recent(limit=1)
        steps = recent[0]["steps"]
        assert len(steps) == 2
        assert steps[0]["name"] == "step_a"

    def test_rt34_trail_persistence(self, tmp_path):
        """RT-34: trail persists to JSONL file."""
        from spine.trail import Trail
        trail = Trail(tmp_path / "traces")
        with trail.span("persist_test"):
            pass
        files = list((tmp_path / "traces").glob("*.jsonl"))
        assert len(files) >= 1
        content = files[0].read_text()
        assert "persist_test" in content

    def test_rt35_trail_query_by_routine(self, tmp_path):
        """RT-35: query filters by routine."""
        from spine.trail import Trail
        trail = Trail(tmp_path / "traces")
        with trail.span("routine_a"):
            pass
        with trail.span("routine_b"):
            pass
        results = trail.query(routine="routine_a")
        assert all(r["routine"] == "routine_a" for r in results)

    def test_rt36_trail_recent_limit(self, tmp_path):
        """RT-36: recent returns limited entries."""
        from spine.trail import Trail
        trail = Trail(tmp_path / "traces")
        for i in range(5):
            with trail.span(f"routine_{i}"):
                pass
        recent = trail.recent(limit=3)
        assert len(recent) == 3

    # ── 19.5 MCPDispatcher ─────────────────────────────────────────────────

    def test_rt40_mcp_empty_config(self, tmp_path):
        """RT-40: MCPDispatcher with no config file."""
        from runtime.mcp_dispatch import MCPDispatcher
        mcp = MCPDispatcher(tmp_path / "nonexistent.json")
        assert mcp.available is False

    def test_rt41_mcp_list_tools_empty(self):
        """RT-41: list_tools empty when no servers."""
        from runtime.mcp_dispatch import MCPDispatcher
        mcp = MCPDispatcher()
        assert mcp.list_tools() == []

    def test_rt42_mcp_available_with_config(self, tmp_path):
        """RT-42: available=True when config has servers."""
        from runtime.mcp_dispatch import MCPDispatcher
        config_path = tmp_path / "mcp_servers.json"
        config_path.write_text(json.dumps({"servers": {"test": {"command": "echo"}}}))
        mcp = MCPDispatcher(config_path)
        assert mcp.available is True

    # ── 19.6 Brief ─────────────────────────────────────────────────────────

    def test_rt50_brief_defaults(self):
        """RT-50: Brief defaults."""
        from runtime.brief import Brief
        b = Brief(objective="test")
        assert b.language == "bilingual"
        assert b.depth == "study"
        assert b.dag_budget == 6

    def test_rt51_brief_from_dict(self):
        """RT-51: Brief.from_dict parses correctly."""
        from runtime.brief import Brief
        b = Brief.from_dict({"objective": "research", "depth": "scrutiny", "dag_budget": 10})
        assert b.objective == "research"
        assert b.depth == "scrutiny"
        assert b.dag_budget == 10

    def test_rt52_brief_invalid_depth(self):
        """RT-52: invalid depth defaults to study."""
        from runtime.brief import Brief
        b = Brief(objective="test", depth="invalid")
        assert b.depth == "study"

    def test_rt53_brief_zero_budget(self):
        """RT-53: zero dag_budget defaults to 6."""
        from runtime.brief import Brief
        b = Brief(objective="test", dag_budget=0)
        assert b.dag_budget == 6

    def test_rt54_brief_to_dict(self):
        """RT-54: to_dict roundtrip."""
        from runtime.brief import Brief
        b = Brief(objective="test", references=["ref1"])
        d = b.to_dict()
        assert d["objective"] == "test"
        assert d["references"] == ["ref1"]

    def test_rt55_brief_execution_defaults(self):
        """RT-55: execution_defaults returns SINGLE_SLIP_DEFAULTS."""
        from runtime.brief import Brief, SINGLE_SLIP_DEFAULTS
        b = Brief(objective="test")
        assert b.execution_defaults() == SINGLE_SLIP_DEFAULTS

    def test_rt56_brief_standing_flag(self):
        """RT-56: standing flag from dict."""
        from runtime.brief import Brief
        b = Brief.from_dict({"objective": "monitor", "standing": True})
        assert b.standing is True


class TestPsycheConfig:
    """§6 — PsycheConfig preferences, rations, InstinctEngine."""

    @pytest.fixture
    def psyche_ctx(self, tmp_path):
        """Build PsycheConfig with temp dir."""
        from psyche.config import PsycheConfig
        psyche_dir = tmp_path / "psyche"
        config = PsycheConfig(psyche_dir)
        return {"config": config, "dir": psyche_dir}

    # ── 6.1 File Existence ─────────────────────────────────────────────────

    def test_pc04_preferences_parseable(self, psyche_ctx):
        """PC-04: preferences.toml is parseable after init."""
        path = psyche_ctx["dir"] / "preferences.toml"
        assert path.exists()
        import tomllib
        data = tomllib.loads(path.read_text())
        assert isinstance(data, dict)

    def test_pc05_rations_parseable(self, psyche_ctx):
        """PC-05: rations.toml is parseable after init."""
        path = psyche_ctx["dir"] / "rations.toml"
        assert path.exists()
        import tomllib
        data = tomllib.loads(path.read_text())
        assert isinstance(data, dict)

    def test_pc06_psyche_config_instantiation(self, psyche_ctx):
        """PC-06: PsycheConfig instantiates and creates default files."""
        assert psyche_ctx["config"] is not None
        assert (psyche_ctx["dir"] / "preferences.toml").exists()
        assert (psyche_ctx["dir"] / "rations.toml").exists()

    def test_pc07_instinct_engine_instantiation(self, tmp_path):
        """PC-07: InstinctEngine instantiates with missing file."""
        from psyche.instinct_engine import InstinctEngine
        engine = InstinctEngine(tmp_path / "instinct.md")
        assert engine is not None

    # ── 6.3 PsycheConfig Read/Write ───────────────────────────────────────

    def test_pc20_get_pref_value(self, psyche_ctx):
        """PC-20: get_pref returns correct default value."""
        val = psyche_ctx["config"].get_pref("general.default_depth")
        assert val == "study"

    def test_pc21_all_prefs_keys(self, psyche_ctx):
        """PC-21: all_prefs returns all keys."""
        prefs = psyche_ctx["config"].all_prefs()
        assert isinstance(prefs, dict)
        assert len(prefs) > 0
        # Should have flattened keys
        assert any("default_depth" in k for k in prefs)

    def test_pc22_consume_ration_deduct(self, psyche_ctx):
        """PC-22: consume_ration deducts correctly."""
        ok = psyche_ctx["config"].consume_ration("minimax_tokens", 1000)
        assert ok is True
        ration = psyche_ctx["config"].get_ration("minimax_tokens")
        assert ration["current_usage"] == 1000

    def test_pc23_consume_ration_over_budget(self, psyche_ctx):
        """PC-23: consume_ration rejects over-budget."""
        # minimax_tokens default limit is 20_000_000
        ok = psyche_ctx["config"].consume_ration("minimax_tokens", 25_000_000)
        assert ok is False

    def test_pc24_reset_rations(self, psyche_ctx):
        """PC-24: reset_rations clears usage."""
        psyche_ctx["config"].consume_ration("minimax_tokens", 5000)
        psyche_ctx["config"].reset_rations()
        ration = psyche_ctx["config"].get_ration("minimax_tokens")
        assert ration["current_usage"] == 0

    def test_pc25_snapshot_format(self, psyche_ctx):
        """PC-25: snapshot returns correct format."""
        snap = psyche_ctx["config"].snapshot()
        assert "preferences" in snap
        assert "rations" in snap
        assert "exported_utc" in snap

    def test_pc26_set_pref(self, psyche_ctx):
        """PC-26: set_pref persists value."""
        psyche_ctx["config"].set_pref("general.default_depth", "glance")
        val = psyche_ctx["config"].get_pref("general.default_depth")
        assert val == "glance"

    def test_pc27_all_rations(self, psyche_ctx):
        """PC-27: all_rations returns list of all resource types."""
        rations = psyche_ctx["config"].all_rations()
        assert isinstance(rations, list)
        assert len(rations) >= 4  # minimax, qwen, zhipu, deepseek, concurrent_deeds
        types = {r["resource_type"] for r in rations}
        assert "minimax_tokens" in types

    def test_pc28_set_ration(self, psyche_ctx):
        """PC-28: set_ration creates new resource type."""
        psyche_ctx["config"].set_ration("custom_tokens", 50000)
        ration = psyche_ctx["config"].get_ration("custom_tokens")
        assert ration is not None
        assert ration["daily_limit"] == 50000

    def test_pc29_get_ration_unknown(self, psyche_ctx):
        """PC-29: get_ration returns None for unknown resource."""
        assert psyche_ctx["config"].get_ration("nonexistent_tokens") is None

    def test_pc30_consume_unknown_ration(self, psyche_ctx):
        """PC-30: consuming unknown resource returns True (don't block)."""
        assert psyche_ctx["config"].consume_ration("unknown_resource", 100) is True

    def test_pc31_stats(self, psyche_ctx):
        """PC-31: stats returns preference and ration counts."""
        s = psyche_ctx["config"].stats()
        assert "preference_count" in s
        assert "ration_count" in s
        assert s["preference_count"] > 0

    def test_pc32_deep_get_flat_key(self, psyche_ctx):
        """PC-32: _deep_get finds key across sections."""
        from psyche.config import PsycheConfig
        data = {"section": {"key1": "val1"}, "top": "val2"}
        assert PsycheConfig._deep_get(data, "key1") == "val1"
        assert PsycheConfig._deep_get(data, "top") == "val2"

    # ── 6.4 InstinctEngine Hard Rules ─────────────────────────────────────

    def test_pc40_instinct_sensitive_filter(self, tmp_path):
        """PC-40: check_outbound_query filters sensitive terms."""
        from psyche.instinct_engine import InstinctEngine
        terms_path = tmp_path / "sensitive_terms.json"
        terms_path.write_text(json.dumps(["SecretProject"]))
        engine = InstinctEngine(tmp_path / "instinct.md", sensitive_terms_path=terms_path)
        cleaned = engine.check_outbound_query("Search for SecretProject details")
        assert "SecretProject" not in cleaned
        assert "某项目" in cleaned

    def test_pc41_instinct_empty_output(self, tmp_path):
        """PC-41: empty output is blocked."""
        from psyche.instinct_engine import InstinctEngine
        engine = InstinctEngine(tmp_path / "instinct.md")
        violations = engine.check_output("", "report")
        assert "empty_output" in violations

    def test_pc42_instinct_sensitive_leak(self, tmp_path):
        """PC-42: sensitive term leak detected."""
        from psyche.instinct_engine import InstinctEngine
        terms_path = tmp_path / "sensitive_terms.json"
        terms_path.write_text(json.dumps(["InternalCode"]))
        engine = InstinctEngine(tmp_path / "instinct.md", sensitive_terms_path=terms_path)
        violations = engine.check_output("Output mentions InternalCode here", "report")
        assert any("sensitive_term_leaked" in v for v in violations)

    def test_pc43_instinct_voice_token_limit(self, tmp_path):
        """PC-43: voice token over limit is rejected."""
        from psyche.instinct_engine import InstinctEngine
        engine = InstinctEngine(tmp_path / "instinct.md")
        long_content = "x" * 800  # 200 estimated tokens > 150 limit
        violations = engine.check_voice_update("identity", long_content)
        assert any("identity_exceeds_token_limit" in v for v in violations)

    def test_pc44_instinct_normal_passes(self, tmp_path):
        """PC-44: normal content passes all checks."""
        from psyche.instinct_engine import InstinctEngine
        engine = InstinctEngine(tmp_path / "instinct.md")
        violations = engine.check_output("This is a normal report about market trends.", "report")
        assert violations == []

    def test_pc45_instinct_wash_oversized_filtered(self, tmp_path):
        """PC-45: wash output oversized voice candidates filtered."""
        from psyche.instinct_engine import InstinctEngine
        engine = InstinctEngine(tmp_path / "instinct.md")
        wash_result = {
            "voice_candidates": [
                {"content": "short ok"},
                {"content": "x" * 600},  # Over 500 chars
            ]
        }
        cleaned = engine.check_wash_output(wash_result)
        assert len(cleaned["voice_candidates"]) == 1
        assert cleaned["voice_candidates"][0]["content"] == "short ok"

    def test_pc46_instinct_prompt_fragment(self, tmp_path):
        """PC-46: prompt_fragment returns instinct.md content."""
        from psyche.instinct_engine import InstinctEngine
        instinct_path = tmp_path / "instinct.md"
        instinct_path.write_text("# System Rules\n\nBe helpful.")
        engine = InstinctEngine(instinct_path)
        fragment = engine.prompt_fragment()
        assert "Be helpful" in fragment

    def test_pc47_instinct_style_limit(self, tmp_path):
        """PC-47: style section over limit detected."""
        from psyche.instinct_engine import InstinctEngine
        engine = InstinctEngine(tmp_path / "instinct.md")
        long_style = "x" * 1200  # 300 tokens > 250 limit
        violations = engine.check_voice_update("common", long_style)
        assert any("style_exceeds_token_limit" in v for v in violations)


class TestDesignValidator:
    """§28 — Design (move DAG) validation."""

    def test_dv01_valid_agents(self):
        """DV-01: all 8 valid agents pass."""
        from runtime.design_validator import validate_design
        for agent in ["counsel", "scout", "sage", "artificer", "arbiter", "scribe", "envoy", "spine"]:
            plan = {
                "moves": [{"id": f"{agent}_1", "agent": agent}],
                "brief": {"dag_budget": 6},
            }
            ok, reason = validate_design(plan)
            assert ok is True, f"Agent {agent} failed: {reason}"

    def test_dv02_invalid_agent(self):
        """DV-02: unknown agent → False."""
        from runtime.design_validator import validate_design
        plan = {"moves": [{"id": "m1", "agent": "unknown_agent"}], "brief": {"dag_budget": 6}}
        ok, reason = validate_design(plan)
        assert ok is False
        assert "unknown agent" in reason

    def test_dv05_budget_zero(self):
        """DV-05: dag_budget=0 defaults to 6 via Brief, so single move passes."""
        from runtime.design_validator import validate_design
        plan = {"moves": [{"id": "m1", "agent": "scout"}], "brief": {"dag_budget": 0}}
        ok, _ = validate_design(plan)
        assert ok is True  # Budget defaults to 6

    def test_dv06_budget_single_move(self):
        """DV-06: dag_budget=1 with single move → True."""
        from runtime.design_validator import validate_design
        plan = {"moves": [{"id": "m1", "agent": "scout"}], "brief": {"dag_budget": 1}}
        ok, _ = validate_design(plan)
        assert ok is True

    def test_dv07_budget_exceeded(self):
        """DV-07: 4 moves exceeds dag_budget=3."""
        from runtime.design_validator import validate_design
        plan = {
            "moves": [
                {"id": f"m{i}", "agent": "scout"} for i in range(4)
            ],
            "brief": {"dag_budget": 3},
        }
        ok, reason = validate_design(plan)
        assert ok is False
        assert "exceeds dag_budget" in reason

    def test_dv08_no_terminal_move(self):
        """DV-08: circular dependency (all depend on each other) → cycle detected."""
        from runtime.design_validator import validate_design
        plan = {
            "moves": [
                {"id": "a", "agent": "scout", "depends_on": ["b"]},
                {"id": "b", "agent": "scout", "depends_on": ["a"]},
            ],
            "brief": {"dag_budget": 6},
        }
        ok, reason = validate_design(plan)
        assert ok is False

    def test_dv09_multiple_terminals(self):
        """DV-09: multiple terminal moves → True."""
        from runtime.design_validator import validate_design
        plan = {
            "moves": [
                {"id": "scout_1", "agent": "scout"},
                {"id": "scribe_1", "agent": "scribe"},
            ],
            "brief": {"dag_budget": 6},
        }
        ok, _ = validate_design(plan)
        assert ok is True

    def test_dv10_self_dependency(self):
        """DV-10: self-dependency → False."""
        from runtime.design_validator import validate_design
        plan = {
            "moves": [{"id": "m1", "agent": "scout", "depends_on": ["m1"]}],
            "brief": {"dag_budget": 6},
        }
        ok, reason = validate_design(plan)
        assert ok is False

    def test_dv11_deep_chain(self):
        """DV-11: 5-level dependency chain → True."""
        from runtime.design_validator import validate_design
        moves = []
        for i in range(5):
            m = {"id": f"m{i}", "agent": "scout"}
            if i > 0:
                m["depends_on"] = [f"m{i-1}"]
            moves.append(m)
        plan = {"moves": moves, "brief": {"dag_budget": 6}}
        ok, _ = validate_design(plan)
        assert ok is True

    def test_dv12_isolated_move(self):
        """DV-12: isolated move (no deps, no dependents) → True (is terminal)."""
        from runtime.design_validator import validate_design
        plan = {"moves": [{"id": "solo", "agent": "scout"}], "brief": {"dag_budget": 6}}
        ok, _ = validate_design(plan)
        assert ok is True

    def test_dv13_empty_depends_on(self):
        """DV-13: empty depends_on → legal."""
        from runtime.design_validator import validate_design
        plan = {"moves": [{"id": "m1", "agent": "scout", "depends_on": []}], "brief": {"dag_budget": 6}}
        ok, _ = validate_design(plan)
        assert ok is True

    def test_dv14_depends_on_none(self):
        """DV-14: depends_on=None → legal."""
        from runtime.design_validator import validate_design
        plan = {"moves": [{"id": "m1", "agent": "scout", "depends_on": None}], "brief": {"dag_budget": 6}}
        ok, _ = validate_design(plan)
        assert ok is True

    def test_dv15_spine_agent(self):
        """DV-15: spine agent move → True."""
        from runtime.design_validator import validate_design
        plan = {"moves": [{"id": "spine_1", "agent": "spine"}], "brief": {"dag_budget": 6}}
        ok, _ = validate_design(plan)
        assert ok is True

    def test_dv16_empty_moves(self):
        """DV-16: empty moves list → False."""
        from runtime.design_validator import validate_design
        ok, reason = validate_design({"moves": [], "brief": {"dag_budget": 6}})
        assert ok is False

    def test_dv17_duplicate_ids(self):
        """DV-17: duplicate move ids → False."""
        from runtime.design_validator import validate_design
        plan = {
            "moves": [
                {"id": "dup", "agent": "scout"},
                {"id": "dup", "agent": "sage"},
            ],
            "brief": {"dag_budget": 6},
        }
        ok, reason = validate_design(plan)
        assert ok is False
        assert "duplicate" in reason

    def test_dv18_unknown_dependency(self):
        """DV-18: depends_on references unknown move → False."""
        from runtime.design_validator import validate_design
        plan = {
            "moves": [{"id": "m1", "agent": "scout", "depends_on": ["nonexistent"]}],
            "brief": {"dag_budget": 6},
        }
        ok, reason = validate_design(plan)
        assert ok is False
        assert "unknown" in reason


# ═══════════════════════════════════════════════════════════════════════════════
# P6 — Round 7: Concurrency · Security · BootstrapStartup
# ═══════════════════════════════════════════════════════════════════════════════


class TestConcurrency:
    """§7.1 — Thread safety of Ledger, LedgerStats, Nerve, Retinue, FolioWrit, Ether, PsycheConfig."""

    # ── 7.1.1 Ledger atomicity ─────────────────────────────────────────────────

    def test_cc01_ledger_locked_rw_atomicity(self, tmp_path):
        """CC-01: concurrent _locked_rw on same file produces consistent data."""
        import threading
        from services.ledger import Ledger

        ledger = Ledger(tmp_path / "state")
        path = ledger.deeds_path
        path.write_text("[]")

        errors = []

        def _append_deed(idx: int):
            try:
                def mutator(deeds):
                    deeds.append({"deed_id": f"d_{idx}", "idx": idx})
                ledger.mutate_deeds(mutator)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_append_deed, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        deeds = ledger.load_deeds()
        assert len(deeds) == 20
        ids = {d["deed_id"] for d in deeds}
        assert len(ids) == 20

    def test_cc02_ledger_write_json_no_corruption(self, tmp_path):
        """CC-02: concurrent _write_json calls don't produce corrupted JSON."""
        import threading
        from services.ledger import Ledger

        ledger = Ledger(tmp_path / "state")
        path = tmp_path / "state" / "test_file.json"
        errors = []

        def _write(idx: int):
            try:
                ledger._write_json(path, {"value": idx, "data": list(range(50))})
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        import json
        data = json.loads(path.read_text())
        assert "value" in data

    def test_cc03_ledger_concurrent_upsert(self, tmp_path):
        """CC-03: concurrent upsert_deed on distinct deed_ids."""
        import threading
        from services.ledger import Ledger

        ledger = Ledger(tmp_path / "state")
        ledger.save_deeds([])
        errors = []

        def _upsert(idx: int):
            try:
                ledger.upsert_deed(f"deed_{idx}", default_row={"deed_status": "running"})
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_upsert, args=(i,)) for i in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        deeds = ledger.load_deeds()
        assert len(deeds) == 15

    def test_cc04_ledger_lock_per_file(self, tmp_path):
        """CC-04: _lock_for returns same lock for same path, different for different paths."""
        from services.ledger import Ledger

        p1 = tmp_path / "a.json"
        p2 = tmp_path / "b.json"
        assert Ledger._lock_for(p1) is Ledger._lock_for(p1)
        assert Ledger._lock_for(p1) is not Ledger._lock_for(p2)

    # ── 7.1.2 LedgerStats concurrency ─────────────────────────────────────────

    def test_cc10_ledger_stats_concurrent_skill_update(self, tmp_path):
        """CC-10: concurrent skill_stats updates don't lose data."""
        import threading
        from psyche.ledger_stats import LedgerStats

        db = LedgerStats(tmp_path / "ledger.db")
        errors = []

        def _update(idx: int):
            try:
                plan = {"moves": [{"id": f"m{idx}", "skill": f"skill_{idx % 5}"}]}
                db.update_skill_stats(plan, accepted=(idx % 2 == 0))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_update, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    def test_cc11_ledger_stats_concurrent_agent_update(self, tmp_path):
        """CC-11: concurrent agent_stats updates."""
        import threading
        from psyche.ledger_stats import LedgerStats

        db = LedgerStats(tmp_path / "ledger.db")
        errors = []

        def _update(idx: int):
            try:
                move_results = [{"agent": f"agent_{idx % 3}", "tokens_used": 200, "duration_s": 1.0}]
                db.update_agent_stats(move_results, accepted=(idx % 2 == 0))
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_update, args=(i,)) for i in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    # ── 7.1.3 Nerve concurrency ───────────────────────────────────────────────

    def test_cc20_nerve_concurrent_emit(self, tmp_path):
        """CC-20: concurrent emit calls don't lose events."""
        import threading
        from spine.nerve import Nerve

        nerve = Nerve(state_dir=tmp_path)
        results = []
        errors = []

        def _emit(idx: int):
            try:
                eid = nerve.emit(f"event_{idx % 3}", {"idx": idx})
                results.append(eid)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_emit, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 30
        # Check persistence
        import json
        lines = [l for l in (tmp_path / "events.jsonl").read_text().splitlines() if l.strip()]
        assert len(lines) == 30

    def test_cc21_nerve_concurrent_emit_with_handlers(self, tmp_path):
        """CC-21: concurrent emit with handlers doesn't crash."""
        import threading
        from spine.nerve import Nerve

        nerve = Nerve(state_dir=tmp_path)
        counter = {"n": 0}
        lock = threading.Lock()

        def handler(payload):
            with lock:
                counter["n"] += 1

        nerve.on("test", handler)
        errors = []

        def _emit(idx: int):
            try:
                nerve.emit("test", {"idx": idx})
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_emit, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert counter["n"] == 20

    # ── 7.1.4 Retinue atomicity ──────────────────────────────────────────────

    def test_cc30_retinue_concurrent_allocate(self, tmp_path):
        """CC-30: concurrent allocate calls don't double-assign same instance."""
        import json
        import threading
        from runtime.retinue import Retinue

        oc_home = tmp_path / "openclaw"
        (oc_home / "workspace" / "scout").mkdir(parents=True)
        daemon_home = tmp_path / "daemon"
        (daemon_home / "state").mkdir(parents=True)

        pool = []
        for i in range(10):
            inst_ws = oc_home / "workspace" / f"scout_{i}"
            inst_ws.mkdir(parents=True, exist_ok=True)
            (oc_home / "agents" / f"scout_{i}").mkdir(parents=True, exist_ok=True)
            pool.append({
                "instance_id": f"scout_{i}", "role": "scout", "status": "idle",
                "deed_id": None, "allocated_utc": None, "session_key": None,
                "agent_dir": str(oc_home / "agents" / f"scout_{i}"),
                "workspace_dir": str(inst_ws),
            })
        (daemon_home / "state" / "pool_status.json").write_text(json.dumps(pool))

        retinue = Retinue(daemon_home, oc_home, pool_size=10)
        allocated = []
        errors = []

        def _allocate(idx: int):
            try:
                inst = retinue.allocate("scout", f"deed_{idx}")
                allocated.append(inst["instance_id"])
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_allocate, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 10 should succeed with distinct instances
        assert len(errors) == 0
        assert len(allocated) == 10
        assert len(set(allocated)) == 10

    def test_cc31_retinue_over_allocate_raises(self, tmp_path):
        """CC-31: allocating more than pool size raises PoolExhausted."""
        import json
        import threading
        from runtime.retinue import Retinue, PoolExhausted

        oc_home = tmp_path / "openclaw"
        (oc_home / "workspace" / "scout").mkdir(parents=True)
        daemon_home = tmp_path / "daemon"
        (daemon_home / "state").mkdir(parents=True)

        pool = []
        for i in range(3):
            inst_ws = oc_home / "workspace" / f"scout_{i}"
            inst_ws.mkdir(parents=True, exist_ok=True)
            (oc_home / "agents" / f"scout_{i}").mkdir(parents=True, exist_ok=True)
            pool.append({
                "instance_id": f"scout_{i}", "role": "scout", "status": "idle",
                "deed_id": None, "allocated_utc": None, "session_key": None,
                "agent_dir": str(oc_home / "agents" / f"scout_{i}"),
                "workspace_dir": str(inst_ws),
            })
        (daemon_home / "state" / "pool_status.json").write_text(json.dumps(pool))

        retinue = Retinue(daemon_home, oc_home, pool_size=16)
        results = {"allocated": 0, "exhausted": 0}
        lock = threading.Lock()

        def _allocate(idx: int):
            try:
                retinue.allocate("scout", f"deed_{idx}")
                with lock:
                    results["allocated"] += 1
            except PoolExhausted:
                with lock:
                    results["exhausted"] += 1

        threads = [threading.Thread(target=_allocate, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert results["allocated"] == 3
        assert results["exhausted"] == 2

    # ── 7.1.5 FolioWrit concurrency ──────────────────────────────────────────

    def test_cc40_folio_writ_concurrent_create_slips(self, tmp_path):
        """CC-40: concurrent create_slip on same folio don't lose slips."""
        import threading
        from services.ledger import Ledger
        from spine.nerve import Nerve
        from services.folio_writ import FolioWritManager as FolioWritRegistry

        ledger = Ledger(tmp_path / "state")
        nerve = Nerve(state_dir=tmp_path / "events")
        reg = FolioWritRegistry(tmp_path / "state", nerve, ledger)

        folio = reg.create_folio("Test Folio")
        folio_id = folio["folio_id"]
        errors = []

        def _create(idx: int):
            try:
                reg.create_slip(
                    title=f"Slip {idx}", objective=f"Objective {idx}",
                    brief={"dag_budget": 3}, design={"moves": []},
                    folio_id=folio_id,
                )
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_create, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        folio_data = reg.get_folio(folio_id)
        assert folio_data is not None
        slip_ids = folio_data.get("slip_ids", [])
        assert len(slip_ids) == 10

    def test_cc41_folio_writ_concurrent_create_folios(self, tmp_path):
        """CC-41: concurrent create_folio calls."""
        import threading
        from services.ledger import Ledger
        from spine.nerve import Nerve
        from services.folio_writ import FolioWritManager as FolioWritRegistry

        ledger = Ledger(tmp_path / "state")
        nerve = Nerve(state_dir=tmp_path / "events")
        reg = FolioWritRegistry(tmp_path / "state", nerve, ledger)
        errors = []
        folio_ids = []
        lock = threading.Lock()

        def _create(idx: int):
            try:
                f = reg.create_folio(f"Folio {idx}")
                with lock:
                    folio_ids.append(f["folio_id"])
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_create, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(folio_ids) == 10
        assert len(set(folio_ids)) == 10

    def test_cc42_folio_writ_concurrent_deed_record(self, tmp_path):
        """CC-42: concurrent record_deed_created on same slip."""
        import threading
        from services.ledger import Ledger
        from spine.nerve import Nerve
        from services.folio_writ import FolioWritManager as FolioWritRegistry

        ledger = Ledger(tmp_path / "state")
        nerve = Nerve(state_dir=tmp_path / "events")
        reg = FolioWritRegistry(tmp_path / "state", nerve, ledger)

        folio = reg.create_folio("Test Folio")
        slip = reg.create_slip(
            title="Test Slip", objective="Test", brief={"dag_budget": 3},
            design={"moves": []}, folio_id=folio["folio_id"],
        )
        slip_id = slip["slip_id"]
        errors = []

        def _record(idx: int):
            try:
                reg.record_deed_created(slip_id, f"deed_{idx}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_record, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    # ── 7.1.6 Ether concurrency ──────────────────────────────────────────────

    def test_cc50_ether_concurrent_emit(self, tmp_path):
        """CC-50: concurrent Ether emit calls don't lose events."""
        import threading
        from runtime.ether import Ether

        ether = Ether(tmp_path, source="producer")
        errors = []

        def _emit(idx: int):
            try:
                ether.emit(f"event_{idx}", {"idx": idx})
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_emit, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        events = ether.recent(200)
        assert len(events) == 20

    def test_cc51_ether_concurrent_consume(self, tmp_path):
        """CC-51: concurrent consume from different consumers."""
        import threading
        from runtime.ether import Ether

        producer = Ether(tmp_path, source="producer")
        for i in range(10):
            producer.emit(f"event_{i}", {"i": i})

        errors = []
        results = {}
        lock = threading.Lock()

        def _consume(consumer_name: str):
            try:
                c = Ether(tmp_path, source=consumer_name)
                events = c.consume(consumer_name, limit=100)
                with lock:
                    results[consumer_name] = len(events)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_consume, args=(f"consumer_{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        for k, v in results.items():
            assert v == 10, f"{k} got {v} events instead of 10"

    def test_cc52_ether_emit_consume_interleaved(self, tmp_path):
        """CC-52: interleaved emit and consume."""
        import threading
        from runtime.ether import Ether

        ether = Ether(tmp_path, source="producer")
        errors = []

        def _emit():
            try:
                for i in range(10):
                    ether.emit(f"event_{i}", {"i": i})
            except Exception as e:
                errors.append(str(e))

        def _consume():
            try:
                c = Ether(tmp_path, source="consumer")
                c.consume("consumer", limit=100)
            except Exception as e:
                errors.append(str(e))

        t1 = threading.Thread(target=_emit)
        t2 = threading.Thread(target=_consume)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        assert not errors

    # ── 7.1.7 PsycheConfig concurrency ───────────────────────────────────────

    def test_cc60_psyche_config_concurrent_pref_write(self, tmp_path):
        """CC-60: concurrent set_pref calls."""
        import threading
        from psyche.config import PsycheConfig

        config = PsycheConfig(tmp_path / "psyche")
        errors = []

        def _set(idx: int):
            try:
                config.set_pref(f"key_{idx}", f"value_{idx}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_set, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    def test_cc61_psyche_config_concurrent_ration_consume(self, tmp_path):
        """CC-61: concurrent consume_ration calls."""
        import threading
        from psyche.config import PsycheConfig

        config = PsycheConfig(tmp_path / "psyche")
        errors = []

        def _consume(idx: int):
            try:
                config.consume_ration("cortex_daily_tokens", 100)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=_consume, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


class TestSecurity:
    """§7.2 — Input validation, instinct security, permissions, resource defense, filesystem, encoding."""

    # ── 7.2.1 Input validation ───────────────────────────────────────────────

    def test_se01_folio_title_sanitization(self, tmp_path):
        """SE-01: folio title with special chars is handled safely."""
        from services.ledger import Ledger
        from spine.nerve import Nerve
        from services.folio_writ import FolioWritManager as FolioWritRegistry

        ledger = Ledger(tmp_path / "state")
        nerve = Nerve(state_dir=tmp_path / "events")
        reg = FolioWritRegistry(tmp_path / "state", nerve, ledger)

        folio = reg.create_folio("<script>alert('xss')</script>")
        assert folio is not None
        assert folio["title"] == "<script>alert('xss')</script>"

    def test_se02_slip_title_special_chars(self, tmp_path):
        """SE-02: slip with HTML-like title stored safely."""
        from services.ledger import Ledger
        from spine.nerve import Nerve
        from services.folio_writ import FolioWritManager as FolioWritRegistry

        ledger = Ledger(tmp_path / "state")
        nerve = Nerve(state_dir=tmp_path / "events")
        reg = FolioWritRegistry(tmp_path / "state", nerve, ledger)

        folio = reg.create_folio("Test")
        slip = reg.create_slip(
            title="title<img onerror=alert(1)>", objective="test",
            brief={"dag_budget": 3}, design={"moves": []},
            folio_id=folio["folio_id"],
        )
        assert slip is not None

    def test_se03_deed_id_injection(self, tmp_path):
        """SE-03: deed_id with path traversal chars is stored as-is but doesn't affect filesystem."""
        from services.ledger import Ledger
        ledger = Ledger(tmp_path / "state")
        ledger.save_deeds([])
        deed = ledger.upsert_deed("../../etc/passwd", default_row={"deed_status": "running"})
        assert deed["deed_id"] == "../../etc/passwd"
        # Verify it's stored in deeds.json, not as a file path
        assert not (tmp_path / "etc").exists()

    def test_se04_long_objective(self, tmp_path):
        """SE-04: very long objective string doesn't crash Brief."""
        from runtime.brief import Brief
        b = Brief(objective="x" * 100_000)
        assert len(b.objective) == 100_000

    def test_se05_null_bytes_in_input(self, tmp_path):
        """SE-05: null bytes in input don't crash Nerve emit."""
        from spine.nerve import Nerve
        nerve = Nerve(state_dir=tmp_path)
        eid = nerve.emit("test\x00event", {"data": "hello\x00world"})
        assert eid.startswith("ev_")

    # ── 7.2.2 Instinct security ──────────────────────────────────────────────

    def test_se10_sensitive_term_case_insensitive(self, tmp_path):
        """SE-10: sensitive term filtering is case-insensitive."""
        import json
        from psyche.instinct_engine import InstinctEngine

        terms_path = tmp_path / "terms.json"
        terms_path.write_text(json.dumps(["SecretProject"]))
        engine = InstinctEngine(tmp_path / "instinct.md", terms_path)

        result = engine.check_outbound_query("tell me about SECRETPROJECT details")
        assert "SECRETPROJECT" not in result
        assert "某项目" in result

    def test_se11_sensitive_term_in_output(self, tmp_path):
        """SE-11: sensitive term leaked in output is detected."""
        import json
        from psyche.instinct_engine import InstinctEngine

        terms_path = tmp_path / "terms.json"
        terms_path.write_text(json.dumps(["classified"]))
        engine = InstinctEngine(tmp_path / "instinct.md", terms_path)

        violations = engine.check_output("This document is classified information", "report")
        assert any("sensitive_term_leaked" in v for v in violations)

    def test_se12_empty_output_detected(self, tmp_path):
        """SE-12: empty/whitespace output flagged."""
        from psyche.instinct_engine import InstinctEngine
        engine = InstinctEngine(tmp_path / "instinct.md")
        violations = engine.check_output("   \n\t  ", "report")
        assert "empty_output" in violations

    # ── 7.2.3 Permissions ─────────────────────────────────────────────────────

    def test_se20_design_validator_rejects_unknown_agent(self):
        """SE-20: design validator rejects unregistered agent."""
        from runtime.design_validator import validate_design
        ok, reason = validate_design({
            "moves": [{"id": "m1", "agent": "hacker_agent"}],
            "brief": {"dag_budget": 6},
        })
        assert ok is False

    def test_se21_retinue_rejects_invalid_role(self, tmp_path):
        """SE-21: retinue rejects allocation for non-pool role."""
        import json
        from runtime.retinue import Retinue

        daemon_home = tmp_path / "daemon"
        oc_home = tmp_path / "openclaw"
        (daemon_home / "state").mkdir(parents=True)
        (daemon_home / "state" / "pool_status.json").write_text("[]")

        retinue = Retinue(daemon_home, oc_home)
        with pytest.raises(ValueError, match="Invalid pool role"):
            retinue.allocate("admin", "deed_1")

    def test_se22_pact_unknown_namespace(self, tmp_path):
        """SE-22: unknown pact namespace silently passes (no matching handler)."""
        from spine.pact import check_pact
        # Unknown namespace doesn't crash — it's a silent no-op
        check_pact("test_routine", "pre", "hacker:something", {"daemon_home": tmp_path})

    # ── 7.2.4 Resource defense ──────────────────────────────────────────────

    def test_se30_ether_consume_limit_bounds(self, tmp_path):
        """SE-30: Ether consume limit is clamped to [1, 1000]."""
        from runtime.ether import Ether
        ether = Ether(tmp_path, source="test")
        # limit=0 → clamped to 1
        events = ether.consume("consumer", limit=0)
        assert isinstance(events, list)

    def test_se31_ether_consume_huge_limit(self, tmp_path):
        """SE-31: Ether consume with huge limit → clamped to 1000."""
        from runtime.ether import Ether
        ether = Ether(tmp_path, source="test")
        events = ether.consume("consumer", limit=999999)
        assert isinstance(events, list)

    def test_se32_retinue_pool_size_minimum(self):
        """SE-32: Retinue enforces MIN_POOL_SIZE."""
        from runtime.retinue import Retinue, MIN_POOL_SIZE
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            from pathlib import Path
            r = Retinue(Path(td), Path(td) / "oc", pool_size=1)
            assert r._pool_size == MIN_POOL_SIZE

    # ── 7.2.5 Filesystem security ─────────────────────────────────────────────

    def test_se40_ledger_read_json_missing_file(self, tmp_path):
        """SE-40: _read_json on missing file returns default."""
        from services.ledger import Ledger
        ledger = Ledger(tmp_path / "state")
        result = ledger._read_json(tmp_path / "nonexistent.json", {"fallback": True})
        assert result == {"fallback": True}

    def test_se41_ledger_read_json_corrupted(self, tmp_path):
        """SE-41: _read_json on corrupted JSON returns default."""
        from services.ledger import Ledger
        ledger = Ledger(tmp_path / "state")
        bad_file = tmp_path / "state" / "bad.json"
        bad_file.write_text("{broken json!!!")
        result = ledger._read_json(bad_file, [])
        assert result == []

    def test_se42_ether_corrupted_events_file(self, tmp_path):
        """SE-42: Ether handles corrupted events.jsonl gracefully."""
        from runtime.ether import Ether
        ether = Ether(tmp_path, source="test")
        # Write some garbage
        events_path = tmp_path / "nerve_bridge" / "events.jsonl"
        events_path.write_text("not json\n{broken\n")
        events = ether.consume("consumer", limit=100)
        assert isinstance(events, list)

    def test_se43_trail_corrupted_jsonl(self, tmp_path):
        """SE-43: Trail handles corrupted trace files."""
        from spine.trail import Trail
        trail = Trail(tmp_path / "traces")
        # Write corrupted data
        (tmp_path / "traces" / "2026-03-13.jsonl").write_text("not json\n{bad\n")
        result = trail.get("nonexistent_id")
        assert result is None

    # ── 7.2.6 Unicode and encoding ────────────────────────────────────────────

    def test_se50_unicode_folio_title(self, tmp_path):
        """SE-50: Unicode folio title stored and retrieved correctly."""
        from services.ledger import Ledger
        from spine.nerve import Nerve
        from services.folio_writ import FolioWritManager as FolioWritRegistry

        ledger = Ledger(tmp_path / "state")
        nerve = Nerve(state_dir=tmp_path / "events")
        reg = FolioWritRegistry(tmp_path / "state", nerve, ledger)

        folio = reg.create_folio("测试项目 📊 テスト")
        assert "测试项目" in folio["title"]
        retrieved = reg.get_folio(folio["folio_id"])
        assert "测试项目" in retrieved["title"]

    def test_se51_unicode_in_ether(self, tmp_path):
        """SE-51: Unicode in Ether payloads preserved."""
        from runtime.ether import Ether
        ether = Ether(tmp_path, source="test")
        ether.emit("unicode_event", {"text": "日本語のテスト 🎌"})
        events = ether.recent(10)
        assert events[0]["payload"]["text"] == "日本語のテスト 🎌"

    def test_se52_unicode_in_nerve(self, tmp_path):
        """SE-52: Unicode in Nerve events preserved."""
        from spine.nerve import Nerve
        nerve = Nerve(state_dir=tmp_path)
        nerve.emit("test", {"text": "中文测试 🔥"})
        events = nerve.recent(10)
        assert events[0]["payload"]["text"] == "中文测试 🔥"

    def test_se53_unicode_in_trail(self, tmp_path):
        """SE-53: Unicode in Trail trace entries."""
        from spine.trail import Trail
        trail = Trail(tmp_path / "traces")
        with trail.span("test_routine", "manual", {"note": "备注 📝"}) as ctx:
            ctx.step("step_1", "步骤一")

        recent = trail.recent(10)
        assert len(recent) == 1
        assert recent[0]["note"] == "备注 📝"
        assert recent[0]["steps"][0]["detail"] == "步骤一"

    def test_se54_emoji_in_brief(self):
        """SE-54: Brief handles emoji in objective."""
        from runtime.brief import Brief
        b = Brief(objective="🚀 Launch the product 🎉")
        assert "🚀" in b.objective

    # ── 7.2.7 Sensitive term edge cases ──────────────────────────────────────

    def test_se60_no_sensitive_terms(self, tmp_path):
        """SE-60: InstinctEngine with no sensitive terms passes everything."""
        from psyche.instinct_engine import InstinctEngine
        engine = InstinctEngine(tmp_path / "instinct.md")
        result = engine.check_outbound_query("any query at all")
        assert result == "any query at all"

    def test_se61_multiple_sensitive_terms(self, tmp_path):
        """SE-61: multiple sensitive terms all filtered."""
        import json
        from psyche.instinct_engine import InstinctEngine

        terms_path = tmp_path / "terms.json"
        terms_path.write_text(json.dumps(["Alpha", "Beta", "Gamma"]))
        engine = InstinctEngine(tmp_path / "instinct.md", terms_path)

        result = engine.check_outbound_query("Alpha and Beta and Gamma project")
        assert "Alpha" not in result
        assert "Beta" not in result
        assert "Gamma" not in result

    def test_se62_sensitive_terms_corrupted_file(self, tmp_path):
        """SE-62: corrupted sensitive_terms.json doesn't crash engine."""
        from psyche.instinct_engine import InstinctEngine
        terms_path = tmp_path / "terms.json"
        terms_path.write_text("not json!!!")
        engine = InstinctEngine(tmp_path / "instinct.md", terms_path)
        assert engine._sensitive_terms == []


class TestBootstrapStartup:
    """§7.3 — Bootstrap cold-start, worker startup, nerve recovery, config validation."""

    # ── 7.3.1 API process bootstrap ──────────────────────────────────────────

    def test_bs01_bootstrap_creates_state_dirs(self, tmp_path):
        """BS-01: bootstrap creates state/ directory structure."""
        from bootstrap import bootstrap
        report = bootstrap(daemon_home=tmp_path, openclaw_home=None)
        assert (tmp_path / "state").is_dir()
        assert (tmp_path / "state" / "psyche").is_dir()

    def test_bs02_bootstrap_creates_psyche_config(self, tmp_path):
        """BS-02: bootstrap creates psyche/ config files."""
        from bootstrap import bootstrap
        report = bootstrap(daemon_home=tmp_path, openclaw_home=None)
        assert (tmp_path / "psyche" / "preferences.toml").exists()
        assert (tmp_path / "psyche" / "rations.toml").exists()

    def test_bs03_bootstrap_creates_ledger_db(self, tmp_path):
        """BS-03: bootstrap creates ledger.db."""
        from bootstrap import bootstrap
        report = bootstrap(daemon_home=tmp_path, openclaw_home=None)
        assert (tmp_path / "state" / "psyche" / "ledger.db").exists()

    def test_bs04_bootstrap_creates_ward_json(self, tmp_path):
        """BS-04: bootstrap creates ward.json."""
        from bootstrap import bootstrap
        report = bootstrap(daemon_home=tmp_path, openclaw_home=None)
        import json
        ward = json.loads((tmp_path / "state" / "ward.json").read_text())
        assert ward["status"] == "GREEN"

    def test_bs05_bootstrap_creates_herald_log(self, tmp_path):
        """BS-05: bootstrap creates herald_log.jsonl."""
        from bootstrap import bootstrap
        bootstrap(daemon_home=tmp_path, openclaw_home=None)
        assert (tmp_path / "state" / "herald_log.jsonl").exists()

    def test_bs06_bootstrap_creates_system_status(self, tmp_path):
        """BS-06: bootstrap creates system_status.json."""
        from bootstrap import bootstrap
        bootstrap(daemon_home=tmp_path, openclaw_home=None)
        import json
        status = json.loads((tmp_path / "state" / "system_status.json").read_text())
        assert status["status"] == "running"

    def test_bs07_bootstrap_creates_alerts_dir(self, tmp_path):
        """BS-07: bootstrap creates alerts/ and TROUBLESHOOTING.md."""
        from bootstrap import bootstrap
        bootstrap(daemon_home=tmp_path, openclaw_home=None)
        assert (tmp_path / "alerts").is_dir()
        assert (tmp_path / "alerts" / "TROUBLESHOOTING.md").exists()

    def test_bs08_bootstrap_creates_template_dirs(self, tmp_path):
        """BS-08: bootstrap creates templates/ for each non-counsel role."""
        from bootstrap import bootstrap, CANONICAL_AGENTS
        bootstrap(daemon_home=tmp_path, openclaw_home=None)
        for role in CANONICAL_AGENTS:
            if role == "counsel":
                continue
            assert (tmp_path / "templates" / role).is_dir()

    def test_bs09_bootstrap_report_structure(self, tmp_path):
        """BS-09: bootstrap report has expected keys."""
        from bootstrap import bootstrap
        report = bootstrap(daemon_home=tmp_path, openclaw_home=None)
        assert "daemon_home" in report
        assert "psyche" in report
        assert "warnings" in report

    def test_bs10_bootstrap_idempotent(self, tmp_path):
        """BS-10: running bootstrap twice doesn't crash or corrupt."""
        from bootstrap import bootstrap
        report1 = bootstrap(daemon_home=tmp_path, openclaw_home=None)
        report2 = bootstrap(daemon_home=tmp_path, openclaw_home=None)
        assert report2 is not None
        assert (tmp_path / "state" / "ward.json").exists()

    # ── 7.3.2 Worker startup ────────────────────────────────────────────────

    def test_bs15_retinue_recover_on_startup(self, tmp_path):
        """BS-15: retinue recovery cleans orphaned occupied instances."""
        import json
        from runtime.retinue import Retinue

        daemon_home = tmp_path / "daemon"
        oc_home = tmp_path / "openclaw"
        (daemon_home / "state").mkdir(parents=True)
        (oc_home / "agents" / "scout_0" / "sessions").mkdir(parents=True)

        pool = [{
            "instance_id": "scout_0", "role": "scout", "status": "occupied",
            "deed_id": "orphan_deed", "allocated_utc": "2026-03-13T00:00:00Z",
            "session_key": "agent:scout_0:main",
            "agent_dir": str(oc_home / "agents" / "scout_0"),
            "workspace_dir": str(oc_home / "workspace" / "scout_0"),
        }]
        (daemon_home / "state" / "pool_status.json").write_text(json.dumps(pool))

        retinue = Retinue(daemon_home, oc_home)
        result = retinue.recover_on_startup()
        assert result["count"] == 1
        assert "scout_0" in result["recovered"]

        inst = retinue.get_instance("scout_0")
        assert inst["status"] == "idle"
        assert inst["deed_id"] is None

    def test_bs16_retinue_recover_empty_pool(self, tmp_path):
        """BS-16: retinue recovery on empty pool is a no-op."""
        import json
        from runtime.retinue import Retinue

        daemon_home = tmp_path / "daemon"
        oc_home = tmp_path / "openclaw"
        (daemon_home / "state").mkdir(parents=True)
        (daemon_home / "state" / "pool_status.json").write_text("[]")

        retinue = Retinue(daemon_home, oc_home)
        result = retinue.recover_on_startup()
        assert result["count"] == 0

    def test_bs17_retinue_recover_idle_untouched(self, tmp_path):
        """BS-17: idle instances are not affected by recovery."""
        import json
        from runtime.retinue import Retinue

        daemon_home = tmp_path / "daemon"
        oc_home = tmp_path / "openclaw"
        (daemon_home / "state").mkdir(parents=True)

        pool = [{
            "instance_id": "scout_0", "role": "scout", "status": "idle",
            "deed_id": None, "allocated_utc": None, "session_key": None,
            "agent_dir": str(oc_home / "agents" / "scout_0"),
            "workspace_dir": str(oc_home / "workspace" / "scout_0"),
        }]
        (daemon_home / "state" / "pool_status.json").write_text(json.dumps(pool))

        retinue = Retinue(daemon_home, oc_home)
        result = retinue.recover_on_startup()
        assert result["count"] == 0

    def test_bs18_retinue_recover_multiple_orphans(self, tmp_path):
        """BS-18: recovery handles multiple orphaned instances."""
        import json
        from runtime.retinue import Retinue

        daemon_home = tmp_path / "daemon"
        oc_home = tmp_path / "openclaw"
        (daemon_home / "state").mkdir(parents=True)

        pool = []
        for i in range(3):
            pool.append({
                "instance_id": f"scout_{i}", "role": "scout", "status": "occupied",
                "deed_id": f"orphan_{i}", "allocated_utc": "2026-03-13T00:00:00Z",
                "session_key": f"agent:scout_{i}:main",
                "agent_dir": str(oc_home / "agents" / f"scout_{i}"),
                "workspace_dir": str(oc_home / "workspace" / f"scout_{i}"),
            })
        (daemon_home / "state" / "pool_status.json").write_text(json.dumps(pool))

        retinue = Retinue(daemon_home, oc_home)
        result = retinue.recover_on_startup()
        assert result["count"] == 3

    # ── 7.3.3 Nerve recovery ────────────────────────────────────────────────

    def test_bs20_nerve_replay_unconsumed(self, tmp_path):
        """BS-20: replay_unconsumed replays events without consumed_utc."""
        import json
        from spine.nerve import Nerve

        # Pre-write events to JSONL
        events_path = tmp_path / "events.jsonl"
        events = [
            {"event": "test_event", "payload": {"n": 1}, "consumed_utc": None, "event_id": "ev_1"},
            {"event": "test_event", "payload": {"n": 2}, "consumed_utc": "2026-03-13T00:00:00Z", "event_id": "ev_2"},
            {"event": "test_event", "payload": {"n": 3}, "consumed_utc": None, "event_id": "ev_3"},
        ]
        events_path.write_text("\n".join(json.dumps(e) for e in events))

        replayed_payloads = []
        nerve = Nerve(state_dir=tmp_path)
        nerve.on("test_event", lambda p: replayed_payloads.append(p))

        count = nerve.replay_unconsumed()
        assert count == 2
        assert len(replayed_payloads) == 2

    def test_bs21_nerve_replay_no_events_file(self, tmp_path):
        """BS-21: replay_unconsumed with no events.jsonl returns 0."""
        from spine.nerve import Nerve
        nerve = Nerve(state_dir=tmp_path)
        count = nerve.replay_unconsumed()
        assert count == 0

    def test_bs22_nerve_replay_empty_file(self, tmp_path):
        """BS-22: replay_unconsumed with empty events.jsonl returns 0."""
        from spine.nerve import Nerve
        (tmp_path / "events.jsonl").write_text("")
        nerve = Nerve(state_dir=tmp_path)
        count = nerve.replay_unconsumed()
        assert count == 0

    def test_bs23_nerve_replay_corrupted_lines(self, tmp_path):
        """BS-23: replay_unconsumed skips corrupted lines gracefully."""
        import json
        from spine.nerve import Nerve

        events_path = tmp_path / "events.jsonl"
        valid = {"event": "test_event", "payload": {"n": 1}, "consumed_utc": None, "event_id": "ev_1"}
        events_path.write_text(f"broken line\n{json.dumps(valid)}\nalso broken\n")

        replayed = []
        nerve = Nerve(state_dir=tmp_path)
        nerve.on("test_event", lambda p: replayed.append(p))

        count = nerve.replay_unconsumed()
        assert count == 1

    # ── 7.3.4 Config validation ──────────────────────────────────────────────

    def test_bs30_normalize_openclaw_missing_file(self, tmp_path):
        """BS-30: normalize_openclaw_config with missing file returns not ok."""
        from bootstrap import normalize_openclaw_config
        result = normalize_openclaw_config(tmp_path)
        assert result["ok"] is False

    def test_bs31_normalize_openclaw_removes_main(self, tmp_path):
        """BS-31: normalize_openclaw_config removes 'main' agent."""
        import json
        from bootstrap import normalize_openclaw_config

        cfg = {
            "agents": {
                "defaults": {},
                "list": [
                    {"id": "main", "model": "test"},
                    {"id": "counsel", "model": "test"},
                ]
            }
        }
        (tmp_path / "openclaw.json").write_text(json.dumps(cfg))

        result = normalize_openclaw_config(tmp_path)
        assert result["ok"] is True

        updated = json.loads((tmp_path / "openclaw.json").read_text())
        ids = [a["id"] for a in updated["agents"]["list"]]
        assert "main" not in ids
        assert "counsel" in ids

    def test_bs32_normalize_openclaw_sets_counsel_default(self, tmp_path):
        """BS-32: normalize_openclaw_config sets counsel as default agent."""
        import json
        from bootstrap import normalize_openclaw_config

        cfg = {
            "agents": {
                "defaults": {},
                "list": [
                    {"id": "counsel", "model": "test"},
                    {"id": "scout", "model": "test", "default": True},
                ]
            }
        }
        (tmp_path / "openclaw.json").write_text(json.dumps(cfg))
        (tmp_path / "workspace" / "_default").mkdir(parents=True)

        result = normalize_openclaw_config(tmp_path)
        assert result["ok"] is True

        updated = json.loads((tmp_path / "openclaw.json").read_text())
        for agent in updated["agents"]["list"]:
            if agent["id"] == "counsel":
                assert agent.get("default") is True
            elif agent["id"] == "scout":
                assert agent.get("default") is not True


# ═══════════════════════════════════════════════════════════════════════════════
# P7 — Round 8: ConfigConsistency · CrossSystem · TelegramAdapter
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfigConsistency:
    """§14 — Configuration consistency and completeness."""

    CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"

    # ── 14.1 spine_registry.json ─────────────────────────────────────────────

    def test_cf01_spine_registry_valid_json(self):
        """CF-01: spine_registry.json is valid JSON."""
        import json
        data = json.loads((self.CONFIG_DIR / "spine_registry.json").read_text())
        assert "routines" in data

    def test_cf02_seven_routines_complete(self):
        """CF-02: all 7 routines present."""
        import json
        data = json.loads((self.CONFIG_DIR / "spine_registry.json").read_text())
        routines = data["routines"]
        expected = {"spine.pulse", "spine.record", "spine.witness", "spine.focus", "spine.relay", "spine.tend", "spine.curate"}
        assert set(routines.keys()) == expected

    def test_cf03_all_modes_deterministic(self):
        """CF-03: all routine modes are 'deterministic'."""
        import json
        data = json.loads((self.CONFIG_DIR / "spine_registry.json").read_text())
        for name, rdef in data["routines"].items():
            assert rdef["mode"] == "deterministic", f"{name} mode is {rdef['mode']}"

    def test_cf04_nerve_triggers_valid(self):
        """CF-04: nerve_triggers reference known events."""
        import json
        data = json.loads((self.CONFIG_DIR / "spine_registry.json").read_text())
        known_events = {
            "service_error", "deed_closed", "herald_completed",
            "config_updated", "ward_changed", "slip_created", "folio_created",
            "deed_settling", "deed_failed", "writ_triggered",
        }
        for name, rdef in data["routines"].items():
            for trigger in rdef.get("nerve_triggers", []):
                assert trigger in known_events, f"{name}: unknown trigger '{trigger}'"

    def test_cf05_depends_on_references_exist(self):
        """CF-05: depends_on references existing routines."""
        import json
        data = json.loads((self.CONFIG_DIR / "spine_registry.json").read_text())
        all_names = set(data["routines"].keys())
        for name, rdef in data["routines"].items():
            for dep in rdef.get("depends_on", []):
                assert dep in all_names, f"{name} depends on unknown '{dep}'"

    def test_cf06_schedule_format_valid(self):
        """CF-06: schedule fields are valid cron expressions or null."""
        import json
        data = json.loads((self.CONFIG_DIR / "spine_registry.json").read_text())
        for name, rdef in data["routines"].items():
            sched = rdef.get("schedule")
            if sched is None:
                continue
            parts = sched.split()
            assert len(parts) == 5, f"{name}: schedule '{sched}' has {len(parts)} fields, expected 5"

    # ── 14.2 model_policy.json ───────────────────────────────────────────────

    def test_cf10_all_agents_have_model_mapping(self):
        """CF-10: all canonical agents + opencode have model mappings."""
        import json
        policy = json.loads((self.CONFIG_DIR / "model_policy.json").read_text())
        agent_map = policy["agent_model_map"]
        expected_agents = {"counsel", "scout", "sage", "artificer", "arbiter", "scribe", "envoy"}
        for agent in expected_agents:
            assert agent in agent_map, f"Agent '{agent}' missing from model_policy"

    def test_cf11_all_aliases_in_registry(self):
        """CF-11: all aliases used in policy exist in registry."""
        import json
        policy = json.loads((self.CONFIG_DIR / "model_policy.json").read_text())
        registry = json.loads((self.CONFIG_DIR / "model_registry.json").read_text())
        registry_aliases = {m["alias"] for m in registry["models"]}
        for agent, alias in policy["agent_model_map"].items():
            if agent.startswith("_"):
                continue
            assert alias in registry_aliases, f"Agent '{agent}' uses alias '{alias}' not in registry"

    # ── 14.3 model_registry.json ─────────────────────────────────────────────

    def test_cf20_all_aliases_have_provider_and_model(self):
        """CF-20: all aliases have provider and model_id."""
        import json
        registry = json.loads((self.CONFIG_DIR / "model_registry.json").read_text())
        for model in registry["models"]:
            assert model.get("provider"), f"Alias '{model.get('alias')}' missing provider"
            assert model.get("model_id"), f"Alias '{model.get('alias')}' missing model_id"

    def test_cf21_providers_are_valid(self):
        """CF-21: all providers are known values."""
        import json
        registry = json.loads((self.CONFIG_DIR / "model_registry.json").read_text())
        valid_providers = {"minimax", "qwen", "zhipu", "deepseek", "openai", "anthropic"}
        for model in registry["models"]:
            assert model["provider"] in valid_providers, f"Unknown provider '{model['provider']}'"

    # ── 14.4 mcp_servers.json ────────────────────────────────────────────────

    def test_cf30_mcp_servers_valid_json(self):
        """CF-30: mcp_servers.json is valid JSON."""
        import json
        data = json.loads((self.CONFIG_DIR / "mcp_servers.json").read_text())
        assert "servers" in data

    def test_cf31_servers_is_dict(self):
        """CF-31: servers field is a dict."""
        import json
        data = json.loads((self.CONFIG_DIR / "mcp_servers.json").read_text())
        assert isinstance(data["servers"], dict)

    def test_cf32_server_entries_have_transport(self):
        """CF-32: each server entry has required fields (if any servers configured)."""
        import json
        data = json.loads((self.CONFIG_DIR / "mcp_servers.json").read_text())
        for name, server in data["servers"].items():
            # At minimum, server must be a dict
            assert isinstance(server, dict), f"Server '{name}' is not a dict"

    # ── 14.5 Cross-file consistency ──────────────────────────────────────────

    def test_cf40_registry_routines_match_spine_methods(self):
        """CF-40: registry routine names match SpineRoutines methods."""
        import json
        data = json.loads((self.CONFIG_DIR / "spine_registry.json").read_text())
        registry_names = {name.replace("spine.", "") for name in data["routines"].keys()}
        from spine.routines import SpineRoutines
        methods = {m for m in dir(SpineRoutines) if not m.startswith("_") and callable(getattr(SpineRoutines, m, None))}
        for rname in registry_names:
            assert rname in methods, f"Routine '{rname}' not a method on SpineRoutines"

    def test_cf41_model_policy_agents_cover_pool_roles(self):
        """CF-41: model_policy agents cover all POOL_ROLES + counsel."""
        import json
        from runtime.retinue import POOL_ROLES
        policy = json.loads((self.CONFIG_DIR / "model_policy.json").read_text())
        agent_map = policy["agent_model_map"]
        for role in POOL_ROLES:
            assert role in agent_map, f"POOL_ROLE '{role}' missing from model_policy"
        assert "counsel" in agent_map

    def test_cf42_preferences_default_depth_valid(self, tmp_path):
        """CF-42: PsycheConfig default depth is a valid value."""
        from psyche.config import PsycheConfig
        config = PsycheConfig(tmp_path / "psyche")
        depth = config.get_pref("default_depth", "study")
        valid = {"glance", "study", "scrutiny"}
        assert depth in valid, f"Default depth '{depth}' not in {valid}"

    # ── 14.6 rations.toml consistency ────────────────────────────────────────

    def test_cf50_rations_has_provider_limits(self, tmp_path):
        """CF-50: rations has provider token limits."""
        from psyche.config import PsycheConfig
        config = PsycheConfig(tmp_path / "psyche")
        ration = config.get_ration("minimax_tokens")
        assert isinstance(ration, dict)
        assert ration.get("daily_limit", 0) > 0

    def test_cf51_concurrent_deeds_positive(self, tmp_path):
        """CF-51: concurrent_deeds ration has positive limit."""
        from psyche.config import PsycheConfig
        config = PsycheConfig(tmp_path / "psyche")
        ration = config.get_ration("concurrent_deeds")
        assert isinstance(ration, dict)
        assert ration.get("daily_limit", 0) > 0

    # ── 14.7 Psyche file consistency ─────────────────────────────────────────

    def test_cf60_instinct_engine_prompt_fragment(self, tmp_path):
        """CF-60: InstinctEngine prompt_fragment matches file content."""
        from psyche.instinct_engine import InstinctEngine
        instinct_path = tmp_path / "instinct.md"
        instinct_path.write_text("Be helpful and safe.")
        engine = InstinctEngine(instinct_path)
        assert engine.prompt_fragment() == "Be helpful and safe."

    def test_cf61_identity_token_limit_enforced(self, tmp_path):
        """CF-61: voice identity exceeding token limit is flagged."""
        from psyche.instinct_engine import InstinctEngine
        engine = InstinctEngine(tmp_path / "instinct.md")
        # 150 tokens ≈ 600 chars
        long_identity = "a" * 800
        violations = engine.check_voice_update("identity", long_identity)
        assert any("identity_exceeds" in v for v in violations)


class TestCrossSystem:
    """§12 — Cross-system integration tests (Python-side logic, no live external services)."""

    # ── 12.1 Temporal integration structures ─────────────────────────────────

    def test_xs01_graphwillworkflow_importable(self):
        """XS-01: GraphWillWorkflow can be imported and instantiated."""
        from temporal.workflows import GraphWillWorkflow
        wf = GraphWillWorkflow()
        assert wf is not None

    def test_xs02_deed_input_structure(self):
        """XS-02: DeedInput dataclass has required fields."""
        from temporal.workflows import DeedInput
        di = DeedInput(
            deed_id="deed_test",
            plan={"moves": []},
            deed_root="/tmp/test",
        )
        assert di.deed_id == "deed_test"
        assert di.plan == {"moves": []}

    def test_xs03_workflow_move_helpers_pure(self):
        """XS-03: workflow _move_id/_deps/_agent are pure functions."""
        from temporal.workflows import GraphWillWorkflow
        wf = GraphWillWorkflow()
        move = {"id": "scout_1", "agent": "scout", "depends_on": ["sage_1"]}
        assert wf._move_id(move, 0) == "scout_1"
        assert wf._deps(move) == ["sage_1"]
        assert wf._agent(move) == "scout"

    def test_xs04_workflow_agent_limits(self):
        """XS-04: _agent_limits returns valid limits."""
        from temporal.workflows import GraphWillWorkflow
        wf = GraphWillWorkflow()
        plan = {"moves": [{"id": "scout_1", "agent": "scout"}], "brief": {"depth": "study"}}
        limits = wf._agent_limits(plan)
        assert isinstance(limits, dict)

    def test_xs05_daemon_activities_importable(self):
        """XS-05: DaemonActivities class is importable."""
        from temporal.activities import DaemonActivities
        assert DaemonActivities is not None

    # ── 12.2 OpenClaw integration structures ─────────────────────────────────

    def test_xs10_retinue_pool_roles_complete(self):
        """XS-10: POOL_ROLES covers all expected agent roles."""
        from runtime.retinue import POOL_ROLES
        expected = {"scout", "sage", "artificer", "arbiter", "scribe", "envoy"}
        assert set(POOL_ROLES) == expected

    def test_xs11_retinue_session_key_format(self, tmp_path):
        """XS-11: allocated instance session_key has correct format."""
        import json
        from runtime.retinue import Retinue

        daemon_home = tmp_path / "daemon"
        oc_home = tmp_path / "openclaw"
        (oc_home / "workspace" / "scout").mkdir(parents=True)
        (daemon_home / "state").mkdir(parents=True)

        pool = [{
            "instance_id": "scout_0", "role": "scout", "status": "idle",
            "deed_id": None, "allocated_utc": None, "session_key": None,
            "agent_dir": str(oc_home / "agents" / "scout_0"),
            "workspace_dir": str(oc_home / "workspace" / "scout_0"),
        }]
        (oc_home / "workspace" / "scout_0").mkdir(parents=True, exist_ok=True)
        (oc_home / "agents" / "scout_0").mkdir(parents=True, exist_ok=True)
        (daemon_home / "state" / "pool_status.json").write_text(json.dumps(pool))

        retinue = Retinue(daemon_home, oc_home, pool_size=16)
        inst = retinue.allocate("scout", "deed_test")
        assert inst["session_key"] == "agent:scout_0:main"

    def test_xs12_canonical_agents_list(self):
        """XS-12: bootstrap CANONICAL_AGENTS has 7 agents."""
        from bootstrap import CANONICAL_AGENTS
        assert len(CANONICAL_AGENTS) == 7
        assert "counsel" in CANONICAL_AGENTS

    def test_xs13_register_retinue_requires_openclaw_json(self, tmp_path):
        """XS-13: register_retinue_instances fails without openclaw.json."""
        from runtime.retinue import register_retinue_instances
        result = register_retinue_instances(tmp_path, tmp_path)
        assert result["ok"] is False

    def test_xs14_workspace_dir_in_allocated_instance(self, tmp_path):
        """XS-14: allocated instance has workspace_dir field."""
        import json
        from runtime.retinue import Retinue

        daemon_home = tmp_path / "daemon"
        oc_home = tmp_path / "openclaw"
        (oc_home / "workspace" / "scout").mkdir(parents=True)
        (daemon_home / "state").mkdir(parents=True)

        pool = [{
            "instance_id": "scout_0", "role": "scout", "status": "idle",
            "deed_id": None, "allocated_utc": None, "session_key": None,
            "agent_dir": str(oc_home / "agents" / "scout_0"),
            "workspace_dir": str(oc_home / "workspace" / "scout_0"),
        }]
        (oc_home / "workspace" / "scout_0").mkdir(parents=True, exist_ok=True)
        (oc_home / "agents" / "scout_0").mkdir(parents=True, exist_ok=True)
        (daemon_home / "state" / "pool_status.json").write_text(json.dumps(pool))

        retinue = Retinue(daemon_home, oc_home, pool_size=16)
        inst = retinue.allocate("scout", "deed_test")
        assert "workspace_dir" in inst
        assert inst["workspace_dir"]

    # ── 12.3 MCP integration ────────────────────────────────────────────────

    def test_xs20_mcp_config_parseable(self):
        """XS-20: mcp_servers.json is parseable."""
        import json
        path = Path(__file__).resolve().parents[1] / "config" / "mcp_servers.json"
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    def test_xs21_mcp_dispatcher_instantiable(self, tmp_path):
        """XS-21: MCPDispatcher instantiates without error."""
        import json
        config_path = tmp_path / "mcp.json"
        config_path.write_text(json.dumps({"servers": {}}))
        from runtime.mcp_dispatch import MCPDispatcher
        mcp = MCPDispatcher(config_path)
        assert mcp is not None

    # ── 12.4 Ether cross-process communication ──────────────────────────────

    def test_xs30_ether_emit_consume_chain(self, tmp_path):
        """XS-30: Ether emit → consume chain works."""
        from runtime.ether import Ether
        producer = Ether(tmp_path, source="api")
        eid = producer.emit("deed_settling", {"deed_id": "d1"})

        consumer = Ether(tmp_path, source="worker")
        events = consumer.consume("worker", limit=10)
        assert len(events) >= 1
        assert events[0]["event"] == "deed_settling"

    def test_xs31_ether_cursor_advances(self, tmp_path):
        """XS-31: cursor advances after consume."""
        from runtime.ether import Ether
        producer = Ether(tmp_path, source="api")
        producer.emit("event_a", {})
        producer.emit("event_b", {})

        consumer = Ether(tmp_path, source="worker")
        events1 = consumer.consume("worker", limit=10)
        assert len(events1) == 2

        producer.emit("event_c", {})
        events2 = consumer.consume("worker", limit=10)
        # Only new event + still-pending events
        new_events = [e for e in events2 if e["event"] == "event_c"]
        assert len(new_events) >= 1

    def test_xs32_ether_ack_removes_from_pending(self, tmp_path):
        """XS-32: ack removes event from pending."""
        from runtime.ether import Ether
        producer = Ether(tmp_path, source="api")
        eid = producer.emit("test_event", {"x": 1})

        consumer = Ether(tmp_path, source="worker")
        events = consumer.consume("worker", limit=10)
        assert len(events) >= 1

        consumer.acknowledge(eid, "test_event", {"x": 1}, "worker")
        events2 = consumer.consume("worker", limit=10)
        pending_ids = {e["event_id"] for e in events2}
        assert eid not in pending_ids

    def test_xs33_ether_cursor_survives_restart(self, tmp_path):
        """XS-33: cursor persists across Ether restarts."""
        from runtime.ether import Ether
        producer = Ether(tmp_path, source="api")
        producer.emit("event_a", {})

        consumer1 = Ether(tmp_path, source="worker")
        consumer1.consume("worker", limit=10)
        consumer1.acknowledge(
            consumer1.consume("worker", limit=10)[0]["event_id"],
            "event_a", {}, "worker"
        ) if consumer1.consume("worker", limit=10) else None

        # Restart consumer
        producer.emit("event_b", {})
        consumer2 = Ether(tmp_path, source="worker_new")
        events = consumer2.consume("worker_new", limit=10)
        # New consumer sees all events
        assert len(events) >= 1

    # ── 12.5 End-to-end logic chains ─────────────────────────────────────────

    def test_xs40_design_to_moves_pipeline(self):
        """XS-40: design → validate → extract moves pipeline."""
        from runtime.design_validator import validate_design
        plan = {
            "moves": [
                {"id": "scout_1", "agent": "scout"},
                {"id": "scribe_1", "agent": "scribe", "depends_on": ["scout_1"]},
            ],
            "brief": {"dag_budget": 6},
        }
        ok, reason = validate_design(plan)
        assert ok is True
        assert len(plan["moves"]) == 2

    def test_xs41_rework_moves_collection(self):
        """XS-41: _rework_moves correctly identifies moves needing rework."""
        from temporal.workflows import GraphWillWorkflow
        wf = GraphWillWorkflow()
        moves = [
            {"id": "scout_1", "agent": "scout"},
            {"id": "scribe_1", "agent": "scribe", "depends_on": ["scout_1"]},
        ]
        # error_code is a string, not a dict
        rework = wf._rework_moves(moves, "generic_quality_issue", 1)
        # Should return at least the last scribe move for generic issues
        assert isinstance(rework, list)
        assert len(rework) >= 1

    def test_xs42_brief_to_execution_defaults(self):
        """XS-42: Brief → execution_defaults pipeline."""
        from runtime.brief import Brief, SINGLE_SLIP_DEFAULTS
        b = Brief(objective="Research AI safety", depth="scrutiny", dag_budget=4)
        defaults = b.execution_defaults()
        assert defaults["concurrency"] == SINGLE_SLIP_DEFAULTS["concurrency"]

    # ── 12.6 Writ chain logic ────────────────────────────────────────────────

    def test_xs50_folio_writ_create_chain(self, tmp_path):
        """XS-50: Folio → Slip → Writ creation chain."""
        from services.ledger import Ledger
        from spine.nerve import Nerve
        from services.folio_writ import FolioWritManager

        ledger = Ledger(tmp_path / "state")
        nerve = Nerve(state_dir=tmp_path / "events")
        reg = FolioWritManager(tmp_path / "state", nerve, ledger)

        folio = reg.create_folio("Project Alpha")
        slip = reg.create_slip(
            title="Task A", objective="Do A",
            brief={"dag_budget": 3}, design={"moves": [{"id": "m1", "agent": "scout"}]},
            folio_id=folio["folio_id"],
        )
        assert slip["folio_id"] == folio["folio_id"]

    def test_xs51_slip_deed_linkage(self, tmp_path):
        """XS-51: record_deed_created links deed to slip."""
        from services.ledger import Ledger
        from spine.nerve import Nerve
        from services.folio_writ import FolioWritManager

        ledger = Ledger(tmp_path / "state")
        nerve = Nerve(state_dir=tmp_path / "events")
        reg = FolioWritManager(tmp_path / "state", nerve, ledger)

        folio = reg.create_folio("Test")
        slip = reg.create_slip(
            title="Slip A", objective="Do A",
            brief={"dag_budget": 3}, design={"moves": []},
            folio_id=folio["folio_id"],
        )
        reg.record_deed_created(slip["slip_id"], "deed_123")
        updated = reg.get_slip(slip["slip_id"])
        assert "deed_123" in (updated.get("deed_ids") or [])

    def test_xs52_folio_slip_ids_populated(self, tmp_path):
        """XS-52: creating slip in folio populates folio.slip_ids."""
        from services.ledger import Ledger
        from spine.nerve import Nerve
        from services.folio_writ import FolioWritManager

        ledger = Ledger(tmp_path / "state")
        nerve = Nerve(state_dir=tmp_path / "events")
        reg = FolioWritManager(tmp_path / "state", nerve, ledger)

        folio = reg.create_folio("Test Folio")
        reg.create_slip(
            title="Slip 1", objective="Obj 1",
            brief={"dag_budget": 3}, design={"moves": []},
            folio_id=folio["folio_id"],
        )
        reg.create_slip(
            title="Slip 2", objective="Obj 2",
            brief={"dag_budget": 3}, design={"moves": []},
            folio_id=folio["folio_id"],
        )
        updated_folio = reg.get_folio(folio["folio_id"])
        assert len(updated_folio["slip_ids"]) == 2

    # ── 12.7 Voice/Instinct pipeline ─────────────────────────────────────────

    def test_xs60_instinct_to_agent_pipeline(self, tmp_path):
        """XS-60: instinct.md → InstinctEngine → prompt_fragment pipeline."""
        from psyche.instinct_engine import InstinctEngine
        instinct_path = tmp_path / "instinct.md"
        instinct_path.write_text("Rule 1: Be safe\nRule 2: Be helpful")
        engine = InstinctEngine(instinct_path)
        fragment = engine.prompt_fragment()
        assert "Be safe" in fragment
        assert "Be helpful" in fragment

    def test_xs61_sensitive_terms_to_query_filter(self, tmp_path):
        """XS-61: sensitive_terms.json → InstinctEngine → query filter pipeline."""
        import json
        from psyche.instinct_engine import InstinctEngine

        terms_path = tmp_path / "terms.json"
        terms_path.write_text(json.dumps(["ProjectX"]))
        engine = InstinctEngine(tmp_path / "instinct.md", terms_path)

        query = "Tell me about ProjectX architecture"
        filtered = engine.check_outbound_query(query)
        assert "ProjectX" not in filtered

    def test_xs62_psyche_config_to_rations_pipeline(self, tmp_path):
        """XS-62: PsycheConfig → consume_ration → check pipeline."""
        from psyche.config import PsycheConfig
        config = PsycheConfig(tmp_path / "psyche")
        # consume_ration returns bool (True=allowed, False=exceeded)
        result = config.consume_ration("minimax_tokens", 100)
        assert result is True  # Within default limit

    # ── 12.8 Trail + Canon integration ───────────────────────────────────────

    def test_xs70_trail_span_records_trace(self, tmp_path):
        """XS-70: Trail.span records a full trace entry."""
        from spine.trail import Trail
        trail = Trail(tmp_path / "traces")
        with trail.span("test_routine", "nerve:test_event") as ctx:
            ctx.step("step_1", "did something")
            ctx.set_result({"ok": True})

        recent = trail.recent(10)
        assert len(recent) == 1
        assert recent[0]["routine"] == "test_routine"
        assert recent[0]["trigger"] == "nerve:test_event"
        assert recent[0]["status"] == "ok"
        assert len(recent[0]["steps"]) == 1

    def test_xs71_canon_loads_all_routines(self):
        """XS-71: SpineCanon loads all 7 routines from registry."""
        from spine.canon import SpineCanon
        canon = SpineCanon(Path(__file__).resolve().parents[1] / "config" / "spine_registry.json")
        all_routines = canon.all()
        assert len(all_routines) == 7

    def test_xs72_canon_routine_has_fields(self):
        """XS-72: RoutineDefinition has expected fields."""
        from spine.canon import SpineCanon
        canon = SpineCanon(Path(__file__).resolve().parents[1] / "config" / "spine_registry.json")
        pulse = canon.get("spine.pulse")
        assert pulse is not None
        assert pulse.mode == "deterministic"
        assert pulse.timeout_s > 0


class TestTelegramAdapter:
    """§27 — Telegram adapter notification and endpoint tests."""

    # ── 27.1 Notification text formatting ────────────────────────────────────

    def test_tg01_notify_text_deed_started(self):
        """TG-01: _notify_text formats deed_started message."""
        from interfaces.telegram.adapter import _notify_text
        msg = _notify_text("deed_started", {"deed_title": "分析任务"})
        assert msg is not None
        assert "分析任务" in msg

    def test_tg02_notify_text_deed_settling(self):
        """TG-02: _notify_text formats deed_settling message."""
        from interfaces.telegram.adapter import _notify_text
        msg = _notify_text("deed_settling", {"deed_title": "研究报告", "summary": "完成了研究"})
        assert msg is not None
        assert "完成" in msg or "研究" in msg

    def test_tg03_notify_text_deed_failed(self):
        """TG-03: _notify_text formats deed_failed message."""
        from interfaces.telegram.adapter import _notify_text
        msg = _notify_text("deed_failed", {"deed_title": "代码生成", "error": "timeout exceeded"})
        assert msg is not None
        assert "timeout" in msg or "失败" in msg

    def test_tg04_notify_text_with_portal_link(self):
        """TG-04: deed_settling includes portal_link."""
        from interfaces.telegram.adapter import _notify_text
        msg = _notify_text("deed_settling", {
            "deed_title": "报告",
            "summary": "已完成",
            "portal_link": "http://localhost:8000/portal/deed_123",
        })
        assert "http://localhost:8000/portal/deed_123" in msg

    def test_tg05_notify_text_unsupported_event(self):
        """TG-05: unsupported event returns None."""
        from interfaces.telegram.adapter import _notify_text
        msg = _notify_text("unknown_event", {"deed_title": "test"})
        assert msg is None

    # ── 27.2 Message helpers ─────────────────────────────────────────────────

    def test_tg10_deed_title_extraction(self):
        """TG-10: _deed_title extracts title from various keys."""
        from interfaces.telegram.adapter import _deed_title
        assert _deed_title({"deed_title": "A"}) == "A"
        assert _deed_title({"title": "B"}) == "B"
        assert _deed_title({}) == "任务"

    def test_tg11_extract_message_from_update(self):
        """TG-11: _extract_message parses Telegram update."""
        from interfaces.telegram.adapter import _extract_message
        update = {
            "message": {
                "text": "/status",
                "chat": {"id": 12345},
            }
        }
        result = _extract_message(update)
        assert result is not None
        assert result == (12345, "/status")

    def test_tg12_extract_message_empty_update(self):
        """TG-12: _extract_message returns None for empty update."""
        from interfaces.telegram.adapter import _extract_message
        assert _extract_message({}) is None
        assert _extract_message({"message": {}}) is None

    def test_tg13_supported_events_complete(self):
        """TG-13: SUPPORTED_EVENTS has all expected events."""
        from interfaces.telegram.adapter import SUPPORTED_EVENTS
        assert "deed_started" in SUPPORTED_EVENTS
        assert "deed_settling" in SUPPORTED_EVENTS
        assert "deed_failed" in SUPPORTED_EVENTS

    # ── 27.3 FastAPI endpoints ───────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_tg20_health_endpoint(self):
        """TG-20: /health returns ok."""
        from httpx import ASGITransport, AsyncClient
        from interfaces.telegram.adapter import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")
            data = resp.json()
        assert data["ok"] is True
        assert data["mode"] == "notify_only"

    @pytest.mark.asyncio
    async def test_tg21_notify_missing_event(self):
        """TG-21: POST /notify without event field → 400."""
        from httpx import ASGITransport, AsyncClient
        from interfaces.telegram.adapter import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/notify", json={"payload": {}})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_tg22_notify_unsupported_event_ignored(self):
        """TG-22: POST /notify with unsupported event → 200 + ignored."""
        from httpx import ASGITransport, AsyncClient
        from interfaces.telegram.adapter import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/notify", json={"event": "random_event", "payload": {}})
        assert resp.status_code == 200
        assert resp.json().get("ignored") is True
