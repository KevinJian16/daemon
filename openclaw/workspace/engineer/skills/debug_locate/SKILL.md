---
name: debug-locate
description: >-
  Locate the root cause of a bug by tracing from symptoms through the call chain
  to the originating code. ALWAYS activate when given an error message, stack
  trace, or anomalous behavior to diagnose. Follow the full call chain; NEVER
  stop at the first suspicious location without completing the trace. NEVER
  confuse a surface symptom with the root cause.
---

# Debug Locate

## 适用场景
需要定位 bug 根因时触发。已知症状（错误信息/异常行为），需找到出问题的代码位置。

## 输入
- 错误信息或异常行为描述
- 相关模块/文件范围（可选）

## 执行步骤
1. 从错误信息提取关键词（函数名、异常类型、变量名）
2. 用 `code_functions` 在目标模块中搜索相关函数
3. 用 `read_file` 阅读可疑函数，追踪数据流
4. 用 `code_imports` 确认跨模块调用关系
5. 沿调用链向上/向下追踪，直到定位根因

## 质量标准
- 必须给出根因所在的具体文件和函数
- 必须解释从症状到根因的推理链
- 区分根因与表面症状

## 常见失败模式
- 停在第一个可疑点就下结论，不做完整链路追踪
- 混淆相关代码和实际触发路径

## 输出格式
根因位置（文件:函数:行号）、推理链、建议修复方向。
