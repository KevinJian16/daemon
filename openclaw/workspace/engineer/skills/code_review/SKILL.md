---
name: code-review
description: >-
  Review code changes for correctness, security vulnerabilities, and style
  consistency. ALWAYS activate when receiving code diffs or file changes for
  review. Reference specific file paths and line numbers for every issue found.
  NEVER skip security checks (injection, hardcoded credentials, unsafe
  dependencies). NEVER conflate style nits with correctness blockers.
---

# Code Review

## When to Activate
When code changes are received that require review.

## Input
- List of file paths or diffs to review

## Execution Steps
1. Use `code_structure` to get function/class structure of changed files
2. Use `read_file` to read change content file by file
3. Use `code_imports` to check whether dependency changes are reasonable
4. Use `code_functions` to check whether callee signatures match
5. Record issues, categorize by severity (blocker / suggestion / nit)

## Quality Standards
- Every issue must reference a specific file and line number
- Blockers must explain the reason and fix direction
- Do not miss public API signature changes

## Common Failure Modes
- Only checking surface formatting without verifying call chain consistency
- Ignoring boundary conditions and error handling paths

## Output Format
Issue list grouped by file, each containing: file path, line number, severity, description, suggested fix.
