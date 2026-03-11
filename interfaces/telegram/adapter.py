"""Telegram Adapter — notification-first bridge for Daemon.

Design constraints:
1. Telegram remains notification-first.
2. Only minimal commands are supported: `/status` and `/cancel`.
3. All substantive collaboration still happens in Portal.
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

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DAEMON_API = os.environ.get("DAEMON_API_URL", "http://127.0.0.1:8000")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
TELEGRAM_ADAPTER_HOST = str(os.environ.get("TELEGRAM_ADAPTER_HOST", "127.0.0.1") or "127.0.0.1").strip()
CONTROL_WINDOW_S = 60

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


def _tg_api(method: str, payload: dict) -> dict:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    r = httpx.post(url, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def _send_message(chat_id: int, text: str, parse_mode: str = "") -> None:
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
            _tg_api("sendMessage", payload)
        except Exception as exc:
            logger.warning("Telegram sendMessage failed: %s", exc)


def _chat_id() -> int:
    raw = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not raw or not raw.lstrip("-").isdigit():
        raise RuntimeError("TELEGRAM_CHAT_ID_not_configured")
    return int(raw)


def _control_state_path() -> Path:
    return _daemon_home() / "state" / "telegram_command_state.json"


def _load_control_state() -> dict[str, dict[str, Any]]:
    path = _control_state_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_control_state(state: dict[str, dict[str, Any]]) -> None:
    path = _control_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _prune_control_state(state: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    now = time.time()
    clean: dict[str, dict[str, Any]] = {}
    for key, row in state.items():
        if not isinstance(row, dict):
            continue
        expires_at = float(row.get("expires_at") or 0.0)
        if expires_at and expires_at < now:
            continue
        clean[str(key)] = row
    return clean


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


def _active_deeds() -> list[dict[str, Any]]:
    ok, data = _daemon_request("GET", "/deeds?phase=running&limit=20")
    if not ok or not isinstance(data, list):
        return []
    return [
        row for row in data
        if str(row.get("deed_status") or "").lower() in {"running"}
    ]


def _status_text() -> str:
    ok, status_payload = _daemon_request("GET", "/system/status")
    system_status = str((status_payload or {}).get("status") or "unknown") if ok else "unreachable"
    active = _active_deeds()
    lines = [f"系统状态：{system_status}"]
    if not active:
        lines.append("当前没有运行中的任务。")
        return "\n".join(lines)
    lines.append("当前任务：")
    for idx, row in enumerate(active[:6], start=1):
        title = str(row.get("deed_title") or row.get("title") or row.get("objective") or row.get("deed_id") or "任务")
        lines.append(f"{idx}. {title} [{str(row.get('deed_status') or '')}]")
        lines.append(f"   {str(row.get('deed_id') or '')}")
    return "\n".join(lines)


def _cancel_deed(chat_id: int, deed_id: str) -> None:
    ok, payload = _daemon_request("POST", f"/deeds/{deed_id}/cancel", {})
    if ok:
        _send_message(chat_id, f"已请求取消：{deed_id}")
        _log_telegram_event("cancel_requested", {"chat_id": chat_id, "deed_id": deed_id})
        return
    detail = str((payload or {}).get("detail") or (payload or {}).get("error") or "unknown_error")
    _send_message(chat_id, f"取消失败：{detail}")
    _log_telegram_event("cancel_failed", {"chat_id": chat_id, "deed_id": deed_id, "detail": detail})


def _set_cancel_state(chat_id: int, deeds: list[dict[str, Any]]) -> None:
    state = _prune_control_state(_load_control_state())
    state[str(chat_id)] = {
        "mode": "cancel_select",
        "expires_at": time.time() + CONTROL_WINDOW_S,
        "choices": [
            {
                "deed_id": str(row.get("deed_id") or ""),
                "title": str(row.get("deed_title") or row.get("title") or row.get("objective") or "任务"),
            }
            for row in deeds[:6]
        ],
        "created_utc": _utc(),
    }
    _save_control_state(state)


def _clear_chat_state(chat_id: int) -> None:
    state = _prune_control_state(_load_control_state())
    state.pop(str(chat_id), None)
    _save_control_state(state)


def _handle_cancel_command(chat_id: int, text: str) -> None:
    active = _active_deeds()
    if not active:
        _send_message(chat_id, "当前没有可取消的任务。")
        return

    _, _, raw_arg = text.partition(" ")
    arg = raw_arg.strip()
    if arg:
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(active):
                _cancel_deed(chat_id, str(active[idx].get("deed_id") or ""))
                return
        for row in active:
            deed_id = str(row.get("deed_id") or "")
            if deed_id == arg or deed_id.startswith(arg):
                _cancel_deed(chat_id, deed_id)
                return
        _send_message(chat_id, "没有匹配到任务。请使用 /status 查看当前任务。")
        return

    if len(active) == 1:
        _cancel_deed(chat_id, str(active[0].get("deed_id") or ""))
        return

    _set_cancel_state(chat_id, active)
    lines = ["回复编号以取消对应任务（60秒内有效）："]
    for idx, row in enumerate(active[:6], start=1):
        title = str(row.get("deed_title") or row.get("title") or row.get("objective") or "任务")
        lines.append(f"{idx}. {title}")
    _send_message(chat_id, "\n".join(lines))


def _handle_pending_state(chat_id: int, text: str) -> bool:
    state = _prune_control_state(_load_control_state())
    row = state.get(str(chat_id))
    if not isinstance(row, dict):
        if state != _load_control_state():
            _save_control_state(state)
        return False
    if str(row.get("mode") or "") != "cancel_select":
        return False
    if text.strip().lower() in {"q", "quit", "exit", "取消"}:
        state.pop(str(chat_id), None)
        _save_control_state(state)
        _send_message(chat_id, "已取消本次选择。")
        return True
    if not text.strip().isdigit():
        _send_message(chat_id, "请回复编号，或发送“取消”结束。")
        return True
    idx = int(text.strip()) - 1
    choices = row.get("choices") if isinstance(row.get("choices"), list) else []
    if idx < 0 or idx >= len(choices):
        _send_message(chat_id, "编号无效，请重新发送。")
        return True
    deed_id = str((choices[idx] or {}).get("deed_id") or "")
    state.pop(str(chat_id), None)
    _save_control_state(state)
    if deed_id:
        _cancel_deed(chat_id, deed_id)
    else:
        _send_message(chat_id, "任务信息无效，请重新发送 /cancel。")
    return True


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


def _deed_title(payload: dict[str, Any]) -> str:
    return str(payload.get("deed_title") or payload.get("title") or "任务")


def _notify_text(event: str, payload: dict[str, Any]) -> str:
    def _title() -> str:
        return _deed_title(payload)

    if event == "deed_started":
        return f'已开始 · "{_title()}"'

    if event == "deed_settling":
        summary = str(payload.get("summary") or "").strip()
        portal_link = str(payload.get("portal_link") or "").strip()
        parts = [f'做好了。\n\n{summary}' if summary else f'做好了 · "{_title()}"']
        if portal_link:
            parts.append(f'\n\n完整结果：{portal_link}')
        return "".join(parts)

    if event == "deed_closed":
        sub = str(payload.get("sub_status") or "").strip()
        return f'已关闭 · "{_title()}" · {sub}' if sub else f'已关闭 · "{_title()}"'

    if event == "deed_failed":
        error = str(payload.get("error") or payload.get("last_error") or "未知错误")
        return f'失败 · "{_title()}" · {error[:160]}'

    if event == "passage_completed":
        idx = payload.get("passage_idx", "?")
        return f'阶段 {idx} 完成 · "{_title()}" · 请去 Portal 查看'

    if event == "deed_paused":
        return f'已暂停 · "{_title()}" · 请去 Portal 继续'

    if event == "deed_rework_exhausted":
        return f'需要处理 · "{_title()}" · 请去 Portal 查看'

    if event == "ward_changed":
        ward_status = str(payload.get("ward_status") or "").strip()
        return f'系统状态变化 · Ward: {ward_status}'

    if event == "eval_expiring":
        return f'反馈即将过期 · "{_title()}" · 请去 Portal 评价'

    if event == "skill_evolution_digest":
        proposals = payload.get("proposals") if isinstance(payload.get("proposals"), list) else []
        return f"Skill Evolution 提案累计 {len(proposals)} 条 · 请去 Portal 查看"

    return f'系统通知 · "{_title()}" · {event}'


@app.post("/notify")
async def notify(request: Request):
    # Notifications are only accepted from localhost.
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
    if not BOT_TOKEN:
        return JSONResponse({"ok": False, "error": "bot_token_missing"})

    try:
        chat_id = _chat_id()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)})

    msg = _notify_text(event, payload)
    _send_message(chat_id, msg)
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
    if not text.startswith("/") and _handle_pending_state(chat_id, text):
        return JSONResponse({"ok": True, "handled": True, "mode": "pending"})

    if text.startswith("/status"):
        _clear_chat_state(chat_id)
        _send_message(chat_id, _status_text())
        return JSONResponse({"ok": True, "handled": True, "command": "status"})

    if text.startswith("/cancel"):
        _handle_cancel_command(chat_id, text)
        return JSONResponse({"ok": True, "handled": True, "command": "cancel"})

    _log_telegram_event("webhook_ignored", {"update_id": update_id, "chat_id": chat_id, "reason": "unsupported_message"})
    return JSONResponse({"ok": True, "ignored": True})


@app.get("/health")
def health():
    return {
        "ok": True,
        "bot": bool(BOT_TOKEN),
        "daemon_api": DAEMON_API,
        "webhook_secret_configured": bool(TELEGRAM_WEBHOOK_SECRET),
        "bind_host": TELEGRAM_ADAPTER_HOST,
        "mode": "notify_plus_minimal_commands",
    }


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run("interfaces.telegram.adapter:app", host=TELEGRAM_ADAPTER_HOST, port=8001, reload=False)
