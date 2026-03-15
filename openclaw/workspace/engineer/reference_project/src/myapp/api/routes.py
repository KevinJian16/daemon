"""API routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import get_settings, Settings

health_router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str


@health_router.get("", response_model=HealthResponse)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Check application health."""
    return HealthResponse(status="ok", version=settings.version)
