"""Daemon Activities — Temporal activity implementations for Agent moves and Spine Routines."""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
import uuid
from html import unescape
from pathlib import Path
from typing import Any

from temporalio import activity
from runtime.ether import Ether
from runtime.openclaw import OpenClawAdapter
from temporal.activities_endeavor import (
    run_endeavor_bootstrap as _run_endeavor_bootstrap_impl,
    run_endeavor_record_passage as _run_endeavor_record_passage_impl,
    run_endeavor_set_status as _run_endeavor_set_status_impl,
)
from temporal.activities_herald import (
    run_finalize_herald as _run_finalize_herald_impl,
    run_update_deed_status as _run_update_deed_status_impl,
)
from temporal.activities_exec import (
    run_openclaw_move as _run_openclaw_move_impl,
    run_spine_routine as _run_spine_routine_impl,
)
from runtime.retinue import Retinue
from services.ledger import Ledger


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
        self._ether = Ether(self._home / "state", source="worker")
        self._ledger = Ledger(self._home / "state")
        self._retinue = Retinue(self._home, self._oc_home)
        try:
            self._openclaw = OpenClawAdapter(self._oc_home)
        except Exception as exc:
            activity.logger.warning("Failed to initialize OpenClawAdapter from %s: %s", self._oc_home, exc)

    def _utc(self) -> str:
        return _utc()

    # ── OpenClaw move ─────────────────────────────────────────────────────────

    @activity.defn(name="activity_openclaw_move")
    async def activity_openclaw_move(self, deed_root: str, plan: dict, move: dict) -> dict:
        """Execute one DAG move through OpenClawAdapter single-channel gateway."""
        return await _run_openclaw_move_impl(self, deed_root, plan, move)

    # ── Spine routine ─────────────────────────────────────────────────────────

    @activity.defn(name="activity_spine_routine")
    async def activity_spine_routine(self, deed_root: str, plan: dict, routine_name: str) -> dict:
        """Execute a Spine Routine directly (no OpenClaw, no LLM unless hybrid)."""
        return await _run_spine_routine_impl(self, deed_root, plan, routine_name)

    # ── Herald finalization ─────────────────────────────────────────────────

    @activity.defn(name="activity_finalize_herald")
    async def activity_finalize_herald(self, deed_root: str, plan: dict, move_results: list[dict]) -> dict:
        """Archive offering + update herald log + ether emit (pure logistics)."""
        return await _run_finalize_herald_impl(self, deed_root, plan, move_results)

    # ── Deed status ────────────────────────────────────────────────────────────

    @activity.defn(name="activity_update_deed_status")
    async def activity_update_deed_status(self, deed_root: str, plan: dict, deed_status: str) -> dict:
        """Update deed status in state/deeds.json (append-only for safety)."""
        return await _run_update_deed_status_impl(self, deed_root, plan, deed_status)

    # ── Endeavor state ────────────────────────────────────────────────────────

    @activity.defn(name="activity_endeavor_bootstrap")
    async def activity_endeavor_bootstrap(self, deed_root: str, plan: dict) -> dict:
        """Initialize or refresh endeavor manifest and passage layout."""
        return await _run_endeavor_bootstrap_impl(self, deed_root, plan)

    @activity.defn(name="activity_endeavor_record_passage")
    async def activity_endeavor_record_passage(self, endeavor_id: str, passage_index: int, result: dict) -> dict:
        """Persist one passage result and update manifest pointer/status."""
        return await _run_endeavor_record_passage_impl(self, endeavor_id, passage_index, result)

    @activity.defn(name="activity_endeavor_set_status")
    async def activity_endeavor_set_status(
        self,
        endeavor_id: str,
        endeavor_status: str,
        endeavor_phase: str,
        extra: dict | None = None,
    ) -> dict:
        """Update endeavor manifest status/phase with mergeable metadata."""
        return await _run_endeavor_set_status_impl(self, endeavor_id, endeavor_status, endeavor_phase, extra)

    # ── Retinue management ────────────────────────────────────────────────────

    @activity.defn(name="activity_allocate_retinue")
    async def activity_allocate_retinue(self, deed_id: str, roles: list[str]) -> dict:
        """Allocate retinue instances for all agent roles needed by this deed."""
        allocations: dict[str, str] = {}
        allocated_ids: list[str] = []
        try:
            for role in roles:
                inst = await asyncio.to_thread(self._retinue.allocate, role, deed_id)
                allocations[role] = inst["instance_id"]
                allocated_ids.append(inst["instance_id"])
        except Exception:
            for iid in allocated_ids:
                try:
                    await asyncio.to_thread(self._retinue.release, iid, deed_id)
                except Exception as exc:
                    activity.logger.warning("Rollback release failed for %s: %s", iid, exc)
            raise
        return {"ok": True, "retinue_allocations": allocations, "allocated_ids": allocated_ids}

    @activity.defn(name="activity_release_retinue")
    async def activity_release_retinue(self, deed_id: str, retinue_allocations: dict) -> dict:
        """Release all retinue instances allocated for this deed."""
        released: list[str] = []
        errors: list[dict] = []
        for role, instance_id in (retinue_allocations or {}).items():
            try:
                await asyncio.to_thread(self._retinue.release, str(instance_id), deed_id)
                released.append(str(instance_id))
            except Exception as exc:
                errors.append({"instance_id": str(instance_id), "error": str(exc)[:200]})
                activity.logger.warning("Failed to release retinue instance %s: %s", instance_id, exc)
        return {"ok": True, "released": released, "errors": errors}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_move_context(self, deed_root: str, plan: dict, move: dict) -> dict:
        """Attach instinct/model snapshots as execution context for Agent moves."""
        snapshots_dir = self._home / "state" / "snapshots"
        context: dict = {}
        for snap_name in (
            "instinct_snapshot.json",
            "model_policy_snapshot.json",
            "model_registry_snapshot.json",
        ):
            snap_path = snapshots_dir / snap_name
            if snap_path.exists():
                try:
                    context[snap_name.replace(".json", "")] = json.loads(snap_path.read_text())
                except Exception as exc:
                    activity.logger.warning("Failed to load snapshot %s: %s", snap_name, exc)
        # Counsel runtime hints are text by design.
        hints_path = self._oc_home / "workspace" / "counsel" / "memory" / "runtime_hints.txt"
        if hints_path.exists():
            try:
                context["runtime_hints"] = hints_path.read_text(encoding="utf-8", errors="ignore")[:4000]
            except Exception as exc:
                activity.logger.warning("Failed to read runtime hints %s: %s", hints_path, exc)
        brief = plan.get("brief") or {}
        context["execution_contract"] = {
            "deed_id": str(plan.get("deed_id") or ""),
            "deed_title": str(plan.get("deed_title") or plan.get("title") or ""),
            "brief": brief,
            "complexity": str(plan.get("complexity") or brief.get("complexity") or "charge"),
            "agent_model_map": plan.get("agent_model_map") or {},
        }
        endeavor_context = plan.get("endeavor_context") if isinstance(plan.get("endeavor_context"), list) else []
        if endeavor_context:
            context["endeavor_context"] = endeavor_context[-8:]
        return context

    def _apply_context_window_precheck(
        self,
        *,
        deed_root: str,
        plan: dict,
        move: dict,
        instruction: str,
        context: dict,
    ) -> dict:
        """Scribe precheck: compress upstream context if estimated prompt > 70% context window."""
        out = dict(context or {})
        agent = str(move.get("agent") or "").strip().lower()
        move_id = str(move.get("id") or move.get("move_id") or "").strip().lower()
        if agent != "scribe" and "scribe" not in move_id:
            return out

        model_window = self._model_context_window(plan, move)
        threshold = int(model_window * 0.70)
        refs = self._collect_upstream_outputs(deed_root, str(move.get("id") or ""))
        base_payload_text = f"{instruction}\n\n{json.dumps(out, ensure_ascii=False)}"
        upstream_tokens = sum(self._estimate_tokens(str(r.get("content") or "")) for r in refs)
        estimated_before = self._estimate_tokens(base_payload_text) + upstream_tokens
        precheck = {
            "model_context_window": model_window,
            "threshold_tokens": threshold,
            "estimated_tokens_before": estimated_before,
            "compression_applied": False,
            "upstream_output_files": len(refs),
            "checked_utc": _utc(),
        }

        if estimated_before <= threshold:
            out["context_precheck"] = precheck
            self._write_context_precheck(deed_root, str(move.get("id") or "move"), precheck)
            return out

        compressed = []
        for row in refs:
            text = str(row.get("content") or "").strip()
            if not text:
                continue
            snippet = text[:1200]
            if len(text) > 1200:
                snippet += "...[truncated]"
            compressed.append(
                {
                    "path": row.get("path", ""),
                    "summary": snippet,
                    "chars": len(text),
                }
            )

        # Keep compression section bounded and always retain raw reference paths.
        out["upstream_raw_references"] = [str(r.get("path") or "") for r in refs]
        out["upstream_compressed"] = compressed[:20]
        precheck["compression_applied"] = True
        precheck["estimated_tokens_after"] = self._estimate_tokens(
            f"{instruction}\n\n{json.dumps(out, ensure_ascii=False)}"
        )
        precheck["reason"] = "prompt_exceeds_70pct_context_window"
        out["context_precheck"] = precheck
        self._write_context_precheck(deed_root, str(move.get("id") or "move"), precheck)
        return out

    def _write_context_precheck(self, deed_root: str, move_id: str, payload: dict) -> None:
        path = Path(deed_root) / "moves" / move_id / "context_precheck.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _estimate_tokens(self, text: str) -> int:
        s = str(text or "")
        return max(1, int(len(s) / 4))

    def _model_context_window(self, plan: dict, move: dict) -> int:
        alias = (
            str(move.get("model_alias") or "").strip()
            or str(plan.get("model_alias") or "").strip()
            or "fast"
        )
        registry_path = self._home / "config" / "model_registry.json"
        if registry_path.exists():
            try:
                reg = json.loads(registry_path.read_text(encoding="utf-8"))
                models = reg.get("models") if isinstance(reg.get("models"), list) else []
                for row in models:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("alias") or "").strip() != alias:
                        continue
                    cw = int(row.get("context_window") or 0)
                    if cw > 0:
                        return cw
            except Exception:
                pass
        return 128000

    def _collect_upstream_outputs(self, deed_root: str, current_move_id: str) -> list[dict]:
        rp = Path(deed_root)
        refs: list[dict] = []
        for p in sorted(rp.glob("moves/*/output/output.md")):
            sid = p.parent.parent.name
            if sid == current_move_id:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            refs.append(
                {
                    "move_id": sid,
                    "path": str(p),
                    "content": content,
                }
            )
            if len(refs) >= 40:
                break
        return refs

    def _write_move_output(self, deed_root: str, move_id: str, content: str) -> str:
        out_dir = Path(deed_root) / "moves" / move_id / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "output.md"
        out_file.write_text(content)
        return str(out_file)

    def _move_checkpoint_path(self, deed_root: str, move_id: str) -> Path:
        return Path(deed_root) / "moves" / move_id / "output.json"

    def _normalized_moves(self, plan: dict) -> list[dict]:
        moves = plan.get("moves") or plan.get("graph", {}).get("moves") or []
        if not isinstance(moves, list):
            return []
        out: list[dict] = []
        for i, st in enumerate(moves):
            if not isinstance(st, dict):
                continue
            sid = str(st.get("id") or st.get("move_id") or f"move_{i}").strip()
            out.append({**st, "id": sid})
        return out

    def _derive_endeavor_passages(self, plan: dict, moves: list[dict]) -> list[dict]:
        explicit = plan.get("passages")
        by_id = {str(st.get("id") or ""): st for st in moves if str(st.get("id") or "")}
        passages: list[dict] = []
        if isinstance(explicit, list) and explicit:
            for i, row in enumerate(explicit):
                if not isinstance(row, dict):
                    continue
                sid_list = row.get("move_ids") if isinstance(row.get("move_ids"), list) else []
                selected_moves = [by_id.get(str(sid)) for sid in sid_list if str(sid) in by_id]
                if not selected_moves:
                    continue
                passages.append(
                    {
                        "passage_id": str(row.get("passage_id") or row.get("id") or f"m{i + 1:02d}"),
                        "title": str(row.get("title") or f"Passage {i + 1}"),
                        "expected_output": str(row.get("expected_output") or ""),
                        "input_dependencies": row.get("input_dependencies") if isinstance(row.get("input_dependencies"), list) else [],
                        "moves": selected_moves,
                        "objective_rework_ration": int(row.get("objective_rework_ration") or 2),
                    }
                )
            if passages:
                return passages

        if not moves:
            return []
        probe = plan.get("complexity_probe") if isinstance(plan.get("complexity_probe"), dict) else {}
        estimated_phases = int(probe.get("estimated_phases") or plan.get("estimated_phases") or 4)
        phases = max(2, min(estimated_phases, len(moves)))
        chunk = max(1, int(math.ceil(len(moves) / phases)))
        prev_passage = ""
        for i in range(0, len(moves), chunk):
            chunk_moves = moves[i:i + chunk]
            idx = len(passages) + 1
            passage_id = f"m{idx:02d}"
            passages.append(
                {
                    "passage_id": passage_id,
                    "title": f"Passage {idx}",
                    "expected_output": f"Complete {len(chunk_moves)} endeavor moves",
                    "input_dependencies": [prev_passage] if prev_passage else [],
                    "moves": chunk_moves,
                    "objective_rework_ration": 2,
                }
            )
            prev_passage = passage_id
        return passages

    def _read_move_checkpoint(self, deed_root: str, move_id: str) -> dict | None:
        path = self._move_checkpoint_path(deed_root, move_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _write_move_checkpoint(self, deed_root: str, move_id: str, result: dict) -> None:
        path = self._move_checkpoint_path(deed_root, move_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(result or {})
        payload["checkpoint_utc"] = _utc()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _feedback_survey_path(self, deed_id: str) -> Path:
        return self._home / "state" / "feedback_surveys" / f"{deed_id}.json"

    def _generate_feedback_survey(self, *, plan: dict, offering_path: Path) -> dict:
        deed_id = str(plan.get("deed_id") or "")
        brief = plan.get("brief") or {}
        complexity = str(plan.get("complexity") or brief.get("complexity") or "charge").strip().lower() or "charge"
        title = str(plan.get("deed_title") or plan.get("title") or brief.get("objective", "") or deed_id)[:200]
        channels = ["portal", "telegram"]
        required = complexity in {"errand", "charge", "endeavor"}
        if complexity == "endeavor":
            survey_type = "endeavor_final"
            prompt = "你对本次 Endeavor 最终交付是否满意？"
        else:
            survey_type = "herald_final"
            prompt = "你对本次任务交付是否满意？"
        return {
            "survey_id": f"svy_{deed_id}",
            "deed_id": deed_id,
            "complexity": complexity,
            "title": title,
            "survey_type": survey_type,
            "prompt": prompt,
            "required": required,
            "channels": channels,
            "status": "pending",
            "created_utc": _utc(),
            "offering_path": str(offering_path),
            "questions": [
                {
                    "key": "overall",
                    "type": "choice",
                    "label": "整体评价",
                    "options": ["satisfactory", "acceptable", "unsatisfactory", "wrong"],
                },
                {
                    "key": "issues",
                    "type": "multi_choice",
                    "label": "问题标记（可多选）",
                    "options": [
                        "depth_insufficient",
                        "missing_info",
                        "format_wrong",
                        "language_issue",
                        "factual_error",
                        "off_topic",
                    ],
                },
            ],
        }

    def _write_feedback_survey(self, payload: dict) -> None:
        deed_id = str(payload.get("deed_id") or "")
        if not deed_id:
            return
        path = self._feedback_survey_path(deed_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _find_scribe_output(self, deed_root: str, move_results: list[dict]) -> Path | None:
        rp = Path(deed_root)
        # Prefer explicit output_path attached to move results. This is critical for
        # endeavor resume deeds where move outputs may come from earlier deed_root.
        for res in reversed(move_results):
            if not isinstance(res, dict):
                continue
            outp = str(res.get("output_path") or "").strip()
            if not outp:
                continue
            p = Path(outp)
            if p.exists() and p.is_file():
                return p
        # Look for scribe move output.
        for res in reversed(move_results):
            sid = res.get("move_id", "")
            if "scribe" in sid.lower():
                out = rp / "moves" / sid / "output" / "output.md"
                if out.exists():
                    return out
        # Fallback: any .html or .md file in deliver/ subdirectories.
        for candidate in sorted(rp.glob("**/deliver/*.html"), key=lambda p: p.stat().st_mtime, reverse=True):
            return candidate
        for candidate in sorted(rp.glob("**/output/*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            return candidate
        return None

    def _archive_offering(
        self,
        deed_root: str,
        plan: dict,
        scribe_path: Path,
        move_results: list[dict],
        offering_root: Path | None = None,
    ) -> Path:
        deed_id = str(plan.get("deed_id") or uuid.uuid4().hex[:8])
        brief = plan.get("brief") or {}
        raw_title = str(
            plan.get("deed_title") or plan.get("title")
            or brief.get("objective", "") or "untitled"
        )
        title = raw_title[:60].replace("/", "-").replace(":", "-").strip()
        root = offering_root or self._resolve_offering_root()

        month_dir = time.strftime("%Y-%m")
        timestamp = time.strftime("%Y-%m-%d %H.%M")
        dest = root / month_dir / f"{timestamp} {title}"
        dest.mkdir(parents=True, exist_ok=True)

        suffix = scribe_path.suffix or ".html"
        safe_title = title[:80]
        dest_file = dest / f"{safe_title}{suffix}"
        # Clean system markers from scribe output before archiving (Q4.6d).
        raw_content = scribe_path.read_bytes()
        if suffix in {".html", ".md", ".txt"}:
            try:
                cleaned = self._clean_system_markers(raw_content.decode("utf-8", errors="replace"))
                dest_file.write_text(cleaned, encoding="utf-8")
            except Exception:
                dest_file.write_bytes(raw_content)
        else:
            dest_file.write_bytes(raw_content)
        self._generate_pdf_best_effort(dest, scribe_path)

        return dest

    # Forbidden system markers that must never appear in delivered offerings (Q4.6d).
    _SYSTEM_MARKER_PATTERNS = [
        r"\[DONE\]",
        r"\[COMPLETE\]",
        r"\[complete\]",
        r"\[done\]",
        r"run complete",
        r"completed successfully",
        r"<!-- ?system[^>]*-->",
        r"\[system:?[^\]]*\]",
        r"<system-note>.*?</system-note>",
        r"---\s*internal notes?\s*---.*?---\s*end\s*---",
    ]

    def _clean_system_markers(self, text: str) -> str:
        """Remove internal system markers from rendered output before archiving."""
        for pattern in self._SYSTEM_MARKER_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.DOTALL)
        # Collapse runs of blank lines left by marker removal.
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _update_offering_index(self, offering_path: Path, plan: dict, offering_root: Path | None = None) -> None:
        root = offering_root or self._resolve_offering_root()
        try:
            rel_path = str(offering_path.relative_to(root))
        except Exception:
            rel_path = str(offering_path)
        brief = plan.get("brief") or {}
        complexity = str(plan.get("complexity") or brief.get("complexity") or "charge")
        entry = {
            "path": rel_path,
            "title": plan.get("deed_title", plan.get("title", "")),
            "complexity": complexity,
            "deed_id": plan.get("deed_id", ""),
            "delivered_utc": _utc(),
        }
        self._ledger.append_herald_log(entry)

    def _resolve_offering_root(self) -> Path:
        root = self._home / "offerings"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _update_deed_status(self, deed_root: str, plan: dict, deed_status: str, offering_path: str | None = None) -> None:
        deed_id = str(plan.get("deed_id") or "")
        brief = plan.get("brief") or {}
        complexity = str(plan.get("complexity") or brief.get("complexity") or "charge")
        last_error = str(plan.get("last_error") or "")
        now_utc = _utc()
        requested_status = str(deed_status or "").strip()
        final_status = requested_status
        phase = "history"
        if requested_status in {"running", "queued", "paused", "cancel_requested", "cancelling"}:
            phase = "running"
        elif requested_status in {"awaiting_eval", "pending_review"}:
            phase = "awaiting_eval"
        elif requested_status == "completed":
            final_status = "awaiting_eval"
            phase = "awaiting_eval"

        try:
            eval_window_hours = float(plan.get("eval_window_hours") or 2.0)
        except Exception:
            eval_window_hours = 2.0
        eval_window_hours = max(0.25, min(eval_window_hours, 168.0))
        deadline_utc = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() + int(eval_window_hours * 3600)),
        )

        def _mutate(deeds: list[dict]) -> None:
            for row in deeds:
                if row.get("deed_id") == deed_id:
                    row["deed_status"] = final_status
                    row["phase"] = phase
                    row["updated_utc"] = now_utc
                    row["deed_id"] = deed_id
                    row["complexity"] = complexity
                    row["deed_title"] = str(
                        plan.get("deed_title") or plan.get("title")
                        or brief.get("objective", "")
                        or row.get("deed_title") or ""
                    )
                    row["title"] = row.get("deed_title") or row.get("title") or ""
                    if plan.get("endeavor_id"):
                        row["endeavor_id"] = str(plan.get("endeavor_id") or "")
                    if last_error:
                        row["last_error"] = last_error
                    if offering_path:
                        row["offering_path"] = offering_path
                    if final_status == "awaiting_eval":
                        row["exec_completed_utc"] = now_utc
                        row["eval_window_hours"] = eval_window_hours
                        row["eval_deadline_utc"] = deadline_utc
                    elif final_status in {"completed", "failed", "cancelled"}:
                        row.pop("eval_deadline_utc", None)
                    break
            else:
                new_row: dict = {
                    "deed_id": deed_id,
                    "deed_title": str(plan.get("deed_title") or plan.get("title") or brief.get("objective", "") or deed_id),
                    "title": str(plan.get("deed_title") or plan.get("title") or brief.get("objective", "") or deed_id),
                    "complexity": complexity,
                    "endeavor_id": str(plan.get("endeavor_id") or ""),
                    "deed_status": final_status,
                    "phase": phase,
                    "updated_utc": now_utc,
                    "deed_root": deed_root,
                }
                if last_error:
                    new_row["last_error"] = last_error
                if offering_path:
                    new_row["offering_path"] = offering_path
                if final_status == "awaiting_eval":
                    new_row["exec_completed_utc"] = now_utc
                    new_row["eval_window_hours"] = eval_window_hours
                    new_row["eval_deadline_utc"] = deadline_utc
                deeds.append(new_row)

        self._ledger.mutate_deeds(_mutate)

    def _generate_pdf_best_effort(self, offering_dir: Path, scribe_path: Path) -> None:
        pdf_path = offering_dir / "report.pdf"
        try:
            text = scribe_path.read_text(encoding="utf-8", errors="ignore")
            if scribe_path.suffix.lower() == ".html":
                text = self._html_to_text(text)
            self._write_simple_pdf(text, pdf_path)
        except Exception as exc:
            activity.logger.warning("PDF best-effort generation failed for %s: %s", scribe_path, exc)

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
