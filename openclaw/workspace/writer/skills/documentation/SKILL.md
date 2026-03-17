---
name: documentation
description: >-
  Write structured documentation: API references, user guides, how-to manuals,
  structured plans (fitness, study, project), or operational procedures. ALWAYS
  activate when the goal is to produce any form of reference documentation or
  actionable plan. Match structure to doc type (reference, guide, plan, manual).
  NEVER produce a plan without concrete timelines and actionable steps. NEVER
  let code examples diverge from the current codebase.
---

# Documentation

## When to Activate
When writing structured documentation: API references, user guides, technical docs, structured plans (fitness/study/project plans), operational manuals, etc.

## Input
- `subject`: Documentation target (module, API, feature, topic)
- `doc_type`: Type (quickstart / reference / guide / plan / manual)
- `source_files`: Related source code paths (optional, technical docs only)
- `research_input`: Materials from upstream researcher (optional)

## Execution Steps
1. Determine document type and target audience
2. If source code paths provided, read source to extract interfaces and behavior
3. If upstream research materials provided, extract key information and annotate sources
4. Select structure template by document type:
   - reference/quickstart: title → overview → usage → parameter table → examples → FAQ
   - guide: title → prerequisites → step-by-step instructions → common issues
   - plan: title → goals → timeline (by day/week/phase) → specific steps → notes → reference sources
   - manual: title → overview → procedures → troubleshooting
5. Write content, preserving source annotations when citing upstream materials
6. Write to file and return path

## Quality Standards
- Technical docs: code examples match current code version, parameter tables complete
- Structured plans: explicit timelines (day/week/phase), each step directly actionable
- All types: any key point findable within 30 seconds
- Upstream research citations preserve source URLs

## Common Failure Modes
- Outdated examples that don't match actual interfaces
- Plan documents missing concrete timelines or actionable steps
- Disorganized structure mixing reference and tutorial content
- Losing upstream source information

## Output Format
Markdown file with hierarchical structure adapted to doc_type.
