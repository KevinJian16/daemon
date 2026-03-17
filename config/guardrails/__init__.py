"""NeMo Guardrails configuration for daemon.

Two-layer guardrails:
  1. NeMo Guardrails runtime (Colang rules) — loaded from config.yml + safety.co
  2. Pattern-based fallback (actions.py) — zero-token deterministic validation

The NeMo runtime is initialized lazily on first use. If nemoguardrails
is unavailable, the system falls back to pattern-based validation only.

Reference: SYSTEM_DESIGN.md §5.2
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_rails_instance: Any = None
_rails_init_attempted: bool = False

GUARDRAILS_DIR = Path(__file__).parent


def get_rails():
    """Get or create the NeMo Guardrails RailsConfig instance.

    Returns None if nemoguardrails is not installed or config is invalid.
    Lazy initialization — only called when actually needed.
    """
    global _rails_instance, _rails_init_attempted

    if _rails_init_attempted:
        return _rails_instance

    _rails_init_attempted = True

    try:
        from nemoguardrails import RailsConfig, LLMRails

        config = RailsConfig.from_path(str(GUARDRAILS_DIR))
        _rails_instance = LLMRails(config)
        logger.info("NeMo Guardrails initialized from %s", GUARDRAILS_DIR)
    except ImportError:
        logger.info("NeMo Guardrails: nemoguardrails not installed, using pattern fallback")
    except Exception as exc:
        logger.warning("NeMo Guardrails init failed: %s — using pattern fallback", exc)

    return _rails_instance
