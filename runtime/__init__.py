"""Runtime package exports with lazy imports.

Avoid importing heavy optional dependencies (for example `httpx`) at package import
time, so utility commands like state reset can run with minimal environment.
"""

from __future__ import annotations

__all__ = ["OpenClawAdapter", "TemporalClient", "MCPDispatcher"]


def __getattr__(name: str):
    if name == "OpenClawAdapter":
        from .openclaw import OpenClawAdapter

        return OpenClawAdapter
    if name == "TemporalClient":
        from .temporal import TemporalClient

        return TemporalClient
    if name == "MCPDispatcher":
        from .mcp_dispatch import MCPDispatcher

        return MCPDispatcher
    raise AttributeError(name)
