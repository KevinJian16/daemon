"""Managed storage path helpers for Vault and Offering roots."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _default_base() -> Path:
    return Path.home() / "My Drive" / "daemon"


def default_storage_roots() -> dict[str, str]:
    base = _default_base()
    return {
        "vault_root": str(base / "vault"),
        "offering_root": str(base / "offerings"),
    }


def load_storage_roots(state_dir: Path) -> dict[str, str]:
    path = state_dir / "managed_storage.json"
    defaults = default_storage_roots()
    if not path.exists():
        return defaults
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    if not isinstance(payload, dict):
        return defaults

    legacy_name = str(payload.get("daemon_dir_name") or "").strip()
    if legacy_name and not payload.get("vault_root") and not payload.get("offering_root"):
        base = Path.home() / "My Drive" / legacy_name
        return {
            "vault_root": str(base / "vault"),
            "offering_root": str(base / "offerings"),
        }

    vault_root = str(payload.get("vault_root") or defaults["vault_root"]).strip()
    offering_root = str(payload.get("offering_root") or defaults["offering_root"]).strip()
    return {
        "vault_root": vault_root or defaults["vault_root"],
        "offering_root": offering_root or defaults["offering_root"],
    }


def save_storage_roots(state_dir: Path, *, vault_root: str, offering_root: str, updated_utc: str) -> dict[str, str]:
    payload = {
        "vault_root": str(vault_root).strip(),
        "offering_root": str(offering_root).strip(),
        "updated_utc": str(updated_utc).strip(),
    }
    path = state_dir / "managed_storage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def resolve_vault_root(state_dir: Path) -> Path:
    root = Path(load_storage_roots(state_dir)["vault_root"]).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_offering_root(state_dir: Path) -> Path:
    root = Path(load_storage_roots(state_dir)["offering_root"]).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    return root


def storage_status(state_dir: Path) -> dict[str, Any]:
    roots = load_storage_roots(state_dir)
    vault_root = Path(roots["vault_root"]).expanduser()
    offering_root = Path(roots["offering_root"]).expanduser()
    return {
        "vault_root": str(vault_root),
        "offering_root": str(offering_root),
        "vault_ready": vault_root.exists(),
        "offering_ready": offering_root.exists(),
        "ready": vault_root.exists() and offering_root.exists(),
    }
