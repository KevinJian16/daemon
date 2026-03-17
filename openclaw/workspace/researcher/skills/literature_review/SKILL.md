---
name: literature-review
description: >-
  Conduct a systematic literature review on a topic, producing a structured
  survey of foundational work, mainstream methods, and recent advances. ALWAYS
  activate when the goal is a comprehensive survey or state-of-the-art analysis.
  Cover three layers: foundational, mainstream, and cutting-edge work. NEVER
  produce a mere list of papers without analytical narrative and synthesis.
---

# Literature Review

## 适用场景
需要对某主题进行系统性文献综述，梳理研究脉络和现状。

## 输入
- `topic`: 综述主题
- `scope`: 时间范围、领域限定
- `paper_count`: 目标论文数量（默认 5-8，避免过多导致超时）

## 执行步骤
1. 用 `semantic_scholar_search` 搜索核心论文（2 组关键词，每组取 top 5）
2. 从搜索结果中选取 5-8 篇最相关论文（优先高引用 + 近期）
3. 对 top 2 高引用论文调 `semantic_scholar_references` 找上游开创性工作（限 3 篇）
4. 对 top 2 近期论文调 `semantic_scholar_citations` 找下游最新进展（限 3 篇）
5. 按时间线和主题聚类，撰写综述
6. 注意：跳过 `ragflow_retrieve`（仅在知识库已有相关资料时使用）

## 效率指导
- 总 API 调用控制在 6-8 次（2 search + 2 references + 2 citations）
- 不追求穷尽，追求核心覆盖
- 搜索结果足够时不需要额外 citation 追溯

## 质量标准
- 覆盖：开创性工作 + 主流方法 + 最新进展三层
- 每篇引用论文标注（作者, 年份）
- 明确指出研究空白和争议点

## 常见失败模式
- 只沿一条引用链走 → 用多组关键词交叉搜索
- 综述变成论文列表 → 必须有分析性叙述和归纳
- API 调用过多导致超时 → 控制总调用次数

## 输出格式
结构化综述：`## 背景` → `## 主要方法/流派` → `## 最新进展` → `## 研究空白` → `## 参考文献列表`
