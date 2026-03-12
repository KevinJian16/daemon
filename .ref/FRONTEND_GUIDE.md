# Daemon 前端开发指南

> 给前端同事的完整开发文档。从零到完成，不需要其他背景知识。
> 日期：2026-03-12

---

## 0. 你在做什么

Daemon 是一个 AI 任务系统。用户（主人）通过 **Portal** 下达任务、查看结果、给反馈。维护者通过 **Console** 做系统治理。

你负责的是 **Portal**——主人和 Daemon 共用的一张案桌。

---

## 1. 五个核心对象

整个系统只有五个正式对象，Portal 和 Console 通用：

| 对象 | 中文 | 一句话定义 | 前端角色 |
|------|------|-----------|---------|
| **Draft** | 草稿 | 还没正式成札的候选事项 | 托盘里的卡片，可收敛为 Slip |
| **Slip** | 签札 | 最小可持久化任务对象 | **Portal 主角**——每张 Slip 有自己的页面 |
| **Folio** | 卷 | 收纳多张 Slip 的主题容器 | 组织层，Slip 的父容器 |
| **Writ** | 成文 | 写在 Folio 里的自动化规则 | 主要在 Console 呈现，Portal 只需感知 |
| **Deed** | 行事 | 一张 Slip 下的一次具体执行 | Slip 页面内的执行实例块 |

**关键关系**：
- 一张 Slip 可以有多个 Deed（每次执行是一个 Deed）
- 多张 Slip 可以收入一个 Folio
- Writ 连接 Folio 内的 Slip，形成 DAG（有向无环图）
- Draft 是 Slip 的前身，收敛后变成 Slip

---

## 2. 状态模型

### Slip 状态
- 主状态：`active` | `archived` | `deleted`
- 子状态：`normal` | `parked`
- 触发类型（`trigger_type`，三选一互斥）：`manual` | `timer` | `writ_chain`

### Deed 状态
- 主状态：`running` | `settling` | `closed`
- 子状态：`queued` | `executing` | `paused` | `cancelling` | `retrying` | `reviewing` | `comparing` | `evaluating` | `succeeded` | `failed` | `cancelled` | `timed_out`

### Folio 状态
- 主状态：`active` | `archived` | `deleted`

### Draft 状态
- 主状态：`drafting` | `gone`

---

## 3. 设计哲学

**必读**：`.ref/INTERACTION_DESIGN.md`（交互设计权威文档）

核心原则：

1. **静态学 Claude**：内容先于控件，排版即层级，留白克制，页面像成熟内容产品而不是后台工具
2. **动态学 Apple**：层级切换有方向感，对象进出有连续感，动效克制精确有弹性
3. **Portal = Claude 静态 + Apple app 层级动态 + 文件系统式对象操作**

**禁止**：
- 不堆按钮、不堆 badge、不堆面板
- 不做 Kanban 看板味、工单后台味、任务管理器味
- 不硬切、不瞬切、不突兀弹出
- 不做普通 web app 的后台布局

---

## 4. 技术栈

当前已搭建：
- **React 18** + **Vite 5**
- **Tailwind CSS 3**
- **React Router v6**
- **lucide-react** 图标
- **react-markdown** + remark-gfm
- 无全局状态管理（纯 useState + 直接 API 调用）

构建：
```bash
cd interfaces/portal
npm install
npm run dev      # 开发 → http://localhost:5173
npm run build    # 产出到 compiled/
```

后端代理：Vite dev server 在 `vite.config.js` 里配了 proxy 到 `http://127.0.0.1:8000`。

---

## 5. 路由

```
/portal/                    → 首页（侧栏 + 默认视图）
/portal/slips/{slug}        → Slip 页面
/portal/slips/{slug}/deeds/{deed_id}  → Deed 详情页（从 Slip 进入）
/portal/folios/{slug}       → Folio 卷页
```

注意：URL 用的是 `slug`（人类可读的短标识），不是 `id`。

---

## 6. API 全量清单（Portal 用到的）

后端 base URL: 同源（Vite proxy 到 `http://127.0.0.1:8000`）。

### 6.1 侧栏

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/portal-api/sidebar` | 侧栏数据 |

响应：
```json
{
  "pending": [...],   // 待收束的 Slip（deed_status == "settling"）
  "live": [...],      // 执行中的 Slip（deed_status == "running"）
  "folios": [...],    // Folio 摘要列表
  "recent": [...],    // 最近的独立 Slip（不在 Folio 内）
}
```

每个 Slip 摘要（`SlipSummary`）的结构：
```json
{
  "id": "slip_xxxxx",
  "slug": "my-task",
  "canonical_slug": "my-task",
  "title": "我的任务",
  "objective": "任务目标",
  "stance": "active",           // active | archived | deleted
  "standing": false,            // 是否常驻
  "trigger_type": "manual",     // ★ manual | timer | writ_chain
  "folio": { "id": "", "slug": "", "title": "", "status": "" } | null,
  "deed": {
    "id": "deed_xxxxx",
    "status": "running",        // running | settling | closed | ""
    "created_utc": "...",
    "updated_utc": "..."
  },
  "updated_utc": "...",
  "created_utc": "...",
  "result_ready": true,
  "cadence": {
    "writ_id": "",
    "schedule": "0 9 * * 1-5",
    "status": "active",
    "standing": true,
    "active": true
  },
  "message_count": 12,
  "plan": {
    "timeline": [
      { "id": "move_1", "label": "搜集资料" },
      { "id": "move_2", "label": "撰写报告" }
    ]
  }
}
```

Folio 摘要（`FolioSummary`）：
```json
{
  "id": "folio_xxxxx",
  "slug": "my-project",
  "title": "我的项目",
  "summary": "项目描述",
  "status": "active",
  "updated_utc": "...",
  "slip_count": 5,
  "live_slip_count": 1,
  "review_slip_count": 2,
  "writ_count": 3,
  "recent_slips": [SlipSummary, ...]  // 最多 4 个
}
```

### 6.2 Slip 详情

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/portal-api/slips/{slug}` | Slip 详情 |

响应：SlipSummary 扩展，额外包含：
```json
{
  ...SlipSummary,
  "feedback": { ... },        // 当前反馈状态
  "current_deed": { "id": "", "status": "", "created_utc": "", "updated_utc": "" },
  "recent_deeds": [           // 最近 6 个 Deed
    { "id": "", "status": "", "created_utc": "", "updated_utc": "" }
  ]
}
```

### 6.3 Slip 消息

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/portal-api/slips/{slug}/messages?limit=300` | 获取对话消息 |
| POST | `/portal-api/slips/{slug}/message` | 发送消息 |

消息结构：
```json
{
  "deed_id": "deed_xxxxx",
  "role": "user" | "assistant" | "system",
  "content": "消息内容",
  "event": "user_message" | "operation" | "deed_progress" | ...,
  "created_utc": "2026-03-12T10:30:00Z",
  "meta": { "source": "portal", "action": "暂停执行" }
}
```

**★ 新增：操作记录消息**
`role == "system"` 且 `event == "operation"` 的消息是按钮操作的自然语言记录。
格式：`[操作] 暂停执行`
建议：用淡色标签样式渲染，与 agent 消息区分。

发送消息 body：`{ "text": "你的消息" }`

### 6.4 Slip 操作

| 方法 | 路径 | Body | 说明 |
|------|------|------|------|
| POST | `/portal-api/slips/{slug}/rerun` | 无 | 执行（创建 Deed + 运行，原子操作）|
| POST | `/portal-api/slips/{slug}/stance` | `{ "target": "continue" \| "park" \| "archive" }` | 状态变更 |
| POST | `/portal-api/slips/{slug}/copy` | 无 | 复制 Slip |
| POST | `/portal-api/slips/{slug}/take-out` | 无 | 从 Folio 取出 |

**★ 强约束**：`trigger_type == "writ_chain"` 的 Slip，前驱未全部 closed 时，`rerun` 和 `stance:continue` 会返回 `409`：
```
writ_precondition_unmet:predecessors_not_closed:slip_xxx,slip_yyy
```
前端应在调用前就 disable 执行按钮（通过 writ-neighbors API 检查），409 时显示"前置任务未完成"。

### 6.5 Slip DAG 导航 ★ 新增

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/portal-api/slips/{slug}/writ-neighbors` | Writ DAG 前驱/后继 |

响应：
```json
{
  "prev": [{ "slip_id": "...", "slug": "...", "title": "..." }],
  "next": [{ "slip_id": "...", "slug": "...", "title": "..." }]
}
```

**UI 处理**：
- `prev` 和 `next` 各只有 1 个 → 单箭头导航（"← 上一张" / "下一张 →"）
- `next` 有多个 → 分支（列出多个"下一张"，标注各自标题）
- `prev` 有多个 → 合并（列出多个"上一张"，标注各自标题）
- 都为空 → 不显示导航

### 6.6 反馈

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/portal-api/slips/{slug}/feedback/state` | 反馈状态 |
| POST | `/portal-api/slips/{slug}/feedback` | 提交反馈 |
| POST | `/portal-api/slips/{slug}/feedback/append` | 追加反馈 |

### 6.7 结果文件

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/portal-api/slips/{slug}/result/files` | 结果文件列表 |
| GET | `/portal-api/slips/{slug}/result/files/{path}` | 下载文件 |

### 6.8 定时 (Cadence)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/portal-api/slips/{slug}/cadence` | 定时状态 |
| PUT | `/portal-api/slips/{slug}/cadence` | 设置定时 `{ "schedule": "0 9 * * 1-5", "enabled": true }` |
| DELETE | `/portal-api/slips/{slug}/cadence` | 删除定时 |

### 6.9 Folio 操作

| 方法 | 路径 | Body | 说明 |
|------|------|------|------|
| GET | `/portal-api/folios/{slug}` | 无 | Folio 详情（含 slips, writs, recent_results）|
| POST | `/portal-api/folios/{slug}/adopt` | `{ "slip_slug": "xxx" }` | 收入一张 Slip |
| POST | `/portal-api/folios/{slug}/reorder` | `{ "ordered_slugs": [...] }` 或 `{ "source_slug": "a", "target_slug": "b" }` | 重排 |
| POST | `/portal-api/folios/from-slips` | `{ "source_slug": "a", "target_slug": "b" }` | 两张 Slip 合成新 Folio |

Folio 详情响应：
```json
{
  ...FolioSummary,
  "slips": [SlipSummary, ...],       // 有序 Slip 列表
  "writs": [                          // Writ 列表
    {
      "id": "writ_xxx",
      "title": "每日报告",
      "status": "active",
      "last_triggered_utc": "...",
      "recent_deeds": [...]
    }
  ],
  "recent_results": [                 // 最近结果
    {
      "deed_id": "...",
      "slip_id": "...",
      "slip_slug": "...",
      "slip_title": "...",
      "title": "结果标题",
      "updated_utc": "..."
    }
  ]
}
```

### 6.10 Voice 对话（创建新任务）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/voice/session` | 创建对话 session |
| POST | `/voice/{session_id}` | `{ "message": "帮我写一份报告" }` 发消息 |

Voice 是 Daemon 的自然语言入口——用户说一句话，Daemon 理解意图、生成 plan、创建 Draft → Slip → Deed。

---

## 7. WebSocket 实时推送

### 连接
```javascript
const ws = new WebSocket(`ws://${location.host}/ws`);
```

### 握手
连接成功后服务端发送：
```json
{ "event": "connected", "payload": { "app_started_utc": "..." }, "created_utc": "..." }
```

### 心跳
服务端每 20 秒发 ping，客户端收到后回 `"pong"`。超时 20 秒断连。

### 事件格式
```json
{
  "event": "deed_progress",
  "payload": { "deed_id": "...", "move_id": "...", "phase": "started", ... },
  "created_utc": "2026-03-12T10:30:00Z"
}
```

### 关键事件

| 事件 | 含义 | payload 关键字段 |
|------|------|-----------------|
| `deed_progress` | 执行进度 | `deed_id`, `move_id`, `phase` (started/waiting/move_completed/degraded), `move_label` |
| `deed_settling` | 执行完成，进入评价 | `deed_id`, `slip_id`, `folio_id`, `summary` |
| `deed_closed` | 行事关闭 | `deed_id`, `slip_id`, `folio_id` |
| `deed_failed` | 执行失败 | `deed_id`, `error` |
| `deed_message` | 新消息 | `deed_id`, `role`, `content`, `event`, `created_utc` |
| `eval_expiring` | 评价窗口即将超时 | `deed_id`, `deadline_utc` |
| `ward_changed` | 系统状态变更 | `status` (GREEN/YELLOW/RED) |

**推荐用法**：
- 收到 `deed_progress` / `deed_message` → 追加到当前 Slip 的消息列表
- 收到 `deed_settling` → 更新 Deed 状态为 settling，提示用户评价
- 收到 `deed_closed` → 更新 Deed 状态，刷新 sidebar
- 所有事件不分频道，前端按 `deed_id` / `slip_id` 过滤

---

## 8. 页面规格

### 8.1 Slip 页面（`/portal/slips/{slug}`）

**结构**（自上而下）：

1. **标题区**
   - Slip 标题（衬线体，大）
   - 目标描述
   - 如果有 Folio → 显示"← 卷名"返回链接

2. **DAG 导航** ★
   - 调用 `GET /portal-api/slips/{slug}/writ-neighbors`
   - 有 prev/next 时显示导航标签（见 §6.5）

3. **Plan Card**
   - 每张 Slip 必须有 plan card（即使任务简单也要有，只是更短）
   - 显示 `plan.timeline` 里的步骤列表
   - DAG 执行中时，当前步骤高亮

4. **历次 Deed 列表**
   - `recent_deeds` 数组，最近的在上
   - 旧 Deed 逐渐淡去（CSS opacity 递减）
   - 点击进入 Deed 详情页

5. **对话流**
   - 调用 `GET .../messages`
   - 渲染所有消息（user / assistant / system）
   - `event == "operation"` 的 system 消息用淡色标签
   - WebSocket 推送 `deed_message` 时实时追加

6. **底部区域**
   - 输入框（Composer）
   - **动作按钮区**（按 `trigger_type` 动态显示）：

| `trigger_type` | 显示内容 |
|----------------|---------|
| `manual` | 「执行」按钮。有 active Deed → 按钮变 disabled "执行中" |
| `timer` | 定时信息。显示 `cadence.schedule` + 下次触发时间 + 开/关 |
| `writ_chain` | 前驱条件。调 writ-neighbors，列出 prev Slips 的状态。全部 closed → 显示可执行；否则 disabled"等待前置任务" |

### 8.2 Deed 页面（`/portal/slips/{slug}/deeds/{deed_id}`）

从 Slip 页面点入某个 Deed，或执行后自动跳转。

**结构**：

1. **DAG 进度**
   - 同 plan card，但显示当前 Move 的执行流动
   - WebSocket `deed_progress` 事件驱动进度更新

2. **对话流**
   - 同 Slip 消息但只显示该 Deed 的
   - running 期间输入框开放，对话不影响执行

3. **按钮区**
   - **开始/停止** (toggle)：`running` 时显示"停止"（→ `POST .../stance` target=park），`paused` 时显示"继续"（→ target=continue）
   - **收束**：结束评价周期，关闭 Deed

4. **收束后**
   - 页面冻结为只读
   - 显示产物标签（result files）
   - 显示完整对话历史
   - 无操作按钮

### 8.3 Folio 页面（`/portal/folios/{slug}`）

**结构**：

1. **卷标题与摘要**
   - 标题（衬线体，大）
   - `summary` 文本

2. **结构视图**（Slip 列表 + 内联操作）
   - `slips` 数组，有序
   - 每张 Slip 旁边按 `trigger_type` 显示内联操作区：

| Slip `trigger_type` | 内联显示 |
|---------------------|---------|
| `manual` | 「执行」按钮（有 active Deed → disabled） |
| `timer` | 下次触发时间 |
| `writ_chain` | 前驱条件状态（满足 ✓ / 未满足 ○） |

3. **Slip Deck**
   - 阅读模式：堆叠卡片视觉
   - 整理模式：拖拽重排（调 `POST .../reorder`）

4. **最近结果**
   - `recent_results` 列表

5. **关系图/脉络图**（待实现）
   - 显示 Folio 内 Slip 通过 Writ 形成的 DAG

**拖拽行为**（文件系统式）：
- Slip 拖到 Folio → `POST /portal-api/folios/{slug}/adopt`
- Slip 拖到另一个 Slip → `POST /portal-api/folios/from-slips`（创建新 Folio）
- Folio 内 Slip 重排 → `POST /portal-api/folios/{slug}/reorder`

### 8.4 侧栏（ClaudeSidebar）

**分区**：
1. **待收束** (pending) — Deed 在 settling 状态的 Slip
2. **进行中** (live) — Deed 在 running 状态的 Slip
3. **卷** (folios) — 活跃的 Folio
4. **最近** (recent) — 独立 Slip（不在 Folio 内）

**行为**：
- 可折叠（宽 ↔ 窄）
- 文本搜索过滤
- 点击项 → 路由到对应页面
- 定期刷新 或 WebSocket 驱动刷新

### 8.5 托盘（Tray）

- 案桌（首页）有一个全局托盘，每个 Folio 有一个 Folio 托盘
- 托盘装 Draft 对象
- Draft 统一淡出机制（过期渐隐）
- Folio 内新建 Draft 不离开 Folio

---

## 9. 视觉规范

### 调色板（已定义在 `styles.css`）
```
--portal-bg:      #f5f5f0    页面背景
--portal-shell:   #ecebe4    侧栏/次级表面
--portal-surface: #ffffff    卡片/内容区
--portal-accent:  #ae5630    主按钮/强调色
--portal-text:    #1a1a18    正文
--portal-muted:   #6b6a68    次要文字
```

### 字体
- 正文：system-ui 无衬线
- 标题：Georgia / Iowan Old Style（衬线，`.portal-serif`）
- 代码：SFMono / Menlo / Monaco

### 组件规格
- 大卡片圆角：`rounded-[1.35rem]`
- 按钮圆角：`rounded-xl`
- 阴影：`shadow-claude`（轻）/ `shadow-claude-strong`（重）
- 分割线：`border-[rgba(0,0,0,0.06)]`

### 动效
- DAG 节点：呼吸动画 1.8s ease-in-out（`.portal-flow-node`）
- DAG 连线：描边动画 1.35s linear（`.portal-flow-stroke`）
- 页面转场：Apple 原生 app 式层级推进/返回
- 对象拖拽：iOS 主屏幕式抓起/让位/吸附/归位

---

## 10. 现有代码结构

```
interfaces/portal/src/
├── App.jsx                     根组件
├── main.jsx                    入口
├── styles.css                  全局样式 + Tailwind
├── components/
│   ├── MockPortal.jsx          主 shell（当前含 mock 数据）
│   ├── ClaudeSidebar.jsx       侧栏
│   ├── SlipPage.jsx            Slip 页
│   ├── FolioPage.jsx           Folio 页
│   ├── Composer.jsx            输入框
│   ├── MessageThread.jsx       消息列表
│   └── ConversationDock.jsx    对话停靠区
└── lib/
    ├── api.js                  API 客户端
    └── format.js               格式化工具
```

### api.js 现状

已实现的 API 调用：
- `getSidebar`, `getSlip`, `getSlipMessages`, `getSlipResultFiles`
- `sendSlipMessage`, `rerunSlip`, `copySlip`, `takeOutSlip`
- `updateSlipStance`, `setSlipCadence`, `deleteSlipCadence`
- `getFolio`, `reorderFolio`

**需要新增的 API 调用**：
```javascript
// Slip DAG 导航
export function getSlipWritNeighbors(slug) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/writ-neighbors`);
}

// Folio 收入 Slip
export function adoptSlipToFolio(folioSlug, slipSlug) {
  return request(`/portal-api/folios/${encodeURIComponent(folioSlug)}/adopt`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ slip_slug: slipSlug }),
  });
}

// 两张 Slip 合成 Folio
export function createFolioFromSlips(sourceSlug, targetSlug) {
  return request(`/portal-api/folios/from-slips`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ source_slug: sourceSlug, target_slug: targetSlug }),
  });
}

// Voice 对话
export function createVoiceSession() {
  return request("/voice/session", { method: "POST" });
}

export function sendVoiceMessage(sessionId, message) {
  return request(`/voice/${encodeURIComponent(sessionId)}`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ message }),
  });
}

// 反馈
export function getSlipFeedbackState(slug) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/feedback/state`);
}

export function submitSlipFeedback(slug, feedback) {
  return request(`/portal-api/slips/${encodeURIComponent(slug)}/feedback`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(feedback),
  });
}
```

同时在 `friendlyError` 中添加新增的错误处理：
```javascript
if (text.includes("writ_precondition_unmet")) return "前置任务未完成，暂时无法执行。";
```

---

## 11. 开发优先级建议

### P0：核心体验
1. **Slip 页面**完善：trigger_type 按钮区、Deed 列表、plan card
2. **Deed 页面**：从 Slip 进入执行详情，DAG 进度，对话，收束
3. **WebSocket 接入**：实时消息、进度、状态变更
4. **消息渲染**：区分 user/assistant/system/operation

### P1：组织体验
5. **Folio 页面**完善：结构视图 + 内联操作区
6. **拖拽操作**：Slip 入卷、出卷、合成卷、重排
7. **DAG 导航**：Slip 页面的 prev/next 导航
8. **侧栏**：WebSocket 驱动刷新

### P2：创建与草稿
9. **Voice 对话入口**：新建任务的自然语言界面
10. **Draft 托盘**：草稿管理
11. **搜索**

---

## 12. 错误处理

API 错误格式统一：HTTP 状态码 + `detail` 字段。

| 状态码 | 常见 detail | 含义 |
|--------|-----------|------|
| 400 | `message_required`, `invalid_stance_target` | 参数错误 |
| 404 | `slip_not_found`, `folio_not_found` | 对象不存在 |
| 409 | `slip_rerun_failed`, `writ_precondition_unmet:...` | 状态冲突 |
| 503 | `temporal_unavailable` | 执行引擎不可用 |

`api.js` 的 `friendlyError` 已经做了翻译，保持这个模式。

---

## 13. 术语对照速查

| 代码/API | 中文显示 | 说明 |
|----------|---------|------|
| slip | 签札 | |
| folio | 卷 | |
| deed | 行事 | |
| draft | 草稿 | |
| writ | 成文 | |
| running | 执行中 | deed 状态 |
| settling | 待收束 | deed 状态 |
| closed | 已冻结 | deed 状态 |
| active | 在场 | slip/folio 状态 |
| archived | 归档 | slip/folio 状态 |
| parked | 暂放 | sub_status |
| offering | 产物 | deed 执行结果 |
| cadence | 时钟 | 定时机制 |
| stance | 姿态 | slip 的状态变更 |
| manual | 手动触发 | trigger_type |
| timer | 定时触发 | trigger_type |
| writ_chain | 前序事件触发 | trigger_type |

---

## 14. 权威文档索引

遇到设计疑问时查阅（优先级从高到低）：

1. `.ref/TERMINOLOGY.md` — 术语规范
2. `.ref/INTERACTION_DESIGN.md` — 交互设计
3. `.ref/DESIGN_QA.md` — 设计决策 Q&A
4. `.ref/EXECUTION_MODEL.md` — 执行模型
5. `.ref/daemon_实施方案.md` — 实施规范
