---
name: refactor
description: >-
  Refactor code (rename, extract, restructure) without changing external
  behavior. ALWAYS activate when the goal is to improve code structure while
  preserving semantics. Find ALL reference points before making changes. NEVER
  leave stale references after renaming. NEVER introduce circular imports.
---

# Refactor

## When to Activate
When code needs refactoring (rename, extract function, restructure modules) without changing external behavior.

## Input
- Refactoring goal description (e.g., "split function X" or "rename Y to Z")
- Scope of affected files/modules

## Execution Steps
1. Use `code_structure` to understand current module structure
2. Use `code_functions` to find all definitions of the target symbol
3. Use `code_imports` to find all import and reference points
4. Create a change plan listing all files that need modification
5. Use `write_file` to apply changes file by file
6. Use `read_file` to verify context correctness at each change point

## Quality Standards
- All reference points must be updated in sync, with none missed
- Public API semantics of the changed module must remain unchanged
- Do not introduce circular imports

## Common Failure Modes
- Changing the definition but missing call sites
- String references (e.g., log messages, config keys) not updated in sync

## Output Format
List of changed files, each annotated with change type (modified / added / deleted) and change summary.
