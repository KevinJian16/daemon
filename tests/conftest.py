"""Shared fixtures for daemon diagnostic tests."""
import json
import time
import pytest
from pathlib import Path


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Directory fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def state_dir(tmp_path):
    d = tmp_path / "state"
    d.mkdir(exist_ok=True)
    (d / "ward.json").write_text(json.dumps({"status": "GREEN"}))
    return d


@pytest.fixture
def psyche_dir(tmp_path):
    d = tmp_path / "psyche"
    d.mkdir(exist_ok=True)
    (d / "preferences.toml").write_text(
        '[general]\ndefault_depth = "study"\nrequire_bilingual = true\n'
        'telegram_enabled = true\npdf_enabled = true\n\n'
        '[execution]\nretinue_size_n = 7\ndeed_running_ttl_s = 14400\n'
        'deed_ration_ratio = 0.2\n\n'
        '[routing]\nresearch_default_sources = ["brave_search"]\n'
    )
    (d / "rations.toml").write_text(
        '[daily_limits]\nminimax_tokens = 20000000\nqwen_tokens = 10000000\n'
        'zhipu_tokens = 10000000\ndeepseek_tokens = 10000000\n'
        'concurrent_deeds = 10\n\n'
        '[current_usage]\n'
    )
    (d / "instinct.md").write_text("# Instinct rules\n\nCore identity rules.\n")
    voice_dir = d / "voice"
    voice_dir.mkdir(exist_ok=True)
    (voice_dir / "identity.md").write_text("# Identity\n\nShort identity.\n")
    (voice_dir / "common.md").write_text("# Common style\n\nBrief style.\n")
    overlays_dir = d / "overlays"
    overlays_dir.mkdir(exist_ok=True)
    return d


@pytest.fixture
def daemon_home(tmp_path, state_dir, psyche_dir):
    """Complete daemon directory with state + psyche + config."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "spine_registry.json").write_text(json.dumps({
        "routines": {
            f"spine.{n}": {
                "mode": "deterministic",
                "schedule": sched,
                "timeout_s": 60,
                "nerve_triggers": triggers,
                "reads": reads,
                "writes": writes,
                "depends_on": deps,
                "degraded_mode": None,
            }
            for n, sched, triggers, reads, writes, deps in [
                ("pulse", "*/10 * * * *", ["service_error"], ["infra:health"], ["state:ward"], []),
                ("record", None, ["deed_closed", "herald_completed"], ["state:trails"], ["psyche:ledger:dag_templates"], []),
                ("witness", "0 */6 * * *", [], ["psyche:ledger:stats"], ["state:system_health"], ["spine.record"]),
                ("focus", "0 6 * * 1", [], ["psyche:ledger:stats"], [], ["spine.witness"]),
                ("relay", "0 */4 * * *", ["config_updated"], ["psyche:config"], ["state:snapshots"], []),
                ("tend", "0 3 * * *", ["ward_changed"], ["state"], ["state"], []),
                ("curate", "0 2 * * 0", [], ["state:deeds"], ["state:vault"], []),
            ]
        }
    }))
    (config_dir / "model_registry.json").write_text(json.dumps({
        "fast": {"provider": "minimax", "model_id": "m2.5"},
        "analysis": {"provider": "deepseek", "model_id": "r1"},
        "review": {"provider": "qwen", "model_id": "max"},
        "glm": {"provider": "zhipu", "model_id": "z1-flash"},
    }))
    (config_dir / "model_policy.json").write_text(json.dumps({
        "counsel": "fast", "scout": "fast", "sage": "analysis",
        "artificer": "fast", "arbiter": "review", "scribe": "glm", "envoy": "fast",
    }))
    (config_dir / "mcp_servers.json").write_text(json.dumps({"servers": {}}))
    return tmp_path


# ── Component fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def nerve():
    from spine.nerve import Nerve
    return Nerve()


@pytest.fixture
def nerve_with_persistence(state_dir):
    from spine.nerve import Nerve
    return Nerve(state_dir=state_dir)


@pytest.fixture
def config(psyche_dir):
    from psyche.config import PsycheConfig
    return PsycheConfig(psyche_dir)


@pytest.fixture
def ledger(state_dir):
    from services.ledger import Ledger
    return Ledger(state_dir)


@pytest.fixture
def ledger_stats(tmp_path):
    from psyche.ledger_stats import LedgerStats
    return LedgerStats(tmp_path / "ledger.db")


@pytest.fixture
def instinct_engine(psyche_dir):
    from psyche.instinct_engine import InstinctEngine
    return InstinctEngine(psyche_dir)


@pytest.fixture
def folio_writ(state_dir, nerve):
    from services.folio_writ import FolioWritManager
    from services.ledger import Ledger
    ld = Ledger(state_dir)
    return FolioWritManager(state_dir, nerve, ld)


@pytest.fixture
def will(config, nerve, state_dir):
    from services.will import Will
    return Will(config, nerve, state_dir)


# ── Helpers ──────────────────────────────────────────────────────────────────


def create_test_deed(ledger, *, deed_id=None, status="running", sub_status="executing",
                     slip_id="slip_test001", age_hours=0):
    """Create a deed in ledger for testing."""
    import uuid as _uuid
    did = deed_id or f"deed_{time.strftime('%Y%m%d%H%M%S')}_{_uuid.uuid4().hex[:6]}"
    now = time.time() - age_hours * 3600
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    row = {
        "deed_id": did,
        "deed_status": status,
        "deed_sub_status": sub_status,
        "slip_id": slip_id,
        "created_utc": created,
        "updated_utc": created,
        "plan": {"moves": [{"id": "m1", "agent": "scout", "depends_on": []}]},
    }
    ledger.upsert_deed(did, row)
    return row


def create_test_slip(folio_writ, *, title="Test Slip", folio_id=None, standing=False,
                     trigger_type="manual"):
    return folio_writ.create_slip(
        title=title, objective=f"Objective for {title}",
        brief={"dag_budget": 6}, design={"moves": []},
        folio_id=folio_id, standing=standing, trigger_type=trigger_type,
    )


def create_test_folio(folio_writ, *, title="Test Folio"):
    return folio_writ.create_folio(title)


def create_test_writ(folio_writ, *, folio_id, slip_id, schedule=None, event=None):
    match = {}
    if schedule:
        match["schedule"] = schedule
    if event:
        match["event"] = event
    return folio_writ.create_writ(
        folio_id=folio_id, title="Test Writ",
        match=match, action={"type": "spawn_deed", "slip_id": slip_id},
    )


def mock_messages(n=5, user_count=3, operation_count=1):
    """Generate mock message list."""
    msgs = []
    for i in range(n):
        if i < user_count:
            msgs.append({"role": "user", "content": f"User message {i}", "created_utc": _utc()})
        elif i < user_count + operation_count:
            msgs.append({"role": "system", "content": f"Operation {i}", "event": "operation", "created_utc": _utc()})
        else:
            msgs.append({"role": "assistant", "content": f"Reply {i}", "created_utc": _utc()})
    return msgs


def mock_embedding(dim=256, seed=42):
    """Generate deterministic mock embedding."""
    import random
    rng = random.Random(seed)
    return [rng.gauss(0, 1) for _ in range(dim)]


def similar_embedding(base, noise=0.01):
    """Generate embedding similar to base (cosine > 0.99)."""
    import random
    rng = random.Random(99)
    return [v + rng.gauss(0, noise) for v in base]


def different_embedding(base):
    """Generate embedding dissimilar to base (cosine < 0.5)."""
    return [-v + 0.5 for v in base]
