# SKILL_GRAPH.md — reviewer

## Entry Points
- "review code" | "check code" → code_review
- "fact check" | "verify claims" → fact_check
- "quality audit" | "review quality" → quality_audit
- "rework" | "revision instructions" | "feedback for fix" → rework_feedback

## Edges
- quality_audit → code_review (audit identifies code issues)
- quality_audit → fact_check (audit identifies factual claims to verify)
- fact_check → quality_audit (after fact-checking, update quality assessment)
- code_review → rework_feedback (review found issues, generate rework instructions)
- quality_audit → rework_feedback (audit found issues, generate rework instructions)
- fact_check → rework_feedback (fact-check found errors, generate rework instructions)
