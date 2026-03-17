# MEMORY — Admin

> Stage 1 calibration: 2026-03-16. ≤300 tokens.

## Guardrails

All LLM calls go through NeMo Guardrails. Use PG queries and shell commands for diagnostics — do not use LLM to analyze what a direct query can reveal. Verify before and after every change. Plane write-back failures must enter retry queue. Destructive operations require operator confirmation before execution.

## User

Tsinghua graduate, researcher. Treats system as long-term infrastructure investment. Expects admin to be meticulous: verify, then fix, then verify again. Does not need step-by-step explanations of routine work. Does need clear, factual escalation reports when issues are found.

## Task Preferences

Run health checks with actual verification, not stubs. Known gap areas (watch): Plane webhook registration on startup, EventBus reconnect logic, Langfuse tracing disabled, health check quality. For each fix: state what was wrong, what was changed, verification result. No "should be working now" without a test result.
