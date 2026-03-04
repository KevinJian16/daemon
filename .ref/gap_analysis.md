# Daemon 功能差距分析

> 基于方案文档 `/Users/kevinjian/mas/.cursor/plans/daemon_系统设计方案_ddbc4981.plan.md`
> 对比实现代码（4038行，/Users/kevinjian/daemon/）生成

---

## 一、关键缺陷（核心闭环断裂）

### 1. Nerve 跨进程 — 学习闭环断裂 [最严重]
- Worker 进程（temporal/activities.py）和 API 进程（services/api.py）各有独立的 Nerve 实例
- `delivery_completed` 在 Worker 里发出，API 里的 Spine 收不到
- `spine.record` 从未被自动调用 → Playbook.evaluate 从不发生 → 整个学习体系失效
- **需要架构方案**：Activity 完成后通过共享文件或独立 HTTP 回调触发 API 进程的 record

### 2. Contracts 存在但未调用
- `spine/contracts.py` 定义了 `check_contract()` 但 `routines.py` 里没有任何调用
- 所有 Routine 的 IO 合约检查是空操作

### 3. Replay 机制断裂
- `tend._replay_queued_tasks()` emit `task_replay` 事件
- 整个代码库没有任何地方注册 `task_replay` handler
- 排队的任务永远不会被重新提交

### 4. delivery.py._update_index 仍有静默 except
- `delivery.py` L125: `except Exception: index = []` 无 logger.warning
- 注意：`activities.py` 里的同名方法已修复，但 `delivery.py` 里的漏掉了

---

## 二、重大功能缺失（透明内化机制未实现）

### 5. witness 只读了 Playbook，没读 OpenClaw
方案第八章（透明内化）要求 witness 读取：
- `agents/*/sessions/*.jsonl` — ❌ 未读
- `workspace/router/memory/langgraph_patterns/` — ❌ 未读
- Cortex LLM 调用 trace — ❌ 未读（只在内存中）
- Telegram/Portal 访问日志 — ❌ 未读
- Spine 自身 trace（自我观察 §8.5） — ✅ 部分实现
- Playbook unanalyzed evaluations — ✅ 已实现

Agent 行为内化、LLM provider 特征内化、用户模式内化——三个核心透明内化目标均是空壳。

### 6. learn 不读 langgraph_patterns
方案要求读取 `workspace/router/memory/langgraph_patterns/`，当前只分析内部 evaluations。

### 7. relay 缺少 runtime_hints.txt 回写
`relay()` 写了 `skill_index.json` 和 `compass_snapshot.json`，但没有写 `runtime_hints.txt`。
Router 学习闭环的回写端缺失。

### 8. Cortex traces 不持久化
Cortex 调用记录只在内存中（最多1000条），进程重启丢失。
witness 无法分析 LLM provider 历史行为，自适应路由数据缺失。

### 9. activities.py 不使用 OpenClawAdapter
`runtime/openclaw.py` 定义了 `OpenClawAdapter`，但 `temporal/activities.py` 直接重复实现了 HTTP 调用逻辑。`OpenClawAdapter` 只被 `DialogService` 使用，两套代码并行。

---

## 三、Scheduler 机制缺陷

### 10. Cron 解析错误
```python
if len(parts) == 5:
    return 86400  # 所有5段cron都返回24小时！
```
`"0 3 * * *"` 和 `"0 6 * * 1"`（每周一）全被当作24小时间隔，无法区分时刻。

### 11. Nerve 触发未注册
`spine_registry.json` 里每个 Routine 有 `nerve_triggers`，但 API 启动代码没有把这些事件注册成对应 Routine 的 handler。所有 Nerve 触发路径是空的，系统只有 cron 触发。

---

## 四、Console API 缺失端点

以下端点在方案 §12.2 中明确列出但未实现：

| 端点 | 状态 |
|---|---|
| `GET /console/fabric/memory?domain=&tier=&since=&limit=` | ❌ |
| `GET /console/fabric/memory/{unit_id}` | ❌ |
| `GET /console/fabric/playbook?status=&category=` | ❌ |
| `GET /console/fabric/playbook/{method_id}` | ❌ |
| `GET /console/fabric/compass/budgets` | ❌ |
| `GET /console/fabric/compass/signals` | ❌ |
| `GET/PUT /console/policy/{name}` + versions + rollback | ❌ |
| `GET /console/agents/{agent}/skills` | ❌ |
| `PUT /console/agents/{agent}/skills/{skill}` | ❌ |
| `PATCH /console/agents/{agent}/skills/{skill}/enabled` | ❌ |
| `PUT /console/schedules/{job_id}` | ❌ |
| `GET /console/traces/{trace_id}` | ❌ |
| `GET /console/spine/nerve/events` | ❌ |
| `GET /console/cortex/usage` | ❌ |

---

## 五、Console UI 功能缺失

### Agent Manager
- 当前：只读列表（id、skills数量、workspace状态）
- 缺失：单个 Agent 的 Skill 列表、启用/禁用/编辑 Skill
- **缺失：Skill Evolution 面板**（方案明确要求，learn 产出的改进提议 → 人工审批 → 写回 SKILL.md）

### Schedule Manager
- 缺失：cron 表达式编辑、启用/禁用、next_run_utc

### Spine Dashboard
- 缺失：Nerve 最近事件流（实时滚动）
- 缺失：Routine 依赖关系可视化图

### Policy Editor
- 当前：只有 Priority 权重滑块
- 缺失：Quality Profile 编辑、Resource Budget 编辑、Preferences 编辑
- 缺失：配置版本历史（diff + 一键回滚）

### Fabric Explorer
- Memory 视图：只有统计数字，缺 unit 浏览/详情/usage/links/audit
- Playbook 视图：只有统计，缺方法列表/评估历史/版本对比
- Compass 视图：只有 Priority，缺 Resource Budgets 仪表盘、Attention Signals 时间线

### 完全缺失的面板
- Config Versions 面板（§8）
- Cortex Usage 面板

---

## 六、Portal UI 问题

| 问题 | 详情 |
|---|---|
| 缺失 Timeline 视图 | 方案§11 明确要求"按时间线查看产出流" |
| 字段名错误 | 读 `o.archived_utc` 但 index.json 存的是 `delivered_utc`，日期永远空 |
| HTML 报告预览失败 | 尝试 `report.md` 但 Delivery 存的是 `report.html` |

---

## 七、其他缺失

- **PDF 生成**：未实现（方案说 best-effort）
- **Bilingual 质量检查**：`require_bilingual: True` 但质量门不检查双语配对
- **Dispatch 未注入 Agent 并发限制**：`workflows.py` 的 `_agent_limits` 默认值写死在代码里，没有从 Compass 读取

---

## 工作量估算

| 类别 | 工作量 |
|---|---|
| 跨进程 Nerve / spine.record 自动触发（需架构方案） | 3-4天 |
| witness/learn 读 OpenClaw 文件系统（透明内化核心） | 2-3天 |
| Scheduler cron 解析 + Nerve handler 注册 | 1天 |
| Console API 缺失端点（14个） | 2-3天 |
| Console UI 缺失面板（Agent Manager/Policy/Fabric/Timeline等） | 3-4天 |
| Portal 修复（Timeline + 字段名 + HTML预览） | 0.5天 |
| Contracts 集成 + replay handler + relay runtime_hints | 1天 |
| 小修复（delivery silent except、bilingual check等） | 0.5天 |
| **合计** | **约13-17天** |

---

## 优先级

- **P0**：跨进程 spine.record 触发、replay handler、delivery._update_index 静默 except
- **P1**：witness 读 OpenClaw 会话日志、Nerve handler 注册、relay runtime_hints、Skill Evolution 面板
- **P2**：Console API 缺失端点 + 对应 UI
- **P3**：Timeline、PDF、bilingual check、cron 精确解析
