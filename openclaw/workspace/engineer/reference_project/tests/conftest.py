"""Pytest configuration."""

import pytest


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """Set async backend for pytest-asyncio."""
    return "asyncio"
