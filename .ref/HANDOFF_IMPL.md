# 实施交接：待改动清单

> 日期：2026-03-06
> 基准文档：`daemon_统一方案_v2.md`
> 本文只列"要做什么"，不列"已做什么"。按优先级分组。

---

## 优先级 1：立即执行（阻塞主线）

### 1.1 术语对齐：task → Pulse / Thread / Campaign

代码、API、UI 全面将 `task` 替换为正确术语。V2 §16 已定义三级命名，但代码里仍在用 `task`。

**涉及范围：**
- `state/tasks.json` → 文件名及内部字段（`task_id` → 保留作内部 ID，但展示层用 Pulse/Thread/Campaign）
- `GET /tasks` / `GET /tasks/{id}` → 路由名称及响应字段
- Console UI：Tasks 面板标题、列名
- Portal UI：任务列表展示
- Telegram 通知文案：`任务完成` → 根据 `task_scale` 显示 `Pulse 完成` / `Thread 完成`
- `dispatch.py`、`activities.py` 内部注释和 log 文案（代码变量名可以暂时不改，优先改对外展示）

**注意：** `task_id` 作为内部主键可以保留，但对用户展示的地方必须用正确术语。

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

### 1.3 Portal 对话控制命令

**问题：** Portal 的对话框（`chat.py`）把所有消息直接发给 Router agent，没有控制命令拦截。Telegram 有，Portal 没有，用户无法在 Portal 通过对话取消/暂停任务。

**改动位置：** `services/api_routes/chat.py` 的 `chat()` endpoint，在调用 `dialog.chat()` 之前加意图识别层。

**需要识别的指令（参考 `telegram/adapter.py` 的实现）：**

| 用户输入 | 动作 |
|---|---|
| `取消` / `cancel` / `暂停` / `pause` | 查找当前 running 状态的 run，调 `POST /runs/{id}/pause` |
| `取消任务 <id>` / `cancel <id>` | 调 `POST /runs/{id}/cancel` |
| `取消回路 <id>` / `cancel circuit <id>` | 调 `DELETE /circuits/{id}` |
| `取消 campaign <id>` | 调 `POST /campaigns/{id}/cancel` |

**返回格式：** 不走 Router，直接返回操作结果文本，格式和 Telegram 保持一致。

**参考：** `interfaces/telegram/adapter.py` 的 `_handle_text()` 和 callback 处理部分，逻辑照搬，替换 httpx 调用为内部函数调用即可。

---

## 优先级 2：架构修复（暖机前完成）

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
| Workflow signals/queries | 不引入 | 现有 activity 模式够用，增加复杂度 |
| Child workflows for Pulse/Thread | 不引入 | 只有 Campaign milestone 需要，Pulse/Thread 直接用 activity 即可 |
