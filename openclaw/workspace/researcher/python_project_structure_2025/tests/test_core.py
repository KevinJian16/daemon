"""Tests for core module."""

from my_project.core import hello, add, Calculator

def test_hello() -> None:
    """Test hello function."""
    assert hello("World") == "Hello, World!"
    assert hello("Alice") == "Hello, Alice!"

def test_add() -> None:
    """Test add function."""
    assert add(1, 2) == 3
    assert add(1.5, 2.5) == 4.0
    assert add(-1, 1) == 0

def test_calculator_initial() -> None:
    """Test Calculator initialization."""
    calc = Calculator()
    assert calc.get_value() == 0
    
    calc2 = Calculator(10)
    assert calc2.get_value() == 10

def test_calculator_add() -> None:
    """Test Calculator add method."""
    calc = Calculator()
    calc.add(5)
    assert calc.get_value() == 5
    
    # Method chaining
    calc.add(3).add(2)
    assert calc.get_value() == 10

def test_calculator_subtract() -> None:
    """Test Calculator subtract method."""
    calc = Calculator(10)
    calc.subtract(3)
    assert calc.get_value() == 7
    
    calc.subtract(2).subtract(1)
    assert calc.get_value() == 4