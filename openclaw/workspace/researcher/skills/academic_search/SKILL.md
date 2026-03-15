# Academic Search

## 适用场景
需要查找学术论文、引用数据、或特定领域的研究成果。

## 输入
- `query`: 搜索关键词或研究问题
- `max_results`: 返回数量上限（默认 10）

## 执行步骤
1. 用 `semantic_scholar_search` 按 query 检索论文列表
2. 对高相关结果调 `semantic_scholar_paper` 获取摘要、年份、引用数
3. 按引用数 + 年份排序，筛选 top 结果
4. 如需补充，用 `semantic_scholar_citations` 或 `semantic_scholar_references` 扩展

## 质量标准
- 每条结果必须包含：标题、作者、年份、引用数、摘要
- 优先返回 peer-reviewed、高引用论文
- 结果按相关性排序，注明检索词

## 常见失败模式
- 关键词过宽导致噪声多 → 加限定词、用 AND 组合
- 只看第一页结果 → 至少检查前 20 条再筛选
- 忽略近期低引用但高相关的论文 → 按年份分层看

## 输出格式
Markdown 表格：`| # | 标题 | 作者 | 年份 | 引用数 | 摘要（一句话） |`
