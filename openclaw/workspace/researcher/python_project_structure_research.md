# Python Project Structure Best Practices (2025)

## Research Summary

Based on analysis of current authoritative sources (Real Python, Hitchhiker's Guide to Python, modern templates like cookiecutter-uv, and Hynek Schlawack's uv-based layout), here are the key best practices for Python project structure in 2025.

### Core Principles

1. **Clear top-level structure**: Root directory should contain critical configuration and metadata files (`pyproject.toml`, `README.md`, `LICENSE`, `.gitignore`).
2. **Separate source code from configuration**: Use either `src/` layout (preferred for packages) or flat layout (simpler for applications).
3. **Dedicated test directory**: Keep tests in `tests/` mirroring source structure.
4. **Proper packaging**: Even applications should be packaged as proper Python packages with `pyproject.toml`.
5. **Modern tooling**: Use `uv` for dependency management, `ruff` for linting, `pytest` for testing.

### Layout Patterns

#### 1. src/ Layout (Recommended for libraries and complex applications)

```
project_name/
├── .github/                    # GitHub Actions workflows
│   └── workflows/
├── .devcontainer/              # VSCode devcontainer config (optional)
├── docs/                       # Documentation (optional)
├── src/                        # Source code
│   └── project_name/
│       ├── __init__.py
│       ├── __main__.py         # CLI entry point
│       ├── core.py
│       └── utils.py
├── tests/                      # Test suite
│   ├── __init__.py
│   ├── test_core.py
│   └── test_utils.py
├── .gitignore
├── .pre-commit-config.yaml     # Pre-commit hooks
├── LICENSE
├── Makefile                    # Common tasks (optional)
├── README.md
├── pyproject.toml              # Project configuration (PEP 621)
└── uv.lock                     # Lock file (if using uv)
```

**Advantages**:
- Clear separation between source and other files
- Prevents accidental imports from local directory
- Encourages proper packaging
- Works well with modern tooling

#### 2. Flat Layout (Simpler for small applications/scripts)

```
project_name/
├── project_name/               # Package at root
│   ├── __init__.py
│   ├── __main__.py
│   ├── core.py
│   └── utils.py
├── tests/
│   ├── __init__.py
│   └── test_core.py
├── pyproject.toml
├── README.md
└── LICENSE
```

### Essential Files

#### `pyproject.toml` (PEP 621)
Central configuration file replacing `setup.py`, `setup.cfg`, `requirements.txt`. Should include:
- Project metadata (name, version, authors)
- Build system (`[build-system]`)
- Dependencies (`[project]` or `[tool.uv]`)
- Tool configurations (ruff, mypy, pytest, etc.)

Example minimal `pyproject.toml`:
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "project-name"
version = "0.1.0"
description = "My project description"
authors = [{name = "Your Name", email = "you@example.com"}]
license = {text = "MIT"}
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "click>=8.0.0",
    "pydantic>=2.0.0",
]
```

#### `README.md`
Should include:
- Project description
- Installation instructions
- Basic usage examples
- Contributing guidelines (or link to CONTRIBUTING.md)
- License information

#### `LICENSE`
Always include an open-source license. MIT and Apache 2.0 are common choices.

#### `.gitignore`
Python-specific ignores plus editor/IDE files.

### Modern Tooling Recommendations

1. **Dependency Management**: `uv` (fast, unified tool for venv, pip, pip-tools, packaging)
2. **Linting & Formatting**: `ruff` (extremely fast, replaces flake8, isort, black)
3. **Type Checking**: `mypy` or `ty` (Astral's type checker)
4. **Testing**: `pytest` with `pytest-cov`
5. **Pre-commit Hooks**: `pre-commit` with hooks for ruff, mypy, etc.
6. **CI/CD**: GitHub Actions with caching for uv
7. **Documentation**: `mkdocs` with `mkdocs-material`
8. **Packaging**: `hatchling` or `setuptools` via `pyproject.toml`

### Dependency Groups (Modern Practice)

Use dependency groups for separation:
```toml
[tool.uv]
# Main dependencies are in [project]
# Additional groups:
dev = [
    "pytest>=7.0.0",
    "ruff>=0.4.0",
    "mypy>=1.8.0",
]
docs = [
    "mkdocs>=1.5.0",
    "mkdocs-material>=9.0.0",
]
```

Install with: `uv sync --group dev --group docs`

### Testing Strategy

- Keep tests in `tests/` directory
- Mirror source structure for easy navigation
- Use `pytest` fixtures and parameterization
- Aim for high test coverage
- Include integration tests if applicable

### Documentation

- Use `docs/` directory for user documentation
- Consider auto-generated API docs with `mkdocstrings`
- Keep README concise with links to full docs

### Containerization (Optional)

- Use multi-stage Docker builds
- Leverage `uv` for fast dependency installation
- Separate dependency and application layers for caching

### Project Initialization Templates

Modern templates to bootstrap projects:
- `cookiecutter-uv` (feature-rich, supports src/flat layout)
- `ultraviolet` (opinionated uv template)
- `python-project-template` by Aditya Ghadge

### Key Trends for 2025

1. **Move away from `requirements.txt`**: Use `pyproject.toml` with dependency groups
2. **Adoption of `uv`**: Fast becoming the standard Python workflow tool
3. **src layout preference**: Growing consensus for proper packaging
4. **Ruff dominance**: Almost universal adoption for linting/formatting
5. **Type hints maturity**: Widespread use, with `mypy` or `ty` in CI
6. **Pre-commit automation**: Standard practice for code quality
7. **GitHub Actions**: Default CI for open-source projects

### Anti-patterns to Avoid

1. **Monolithic `utils.py` files**: Split into logical modules
2. **Circular dependencies**: Use dependency injection or refactor
3. **Global state**: Prefer pure functions and explicit dependencies
4. **No tests or poor test structure**: Start with testing from day one
5. **Mixed concerns in modules**: Separate I/O, business logic, and presentation layers
6. **Ignoring type hints**: Even gradual typing improves maintainability

## Conclusion

A well-structured Python project in 2025 should:
- Use `src/` layout for packages, flat layout for simple apps
- Centralize configuration in `pyproject.toml`
- Leverage modern tools (`uv`, `ruff`, `pytest`)
- Include comprehensive testing from the start
- Maintain clear separation of concerns
- Automate quality checks with pre-commit and CI
- Provide clear documentation

This approach ensures maintainability, scalability, and ease of collaboration.