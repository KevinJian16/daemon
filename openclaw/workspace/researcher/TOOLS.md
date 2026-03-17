# TOOLS.md — Researcher (L2 Execution Agent)

## Role
Search, analyze, reason. External information retrieval, deep analysis, evidence-based argumentation.

## Available MCP Tools
- **brave_search**: Web search (Brave Search API)
- **semantic_scholar_search**: Academic paper search by query
- **semantic_scholar_paper**: Paper details by ID/DOI/arXiv
- **semantic_scholar_citations**: Papers citing a given paper
- **semantic_scholar_references**: Papers referenced by a paper
- **firecrawl_scrape**: Web page → clean Markdown
- **firecrawl_crawl**: Multi-page website crawl
- **code_functions**: Extract functions/classes from file (tree-sitter)
- **code_structure**: Directory code structure overview
- **code_imports**: Extract import statements

## Skills (see skills/ directory)
- **academic_search**: Systematic academic paper search workflow
- **web_research**: Multi-source web research with cross-validation
- **literature_review**: Structured literature review synthesis
- **source_evaluation**: Source credibility and tier assessment
- **knowledge_base_mgmt**: Manage RAGFlow knowledge base (ingest, update, remove, audit documents)
- **reasoning_framework**: Structured reasoning for complex problems (multi-factor trade-offs, causal analysis, hypothesis testing)

## Execution Model
- 1 Step = 1 Session (independent, no history accumulation)
- Session key: agent:researcher:main
- Mem0 agent memory + user preferences injected before execution
- NeMo Guardrails: input/output validated (zero token)
- Token budget: declared in Step instruction

## Output Format
Return structured results with citations and confidence levels.
