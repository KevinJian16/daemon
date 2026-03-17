#!/usr/bin/env python3
"""Lexicon validation script (§0.5).

Reads config/lexicon.json and greps the Python codebase for usage of
non-canonical (deprecated) terms. Reports any violations to stdout.

Canonical terms are those with "state": "canonical" in lexicon.json.
Deprecated terms are derived from the old terminology mapping embedded
below (maintained alongside the lexicon).

Usage:
    python scripts/validate_lexicon.py [--path <root>] [--strict]

Exit codes:
    0 — no violations found
    1 — violations found
    2 — script/config error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# Deprecated → canonical term mapping (§1.8, §lexicon).
# Key = old term (case-insensitive search pattern)
# Value = canonical replacement
DEPRECATED_TERMS: dict[str, str] = {
    # Object model renames
    "deed": "Job",
    "writ": "Task",
    "folio": "Project",
    "slip": "Task",
    # Infrastructure renames
    "ledger": "Store",
    "ether": "EventBus",
    "vault": "MinIO",
    "trail": "Langfuse",
    "source_cache": "Knowledge Base",
    # Agent/persona renames (old names no longer in use)
    "counsel": "copilot/instructor/navigator/autopilot (L1 agents)",
    "scholar": "researcher",
    "artificer": "engineer",
    "scribe": "writer",
    "arbiter": "reviewer",
    "envoy": "publisher",
    "steward": "admin",
    # Module/system renames
    "psyche": "Mem0",
    "instinct": "NeMo Guardrails",
    "retinue": "OC native sessions",
    "cortex": "Mem0",
    "cadence": "Temporal Schedules",
    "herald": "publisher agent",
    "portal": "Plane",
    "console": "Plane",
}

# Patterns that are false positives for certain terms (regexes on the whole line).
# If a line matches any of these for a given term, the match is suppressed.
FALSE_POSITIVE_PATTERNS: dict[str, list[str]] = {
    # "portal" appears legitimately in static-file route comments referring to
    # the compiled portal dir (it is the directory name, not the deprecated UI term)
    "portal": [
        r"interfaces/portal",
        r"portal_dir",
        r"portal/compiled",
        r"/portal",
        r"Portal mounted",
        r"Portal UI",
        r'"portal"',
        r"'portal'",
    ],
    # "console" can legitimately appear as Python's logging/console references
    "console": [
        r"console_admin",
        r"console_runtime",
        r"api_routes/console",
        r"logging\.getLogger",
    ],
    # "herald" may remain in this very script's comment block
    "herald": [
        r"#.*herald",
    ],
}

# File extensions to scan
SCAN_EXTENSIONS = {".py"}

# Directories/files to skip entirely
SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".ref", "_archive", "compiled",
}
SKIP_FILES = {
    "validate_lexicon.py",  # this script itself
}


def _load_lexicon(lexicon_path: Path) -> dict:
    with lexicon_path.open(encoding="utf-8") as f:
        return json.load(f)


def _iter_python_files(root: Path):
    for path in root.rglob("*.py"):
        # Skip excluded directories
        parts = set(path.parts)
        if parts & SKIP_DIRS:
            continue
        if path.name in SKIP_FILES:
            continue
        yield path


def _is_false_positive(term: str, line: str) -> bool:
    patterns = FALSE_POSITIVE_PATTERNS.get(term.lower(), [])
    for pat in patterns:
        if re.search(pat, line, re.IGNORECASE):
            return True
    return False


def _scan_file(path: Path, term_patterns: dict[str, re.Pattern]) -> list[dict]:
    """Return list of violation records for a single file."""
    violations = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return violations

    for lineno, line in enumerate(lines, 1):
        # Only scan comments and docstrings — skip executable code lines
        stripped = line.strip()
        is_comment = stripped.startswith("#")
        is_docstring_line = stripped.startswith('"""') or stripped.startswith("'''")
        is_in_string = '"""' in line or "'''" in line or stripped.startswith('"') or stripped.startswith("'")

        # We scan ALL lines but flag separately whether it is in code vs comment
        for term, pattern in term_patterns.items():
            if pattern.search(line):
                if _is_false_positive(term, line):
                    continue
                in_comment = is_comment or is_docstring_line or is_in_string
                violations.append({
                    "file": str(path),
                    "line": lineno,
                    "term": term,
                    "canonical": DEPRECATED_TERMS[term],
                    "context": line.rstrip(),
                    "in_comment": in_comment,
                })

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate lexicon usage in Python codebase")
    parser.add_argument("--path", default=None, help="Root path to scan (default: daemon root)")
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit 1 even if violations are only in comments/docstrings"
    )
    parser.add_argument(
        "--comments-only", action="store_true",
        help="Only report violations in comments/docstrings (skip code)"
    )
    args = parser.parse_args()

    # Resolve paths
    script_dir = Path(__file__).parent
    daemon_root = Path(args.path) if args.path else script_dir.parent
    lexicon_path = daemon_root / "config" / "lexicon.json"

    if not lexicon_path.exists():
        print(f"ERROR: lexicon.json not found at {lexicon_path}", file=sys.stderr)
        return 2

    # Load lexicon (for reference — violations are derived from DEPRECATED_TERMS)
    try:
        lexicon = _load_lexicon(lexicon_path)
    except Exception as exc:
        print(f"ERROR: Failed to parse lexicon.json: {exc}", file=sys.stderr)
        return 2

    # Compile patterns — word-boundary match, case-insensitive
    term_patterns: dict[str, re.Pattern] = {}
    for term in DEPRECATED_TERMS:
        term_patterns[term] = re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)

    # Scan
    all_violations: list[dict] = []
    files_scanned = 0
    for py_file in _iter_python_files(daemon_root):
        violations = _scan_file(py_file, term_patterns)
        all_violations.extend(violations)
        files_scanned += 1

    # Report
    print(f"Scanned {files_scanned} Python files under {daemon_root}")
    print(f"Lexicon version: {lexicon.get('version', 'unknown')}")
    print()

    if not all_violations:
        print("No deprecated term violations found.")
        return 0

    # Group by term
    by_term: dict[str, list[dict]] = {}
    for v in all_violations:
        by_term.setdefault(v["term"], []).append(v)

    code_violations = [v for v in all_violations if not v["in_comment"]]
    comment_violations = [v for v in all_violations if v["in_comment"]]

    print(f"Found {len(all_violations)} occurrence(s) of deprecated terms:")
    print(f"  - In code (variable names / live logic): {len(code_violations)}")
    print(f"  - In comments / docstrings: {len(comment_violations)}")
    print()

    for term, violations in sorted(by_term.items()):
        canonical = DEPRECATED_TERMS[term]
        print(f"  [{term}] -> use '{canonical}' instead ({len(violations)} occurrence(s))")
        for v in violations[:10]:
            location_type = "comment" if v["in_comment"] else "CODE"
            print(f"    {v['file']}:{v['line']} [{location_type}]")
            print(f"      {v['context'][:120]}")
        if len(violations) > 10:
            print(f"    ... and {len(violations) - 10} more")
        print()

    # Determine exit code
    if code_violations:
        print("ACTION REQUIRED: deprecated terms found in live code (not just comments).")
        return 1
    elif args.strict and comment_violations:
        print("ACTION REQUIRED (--strict): deprecated terms found in comments/docstrings.")
        return 1
    else:
        print("NOTE: deprecated terms found only in comments/docstrings.")
        print("Run with --strict to treat these as failures.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
