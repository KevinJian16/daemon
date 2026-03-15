"""Service package exports with lazy import to avoid heavy optional deps at import time."""

from __future__ import annotations

__all__ = ["create_app"]


def __getattr__(name: str):
    if name == "create_app":
        from .api import create_app

        return create_app
    raise AttributeError(name)
