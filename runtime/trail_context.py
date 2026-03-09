"""Runtime trail context shared across Trail/Cortex for per-trail attribution."""
from __future__ import annotations

from contextvars import ContextVar, Token

_TRAIL_ID: ContextVar[str] = ContextVar("daemon_trail_id", default="")
_TRAIL_ROUTINE: ContextVar[str] = ContextVar("daemon_trail_routine", default="")


def set_current_trail(trail_id: str, routine: str = "") -> tuple[Token, Token]:
    """Bind current trail metadata to context."""
    token_id = _TRAIL_ID.set(trail_id or "")
    token_routine = _TRAIL_ROUTINE.set(routine or "")
    return token_id, token_routine


def reset_current_trail(tokens: tuple[Token, Token] | None) -> None:
    """Reset trail context previously returned by set_current_trail()."""
    if not tokens:
        return
    token_id, token_routine = tokens
    _TRAIL_ID.reset(token_id)
    _TRAIL_ROUTINE.reset(token_routine)


def current_trail() -> dict[str, str]:
    """Return currently bound trail context, empty values if none."""
    return {"trail_id": _TRAIL_ID.get(""), "routine": _TRAIL_ROUTINE.get("")}


# Backward compatibility aliases
set_current_trace = set_current_trail
reset_current_trace = reset_current_trail
current_trace = current_trail
