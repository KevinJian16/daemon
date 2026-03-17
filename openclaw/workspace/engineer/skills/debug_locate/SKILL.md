---
name: debug-locate
description: >-
  Locate the root cause of a bug by tracing from symptoms through the call chain
  to the originating code. ALWAYS activate when given an error message, stack
  trace, or anomalous behavior to diagnose. Follow the full call chain; NEVER
  stop at the first suspicious location without completing the trace. NEVER
  confuse a surface symptom with the root cause.
---

# Debug Locate

## When to Activate
When a bug root cause needs to be located. Known symptoms (error messages/anomalous behavior) exist; the faulty code location must be found.

## Input
- Error message or anomalous behavior description
- Relevant module/file scope (optional)

## Execution Steps
1. Extract keywords from error message (function name, exception type, variable name)
2. Use `code_functions` to search for relevant functions in target module
3. Use `read_file` to read suspicious functions, trace data flow
4. Use `code_imports` to confirm cross-module call relationships
5. Trace up/down the call chain until root cause is located

## Quality Standards
- Must identify the specific file and function where the root cause resides
- Must explain the reasoning chain from symptom to root cause
- Distinguish root cause from surface symptoms

## Common Failure Modes
- Stopping at the first suspicious point without completing full chain trace
- Confusing related code with the actual trigger path

## Output Format
Root cause location (file:function:line), reasoning chain, suggested fix direction.
