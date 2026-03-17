# SKILL_GRAPH.md — admin

## Entry Points
- "health check" → health_check
- "incident" | "error" | "crash" → incident_response
- "audit" | "review skills" → skill_audit

## Edges
- health_check → incident_response (when health check detects failure)
- incident_response → health_check (verify after fix applied)
- skill_audit → health_check (validate changes)
