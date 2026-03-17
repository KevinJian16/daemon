"""Daemon diagnostic tests — new architecture (7th draft).

Tests the core glue layer modules without requiring external infrastructure.
Integration tests requiring PG/Temporal/Plane are separate.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── PlaneClient unit tests ──────────────────────────────────────────────────


class TestPlaneClient:
    """Test PlaneClient request building and error handling."""

    def test_import(self):
        from services.plane_client import PlaneClient, PlaneAPIError
        client = PlaneClient(
            api_url="http://localhost:8001",
            api_token="test_token",
            workspace_slug="test",
        )
        assert client.api_url == "http://localhost:8001"
        assert client.workspace_slug == "test"

    def test_workspace_path(self):
        from services.plane_client import PlaneClient
        client = PlaneClient(
            api_url="http://localhost:8001",
            api_token="test_token",
            workspace_slug="daemon",
        )
        assert client._ws() == "/api/v1/workspaces/daemon"
        assert client._proj("proj123") == "/api/v1/workspaces/daemon/projects/proj123"

    def test_webhook_signature_verification(self):
        from services.plane_client import PlaneClient
        import hashlib, hmac

        secret = "test_secret"
        payload = b'{"event": "issue", "action": "created"}'
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        assert PlaneClient.verify_webhook_signature(payload, sig, secret)
        assert not PlaneClient.verify_webhook_signature(payload, "bad_sig", secret)


# ── Store unit tests ────────────────────────────────────────────────────────


class TestStore:
    """Test Store import and structure (actual DB tests need PG)."""

    def test_import(self):
        from services.store import Store
        assert Store is not None

    def test_store_methods_exist(self):
        from services.store import Store
        expected_methods = [
            "create_task", "get_task", "get_task_by_plane_issue",
            "create_job", "get_job", "update_job_status", "list_jobs_for_task",
            "create_step", "update_step_status", "get_steps_for_job",
            "create_artifact", "get_artifacts_for_job",
            "save_message", "get_recent_messages",
            "save_digest", "get_recent_digests",
            "save_decision", "get_recent_decisions",
            "upsert_knowledge", "cleanup_expired_knowledge",
        ]
        for method in expected_methods:
            assert hasattr(Store, method), f"Store missing method: {method}"


# ── EventBus unit tests ────────────────────────────────────────────────────


class TestEventBus:
    """Test EventBus subscribe/unsubscribe logic."""

    def test_import(self):
        from services.event_bus import EventBus
        bus = EventBus("postgresql://localhost/test")
        assert bus is not None

    def test_subscribe_unsubscribe(self):
        from services.event_bus import EventBus

        bus = EventBus("postgresql://localhost/test")
        callback = AsyncMock()

        bus.subscribe("job_events", callback)
        assert "job_events" in bus._callbacks
        assert callback in bus._callbacks["job_events"]

        bus.unsubscribe("job_events", callback)
        assert callback not in bus._callbacks.get("job_events", [])

    def test_unsubscribe_all(self):
        from services.event_bus import EventBus

        bus = EventBus("postgresql://localhost/test")
        bus.subscribe("job_events", AsyncMock())
        bus.subscribe("job_events", AsyncMock())
        bus.unsubscribe("job_events")
        assert "job_events" not in bus._callbacks


# ── SessionManager unit tests ──────────────────────────────────────────────


class TestSessionManager:
    """Test SessionManager structure and action extraction."""

    def test_import(self):
        from services.session_manager import SessionManager, L1_SCENES
        assert set(L1_SCENES) == {"copilot", "instructor", "navigator", "autopilot"}

    def test_extract_action_json_block(self):
        from services.session_manager import SessionManager

        sm = SessionManager(
            openclaw_adapter=None,
            store=MagicMock(),
            event_bus=MagicMock(),
        )

        reply = 'Here is my plan:\n```json\n{"action": "create_job", "steps": [{"id": 1}]}\n```'
        action = sm._extract_action(reply)
        assert action is not None
        assert action["route"] == "task"

    def test_extract_action_none(self):
        from services.session_manager import SessionManager

        sm = SessionManager(
            openclaw_adapter=None,
            store=MagicMock(),
            event_bus=MagicMock(),
        )

        reply = "Just a regular reply with no action."
        action = sm._extract_action(reply)
        assert action is None


# ── Scenes route tests ─────────────────────────────────────────────────────


class TestScenesRoutes:
    """Test scene routes import and structure."""

    def test_import(self):
        from services.api_routes.scenes import router
        assert router is not None

    def test_router_has_correct_prefix(self):
        from services.api_routes.scenes import router
        assert router.prefix == "/scenes"


# ── Workflow tests ─────────────────────────────────────────────────────────


class TestWorkflows:
    """Test workflow import and structure."""

    def test_import_all_workflows(self):
        from temporal.workflows import (
            JobWorkflow,
            HealthCheckWorkflow,
            SelfHealWorkflow,
            MaintenanceWorkflow,
            BackupWorkflow,
        )
        assert JobWorkflow is not None
        assert HealthCheckWorkflow is not None


# ── PlaneWebhook tests ─────────────────────────────────────────────────────


class TestPlaneWebhook:
    """Test webhook handler import and configuration."""

    def test_import(self):
        from services.plane_webhook import router, configure
        assert router is not None

    def test_configure(self):
        from services.plane_webhook import configure, _webhook_secret
        configure("test_secret_123")
        from services import plane_webhook
        assert plane_webhook._webhook_secret == "test_secret_123"


# ── Module import smoke tests ──────────────────────────────────────────────


class TestModuleImports:
    """Verify all retained modules can be imported without error."""

    def test_runtime_openclaw(self):
        from runtime.openclaw import OpenClawAdapter

    def test_runtime_temporal(self):
        from runtime.temporal import TemporalClient

    def test_runtime_mcp_dispatch(self):
        from runtime.mcp_dispatch import MCPDispatcher

    def test_services_store(self):
        from services.store import Store

    def test_services_plane_client(self):
        from services.plane_client import PlaneClient

    def test_services_event_bus(self):
        from services.event_bus import EventBus

    def test_services_session_manager(self):
        from services.session_manager import SessionManager

    def test_temporal_activities(self):
        try:
            from temporal.activities import DaemonActivities
        except ImportError:
            pytest.skip("asyncpg not available")

    def test_temporal_workflows(self):
        from temporal.workflows import JobWorkflow
