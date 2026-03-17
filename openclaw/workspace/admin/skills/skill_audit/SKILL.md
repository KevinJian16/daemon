---
name: skill-audit
description: >-
  Audit SKILL.md effectiveness using Langfuse trace data: measure success rate,
  latency, token usage, and identify failure patterns. ALWAYS activate when
  skill performance needs evaluation or when success rates drop below baseline.
  Base all recommendations on actual trace evidence. NEVER propose changes
  without citing specific trace IDs. NEVER draw conclusions from insufficient
  sample sizes.
---

# Skill Audit

## When to Activate
When evaluating the actual execution effectiveness of SKILL.md based on Langfuse metrics and proposing improvements.

## Input
Target agent name + skill name, or "all" for full audit.

## Execution Steps
1. Pull recent trace data for the skill from Langfuse (success rate, latency, token usage)
2. Analyze root cause distribution of failed traces
3. Compare SKILL.md text against actual execution path deviations
4. Generate improvement recommendations (step adjustments / constraint additions / example additions)

## Quality Standards
- Improvement recommendations must be based on actual trace data, not guesswork
- Each recommendation must cite the corresponding failed trace ID

## Common Failure Modes
- Drawing conclusions prematurely with insufficient sample size
- Focusing only on success rate while ignoring token efficiency degradation

## Output Format
```
Skill: {agent}/{skill} | Success rate: X% | Avg latency: Xs
[issue] description | trace_id | suggested change
```
