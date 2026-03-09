"""Dominion-Writ-Deed management — goal-oriented task orchestration.

Dominion: long-term goal container (optional, most deeds don't belong to one)
Writ: scheduling unit with unified event trigger (replaces old "chain" concept)
Deed: individual task execution (already managed by will/temporal)

Writ triggers are unified event subscriptions on the Nerve bus, not enumerated types.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

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


class DominionWritManager:
    """Manages Dominion and Writ lifecycle + Writ trigger subscriptions."""

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
        self._ensure_files()

    def _ensure_files(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        for f in (self._dominions_file, self._writs_file):
            if not f.exists():
                f.write_text("[]", encoding="utf-8")

    # ── Dominion CRUD ─────────────────────────────────────────────────────────

    def list_dominions(self) -> list[dict]:
        return self._load_json(self._dominions_file)

    def get_dominion(self, dominion_id: str) -> dict | None:
        for t in self.list_dominions():
            if t.get("dominion_id") == dominion_id:
                return t
        return None

    def create_dominion(self, objective: str, metadata: dict | None = None) -> dict:
        dominion = {
            "dominion_id": _uuid(),
            "objective": objective,
            "status": "active",
            "created_utc": _utc(),
            "updated_utc": _utc(),
            "writs": [],
            "progress_notes": [],
            **(metadata or {}),
        }
        dominions = self.list_dominions()
        dominions.append(dominion)
        self._save_json(self._dominions_file, dominions)
        self._nerve.emit("dominion_created", {"dominion_id": dominion["dominion_id"]})
        return dominion

    def update_dominion(self, dominion_id: str, updates: dict) -> dict | None:
        dominions = self.list_dominions()
        for t in dominions:
            if t.get("dominion_id") == dominion_id:
                allowed = {"objective", "status", "progress_notes"}
                for k, v in updates.items():
                    if k in allowed:
                        t[k] = v
                if "status" in updates and updates["status"] not in VALID_DOMINION_STATUSES:
                    return None
                t["updated_utc"] = _utc()
                self._save_json(self._dominions_file, dominions)
                return t
        return None

    def delete_dominion(self, dominion_id: str) -> bool:
        dominions = self.list_dominions()
        filtered = [t for t in dominions if t.get("dominion_id") != dominion_id]
        if len(filtered) == len(dominions):
            return False
        self._save_json(self._dominions_file, filtered)
        return True

    # ── Writ CRUD ─────────────────────────────────────────────────────────────

    def list_writs(self, dominion_id: str | None = None) -> list[dict]:
        writs = self._load_json(self._writs_file)
        if dominion_id:
            return [l for l in writs if l.get("dominion_id") == dominion_id]
        return writs

    def get_writ(self, writ_id: str) -> dict | None:
        for l in self.list_writs():
            if l.get("writ_id") == writ_id:
                return l
        return None

    def create_writ(
        self,
        brief_template: dict,
        trigger: dict,
        dominion_id: str | None = None,
        label: str = "",
        depends_on_writ: str | None = None,
    ) -> dict:
        """Create a new Writ with unified event trigger config.

        trigger format:
            event: str           # Nerve event name to subscribe to
            filter: dict | None  # Optional payload filter
            schedule: str | None # Optional cron expression
        """
        writ = {
            "writ_id": _uuid(),
            "dominion_id": dominion_id,
            "label": label,
            "status": "active",
            "brief_template": brief_template,
            "trigger": trigger,
            "depends_on_writ": depends_on_writ,
            "created_utc": _utc(),
            "updated_utc": _utc(),
            "last_triggered_utc": None,
            "deed_count": 0,
        }
        writs = self.list_writs()
        writs.append(writ)
        self._save_json(self._writs_file, writs)

        # Register trigger subscription on Nerve
        self._register_trigger(writ)

        # Update Dominion's writ list if applicable
        if dominion_id:
            dominions = self.list_dominions()
            for t in dominions:
                if t.get("dominion_id") == dominion_id:
                    writ_ids = t.get("writs", [])
                    writ_ids.append(writ["writ_id"])
                    t["writs"] = writ_ids
                    t["updated_utc"] = _utc()
                    break
            self._save_json(self._dominions_file, dominions)

        self._nerve.emit("writ_created", {"writ_id": writ["writ_id"], "dominion_id": dominion_id})
        return writ

    def update_writ(self, writ_id: str, updates: dict) -> dict | None:
        writs = self.list_writs()
        for l in writs:
            if l.get("writ_id") == writ_id:
                allowed = {"label", "status", "brief_template", "trigger", "depends_on_writ"}
                for k, v in updates.items():
                    if k in allowed:
                        l[k] = v
                if "status" in updates and updates["status"] not in VALID_WRIT_STATUSES:
                    return None
                l["updated_utc"] = _utc()
                self._save_json(self._writs_file, writs)
                # Re-register trigger if changed
                if "trigger" in updates or "status" in updates:
                    self._register_trigger(l)
                return l
        return None

    def delete_writ(self, writ_id: str) -> bool:
        writs = self.list_writs()
        target = None
        filtered = []
        for l in writs:
            if l.get("writ_id") == writ_id:
                target = l
            else:
                filtered.append(l)
        if not target:
            return False
        self._save_json(self._writs_file, filtered)

        # Remove from Dominion's writ list
        dominion_id = target.get("dominion_id")
        if dominion_id:
            dominions = self.list_dominions()
            for t in dominions:
                if t.get("dominion_id") == dominion_id:
                    t["writs"] = [lid for lid in t.get("writs", []) if lid != writ_id]
                    t["updated_utc"] = _utc()
                    break
            self._save_json(self._dominions_file, dominions)
        return True

    def record_writ_triggered(self, writ_id: str, deed_id: str) -> None:
        """Record that a Writ was triggered and produced a Deed."""
        writs = self.list_writs()
        for l in writs:
            if l.get("writ_id") == writ_id:
                l["last_triggered_utc"] = _utc()
                l["deed_count"] = (l.get("deed_count") or 0) + 1
                break
        self._save_json(self._writs_file, writs)

    # ── Trigger management ────────────────────────────────────────────────────

    def register_all_triggers(self) -> int:
        """Register Nerve handlers for all active Writ triggers. Called on startup."""
        writs = self.list_writs()
        count = 0
        for writ in writs:
            if writ.get("status") == "active":
                self._register_trigger(writ)
                count += 1
        return count

    def _register_trigger(self, writ: dict) -> None:
        """Register (or deregister) a Writ's event trigger on the Nerve bus."""
        trigger = writ.get("trigger") or {}
        event = trigger.get("event")
        status = writ.get("status", "active")

        if not event or status != "active":
            return

        writ_id = writ["writ_id"]

        def _handler(payload: dict) -> None:
            self._on_trigger_fired(writ_id, payload)

        # Tag handler so we can identify it for deregistration
        _handler._writ_id = writ_id  # type: ignore[attr-defined]
        self._nerve.on(event, _handler)

    def _on_trigger_fired(self, writ_id: str, payload: dict) -> None:
        """Called when a subscribed Nerve event fires for a Writ."""
        writ = self.get_writ(writ_id)
        if not writ or writ.get("status") != "active":
            return

        trigger = writ.get("trigger") or {}
        trigger_filter = trigger.get("filter")

        # Apply payload filter if specified
        if trigger_filter and isinstance(trigger_filter, dict):
            for key, expected in trigger_filter.items():
                if expected == "self":
                    expected = writ_id
                actual = payload.get(key)
                if actual != expected:
                    return

        # Check depends_on_writ
        depends = writ.get("depends_on_writ")
        if depends:
            dep_writ = self.get_writ(depends)
            if not dep_writ or dep_writ.get("deed_count", 0) == 0:
                logger.info("Writ %s skipped: dependency %s not yet completed", writ_id, depends)
                return

        logger.info("Writ %s trigger fired, emitting writ_trigger_ready", writ_id)
        self._nerve.emit("writ_trigger_ready", {
            "writ_id": writ_id,
            "dominion_id": writ.get("dominion_id"),
            "brief_template": writ.get("brief_template"),
            "trigger_payload": payload,
        })

    # ── File I/O ──────────────────────────────────────────────────────────────

    def _load_json(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_json(self, path: Path, data: list[dict]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
