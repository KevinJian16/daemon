"""Delivery Service — structural quality gate, outcome archiving, channel routing."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from html import unescape
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from fabric.compass import CompassFabric
    from spine.nerve import Nerve


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


logger = logging.getLogger(__name__)


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
        self._generate_pdf_best_effort(outcome_dir, render_file)
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

    def _generate_pdf_best_effort(self, outcome_dir: Path, render_file: Path) -> None:
        pdf_path = outcome_dir / "report.pdf"
        try:
            text = render_file.read_text(encoding="utf-8", errors="ignore")
            if render_file.suffix.lower() == ".html":
                text = self._html_to_text(text)
            self._write_simple_pdf(text, pdf_path)
        except Exception as exc:
            logger.warning("PDF best-effort generation failed for %s: %s", render_file, exc)

    def _html_to_text(self, html: str) -> str:
        cleaned = re.sub(r"<script[\\s\\S]*?</script>", " ", html, flags=re.IGNORECASE)
        cleaned = re.sub(r"<style[\\s\\S]*?</style>", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = unescape(cleaned)
        cleaned = re.sub(r"\\s+", " ", cleaned).strip()
        return cleaned

    def _write_simple_pdf(self, text: str, pdf_path: Path) -> None:
        lines = (text or "").replace("\r", "").split("\n")
        lines = [ln.strip() for ln in lines if ln.strip()]
        if not lines:
            lines = ["(empty report)"]
        wrapped: list[str] = []
        for ln in lines:
            while len(ln) > 96:
                wrapped.append(ln[:96])
                ln = ln[96:]
            wrapped.append(ln)
        page_size = 48
        pages = [wrapped[i:i + page_size] for i in range(0, len(wrapped), page_size)]
        if not pages:
            pages = [["(empty report)"]]

        objects: list[bytes | None] = [None]
        page_object_ids: list[int] = []
        content_object_ids: list[int] = []

        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")  # 1
        objects.append(b"<< /Type /Pages /Kids [] /Count 0 >>")  # 2 placeholder
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")  # 3

        for page_lines in pages:
            content_stream = self._pdf_stream(page_lines)
            content_obj = len(objects)
            objects.append(
                f"<< /Length {len(content_stream)} >>\nstream\n".encode("latin-1")
                + content_stream
                + b"\nendstream"
            )
            content_object_ids.append(content_obj)
            page_obj = len(objects)
            objects.append(
                (
                    f"<< /Type /Page /Parent 2 0 R "
                    f"/MediaBox [0 0 595 842] "
                    f"/Resources << /Font << /F1 3 0 R >> >> "
                    f"/Contents {content_obj} 0 R >>"
                ).encode("latin-1")
            )
            page_object_ids.append(page_obj)

        kids = " ".join(f"{pid} 0 R" for pid in page_object_ids)
        objects[2] = f"<< /Type /Pages /Kids [ {kids} ] /Count {len(page_object_ids)} >>".encode("latin-1")

        out = bytearray()
        out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for i in range(1, len(objects)):
            offsets.append(len(out))
            out.extend(f"{i} 0 obj\n".encode("latin-1"))
            out.extend(objects[i] or b"")
            out.extend(b"\nendobj\n")
        xref = len(out)
        out.extend(f"xref\n0 {len(objects)}\n".encode("latin-1"))
        out.extend(b"0000000000 65535 f \n")
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
        out.extend(f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("latin-1"))
        pdf_path.write_bytes(bytes(out))

    def _pdf_stream(self, lines: list[str]) -> bytes:
        chunks = ["BT", "/F1 11 Tf", "50 790 Td", "14 TL"]
        for ln in lines:
            safe = ln.encode("latin-1", "replace").decode("latin-1")
            safe = safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            chunks.append(f"({safe}) Tj")
            chunks.append("T*")
        chunks.append("ET")
        return ("\n".join(chunks) + "\n").encode("latin-1")

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

        min_items = int(profile.get("min_items") or 0)
        if min_items:
            bullet_items = [ln for ln in content.splitlines() if ln.strip().startswith(("-", "*", "1.", "2.", "3."))]
            if len(bullet_items) < min_items:
                return {"ok": False, "error_code": "brief_items_too_few"}

        min_domain_coverage = int(profile.get("min_domain_coverage") or 0)
        if min_domain_coverage:
            domains = set()
            for ln in content.splitlines():
                low = ln.lower()
                if "domain:" in low:
                    domains.add(low.split("domain:", 1)[1].strip())
            if len(domains) < min_domain_coverage:
                return {"ok": False, "error_code": "brief_domain_coverage_too_low"}

        if bool(profile.get("require_bilingual")):
            has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in content)
            has_latin = any("a" <= ch.lower() <= "z" for ch in content)
            if not (has_cjk and has_latin):
                return {"ok": False, "error_code": "bilingual_incomplete"}

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
        except Exception as exc:
            logger.warning("Failed to parse outcome index %s: %s", index_path, exc)
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
        except Exception as exc:
            logger.warning("Telegram delivery failed for task %s: %s", plan.get("task_id", ""), exc)
