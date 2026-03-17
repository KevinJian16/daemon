---
name: refactor
description: >-
  Refactor code (rename, extract, restructure) without changing external
  behavior. ALWAYS activate when the goal is to improve code structure while
  preserving semantics. Find ALL reference points before making changes. NEVER
  leave stale references after renaming. NEVER introduce circular imports.
---

# Refactor

## 适用场景
需要重构代码（重命名、提取函数、调整模块结构）且不改变外部行为时触发。

## 输入
- 重构目标描述（如"将 X 函数拆分"或"重命名 Y 为 Z"）
- 涉及的文件/模块范围

## 执行步骤
1. 用 `code_structure` 理解当前模块结构
2. 用 `code_functions` 找出目标符号的所有定义
3. 用 `code_imports` 找出所有导入和引用点
4. 制定变更计划，列出所有需要修改的文件
5. 用 `write_file` 逐文件执行变更
6. 用 `read_file` 验证每个变更点的上下文正确性

## 质量标准
- 所有引用点必须同步更新，不遗漏
- 变更后模块的公共 API 语义不变
- 不引入循环导入

## 常见失败模式
- 改了定义但漏改调用方
- 字符串中的引用（如日志、配置键）未同步更新

## 输出格式
变更文件列表，每个文件标注变更类型（修改/新增/删除）和变更摘要。
