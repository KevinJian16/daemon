---
name: replan-assessment
description: >-
  Evaluate a completed Job's output against its original goal and decide whether
  replanning is needed. ALWAYS activate at the Replan Gate after every Job
  closes. Compare output to goal, check downstream input requirements, and
  classify deviation as none/adjustable/replan. NEVER pass a clearly deficient
  output through the gate. NEVER introduce new Jobs unrelated to the original
  goal during replanning.
---

# Replan Assessment

## Applicable Scenarios
After a Job completes, evaluate whether its output deviates from the original goal and decide whether replanning is needed.

## Input
Original goal + Job execution result + current DAG state.

## Execution Steps
1. Compare Job output against the expected goal for alignment
2. Check whether the output satisfies downstream Job input requirements
3. Classify deviation level: none / adjustable / replan
4. If replanning is needed, provide an adjustment plan (modify/add/remove Jobs)

## Quality Standards
- Deviation classification must be based on concrete evidence, not subjective impressions
- Replan proposals must maintain DAG consistency

## Common Failure Modes
- Being overly optimistic about partially completed results, passing deficient output through the gate
- Introducing new Jobs unrelated to the original goal during replanning

## Output Format
```
Deviation level: none / adjustable / replan
Reason: ...
Adjustment plan: [only provided for adjustable/replan]
```
