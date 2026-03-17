---
name: reasoning-framework
description: >-
  Apply structured reasoning to complex problems involving multi-factor
  trade-offs, causal analysis, hypothesis testing, or strategic decisions.
  ALWAYS activate when the problem has ambiguous boundaries, incomplete
  information, or contradictory evidence. Separate facts from inferences;
  actively seek counter-evidence. NEVER present conclusions without stating
  confidence level and key uncertainties. NEVER skip the counter-argument step.
---

# Reasoning Framework

## 适用场景
需要对复杂问题进行结构化推理：多因素权衡、因果分析、假设检验、战略决策支持。
适合问题边界模糊、信息不完整或存在相互矛盾证据的情况。

## 输入
- `problem`: 需要推理的问题或决策场景描述
- `evidence`: 已知事实、数据、约束条件（可选）
- `depth`: shallow（快速判断）| deep（深度分析，使用 deepseek-reasoner）
- `output_format`: conclusion（结论为主）| structured（结构化推理链）

## 执行步骤

### 浅层推理（shallow）
1. 识别问题核心：一句话描述核心矛盾或决策要点
2. 列举关键因素（3-5 个）
3. 评估每个因素的权重和方向
4. 得出结论，注明置信度（高/中/低）

### 深层推理（deep）
1. **问题拆解**：将复杂问题分解为独立子问题
2. **假设列举**：列出可能的假设前提，标注是否已验证
3. **证据映射**：将已知证据与各假设对应，标注支持/反驳关系
4. **推理链构建**：
   - 前提 → 推论 → 结论（显式标注每步逻辑）
   - 识别推理中的弱环节（信息缺口、因果跳跃）
5. **反驳检验**：主动寻找与结论相悖的证据或反例
6. **结论与建议**：给出结论 + 置信度 + 关键不确定性 + 建议后续行动

## 推理原则
- **分离事实与推论**：明确标注"已知事实"vs"推断"vs"假设"
- **避免确认偏误**：主动寻找反例，不只搜索支持性证据
- **量化不确定性**：用概率区间或高/中/低表达信心程度
- **最小化假设**：优先使用已验证信息，减少未验证假设数量
- **可追溯性**：每个结论必须能追溯到具体证据或推理步骤

## 质量标准
- 推理链完整，无逻辑跳跃
- 关键假设明确列出
- 结论与证据强度匹配（不过度推断）
- 识别并说明主要不确定性来源

## 常见失败模式
- 问题定义不清 → 先与用户确认问题边界
- 证据不足就下结论 → 明确标注"信息不足，结论为初步判断"
- 单一视角分析 → 主动考虑对立观点或利益相关方视角
- 忽略约束条件 → 检查是否遗漏时间/资源/伦理约束

## 输出格式
```
## 问题
[问题陈述]

## 关键假设
- [假设1]（已验证/未验证）
- [假设2]（已验证/未验证）

## 推理过程
1. [步骤1：事实/推断]
2. [步骤2：推论]
...

## 结论
[结论内容]（置信度：高/中/低）

## 主要不确定性
- [不确定因素1]
- [不确定因素2]

## 建议后续行动
- [行动1]
```
