"""Managed local Google Drive storage paths for daemon archive/outcome."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

DEFAULT_DAEMON_DIR = "daemon"


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _safe_name(raw: str, default: str = DEFAULT_DAEMON_DIR) -> str:
    value = str(raw or "").strip()
    if not value:
        return default
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return cleaned or default


class DriveAccountRegistry:
    """Single-source managed storage rooted at My Drive/<daemon_dir>/."""

    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.base_dir = state_dir / "integrations" / "drive"
        self.settings_path = self.base_dir / "settings.json"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if not self.settings_path.exists():
            self._save_settings({})
        self.ensure_managed_structure()

    # ── Public API ─────────────────────────────────────────────────────────

    def integration_status(self) -> dict[str, Any]:
        settings = self._load_settings()
        return {
            "ok": bool(settings.get("ready")),
            "ready": bool(settings.get("ready")),
            "error": str(settings.get("error") or ""),
            "daemon_dir_name": str(settings.get("daemon_dir_name") or DEFAULT_DAEMON_DIR),
            "my_drive_root": str(settings.get("my_drive_root") or ""),
            "daemon_root": str(settings.get("daemon_root") or ""),
            "archive_root": str(settings.get("archive_root") or ""),
            "outcome_root": str(settings.get("outcome_root") or ""),
            "updated_utc": str(settings.get("updated_utc") or ""),
        }

    def set_daemon_dir_name(self, name: str) -> dict[str, Any]:
        settings = self._load_settings()
        settings["daemon_dir_name"] = _safe_name(name, default=DEFAULT_DAEMON_DIR)
        self._save_settings(settings)
        self.ensure_managed_structure()
        return self.integration_status()

    def ensure_managed_structure(self) -> dict[str, Any]:
        settings = self._load_settings()
        daemon_dir = _safe_name(str(settings.get("daemon_dir_name") or ""), default=DEFAULT_DAEMON_DIR)

        root = self._resolve_my_drive_root(settings)
        if not root:
            settings["ready"] = False
            settings["error"] = "my_drive_root_not_found_or_not_writable"
            settings["daemon_dir_name"] = daemon_dir
            settings["updated_utc"] = _utc()
            self._save_settings(settings)
            return self.integration_status()

        daemon_root = root / daemon_dir
        archive_root = daemon_root / "archive"
        outcome_root = daemon_root / "outcomes"
        archive_root.mkdir(parents=True, exist_ok=True)
        outcome_root.mkdir(parents=True, exist_ok=True)

        settings.update(
            {
                "ready": True,
                "error": "",
                "daemon_dir_name": daemon_dir,
                "my_drive_root": str(root),
                "daemon_root": str(daemon_root),
                "archive_root": str(archive_root),
                "outcome_root": str(outcome_root),
                "updated_utc": _utc(),
            }
        )
        self._save_settings(settings)
        return self.integration_status()

    def resolve_upload_target(self) -> dict[str, Any]:
        status = self.ensure_managed_structure()
        if not status.get("ready"):
            return {"ok": False, "error": str(status.get("error") or "drive_storage_unavailable")}
        return {
            "ok": True,
            "source": "local_sync",
            "archive_root": str(status.get("archive_root") or ""),
        }

    def resolve_outcome_root(self) -> dict[str, Any]:
        status = self.ensure_managed_structure()
        if not status.get("ready"):
            return {"ok": False, "error": str(status.get("error") or "drive_storage_unavailable")}
        return {
            "ok": True,
            "source": "local_sync",
            "outcome_root": str(status.get("outcome_root") or ""),
        }

    def list_files(self, kind: str, subpath: str = "", limit: int = 200) -> dict[str, Any]:
        root = self._kind_root(kind)
        if not root:
            return {"ok": False, "error": "invalid_kind"}
        if not root.exists():
            return {"ok": True, "kind": kind, "root": str(root), "items": []}
        target = root / str(subpath or "").strip()
        try:
            target = target.resolve()
            root_resolved = root.resolve()
            target.relative_to(root_resolved)
        except Exception:
            return {"ok": False, "error": "subpath_outside_root"}
        if not target.exists() or not target.is_dir():
            return {"ok": False, "error": "subpath_not_found"}

        rows: list[dict[str, Any]] = []
        try:
            for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
                rel = str(entry.relative_to(root_resolved))
                rows.append(
                    {
                        "name": entry.name,
                        "path": rel.replace("\\", "/"),
                        "is_dir": entry.is_dir(),
                        "size": entry.stat().st_size if entry.is_file() else 0,
                        "mtime": int(entry.stat().st_mtime),
                    }
                )
                if len(rows) >= max(1, min(int(limit), 2000)):
                    break
        except Exception as exc:
            return {"ok": False, "error": f"list_failed:{str(exc)[:120]}"}
        return {
            "ok": True,
            "kind": kind,
            "root": str(root),
            "subpath": str(subpath or ""),
            "items": rows,
        }

    def delete_file(self, kind: str, rel_path: str) -> dict[str, Any]:
        root = self._kind_root(kind)
        if not root:
            return {"ok": False, "error": "invalid_kind"}
        raw = str(rel_path or "").strip()
        if not raw:
            return {"ok": False, "error": "path_required"}
        root_resolved = root.resolve()
        target = (root / raw).resolve()
        try:
            target.relative_to(root_resolved)
        except Exception:
            return {"ok": False, "error": "path_outside_root"}
        if not target.exists():
            return {"ok": False, "error": "path_not_found"}
        if target.is_dir():
            return {"ok": False, "error": "delete_dir_not_allowed"}
        try:
            target.unlink()
        except Exception as exc:
            return {"ok": False, "error": f"delete_failed:{str(exc)[:120]}"}
        return {"ok": True, "kind": kind, "path": raw}

    # ── Internal ───────────────────────────────────────────────────────────

    def _resolve_my_drive_root(self, settings: dict[str, Any]) -> Path | None:
        configured = str(settings.get("my_drive_root") or "").strip()
        if configured:
            p = Path(configured).expanduser()
            if self._is_rw_dir(p):
                return p
        for p in self._detect_my_drive_roots():
            if self._is_rw_dir(p):
                return p
        return None

    def _detect_my_drive_roots(self) -> list[Path]:
        home = Path.home()
        candidates: list[Path] = []

        preferred = home / "My Drive"
        if preferred.exists():
            candidates.append(preferred)

        cloud = home / "Library" / "CloudStorage"
        if cloud.exists():
            for root in sorted(cloud.glob("GoogleDrive-*")):
                for suffix in ("My Drive", "我的云端硬盘", "MyDrive"):
                    p = root / suffix
                    if p.exists():
                        candidates.append(p)

        fallback = home / "Google Drive"
        if fallback.exists():
            candidates.append(fallback)

        dedup: dict[str, Path] = {}
        for p in candidates:
            try:
                k = str(p.resolve())
            except Exception:
                k = str(p)
            dedup[k] = p
        return list(dedup.values())

    def _kind_root(self, kind: str) -> Path | None:
        status = self.ensure_managed_structure()
        if not status.get("ready"):
            return None
        k = str(kind or "").strip().lower()
        if k == "archive":
            return Path(str(status.get("archive_root") or ""))
        if k == "outcome":
            return Path(str(status.get("outcome_root") or ""))
        return None

    def _is_rw_dir(self, path: Path) -> bool:
        return bool(path.exists() and path.is_dir() and os.access(path, os.R_OK) and os.access(path, os.W_OK) and os.access(path, os.X_OK))

    def _load_settings(self) -> dict[str, Any]:
        if not self.settings_path.exists():
            return {}
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return dict(data) if isinstance(data, dict) else {}

    def _save_settings(self, payload: dict[str, Any]) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

