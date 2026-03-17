---
name: code-review
description: >-
  Audit code changes for correctness, security, and style conformance, producing
  categorized findings with line references. ALWAYS activate when code diffs or
  changed files need independent review. Mark all security issues as blockers.
  NEVER review changed lines in isolation without reading surrounding context.
  NEVER mix severity levels (blocker vs. nit) without clear categorization.
---

# Code Review

## 适用场景
审查代码变更的正确性、安全性和风格一致性。

## 输入
代码 diff 或文件路径列表。

## 执行步骤
1. 读取变更文件，理解修改意图
2. 检查正确性：逻辑错误、边界条件、异常处理
3. 检查安全性：注入、硬编码凭证、不安全依赖
4. 检查风格：命名规范、类型注解、文档字符串
5. 按严重程度标注发现项

## 质量标准
- 安全问题必须标为 blocker
- 每条反馈附具体行号和修正建议

## 常见失败模式
- 只看改动行，忽略上下文逻辑
- 风格问题与正确性问题混为一谈

## 输出格式
```
[blocker/warning/nit] file:line - 描述 | 建议修改
```
