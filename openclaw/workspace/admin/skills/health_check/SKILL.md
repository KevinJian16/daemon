---
name: health-check
description: >-
  Diagnose the running status of all system components (API, Worker, PostgreSQL,
  MinIO, Langfuse, Temporal). ALWAYS activate when the goal is to check system
  health or when anomalies are suspected. Verify actual service response, not
  just port availability. NEVER report a service as healthy based solely on an
  open port without a successful response.
---

# Health Check

## When to Activate
When diagnosing the running status of system components and detecting potential failures.

## Input
Optional: specify check scope (all / api / worker / infra).

## Execution Steps
1. Check API process: HTTP endpoint reachability and response time
2. Check Worker process: Temporal worker registration status
3. Check infrastructure: PostgreSQL / MinIO / Langfuse connectivity
4. Check resources: disk space, memory usage
5. Summarize anomalies and provide fix recommendations

## Quality Standards
- Every component must have a clear healthy/degraded/down status
- Response time exceeding threshold marked as degraded

## Common Failure Modes
- Only checking port availability without verifying actual service response
- Missing check on Temporal namespace status

## Output Format
```
System Status: HEALTHY / DEGRADED / DOWN
[healthy/degraded/down] component name | details
```
