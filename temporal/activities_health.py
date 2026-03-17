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
    token = os.environ.get("TELEGRAM_BOT_TOKEN_AUTOPILOT") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
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

    Threshold-based alerting (§B.6):
      - reviewer pass rate < 80% → alert
      - token usage > 150% baseline → alert
      - pseudo-human score < 4/5 → alert
    """
    if infra_result.get("overall") == "RED":
        return {
            "ok": False,
            "overall": "RED",
            "skipped": True,
            "reason": "infrastructure_red",
        }

    checks: list[dict] = []
    alerts: list[str] = []
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

                # ── Threshold-based alerting (§B.6) ──────────────────────

                # Threshold 1: reviewer pass rate < 80%
                # reviewer steps = steps assigned to agent_id containing 'reviewer'
                reviewer_row = await conn.fetchrow("""
                    SELECT
                        count(*) FILTER (WHERE status = 'completed') AS passed,
                        count(*) AS total
                    FROM job_steps
                    WHERE agent_id = 'reviewer'
                      AND created_at > now() - interval '7 days'
                """)
                if reviewer_row and (reviewer_row["total"] or 0) >= 5:
                    r_total = reviewer_row["total"]
                    r_passed = reviewer_row["passed"] or 0
                    r_rate = (r_passed / r_total * 100) if r_total > 0 else 100.0
                    r_pass = r_rate >= 80.0
                    checks.append({
                        "name": "reviewer_pass_rate_7d",
                        "passed": r_passed,
                        "total": r_total,
                        "rate_pct": round(r_rate, 1),
                        "pass": r_pass,
                        "threshold": 80.0,
                    })
                    if not r_pass:
                        msg = f"[ALERT] reviewer pass rate {r_rate:.1f}% < 80% threshold (last 7d)"
                        alerts.append(msg)
                        logger.warning(msg)
                        _notify_telegram(f"daemon 质量警报: {msg}")

                # Threshold 2: token usage > 150% baseline
                # Compare last 24h tokens vs 7-day daily average
                token_row = await conn.fetchrow("""
                    SELECT
                        coalesce(sum(token_count) FILTER (
                            WHERE created_at > now() - interval '1 day'), 0) AS tokens_24h,
                        coalesce(sum(token_count) FILTER (
                            WHERE created_at > now() - interval '7 days'), 0) / 7.0 AS tokens_daily_avg
                    FROM job_steps
                    WHERE token_count IS NOT NULL
                """)
                if token_row:
                    tokens_24h = token_row["tokens_24h"] or 0
                    tokens_avg = float(token_row["tokens_daily_avg"] or 0)
                    if tokens_avg > 1000:  # Only alert if baseline is meaningful
                        usage_pct = (tokens_24h / tokens_avg * 100) if tokens_avg > 0 else 0
                        t_pass = usage_pct <= 150.0
                        checks.append({
                            "name": "token_usage_vs_baseline",
                            "tokens_24h": int(tokens_24h),
                            "tokens_daily_avg": round(tokens_avg, 0),
                            "usage_pct": round(usage_pct, 1),
                            "pass": t_pass,
                            "threshold_pct": 150.0,
                        })
                        if not t_pass:
                            msg = f"[ALERT] token usage {usage_pct:.1f}% of baseline (>150% threshold)"
                            alerts.append(msg)
                            logger.warning(msg)
                            _notify_telegram(f"daemon 质量警报: {msg}")

                # Threshold 3: pseudo-human score < 4/5
                # Pseudo-human score is stored in system_events via health reports.
                # Read from state/health_reports for the latest weekly score if present.
                phs_row = await conn.fetchrow("""
                    SELECT payload->>'pseudo_human_score' AS score
                    FROM event_log
                    WHERE event_type = 'health_check_completed'
                      AND payload ? 'pseudo_human_score'
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                if phs_row and phs_row["score"] is not None:
                    try:
                        phs = float(phs_row["score"])
                        phs_pass = phs >= 4.0
                        checks.append({
                            "name": "pseudo_human_score",
                            "score": phs,
                            "pass": phs_pass,
                            "threshold": 4.0,
                        })
                        if not phs_pass:
                            msg = f"[ALERT] pseudo-human score {phs:.1f}/5 < 4.0 threshold"
                            alerts.append(msg)
                            logger.warning(msg)
                            _notify_telegram(f"daemon 质量警报: {msg}")
                    except (TypeError, ValueError):
                        pass

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
        "alerts": alerts,
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


@activity.defn(name="activity_schedule_reconciliation")
async def activity_schedule_reconciliation() -> dict:
    """Compare config/schedules.json with actual Temporal schedules and log discrepancies (§6.9).

    Reads the canonical schedule definitions from config/schedules.json, then
    queries Temporal's list-schedules API. Any schedule that is defined in the
    config but missing from Temporal (or vice-versa) is logged as a discrepancy.

    Called as part of the weekly HealthCheckWorkflow so the operator is notified
    when drift is detected.

    Returns:
        dict with:
          ok: bool
          expected: list of schedule IDs from config
          actual:   list of schedule IDs from Temporal
          missing:  schedules in config but not in Temporal (needs creation)
          extra:    schedules in Temporal but not in config (unexpected)
          drift:    bool — True if any discrepancy found
    """
    home = _daemon_home()
    schedules_path = home / "config" / "schedules.json"

    # Load expected schedule IDs from config
    expected_ids: list[str] = []
    try:
        config_data = json.loads(schedules_path.read_text())
        expected_ids = [s["id"] for s in config_data.get("schedules", []) if s.get("id")]
    except Exception as exc:
        return {"ok": False, "error": f"Failed to read schedules.json: {exc}"}

    # Query Temporal for actual schedule IDs
    actual_ids: list[str] = []
    try:
        temporal_addr = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
        temporal_ns = os.environ.get("TEMPORAL_NAMESPACE", "default")
        r = subprocess.run(
            ["temporal", "schedule", "list",
             "--address", temporal_addr,
             "--namespace", temporal_ns,
             "--output", "json"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            try:
                data = json.loads(r.stdout)
                # Output may be a list of schedules or {"schedules": [...]}
                if isinstance(data, list):
                    schedules_list = data
                elif isinstance(data, dict):
                    schedules_list = data.get("schedules", [])
                else:
                    schedules_list = []
                for s in schedules_list:
                    sid = (
                        s.get("scheduleId")
                        or s.get("schedule_id")
                        or (s.get("info") or {}).get("scheduleId")
                        or ""
                    )
                    if sid:
                        actual_ids.append(sid)
            except json.JSONDecodeError:
                # Some versions output one JSON object per line
                for line in r.stdout.strip().splitlines():
                    try:
                        obj = json.loads(line)
                        sid = (
                            obj.get("scheduleId")
                            or obj.get("schedule_id")
                            or (obj.get("info") or {}).get("scheduleId")
                            or ""
                        )
                        if sid:
                            actual_ids.append(sid)
                    except json.JSONDecodeError:
                        pass
        else:
            logger.warning(
                "temporal schedule list returned code %d: %s",
                r.returncode, r.stderr[:200],
            )
    except FileNotFoundError:
        logger.warning("temporal CLI not found in PATH — skipping schedule reconciliation")
        return {
            "ok": False,
            "error": "temporal_cli_not_found",
            "expected": expected_ids,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "expected": expected_ids}

    expected_set = set(expected_ids)
    actual_set = set(actual_ids)
    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)
    drift = bool(missing or extra)

    if missing:
        logger.warning(
            "Schedule reconciliation: %d schedule(s) in config but missing from Temporal: %s",
            len(missing), missing,
        )
    if extra:
        logger.info(
            "Schedule reconciliation: %d schedule(s) in Temporal but not in config: %s",
            len(extra), extra,
        )
    if not drift:
        logger.info("Schedule reconciliation: all %d schedules in sync", len(expected_ids))

    if drift:
        _notify_telegram(
            f"daemon 调度漂移: {len(missing)} 个缺失, {len(extra)} 个多余\n"
            f"缺失: {missing}\n多余: {extra}"
        )

    return {
        "ok": not drift,
        "expected": expected_ids,
        "actual": actual_ids,
        "missing": missing,
        "extra": extra,
        "drift": drift,
        "checked_utc": _utc(),
    }


@activity.defn(name="activity_health_report")
async def activity_health_report(
    infra: dict, quality: dict, frontier: dict,
    schedule_reconciliation: dict | None = None,
) -> dict:
    """Generate final health report and send Telegram notification.

    schedule_reconciliation is optional — supplied by HealthCheckWorkflow
    after activity_schedule_reconciliation runs.
    """
    # Determine overall status
    statuses = [
        infra.get("overall", "RED"),
        quality.get("overall", "YELLOW"),
    ]
    if schedule_reconciliation and schedule_reconciliation.get("drift"):
        statuses.append("YELLOW")

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
        "schedule_reconciliation": schedule_reconciliation or {},
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
    schedule_status = "OK" if not (schedule_reconciliation or {}).get("drift") else "DRIFT"
    alerts = quality.get("alerts", [])
    alert_line = f"\n质量警报: {len(alerts)} 条" if alerts else ""
    msg = (
        f"{emoji} daemon 周度体检: {overall}\n"
        f"基础设施: {infra_status}\n"
        f"质量: {quality_status}{alert_line}\n"
        f"调度同步: {schedule_status}\n"
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

    # MinIO incremental backup using `mc mirror` (§6.11)
    minio_backup_target = os.environ.get("MINIO_BACKUP_TARGET", "")
    if minio_backup_target:
        minio_endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
        minio_access_key = os.environ.get("MINIO_ACCESS_KEY", "")
        minio_secret_key = os.environ.get("MINIO_SECRET_KEY", "")
        minio_bucket = os.environ.get("MINIO_BUCKET", "daemon-artifacts")

        try:
            # Configure mc alias for source (daemon MinIO) if not already configured.
            # We use a temp alias to avoid polluting user's mc config.
            alias_env = {
                **os.environ,
                "DAEMON_HOME": str(home),
            }
            subprocess.run(
                ["mc", "alias", "set", "daemon-minio",
                 f"http://{minio_endpoint}", minio_access_key, minio_secret_key],
                capture_output=True, text=True, timeout=30, env=alias_env,
            )
            # Run incremental mirror: source → backup target
            # minio_backup_target can be e.g. "s3://bucket/daemon-backup" or a local path.
            r = subprocess.run(
                ["mc", "mirror", "--overwrite",
                 f"daemon-minio/{minio_bucket}", minio_backup_target],
                capture_output=True, text=True, timeout=600, env=alias_env,
            )
            if r.returncode == 0:
                results["minio_mirror"] = {"ok": True, "target": minio_backup_target}
            else:
                results["minio_mirror"] = {
                    "ok": False,
                    "error": r.stderr[:300] or r.stdout[:300],
                    "target": minio_backup_target,
                }
        except FileNotFoundError:
            results["minio_mirror"] = {"ok": False, "error": "mc_cli_not_found"}
        except Exception as exc:
            results["minio_mirror"] = {"ok": False, "error": str(exc)[:200]}
    else:
        results["minio_mirror"] = {"ok": True, "skipped": True, "reason": "MINIO_BACKUP_TARGET_not_set"}

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

    pg_ok = results.get("pg_dump", {}).get("ok", False)
    minio_ok = results.get("minio_mirror", {}).get("ok", False)
    results["ok"] = pg_ok and minio_ok
    return results
