# 重构方案：Session 模式与记忆机制

> 日期：2026-03-11
> 起源：MECHANISM_AUDIT.md §17.6（per-Deed session gap）
> 状态：待确认

---

## 0. 背景与问题

### 0.1 核心发现

1. 当前所有 move 使用 `sessions_spawn` + `runtime: "subagent"` 执行
2. OC 的 subagent 模式下 `memory_search` / `memory_get` 被硬性禁止（`SUBAGENT_TOOL_DENY_ALWAYS`）
3. OC SDK 中不存在 `memory_write` tool——任何模式的 agent 都无法主动写 memory
4. Psyche → MEMORY.md 的内化链路从未实际生效（subagent 读不到 workspace memory）
5. 每个 move spawn 的 session 从未销毁（`cleanup: "keep"`），产生大量孤儿 session
6. 同 agent 多个 move 之间完全无上下文共享

### 0.2 OC 原生机制确认（来源：docs.openclaw.ai）

- **Memory 架构**：per-agent workspace 级别。`MEMORY.md`（长期）+ `memory/YYYY-MM-DD.md`（日志）+ SQLite 向量索引
- **Memory 加载**：full session 启动时自动读取 `MEMORY.md` + 当天/昨天日志。subagent 不加载
- **Parallel tool calls**：OC 原生支持。模型在一个 response 中返回多个 tool_use 时并行执行
- **Subagent 设计意图**：纯任务执行器，不读不写记忆。上下文通过 `task` 参数和 `attachments` 传入
- **Session 隔离**：`sessions_spawn` 的子 session 不继承父 session 上下文

---

## 1. 方案概述

将执行模式从 **subagent spawn（一次性隔离 session）** 改为 **persistent full session + sessions_send（Deed 级持久 session）**。

核心变化：
- 每个 Deed 为每个使用的 role 创建一个 persistent session
- 同 agent 的 move 顺序发送到同一个 session，上下文自然积累
- 不同 agent 之间由 Temporal 并行调度
- agent 内部的并行由 OC 的 parallel tool calls 处理
- Psyche → MEMORY.md 内化机制在 full session 下真正生效
- Session 生命周期显式管理（创建 → 使用 → 销毁）

---

## 2. 文件级改动清单

### 2.1 runtime/openclaw.py（OpenClawAdapter）

**删除**：
- `send()` 中 `sessions_spawn` 路径（不保留 fallback）
- `_session_alias` 字典（subagent session key 映射不再需要）

**新增**：
- `create_session(agent_id: str, session_key: str) -> dict`
  - 调用 OC gateway 创建 persistent full session
  - 返回 session 元信息
- `send_to_session(session_key: str, message: str) -> dict`
  - 调用 `sessions_send` 向已有 session 发消息
  - 等待执行完成，返回结果
- `destroy_session(session_key: str) -> None`
  - 销毁 session，释放资源

**修改**：
- `session_key()` 格式改为 `deed:{deed_id}:role:{role}`（per-role-per-deed，不再 per-move）

### 2.2 runtime/retinue.py（Retinue）

**修改 `allocate()`**：
```
现在：find idle → _fill_templates → write_psyche_snapshot → mark occupied
改为：find idle → _fill_templates → write_psyche_snapshot → create_session → 存 session_key → mark occupied
```

**修改 `release()`**：
```
现在：_clean_instance → mark idle（session_key 置 None 但从未有值）
改为：destroy_session → _clean_instance → mark idle
```

`write_psyche_snapshot()` **保留不变**——现在 full session 会自动加载，这是内化机制的关键环节。

### 2.3 temporal/workflows.py（GraphWillWorkflow）

**并发策略变更**：
- 同 agent move 强制串行：同一 role 的 move 排队顺序执行
- 跨 agent move 保持并行：不同 role 的 move 可同时运行
- `agent_limits` 简化或移除（同 agent 自然只有 1 个 session，串行执行）

**执行循环调整**：
- `_start()` 改为 session-aware：从 plan 的 `retinue_allocations` 获取 session_key，调用 session send activity
- ready move 调度增加约束：如果该 role 已有 move 在执行，不启动新的同 role move

**Retinue session 生命周期集成**：
- 在 `activity_allocate_retinue` 后，调用 `activity_create_deed_sessions`
- 在 `activity_release_retinue` 前，调用 `activity_destroy_deed_sessions`

### 2.4 temporal/activities.py

**修改 `activity_openclaw_move()`**：
- 从 `self._openclaw.send(session_key, message, agent_id)` 改为 `self._openclaw.send_to_session(session_key, message)`
- session_key 从 plan 的 retinue_allocations 中获取，不再现场生成

**新增**：
- `activity_create_deed_sessions(deed_id, retinue_allocations) -> dict`
  - 为每个分配的 pool instance 创建 persistent session
  - 返回 `{role: session_key}` 映射
- `activity_destroy_deed_sessions(deed_id, session_keys) -> None`
  - 销毁所有 Deed 关联的 session

### 2.5 Will / Planning 层

**plan 生成规则变更**：
- 同 agent 不拆并行 move，写复合 instruction
- "搜索 A/B/C 三个侧面" = 1 个 scout move，不是 3 个
- move timeout 按复合程度调整（Will 可根据子任务数估算）
- DAG 节点数减少，依赖关系简化

**move 内并发策略**：交由 agent 自主决定。OC 原生支持 parallel tool calls（模型返回多个 tool_use 时并行执行），具体并发行为通过 agent 的 SKILL.md / TOOLS.md 引导，不在调度层强制。

### 2.6 spine/routines_ops_learn.py

**`run_learn()` 增强**：
- 除了读 move outputs，还可通过 `sessions_history` 读取 persistent session 的对话记录
- 提取知识时正确分配 tier tag（见 §3）

### 2.7 spine/routines_ops_maintenance.py

**`run_relay()` 保留不变**——生成 Psyche snapshot → 写入 MEMORY.md。现在 full session 会自动加载，这条链路真正生效。

### 2.8 清理项

- 删除 `openclaw.py` 中 `sessions_spawn` 相关代码
- 删除 `_session_alias` 字典
- 删除 `cleanup_orphaned_sessions()` 中仅清 index 的逻辑，改为真正的 session 清理
- `agent_concurrency_defaults`（scout:8 等）移除或统一为 1

---

## 3. 记忆分层制度补全

### 3.1 现状

| 项目 | 状态 |
|------|------|
| tag 基础设施（`tier:`, `source_type:`, `domain:`） | 已实现 |
| `memory.query(tier=...)` 过滤 | 已实现 |
| `_derived_fields()` 提取 tier/source_type/domain | 已实现 |
| tier 值枚举 | 未定义，仅 `deep`/`working` 在用 |
| `run_learn()` tier 标记 | 未实现，全部落入默认 `working` |
| 动态 tier 调整（Q1.6） | 未实现 |
| 来源可信度追踪 | 未实现 |

### 3.2 正式 tier 枚举

| tier | 含义 | 来源 | 衰减 |
|------|------|------|------|
| `core` | 核心事实，用户确认或多次验证 | 用户反馈、多次 Deed 交叉验证 | 不衰减 |
| `deep` | 高可信知识 | warmup 注入、用户正面反馈 | 极慢衰减 |
| `working` | 工作知识，单次提取未验证 | `run_learn()` 提取 | 正常衰减 |
| `transient` | 临时事实，时效性强 | 执行中发现的时间敏感信息 | 快速衰减 |

### 3.3 tier 分配规则

**`run_learn()` 提取时**：
- 默认标记为 `tier:working`
- 如果同一事实在多个 Deed 中被重复提取（embedding 相似度 > 0.92），提升为 `tier:deep`

**用户反馈时**：
- 用户正面评价的 Deed 关联知识：提升为 `tier:deep`
- 用户负面评价的 Deed 关联知识：降级为 `tier:transient` 或删除

**warmup 注入**：
- 标记为 `tier:deep`（现有行为，保持不变）

**动态调整（Q1.6 实现）**：
- `run_witness()` 中增加逻辑：分析 Lore 记录，追踪知识来源与 Deed 成败的关联
- 来源一致低质量 → 该来源所有条目降 tier
- 来源一致高质量 → 该来源条目升 tier

### 3.4 tier 分配改动涉及的文件

- `spine/routines_ops_learn.py`：`run_learn()` 提取时标记 `tier:working`，查重复时升级
- `services/api.py`：用户反馈处理时关联 Deed 知识条目，调整 tier
- `spine/routines_ops_learn.py`：`run_witness()` 增加来源可信度分析
- `psyche/memory.py`：`distill()` 中 decay 按 tier 分速率
- `scripts/warmup.py`：保持 `tier:deep` 不变

---

## 4. 实施顺序

### Phase 1：Session 模式切换（核心）
1. `runtime/openclaw.py`：实现 create_session / send_to_session / destroy_session
2. `runtime/retinue.py`：allocate/release 集成 session 生命周期
3. `temporal/activities.py`：新增 session 管理 activity，修改 move activity
4. `temporal/workflows.py`：同 agent 串行调度，session-aware 启动
5. 清理 spawn 相关代码

### Phase 2：验证内化机制
6. 确认 full session 启动时自动加载 MEMORY.md
7. 确认 Psyche snapshot → MEMORY.md → agent 可用 → 执行中可查询
8. E2E 测试：submit Deed → session 创建 → move 执行 → 上下文积累 → session 销毁

### Phase 3：记忆分层补全
9. 定义 tier 枚举，更新 `run_learn()` 标记逻辑
10. `distill()` 按 tier 分速率衰减
11. 用户反馈关联 tier 调整
12. `run_witness()` 来源可信度分析

### Phase 4：Planning 适配
13. Will plan 生成：同 agent 不拆并行 move
14. 复合 instruction 模板
15. timeout 估算调整

---

## 5. 风险与缓解

| 风险 | 严重性 | 缓解措施 |
|------|--------|----------|
| Context window 溢出 | 高 | 实测 OC session 上下文压缩能力；必要时在 move 间插入摘要指令 |
| Session 意外死亡 | 中 | activity 中检测 session 存活状态；死亡时重建 session 并记录断点 |
| Planning 逻辑不匹配 | 中 | Phase 4 专门处理；过渡期人工检查 plan 结构 |
| 学习归因粒度变粗 | 低 | session history 仍可做细粒度分析；Lore 记录保持 move 级别 |

---

## 6. 不做的事

- 不修改 OC 源码（不 fork，不加 memoryDir 参数）
- 不保留 subagent spawn fallback（掩盖错误）
- 不在 move 之间手动传递 attachments/memo（session 自然积累）
- 不减少 pool instance 数量（隔离安全性不变）
