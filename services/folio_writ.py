"""Folio-Writ-Slip registry and event rule engine."""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spine.nerve import Nerve
    from services.ledger import Ledger

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _uuid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _slugify(text: str, fallback: str) -> str:
    raw = str(text or "").strip().lower()
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", raw).strip("-")
    return slug[:80] or fallback


def _parse_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _cron_values(field: str, minimum: int, maximum: int, *, is_dow: bool = False) -> set[int]:
    values: set[int] = set()
    for part in str(field or "*").split(","):
        token = part.strip()
        if not token:
            continue
        if token == "*":
            values.update(range(minimum, maximum + 1))
            continue
        if token.startswith("*/"):
            try:
                step = max(1, int(token[2:]))
            except Exception:
                continue
            values.update(range(minimum, maximum + 1, step))
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            try:
                start = int(left)
                end = int(right)
            except Exception:
                continue
            values.update(range(max(minimum, start), min(maximum, end) + 1))
            continue
        try:
            values.add(int(token))
        except Exception:
            continue
    normalized: set[int] = set()
    for value in values:
        if is_dow and value == 7:
            value = 0
        if minimum <= value <= maximum:
            normalized.add(value)
    return normalized or set(range(minimum, maximum + 1))


def _cron_matches(schedule: str, now_utc: datetime) -> bool:
    parts = str(schedule or "").split()
    if len(parts) != 5:
        return False
    minute, hour, dom, month, dow = parts
    minutes = _cron_values(minute, 0, 59)
    hours = _cron_values(hour, 0, 23)
    dom_values = _cron_values(dom, 1, 31)
    months = _cron_values(month, 1, 12)
    dows = _cron_values(dow, 0, 7, is_dow=True)
    dom_any = dom == "*"
    dow_any = dow == "*"
    cron_dow = (now_utc.weekday() + 1) % 7
    if dom_any and dow_any:
        day_match = True
    elif dom_any:
        day_match = cron_dow in dows
    elif dow_any:
        day_match = now_utc.day in dom_values
    else:
        day_match = now_utc.day in dom_values or cron_dow in dows
    return (
        now_utc.minute in minutes
        and now_utc.hour in hours
        and now_utc.month in months
        and day_match
    )


VALID_FOLIO_STATUSES = {"active", "parked", "archived", "dissolved"}
VALID_SLIP_STATUSES = {"active", "parked", "settled", "archived", "absorbed"}
VALID_DRAFT_STATUSES = {"open", "refining", "crystallized", "superseded", "abandoned"}
VALID_WRIT_STATUSES = {"active", "paused", "disabled"}
ACTIVE_DEED_STATUSES = {"running", "queued", "paused", "cancelling", "awaiting_eval"}


class FolioWritManager:
    """Manage Folio/Slip/Writ/Draft persistence and event-triggered actions."""

    def __init__(self, state_dir: Path, nerve: "Nerve", ledger: "Ledger") -> None:
        self._state_dir = state_dir
        self._nerve = nerve
        self._ledger = ledger
        self._drafts_file = "drafts.json"
        self._slips_file = "slips.json"
        self._folios_file = "folios.json"
        self._writs_file = "writs.json"
        self._registered_triggers: set[tuple[str, str]] = set()
        self._ensure_files()

    def _ensure_files(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        for filename in (self._drafts_file, self._slips_file, self._folios_file, self._writs_file):
            path = self._state_dir / filename
            if not path.exists():
                path.write_text("[]", encoding="utf-8")

    def _load_rows(self, filename: str) -> list[dict]:
        rows = self._ledger.load_json(filename, [])
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def _save_rows(self, filename: str, rows: list[dict]) -> None:
        self._ledger.save_json(filename, [row for row in rows if isinstance(row, dict)])

    # Drafts
    def list_drafts(self) -> list[dict]:
        rows = self._load_rows(self._drafts_file)
        return sorted(rows, key=lambda row: str(row.get("updated_utc") or ""), reverse=True)

    def get_draft(self, draft_id: str) -> dict | None:
        key = str(draft_id or "").strip()
        for row in self.list_drafts():
            if str(row.get("draft_id") or "") == key:
                return row
        return None

    def create_draft(
        self,
        *,
        source: str,
        intent_snapshot: str,
        candidate_brief: dict | None = None,
        candidate_design: dict | None = None,
        folio_id: str | None = None,
        seed_event: dict | None = None,
    ) -> dict:
        draft = {
            "draft_id": _uuid("draft"),
            "source": str(source or "manual"),
            "folio_id": str(folio_id or "") or None,
            "seed_event": seed_event if isinstance(seed_event, dict) else {},
            "intent_snapshot": str(intent_snapshot or "").strip(),
            "candidate_brief": candidate_brief if isinstance(candidate_brief, dict) else {},
            "candidate_design": candidate_design if isinstance(candidate_design, dict) else {},
            "status": "open",
            "created_utc": _utc(),
            "updated_utc": _utc(),
        }
        rows = self.list_drafts()
        rows.append(draft)
        self._save_rows(self._drafts_file, rows)
        self._nerve.emit("draft_created", {"draft_id": draft["draft_id"]})
        return draft

    def update_draft(self, draft_id: str, updates: dict) -> dict | None:
        rows = self.list_drafts()
        target: dict | None = None
        for row in rows:
            if str(row.get("draft_id") or "") != str(draft_id or ""):
                continue
            target = row
            break
        if not target:
            return None
        for key in ("folio_id", "seed_event", "intent_snapshot", "candidate_brief", "candidate_design", "status"):
            if key not in updates:
                continue
            value = updates[key]
            if key == "status" and str(value or "") not in VALID_DRAFT_STATUSES:
                continue
            target[key] = value
        target["updated_utc"] = _utc()
        self._save_rows(self._drafts_file, rows)
        self._nerve.emit("draft_updated", {"draft_id": draft_id, "status": target.get("status")})
        return target

    # Folios
    def list_folios(self) -> list[dict]:
        rows = self._load_rows(self._folios_file)
        return sorted(rows, key=lambda row: str(row.get("updated_utc") or ""), reverse=True)

    def get_folio(self, folio_id: str) -> dict | None:
        key = str(folio_id or "").strip()
        for row in self.list_folios():
            if str(row.get("folio_id") or "") == key:
                return row
        return None

    def create_folio(self, title: str, *, summary: str = "", metadata: dict | None = None) -> dict:
        folio = {
            "folio_id": _uuid("folio"),
            "title": str(title or "新卷").strip() or "新卷",
            "slug": _slugify(title, "folio"),
            "slug_history": [],
            "summary": str(summary or "").strip(),
            "status": "active",
            "slip_ids": [],
            "writ_ids": [],
            "created_utc": _utc(),
            "updated_utc": _utc(),
        }
        if isinstance(metadata, dict):
            if str(metadata.get("status") or "") in VALID_FOLIO_STATUSES:
                folio["status"] = str(metadata.get("status"))
            if metadata.get("summary"):
                folio["summary"] = str(metadata.get("summary") or "")
        rows = self.list_folios()
        rows.append(folio)
        self._save_rows(self._folios_file, rows)
        self._nerve.emit("folio_created", {"folio_id": folio["folio_id"]})
        return folio

    def update_folio(self, folio_id: str, updates: dict) -> dict | None:
        rows = self.list_folios()
        target: dict | None = None
        for row in rows:
            if str(row.get("folio_id") or "") != str(folio_id or ""):
                continue
            target = row
            break
        if not target:
            return None
        for key in ("title", "summary", "status", "slip_ids", "writ_ids"):
            if key not in updates:
                continue
            value = updates[key]
            if key == "status" and str(value or "") not in VALID_FOLIO_STATUSES:
                continue
            target[key] = value
        target["updated_utc"] = _utc()
        self._save_rows(self._folios_file, rows)
        self._nerve.emit("folio_updated", {"folio_id": folio_id, "status": target.get("status")})
        return target

    def delete_folio(self, folio_id: str) -> bool:
        rows = self.list_folios()
        filtered = [row for row in rows if str(row.get("folio_id") or "") != str(folio_id or "")]
        if len(filtered) == len(rows):
            return False
        self._save_rows(self._folios_file, filtered)
        for slip in self.list_slips():
            if str(slip.get("folio_id") or "") == str(folio_id or ""):
                self.update_slip(str(slip.get("slip_id") or ""), {"folio_id": None})
        for writ in self.list_writs(folio_id=str(folio_id)):
            self.update_writ(str(writ.get("writ_id") or ""), {"status": "disabled"})
        self._nerve.emit("folio_deleted", {"folio_id": folio_id})
        return True

    # Slips
    def list_slips(self, folio_id: str | None = None) -> list[dict]:
        rows = self._load_rows(self._slips_file)
        if folio_id:
            rows = [row for row in rows if str(row.get("folio_id") or "") == str(folio_id or "")]
        return sorted(rows, key=lambda row: str(row.get("updated_utc") or ""), reverse=True)

    def get_slip(self, slip_id: str) -> dict | None:
        key = str(slip_id or "").strip()
        for row in self.list_slips():
            if str(row.get("slip_id") or "") == key:
                return row
        return None

    def create_slip(
        self,
        *,
        title: str,
        objective: str,
        brief: dict,
        design: dict,
        folio_id: str | None = None,
        standing: bool = False,
        metadata: dict | None = None,
    ) -> dict:
        slip = {
            "slip_id": _uuid("slip"),
            "folio_id": str(folio_id or "") or None,
            "title": str(title or objective or "新签札").strip() or "新签札",
            "slug": _slugify(title or objective, "slip"),
            "slug_history": [],
            "objective": str(objective or title or "").strip(),
            "brief": brief if isinstance(brief, dict) else {},
            "design": design if isinstance(design, dict) else {},
            "status": "active",
            "standing": bool(standing),
            "latest_deed_id": "",
            "deed_ids": [],
            "created_utc": _utc(),
            "updated_utc": _utc(),
        }
        if isinstance(metadata, dict):
            if str(metadata.get("status") or "") in VALID_SLIP_STATUSES:
                slip["status"] = str(metadata.get("status"))
        rows = self.list_slips()
        rows.append(slip)
        self._save_rows(self._slips_file, rows)
        if folio_id:
            self._attach_slip_to_folio(slip["slip_id"], folio_id)
        self._nerve.emit("slip_created", {"slip_id": slip["slip_id"], "folio_id": folio_id})
        return slip

    def update_slip(self, slip_id: str, updates: dict) -> dict | None:
        rows = self.list_slips()
        target: dict | None = None
        previous_folio_id = ""
        for row in rows:
            if str(row.get("slip_id") or "") != str(slip_id or ""):
                continue
            target = row
            previous_folio_id = str(row.get("folio_id") or "")
            break
        if not target:
            return None
        for key in ("folio_id", "title", "objective", "brief", "design", "status", "standing", "latest_deed_id", "deed_ids"):
            if key not in updates:
                continue
            value = updates[key]
            if key == "status" and str(value or "") not in VALID_SLIP_STATUSES:
                continue
            target[key] = value
        target["updated_utc"] = _utc()
        self._save_rows(self._slips_file, rows)
        current_folio_id = str(target.get("folio_id") or "")
        if previous_folio_id != current_folio_id:
            if previous_folio_id:
                self._detach_slip_from_folio(slip_id, previous_folio_id)
            if current_folio_id:
                self._attach_slip_to_folio(slip_id, current_folio_id)
        self._nerve.emit("slip_updated", {"slip_id": slip_id, "status": target.get("status")})
        return target

    def crystallize_draft(
        self,
        draft_id: str,
        *,
        title: str,
        objective: str,
        brief: dict,
        design: dict,
        folio_id: str | None = None,
        standing: bool = False,
    ) -> dict:
        draft = self.get_draft(draft_id)
        if not draft:
            raise ValueError("draft_not_found")
        slip = self.create_slip(
            title=title,
            objective=objective,
            brief=brief,
            design=design,
            folio_id=folio_id or str(draft.get("folio_id") or "") or None,
            standing=standing,
        )
        self.update_draft(draft_id, {"status": "crystallized"})
        self._nerve.emit("draft_crystallized", {"draft_id": draft_id, "slip_id": slip["slip_id"]})
        return slip

    def record_deed_created(self, slip_id: str, deed_id: str, *, writ_id: str | None = None) -> None:
        slip = self.get_slip(slip_id)
        if not slip:
            return
        deed_ids = slip.get("deed_ids") if isinstance(slip.get("deed_ids"), list) else []
        deed_ids.append(str(deed_id))
        self.update_slip(
            slip_id,
            {
                "latest_deed_id": str(deed_id),
                "deed_ids": deed_ids[-200:],
            },
        )
        if writ_id:
            self.record_writ_triggered(writ_id, deed_id)

    # Writs
    def list_writs(self, folio_id: str | None = None) -> list[dict]:
        rows = self._load_rows(self._writs_file)
        if folio_id:
            rows = [row for row in rows if str(row.get("folio_id") or "") == str(folio_id)]
        return sorted(rows, key=lambda row: str(row.get("updated_utc") or ""), reverse=True)

    def get_writ(self, writ_id: str) -> dict | None:
        key = str(writ_id or "").strip()
        for row in self.list_writs():
            if str(row.get("writ_id") or "") == key:
                return row
        return None

    def create_writ(
        self,
        *,
        folio_id: str,
        title: str,
        match: dict,
        action: dict,
        metadata: dict | None = None,
    ) -> dict:
        writ = {
            "writ_id": _uuid("writ"),
            "folio_id": str(folio_id or "").strip(),
            "title": str(title or "新成文").strip() or "新成文",
            "match": match if isinstance(match, dict) else {},
            "action": action if isinstance(action, dict) else {},
            "status": "active",
            "priority": int((metadata or {}).get("priority") or 100),
            "suppression": (metadata or {}).get("suppression") if isinstance((metadata or {}).get("suppression"), dict) else {},
            "version": int((metadata or {}).get("version") or 1),
            "deed_history": [],
            "last_triggered_utc": "",
            "created_utc": _utc(),
            "updated_utc": _utc(),
        }
        rows = self.list_writs()
        rows.append(writ)
        self._save_rows(self._writs_file, rows)
        self._attach_writ_to_folio(writ["writ_id"], folio_id)
        self._register_trigger(writ)
        self._nerve.emit("writ_created", {"writ_id": writ["writ_id"], "folio_id": folio_id})
        return writ

    def update_writ(self, writ_id: str, updates: dict) -> dict | None:
        rows = self.list_writs()
        target: dict | None = None
        for row in rows:
            if str(row.get("writ_id") or "") != str(writ_id or ""):
                continue
            target = row
            break
        if not target:
            return None
        for key in ("title", "match", "action", "status", "priority", "suppression", "version", "deed_history", "last_triggered_utc"):
            if key not in updates:
                continue
            value = updates[key]
            if key == "status" and str(value or "") not in VALID_WRIT_STATUSES:
                continue
            target[key] = value
        target["updated_utc"] = _utc()
        self._save_rows(self._writs_file, rows)
        self._register_trigger(target)
        self._nerve.emit("writ_updated", {"writ_id": writ_id, "status": target.get("status")})
        return target

    def delete_writ(self, writ_id: str) -> bool:
        rows = self.list_writs()
        target = None
        filtered = []
        for row in rows:
            if str(row.get("writ_id") or "") == str(writ_id or ""):
                target = row
            else:
                filtered.append(row)
        if not target:
            return False
        self._save_rows(self._writs_file, filtered)
        self._detach_writ_from_folio(writ_id, str(target.get("folio_id") or ""))
        self._nerve.emit("writ_deleted", {"writ_id": writ_id})
        return True

    def record_writ_triggered(self, writ_id: str, deed_id: str) -> None:
        writ = self.get_writ(writ_id)
        if not writ:
            return
        history = writ.get("deed_history") if isinstance(writ.get("deed_history"), list) else []
        history.append(str(deed_id))
        self.update_writ(
            writ_id,
            {
                "deed_history": history[-200:],
                "last_triggered_utc": _utc(),
            },
        )

    # Trigger management
    def register_all_triggers(self) -> int:
        count = 0
        for writ in self.list_writs():
            if str(writ.get("status") or "") == "active":
                self._register_trigger(writ)
                count += 1
        return count

    def _register_trigger(self, writ: dict) -> None:
        status = str(writ.get("status") or "")
        if status != "active":
            return
        match = writ.get("match") if isinstance(writ.get("match"), dict) else {}
        writ_id = str(writ.get("writ_id") or "")
        event_name = str(match.get("event") or "").strip()
        schedule = str(match.get("schedule") or "").strip()
        source_events = [event_name] if event_name else []
        if schedule:
            source_events.append("cadence.tick")
        for source_event in source_events:
            key = (writ_id, source_event)
            if key in self._registered_triggers:
                continue
            def _handler(payload: dict, *, _writ_id: str = writ_id, _source_event: str = source_event) -> None:
                self._on_trigger_fired(_writ_id, payload if isinstance(payload, dict) else {}, source_event=_source_event)
            self._nerve.on(source_event, _handler)
            self._registered_triggers.add(key)

    def _on_trigger_fired(self, writ_id: str, payload: dict, *, source_event: str) -> None:
        writ = self.get_writ(writ_id)
        if not writ or str(writ.get("status") or "") != "active":
            return
        match = writ.get("match") if isinstance(writ.get("match"), dict) else {}
        action = writ.get("action") if isinstance(writ.get("action"), dict) else {}
        event_name = str(match.get("event") or "").strip()
        schedule = str(match.get("schedule") or "").strip()
        if source_event == "cadence.tick":
            tick_dt = _parse_utc(str(payload.get("tick_utc") or ""))
            if not schedule or not tick_dt or not _cron_matches(schedule, tick_dt):
                return
            last_triggered = _parse_utc(str(writ.get("last_triggered_utc") or ""))
            if last_triggered and last_triggered.strftime("%Y-%m-%dT%H:%M") == tick_dt.strftime("%Y-%m-%dT%H:%M"):
                return
        elif event_name and event_name != source_event:
            return

        filters = match.get("filter") if isinstance(match.get("filter"), dict) else {}
        for key, expected in filters.items():
            if payload.get(key) != expected:
                return
        ok, reason = self.can_trigger_writ(writ_id)
        if not ok:
            logger.info("Writ %s skipped: %s", writ_id, reason)
            return
        self._nerve.emit(
            "writ_trigger_ready",
            {
                "writ_id": writ_id,
                "folio_id": str(writ.get("folio_id") or ""),
                "match": match,
                "action": action,
                "trigger_payload": payload,
                "trigger_event": source_event,
            },
        )

    # Submission limits / learning helpers
    def can_trigger_writ(self, writ_id: str) -> tuple[bool, str]:
        writ = self.get_writ(writ_id)
        if not writ:
            return False, "writ_not_found"
        folio_id = str(writ.get("folio_id") or "")
        suppression = writ.get("suppression") if isinstance(writ.get("suppression"), dict) else {}
        max_active_per_writ = max(1, int(suppression.get("max_active_deeds") or 3))
        active_same_writ = 0
        active_same_folio = 0
        for row in self._ledger.load_deeds():
            if not isinstance(row, dict):
                continue
            if str(row.get("deed_status") or "") not in ACTIVE_DEED_STATUSES:
                continue
            if str(row.get("writ_id") or "") == writ_id:
                active_same_writ += 1
            if folio_id and str(row.get("folio_id") or "") == folio_id:
                active_same_folio += 1
        if active_same_writ >= max_active_per_writ:
            return False, "writ_max_active_deeds"
        max_active_folio = max(1, int(suppression.get("max_active_folio_deeds") or 6))
        if folio_id and active_same_folio >= max_active_folio:
            return False, "folio_max_active_deeds"
        return True, ""

    def check_submission_limits(self, plan: dict, *, concurrent_limit: int | None = None) -> tuple[bool, str]:
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        writ_id = str(metadata.get("writ_id") or plan.get("writ_id") or "")
        if writ_id:
            return self.can_trigger_writ(writ_id)
        if concurrent_limit is None:
            return True, ""
        running_total = sum(
            1 for row in self._ledger.load_deeds()
            if isinstance(row, dict) and str(row.get("deed_status") or "") in ACTIVE_DEED_STATUSES
        )
        if running_total >= int(concurrent_limit):
            return False, "global_active_deeds_limit"
        return True, ""

    def infer_dag_budget_from_history(self, writ_id: str, default: int) -> int:
        writ = self.get_writ(writ_id)
        if not writ:
            return default
        deed_rows = {
            str(row.get("deed_id") or ""): row
            for row in self._ledger.load_deeds()
            if isinstance(row, dict)
        }
        budgets: list[int] = []
        for deed_id in reversed(writ.get("deed_history") or []):
            row = deed_rows.get(str(deed_id))
            if not row:
                continue
            brief = row.get("brief_snapshot") if isinstance(row.get("brief_snapshot"), dict) else {}
            try:
                budgets.append(int(brief.get("dag_budget") or 0))
            except Exception:
                continue
            if len(budgets) >= 20:
                break
        if not budgets:
            return default
        return max(1, round(sum(budgets) / len(budgets)))

    def recent_deed_summaries(self, writ_id: str, *, limit: int = 3) -> list[dict]:
        writ = self.get_writ(writ_id)
        if not writ:
            return []
        deed_rows = {
            str(row.get("deed_id") or ""): row
            for row in self._ledger.load_deeds()
            if isinstance(row, dict)
        }
        summaries: list[dict] = []
        for deed_id in reversed(writ.get("deed_history") or []):
            row = deed_rows.get(str(deed_id))
            if not row:
                continue
            summaries.append(
                {
                    "deed_id": str(row.get("deed_id") or ""),
                    "slip_id": str(row.get("slip_id") or ""),
                    "title": str(row.get("slip_title") or row.get("title") or ""),
                    "status": str(row.get("deed_status") or ""),
                    "updated_utc": str(row.get("updated_utc") or ""),
                }
            )
            if len(summaries) >= limit:
                break
        return summaries

    def active_folio_matches(self, text: str, *, limit: int = 3) -> list[dict]:
        hay = {token for token in str(text or "").lower().split() if token}
        ranked: list[tuple[int, dict]] = []
        for folio in self.list_folios():
            if str(folio.get("status") or "") != "active":
                continue
            title_tokens = {token for token in str(folio.get("title") or "").lower().split() if token}
            summary_tokens = {token for token in str(folio.get("summary") or "").lower().split() if token}
            score = len(hay & (title_tokens | summary_tokens))
            if score > 0:
                ranked.append((score, folio))
        ranked.sort(key=lambda item: (-item[0], str(item[1].get("updated_utc") or "")))
        return [row for _, row in ranked[: max(1, int(limit))]]

    # Internal attach helpers
    def _attach_slip_to_folio(self, slip_id: str, folio_id: str) -> None:
        folio = self.get_folio(folio_id)
        if not folio:
            return
        slip_ids = folio.get("slip_ids") if isinstance(folio.get("slip_ids"), list) else []
        if slip_id not in slip_ids:
            slip_ids.append(slip_id)
            self.update_folio(folio_id, {"slip_ids": slip_ids})

    def _detach_slip_from_folio(self, slip_id: str, folio_id: str) -> None:
        folio = self.get_folio(folio_id)
        if not folio:
            return
        slip_ids = [row for row in (folio.get("slip_ids") or []) if str(row) != str(slip_id)]
        self.update_folio(folio_id, {"slip_ids": slip_ids})

    def _attach_writ_to_folio(self, writ_id: str, folio_id: str) -> None:
        folio = self.get_folio(folio_id)
        if not folio:
            return
        writ_ids = folio.get("writ_ids") if isinstance(folio.get("writ_ids"), list) else []
        if writ_id not in writ_ids:
            writ_ids.append(writ_id)
            self.update_folio(folio_id, {"writ_ids": writ_ids})

    def _detach_writ_from_folio(self, writ_id: str, folio_id: str) -> None:
        folio = self.get_folio(folio_id)
        if not folio:
            return
        writ_ids = [row for row in (folio.get("writ_ids") or []) if str(row) != str(writ_id)]
        self.update_folio(folio_id, {"writ_ids": writ_ids})
