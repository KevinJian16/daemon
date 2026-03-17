---
name: incident-response
description: >-
  Respond to system failures: triage, contain the blast radius, diagnose root
  cause, fix, and produce a post-mortem. ALWAYS activate when a system component
  is down or degraded and user operations are impacted. Contain the incident
  BEFORE diagnosing root cause. NEVER skip containment to jump straight into
  debugging. NEVER close an incident without a prevention measure in the
  post-mortem.
---

# Incident Response

## When to Activate
When a system failure occurs requiring diagnosis, containment, and recovery.

## Input
Failure symptom description + impact scope + alert source.

## Execution Steps
1. Confirm failure scope: affected components and user operations
2. Contain: isolate faulty component, prevent spread (restart service / divert traffic)
3. Diagnose: check logs, Temporal workflow state, PG connection pool
4. Fix: execute fix and verify
5. Document: write post-mortem (timeline + root cause + improvement items)

## Quality Standards
- Containment must precede diagnosis
- Post-mortem must include recurrence prevention measures

## Common Failure Modes
- Skipping containment to debug directly, causing wider impact
- Not verifying after fix, leading to recurrence

## Output Format
```
Incident: {description} | Status: recovered / in progress
Timeline: detected → contained → fixed → verified
Root cause: ...
Prevention: ...
```
