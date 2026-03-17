---
name: implementation
description: >-
  Implement new features or fix bugs, producing working code that follows
  existing patterns. ALWAYS activate when the step goal requires writing or
  modifying source code. Read existing code structure and conventions before
  writing. NEVER write code without first reading the target module's existing
  style. NEVER skip error handling or boundary checks.
---

# Implementation

## When to Activate
When new functionality must be implemented or a bug fixed, producing working code.

## Input
- Feature requirement or bug fix description
- Target module/file (optional)

## Execution Steps
1. Use `code_structure` to understand the target module's existing structure
2. Use `code_imports` to identify reusable dependencies and utility functions
3. Use `read_file` to read related code, understand existing patterns and conventions
4. Write implementation code following existing code style
5. Use `write_file` to write changes
6. Use `read_file` to read back and verify the write is correct

## Quality Standards
- Follow the target module's existing code style and naming conventions
- Include necessary error handling and boundary checks
- New public functions must have docstrings

## Common Failure Modes
- Writing code without reading existing code first, causing style inconsistency or duplicate implementation
- Only writing the happy path, ignoring exception handling

## Output Format
List of changed files with a change summary per file. If new public APIs are added, include signature descriptions.
