# Codex 自用执行计划（基于 V2 + INTERFACE + HANDOFF）

> 日期：2026-03-06
> 计划用途：执行者（Codex）内部作战清单
> 单一事实源：
> 1) `.ref/daemon_统一方案_v2.md`
> 2) `.ref/INTERFACE_DESIGN.md`
> 3) `.ref/HANDOFF_IMPL.md`

---

## 0. 执行原则（硬约束）

1. 术语硬约束：对外只使用 `run / run_id / run_title / work_scale / circuit`，不出现旧执行实例口径。
2. 交互边界硬约束：Portal = 用户操作唯一入口；Telegram = 纯推送；Console = 治理。
3. 取消硬约束：废弃文件轮询取消，统一走 Temporal heartbeat + cancel 传播。
4. 中途追加硬约束：Thread/Campaign 支持 signal 追加要求；Pulse 不支持。
5. Campaign 硬约束：里程碑线性；milestone 内可并行 activity；milestone 间不并行。
6. 评价硬约束：用户评价 optional，不阻断 completed 与后续推进。
7. 工程硬约束：每次提交前执行 strict reset，保证交付目录无验收垃圾。

---

## 1. 全局里程碑（按交付顺序）

| 里程碑 | 名称 | 目标结果 |
|---|---|---|
| M1 | 接口与术语收敛 | 所有 API/UI/文案按 run + circuit 口径统一 |
| M2 | Temporal 控制链路改造 | 取消走 heartbeat；追加要求走 signal |
| M3 | Campaign 稳态闭环 | child workflow + campaign_context + 失败门控 + retry |
| M4 | Portal 三页 + Circuit 页闭环 | 运行中/待评价/历史 + Circuit CRUD 可用 |
| M5 | Telegram 纯推送化 | 无入站处理，仅规范化通知出站 |
| M6 | Console 治理收敛 | Circuit 只读 + eval_window_hours 可管控 |
| M7 | E2E 验收与清洁收口 | 关键场景验证通过，strict reset 后可交付 |

---

## 2. 工作流拆解（文件级、步骤级）

## WS-00 预处理与基线冻结

**目标**：冻结当前状态、确认改动边界、避免并行误改。

**执行步骤**：
1. `git status --short` 记录现场。
2. 用 `rg` 建立关键词基线：`task|chains|/tasks|/chains|cancel_requested|_handle_text|callback_query`。
3. 确认三份文档最新时间戳与新增段落（§17、§19A、HANDOFF 1.4/1.5/2.0）。

**完成标准**：
- 已形成“改动前基线快照”。
- 所有后续改动可追踪到具体文档条目。

---

## WS-01 术语与接口命名收敛（M1）

**目标**：代码对外层彻底 run/circuit 化。

**主要文件**：
- `services/api.py`
- `services/api_routes/*.py`
- `interfaces/portal/**/*.js`
- `interfaces/console/**/*.js`
- `interfaces/telegram/adapter.py`
- `interfaces/cli/main.py`

**执行步骤**：
1. API 路由层确保仅暴露 `/runs`、`/circuits`；无 `/tasks`、`/chains`。
2. Portal/Console/Telegram 对外文本统一：运行、Pulse/Thread/Campaign、Circuit。
3. 用户可见对象统一使用 `run_title`，内部关联用 `run_id`。
4. 兼容分层：内部临时变量允许保留，但输出 DTO 禁止旧字段。

**完成标准**：
- `rg` 搜索对外层无旧名残留。
- 文档示例与 API 返回字段一致。

**回滚点**：
- 若前端调用断裂，回滚到“仅适配层改名”并保留旧内部变量，不回滚路由契约。

---

## WS-02 Runs API + Eval Window 状态机（M1/M4）

**目标**：支撑 Portal 三页与窗口期语义。

**主要文件**：
- `services/api_routes/runs.py`（新建或扩展）
- `services/state_store.py`
- `services/scheduler.py`
- `services/api_routes/feedback.py`

**执行步骤**：
1. 增加查询入口：
   - `GET /runs?status=running`
   - `GET /runs?phase=awaiting_eval`
   - `GET /runs?phase=history`
2. 反馈入口：
   - `POST /runs/{run_id}/feedback`（partial 接受）
   - `POST /runs/{run_id}/feedback/append`
3. Run 扩展字段：
   - `eval_window_hours`
   - `exec_completed_utc`
   - `eval_deadline_utc`
   - `phase`（running / awaiting_eval / history）
4. 调度器 `_tick()` 增加窗口期超时迁移逻辑。
5. 事件落盘：`run_eval_expired`、`run_feedback_submitted`。

**完成标准**：
- 三页数据源可由 API 独立返回。
- partial feedback 不报错。
- 超时后 run 自动迁移状态正确。

---

## WS-03 Temporal 取消链路改造（Heartbeat）

**目标**：取消响应低延迟、无文件竞争。

**主要文件**：
- `temporal/activities.py`
- `temporal/workflows.py`
- `temporal/campaign_workflow.py`
- `services/api_routes/runs.py`

**执行步骤**：
1. 在长 activity 循环中注入 `activity.heartbeat(...)`。
2. 捕获 `CancelledError`，执行清理后重新抛出。
3. `POST /runs/{run_id}/cancel` 直接调用 workflow handle `cancel()`。
4. 删除 `state/runs/<run_id>/cancel_requested` 文件机制及读取逻辑。
5. 配置 heartbeat timeout（建议 60-120s，按单轮工具耗时校正）。

**完成标准**：
- 取消不依赖文件 flag。
- 长步骤 run 可在下个 heartbeat 周期内取消。

**风险控制**：
- 心跳过短导致误超时：先用 90s 默认，压测后再调小。

---

## WS-04 Temporal 追加要求 signal 机制

**目标**：Thread/Campaign 支持中途追加要求。

**主要文件**：
- `temporal/workflows.py`（GraphDispatchWorkflow）
- `temporal/campaign_workflow.py`
- `services/api_routes/runs.py`
- `interfaces/portal/js/compose.js`

**执行步骤**：
1. Workflow 增加 signal：`append_requirement(payload)`。
2. 维护 `pending_requirements` queue。
3. 在每个 activity 调度前将 queue 注入 prompt/context 并清空。
4. API 增加 `POST /runs/{run_id}/append`。
5. Portal 对话意图：
   - 命中 cancel/pause 走控制命令。
   - 其他文本在存在 running run 时走 append。

**完成标准**：
- Thread/Campaign 可被中途补充要求。
- Pulse 调用 append 返回明确不支持/无注入时机。

---

## WS-05 Campaign Context 累积 + 失败门控

**目标**：每个 milestone 可继承前序摘要，失败进入可恢复介入态。

**主要文件**：
- `temporal/campaign_workflow.py`
- `services/api_routes/campaigns.py`
- `services/state_store.py`

**执行步骤**：
1. `manifest.json` 新增：
   - `campaign_context: []`
   - `campaign_status` 支持 `awaiting_intervention`
2. milestone 成功后追加 context 条目（summary + drive_links + completed_utc）。
3. 下一 milestone 注入 `plan.context.campaign_context`。
4. milestone 失败超预算：
   - 写 `result.json`
   - campaign_status 置 `awaiting_intervention`
   - 推送告警
5. 新增 retry API：`POST /campaigns/{campaign_id}/milestones/{n}/retry`。

**完成标准**：
- context 可累计并被后续 milestone读取。
- 失败后可“重试/中止”，不陷入悬空状态。

---

## WS-06 Campaign Child Workflow 化（M3）

**目标**：里程碑内失败可恢复，不重跑整段。

**主要文件**：
- `temporal/campaign_workflow.py`
- `temporal/workflows.py`
- `temporal/worker.py`
- `services/api_routes/campaigns.py`

**执行步骤**：
1. 父 workflow 改为 `execute_child_workflow(GraphDispatchWorkflow, milestone_plan)`。
2. child workflow id 规范：`daemon-campaign-{campaign_id}-m{n}`。
3. cancel campaign 时联动 cancel 当前 child。
4. 里程碑 gate 状态与 child lifecycle 对齐。

**完成标准**：
- 每个 milestone 在 Temporal UI 可独立追踪。
- 单里程碑失败不影响已完成里程碑。

---

## WS-07 Portal 三页 + Circuit 页（M4）

**目标**：Portal 成为用户唯一操作入口。

**主要文件**：
- `interfaces/portal/index.html`
- `interfaces/portal/js/run_list.js`
- `interfaces/portal/js/review.js`
- `interfaces/portal/js/controls.js`
- `interfaces/portal/js/compose.js`
- `interfaces/portal/js/i18n.js`

**执行步骤**：
1. 侧栏固定入口：对话 / 运行中 / 待评价 / 历史 / Circuit。
2. 运行中页：展示 run_title、work_scale、取消/暂停。
3. 待评价页：倒计时 + 动态问卷 + Campaign 继续/中止。
4. 历史页：仅追加评语。
5. Circuit 页：列表 + 暂停 + 立即触发 + 删除；创建仍走对话意图。

**完成标准**：
- 所有用户操作可在 Portal 完成。
- 与 INTERFACE 规范完全一致。

---

## WS-08 Telegram 纯推送化（M5）

**目标**：彻底移除入站交互路径。

**主要文件**：
- `interfaces/telegram/adapter.py`

**执行步骤**：
1. 删除 `_handle_text`、commands、callback handlers、MessageHandler 入站路由。
2. 保留 `send_message` + 通知封装。
3. 统一通知模板（中文系统文本 + 原样 run_title）。
4. 通知触发点覆盖：run 完成、milestone 完成/自动推进、campaign 完成、系统告警。

**完成标准**：
- Telegram 无任何可执行用户命令。
- 仅承担通知职责。

---

## WS-09 Console 治理收敛（M6）

**目标**：Console 只治理，不承担用户流程。

**主要文件**：
- `interfaces/console/index.html`
- `interfaces/console/js/panels/*.js`
- `services/api_routes/console_*.py`

**执行步骤**：
1. Circuit 在 Console 只读展示，不可 CRUD。
2. 保留 Strategy/Norm/Gate 治理写操作。
3. 增加 Norm 配置项 `eval_window_hours` 的可编辑入口。
4. 明确 Console 不发起 run、不做用户评价。

**完成标准**：
- Console 和 Portal 的职责无重叠。

---

## WS-10 circuits 数据模型扁平化与迁移

**目标**：`trigger{}` 嵌套改扁平，兼容历史数据迁移一次完成。

**主要文件**：
- `services/scheduler.py`
- `services/api_routes/circuits.py`
- `state/circuits.json`（迁移脚本）

**执行步骤**：
1. 读路径统一：`state/circuits.json`。
2. 数据结构统一：`circuit_id, cron, tz` 顶层字段。
3. 迁移函数：旧结构自动一次性转换并写回。
4. API 输入输出仅接受新结构。

**完成标准**：
- 旧数据可自动迁移。
- 新写入不再包含 `trigger` 嵌套。

---

## WS-11 端到端验收（M7）

**目标**：验证关键闭环，不做“看上去能跑”。

**场景清单**：
1. Pulse 完成后进入待评价，超时自动进入历史。
2. Thread 运行中追加要求，下一步 prompt 可见注入内容。
3. Thread 取消：通过 heartbeat 在可接受延迟内停止。
4. Campaign milestone 成功：写 context、进入待评价、继续推进。
5. Campaign milestone 失败：进入 awaiting_intervention，可 retry/cancel。
6. Campaign 走 child workflow：Temporal UI 可看到父子分离。
7. Circuit 实例完成：进入待评价（窗口期），超时后进历史，不影响下一次 cron。
8. Telegram 全程无入站命令可用，仅收到推送。
9. Console 可改 `eval_window_hours` 并立即影响后续 run。

**验收证据**：
- API 回包样本
- state 快照
- telemetry 事件
- Temporal workflow 截图/ID

---

## WS-12 阶段三能力（Skills Campaign 相关）

**目标**：对齐 V2 §21 与 §20。

**执行内容**：
1. 所有 SKILL.md 补 `skill_type`。
2. 基准目录 `benchmark/`（cases/rubric/baseline/history）。
3. benchmark runner（前后对比、阈值判定、摘要推送）。
4. iter-report weave pattern（触发阈值 >=4 工具轮次）。

**状态**：后置，不阻塞 M1-M7。

---

## 3. 交付切分与提交策略

1. 提交策略：每个 WS 至少一个独立 commit，避免大杂烩。
2. 回归策略：每个 WS 完成后做最小 smoke，M7 做全量 E2E。
3. 失败策略：不降级需求；无法完成即登记阻塞与下一步。
4. 清洁策略：提交前执行 strict reset，确认无测试残留。

---

## 4. 每轮执行模板（自用）

1. 选择一个 WS（只做一个主目标）。
2. 列出改动文件与契约。
3. 编码 + 静态校验。
4. 跑对应最小验收场景。
5. 记录证据（不污染交付目录）。
6. strict reset。
7. 提交并更新本文状态。

---

## 5. 当前执行顺序（锁定）

1. WS-03（heartbeat cancel）
2. WS-04（append signal）
3. WS-05（campaign_context + awaiting_intervention + retry）
4. WS-06（child workflow）
5. WS-02（runs phase API + eval window timer）
6. WS-07（Portal 三页 + Circuit）
7. WS-08（Telegram 纯推送）
8. WS-09（Console 治理收敛）
9. WS-10（circuits 扁平迁移）
10. WS-11（全链路验收）

> 说明：先打通 Temporal 关键控制链路（取消/追加/里程碑恢复），再做界面层；避免 UI 先行导致假闭环。
