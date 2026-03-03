"""Telegram Adapter — webhook listener that forwards messages to Daemon API."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

DAEMON_API = os.environ.get("DAEMON_API_URL", "http://127.0.0.1:8000")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
# Allowed Telegram user IDs (comma-separated). Empty = allow all.
ALLOWED_USERS = {
    int(uid.strip())
    for uid in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")
    if uid.strip().isdigit()
}

# Per-user dialog session cache: {user_id: session_id}
_sessions: dict[int, str] = {}

app = FastAPI(title="Daemon Telegram Adapter")


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

    # Authorization check.
    if ALLOWED_USERS and user_id not in ALLOWED_USERS:
        _send_message(chat_id, "⛔ Access denied.")
        return

    # Built-in commands.
    if text == "/start" or text == "/help":
        _send_message(chat_id,
            "*Daemon Portal*\n\n"
            "Talk naturally to submit tasks. When a plan is ready, the Router will show it and you can confirm.\n\n"
            "Commands:\n"
            "`/status` — running tasks\n"
            "`/outcomes` — recent outcomes\n"
            "`/reset` — start new session\n"
            "`/help` — this message"
        )
        return

    if text == "/reset":
        _sessions.pop(user_id, None)
        _send_message(chat_id, "✓ Session reset. Start a new conversation.")
        return

    if text == "/status":
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
            _send_message(chat_id, f"Error: {e}")
        return

    if text == "/outcomes":
        try:
            r = httpx.get(f"{DAEMON_API}/outcome?limit=5", timeout=10)
            items = r.json() if r.ok else []
            if not items:
                _send_message(chat_id, "No outcomes yet.")
            else:
                lines = [f"*Recent outcomes ({len(items)}):*"]
                for o in items:
                    lines.append(f"• {o.get('title') or o.get('task_id')} — {(o.get('archived_utc') or '')[:10]}")
                _send_message(chat_id, "\n".join(lines))
        except Exception as e:
            _send_message(chat_id, f"Error: {e}")
        return

    # Regular chat — forward to dialog service.
    try:
        result = _chat(user_id, text)
        content = result.get("content") or "(no response)"

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
        _send_message(chat_id, f"⚠️ Error: {str(e)[:200]}")


# Pending plan confirmation store: {user_id: plan}
_pending_plans: dict[int, dict] = {}


@app.post("/webhook")
async def webhook(request: Request):
    """Receive Telegram webhook updates."""
    # Verify secret token if configured.
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    if secret:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(header_secret, secret):
            raise HTTPException(status_code=403, detail="invalid secret")

    body = await request.body()
    try:
        update = json.loads(body)
    except Exception:
        return JSONResponse({"ok": True})

    # Handle /confirm command specially.
    msg = update.get("message") or {}
    user_id = (msg.get("from") or {}).get("id")
    text = (msg.get("text") or "").strip()
    if text == "/confirm" and user_id and user_id in _pending_plans:
        chat_id = msg["chat"]["id"]
        plan = _pending_plans.pop(user_id)
        try:
            result = _submit_plan(plan)
            _send_message(chat_id, f"✓ Plan submitted! Task ID: `{result.get('task_id')}`")
        except Exception as e:
            _send_message(chat_id, f"✗ Submission failed: {str(e)[:200]}")
        return JSONResponse({"ok": True})

    try:
        _handle_update(update)
    except Exception as e:
        logger.error(f"Unhandled error in webhook: {e}")

    return JSONResponse({"ok": True})


@app.get("/health")
def health():
    return {"ok": True, "bot": bool(BOT_TOKEN), "daemon_api": DAEMON_API}


def register_webhook(url: str) -> None:
    """Register this adapter's webhook URL with Telegram."""
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    payload: dict[str, Any] = {"url": url}
    if secret:
        payload["secret_token"] = secret
    result = _tg_api("setWebhook", payload)
    logger.info(f"Webhook registered: {result}")


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
        port = int(os.environ.get("TELEGRAM_ADAPTER_PORT", "8001"))
        uvicorn.run("adapter:app", host="0.0.0.0", port=port, reload=False)
