---
name: source-evaluation
description: >-
  Evaluate the credibility and quality of information sources (papers, URLs) to
  decide whether to adopt their claims. ALWAYS activate when a claim needs
  verification or when sources of varying reliability must be ranked. Assess
  authority, recency, peer review status, and conflict of interest. NEVER use
  citation count as the sole quality indicator. NEVER label a preprint as
  peer-reviewed.
---

# Source Evaluation

## When to Activate
When source credibility and quality must be assessed to decide whether to adopt their claims.

## Input
- `sources`: List of URLs or paper IDs to evaluate
- `claim`: Specific assertion to verify (optional)

## Execution Steps
1. For papers: use `semantic_scholar_paper` to get citation count, journal, author h-index
2. For web pages: use `firecrawl_scrape` to fetch full text, check author credentials and citations
3. Use `brave_search` to cross-reference the same claim from other sources
4. Score each source and provide adoption recommendation

## Quality Standards
- Each source evaluated on: authority, recency, peer review status, conflict of interest
- When a claim is provided, must determine: supports / contradicts / insufficient
- Scores must include justification, not just a number

## Common Failure Modes
- Using citation count as sole indicator → consider journal tier and field differences
- Ignoring conflict of interest → check author affiliation and funding sources
- Treating preprints as published → explicitly label review status

## Output Format
One row per source: `| Source | Authority | Recency | Review Status | Score (1-5) | Adoption Recommendation | Rationale |`
