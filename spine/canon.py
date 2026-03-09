"""Spine Canon — loads and validates Routine definitions from spine_registry.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class RoutineDefinition:
    def __init__(self, name: str, data: dict) -> None:
        self.name = name
        self.mode: str = data["mode"]
        self.schedule: str | None = data.get("schedule")
        self.nerve_triggers: list[str] = data.get("nerve_triggers", [])
        self.reads: list[str] = data.get("reads", [])
        self.writes: list[str] = data.get("writes", [])
        self.depends_on: list[str] = data.get("depends_on", [])
        self.degraded_mode: str | None = data.get("degraded_mode")

    @property
    def is_hybrid(self) -> bool:
        return self.mode == "hybrid"

    @property
    def is_deterministic(self) -> bool:
        return self.mode == "deterministic"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.mode,
            "schedule": self.schedule,
            "nerve_triggers": self.nerve_triggers,
            "reads": self.reads,
            "writes": self.writes,
            "depends_on": self.depends_on,
            "degraded_mode": self.degraded_mode,
        }


class SpineCanon:
    def __init__(self, registry_path: Path) -> None:
        self._path = registry_path
        self._routines: dict[str, RoutineDefinition] = {}
        self._load()

    def _load(self) -> None:
        data = json.loads(self._path.read_text())
        for name, rdef in data.get("routines", {}).items():
            self._routines[name] = RoutineDefinition(name, rdef)

    def get(self, name: str) -> RoutineDefinition | None:
        return self._routines.get(name)

    def all(self) -> list[RoutineDefinition]:
        return list(self._routines.values())

    def all_names(self) -> list[str]:
        return list(self._routines.keys())

    def by_trigger(self, nerve_event: str) -> list[RoutineDefinition]:
        return [r for r in self._routines.values() if nerve_event in r.nerve_triggers]
