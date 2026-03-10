"""Will — Brief validation, slip materialization, ward check, Temporal submission."""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from runtime.brief import Brief, SINGLE_SLIP_DEFAULTS
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
        folio_writ_manager: Any | None = None,
    ) -> None:
        self._lore = lore
        self._instinct = instinct
        self._nerve = nerve
        self._state = state_dir
        self._ledger = Ledger(state_dir)
        self._temporal = temporal_client
        self._temporal_queue = temporal_queue
        self._cortex = cortex
        self._folio_writ = folio_writ_manager
        self._model_policy_path = self._state.parent / "config" / "model_policy.json"
        self._model_registry_path = self._state.parent / "config" / "model_registry.json"
        self._quality_profiles_path = self._state / "norm_quality.json"

    def set_temporal_client(self, temporal_client) -> None:
        self._temporal = temporal_client

    def validate(self, plan: dict) -> tuple[bool, str]:
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

        brief = Brief.from_dict(plan.get("brief") if isinstance(plan.get("brief"), dict) else {})
        if len(moves) > int(brief.dag_budget):
            return False, f"move count {len(moves)} exceeds dag_budget {brief.dag_budget}"

        terminal = [s for s in moves if not any(
            s["id"] in (other.get("depends_on") or []) for other in moves if other["id"] != s["id"]
        )]
        if not terminal:
            return False, "plan has no terminal moves (DAG cycle suspected)"

        return True, ""

    def enrich(self, plan: dict) -> dict:
        plan = dict(plan)
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        plan["metadata"] = metadata

        raw_brief = plan.get("brief") if isinstance(plan.get("brief"), dict) else {}
        brief = Brief.from_dict(raw_brief)
        self._apply_writ_budget_hint(brief, metadata, raw_brief)
        plan["brief"] = brief.to_dict()
        plan.setdefault("deed_id", _new_deed_id())
        plan.setdefault("default_move_timeout_s", brief.execution_defaults()["timeout_per_move_s"])
        plan.setdefault("timeout_per_move_s", plan["default_move_timeout_s"])
        plan.setdefault("eval_window_hours", 48)
        plan["slip_title"] = self._resolve_slip_title(plan, brief)
        plan["title"] = plan["slip_title"]

        defaults = brief.execution_defaults()
        plan.setdefault("concurrency", defaults["concurrency"])
        plan.setdefault("timeout_per_move_s", defaults["timeout_per_move_s"])
        plan.setdefault("default_move_timeout_s", defaults["timeout_per_move_s"])
        plan.setdefault("rework_limit", defaults["rework_limit"])

        prefs = self._instinct.all_prefs()
        plan.setdefault("require_bilingual", prefs.get("require_bilingual", "true") == "true")
        plan.setdefault("default_depth", brief.depth)
        plan.setdefault("quality_profile", self._quality_profile_for(plan, brief, prefs))

        self._apply_model_routing(plan)
        plan = self._ration_preflight(plan)
        plan = self._submission_preflight(plan)

        sys_status = self._ledger.load_system_status()
        if sys_status not in {"running", ""}:
            plan["queued"] = True
            plan["queue_reason"] = f"system_{sys_status}"

        ward = self._ledger.load_ward()
        ward_status = str(ward.get("status") or "GREEN").upper()
        if ward_status == "RED":
            plan["queued"] = True
            plan["queue_reason"] = "ward_red"
        elif ward_status == "YELLOW" and int(brief.dag_budget) >= int(SINGLE_SLIP_DEFAULTS["dag_budget"]):
            plan["queued"] = True
            plan["queue_reason"] = "ward_yellow_deferred"

        return plan

    async def submit(self, plan: dict) -> dict:
        try:
            plan = self.enrich(plan)
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:400], "error_code": "enrich_failed"}

        brief = Brief.from_dict(plan.get("brief") if isinstance(plan.get("brief"), dict) else {})
        if len(plan.get("moves") or []) > int(brief.dag_budget):
            return await self._submit_promoted_folio(plan, brief)

        ok, err = self.validate(plan)
        if not ok:
            return {"ok": False, "error": err, "error_code": "invalid_plan"}

        try:
            plan = self._materialize_objects(plan, brief=brief)
        except Exception as exc:
            logger.error("Folio/Writ/Slip materialization failed: %s", exc)
            return {"ok": False, "error": str(exc)[:400], "error_code": "object_materialization_failed"}

        return await self._submit_materialized_plan(plan)

    async def _submit_materialized_plan(self, plan: dict) -> dict:
        deed_id = str(plan["deed_id"])
        if plan.get("queued"):
            self._queue_deed(plan)
            self._record_registry_links(plan)
            return {
                "ok": True,
                "deed_id": deed_id,
                "slip_id": str(plan.get("slip_id") or ""),
                "folio_id": str(plan.get("folio_id") or ""),
                "writ_id": str(plan.get("writ_id") or ""),
                "deed_status": "queued",
                "reason": plan.get("queue_reason"),
            }

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
        self._record_registry_links(plan)

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

        self._nerve.emit(
            "deed_submitted",
            {
                "deed_id": deed_id,
                "slip_id": str(plan.get("slip_id") or ""),
                "folio_id": str(plan.get("folio_id") or ""),
                "deed_root": deed_root,
            },
        )
        self._notify_deed_started(plan)
        return {
            "ok": True,
            "deed_id": deed_id,
            "slip_id": str(plan.get("slip_id") or ""),
            "folio_id": str(plan.get("folio_id") or ""),
            "writ_id": str(plan.get("writ_id") or ""),
            "deed_status": "running",
            "deed_root": deed_root,
        }

    async def _submit_promoted_folio(self, plan: dict, brief: Brief) -> dict:
        if not self._folio_writ:
            return {"ok": False, "error": "folio_manager_unavailable", "error_code": "folio_manager_unavailable"}

        title = self._resolve_slip_title(plan, brief)
        folio = self._folio_writ.create_folio(title=title, summary=str(brief.objective or title))
        chunks = self._chunk_moves(plan.get("moves") or [], int(brief.dag_budget))
        previous_slip_id = ""
        first_plan: dict | None = None
        for idx, chunk in enumerate(chunks):
            chunk_brief = brief.to_dict()
            chunk_brief["dag_budget"] = max(len(chunk), 1)
            draft = self._folio_writ.create_draft(
                source=str((plan.get("metadata") or {}).get("source") or "manual"),
                intent_snapshot=str(brief.objective or title),
                candidate_brief=chunk_brief,
                candidate_design={"moves": chunk},
                folio_id=str(folio.get("folio_id") or ""),
            )
            slip = self._folio_writ.crystallize_draft(
                str(draft.get("draft_id") or ""),
                title=f"{title} · {idx + 1}",
                objective=str(brief.objective or title),
                brief=chunk_brief,
                design={"moves": chunk},
                folio_id=str(folio.get("folio_id") or ""),
                standing=False,
            )
            if idx == 0:
                first_plan = {
                    "brief": chunk_brief,
                    "moves": chunk,
                    "metadata": {
                        **(plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}),
                        "draft_id": str(draft.get("draft_id") or ""),
                        "slip_id": str(slip.get("slip_id") or ""),
                        "folio_id": str(folio.get("folio_id") or ""),
                    },
                    "slip_id": str(slip.get("slip_id") or ""),
                    "folio_id": str(folio.get("folio_id") or ""),
                    "slip_title": str(slip.get("title") or ""),
                    "title": str(slip.get("title") or ""),
                }
            if previous_slip_id:
                self._folio_writ.create_writ(
                    folio_id=str(folio.get("folio_id") or ""),
                    title=f"{title} · 接续 {idx}",
                    match={"event": "deed_completed", "filter": {"slip_id": previous_slip_id}},
                    action={"type": "spawn_deed", "slip_id": str(slip.get("slip_id") or "")},
                )
            previous_slip_id = str(slip.get("slip_id") or "")

        if not first_plan:
            return {"ok": False, "error": "promotion_generated_no_slips", "error_code": "promotion_failed"}
        enriched_first = self.enrich(first_plan)
        enriched_first = self._materialize_objects(enriched_first, brief=Brief.from_dict(enriched_first["brief"]))
        result = await self._submit_materialized_plan(enriched_first)
        if result.get("ok"):
            result["folio_id"] = str(folio.get("folio_id") or "")
            result["promoted_to_folio"] = True
            result["slip_count"] = len(chunks)
        return result

    def _chunk_moves(self, moves: list[dict], budget: int) -> list[list[dict]]:
        size = max(1, int(budget))
        return [moves[idx: idx + size] for idx in range(0, len(moves), size)] or [[]]

    def _materialize_objects(self, plan: dict, *, brief: Brief) -> dict:
        if not self._folio_writ:
            return plan
        plan = dict(plan)
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}

        folio_id = str(metadata.get("folio_id") or plan.get("folio_id") or "").strip()
        if not folio_id and str(metadata.get("create_folio_title") or "").strip():
            folio = self._folio_writ.create_folio(
                title=str(metadata.get("create_folio_title") or plan.get("title") or brief.objective or ""),
                summary=str(metadata.get("create_folio_summary") or brief.objective or ""),
            )
            folio_id = str(folio.get("folio_id") or "")

        writ_id = str(metadata.get("writ_id") or plan.get("writ_id") or "").strip()
        create_writ = metadata.get("create_writ") if isinstance(metadata.get("create_writ"), dict) else {}
        if folio_id and not writ_id and create_writ:
            writ = self._folio_writ.create_writ(
                folio_id=folio_id,
                title=str(create_writ.get("title") or plan.get("title") or "新成文"),
                match=create_writ.get("match") if isinstance(create_writ.get("match"), dict) else {},
                action=create_writ.get("action") if isinstance(create_writ.get("action"), dict) else {},
                metadata=create_writ.get("metadata") if isinstance(create_writ.get("metadata"), dict) else {},
            )
            writ_id = str(writ.get("writ_id") or "")

        draft_id = str(metadata.get("draft_id") or plan.get("draft_id") or "").strip()
        if not draft_id:
            draft = self._folio_writ.create_draft(
                source=str(metadata.get("source") or "manual"),
                intent_snapshot=str(brief.objective or plan.get("title") or ""),
                candidate_brief=brief.to_dict(),
                candidate_design={"moves": plan.get("moves") or []},
                folio_id=folio_id or None,
                seed_event=metadata.get("seed_event") if isinstance(metadata.get("seed_event"), dict) else {},
            )
            draft_id = str(draft.get("draft_id") or "")

        slip_id = str(metadata.get("slip_id") or plan.get("slip_id") or "").strip()
        if not slip_id:
            slip = self._folio_writ.crystallize_draft(
                draft_id,
                title=str(plan.get("slip_title") or plan.get("title") or brief.objective or ""),
                objective=str(brief.objective or plan.get("title") or ""),
                brief=brief.to_dict(),
                design={"moves": plan.get("moves") or []},
                folio_id=folio_id or None,
                standing=brief.standing,
            )
            slip_id = str(slip.get("slip_id") or "")

        metadata["folio_id"] = folio_id or None
        metadata["writ_id"] = writ_id or None
        metadata["draft_id"] = draft_id
        metadata["slip_id"] = slip_id
        plan["metadata"] = metadata
        plan["folio_id"] = folio_id or None
        plan["writ_id"] = writ_id or None
        plan["draft_id"] = draft_id
        plan["slip_id"] = slip_id
        return plan

    def _record_registry_links(self, plan: dict) -> None:
        if not self._folio_writ:
            return
        slip_id = str(plan.get("slip_id") or "")
        deed_id = str(plan.get("deed_id") or "")
        writ_id = str(plan.get("writ_id") or "")
        if slip_id and deed_id:
            self._folio_writ.record_deed_created(slip_id, deed_id, writ_id=writ_id or None)

    def _apply_model_routing(self, plan: dict) -> None:
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
        rations = self._instinct.all_rations()
        for row in rations:
            resource = str(row.get("resource_type") or "")
            if resource == "concurrent_deeds":
                current = float(row.get("current_usage", 0))
                limit = float(row.get("daily_limit", 10))
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
        if not self._folio_writ:
            return plan
        ok, reason = self._folio_writ.check_submission_limits(plan)
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

    def _apply_writ_budget_hint(self, brief: Brief, metadata: dict, raw_brief: dict) -> None:
        if str(raw_brief.get("dag_budget") or "").strip():
            return
        if not self._folio_writ:
            return
        writ_id = str(metadata.get("writ_id") or "").strip()
        if not writ_id:
            return
        brief.dag_budget = self._folio_writ.infer_dag_budget_from_history(writ_id, default=brief.dag_budget)

    def _resolve_slip_title(self, plan: dict, brief: Brief) -> str:
        for key in ("slip_title", "title", "run_title"):
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
            },
            "standing": {
                "min_sections": 2,
                "min_word_count": 500,
                "forbidden_markers": ["[DONE]", "[COMPLETE]", "<system>", "[INTERNAL]"],
                "language_consistency": True,
                "format_compliance": True,
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
        key = "standing" if brief.standing else "default"
        profile = dict(profiles.get(key) or profiles["default"])
        if prefs.get("require_bilingual") == "true":
            profile["require_bilingual"] = True
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

    def _make_deed_root(self, deed_id: str) -> str:
        deeds_dir = self._state / "deeds" / deed_id
        deeds_dir.mkdir(parents=True, exist_ok=True)
        return str(deeds_dir)

    def _record_deed(self, plan: dict, deed_status: str, deed_root: str) -> None:
        deed_id = str(plan.get("deed_id") or "")
        brief = Brief.from_dict(plan.get("brief") if isinstance(plan.get("brief"), dict) else {})
        objective = str(brief.objective or plan.get("title") or deed_id)[:200]
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}

        def _mutate(deeds: list[dict]) -> None:
            for row in deeds:
                if str(row.get("deed_id") or "") != deed_id:
                    continue
                row["deed_status"] = deed_status
                row["updated_utc"] = _utc()
                row["deed_root"] = deed_root or row.get("deed_root") or ""
                row["draft_id"] = metadata.get("draft_id")
                row["slip_id"] = metadata.get("slip_id")
                row["folio_id"] = metadata.get("folio_id")
                row["writ_id"] = metadata.get("writ_id")
                row["slip_title"] = str(plan.get("slip_title") or plan.get("title") or objective)
                row["title"] = str(plan.get("slip_title") or plan.get("title") or objective)
                row["brief_snapshot"] = plan.get("brief") if isinstance(plan.get("brief"), dict) else {}
                row["design_snapshot"] = {"moves": plan.get("moves") or []}
                row["plan"] = plan
                if plan.get("last_error"):
                    row["last_error"] = plan["last_error"]
                return
            deeds.append(
                {
                    "deed_id": deed_id,
                    "draft_id": metadata.get("draft_id"),
                    "slip_id": metadata.get("slip_id"),
                    "folio_id": metadata.get("folio_id"),
                    "writ_id": metadata.get("writ_id"),
                    "objective": objective,
                    "deed_status": deed_status,
                    "deed_root": deed_root,
                    "submitted_utc": _utc(),
                    "updated_utc": _utc(),
                    "priority": metadata.get("priority", 5),
                    "slip_title": str(plan.get("slip_title") or plan.get("title") or objective),
                    "title": str(plan.get("slip_title") or plan.get("title") or objective),
                    "source": metadata.get("source", "portal_voice"),
                    "brief_snapshot": plan.get("brief") if isinstance(plan.get("brief"), dict) else {},
                    "design_snapshot": {"moves": plan.get("moves") or []},
                    "plan": plan,
                    "last_error": plan.get("last_error", ""),
                }
            )

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
                        "slip_id": str(plan.get("slip_id") or ""),
                        "folio_id": str(plan.get("folio_id") or ""),
                        "objective": str((plan.get("brief") or {}).get("objective") or ""),
                    },
                },
                timeout=5,
            )
        except Exception as exc:
            logger.warning("Telegram notify deed_started failed: %s", exc)
