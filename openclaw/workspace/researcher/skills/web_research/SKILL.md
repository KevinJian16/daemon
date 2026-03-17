---
name: web-research
description: >-
  Search the internet and scrape web pages to gather information on any topic:
  technical docs, news, product comparisons, health, lifestyle, etc. ALWAYS
  activate when the goal requires up-to-date web information rather than
  academic papers. Cross-verify facts from at least 2 independent sources. NEVER
  present information without its source URL. NEVER treat opinions as facts.
---

# Web Research

## When to Activate
When information must be gathered from the internet: technical docs, news, blogs, product comparisons, health/lifestyle/learning topics, etc.

## Input
- `query`: Search question or keywords
- `depth`: shallow (summaries only) | deep (fetch full text)
- `domain`: Optional, domain-constraining keywords (e.g., "evidence-based", "peer-reviewed")

## Execution Steps
1. Use `brave_search` to search, obtain URL list and summaries
2. Filter the 3-5 most relevant URLs (prioritize official/authoritative sources)
3. For filtered results, call `firecrawl_scrape` to fetch pages as Markdown
4. Extract key passages, annotate with source URL
5. For sensitive domains (health/medical/legal), label as "not professional advice"

## Quality Standards
- Every piece of information must include the original URL
- Cross-verification: at least 2 independent sources for the same fact
- Note information recency (publication date)
- For sensitive domains, prioritize government/academic/professional institution sources

## Common Failure Modes
- Using only one search term → try synonyms / different angles
- Scrape fails (paywall/anti-crawler) → use summary instead, label "full text not retrieved"
- Treating opinions as facts → distinguish factual statements from author opinions
- Health information from non-authoritative sources → prioritize WHO/NIH/Mayo Clinic etc.

## Output Format
Organized by topic, each section ends with `[Source](URL)`, followed by a consolidated source list. Output as structured data for direct consumption by downstream writer.
