---
name: cc-codex-handoff
description: >-
  Prepare and execute a Claude Code or Codex subprocess for code-intensive
  steps, including context file generation and subprocess lifecycle management.
  ALWAYS activate when execution_type is claude_code or codex. Generate
  CLAUDE.md context from prior artifacts, inject MEMORY.md, and manage
  subprocess timeout. NEVER launch a subprocess without gathering upstream
  artifact context first.
---

# Skill: cc_codex_handoff

## Purpose
Prepare and execute a Claude Code or Codex subprocess for code-intensive Steps, including generating context files (CLAUDE.md / AGENTS.md) from prior Artifacts and managing the subprocess lifecycle.

## Steps
1. Receive Step goal and execution_type (claude_code | codex)
2. Gather prior Artifacts from upstream Steps/Jobs via MinIO
3. Generate CLAUDE.md context file: project summary, relevant code paths, constraints
4. Generate AGENTS.md if multi-agent coordination is needed
5. Inject MEMORY.md content for the assigned agent
6. Launch subprocess via code_exec MCP tool with appropriate working directory
7. Monitor subprocess output, enforce timeout per Step type
8. Capture output artifacts and upload to MinIO
9. Return structured result with artifact references

## Input
- Step goal and execution_type (claude_code | codex)
- Prior Artifact summaries from upstream Steps
- Agent MEMORY.md content
- Working directory path
- Timeout (default: 300s for code tasks)

## Output
- Subprocess exit code and stdout/stderr summary
- Artifact IDs uploaded to MinIO
- Generated file paths (if any)
- Error details on failure

## Token Budget
~1500 tokens (subprocess orchestration, minimal LLM reasoning)
