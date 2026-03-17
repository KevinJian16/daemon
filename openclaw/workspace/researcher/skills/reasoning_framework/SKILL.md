---
name: reasoning-framework
description: >-
  Apply structured reasoning to complex problems involving multi-factor
  trade-offs, causal analysis, hypothesis testing, or strategic decisions.
  ALWAYS activate when the problem has ambiguous boundaries, incomplete
  information, or contradictory evidence. Separate facts from inferences;
  actively seek counter-evidence. NEVER present conclusions without stating
  confidence level and key uncertainties. NEVER skip the counter-argument step.
---

# Reasoning Framework

## When to Activate
When structured reasoning is needed for complex problems: multi-factor trade-offs, causal analysis, hypothesis testing, strategic decision support. Suitable when problem boundaries are ambiguous, information is incomplete, or evidence is contradictory.

## Input
- `problem`: Problem or decision scenario description
- `evidence`: Known facts, data, constraints (optional)
- `depth`: shallow (quick judgment) | deep (deep analysis, uses deepseek-reasoner)
- `output_format`: conclusion (conclusion-focused) | structured (full reasoning chain)

## Execution Steps

### Shallow Reasoning
1. Identify the core issue: one-sentence description of the key conflict or decision point
2. List key factors (3-5)
3. Assess each factor's weight and direction
4. Draw a conclusion with confidence level (high / medium / low)

### Deep Reasoning
1. **Problem decomposition**: Break complex problem into independent sub-problems
2. **Hypothesis enumeration**: List possible premises, annotate whether verified
3. **Evidence mapping**: Map known evidence to each hypothesis, annotate support/refute relationships
4. **Reasoning chain construction**:
   - Premise → inference → conclusion (explicitly label each logical step)
   - Identify weak links in reasoning (information gaps, causal leaps)
5. **Counter-argument testing**: Actively seek evidence or counter-examples that contradict the conclusion
6. **Conclusion and recommendations**: Provide conclusion + confidence + key uncertainties + recommended next actions

## Reasoning Principles
- **Separate facts from inferences**: Explicitly label "known fact" vs "inference" vs "assumption"
- **Avoid confirmation bias**: Actively seek counter-examples, not only supporting evidence
- **Quantify uncertainty**: Use probability ranges or high/medium/low for confidence
- **Minimize assumptions**: Prefer verified information, reduce unverified assumption count
- **Traceability**: Every conclusion must trace back to specific evidence or reasoning step

## Quality Standards
- Complete reasoning chain with no logical leaps
- Key assumptions explicitly listed
- Conclusions match evidence strength (no over-extrapolation)
- Major uncertainty sources identified and explained

## Common Failure Modes
- Problem poorly defined → confirm problem boundaries with user first
- Concluding with insufficient evidence → explicitly label "insufficient data, conclusion is preliminary"
- Single-perspective analysis → actively consider opposing viewpoints or stakeholder perspectives
- Ignoring constraints → check for missed time/resource/ethical constraints

## Output Format
```
## Problem
[Problem statement]

## Key Assumptions
- [Assumption 1] (verified / unverified)
- [Assumption 2] (verified / unverified)

## Reasoning Process
1. [Step 1: fact / inference]
2. [Step 2: deduction]
...

## Conclusion
[Conclusion] (confidence: high / medium / low)

## Key Uncertainties
- [Uncertainty 1]
- [Uncertainty 2]

## Recommended Next Actions
- [Action 1]
```
