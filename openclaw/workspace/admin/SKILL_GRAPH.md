# SKILL_GRAPH.md — admin

## Entry Points
- "health check" → health_check
- "incident" | "error" | "crash" → incident_response
- "audit" | "review skills" → skill_audit
- "upgrade" | "new model" | "evaluate component" → frontier_iteration
- "full health audit" | "3-layer check" | "system diagnostics" → health_check_3layer

## Edges
- health_check → incident_response (when health check detects failure)
- incident_response → health_check (verify after fix applied)
- skill_audit → health_check (validate changes)
- health_check_3layer → incident_response (3-layer check detects failure, trigger incident response)
- health_check_3layer → skill_audit (fidelity layer reveals skill performance issues)
- incident_response → health_check_3layer (after incident fix, run full 3-layer verification)
- frontier_iteration → health_check_3layer (after component upgrade, validate system health)
- frontier_iteration → skill_audit (after model upgrade, audit affected skills)
