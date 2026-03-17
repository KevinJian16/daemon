---
name: health-check-3layer
description: >-
  Execute the three-layer health check: infrastructure health (containers, DB,
  queues), service quality (pass rates, token usage, latency), and output
  fidelity (pseudo-human scoring). ALWAYS activate for comprehensive system
  diagnostics or scheduled health audits. Attempt self-heal for yellow/red items
  before escalating to user. NEVER skip Layer 3 fidelity checks during a full
  audit.
---

# Skill: health_check_3layer

## Purpose
Execute the three-layer health check: infrastructure health (containers, DB, queues), service quality (reviewer pass rate, token usage, latency), and output fidelity (pseudo-human score).

## Steps
1. **Layer 1 — Infrastructure**: check Docker container status, PG connectivity, Temporal server, MinIO, Redis, Langfuse, EventBus
2. **Layer 2 — Service Quality**: query Langfuse for per-Step token usage, query PG for reviewer pass rate (target >= 80%), check Job completion rate and average latency
3. **Layer 3 — Output Fidelity**: evaluate recent artifacts against pseudo-human baseline (score >= 4/5), check for style drift using Mem0 persona data
4. Aggregate results into a health report with status per layer (green / yellow / red)
5. For any yellow/red items: generate specific diagnosis and recommended fix action
6. If self-heal is possible (restart container, clear queue, retry failed job): execute fix automatically
7. If self-heal insufficient: escalate to user via Telegram notification

## Input
- Check scope: full | infrastructure | quality | fidelity
- Threshold overrides (optional)

## Output
- Health report: per-layer status (green/yellow/red) with details
- Actions taken (self-heal attempts and results)
- Escalation messages (if any layers are red)
- Metrics snapshot (token usage, pass rates, latency p50/p95)

## Token Budget
~2500 tokens (mostly PG/API queries, LLM for fidelity evaluation)
