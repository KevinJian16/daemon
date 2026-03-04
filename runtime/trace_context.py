"""Runtime trace context shared across Tracer/Cortex for per-trace attribution."""
from __future__ import annotations

from contextvars import ContextVar, Token

_TRACE_ID: ContextVar[str] = ContextVar("daemon_trace_id", default="")
_TRACE_ROUTINE: ContextVar[str] = ContextVar("daemon_trace_routine", default="")


def set_current_trace(trace_id: str, routine: str = "") -> tuple[Token, Token]:
    """Bind current trace metadata to context."""
    token_id = _TRACE_ID.set(trace_id or "")
    token_routine = _TRACE_ROUTINE.set(routine or "")
    return token_id, token_routine


def reset_current_trace(tokens: tuple[Token, Token] | None) -> None:
    """Reset trace context previously returned by set_current_trace()."""
    if not tokens:
        return
    token_id, token_routine = tokens
    _TRACE_ID.reset(token_id)
    _TRACE_ROUTINE.reset(token_routine)


def current_trace() -> dict[str, str]:
    """Return currently bound trace context, empty values if none."""
    return {"trace_id": _TRACE_ID.get(""), "routine": _TRACE_ROUTINE.get("")}
