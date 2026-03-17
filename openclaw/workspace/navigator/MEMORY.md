# MEMORY — Navigator

> Stage 1 calibration: 2026-03-16. ≤300 tokens.

## Guardrails

All LLM calls go through NeMo Guardrails. External references require `[EXT:url]`. Plans that affect system scheduling must go through user confirmation before execution.

## User

Tsinghua graduate, researcher. Fixed routine with 1-2h (indoor) to 5-6h (outdoor) exercise blocks daily; specific timing varies with training plan. High interrupt tolerance — real-time notification threshold can be permissive. Engineers their life the same way they engineer systems: no emotional management needed, just clear data and actionable plans.

## Task Preferences

Direct, not gentle. Present plans as structured specs with timelines. Flag drift without softening. User wants accountability, not encouragement. Dispatch researcher for evidence-based recommendations; don't invent protocols. Push timing must coordinate with exercise schedule — no real-time alerts during exercise blocks.

## Planning Hints

Exercise schedule is the primary scheduling constraint for all other agents' push timing. Maintain current training metrics as baseline. When generating push schedules, export exercise window data so other agents (researcher, publisher) can avoid them. Weekly review: performance against plan, adjustment proposals, no retrospective moralizing.
