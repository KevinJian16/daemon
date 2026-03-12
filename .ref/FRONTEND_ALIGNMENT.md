# 前端对齐：14 个问题的后端回答

> 日期：2026-03-12
> 本文档回答前端同事在对接过程中提出的 14 个阻塞问题。
> 每条回答包含：结论、后端需要做的改动、前端应如何对接。
> ⚠ 标注的项表示 INTERACTION_DESIGN.md 文档尚未更新到最新设计，以本文档为准。

---

## 重要前置：对话模型

### 对话统一在 Slip 层

没有独立的"Deed 对话"。Slip 页面只有一条对话流，承载所有交互。

INTERACTION_DESIGN.md §2.3 写的"Slip 对话只调整 DAG"和 §2.3.1 写的"Deed 对话框"是旧设计。文档更新会跟进。

### 交互行为与对话完全等价

用户打字说"执行"和用户按"执行"按钮，对系统来说效果完全一样。按钮只是 UI 便捷入口，不是独立于对话的控制通道。

所有用户操作（按钮、拖拽、姿态变更等）都生成自然语言记录插入对话流（DESIGN_QA §7.6、INTERACTION_DESIGN §2.7.2）。对话流是唯一的、完整的行为日志。

系统内所有需要理解"用户做了什么、说了什么"的模块（counsel、洗信息等），只读对话流，不区分条目来源。用户打的字和按钮生成的记录，权重一样、处理方式一样，不走不同逻辑分支。

底层存储可以用字段标记来源（方便前端渲染成不同视觉样式），但后端处理时等价。

### 评价链 = Deed 内、以运行为分段

评价是 Deed 级别的，不是 Slip 级别的。

一个 Deed 的生命周期内可以有多次运行（rework）。**评价段** = 一次运行开始到下一次运行开始之间的所有对话内容。多个评价段串起来就是这个 Deed 的评价链。

- 链头 = 第一次运行开始
- 链尾 = 收束
- 运行不一定是用户按按钮触发的——counsel 判断 rework 也会启动新运行、定时器和 Writ 链也会

**洗信息**在运行周期边界触发：新一次运行开始时，机械提取上一段对话内容（DESIGN_QA §7.5）。洗信息不用 LLM，纯机械。

### counsel 的判断依据

counsel 读对话流。对话流里既有用户说的话，也有操作转化成的自然语言记录。counsel 基于这些内容判断反馈是 rework（同 Deed 再跑）还是 DAG 修改。对话流是 counsel 唯一的输入。

---

## Portal 阻塞（1-11）

### 1. Deed 详情页是不是正式公开路由？

**结论**：⚠ Deed 不是独立页面，是 Slip 页面内的展开块。

按合并后的设计，Deed 没有独立页面。用户在 Slip 页面看到所有 Deed 执行块，点击可展开。

但 `/portal/slips/{slug}/deeds/{deed_id}` 作为**深链接**保留：打开后定位到 Slip 页面，并自动展开/聚焦到对应的 Deed 执行块。

**后端要做**：
- 加上 `/portal/slips/{slug}/deeds/{deed_id}` 静态路由（serve index.html，前端路由处理）

**前端对接**：
- 路由 `/portal/slips/{slug}/deeds/{deed_id}` → 渲染 Slip 页面 + 自动滚动到该 Deed 块
- 不需要做独立的 Deed 页面组件

---

### 2. Slip 页对话是 Slip-owned 还是 Deed 的代理？

**结论**：Slip-owned。

对话统一在 Slip 层。所有消息（用户对话、系统操作记录、Deed 执行进度）都在一个流里。

当前后端 `/portal-api/slips/{slug}/messages` 只读 active/latest deed 的消息——这需要改。

**后端要做**：
- `/portal-api/slips/{slug}/messages` 改为返回该 Slip 下所有 Deed 的消息，按时间排序，合并为统一对话流
- 每条消息带 `deed_id` 字段，前端可按此区分属于哪次执行
- Deed 执行块的边界通过 `event: "operation"` 类型的消息（如"开始执行""收束"）来标识

**前端对接**：
- 调一次 `/portal-api/slips/{slug}/messages` 就拿到完整对话流
- 根据消息的 `deed_id` 和 `event` 类型，在流中渲染 Deed 执行块的起止边界

---

### 3. Slip 没有 active Deed 时发消息的语义？

**结论**：发消息 = 用户给出新指令，后端用这条消息创建新 Deed 并执行。当前后端行为正确。

这和 Claude 的交互模式一致：你在对话框输入一条消息，系统理解意图并执行。"执行"按钮是另一个入口，用于"按现有 DAG 再执行一次"而不附带新消息。

**后端要做**：无改动，当前逻辑正确。

**前端对接**：
- 没有 active Deed 时，输入框正常可用
- 用户发消息 → 调 `POST /portal-api/slips/{slug}/message` → 后端自动创建 Deed 并执行
- "执行"按钮 → 调 `POST /portal-api/slips/{slug}/rerun` → 后端按现有 DAG 创建新 Deed

---

### 4. Deed running 期间发消息是否暂停执行？

**结论**：不暂停。

用户在执行期间发消息是正常的——聊聊方向、补充想法、记录调整意见。这些消息追加到对话流，当前执行继续跑。等这次执行完成（或用户主动按停止），下次 rework/洗信息时再消费这些消息。

当前后端的 `pause_execution` 行为是 bug，会修掉。

---

### 5. settling / 反馈 / 收束的正式前台语义？

**结论**：

1. **不存在独立反馈 UI**（DESIGN_QA §7.3 已定死）。用户在对话框里说的话就是反馈。
2. **"收束"是按钮**，调用方式：`POST /portal-api/slips/{slug}/stance` + `{ "target": "settle" }`。（已实现）
3. **feedback API 不进前台**。FRONTEND_GUIDE 里提到的 `feedback*` 接口是纯后台机制（供 Console 和内部统计用），Portal 不调。

**后端已做**：
- `settle` 目标已加入 stance 端点，语义明确：停止当前执行 → Deed 状态转 closed/succeeded → 发 deed_closed 事件
- `park` 保留为"暂存"语义，不用于收束

**前端对接**：
- settling 阶段：Deed 执行块显示产物预览 + 对话框继续可用（用户可以发评价/调整意见）
- 收束按钮 → 调 `POST /portal-api/slips/{slug}/stance` + `{ "target": "settle" }`
- 不需要做任何 feedback 表单/弹窗/评分组件

---

### 6. Deed 页用哪组接口？

**结论**：Portal 直接用 generic `/deeds/*` 接口处理 Deed 级操作。

由于 Deed 不是独立页面（是 Slip 页内嵌块），Deed 的操作在 Slip 页面中完成。接口分工：

| 操作 | 接口 | 说明 |
|------|------|------|
| 暂停 | `POST /deeds/{deed_id}/pause` | generic 接口 |
| 恢复 | `POST /deeds/{deed_id}/resume` | generic 接口 |
| 发消息 | `POST /portal-api/slips/{slug}/message` | Slip 级统一入口，running 期间不暂停执行 |
| 查消息 | `GET /portal-api/slips/{slug}/messages` | Slip 级统一流 |
| 收束 | `POST /portal-api/slips/{slug}/stance` + `settle` | Slip 级，停止执行并关闭 Deed |
| 查 Deed 详情 | `GET /deeds/{deed_id}` | generic 接口，展开历史 Deed 块时用 |
| 查产物文件 | `GET /offerings/{deed_id}/files` | generic 接口，按 deed_id 查 |
| 查产物文件（Slip 级） | `GET /portal-api/slips/{slug}/result/files` | 查最新 Deed 的产物 |

不需要 `/portal-api/deeds/*` 系列。暂停/恢复和历史 Deed 查询都是 Deed 级别的精确操作，直接用 deed_id 调 generic 接口。

**后端已做**：`settle` 目标已实现；`/deeds/{deed_id}` 和 `/offerings/{deed_id}/files` 已存在。

**前端对接**：
- Slip 页面拿到 deed 信息后（包含 `deed_id`），Deed 执行块内的暂停/恢复按钮直接调 `/deeds/{deed_id}/pause|resume`
- 其他操作走 `/portal-api/slips/{slug}/*`

---

### 7. Deed sub_status 正式枚举

**结论**：以 EXECUTION_MODEL.md §5.5 为准，最终枚举如下：

| 主状态 | sub_status 枚举 |
|--------|----------------|
| `running` | `queued`, `executing`, `paused`, `retrying` |
| `settling` | `reviewing` |
| `closed` | `succeeded`, `failed`, `cancelled`, `timed_out` |

FRONTEND_GUIDE 里的 `comparing` / `evaluating` 是旧值，已废弃。代码中如果有不在此表中的值，是后端 bug，会在验收脚本中检出。

**后端要做**：
- 清理代码中的旧 sub_status 值
- 更新 FRONTEND_GUIDE

**前端对接**：
- 只需处理上表中的 sub_status 值
- 收到未知 sub_status 时 fallback 显示为主状态的文案

---

### 8. Deed 主状态中文文案

**结论**：统一为以下文案，不再变。

主状态：

| 状态 | 中文 |
|------|------|
| `running` | 执行中 |
| `settling` | 待收束 |
| `closed` | 已关闭 |

子状态：

| sub_status | 中文 |
|-----------|------|
| `queued` | 排队中 |
| `executing` | 执行中 |
| `paused` | 已暂停 |
| `retrying` | 重试中 |
| `reviewing` | 待收束 |
| `succeeded` | 已完成 |
| `failed` | 失败 |
| `cancelled` | 已取消 |
| `timed_out` | 已超时 |

"待比较"、"已冻结"等旧文案全部废弃。

**后端要做**：更新 FRONTEND_GUIDE 中的文案表。

**前端对接**：前端 `format.js` 中的映射表以此为准。

---

### 9. Move DAG 图结构 payload

**结论**：后端会在 Slip 详情和消息流中提供 DAG 图结构。

当前 `plan.timeline` 只是线性步骤列表，不够。后端会改为返回：

```json
{
  "dag": {
    "nodes": [
      { "id": "move_001", "agent": "scout", "label": "搜索资料", "status": "pending" }
    ],
    "edges": [
      { "from": "move_001", "to": "move_002" }
    ]
  }
}
```

- `status` 取值：`pending` / `running` / `completed` / `failed` / `skipped`
- Deed 运行时通过 WebSocket `deed_progress` 事件推送节点状态更新
- 已关闭的 Deed，DAG 是冻结快照

**后端要做**：
- Slip 详情的 `plan` 字段改为包含 `dag`（nodes + edges）
- WebSocket `deed_progress` 事件的 payload 加上 `move_status` 变更

**前端对接**：
- 用 `dag.nodes` 和 `dag.edges` 画图
- 监听 `deed_progress` 事件更新节点状态

---

### 10. Folio 关系图 graph payload

**结论**：后端会在 Folio 详情里补上 Writ edge 结构。

当前 Folio 的 `writs` 摘要没有 source/target。后端改为：

```json
{
  "writs": [
    {
      "id": "writ_xxx",
      "title": "完成后触发",
      "source_slip_id": "slip_aaa",
      "target_slip_id": "slip_bbb",
      "event": "deed_closed",
      "status": "active"
    }
  ]
}
```

前端拿 `slips` 当 nodes、`writs` 当 edges 就能画 Folio 内的关系图。

**后端要做**：
- Folio 详情的 `writs` 数组改为上述结构（从 Writ 的 match/action 中提取 source/target）

**前端对接**：
- `slips` = 节点
- `writs` = 有向边（source_slip_id → target_slip_id）

---

### 11. writ_chain 和 timer 的前台摘要字段

**结论**：后端补，不让前端 N+1 查。

- `writ-neighbors` 响应：每个前驱/后继 Slip 补上 `latest_deed_status`（前端可直接判断阻塞状态）
- `cadence` 响应：补上 `next_trigger_utc`（从 Writ 的 schedule cron 表达式算出下次触发时间）

**后端要做**：
- `writ_neighbors()` 返回值的每个 Slip 加 `latest_deed_status` 字段
- `_cadence_state_for_slip()` 加 `next_trigger_utc` 字段

**前端对接**：
- `trigger_type == "writ_chain"` 时，显示前驱 Slip 列表 + 各自的 `latest_deed_status`
- `trigger_type == "timer"` 时，显示 `next_trigger_utc`

---

## WebSocket 心跳（12）

### 12. WebSocket 心跳契约

**结论**：FRONTEND_GUIDE 写反了。以代码实际行为为准：

实际行为（api.py:1215-1226）：
1. 服务端等待客户端消息，超时 20 秒
2. 超时后服务端发 `{"event": "ping"}`
3. 客户端发文本 `"ping"` 时，服务端回 `{"event": "pong"}`

**前端应实现**：
- 每 15 秒发一次文本 `"ping"`
- 收到 `{"event": "ping"}` 时回文本 `"ping"`
- 20 秒没收到任何服务端消息 → 断连重连

**后端要做**：更新 FRONTEND_GUIDE 心跳部分。

---

## Draft API（13）

### 13. Draft 的 Portal 前台 API / 路由

**结论**：

- Draft **没有详情页**。它活在 tray 里。
- Portal 直接用 generic `/drafts` 接口：

| 操作 | 接口 |
|------|------|
| 列出所有 Draft（tray 内容） | `GET /drafts` |
| 获取单个 Draft | `GET /drafts/{draft_id}` |
| 更新 Draft（改 title/objective 等） | `PUT /drafts/{draft_id}` |
| 成札（crystallize） | `PUT /drafts/{draft_id}` + `{ "status": "gone", "sub_status": "crystallized" }` |
| 放弃 | `PUT /drafts/{draft_id}` + `{ "status": "gone", "sub_status": "abandoned" }` |
| 继续收敛 | Voice 对话接口，session 关联 draft_id |

**前端对接**：
- Tray 组件调 `GET /drafts` 显示列表
- 每个 Draft 条目：点击 → 继续收敛（进 Voice 对话）/ 成札 / 放弃
- 不需要 `/portal-api/drafts/*`

---

## Console 规范冲突（14-15）

### 14. Console 里 Voice 文件能不能直接编辑？

**结论**：可以。这是第二个正式例外。

Voice 文件（identity.md / common.md / zh.md / en.md + overlays/*.md）和技能正文一样，是文本能力对象，结构化编辑反而破坏表达。

后端 `/console/psyche/voice/{filename}` PUT 接口已开放，是有意为之。

INTERACTION_DESIGN.md §3.6 的"唯一明确例外"需要更新为两个例外：技能正文 + Voice 文件。

---

### 15. Console 的隐私边界

**结论**：当前 `/console/slips/{id}` 返回了完整 `brief` 和 `design`，需要裁剪。

INTERACTION_DESIGN.md §3.7 明确：Console 不暴露主人的对话正文、Slip 私人内容全文。

**后端要做**：
- `/console/slips/{id}` 的 `brief` 字段只返回结构化元数据：`objective`（标题级摘要）、`complexity`、`depth`、`dag_budget`
- `design` 字段只返回结构信息：moves 数量、agent 角色列表，不返回 `instruction` 等指令原文
- 完整内容只在 Portal 可见

**前端对接**：
- Console 的 Slip 详情页不显示对话原文和指令详情
- 显示：objective、complexity、depth、moves 数量、agent 列表、状态、统计

---

## 后端改动汇总

### 核心机制（设计已定、后端未实现）

| 改动 | 优先级 |
|------|--------|
| 对话流统一到 Slip 层——消息存储和 API 都要改 | P0 |
| 所有用户操作（按钮、拖拽、姿态变更）→ 自然语言记录 → 插入 Slip 对话流 | P0 |
| running 期间发消息不暂停执行（删除 pause_execution） | P0 |
| 洗信息在运行周期边界触发（新运行开始时，机械提取上一段对话） | P0 |

### 接口与数据补全

| # | 改动 | 优先级 |
|---|------|--------|
| 1 | 加 `/portal/slips/{slug}/deeds/{deed_id}` 静态路由 | P0 |
| 2 | `/portal-api/slips/{slug}/messages` 返回 Slip 下所有 Deed 的合并对话流 | P0 |
| 5 | 更新 FRONTEND_GUIDE，删除 feedback 前台引用 | P1 |
| 7 | 清理代码中的旧 sub_status 值 | P1 |
| 9 | Slip 详情补 DAG graph 结构（nodes + edges） | P0 |
| 10 | Folio 详情补 Writ edge 结构（source_slip_id / target_slip_id） | P0 |
| 11 | writ-neighbors 补 latest_deed_status，cadence 补 next_trigger_utc | P1 |
| 12 | 更新 FRONTEND_GUIDE 心跳描述 | P1 |
| 15 | Console slip 详情做字段裁剪 | P1 |

不需要改动的：3（当前行为正确）、6（接口分工已明确）、8（文案已定）、13（generic 接口够用）、14（已开放）。
