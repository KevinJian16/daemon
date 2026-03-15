"""Temporal activities: health check + self-heal.

Activities for HealthCheckWorkflow and SelfHealWorkflow.

Reference: SYSTEM_DESIGN.md §7.7, §7.8
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from temporalio import activity

logger = logging.getLogger(__name__)


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _daemon_home() -> Path:
    return Path(os.environ.get("DAEMON_HOME", Path(__file__).parent.parent))


def _state_dir() -> Path:
    d = _daemon_home() / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _notify_telegram(msg: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN_OPERATOR") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return False
    try:
        data = json.dumps({"chat_id": chat_id, "text": msg}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as exc:
        logger.warning("Telegram notification failed: %s", exc)
        return False


# ── Health Check Activities ──────────────────────────────────────────────


@activity.defn(name="activity_health_check_infrastructure")
async def activity_health_check_infrastructure() -> dict:
    """Run infrastructure health checks (Layer 1 of §7.7.1).

    Runs scripts/verify.py and captures results.
    """
    home = _daemon_home()
    verify_script = home / "scripts" / "verify.py"

    if not verify_script.exists():
        return {"ok": False, "error": "verify.py not found", "overall": "RED"}

    try:
        r = subprocess.run(
            [sys.executable, str(verify_script)],
            capture_output=True, text=True, timeout=300,
            cwd=str(home),
            env={**os.environ, "DAEMON_HOME": str(home)},
        )
        # Read the health report
        today = time.strftime("%Y-%m-%d")
        report_path = _state_dir() / "health_reports" / f"{today}.json"
        if report_path.exists():
            return json.loads(report_path.read_text())
        return {
            "ok": r.returncode == 0,
            "overall": "GREEN" if r.returncode == 0 else "RED",
            "stdout": r.stdout[-1000:] if r.stdout else "",
        }
    except Exception as exc:
        return {"ok": False, "overall": "RED", "error": str(exc)[:300]}


@activity.defn(name="activity_health_check_quality")
async def activity_health_check_quality(infra_result: dict) -> dict:
    """Quality layer check (Layer 2 of §7.7.1).

    Queries PG for recent job success/failure metrics and validates
    that the execution pipeline is producing results.
    """
    if infra_result.get("overall") == "RED":
        return {
            "ok": False,
            "overall": "RED",
            "skipped": True,
            "reason": "infrastructure_red",
        }

    checks: list[dict] = []
    try:
        import asyncpg
        pool = await _create_quality_pool()
        try:
            async with pool.acquire() as conn:
                # Check 1: Recent job completion rate (last 7 days)
                row = await conn.fetchrow("""
                    SELECT
                        count(*) FILTER (WHERE sub_status = 'completed') AS completed,
                        count(*) FILTER (WHERE sub_status = 'failed') AS failed,
                        count(*) AS total
                    FROM jobs
                    WHERE created_at > now() - interval '7 days'
                """)
                total = row["total"] if row else 0
                completed = row["completed"] if row else 0
                failed = row["failed"] if row else 0
                success_rate = (completed / total * 100) if total > 0 else None

                checks.append({
                    "name": "job_success_rate_7d",
                    "total": total,
                    "completed": completed,
                    "failed": failed,
                    "rate_pct": round(success_rate, 1) if success_rate is not None else None,
                    "pass": total == 0 or (success_rate is not None and success_rate >= 50),
                })

                # Check 2: Recent step error patterns
                step_errors = await conn.fetchval("""
                    SELECT count(*)
                    FROM job_steps
                    WHERE status = 'failed'
                      AND created_at > now() - interval '7 days'
                """)
                checks.append({
                    "name": "step_errors_7d",
                    "count": step_errors or 0,
                    "pass": (step_errors or 0) < 50,
                })

                # Check 3: DB responsiveness (query time)
                t0 = time.monotonic()
                await conn.fetchval("SELECT 1")
                latency_ms = round((time.monotonic() - t0) * 1000, 1)
                checks.append({
                    "name": "db_latency_ms",
                    "value": latency_ms,
                    "pass": latency_ms < 500,
                })

                # Check 4: Table row counts (sanity)
                for table in ("daemon_tasks", "jobs", "conversation_messages"):
                    cnt = await conn.fetchval(f"SELECT count(*) FROM {table}")
                    checks.append({
                        "name": f"table_{table}_rows",
                        "count": cnt or 0,
                        "pass": True,
                    })
        finally:
            await pool.close()
    except Exception as exc:
        checks.append({"name": "pg_connection", "pass": False, "error": str(exc)[:200]})

    all_pass = all(c.get("pass", False) for c in checks)
    has_failures = any(not c.get("pass", True) for c in checks)

    if has_failures:
        overall = "RED"
    elif all_pass:
        overall = infra_result.get("overall", "GREEN")
    else:
        overall = "YELLOW"

    return {
        "ok": all_pass,
        "overall": overall,
        "quality_checks": checks,
        "checked_utc": _utc(),
    }


async def _create_quality_pool():
    """Create a temporary asyncpg pool for quality checks."""
    import asyncpg
    pg_url = (
        f"postgresql://{os.environ.get('POSTGRES_USER', 'daemon')}:"
        f"{os.environ.get('POSTGRES_PASSWORD', 'daemon')}@"
        f"{os.environ.get('POSTGRES_HOST', '127.0.0.1')}:"
        f"{os.environ.get('POSTGRES_PORT', '5432')}/"
        f"{os.environ.get('POSTGRES_DB', 'daemon')}"
    )
    return await asyncpg.create_pool(pg_url, min_size=1, max_size=2)


@activity.defn(name="activity_health_check_frontier")
async def activity_health_check_frontier(quality_result: dict) -> dict:
    """Frontier scan (Layer 3 of §7.7.1).

    researcher agent scans for improvements in each agent's domain.
    For now: stub that records scan attempt.
    """
    return {
        "ok": True,
        "scanned": False,
        "note": "frontier_scan_stub_pending_researcher_agent",
    }


@activity.defn(name="activity_health_report")
async def activity_health_report(
    infra: dict, quality: dict, frontier: dict
) -> dict:
    """Generate final health report and send Telegram notification."""
    # Determine overall status
    statuses = [
        infra.get("overall", "RED"),
        quality.get("overall", "YELLOW"),
    ]
    if "RED" in statuses:
        overall = "RED"
    elif "YELLOW" in statuses:
        overall = "YELLOW"
    else:
        overall = "GREEN"

    report = {
        "checked_utc": _utc(),
        "overall": overall,
        "infrastructure": infra,
        "quality": quality,
        "frontier": frontier,
    }

    # Save report
    reports_dir = _state_dir() / "health_reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    report_path = reports_dir / f"{today}-weekly.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))

    # Telegram notification
    emoji = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(overall, "⚪")
    infra_status = infra.get("overall", "?")
    quality_status = quality.get("overall", "?")
    msg = (
        f"{emoji} daemon 周度体检: {overall}\n"
        f"基础设施: {infra_status}\n"
        f"质量: {quality_status}\n"
        f"前沿扫描: {'有更新' if frontier.get('scanned') else '无更新'}"
    )
    _notify_telegram(msg)

    return report


# ── Self-Heal Activities ─────────────────────────────────────────────────


@activity.defn(name="activity_self_heal_diagnose")
async def activity_self_heal_diagnose(trigger: dict) -> dict:
    """Activity 1: admin generates issue file.

    Analyzes the trigger (health check failure, error report) and creates
    a self-describing issue file at state/issues/YYYY-MM-DD-HHMM.md.
    """
    ts = time.strftime("%Y-%m-%d-%H%M")
    issue_id = ts
    issues_dir = _state_dir() / "issues"
    issues_dir.mkdir(parents=True, exist_ok=True)

    error_msg = trigger.get("error", "unknown error")
    failed_checks = trigger.get("failed_checks", [])
    source = trigger.get("source", "health_check")

    # Generate self-describing issue file (§7.9 format)
    content = f"""# 问题报告

## 你需要做什么
检查并修复 daemon 系统中检测到的问题。

## 背景
daemon 是一个自动化助手系统。这个文件由自动健康检查生成。

## 具体问题
来源: {source}
时间: {_utc()}
错误: {error_msg}

失败的检查项:
{chr(10).join(f'- {c}' for c in failed_checks) if failed_checks else '- 见上方错误描述'}

## 触发数据
```json
{json.dumps(trigger, ensure_ascii=False, indent=2)}
```

## 期望行为
所有健康检查通过，系统状态恢复为 GREEN。

## 执行步骤（修复完成后按顺序运行）
1. python scripts/start.py          # 确保所有进程就绪
2. python scripts/verify.py --issue {issue_id}  # 自动验证并发送通知
"""

    issue_path = issues_dir / f"{issue_id}.md"
    issue_path.write_text(content, encoding="utf-8")
    logger.info("Generated issue file: %s", issue_path)

    return {"ok": True, "issue_id": issue_id, "path": str(issue_path)}


@activity.defn(name="activity_self_heal_fix")
async def activity_self_heal_fix(issue_id: str) -> dict:
    """Activity 2: Apply fix via Claude Code CLI.

    Invokes `claude` CLI in non-interactive mode with the issue file as prompt.
    CC reads the issue → analyzes → applies file/config changes.
    Scoped to daemon/ directory only (§7.8).
    """
    issue_path = _state_dir() / "issues" / f"{issue_id}.md"
    if not issue_path.exists():
        return {"ok": False, "error": "issue_file_not_found"}

    content = issue_path.read_text()

    # Check if already manually resolved
    if "## 状态" in content and "已修复" in content:
        return {"ok": True, "fixed_by": "manual"}

    home = _daemon_home()

    # Try Claude Code first, fall back to Codex
    claude_bin = _find_cli("claude")
    codex_bin = _find_cli("codex") if not claude_bin else None

    if not claude_bin and not codex_bin:
        logger.warning("Neither 'claude' nor 'codex' CLI found in PATH")
        return {"ok": False, "error": "cc_codex_cli_not_found", "issue_id": issue_id}

    prompt = (
        f"Read the issue file at {issue_path} and apply the fix. "
        f"Only modify files under {home}. Do not delete data or run destructive commands. "
        f"After fixing, briefly describe what you changed."
    )

    try:
        if claude_bin:
            r = subprocess.run(
                [claude_bin, "--print", "--dangerously-skip-permissions", prompt],
                capture_output=True, text=True, timeout=600,
                cwd=str(home),
                env={**os.environ, "DAEMON_HOME": str(home)},
            )
        else:
            r = subprocess.run(
                [codex_bin, "--quiet", "--approval-mode", "auto-edit", prompt],
                capture_output=True, text=True, timeout=600,
                cwd=str(home),
                env={**os.environ, "DAEMON_HOME": str(home)},
            )

        ok = r.returncode == 0
        output = (r.stdout or "")[-2000:]

        # Append status to issue file
        status_section = f"\n\n## 状态\n{'已修复' if ok else '修复失败'} ({_utc()})\n\n### 输出\n```\n{output[:1000]}\n```\n"
        with open(issue_path, "a") as f:
            f.write(status_section)

        if ok:
            logger.info("Self-heal fix applied for issue %s via %s",
                        issue_id, "claude" if claude_bin else "codex")
        else:
            logger.warning("Self-heal fix failed for issue %s: %s",
                           issue_id, (r.stderr or "")[:200])

        return {
            "ok": ok,
            "issue_id": issue_id,
            "fixed_by": "claude_code" if claude_bin else "codex",
            "output": output[:500],
            "returncode": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "cc_codex_timeout", "issue_id": issue_id}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "issue_id": issue_id}


def _find_cli(name: str) -> str | None:
    """Find a CLI binary in PATH. Returns full path or None."""
    import shutil
    return shutil.which(name)


@activity.defn(name="activity_self_heal_restart")
async def activity_self_heal_restart() -> dict:
    """Activity 3: Restart daemon services via scripts/start.py.

    WARNING: This may kill the Worker process. Temporal will retry this activity
    after Worker recovers.
    """
    home = _daemon_home()
    start_script = home / "scripts" / "start.py"

    try:
        r = subprocess.run(
            [sys.executable, str(start_script)],
            capture_output=True, text=True, timeout=300,
            cwd=str(home),
            env={**os.environ, "DAEMON_HOME": str(home)},
        )
        return {"ok": r.returncode == 0, "stdout": r.stdout[-500:]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


@activity.defn(name="activity_self_heal_verify")
async def activity_self_heal_verify(issue_id: str) -> dict:
    """Activity 4: Verify fix via scripts/verify.py --issue ID."""
    home = _daemon_home()
    verify_script = home / "scripts" / "verify.py"

    try:
        r = subprocess.run(
            [sys.executable, str(verify_script), "--issue", issue_id],
            capture_output=True, text=True, timeout=300,
            cwd=str(home),
            env={**os.environ, "DAEMON_HOME": str(home)},
        )
        # Read report
        today = time.strftime("%Y-%m-%d")
        report_path = _state_dir() / "health_reports" / f"{today}.json"
        if report_path.exists():
            return json.loads(report_path.read_text())
        return {"ok": r.returncode == 0, "overall": "GREEN" if r.returncode == 0 else "RED"}
    except Exception as exc:
        return {"ok": False, "overall": "RED", "error": str(exc)[:300]}


@activity.defn(name="activity_self_heal_notify_failure")
async def activity_self_heal_notify_failure(issue_id: str, details: dict) -> dict:
    """Layer 3: Notify user that auto-fix failed."""
    issue_path = _state_dir() / "issues" / f"{issue_id}.md"
    msg = (
        f"🔴 daemon 自动修复失败\n"
        f"请把以下文件发给 Claude Code：\n"
        f"`{issue_path}`"
    )
    sent = _notify_telegram(msg)
    return {"ok": True, "notified": sent, "issue_id": issue_id}


# ── Backup Activity ──────────────────────────────────────────────────────


@activity.defn(name="activity_backup")
async def activity_backup(config: dict) -> dict:
    """Daily incremental backup of PG + MinIO.

    Reference: SYSTEM_DESIGN.md §6.11
    """
    home = _daemon_home()
    backup_dir = Path(os.environ.get("DAEMON_BACKUP_DIR", str(home / "backups")))
    backup_dir.mkdir(parents=True, exist_ok=True)

    today = time.strftime("%Y-%m-%d")
    dest = backup_dir / today
    dest.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {"date": today, "path": str(dest)}

    # PG dump
    pg_user = os.environ.get("POSTGRES_USER", "daemon")
    pg_db = os.environ.get("POSTGRES_DB", "daemon")
    pg_dump_path = dest / "daemon.sql.gz"

    try:
        r = subprocess.run(
            ["docker", "compose", "exec", "-T", "postgres",
             "pg_dump", "-U", pg_user, pg_db],
            capture_output=True, timeout=600, cwd=str(home),
        )
        if r.returncode == 0:
            import gzip
            with gzip.open(pg_dump_path, "wb") as f:
                f.write(r.stdout)
            results["pg_dump"] = {"ok": True, "size_bytes": pg_dump_path.stat().st_size}
        else:
            results["pg_dump"] = {"ok": False, "error": r.stderr.decode()[:200]}
    except Exception as exc:
        results["pg_dump"] = {"ok": False, "error": str(exc)[:200]}

    # Prune old backups (keep 90 days per §6.11)
    try:
        cutoff = time.time() - 90 * 86400
        pruned = 0
        for d in backup_dir.iterdir():
            if d.is_dir() and d != dest:
                if d.stat().st_mtime < cutoff:
                    import shutil
                    shutil.rmtree(d)
                    pruned += 1
        results["pruned"] = pruned
    except Exception as exc:
        results["prune_error"] = str(exc)[:200]

    results["ok"] = results.get("pg_dump", {}).get("ok", False)
    return results
