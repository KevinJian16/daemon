---
name: rework-feedback
description: >-
  Generate structured, actionable rework instructions when a reviewed artifact
  fails quality standards. ALWAYS activate when a review result contains failed
  items that require the producing agent to revise. Classify issues by type and
  severity; reference specific locations in the artifact. NEVER give vague
  feedback without specifying what is wrong, where, and what the fix should look
  like.
---

# Skill: rework_feedback

## Purpose
When a reviewed artifact fails quality standards, generate structured rework feedback that identifies specific issues and provides actionable guidance for the producing agent to fix them.

## Steps
1. Receive the failed review result (issues list, severity, artifact reference)
2. Classify each issue by type: factual error, style mismatch, structural problem, missing content, policy violation
3. For each issue, produce actionable feedback: what is wrong, where it is, what the fix should look like
4. Prioritize issues by severity (blocking → important → suggestion)
5. Format feedback as structured rework instructions for the target agent
6. Ensure feedback references specific locations in the artifact (section, line, paragraph)

## Input
- Review result with issues list
- Original artifact (via MinIO reference)
- Quality standards that were violated
- Target agent ID (who will do the rework)

## Output
- Structured rework instructions (ordered by priority)
- Per-issue: type, location, description, suggested fix
- Overall rework scope estimate (minor / moderate / major)

## Token Budget
~3000 tokens (analysis of review results + feedback generation)
