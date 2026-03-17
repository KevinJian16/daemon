# SKILL_GRAPH.md — writer

## Entry Points
- "write paper" | "academic" → academic_paper
- "announce" | "news" → announcement
- "visualize" | "chart" | "graph" → data_visualization
- "document" | "docs" → documentation
- "blog" | "article" → tech_blog

## Edges
- tech_blog → data_visualization (blog needs charts/diagrams)
- academic_paper → data_visualization (paper needs figures)
- documentation → data_visualization (docs need diagrams)
- announcement → tech_blog (announcement leads to detailed blog post)
