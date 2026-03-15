"""Shared fixtures for daemon tests — new architecture (7th draft).

Only tests the new modules: store, plane_client, event_bus, session_manager,
scenes, plane_webhook, workflows, activities.
"""
import json
import time
import pytest
from pathlib import Path


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Directory fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def daemon_home(tmp_path):
    """Minimal daemon directory for testing."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "mcp_servers.json").write_text(json.dumps({"servers": {}}))

    state_dir = tmp_path / "state"
    state_dir.mkdir(exist_ok=True)

    return tmp_path


# ── Helpers ──────────────────────────────────────────────────────────────────


def mock_messages(n=5, user_count=3):
    """Generate mock message list."""
    msgs = []
    for i in range(n):
        if i < user_count:
            msgs.append({"role": "user", "content": f"User message {i}", "created_utc": _utc()})
        else:
            msgs.append({"role": "assistant", "content": f"Reply {i}", "created_utc": _utc()})
    return msgs


def mock_embedding(dim=256, seed=42):
    """Generate deterministic mock embedding."""
    import random
    rng = random.Random(seed)
    return [rng.gauss(0, 1) for _ in range(dim)]
