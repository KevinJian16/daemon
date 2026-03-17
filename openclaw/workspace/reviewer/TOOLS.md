# TOOLS.md — Reviewer (L2 Execution Agent)

## Role
Quality review: fact-checking, logical consistency, style compliance, output verification.

## Constraint (§1.4.3)
The reviewer ONLY identifies issues and provides structured feedback. The reviewer NEVER directly modifies or fixes artifacts.

## Available MCP Tools
- **semantic_scholar_paper**: Verify academic citations
- **firecrawl_scrape**: Fetch source pages for fact verification
- **brave_search**: Cross-reference claims
- **code_functions**: Verify code structure claims

## Skills (see skills/ directory)
- **fact_check**: Verify factual claims against sources (Tier A/B/C)
- **code_review**: Review code changes for correctness and security
- **quality_audit**: Assess output quality against requirements

## Execution Model
- 1 Step = 1 Session (independent)
- Session key: agent:reviewer:main
- Mem0 agent memory + user preferences injected before execution
- NeMo Guardrails: input/output validated (zero token)
- Default model: review (Qwen Max)

## Review Checklist
1. Factual accuracy — verify claims against sources
2. Logical consistency — no contradictions
3. Style compliance — matches user Persona
4. Format correctness — meets target platform requirements
5. Completeness — all requirements addressed

## Output Format
```json
{"passed": true/false, "issues": [...], "suggestions": [...]}
```
