---
name: quality-audit
description: >-
  Evaluate whether an output artifact meets the original requirements and
  acceptance criteria. ALWAYS activate when a completed deliverable must be
  validated against its specification. Check every acceptance criterion; flag
  missing and extraneous content. NEVER pass an artifact that fails any blocking
  criterion. NEVER do surface-only checks without verifying substantive content.
---

# Quality Audit

## When to Activate
When evaluating whether overall output meets original requirements and quality standards.

## Input
Original requirement description + actual output artifact.

## Execution Steps
1. Extract acceptance criteria from requirements
2. Compare output against each criterion one by one
3. Check for omissions: content mentioned in requirements but absent from output
4. Check for extras: content in output not required by specification
5. Issue pass/fail verdict with gap list

## Quality Standards
- Every acceptance criterion must have a clear pass/fail determination
- Failed items must describe the gap and remediation path

## Common Failure Modes
- Misunderstanding requirements leading to wrong evaluation criteria
- Surface-only checks without verifying substantive content

## Output Format
```
Verdict: PASS / FAIL
[PASS/FAIL] criterion description | evidence or gap explanation
```
