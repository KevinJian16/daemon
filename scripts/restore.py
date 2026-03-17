#!/usr/bin/env python3
"""Restore daemon from backup — PG + MinIO.

Usage:
  python scripts/restore.py --date 2026-03-16
  python scripts/restore.py --date 2026-03-16 --pg-only
  python scripts/restore.py --date 2026-03-16 --minio-only
  python scripts/restore.py --list

Reference: SYSTEM_DESIGN.md §6.11
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("restore")

DAEMON_HOME = Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))
BACKUP_DIR = DAEMON_HOME / "state" / "backups"


def list_backups() -> list[dict]:
    """List available backups."""
    if not BACKUP_DIR.exists():
        logger.warning("No backup directory: %s", BACKUP_DIR)
        return []

    backups = []
    for d in sorted(BACKUP_DIR.iterdir()):
        if not d.is_dir():
            continue
        meta_file = d / "metadata.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text())
        else:
            meta = {"date": d.name}

        pg_dump = d / "daemon_pg.sql.gz"
        minio_marker = d / "minio_backup_done"

        backups.append({
            "date": d.name,
            "path": str(d),
            "pg_available": pg_dump.exists(),
            "minio_available": minio_marker.exists() or (d / "minio").is_dir(),
            "metadata": meta,
        })

    return backups


def restore_pg(backup_dir: Path) -> bool:
    """Restore PostgreSQL from pg_dump."""
    dump_file = backup_dir / "daemon_pg.sql.gz"
    if not dump_file.exists():
        # Try uncompressed
        dump_file = backup_dir / "daemon_pg.sql"
        if not dump_file.exists():
            logger.error("No PG dump found in %s", backup_dir)
            return False

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://daemon:daemon@localhost:5432/daemon",
    )

    logger.info("Restoring PG from %s ...", dump_file)

    # Parse database URL for psql args
    # Format: postgresql://user:pass@host:port/dbname
    parts = db_url.replace("postgresql://", "").split("@")
    user_pass = parts[0].split(":")
    host_port_db = parts[1].split("/")
    host_port = host_port_db[0].split(":")

    env = {
        **os.environ,
        "PGPASSWORD": user_pass[1] if len(user_pass) > 1 else "",
    }

    psql_args = [
        "psql",
        "-h", host_port[0],
        "-p", host_port[1] if len(host_port) > 1 else "5432",
        "-U", user_pass[0],
        "-d", host_port_db[1] if len(host_port_db) > 1 else "daemon",
    ]

    if str(dump_file).endswith(".gz"):
        # Pipe through gunzip
        gunzip = subprocess.Popen(
            ["gunzip", "-c", str(dump_file)],
            stdout=subprocess.PIPE,
        )
        result = subprocess.run(
            psql_args,
            stdin=gunzip.stdout,
            env=env,
            capture_output=True,
            text=True,
        )
        gunzip.wait()
    else:
        with open(dump_file) as f:
            result = subprocess.run(
                psql_args,
                stdin=f,
                env=env,
                capture_output=True,
                text=True,
            )

    if result.returncode != 0:
        logger.error("PG restore failed: %s", result.stderr[:500])
        return False

    logger.info("PG restore completed successfully")
    return True


def restore_minio(backup_dir: Path) -> bool:
    """Restore MinIO artifacts from backup."""
    minio_dir = backup_dir / "minio"
    if not minio_dir.is_dir():
        logger.error("No MinIO backup directory found in %s", backup_dir)
        return False

    endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.environ.get("MINIO_ROOT_USER", "minioadmin")
    secret_key = os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin")

    try:
        from minio import Minio
        client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)

        bucket = "artifacts"
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)

        count = 0
        for file_path in minio_dir.rglob("*"):
            if not file_path.is_file():
                continue
            object_name = str(file_path.relative_to(minio_dir))
            client.fput_object(bucket, object_name, str(file_path))
            count += 1

        logger.info("MinIO restore: uploaded %d objects to bucket '%s'", count, bucket)
        return True

    except ImportError:
        logger.error("minio package not installed — cannot restore MinIO")
        return False
    except Exception as exc:
        logger.error("MinIO restore failed: %s", exc)
        return False


def main():
    parser = argparse.ArgumentParser(description="Restore daemon from backup")
    parser.add_argument("--date", help="Backup date (YYYY-MM-DD)")
    parser.add_argument("--list", action="store_true", help="List available backups")
    parser.add_argument("--pg-only", action="store_true", help="Restore only PostgreSQL")
    parser.add_argument("--minio-only", action="store_true", help="Restore only MinIO")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if args.list:
        backups = list_backups()
        if not backups:
            print("No backups found.")
            return

        print(f"{'Date':<15} {'PG':>4} {'MinIO':>6}  Path")
        print("-" * 60)
        for b in backups:
            pg = "yes" if b["pg_available"] else "no"
            minio = "yes" if b["minio_available"] else "no"
            print(f"{b['date']:<15} {pg:>4} {minio:>6}  {b['path']}")
        return

    if not args.date:
        parser.error("--date is required (use --list to see available backups)")

    backup_dir = BACKUP_DIR / args.date
    if not backup_dir.is_dir():
        logger.error("Backup directory not found: %s", backup_dir)
        sys.exit(1)

    if not args.yes:
        print(f"\nWARNING: This will overwrite the current daemon database with backup from {args.date}.")
        confirm = input("Continue? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    restore_pg_flag = not args.minio_only
    restore_minio_flag = not args.pg_only

    success = True
    if restore_pg_flag:
        if not restore_pg(backup_dir):
            success = False
    if restore_minio_flag:
        if not restore_minio(backup_dir):
            success = False

    if success:
        logger.info("Restore completed successfully from %s", args.date)
    else:
        logger.error("Restore completed with errors")
        sys.exit(1)


if __name__ == "__main__":
    main()
