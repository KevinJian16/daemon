"""Message washing — mechanical extraction at run boundaries.

Triggered when a new Deed run starts for a Slip that already has previous Deeds.
Extracts conversation content from the previous evaluation segment and distributes:
  - Brief supplement (compressed conversation → injected into next run)
  - Ledger stats (rework count, message count, duration)
  - Voice candidates (keyword-matched style patterns, pending user confirmation)

No LLM involved — pure mechanical extraction.
"""
from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def wash_at_run_boundary(
    *,
    slip_id: str,
    new_deed_id: str,
    previous_deed_ids: list[str],
    load_messages_fn: "callable",
    ledger: Any,
    state_dir: Path,
) -> dict:
    """Extract and distribute conversation content from the previous evaluation segment.

    Returns a wash result dict with brief_supplement and stats.
    """
    if not previous_deed_ids:
        return {"washed": False, "reason": "no_previous_deeds"}

    # Collect messages from the most recent previous deed (= the last evaluation segment)
    prev_deed_id = previous_deed_ids[0]  # most recent
    try:
        messages = load_messages_fn(prev_deed_id, 500)
    except Exception as exc:
        logger.warning("Wash: failed to load messages for deed %s: %s", prev_deed_id, exc)
        return {"washed": False, "reason": f"load_failed:{str(exc)[:100]}"}

    if not messages:
        return {"washed": False, "reason": "no_messages"}

    # --- Extract ---
    user_messages = [m for m in messages if isinstance(m, dict) and str(m.get("role") or "") == "user"]
    system_ops = [m for m in messages if isinstance(m, dict) and str(m.get("event") or "") == "operation"]
    all_content = [m for m in messages if isinstance(m, dict)]

    # 1. Brief supplement: compress user conversation into a summary
    brief_supplement = _compress_conversation(user_messages, system_ops)

    # 2. Ledger stats
    stats = _extract_stats(all_content, prev_deed_id)

    # 3. Voice candidates (keyword matching for style patterns)
    voice_candidates = _extract_voice_candidates(user_messages)

    # --- Distribute ---
    wash_result = {
        "washed": True,
        "slip_id": slip_id,
        "source_deed_id": prev_deed_id,
        "target_deed_id": new_deed_id,
        "brief_supplement": brief_supplement,
        "stats": stats,
        "voice_candidates": voice_candidates,
        "washed_utc": _utc(),
    }

    # Persist wash result
    _persist_wash(state_dir, wash_result)

    # Update ledger stats
    try:
        ledger.append_jsonl(
            state_dir / "telemetry" / "wash_log.jsonl",
            {
                "slip_id": slip_id,
                "source_deed_id": prev_deed_id,
                "target_deed_id": new_deed_id,
                "message_count": stats["message_count"],
                "user_message_count": stats["user_message_count"],
                "operation_count": stats["operation_count"],
                "washed_utc": _utc(),
            },
        )
    except Exception as exc:
        logger.warning("Wash: failed to log stats: %s", exc)

    return wash_result


def _compress_conversation(user_messages: list[dict], system_ops: list[dict]) -> str:
    """Mechanically compress user messages + operation records into a brief supplement.

    No LLM — just concatenation with deduplication and truncation.
    """
    seen: set[str] = set()
    parts: list[str] = []
    max_total = 1200  # token-budget-friendly

    # Interleave user messages and operations by time
    combined = sorted(
        [*user_messages, *system_ops],
        key=lambda m: str(m.get("created_utc") or ""),
    )

    for msg in combined:
        content = str(msg.get("content") or "").strip()
        if not content or content in seen:
            continue
        seen.add(content)
        # Truncate individual messages
        if len(content) > 200:
            content = content[:200] + "..."
        parts.append(content)

    text = "\n".join(parts)
    if len(text) > max_total:
        text = text[:max_total] + "\n..."
    return text


def _extract_stats(messages: list[dict], deed_id: str) -> dict:
    """Extract objective statistics from the conversation."""
    user_count = 0
    system_count = 0
    operation_count = 0
    first_ts = ""
    last_ts = ""

    for msg in messages:
        ts = str(msg.get("created_utc") or "")
        if ts:
            if not first_ts or ts < first_ts:
                first_ts = ts
            if not last_ts or ts > last_ts:
                last_ts = ts
        role = str(msg.get("role") or "")
        event = str(msg.get("event") or "")
        if role == "user":
            user_count += 1
        elif role == "system":
            system_count += 1
        if event == "operation":
            operation_count += 1

    return {
        "deed_id": deed_id,
        "message_count": len(messages),
        "user_message_count": user_count,
        "system_message_count": system_count,
        "operation_count": operation_count,
        "first_message_utc": first_ts,
        "last_message_utc": last_ts,
    }


def _extract_voice_candidates(user_messages: list[dict]) -> list[dict]:
    """Keyword-match user messages for style/preference patterns.

    Returns candidates that need user confirmation before being written to Voice.
    """
    candidates: list[dict] = []
    style_patterns = [
        (r"(?:风格|语气|tone|style).*(?:要|用|像|偏)", "style_preference"),
        (r"(?:不要|别|不用|不需要).*(?:太|过于|非常)", "negative_preference"),
        (r"(?:简洁|详细|正式|口语|学术|专业)", "formality_preference"),
    ]

    for msg in user_messages:
        content = str(msg.get("content") or "").strip()
        if len(content) < 4:
            continue
        for pattern, category in style_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                candidates.append({
                    "text": content[:200],
                    "category": category,
                    "source_utc": str(msg.get("created_utc") or ""),
                    "confirmed": False,
                })
                break  # one match per message

    return candidates[:5]  # cap at 5 candidates per wash


def _persist_wash(state_dir: Path, result: dict) -> None:
    """Write wash result to disk for the target deed to pick up."""
    wash_dir = state_dir / "wash"
    wash_dir.mkdir(parents=True, exist_ok=True)
    target = str(result.get("target_deed_id") or "")
    if target:
        path = wash_dir / f"{target}.json"
        try:
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Wash: failed to persist wash result: %s", exc)


def load_wash_supplement(state_dir: Path, deed_id: str) -> str:
    """Load the brief supplement from a previous wash, if available."""
    path = state_dir / "wash" / f"{deed_id}.json"
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("brief_supplement") or "")
    except Exception:
        return ""
