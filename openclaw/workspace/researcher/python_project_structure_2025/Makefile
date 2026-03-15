.PHONY: help install dev test lint format type-check check clean

help:
	@echo "Available commands:"
	@echo "  install   : Install production dependencies"
	@echo "  dev       : Install development dependencies"
	@echo "  test      : Run tests"
	@echo "  lint      : Run ruff linting"
	@echo "  format    : Run ruff formatting"
	@echo "  type-check: Run mypy type checking"
	@echo "  check     : Run lint, format, type-check, and tests"
	@echo "  clean     : Remove build artifacts and caches"

install:
	uv sync

dev:
	uv sync --group dev --group docs

test:
	uv run pytest -v --cov=src --cov-report=term-missing

lint:
	uv run ruff check .

format:
	uv run ruff format .

type-check:
	uv run mypy src/

check: lint format type-check test

clean:
	rm -rf .coverage coverage.xml .pytest_cache .mypy_cache
	rm -rf build dist *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete