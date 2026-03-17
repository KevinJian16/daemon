# SKILL_GRAPH.md — engineer

## Entry Points
- "implement" | "build" | "write code" → implementation
- "debug" | "fix" | "error" → debug_locate
- "review" | "check code" → code_review
- "refactor" | "clean up" → refactor

## Edges
- implementation → code_review (after writing, review quality)
- debug_locate → implementation (after finding root cause, implement fix)
- code_review → refactor (when review finds structural issues)
- refactor → code_review (verify refactored code)
