"""Spine Contracts — IO contract validation for Routine pre/post conditions."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any


class ContractError(Exception):
    pass


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def check_contract(
    routine_name: str,
    phase: str,  # "pre" | "post"
    resource: str,
    context: dict[str, Any],
) -> None:
    """Raise ContractError if the declared IO contract is violated.

    context keys used:
        daemon_home: Path — root daemon directory
        state_dir: Path — state/ directory
        fabric: dict — {memory, playbook, compass} instances
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
        # Health checks validated at runtime — no file contract here.
        pass

    elif ns == "state":
        kind = parts[1] if len(parts) > 1 else ""
        if kind == "gate":
            p = state_dir / "gate.json"
            if phase == "post" and not p.exists():
                raise ContractError(f"{routine_name}.post: state:gate not written at {p}")
        elif kind == "traces":
            p = state_dir / "traces"
            if phase == "pre" and not p.is_dir():
                raise ContractError(f"{routine_name}.pre: state:traces directory missing at {p}")

    elif ns == "fabric":
        fabric_ns = parts[1] if len(parts) > 1 else ""
        fabric_instances = context.get("fabric", {})
        if phase == "pre" and fabric_ns and fabric_ns not in fabric_instances:
            raise ContractError(f"{routine_name}.pre: fabric:{fabric_ns} not available in context")

    elif ns == "runs":
        kind = parts[1] if len(parts) > 1 else ""
        runs_dir = daemon_home / "state" / "runs"
        if phase == "pre" and kind == "collect_output":
            if not any(runs_dir.glob("**/signals_prepare.json")) if runs_dir.exists() else True:
                pass  # Warning only — collect may not have run yet.

    elif ns == "openclaw":
        # OpenClaw contracts validated at runtime via Gateway health check.
        pass
