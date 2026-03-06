"""Cold-start bootstrap: create Fabric DBs, seed initial data, validate OpenClaw environment."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fabric.memory import MemoryFabric
from fabric.playbook import PlaybookFabric, BOOTSTRAP_METHODS
from fabric.compass import (
    CompassFabric,
    BOOTSTRAP_PRIORITIES,
    BOOTSTRAP_QUALITY_PROFILES,
    BOOTSTRAP_BUDGETS,
    BOOTSTRAP_PREFERENCES,
)


CANONICAL_AGENTS = ["router", "collect", "analyze", "build", "review", "render", "apply"]
_UNSET = object()


def _daemon_home() -> Path:
    return Path(os.environ.get("DAEMON_HOME", Path(__file__).parent))


def _openclaw_home() -> Path:
    v = os.environ.get("OPENCLAW_HOME")
    return Path(v) if v else _daemon_home() / "openclaw"


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

    agent_list = agents.get("list")
    if not isinstance(agent_list, list):
        report["warnings"].append("agents.list missing or invalid; skip normalization")
        return report

    filtered_list: list[dict] = []
    removed_main = 0
    for row in agent_list:
        if not isinstance(row, dict):
            filtered_list.append(row)
            continue
        if str(row.get("id") or "").strip() == "main":
            removed_main += 1
            continue
        filtered_list.append(row)
    if removed_main:
        agents["list"] = filtered_list
        agent_list = filtered_list
        report["updated"] = True
        report["changes"].append(f"agents.list.removed_main={removed_main}")

    router: dict | None = None
    for row in agent_list:
        if isinstance(row, dict) and str(row.get("id") or "").strip() == "router":
            router = row
            break
    if router is None:
        report["warnings"].append("router agent not found; cannot set default router")
    else:
        for row in agent_list:
            if not isinstance(row, dict):
                continue
            if row is not router and row.get("default") is True:
                row.pop("default", None)
                report["updated"] = True
                report["changes"].append(f"agents.list.default_removed:{row.get('id')}")
        if router.get("default") is not True:
            router["default"] = True
            report["updated"] = True
            report["changes"].append("agents.list.default=router")

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

    if report["updated"]:
        cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def bootstrap(daemon_home: Path | None = None, openclaw_home: Path | None | object = _UNSET, force: bool = False) -> dict:
    """Run cold-start bootstrap. Returns a report of what was done.

    force=True re-seeds even if DBs exist (useful for dev resets).
    """
    home = daemon_home or _daemon_home()
    # Distinguish "argument omitted" from explicit None.
    oc_home = _openclaw_home() if openclaw_home is _UNSET else openclaw_home

    report: dict = {
        "daemon_home": str(home),
        "openclaw_home": str(oc_home) if oc_home else None,
        "fabric": {},
        "openclaw_validation": {},
        "warnings": [],
    }

    db_dir = home / "state"
    db_dir.mkdir(parents=True, exist_ok=True)

    # ── Memory Fabric ─────────────────────────────────────────────────────────
    mem_db = db_dir / "memory.db"
    mem_is_new = not mem_db.exists() or force
    memory = MemoryFabric(mem_db)
    report["fabric"]["memory"] = {"new": mem_is_new, "path": str(mem_db)}

    # ── Playbook Fabric ───────────────────────────────────────────────────────
    pb_db = db_dir / "playbook.db"
    pb_is_new = not pb_db.exists() or force
    playbook = PlaybookFabric(pb_db)
    if pb_is_new:
        for method in BOOTSTRAP_METHODS:
            playbook.register(
                name=method["name"],
                category=method["category"],
                spec=method["spec"],
                description=method["description"],
                status="active",
            )
    report["fabric"]["playbook"] = {"new": pb_is_new, "methods_seeded": len(BOOTSTRAP_METHODS) if pb_is_new else 0}

    # ── Compass Fabric ────────────────────────────────────────────────────────
    cp_db = db_dir / "compass.db"
    cp_is_new = not cp_db.exists() or force
    compass = CompassFabric(cp_db)
    if cp_is_new:
        for p in BOOTSTRAP_PRIORITIES:
            compass.set_priority(p["domain"], p["weight"], p.get("reason", ""), source="bootstrap")
        for q in BOOTSTRAP_QUALITY_PROFILES:
            compass.set_quality_profile(q["run_type"], q["rules"], changed_by="bootstrap")
        for b in BOOTSTRAP_BUDGETS:
            compass.set_budget(b["resource_type"], float(b["daily_limit"]), changed_by="bootstrap")
        for pref in BOOTSTRAP_PREFERENCES:
            compass.set_pref(pref["pref_key"], pref["value"], source="bootstrap")
    report["fabric"]["compass"] = {
        "new": cp_is_new,
        "priorities_seeded": len(BOOTSTRAP_PRIORITIES) if cp_is_new else 0,
    }

    # ── Ensure gate.json exists ───────────────────────────────────────────────
    gate_path = home / "state" / "gate.json"
    if not gate_path.exists():
        gate_path.write_text(json.dumps({"status": "GREEN", "updated_utc": "bootstrap"}, indent=2))

    # ── Ensure outcome/index.json exists ─────────────────────────────────────
    outcome_index = home / "outcome" / "index.json"
    outcome_index.parent.mkdir(parents=True, exist_ok=True)
    if not outcome_index.exists():
        outcome_index.write_text("[]")

    # ── ~/Outcome symlink ─────────────────────────────────────────────────────
    symlink = Path.home() / "Outcome"
    outcome_dir = home / "outcome"
    if not symlink.exists() and not symlink.is_symlink():
        try:
            symlink.symlink_to(outcome_dir)
            report["symlink"] = str(symlink)
        except Exception as e:
            report["warnings"].append(f"Could not create ~/Outcome symlink: {e}")

    # ── OpenClaw environment validation ──────────────────────────────────────
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

    # Check all canonical agents are registered.
    registered_agents = {a.get("id") for a in cfg.get("agents", {}).get("list", [])}
    missing = [a for a in CANONICAL_AGENTS if a not in registered_agents]
    if missing:
        result["warnings"].append(f"Agents missing from openclaw.json: {missing}")

    # Check workspace directories exist.
    workspace = oc_home / "workspace"
    for agent in CANONICAL_AGENTS:
        agent_dir = workspace / agent
        if not agent_dir.exists():
            result["warnings"].append(f"Workspace missing for agent '{agent}': {agent_dir}")

    # Check defaults directory.
    defaults_dir = oc_home / "defaults"
    if not defaults_dir.exists():
        result["warnings"].append(f"defaults/ directory missing at {defaults_dir}")

    result["registered_agents"] = list(registered_agents)
    result["missing_agents"] = missing
    return result


if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    rep = bootstrap(force=force)
    print(json.dumps(rep, indent=2, ensure_ascii=False))
