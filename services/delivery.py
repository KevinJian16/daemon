"""Delivery Service — structural quality gate, outcome archiving, channel routing."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from fabric.compass import CompassFabric
    from spine.nerve import Nerve


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class DeliveryService:
    def __init__(self, compass: "CompassFabric", nerve: "Nerve", daemon_home: Path) -> None:
        self._compass = compass
        self._nerve = nerve
        self._home = daemon_home

    def deliver(self, run_root: str, plan: dict, step_results: list[dict]) -> dict:
        """Full delivery pipeline: quality gate → archive → channel routing."""
        task_type = str(plan.get("task_type") or "default")
        profile = self._compass.get_quality_profile(task_type)

        # Find render output.
        render_file = self._find_render_output(Path(run_root), step_results)
        if not render_file:
            return {"ok": False, "error_code": "render_output_missing"}

        content = render_file.read_text()

        # Structural quality gate (deterministic — no LLM).
        check = self._quality_gate(content, profile)
        if not check["ok"]:
            return check

        # Archive.
        outcome_dir = self._archive(run_root, plan, render_file)
        self._update_index(outcome_dir, plan)

        # Channel routing (best-effort — failures don't block delivery).
        prefs = self._compass.all_prefs()
        self._route_telegram(content, plan, prefs)

        self._nerve.emit("delivery_completed", {
            "task_id": plan.get("task_id", ""),
            "outcome_path": str(outcome_dir),
        })

        return {
            "ok": True,
            "outcome_path": str(outcome_dir),
            "delivered_utc": _utc(),
        }

    def _quality_gate(self, content: str, profile: dict) -> dict:
        for marker in profile.get("forbidden_markers") or []:
            if marker.lower() in content.lower():
                return {"ok": False, "error_code": "forbidden_marker", "detail": f"Contains: {marker}"}

        min_words = int(profile.get("min_word_count") or 0)
        if min_words and len(content.split()) < min_words:
            return {"ok": False, "error_code": "word_count_too_low"}

        min_sections = int(profile.get("min_sections") or 0)
        if min_sections:
            sections = [ln for ln in content.splitlines() if ln.strip().startswith("#")]
            if len(sections) < min_sections:
                return {"ok": False, "error_code": "sections_too_few"}

        return {"ok": True}

    def _find_render_output(self, run_root: Path, step_results: list[dict]) -> Path | None:
        for res in reversed(step_results):
            sid = res.get("step_id", "")
            if "render" in sid.lower():
                candidates = [
                    run_root / "steps" / sid / "output" / "output.md",
                    run_root / "steps" / sid / "deliver" / "report.html",
                ]
                for c in candidates:
                    if c.exists():
                        return c
        for pat in ("**/deliver/*.html", "**/output/*.md", "**/deliver/*.md"):
            files = sorted(run_root.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True)
            if files:
                return files[0]
        return None

    def _archive(self, run_root: str, plan: dict, render_file: Path) -> Path:
        task_type = str(plan.get("task_type") or "manual")
        task_id = str(plan.get("task_id") or uuid.uuid4().hex[:8])
        title = str(plan.get("title") or task_id)[:60].replace("/", "-").strip()

        if task_type in ("daily_brief", "weekly_brief"):
            today = time.strftime("%Y-%m-%d")
            dest = self._home / "outcome" / "scheduled" / task_type / today
        else:
            dest = self._home / "outcome" / "manual" / title

        dest.mkdir(parents=True, exist_ok=True)
        out = dest / f"report{render_file.suffix}"
        out.write_text(render_file.read_text())

        manifest = {
            "task_id": task_id,
            "title": title,
            "task_type": task_type,
            "run_root": run_root,
            "delivered_utc": _utc(),
        }
        (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        return dest

    def _update_index(self, outcome_dir: Path, plan: dict) -> None:
        index_path = self._home / "outcome" / "index.json"
        try:
            index = json.loads(index_path.read_text())
        except Exception:
            index = []
        index.append({
            "path": str(outcome_dir.relative_to(self._home / "outcome")),
            "title": plan.get("title", ""),
            "task_type": plan.get("task_type", "manual"),
            "task_id": plan.get("task_id", ""),
            "delivered_utc": _utc(),
        })
        index_path.write_text(json.dumps(index[-1000:], ensure_ascii=False, indent=2))

    def _route_telegram(self, content: str, plan: dict, prefs: dict[str, str]) -> None:
        if prefs.get("telegram_enabled") != "true":
            return
        bot_token = __import__("os").environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = prefs.get("telegram_chat_id") or __import__("os").environ.get("TELEGRAM_CHAT_ID", "")
        if not bot_token or not chat_id:
            return
        title = plan.get("title", "Daemon Delivery")
        summary = content[:800].strip()
        msg = f"*{title}*\n\n{summary}"
        try:
            httpx.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                timeout=15,
            )
        except Exception:
            pass  # Best-effort; never block delivery.
