---
name: release-checklist
description: >-
  Execute a pre-release checklist to verify all publishing conditions are met
  before a version release. ALWAYS activate before creating a GitHub release or
  deploying a new version. Block the release if any mandatory check fails. NEVER
  skip version consistency checks across pyproject.toml, package.json, and
  CHANGELOG.
---

# Release Checklist

## When to Activate
When executing a pre-release checklist to verify all release conditions are met.

## Input
Version number to release + target branch/tag.

## Execution Steps
1. Confirm all related issues/PRs are closed or merged
2. Confirm all CI tests pass
3. Confirm CHANGELOG is updated
4. Confirm version numbers are consistent (pyproject.toml / package.json etc.)
5. Confirm no uncommitted changes
6. Generate check report

## Quality Standards
- Any mandatory item failing blocks the release
- Report must include check result and evidence for each item

## Common Failure Modes
- Version numbers inconsistent across multiple files
- Missing check on dependency lockfile versions

## Output Format
```
Release v{version} pre-check: READY / BLOCKED
[PASS/FAIL] check item | details
```
