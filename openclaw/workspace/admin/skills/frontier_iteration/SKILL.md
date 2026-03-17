---
name: frontier-iteration
description: >-
  Evaluate and integrate updates to AI models, infrastructure components, or
  open-source tools through a phased process: assessment, compatibility
  analysis, sandbox testing, gradual rollout, and documentation. ALWAYS activate
  when a new model release, major dependency upgrade, or capability gap triggers
  an evaluation. NEVER switch a primary component without a rollback plan. NEVER
  skip sandbox testing before production rollout.
---

# Frontier-Driven Iteration

## 适用场景
评估并整合前沿 AI 模型、基础设施组件或开源工具的更新，以持续提升 daemon 系统能力。
触发条件：新模型发布、依赖库重大版本升级、用户反馈揭示系统能力短板。

## 输入
- `component`: 需要评估的组件（模型/库/工具名称）
- `current_version`: 当前使用的版本或模型 ID
- `candidate`: 候选升级项（新版本/新模型）
- `evaluation_criteria`: 评估维度（速度/质量/成本/稳定性）

## 执行步骤

### 阶段 1：评估触发
1. 确认升级触发原因（性能不足 / 新功能需求 / 安全漏洞 / 社区推荐）
2. 检查当前组件的性能基线（从 Langfuse 获取历史 token 用量和错误率）
3. 获取候选版本的 changelog 和已知 breaking changes

### 阶段 2：兼容性分析
1. 检查 API 兼容性：新版本是否有接口变更
2. 检查 openclaw.json 中的模型配置是否需要更新
3. 评估对现有 Skill/SOUL 文件的影响
4. 识别依赖该组件的下游服务（activities.py, session_manager 等）

### 阶段 3：沙箱验证
1. 在 `config/` 中以新版本创建实验性配置（不修改生产配置）
2. 选取 3-5 个代表性任务进行对比测试
3. 记录对比结果：输出质量 / 延迟 / token 消耗 / 错误率
4. 对比阈值：新版本在主要维度至少持平，目标维度有提升

### 阶段 4：渐进式切换
1. 更新 openclaw.json 或相关配置，将新版本设为 fallback
2. 观察 1-2 个工作日，通过 Langfuse 监控异常
3. 若稳定，将新版本提升为 primary
4. 更新 SYSTEM_DESIGN.md 相关章节记录版本变更

### 阶段 5：文档与回顾
1. 更新 `.ref/` 中的相关文档（版本号、特性说明）
2. 在 Mem0 中记录迭代经验（效果提升点 + 注意事项）
3. 若升级失败，回滚并记录原因，避免重复踩坑

## 评估维度权重

| 维度 | 权重 | 说明 |
|------|------|------|
| 输出质量 | 40% | 与 ground truth 或人工评估对比 |
| 延迟 | 20% | P50/P95 响应时间 |
| 成本 | 20% | token 单价 × 平均用量 |
| 稳定性 | 20% | 错误率、超时率 |

## 质量标准
- 升级不得降低核心功能的输出质量（质量评分不低于当前版本的 95%）
- 升级须有可回滚方案（旧配置保留至少 7 天）
- 重大升级须有 operator 确认

## 常见失败模式
- 直接切换 primary 无灰度 → 必须先设为 fallback 观察
- 只测试 happy path → 必须包含边界情况和错误输入测试
- 忽略 breaking changes → changelog 必须完整阅读
- 未更新文档 → 升级完成后文档必须同步

## 输出格式
```
## 升级评估报告

**组件**: [组件名]
**当前版本**: [版本]
**候选版本**: [版本]
**评估结论**: 建议升级 / 不建议升级 / 待观察

### 评估结果
| 维度 | 当前 | 候选 | 变化 |
|------|------|------|------|
| 质量 | ... | ... | +X% |
| 延迟 | ... | ... | -Xms |
| 成本 | ... | ... | -X% |
| 稳定性 | ... | ... | ... |

### 关键发现
- [发现1]
- [发现2]

### 切换计划
1. [步骤]
2. [步骤]

### 回滚方案
[回滚步骤]
```
