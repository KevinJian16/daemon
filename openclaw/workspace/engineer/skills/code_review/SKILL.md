---
name: code-review
description: >-
  Review code changes for correctness, security vulnerabilities, and style
  consistency. ALWAYS activate when receiving code diffs or file changes for
  review. Reference specific file paths and line numbers for every issue found.
  NEVER skip security checks (injection, hardcoded credentials, unsafe
  dependencies). NEVER conflate style nits with correctness blockers.
---

# Code Review

## 适用场景
收到代码变更需要审查时触发。

## 输入
- 待审查的文件路径列表或 diff

## 执行步骤
1. 用 `code_structure` 获取变更文件的函数/类结构
2. 用 `read_file` 逐文件阅读变更内容
3. 用 `code_imports` 检查依赖变更是否合理
4. 用 `code_functions` 检查被调用方签名是否匹配
5. 记录问题，按严重程度分类（阻塞/建议/nit）

## 质量标准
- 每个问题必须引用具体文件和行号
- 阻塞项必须说明原因和修复方向
- 不遗漏公共 API 签名变更

## 常见失败模式
- 只看表面格式，不验证调用链一致性
- 忽略边界条件和错误处理路径

## 输出格式
按文件分组的问题列表，每条含：文件路径、行号、严重程度、描述、建议修复。
