---
name: web-research
description: >-
  Search the internet and scrape web pages to gather information on any topic:
  technical docs, news, product comparisons, health, lifestyle, etc. ALWAYS
  activate when the goal requires up-to-date web information rather than
  academic papers. Cross-verify facts from at least 2 independent sources. NEVER
  present information without its source URL. NEVER treat opinions as facts.
---

# Web Research

## 适用场景
需要从互联网获取信息：技术文档、新闻、博客、产品对比、健康/生活/学习资讯等。

## 输入
- `query`: 搜索问题或关键词
- `depth`: shallow（仅摘要）| deep（抓取全文）
- `domain`: 可选，限定领域关键词（如 "evidence-based", "peer-reviewed"）

## 执行步骤
1. 用 `brave_search` 搜索，获取 URL 列表和摘要
2. 筛选最相关的 3-5 个 URL（优先官方/权威来源）
3. 对筛选结果调 `firecrawl_scrape` 抓取页面转 Markdown
4. 提取关键段落，标注来源 URL
5. 对健康/医学/法律等敏感领域，标注"非专业建议"

## 质量标准
- 每条信息必须附原始 URL
- 交叉验证：同一事实至少 2 个独立来源
- 注明信息时效性（发布日期）
- 敏感领域优先引用政府/学术/专业机构来源

## 常见失败模式
- 只用一个搜索词 → 换同义词/不同角度重搜
- 抓取失败（paywall/反爬）→ 用摘要替代，标注"未获取全文"
- 把观点当事实 → 区分事实陈述与作者观点
- 健康类信息引用非权威来源 → 优先 WHO/NIH/Mayo Clinic 等

## 输出格式
按主题分段，每段末尾标注 `[来源](URL)`，最后附来源汇总列表。输出为结构化数据，便于下游 writer 直接消费。
