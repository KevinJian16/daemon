---
name: academic-paper
description: >-
  Write or polish an academic-style paper or research report following IMRaD or
  appropriate structure. ALWAYS activate when the output must follow academic
  conventions (abstract, citations, methodology). Every claim must have
  supporting evidence or citation. NEVER use colloquial language. NEVER omit the
  methodology section.
---

# Academic Paper

## When to Activate
When writing or polishing academic-style papers or research reports.

## Input
- `title`: Paper title
- `abstract_draft`: Draft abstract (optional)
- `references`: Reference list or key papers

## Execution Steps
1. Determine paper structure based on title and materials (IMRaD or appropriate variant)
2. Write each section: abstract, introduction, methods, results, discussion, conclusion
3. Mark citation positions, generate reference list
4. Check logical chain completeness and academic language conventions
5. Write to file and return path

## Quality Standards
- Every argument backed by evidence or citation
- Abstract readable standalone, covering purpose, methods, conclusion
- No colloquial language

## Common Failure Modes
- Missing citations or inconsistent citation formatting
- Methods section not reproducible
- Discussion disconnected from results

## Output Format
Markdown file, citations using `[n]` numbered format, reference list appended at the end.
