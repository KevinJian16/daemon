# SKILL_GRAPH.md — researcher

## Entry Points
- "search papers" | "find research" → academic_search
- "search web" | "find information" → web_research
- "review literature" | "synthesize" → literature_review
- "evaluate source" | "verify claim" → source_evaluation
- "manage knowledge base" | "ingest document" | "audit corpus" → knowledge_base_mgmt
- "analyze problem" | "reason about" | "trade-off" | "hypothesis" → reasoning_framework

## Edges
- academic_search → source_evaluation (evaluate found papers)
- web_research → source_evaluation (evaluate web sources)
- academic_search → literature_review (synthesize search results)
- web_research → literature_review (synthesize web findings)
- source_evaluation → literature_review (after evaluation, synthesize)
- academic_search → knowledge_base_mgmt (ingest discovered papers into corpus)
- web_research → knowledge_base_mgmt (ingest web findings into corpus)
- literature_review → knowledge_base_mgmt (update corpus after synthesis)
- knowledge_base_mgmt → source_evaluation (verify ingested documents)
- reasoning_framework → literature_review (reasoning identifies knowledge gaps, trigger review)
- source_evaluation → reasoning_framework (after evaluating evidence, apply structured reasoning)
- literature_review → reasoning_framework (after synthesis, reason about conclusions)
