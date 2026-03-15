# Python Project Structure Best Practices (2025)

## Summary of Research

After researching current best practices for Python project structure in 2025, we've identified key trends and recommendations for modern Python development.

### Key Findings

1. **Tooling Shift**: `uv` has become the dominant tool for dependency management, virtual environments, and packaging, often replacing `pip`, `pip-tools`, `poetry`, and `pipenv`.
2. **Configuration Standardization**: `pyproject.toml` (PEP 621) is now the single source of truth for project metadata, dependencies, and tool configurations.
3. **Linting/Formatting Convergence**: `ruff` is nearly universally adopted for both linting and formatting, replacing `flake8`, `isort`, `black`, and others.
4. **Layout Preference**: The `src/` layout is recommended for packages and larger applications, while flat layout remains acceptable for simple scripts.
5. **Type Hints Maturity**: Static type checking with `mypy` or `ty` is considered essential for production code.
6. **Automation**: Pre-commit hooks and CI/CD (typically GitHub Actions) are standard practice.

### Recommended Project Structure

```
project_name/
├── .github/workflows/          # CI/CD pipelines
├── .devcontainer/              # Dev container config (optional)
├── docs/                       # Documentation (MkDocs recommended)
├── src/                        # Source code (src layout)
│   └── project_name/
│       ├── __init__.py
│       ├── __main__.py         # CLI entry point
│       ├── core.py             # Business logic
│       └── utils.py            # Utilities
├── tests/                      # Test suite
│   ├── __init__.py
│   ├── test_core.py
│   └── test_utils.py
├── .gitignore
├── .pre-commit-config.yaml     # Pre-commit hooks
├── LICENSE
├── Makefile                    # Common tasks (optional)
├── README.md
├── pyproject.toml              # Project configuration
└── uv.lock                     # Lock file (if using uv)
```

### Essential Configuration Files

#### `pyproject.toml` (Minimal Example)
```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "project-name"
version = "0.1.0"
description = "Project description"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
dependencies = [
    "click>=8.0.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = ["ruff", "mypy", "pytest", "pre-commit"]
docs = ["mkdocs", "mkdocs-material"]

[project.scripts]
project-name = "project_name.__main__:main"

[tool.ruff]
line-length = 88
select = ["E", "F", "I", "UP"]

[tool.mypy]
python_version = "3.12"
strict = true
```

#### `.pre-commit-config.yaml` (Essential Hooks)
```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks: [trailing-whitespace, end-of-file-fixer, check-yaml]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks: [ruff, ruff-format]
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks: [{id: mypy, additional_dependencies: [types-all]}]
```

### Modern Tooling Stack

| Category | Recommended Tool | Purpose |
|----------|------------------|---------|
| Dependency Management | `uv` | Fast, unified tool for venv, pip, packaging |
| Linting | `ruff` | Extremely fast Python linter |
| Formatting | `ruff format` | Built-in formatter in ruff |
| Type Checking | `mypy` or `ty` | Static type checking |
| Testing | `pytest` | Testing framework with rich ecosystem |
| Documentation | `mkdocs` with `mkdocs-material` | Modern documentation site |
| CI/CD | GitHub Actions | Automated testing and deployment |
| Packaging | `hatchling` via `pyproject.toml` | Modern build backend |

### Best Practices Checklist

- [ ] Use `src/` layout for packages and complex applications
- [ ] Centralize configuration in `pyproject.toml` (PEP 621)
- [ ] Define dependency groups (`dev`, `docs`, `test`) in `pyproject.toml`
- [ ] Include comprehensive type hints
- [ ] Set up pre-commit hooks for automated code quality checks
- [ ] Configure CI pipeline with GitHub Actions
- [ ] Write tests with `pytest` and aim for high coverage
- [ ] Document with `mkdocs` and maintain a useful README
- [ ] Use `uv` for dependency management and virtual environments
- [ ] Follow semantic versioning
- [ ] Include an open-source license

### Anti-patterns to Avoid

1. **Multiple configuration files**: Avoid `setup.py`, `setup.cfg`, `requirements.txt`, `MANIFEST.in` in favor of `pyproject.toml`
2. **Monolithic utility modules**: Split large `utils.py` files into logical modules
3. **Global state**: Prefer pure functions and dependency injection
4. **Untyped code**: Use type hints even for internal functions
5. **Manual quality checks**: Automate with pre-commit and CI
6. **Mixed concerns**: Separate I/O, business logic, and presentation layers

### Reference Implementation

We've created a complete reference example project at `python_project_structure_2025/` that demonstrates all these best practices, including:

- Full `src/` layout with example modules
- Comprehensive `pyproject.toml` with modern tool configurations
- Pre-commit hooks configuration
- GitHub Actions CI workflow
- Example tests with `pytest`
- Type hints throughout
- CLI entry point using `click`

### Next Steps

1. **Adopt these practices** in new Python projects
2. **Migrate existing projects** gradually to the modern tooling stack
3. **Contribute improvements** to the reference implementation
4. **Share knowledge** with team members about modern Python practices

### Resources

- [Real Python: Python Project Layout](https://realpython.com/python-project-structure/)
- [Hynek Schlawack: My 2025 uv-based Python Project Layout](https://youtu.be/mFyE9xgeKcA)
- [cookiecutter-uv template](https://github.com/fpgmaas/cookiecutter-uv)
- [Astral's uv documentation](https://docs.astral.sh/uv/)
- [Ruff documentation](https://docs.astral.sh/ruff/)

This research provides a foundation for consistent, maintainable Python projects in 2025 and beyond.