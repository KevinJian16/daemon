"""Minimal .env loader used by daemon runtime entrypoints.

We avoid third-party dotenv dependency to keep bootstrap lightweight.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_daemon_env(home: Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Load KEY=VALUE pairs from `<home>/.env` into os.environ.

    Returns a mapping of keys loaded into environment.
    """
    base = home or Path(os.environ.get("DAEMON_HOME", Path(__file__).resolve().parent))
    env_path = base / ".env"
    loaded: dict[str, str] = {}
    if not env_path.exists():
        return loaded

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        k = key.strip()
        if not k:
            continue
        v = value.strip()
        if v and ((v[0] == v[-1] == '"') or (v[0] == v[-1] == "'")):
            v = v[1:-1]
        if override or k not in os.environ:
            os.environ[k] = v
            loaded[k] = v
    return loaded


__all__ = ["load_daemon_env"]
