---
name: frontier-iteration
description: >-
  Evaluate and integrate updates to AI models, infrastructure components, or
  open-source tools through a phased process: assessment, compatibility
  analysis, sandbox testing, gradual rollout, and documentation. ALWAYS activate
  when a new model release, major dependency upgrade, or capability gap triggers
  an evaluation. NEVER switch a primary component without a rollback plan. NEVER
  skip sandbox testing before production rollout.
---

# Frontier-Driven Iteration

## When to Activate
When evaluating and integrating updates to AI models, infrastructure components, or open-source tools to continuously improve daemon capabilities. Triggers: new model release, major dependency version upgrade, user feedback revealing capability gaps.

## Input
- `component`: Component to evaluate (model/library/tool name)
- `current_version`: Currently used version or model ID
- `candidate`: Candidate upgrade (new version/new model)
- `evaluation_criteria`: Evaluation dimensions (speed/quality/cost/stability)

## Execution Steps

### Phase 1: Evaluation Trigger
1. Confirm upgrade trigger reason (performance gap / new feature need / security vulnerability / community recommendation)
2. Check current component's performance baseline (get historical token usage and error rate from Langfuse)
3. Obtain candidate version's changelog and known breaking changes

### Phase 2: Compatibility Analysis
1. Check API compatibility: whether new version has interface changes
2. Check if openclaw.json model configuration needs updating
3. Assess impact on existing Skill/SOUL files
4. Identify downstream services depending on this component (activities.py, session_manager, etc.)

### Phase 3: Sandbox Validation
1. Create experimental configuration in `config/` with new version (do not modify production config)
2. Select 3-5 representative tasks for comparative testing
3. Record comparison results: output quality / latency / token consumption / error rate
4. Comparison threshold: new version at least matches on primary dimensions, improves on target dimension

### Phase 4: Gradual Rollout
1. Update openclaw.json or related config, set new version as fallback
2. Observe for 1-2 business days, monitor for anomalies via Langfuse
3. If stable, promote new version to primary
4. Update relevant SYSTEM_DESIGN.md sections to record version change

### Phase 5: Documentation and Retrospective
1. Update relevant documents in `.ref/` (version numbers, feature descriptions)
2. Record iteration experience in Mem0 (improvement points + caveats)
3. If upgrade fails, rollback and document the reason to avoid repeating the mistake

## Evaluation Dimension Weights

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Output Quality | 40% | Compared against ground truth or human evaluation |
| Latency | 20% | P50/P95 response time |
| Cost | 20% | Token unit price x average usage |
| Stability | 20% | Error rate, timeout rate |

## Quality Standards
- Upgrade must not degrade core functionality output quality (quality score no lower than 95% of current version)
- Upgrade must have a rollback plan (old config retained for at least 7 days)
- Major upgrades require autopilot confirmation

## Common Failure Modes
- Switching primary directly without canary → must set as fallback first and observe
- Testing only happy path → must include edge cases and error input tests
- Ignoring breaking changes → changelog must be read completely
- Not updating docs → documentation must be synced after upgrade completion

## Output Format
```
## Upgrade Evaluation Report

**Component**: [component name]
**Current Version**: [version]
**Candidate Version**: [version]
**Evaluation Conclusion**: Recommend upgrade / Do not recommend / Under observation

### Evaluation Results
| Dimension | Current | Candidate | Change |
|-----------|---------|-----------|--------|
| Quality | ... | ... | +X% |
| Latency | ... | ... | -Xms |
| Cost | ... | ... | -X% |
| Stability | ... | ... | ... |

### Key Findings
- [Finding 1]
- [Finding 2]

### Rollout Plan
1. [Step]
2. [Step]

### Rollback Plan
[Rollback steps]
```
