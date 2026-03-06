# 实施交接：待改动清单

> 日期：2026-03-06
> 基准文档：`daemon_统一方案_v2.md`
> 本文只列"要做什么"，不列"已做什么"。按优先级分组。

---

## 优先级 1：立即执行（阻塞主线）

### 1.1 术语对齐：run + Pulse / Thread / Campaign

代码、API、UI 全面使用 `run` 作为执行实例术语。V2 §16 已定义三级命名（Pulse / Thread / Campaign），对外不再出现旧执行实例口径。

**涉及范围：**
- `state/runs.json`（及 run 相关状态文件）作为执行实例存储，展示层使用 Pulse / Thread / Campaign
- `GET /runs` / `GET /runs/{id}` 路由及响应字段
- Console UI：Runs 面板标题、列名
- Portal UI：运行列表展示
- Telegram 通知文案：`运行完成`，并根据 `work_scale` 显示 `Pulse 完成` / `Thread 完成`
- `dispatch.py`、`activities.py` 内部注释和 log 文案（优先修正所有对外可见文本）

**注意：** `run_id` 作为内部主键保留，对用户展示统一使用 `run_title`。

---

### 1.2 chains → circuits 全面重命名

当前代码里 Circuit 功能还叫 `chains`，需要统一改为 `circuits`。

**涉及文件：**
- `services/api_routes/chains.py` → 重命名为 `circuits.py`，内部函数名前缀 `chain` → `circuit`
- `services/api.py`：`from services.api_routes.chains import register_chains_routes` → circuits
- `services/scheduler.py`：
  - `_chains_path` → `_circuits_path`
  - `state/recurring_chains.json` → `state/circuits.json`
  - `_tick_user_chains()` → `_tick_circuits()`
  - `list_chains/create_chain/update_chain/cancel_chain/trigger_chain` → 全部改 circuit
- `interfaces/telegram/adapter.py`：`/chains` 命令 → `/circuits`，`取消链` → `取消回路`
- `interfaces/console/js/panels/schedules.js`：`loadChains/triggerChain/cancelChain/openCreateChainModal` → circuit
- `interfaces/console/index.html`：`chains-tbody`、按钮文案
- `state/recurring_chains.json`：若已存在，迁移为 `state/circuits.json`，`chain_id` → `circuit_id`

**数据结构同步简化**（当前代码有嵌套 trigger 对象，按 V2 §22.1 改为扁平）：

```json
// 旧（chains 时代）
{
  "chain_id": "...",
  "trigger": { "type": "cron", "cron": "0 8 * * *", "tz": "..." }
}

// 新（circuits）
{
  "circuit_id": "...",
  "cron": "0 8 * * *",
  "tz": "..."
}
```

---

### 1.3 Telegram 改为纯推送 + Portal 成为用户操作唯一入口

**背景：** 新界面分野设计（见 `.ref/INTERFACE_DESIGN.md`）确立零重叠原则：Telegram 改为纯推送频道，Portal 承接所有用户操作。原 P1.3 描述的"Portal 对话控制命令对标 Telegram"方向已废弃。

---

#### 1.3.1 Telegram adapter 改造（`interfaces/telegram/adapter.py`）

**删除：**
- `_handle_text()` 函数及其所有分支
- 所有 `/command` 处理器（`/circuits`、`/runs`、`/status` 等）
- 所有 callback_query（inline keyboard）处理逻辑
- 所有入站消息路由（`application.add_handler(MessageHandler(...))` 等）

**保留（只保留出站推送）：**
- `send_message(text)` 函数
- `send_notification(event_type, run_title, extra)` 封装函数

**通知格式（固定中文 + 原样 run_title）：**
```
Thread 完成 · "Write a summary of this paper" · 请去 Portal 评价
Campaign 里程碑 2 完成 · "分阶段竞争格局研究" · 请去 Portal 查看
Campaign 里程碑已自动推进（无操作）· "分阶段竞争格局研究"
Circuit 实例完成 · "每日简报" · 请去 Portal 评价
```
注：`run_title` 原样嵌入，不翻译。`run_id` 不对用户暴露。

---

#### 1.3.2 Portal 对话框意图识别（`services/api_routes/chat.py`）

在 `chat()` endpoint 调用 `dialog.chat()` 之前加意图识别层：

| 用户输入 | 动作 |
|---|---|
| `取消` / `cancel` | 查找 `running` 状态的 run，调 `POST /runs/{id}/cancel` |
| `暂停` / `pause` | 查找 `running` 状态的 run，调 `POST /runs/{id}/pause` |

匹配后直接返回结果文本，不走 Router。Circuit 操作和 Campaign 操作通过 Portal 页面按钮执行，不走对话框。

---

#### 1.3.3 Portal 三页结构 + 评价窗口期（新建）

**新增 API endpoints（`services/api_routes/runs.py` 或扩展现有）：**

```
GET /runs?status=running          → 运行中页数据
GET /runs?phase=awaiting_eval     → 待评价页数据（含 circuit 实例窗口期内的）
GET /runs?phase=history           → 历史页数据（窗口期已过）
POST /runs/{run_id}/feedback      → 提交用户评价（partial OK，不报错）
POST /runs/{run_id}/feedback/append → 追加评语（历史页，纯文字）
POST /campaigns/{campaign_id}/milestones/{n}/gate → 里程碑门控（continue / abort）
```

**窗口期计时实现（`services/scheduler.py` 的 `_tick()` 里加）：**
- 遍历 `run_status = awaiting_eval` 的 run
- 检查 `eval_deadline_utc`（= `exec_completed_utc` + `eval_window_hours`）
- 超时 → 将 run 转为 `completed`，写事件 `run_eval_expired`
- Campaign milestone 超时 → 调 `milestone_auto_advance()`，发 Telegram 通知

**Norm 配置项：** `eval_window_hours`（默认 2），在 Console Norm 面板暴露为可编辑字段。

---

#### 1.3.4 run_title 生成（Router 改动）

Router 在生成 Weave Plan 时同步生成 `run_title`：
- 风格：简短描述性（≤15 词），与用户提交语言一致
- 写入 run 记录字段 `run_title`（不可变）
- **所有对用户可见的界面**（Portal、Telegram）使用 `run_title`，不显示 `run_id`

**涉及文件：** `services/dispatch.py` 的 `enrich()` 函数负责将 Router 返回的 `run_title` 写入 run 记录。

---

## 优先级 1（续）：Cancel 与追加要求机制

### 1.4 Activity Heartbeat 取消（替代文件轮询）

**问题：** 当前 `activity_openclaw_step` 内部用文件 flag（`state/runs/<run_id>/cancel_requested`）轮询来响应取消请求。对于运行时间长的 session（可能持续数分钟甚至更长），轮询间隔决定了响应延迟——且本质上不优雅，Temporal 本身有更好的机制。

**正确方案：Temporal activity heartbeat**

Temporal Python SDK 提供 `activity.heartbeat(details=...)` 机制：
- 长时间运行的 activity 应定期调用 `activity.heartbeat()`（建议每次工具调用之间调用一次）
- 当 workflow 收到取消信号时，下一次 `heartbeat()` 调用会抛出 `CancelledError`
- Activity 捕获 `CancelledError` → 执行清理 → 重新抛出，Temporal 自动标记 activity 为 cancelled
- OpenClaw 的 Python 层也支持 heartbeat，两侧都可触发

**改动范围：**

- `temporal/activities.py` 的 `activity_openclaw_step()`：
  - 在每次工具调用（即每次对 OpenClaw 的一轮请求）结束后加 `activity.heartbeat({"step": step_index, "run_id": run_id})`
  - 捕获 `temporalio.exceptions.CancelledError`（而非检查文件 flag）→ 写 `run_status = cancelled` → 重新抛出
  - 移除现有的文件 flag 检查逻辑（`cancel_requested` 文件读取）

- `temporal/workflows.py` / `temporal/campaign_workflow.py`：
  - 工作流层无需修改；cancel 请求通过 `workflow.cancel()` 发给 workflow → 自动传播给当前 activity

- `services/api_routes/runs.py`（cancel endpoint）：
  - `POST /runs/{run_id}/cancel` → 调 `temporal_client.get_workflow_handle(workflow_id).cancel()`
  - 无需再写文件 flag，heartbeat 机制负责 intra-activity 传播

- **删除：** `state/runs/<run_id>/cancel_requested` 机制（文件读写相关代码全部移除）

**Heartbeat timeout 配置（`temporal/activities.py` 注册处）：**
```python
@activity.defn
async def activity_openclaw_step(...):
    ...
# 注册时设置：
# heartbeat_timeout=timedelta(seconds=30)
# 即 30s 内未 heartbeat → Temporal 视 worker 失联，自动重新调度
```

**注意：** heartbeat_timeout 应 > 单次工具调用的最长时间（建议 60-120s），防止正常工具调用期间被误判超时。

---

### 1.5 追加要求机制（Mid-Run Modification）

**问题：** 目前没有任何机制让用户在 run 执行中途追加或修改要求。Pulse/Thread/Campaign 的 prompt 一旦提交即固定，无法注入新信息。

**设计方案：Temporal workflow signal + signal queue**

对于需要中途接受用户输入的 run，引入 `append_requirement` signal：

```
用户在 Portal 对话框输入追加要求
  → POST /runs/{run_id}/append
  → temporal_client.get_workflow_handle(workflow_id).signal("append_requirement", payload)
  → Workflow 收到 signal，存入 signal queue（列表）
  → 当前 activity 完成后，workflow 在下一个 activity 开始前将 queue 中的内容注入 context
```

**适用范围：**
- **Thread**：可在任意两个 activity 之间接收追加要求，注入到下一 activity 的 system prompt 补充区
- **Campaign**：在里程碑间（milestone gate 等待期间）接收，影响下一 milestone 的执行
- **Pulse**：不适用（单步执行，注入时机不存在）
- **Circuit 实例**：每次是独立 run，可用 Thread 规则

**注入格式（追加到 activity 的 system prompt 末尾）：**
```
---
[用户追加要求 · 注入时间 2026-03-06T08:30:00Z]
请在本步骤中额外关注：<用户输入内容>
---
```

**改动范围：**

- `temporal/workflows.py`（`GraphDispatchWorkflow`）：
  - 加 `@workflow.signal` handler `append_requirement(payload)`，将 payload append 到 `self._pending_requirements: list`
  - 在每次 `execute_activity(activity_openclaw_step, ...)` 调用前，将 `_pending_requirements` 合并进 step 参数，清空队列

- `temporal/campaign_workflow.py`：
  - 同样加 `@workflow.signal` handler，在里程碑间等待期间积累，下一 milestone 开始时注入

- `services/api_routes/runs.py`：
  - 新增 `POST /runs/{run_id}/append`，body: `{"requirement": "..."}`
  - 调用 `workflow_handle.signal("append_requirement", {"text": requirement, "appended_at": utc_now()})`

- **Portal 对话页**：
  - 意图识别层（§1.3.2）追加一条：检测到有 `running` 状态的 run 时，普通文本（非 cancel/pause 关键词）→ 识别为追加要求 → 调 `POST /runs/{run_id}/append`，返回"已将要求追加至 run：<run_title>"

**注意：** 仅 Thread / Campaign 支持此机制（workflow signal 在 Pulse 场景下 timing 无意义）；Portal UI 需在运行中页和待评价页显示"追加要求"入口。

**`已知不改` 表格更新：** 见下方。

---

## 优先级 2：架构修复（暖机前完成）

### 2.0 Campaign Context 累积器 + Milestone 失败门控

**Campaign context 累积（新增字段）：**

每个 milestone 成功完成后，`temporal/campaign_workflow.py` 负责将 review agent 生成的摘要追加到 manifest：

```python
manifest["campaign_context"].append({
    "milestone_n": n,
    "summary": review_summary,       # review agent 输出的简述
    "drive_links": drive_links,      # 本 milestone 的 Drive 产出链接列表
    "completed_utc": utc_now_iso()
})
save_manifest(campaign_id, manifest)
```

下一个 milestone 执行时，`campaign_context` 作为额外字段注入其 Weave Plan（`plan.context.campaign_context`），各 activity 的 system prompt 末尾附加前序 milestone 摘要列表。

**manifest.json 补充字段：**
```json
{
  "campaign_context": [],      // 初始为空，随 milestone 完成追加
  "campaign_status": "running" // 新增状态值：awaiting_intervention（失败等待人工）
}
```

**Milestone 执行失败处理：**

失败条件：review rubric 不通过且超出 rework 预算（默认 2 次）。

处理流程：
1. 写 `milestones/<n>/result.json`：`{ "status": "failed", "reason": "..." }`
2. 写 manifest：`campaign_status = "awaiting_intervention"`
3. Telegram 推送告警
4. Campaign 保持在 Portal 运行中页，显示"milestone N 执行失败" + **重试 / 中止** 按钮

**新增 API endpoint：**
```
POST /campaigns/{campaign_id}/milestones/{n}/retry  → 重新执行 milestone N
```
中止 Campaign 复用现有 `DELETE /campaigns/{campaign_id}`。

**改动范围：**
- `temporal/campaign_workflow.py`：milestone 失败后写 `awaiting_intervention`，通过 `@workflow.signal` 等待 retry 或 cancel
- `services/api_routes/campaigns.py`：新增 `/milestones/{n}/retry` endpoint，发 signal 给 CampaignWorkflow

---

### 2.1 CampaignWorkflow → Child Workflow 架构

**问题：** 当前 `CampaignWorkflow` 把 milestone 的所有步骤作为 activity 直接挂在父 workflow 里，导致 milestone 内任意 activity 失败时，整个 milestone 必须重跑（没有步骤级恢复）。

**正确架构：**

```
CampaignWorkflow（父，负责 milestone 编排 + 用户反馈门控）
  └─ workflow.execute_child_workflow(GraphDispatchWorkflow, milestone_1_plan)
  └─ [等用户评价]
  └─ workflow.execute_child_workflow(GraphDispatchWorkflow, milestone_2_plan)
  └─ ...
```

每个 milestone 是一个独立的 `GraphDispatchWorkflow` child workflow。它本身已有步骤级 checkpoint（`activity_openclaw_step` 的 checkpoint 机制），milestone 内崩了从最后成功的 activity 恢复，不影响其他 milestone。

**改动范围：**

- `temporal/campaign_workflow.py`：
  - 移除直接调用 `activity_openclaw_step` 的代码
  - 改为 `workflow.execute_child_workflow(GraphDispatchWorkflow, milestone_plan, id=milestone_workflow_id)`
  - `milestone_workflow_id` 格式：`daemon-campaign-{campaign_id}-m{n}`，可以按此 ID 查询/取消单个 milestone
- `temporal/worker.py`：worker 注册不变，GraphDispatchWorkflow 已注册
- `services/dispatch.py`：Campaign 提交时仍走 `CampaignWorkflow`，不变
- `services/api_routes/campaigns.py`：cancel campaign 时需要同时 cancel 当前 running 的 child workflow

**注意：** Child workflow 的 history 在 Temporal UI 里是独立条目，便于调试。

---

### 2.2 max_concurrent_activities 可配置化

**问题：** `temporal/worker.py` 中 `max_concurrent_activities` 硬编码为 10，与本地硬件资源不匹配。

**改动：** `temporal/worker.py` 的 `start_worker()` 函数：

```python
# 改前
max_concurrent_activities=10

# 改后
max_concurrent_activities=int(os.environ.get("TEMPORAL_MAX_CONCURRENT_ACTIVITIES", "32"))
```

**建议默认值：32**（实际瓶颈是 LLM provider rate limit，不是本地资源）。

同时在 `.env.example` 加注释说明此参数。

---

## 优先级 3：V2 新增设计，按阶段实施

以下三项均为本次会话中新增至 V2 的设计规范，**目前零代码实现**。

---

### 3.1 Skill 分类声明（V2 §21.1）—— Skills Campaign 前完成

**要做什么：** 在每个现有 skill 的 `SKILL.md` 中加一行 `skill_type` 声明。

```markdown
# skill_type: capability   # 或 preference
```

**分类规则：**
- `capability`：没有这个 skill 系统功能缺失（url_summarize、coding_agent_v2、nano_pdf_render 等）
- `preference`：没有这个 skill 质量下降但不崩溃（router_weave_plan、generate_user_feedback_survey、review rubric skills 等）

**涉及文件：** `workspace/` 下所有 agent 的 `skills/*/SKILL.md`，逐一标注。

**为什么现在做：** 分类是 Skill Benchmark 的前提，且影响 Skills Campaign 里 benchmark rubric 的选择。

---

### 3.2 Skill Benchmark 机制（V2 §21.2-21.4）—— Skills Campaign 中同步建立

**触发时机：** Skills Campaign Milestone 2 时，随每个 skill 的引入/修改同步建立，不提前单独实施。

**每个 skill 新增目录结构：**
```
workspace/<agent>/skills/<skill_name>/benchmark/
  cases.json       # 测试用例列表（输入 + 期望行为 + must_not 约束）
  rubric.json      # 评分维度与权重（capability 型 vs preference 型不同）
  baseline.json    # 当前版本得分基线（首次运行后自动写入）
  history.jsonl    # 历次评测对比记录
```

**cases.json 格式：**
```json
[{
  "case_id": "c001",
  "input": {},
  "expected_behavior": "...",
  "must_not": ["..."]
}]
```

**rubric.json 格式（capability 型）：**
```json
{"correctness": 0.5, "completeness": 0.3, "latency_p95_ok": 0.2}
```

**rubric.json 格式（preference 型）：**
```json
{"style_compliance": 0.4, "user_satisfaction_proxy": 0.4, "consistency": 0.2}
```

**Benchmark 运行工作流（需实现为可调用脚本或 activity）：**
```
1. 读取 cases.json + rubric.json
2. 对改动前后各运行全部 cases（analyze agent 执行）
3. 对比得分：任意维度下降 > 5% → 必须人工审批；全部 ≥ baseline → 允许上线
4. 写入 history.jsonl，更新 baseline.json
5. Telegram 推送对比摘要
```

**与 §15.2 的关系：** `skill_evolution_proposals.json` 中的改动上线前必须先过 benchmark，已在 V2 §15.2 加了强制约束。

详见 V2 §21。

---

### 3.3 Iter-Report Weave Pattern（V2 §20）—— 暖机后按信号引入

**触发条件：** 暖机后 collect/analyze activity 出现上下文质量下降（后期回答质量明显不如前期），届时评估是否引入。

**实现位置：** `weave_patterns/iter_report/`，不改 pipeline 结构，activity 通过 Weave Plan 中 `execution_mode: iter_report` 声明使用。

**核心逻辑：**
- 每轮输入 = `[System Prompt] + [Report_v_n] + [上一轮工具结果]`（非完整历史）
- 每轮输出 = think → 更新 `Report_v_{n+1}` + 下一个 Action
- 终止：Report 标记 `done: true` 或达到最大步数
- Report 每版写入 `state/runs/<run_id>/steps/<step_id>/report_v<n>.json`

**适用 activity：** collect（多 URL 抓取）、analyze（多轮比较）、build（多文件编辑）。

**触发阈值：** Weave Plan 预估该 activity 工具调用轮次 ≥ 4。

详见 V2 §20。

---

## 已知不改的设计决策（不要引入）

| 项目 | 决策 | 原因 |
|---|---|---|
| Circuit 触发策略 | 只保留 cron，不加 on_complete/on_event | 没有具体场景驱动，过度设计 |
| Circuit 实例历史 API | 不做 `/circuits/{id}/history` | Memory fabric 负责实例间记忆，Circuit 自身无状态 |
| Workflow signals（追加要求） | **已引入**（§1.5） | Thread/Campaign 需要；Pulse 不需要 |
| Workflow queries | 不引入 | 现有 REST 轮询够用，queries 仅适合 workflow 内部状态查询 |
| Child workflows for Pulse/Thread | 不引入 | 只有 Campaign milestone 需要，Pulse/Thread 直接用 activity 即可 |
| Activity 文件 flag 取消轮询 | **已废弃**，改为 heartbeat（§1.4） | Heartbeat 是 Temporal 原生机制，延迟低、无竞争条件 |
