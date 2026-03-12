"""Console psyche routes — voice, ledger stats, ledger templates (§14.2)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request


def register_console_psyche_routes(app: FastAPI, *, ctx: Any) -> None:
    # ── Voice endpoints ──────────────────────────────────────────────────────

    @app.get("/console/psyche/voice")
    def console_voice():
        """Return voice files content (§14.2)."""
        psyche_dir = ctx.psyche_config._psyche_dir if hasattr(ctx.psyche_config, "_psyche_dir") else ctx.state.parent / "psyche"
        voice_dir = psyche_dir / "voice"
        result: dict[str, str] = {}
        for name in ("identity.md", "common.md", "zh.md", "en.md"):
            path = voice_dir / name
            if path.exists():
                try:
                    result[name] = path.read_text(encoding="utf-8")
                except Exception:
                    result[name] = ""
            else:
                result[name] = ""
        # Overlays
        overlays_dir = psyche_dir / "overlays"
        overlay_files: dict[str, str] = {}
        if overlays_dir.exists():
            for p in sorted(overlays_dir.glob("*.md")):
                try:
                    overlay_files[p.name] = p.read_text(encoding="utf-8")
                except Exception:
                    overlay_files[p.name] = ""
        result["overlays"] = overlay_files
        return result

    @app.put("/console/psyche/voice/{filename}")
    async def console_update_voice(filename: str, request: Request):
        """Update a voice file (§14.2)."""
        if not filename.endswith(".md"):
            raise HTTPException(status_code=400, detail="filename must end with .md")
        allowed = {"identity.md", "common.md", "zh.md", "en.md"}
        psyche_dir = ctx.psyche_config._psyche_dir if hasattr(ctx.psyche_config, "_psyche_dir") else ctx.state.parent / "psyche"

        if filename in allowed:
            target = psyche_dir / "voice" / filename
        elif filename.startswith("overlays/"):
            target = psyche_dir / filename
        else:
            raise HTTPException(status_code=400, detail=f"Unknown voice file: {filename}")

        body = await request.body()
        content = body.decode("utf-8", errors="replace")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "file": str(target.relative_to(psyche_dir))}

    # ── Config snapshot (replaces old instinct endpoint) ─────────────────────

    @app.get("/console/psyche/config")
    def console_psyche_config():
        """Return PsycheConfig snapshot (§14.2 — replaces /console/psyche/instinct)."""
        return ctx.psyche_config.snapshot()

    # ── Ledger stats ─────────────────────────────────────────────────────────

    @app.get("/console/ledger/stats")
    def console_ledger_stats():
        """Return deed/skill/agent statistics (§14.2)."""
        ls = ctx.ledger_stats
        return {
            "global_hints": ls.global_planning_hints(),
            "skills_needing_review": ls.skills_needing_review(),
            "agent_summary": ls.agent_summary(),
        }

    @app.get("/console/ledger/templates")
    def console_ledger_templates():
        """Return DAG and Folio templates (§14.2)."""
        ls = ctx.ledger_stats
        hints = ls.global_planning_hints()
        # Return top templates without needing an embedding query
        return {
            "dag_template_count": hints.get("dag_template_count", 0),
            "folio_template_count": hints.get("folio_template_count", 0),
            "top_dag_templates": hints.get("top_dag_templates", []),
        }
