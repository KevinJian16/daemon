# TOOLS.md — Writer (L2 Execution Agent)

## Role
Writing, content production, format adaptation. Essays, articles, reports, external communications.

## Available MCP Tools
- **latex_compile**: LaTeX → PDF compilation
- **bibtex_format**: Format BibTeX entries
- **chart_matplotlib**: Generate charts (matplotlib)
- **chart_mermaid**: Render Mermaid diagrams to SVG
- **read_file** / **write_file**: File system operations

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
