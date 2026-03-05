"""Daemon Activities — Temporal activity implementations for Agent steps and Spine Routines."""
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
from runtime.drive_accounts import DriveAccountRegistry
from runtime.event_bridge import EventBridge
from runtime.openclaw import OpenClawAdapter
from temporal.activities_campaign import (
    run_campaign_bootstrap as _run_campaign_bootstrap_impl,
    run_campaign_record_milestone as _run_campaign_record_milestone_impl,
    run_campaign_set_status as _run_campaign_set_status_impl,
)
from temporal.activities_delivery import (
    run_finalize_delivery as _run_finalize_delivery_impl,
    run_update_task_status as _run_update_task_status_impl,
)
from temporal.activities_exec import (
    run_openclaw_step as _run_openclaw_step_impl,
    run_spine_routine as _run_spine_routine_impl,
)
from services.state_store import StateStore


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
        self._drive_registry = DriveAccountRegistry(self._home / "state")
        self._event_bridge = EventBridge(self._home / "state", source="worker")
        self._store = StateStore(self._home / "state")
        try:
            self._openclaw = OpenClawAdapter(self._oc_home)
        except Exception as exc:
            activity.logger.warning("Failed to initialize OpenClawAdapter from %s: %s", self._oc_home, exc)

    def _utc(self) -> str:
        return _utc()

    # ── OpenClaw step ─────────────────────────────────────────────────────────

    @activity.defn(name="activity_openclaw_step")
    async def activity_openclaw_step(self, run_root: str, plan: dict, step: dict) -> dict:
        """Execute one DAG step through OpenClawAdapter single-channel gateway."""
        return await _run_openclaw_step_impl(self, run_root, plan, step)

    # ── Spine routine ─────────────────────────────────────────────────────────

    @activity.defn(name="activity_spine_routine")
    async def activity_spine_routine(self, run_root: str, plan: dict, routine_name: str) -> dict:
        """Execute a Spine Routine directly (no OpenClaw, no LLM unless hybrid)."""
        return await _run_spine_routine_impl(self, run_root, plan, routine_name)

    # ── Delivery finalization ─────────────────────────────────────────────────

    @activity.defn(name="activity_finalize_delivery")
    async def activity_finalize_delivery(self, run_root: str, plan: dict, step_results: list[dict]) -> dict:
        """Contract quality gate + drift check + archive + bridge emit."""
        return await _run_finalize_delivery_impl(self, run_root, plan, step_results)

    # ── Task status ───────────────────────────────────────────────────────────

    @activity.defn(name="activity_update_task_status")
    async def activity_update_task_status(self, run_root: str, plan: dict, status: str) -> dict:
        """Update task status in state/tasks.json (append-only for safety)."""
        return await _run_update_task_status_impl(self, run_root, plan, status)

    # ── Campaign state ────────────────────────────────────────────────────────

    @activity.defn(name="activity_campaign_bootstrap")
    async def activity_campaign_bootstrap(self, run_root: str, plan: dict) -> dict:
        """Initialize or refresh campaign manifest and milestone layout."""
        return await _run_campaign_bootstrap_impl(self, run_root, plan)

    @activity.defn(name="activity_campaign_record_milestone")
    async def activity_campaign_record_milestone(self, campaign_id: str, milestone_index: int, result: dict) -> dict:
        """Persist one milestone result and update manifest pointer/status."""
        return await _run_campaign_record_milestone_impl(self, campaign_id, milestone_index, result)

    @activity.defn(name="activity_campaign_set_status")
    async def activity_campaign_set_status(self, campaign_id: str, status: str, phase: str, extra: dict | None = None) -> dict:
        """Update campaign manifest status/phase with mergeable metadata."""
        return await _run_campaign_set_status_impl(self, campaign_id, status, phase, extra)

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
            "model_registry_snapshot.json",
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

    def _apply_context_window_precheck(
        self,
        *,
        run_root: str,
        plan: dict,
        step: dict,
        instruction: str,
        context: dict,
    ) -> dict:
        """Render precheck: compress upstream context if estimated prompt > 70% context window."""
        out = dict(context or {})
        agent = str(step.get("agent") or "").strip().lower()
        step_id = str(step.get("id") or step.get("step_id") or "").strip().lower()
        if agent != "render" and "render" not in step_id:
            return out

        model_window = self._model_context_window(plan, step)
        threshold = int(model_window * 0.70)
        refs = self._collect_upstream_outputs(run_root, str(step.get("id") or ""))
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
            self._write_context_precheck(run_root, str(step.get("id") or "step"), precheck)
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
        self._write_context_precheck(run_root, str(step.get("id") or "step"), precheck)
        return out

    def _write_context_precheck(self, run_root: str, step_id: str, payload: dict) -> None:
        path = Path(run_root) / "steps" / step_id / "context_precheck.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _estimate_tokens(self, text: str) -> int:
        s = str(text or "")
        return max(1, int(len(s) / 4))

    def _model_context_window(self, plan: dict, step: dict) -> int:
        alias = (
            str(step.get("model_alias") or "").strip()
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

    def _collect_upstream_outputs(self, run_root: str, current_step_id: str) -> list[dict]:
        rp = Path(run_root)
        refs: list[dict] = []
        for p in sorted(rp.glob("steps/*/output/output.md")):
            sid = p.parent.parent.name
            if sid == current_step_id:
                continue
            try:
                content = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            refs.append(
                {
                    "step_id": sid,
                    "path": str(p),
                    "content": content,
                }
            )
            if len(refs) >= 40:
                break
        return refs

    def _write_step_output(self, run_root: str, step_id: str, content: str) -> str:
        out_dir = Path(run_root) / "steps" / step_id / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / "output.md"
        out_file.write_text(content)
        return str(out_file)

    def _step_checkpoint_path(self, run_root: str, step_id: str) -> Path:
        return Path(run_root) / "steps" / step_id / "output.json"

    def _normalized_steps(self, plan: dict) -> list[dict]:
        steps = plan.get("steps") or plan.get("graph", {}).get("steps") or []
        if not isinstance(steps, list):
            return []
        out: list[dict] = []
        for i, st in enumerate(steps):
            if not isinstance(st, dict):
                continue
            sid = str(st.get("id") or st.get("step_id") or f"step_{i}").strip()
            out.append({**st, "id": sid})
        return out

    def _derive_campaign_milestones(self, plan: dict, steps: list[dict]) -> list[dict]:
        explicit = plan.get("milestones")
        by_id = {str(st.get("id") or ""): st for st in steps if str(st.get("id") or "")}
        milestones: list[dict] = []
        if isinstance(explicit, list) and explicit:
            for i, row in enumerate(explicit):
                if not isinstance(row, dict):
                    continue
                sid_list = row.get("step_ids") if isinstance(row.get("step_ids"), list) else []
                selected_steps = [by_id.get(str(sid)) for sid in sid_list if str(sid) in by_id]
                if not selected_steps:
                    continue
                milestones.append(
                    {
                        "milestone_id": str(row.get("milestone_id") or row.get("id") or f"m{i + 1:02d}"),
                        "title": str(row.get("title") or f"Milestone {i + 1}"),
                        "expected_output": str(row.get("expected_output") or ""),
                        "input_dependencies": row.get("input_dependencies") if isinstance(row.get("input_dependencies"), list) else [],
                        "steps": selected_steps,
                        "objective_rework_budget": int(row.get("objective_rework_budget") or 2),
                    }
                )
            if milestones:
                return milestones

        if not steps:
            return []
        probe = plan.get("complexity_probe") if isinstance(plan.get("complexity_probe"), dict) else {}
        estimated_phases = int(probe.get("estimated_phases") or plan.get("estimated_phases") or 4)
        phases = max(2, min(estimated_phases, len(steps)))
        chunk = max(1, int(math.ceil(len(steps) / phases)))
        prev_milestone = ""
        for i in range(0, len(steps), chunk):
            chunk_steps = steps[i:i + chunk]
            idx = len(milestones) + 1
            milestone_id = f"m{idx:02d}"
            milestones.append(
                {
                    "milestone_id": milestone_id,
                    "title": f"Milestone {idx}",
                    "expected_output": f"Complete {len(chunk_steps)} campaign steps",
                    "input_dependencies": [prev_milestone] if prev_milestone else [],
                    "steps": chunk_steps,
                    "objective_rework_budget": 2,
                }
            )
            prev_milestone = milestone_id
        return milestones

    def _read_step_checkpoint(self, run_root: str, step_id: str) -> dict | None:
        path = self._step_checkpoint_path(run_root, step_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return payload if isinstance(payload, dict) else None

    def _write_step_checkpoint(self, run_root: str, step_id: str, result: dict) -> None:
        path = self._step_checkpoint_path(run_root, step_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(result or {})
        payload["checkpoint_utc"] = _utc()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _feedback_survey_path(self, task_id: str) -> Path:
        return self._home / "state" / "feedback_surveys" / f"{task_id}.json"

    def _generate_feedback_survey(self, *, plan: dict, outcome_path: Path) -> dict:
        task_id = str(plan.get("task_id") or "")
        task_scale = str(plan.get("task_scale") or "thread").strip().lower() or "thread"
        task_type = str(plan.get("task_type") or "")
        title = str(plan.get("title") or task_id)[:200]
        channels = ["portal", "telegram"]
        required = task_scale in {"pulse", "thread", "campaign"}
        if task_scale == "campaign":
            survey_type = "campaign_final"
            prompt = "你对本次 Campaign 最终交付是否满意？"
        else:
            survey_type = "delivery_final"
            prompt = "你对本次任务交付是否满意？"
        return {
            "survey_id": f"svy_{task_id}",
            "task_id": task_id,
            "task_type": task_type,
            "task_scale": task_scale,
            "title": title,
            "survey_type": survey_type,
            "prompt": prompt,
            "required": required,
            "channels": channels,
            "status": "pending",
            "created_utc": _utc(),
            "outcome_path": str(outcome_path),
            "questions": [
                {
                    "key": "overall",
                    "type": "rating",
                    "label": "整体满意度",
                    "scale": [1, 2, 3, 4, 5],
                },
                {
                    "key": "quality",
                    "type": "choice",
                    "label": "交付质量评价",
                    "options": ["符合预期", "部分符合", "不符合"],
                },
                {
                    "key": "next_action",
                    "type": "choice",
                    "label": "后续动作建议",
                    "options": ["继续下一步", "需要补充修改", "暂停"],
                },
            ],
        }

    def _write_feedback_survey(self, payload: dict) -> None:
        task_id = str(payload.get("task_id") or "")
        if not task_id:
            return
        path = self._feedback_survey_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _find_render_output(self, run_root: str, step_results: list[dict]) -> Path | None:
        rp = Path(run_root)
        # Prefer explicit output_path attached to step results. This is critical for
        # campaign resume runs where step outputs may come from earlier run_root.
        for res in reversed(step_results):
            if not isinstance(res, dict):
                continue
            outp = str(res.get("output_path") or "").strip()
            if not outp:
                continue
            p = Path(outp)
            if p.exists() and p.is_file():
                return p
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
        word_count = self._effective_word_count(content)
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

    def _load_quality_contract(self, cluster_id: str, task_type: str) -> dict:
        contracts_dir = self._home / "config" / "semantics" / "quality_contracts"
        if cluster_id:
            p = contracts_dir / f"{cluster_id}.json"
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception as exc:
                    activity.logger.warning("Failed to load quality contract %s: %s", p, exc)
        if task_type:
            p = contracts_dir / f"{task_type}.json"
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception as exc:
                    activity.logger.warning("Failed to load quality contract %s: %s", p, exc)
        return {}

    def _quality_score(self, content: str, plan: dict, step_results: list[dict], contract: dict, profile: dict) -> tuple[float, dict]:
        weights = contract.get("quality_weights") if isinstance(contract.get("quality_weights"), dict) else {}
        structural_w = float(weights.get("structural") or 0.50)
        evidence_w = float(weights.get("evidence_completeness") or 0.30)
        review_w = float(weights.get("content_review") or 0.20)
        total = structural_w + evidence_w + review_w
        if total <= 0:
            structural_w, evidence_w, review_w = 0.50, 0.30, 0.20
            total = 1.0
        structural_w, evidence_w, review_w = structural_w / total, evidence_w / total, review_w / total

        structural = self._structural_score(content, contract, profile)
        evidence = self._evidence_score(plan, step_results)
        # Deterministic fallback in activity layer — review score mirrors structural.
        review = structural

        score = structural_w * structural + evidence_w * evidence + review_w * review
        components = {
            "quality": round(score, 4),
            "structural": round(structural, 4),
            "evidence_completeness": round(evidence, 4),
            "content_review": round(review, 4),
            # stability/latency/cost are filled by spine.record from runtime outcomes.
            "stability": 1.0,
            "latency": 1.0,
            "cost": 1.0,
            "weights": {
                "structural": round(structural_w, 4),
                "evidence_completeness": round(evidence_w, 4),
                "content_review": round(review_w, 4),
            },
        }
        return score, components

    def _structural_score(self, content: str, contract: dict, profile: dict) -> float:
        structural = contract.get("structural") if isinstance(contract.get("structural"), dict) else {}

        forbidden = structural.get("forbidden_markers") or profile.get("forbidden_markers") or []
        for marker in forbidden:
            if str(marker).lower() in content.lower():
                return 0.0

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

        bilingual = bool(structural.get("bilingual_check") or profile.get("require_bilingual"))
        if bilingual:
            has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in content)
            has_latin = any("a" <= ch.lower() <= "z" for ch in content)
            bilingual_score = 1.0 if (has_cjk and has_latin) else 0.0
        else:
            bilingual_score = 1.0

        return max(0.0, min(1.0, (word_score + section_score + item_score + bilingual_score) / 4.0))

    def _effective_word_count(self, content: str) -> int:
        """Estimate word count robustly for mixed Chinese/English text.

        - Latin tokens count by word regex.
        - CJK tokens are approximated as 1 token per 2 Han characters.
        - Final count uses max(whitespace split, regex estimate) to avoid undercount.
        """
        text = str(content or "")
        whitespace_tokens = len(text.split())
        latin_tokens = len(re.findall(r"[A-Za-z0-9]+(?:[-_'][A-Za-z0-9]+)*", text))
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        cjk_tokens = (cjk_chars + 1) // 2
        return max(whitespace_tokens, latin_tokens + cjk_tokens)

    def _evidence_score(self, plan: dict, step_results: list[dict]) -> float:
        evidence_ids = plan.get("evidence_unit_ids")
        if isinstance(evidence_ids, list) and evidence_ids:
            target = max(int(plan.get("evidence_target", 5) or 5), 1)
            return max(0.0, min(1.0, len(evidence_ids) / target))

        if not isinstance(step_results, list) or not step_results:
            return 0.5
        steps_with_output = sum(
            1
            for r in step_results
            if isinstance(r, dict) and (r.get("output") or r.get("artifacts") or r.get("evidence"))
        )
        target = max(len(step_results) // 2, 1)
        return max(0.0, min(1.0, steps_with_output / target))

    def _quality_drift_check(self, plan: dict, score: float, contract: dict) -> dict:
        cfg = contract.get("drift") if isinstance(contract.get("drift"), dict) else {}
        window = max(5, int(cfg.get("window") or 30))
        min_samples = max(5, int(cfg.get("min_samples") or 10))
        max_drop = float(cfg.get("max_drop") or 0.15)

        path = self._home / "state" / "telemetry" / "quality_scores.jsonl"
        if not path.exists():
            return {"blocked": False, "reason": "no_history"}
        cluster_id = str(plan.get("cluster_id") or "")
        task_type = str(plan.get("task_type") or "")
        history: list[float] = []
        try:
            for line in reversed(path.read_text(encoding="utf-8").splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                if cluster_id and str(row.get("cluster_id") or "") != cluster_id:
                    continue
                if not cluster_id and task_type and str(row.get("task_type") or "") != task_type:
                    continue
                try:
                    history.append(float(row.get("quality_score") or 0.0))
                except Exception:
                    continue
                if len(history) >= window:
                    break
        except Exception:
            return {"blocked": False, "reason": "history_read_failed"}
        if len(history) < min_samples:
            return {"blocked": False, "reason": "insufficient_history", "samples": len(history)}

        baseline = sum(history) / len(history)
        threshold = baseline - max_drop
        if score < threshold:
            return {
                "blocked": True,
                "reason": "quality_drop_below_baseline",
                "baseline": round(baseline, 4),
                "threshold": round(threshold, 4),
                "current": round(score, 4),
                "samples": len(history),
                "detail": f"current={round(score,4)} < baseline={round(baseline,4)}-drop={round(max_drop,4)}",
            }
        return {
            "blocked": False,
            "reason": "within_baseline",
            "baseline": round(baseline, 4),
            "threshold": round(threshold, 4),
            "samples": len(history),
        }

    def _append_quality_score(self, plan: dict, score: float, components: dict, drift: dict) -> None:
        path = self._home / "state" / "telemetry" / "quality_scores.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "task_id": str(plan.get("task_id") or ""),
            "cluster_id": str(plan.get("cluster_id") or ""),
            "task_type": str(plan.get("task_type") or ""),
            "strategy_id": str(plan.get("strategy_id") or ""),
            "strategy_stage": str(plan.get("strategy_stage") or ""),
            "quality_score": round(float(score or 0.0), 4),
            "global_score_components": components,
            "drift": drift,
            "created_utc": _utc(),
            "is_shadow": bool(plan.get("is_shadow", False)),
        }
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as exc:
            activity.logger.warning("Failed to write quality score telemetry: %s", exc)

    def _failure_meta(self, plan: dict) -> dict:
        return {
            "trace_id": str(plan.get("trace_id") or ""),
            "strategy_id": str(plan.get("strategy_id") or ""),
            "semantic_fingerprint": plan.get("semantic_fingerprint") if isinstance(plan.get("semantic_fingerprint"), dict) else {},
        }

    def _archive_outcome(
        self,
        run_root: str,
        plan: dict,
        render_path: Path,
        step_results: list[dict],
        outcome_root: Path | None = None,
    ) -> Path:
        task_type = str(plan.get("task_type") or "manual")
        task_id = str(plan.get("task_id") or uuid.uuid4().hex[:8])
        raw_title = str(plan.get("title") or task_type)
        title = raw_title[:60].replace("/", "-").replace(":", "-").strip()
        root = outcome_root or self._resolve_outcome_root()

        # Directory: outcomes/YYYY-MM/YYYY-MM-DD HH.MM <title>/
        # HH.MM instead of HH:MM — colon is not allowed on macOS/Windows FS.
        month_dir = time.strftime("%Y-%m")
        timestamp = time.strftime("%Y-%m-%d %H.%M")
        dest = root / month_dir / f"{timestamp} {title}"
        dest.mkdir(parents=True, exist_ok=True)

        # Copy render output — filename is the title, no internal IDs.
        suffix = render_path.suffix or ".html"
        safe_title = title[:80]
        dest_file = dest / f"{safe_title}{suffix}"
        dest_file.write_bytes(render_path.read_bytes())

        # manifest.json stays for system reference but is not the user-facing file.
        manifest = {
            "task_id": task_id,
            "title": raw_title,
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

    def _update_outcome_index(self, outcome_path: Path, plan: dict, outcome_root: Path | None = None) -> None:
        root = outcome_root or self._resolve_outcome_root()
        index = self._store.load_outcome_index(root)
        try:
            rel_path = str(outcome_path.relative_to(root))
        except Exception:
            rel_path = str(outcome_path)
        entry = {
            "path": rel_path,
            "drive_path": rel_path,  # task_id → drive_path mapping for Portal lookup
            "title": plan.get("title", ""),
            "task_type": plan.get("task_type", "manual"),
            "task_id": plan.get("task_id", ""),
            "delivered_utc": _utc(),
        }
        index.append(entry)
        self._store.save_outcome_index(root, index, max_items=1000)

    def _resolve_outcome_root(self) -> Path:
        resolved = self._drive_registry.resolve_outcome_root()
        if not resolved.get("ok"):
            raise RuntimeError(f"drive_outcome_unavailable: {resolved.get('error', '')}")
        root = Path(str(resolved.get("outcome_root") or "")).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _update_task_status(self, run_root: str, plan: dict, status: str, outcome_path: str | None = None) -> None:
        tasks = self._store.load_tasks()
        task_id = str(plan.get("task_id") or "")
        last_error = str(plan.get("last_error") or "")
        for task in tasks:
            if task.get("task_id") == task_id:
                task["status"] = status
                task["updated_utc"] = _utc()
                if last_error:
                    task["last_error"] = last_error
                if outcome_path:
                    task["outcome_path"] = outcome_path
                break
        else:
            row = {"task_id": task_id, "status": status, "updated_utc": _utc(), "run_root": run_root}
            if last_error:
                row["last_error"] = last_error
            if outcome_path:
                row["outcome_path"] = outcome_path
            tasks.append(row)
        self._store.save_tasks(tasks)

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
