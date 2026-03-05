"""Telegram Adapter — webhook listener + push notifier for Daemon.

Push model (system → user):
  POST /notify  with JSON payload triggers proactive Telegram messages.
  Events: task_started, task_completed, milestone_done, campaign_plan_ready,
          task_failed, task_paused, skill_evolution_digest.

Pull model (user → system):
  Webhook receives messages and callback queries, forwards to Daemon API.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daemon_env import load_daemon_env

logger = logging.getLogger(__name__)

# Load .env before resolving adapter constants.
load_daemon_env(ROOT)

DAEMON_API = os.environ.get("DAEMON_API_URL", "http://127.0.0.1:8000")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
TELEGRAM_ADAPTER_HOST = str(os.environ.get("TELEGRAM_ADAPTER_HOST", "127.0.0.1") or "127.0.0.1").strip()
TELEGRAM_ADAPTER_ALLOW_REMOTE = str(
    os.environ.get("TELEGRAM_ADAPTER_ALLOW_REMOTE", "0") or "0"
).strip().lower() in {"1", "true", "yes", "on"}


def _parse_allowed_users(raw: str) -> set[int]:
    out: set[int] = set()
    for uid in raw.split(","):
        token = uid.strip()
        if token.isdigit():
            out.add(int(token))
    return out


# Allowed Telegram user IDs (comma-separated). Empty is unsafe and rejected in secure mode.
ALLOWED_USERS = _parse_allowed_users(os.environ.get("TELEGRAM_ALLOWED_USERS", ""))

# Per-user dialog session cache: {user_id: session_id}
_sessions: dict[int, str] = {}

# Pending plan confirmation store: {user_id: plan}
_pending_plans: dict[int, dict] = {}

# Pending rating store: {callback_prefix: task_id} — e.g. "rate:abc123" → task_id
# Also tracks which task_ids are awaiting optional comment after star rating.
_awaiting_comment: dict[int, dict] = {}  # {user_id: {"task_id": ..., "score": ...}}

app = FastAPI(title="Daemon Telegram Adapter")


def _daemon_home() -> Path:
    env = os.environ.get("DAEMON_HOME")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _log_telegram_event(event: str, payload: dict[str, Any]) -> None:
    rec = {
        "event": event,
        "payload": payload,
        "source": "telegram",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        _append_jsonl(_daemon_home() / "state" / "telemetry" / "telegram_events.jsonl", rec)
    except Exception as exc:
        logger.warning("Failed to write telegram telemetry: %s", exc)


def _tg_api(method: str, payload: dict) -> dict:
    """Call Telegram Bot API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    r = httpx.post(url, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def _send_message(chat_id: int, text: str, parse_mode: str = "Markdown") -> None:
    """Send a Telegram message, splitting if > 4096 chars."""
    limit = 4000
    while text:
        chunk, text = text[:limit], text[limit:]
        try:
            _tg_api("sendMessage", {"chat_id": chat_id, "text": chunk, "parse_mode": parse_mode})
        except Exception as e:
            logger.warning(f"Failed to send Telegram message: {e}")


def _get_session(user_id: int) -> str:
    """Return existing or create new Daemon dialog session for user."""
    if user_id in _sessions:
        return _sessions[user_id]
    try:
        r = httpx.post(f"{DAEMON_API}/chat/session", timeout=10)
        r.raise_for_status()
        sid = r.json()["session_id"]
        _sessions[user_id] = sid
        return sid
    except Exception as e:
        raise RuntimeError(f"Cannot create session: {e}")


def _chat(user_id: int, message: str) -> dict:
    """Forward message to Daemon dialog API."""
    sid = _get_session(user_id)
    r = httpx.post(
        f"{DAEMON_API}/chat/{sid}",
        json={"message": message},
        timeout=90,
    )
    if not r.ok:
        # Session may have expired — create new one and retry once.
        _sessions.pop(user_id, None)
        sid = _get_session(user_id)
        r = httpx.post(
            f"{DAEMON_API}/chat/{sid}",
            json={"message": message},
            timeout=90,
        )
    r.raise_for_status()
    return r.json()


def _submit_plan(plan: dict) -> dict:
    """Submit a plan to the Daemon API."""
    r = httpx.post(f"{DAEMON_API}/submit", json=plan, timeout=30)
    r.raise_for_status()
    return r.json()


def _send_inline(chat_id: int, text: str, keyboard: list[list[dict]], parse_mode: str = "Markdown") -> None:
    """Send a message with an inline keyboard."""
    try:
        _tg_api("sendMessage", {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": {"inline_keyboard": keyboard},
        })
    except Exception as exc:
        logger.warning("Failed to send inline keyboard message: %s", exc)


def _rating_keyboard(task_id: str) -> list[list[dict]]:
    """4-choice inline keyboard matching Portal quick rating."""
    choices = [("超出预期", 5), ("满足需求", 4), ("偏浅了", 2), ("不满意", 1)]
    return [
        [{"text": label, "callback_data": f"rate:{task_id}:{v}"} for label, v in choices[:2]],
        [{"text": label, "callback_data": f"rate:{task_id}:{v}"} for label, v in choices[2:]],
    ]


def _confirm_keyboard(campaign_id: str) -> list[list[dict]]:
    """Build a confirm/cancel inline keyboard for campaign plans."""
    return [[
        {"text": "✓ 确认开始", "callback_data": f"campaign_confirm:{campaign_id}"},
        {"text": "✗ 取消", "callback_data": f"campaign_cancel:{campaign_id}"},
    ]]


def _retry_cancel_keyboard(task_id: str) -> list[list[dict]]:
    """Build a retry/cancel inline keyboard for failed tasks."""
    return [[
        {"text": "↺ 重试", "callback_data": f"task_retry:{task_id}"},
        {"text": "✗ 取消", "callback_data": f"task_cancel:{task_id}"},
    ]]


def _handle_callback_query(cq: dict) -> None:
    """Handle inline keyboard button presses."""
    cq_id: str = cq.get("id", "")
    user_id: int = (cq.get("from") or {}).get("id", 0)
    chat_id: int = ((cq.get("message") or {}).get("chat") or {}).get("id", 0)
    data: str = (cq.get("data") or "").strip()

    if not data or not chat_id:
        return

    _log_telegram_event("callback_query", {"user_id": user_id, "chat_id": chat_id, "data": data})

    # Authorization.
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        try:
            _tg_api("answerCallbackQuery", {"callback_query_id": cq_id, "text": "Access denied."})
        except Exception:
            pass
        return

    parts = data.split(":", 2)
    action = parts[0]

    # ── 1–5 star rating ────────────────────────────────────────────────
    if action == "rate" and len(parts) >= 3:
        task_id, score_str = parts[1], parts[2]
        try:
            score = int(score_str)
        except ValueError:
            score = 3
        try:
            _tg_api("answerCallbackQuery", {"callback_query_id": cq_id, "text": f"{'★' * score} 已记录"})
        except Exception:
            pass
        # Submit rating.
        try:
            httpx.post(
                f"{DAEMON_API}/tasks/{task_id}/feedback",
                json={"source": "telegram", "quick_rating": score},
                timeout=15,
            )
        except Exception as exc:
            logger.warning("Failed to submit rating for task %s: %s", task_id, exc)
        # Store for optional comment.
        _awaiting_comment[user_id] = {"task_id": task_id, "score": score}
        _send_message(chat_id, f"{'★' * score}{'☆' * (5 - score)} 评分已记录。\n可以补充一句评语，或直接继续对话。")
        return

    # ── Campaign confirm ───────────────────────────────────────────────
    if action == "campaign_confirm" and len(parts) >= 2:
        campaign_id = parts[1]
        try:
            _tg_api("answerCallbackQuery", {"callback_query_id": cq_id, "text": "确认中…"})
        except Exception:
            pass
        try:
            resp = httpx.post(f"{DAEMON_API}/campaigns/{campaign_id}/confirm", json={}, timeout=20)
            resp.raise_for_status()
            data_resp = resp.json() if resp.text else {}
            _send_message(chat_id, f"✓ Campaign 已确认，任务已启动：`{data_resp.get('task_id', campaign_id)}`")
        except Exception as exc:
            _log_telegram_event("campaign_confirm_failed", {"chat_id": chat_id, "error": str(exc)[:200]})
            _send_message(chat_id, f"✗ 确认失败：{str(exc)[:200]}")
        return

    # ── Campaign cancel ────────────────────────────────────────────────
    if action == "campaign_cancel" and len(parts) >= 2:
        campaign_id = parts[1]
        try:
            _tg_api("answerCallbackQuery", {"callback_query_id": cq_id, "text": "已取消"})
        except Exception:
            pass
        try:
            httpx.post(f"{DAEMON_API}/campaigns/{campaign_id}/cancel", json={}, timeout=20)
        except Exception as exc:
            logger.warning("Campaign cancel failed %s: %s", campaign_id, exc)
        _send_message(chat_id, f"Campaign `{campaign_id}` 已取消。")
        return

    # ── Task retry ─────────────────────────────────────────────────────
    if action == "task_retry" and len(parts) >= 2:
        task_id = parts[1]
        try:
            _tg_api("answerCallbackQuery", {"callback_query_id": cq_id, "text": "重试中…"})
        except Exception:
            pass
        try:
            resp = httpx.post(f"{DAEMON_API}/tasks/{task_id}/retry", json={}, timeout=20)
            resp.raise_for_status()
            _send_message(chat_id, f"✓ 任务 `{task_id}` 已重新提交。")
        except Exception as exc:
            _send_message(chat_id, f"✗ 重试失败：{str(exc)[:200]}")
        return

    # ── Task cancel ────────────────────────────────────────────────────
    if action == "task_cancel" and len(parts) >= 2:
        task_id = parts[1]
        try:
            _tg_api("answerCallbackQuery", {"callback_query_id": cq_id, "text": "取消中…"})
        except Exception:
            pass
        try:
            resp = httpx.post(f"{DAEMON_API}/tasks/{task_id}/cancel", json={}, timeout=20)
            resp.raise_for_status()
            _send_message(chat_id, f"✓ 任务 `{task_id}` 已取消。")
        except Exception as exc:
            _send_message(chat_id, f"✗ 取消失败：{str(exc)[:200]}")
        return

    # Unknown callback.
    try:
        _tg_api("answerCallbackQuery", {"callback_query_id": cq_id})
    except Exception:
        pass


def _handle_update(update: dict) -> None:
    """Process a single Telegram update."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return

    chat_id: int = msg["chat"]["id"]
    user_id: int = msg["from"]["id"]
    text: str = (msg.get("text") or "").strip()

    if not text:
        return

    _log_telegram_event("message_received", {"chat_id": chat_id, "user_id": user_id, "text_len": len(text)})

    # Authorization check (fail-closed).
    if not ALLOWED_USERS:
        _log_telegram_event("access_denied_unconfigured", {"chat_id": chat_id, "user_id": user_id})
        _send_message(chat_id, "⛔ Adapter not ready: TELEGRAM_ALLOWED_USERS is not configured.")
        return
    if user_id not in ALLOWED_USERS:
        _log_telegram_event("access_denied", {"chat_id": chat_id, "user_id": user_id})
        _send_message(chat_id, "⛔ Access denied.")
        return

    # Built-in commands.
    if text == "/start" or text == "/help":
        _log_telegram_event("command", {"chat_id": chat_id, "user_id": user_id, "cmd": text})
        _send_message(chat_id,
            "*Daemon*\n\n"
            "直接描述任务，系统会规划并确认后执行。\n\n"
            "命令：\n"
            "`/status` — 查看运行中的任务\n"
            "`/outcomes` — 最近的产出\n"
            "`/pause` — 暂停当前任务（等当前步骤完成后暂停）\n"
            "`/reset` — 重置会话\n"
            "`/help` — 此帮助\n\n"
            "评分、确认等操作会通过按钮发起，无需记忆命令。"
        )
        return

    if text == "/reset":
        _log_telegram_event("command", {"chat_id": chat_id, "user_id": user_id, "cmd": text})
        _sessions.pop(user_id, None)
        _awaiting_comment.pop(user_id, None)
        _send_message(chat_id, "✓ 会话已重置。")
        return

    if text == "/pause":
        _log_telegram_event("command", {"chat_id": chat_id, "user_id": user_id, "cmd": text})
        try:
            r = httpx.get(f"{DAEMON_API}/tasks?status=running&limit=1", timeout=10)
            tasks = r.json() if r.ok else []
            if not tasks:
                _send_message(chat_id, "当前没有运行中的任务。")
            else:
                task = tasks[0]
                task_id = task.get("task_id", "")
                resp = httpx.post(f"{DAEMON_API}/tasks/{task_id}/pause", json={}, timeout=15)
                resp.raise_for_status()
                _send_message(chat_id, f"⏸ 任务 `{task_id}` 暂停请求已发送，等待当前步骤完成后暂停。")
        except Exception as exc:
            _log_telegram_event("pause_failed", {"chat_id": chat_id, "error": str(exc)[:200]})
            _send_message(chat_id, f"✗ 暂停失败：{str(exc)[:200]}")
        return

    if text == "/status":
        _log_telegram_event("command", {"chat_id": chat_id, "user_id": user_id, "cmd": text})
        try:
            r = httpx.get(f"{DAEMON_API}/tasks?status=running&limit=10", timeout=10)
            tasks = r.json() if r.ok else []
            if not tasks:
                _send_message(chat_id, "No tasks currently running.")
            else:
                lines = [f"*{len(tasks)} running task(s):*"]
                for t in tasks:
                    lines.append(f"• `{t.get('task_id')}` — {t.get('title') or t.get('task_type') or '?'}")
                _send_message(chat_id, "\n".join(lines))
        except Exception as e:
            _log_telegram_event("status_failed", {"chat_id": chat_id, "user_id": user_id, "error": str(e)[:200]})
            _send_message(chat_id, f"Error: {e}")
        return

    if text == "/outcomes":
        _log_telegram_event("command", {"chat_id": chat_id, "user_id": user_id, "cmd": text})
        try:
            r = httpx.get(f"{DAEMON_API}/outcome?limit=5", timeout=10)
            items = r.json() if r.ok else []
            if not items:
                _send_message(chat_id, "No outcomes yet.")
            else:
                lines = [f"*Recent outcomes ({len(items)}):*"]
                for o in items:
                    ts = (o.get("delivered_utc") or o.get("archived_utc") or "")[:10]
                    lines.append(f"• {o.get('title') or o.get('task_id')} — {ts}")
                _send_message(chat_id, "\n".join(lines))
        except Exception as e:
            _log_telegram_event("outcomes_failed", {"chat_id": chat_id, "user_id": user_id, "error": str(e)[:200]})
            _send_message(chat_id, f"Error: {e}")
        return

    if text.startswith("/campaign_feedback"):
        _log_telegram_event("command", {"chat_id": chat_id, "user_id": user_id, "cmd": "campaign_feedback"})
        parts = text.split(maxsplit=4)
        if len(parts) < 4:
            _send_message(chat_id, "Usage: /campaign_feedback <campaign_id> <milestone_idx> <yes|no> [comment]")
            return
        campaign_id = parts[1].strip()
        try:
            milestone_idx = int(parts[2].strip())
        except Exception:
            _send_message(chat_id, "milestone_idx must be an integer")
            return
        verdict = parts[3].strip().lower()
        comment = parts[4].strip() if len(parts) > 4 else ""
        satisfied = verdict in {"yes", "y", "ok", "pass", "1", "满意"}
        payload = {
            "source": "telegram",
            "feedback": {
                "satisfied": satisfied,
                "rating": 5 if satisfied else 2,
                "comment": comment,
                "raw_verdict": verdict,
            },
        }
        try:
            resp = httpx.post(
                f"{DAEMON_API}/campaigns/{campaign_id}/milestones/{milestone_idx}/feedback",
                json=payload,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json() if resp.text else {}
            if bool(data.get("accepted")):
                _send_message(chat_id, f"✓ Feedback accepted: {campaign_id} milestone {milestone_idx}")
            else:
                _send_message(chat_id, f"ℹ️ Feedback recorded as late: {campaign_id} milestone {milestone_idx}")
        except Exception as e:
            _log_telegram_event("campaign_feedback_failed", {"chat_id": chat_id, "user_id": user_id, "error": str(e)[:200]})
            _send_message(chat_id, f"✗ campaign feedback failed: {str(e)[:200]}")
        return

    if text.startswith("/campaign_confirm"):
        _log_telegram_event("command", {"chat_id": chat_id, "user_id": user_id, "cmd": "campaign_confirm"})
        parts = text.split(maxsplit=1)
        if len(parts) < 2:
            _send_message(chat_id, "Usage: /campaign_confirm <campaign_id>")
            return
        campaign_id = parts[1].strip()
        try:
            resp = httpx.post(
                f"{DAEMON_API}/campaigns/{campaign_id}/confirm",
                json={},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json() if resp.text else {}
            _send_message(chat_id, f"✓ campaign confirmed: {campaign_id}\nresume task: `{data.get('task_id','')}`")
        except Exception as e:
            _log_telegram_event("campaign_confirm_failed", {"chat_id": chat_id, "user_id": user_id, "error": str(e)[:200]})
            _send_message(chat_id, f"✗ campaign confirm failed: {str(e)[:200]}")
        return

    # Optional comment after star rating.
    if user_id in _awaiting_comment and not text.startswith("/"):
        ctx = _awaiting_comment.pop(user_id)
        task_id = ctx["task_id"]
        score = ctx["score"]
        try:
            httpx.post(
                f"{DAEMON_API}/tasks/{task_id}/feedback",
                json={"source": "telegram", "quick_rating": score, "comment": text},
                timeout=15,
            )
            _log_telegram_event("feedback_comment_ok", {"chat_id": chat_id, "task_id": task_id})
            _send_message(chat_id, "✓ 评语已补充。")
        except Exception as exc:
            logger.warning("Failed to submit feedback comment for task %s: %s", task_id, exc)
            _send_message(chat_id, "✗ 评语提交失败，继续对话不受影响。")
        return

    # Regular chat — forward to dialog service.
    try:
        result = _chat(user_id, text)
        content = result.get("content") or "(no response)"
        _log_telegram_event("chat_ok", {"chat_id": chat_id, "user_id": user_id, "has_plan": bool(result.get("plan"))})

        # Telegram Markdown: convert code fences.
        tg_content = content.replace("```json", "```").replace("```python", "```")

        _send_message(chat_id, tg_content)

        # If plan detected, offer confirmation.
        plan = result.get("plan")
        if plan:
            plan_json = json.dumps(plan, ensure_ascii=False, indent=2)
            _send_message(chat_id,
                f"📋 *Plan detected.* Reply `/confirm` to submit, or continue chatting to refine.\n\n```\n{plan_json[:1000]}\n```"
            )
            _sessions[user_id] = result.get("session_id") or _sessions.get(user_id, "")
            # Stash plan for confirmation.
            _pending_plans[user_id] = plan

    except Exception as e:
        logger.error(f"Chat error for user {user_id}: {e}")
        _log_telegram_event("chat_failed", {"chat_id": chat_id, "user_id": user_id, "error": str(e)[:200]})
        _send_message(chat_id, f"⚠️ Error: {str(e)[:200]}")


@app.post("/webhook")
async def webhook(request: Request):
    """Receive Telegram webhook updates."""
    # Verify secret token (mandatory).
    if not TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="webhook_secret_not_configured")
    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(header_secret, TELEGRAM_WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="invalid secret")

    body = await request.body()
    try:
        update = json.loads(body)
    except Exception:
        return JSONResponse({"ok": True})

    # Route callback_query (inline keyboard button presses).
    if update.get("callback_query"):
        try:
            _handle_callback_query(update["callback_query"])
        except Exception as exc:
            logger.error("Unhandled error in callback_query: %s", exc)
        return JSONResponse({"ok": True})

    # Handle /confirm command specially (text fallback for plan confirmation).
    msg = update.get("message") or {}
    user_id = (msg.get("from") or {}).get("id")
    text = (msg.get("text") or "").strip()
    if text == "/confirm" and user_id and user_id in _pending_plans:
        chat_id = msg["chat"]["id"]
        plan = _pending_plans.pop(user_id)
        try:
            result = _submit_plan(plan)
            _log_telegram_event("confirm_ok", {"chat_id": chat_id, "user_id": user_id, "task_id": result.get("task_id", "")})
            _send_message(chat_id, f"✓ 任务已提交。Task ID: `{result.get('task_id')}`")
        except Exception as e:
            _log_telegram_event("confirm_failed", {"chat_id": chat_id, "user_id": user_id, "error": str(e)[:200]})
            _send_message(chat_id, f"✗ 提交失败：{str(e)[:200]}")
        return JSONResponse({"ok": True})

    try:
        _handle_update(update)
    except Exception as e:
        logger.error("Unhandled error in webhook: %s", e)

    return JSONResponse({"ok": True})


@app.post("/notify")
async def notify(request: Request):
    """Internal endpoint: system pushes events here to notify the user via Telegram.

    Expected payload: {"event": "<name>", "payload": {...}}

    Events handled:
      task_started        → 收到任务确认 + 规模
      task_completed      → 完整摘要 + 1-5 评分 inline keyboard
      milestone_done      → milestone 摘要 + 1-5 评分 inline keyboard
      campaign_plan_ready → 计划摘要 + 确认/取消 inline keyboard
      task_failed         → 错误说明 + 重试/取消 inline keyboard
      task_paused         → 暂停通知
      skill_evolution_digest → proposals 摘要
    """
    # Only allow calls from localhost.
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="notify_localhost_only")

    body = await request.body()
    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")

    event = str(data.get("event") or "").strip()
    payload = data.get("payload") or {}

    if not BOT_TOKEN:
        return JSONResponse({"ok": False, "error": "bot_token_missing"})

    # Resolve the primary chat_id — use TELEGRAM_CHAT_ID env var.
    raw_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not raw_chat_id or not raw_chat_id.lstrip("-").isdigit():
        return JSONResponse({"ok": False, "error": "TELEGRAM_CHAT_ID_not_configured"})
    chat_id = int(raw_chat_id)

    _log_telegram_event(f"notify_{event}", {"event": event, "payload_keys": list(payload.keys())})

    if event == "task_started":
        task_id = str(payload.get("task_id") or "")
        title = str(payload.get("title") or payload.get("task_type") or "任务")
        scale = str(payload.get("task_scale") or "thread")
        _send_message(chat_id, f"📥 *{title}*\n已收到，规模：{scale}。`{task_id}`")

    elif event == "task_completed":
        task_id = str(payload.get("task_id") or "")
        title = str(payload.get("title") or payload.get("task_type") or "任务")
        summary = str(payload.get("summary") or payload.get("content") or "")
        score = payload.get("score")
        score_str = f"\n系统自评：{round(float(score), 2)}" if score is not None else ""
        msg = f"✅ *{title}*\n\n{summary[:1200]}{score_str}\n\n请评分："
        _send_inline(chat_id, msg, _rating_keyboard(task_id))

    elif event == "milestone_done":
        campaign_id = str(payload.get("campaign_id") or "")
        milestone_idx = payload.get("milestone_idx", 0)
        title = str(payload.get("milestone_title") or f"Milestone {milestone_idx}")
        summary = str(payload.get("summary") or "")
        task_id = str(payload.get("task_id") or campaign_id)
        msg = f"📍 *{title}*（Campaign milestone {milestone_idx}）\n\n{summary[:1200]}\n\n请评分："
        _send_inline(chat_id, msg, _rating_keyboard(task_id))

    elif event == "campaign_plan_ready":
        campaign_id = str(payload.get("campaign_id") or "")
        title = str(payload.get("title") or "Campaign")
        plan_summary = str(payload.get("plan_summary") or json.dumps(payload.get("plan") or {}, ensure_ascii=False)[:800])
        msg = f"📋 *{title}* — Campaign 计划已就绪\n\n{plan_summary[:1200]}"
        _send_inline(chat_id, msg, _confirm_keyboard(campaign_id))

    elif event == "task_failed":
        task_id = str(payload.get("task_id") or "")
        title = str(payload.get("title") or payload.get("task_type") or "任务")
        error = str(payload.get("error") or payload.get("last_error") or "未知错误")
        msg = f"❌ *{title}* 失败\n\n{error[:600]}"
        _send_inline(chat_id, msg, _retry_cancel_keyboard(task_id))

    elif event == "task_paused":
        task_id = str(payload.get("task_id") or "")
        title = str(payload.get("title") or "任务")
        _send_message(chat_id, f"⏸ *{title}* 已暂停 (`{task_id}`)\n发送任意消息或 /resume 继续。")

    elif event == "skill_evolution_digest":
        proposals = payload.get("proposals") or []
        count = len(proposals)
        lines = [f"🔧 *Skills 升级提案（{count} 条）*"]
        for p in proposals[:8]:
            lines.append(f"• `{p.get('skill_name','?')}` — {str(p.get('title') or p.get('summary',''))[:80]}")
        if count > 8:
            lines.append(f"…及另外 {count - 8} 条，在 Console 查看。")
        _send_message(chat_id, "\n".join(lines))

    else:
        _log_telegram_event("notify_unknown_event", {"event": event})
        return JSONResponse({"ok": False, "error": f"unknown_event:{event}"})

    return JSONResponse({"ok": True, "event": event})


@app.get("/health")
def health():
    return {
        "ok": True,
        "bot": bool(BOT_TOKEN),
        "daemon_api": DAEMON_API,
        "webhook_secret_configured": bool(TELEGRAM_WEBHOOK_SECRET),
        "allowed_users_count": len(ALLOWED_USERS),
        "bind_host": TELEGRAM_ADAPTER_HOST,
    }


def register_webhook(url: str) -> None:
    """Register this adapter's webhook URL with Telegram."""
    payload: dict[str, Any] = {"url": url}
    if TELEGRAM_WEBHOOK_SECRET:
        payload["secret_token"] = TELEGRAM_WEBHOOK_SECRET
    result = _tg_api("setWebhook", payload)
    logger.info(f"Webhook registered: {result}")


def _security_issues() -> list[str]:
    issues: list[str] = []
    if not BOT_TOKEN:
        issues.append("TELEGRAM_BOT_TOKEN missing")
    if not TELEGRAM_WEBHOOK_SECRET:
        issues.append("TELEGRAM_WEBHOOK_SECRET missing")
    if not ALLOWED_USERS:
        issues.append("TELEGRAM_ALLOWED_USERS missing/empty")
    host_lower = TELEGRAM_ADAPTER_HOST.lower()
    is_local = host_lower in {"127.0.0.1", "::1", "localhost"}
    if not is_local and not TELEGRAM_ADAPTER_ALLOW_REMOTE:
        issues.append(
            "TELEGRAM_ADAPTER_HOST is not loopback; set TELEGRAM_ADAPTER_ALLOW_REMOTE=1 only if intentional"
        )
    return issues


if __name__ == "__main__":
    import sys
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if len(sys.argv) > 1 and sys.argv[1] == "register":
        webhook_url = sys.argv[2] if len(sys.argv) > 2 else ""
        if not webhook_url:
            print("Usage: python adapter.py register <webhook_url>")
            sys.exit(1)
        register_webhook(webhook_url)
    else:
        issues = _security_issues()
        if issues:
            for item in issues:
                logger.error("Telegram adapter secure-mode check failed: %s", item)
            sys.exit(2)
        port = int(os.environ.get("TELEGRAM_ADAPTER_PORT", "8001"))
        uvicorn.run(app, host=TELEGRAM_ADAPTER_HOST, port=port, reload=False)
