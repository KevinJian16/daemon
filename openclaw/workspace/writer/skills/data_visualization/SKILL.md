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

## 适用场景
需要将数据对比、趋势分析、排名等信息转化为图表或结构化表格。

## 输入
- `data`: 上游 researcher 提供的结构化数据或对比维度
- `chart_type`: 图表类型（table / bar / line / radar / comparison）
- `format`: 输出格式（markdown_table / matplotlib_png / mermaid_svg）

## 执行步骤
1. 整理上游数据，确认对比维度和数值来源
2. 选择最合适的可视化形式：
   - 对比（≤5 项 × ≤6 维度）→ Markdown 表格 + 评分
   - 时间趋势 → 折线图（matplotlib）
   - 多维对比 → 雷达图（matplotlib）
   - 流程/架构 → Mermaid 图
3. 生成图表：
   - Markdown 表格：直接在文档中输出
   - matplotlib：调用 `chart_matplotlib` MCP tool，传入 Python 脚本
   - Mermaid：调用 `chart_mermaid` MCP tool，传入 DSL
4. 添加图表标题、图例、数据来源标注
5. 写入文件并返回路径

## 质量标准
- 数据准确，与上游来源一致
- 图表有标题、轴标签、图例
- 来源 URL 标注在图表下方
- 对比维度不超过 6 个（防止信息过载）

## 常见失败模式
- 数据维度不一致（某些项缺少某个维度的数据）→ 标注 N/A
- matplotlib 脚本语法错误 → 先用简单脚本验证
- 过多维度导致图表难以阅读 → 拆分为多个图表

## 输出格式
Markdown 文件，内嵌表格或图表路径引用。图片输出到 `state/artifacts/` 目录。
