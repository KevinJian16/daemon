"""API module."""

from fastapi import FastAPI

from .routes import health_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="MyApp",
        description="A modern Python application",
        version="0.1.0",
    )

    app.include_router(health_router)

    return app
