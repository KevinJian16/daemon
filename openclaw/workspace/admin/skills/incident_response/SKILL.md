---
name: incident-response
description: >-
  Respond to system failures: triage, contain the blast radius, diagnose root
  cause, fix, and produce a post-mortem. ALWAYS activate when a system component
  is down or degraded and user operations are impacted. Contain the incident
  BEFORE diagnosing root cause. NEVER skip containment to jump straight into
  debugging. NEVER close an incident without a prevention measure in the
  post-mortem.
---

# Incident Response

## 适用场景
系统故障发生时进行诊断、止血和恢复。

## 输入
故障现象描述 + 影响范围 + 告警来源。

## 执行步骤
1. 确认故障范围：受影响的组件和用户操作
2. 止血：隔离故障组件，防止扩散（重启服务 / 切流量）
3. 诊断：检查日志、Temporal workflow 状态、PG 连接池
4. 修复：执行修复操作并验证
5. 记录：写入事后报告（时间线 + 根因 + 改进项）

## 质量标准
- 止血必须在诊断之前
- 事后报告必须包含防复发措施

## 常见失败模式
- 跳过止血直接调试，导致影响扩大
- 修复后未验证，故障复发

## 输出格式
```
事件: {描述} | 状态: 已恢复/处理中
时间线: 发现→止血→修复→验证
根因: ...
防复发: ...
```
