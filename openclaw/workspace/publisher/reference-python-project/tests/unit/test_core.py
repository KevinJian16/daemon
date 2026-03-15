"""Unit tests for core module."""
from my_package.core import process


def test_process():
    """Test the process function."""
    assert process("hello") == "HELLO"
    assert process("world") == "WORLD"
    assert process("") == ""
