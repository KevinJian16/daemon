# Python Project Structure Best Practices (2025)

## Research Summary

After researching current best practices for Python project structure in 2025, here are the key findings:

### 1. Project Layout: **src Layout** (Recommended for Libraries/Packages)

**src layout** is now the recommended approach because:
- Enforces proper imports - only installed packages are importable
- Clean separation between package code and project metadata
- Works seamlessly with editable installs (`pip install -e .`)
- Industry standard for distributable packages

```
project/
├── src/
│   └── my_package/
│       ├── __init__.py
│       ├── core/
│       ├── cli/
│       └── utils/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── docs/
├── scripts/
├── pyproject.toml
├── README.md
├── .gitignore
└── LICENSE
```

### 2. Configuration: **pyproject.toml** (PEP 621)

- Standard configuration file for Python projects (replaces setup.py, setup.cfg)
- Supports all build backends: hatchling, setuptools, flit
- Tool configuration (pytest, ruff, mypy, etc.)

### 3. Modern Build Tools (2025)

| Tool | Status | Notes |
|------|--------|-------|
| **Hatch** | Active | PyPA official, fast |
| **PDM** | Active | npm-like feel, standards-based |
| **Poetry** | Active | Mature, rich features (v2.0 supports pyproject.toml) |
| **uv** | Rising | Fast, Rust-based |

### 4. Key Best Practices

1. **Use `src/` layout** for packages/libraries
2. **Flat layout** is okay for simple scripts/applications
3. **Always have `pyproject.toml`** - it's the modern standard
4. **Include type hints** - use mypy for type checking
5. **Use ruff** - fastest Python linter (replaces flake8, isort, etc.)
6. **Structure tests** - unit/, integration/, e2e/ subdirectories

### 5. Example pyproject.toml

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "my-package"
version = "0.1.0"
requires-python = ">=3.9"

[tool.hatch.build.targets.wheel]
packages = ["src/my_package"]

[tool.ruff]
line-length = 100
```

---

## Reference Implementation

Created a reference project at: `reference-python-project/`

This can serve as a template for new Python projects following 2025 best practices.

---
*Researched: 2026-03-15*
