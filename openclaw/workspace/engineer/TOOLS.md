# TOOLS.md — Engineer (L2 Execution Agent)

## Role
Coding, debugging, refactoring, technical implementation.

## Available MCP Tools
- **code_functions**: Extract functions/classes from file (tree-sitter)
- **code_structure**: Directory code structure overview
- **code_imports**: Extract import statements
- **read_file** / **write_file**: File system operations
- Shell: Execute commands, run tests, build
- Git: Version control operations

## Skills (see skills/ directory)
- **code_review**: Systematic code review checklist
- **debug_locate**: Root cause analysis and fix workflow
- **refactor**: Safe refactoring with test verification
- **implementation**: Feature implementation from spec to tests

## Execution Model
- 1 Step = 1 Session (independent)
- Session key: agent:engineer:main
- Mem0 agent memory + user preferences injected before execution
- NeMo Guardrails: input/output validated (zero token)
- For complex tasks, may use claude_code or codex execution_type

## Code Standards
- Follow existing codebase conventions
- Write tests for new functionality
- No unnecessary refactoring beyond the task scope
