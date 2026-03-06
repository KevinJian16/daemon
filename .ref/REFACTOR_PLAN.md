# Daemon 重构执行文档（V2 对齐）

> 生效日期：2026-03-06  
> 执行基准：`daemon_统一方案_v2.md`、`NEXT_PHASE_PLAN.md`、`UX_SPEC.md`  
> 目的：在不降级功能的前提下，完成结构性重构，降低耦合与维护风险，为后续“优化/实用化/精细化”提供稳定底座。

---

## 1. 当前基线（重构触发原因）

### 1.1 体量与热点

| 文件 | 规模 | 主要问题 |
|---|---:|---|
| `interfaces/console/index.html` | 3316 行 | 样式/状态/API/i18n 混杂；大量 `onclick` 与 `innerHTML` |
| `interfaces/portal/index.html` | 1149 行 | 任务列表、评价流程、追加评价、多端状态同步逻辑集中在单文件，维护风险高 |
| `services/api.py` | 2845 行 | `create_app()` 过载，路由与业务逻辑耦合 |
| `spine/routines.py` | 1914 行 | 10 个 routine + 治理逻辑 + I/O 强耦合 |
| `temporal/activities.py` | 1318 行 | 执行、质量门、交付、Campaign 混合 |
| `fabric/playbook.py` | 1372 行 | 方法生命周期与 Strategy 生命周期混合 |
| `services/dispatch.py` | 1081 行 | 语义解析、策略注入、预算、replay、shadow 全在同类 |

### 1.2 架构级风险

1. 状态文件多点读写：`runs.json`、`gate.json` 在 API/Dispatch/Spine/Temporal/Scheduler 分散访问，存在状态漂移风险。  
2. API 单体化：路由数量高（约 99），变更容易产生连带回归。  
3. Console 单页脚本过大：同屏承担交互、渲染、翻译、网络调用，难以维护。  
4. 异常处理粒度不统一：大量宽泛 `except Exception`，错误语义与可追踪性不稳定。  

---

## 2. 不可妥协原则

1. **V2 一致性优先**：重构是“结构变更”，不是“语义改写”；行为必须对齐 V2。  
2. **禁止功能降级**：不允许通过删功能/弱化约束换取重构速度。  
3. **先抽共享层，再拆上层**：先统一状态访问，再拆 API、Dispatch、Spine，避免并发写冲突。  
4. **提交前状态清洁**：每次提交前执行 strict reset，保证交付目录干净。  
5. **重构提交与功能提交隔离**：单个 commit 只做一种性质变更（结构移动或行为修复）。  

---

## 3. 目标架构（重构后的边界）

### 3.1 API 分层（替代单体 `services/api.py`）

建议落地目录：

```text
services/api/
  app.py
  deps.py
  lifecycle.py
  routers/
    health.py
    submit.py
    tasks.py
    outcome.py
    feedback.py
    campaigns.py
    portal_integrations.py
    console_overview.py
    console_spine.py
    console_fabric.py
    console_policy.py
    console_strategy.py
    console_semantics.py
    console_model.py
    console_agents.py
    console_schedules.py
    console_system.py
```

规则：
1. Router 只做协议编排（请求解析、参数校验、错误码映射）。  
2. 业务逻辑下沉到 service 层，Router 禁止直接读写状态文件。  
3. 事件桥、startup/shutdown 独立为 lifecycle。  

### 3.2 状态访问统一层（新增）

新增 `services/state_store.py`（或 `runtime/state_store.py`），统一托管：
1. `tasks` 读写（查询、upsert、状态迁移、replay 元数据）。  
2. `gate` 读写。  
3. `schedule_history`、`outcome_index` 等高频结构化状态。  

要求：
1. 原子写（tmp + replace）。  
2. 最小并发保护（文件锁或单进程锁封装）。  
3. 统一 schema 默认值，减少各模块重复兜底逻辑。  

### 3.3 Dispatch 管线化

将 `Dispatch` 拆为可组合步骤：
1. `SemanticResolver`  
2. `PlanValidator`  
3. `StrategyInjector`  
4. `ModelRouter`  
5. `BudgetPreflight`  
6. `QueueReplayCoordinator`  
7. `TemporalSubmitter`

### 3.4 Spine 例程模块化

将 `spine/routines.py` 拆分为：
1. `spine/routines/core.py`（公共上下文、快照、门控）  
2. `spine/routines/ops_record.py`  
3. `spine/routines/ops_learn.py`（witness/distill/learn/judge）  
4. `spine/routines/ops_maintenance.py`（tend/librarian/focus/relay）

### 3.5 Temporal Activities 分层

拆分为：
1. `temporal/activities_exec.py`（step 执行、checkpoint）  
2. `temporal/activities_quality.py`（质量门与 drift）  
3. `temporal/activities_delivery.py`（归档、index、PDF）  
4. `temporal/activities_campaign.py`（Campaign 生命周期）

### 3.6 Console 前端模块化

保留 `interfaces/console/index.html` 外壳，拆 JS/CSS：

```text
interfaces/console/
  index.html
  console.css
  js/
    app.js
    i18n.js
    api.js
    state.js
    panels/
      overview.js
      spine.js
      fabric.js
      policy.js
      strategies.js
      model.js
      agents.js
      schedules.js
      campaigns.js
      system.js
```

### 3.7 Portal 前端模块化（新增）

保留 `interfaces/portal/index.html` 入口，拆分为可维护模块：

```text
interfaces/portal/
  index.html
  portal.css
  js/
    app.js
    i18n.js
    api.js
    state.js
    task_list.js
    review.js
    append_feedback.js
    sync.js
```

规则：
1. 任务卡片渲染、评分入口、详细评价、追加评价必须拆成独立模块。  
2. Portal/Telegram 去重与“先到先得”状态标记集中在 `sync.js`，避免散落判断。  
3. Portal 文案遵循统一语言规则：专有词保留英文，其余按界面语言显示。  

---

## 4. 分阶段执行（按优先级）

## Phase 0：基线冻结（P0）
1. 输出当前行为基线（关键 API 响应字段、状态迁移、Console 面板能力清单）。  
2. 标记“重构期间禁止变更项”（V2 功能语义、字段命名、错误码）。  

完成定义：
1. 有可比对的 before baseline。  
2. 后续每个 phase 都可对照 baseline 回归。  

## Phase 1：StateStore 抽取（P0）
1. 新增统一状态访问层。  
2. API/Dispatch/Spine/Temporal/Scheduler 改为调用 StateStore。  

完成定义：
1. 代码库中不再散落直接操作 `runs.json`/`gate.json` 的业务逻辑。  
2. 状态读写路径统一且可追踪。  

## Phase 2：API Router 拆分（P0）
1. 按领域拆分 routers；`create_app` 仅保留装配。  
2. 生命周期（startup/shutdown/bridge）独立。  

完成定义：
1. `services/api.py` 不再承载全部路由。  
2. 接口路径与返回协议保持不变。  

## Phase 3：Dispatch 管线化（P0）
1. 把语义/策略/模型/预算/replay/shadow 提交流程拆成独立组件。  
2. 保持 `/submit` 行为语义一致。  

完成定义：
1. `Dispatch` 主类仅负责 orchestration。  
2. 每个步骤可独立测试与替换。  

## Phase 4：Spine 模块化（P0/P1）
1. 例程逻辑按功能域拆分。  
2. 强化关键失败日志与错误上下文。  

完成定义：
1. `spine.record -> witness -> learn -> judge -> relay` 闭环行为不变。  
2. routine 代码可独立定位与维护。  

## Phase 5：Temporal Activities 分层（P1）
1. 拆执行、质量、交付、Campaign 模块。  
2. 保持 checkpoint、quality gate、outcome 归档逻辑语义一致。  

完成定义：
1. 任务与 Campaign 流程保持可运行。  
2. 重启恢复与状态迁移行为不变。  

## Phase 6：Console 前端模块化（P1）
1. JS 按 panel 切分，统一渲染与事件绑定模式。  
2. 保留现有 UX 规范（中英文同步、专有词不翻译、分页/筛选逻辑）。  

完成定义：
1. 页面行为与现状一致。  
2. 不再依赖大面积内联 `onclick`。  

## Phase 7：收口与硬化（P1）
1. 异常处理标准化（保留必要兜底，减少无语义吞错）。  
2. 文档更新（模块边界图、维护指南、常见故障点）。  

完成定义：
1. 关键链路错误可追溯、可定位。  
2. 代码结构可由新接手者快速理解。  

## Phase 8：Portal 重构（P1）
1. 将 `interfaces/portal/index.html` 的状态管理、渲染、网络请求、i18n 拆为模块。  
2. 把“待处理置顶、评价提交、追加评价、Portal/Telegram 去重”做成可单测的纯函数层。  
3. 保持现有 UX 不降级，确保 pending_review 与评价闭环行为一致。  

完成定义：
1. Portal 代码不再依赖大段内联脚本与全局变量串联。  
2. 中文/英文切换即时生效，专有词保留英文口径一致。  
3. 任务评价链路（快速评价/详细评价/追加评价）行为与当前一致。  

---

## 5. 验收标准

### 5.1 行为等价验收

1. `/submit`、`/runs`、`/outcome`、`/campaigns`、`/console/*` 协议字段不回退。  
2. `run_completed -> spine.record -> learn/judge/relay` 闭环保持可用。  
3. Portal/Console/Telegram 反馈去重规则保持一致。  

### 5.2 结构验收

1. 单文件职责显著收敛（API 与 Console 不再单体过载）。  
2. 状态文件读写统一经 StateStore。  
3. 路由层与业务层边界清晰。  

### 5.3 交付验收

1. 提交前执行 strict reset，系统回到干净态。  
2. 不保留测试临时产物。  
3. 文档与代码结构一致，可由后续执行者直接接手。  

---

## 6. 风险与应对

1. **拆分导致 import 循环**  
应对：先定义依赖方向（router -> service -> runtime/fabric/spine），禁止反向依赖。

2. **状态迁移期并发写冲突**  
应对：先落地 StateStore，再替换调用点，最后移除旧入口。

3. **前端拆分造成 i18n 漏刷**  
应对：抽统一 `applyLang()` 与 panel lifecycle，所有文本刷新走同一入口。

4. **重构和功能修复混在同一提交**  
应对：严格 commit 粒度管理，结构重构与行为变更分离。

---

## 7. 第一批可执行任务（立即开工）

1. 落地 `StateStore`，替换 `runs.json/gate.json` 访问。  
2. 拆 API 为多 router，保留旧接口不变。  
3. 拆 Dispatch 为语义/策略/模型/预算/replay 子模块。  
4. 拆 Console JS 为 `app + panels`，先保持行为等价再做细化优化。  
5. 拆 Portal JS 为 `app + task/review/sync`，优先抽离评价与多端同步逻辑。  

---

## 8. 备注

1. 本文档是“结构重构执行规范”，不替代 V2 功能方案。  
2. 若与 V2 冲突，以 `daemon_统一方案_v2.md` 为准。  
