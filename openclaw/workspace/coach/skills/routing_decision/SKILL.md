---
name: routing-decision
description: >-
  Parse user intent and select the execution route (direct, task, or project).
  ALWAYS activate when a user message requires action beyond simple
  conversation. Classify complexity, identify required agents, and output a
  structured routing decision with step dependencies. NEVER route to project
  when task suffices; NEVER route to task when direct suffices.
---

# Routing Decision

## Applicable Scenarios
When user sends a message that requires action (not just conversation).

## Input
User message (natural language) + conversation context.

## Execution Steps
1. Parse user intent from the message
2. Classify complexity: can it be done in 1 step, multiple steps, or requires a project?
3. Select route:
   - `direct`: single-step, one agent, no Task needed
   - `task`: multi-step Job with DAG
   - `project`: multi-task complex work with dependencies
4. For `task`/`project`: identify required agents and step dependencies
5. Output structured routing decision

## Output Format
```json
{
  "intent": "user's actual intent",
  "route": "direct|task|project",
  "model": "fast|analysis|creative",
  "agent_id": "agent for direct route",
  "steps": [{"goal": "...", "agent_id": "...", "depends_on": []}]
}
```

## Quality Standards
- Conservative: prefer `direct` over `task`, `task` over `project`
- Each step has a single clear objective
- Dependencies are accurate (no hidden assumptions)
- Goal descriptions are specific enough for the assigned agent
