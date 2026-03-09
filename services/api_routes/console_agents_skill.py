"""Console agent and skill evolution routes."""
from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_agents_skill_routes(app: FastAPI, *, ctx: Any) -> None:
    # ── Console — Agent manager ───────────────────────────────────────────────

    @app.get("/console/agents")
    def list_agents():
        cfg_path = ctx.oc_home / "openclaw.json"
        if not cfg_path.exists():
            return []
        try:
            cfg = json.loads(cfg_path.read_text())
        except Exception as exc:
            ctx.logger.warning("Failed to read openclaw.json: %s", exc)
            return []
        agents = cfg.get("agents", {}).get("list", [])
        result = []
        for agent in agents:
            agent_id = agent.get("id", "")
            workspace = ctx.oc_home / "workspace" / agent_id
            skills_dir = workspace / "skills"
            skills_count = len(list(skills_dir.glob("*/SKILL.md"))) if skills_dir.exists() else 0
            result.append({
                "id": agent_id,
                "workspace_exists": workspace.exists(),
                "skills_count": skills_count,
            })
        return result

    @app.get("/console/agents/{agent}/skills")
    def get_agent_skills(agent: str):
        skills_dir = ctx.oc_home / "workspace" / agent / "skills"
        if not skills_dir.exists():
            return []
        out = []
        for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
            skill_dir = skill_md.parent
            disabled = (skill_dir / ".disabled").exists()
            content = skill_md.read_text()
            out.append(
                {
                    "skill": skill_dir.name,
                    "enabled": not disabled,
                    "path": str(skill_md),
                    "content": content,
                }
            )
        return out

    @app.put("/console/agents/{agent}/skills/{skill}")
    async def update_agent_skill(agent: str, skill: str, request: Request):
        body = await request.json()
        content = str(body.get("content") or "")
        if not content.strip():
            raise HTTPException(status_code=400, detail="content required")
        skill_dir = ctx.oc_home / "workspace" / agent / "skills" / skill
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(content)
        return {"ok": True, "agent": agent, "skill": skill}

    @app.patch("/console/agents/{agent}/skills/{skill}/enabled")
    async def set_skill_enabled(agent: str, skill: str, request: Request):
        body = await request.json()
        enabled = bool(body.get("enabled"))
        skill_dir = ctx.oc_home / "workspace" / agent / "skills" / skill
        if not skill_dir.exists():
            raise HTTPException(status_code=404, detail="skill not found")
        marker = skill_dir / ".disabled"
        if enabled:
            if marker.exists():
                marker.unlink()
        else:
            marker.write_text("disabled")
        return {"ok": True, "agent": agent, "skill": skill, "enabled": enabled}

    # ── Console — Skill Evolution ────────────────────────────────────────────

    @app.get("/console/skill-evolution/proposals")
    def list_skill_evolution(status: str | None = None, limit: int = 100):
        proposals = ctx.sync_skill_proposals()
        if status:
            proposals = [p for p in proposals if str(p.get("status", "")) == status]
        return proposals[: max(1, min(limit, 500))]

    @app.post("/console/skill-evolution/proposals/{proposal_id}/review")
    async def review_skill_evolution(proposal_id: str, request: Request):
        body = await request.json()
        decision = str(body.get("decision") or "").strip().lower()
        reviewer = str(body.get("reviewer") or "console")
        note = str(body.get("note") or "")
        auto_apply = bool(body.get("apply"))
        if decision not in {"approve", "reject"}:
            raise HTTPException(status_code=400, detail="decision must be approve|reject")

        proposals = ctx.sync_skill_proposals()
        target = None
        for row in proposals:
            if str(row.get("proposal_id") or "") == proposal_id:
                target = row
                break
        if not target:
            raise HTTPException(status_code=404, detail="proposal not found")

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

    @app.post("/console/skill-evolution/proposals/{proposal_id}/apply")
    def apply_skill_evolution(proposal_id: str):
        proposals = ctx.sync_skill_proposals()
        target = None
        for row in proposals:
            if str(row.get("proposal_id") or "") == proposal_id:
                target = row
                break
        if not target:
            raise HTTPException(status_code=404, detail="proposal not found")
        if str(target.get("status") or "") == "rejected":
            raise HTTPException(status_code=400, detail="proposal rejected")
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
