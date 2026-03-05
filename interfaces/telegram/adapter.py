"""Telegram Adapter — webhook listener that forwards messages to Daemon API."""
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
            "*Daemon Portal*\n\n"
            "Talk naturally to submit tasks. When a plan is ready, the Router will show it and you can confirm.\n\n"
            "Commands:\n"
            "`/status` — running tasks\n"
            "`/outcomes` — recent outcomes\n"
            "`/campaign_confirm <campaign_id>` — confirm campaign phase0 plan\n"
            "`/campaign_feedback <campaign_id> <milestone_idx> <yes|no> [comment]` — submit campaign milestone feedback\n"
            "`/reset` — start new session\n"
            "`/help` — this message"
        )
        return

    if text == "/reset":
        _log_telegram_event("command", {"chat_id": chat_id, "user_id": user_id, "cmd": text})
        _sessions.pop(user_id, None)
        _send_message(chat_id, "✓ Session reset. Start a new conversation.")
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


# Pending plan confirmation store: {user_id: plan}
_pending_plans: dict[int, dict] = {}


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

    # Handle /confirm command specially.
    msg = update.get("message") or {}
    user_id = (msg.get("from") or {}).get("id")
    text = (msg.get("text") or "").strip()
    if text == "/confirm" and user_id and user_id in _pending_plans:
        chat_id = msg["chat"]["id"]
        plan = _pending_plans.pop(user_id)
        try:
            result = _submit_plan(plan)
            _log_telegram_event("confirm_ok", {"chat_id": chat_id, "user_id": user_id, "task_id": result.get("task_id", "")})
            _send_message(chat_id, f"✓ Plan submitted! Task ID: `{result.get('task_id')}`")
        except Exception as e:
            _log_telegram_event("confirm_failed", {"chat_id": chat_id, "user_id": user_id, "error": str(e)[:200]})
            _send_message(chat_id, f"✗ Submission failed: {str(e)[:200]}")
        return JSONResponse({"ok": True})

    try:
        _handle_update(update)
    except Exception as e:
        logger.error(f"Unhandled error in webhook: {e}")

    return JSONResponse({"ok": True})


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
