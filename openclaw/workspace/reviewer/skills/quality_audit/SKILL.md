---
name: quality-audit
description: >-
  Evaluate whether an output artifact meets the original requirements and
  acceptance criteria. ALWAYS activate when a completed deliverable must be
  validated against its specification. Check every acceptance criterion; flag
  missing and extraneous content. NEVER pass an artifact that fails any blocking
  criterion. NEVER do surface-only checks without verifying substantive content.
---

# Quality Audit

## 适用场景
评估整体输出是否满足原始需求和质量标准。

## 输入
原始需求描述 + 实际输出产物。

## 执行步骤
1. 提取需求中的验收条件
2. 逐条比对输出是否满足每项条件
3. 检查遗漏：需求中提到但输出中未体现的内容
4. 检查多余：输出中有但需求未要求的内容
5. 给出通过/不通过判定及差距列表

## 质量标准
- 每项验收条件必须有明确的通过/不通过判定
- 不通过项必须说明差距和补救路径

## 常见失败模式
- 需求理解偏差导致评估标准错误
- 只做形式检查，未验证实质内容

## 输出格式
```
总判定: PASS / FAIL
[PASS/FAIL] 条件描述 | 证据或差距说明
```
