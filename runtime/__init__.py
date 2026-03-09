"""Runtime package exports with lazy imports.

Avoid importing heavy optional dependencies (for example `httpx`) at package import
time, so utility commands like state reset can run with minimal environment.
"""

from __future__ import annotations

__all__ = ["Cortex", "OpenClawAdapter", "Ether", "TemporalClient"]


def __getattr__(name: str):
    if name == "Cortex":
        from .cortex import Cortex

        return Cortex
    if name == "OpenClawAdapter":
        from .openclaw import OpenClawAdapter

        return OpenClawAdapter
    if name == "Ether":
        from .ether import Ether

        return Ether
    if name == "TemporalClient":
        from .temporal import TemporalClient

        return TemporalClient
    raise AttributeError(name)
