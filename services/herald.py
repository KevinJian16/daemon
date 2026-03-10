"""Herald Service — offering archiving, PDF generation, channel routing (pure logistics)."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from html import unescape
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from services.storage_paths import resolve_offering_root

if TYPE_CHECKING:
    from psyche.instinct import InstinctPsyche
    from spine.nerve import Nerve


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


logger = logging.getLogger(__name__)


class HeraldService:
    def __init__(
        self,
        instinct: "InstinctPsyche",
        nerve: "Nerve",
        daemon_home: Path,
        ledger: "Ledger | None" = None,
    ) -> None:
        from services.ledger import Ledger

        self._instinct = instinct
        self._nerve = nerve
        self._home = daemon_home
        self._ledger = ledger or Ledger(daemon_home / "state")

    def deliver(self, deed_root: str, plan: dict, move_results: list[dict]) -> dict:
        """Herald pipeline: find scribe output -> vault -> PDF -> index -> notify."""
        render_file = self._find_scribe_output(Path(deed_root), move_results)
        if not render_file:
            return {"ok": False, "error_code": "scribe_output_missing"}

        content = render_file.read_text()

        offering_dir = self._vault(deed_root, plan, render_file)
        self._generate_pdf_best_effort(offering_dir, render_file)
        self._update_index(offering_dir, plan)

        prefs = self._instinct.all_prefs()
        self._route_telegram(content, plan, prefs)

        self._nerve.emit("herald_completed", {
            "deed_id": plan.get("deed_id", ""),
            "offering_path": str(offering_dir),
        })

        return {
            "ok": True,
            "offering_path": str(offering_dir),
            "delivered_utc": _utc(),
        }

    def _generate_pdf_best_effort(self, offering_dir: Path, render_file: Path) -> None:
        pdf_path = offering_dir / "report.pdf"
        try:
            text = render_file.read_text(encoding="utf-8", errors="ignore")
            if render_file.suffix.lower() == ".html":
                text = self._html_to_text(text)
            self._write_simple_pdf(text, pdf_path)
        except Exception as exc:
            logger.warning("PDF best-effort generation failed for %s: %s", render_file, exc)

    def _html_to_text(self, html: str) -> str:
        cleaned = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.IGNORECASE)
        cleaned = re.sub(r"<style[\s\S]*?</style>", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = unescape(cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
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

    def _find_scribe_output(self, deed_root: Path, move_results: list[dict]) -> Path | None:
        for res in reversed(move_results):
            sid = res.get("move_id", "")
            if "scribe" in sid.lower() or "render" in sid.lower():
                candidates = [
                    deed_root / "moves" / sid / "output" / "output.md",
                    deed_root / "moves" / sid / "deliver" / "report.html",
                ]
                for c in candidates:
                    if c.exists():
                        return c
        for pat in ("**/deliver/*.html", "**/output/*.md", "**/deliver/*.md"):
            files = sorted(deed_root.glob(pat), key=lambda p: p.stat().st_mtime, reverse=True)
            if files:
                return files[0]
        return None

    def _vault(self, deed_root: str, plan: dict, render_file: Path) -> Path:
        brief = plan.get("brief") or {}
        raw_title = str(
            plan.get("deed_title")
            or plan.get("title")
            or brief.get("objective", "")
            or "untitled"
        )
        title = raw_title[:60].replace("/", "-").replace(":", "-").strip()
        offering_root = self._resolve_offering_root()

        month_dir = time.strftime("%Y-%m")
        timestamp = time.strftime("%Y-%m-%d %H.%M")
        dest = offering_root / month_dir / f"{timestamp} {title}"
        dest.mkdir(parents=True, exist_ok=True)

        safe_title = title[:80]
        out = dest / f"{safe_title}{render_file.suffix}"
        out.write_bytes(render_file.read_bytes())

        return dest

    def _update_index(self, offering_dir: Path, plan: dict) -> None:
        offering_root = self._resolve_offering_root()
        try:
            rel_path = str(offering_dir.relative_to(offering_root))
        except Exception:
            rel_path = str(offering_dir)
        brief = plan.get("brief") or {}
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        entry = {
            "path": rel_path,
            "title": plan.get("slip_title") or plan.get("deed_title", plan.get("title", "")),
            "deed_id": plan.get("deed_id", ""),
            "slip_id": metadata.get("slip_id") or plan.get("slip_id") or "",
            "folio_id": metadata.get("folio_id") or plan.get("folio_id") or "",
            "delivered_utc": _utc(),
        }
        self._ledger.append_herald_log(entry)

    def _resolve_offering_root(self) -> Path:
        return resolve_offering_root(self._ledger.state_dir)

    def _route_telegram(self, content: str, plan: dict, prefs: dict[str, str]) -> None:
        if prefs.get("telegram_enabled") != "true":
            return
        adapter_url = os.environ.get("TELEGRAM_ADAPTER_URL", "http://127.0.0.1:8001")
        brief = plan.get("brief") or {}
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        notify_payload = {
            "event": "deed_completed",
            "payload": {
                "deed_id": str(plan.get("deed_id") or ""),
                "slip_id": str(metadata.get("slip_id") or plan.get("slip_id") or ""),
                "folio_id": str(metadata.get("folio_id") or plan.get("folio_id") or ""),
                "deed_title": str(
                    plan.get("slip_title")
                    or plan.get("deed_title")
                    or plan.get("title")
                    or brief.get("objective", "")
                    or "签札"
                ),
                "summary": content[:1200].strip(),
            },
        }
        try:
            httpx.post(f"{adapter_url}/notify", json=notify_payload, timeout=10)
        except Exception as exc:
            logger.warning("Telegram adapter notify failed for deed %s: %s", plan.get("deed_id", ""), exc)
            self._ledger.enqueue_failed_notification({
                "channel": "telegram",
                "adapter_url": adapter_url,
                "payload": notify_payload,
                "error": str(exc)[:200],
            })
