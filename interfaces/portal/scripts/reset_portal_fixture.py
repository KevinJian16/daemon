from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.storage_paths import resolve_offering_root


STATE_DIR = REPO_ROOT / "state"
DEEDS_DIR = STATE_DIR / "deeds"
OFFERING_ROOT = resolve_offering_root(STATE_DIR)


SLIPS = [
    {
        "slip_id": "slip_0b5eba259a65",
        "folio_id": "folio_8c3f55e7cdc0",
        "title": "整理项目周报",
        "slug": "整理项目周报",
        "slug_history": [],
        "objective": "汇总本周项目进展，并生成一份对外可读的摘要。",
        "brief": {"objective": "汇总本周项目进展，并生成一份对外可读的摘要。"},
        "design": {
            "moves": [
                {"id": "move_collect", "instruction": "搜集本周进展", "agent": "scout"},
                {"id": "move_write", "instruction": "整理周报结构", "agent": "scribe"},
                {"id": "move_polish", "instruction": "润色结论", "agent": "critic"},
            ]
        },
        "status": "active",
        "sub_status": "normal",
        "standing": False,
        "trigger_type": "manual",
        "latest_deed_id": "deed_demo_closed",
        "deed_ids": ["deed_demo_closed"],
        "created_utc": "2026-03-12T14:31:31Z",
        "updated_utc": "2026-03-12T14:31:31Z",
    },
    {
        "slip_id": "slip_3fec6fab61c5",
        "folio_id": "folio_8c3f55e7cdc0",
        "title": "跟进阻塞项",
        "slug": "跟进阻塞项",
        "slug_history": [],
        "objective": "根据周报里暴露的问题，继续拆出阻塞项并生成跟进清单。",
        "brief": {"objective": "根据周报里暴露的问题，继续拆出阻塞项并生成跟进清单。"},
        "design": {
            "moves": [
                {"id": "move_pick", "instruction": "识别阻塞项", "agent": "scout"},
                {"id": "move_split", "instruction": "拆出跟进动作", "agent": "planner"},
                {"id": "move_export", "instruction": "输出清单", "agent": "scribe"},
            ]
        },
        "status": "active",
        "sub_status": "normal",
        "standing": False,
        "trigger_type": "writ_chain",
        "latest_deed_id": "deed_demo_running",
        "deed_ids": ["deed_demo_running"],
        "created_utc": "2026-03-12T14:31:31Z",
        "updated_utc": "2026-03-12T14:31:31Z",
    },
    {
        "slip_id": "slip_4517dbdb421f",
        "folio_id": "folio_1daa1a3b0e76",
        "title": "晨间巡检摘要",
        "slug": "晨间巡检摘要",
        "slug_history": [],
        "objective": "每天早上生成一份简短巡检摘要。",
        "brief": {"objective": "每天早上生成一份简短巡检摘要。"},
        "design": {
            "moves": [
                {"id": "move_scan", "instruction": "读取昨日日志", "agent": "scout"},
                {"id": "move_digest", "instruction": "整理巡检摘要", "agent": "scribe"},
            ]
        },
        "status": "active",
        "sub_status": "normal",
        "standing": True,
        "trigger_type": "timer",
        "latest_deed_id": "",
        "deed_ids": [],
        "created_utc": "2026-03-12T14:31:31Z",
        "updated_utc": "2026-03-12T14:31:31Z",
    },
    {
        "slip_id": "slip_42508e971cfe",
        "slug": "准备客户回访问题",
        "title": "准备客户回访问题",
        "objective": "整理客户回访前要确认的四个问题，先放在案头。",
        "brief": {"objective": "整理客户回访前要确认的四个问题，先放在案头。"},
        "design": {
            "moves": [
                {"id": "move_collect", "instruction": "收集现有分歧"},
                {"id": "move_order", "instruction": "排出问题顺序"},
            ]
        },
        "status": "active",
        "sub_status": "",
        "standing": False,
        "trigger_type": "manual",
        "latest_deed_id": "",
        "deed_ids": [],
        "folio_id": None,
        "created_utc": "2026-03-12T15:38:52Z",
        "updated_utc": "2026-03-12T15:38:52Z",
    },
    {
        "slip_id": "slip_29eb2c935392",
        "slug": "整理部署检查项",
        "title": "整理部署检查项",
        "objective": "把部署前的检查项收成一张散札，暂时不入卷。",
        "brief": {"objective": "把部署前的检查项收成一张散札，暂时不入卷。"},
        "design": {
            "moves": [
                {"id": "move_scan", "instruction": "读取检查项来源"},
                {"id": "move_shape", "instruction": "压成执行清单"},
            ]
        },
        "status": "active",
        "sub_status": "",
        "standing": False,
        "trigger_type": "manual",
        "latest_deed_id": "",
        "deed_ids": [],
        "folio_id": None,
        "created_utc": "2026-03-12T15:38:52Z",
        "updated_utc": "2026-03-12T15:38:52Z",
    },
]

FOLIOS = [
    {
        "folio_id": "folio_8c3f55e7cdc0",
        "title": "周报推进",
        "slug": "周报推进",
        "slug_history": [],
        "summary": "把本周几个相关签札收在同一卷里。",
        "status": "active",
        "sub_status": "normal",
        "slip_ids": ["slip_3fec6fab61c5", "slip_0b5eba259a65"],
        "writ_ids": ["writ_68c304e4385a"],
        "created_utc": "2026-03-12T14:31:31Z",
        "updated_utc": "2026-03-12T14:31:31Z",
    },
    {
        "folio_id": "folio_1daa1a3b0e76",
        "title": "晨间巡检摘要",
        "slug": "晨间巡检摘要",
        "slug_history": [],
        "summary": "每天早上生成一份简短巡检摘要。",
        "status": "active",
        "sub_status": "normal",
        "slip_ids": ["slip_4517dbdb421f"],
        "writ_ids": ["writ_f3b18373693c"],
        "created_utc": "2026-03-12T14:31:31Z",
        "updated_utc": "2026-03-12T14:31:31Z",
    },
]

WRITS = [
    {
        "writ_id": "writ_68c304e4385a",
        "folio_id": "folio_8c3f55e7cdc0",
        "title": "周报收束后继续跟进",
        "match": {"event": "deed_closed", "filter": {"slip_id": "slip_0b5eba259a65"}},
        "action": {"type": "spawn_deed", "slip_id": "slip_3fec6fab61c5"},
        "status": "active",
        "priority": 100,
        "suppression": {},
        "version": 1,
        "deed_history": [],
        "last_triggered_utc": "",
        "created_utc": "2026-03-12T14:31:31Z",
        "updated_utc": "2026-03-12T14:31:31Z",
    },
    {
        "writ_id": "writ_f3b18373693c",
        "folio_id": "folio_1daa1a3b0e76",
        "title": "晨间巡检节律",
        "match": {"schedule": "0 9 * * 1-5"},
        "action": {"type": "spawn_deed", "slip_id": "slip_4517dbdb421f"},
        "status": "active",
        "priority": 100,
        "suppression": {},
        "version": 1,
        "deed_history": [],
        "last_triggered_utc": "",
        "created_utc": "2026-03-12T14:31:31Z",
        "updated_utc": "2026-03-12T14:31:31Z",
    },
]

DRAFTS = [
    {
        "draft_id": "draft_b2e43d25b2ab",
        "source": "chat",
        "folio_id": None,
        "seed_event": {},
        "intent_snapshot": "补写下周例会要问的三个问题，并收成一张能继续跟进的札。",
        "candidate_brief": {"objective": "补写下周例会要问的三个问题，并收成一张能继续跟进的札。"},
        "candidate_design": {
            "moves": [
                {"id": "move_collect", "instruction": "收集现有问题"},
                {"id": "move_shape", "instruction": "压成三条问题"},
            ]
        },
        "status": "drafting",
        "sub_status": "open",
        "created_utc": "2026-03-12T15:06:42Z",
        "updated_utc": "2026-03-12T15:06:42Z",
    },
    {
        "draft_id": "draft_2cc314e2dfb6",
        "source": "chat",
        "folio_id": "folio_8c3f55e7cdc0",
        "seed_event": {},
        "intent_snapshot": "给周报补一段风险提醒，语气克制一些，最后看能不能直接成札。",
        "candidate_brief": {"objective": "给周报补一段风险提醒，语气克制一些，最后看能不能直接成札。"},
        "candidate_design": {
            "moves": [
                {"id": "move_read", "instruction": "读取周报上下文"},
                {"id": "move_write", "instruction": "补写风险提醒"},
            ]
        },
        "status": "drafting",
        "sub_status": "refining",
        "created_utc": "2026-03-12T15:06:42Z",
        "updated_utc": "2026-03-12T15:06:42Z",
    },
]

DEEDS = [
    {
        "deed_id": "deed_demo_closed",
        "slip_id": "slip_0b5eba259a65",
        "folio_id": "folio_8c3f55e7cdc0",
        "deed_status": "closed",
        "deed_sub_status": "succeeded",
        "phase": "history",
        "created_utc": "2026-03-12T04:30:00Z",
        "updated_utc": "2026-03-12T05:10:00Z",
        "started_utc": "2026-03-12T04:30:00Z",
        "settled_utc": "2026-03-12T05:10:00Z",
        "deed_title": "整理项目周报",
        "plan": {
            "title": "整理项目周报",
            "brief": {"objective": "汇总本周项目进展，并生成一份对外可读的摘要。"},
            "moves": [
                {"id": "move_collect", "instruction": "搜集本周进展", "agent": "scout"},
                {"id": "move_write", "instruction": "整理周报结构", "agent": "scribe"},
                {"id": "move_polish", "instruction": "润色结论", "agent": "critic"},
            ],
            "move_results": [
                {"move_id": "move_collect", "ok": True},
                {"move_id": "move_write", "ok": True},
                {"move_id": "move_polish", "ok": True},
            ],
            "plan_display": {
                "timeline": [
                    {"id": "move_collect", "label": "搜集本周进展", "agent": "scout"},
                    {"id": "move_write", "label": "整理周报结构", "agent": "scribe"},
                    {"id": "move_polish", "label": "润色结论", "agent": "critic"},
                ]
            },
            "metadata": {"slip_id": "slip_0b5eba259a65", "folio_id": "folio_8c3f55e7cdc0"},
        },
    },
    {
        "deed_id": "deed_demo_running",
        "slip_id": "slip_3fec6fab61c5",
        "folio_id": "folio_8c3f55e7cdc0",
        "deed_status": "running",
        "deed_sub_status": "executing",
        "phase": "running",
        "created_utc": "2026-03-12T21:58:00Z",
        "updated_utc": "2026-03-12T22:27:00Z",
        "started_utc": "2026-03-12T21:59:00Z",
        "deed_title": "跟进阻塞项",
        "plan": {
            "title": "跟进阻塞项",
            "brief": {"objective": "根据周报里暴露的问题，继续拆出阻塞项并生成跟进清单。"},
            "moves": [
                {"id": "move_pick", "instruction": "识别阻塞项", "agent": "scout"},
                {"id": "move_split", "instruction": "拆出跟进动作", "agent": "planner"},
                {"id": "move_export", "instruction": "输出清单", "agent": "scribe"},
            ],
            "move_results": [{"move_id": "move_pick", "ok": True}],
            "plan_display": {
                "timeline": [
                    {"id": "move_pick", "label": "识别阻塞项", "agent": "scout"},
                    {"id": "move_split", "label": "拆出跟进动作", "agent": "planner"},
                    {"id": "move_export", "label": "输出清单", "agent": "scribe"},
                ]
            },
            "metadata": {"slip_id": "slip_3fec6fab61c5", "folio_id": "folio_8c3f55e7cdc0"},
        },
    },
]

CLOSED_MESSAGES = [
    {"deed_id": "deed_demo_closed", "role": "user", "content": "把这周推进整理成一页摘要。", "event": "user_message", "created_utc": "2026-03-12T04:30:00Z", "meta": {"source": "portal"}},
    {"deed_id": "deed_demo_closed", "role": "system", "content": "[操作] 执行", "event": "operation", "created_utc": "2026-03-12T04:32:00Z", "meta": {"action": "执行"}},
    {"deed_id": "deed_demo_closed", "role": "assistant", "content": "开始处理：搜集本周进展", "event": "deed_progress", "created_utc": "2026-03-12T04:34:00Z", "meta": {"move_id": "move_collect"}},
    {"deed_id": "deed_demo_closed", "role": "assistant", "content": "周报摘要已经整理好，重点风险集中在发布节奏与依赖协同。", "event": "assistant_message", "created_utc": "2026-03-12T05:09:00Z", "meta": {}},
    {"deed_id": "deed_demo_closed", "role": "system", "content": "[操作] 收束", "event": "operation", "created_utc": "2026-03-12T05:10:00Z", "meta": {"action": "收束"}},
]

RUNNING_MESSAGES = [
    {"deed_id": "deed_demo_running", "role": "system", "content": "[操作] 重新执行：跟进阻塞项", "event": "operation", "created_utc": "2026-03-12T21:58:00Z", "meta": {"action": "重新执行"}},
    {"deed_id": "deed_demo_running", "role": "user", "content": "继续沿着周报里提到的阻塞项，拆成明确跟进行动。", "event": "user_message", "created_utc": "2026-03-12T21:59:00Z", "meta": {"source": "portal"}},
    {"deed_id": "deed_demo_running", "role": "assistant", "content": "开始处理：识别阻塞项", "event": "deed_progress", "created_utc": "2026-03-12T22:01:00Z", "meta": {"move_id": "move_pick"}},
    {"deed_id": "deed_demo_running", "role": "assistant", "content": "已完成：识别阻塞项", "event": "deed_progress", "created_utc": "2026-03-12T22:19:00Z", "meta": {"move_id": "move_pick"}},
    {"deed_id": "deed_demo_running", "role": "assistant", "content": "正在等待结果：拆出跟进动作", "event": "deed_progress", "created_utc": "2026-03-12T22:27:00Z", "meta": {"move_id": "move_split"}},
]

HERALD_LOG = {
    "path": "2026-03/20260312 周报摘要",
    "title": "周报摘要",
    "deed_id": "deed_demo_closed",
    "slip_id": "slip_0b5eba259a65",
    "folio_id": "folio_8c3f55e7cdc0",
    "delivered_utc": "2026-03-12T05:10:00Z",
}

OFFERING_TEXT = """# 周报摘要

- 本周推进已整理完成
- 风险集中在发布节奏与依赖协同
- 建议下周优先处理阻塞项
"""


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows) -> None:
    path.write_text("".join(f"{json.dumps(row, ensure_ascii=False)}\n" for row in rows), encoding="utf-8")


def main() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(DEEDS_DIR, ignore_errors=True)
    DEEDS_DIR.mkdir(parents=True, exist_ok=True)

    write_json(STATE_DIR / "slips.json", SLIPS)
    write_json(STATE_DIR / "folios.json", FOLIOS)
    write_json(STATE_DIR / "writs.json", WRITS)
    write_json(STATE_DIR / "drafts.json", DRAFTS)
    write_json(STATE_DIR / "deeds.json", DEEDS)
    write_jsonl(STATE_DIR / "herald_log.jsonl", [HERALD_LOG])

    closed_dir = DEEDS_DIR / "deed_demo_closed"
    running_dir = DEEDS_DIR / "deed_demo_running"
    closed_dir.mkdir(parents=True, exist_ok=True)
    running_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(closed_dir / "messages.jsonl", CLOSED_MESSAGES)
    write_jsonl(running_dir / "messages.jsonl", RUNNING_MESSAGES)
    (closed_dir / "messages.lock").write_text("", encoding="utf-8")
    (running_dir / "messages.lock").write_text("", encoding="utf-8")

    offering_dir = OFFERING_ROOT / "2026-03" / "20260312 周报摘要"
    offering_dir.mkdir(parents=True, exist_ok=True)
    (offering_dir / "report.md").write_text(OFFERING_TEXT, encoding="utf-8")


if __name__ == "__main__":
    main()
