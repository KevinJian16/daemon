"""Cold-start bootstrap: validate OpenClaw environment, ensure directory structure.

New architecture (7th draft): Psyche/Retinue/Ledger replaced by Mem0/OC native/PG.
Bootstrap now focuses on:
  1. OpenClaw config normalization (10 agents: 4 L1 + 6 L2)
  2. Directory structure creation
  3. Environment validation
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path


# New architecture: 4 L1 + 6 L2 agents
L1_AGENTS = ["copilot", "mentor", "coach", "operator"]
L2_AGENTS = ["researcher", "engineer", "writer", "reviewer", "publisher", "admin"]
ALL_AGENTS = L1_AGENTS + L2_AGENTS

_UNSET = object()


def _daemon_home() -> Path:
    return Path(os.environ.get("DAEMON_HOME", Path(__file__).parent))


def _openclaw_home() -> Path:
    v = os.environ.get("OPENCLAW_HOME")
    return Path(v) if v else _daemon_home() / "openclaw"


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def normalize_openclaw_config(oc_home: Path) -> dict:
    """Normalize OpenClaw config to daemon canonical agent topology."""
    report: dict = {"ok": True, "updated": False, "changes": [], "warnings": []}
    cfg_path = oc_home / "openclaw.json"
    if not cfg_path.exists():
        report["ok"] = False
        report["warnings"].append(f"openclaw.json not found at {cfg_path}")
        return report
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        report["ok"] = False
        report["warnings"].append(f"openclaw.json parse error: {exc}")
        return report

    agents = cfg.get("agents")
    if not isinstance(agents, dict):
        agents = {}
        cfg["agents"] = agents
        report["updated"] = True
        report["changes"].append("agents.created")

    defaults = agents.get("defaults")
    if not isinstance(defaults, dict):
        defaults = {}
        agents["defaults"] = defaults
        report["updated"] = True
        report["changes"].append("agents.defaults.created")

    # Ensure default workspace points to _default
    desired_default_workspace = (oc_home / "workspace" / "_default").resolve()
    current_workspace = str(defaults.get("workspace") or "").strip()
    root_workspace = (oc_home / "workspace").resolve()
    resolved_current: Path | None = None
    if current_workspace:
        try:
            resolved_current = Path(current_workspace).expanduser().resolve()
        except Exception:
            resolved_current = None

    if not current_workspace or resolved_current == root_workspace:
        defaults["workspace"] = str(desired_default_workspace)
        desired_default_workspace.mkdir(parents=True, exist_ok=True)
        report["updated"] = True
        report["changes"].append(f"agents.defaults.workspace={desired_default_workspace}")

    # Clean gateway runtime keys
    gateway = cfg.get("gateway")
    if isinstance(gateway, dict):
        tailscale = gateway.get("tailscale")
        if isinstance(tailscale, dict):
            for k in ("url", "port"):
                if k in tailscale:
                    tailscale.pop(k, None)
                    report["updated"] = True
                    report["changes"].append(f"gateway.tailscale.removed:{k}")

    if report["updated"]:
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def bootstrap(daemon_home: Path | None = None, openclaw_home: Path | None | object = _UNSET, force: bool = False) -> dict:
    """Run cold-start bootstrap. Returns a report of what was done."""
    home = daemon_home or _daemon_home()
    oc_home = _openclaw_home() if openclaw_home is _UNSET else openclaw_home

    report: dict = {
        "daemon_home": str(home),
        "openclaw_home": str(oc_home) if oc_home else None,
        "warnings": [],
    }

    # Ensure directory structure
    for d in ["state", "state/health_reports", "state/issues", "backups", "warmup"]:
        (home / d).mkdir(parents=True, exist_ok=True)

    # Persona directory
    for d in ["persona/voice", "persona/voice/overlays"]:
        (home / d).mkdir(parents=True, exist_ok=True)

    # Config directory
    (home / "config").mkdir(parents=True, exist_ok=True)
    (home / "config" / "guardrails").mkdir(parents=True, exist_ok=True)

    # OpenClaw validation
    if oc_home:
        norm = normalize_openclaw_config(oc_home)
        report["openclaw_normalization"] = norm
        if norm.get("warnings"):
            report["warnings"].extend(list(norm.get("warnings") or []))
        val = _validate_openclaw(oc_home)
        report["openclaw_validation"] = val
        if val.get("warnings"):
            report["warnings"].extend(val["warnings"])
    else:
        report["openclaw_validation"] = {"skipped": True, "reason": "OPENCLAW_HOME not set"}
        report["warnings"].append("OPENCLAW_HOME not set — OpenClaw validation skipped")

    return report


def _validate_openclaw(oc_home: Path) -> dict:
    result: dict = {"ok": True, "warnings": []}

    cfg_path = oc_home / "openclaw.json"
    if not cfg_path.exists():
        result["ok"] = False
        result["warnings"].append(f"openclaw.json not found at {cfg_path}")
        return result

    try:
        cfg = json.loads(cfg_path.read_text())
    except Exception as e:
        result["ok"] = False
        result["warnings"].append(f"openclaw.json parse error: {e}")
        return result

    # Check all agents are registered
    registered_agents = {a.get("id") for a in cfg.get("agents", {}).get("list", [])}
    missing = [a for a in ALL_AGENTS if a not in registered_agents]
    if missing:
        result["warnings"].append(f"Agents missing from openclaw.json: {missing}")

    # Check workspace directories exist
    workspace = oc_home / "workspace"
    for agent in ALL_AGENTS:
        agent_dir = workspace / agent
        if not agent_dir.exists():
            result["warnings"].append(f"Workspace missing for agent '{agent}': {agent_dir}")

    result["registered_agents"] = list(registered_agents)
    result["missing_agents"] = missing
    return result


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    rep = bootstrap(force=force)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
