# SKILL_GRAPH.md — researcher

## Entry Points
- "search papers" | "find research" → academic_search
- "search web" | "find information" → web_research
- "review literature" | "synthesize" → literature_review
- "evaluate source" | "verify claim" → source_evaluation

## Edges
- academic_search → source_evaluation (evaluate found papers)
- web_research → source_evaluation (evaluate web sources)
- academic_search → literature_review (synthesize search results)
- web_research → literature_review (synthesize web findings)
- source_evaluation → literature_review (after evaluation, synthesize)
