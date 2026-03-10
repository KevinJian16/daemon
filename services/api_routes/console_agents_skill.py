"""Console agent and skill routes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_agents_skill_routes(app: FastAPI, *, ctx: Any) -> None:
    def _agent_rows() -> list[dict]:
        cfg_path = ctx.oc_home / "openclaw.json"
        if not cfg_path.exists():
            return []
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            ctx.logger.warning("Failed to read openclaw.json: %s", exc)
            return []
        agents = cfg.get("agents", {}).get("list", [])
        result = []
        for agent in agents:
            agent_id = str(agent.get("id") or "").strip()
            if not agent_id:
                continue
            workspace = ctx.oc_home / "workspace" / agent_id
            skills_dir = workspace / "skills"
            skills = sorted(skills_dir.glob("*/SKILL.md")) if skills_dir.exists() else []
            result.append(
                {
                    "id": agent_id,
                    "workspace_exists": workspace.exists(),
                    "skills_count": len(skills),
                }
            )
        return result

    def _skill_dir(role: str, skill: str) -> Path:
        return ctx.oc_home / "workspace" / role / "skills" / skill

    def _skill_row(skill_md: Path, *, role: str) -> dict:
        skill_dir = skill_md.parent
        disabled = (skill_dir / ".disabled").exists()
        stat = skill_md.stat()
        heading = ""
        try:
            first = skill_md.read_text(encoding="utf-8").splitlines()
            for line in first[:8]:
                line = str(line or "").strip()
                if line.startswith("#"):
                    heading = line.lstrip("#").strip()
                    break
        except Exception:
            heading = ""
        return {
            "role": role,
            "skill": skill_dir.name,
            "key": f"{role}:{skill_dir.name}",
            "enabled": not disabled,
            "title": heading or skill_dir.name,
            "updated_utc": ctx.utc_from_ts(stat.st_mtime) if hasattr(ctx, "utc_from_ts") else "",
            "size_bytes": int(stat.st_size),
        }

    def _all_skill_rows() -> list[dict]:
        rows: list[dict] = []
        workspace_root = ctx.oc_home / "workspace"
        if not workspace_root.exists():
            return rows
        for role_dir in sorted(workspace_root.iterdir()):
            if not role_dir.is_dir():
                continue
            skills_dir = role_dir / "skills"
            if not skills_dir.exists():
                continue
            for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
                rows.append(_skill_row(skill_md, role=role_dir.name))
        rows.sort(key=lambda row: (row["role"], row["skill"]))
        return rows

    def _find_skill(role: str, skill: str) -> Path:
        skill_md = _skill_dir(role, skill) / "SKILL.md"
        if not skill_md.exists():
            raise HTTPException(status_code=404, detail="skill_not_found")
        return skill_md

    @app.get("/console/agents")
    def list_agents():
        return _agent_rows()

    @app.get("/console/agents/{agent}/skills")
    def get_agent_skills(agent: str):
        skills_dir = ctx.oc_home / "workspace" / agent / "skills"
        if not skills_dir.exists():
            return []
        out = []
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            row = _skill_row(skill_md, role=agent)
            out.append({"skill": row["skill"], "enabled": row["enabled"], "title": row["title"]})
        return out

    @app.patch("/console/agents/{agent}/skills/{skill}/enabled")
    async def set_skill_enabled(agent: str, skill: str, request: Request):
        body = await request.json()
        enabled = bool(body.get("enabled"))
        skill_dir = _skill_dir(agent, skill)
        if not skill_dir.exists():
            raise HTTPException(status_code=404, detail="skill_not_found")
        marker = skill_dir / ".disabled"
        if enabled:
            if marker.exists():
                marker.unlink()
        else:
            marker.write_text("disabled", encoding="utf-8")
        ctx.audit_console("update", f"agent-skill:{agent}:{skill}", {"enabled": not enabled}, {"enabled": enabled})
        return {"ok": True, "agent": agent, "skill": skill, "enabled": enabled}

    @app.get("/console/skills")
    def list_skills(role: str | None = None):
        rows = _all_skill_rows()
        if role:
            target = str(role).strip()
            rows = [row for row in rows if row["role"] == target]
        return rows

    @app.get("/console/skills/{role}/{skill}")
    def get_skill(role: str, skill: str):
        skill_md = _find_skill(role, skill)
        row = _skill_row(skill_md, role=role)
        row["content"] = skill_md.read_text(encoding="utf-8")
        return row

    @app.put("/console/skills/{role}/{skill}")
    async def update_skill(role: str, skill: str, request: Request):
        body = await request.json()
        content = str(body.get("content") or "")
        if not content.strip():
            raise HTTPException(status_code=400, detail="skill_content_required")
        skill_dir = _skill_dir(role, skill)
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"
        before = skill_md.read_text(encoding="utf-8") if skill_md.exists() else ""
        skill_md.write_text(content, encoding="utf-8")
        ctx.audit_console("update", f"skill:{role}:{skill}", {"content": before}, {"content": content})
        return {"ok": True, "role": role, "skill": skill}

    @app.get("/console/skills/proposals")
    def list_skill_evolution(status: str | None = None, limit: int = 100):
        proposals = ctx.sync_skill_proposals()
        if status:
            proposals = [p for p in proposals if str(p.get("status", "")) == status]
        return proposals[: max(1, min(limit, 500))]

    @app.post("/console/skills/proposals/{proposal_id}/review")
    async def review_skill_evolution(proposal_id: str, request: Request):
        body = await request.json()
        decision = str(body.get("decision") or "").strip().lower()
        reviewer = str(body.get("reviewer") or "console")
        note = str(body.get("note") or "")
        auto_apply = bool(body.get("apply"))
        if decision not in {"approve", "reject"}:
            raise HTTPException(status_code=400, detail="decision_must_be_approve_or_reject")

        proposals = ctx.sync_skill_proposals()
        target = next((row for row in proposals if str(row.get("proposal_id") or "") == proposal_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="proposal_not_found")

        target["reviewed_utc"] = ctx.utc()
        target["reviewed_by"] = reviewer
        target["review_note"] = note
        if decision == "reject":
            target["status"] = "rejected"
            target["apply_error"] = ""
            target["applied_utc"] = ""
            ctx.write_json_list(ctx.skill_queue_path, proposals)
            return {"ok": True, "proposal_id": proposal_id, "status": target["status"]}

        target["status"] = "approved"
        target["apply_error"] = ""
        proposal_type = str(target.get("proposal_type") or "skill")
        if proposal_type == "python":
            target["status"] = "pending_human_review"
            target["apply_error"] = "python_change_requires_human_review"
        elif not ctx.sandbox_ward_open():
            target["status"] = "sandbox_blocked"
            target["apply_error"] = "sandbox_ward_closed"
        elif auto_apply or proposal_type in {"skill", "config"}:
            ok, err = ctx.apply_evolution_proposal(target)
            if ok:
                target["status"] = "applied"
                target["applied_utc"] = ctx.utc()
                target["apply_error"] = ""
            else:
                target["status"] = "apply_failed"
                target["apply_error"] = err

        ctx.write_json_list(ctx.skill_queue_path, proposals)
        return {"ok": True, "proposal_id": proposal_id, "status": target["status"], "apply_error": target.get("apply_error", "")}

    @app.post("/console/skills/proposals/{proposal_id}/apply")
    def apply_skill_evolution(proposal_id: str):
        proposals = ctx.sync_skill_proposals()
        target = next((row for row in proposals if str(row.get("proposal_id") or "") == proposal_id), None)
        if not target:
            raise HTTPException(status_code=404, detail="proposal_not_found")
        if str(target.get("status") or "") == "rejected":
            raise HTTPException(status_code=400, detail="proposal_rejected")
        if str(target.get("proposal_type") or "") == "python":
            target["status"] = "pending_human_review"
            target["apply_error"] = "python_change_requires_human_review"
            ctx.write_json_list(ctx.skill_queue_path, proposals)
            return {"ok": False, "proposal_id": proposal_id, "status": target["status"], "apply_error": target["apply_error"]}
        if not ctx.sandbox_ward_open():
            target["status"] = "sandbox_blocked"
            target["apply_error"] = "sandbox_ward_closed"
            ctx.write_json_list(ctx.skill_queue_path, proposals)
            return {"ok": False, "proposal_id": proposal_id, "status": target["status"], "apply_error": target["apply_error"]}

        ok, err = ctx.apply_evolution_proposal(target)
        if ok:
            target["status"] = "applied"
            target["applied_utc"] = ctx.utc()
            target["apply_error"] = ""
        else:
            target["status"] = "apply_failed"
            target["apply_error"] = err
        ctx.write_json_list(ctx.skill_queue_path, proposals)
        return {"ok": ok, "proposal_id": proposal_id, "status": target["status"], "apply_error": target.get("apply_error", "")}
