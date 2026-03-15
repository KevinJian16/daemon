"""
Core module containing business logic.
"""

from typing import Union

def hello(name: str) -> str:
    """Return a greeting string."""
    return f"Hello, {name}!"

def add(a: Union[int, float], b: Union[int, float]) -> Union[int, float]:
    """Add two numbers."""
    return a + b

class Calculator:
    """Simple calculator class."""

    def __init__(self, initial: Union[int, float] = 0):
        self.value = initial

    def add(self, x: Union[int, float]) -> "Calculator":
        """Add x to the current value."""
        self.value += x
        return self

    def subtract(self, x: Union[int, float]) -> "Calculator":
        """Subtract x from the current value."""
        self.value -= x
        return self

    def get_value(self) -> Union[int, float]:
        """Return the current value."""
        return self.value