---
name: requires-review-judgment
description: >-
  Decide whether a Job's output requires user review before downstream steps
  proceed. ALWAYS activate when planning or completing a Job that produces
  external-facing, irreversible, or high-stakes output. ALWAYS set
  requires_review=true for external publication, code deployment, or
  financial/legal actions. NEVER require review for internal analysis, drafts,
  or intermediate artifacts.
---

# Requires Review Judgment

## Applicable Scenarios
When deciding whether a Job's output needs user review before proceeding.

## Input
Job plan (steps, agents, outputs) + Task context.

## Execution Steps
1. Assess output type: external-facing? high-stakes? irreversible?
2. Check if output modifies external systems (publishing, email, code deploy)
3. Check if output involves financial or legal implications
4. Decide: requires_review = true/false

## Decision Rules
- External publication → requires_review = true
- Code deployment → requires_review = true
- Internal analysis/research → requires_review = false
- Draft/intermediate output → requires_review = false
- User explicitly asked "don't ask me" → requires_review = false

## Output
Boolean `requires_review` flag + brief reason.
