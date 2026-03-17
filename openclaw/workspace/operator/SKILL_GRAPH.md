# SKILL_GRAPH.md — operator

## Entry Points
- "schedule" | "manage" | "operate" → task_decomposition
- "replan" | "adjust" → replan_assessment

## Edges
- task_decomposition → replan_assessment (after operations complete, evaluate)
- replan_assessment → task_decomposition (replan operations if needed)
