---
name: code-review
description: >-
  Audit code changes for correctness, security, and style conformance, producing
  categorized findings with line references. ALWAYS activate when code diffs or
  changed files need independent review. Mark all security issues as blockers.
  NEVER review changed lines in isolation without reading surrounding context.
  NEVER mix severity levels (blocker vs. nit) without clear categorization.
---

# Code Review

## When to Activate
When reviewing code changes for correctness, security, and style consistency.

## Input
Code diff or list of file paths.

## Execution Steps
1. Read changed files, understand modification intent
2. Check correctness: logic errors, boundary conditions, exception handling
3. Check security: injection, hardcoded credentials, unsafe dependencies
4. Check style: naming conventions, type annotations, docstrings
5. Categorize findings by severity

## Quality Standards
- Security issues must be marked as blocker
- Each finding includes specific line number and fix suggestion

## Common Failure Modes
- Only reading changed lines, ignoring surrounding context logic
- Conflating style issues with correctness issues

## Output Format
```
[blocker/warning/nit] file:line - description | suggested fix
```
