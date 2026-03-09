"""Will — Brief validation, plan enrichment, ward check, Temporal submission."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.brief import COMPLEXITY_DEFAULTS, Brief
from services.ledger import Ledger

if TYPE_CHECKING:
    from psyche.instinct import InstinctPsyche
    from psyche.lore import LorePsyche
    from runtime.cortex import Cortex
    from spine.nerve import Nerve


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_deed_id() -> str:
    ts = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    return f"deed_{ts}_{uuid.uuid4().hex[:6]}"


logger = logging.getLogger(__name__)


class Will:
    def __init__(
        self,
        lore: "LorePsyche",
        instinct: "InstinctPsyche",
        nerve: "Nerve",
        state_dir: Path,
        temporal_client=None,
        temporal_queue: str = "daemon-queue",
        cortex: "Cortex | None" = None,
        dominion_writ_manager: Any | None = None,
    ) -> None:
        self._lore = lore
        self._instinct = instinct
        self._nerve = nerve
        self._state = state_dir
        self._ledger = Ledger(state_dir)
        self._temporal = temporal_client
        self._temporal_queue = temporal_queue
        self._cortex = cortex
        self._dominion_writ = dominion_writ_manager
        self._model_policy_path = self._state.parent / "config" / "model_policy.json"
        self._model_registry_path = self._state.parent / "config" / "model_registry.json"
        self._quality_profiles_path = self._state / "norm_quality.json"

    def set_temporal_client(self, temporal_client) -> None:
        self._temporal = temporal_client

    def validate(self, plan: dict) -> tuple[bool, str]:
        """Validate plan DAG before submission."""
        moves = plan.get("moves") or []
        if not isinstance(moves, list) or not moves:
            return False, "plan must contain a non-empty moves list"

        valid_agents = {"scout", "sage", "artificer", "arbiter", "scribe", "envoy"}
        ids: set[str] = set()
        normalized: list[tuple[str, dict]] = []
        for i, st in enumerate(moves):
            if not isinstance(st, dict):
                return False, f"move {i} is not an object"
            sid = str(st.get("id") or f"move_{i}")
            if sid in ids:
                return False, f"duplicate move id: {sid}"
            ids.add(sid)
            normalized.append((sid, st))
            agent = str(st.get("agent") or "")
            if agent and agent not in valid_agents:
                return False, f"move {sid}: unknown agent type {agent!r}"
        for sid, st in normalized:
            for dep in st.get("depends_on") or []:
                if dep not in ids:
                    return False, f"move {sid}: depends_on unknown move {dep!r}"

        brief = plan.get("brief") or {}
        move_ration = int(brief.get("move_ration") or 999)
        if len(moves) > move_ration:
            return False, f"move count {len(moves)} exceeds move_ration {move_ration}"

        terminal = [s for s in moves if not any(
            s["id"] in (other.get("depends_on") or []) for other in moves if other["id"] != s["id"]
        )]
        if not terminal:
            return False, "plan has no terminal moves (DAG cycle suspected)"

        return True, ""

    def enrich(self, plan: dict) -> dict:
        """V2 enrich pipeline: normalize -> complexity_defaults -> model_routing -> ration -> ward."""
        plan = dict(plan)
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        plan["metadata"] = metadata

        # 1. Normalize Brief
        raw_spec = plan.get("brief") or {}
        brief = Brief.from_dict(raw_spec)
        self._apply_writ_complexity_hint(brief, metadata, raw_spec)
        self._apply_dominion_overrides(brief, plan, metadata)
        plan["brief"] = brief.to_dict()
        plan.setdefault("deed_id", _new_deed_id())
        plan.setdefault("complexity", brief.complexity)
        plan.setdefault("default_move_timeout_s", brief.execution_defaults().get("timeout_per_move_s", 300))
        plan.setdefault("timeout_per_move_s", plan["default_move_timeout_s"])
        plan.setdefault("eval_window_hours", 48)
        plan["deed_title"] = self._resolve_deed_title(plan, brief)
        plan["title"] = plan["deed_title"]

        # 2. Complexity defaults
        defaults = brief.execution_defaults()
        plan.setdefault("concurrency", defaults.get("concurrency", 2))
        plan.setdefault("timeout_per_move_s", defaults.get("timeout_per_move_s", 300))
        plan.setdefault("default_move_timeout_s", defaults.get("timeout_per_move_s", 300))
        plan.setdefault("rework_limit", defaults.get("rework_limit", 1))

        # 3. Quality profile from Instinct preferences + Brief.depth
        prefs = self._instinct.all_prefs()
        plan.setdefault("require_bilingual", prefs.get("require_bilingual", "true") == "true")
        plan.setdefault("default_depth", brief.depth)
        plan.setdefault("quality_profile", self._quality_profile_for(plan, brief, prefs))

        # 4. Model routing
        self._apply_model_routing(plan)

        # 5. Ration preflight
        plan = self._ration_preflight(plan)
        plan = self._submission_preflight(plan)

        # 6. System status check
        sys_status = self._ledger.load_system_status()
        if sys_status not in {"running", ""}:
            plan["queued"] = True
            plan["queue_reason"] = f"system_{sys_status}"

        # 7. Ward check
        ward = self._ledger.load_ward()
        ward_status = str(ward.get("status") or "GREEN").upper()
        if ward_status == "RED":
            plan["queued"] = True
            plan["queue_reason"] = "ward_red"
        elif ward_status == "YELLOW":
            complexity = str(plan.get("complexity") or "charge")
            if complexity == "endeavor":
                plan["queued"] = True
                plan["queue_reason"] = "ward_yellow_endeavor_queued"

        return plan

    async def submit(self, plan: dict) -> dict:
        """Submit a plan for execution. plan must include brief and moves."""
        ok, err = self.validate(plan)
        if not ok:
            return {"ok": False, "error": err, "error_code": "invalid_plan"}

        try:
            plan = self.enrich(plan)
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:400], "error_code": "enrich_failed"}

        try:
            self._materialize_dominion_writ(plan)
        except Exception as exc:
            logger.error("Dominion/Writ materialization failed: %s", exc)
            return {"ok": False, "error": str(exc)[:400], "error_code": "dominion_writ_materialization_failed"}

        deed_id = str(plan["deed_id"])
        complexity = str(plan.get("complexity") or "charge")

        if plan.get("queued"):
            self._queue_deed(plan)
            return {
                "ok": True,
                "deed_id": deed_id,
                "deed_status": "queued",
                "reason": plan.get("queue_reason"),
                "complexity": complexity,
            }

        if complexity == "endeavor":
            return await self._submit_endeavor(plan)

        if not self._temporal:
            self._record_deed(plan, "failed_submission", "")
            return {
                "ok": False,
                "deed_id": deed_id,
                "error_code": "temporal_unavailable",
                "error": "Temporal client unavailable",
            }

        deed_root = self._make_deed_root(deed_id)
        self._record_deed(plan, "running", deed_root)

        try:
            workflow_id = f"daemon-{deed_id}"
            await self._temporal.submit(workflow_id, plan, deed_root)
        except Exception as exc:
            logger.error("Temporal submit failed for deed %s: %s", deed_id, exc)
            self._record_deed({**plan, "last_error": str(exc)[:300]}, "failed_submission", deed_root)
            return {
                "ok": False,
                "deed_id": deed_id,
                "error_code": "temporal_submit_failed",
                "error": str(exc)[:400],
            }

        self._nerve.emit("deed_submitted", {"deed_id": deed_id, "deed_root": deed_root})
        self._notify_deed_started(plan)
        return {
            "ok": True,
            "deed_id": deed_id,
            "deed_status": "running",
            "complexity": complexity,
            "deed_root": deed_root,
        }

    async def _submit_endeavor(self, plan: dict) -> dict:
        deed_id = str(plan.get("deed_id") or _new_deed_id())
        plan = dict(plan)
        plan["deed_id"] = deed_id
        plan.setdefault("complexity", "endeavor")
        endeavor_id = f"edv_{deed_id}"
        plan["endeavor_id"] = endeavor_id
        workflow_id = f"daemon-endeavor-{endeavor_id}"

        if not self._temporal:
            self._record_deed(plan, "failed_submission", "")
            return {
                "ok": False,
                "deed_id": deed_id,
                "endeavor_id": endeavor_id,
                "error_code": "temporal_unavailable",
            }

        deed_root = self._make_deed_root(deed_id)
        self._record_deed(plan, "running", deed_root)

        try:
            await self._temporal.submit(
                workflow_id=workflow_id, plan=plan, deed_root=deed_root,
                workflow_name="EndeavorWorkflow",
            )
        except Exception as exc:
            logger.error("Endeavor submit failed for deed %s: %s", deed_id, exc)
            self._record_deed({**plan, "last_error": str(exc)[:300]}, "failed_submission", deed_root)
            return {
                "ok": False,
                "deed_id": deed_id,
                "endeavor_id": endeavor_id,
                "error_code": "temporal_submit_failed",
                "error": str(exc)[:400],
            }

        self._nerve.emit("endeavor_submitted", {"deed_id": deed_id, "endeavor_id": endeavor_id})
        return {
            "ok": True,
            "deed_id": deed_id,
            "endeavor_id": endeavor_id,
            "complexity": "endeavor",
            "deed_status": "running",
            "deed_root": deed_root,
        }

    def _apply_model_routing(self, plan: dict) -> None:
        """Apply agent_model_map from model_policy.json to plan moves."""
        try:
            policy = json.loads(self._model_policy_path.read_text(encoding="utf-8"))
        except Exception:
            policy = {}
        agent_model_map = policy.get("agent_model_map", {})

        try:
            registry = json.loads(self._model_registry_path.read_text(encoding="utf-8"))
        except Exception:
            registry = {}

        plan["agent_model_map"] = agent_model_map
        plan["model_registry"] = registry

    def _ration_preflight(self, plan: dict) -> dict:
        """Check if ration is sufficient for estimated token usage."""
        rations = self._instinct.all_rations()
        for b in rations:
            resource = str(b.get("resource_type") or "")
            if resource == "concurrent_deeds":
                current = float(b.get("current_usage", 0))
                limit = float(b.get("daily_limit", 10))
                if current >= limit:
                    plan["queued"] = True
                    plan["queue_reason"] = "concurrent_deeds_limit"
                    return plan
        remains = self._provider_remaining_budget(plan)
        if remains is not None and remains <= 0:
            plan["queued"] = True
            plan["queue_reason"] = "provider_budget_exhausted"
        return plan

    def _submission_preflight(self, plan: dict) -> dict:
        if not self._dominion_writ:
            return plan
        ok, reason = self._dominion_writ.check_submission_limits(plan)
        if not ok:
            plan["queued"] = True
            plan["queue_reason"] = reason
        return plan

    def _provider_remaining_budget(self, plan: dict) -> float | None:
        if not self._cortex:
            return None
        provider = self._selected_provider(plan)
        if provider != "minimax":
            return None
        try:
            return self._cortex.provider_remaining_budget("minimax")
        except Exception as exc:
            logger.warning("MiniMax budget check failed: %s", exc)
            return None

    def _selected_provider(self, plan: dict) -> str:
        alias = str(plan.get("default_alias") or plan.get("model_alias") or "").strip()
        model_registry = plan.get("model_registry") if isinstance(plan.get("model_registry"), dict) else {}
        for row in model_registry.get("models") or []:
            if not isinstance(row, dict):
                continue
            if str(row.get("alias") or "") == alias:
                return str(row.get("provider") or "")
        return ""

    def _apply_writ_complexity_hint(self, brief: Brief, metadata: dict, raw_spec: dict) -> None:
        if str(raw_spec.get("complexity") or "").strip():
            return
        if not self._dominion_writ:
            return
        writ_id = str(metadata.get("writ_id") or "").strip()
        if not writ_id:
            return
        brief.complexity = self._dominion_writ.infer_complexity_from_history(writ_id, default=brief.complexity)
        defaults = COMPLEXITY_DEFAULTS.get(brief.complexity, COMPLEXITY_DEFAULTS["charge"])
        brief.move_budget = int(raw_spec.get("move_budget") or defaults["move_budget"])

    def _apply_dominion_overrides(self, brief: Brief, plan: dict, metadata: dict) -> None:
        if not self._dominion_writ:
            return
        dominion_id = str(metadata.get("dominion_id") or plan.get("dominion_id") or "").strip()
        if not dominion_id:
            return
        dominion = self._dominion_writ.get_dominion(dominion_id)
        overrides = dominion.get("instinct_overrides") if isinstance(dominion, dict) else {}
        if not isinstance(overrides, dict):
            return
        for key, value in overrides.items():
            if key == "default_language" and value:
                brief.language = str(value)
            elif key == "default_format" and value:
                brief.format = str(value)
            elif key == "default_depth" and value:
                brief.depth = str(value)
            elif key == "require_bilingual":
                plan["require_bilingual"] = bool(value)
            elif key == "review_emphasis":
                plan["review_emphasis"] = value
            elif key == "quality_hints" and isinstance(value, list):
                brief.quality_hints = [str(x) for x in value if str(x).strip()]
        metadata["dominion_id"] = dominion_id
        plan["metadata"] = metadata

    def _resolve_deed_title(self, plan: dict, brief: Brief) -> str:
        for key in ("deed_title", "title", "charge_title", "run_title"):
            text = str(plan.get(key) or "").strip()
            if text:
                return text[:120]
        objective = str(brief.objective or "").strip()
        if objective:
            compact = objective.replace("\n", " ").strip()
            return compact[:120]
        return str(plan.get("deed_id") or _new_deed_id())

    def _quality_profile_for(self, plan: dict, brief: Brief, prefs: dict[str, str]) -> dict:
        defaults = {
            "default": {
                "min_sections": 3,
                "min_word_count": 800,
                "forbidden_markers": ["[DONE]", "[COMPLETE]", "<system>", "[INTERNAL]"],
                "language_consistency": True,
                "format_compliance": True,
                "academic_format": False,
            },
            "errand": {
                "min_sections": 1,
                "min_word_count": 200,
                "forbidden_markers": ["[DONE]", "[COMPLETE]", "<system>", "[INTERNAL]"],
                "language_consistency": True,
                "format_compliance": True,
                "academic_format": False,
            },
            "charge": {
                "min_sections": 3,
                "min_word_count": 800,
                "forbidden_markers": ["[DONE]", "[COMPLETE]", "<system>", "[INTERNAL]"],
                "language_consistency": True,
                "format_compliance": True,
                "academic_format": "citation" in " ".join(brief.quality_hints).lower(),
            },
            "endeavor": {
                "min_sections": 4,
                "min_word_count": 1200,
                "forbidden_markers": ["[DONE]", "[COMPLETE]", "<system>", "[INTERNAL]"],
                "language_consistency": True,
                "format_compliance": True,
                "academic_format": "citation" in " ".join(brief.quality_hints).lower(),
            },
        }
        profiles = defaults
        if self._quality_profiles_path.exists():
            try:
                payload = json.loads(self._quality_profiles_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    profiles = {**profiles, **payload}
            except Exception as exc:
                logger.warning("Failed to read norm_quality.json: %s", exc)
        key = str(plan.get("quality_profile_key") or brief.complexity or "default")
        profile = dict(profiles.get(key) or profiles.get(brief.complexity) or profiles["default"])
        if prefs.get("require_bilingual") == "true":
            profile["require_bilingual"] = True
        if "review_emphasis" in plan:
            profile["review_emphasis"] = plan.get("review_emphasis")
        if str(prefs.get("min_word_count") or "").strip():
            try:
                profile["min_word_count"] = int(float(prefs["min_word_count"]))
            except Exception:
                pass
        if str(prefs.get("min_sections") or "").strip():
            try:
                profile["min_sections"] = int(float(prefs["min_sections"]))
            except Exception:
                pass
        try:
            profile["min_quality_score"] = float(
                plan.get("min_quality_score")
                or prefs.get("min_quality_score")
                or prefs.get("quality_min_score")
                or 0.6
            )
        except Exception:
            profile["min_quality_score"] = 0.6
        return profile

    def _materialize_dominion_writ(self, plan: dict) -> None:
        if not self._dominion_writ:
            return
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        brief = plan.get("brief") if isinstance(plan.get("brief"), dict) else {}
        dominion_id = str(metadata.get("dominion_id") or plan.get("dominion_id") or "").strip()
        if not dominion_id and str(metadata.get("create_dominion_objective") or "").strip():
            dominion = self._dominion_writ.create_dominion(
                str(metadata.get("create_dominion_objective") or brief.get("objective") or plan.get("title") or "").strip(),
                metadata={"instinct_overrides": metadata.get("instinct_overrides") if isinstance(metadata.get("instinct_overrides"), dict) else {}},
            )
            dominion_id = str(dominion.get("dominion_id") or "")
            metadata["dominion_id"] = dominion_id
        writ_id = str(metadata.get("writ_id") or plan.get("writ_id") or "").strip()
        writ_trigger = metadata.get("create_writ_trigger") if isinstance(metadata.get("create_writ_trigger"), dict) else {}
        if dominion_id and not writ_id and writ_trigger:
            writ = self._dominion_writ.create_writ(
                brief_template={
                    "objective": str(brief.get("objective") or plan.get("title") or ""),
                    "complexity": str(brief.get("complexity") or plan.get("complexity") or "charge"),
                    "language": str(brief.get("language") or "bilingual"),
                    "format": str(brief.get("format") or "markdown"),
                    "depth": str(brief.get("depth") or "study"),
                    "references": brief.get("references") if isinstance(brief.get("references"), list) else [],
                    "quality_hints": brief.get("quality_hints") if isinstance(brief.get("quality_hints"), list) else [],
                },
                trigger=writ_trigger,
                dominion_id=dominion_id,
                label=str(metadata.get("create_writ_label") or plan.get("deed_title") or plan.get("title") or "Writ"),
            )
            writ_id = str(writ.get("writ_id") or "")
            metadata["writ_id"] = writ_id
        if dominion_id:
            plan["dominion_id"] = dominion_id
        if writ_id:
            plan["writ_id"] = writ_id
        plan["metadata"] = metadata

    def _make_deed_root(self, deed_id: str) -> str:
        deeds_dir = self._state / "deeds" / deed_id
        deeds_dir.mkdir(parents=True, exist_ok=True)
        return str(deeds_dir)

    def _record_deed(self, plan: dict, deed_status: str, deed_root: str) -> None:
        deed_id = str(plan.get("deed_id") or "")
        brief = plan.get("brief") or {}
        objective = str(brief.get("objective") or plan.get("title") or deed_id)[:200]
        complexity = str(plan.get("complexity") or "charge")
        metadata = plan.get("metadata") or {}

        def _mutate(deeds: list[dict]) -> None:
            for row in deeds:
                if str(row.get("deed_id") or "") == deed_id:
                    row["deed_status"] = deed_status
                    row["updated_utc"] = _utc()
                if deed_root:
                    row["deed_root"] = deed_root
                row["dominion_id"] = metadata.get("dominion_id")
                row["writ_id"] = metadata.get("writ_id")
                row["deed_title"] = str(plan.get("deed_title") or plan.get("title") or objective)
                row["title"] = str(plan.get("deed_title") or plan.get("title") or objective)
                row["plan"] = plan
                if plan.get("last_error"):
                    row["last_error"] = plan["last_error"]
                break
            else:
                deeds.append({
                    "deed_id": deed_id,
                    "objective": objective,
                    "complexity": complexity,
                    "deed_status": deed_status,
                    "deed_root": deed_root,
                    "submitted_utc": _utc(),
                    "updated_utc": _utc(),
                    "priority": metadata.get("priority", 5),
                    "dominion_id": metadata.get("dominion_id"),
                    "writ_id": metadata.get("writ_id"),
                    "deed_title": str(plan.get("deed_title") or plan.get("title") or objective),
                    "title": str(plan.get("deed_title") or plan.get("title") or objective),
                    "source": metadata.get("source", "portal_voice"),
                    "plan": plan,
                    "last_error": plan.get("last_error", ""),
                })

        self._ledger.mutate_deeds(_mutate)

    def _queue_deed(self, plan: dict) -> None:
        plan_copy = dict(plan)
        plan_copy["deed_status"] = "queued"
        plan_copy["queued_utc"] = _utc()
        self._record_deed(plan_copy, "queued", "")

    def _notify_deed_started(self, plan: dict) -> None:
        prefs = {}
        try:
            prefs = self._instinct.all_prefs() if self._instinct else {}
        except Exception:
            pass
        if prefs.get("telegram_enabled") != "true":
            return

        adapter_url = os.environ.get("TELEGRAM_ADAPTER_URL", "http://127.0.0.1:8001")
        try:
            import httpx
            httpx.post(
                f"{adapter_url}/notify",
                json={
                    "event": "deed_started",
                    "payload": {
                        "deed_id": str(plan.get("deed_id") or ""),
                        "objective": str((plan.get("brief") or {}).get("objective") or ""),
                        "complexity": str(plan.get("complexity") or "charge"),
                    },
                },
                timeout=5,
            )
        except Exception as exc:
            logger.warning("Telegram notify deed_started failed: %s", exc)
