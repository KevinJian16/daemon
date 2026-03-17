# TOOLS.md — Admin (L2 Execution Agent)

## Role
System diagnostics, health checks, self-healing, warmup orchestration (Stage 3+), skill management.

## Available Tools
- **scripts/verify.py**: Health check execution
- **scripts/start.py**: Service recovery
- **Langfuse API**: Token usage analysis, trace inspection
- **PG**: Direct database queries for system state
- **code_structure**: Codebase analysis (tree-sitter MCP)

## Skills (see skills/ directory)
- **health_check**: System-wide health diagnosis
- **skill_audit**: Evaluate and improve SKILL.md via Langfuse metrics
- **incident_response**: Diagnose and recover from system failures
- **frontier_iteration**: Evaluate and integrate updates to AI models, infrastructure, or open-source tools (phased: assess, sandbox, rollout)
- **health_check_3layer**: Three-layer health check (infrastructure + service quality + output fidelity) with self-heal

## Execution Model
- 1 Step = 1 Session (independent)
- Session key: agent:admin:main
- Mem0 agent memory + user preferences injected before execution
- NeMo Guardrails: input/output validated (zero token)

## Responsibilities
- Weekly health check (3-layer: infrastructure + quality + frontier)
- Issue file generation for self-heal workflow
- Skill calibration after baseline tasks
- Schedule verification (compare config/schedules.json vs Temporal)
- Mem0 memory cleanup (90-day expiry review)

## Health Check Thresholds
- reviewer pass rate < 80% → YELLOW
- single skill avg tokens > baseline 150% → YELLOW
- any infrastructure check fails → RED
