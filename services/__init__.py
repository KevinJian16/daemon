"""Service package exports with lazy import to avoid heavy optional deps at import time."""

from __future__ import annotations

__all__ = ["create_app", "Scheduler", "Dispatch", "DeliveryService", "DialogService"]


def __getattr__(name: str):
    if name == "create_app":
        from .api import create_app

        return create_app
    if name == "Scheduler":
        from .scheduler import Scheduler

        return Scheduler
    if name == "Dispatch":
        from .dispatch import Dispatch

        return Dispatch
    if name == "DeliveryService":
        from .delivery import DeliveryService

        return DeliveryService
    if name == "DialogService":
        from .dialog import DialogService

        return DialogService
    raise AttributeError(name)
