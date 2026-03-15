"""Custom NeMo Guardrails actions for daemon.

Pattern-based validation actions that run at zero LLM token cost.
Reference: SYSTEM_DESIGN.md §4.2, §5.2, §10
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Forbidden markers (§10 item 42) ─────────────────────────────

FORBIDDEN_MARKERS = [
    "[DONE]", "[COMPLETE]", "[INTERNAL]", "[DEBUG]", "[TOOL_CALL]",
    "<system-note>", "</system-note>",
]
FORBIDDEN_PATTERN = re.compile(
    r"\[DONE\]|\[COMPLETE\]|\[INTERNAL\]|\[DEBUG\]|\[TOOL_CALL\]"
    r"|<system-note>.*?</system-note>"
    r"|\[system:[^\]]*\]"
    r"|```system\n.*?```",
    re.DOTALL,
)

# ── Source tier patterns ─────────────────────────────────────────

TIER_A_PATTERNS = [
    r"arxiv\.org", r"doi\.org", r"scholar\.google", r"semantic-?scholar",
    r"docs\.\w+\.(com|org|io)", r"spec\.", r"rfc-editor\.org",
]
TIER_C_PATTERNS = [
    r"reddit\.com", r"quora\.com", r"zhihu\.com",
    r"stackoverflow\.com/questions/\d+#comment",
    r"twitter\.com", r"x\.com/\w+/status",
]

_tier_a_re = re.compile("|".join(TIER_A_PATTERNS), re.IGNORECASE)
_tier_c_re = re.compile("|".join(TIER_C_PATTERNS), re.IGNORECASE)

# ── Sensitive terms ──────────────────────────────────────────────

_sensitive_terms: list[str] | None = None


def _load_sensitive_terms() -> list[str]:
    global _sensitive_terms
    if _sensitive_terms is not None:
        return _sensitive_terms
    p = Path(__file__).parent.parent / "sensitive_terms.json"
    if p.exists():
        _sensitive_terms = json.loads(p.read_text())
    else:
        _sensitive_terms = []
    return _sensitive_terms


# ── Public API ───────────────────────────────────────────────────


def clean_forbidden_markers(text: str) -> str:
    """Remove all forbidden system markers from text."""
    return FORBIDDEN_PATTERN.sub("", text).strip()


def classify_source_tier(url: str) -> str:
    """Classify a URL into source tier A/B/C.
    A = high trust (academic, official docs)
    B = medium trust (Wikipedia, MDN, mainstream)
    C = low trust (forums, social media, anonymous)
    """
    if _tier_a_re.search(url):
        return "A"
    if _tier_c_re.search(url):
        return "C"
    return "B"


def check_tier_c_sole_support(text: str) -> bool:
    """Check if text relies solely on Tier C sources for factual claims.
    Returns True if violation detected (Tier C is sole source)."""
    urls = re.findall(r"https?://[^\s\)]+", text)
    if not urls:
        return False
    tiers = [classify_source_tier(u) for u in urls]
    # Violation: all cited sources are Tier C
    return len(tiers) > 0 and all(t == "C" for t in tiers)


def filter_sensitive_outbound(query: str) -> str:
    """Replace sensitive terms in outbound queries with generic descriptions.
    Used before external MCP tool calls (§5.6.2)."""
    terms = _load_sensitive_terms()
    result = query
    for term in terms:
        if term.lower() in result.lower():
            result = re.sub(re.escape(term), "[REDACTED]", result, flags=re.IGNORECASE)
    return result


def validate_output(text: str) -> tuple[str, list[str]]:
    """Run all output validation checks. Returns (cleaned_text, warnings).

    This is the main entry point called by the daemon activity execution pipeline.
    Zero LLM tokens — all pattern-based.
    """
    warnings: list[str] = []

    # 1. Remove forbidden markers
    cleaned = clean_forbidden_markers(text)
    if cleaned != text:
        warnings.append("Removed internal system markers from output")

    # 2. Check Tier C sole support
    if check_tier_c_sole_support(cleaned):
        warnings.append(
            "Output relies solely on low-trust (Tier C) sources. "
            "Cross-verification with Tier A/B sources recommended."
        )

    return cleaned, warnings


def validate_input(text: str) -> tuple[str, list[str]]:
    """Run input validation checks. Returns (filtered_text, warnings).

    Checks for instruction override attempts and sensitive data.
    Zero LLM tokens — all pattern-based.
    """
    warnings: list[str] = []

    # 1. Instruction override detection
    override_patterns = [
        r"ignore\s+(previous|your)\s+instructions",
        r"forget\s+your\s+rules",
        r"override\s+system",
        r"disable\s+guardrails",
        r"bypass\s+safety",
        r"act\s+as\s+if.*no\s+restrictions",
        r"pretend.*unrestricted",
        r"jailbreak",
    ]
    for pattern in override_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            warnings.append("Instruction override attempt detected and blocked")
            return "", warnings  # Block entirely

    # 2. Sensitive term filtering for outbound queries
    filtered = filter_sensitive_outbound(text)
    if filtered != text:
        warnings.append("Sensitive terms redacted from query")

    return filtered, warnings


def validate_mem0_write(entry: dict) -> tuple[bool, str]:
    """Validate a Mem0 memory entry before writing.
    Returns (is_valid, reason).
    Reference: §5.4, §5.3.1"""
    if not entry.get("content"):
        return False, "Memory entry has no content"

    content = str(entry["content"])

    # Check for system instruction leakage
    if any(marker in content for marker in FORBIDDEN_MARKERS):
        return False, "Memory entry contains forbidden system markers"

    # Check minimum meaningful length
    if len(content.strip()) < 5:
        return False, "Memory entry too short to be meaningful"

    return True, "ok"
