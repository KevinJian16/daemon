"""Dual-layer validation: verify Python layer and OC layer are in sync (§0.6).

Checks:
  1. Agent IDs in openclaw.json match workspace directory names.
  2. Skills referenced in config/skill_registry.json have a corresponding
     SKILL.md file under openclaw/workspace/{agent}/skills/{skill}/SKILL.md.
  3. Agent IDs referenced in skill_registry.json exist in openclaw.json.
  4. Workspace directories in openclaw/workspace/ all have a corresponding
     agent entry in openclaw.json (no orphaned workspaces).

Usage:
  python scripts/verify_sync.py [--json]
    --json: output results as JSON instead of human-readable text

Exit codes:
  0 — all checks passed
  1 — one or more sync issues found
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _daemon_home() -> Path:
    return Path(__file__).parent.parent


def load_openclaw_agents(daemon_home: Path) -> list[str]:
    """Return list of agent IDs from openclaw.json."""
    oc_json = daemon_home / "openclaw" / "openclaw.json"
    if not oc_json.exists():
        raise FileNotFoundError(f"openclaw.json not found: {oc_json}")
    data = json.loads(oc_json.read_text())
    agents_section = data.get("agents", {})
    agent_list: list[dict] = (
        agents_section if isinstance(agents_section, list)
        else agents_section.get("list", [])
    )
    return [a["id"] for a in agent_list if a.get("id")]


def load_workspace_agents(daemon_home: Path) -> list[str]:
    """Return list of agent directory names in openclaw/workspace/."""
    workspace = daemon_home / "openclaw" / "workspace"
    if not workspace.is_dir():
        return []
    return [d.name for d in workspace.iterdir() if d.is_dir()]


def load_skill_registry(daemon_home: Path) -> dict:
    """Return contents of config/skill_registry.json."""
    path = daemon_home / "config" / "skill_registry.json"
    if not path.exists():
        raise FileNotFoundError(f"skill_registry.json not found: {path}")
    return json.loads(path.read_text())


def check_skill_md_exists(daemon_home: Path, agent_id: str, skill_name: str) -> bool:
    """Check that SKILL.md exists for a given agent+skill combination."""
    skill_md = (
        daemon_home / "openclaw" / "workspace" / agent_id / "skills" / skill_name / "SKILL.md"
    )
    return skill_md.exists()


def run_checks(daemon_home: Path) -> dict:
    """Run all dual-layer sync checks. Returns a result dict."""
    issues: list[str] = []
    details: dict = {}

    # ── Load data ────────────────────────────────────────────────────────

    try:
        oc_agent_ids = load_openclaw_agents(daemon_home)
    except FileNotFoundError as exc:
        issues.append(str(exc))
        oc_agent_ids = []

    workspace_agent_dirs = load_workspace_agents(daemon_home)

    try:
        skill_registry = load_skill_registry(daemon_home)
    except FileNotFoundError as exc:
        issues.append(str(exc))
        skill_registry = {}

    skills_map: dict[str, dict] = skill_registry.get("skills", {})

    # ── Check 1: openclaw.json agent IDs match workspace directories ─────

    oc_set = set(oc_agent_ids)
    ws_set = set(workspace_agent_dirs)

    in_oc_not_ws = sorted(oc_set - ws_set)
    in_ws_not_oc = sorted(ws_set - oc_set)

    details["agent_id_check"] = {
        "oc_agents": sorted(oc_agent_ids),
        "workspace_dirs": sorted(workspace_agent_dirs),
        "in_oc_not_workspace": in_oc_not_ws,
        "in_workspace_not_oc": in_ws_not_oc,
        "pass": not in_oc_not_ws and not in_ws_not_oc,
    }
    for aid in in_oc_not_ws:
        issues.append(
            f"Agent '{aid}' in openclaw.json but no workspace directory at "
            f"openclaw/workspace/{aid}/"
        )
    for aid in in_ws_not_oc:
        issues.append(
            f"Workspace directory 'openclaw/workspace/{aid}/' exists but agent "
            f"'{aid}' not in openclaw.json"
        )

    # ── Check 2: skill_registry agents exist in openclaw.json ───────────

    skill_agent_issues: list[dict] = []
    for skill_name, skill_def in skills_map.items():
        agent_id = skill_def.get("agent", "")
        if agent_id and agent_id not in oc_set:
            skill_agent_issues.append({
                "skill": skill_name,
                "agent": agent_id,
                "issue": "agent_not_in_openclaw_json",
            })
            issues.append(
                f"Skill '{skill_name}' references agent '{agent_id}' which is not in openclaw.json"
            )

    details["skill_agent_check"] = {
        "total_skills": len(skills_map),
        "issues": skill_agent_issues,
        "pass": len(skill_agent_issues) == 0,
    }

    # ── Check 3: SKILL.md files exist for each registered skill ─────────

    skill_md_issues: list[dict] = []
    skill_md_ok: list[str] = []
    for skill_name, skill_def in skills_map.items():
        agent_id = skill_def.get("agent", "")
        if not agent_id:
            continue
        if check_skill_md_exists(daemon_home, agent_id, skill_name):
            skill_md_ok.append(skill_name)
        else:
            skill_md_issues.append({
                "skill": skill_name,
                "agent": agent_id,
                "expected_path": str(
                    Path("openclaw/workspace") / agent_id / "skills" / skill_name / "SKILL.md"
                ),
            })
            issues.append(
                f"SKILL.md missing for skill '{skill_name}' "
                f"(expected: openclaw/workspace/{agent_id}/skills/{skill_name}/SKILL.md)"
            )

    details["skill_md_check"] = {
        "total_skills_checked": len(skills_map),
        "ok_count": len(skill_md_ok),
        "missing_count": len(skill_md_issues),
        "missing": skill_md_issues,
        "pass": len(skill_md_issues) == 0,
    }

    # ── Summary ──────────────────────────────────────────────────────────

    passed = len(issues) == 0
    return {
        "passed": passed,
        "issue_count": len(issues),
        "issues": issues,
        "details": details,
        "daemon_home": str(daemon_home),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify Python layer and OC layer are in sync (§0.6)"
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output results as JSON",
    )
    args = parser.parse_args()

    daemon_home = _daemon_home()
    result = run_checks(daemon_home)

    if args.json_output:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if result["passed"]:
            print(f"OK  Python <-> OC layer sync: all checks passed ({daemon_home})")
        else:
            print(f"FAIL  Python <-> OC layer sync: {result['issue_count']} issue(s) found")
            for issue in result["issues"]:
                print(f"  - {issue}")
            print()
            print("Details:")
            for check_name, check_data in result["details"].items():
                status = "PASS" if check_data.get("pass") else "FAIL"
                print(f"  [{status}] {check_name}")

    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
