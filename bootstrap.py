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
            compass.set_quality_profile(q["task_type"], q["rules"], changed_by="bootstrap")
        for b in BOOTSTRAP_BUDGETS:
            import time
            tomorrow = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
            with compass._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO resource_budgets VALUES (?,?,?,?)",
                    (b["resource_type"], b["daily_limit"], 0, tomorrow),
                )
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
