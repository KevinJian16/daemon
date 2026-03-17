"""Telegram Adapter — per-scene notification bridge for Daemon.

4 independent bots (one per scene: copilot/instructor/navigator/autopilot).
Events: job_started, job_completed, job_failed.
Command: /status.
Everything else is silently ignored.

Reference: SYSTEM_DESIGN.md §5.4, TODO.md Phase 5.4
"""
from __future__ import annotations

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
load_daemon_env(ROOT)

# Per-scene bot tokens (4 independent bots)
BOT_TOKENS: dict[str, str] = {
    "copilot": os.environ.get("TELEGRAM_BOT_TOKEN_COPILOT", ""),
    "instructor": os.environ.get("TELEGRAM_BOT_TOKEN_INSTRUCTOR", ""),
    "navigator": os.environ.get("TELEGRAM_BOT_TOKEN_NAVIGATOR", ""),
    "autopilot": os.environ.get("TELEGRAM_BOT_TOKEN_AUTOPILOT", ""),
}
# Fallback: single token for backwards compat
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DAEMON_API = os.environ.get("DAEMON_API_URL", "http://127.0.0.1:8100")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
TELEGRAM_ADAPTER_HOST = str(os.environ.get("TELEGRAM_ADAPTER_HOST", "127.0.0.1") or "127.0.0.1").strip()

SUPPORTED_EVENTS = {"job_started", "job_completed", "job_failed"}


def _resolve_bot_token(scene: str = "") -> str:
    """Resolve bot token for a scene. Falls back to single BOT_TOKEN."""
    if scene and BOT_TOKENS.get(scene):
        return BOT_TOKENS[scene]
    return BOT_TOKEN

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


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _log_telegram_event(event: str, payload: dict[str, Any]) -> None:
    rec = {
        "event": event,
        "payload": payload,
        "source": "telegram",
        "created_utc": _utc(),
    }
    try:
        _append_jsonl(_daemon_home() / "state" / "telemetry" / "telegram_events.jsonl", rec)
    except Exception as exc:
        logger.warning("Failed to write telegram telemetry: %s", exc)


def _tg_api(method: str, payload: dict, *, token: str = "") -> dict:
    bot_token = token or BOT_TOKEN
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    r = httpx.post(url, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def _send_message(chat_id: int, text: str, parse_mode: str = "", *, scene: str = "") -> None:
    limit = 3900
    chunks: list[str] = []
    msg = str(text or "")
    while msg:
        chunks.append(msg[:limit])
        msg = msg[limit:]
    if not chunks:
        chunks = [""]
    for chunk in chunks:
        try:
            payload: dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if parse_mode:
                payload["parse_mode"] = parse_mode
            _tg_api("sendMessage", payload, token=_resolve_bot_token(scene))
        except Exception as exc:
            logger.warning("Telegram sendMessage failed: %s", exc)


def _chat_id() -> int:
    raw = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not raw or not raw.lstrip("-").isdigit():
        raise RuntimeError("TELEGRAM_CHAT_ID_not_configured")
    return int(raw)


def _command_allowed(chat_id: int) -> bool:
    configured = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not configured or not configured.lstrip("-").isdigit():
        return True
    return int(configured) == int(chat_id)


def _daemon_request(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[bool, Any]:
    url = f"{DAEMON_API.rstrip('/')}{path}"
    try:
        response = httpx.request(method, url, json=payload, timeout=15)
        data: Any = response.json() if response.content else {}
    except Exception as exc:
        return False, {"error": f"daemon_api_unreachable:{str(exc)[:160]}"}
    if response.status_code >= 300:
        return False, data if isinstance(data, dict) else {"error": f"http_{response.status_code}"}
    return True, data


def _active_jobs() -> list[dict[str, Any]]:
    ok, data = _daemon_request("GET", "/jobs?status=running&limit=20")
    if not ok or not isinstance(data, list):
        return []
    return [
        row for row in data
        if str(row.get("status") or "").lower() == "running"
    ]


def _status_text() -> str:
    ok, status_payload = _daemon_request("GET", "/status")
    system_status = str((status_payload or {}).get("status") or "unknown") if ok else "unreachable"
    active = _active_jobs()
    lines = [f"系统状态：{system_status}"]
    if not active:
        lines.append("当前没有运行中的任务。")
        return "\n".join(lines)
    lines.append("当前任务：")
    for idx, row in enumerate(active[:6], start=1):
        title = str(row.get("title") or row.get("job_id") or "任务")
        lines.append(f"{idx}. {title}")
    return "\n".join(lines)


def _extract_message(update: dict[str, Any]) -> tuple[int, str] | None:
    message = update.get("message") if isinstance(update.get("message"), dict) else {}
    text = str(message.get("text") or "").strip()
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    chat_id = chat.get("id")
    if not text or chat_id is None:
        return None
    try:
        return int(chat_id), text
    except Exception:
        return None


def _task_title(payload: dict[str, Any]) -> str:
    return str(payload.get("title") or payload.get("task_title") or "任务")


def _notify_text(event: str, payload: dict[str, Any]) -> str | None:
    title = _task_title(payload)

    if event == "job_started":
        return f'已开始 · "{title}"'

    if event == "job_completed":
        summary = str(payload.get("summary") or "").strip()
        return f'做好了。\n\n{summary}' if summary else f'做好了 · "{title}"'

    if event == "job_failed":
        error = str(payload.get("error") or "未知错误")
        return f'失败 · "{title}" · {error[:160]}'

    return None


# Per-user scene selection (in-memory, defaults to copilot)
_user_scenes: dict[int, str] = {}


def _get_user_scene(chat_id: int) -> str:
    return _user_scenes.get(chat_id, "copilot")


def _set_user_scene(chat_id: int, scene: str) -> None:
    _user_scenes[chat_id] = scene


async def _forward_to_scene(scene: str, text: str, chat_id: int) -> str:
    """Forward a user message to the daemon scene chat API and return the reply.

    §4.10 Telegram ↔ desktop sync: messages are routed through session_manager
    and stored in PG (conversation_messages) with source="telegram", so they
    appear in the desktop client's conversation view. The daemon API's
    /scenes/{scene}/chat endpoint handles PG persistence via SessionManager.
    """
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{DAEMON_API.rstrip('/')}/scenes/{scene}/chat",
                json={
                    "content": text,
                    "metadata": {
                        "source": "telegram",
                        "telegram_chat_id": chat_id,
                    },
                },
            )
            if resp.status_code >= 400:
                return f"（错误 {resp.status_code}）"
            data = resp.json()
            reply = str(data.get("reply") or data.get("text") or data.get("content") or "")

            # Publish sync event so desktop client receives Telegram messages in real-time
            try:
                await client.post(
                    f"{DAEMON_API.rstrip('/')}/events/publish",
                    json={
                        "event_type": "telegram_message",
                        "payload": {
                            "scene": scene,
                            "telegram_chat_id": chat_id,
                            "user_text": text[:500],
                            "reply_text": reply[:500],
                        },
                    },
                    timeout=5,
                )
            except Exception:
                # Sync event is best-effort; don't fail the Telegram response
                pass

            return reply
    except httpx.TimeoutException:
        return "（请求超时，任务可能仍在执行中）"
    except Exception as exc:
        logger.warning("Forward to scene %s failed: %s", scene, exc)
        return f"（连接失败: {str(exc)[:100]}）"


@app.post("/notify")
async def notify(request: Request):
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(status_code=403, detail="notify_localhost_only")

    body = await request.body()
    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_json")

    event = str(data.get("event") or "").strip()
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    if not event:
        raise HTTPException(status_code=400, detail="event_required")

    if event not in SUPPORTED_EVENTS:
        _log_telegram_event(f"notify_ignored_{event}", {"event": event})
        return JSONResponse({"ok": True, "ignored": True, "reason": "unsupported_event"})

    scene = str(payload.get("scene") or data.get("scene") or "").strip()
    token = _resolve_bot_token(scene)
    if not token:
        return JSONResponse({"ok": False, "error": "bot_token_missing"})

    try:
        chat_id = _chat_id()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})

    msg = _notify_text(event, payload)
    if not msg:
        return JSONResponse({"ok": True, "ignored": True, "reason": "no_message"})

    _send_message(chat_id, msg, scene=scene)
    _log_telegram_event(f"notify_{event}", {"event": event, "payload_keys": list(payload.keys())})
    return JSONResponse({"ok": True, "event": event})


@app.post("/webhook")
async def webhook(request: Request):
    if TELEGRAM_WEBHOOK_SECRET:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(header_secret, TELEGRAM_WEBHOOK_SECRET):
            raise HTTPException(status_code=403, detail="invalid_secret")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    update_id = payload.get("update_id")
    extracted = _extract_message(payload if isinstance(payload, dict) else {})
    if not extracted:
        _log_telegram_event("webhook_ignored", {"update_id": update_id})
        return JSONResponse({"ok": True, "ignored": True})

    chat_id, text = extracted
    if not _command_allowed(chat_id):
        _log_telegram_event("webhook_denied", {"update_id": update_id, "chat_id": chat_id})
        return JSONResponse({"ok": True, "ignored": True})

    _log_telegram_event("webhook_message", {"update_id": update_id, "chat_id": chat_id, "text": text[:120]})

    if text.startswith("/status"):
        _send_message(chat_id, _status_text())
        return JSONResponse({"ok": True, "handled": True, "command": "status"})

    if text.startswith("/scene "):
        # /scene copilot — switch default scene
        parts = text.split(maxsplit=1)
        scene_name = parts[1].strip().lower() if len(parts) > 1 else ""
        if scene_name in ("copilot", "instructor", "navigator", "autopilot"):
            _set_user_scene(chat_id, scene_name)
            _send_message(chat_id, f"已切换到 {scene_name} 场景。")
        else:
            _send_message(chat_id, "可用场景: copilot / instructor / navigator / autopilot")
        return JSONResponse({"ok": True, "handled": True, "command": "scene"})

    # Forward user message to daemon scene chat API
    scene = _get_user_scene(chat_id)
    reply = await _forward_to_scene(scene, text, chat_id)
    if reply:
        _send_message(chat_id, reply, scene=scene)
        _log_telegram_event("webhook_chat", {"update_id": update_id, "scene": scene, "reply_len": len(reply)})
    else:
        _send_message(chat_id, "（无回复）", scene=scene)
        _log_telegram_event("webhook_chat_empty", {"update_id": update_id, "scene": scene})

    return JSONResponse({"ok": True, "handled": True, "scene": scene})


@app.get("/health")
def health():
    return {
        "ok": True,
        "bots": {scene: bool(token) for scene, token in BOT_TOKENS.items()},
        "fallback_bot": bool(BOT_TOKEN),
        "daemon_api": DAEMON_API,
        "webhook_secret_configured": bool(TELEGRAM_WEBHOOK_SECRET),
        "bind_host": TELEGRAM_ADAPTER_HOST,
        "mode": "notify_and_chat",
    }


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run("interfaces.telegram.adapter:app", host=TELEGRAM_ADAPTER_HOST, port=8001, reload=False)
