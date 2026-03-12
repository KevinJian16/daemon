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
from temporal.activities_herald import (
    run_finalize_herald as _run_finalize_herald_impl,
    run_update_deed_status as _run_update_deed_status_impl,
)
from temporal.activities_exec import (
    run_openclaw_move as _run_openclaw_move_impl,
    run_direct_move as _run_direct_move_impl,
    run_spine_routine as _run_spine_routine_impl,
)
from runtime.mcp_dispatch import MCPDispatcher
from runtime.retinue import Retinue
from services.ledger import Ledger
from services.storage_paths import resolve_offering_root


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
        self._mcp = MCPDispatcher(self._home / "config" / "mcp_servers.json")
        self._psyche_config = None
        self._cortex = None
        self._ledger_stats = None
        self._instinct_engine = None
        try:
            self._openclaw = OpenClawAdapter(self._oc_home)
        except Exception as exc:
            activity.logger.warning("Failed to initialize OpenClawAdapter from %s: %s", self._oc_home, exc)
        try:
            from psyche.config import PsycheConfig
            from psyche.instinct_engine import InstinctEngine
            from psyche.ledger_stats import LedgerStats
            from runtime.cortex import Cortex

            self._psyche_config = PsycheConfig(self._home / "psyche")
            self._cortex = Cortex(self._psyche_config)
            self._ledger_stats = LedgerStats(self._home / "state" / "ledger.db")
            self._instinct_engine = InstinctEngine(self._home / "psyche" / "instinct.md")
        except Exception as exc:
            activity.logger.warning("Failed to initialize worker Psyche/Cortex: %s", exc)

    def _utc(self) -> str:
        return _utc()

    # ── OpenClaw move ─────────────────────────────────────────────────────────

    @activity.defn(name="activity_openclaw_move")
    async def activity_openclaw_move(self, deed_root: str, plan: dict, move: dict) -> dict:
        """Execute one DAG move via persistent full session (sessions_send)."""
        return await _run_openclaw_move_impl(self, deed_root, plan, move)

    # ── Direct move (MCP / Python, zero LLM) ─────────────────────────────────

    @activity.defn(name="activity_direct_move")
    async def activity_direct_move(self, deed_root: str, plan: dict, move: dict) -> dict:
        """Execute a direct move via MCP tool — zero LLM tokens."""
        return await _run_direct_move_impl(self, deed_root, plan, move)

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
        """Build execution context with selective Psyche injection per agent role (§13.2)."""
        agent_role = str(move.get("agent") or "").strip().lower()
        brief = plan.get("brief") or {}
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        folio_id = str(plan.get("folio_id") or metadata.get("folio_id") or "").strip()
        writ_id = str(plan.get("writ_id") or metadata.get("writ_id") or "").strip()

        context: dict = {}

        # ── Psyche injection: all agents get instinct + identity (~300 tokens) ──
        psyche_parts: list[str] = []
        if self._instinct_engine:
            fragment = self._instinct_engine.prompt_fragment()
            if fragment:
                psyche_parts.append(fragment)
        identity = self._read_voice_identity()
        if identity:
            psyche_parts.append(identity)

        # scribe/envoy: +style +overlay (~250 tokens)
        if agent_role in ("scribe", "envoy"):
            lang = str(brief.get("language") or brief.get("output_language") or "zh").strip()
            style = self._read_voice_style(lang)
            if style:
                psyche_parts.append(style)
            task_type = str(brief.get("task_type") or "").strip()
            overlay = self._read_overlay(task_type)
            if overlay:
                psyche_parts.append(overlay)

        # counsel: +planning hints (~100 tokens)
        if agent_role == "counsel" and self._ledger_stats:
            hints = self._ledger_planning_hints(plan)
            if hints:
                psyche_parts.append(hints)

        if psyche_parts:
            context["psyche_context"] = "\n\n".join(psyche_parts)

        # ── Model snapshots (for agent model resolution) ──
        snapshots_dir = self._home / "state" / "snapshots"
        for snap_name in ("model_policy_snapshot.json", "model_registry_snapshot.json"):
            snap_path = snapshots_dir / snap_name
            if snap_path.exists():
                try:
                    context[snap_name.replace(".json", "")] = json.loads(snap_path.read_text())
                except Exception as exc:
                    activity.logger.warning("Failed to load snapshot %s: %s", snap_name, exc)

        # ── Execution contract ──
        context["execution_contract"] = {
            "deed_id": str(plan.get("deed_id") or ""),
            "slip_title": str(plan.get("slip_title") or plan.get("title") or ""),
            "brief": brief,
            "dag_budget": int((brief or {}).get("dag_budget") or 0),
            "agent_model_map": plan.get("agent_model_map") or {},
            "folio_id": folio_id,
            "writ_id": writ_id,
            "review_emphasis": plan.get("review_emphasis") or {},
        }
        coordination = self._coordination_context(folio_id=folio_id, writ_id=writ_id)
        if coordination:
            context["coordination_context"] = coordination
        recent_deeds = self._recent_deed_context(
            current_deed_id=str(plan.get("deed_id") or ""),
            folio_id=folio_id,
            writ_id=writ_id,
        )
        if recent_deeds:
            context["recent_deeds"] = recent_deeds
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

    def _coordination_context(self, *, folio_id: str, writ_id: str) -> dict:
        out: dict[str, Any] = {}
        state_dir = self._home / "state"
        if folio_id:
            try:
                folios = json.loads((state_dir / "folios.json").read_text(encoding="utf-8"))
            except Exception:
                folios = []
            if isinstance(folios, list):
                for row in folios:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("folio_id") or "") != folio_id:
                        continue
                    out["folio"] = {
                        "folio_id": folio_id,
                        "title": str(row.get("title") or ""),
                        "summary": str(row.get("summary") or ""),
                        "status": str(row.get("status") or ""),
                        "slip_ids": list(row.get("slip_ids") or [])[-5:],
                    }
                    break
        if writ_id:
            try:
                writs = json.loads((state_dir / "writs.json").read_text(encoding="utf-8"))
            except Exception:
                writs = []
            if isinstance(writs, list):
                for row in writs:
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("writ_id") or "") != writ_id:
                        continue
                    out["writ"] = {
                        "writ_id": writ_id,
                        "title": str(row.get("title") or ""),
                        "status": str(row.get("status") or ""),
                        "match": row.get("match") if isinstance(row.get("match"), dict) else {},
                        "deed_history": list(row.get("deed_history") or [])[-5:],
                    }
                    break
        return out

    def _recent_deed_context(
        self,
        *,
        current_deed_id: str,
        folio_id: str,
        writ_id: str,
        limit: int = 3,
    ) -> list[dict]:
        rows = self._ledger.load_deeds()
        scoped: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            deed_id = str(row.get("deed_id") or "")
            if not deed_id or deed_id == current_deed_id:
                continue
            if writ_id and str(row.get("writ_id") or "") != writ_id:
                continue
            if folio_id and str(row.get("folio_id") or "") != folio_id:
                continue
            scoped.append(row)
        scoped.sort(key=lambda row: str(row.get("updated_utc") or row.get("created_utc") or ""), reverse=True)
        return [
            {
                "deed_id": str(row.get("deed_id") or ""),
                "title": str(row.get("deed_title") or row.get("title") or row.get("objective") or ""),
                "status": str(row.get("deed_status") or ""),
                "summary": str(row.get("last_error") or ""),
                "updated_utc": str(row.get("updated_utc") or row.get("created_utc") or ""),
            }
            for row in scoped[: max(1, min(limit, 8))]
        ]

    def _read_voice_identity(self) -> str:
        """Read psyche/voice/identity.md for agent context injection."""
        path = self._home / "psyche" / "voice" / "identity.md"
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _read_voice_style(self, language: str = "zh") -> str:
        """Read voice style files (common + language-specific) for scribe/envoy."""
        voice_dir = self._home / "psyche" / "voice"
        parts: list[str] = []
        for name in ("common.md", f"{language}.md"):
            path = voice_dir / name
            if path.exists():
                try:
                    text = path.read_text(encoding="utf-8").strip()
                    if text:
                        parts.append(text)
                except Exception:
                    pass
        return "\n\n".join(parts)

    def _read_overlay(self, task_type: str) -> str:
        """Read psyche/overlays/{task_type}.md for task-specific context."""
        if not task_type:
            return ""
        path = self._home / "psyche" / "overlays" / f"{task_type}.md"
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""

    def _ledger_planning_hints(self, plan: dict) -> str:
        """Generate planning hints text for counsel from Ledger stats."""
        if not self._ledger_stats:
            return ""
        try:
            hints = self._ledger_stats.global_planning_hints()
            top_dags = hints.get("top_dag_templates") or []
            if not top_dags:
                return ""
            lines = ["Similar successful DAG templates:"]
            for tpl in top_dags[:3]:
                lines.append(
                    f"  - {tpl.get('objective_text', '')[:80]} "
                    f"(validated {tpl.get('times_validated', 0)}x, "
                    f"avg {int(tpl.get('avg_tokens') or 0)} tokens)"
                )
            return "\n".join(lines)
        except Exception:
            return ""

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

    def _quality_check_path(self, deed_root: str) -> Path:
        return Path(deed_root) / "quality_check.json"

    def _write_quality_check(self, deed_root: str, payload: dict) -> None:
        path = self._quality_check_path(deed_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _render_offering_text(self, scribe_path: Path) -> tuple[str, str]:
        raw_text = scribe_path.read_text(encoding="utf-8", errors="ignore")
        if scribe_path.suffix.lower() == ".html":
            return raw_text, self._html_to_text(raw_text)
        return raw_text, raw_text

    def _section_count(self, scribe_path: Path, raw_text: str, rendered_text: str) -> int:
        if scribe_path.suffix.lower() == ".html":
            html_headers = re.findall(r"<h[1-6][^>]*>.*?</h[1-6]>", raw_text, flags=re.IGNORECASE | re.DOTALL)
            if html_headers:
                return len(html_headers)
        markdown_headers = re.findall(r"(?m)^\s{0,3}(?:#{1,6}\s+.+|\d+[.)]\s+.+)$", raw_text)
        if markdown_headers:
            return len(markdown_headers)
        chunks = [part for part in re.split(r"\n\s*\n", rendered_text) if part.strip()]
        return max(1, min(len(chunks), 12)) if chunks else 0

    def _content_review_score(
        self,
        *,
        rendered_text: str,
        brief: dict,
        review_emphasis: Any,
        fallback_score: float,
    ) -> tuple[float, str]:
        if not self._cortex or not self._cortex.is_available():
            return fallback_score, "fallback_structural"
        prompt = (
            "Evaluate the following offering on a 0.0-1.0 scale for overall content quality.\n"
            "Return JSON only: {\"score\": 0.0-1.0, \"reason\": \"short text\"}.\n\n"
            f"Objective: {str(brief.get('objective') or '')[:200]}\n"
            f"Language: {str(brief.get('language') or '')}\n"
            f"Format: {str(brief.get('format') or '')}\n"
            f"Depth: {str(brief.get('depth') or '')}\n"
            f"Review emphasis: {json.dumps(review_emphasis, ensure_ascii=False)[:400]}\n\n"
            f"Offering excerpt:\n{rendered_text[:4000]}"
        )
        try:
            raw = self._cortex.complete(prompt, model="review", max_tokens=180, temperature=0.2).strip()
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                payload = json.loads(raw[start:end + 1])
                score = float(payload.get("score"))
                score = max(0.0, min(score, 1.0))
                return score, str(payload.get("reason") or "llm_review")
        except Exception as exc:
            activity.logger.warning("Worker quality content review failed: %s", exc)
        return fallback_score, "fallback_structural"

    def _quality_floor_check(self, deed_root: str, plan: dict, scribe_path: Path, move_results: list[dict]) -> dict:
        brief = plan.get("brief") if isinstance(plan.get("brief"), dict) else {}
        profile = plan.get("quality_profile") if isinstance(plan.get("quality_profile"), dict) else {}
        raw_text, rendered_text = self._render_offering_text(scribe_path)
        cleaned_text = self._clean_system_markers(rendered_text)
        words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", cleaned_text)
        word_count = len(words)
        section_count = self._section_count(scribe_path, raw_text, cleaned_text)
        min_words = max(1, int(profile.get("min_word_count") or 800))
        min_sections = max(1, int(profile.get("min_sections") or 3))
        expected_format = str(brief.get("format") or "").strip().lower()
        actual_ext = scribe_path.suffix.lower()
        format_score = 1.0
        if "html" in expected_format and actual_ext not in {".html", ".htm"}:
            format_score = 0.6
        elif "markdown" in expected_format and actual_ext not in {".md", ".markdown", ".txt"}:
            format_score = 0.6

        forbidden_markers = [str(x) for x in profile.get("forbidden_markers") or [] if str(x).strip()]
        marker_hits = [marker for marker in forbidden_markers if marker.lower() in raw_text.lower()]
        word_score = min(1.0, word_count / max(min_words, 1))
        section_score = min(1.0, section_count / max(min_sections, 1))
        marker_penalty = 0.0 if marker_hits else 1.0
        structural_score = max(
            0.0,
            min(1.0, (word_score * 0.45 + section_score * 0.35 + format_score * 0.20) * marker_penalty),
        )

        references = brief.get("references") if isinstance(brief.get("references"), list) else []
        if references:
            lowered = cleaned_text.lower()
            matched = 0
            for ref in references:
                ref_text = str(ref or "").strip().lower()
                if not ref_text:
                    continue
                tokens = [tok for tok in re.split(r"\W+", ref_text) if len(tok) >= 4][:3]
                if ref_text in lowered or any(tok in lowered for tok in tokens):
                    matched += 1
            evidence_score = matched / max(len(references), 1)
        else:
            supporting_moves = [
                row for row in move_results
                if isinstance(row, dict)
                and any(tag in str(row.get("move_id") or "").lower() for tag in ("scout", "sage", "arbiter"))
            ]
            evidence_score = 1.0 if supporting_moves else 0.7

        content_review, review_reason = self._content_review_score(
            rendered_text=cleaned_text,
            brief=brief,
            review_emphasis=profile.get("review_emphasis") or plan.get("review_emphasis") or {},
            fallback_score=structural_score,
        )

        overall_score = round(structural_score * 0.50 + evidence_score * 0.30 + content_review * 0.20, 4)
        min_quality_score = float(profile.get("min_quality_score") or 0.6)
        ok = bool(not marker_hits and overall_score >= min_quality_score)
        reason = ""
        if marker_hits:
            reason = "forbidden_markers_present"
        elif overall_score < min_quality_score:
            reason = "quality_floor_not_met"
        result = {
            "ok": ok,
            "reason": reason,
            "score": overall_score,
            "min_quality_score": min_quality_score,
            "components": {
                "structural": round(structural_score, 4),
                "evidence_completeness": round(evidence_score, 4),
                "content_review": round(content_review, 4),
            },
            "content_review_reason": review_reason,
            "word_count": word_count,
            "section_count": section_count,
            "artifact_extension": actual_ext,
            "forbidden_marker_hits": marker_hits,
            "checked_utc": _utc(),
        }
        self._write_quality_check(deed_root, result)
        return result

    def _find_scribe_output(self, deed_root: str, move_results: list[dict]) -> Path | None:
        rp = Path(deed_root)
        # Prefer explicit output_path attached to move results. This is critical for
        # Resume deeds may reuse existing move outputs from earlier deed roots.
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
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        entry = {
            "path": rel_path,
            "title": plan.get("deed_title", plan.get("title", "")),
            "deed_id": plan.get("deed_id", ""),
            "folio_id": plan.get("folio_id") or metadata.get("folio_id", ""),
            "slip_id": plan.get("slip_id") or metadata.get("slip_id", ""),
            "writ_id": plan.get("writ_id") or metadata.get("writ_id", ""),
            "score": ((plan.get("_quality_check") or {}).get("score") if isinstance(plan.get("_quality_check"), dict) else None),
            "delivered_utc": _utc(),
        }
        self._ledger.append_herald_log(entry)

    def _resolve_offering_root(self) -> Path:
        return resolve_offering_root(self._home / "state")

    def _update_deed_status(self, deed_root: str, plan: dict, deed_status: str, offering_path: str | None = None, result_summary: str | None = None) -> None:
        deed_id = str(plan.get("deed_id") or "")
        brief = plan.get("brief") or {}
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        last_error = str(plan.get("last_error") or "")
        now_utc = _utc()
        requested_status = str(deed_status or "").strip()
        sub_status = str(plan.get("deed_sub_status") or "").strip()
        final_status = requested_status
        phase = "history"
        if requested_status == "running":
            phase = "running"
        elif requested_status == "settling":
            phase = "settling"
        elif requested_status == "closed":
            phase = "history"

        try:
            eval_window_hours = float(plan.get("eval_window_hours") or 48.0)
        except Exception:
            eval_window_hours = 48.0
        eval_window_hours = max(0.25, min(eval_window_hours, 168.0))
        deadline_utc = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() + int(eval_window_hours * 3600)),
        )

        def _mutate(deeds: list[dict]) -> None:
            for row in deeds:
                if row.get("deed_id") == deed_id:
                    row["deed_status"] = final_status
                    if sub_status:
                        row["deed_sub_status"] = sub_status
                    row["phase"] = phase
                    row["updated_utc"] = now_utc
                    if final_status == "running" and not row.get("started_utc"):
                        row["started_utc"] = now_utc
                    if final_status in {"settling", "closed"} and not row.get("ended_utc"):
                        row["ended_utc"] = now_utc
                    row["deed_id"] = deed_id
                    row["deed_title"] = str(
                        plan.get("deed_title") or plan.get("title")
                        or brief.get("objective", "")
                        or row.get("deed_title") or ""
                    )
                    row["title"] = row.get("deed_title") or row.get("title") or ""
                    row["folio_id"] = plan.get("folio_id") or metadata.get("folio_id", "")
                    row["slip_id"] = plan.get("slip_id") or metadata.get("slip_id", "")
                    row["writ_id"] = plan.get("writ_id") or metadata.get("writ_id", "")
                    if last_error:
                        row["last_error"] = last_error
                    if offering_path:
                        row["offering_path"] = offering_path
                    if result_summary:
                        row["result_summary"] = result_summary
                    if final_status == "settling":
                        row["exec_completed_utc"] = now_utc
                        row["eval_window_hours"] = eval_window_hours
                        row["eval_deadline_utc"] = deadline_utc
                    elif final_status == "closed":
                        row.pop("eval_deadline_utc", None)
                    break
            else:
                new_row: dict = {
                    "deed_id": deed_id,
                    "deed_title": str(plan.get("deed_title") or plan.get("title") or brief.get("objective", "") or deed_id),
                    "title": str(plan.get("deed_title") or plan.get("title") or brief.get("objective", "") or deed_id),
                    "deed_status": final_status,
                    "deed_sub_status": sub_status,
                    "phase": phase,
                    "updated_utc": now_utc,
                    "deed_root": deed_root,
                    "folio_id": plan.get("folio_id") or metadata.get("folio_id", ""),
                    "slip_id": plan.get("slip_id") or metadata.get("slip_id", ""),
                    "writ_id": plan.get("writ_id") or metadata.get("writ_id", ""),
                }
                if last_error:
                    new_row["last_error"] = last_error
                if offering_path:
                    new_row["offering_path"] = offering_path
                if final_status == "settling":
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
