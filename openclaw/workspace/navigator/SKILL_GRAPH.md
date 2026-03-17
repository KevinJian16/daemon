# SKILL_GRAPH.md — navigator

## Entry Points
- "plan" | "schedule" | "training" -> task_decomposition
- "replan" | "adjust" | "review progress" -> replan_assessment

## Edges
- task_decomposition -> replan_assessment (after initial plan, evaluate alignment)
- replan_assessment -> task_decomposition (when replan needed, decompose new plan)
