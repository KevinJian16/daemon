"""Cold-start bootstrap: create Psyche DBs, seed initial data, validate OpenClaw environment, register Retinue."""
from __future__ import annotations

import json
import os
from pathlib import Path

from psyche.config import PsycheConfig
from psyche.ledger_stats import LedgerStats
from runtime.retinue import Retinue, register_retinue_instances, DEFAULT_POOL_SIZE


CANONICAL_AGENTS = ["counsel", "scout", "sage", "artificer", "arbiter", "scribe", "envoy"]
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

    counsel: dict | None = None
    for row in agent_list:
        if isinstance(row, dict) and str(row.get("id") or "").strip() == "counsel":
            counsel = row
            break
    if counsel is None:
        report["warnings"].append("counsel agent not found; cannot set default counsel")
    else:
        for row in agent_list:
            if not isinstance(row, dict):
                continue
            if row is not counsel and row.get("default") is True:
                row.pop("default", None)
                report["updated"] = True
                report["changes"].append(f"agents.list.default_removed:{row.get('id')}")
        if counsel.get("default") is not True:
            counsel["default"] = True
            report["updated"] = True
            report["changes"].append("agents.list.default=counsel")
        # Ensure counsel can spawn all daemon agents (base roles + pool instances).
        subagents = counsel.get("subagents")
        if not isinstance(subagents, dict):
            subagents = {}
            counsel["subagents"] = subagents
        pool_roles = [a for a in CANONICAL_AGENTS if a != "counsel"]
        desired_allow = list(CANONICAL_AGENTS)
        for role in pool_roles:
            for i in range(DEFAULT_POOL_SIZE):
                desired_allow.append(f"{role}_{i}")
        allow_agents = subagents.get("allowAgents")
        if not isinstance(allow_agents, list) or set(str(x) for x in allow_agents) != set(desired_allow):
            subagents["allowAgents"] = desired_allow
            report["updated"] = True
            report["changes"].append("counsel.subagents.allowAgents=canonical+pool")

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

    gateway = cfg.get("gateway")
    if isinstance(gateway, dict):
        tailscale = gateway.get("tailscale")
        if isinstance(tailscale, dict):
            # OpenClaw 2026.3.x does not accept persisted runtime-discovery keys here.
            for k in ("url", "port"):
                if k in tailscale:
                    tailscale.pop(k, None)
                    report["updated"] = True
                    report["changes"].append(f"gateway.tailscale.removed:{k}")

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
        "psyche": {},
        "openclaw_validation": {},
        "warnings": [],
    }

    db_dir = home / "state" / "psyche"
    db_dir.mkdir(parents=True, exist_ok=True)

    # ── PsycheConfig (TOML-based preferences + rations) ─────────────────────
    psyche_config = PsycheConfig(home / "psyche")
    report["psyche"]["config"] = {"path": str(home / "psyche")}

    # ── LedgerStats (SQLite: dag_templates, folio_templates, skill_stats, agent_stats) ──
    ledger_db = db_dir / "ledger.db"
    ledger_is_new = not ledger_db.exists() or force
    ledger_stats = LedgerStats(ledger_db)
    report["psyche"]["ledger"] = {"new": ledger_is_new, "path": str(ledger_db)}

    # ── Ensure ward.json exists ───────────────────────────────────────────────
    ward_path = home / "state" / "ward.json"
    if not ward_path.exists():
        ward_path.write_text(json.dumps({"status": "GREEN", "updated_utc": "bootstrap"}, indent=2))
    # Migrate old gate.json if it exists
    gate_path = home / "state" / "gate.json"
    if gate_path.exists() and not ward_path.exists():
        gate_path.rename(ward_path)

    # ── Ensure state/herald_log.jsonl exists ───────────────────────────
    herald_log = home / "state" / "herald_log.jsonl"
    herald_log.parent.mkdir(parents=True, exist_ok=True)
    if not herald_log.exists():
        herald_log.write_text("")

    # ── ~/Offerings symlink ────────────────────────────────────────────────────
    symlink = Path.home() / "Offerings"
    offering_dir = home / "offerings"
    if not symlink.exists() and not symlink.is_symlink():
        try:
            symlink.symlink_to(offering_dir)
            report["symlink"] = str(symlink)
        except Exception as e:
            report["warnings"].append(f"Could not create ~/Offerings symlink: {e}")

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

        # ── Retinue registration ──────────────────────────────────────
        retinue_status_file = home / "state" / "pool_status.json"
        if not retinue_status_file.exists() or force:
            retinue_size = int(psyche_config.get_pref("retinue_size_n", str(DEFAULT_POOL_SIZE)))
            retinue_report = register_retinue_instances(oc_home, home, pool_size=retinue_size)
            report["retinue"] = retinue_report
            if not retinue_report.get("ok"):
                report["warnings"].append(f"Retinue registration issue: {retinue_report.get('error', 'unknown')}")
        else:
            report["retinue"] = {"skipped": True, "reason": "pool_status.json already exists"}
    else:
        report["openclaw_validation"] = {"skipped": True, "reason": "OPENCLAW_HOME not set"}
        report["warnings"].append("OPENCLAW_HOME not set — OpenClaw validation skipped")

    # ── Ensure templates/ directory structure ─────────────────────────────
    for role in CANONICAL_AGENTS:
        if role == "counsel":
            continue
        tmpl_dir = home / "templates" / role
        tmpl_dir.mkdir(parents=True, exist_ok=True)

    # ── Ensure system_status.json ─────────────────────────────────────────
    sys_status_path = home / "state" / "system_status.json"
    if not sys_status_path.exists():
        sys_status_path.write_text(json.dumps({
            "status": "running",
            "updated_utc": _utc(),
        }, indent=2))

    # ── Alerts directory + TROUBLESHOOTING.md (§4.5) ───────────────────
    alerts_dir = home / "alerts"
    alerts_dir.mkdir(parents=True, exist_ok=True)
    troubleshoot = alerts_dir / "TROUBLESHOOTING.md"
    if not troubleshoot.exists():
        troubleshoot.write_text(_TROUBLESHOOTING_MD, encoding="utf-8")

    # ── Install watchdog cron job (§4.5) ───────────────────────────────
    watchdog_script = home / "scripts" / "watchdog.sh"
    if watchdog_script.exists():
        cron_result = _install_watchdog_cron(home, watchdog_script)
        report["watchdog_cron"] = cron_result

    return report


def _utc() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _install_watchdog_cron(home: Path, script: Path) -> dict:
    """Install watchdog cron job (every 5 minutes). Idempotent."""
    import subprocess
    marker = "# daemon-watchdog"
    cron_line = f"*/5 * * * * DAEMON_HOME={home} {script} {marker}"
    try:
        existing = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True
        ).stdout
    except Exception:
        existing = ""
    if marker in existing:
        return {"installed": False, "reason": "already_installed"}
    new_crontab = existing.rstrip("\n") + "\n" + cron_line + "\n"
    try:
        subprocess.run(
            ["crontab", "-"], input=new_crontab, text=True, check=True,
            capture_output=True,
        )
        return {"installed": True}
    except Exception as exc:
        return {"installed": False, "error": str(exc)}


_TROUBLESHOOTING_MD = """\
# Daemon Troubleshooting Guide

## Watchdog Alerts

### API process not running
- Check: `pgrep -f "uvicorn.*services.api"`
- Fix: `cd $DAEMON_HOME && python -m uvicorn services.api:create_app --factory --host 0.0.0.0 --port 8000`

### Temporal worker not running
- Check: `pgrep -f "python.*temporal.*worker"`
- Fix: `cd $DAEMON_HOME && python temporal/worker.py`

### API not responding
- Check logs: `tail -50 $DAEMON_HOME/state/api.log`
- Common cause: port conflict, missing .env vars

### Pulse routine stale
- Check cadence: `curl -s http://127.0.0.1:8000/console/schedules | python3 -m json.tool`
- Check spine status: `cat $DAEMON_HOME/state/spine_status.json`

## Manual Recovery
1. Stop all: `pkill -f "uvicorn.*services.api"; pkill -f "python.*temporal.*worker"`
2. Re-bootstrap: `cd $DAEMON_HOME && python bootstrap.py --force`
3. Restart: start API + Worker processes

## Log Locations
- API: stdout / systemd journal
- Worker: stdout / systemd journal
- Watchdog: `$DAEMON_HOME/alerts/watchdog.log`
- Spine: `$DAEMON_HOME/state/spine_log.jsonl`
"""


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
