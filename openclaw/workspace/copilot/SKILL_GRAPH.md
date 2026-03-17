# SKILL_GRAPH.md — copilot

## Entry Points
- "plan" | "do" | "create" | "build" → task_decomposition
- "replan" | "adjust" | "review" → replan_assessment

## Edges
- task_decomposition → replan_assessment (after Job completes, evaluate alignment)
- replan_assessment → task_decomposition (when replan needed, decompose revised plan)
