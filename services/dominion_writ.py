"""Dominion-Writ-Deed management — long-horizon orchestration primitives."""
from __future__ import annotations

import json
import logging
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


def _uuid() -> str:
    return uuid.uuid4().hex[:12]


VALID_DOMINION_STATUSES = {"active", "paused", "completed", "abandoned"}
VALID_WRIT_STATUSES = {"active", "paused", "disabled"}
ACTIVE_DEED_STATUSES = {"running", "queued", "paused", "cancelling", "awaiting_eval", "pending_review"}
DEFAULT_RESERVED_INDEPENDENT_SLOTS = 4


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
        part = part.strip()
        if not part:
            continue
        if part == "*":
            values.update(range(minimum, maximum + 1))
            continue
        if part.startswith("*/"):
            try:
                step = max(1, int(part[2:]))
            except Exception:
                continue
            values.update(range(minimum, maximum + 1, step))
            continue
        if "-" in part:
            left, right = part.split("-", 1)
            try:
                start = int(left)
                end = int(right)
            except Exception:
                continue
            values.update(range(max(minimum, start), min(maximum, end) + 1))
            continue
        try:
            values.add(int(part))
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


class DominionWritManager:
    """Manage Dominion/Writ lifecycle, trigger subscriptions, and resource limits."""

    def __init__(
        self,
        state_dir: Path,
        nerve: "Nerve",
        ledger: "Ledger",
    ) -> None:
        self._state_dir = state_dir
        self._nerve = nerve
        self._ledger = ledger
        self._dominions_file = state_dir / "dominions.json"
        self._writs_file = state_dir / "writs.json"
        self._registered_triggers: set[tuple[str, str]] = set()
        self._ensure_files()

    def _ensure_files(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        for f in (self._dominions_file, self._writs_file):
            if not f.exists():
                f.write_text("[]", encoding="utf-8")

    # ── Dominion CRUD ─────────────────────────────────────────────────────

    def list_dominions(self) -> list[dict]:
        rows = self._load_json(self._dominions_file)
        return sorted(rows, key=lambda row: str(row.get("updated_utc") or ""), reverse=True)

    def get_dominion(self, dominion_id: str) -> dict | None:
        key = str(dominion_id or "").strip()
        for row in self.list_dominions():
            if str(row.get("dominion_id") or "") == key:
                return row
        return None

    def create_dominion(self, objective: str, metadata: dict | None = None) -> dict:
        dominion = {
            "dominion_id": _uuid(),
            "objective": str(objective or "").strip(),
            "status": "active",
            "writs": [],
            "max_concurrent_deeds": 6,
            "max_writs": 8,
            "instinct_overrides": {},
            "progress_notes": [],
            "created_utc": _utc(),
            "updated_utc": _utc(),
        }
        if isinstance(metadata, dict):
            dominion.update({
                "max_concurrent_deeds": int(metadata.get("max_concurrent_deeds") or dominion["max_concurrent_deeds"]),
                "max_writs": int(metadata.get("max_writs") or dominion["max_writs"]),
                "instinct_overrides": metadata.get("instinct_overrides") if isinstance(metadata.get("instinct_overrides"), dict) else {},
                "progress_notes": metadata.get("progress_notes") if isinstance(metadata.get("progress_notes"), list) else [],
            })
        dominions = self.list_dominions()
        dominions.append(dominion)
        self._save_json(self._dominions_file, dominions)
        self._nerve.emit("dominion_created", {"dominion_id": dominion["dominion_id"]})
        return dominion

    def update_dominion(self, dominion_id: str, updates: dict) -> dict | None:
        dominions = self.list_dominions()
        target: dict | None = None
        for dominion in dominions:
            if str(dominion.get("dominion_id") or "") != str(dominion_id or ""):
                continue
            target = dominion
            break
        if not target:
            return None
        status = str(updates.get("status") or target.get("status") or "").strip()
        if status and status not in VALID_DOMINION_STATUSES:
            return None
        allowed = {"objective", "status", "progress_notes", "max_concurrent_deeds", "max_writs", "instinct_overrides"}
        for key, value in updates.items():
            if key not in allowed:
                continue
            target[key] = value
        target["updated_utc"] = _utc()
        self._save_json(self._dominions_file, dominions)
        if str(target.get("status") or "") in {"paused", "completed", "abandoned"}:
            child_status = "paused" if str(target.get("status") or "") == "paused" else "disabled"
            for writ_id in list(target.get("writs") or []):
                self.update_writ(str(writ_id), {"status": child_status}, cascade=True)
        self._nerve.emit("dominion_updated", {"dominion_id": dominion_id, "status": target.get("status")})
        return target

    def delete_dominion(self, dominion_id: str) -> bool:
        dominions = self.list_dominions()
        filtered = [row for row in dominions if str(row.get("dominion_id") or "") != str(dominion_id or "")]
        if len(filtered) == len(dominions):
            return False
        self._save_json(self._dominions_file, filtered)
        writs = [row for row in self.list_writs() if str(row.get("dominion_id") or "") == str(dominion_id or "")]
        for writ in writs:
            self.update_writ(str(writ.get("writ_id") or ""), {"status": "disabled"}, cascade=True)
        self._nerve.emit("dominion_deleted", {"dominion_id": dominion_id})
        return True

    # ── Writ CRUD ─────────────────────────────────────────────────────────

    def list_writs(self, dominion_id: str | None = None) -> list[dict]:
        rows = self._load_json(self._writs_file)
        if dominion_id:
            rows = [row for row in rows if str(row.get("dominion_id") or "") == str(dominion_id)]
        return sorted(rows, key=lambda row: str(row.get("updated_utc") or ""), reverse=True)

    def get_writ(self, writ_id: str) -> dict | None:
        key = str(writ_id or "").strip()
        for row in self.list_writs():
            if str(row.get("writ_id") or "") == key:
                return row
        return None

    def create_writ(
        self,
        brief_template: dict,
        trigger: dict,
        dominion_id: str | None = None,
        label: str = "",
        depends_on_writ: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        dominion = self.get_dominion(str(dominion_id or "")) if dominion_id else None
        if dominion and len(dominion.get("writs") or []) >= int(dominion.get("max_writs") or 8):
            raise ValueError("dominion_max_writs_exceeded")
        writ = {
            "writ_id": _uuid(),
            "dominion_id": dominion_id,
            "label": label or (brief_template.get("objective") if isinstance(brief_template, dict) else "") or "Writ",
            "status": "active",
            "brief_template": brief_template if isinstance(brief_template, dict) else {},
            "trigger": trigger if isinstance(trigger, dict) else {},
            "depends_on_writ": depends_on_writ,
            "max_pending_deeds": 3,
            "deed_history": [],
            "split_from": "",
            "merged_from": [],
            "created_utc": _utc(),
            "updated_utc": _utc(),
            "last_triggered_utc": "",
            "deed_count": 0,
        }
        if isinstance(metadata, dict):
            if metadata.get("max_pending_deeds") is not None:
                writ["max_pending_deeds"] = int(metadata.get("max_pending_deeds") or 3)
            if isinstance(metadata.get("deed_history"), list):
                writ["deed_history"] = [str(x) for x in metadata.get("deed_history") if x]
            if metadata.get("split_from"):
                writ["split_from"] = str(metadata.get("split_from") or "")
            if isinstance(metadata.get("merged_from"), list):
                writ["merged_from"] = [str(x) for x in metadata.get("merged_from") if x]
        writs = self.list_writs()
        writs.append(writ)
        self._save_json(self._writs_file, writs)
        if dominion:
            dominions = self.list_dominions()
            for row in dominions:
                if str(row.get("dominion_id") or "") != str(dominion_id or ""):
                    continue
                row["writs"] = list(dict.fromkeys([*(row.get("writs") or []), writ["writ_id"]]))
                row["updated_utc"] = _utc()
                break
            self._save_json(self._dominions_file, dominions)
        self._register_trigger(writ)
        self._nerve.emit("writ_created", {"writ_id": writ["writ_id"], "dominion_id": dominion_id})
        return writ

    def update_writ(self, writ_id: str, updates: dict, *, cascade: bool = False) -> dict | None:
        writs = self.list_writs()
        target: dict | None = None
        for writ in writs:
            if str(writ.get("writ_id") or "") != str(writ_id or ""):
                continue
            target = writ
            break
        if not target:
            return None
        status = str(updates.get("status") or target.get("status") or "").strip()
        if status and status not in VALID_WRIT_STATUSES:
            return None
        allowed = {
            "label", "status", "brief_template", "trigger", "depends_on_writ",
            "max_pending_deeds", "deed_history", "split_from", "merged_from",
        }
        for key, value in updates.items():
            if key not in allowed:
                continue
            target[key] = value
        target["updated_utc"] = _utc()
        self._save_json(self._writs_file, writs)
        self._register_trigger(target)
        if str(target.get("status") or "") == "disabled":
            self._cascade_disable(target["writ_id"])
        self._nerve.emit("writ_updated", {"writ_id": writ_id, "status": target.get("status"), "cascade": cascade})
        return target

    def delete_writ(self, writ_id: str) -> bool:
        writs = self.list_writs()
        target = None
        filtered = []
        for writ in writs:
            if str(writ.get("writ_id") or "") == str(writ_id or ""):
                target = writ
            else:
                filtered.append(writ)
        if not target:
            return False
        self._save_json(self._writs_file, filtered)
        dominion_id = str(target.get("dominion_id") or "")
        if dominion_id:
            dominions = self.list_dominions()
            for dominion in dominions:
                if str(dominion.get("dominion_id") or "") != dominion_id:
                    continue
                dominion["writs"] = [row for row in dominion.get("writs") or [] if str(row) != str(writ_id)]
                dominion["updated_utc"] = _utc()
                break
            self._save_json(self._dominions_file, dominions)
        self._nerve.emit("writ_deleted", {"writ_id": writ_id, "dominion_id": dominion_id})
        return True

    def split_writ(self, writ_id: str, splits: list[dict]) -> list[dict]:
        source = self.get_writ(writ_id)
        if not source:
            raise ValueError("writ_not_found")
        created: list[dict] = []
        for row in splits:
            child = self.create_writ(
                brief_template=row.get("brief_template") or source.get("brief_template") or {},
                trigger=row.get("trigger") or source.get("trigger") or {},
                dominion_id=source.get("dominion_id"),
                label=str(row.get("label") or f"{source.get('label', 'Writ')} split"),
                depends_on_writ=row.get("depends_on_writ") or source.get("depends_on_writ"),
                metadata={"split_from": writ_id},
            )
            created.append(child)
        return created

    def merge_writs(self, writ_ids: list[str], *, label: str, brief_template: dict, trigger: dict) -> dict:
        sources = [self.get_writ(writ_id) for writ_id in writ_ids]
        sources = [row for row in sources if isinstance(row, dict)]
        if not sources:
            raise ValueError("writs_not_found")
        dominion_id = str(sources[0].get("dominion_id") or "")
        return self.create_writ(
            brief_template=brief_template,
            trigger=trigger,
            dominion_id=dominion_id or None,
            label=label,
            metadata={"merged_from": [str(row.get("writ_id") or "") for row in sources]},
        )

    def record_writ_triggered(self, writ_id: str, deed_id: str) -> None:
        writs = self.list_writs()
        for writ in writs:
            if str(writ.get("writ_id") or "") != str(writ_id or ""):
                continue
            writ["last_triggered_utc"] = _utc()
            writ["deed_count"] = int(writ.get("deed_count") or 0) + 1
            history = writ.get("deed_history") if isinstance(writ.get("deed_history"), list) else []
            history.append(str(deed_id))
            writ["deed_history"] = history[-200:]
            writ["updated_utc"] = _utc()
            break
        self._save_json(self._writs_file, writs)

    # ── Trigger management ────────────────────────────────────────────────

    def register_all_triggers(self) -> int:
        count = 0
        for writ in self.list_writs():
            if str(writ.get("status") or "") == "active":
                self._register_trigger(writ)
                count += 1
        return count

    def _register_trigger(self, writ: dict) -> None:
        trigger = writ.get("trigger") if isinstance(writ.get("trigger"), dict) else {}
        status = str(writ.get("status") or "")
        writ_id = str(writ.get("writ_id") or "")
        event = str(trigger.get("event") or "").strip()
        schedule = str(trigger.get("schedule") or "").strip()
        source_events = []
        if event:
            source_events.append(event)
        if schedule:
            source_events.append("cadence.tick")
        if status != "active":
            return
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
        trigger = writ.get("trigger") if isinstance(writ.get("trigger"), dict) else {}
        event = str(trigger.get("event") or "").strip()
        schedule = str(trigger.get("schedule") or "").strip()
        if source_event == "cadence.tick":
            tick_dt = _parse_utc(str(payload.get("tick_utc") or ""))
            if not schedule or not tick_dt or not _cron_matches(schedule, tick_dt):
                return
            last_triggered = _parse_utc(str(writ.get("last_triggered_utc") or ""))
            if last_triggered and last_triggered.strftime("%Y-%m-%dT%H:%M") == tick_dt.strftime("%Y-%m-%dT%H:%M"):
                return
        elif event and event != source_event:
            return

        trigger_filter = trigger.get("filter") if isinstance(trigger.get("filter"), dict) else {}
        for key, expected in trigger_filter.items():
            actual = payload.get(key)
            if expected == "self":
                expected = writ_id
            if actual != expected:
                return

        depends = str(writ.get("depends_on_writ") or "").strip()
        if depends:
            dep_writ = self.get_writ(depends)
            if not dep_writ or int(dep_writ.get("deed_count") or 0) <= 0:
                return

        ok, reason = self.can_trigger_writ(writ_id)
        if not ok:
            logger.info("Writ %s skipped: %s", writ_id, reason)
            return

        self._nerve.emit(
            "writ_trigger_ready",
            {
                "writ_id": writ_id,
                "dominion_id": writ.get("dominion_id"),
                "brief_template": writ.get("brief_template"),
                "trigger_payload": payload,
                "trigger_event": source_event,
            },
        )

    # ── Limits / helpers ──────────────────────────────────────────────────

    def can_trigger_writ(self, writ_id: str) -> tuple[bool, str]:
        writ = self.get_writ(writ_id)
        if not writ:
            return False, "writ_not_found"
        limit = int(writ.get("max_pending_deeds") or 3)
        active_same_writ = 0
        for row in self._ledger.load_deeds():
            if not isinstance(row, dict):
                continue
            if str(row.get("writ_id") or "") != writ_id:
                continue
            if str(row.get("deed_status") or "") in ACTIVE_DEED_STATUSES:
                active_same_writ += 1
        if active_same_writ >= limit:
            return False, "writ_max_pending_deeds_exceeded"
        dominion_id = str(writ.get("dominion_id") or "")
        if dominion_id:
            dominion = self.get_dominion(dominion_id)
            if dominion:
                limit = int(dominion.get("max_concurrent_deeds") or 6)
                active_same_dominion = 0
                for row in self._ledger.load_deeds():
                    if not isinstance(row, dict):
                        continue
                    if str(row.get("dominion_id") or "") != dominion_id:
                        continue
                    if str(row.get("deed_status") or "") in ACTIVE_DEED_STATUSES:
                        active_same_dominion += 1
                if active_same_dominion >= limit:
                    return False, "dominion_max_concurrent_deeds_exceeded"
        return True, ""

    def check_submission_limits(self, plan: dict, *, concurrent_limit: int | None = None) -> tuple[bool, str]:
        metadata = plan.get("metadata") if isinstance(plan.get("metadata"), dict) else {}
        writ_id = str(metadata.get("writ_id") or plan.get("writ_id") or "")
        dominion_id = str(metadata.get("dominion_id") or plan.get("dominion_id") or "")
        deeds = self._ledger.load_deeds()
        running_total = sum(1 for row in deeds if isinstance(row, dict) and str(row.get("deed_status") or "") in ACTIVE_DEED_STATUSES)
        if writ_id:
            max_running = max(1, int(concurrent_limit or 10) - DEFAULT_RESERVED_INDEPENDENT_SLOTS)
            if running_total >= max_running:
                return False, "reserved_independent_slots"
            ok, reason = self.can_trigger_writ(writ_id)
            if not ok:
                return False, reason
        if dominion_id:
            dominion = self.get_dominion(dominion_id)
            if dominion and str(dominion.get("status") or "") != "active":
                return False, "dominion_not_active"
        return True, ""

    def infer_complexity_from_history(self, writ_id: str, default: str = "charge") -> str:
        if not writ_id:
            return default
        counts: dict[str, int] = {}
        writ = self.get_writ(writ_id)
        if not writ:
            return default
        history = writ.get("deed_history") if isinstance(writ.get("deed_history"), list) else []
        deed_rows = {
            str(row.get("deed_id") or ""): row
            for row in self._ledger.load_deeds()
            if isinstance(row, dict)
        }
        for deed_id in history[-50:]:
            row = deed_rows.get(str(deed_id))
            if not row:
                continue
            complexity = str(
                row.get("complexity")
                or ((row.get("plan") or {}).get("complexity") if isinstance(row.get("plan"), dict) else "")
                or ""
            ).strip()
            if complexity:
                counts[complexity] = counts.get(complexity, 0) + 1
        if not counts:
            return default
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    def recent_deed_summaries(self, writ_id: str, *, limit: int = 3) -> list[dict]:
        if not writ_id:
            return []
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
                    "title": str(row.get("deed_title") or row.get("title") or ""),
                    "status": str(row.get("deed_status") or ""),
                    "updated_utc": str(row.get("updated_utc") or ""),
                }
            )
            if len(summaries) >= limit:
                break
        return summaries

    def active_dominion_matches(self, text: str, *, limit: int = 3) -> list[dict]:
        hay = {token for token in str(text or "").lower().split() if token}
        ranked: list[tuple[int, dict]] = []
        for dominion in self.list_dominions():
            if str(dominion.get("status") or "") != "active":
                continue
            objective_tokens = {token for token in str(dominion.get("objective") or "").lower().split() if token}
            score = len(hay & objective_tokens)
            if score > 0:
                ranked.append((score, dominion))
        ranked.sort(key=lambda item: (-item[0], str(item[1].get("updated_utc") or "")), reverse=False)
        return [row for _, row in ranked[: max(1, int(limit))]]

    # ── Internal helpers ──────────────────────────────────────────────────

    def _cascade_disable(self, root_writ_id: str) -> None:
        writs = self.list_writs()
        children = []
        for writ in writs:
            if str(writ.get("writ_id") or "") == str(root_writ_id or ""):
                continue
            if str(writ.get("split_from") or "") == str(root_writ_id or ""):
                children.append(str(writ.get("writ_id") or ""))
                continue
            merged_from = writ.get("merged_from") if isinstance(writ.get("merged_from"), list) else []
            if str(root_writ_id or "") in [str(x) for x in merged_from]:
                all_disabled = True
                for src in merged_from:
                    source = self.get_writ(str(src))
                    if source and str(source.get("status") or "") != "disabled":
                        all_disabled = False
                        break
                if all_disabled:
                    children.append(str(writ.get("writ_id") or ""))
                continue
            if str(writ.get("depends_on_writ") or "") == str(root_writ_id or ""):
                children.append(str(writ.get("writ_id") or ""))
        for child_id in children:
            child = self.get_writ(child_id)
            if not child or str(child.get("status") or "") == "disabled":
                continue
            self.update_writ(child_id, {"status": "disabled"}, cascade=True)

    def _load_json(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    def _save_json(self, path: Path, data: list[dict]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
