---
name: skill-audit
description: >-
  Audit SKILL.md effectiveness using Langfuse trace data: measure success rate,
  latency, token usage, and identify failure patterns. ALWAYS activate when
  skill performance needs evaluation or when success rates drop below baseline.
  Base all recommendations on actual trace evidence. NEVER propose changes
  without citing specific trace IDs. NEVER draw conclusions from insufficient
  sample sizes.
---

# Skill Audit

## 适用场景
基于 Langfuse 指标评估 SKILL.md 的实际执行效果并提出改进。

## 输入
目标 agent 名 + skill 名，或 "all" 全量审计。

## 执行步骤
1. 从 Langfuse 拉取该 skill 近期 trace 数据（成功率、耗时、token 用量）
2. 分析失败 trace 的根因分布
3. 比对 SKILL.md 文本与实际执行路径的偏差
4. 生成改进建议（步骤调整 / 约束补充 / 示例添加）

## 质量标准
- 改进建议必须基于实际 trace 数据，不凭猜测
- 每条建议附对应的失败 trace ID

## 常见失败模式
- 样本量不足时过早下结论
- 只关注成功率，忽略 token 效率退化

## 输出格式
```
Skill: {agent}/{skill} | 成功率: X% | 均耗时: Xs
[issue] 描述 | trace_id | 建议修改
```
