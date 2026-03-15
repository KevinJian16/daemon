# My Project

A modern Python project structured with best practices (2025).

## Features

- **src-layout**: Package code inside `src/` to avoid import confusion.
- **pyproject.toml**: Single configuration file for dependencies, build system, and tooling.
- **UV package manager**: Fast, PEP-compliant dependency management.
- **Ruff**: Extremely fast linting and formatting.
- **Pytest**: Testing framework with rich plugins.
- **Type checking**: Mypy configured for static type safety.
- **Pre-commit hooks**: Automate code quality checks before commits.
- **CI/CD**: GitHub Actions workflows for testing, linting, and publishing.

## Project Structure

```
my_project/
├── src/
│   └── my_project/
│       ├── __init__.py
│       ├── __main__.py
│       ├── core.py
│       └── utils.py
├── tests/
│   ├── __init__.py
│   ├── test_core.py
│   └── test_utils.py
├── docs/
│   └── index.md
├── scripts/
│   └── deploy.sh
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── publish.yml
├── .vscode/
│   └── settings.json
├── .gitignore
├── LICENSE
├── pyproject.toml
├── README.md
└── pre-commit-config.yaml
```

## Getting Started

### Prerequisites

- Python 3.12 or later
- [UV](https://github.com/astral-sh/uv) (recommended) or Poetry

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd my_project

# Install dependencies using UV
uv sync

# Or using Poetry
poetry install
```

### Development

```bash
# Activate virtual environment (UV)
source .venv/bin/activate

# Run tests
uv run pytest

# Lint and format
uv run ruff check .
uv run ruff format .

# Type check
uv run mypy src/
```

### Pre-commit Hooks

Install pre-commit hooks to automatically run checks before each commit:

```bash
uv run pre-commit install
```

## License

MIT