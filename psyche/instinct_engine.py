"""InstinctEngine — hard-rule enforcement + prompt injection for system principles."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


class InstinctEngine:
    """Instinct = code-level enforcement, not LLM suggestion.

    Three layers:
    1. Hard rules: Python if/else pre/post checks (this class)
    2. Soft rules: instinct.md injected into agent prompt (~200 tokens)
    3. Critical review: arbiter agent for high-risk output (triggered by Brief.review_required)
    """

    # Token budget hard limits for Voice files
    IDENTITY_TOKEN_LIMIT = 150
    STYLE_TOKEN_LIMIT = 250
    OVERLAY_TOKEN_LIMIT = 50

    def __init__(
        self,
        instinct_path: Path,
        sensitive_terms_path: Path | None = None,
    ) -> None:
        self._instinct_path = instinct_path
        self._instinct_text = ""
        if instinct_path.exists():
            try:
                self._instinct_text = instinct_path.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning("Failed to read instinct.md: %s", exc)

        self._sensitive_terms: list[str] = []
        if sensitive_terms_path and sensitive_terms_path.exists():
            try:
                data = json.loads(sensitive_terms_path.read_text(encoding="utf-8"))
                self._sensitive_terms = [str(t) for t in data if isinstance(t, str) and t.strip()]
            except Exception as exc:
                logger.warning("Failed to load sensitive_terms.json: %s", exc)

    # ── Prompt injection (soft rules) ─────────────────────────────────────────

    def prompt_fragment(self) -> str:
        """Return instinct.md content for agent prompt injection (~200 tokens)."""
        return self._instinct_text

    # ── Hard rule checks ──────────────────────────────────────────────────────

    def check_outbound_query(self, query: str) -> str:
        """Filter sensitive terms from outbound search queries. Returns cleaned query."""
        cleaned = query
        for term in self._sensitive_terms:
            if term.lower() in cleaned.lower():
                cleaned = re.sub(re.escape(term), "某项目", cleaned, flags=re.IGNORECASE)
        return cleaned

    def check_output(self, output: str, task_type: str) -> list[str]:
        """Check output against hard rules. Returns list of violations (empty = pass)."""
        violations: list[str] = []
        if not output or not output.strip():
            violations.append("empty_output")
            return violations

        # Sensitive term leakage check
        lower_output = output.lower()
        for term in self._sensitive_terms:
            if term.lower() in lower_output:
                violations.append(f"sensitive_term_leaked:{term[:20]}")

        return violations

    def check_wash_output(self, wash_result: dict) -> dict:
        """Validate and clean wash output before consumption. Returns cleaned dict."""
        cleaned = dict(wash_result)

        # Check Voice candidates for token budget
        voice_candidates = cleaned.get("voice_candidates", [])
        if isinstance(voice_candidates, list):
            filtered = []
            for candidate in voice_candidates:
                if not isinstance(candidate, dict):
                    continue
                content = str(candidate.get("content", ""))
                # Reject candidates that are too long (likely noise)
                if len(content) > 500:
                    continue
                filtered.append(candidate)
            cleaned["voice_candidates"] = filtered

        return cleaned

    def check_voice_update(self, section: str, content: str) -> list[str]:
        """Validate Voice file update. Returns violations list."""
        violations: list[str] = []
        estimated_tokens = len(content) // 4

        if section == "identity" and estimated_tokens > self.IDENTITY_TOKEN_LIMIT:
            violations.append(f"identity_exceeds_token_limit:{estimated_tokens}/{self.IDENTITY_TOKEN_LIMIT}")
        elif section in ("common", "zh", "en") and estimated_tokens > self.STYLE_TOKEN_LIMIT:
            violations.append(f"style_exceeds_token_limit:{estimated_tokens}/{self.STYLE_TOKEN_LIMIT}")

        return violations
