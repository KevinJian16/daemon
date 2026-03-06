"""Telegram Adapter — pure push notifier for Daemon.

Design constraints:
1. Telegram is notification-only.
2. No user commands, no callback handlers, no plan confirmation in Telegram.
3. All user operations happen in Portal.
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


def _run_title(payload: dict[str, Any]) -> str:
    return str(payload.get("run_title") or payload.get("title") or payload.get("run_type") or "运行")


def _notify_text(event: str, payload: dict[str, Any]) -> str:
    def _title() -> str:
        return _run_title(payload)

    if event == "run_started":
        scale = str(payload.get("work_scale") or "thread").strip().lower()
        if scale == "pulse":
            return f'Pulse 已开始 · "{_title()}"'
        if scale == "campaign":
            return f'Campaign 已开始 · "{_title()}"'
        return f'Thread 已开始 · "{_title()}"'

    if event == "run_completed":
        scale = str(payload.get("work_scale") or "thread").strip().lower()
        if str(payload.get("circuit_id") or "").strip():
            return f'Circuit 实例完成 · "{_title()}" · 请去 Portal 评价'
        if scale == "pulse":
            return f'Pulse 完成 · "{_title()}" · 请去 Portal 评价'
        if scale == "campaign":
            return f'Campaign 完成 · "{_title()}" · 请去 Portal 查看'
        return f'Thread 完成 · "{_title()}" · 请去 Portal 评价'

    if event == "run_failed":
        error = str(payload.get("error") or payload.get("last_error") or "未知错误")
        return f'运行失败 · "{_title()}" · {error[:160]}'

    if event == "milestone_done":
        idx = payload.get("milestone_idx", "?")
        return f'Campaign 里程碑 {idx} 完成 · "{_title()}" · 请去 Portal 查看'

    if event == "campaign_plan_ready":
        return f'Campaign 计划已生成 · "{_title()}" · 请去 Portal 确认'

    if event == "run_paused":
        return f'运行已暂停 · "{_title()}" · 请去 Portal 继续'

    if event == "skill_evolution_digest":
        proposals = payload.get("proposals") if isinstance(payload.get("proposals"), list) else []
        return f"Skill Evolution 提案累计 {len(proposals)} 条 · 请去 Portal 查看"

    if event == "campaign_auto_advanced":
        idx = payload.get("milestone_idx", "?")
        return f'Campaign 里程碑已自动推进（无操作）· "{_title()}"'

    if event == "campaign_status":
        status = str(payload.get("campaign_status") or "").strip().lower()
        phase = str(payload.get("campaign_phase") or "").strip().lower()
        idx = int(payload.get("current_milestone_index") or 0)
        if status == "awaiting_intervention" or phase == "milestone_failed":
            return f'Campaign 里程碑失败 · "{_title()}" · 请去 Portal 处理'
        if status == "completed" or phase == "finished":
            return f'Campaign 完成 · "{_title()}" · 请去 Portal 查看'
        return f'Campaign 状态更新 · "{_title()}" · milestone {idx}'

    if event == "feedback_survey":
        return f'请评价本次结果 · "{_title()}" · 请去 Portal 处理'

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
    # Webhook is accepted only to acknowledge updates; user input is ignored by design.
    if TELEGRAM_WEBHOOK_SECRET:
        header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(header_secret, TELEGRAM_WEBHOOK_SECRET):
            raise HTTPException(status_code=403, detail="invalid_secret")
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    update_id = payload.get("update_id")
    _log_telegram_event("webhook_ignored", {"update_id": update_id})
    return JSONResponse({"ok": True, "ignored": True})


@app.get("/health")
def health():
    return {
        "ok": True,
        "bot": bool(BOT_TOKEN),
        "daemon_api": DAEMON_API,
        "webhook_secret_configured": bool(TELEGRAM_WEBHOOK_SECRET),
        "bind_host": TELEGRAM_ADAPTER_HOST,
        "mode": "push_only",
    }


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run("interfaces.telegram.adapter:app", host=TELEGRAM_ADAPTER_HOST, port=8001, reload=False)
