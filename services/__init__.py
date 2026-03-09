"""Service package exports with lazy import to avoid heavy optional deps at import time."""

from __future__ import annotations

__all__ = ["create_app", "Cadence", "Will", "HeraldService", "VoiceService"]


def __getattr__(name: str):
    if name == "create_app":
        from .api import create_app

        return create_app
    if name == "Cadence":
        from .cadence import Cadence

        return Cadence
    if name == "Will":
        from .will import Will

        return Will
    if name == "HeraldService":
        from .herald import HeraldService

        return HeraldService
    if name == "VoiceService":
        from .voice import VoiceService

        return VoiceService
    raise AttributeError(name)
