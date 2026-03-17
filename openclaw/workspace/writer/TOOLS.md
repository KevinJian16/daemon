# TOOLS.md — Writer (L2 Execution Agent)

## Role
Writing, content production, format adaptation. Essays, articles, reports, external communications.

## Available MCP Tools
- **read_file** / **write_file**: File system operations (filesystem MCP)
- **brave_search**: Web search for research and references (brave-search MCP)
- **firecrawl_scrape**: Fetch and convert web pages to clean Markdown (firecrawl MCP)
- **github_***: GitHub repository operations — read files, open PRs (github MCP)
- **code_exec**: Execute code tasks via Claude Code or Codex CLI (code-exec MCP)

Note: latex_compile, bibtex_format, chart_matplotlib, chart_mermaid are NOT registered
in config/mcp_servers.json and are not available. Use code_exec with appropriate
instructions if document compilation or chart generation is needed.

## Skills (see skills/ directory)
- **tech_blog**: Technical blog post writing workflow
- **academic_paper**: Academic paper structure and writing
- **documentation**: Technical documentation and structured plans
- **data_visualization**: Data comparison charts and tables
- **announcement**: External announcement drafting

## Execution Model
- 1 Step = 1 Session (independent)
- Session key: agent:writer:main
- Mem0 agent memory + user preferences injected before execution
- NeMo Guardrails: input/output validated (zero token)
- Default model: creative (GLM Z1 Flash)

## Style Guidelines
- Match user's Persona (loaded from Mem0 at session start)
- Cross-language consistency (Chinese/English style coherent)
- Format adapted to target platform
