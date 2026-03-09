"""Spine Pact — IO pact validation for Routine pre/post conditions."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any


class PactError(Exception):
    pass


logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def check_pact(
    routine_name: str,
    phase: str,  # "pre" | "post"
    resource: str,
    context: dict[str, Any],
) -> None:
    """Raise PactError if the declared IO pact is violated.

    context keys used:
        daemon_home: Path — root daemon directory
        state_dir: Path — state/ directory
        psyche: dict — {memory, lore, instinct} instances
    """
    daemon_home: Path = context.get("daemon_home", Path("."))
    state_dir: Path = context.get("state_dir", daemon_home / "state")

    def _path_fresh(p: Path, max_age_hours: int = 24) -> bool:
        if not p.exists():
            return False
        age = time.time() - p.stat().st_mtime
        return age < max_age_hours * 3600

    # Resource spec format: "namespace:kind[:qualifier]"
    parts = resource.split(":")
    ns = parts[0]

    if ns == "infra":
        # Health checks validated at runtime — no file pact here.
        pass

    elif ns == "state":
        kind = parts[1] if len(parts) > 1 else ""
        if kind == "ward":
            p = state_dir / "ward.json"
            if phase == "post" and not p.exists():
                raise PactError(f"{routine_name}.post: state:ward not written at {p}")
        elif kind == "traces":
            p = state_dir / "traces"
            if phase == "pre" and not p.is_dir():
                raise PactError(f"{routine_name}.pre: state:traces directory missing at {p}")

    elif ns == "psyche":
        psyche_ns = parts[1] if len(parts) > 1 else ""
        psyche_instances = context.get("psyche", {})
        if phase == "pre" and psyche_ns and psyche_ns not in psyche_instances:
            raise PactError(f"{routine_name}.pre: psyche:{psyche_ns} not available in context")

    elif ns == "deeds":
        kind = parts[1] if len(parts) > 1 else ""
        deeds_dir = daemon_home / "state" / "deeds"
        if phase == "pre" and kind == "scout_output":
            if not any(deeds_dir.glob("**/signals_prepare.json")) if deeds_dir.exists() else True:
                logger.info("%s.pre: deeds:scout_output not found yet under %s", routine_name, deeds_dir)

    elif ns == "openclaw":
        # OpenClaw pacts validated at runtime via Gateway health check.
        pass
