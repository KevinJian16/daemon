---
name: tech-blog
description: >-
  Write a technical blog post targeting developers, with clear structure,
  runnable code examples, and actionable takeaways. ALWAYS activate when the
  goal is to produce a blog post or technical article for a developer audience.
  State reader benefit within the first 3 sentences. NEVER include code examples
  that cannot run standalone. NEVER use undefined technical terms without
  explanation.
---

# Tech Blog

## When to Activate
When writing a technical blog post targeting developers or technical audiences.

## Input
- `topic`: Topic or title
- `audience`: Target readers (default: intermediate developers)
- `length`: Target word count (default: 1500)

## Execution Steps
1. Determine core thesis and reader benefit
2. Draft outline: introduction, body (2-4 sections), conclusion
3. Write first draft, each section with code examples or diagrams
4. Check technical accuracy and prose flow
5. Write to file and return path

## Quality Standards
- Reader benefit stated within first 3 sentences
- Code examples runnable standalone
- No undefined terms; explain on first occurrence

## Common Failure Modes
- Piling up concepts without examples
- Code snippets lacking context or dependency descriptions
- No call to action at the end

## Output Format
Markdown file with YAML front matter (title, date, tags).
