"""PsycheConfig — TOML-based preferences and rations (replaces InstinctPsyche SQLite)."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

try:
    import tomli_w
except ImportError:
    tomli_w = None  # type: ignore[assignment]


def _read_toml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse %s: %s — using defaults", path, exc)
        return {}


def _write_toml(path: Path, data: dict) -> None:
    if tomli_w is not None:
        path.write_bytes(tomli_w.dumps(data))
    else:
        # Minimal fallback: dump as simple key=value TOML.
        lines: list[str] = []
        for section, values in data.items():
            if isinstance(values, dict):
                lines.append(f"[{section}]")
                for k, v in values.items():
                    lines.append(f"{k} = {_toml_value(v)}")
                lines.append("")
            else:
                lines.append(f"{section} = {_toml_value(values)}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(v)
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, list):
        inner = ", ".join(_toml_value(x) for x in v)
        return f"[{inner}]"
    return f'"{v}"'


# ── Bootstrap defaults ────────────────────────────────────────────────────────

_DEFAULT_PREFS = {
    "general": {
        "default_depth": "study",
        "default_format": "markdown",
        "output_languages": ["zh", "en"],
        "require_bilingual": True,
        "telegram_enabled": True,
        "pdf_enabled": True,
    },
    "execution": {
        "retinue_size_n": 7,
        "deed_ration_ratio": 0.75,
    },
    "routing": {
        "research_default_sources": ["brave", "semantic_scholar"],
        "code_default_sources": ["github"],
    },
}

_DEFAULT_RATIONS = {
    "daily_limits": {
        "minimax_tokens": 20_000_000,
        "qwen_tokens": 10_000_000,
        "zhipu_tokens": 5_000_000,
        "deepseek_tokens": 5_000_000,
        "concurrent_deeds": 10,
    },
    "current_usage": {},
}


class PsycheConfig:
    """Read/write preferences.toml and rations.toml. Replaces InstinctPsyche."""

    def __init__(self, psyche_dir: Path) -> None:
        self._psyche_dir = psyche_dir
        self._prefs_path = psyche_dir / "preferences.toml"
        self._rations_path = psyche_dir / "rations.toml"
        self._psyche_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        if not self._prefs_path.exists():
            _write_toml(self._prefs_path, _DEFAULT_PREFS)
        if not self._rations_path.exists():
            _write_toml(self._rations_path, _DEFAULT_RATIONS)

    # ── Preferences ───────────────────────────────────────────────────────────

    def get_pref(self, key: str, default: str = "") -> str:
        """Get a preference value by dotted or flat key. Returns string."""
        data = _read_toml(self._prefs_path)
        val = self._deep_get(data, key)
        if val is None:
            return default
        return str(val)

    def set_pref(self, key: str, value: str, **_kwargs: Any) -> None:
        """Set a preference. Accepts source/changed_by kwargs for compat but ignores them."""
        data = _read_toml(self._prefs_path)
        self._deep_set(data, key, value)
        _write_toml(self._prefs_path, data)

    def all_prefs(self) -> dict[str, str]:
        """Return flat dict of all preferences."""
        data = _read_toml(self._prefs_path)
        return self._flatten(data)

    # ── Rations ───────────────────────────────────────────────────────────────

    def get_ration(self, resource_type: str) -> dict | None:
        data = _read_toml(self._rations_path)
        limits = data.get("daily_limits", {})
        usage = data.get("current_usage", {})
        if resource_type not in limits:
            return None
        return {
            "resource_type": resource_type,
            "daily_limit": limits[resource_type],
            "current_usage": usage.get(resource_type, 0),
            "reset_utc": data.get("reset_utc", ""),
        }

    def consume_ration(self, resource_type: str, amount: float) -> bool:
        """Check and deduct usage. Returns False if exceeds limit."""
        data = _read_toml(self._rations_path)
        limits = data.get("daily_limits", {})
        if resource_type not in limits:
            return True  # Unknown resource, don't block
        usage = data.setdefault("current_usage", {})
        current = float(usage.get(resource_type, 0))
        limit = float(limits[resource_type])
        if current + amount > limit:
            return False
        usage[resource_type] = current + amount
        _write_toml(self._rations_path, data)
        return True

    def reset_rations(self) -> None:
        data = _read_toml(self._rations_path)
        data["current_usage"] = {}
        tomorrow = time.strftime(
            "%Y-%m-%dT00:00:00Z",
            time.gmtime(time.time() + 86400),
        )
        data["reset_utc"] = tomorrow
        _write_toml(self._rations_path, data)

    def all_rations(self) -> list[dict]:
        data = _read_toml(self._rations_path)
        limits = data.get("daily_limits", {})
        usage = data.get("current_usage", {})
        return [
            {
                "resource_type": k,
                "daily_limit": v,
                "current_usage": usage.get(k, 0),
                "reset_utc": data.get("reset_utc", ""),
            }
            for k, v in limits.items()
        ]

    def set_ration(self, resource_type: str, daily_limit: float, **_kwargs: Any) -> None:
        data = _read_toml(self._rations_path)
        data.setdefault("daily_limits", {})[resource_type] = daily_limit
        _write_toml(self._rations_path, data)

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        return {
            "preferences": _read_toml(self._prefs_path),
            "rations": _read_toml(self._rations_path),
            "exported_utc": _utc(),
        }

    def stats(self) -> dict:
        prefs = _read_toml(self._prefs_path)
        rations = _read_toml(self._rations_path)
        return {
            "preference_count": sum(len(v) if isinstance(v, dict) else 1 for v in prefs.values()),
            "ration_count": len(rations.get("daily_limits", {})),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _deep_get(data: dict, key: str) -> Any:
        """Get value by dotted key (e.g. 'general.default_depth') or flat key."""
        # Try flat first (compat with old InstinctPsyche keys like 'eval_window_hours')
        if key in data:
            return data[key]
        # Try dotted path
        parts = key.split(".")
        current: Any = data
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                # Try flat search across all sections
                for section_val in data.values():
                    if isinstance(section_val, dict) and key in section_val:
                        return section_val[key]
                return None
        return current

    @staticmethod
    def _deep_set(data: dict, key: str, value: Any) -> None:
        """Set value by dotted key or flat key."""
        if "." in key:
            parts = key.split(".")
            current = data
            for part in parts[:-1]:
                current = current.setdefault(part, {})
            current[parts[-1]] = value
            return
        # Flat key: search across sections first
        for section_val in data.values():
            if isinstance(section_val, dict) and key in section_val:
                section_val[key] = value
                return
        # Not found in any section, put at top level
        data[key] = value

    @staticmethod
    def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
        """Flatten nested dict to {key: str_value}."""
        out: dict[str, str] = {}
        for k, v in data.items():
            full_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                out.update(PsycheConfig._flatten(v, full_key))
            else:
                out[full_key] = str(v)
        return out
