---
name: implementation
description: >-
  Implement new features or fix bugs, producing working code that follows
  existing patterns. ALWAYS activate when the step goal requires writing or
  modifying source code. Read existing code structure and conventions before
  writing. NEVER write code without first reading the target module's existing
  style. NEVER skip error handling or boundary checks.
---

# Implementation

## 适用场景
需要实现新功能或修复 bug，产出可运行代码时触发。

## 输入
- 功能需求或 bug 修复描述
- 目标模块/文件（可选）

## 执行步骤
1. 用 `code_structure` 了解目标模块的现有结构
2. 用 `code_imports` 确认可复用的依赖和工具函数
3. 用 `read_file` 阅读相关代码，理解现有模式和约定
4. 编写实现代码，遵循现有代码风格
5. 用 `write_file` 写入变更
6. 用 `read_file` 回读验证写入结果正确

## 质量标准
- 遵循目标模块的现有代码风格和命名约定
- 包含必要的错误处理和边界检查
- 新增公共函数必须有 docstring

## 常见失败模式
- 不读现有代码就动手，导致风格不一致或重复实现
- 只写 happy path，忽略异常处理

## 输出格式
变更文件列表及每个文件的变更摘要。如有新增公共 API，附签名说明。
