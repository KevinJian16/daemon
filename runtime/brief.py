"""Brief — normalized single-slip planning contract."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


VALID_DEPTHS = {"glance", "study", "scrutiny"}
VALID_LANGUAGES = {"zh", "en", "bilingual"}
VALID_FIT_CONFIDENCES = {"high", "medium", "low"}

SINGLE_SLIP_DEFAULTS = {
    "dag_budget": 6,
    "concurrency": 2,
    "timeout_per_move_s": 300,
    "rework_limit": 1,
}


@dataclass
class Brief:
    objective: str
    language: str = "bilingual"
    format: str = "markdown"
    depth: str = "study"
    references: list[str] = field(default_factory=list)
    dag_budget: int = SINGLE_SLIP_DEFAULTS["dag_budget"]
    fit_confidence: str = "medium"
    quality_hints: list[str] = field(default_factory=list)
    standing: bool = False

    def __post_init__(self) -> None:
        if self.depth not in VALID_DEPTHS:
            self.depth = "study"
        if self.language not in VALID_LANGUAGES:
            self.language = "bilingual"
        if self.fit_confidence not in VALID_FIT_CONFIDENCES:
            self.fit_confidence = "medium"
        if self.dag_budget <= 0:
            self.dag_budget = SINGLE_SLIP_DEFAULTS["dag_budget"]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Brief":
        return cls(
            objective=str(d.get("objective") or ""),
            language=str(d.get("language") or "bilingual"),
            format=str(d.get("format") or "markdown"),
            depth=str(d.get("depth") or "study"),
            references=[str(x) for x in (d.get("references") or []) if str(x).strip()],
            dag_budget=int(d.get("dag_budget") or 0),
            fit_confidence=str(d.get("fit_confidence") or "medium"),
            quality_hints=[str(x) for x in (d.get("quality_hints") or []) if str(x).strip()],
            standing=bool(d.get("standing")),
        )

    def execution_defaults(self) -> dict:
        return dict(SINGLE_SLIP_DEFAULTS)
