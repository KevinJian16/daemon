# MEMORY — Copilot

> Stage 1 calibration: 2026-03-16. ≤300 tokens.

## Guardrails

All LLM calls go through NeMo Guardrails — no exceptions. 1 Step = 1 Session; never carry session history across steps. Plane write-back failures must enter retry queue, never silently ignored. All external references require `[EXT:url]` markers.

## User

Tsinghua graduate, researcher. Goal: industry 3+ years engineering + PhD-level research depth in parallel. Build-first path: engineer → locate in literature → write if worth it. High-autonomy preference (C-level): execute and report, user reviews retrospectively. Fast decision-maker with strong metacognitive monitoring — will test whether you understand the mechanism.

## Task Preferences

Default routing: simple task → single agent direct; complex → multi-step Job with dependencies. After each build cycle, force a literature mapping pass. Copilot default pipeline: engineer → researcher (locate) → writer (if worth writing). User reviews output direction, not line-level details.

## Planning Hints

Route research tasks to researcher — user does not patrol sources, daemon is the primary channel. Engineering tasks: engineer writes, user code reviews (instructor builds this capacity). Learning contexts: route to instructor, do not deliver complete solutions. Plans at goal level; L2 agents own implementation.
