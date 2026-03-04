"""Daemon Activities — Temporal activity implementations for Agent steps and Spine Routines."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from html import unescape
from pathlib import Path
from typing import Any

from temporalio import activity
from runtime.event_bridge import EventBridge
from runtime.openclaw import OpenClawAdapter


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _daemon_home() -> Path:
    return Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))


def _openclaw_home() -> Path:
    v = os.environ.get("OPENCLAW_HOME")
    return Path(v) if v else _daemon_home() / "openclaw"


class DaemonActivities:
    """All Temporal activities. Instantiated once per Worker process."""

    def __init__(self) -> None:
        self._home = _daemon_home()
        self._oc_home = _openclaw_home()
        self._openclaw: OpenClawAdapter | None = None
        self._event_bridge = EventBridge(self._home / "state", source="worker")
        try:
            self._openclaw = OpenClawAdapter(self._oc_home)
        except Exception as exc:
            activity.logger.warning("Failed to initialize OpenClawAdapter from %s: %s", self._oc_home, exc)

    # ── OpenClaw step ─────────────────────────────────────────────────────────

    @activity.defn(name="activity_openclaw_step")
    async def activity_openclaw_step(self, run_root: str, plan: dict, step: dict) -> dict:
        """Execute one DAG step through OpenClawAdapter single-channel gateway."""
        if not self._openclaw:
            raise RuntimeError("OpenClawAdapter unavailable (OPENCLAW_HOME missing or openclaw.json invalid)")

        agent_id = str(step.get("agent") or "").strip()
        step_id = str(step.get("id") or "step").strip()
        task_id = str(plan.get("task_id") or run_root.split("/")[-1] or uuid.uuid4().hex[:8])
        session_key = self._openclaw.session_key(agent_id, task_id, step_id)
        instruction = str(step.get("instruction") or step.get("message") or "").strip()
        timeout_s = int(step.get("timeout_s") or plan.get("default_step_timeout_s") or 480)

        # Build context payload including Fabric snapshots.
        context_payload = self._build_step_context(run_root, plan, step)

        # Send message to Agent.
        composed_message = (
            f"{instruction}\n\n{json.dumps(context_payload, ensure_ascii=False)}"
            if context_payload
            else instruction
        )
        await asyncio.to_thread(self._openclaw.send, session_key, composed_message)

        # Poll for completion.
        deadline = time.time() + timeout_s
        poll_interval = 5
        last_content = ""

        while time.time() < deadline:
            await asyncio.sleep(poll_interval)
            try:
                messages = await asyncio.to_thread(self._openclaw.history, session_key, 1)
            except Exception as exc:
                activity.logger.warning("history poll failed for %s: %s", session_key, exc)
                poll_interval = min(poll_interval * 1.2, 30)
                continue
            if not isinstance(messages, list):
                messages = []

            latest = messages[-1] if messages else {}
            content = latest.get("content") or latest.get("text") or ""
            role = latest.get("role") or ""

            if role == "assistant" and content and content != last_content:
                last_content = content
                # Check for completion signals.
                if any(signal in content.lower() for signal in ["[done]", "[complete]", "task complete", "completed successfully"]):
                    output_path = self._write_step_output(run_root, step_id, content)
                    return {"status": "ok", "step_id": step_id, "agent": agent_id, "session_key": session_key, "output_path": output_path}

            poll_interval = min(poll_interval * 1.2, 30)

        # Timeout — mark as degraded, not error (Temporal will handle retry policy).
        activity.logger.warning(f"Step {step_id} timed out after {timeout_s}s — marking degraded")
        return {
            "status": "degraded",
            "step_id": step_id,
            "agent": agent_id,
            "session_key": session_key,
            "error": f"timeout_after_{timeout_s}s",
            "degraded": True,
        }

    # ── Spine routine ─────────────────────────────────────────────────────────

    @activity.defn(name="activity_spine_routine")
    async def activity_spine_routine(self, run_root: str, plan: dict, routine_name: str) -> dict:
        """Execute a Spine Routine directly (no OpenClaw, no LLM unless hybrid)."""
        from fabric.memory import MemoryFabric
        from fabric.playbook import PlaybookFabric
        from fabric.compass import CompassFabric
        from runtime.cortex import Cortex
        from spine.nerve import Nerve
        from spine.trace import Tracer
        from spine.routines import SpineRoutines

        home = self._home
        state = home / "state"
        memory = MemoryFabric(state / "memory.db")
        playbook = PlaybookFabric(state / "playbook.db")
        compass = CompassFabric(state / "compass.db")
        cortex = Cortex(compass)
        nerve = Nerve()
        tracer = Tracer(state / "traces")

        routines = SpineRoutines(
            memory=memory, playbook=playbook, compass=compass,
            cortex=cortex, nerve=nerve, tracer=tracer,
            daemon_home=home, openclaw_home=self._oc_home,
        )

        method = getattr(routines, routine_name.replace("spine.", ""), None)
        if not callable(method):
            raise ValueError(f"Unknown spine routine: {routine_name}")
        result = method()
        return {"status": "ok", "routine": routine_name, "result": result}

    # ── Delivery finalization ─────────────────────────────────────────────────

    @activity.defn(name="activity_finalize_delivery")
    async def activity_finalize_delivery(self, run_root: str, plan: dict, step_results: list[dict]) -> dict:
        """Structural quality gate + archive to outcome/ + Nerve emit."""
        from fabric.compass import CompassFabric

        home = self._home
        state = home / "state"
        compass = CompassFabric(state / "compass.db")
        is_shadow = bool(plan.get("is_shadow", False))

        task_type = str(plan.get("task_type") or "default").strip()
        profile = compass.get_quality_profile(task_type)

        # Find render output.
        render_path = self._find_render_output(run_root, step_results)
        if not render_path:
            return {"ok": False, "error_code": "render_output_missing", "detail": "No render output found"}

        content = render_path.read_text()

        # Structural quality checks.
        check_result = self._structural_check(content, profile)
        if not check_result["ok"]:
            return {
                "ok": False,
                "error_code": check_result["error_code"],
                "detail": check_result["detail"],
            }

        if is_shadow:
            outcome_path = self._archive_shadow_outcome(run_root, plan, render_path, step_results)
        else:
            # Archive to outcome/.
            outcome_path = self._archive_outcome(run_root, plan, render_path, step_results)
            # Update outcome index.
            self._update_outcome_index(outcome_path, plan)

        # Update task status.
        self._update_task_status(run_root, plan, "completed_shadow" if is_shadow else "completed")

        # Emit cross-process events for API process.
        task_id = str(plan.get("task_id") or "")
        delivery_payload = {
            "task_id": task_id,
            "plan": plan,
            "step_results": step_results,
            "outcome": {"ok": True, "score": 1.0, "outcome_path": str(outcome_path), "is_shadow": is_shadow},
        }
        if not is_shadow:
            self._event_bridge.emit("delivery_completed", delivery_payload)
        self._event_bridge.emit("task_completed", delivery_payload)
        activity.logger.info(f"Delivery completed for task {task_id}; bridge events emitted")

        return {
            "ok": True,
            "outcome_path": str(outcome_path),
            "task_id": task_id,
            "delivered_utc": _utc(),
            "is_shadow": is_shadow,
        }

    # ── Task status ───────────────────────────────────────────────────────────

    @activity.defn(name="activity_update_task_status")
    async def activity_update_task_status(self, run_root: str, plan: dict, status: str) -> dict:
        """Update task status in state/tasks.json (append-only for safety)."""
        self._update_task_status(run_root, plan, status)
        # Failure/terminal signal for spine.record when delivery path does not complete.
        if status in {"failed", "cancelled"}:
            task_id = str(plan.get("task_id") or "")
            self._event_bridge.emit(
                "task_completed",
                {
                    "task_id": task_id,
                    "plan": plan,
                    "step_results": [],
                    "outcome": {"ok": False, "score": 0.0, "status": status, "error": plan.get("last_error", "")},
                },
            )
        return {"ok": True, "status": status}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_step_context(self, run_root: str, plan: dict, step: dict) -> dict:
        """Attach semantic/strategy/model snapshots as execution context for Agent steps."""
        snapshots_dir = self._home / "state" / "snapshots"
        context: dict = {}
        for snap_name in (
            "compass_snapshot.json",
            "semantic_snapshot.json",
            "strategy_snapshot.json",
            "model_policy_snapshot.json",
        ):
            snap_path = snapshots_dir / snap_name
            if snap_path.exists():
                try:
                    context[snap_name.replace(".json", "")] = json.loads(snap_path.read_text())
                except Exception as exc:
                    activity.logger.warning("Failed to load snapshot %s: %s", snap_name, exc)
        # Router runtime hints are text by design.
        hints_path = self._oc_home / "workspace" / "router" / "memory" / "runtime_hints.txt"
        if hints_path.exists():
            try:
                context["runtime_hints"] = hints_path.read_text(encoding="utf-8", errors="ignore")[:4000]
            except Exception as exc:
                activity.logger.warning("Failed to read runtime hints %s: %s", hints_path, exc)
        # Embed task/strategy contract so Agent sees the active semantic + governance context.
        context["execution_contract"] = {
            "task_id": str(plan.get("task_id") or ""),
            "cluster_id": str(plan.get("cluster_id") or ""),
            "semantic_fingerprint": plan.get("semantic_fingerprint") if isinstance(plan.get("semantic_fingerprint"), dict) else {},
            "strategy_id": str(plan.get("strategy_id") or ""),
            "strategy_stage": str(plan.get("strategy_stage") or ""),
            "model_alias": str(plan.get("model_alias") or ""),
            "is_shadow": bool(plan.get("is_shadow", False)),
            "capability_id": str(step.get("capability_id") or ""),
            "quality_contract_id": str(step.get("quality_contract_id") or ""),
        }
        return context

    def _write_step_output(self, run_root: str, step_id: str, content: str) -> str:
        out_dir = Path(run_root) / "steps" / step_id / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "output.md"
        out_file.write_text(content)
        return str(out_file)

    def _find_render_output(self, run_root: str, step_results: list[dict]) -> Path | None:
        rp = Path(run_root)
        # Look for render step output.
        for res in reversed(step_results):
            sid = res.get("step_id", "")
            if "render" in sid.lower():
                out = rp / "steps" / sid / "output" / "output.md"
                if out.exists():
                    return out
        # Fallback: any .html or .md file in deliver/ subdirectories.
        for candidate in sorted(rp.glob("**/deliver/*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
            return candidate
        for candidate in sorted(rp.glob("**/output/*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            return candidate
        return None

    def _structural_check(self, content: str, profile: dict) -> dict:
        """Deterministic structural quality checks — no LLM needed."""
        # Forbidden markers.
        for marker in (profile.get("forbidden_markers") or []):
            if marker.lower() in content.lower():
                return {"ok": False, "error_code": "forbidden_marker", "detail": f"Contains forbidden marker: {marker}"}

        # Minimum word count.
        min_words = int(profile.get("min_word_count") or 0)
        word_count = len(content.split())
        if min_words and word_count < min_words:
            return {"ok": False, "error_code": "word_count_too_low", "detail": f"{word_count} < {min_words}"}

        min_sections = int(profile.get("min_sections") or 0)
        if min_sections:
            sections = [ln for ln in content.splitlines() if ln.strip().startswith("#")]
            if len(sections) < min_sections:
                return {"ok": False, "error_code": "sections_too_few", "detail": f"{len(sections)} < {min_sections}"}

        min_items = int(profile.get("min_items") or 0)
        if min_items:
            bullet_items = [ln for ln in content.splitlines() if ln.strip().startswith(("-", "*", "1.", "2.", "3."))]
            if len(bullet_items) < min_items:
                return {"ok": False, "error_code": "brief_items_too_few", "detail": f"{len(bullet_items)} < {min_items}"}

        min_domain_coverage = int(profile.get("min_domain_coverage") or 0)
        if min_domain_coverage:
            domains = set()
            for ln in content.splitlines():
                low = ln.lower()
                if "domain:" in low:
                    domains.add(low.split("domain:", 1)[1].strip())
            if len(domains) < min_domain_coverage:
                return {
                    "ok": False,
                    "error_code": "brief_domain_coverage_too_low",
                    "detail": f"{len(domains)} < {min_domain_coverage}",
                }

        if bool(profile.get("require_bilingual")):
            has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in content)
            has_latin = any("a" <= ch.lower() <= "z" for ch in content)
            if not (has_cjk and has_latin):
                return {"ok": False, "error_code": "bilingual_incomplete", "detail": "missing zh/en mixed content"}

        return {"ok": True}

    def _archive_outcome(self, run_root: str, plan: dict, render_path: Path, step_results: list[dict]) -> Path:
        task_type = str(plan.get("task_type") or "manual")
        task_id = str(plan.get("task_id") or uuid.uuid4().hex[:8])
        title = str(plan.get("title") or task_id)[:60].replace("/", "-")

        # Choose outcome category.
        if task_type in ("daily_brief", "weekly_brief"):
            today = time.strftime("%Y-%m-%d")
            dest = self._home / "outcome" / "scheduled" / task_type / today
        else:
            dest = self._home / "outcome" / "manual" / title

        dest.mkdir(parents=True, exist_ok=True)

        # Copy render output.
        suffix = render_path.suffix or ".html"
        dest_file = dest / f"report{suffix}"
        dest_file.write_text(render_path.read_text())

        # Write manifest.
        manifest = {
            "task_id": task_id,
            "title": title,
            "task_type": task_type,
            "run_root": run_root,
            "steps": len(step_results),
            "delivered_utc": _utc(),
        }
        (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        self._generate_pdf_best_effort(dest, render_path)

        return dest

    def _archive_shadow_outcome(self, run_root: str, plan: dict, render_path: Path, step_results: list[dict]) -> Path:
        task_id = str(plan.get("task_id") or uuid.uuid4().hex[:8])
        shadow_of = str(plan.get("shadow_of") or "")
        strategy_id = str(plan.get("strategy_id") or "")
        dest = self._home / "state" / "shadow_outcomes" / task_id
        dest.mkdir(parents=True, exist_ok=True)

        suffix = render_path.suffix or ".html"
        dest_file = dest / f"report{suffix}"
        dest_file.write_text(render_path.read_text())
        manifest = {
            "task_id": task_id,
            "shadow_of": shadow_of,
            "strategy_id": strategy_id,
            "task_type": str(plan.get("task_type") or ""),
            "run_root": run_root,
            "steps": len(step_results),
            "delivered_utc": _utc(),
            "is_shadow": True,
        }
        (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        self._generate_pdf_best_effort(dest, render_path)
        self._append_shadow_audit(manifest)
        return dest

    def _append_shadow_audit(self, manifest: dict) -> None:
        path = self._home / "state" / "telemetry" / "shadow_delivery.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(manifest, ensure_ascii=False) + "\n")
        except Exception as exc:
            activity.logger.warning("Failed to append shadow audit: %s", exc)

    def _update_outcome_index(self, outcome_path: Path, plan: dict) -> None:
        index_path = self._home / "outcome" / "index.json"
        try:
            index = json.loads(index_path.read_text())
        except Exception as exc:
            activity.logger.warning("Failed to read outcome index %s: %s", index_path, exc)
            index = []
        entry = {
            "path": str(outcome_path.relative_to(self._home / "outcome")),
            "title": plan.get("title", ""),
            "task_type": plan.get("task_type", "manual"),
            "task_id": plan.get("task_id", ""),
            "delivered_utc": _utc(),
        }
        index.append(entry)
        # Keep last 1000 entries.
        index_path.write_text(json.dumps(index[-1000:], ensure_ascii=False, indent=2))

    def _update_task_status(self, run_root: str, plan: dict, status: str) -> None:
        tasks_path = self._home / "state" / "tasks.json"
        try:
            tasks = json.loads(tasks_path.read_text()) if tasks_path.exists() else []
        except Exception as exc:
            activity.logger.warning("Failed to read tasks.json %s: %s", tasks_path, exc)
            tasks = []
        task_id = str(plan.get("task_id") or "")
        for task in tasks:
            if task.get("task_id") == task_id:
                task["status"] = status
                task["updated_utc"] = _utc()
                break
        else:
            tasks.append({"task_id": task_id, "status": status, "updated_utc": _utc(), "run_root": run_root})
        tasks_path.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically via temp file to avoid partial writes.
        tmp = tasks_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2))
        tmp.replace(tasks_path)

    def _generate_pdf_best_effort(self, outcome_dir: Path, render_path: Path) -> None:
        pdf_path = outcome_dir / "report.pdf"
        try:
            text = render_path.read_text(encoding="utf-8", errors="ignore")
            if render_path.suffix.lower() == ".html":
                text = self._html_to_text(text)
            self._write_simple_pdf(text, pdf_path)
        except Exception as exc:
            activity.logger.warning("PDF best-effort generation failed for %s: %s", render_path, exc)

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
