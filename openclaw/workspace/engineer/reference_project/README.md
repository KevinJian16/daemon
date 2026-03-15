# MyApp

A modern Python application.

## Features

- FastAPI-based API
- Pydantic for data validation
- Type hints throughout
- pytest for testing

## Installation

```bash
pip install -e ".[dev]"
```

## Development

```bash
# Run tests
pytest

# Run linter
ruff check src/

# Type checking
mypy src/
```

## Usage

```bash
# Run the server
uvicorn myapp.api:create_app --factory
```
