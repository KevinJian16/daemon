"""Tests for utils module."""

import logging
from my_project.utils import format_greeting, safe_get

def test_format_greeting() -> None:
    """Test format_greeting function."""
    assert format_greeting("World") == "Hello, World!"
    assert format_greeting("Alice", "Hi") == "Hi, Alice!"
    assert format_greeting("Bob", greeting="Greetings") == "Greetings, Bob!"

def test_safe_get_key_exists(caplog) -> None:
    """Test safe_get when key exists."""
    caplog.set_level(logging.WARNING)
    d = {"a": 1, "b": 2}
    assert safe_get(d, "a") == 1
    assert safe_get(d, "b", default=99) == 2
    assert len(caplog.records) == 0

def test_safe_get_key_missing(caplog) -> None:
    """Test safe_get when key missing."""
    caplog.set_level(logging.WARNING)
    d = {"a": 1}
    assert safe_get(d, "missing") is None
    assert len(caplog.records) == 1
    assert "Key 'missing' not found" in caplog.records[0].message
    
    # With custom default
    assert safe_get(d, "missing", default=42) == 42
    assert len(caplog.records) == 2