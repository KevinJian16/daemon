---
name: literature-review
description: >-
  Conduct a systematic literature review on a topic, producing a structured
  survey of foundational work, mainstream methods, and recent advances. ALWAYS
  activate when the goal is a comprehensive survey or state-of-the-art analysis.
  Cover three layers: foundational, mainstream, and cutting-edge work. NEVER
  produce a mere list of papers without analytical narrative and synthesis.
---

# Literature Review

## When to Activate
When a systematic literature review is needed on a topic — mapping the research landscape and current state of the art.

## Input
- `topic`: Review topic
- `scope`: Time range, domain constraints
- `paper_count`: Target number of papers (default 5-8, avoid excess to prevent timeout)

## Execution Steps
1. Use `semantic_scholar_search` to find core papers (2 keyword sets, top 5 per set)
2. Select 5-8 most relevant papers from results (prioritize high-citation + recent)
3. For top 2 high-citation papers, call `semantic_scholar_references` to find upstream foundational work (limit 3)
4. For top 2 recent papers, call `semantic_scholar_citations` to find downstream latest advances (limit 3)
5. Organize by timeline and thematic clusters, write the review
6. Note: skip `ragflow_retrieve` (use only when knowledge base already has relevant material)

## Efficiency Guidelines
- Keep total API calls to 6-8 (2 search + 2 references + 2 citations)
- Aim for core coverage, not exhaustiveness
- No additional citation tracing when search results are sufficient

## Quality Standards
- Three-layer coverage: foundational work + mainstream methods + latest advances
- Every cited paper annotated with (author, year)
- Explicitly identify research gaps and contested points

## Common Failure Modes
- Following only one citation chain → use multiple keyword sets for cross-search
- Review degenerates into a paper list → must include analytical narrative and synthesis
- Too many API calls causing timeout → control total call count

## Output Format
Structured review: `## Background` → `## Main Methods/Schools` → `## Latest Advances` → `## Research Gaps` → `## Reference List`
