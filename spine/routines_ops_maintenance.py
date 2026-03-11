"""Spine relay/tend/curate implementations (V2 aligned)."""
from __future__ import annotations

import json
import logging
import shutil
import time
from pathlib import Path
from services.storage_paths import resolve_vault_root

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run_relay(self) -> dict:
    """Export Psyche snapshots to state/snapshots/ and retinue instance workspaces."""
    with self.trail.span("spine.relay", trigger="nerve:deed_allocated") as ctx:
        snapshots_dir = self.state_dir / "snapshots"
        snapshots_dir.mkdir(parents=True, exist_ok=True)

        mem_snap = self.memory.snapshot()
        lore_snap = self.lore.snapshot()
        inst_snap = self.instinct.snapshot()

        (snapshots_dir / "memory_snapshot.json").write_text(
            json.dumps(mem_snap, ensure_ascii=False, indent=2))
        (snapshots_dir / "lore_snapshot.json").write_text(
            json.dumps(lore_snap, ensure_ascii=False, indent=2))
        (snapshots_dir / "instinct_snapshot.json").write_text(
            json.dumps(inst_snap, ensure_ascii=False, indent=2))
        ctx.step("snapshots_written", 3)

        model_policy = self._build_model_policy_snapshot()
        model_registry = self._build_model_registry_snapshot()
        (snapshots_dir / "model_policy_snapshot.json").write_text(
            json.dumps(model_policy, ensure_ascii=False, indent=2))
        (snapshots_dir / "model_registry_snapshot.json").write_text(
            json.dumps(model_registry, ensure_ascii=False, indent=2))
        ctx.step("model_snapshots_written", 2)

        runtime_hints = _build_runtime_hints(mem_snap, lore_snap, inst_snap)
        (snapshots_dir / "runtime_hints.json").write_text(
            json.dumps(runtime_hints, ensure_ascii=False, indent=2))
        ctx.step("runtime_hints_written", True)

        result = {"snapshots": 5, "runtime_hints": True}
        ctx.set_result(result)
    return result


def run_tend(self) -> dict:
    """Housekeeping: clean traces, check rations, state/ git commit."""
    with self.trail.span("spine.tend", trigger="daily") as ctx:
        self._maybe_reset_rations()
        ctx.step("rations_checked")

        cleaned = self._clean_old_traces(max_age_days=7)
        ctx.step("traces_cleaned", cleaned)

        _clean_old_events(self.state_dir, max_age_days=30)
        ctx.step("events_cleaned")

        herald_log_rotated = _rotate_herald_log(self.state_dir, max_entries=2000)
        ctx.step("herald_log_rotated", herald_log_rotated)

        notify_queue_cleaned = _clean_notify_queue(self.state_dir, max_age_days=3)
        ctx.step("notify_queue_cleaned", notify_queue_cleaned)

        console_audit_cleaned = _clean_old_console_audit(self.state_dir, max_age_days=90)
        ctx.step("console_audit_cleaned", console_audit_cleaned)

        daily_stats = _write_daily_stats(self)
        ctx.step("daily_stats_written", daily_stats)

        _state_git_commit(self.state_dir)
        ctx.step("state_git_committed")

        backup_result = _backup_state(self.daemon_home)
        ctx.step("state_backed_up", backup_result)

        result = {
            "traces_cleaned": cleaned,
            "rations_checked": True,
            "herald_log_rotated": herald_log_rotated,
            "notify_queue_cleaned": notify_queue_cleaned,
            "console_audit_cleaned": console_audit_cleaned,
            "daily_stats_written": bool(daily_stats),
            "state_committed": True,
            "backup": backup_result,
        }
        ctx.set_result(result)
    return result


def run_curate(self) -> dict:
    """Vault deed_root to vault/, clean expired vaults (90 days)."""
    with self.trail.span("spine.curate", trigger="every_6h") as ctx:
        vaulted = _vault_completed_deeds(self)
        ctx.step("deeds_vaulted", vaulted)

        lore_decay = self.lore.decay()
        ctx.step("lore_decay", lore_decay)

        expired = _expire_old_vaults(self)
        ctx.step("vaults_expired", expired)

        cleaned = _clean_old_deed_roots(self)
        ctx.step("deed_roots_cleaned", cleaned)

        result = {
            "deeds_vaulted": vaulted,
            "lore_decay_removed": lore_decay.get("removed", 0),
            "vaults_expired": expired,
            "deed_roots_cleaned": cleaned,
        }
        ctx.set_result(result)
    return result


def _build_runtime_hints(mem_snap: dict, lore_snap: dict, inst_snap: dict) -> dict:
    recent_records = lore_snap.get("records", [])[:5]
    prefs = inst_snap.get("preferences", {})
    return {
        "generated_utc": _utc(),
        "preferences": prefs,
        "recent_records": [
            {
                "objective": r.get("objective_text", "")[:100],
                "dag_budget": r.get("dag_budget"),
                "success": r.get("success"),
            }
            for r in recent_records
        ],
        "memory_summary": {
            "total_entries": len(mem_snap.get("entries", [])),
        },
    }


def _vault_completed_deeds(self) -> int:
    """Move completed deed_roots to vault/."""
    deeds_dir = self.state_dir / "deeds"
    if not deeds_dir.exists():
        return 0

    drive_vault = resolve_vault_root(self.state_dir)
    vaulted = 0
    deed_rows = {
        str(row.get("deed_id") or ""): row
        for row in self._store.load_deeds()
        if isinstance(row, dict)
    }

    for deed_dir in deeds_dir.iterdir():
        if not deed_dir.is_dir():
            continue
        deed_id = deed_dir.name
        deed_row = deed_rows.get(deed_id, {})
        status_file = deed_dir / "status.json"
        status = deed_row if isinstance(deed_row, dict) else {}
        if status_file.exists():
            try:
                raw_status = json.loads(status_file.read_text())
                if isinstance(raw_status, dict):
                    status.update(raw_status)
            except Exception:
                pass

        deed_status = str(status.get("deed_status") or status.get("status") or "")
        if deed_status not in {"closed"}:
            continue

        completed_utc = str(
            status.get("completed_utc")
            or status.get("eval_submitted_utc")
            or status.get("eval_expired_utc")
            or status.get("updated_utc")
            or ""
        )
        if not completed_utc:
            continue

        age_days = (time.time() - _iso_to_ts(completed_utc)) / 86400 if _iso_to_ts(completed_utc) else 0
        if age_days < 1:
            continue

        month = completed_utc[:7]
        dest = drive_vault / month / deed_id
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            manifest = {
                "deed_id": deed_id,
                "status": deed_status,
                "completed_utc": completed_utc,
                "vaulted_utc": _utc(),
            }

            dest.mkdir(parents=True, exist_ok=True)
            (dest / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))

            moves_src = deed_dir / "moves"
            if moves_src.exists():
                shutil.copytree(moves_src, dest / "moves", dirs_exist_ok=True)

            design = status.get("plan") if isinstance(status.get("plan"), dict) else {}
            if design:
                (dest / "design.json").write_text(json.dumps(design, ensure_ascii=False, indent=2), encoding="utf-8")
            if status:
                (dest / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

            vaulted += 1
        except Exception as exc:
            logger.warning("Failed to vault deed %s: %s", deed_id, exc)

    return vaulted


def _expire_old_vaults(self) -> int:
    """Delete vaults older than 90 days."""
    drive_vault = resolve_vault_root(self.state_dir)
    if not drive_vault.exists():
        return 0

    cutoff = time.time() - 90 * 86400
    expired = 0
    for month_dir in drive_vault.iterdir():
        if not month_dir.is_dir():
            continue
        for deed_dir in month_dir.iterdir():
            if not deed_dir.is_dir():
                continue
            manifest_path = deed_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text())
                vaulted_utc = manifest.get("vaulted_utc", "")
                ts = _iso_to_ts(vaulted_utc)
                if ts and ts < cutoff:
                    shutil.rmtree(deed_dir)
                    expired += 1
            except Exception as exc:
                logger.warning("Failed to expire vault %s: %s", deed_dir, exc)

    return expired


def _clean_old_deed_roots(self) -> int:
    """Delete deed_roots that have been vaulted and are older than 7 days."""
    deeds_dir = self.state_dir / "deeds"
    if not deeds_dir.exists():
        return 0

    cutoff = time.time() - 7 * 86400
    drive_vault = resolve_vault_root(self.state_dir)
    cleaned = 0
    deed_rows = {
        str(row.get("deed_id") or ""): row
        for row in self._store.load_deeds()
        if isinstance(row, dict)
    }

    for deed_dir in deeds_dir.iterdir():
        if not deed_dir.is_dir():
            continue
        deed_id = deed_dir.name
        status = deed_rows.get(deed_id, {}) if isinstance(deed_rows.get(deed_id, {}), dict) else {}
        status_file = deed_dir / "status.json"
        if status_file.exists():
            try:
                raw_status = json.loads(status_file.read_text())
                if isinstance(raw_status, dict):
                    status.update(raw_status)
            except Exception:
                pass

        deed_status = str(status.get("deed_status") or status.get("status") or "")
        if deed_status not in {"closed"}:
            continue

        if deed_dir.stat().st_mtime > cutoff:
            continue

        in_vault = any(drive_vault.glob(f"*/{deed_id}")) if drive_vault.exists() else False
        if not in_vault and deed_status == "closed":
            continue

        try:
            shutil.rmtree(deed_dir)
            cleaned += 1
        except Exception as exc:
            logger.warning("Failed to clean deed root %s: %s", deed_dir, exc)

    return cleaned


def _clean_old_events(state_dir: Path, max_age_days: int = 30) -> None:
    events_path = state_dir / "events.jsonl"
    if not events_path.exists():
        return
    try:
        cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - max_age_days * 86400))
        lines = events_path.read_text(encoding="utf-8").splitlines()
        kept = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                ts = str(row.get("timestamp") or "")
                if ts >= cutoff:
                    kept.append(line)
            except json.JSONDecodeError:
                continue
        events_path.write_text("\n".join(kept) + "\n" if kept else "", encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to clean old events: %s", exc)


def _rotate_herald_log(state_dir: Path, max_entries: int = 2000) -> int:
    """Keep only the last max_entries in herald_log.jsonl."""
    path = state_dir / "herald_log.jsonl"
    if not path.exists():
        return 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        non_empty = [ln for ln in lines if ln.strip()]
        if len(non_empty) <= max_entries:
            return 0
        trimmed = len(non_empty) - max_entries
        path.write_text("\n".join(non_empty[-max_entries:]) + "\n", encoding="utf-8")
        return trimmed
    except Exception as exc:
        logger.warning("Herald log rotation failed: %s", exc)
        return 0


def _clean_notify_queue(state_dir: Path, max_age_days: int = 3) -> int:
    """Remove notification queue entries older than max_age_days or with 3+ retries."""
    path = state_dir / "notify_queue.jsonl"
    if not path.exists():
        return 0
    try:
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - max_age_days * 86400),
        )
        lines = path.read_text(encoding="utf-8").splitlines()
        remaining: list[str] = []
        dropped = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                queued = str(obj.get("queued_utc") or "")
                retries = int(obj.get("retry_count") or 0)
                if retries >= 3 or (queued and queued < cutoff):
                    dropped += 1
                    continue
                remaining.append(line)
            except (json.JSONDecodeError, ValueError):
                dropped += 1
        path.write_text("\n".join(remaining) + "\n" if remaining else "", encoding="utf-8")
        return dropped
    except Exception as exc:
        logger.warning("Notify queue cleanup failed: %s", exc)
        return 0


def _clean_old_console_audit(state_dir: Path, max_age_days: int = 90) -> int:
    path = state_dir / "console_audit.jsonl"
    if not path.exists():
        return 0
    try:
        cutoff = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(time.time() - max_age_days * 86400),
        )
        rows = []
        dropped = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                dropped += 1
                continue
            ts = str(obj.get("created_utc") or "")
            if ts and ts < cutoff:
                dropped += 1
                continue
            rows.append(obj)
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        return dropped
    except Exception as exc:
        logger.warning("Console audit cleanup failed: %s", exc)
        return 0


def _write_daily_stats(self) -> dict:
    today = time.strftime("%Y-%m-%d", time.gmtime())
    existing = self._store.load_daily_stats(max_items=30)
    if any(str(row.get("date") or "") == today for row in existing):
        return {}
    deeds = self._store.load_deeds()
    herald = self._store.load_herald_log(max_items=5000)
    health = self._store.load_json("system_health.json", {})
    row = {
        "date": today,
        "deeds_total": len(deeds),
        "deeds_running": sum(1 for d in deeds if str(d.get("deed_status") or "") in {"running", "settling"}),
        "deeds_awaiting_eval": sum(1 for d in deeds if str(d.get("deed_status") or "") == "settling"),
        "offerings_total": len(herald),
        "avg_quality": float((health or {}).get("avg_quality") or 0.0),
        "success_rate": float((health or {}).get("success_rate") or 0.0),
    }
    self._store.append_daily_stats(row)
    return row


def _backup_state(home: Path) -> dict:
    """Snapshot critical state files to state/backups/. Keep last 7."""
    state_dir = home / "state"
    backup_root = state_dir / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    dest = backup_root / timestamp
    dest.mkdir(parents=True, exist_ok=True)

    files_to_backup = [
        "deeds.json", "ward.json", "schedule_history.json",
        "herald_log.jsonl", "psyche/instinct.db",
    ]
    copied = 0
    for fname in files_to_backup:
        src = state_dir / fname
        if src.exists():
            try:
                shutil.copy2(str(src), str(dest / fname))
                copied += 1
            except Exception as exc:
                logger.warning("Backup failed for %s: %s", fname, exc)

    # Prune old backups (keep last 7).
    existing = sorted(
        [d for d in backup_root.iterdir() if d.is_dir()],
        key=lambda d: d.name,
    )
    pruned = 0
    while len(existing) > 7:
        old = existing.pop(0)
        try:
            shutil.rmtree(str(old))
            pruned += 1
        except Exception as exc:
            logger.warning("Backup prune failed for %s: %s", old, exc)

    return {"copied": copied, "pruned": pruned, "path": str(dest)}


def _state_git_commit(state_dir: Path) -> None:
    """Commit state/ changes to its internal git repo."""
    import subprocess
    git_dir = state_dir / ".git"
    if not git_dir.exists():
        return
    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=state_dir, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "commit", "-m", f"tend: auto-commit {_utc()}", "--allow-empty"],
            cwd=state_dir, capture_output=True, timeout=10,
        )
    except Exception as exc:
        logger.warning("state/ git commit failed: %s", exc)


def _iso_to_ts(v: str) -> float | None:
    if not v:
        return None
    try:
        import calendar
        return float(calendar.timegm(time.strptime(v, "%Y-%m-%dT%H:%M:%SZ")))
    except Exception:
        return None
