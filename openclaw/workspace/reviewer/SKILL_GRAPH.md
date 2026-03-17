# SKILL_GRAPH.md — reviewer

## Entry Points
- "review code" | "check code" → code_review
- "fact check" | "verify claims" → fact_check
- "quality audit" | "review quality" → quality_audit

## Edges
- quality_audit → code_review (audit identifies code issues)
- quality_audit → fact_check (audit identifies factual claims to verify)
- fact_check → quality_audit (after fact-checking, update quality assessment)
