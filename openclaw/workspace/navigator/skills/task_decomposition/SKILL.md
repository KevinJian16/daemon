---
name: task-decomposition
description: >-
  Decompose a user request into a structured Task/Job DAG with agent assignments
  and dependency edges. ALWAYS activate when the routing decision yields task or
  project route. Each Job must have a single clear goal executable by one agent.
  NEVER produce Jobs with ambiguous goals or missing depends_on edges. NEVER mix
  multiple objectives into a single Job.
---

# Task Decomposition

## Applicable Scenarios
Decompose user requests into a structured Task/Job DAG.

## Input
User's natural language request or goal description.

## Execution Steps
1. Identify independent objectives in the request; each objective maps to one Task
2. Break each Task into executable Jobs, specifying agent and goal
3. Analyze inter-Job dependencies and set depends_on
4. Verify the DAG is acyclic and all dependencies are reachable
5. Provide sufficient context in each Step's goal so the agent can execute without additional information

## Agent Selection Guide
- **researcher**: Search, analyze, information retrieval (academic + web)
- **engineer**: Code, debug, code analysis
- **writer**: Writing, documents, chart generation, structured plans
- **reviewer**: Review, evaluate, fact-check
- **publisher**: External publishing (Telegram/GitHub)
- **admin**: System diagnostics, maintenance

## Quality Standards
- Each Job must have a single clear objective, completable by one agent independently
- depends_on must accurately reflect data/logic dependencies
- Step goal descriptions must be specific ("search aspect Y of X" not "search X")

## Common Failure Modes
- Job granularity too coarse, mixing multiple objectives
- Missing implicit dependencies causing data races during parallel execution
- Step goals too vague for the agent to know what to do

## Output Format
```yaml
tasks:
  - name: ...
    jobs:
      - id: j1
        agent: ...
        goal: ...
        depends_on: []
```
