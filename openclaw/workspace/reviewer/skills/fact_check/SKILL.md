---
name: fact-check
description: >-
  Verify factual claims in text by classifying each as Tier A (primary source
  confirmed), Tier B (secondary source or reasonable inference), or Tier C
  (unsupported or contradicted). ALWAYS activate when output contains factual
  assertions (numbers, dates, causal claims, citations) that need verification.
  NEVER label an unverified claim as Tier A. NEVER skip implicit claims (e.g.,
  comparative statements implying a baseline).
---

# Fact Check

## When to Activate
When verifying whether factual claims in output have source support.

## Input
Text paragraphs or list of claims to verify.

## Execution Steps
1. Extract all factual claims (numbers, dates, causal assertions, citations)
2. Classify each claim: Tier A (primary source confirmed), Tier B (secondary source or reasonable inference), Tier C (unsupported or contradicted)
3. Use MCP tools to retrieve relevant source documents for comparison
4. Output classification results and correction suggestions

## Quality Standards
- Tier C claims must include a correction plan
- Unverified claims must not be labeled Tier A

## Common Failure Modes
- Surface keyword matching only, without verifying semantic consistency
- Missing implicit claims (e.g., "significant improvement" implies a comparison baseline)

## Output Format
One line per claim: `[A/B/C] claim content | source / correction suggestion`
