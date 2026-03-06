#!/usr/bin/env python3
"""Daemon Warmup Script — seeds initial learned state into Fabric and Spine.

Run once before first production use:
    cd /path/to/daemon
    python scripts/warmup.py

Phases:
  1. Compass  — domain priorities + system preferences
  2. Memory   — initial knowledge units (architecture, cluster specs, best practices)
  3. Playbook — register DAG methods + simulate baseline evaluations per cluster
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

from fabric.memory import MemoryFabric
from fabric.playbook import PlaybookFabric
from fabric.compass import CompassFabric
from runtime.cortex import Cortex
from spine.nerve import Nerve
from spine.trace import Tracer
from spine.routines import SpineRoutines


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Phase 1: Compass ──────────────────────────────────────────────────────────

def warmup_compass(compass: CompassFabric) -> None:
    print("  [1] Compass — domain priorities + preferences")

    priorities = [
        ("technology",   1.5, "Core domain for dev and research runs"),
        ("development",  1.4, "Software development and coding runs"),
        ("research",     1.3, "Research, analysis, and synthesis runs"),
        ("knowledge",    1.2, "Knowledge consolidation and learning"),
        ("system",       1.0, "System health and operations monitoring"),
        ("productivity", 1.0, "Personal productivity and planning"),
        ("finance",      0.8, "Financial and market analysis"),
    ]
    for domain, weight, reason in priorities:
        compass.set_priority(domain, weight, reason, source="warmup", changed_by="warmup")

    prefs = {
        "default_step_timeout_s": "480",
        "model_primary":          "deepseek-reasoner",
        "quality_min_score":      "0.65",
        "max_concurrent_runs":   "3",
    }
    for k, v in prefs.items():
        compass.set_pref(k, v, source="warmup", changed_by="warmup")

    print(f"      {len(priorities)} priorities, {len(prefs)} prefs set.")


# ── Phase 2: Memory ───────────────────────────────────────────────────────────

def warmup_memory(memory: MemoryFabric) -> list[str]:
    print("  [2] Memory — seeding initial knowledge units")

    units = [
        {
            "title": "Daemon System Architecture",
            "domain": "system", "tier": "permanent",
            "summary_zh": "Daemon是基于Temporal工作流、OpenClaw智能体、FastAPI的自主任务执行系统。核心层：Fabric（Memory/Playbook/Compass）存储持久知识；Spine（10个治理例程）驱动自主学习；Runtime（Cortex/Nerve/EventBridge）提供模型调用和事件总线；Services（Dispatch/Delivery/Dialog/Scheduler）处理任务全生命周期。",
            "summary_en": "Daemon is an autonomous run execution system on Temporal + OpenClaw + FastAPI. Layers: Fabric (Memory/Playbook/Compass), Spine (10 governance routines), Runtime (Cortex/Nerve/EventBridge), Services (Dispatch/Delivery/Dialog/Scheduler).",
            "confidence": 1.0, "provider": "warmup", "url": "",
        },
        {
            "title": "Semantic Cluster: Research Report (clst_research_report)",
            "domain": "research", "tier": "permanent",
            "summary_zh": "深度研究报告集群。输出：research_report, analysis_document。风险：medium。质量门槛：≥800字，≥3章节，quality_score≥0.65。DAG标准步骤：collect→analyze→review→render。",
            "summary_en": "Deep research report cluster. Artifacts: research_report, analysis_document. Risk: medium. Quality: ≥800 words, ≥3 sections, score≥0.65. Steps: collect→analyze→review→render.",
            "confidence": 1.0, "provider": "warmup", "url": "",
        },
        {
            "title": "Semantic Cluster: Knowledge Synthesis (clst_knowledge_synthesis)",
            "domain": "knowledge", "tier": "permanent",
            "summary_zh": "知识整合综述集群。输出：knowledge_doc, summary。风险：low。适合领域综述、概念提炼、跨文档知识聚合。步骤：collect→analyze→render。",
            "summary_en": "Knowledge consolidation cluster. Artifacts: knowledge_doc, summary. Risk: low. Good for domain surveys, concept distillation. Steps: collect→analyze→render.",
            "confidence": 1.0, "provider": "warmup", "url": "",
        },
        {
            "title": "Semantic Cluster: Dev Project (clst_dev_project)",
            "domain": "development", "tier": "permanent",
            "summary_zh": "软件开发项目集群。输出：code_artifact, technical_doc。风险：high（代码执行）。标准步骤：analyze→build→review→apply。rework_budget=3允许多轮修改。",
            "summary_en": "Software development cluster. Artifacts: code_artifact, technical_doc. Risk: high (code execution). Steps: analyze→build→review→apply. rework_budget=3.",
            "confidence": 1.0, "provider": "warmup", "url": "",
        },
        {
            "title": "Semantic Cluster: Personal Plan (clst_personal_plan)",
            "domain": "productivity", "tier": "permanent",
            "summary_zh": "个人规划行动集群。输出：plan_doc, schedule。风险：low。步骤精简：analyze→render。适合目标设定、周计划、OKR制定。",
            "summary_en": "Personal planning cluster. Artifacts: plan_doc, schedule. Risk: low. Steps: analyze→render. Good for goal setting, weekly plans, OKRs.",
            "confidence": 1.0, "provider": "warmup", "url": "",
        },
        {
            "title": "DeepSeek Reasoner (deepseek-reasoner) Usage",
            "domain": "technology", "tier": "deep",
            "summary_zh": "deepseek-reasoner使用规范：①temperature必须=1.0，不可修改；②最终答案从choices[0].message.content读取，reasoning_content是推理链不作为输出；③适合需要深度分析的analytical任务；④成本较高，避免用于简单对话。",
            "summary_en": "deepseek-reasoner rules: ①temperature=1.0 required; ②answer from choices[0].message.content, reasoning_content is circuit-of-thought only; ③best for analytical runs; ④higher cost, avoid for simple chat.",
            "confidence": 0.95, "provider": "warmup", "url": "",
        },
        {
            "title": "MiniMax M2.5 Anthropic-Compatible API",
            "domain": "technology", "tier": "deep",
            "summary_zh": "MiniMax M2.5接入方式：endpoint=api.minimaxi.com/anthropic（Anthropic兼容），无需GROUP_ID，使用MINIMAX_API_KEY，适合内容审阅和对话任务，作为DeepSeek的备用方案（model_policy provider_route）。",
            "summary_en": "MiniMax M2.5 via Anthropic-compatible API at api.minimaxi.com/anthropic. No GROUP_ID needed. Use MINIMAX_API_KEY. Good for content review, chat. Fallback for DeepSeek per model_policy.",
            "confidence": 0.92, "provider": "warmup", "url": "",
        },
        {
            "title": "V2 Quality Scoring: Continuous Subscores",
            "domain": "system", "tier": "deep",
            "summary_zh": "V2质量评分三维度：structural（词数+章节+格式，权重因集群而异）+ evidence_completeness（证据单元完整度）+ content_review（LLM审阅，Cortex不可用时fallback到structural）。综合分<min_quality_score时delivery拒绝。",
            "summary_en": "V2 quality: structural (word/section/format, weight varies by cluster) + evidence_completeness (evidence unit coverage) + content_review (LLM review, fallback to structural if Cortex unavailable). Rejected if composite < min_quality_score.",
            "confidence": 1.0, "provider": "warmup", "url": "",
        },
        {
            "title": "Replay Backoff and Run Queue Management",
            "domain": "system", "tier": "deep",
            "summary_zh": "任务排队重播机制：最大5次，退避[60s,300s,900s,3600s,14400s]。replay_token保证幂等。超限→replay_exhausted终态。spine.tend在gate=GREEN且next_replay_utc已过时自动触发重播。",
            "summary_en": "Replay backoff: max 5 attempts, delays [60s,300s,900s,1h,4h]. replay_token for idempotency. Exceeded→replay_exhausted. spine.tend auto-triggers eligible runs when gate=GREEN.",
            "confidence": 1.0, "provider": "warmup", "url": "",
        },
        {
            "title": "Spine Routine Execution Schedule",
            "domain": "system", "tier": "deep",
            "summary_zh": "Spine例程调度：pulse（5分钟）、intake（15分钟）、relay（30分钟）、tend（1小时）、witness/learn/focus/judge（较低频）。所有例程通过SpineRoutines类执行，结果写入Tracer trace span。",
            "summary_en": "Spine routine cadence: pulse (5min), intake (15min), relay (30min), tend (1h), witness/learn/focus/judge (lower frequency). All via SpineRoutines class, results traced to Tracer spans.",
            "confidence": 0.9, "provider": "warmup", "url": "",
        },
    ]

    result = memory.intake(units, actor="warmup")
    print(f"      {result['inserted']} units inserted, {result['skipped']} skipped.")
    return result["unit_ids"]


# ── Phase 3: Playbook ─────────────────────────────────────────────────────────

def warmup_playbook(playbook: PlaybookFabric, unit_ids: list[str]) -> dict[str, str]:
    print("  [3] Playbook — register DAG methods + simulate evaluations")

    method_defs = [
        {
            "name": "research_report",
            "description": "Deep research report: collect → analyze → review → render",
            "spec": {
                "steps_template": ["collect", "analyze", "review", "render"],
                "rework_budget": 2, "rework_strategy": "error_code_based",
                "concurrency": {"collect": 6, "analyze": 3, "review": 2, "render": 1},
                "timeout_hints": {"collect": 300, "analyze": 480, "review": 240, "render": 120},
            },
            "status": "champion",
        },
        {
            "name": "knowledge_synthesis",
            "description": "Knowledge synthesis: collect → analyze → render",
            "spec": {
                "steps_template": ["collect", "analyze", "render"],
                "rework_budget": 1, "rework_strategy": "error_code_based",
                "concurrency": {"collect": 4, "analyze": 2, "render": 1},
                "timeout_hints": {"collect": 240, "analyze": 360, "render": 120},
            },
            "status": "champion",
        },
        {
            "name": "dev_project",
            "description": "Dev project: analyze → build → review → apply",
            "spec": {
                "steps_template": ["analyze", "build", "review", "apply"],
                "rework_budget": 3, "rework_strategy": "error_code_based",
                "concurrency": {"analyze": 2, "build": 2, "review": 2, "apply": 1},
                "timeout_hints": {"analyze": 360, "build": 600, "review": 300, "apply": 180},
            },
            "status": "champion",
        },
        {
            "name": "personal_plan",
            "description": "Personal planning: analyze context → render plan",
            "spec": {
                "steps_template": ["analyze", "render"],
                "rework_budget": 1, "rework_strategy": "error_code_based",
                "concurrency": {"analyze": 1, "render": 1},
                "timeout_hints": {"analyze": 240, "render": 120},
            },
            "status": "champion",
        },
    ]

    # Register methods (idempotent by name).
    existing = {m["name"]: m["method_id"] for m in playbook.consult(category="dag_pattern")}
    method_ids: dict[str, str] = {}
    for m in method_defs:
        if m["name"] in existing:
            method_ids[m["name"]] = existing[m["name"]]
        else:
            mid = playbook.register(
                name=m["name"], category="dag_pattern",
                spec=m["spec"], description=m["description"], status=m["status"],
            )
            method_ids[m["name"]] = mid

    # Simulate baseline evaluations (realistic distribution).
    evals = [
        # (method, outcome, score)
        ("research_report",    "success", 0.82),
        ("research_report",    "success", 0.76),
        ("research_report",    "success", 0.88),
        ("research_report",    "success", 0.71),
        ("research_report",    "failure", 0.40),
        ("knowledge_synthesis","success", 0.85),
        ("knowledge_synthesis","success", 0.79),
        ("knowledge_synthesis","success", 0.90),
        ("knowledge_synthesis","failure", 0.35),
        ("dev_project",        "success", 0.78),
        ("dev_project",        "success", 0.72),
        ("dev_project",        "failure", 0.45),
        ("dev_project",        "failure", 0.38),
        ("personal_plan",      "success", 0.88),
        ("personal_plan",      "success", 0.92),
        ("personal_plan",      "success", 0.85),
        ("personal_plan",      "success", 0.80),
    ]

    ev_ids: list[str] = []
    for i, (name, outcome, score) in enumerate(evals):
        mid = method_ids.get(name)
        if not mid:
            continue
        eid = playbook.evaluate(
            method_id=mid,
            run_id=f"warmup_{name}_{i:02d}",
            outcome=outcome,
            score=score,
            detail={"source": "warmup_simulation", "evidence_unit_ids": unit_ids[:3]},
        )
        ev_ids.append(eid)

    print(f"      {len(method_ids)} methods registered, {len(ev_ids)} evaluations recorded.")
    return method_ids


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

def print_summary(playbook: PlaybookFabric, memory: MemoryFabric, compass: CompassFabric) -> None:
    print("\n── Warmup Complete ──────────────────────────────────────")

    methods = playbook.consult(category="dag_pattern")
    print(f"  Playbook: {len(methods)} methods")
    for m in methods:
        sr = m.get("success_rate")
        sr_str = f"{sr:.0%}" if sr is not None else "n/a"
        print(f"    • {m['name']:<22} status={m.get('status','?'):<10} success_rate={sr_str}  runs={m.get('total_runs',0)}")

    mem_stats = memory.stats()
    by_domain = mem_stats.get("by_domain", {})
    print(f"\n  Memory: {mem_stats.get('total_active',0)} units / {len(by_domain)} domains")
    for domain, count in sorted(by_domain.items(), key=lambda x: x[1], reverse=True)[:5]:
        print(f"    • {domain}: {count}")

    priorities = sorted(compass.get_priorities(), key=lambda x: float(x.get("weight", 1)), reverse=True)
    print(f"\n  Compass: {len(priorities)} priority domains")
    for p in priorities[:5]:
        print(f"    • {p['domain']:<16} weight={p.get('weight')}")

    signals = compass.active_signals()
    print(f"\n  Attention signals: {len(signals)}")
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

    memory   = MemoryFabric(state / "memory.db")
    playbook = PlaybookFabric(state / "playbook.db")
    compass  = CompassFabric(state / "compass.db")
    cortex   = Cortex(compass)
    nerve    = Nerve()
    tracer   = Tracer(state / "traces")
    openclaw = home / "openclaw"

    routines = SpineRoutines(
        memory=memory, playbook=playbook, compass=compass,
        cortex=cortex, nerve=nerve, tracer=tracer,
        daemon_home=home,
        openclaw_home=openclaw if openclaw.exists() else None,
    )

    # Seed semantic clusters from catalog (idempotent).
    catalog_path = home / "config" / "semantics" / "capability_catalog.json"
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        clusters = catalog.get("clusters", [])
        if clusters:
            playbook.seed_clusters(clusters)
            print(f"  Seeded {len(clusters)} semantic clusters.\n")
    except Exception as exc:
        print(f"  Warning: could not seed clusters: {exc}\n")

    warmup_compass(compass)
    unit_ids = warmup_memory(memory)
    warmup_playbook(playbook, unit_ids)
    print()
    run_spine_cycles(routines)
    print_summary(playbook, memory, compass)


if __name__ == "__main__":
    main()
