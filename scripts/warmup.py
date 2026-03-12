#!/usr/bin/env python3
"""Daemon Warmup Script — seeds initial state into Psyche and Spine.

Run once before first production use:
    cd /path/to/daemon
    python scripts/warmup.py

Phases:
  1. PsycheConfig — verify preferences + rations TOML
  2. LedgerStats  — seed baseline dag_templates for planning hints
  3. Spine        — pulse → witness → focus → relay cycles
  4. Summary      — print state overview
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

from psyche.config import PsycheConfig
from psyche.ledger_stats import LedgerStats
from psyche.instinct_engine import InstinctEngine
from runtime.cortex import Cortex
from spine.nerve import Nerve
from spine.trail import Trail
from spine.routines import SpineRoutines


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Phase 1: PsycheConfig ────────────────────────────────────────────────────

def warmup_config(config: PsycheConfig) -> None:
    print("  [1] PsycheConfig — verify preferences + rations")

    prefs = config.all_prefs()
    rations = config.all_rations()
    print(f"      {len(prefs)} preferences loaded, {len(rations)} ration entries loaded.")


# ── Phase 2: LedgerStats ─────────────────────────────────────────────────────

def warmup_ledger(ledger: LedgerStats) -> None:
    print("  [2] LedgerStats — seeding baseline dag_templates")

    templates = [
        {
            "objective": "Research report on distributed systems consensus algorithms",
            "dag_structure": json.dumps({"agents": ["scout", "sage", "arbiter", "scribe"], "dag_budget": 6}),
            "embedding": [],
        },
        {
            "objective": "Deep analysis of LLM inference optimization techniques",
            "dag_structure": json.dumps({"agents": ["scout", "sage", "arbiter", "scribe"], "dag_budget": 6}),
            "embedding": [],
        },
        {
            "objective": "Software development: implement caching middleware",
            "dag_structure": json.dumps({"agents": ["sage", "artificer", "arbiter", "envoy"], "dag_budget": 6}),
            "embedding": [],
        },
        {
            "objective": "Personal weekly planning and OKR review",
            "dag_structure": json.dumps({"agents": ["sage", "scribe"], "dag_budget": 3}),
            "embedding": [],
        },
    ]

    seeded = 0
    for tmpl in templates:
        try:
            ledger.merge_dag_template(
                objective_text=tmpl["objective"],
                objective_emb=None,
                dag_structure=json.loads(tmpl["dag_structure"]),
                eval_summary="seed",
                total_tokens=0,
                total_duration_s=0.0,
                rework_count=0,
            )
            seeded += 1
        except Exception as exc:
            print(f"      warning: failed to seed template: {exc}")

    print(f"      {seeded} dag_templates seeded.")


# ── Phase 3: Spine Cycles ────────────────────────────────────────────────────

def run_spine_cycles(routines: SpineRoutines) -> None:
    print("  [3] Spine — running governance cycles")

    r = routines.pulse()
    print(f"      pulse:   ward={r.get('ward', '?')}")

    r = routines.witness()
    print(f"      witness: {r}")

    r = routines.focus()
    print(f"      focus:   {r}")

    r = routines.relay()
    print(f"      relay:   snapshots={r.get('snapshots', 0)}")


# ── Phase 4: Summary ─────────────────────────────────────────────────────────

def print_summary(config: PsycheConfig, ledger: LedgerStats) -> None:
    print("\n── Warmup Complete ──────────────────────────────────────")

    prefs = config.all_prefs()
    rations = config.all_rations()
    print(f"  Config: {len(prefs)} preferences, {len(rations)} ration entries")

    hints = ledger.global_planning_hints()
    print(f"  Ledger: dag_templates={hints.get('dag_template_count', 0)}, "
          f"folio_templates={hints.get('folio_template_count', 0)}")

    print("\n  System ready for production use.")
    print("─────────────────────────────────────────────────────────\n")


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n══ Daemon Warmup ═══════════════════════════════════════════")

    home = _ROOT
    state = home / "state"
    state.mkdir(parents=True, exist_ok=True)
    print(f"  Home:  {home}")
    print(f"  State: {state}\n")

    psyche_dir = state / "psyche"
    psyche_dir.mkdir(parents=True, exist_ok=True)
    psyche_config = PsycheConfig(home / "psyche")
    ledger_stats = LedgerStats(psyche_dir / "ledger.db")
    instinct_engine = InstinctEngine(home / "psyche")
    cortex = Cortex(psyche_config)
    nerve = Nerve()
    trail = Trail(state / "trails")
    openclaw = home / "openclaw"

    routines = SpineRoutines(
        psyche_config=psyche_config, ledger_stats=ledger_stats, instinct_engine=instinct_engine,
        cortex=cortex, nerve=nerve, trail=trail,
        daemon_home=home,
        openclaw_home=openclaw if openclaw.exists() else None,
    )

    warmup_config(psyche_config)
    warmup_ledger(ledger_stats)
    print()
    run_spine_cycles(routines)
    print_summary(psyche_config, ledger_stats)


if __name__ == "__main__":
    main()
