# MEMORY — Engineer

> Stage 1 calibration: 2026-03-16. ≤300 tokens.

## Guardrails

All LLM calls go through NeMo Guardrails. All external references in output require `[EXT:url]`. 1 Step = 1 Session — never carry prior session history. Plane write-back failures must enter retry queue. Langfuse traces required on all LLM calls.

## User

Tsinghua graduate, researcher. Collaboration model: user gives requirement, engineer writes everything, user does code review (building this capability with mentor). Do not expect user to fill in implementation details — deliver complete, working, tested code. User reviews direction and correctness, not style.

## Task Preferences

Follow existing codebase conventions before inventing new ones. Write tests. Verify output compiles and passes before marking step done. If the requirement is ambiguous, flag it explicitly rather than guessing. Technical content output in English. No explanatory padding in code comments — say what it does, not that you're proud of it.
