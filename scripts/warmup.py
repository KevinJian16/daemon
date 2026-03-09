#!/usr/bin/env python3
"""Daemon Warmup Script — seeds initial learned state into Psyche and Spine.

Run once before first production use:
    cd /path/to/daemon
    python scripts/warmup.py

Phases:
  1. Instinct — system preferences + rations
  2. Memory   — initial knowledge units (architecture, best practices)
  3. Lore     — simulate baseline Deed records for experience retrieval
  4. Spine    — witness → learn → focus → judge → relay cycles
  5. Summary  — print learned state overview
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

# ── Bootstrap path and .env ───────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

_env = _ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")

from psyche.memory import MemoryPsyche
from psyche.lore import LorePsyche
from psyche.instinct import InstinctPsyche
from runtime.cortex import Cortex
from spine.nerve import Nerve
from spine.trail import Trail
from spine.routines import SpineRoutines


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Phase 1: Instinct ──────────────────────────────────────────────────────────

def warmup_instinct(instinct: InstinctPsyche) -> None:
    print("  [1] Instinct — preferences + rations")

    prefs = {
        "default_move_timeout_s": "480",
        "quality_min_score":      "0.65",
        "max_concurrent_deeds":   "3",
        "min_word_count":         "800",
        "min_sections":           "3",
        "require_bilingual":      "true",
        "min_quality_score":      "0.60",
    }
    for k, v in prefs.items():
        instinct.set_pref(k, v, source="warmup", changed_by="warmup")

    print(f"      {len(prefs)} prefs set.")


# ── Phase 2: Memory ───────────────────────────────────────────────────────────

def warmup_memory(memory: MemoryPsyche) -> list[str]:
    print("  [2] Memory — seeding initial knowledge units")

    units = [
        {
            "title": "Daemon System Architecture",
            "domain": "system", "tier": "permanent",
            "summary_zh": "Daemon是基于Temporal工作流、OpenClaw智能体、FastAPI的自主任务执行系统。核心层：Psyche（Memory/Lore/Instinct）存储持久知识；Spine（治理例程）驱动自主学习；Runtime（Cortex/Nerve）提供模型调用和事件总线；Services（Will/Herald/Voice/Cadence）处理任务全生命周期。",
            "summary_en": "Daemon is an autonomous Deed execution system on Temporal + OpenClaw + FastAPI. Layers: Psyche (Memory/Lore/Instinct), Spine (governance routines), Runtime (Cortex/Nerve), Services (Will/Herald/Voice/Cadence).",
            "confidence": 1.0, "provider": "warmup", "url": "",
        },
        {
            "title": "V2 Brief and Complexity Model",
            "domain": "system", "tier": "permanent",
            "summary_zh": "V2用Brief统一请求规范：{objective, complexity, move_budget, language, format, depth, references, confidence, quality_hints}。complexity三级：errand（轻量单步）、charge（标准DAG）、endeavor（多Passage）。替代了V1的SemanticSpec+IntentContract+cluster_id+run_type。",
            "summary_en": "V2 Brief unifies request spec: {objective, complexity, move_budget, language, format, depth, references, confidence, quality_hints}. Three complexity levels: errand (lightweight), charge (standard DAG), endeavor (multi-Passage). Replaces V1 SemanticSpec+IntentContract+cluster_id+run_type.",
            "confidence": 1.0, "provider": "warmup", "url": "",
        },
        {
            "title": "DeepSeek Reasoner (deepseek-reasoner) Usage",
            "domain": "technology", "tier": "deep",
            "summary_zh": "deepseek-reasoner使用规范：①temperature必须=1.0，不可修改；②最终答案从choices[0].message.content读取，reasoning_content是推理链不作为输出；③适合需要深度分析的sage任务；④成本较高，避免用于简单对话。",
            "summary_en": "deepseek-reasoner rules: ①temperature=1.0 required; ②answer from choices[0].message.content, reasoning_content is circuit-of-thought only; ③best for sage (analytical) Deeds; ④higher cost, avoid for simple chat.",
            "confidence": 0.95, "provider": "warmup", "url": "",
        },
        {
            "title": "MiniMax M2.5 Anthropic-Compatible API",
            "domain": "technology", "tier": "deep",
            "summary_zh": "MiniMax M2.5接入方式：endpoint=api.minimaxi.com/anthropic（Anthropic兼容），无需GROUP_ID，使用MINIMAX_API_KEY，适合内容审阅和对话任务。",
            "summary_en": "MiniMax M2.5 via Anthropic-compatible API at api.minimaxi.com/anthropic. No GROUP_ID needed. Use MINIMAX_API_KEY. Good for content review, chat.",
            "confidence": 0.92, "provider": "warmup", "url": "",
        },
        {
            "title": "V2 Quality Scoring: Continuous Subscores",
            "domain": "system", "tier": "deep",
            "summary_zh": "V2质量评分三维度：structural（词数+章节+格式）权重0.50 + evidence_completeness（证据单元完整度）权重0.30 + content_review（LLM审阅，Cortex不可用时fallback到structural）权重0.20。综合分<min_quality_score时Herald拒绝。",
            "summary_en": "V2 quality: structural (word/section/format, w=0.50) + evidence_completeness (w=0.30) + content_review (LLM review, fallback to structural, w=0.20). Rejected if composite < min_quality_score.",
            "confidence": 1.0, "provider": "warmup", "url": "",
        },
        {
            "title": "Agent Model Assignment (V2)",
            "domain": "system", "tier": "deep",
            "summary_zh": "V2模型策略：counsel/scout/artificer/envoy→MiniMax M2.5(fast)；sage→DeepSeek R1(analysis)；arbiter→Qwen Max(review)；scribe→GLM Z1 Flash(glm)；opencode子进程→Qwen Max(qwen)。",
            "summary_en": "V2 model assignment: counsel/scout/artificer/envoy→MiniMax M2.5(fast); sage→DeepSeek R1(analysis); arbiter→Qwen Max(review); scribe→GLM Z1 Flash(glm); opencode→Qwen Max(qwen).",
            "confidence": 1.0, "provider": "warmup", "url": "",
        },
        {
            "title": "Spine Routine Execution Schedule",
            "domain": "system", "tier": "deep",
            "summary_zh": "Spine例程调度：pulse（5分钟）、intake（15分钟）、relay（30分钟）、tend（1小时）、witness/learn/focus/judge（较低频）。所有例程通过SpineRoutines类执行，结果写入Trail span。",
            "summary_en": "Spine routine cadence: pulse (5min), intake (15min), relay (30min), tend (1h), witness/learn/focus/judge (lower frequency). All via SpineRoutines class, results traced to Trail spans.",
            "confidence": 0.9, "provider": "warmup", "url": "",
        },
    ]

    result = memory.intake(units, actor="warmup")
    print(f"      {result['inserted']} units inserted, {result['skipped']} skipped.")
    return result["unit_ids"]


# ── Phase 3: Lore ─────────────────────────────────────────────────────────

def warmup_lore(lore: LorePsyche) -> None:
    print("  [3] Lore — simulating baseline Deed records")

    simulated_deeds = [
        {
            "objective": "Research report on distributed systems consensus algorithms",
            "complexity": "charge",
            "moves": ["scout", "sage", "arbiter", "scribe"],
            "success": True, "quality": 0.82, "duration": 420.0,
        },
        {
            "objective": "Deep analysis of LLM inference optimization techniques",
            "complexity": "charge",
            "moves": ["scout", "sage", "arbiter", "scribe"],
            "success": True, "quality": 0.88, "duration": 380.0,
        },
        {
            "objective": "Knowledge synthesis of modern authentication protocols",
            "complexity": "charge",
            "moves": ["scout", "sage", "scribe"],
            "success": True, "quality": 0.85, "duration": 300.0,
        },
        {
            "objective": "Software development: implement caching middleware",
            "complexity": "charge",
            "moves": ["sage", "artificer", "arbiter", "envoy"],
            "success": True, "quality": 0.78, "duration": 540.0,
        },
        {
            "objective": "Personal weekly planning and OKR review",
            "complexity": "errand",
            "moves": ["sage", "scribe"],
            "success": True, "quality": 0.92, "duration": 120.0,
        },
        {
            "objective": "Market analysis report on AI chip industry",
            "complexity": "charge",
            "moves": ["scout", "sage", "arbiter", "scribe"],
            "success": False, "quality": 0.40, "duration": 480.0,
        },
    ]

    recorded = 0
    for i, sim in enumerate(simulated_deeds):
        lore.record(
            deed_id=f"warmup_deed_{i:02d}",
            objective_text=sim["objective"],
            complexity=sim["complexity"],
            move_count=len(sim["moves"]),
            design_structure={"moves": sim["moves"]},
            offering_quality={"quality_score": sim["quality"]},
            token_consumption={"total_tokens": 50000},
            success=sim["success"],
            duration_s=sim["duration"],
        )
        recorded += 1

    print(f"      {recorded} experience records created.")


# ── Phase 4: Spine Cycles ─────────────────────────────────────────────────────

def run_spine_cycles(routines: SpineRoutines) -> None:
    print("  [4] Spine — running governance cycles")

    r = routines.witness()
    if r.get("skipped"):
        print(f"      witness: skipped ({r.get('reason','?')})")
    else:
        print(f"      witness: analyzed={r.get('analyzed',0)}, signals={r.get('signals_added',0)}, degraded={r.get('degraded',False)}")

    r = routines.learn()
    print(f"      learn:   candidates={r.get('candidates_added',0)}, proposals={r.get('proposals',0)}, degraded={r.get('degraded',False)}")

    r = routines.focus()
    print(f"      focus:   signals={r.get('signals_analyzed',0)}, adjusted={r.get('adjusted',0)}, degraded={r.get('degraded',False)}")

    r = routines.judge()
    print(f"      judge:   promoted={r.get('promoted',0)}, retired={r.get('retired',0)}")

    r = routines.relay()
    print(f"      relay:   snapshots={r.get('snapshots',0)}, skill_index={r.get('skill_index',False)}, model_policy={r.get('model_policy_snapshot',False)}")


# ── Phase 5: Summary ──────────────────────────────────────────────────────────

def print_summary(lore: LorePsyche, memory: MemoryPsyche, instinct: InstinctPsyche) -> None:
    print("\n── Warmup Complete ──────────────────────────────────────")

    lore_stats = lore.stats()
    print(f"  Lore: {lore_stats.get('total_records', 0)} experience records")

    mem_stats = memory.stats()
    by_domain = mem_stats.get("by_domain", {})
    print(f"  Memory: {mem_stats.get('total_active',0)} units / {len(by_domain)} domains")
    for domain, count in sorted(by_domain.items(), key=lambda x: x[1], reverse=True)[:5]:
        print(f"    • {domain}: {count}")

    prefs = instinct.all_prefs()
    rations = instinct.all_rations()
    print(f"  Instinct: {len(prefs)} preferences, {len(rations)} rations")

    print("\n  System ready for production use.")
    print("─────────────────────────────────────────────────────────\n")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n══ Daemon Warmup ═══════════════════════════════════════════")

    home = _ROOT
    state = home / "state"
    state.mkdir(parents=True, exist_ok=True)
    print(f"  Home:  {home}")
    print(f"  State: {state}\n")

    memory   = MemoryPsyche(state / "memory.db")
    lore     = LorePsyche(state / "lore.db")
    instinct = InstinctPsyche(state / "instinct.db")
    cortex   = Cortex(instinct)
    nerve    = Nerve()
    trail    = Trail(state / "trails")
    openclaw = home / "openclaw"

    routines = SpineRoutines(
        memory=memory, lore=lore, instinct=instinct,
        cortex=cortex, nerve=nerve, trail=trail,
        daemon_home=home,
        openclaw_home=openclaw if openclaw.exists() else None,
    )

    warmup_instinct(instinct)
    unit_ids = warmup_memory(memory)
    warmup_lore(lore)
    print()
    run_spine_cycles(routines)
    print_summary(lore, memory, instinct)


if __name__ == "__main__":
    main()
