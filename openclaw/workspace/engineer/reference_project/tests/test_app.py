"""Tests for myapp."""

from myapp import create_app


def test_create_app() -> None:
    """Test app creation."""
    app = create_app()
    assert app.title == "MyApp"
    assert app.version == "0.1.0"
