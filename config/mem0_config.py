"""Mem0 configuration and initialization.

Mem0 provides semantic memory storage backed by PG + pgvector.
Replaces previous per-agent flat-file memory directories.

Memory categories:
  - agent-level: identity, role definition, capabilities
  - user-level: preferences, interaction style, domain expertise
  - procedural: writing style (writer/publisher), planning patterns (L1)
  - project-level: project context, ongoing work

Reference: SYSTEM_DESIGN.md §4.3, TODO.md Phase 4.4-4.6
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_mem0_config() -> dict[str, Any]:
    """Return Mem0 configuration using daemon's existing PG + pgvector.

    Uses fastembed (local ONNX) for embeddings — no external API key needed.
    Model: BAAI/bge-small-en-v1.5 (384 dim, ~33MB).
    """
    pg_user = os.environ.get("POSTGRES_USER", "daemon")
    pg_pass = os.environ.get("POSTGRES_PASSWORD", "daemon")
    pg_host = os.environ.get("POSTGRES_HOST", "localhost")
    pg_port = os.environ.get("POSTGRES_PORT", "5432")
    pg_db = os.environ.get("POSTGRES_DB", "daemon")

    daemon_home = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
    qdrant_path = str(daemon_home / "state" / "mem0_qdrant")

    return {
        "llm": {
            "provider": "deepseek",
            "config": {
                "model": "deepseek-chat",
                "api_key": os.environ.get("DEEPSEEK_API_KEY", ""),
            },
        },
        "embedder": {
            "provider": "fastembed",
            "config": {
                "model": "BAAI/bge-small-en-v1.5",
            },
        },
        "vector_store": {
            "provider": "qdrant",
            "config": {
                "collection_name": "daemon_memories",
                "path": qdrant_path,
                "embedding_model_dims": 384,
            },
        },
        "version": "v1.1",
    }


def init_mem0():
    """Initialize Mem0 client. Returns None if mem0 is not installed."""
    try:
        from mem0 import Memory

        config = get_mem0_config()
        memory = Memory.from_config(config)
        logger.info("Mem0 initialized with pgvector backend")
        return memory
    except ImportError:
        logger.warning("mem0ai not installed — memory features disabled")
        return None
    except Exception as exc:
        logger.warning("Mem0 initialization failed: %s", exc)
        return None


# Memory injection helpers for Step execution

def _agent_focus_query(agent_id: str) -> str:
    """Return a focus query string tailored to the agent type (§5.5).

    L1 agents (copilot/instructor/navigator/autopilot): planning experience
    writer: style preferences
    reviewer: quality standards
    researcher: domain knowledge
    engineer: code patterns
    publisher: platform preferences
    """
    agent_id_lower = agent_id.lower()
    # L1 scene agents — planning and coordination experience
    if agent_id_lower in {"copilot", "instructor", "navigator", "autopilot"}:
        return f"agent:{agent_id} planning experience coordination"
    # writer — style and voice
    if agent_id_lower == "writer":
        return f"agent:{agent_id} style preferences writing voice tone"
    # reviewer — quality criteria and standards
    if agent_id_lower == "reviewer":
        return f"agent:{agent_id} quality standards review criteria checklist"
    # researcher — domain knowledge and sources
    if agent_id_lower == "researcher":
        return f"agent:{agent_id} domain knowledge sources research patterns"
    # engineer — code conventions and patterns
    if agent_id_lower == "engineer":
        return f"agent:{agent_id} code patterns conventions best practices"
    # publisher — platform-specific preferences
    if agent_id_lower == "publisher":
        return f"agent:{agent_id} platform preferences publishing channels format"
    # fallback for any other agent
    return f"agent:{agent_id} context"


def retrieve_agent_context(memory, agent_id: str, limit: int = 5) -> str:
    """Retrieve relevant memories for an agent before Step execution.

    Returns a compact text block (~50-200 tokens) to inject into
    the agent's session context.

    Query is customised per agent type (§5.5):
    - L1 agents: planning experience
    - writer: style preferences
    - reviewer: quality standards
    - researcher: domain knowledge
    - engineer: code patterns
    - publisher: platform preferences
    """
    if memory is None:
        return ""

    try:
        results = memory.search(
            query=_agent_focus_query(agent_id),
            user_id=agent_id,
            limit=limit,
        )
        if not results or not results.get("results"):
            return ""

        parts = []
        for r in results["results"][:limit]:
            text = str(r.get("memory") or r.get("text") or "").strip()
            if text:
                parts.append(f"- {text}")

        if not parts:
            return ""

        return f"[Agent Memory]\n" + "\n".join(parts)
    except Exception as exc:
        logger.debug("Mem0 search failed for agent %s: %s", agent_id, exc)
        return ""


def retrieve_user_preferences(memory, limit: int = 5) -> str:
    """Retrieve user preferences from Mem0 for persona injection."""
    if memory is None:
        return ""

    try:
        results = memory.search(
            query="user preferences and style",
            user_id="user_persona",
            limit=limit,
        )
        if not results or not results.get("results"):
            return ""

        parts = []
        for r in results["results"][:limit]:
            text = str(r.get("memory") or r.get("text") or "").strip()
            if text:
                parts.append(f"- {text}")

        if not parts:
            return ""

        return f"[User Preferences]\n" + "\n".join(parts)
    except Exception as exc:
        logger.debug("Mem0 user preferences search failed: %s", exc)
        return ""
