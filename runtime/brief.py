"""Brief — unified request specification replacing SemanticSpec + IntentContract."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


VALID_COMPLEXITIES = {"errand", "charge", "endeavor"}
VALID_DEPTHS = {"glance", "study", "scrutiny"}
# format is a free-form user hint (can be empty); actual output format is adaptive.
# This set is kept only for backward compatibility with existing plans.
KNOWN_FORMATS = {"pdf", "markdown", "code", "text"}
VALID_LANGUAGES = {"zh", "en", "bilingual"}
VALID_CONFIDENCES = {"high", "medium", "low"}

COMPLEXITY_DEFAULTS = {
    "errand": {"move_budget": 1, "concurrency": 1, "timeout_per_move_s": 120, "rework_limit": 0},
    "charge": {"move_budget": 6, "concurrency": 2, "timeout_per_move_s": 300, "rework_limit": 1},
    "endeavor": {"move_budget": 40, "concurrency": 4, "timeout_per_move_s": 600, "rework_limit": 2},
}

# Backward compatibility: old complexity/depth names map to new ones.
_COMPLEXITY_ALIASES = {"pulse": "errand", "thread": "charge", "campaign": "endeavor"}
_DEPTH_ALIASES = {"brief": "glance", "standard": "study", "thorough": "scrutiny"}


@dataclass
class Brief:
    objective: str
    complexity: str = "charge"
    move_budget: int = 6
    language: str = "bilingual"
    format: str = "markdown"
    depth: str = "study"
    references: list[str] = field(default_factory=list)
    confidence: str = "high"
    quality_hints: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Normalize old complexity/depth names.
        self.complexity = _COMPLEXITY_ALIASES.get(self.complexity, self.complexity)
        self.depth = _DEPTH_ALIASES.get(self.depth, self.depth)
        if self.complexity not in VALID_COMPLEXITIES:
            self.complexity = "charge"
        if self.depth not in VALID_DEPTHS:
            self.depth = "study"
        # format is a free-form hint; no validation needed
        if self.language not in VALID_LANGUAGES:
            self.language = "bilingual"
        if self.confidence not in VALID_CONFIDENCES:
            self.confidence = "high"
        defaults = COMPLEXITY_DEFAULTS.get(self.complexity, COMPLEXITY_DEFAULTS["charge"])
        if self.move_budget <= 0:
            self.move_budget = defaults["move_budget"]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Brief":
        return cls(
            objective=str(d.get("objective") or ""),
            complexity=str(d.get("complexity") or "charge"),
            move_budget=int(d.get("move_budget") or d.get("step_budget") or 0),
            language=str(d.get("language") or "bilingual"),
            format=str(d.get("format") or "markdown"),
            depth=str(d.get("depth") or "study"),
            references=list(d.get("references") or []),
            confidence=str(d.get("confidence") or "high"),
            quality_hints=list(d.get("quality_hints") or []),
        )

    def execution_defaults(self) -> dict:
        """Return complexity-based execution defaults."""
        return dict(COMPLEXITY_DEFAULTS.get(self.complexity, COMPLEXITY_DEFAULTS["charge"]))


# Backward compatibility alias
RunSpec = Brief
