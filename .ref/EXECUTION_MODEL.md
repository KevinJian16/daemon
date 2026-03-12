# 执行模型设计

> 日期：2026-03-11
> 本文档记录执行模型的正式设计决策，覆盖 Move/Session/Deed/Folio 的运行机制与状态模型。
> 与 `daemon_实施方案.md` 冲突时，以本文档为准。

---

## 1. Move 颗粒度

### §1.1 1 Move = 1 Agent + 1 交付物

Move 是执行的最小调度单位。每个 Move 由一个 agent 完成，产出一个明确的交付物（outcome-oriented）。

定义的是"产出什么"，不是"执行什么指令"。

### §1.2 不合并、不拆分

同 agent 的并行 Move 不合并为复合指令。每个 Move 独立使用一个 session，OC 在不同 session key 上自然并行。

原 `_consolidate_same_agent_moves()` 机制废止。

### §1.3 职责分界

- **Temporal**：管理 Move 间编排（DAG 依赖、并发控制、重试）
- **Agent**：管理 Move 内执行（包括是否使用 subagent）

系统不干预 agent 在 Move 内部的行为。

---

## 2. Session 模型

### §2.1 单实例多 Session

每个 agent role = 1 个 OC agent instance。总共 7 个 role = 7 个 instance。

并行能力通过多个 session 实现，不通过多个 instance。Retinue 池规模 = 7。

### §2.2 Session 生命周期 = Deed 级别

Session 在 Deed 开始时按需创建，Deed 结束时全部销毁。

同一 Deed 内：

- **串行 Move**：共享同一 session（上下文累积，减少重复 bootstrap）
- **并行 Move**：各自独立 session
- **Rework**：append 到已有 session（不创建新 move_id）

### §2.3 Session Key 格式

```
{agent_id}:{deed_id}:{session_seq}
```

- `session_seq` 从 0 开始
- 串行 Move 共享 seq 0
- 并行 Move 分配递增 seq

### §2.4 Counsel 特殊处理

Counsel 的 UI 对话 ≠ OC session。

- 每次对话可重开 session（ephemeral）
- 跨对话不需要 session 上下文
- Folio/Slip 的对话框与 agent session 是独立概念

---

## 3. Direct Move

### §3.1 定义

机械操作（Telegram 发送、PDF 生成、git 操作等）使用 MCP tool 或 Python activity 直接执行，不经过 OC agent session，零 LLM token 开销。

### §3.2 执行类型

Move 有两种执行类型：

| `execution_type` | 执行路径 | Token 开销 |
|---|---|---|
| `agent`（默认） | OC session | 有 |
| `direct` | MCP / Python activity | 零 |

### §3.3 Direct Move 不需要 Session

Direct Move 不分配 session key，不消耗 retinue allocation。

已有现成 MCP server 的操作优先使用，不自行编写。

### §3.4 MCP 工具分发

Direct Move 通过 `runtime/mcp_dispatch.py` 的 `MCPDispatcher` 执行：

- **配置**：`config/mcp_servers.json`，定义可用的 MCP server（stdio 或 HTTP 传输）
- **路由**：首次使用时连接所有 server，通过 `list_tools()` 构建 tool_name → server 路由表
- **连接**：持久化，Worker 进程级别复用（不是每次 call 重连）
- **SDK**：使用官方 `mcp` Python SDK（Anthropic 维护）的 `ClientSession.call_tool()`
- **超时**：每次 `call_tool` 带 `asyncio.wait_for` 防止 server 崩溃导致 hang

配置格式：
```json
{
  "servers": {
    "server_name": {
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "my_mcp_server"],
      "env": {"API_KEY": "${MY_API_KEY}"}
    }
  }
}
```

`env` 中 `${VAR}` 会被展开为实际环境变量值。

---

## 4. Folio 晋升

### §4.1 触发条件：决策分叉点

Folio 晋升的触发条件是 **decision branch point**：后续阶段的 Design 依赖前面阶段的执行**结果**。

不是 step count 超过 dag_budget。

### §4.2 dag_budget 的定位

dag_budget 是 Ward 层面的**成本护栏**：

- 防止恶意或失控的超大 DAG（如"执行 xxx 100 次"）
- 即使不触发 Folio 晋升，dag_budget 仍然强制执行
- 不决定何时分 Folio（结构性约束），只决定"这个请求是否被允许"（预算约束）

### §4.3 Design 归属

Slip 拥有 Design（DAG 定义）。Deed 创建时冻结当前 DAG 版本。

Deed 不拥有 DAG——它是 Slip 上的一次行为。

### §4.4 DAG 快照机制

Deed 创建时对 Slip 当前 DAG 做快照。Slip 端的 DAG 修改不影响正在运行的 Deed。

- **首次执行**：counsel 从 Slip 对话生成 DAG
- **后续修改**：用户通过 Slip 对话增量调整 DAG
- **生效时机**：新 DAG 只在下一个 Deed 创建时生效

DAG 是 source of truth，Slip 对话是 DAG 的编辑过程，可定期修剪。

---

## 5. 状态模型

### §5.1 设计原则：两层模型

- **主状态**（每种对象 2-3 个）：用户可见，直接控制 UI 展示
- **技术子状态**（`sub_status` 字段）：系统内部运行细节，作为 metadata 存储

### §5.2 Draft

| 主状态 | 含义 | 对应旧状态 |
|---|---|---|
| `drafting` | 草稿编辑中 | open, refining |
| `gone` | 已完成使命 | crystallized, superseded, abandoned |

子状态：`gone` → `{crystallized, superseded, abandoned}`

### §5.3 Slip

| 主状态 | 含义 | 对应旧状态 |
|---|---|---|
| `active` | 活跃 | active, parked |
| `archived` | 归档 | settled, archived |
| `deleted` | 已删除 | absorbed |

子状态：`active` → `{normal, parked}`

### §5.4 Folio

| 主状态 | 含义 | 对应旧状态 |
|---|---|---|
| `active` | 活跃 | active, parked |
| `archived` | 归档 | archived |
| `deleted` | 已解散 | dissolved |

子状态：`active` → `{normal, parked}`

### §5.5 Deed

| 主状态 | 含义 | 对应旧状态 |
|---|---|---|
| `running` | 执行中 | queued, running, paused, cancelling |
| `settling` | 待定，等待用户评审 | awaiting_eval |
| `closed` | 已关闭 | completed, failed, cancelled |

子状态：

- `running` → `{queued, executing, paused, retrying}`
- `settling` → `{reviewing}`
- `closed` → `{succeeded, failed, cancelled, timed_out}`

### §5.5.1 Deed 按钮模型

Deed 只有两组按钮：

| 按钮 | 作用 | 触发行为 |
|------|------|---------|
| 开始/停止（toggle） | 启动或中断当前执行 | 按「开始」触发洗信息 → 调整内容喂给 Brief |
| 收束 | 关闭 Deed | 触发洗信息 → 评价内容喂给系统 |

Deed 内多次开始/停止是同一个 Deed。「开始」不创建新 Deed。

Slip 页面的「执行」按钮创建新 Deed，与 Deed 内的「开始」是不同层级的操作。

### §5.6 Writ

保持不变：`active | paused | disabled`

### §5.7 Deed Settling 机制

Deed 完成执行后进入 `settling`。

不存在独立的评价表单。Settling 就是 Deed 对话本身：

- 用户对话即反馈（"太正式了""算了就这样吧"）
- 用户按钮即动作（开始 = 再来一次，收束 = 接受结果）
- 30 分钟评审窗口，超时后 custody 机制自动 close

### §5.7.1 洗信息触发

按钮按下时触发洗信息。洗信息只做**机械提取**，不用 LLM：

- Ledger：rework 次数、消息数、时长
- Voice 候选：关键词匹配提取

按钮决定洗出物路由：

- 按「开始」→ 洗出物喂给下次执行（Brief 补充）+ 系统（Ledger 统计）
- 按「收束」→ 洗出物只喂系统

调整和评价不是两种类别——每条消息同时包含两者。分类由按钮决定路由，不由内容决定分类。

所有洗出物流入系统前必须过 Instinct 代码门控。

### §5.7.2 对话段归属

按钮定义状态边界，对话填充边界间的语义空间。Slash command = 按钮。

running 期间输入框始终开放，但对话不影响当前执行。running 期间和执行完成后的消息语义等价——都是对下次执行（或最终评价）的输入。

### §5.7.3 Deed 收束后冻结

Deed 收束后只保留产物标签和对话历史。只读，无操作。

过去的 Deed 有保质期，过期从页面淡去。

### §5.8 下游触发

Writ chain 的下游触发基于 `deed_closed`（用户确认关闭），不是 `deed_completed`（系统完成执行）。

一个 Slip 同一时间只允许一个 non-closed Deed。

---

## 6. Token 优化

### §6.1 Session Bootstrap 最小化

Session 启动只加载 objective + 选择性 Psyche 注入（见 `DESIGN_QA.md` Q1.8），不加载全量上下文。

### §6.2 上下文摘要

Move 间传递上下文使用摘要而非原文。

### §6.3 Ledger 统计注入

Counsel 通过 `planning_hints`（Ledger 统计摘要）获得规划参考，不直接注入原始数据。

### §6.4 Direct Move 零 Token

机械操作使用 Direct Move。

---

## 7. Rework 机制修正

### §7.1 Rework 不创建新 Move

Arbiter 驳回后，rework 的 Move append 到原 agent 的已有 session，不生成新 move_id。

Agent 在已有上下文中看到 arbiter 反馈，直接修正输出。

### §7.2 Rework Session 复用

Rework 使用与原 Move 相同的 session key，利用已积累的上下文。
