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
    from runtime.cortex import Cortex
    from spine.nerve import Nerve

from runtime.drive_accounts import DriveAccountRegistry


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


logger = logging.getLogger(__name__)

_CONTRACTS_DIR = Path(__file__).parent.parent / "config" / "semantics" / "quality_contracts"


class DeliveryService:
    def __init__(
        self,
        compass: "CompassFabric",
        nerve: "Nerve",
        daemon_home: Path,
        cortex: "Cortex | None" = None,
    ) -> None:
        self._compass = compass
        self._nerve = nerve
        self._home = daemon_home
        self._cortex = cortex
        self._drive_registry = DriveAccountRegistry(self._home / "state")

    def deliver(self, run_root: str, plan: dict, step_results: list[dict]) -> dict:
        """Full delivery pipeline: quality gate → archive → channel routing."""
        task_type = str(plan.get("task_type") or "default")
        cluster_id = str(plan.get("cluster_id") or "")

        # Load quality contract (cluster-aware, falls back to Compass profile).
        contract = self._load_contract(cluster_id, task_type)
        profile = self._compass.get_quality_profile(task_type)

        # Find render output.
        render_file = self._find_render_output(Path(run_root), step_results)
        if not render_file:
            return {"ok": False, "error_code": "render_output_missing"}

        content = render_file.read_text()

        # Compute continuous quality score (replaces binary gate).
        quality_score, score_components = self._compute_quality_score(
            content, plan, step_results, contract, profile
        )
        min_quality = float(contract.get("min_quality_score") or profile.get("min_quality_score") or 0.60)
        if quality_score < min_quality:
            return {
                "ok": False,
                "error_code": "quality_gate_failed",
                "quality_score": round(quality_score, 4),
                "min_quality_score": min_quality,
                "score_components": score_components,
            }

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
            "quality_score": round(quality_score, 4),
        })

        return {
            "ok": True,
            "outcome_path": str(outcome_dir),
            "delivered_utc": _utc(),
            "quality_score": round(quality_score, 4),
            "score_components": score_components,
        }

    def _load_contract(self, cluster_id: str, task_type: str) -> dict:
        """Load quality contract JSON for cluster_id or task_type, fallback to {}."""
        # Try cluster-based contract first.
        if cluster_id:
            p = _CONTRACTS_DIR / f"{cluster_id}.json"
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.warning("Failed to load quality contract %s: %s", p, exc)
        # Try task_type-based contract.
        if task_type:
            p = _CONTRACTS_DIR / f"{task_type}.json"
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.warning("Failed to load quality contract %s: %s", p, exc)
        return {}

    def _compute_quality_score(
        self,
        content: str,
        plan: dict,
        step_results: list[dict],
        contract: dict,
        profile: dict,
    ) -> tuple[float, dict]:
        """Return (quality_score 0-1, score_components dict)."""
        weights = contract.get("quality_weights") or {
            "structural": 0.50,
            "evidence_completeness": 0.30,
            "content_review": 0.20,
        }
        structural_w = float(weights.get("structural") or 0.50)
        evidence_w = float(weights.get("evidence_completeness") or 0.30)
        review_w = float(weights.get("content_review") or 0.20)

        structural_score = self._structural_score(content, contract, profile)
        evidence_score = self._evidence_score(plan, step_results)
        review_score = self._content_review_score(content, structural_score)

        composite = (
            structural_w * structural_score
            + evidence_w * evidence_score
            + review_w * review_score
        )

        components = {
            "structural": round(structural_score, 4),
            "evidence_completeness": round(evidence_score, 4),
            "content_review": round(review_score, 4),
            "weights": {"structural": structural_w, "evidence_completeness": evidence_w, "content_review": review_w},
        }
        return composite, components

    def _quality_gate(self, content: str, profile: dict) -> dict:
        """Compatibility deterministic quality gate used by tests and legacy callers."""
        for marker in (profile.get("forbidden_markers") or []):
            if marker.lower() in content.lower():
                return {"ok": False, "error_code": "forbidden_marker", "detail": f"Contains forbidden marker: {marker}"}

        min_words = int(profile.get("min_word_count") or 0)
        words = self._effective_word_count(content)
        if min_words and words < min_words:
            return {"ok": False, "error_code": "word_count_too_low", "detail": f"{words} < {min_words}"}

        min_sections = int(profile.get("min_sections") or 0)
        if min_sections:
            sections = [ln for ln in content.splitlines() if ln.strip().startswith("#")]
            if len(sections) < min_sections:
                return {"ok": False, "error_code": "sections_too_few", "detail": f"{len(sections)} < {min_sections}"}

        min_items = int(profile.get("min_items") or 0)
        if min_items:
            bullets = [ln for ln in content.splitlines() if ln.strip().startswith(("-", "*", "1.", "2.", "3."))]
            if len(bullets) < min_items:
                return {"ok": False, "error_code": "brief_items_too_few", "detail": f"{len(bullets)} < {min_items}"}

        if bool(profile.get("require_bilingual")):
            has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in content)
            has_latin = any("a" <= ch.lower() <= "z" for ch in content)
            if not (has_cjk and has_latin):
                return {"ok": False, "error_code": "bilingual_incomplete", "detail": "missing zh/en mixed content"}
        return {"ok": True}

    def _structural_score(self, content: str, contract: dict, profile: dict) -> float:
        """Normalized structural score 0-1. Hard-zero on forbidden markers."""
        structural = contract.get("structural") or {}
        forbidden = structural.get("forbidden_markers") or profile.get("forbidden_markers") or []
        for marker in forbidden:
            if marker.lower() in content.lower():
                return 0.0  # Hard fail

        words = self._effective_word_count(content)
        min_words = int(structural.get("min_word_count") or profile.get("min_word_count") or 0)
        word_score = min(words / min_words, 1.0) if min_words else 1.0

        sections = [ln for ln in content.splitlines() if ln.strip().startswith("#")]
        min_sections = int(structural.get("min_sections") or profile.get("min_sections") or 0)
        section_score = min(len(sections) / min_sections, 1.0) if min_sections else 1.0

        min_items = int(profile.get("min_items") or 0)
        if min_items:
            bullets = [ln for ln in content.splitlines() if ln.strip().startswith(("-", "*", "1.", "2.", "3."))]
            item_score = min(len(bullets) / min_items, 1.0)
        else:
            item_score = 1.0

        bilingual = structural.get("bilingual_check") or profile.get("require_bilingual") or False
        if bilingual:
            has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in content)
            has_latin = any("a" <= ch.lower() <= "z" for ch in content)
            bilingual_score = 1.0 if (has_cjk and has_latin) else 0.0
        else:
            bilingual_score = 1.0

        return (word_score + section_score + item_score + bilingual_score) / 4.0

    def _effective_word_count(self, content: str) -> int:
        """Estimate word count robustly for mixed Chinese/English text."""
        text = str(content or "")
        whitespace_tokens = len(text.split())
        latin_tokens = len(re.findall(r"[A-Za-z0-9]+(?:[-_'][A-Za-z0-9]+)*", text))
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        cjk_tokens = (cjk_chars + 1) // 2
        return max(whitespace_tokens, latin_tokens + cjk_tokens)

    def _evidence_score(self, plan: dict, step_results: list[dict]) -> float:
        """Evidence completeness 0-1 based on evidence_unit_ids or step outputs."""
        evidence_ids = plan.get("evidence_unit_ids")
        if isinstance(evidence_ids, list) and len(evidence_ids) > 0:
            target = max(int(plan.get("evidence_target", 5)), 1)
            return min(len(evidence_ids) / target, 1.0)

        # Fallback: count steps with non-empty output as evidence.
        steps_with_output = sum(
            1 for r in step_results
            if r.get("output") or r.get("artifacts") or r.get("evidence")
        )
        if not step_results:
            return 0.5  # Unknown
        target = max(len(step_results) // 2, 1)
        return min(steps_with_output / target, 1.0)

    def _content_review_score(self, content: str, structural_score: float) -> float:
        """LLM content review 0-1; fallback to structural_score if unavailable."""
        if not self._cortex or not self._cortex.is_available():
            return structural_score

        prompt = (
            "Rate the quality of this report on a scale from 0 to 10. "
            "Consider: clarity, completeness, accuracy, and usefulness. "
            "Respond with a single integer 0-10.\n\n"
            f"{content[:3000]}"
        )
        try:
            result = self._cortex.complete(prompt, max_tokens=10)
            text = (result or "").strip()
            # Extract first integer found.
            m = re.search(r"\b(\d+)\b", text)
            if m:
                score = int(m.group(1))
                return min(max(score / 10.0, 0.0), 1.0)
        except Exception as exc:
            logger.warning("Content review LLM call failed: %s", exc)
        return structural_score

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
        outcome_root = self._resolve_outcome_root()

        if task_type in ("daily_brief", "weekly_brief"):
            today = time.strftime("%Y-%m-%d")
            dest = outcome_root / "scheduled" / task_type / today
        else:
            dest = outcome_root / "manual" / title

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
        outcome_root = self._resolve_outcome_root()
        index_path = outcome_root / "index.json"
        try:
            index = json.loads(index_path.read_text())
        except Exception as exc:
            logger.warning("Failed to parse outcome index %s: %s", index_path, exc)
            index = []
        try:
            rel_path = str(outcome_dir.relative_to(outcome_root))
        except Exception:
            rel_path = str(outcome_dir)
        index.append({
            "path": rel_path,
            "title": plan.get("title", ""),
            "task_type": plan.get("task_type", "manual"),
            "task_id": plan.get("task_id", ""),
            "delivered_utc": _utc(),
        })
        index_path.write_text(json.dumps(index[-1000:], ensure_ascii=False, indent=2))

    def _resolve_outcome_root(self) -> Path:
        resolved = self._drive_registry.resolve_outcome_root()
        if not resolved.get("ok"):
            raise RuntimeError(f"drive_outcome_unavailable: {resolved.get('error', '')}")
        root = Path(str(resolved.get("outcome_root") or "")).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root

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
