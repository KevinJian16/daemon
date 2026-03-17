---
name: replan-assessment
description: >-
  Evaluate a completed Job's output against its original goal and decide whether
  replanning is needed. ALWAYS activate at the Replan Gate after every Job
  closes. Compare output to goal, check downstream input requirements, and
  classify deviation as none/adjustable/replan. NEVER pass a clearly deficient
  output through the gate. NEVER introduce new Jobs unrelated to the original
  goal during replanning.
---

# Replan Assessment

## 适用场景
Job 完成后评估结果是否偏离原始目标，决定是否需要重新规划。

## 输入
原始 goal + Job 执行结果 + 当前 DAG 状态。

## 执行步骤
1. 比对 Job 输出与预期目标的匹配度
2. 检查输出是否满足下游 Job 的输入要求
3. 判定偏差级别：无偏差 / 可调整 / 需重规划
4. 若需重规划，给出调整方案（修改/新增/删除 Job）

## 质量标准
- 偏差判定必须基于具体证据，不凭主观印象
- 重规划方案必须保持 DAG 一致性

## 常见失败模式
- 对部分完成的结果过度乐观，放行不合格输出
- 重规划时引入与原始目标无关的新 Job

## 输出格式
```
偏差级别: none / adjustable / replan
原因: ...
调整方案: [仅 adjustable/replan 时提供]
```
