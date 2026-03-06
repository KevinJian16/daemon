"""Semantic Layer — SemanticSpec generation and intent contract parsing.

Generation order (decision §4.1):
1. Deterministic parsing (keywords, artifact types, risk words, temporality).
2. Cortex structured completion for any unfilled slots.
3. Cortex unavailable → retain deterministic result, mark confidence=low.

Mapping failure (no cluster match + no run_type compat) → raises SemanticMappingError.
Callers must NOT fall back to a fake run_type.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime.cortex import Cortex

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).parent.parent / "config" / "semantics" / "capability_catalog.json"
_RULES_PATH = Path(__file__).parent.parent / "config" / "semantics" / "mapping_rules.json"


class SemanticMappingError(Exception):
    """Raised when no cluster can be resolved for a request."""


@dataclass
class SemanticSpec:
    cluster_id: str
    objective: str
    artifact_types: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    temporal_scope: str = "immediate"   # immediate | historical | ongoing
    risk_level: str = "low"             # low | medium | high
    language: str = "zh"                # zh | en | bilingual
    semantic_confidence: str = "high"   # high | medium | low

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SemanticSpec":
        return cls(
            cluster_id=str(d.get("cluster_id") or ""),
            objective=str(d.get("objective") or ""),
            artifact_types=list(d.get("artifact_types") or []),
            constraints=list(d.get("constraints") or []),
            temporal_scope=str(d.get("temporal_scope") or "immediate"),
            risk_level=str(d.get("risk_level") or "low"),
            language=str(d.get("language") or "zh"),
            semantic_confidence=str(d.get("semantic_confidence") or "high"),
        )


@dataclass
class IntentContract:
    objective: str
    constraints: dict[str, Any] = field(default_factory=dict)
    acceptance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def _normalize_kv(value: Any, key: str) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, list):
            # Accept array-style contract payloads from clients and normalize.
            return {"items": list(value)}
        if isinstance(value, str):
            s = value.strip()
            return {key: s} if s else {}
        if value is None:
            return {}
        return {key: value}

    @classmethod
    def from_dict(cls, d: dict) -> "IntentContract":
        if not isinstance(d, dict):
            raise SemanticMappingError("intent_contract_invalid: expected object")
        return cls(
            objective=str(d.get("objective") or ""),
            constraints=cls._normalize_kv(d.get("constraints"), "constraint"),
            acceptance=cls._normalize_kv(d.get("acceptance"), "acceptance"),
        )


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class SemanticGenerator:
    """Generates SemanticSpec from raw request input."""

    def __init__(self, cortex: "Cortex | None" = None) -> None:
        self._cortex = cortex
        self._catalog: dict = {}
        self._rules: dict = {}
        self._load_configs()

    def _load_configs(self) -> None:
        try:
            self._catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load capability_catalog.json: %s", exc)
        try:
            self._rules = json.loads(_RULES_PATH.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load mapping_rules.json: %s", exc)

    def _clusters(self) -> list[dict]:
        return self._catalog.get("clusters", [])

    def _cluster_by_id(self, cluster_id: str) -> dict | None:
        for c in self._clusters():
            if c.get("cluster_id") == cluster_id:
                return c
        return None

    def _cluster_by_run_type(self, run_type: str) -> dict | None:
        for c in self._clusters():
            if c.get("run_type_compat") == run_type:
                return c
        return None

    # ── Public API ─────────────────────────────────────────────────────────────

    def from_spec_dict(self, fp: dict) -> SemanticSpec:
        """Direct spec path — caller provides pre-formed spec."""
        cluster_id = str(fp.get("cluster_id") or "")
        if not cluster_id or not self._cluster_by_id(cluster_id):
            raise SemanticMappingError(f"Unknown cluster_id in provided spec: {cluster_id!r}")
        return SemanticSpec.from_dict(fp)

    def from_intent_contract(self, contract: dict, cortex: "Cortex | None" = None) -> SemanticSpec:
        """Intent contract path — generate spec from objective + constraints."""
        ic = IntentContract.from_dict(contract)
        if not ic.objective:
            raise SemanticMappingError("intent_contract.objective is required")
        return self._generate(ic.objective, cortex=cortex or self._cortex)

    def from_run_type(self, run_type: str, title: str = "") -> SemanticSpec:
        """run_type compat path — map legacy run_type to cluster."""
        cluster = self._cluster_by_run_type(run_type)
        if not cluster:
            raise SemanticMappingError(f"run_type {run_type!r} has no cluster mapping in capability_catalog.json")
        objective = title or run_type.replace("_", " ")
        return SemanticSpec(
            cluster_id=cluster["cluster_id"],
            objective=objective,
            artifact_types=list(cluster.get("artifact_types", [])),
            risk_level=cluster.get("risk_level", "low"),
            semantic_confidence="high",
        )

    # ── Internal ───────────────────────────────────────────────────────────────

    def _generate(self, text: str, cortex: "Cortex | None" = None) -> SemanticSpec:
        """Deterministic first, Cortex fill-in second."""
        det = self._deterministic_parse(text)
        if det and det.get("confidence") == "high":
            return SemanticSpec.from_dict(det)

        if cortex and cortex.is_available():
            try:
                llm_result = cortex.structured(
                    f"Analyze this run request and classify it:\n\n{text}\n\n"
                    "Match to one of these cluster IDs: "
                    + ", ".join(c["cluster_id"] for c in self._clusters()),
                    schema={
                        "cluster_id": "string",
                        "objective": "string",
                        "artifact_types": ["string"],
                        "temporal_scope": "immediate|historical|ongoing",
                        "risk_level": "low|medium|high",
                        "language": "zh|en|bilingual",
                    },
                )
                cluster_id = str(llm_result.get("cluster_id") or "")
                if cluster_id and self._cluster_by_id(cluster_id):
                    fp = SemanticSpec.from_dict(llm_result)
                    fp.semantic_confidence = "medium"
                    return fp
            except Exception as exc:
                logger.warning("Cortex spec generation failed: %s", exc)

        # Fall back to deterministic result (even if low confidence) or fail.
        if det:
            fp = SemanticSpec.from_dict(det)
            fp.semantic_confidence = "low"
            return fp

        raise SemanticMappingError(
            f"semantic_mapping_failed: could not resolve cluster for input: {text[:200]!r}"
        )

    def _deterministic_parse(self, text: str) -> dict | None:
        """Rule-based cluster matching. Returns dict with cluster fields, or None."""
        text_lower = text.lower()
        rules = sorted(
            self._rules.get("rules", []),
            key=lambda r: int(r.get("priority", 0)),
            reverse=True,
        )
        best_rule: dict | None = None
        best_score = 0
        for rule in rules:
            if rule.get("is_default_fallback"):
                continue
            keywords = rule.get("match", {}).get("keywords", [])
            matched = sum(1 for kw in keywords if kw.lower() in text_lower)
            if matched > 0 and matched >= best_score:
                best_score = matched
                best_rule = rule

        # If no rule matched, use default fallback rule.
        if not best_rule:
            for rule in rules:
                if rule.get("is_default_fallback"):
                    best_rule = rule
                    break

        if not best_rule:
            return None

        cluster_id = str(best_rule.get("cluster_id") or "")
        cluster = self._cluster_by_id(cluster_id)
        if not cluster:
            return None

        thresholds = self._rules.get("confidence_thresholds", {"high": 0.85, "medium": 0.60})
        # Confidence based on keyword coverage ratio.
        keywords = best_rule.get("match", {}).get("keywords", [])
        ratio = best_score / max(len(keywords), 1) if keywords else 0.0
        if ratio >= thresholds.get("high", 0.85):
            confidence = "high"
        elif ratio >= thresholds.get("medium", 0.60):
            confidence = "medium"
        else:
            confidence = "low"

        # Detect language hints.
        has_chinese = bool(re.search(r"[\u4e00-\u9fff]", text))
        has_english = bool(re.search(r"[a-zA-Z]{3,}", text))
        if has_chinese and has_english:
            language = "bilingual"
        elif has_chinese:
            language = "zh"
        else:
            language = "en"

        return {
            "cluster_id": cluster_id,
            "objective": text[:300],
            "artifact_types": list(cluster.get("artifact_types", [])),
            "temporal_scope": "immediate",
            "risk_level": cluster.get("risk_level", "low"),
            "language": language,
            "confidence": confidence,
        }
