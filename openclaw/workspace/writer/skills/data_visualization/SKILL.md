---
name: data-visualization
description: >-
  Transform structured data into charts, tables, or diagrams (Markdown tables,
  matplotlib, Mermaid) for clear visual communication. ALWAYS activate when the
  goal involves presenting data comparisons, trends, rankings, or architecture
  as visual artifacts. Label all axes, add titles and legends, cite data
  sources. NEVER exceed 6 comparison dimensions per chart. NEVER omit source
  attribution below the visualization.
---

# Data Visualization

## When to Activate
When data comparisons, trend analyses, rankings, or similar information need to be transformed into charts or structured tables.

## Input
- `data`: Structured data or comparison dimensions from upstream researcher
- `chart_type`: Chart type (table / bar / line / radar / comparison)
- `format`: Output format (markdown_table / matplotlib_png / mermaid_svg)

## Execution Steps
1. Organize upstream data, confirm comparison dimensions and data sources
2. Select the most appropriate visualization form:
   - Comparison (<=5 items x <=6 dimensions) → Markdown table + scores
   - Time trends → line chart (matplotlib)
   - Multi-dimensional comparison → radar chart (matplotlib)
   - Process/architecture → Mermaid diagram
3. Generate chart:
   - Markdown table: output directly in document
   - matplotlib: call `chart_matplotlib` MCP tool with Python script
   - Mermaid: call `chart_mermaid` MCP tool with DSL
4. Add chart title, legend, data source attribution
5. Write to file and return path

## Quality Standards
- Data accurate and consistent with upstream source
- Charts include title, axis labels, legend
- Source URL annotated below the chart
- Comparison dimensions do not exceed 6 (prevent information overload)

## Common Failure Modes
- Inconsistent data dimensions (some items missing data for a dimension) → mark N/A
- matplotlib script syntax errors → test with a simple script first
- Too many dimensions making chart unreadable → split into multiple charts

## Output Format
Markdown file with embedded tables or chart path references. Images output to `state/artifacts/` directory.
