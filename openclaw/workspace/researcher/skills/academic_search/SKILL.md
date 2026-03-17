---
name: academic-search
description: >-
  Search academic literature using Semantic Scholar to find papers, citations,
  and research results for a given query. ALWAYS activate when the goal involves
  finding scholarly papers, citation data, or domain-specific research.
  Prioritize peer-reviewed, high-citation papers. NEVER return results without
  title, authors, year, citation count, and abstract.
---

# Academic Search

## When to Activate
When the goal requires finding academic papers, citation data, or domain-specific research results.

## Input
- `query`: Search keywords or research question
- `max_results`: Maximum number of results to return (default 10)

## Execution Steps
1. Use `semantic_scholar_search` to retrieve a paper list by query
2. For highly relevant results, call `semantic_scholar_paper` to get abstract, year, citation count
3. Sort by citation count + year, filter top results
4. If more coverage needed, use `semantic_scholar_citations` or `semantic_scholar_references` to expand

## Quality Standards
- Every result must include: title, authors, year, citation count, abstract
- Prioritize peer-reviewed, high-citation papers
- Results sorted by relevance, with search terms noted

## Common Failure Modes
- Keywords too broad causing noise → add qualifiers, use AND combinations
- Only checking first page of results → inspect at least top 20 before filtering
- Ignoring recent low-citation but highly relevant papers → stratify by year

## Output Format
Markdown table: `| # | Title | Authors | Year | Citations | Abstract (one sentence) |`
