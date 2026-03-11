# OpenClaw 文档参考（本地缓存）

> 来源：docs.openclaw.ai + github.com/openclaw/openclaw，抓取日期 2026-03-11
> 用途：避免每次审计/重构都要上网查 OC 机制
> 获取方式：文档站不全时直接从 GitHub 仓库 `openclaw/openclaw` 的 `docs/` 和 `src/` 拿

---

## 1. Memory 系统

来源：`/concepts/memory`

### 1.1 核心架构

Memory 以 **plain Markdown 文件** 存储在 agent workspace。模型只保留写到磁盘上的内容。

### 1.2 文件结构

- **Daily Logs** (`memory/YYYY-MM-DD.md`)：append-only，每日笔记
  - Session 启动时加载今天和昨天的日志
  - 位于 workspace 目录（默认 `~/.openclaw/workspace`）

- **Long-term Memory** (`MEMORY.md`)：持久事实和偏好
  - **"Only load in the main, private session"** — 不在 group context 中暴露
  - 可选文件，用于跨 session 持久化信息

### 1.3 Memory 访问工具

**memory_search**：语义搜索 Markdown 文件中的索引文本片段。返回结果上限约 700 字符，含文件路径和行范围。搜索范围：`MEMORY.md` + `memory/**/*.md`，chunk 大小约 400 token，80 token overlap。

**memory_get**：读取特定 memory Markdown 文件（workspace 相对路径），可选起始行和行数。路径限制在 `MEMORY.md` 和 `memory/` 内。文件不存在时优雅降级返回空内容。

**两个工具仅在 `memorySearch.enabled` 为 true 时可用。**

### 1.4 写入 Memory

**没有 `memory_write` 工具。** 模型通过文件写工具（write/edit）写入 memory 文件。

写入建议：
- 决策、偏好、持久事实 → `MEMORY.md`
- 日常上下文和笔记 → `memory/YYYY-MM-DD.md`
- 用户要求记住的 → 立即写入磁盘

### 1.5 Compaction 前自动 Memory Flush

Session 接近 context 限制时，OC 触发 "silent, agentic turn" 提醒模型保存持久记忆。

配置：`agents.defaults.compaction.memoryFlush`
- 触发条件：token 估算超过 `contextWindow - reserveTokensFloor - softThresholdTokens`
- 需要可写 workspace（`workspaceAccess` 为 `"ro"` 或 `"none"` 时跳过）
- 每个 compaction 周期一次，在 `sessions.json` 中追踪

### 1.6 向量搜索

OC 对 memory 文件构建小型向量索引。

- 默认启用，监视 memory 文件变化（debounce 1.5s）
- 配置在 `agents.defaults.memorySearch`
- 自动选择 embedding provider：local > OpenAI > Gemini > Voyage > Mistral；无可用时禁用
- 存储：per-agent SQLite at `~/.openclaw/memory/<agentId>.sqlite`

### 1.7 混合搜索（BM25 + Vector）

向量相似度 + BM25 关键词搜索，加权合并：
`finalScore = vectorWeight * vectorScore + textWeight * textScore`

默认权重：vector 0.7, text 0.3

### 1.8 MMR 重排序

Maximal Marginal Relevance 减少冗余结果：
`λ × relevance − (1−λ) × max_similarity_to_selected`
默认 λ = 0.7

### 1.9 时间衰减

指数衰减：`decayedScore = score × e^(-λ × ageInDays)`
- 默认半衰期 30 天
- `MEMORY.md` 和非日期文件不衰减
- Daily 文件从文件名提取日期

### 1.10 Session Memory Search（实验性）

可选索引 session transcript：
```json
{
  "experimental": { "sessionMemory": true },
  "sources": ["memory", "sessions"]
}
```
- 默认关闭，异步索引，结果可能略有延迟
- `memory_get` 仍限于 memory 文件
- 每 agent 隔离

---

## 2. Sub-Agents

来源：`/tools/subagents`

### 2.1 核心概念

Sub-agents 是从活跃 session 生成的后台进程，独立运行并将结果报告给请求者。运行在隔离 session 中：`agent:<agentId>:subagent:<uuid>`。

### 2.2 工具访问

Sub-agents 获得所有工具 **除了 session 管理工具**（`sessions_list`, `sessions_history`, `sessions_send`, `sessions_spawn`）。

**关键补充（来自源码确认）**：`SUBAGENT_TOOL_DENY_ALWAYS` 还包含 `memory_search` 和 `memory_get`。即 **sub-agent 不能读写 memory**。

### 2.3 嵌套深度

- 默认 `maxSpawnDepth: 1`（不可嵌套）
- 启用 `maxSpawnDepth: 2` 支持编排器模式：depth-1 sub-agent 可以 spawn workers
- 最大嵌套 5 层（推荐 2 层）

### 2.4 并发限制

- 每 session 活跃子进程：`maxChildrenPerAgent`（默认 5）
- 全局并发：`maxConcurrent`（默认 8）
- 自动归档：`archiveAfterMinutes`（默认 60）

### 2.5 认证与隔离

认证通过 agent ID 解析，从该 agent 目录加载 profile，以主 agent profile 为 fallback。Session 通过独立 context scoping 隔离。

---

## 3. Agent Runtime

来源：`/concepts/agent`

### 3.1 运行时架构

基于 **pi-mono** 的单一嵌入式 agent runtime。需要 workspace 目录作为工作环境。

启动时注入 bootstrap 文件：AGENTS.md, SOUL.md, TOOLS.md 等。

### 3.2 内置工具

核心 read/exec/edit/write 始终可用。

### 3.3 Session 存储

JSONL 格式，位于 `~/.openclaw/agents/<agentId>/sessions/`

### 3.4 流式模式

支持 "steer", "followup", "collect" 队列模式。

---

## 4. Agent Loop

来源：`/concepts/agent-loop`

### 4.1 执行流程

intake → context assembly → model inference → tool execution → streaming replies → persistence

### 4.2 并发控制

**"Runs are serialized per session key (session lane) and optionally through a global lane"** — 防止竞争条件。

同一 session 内的 run 是串行的。

### 4.3 Hook 系统

- 内部 Gateway hooks：`agent:bootstrap`
- Plugin hooks：`before_model_resolve`, `before_prompt_build`, tool execution, message phases

### 4.4 超时

- 默认 wait timeout：30 秒
- Agent runtime 默认：600 秒

---

## 5. Context 管理

来源：`/concepts/context`

### 5.1 Context 组成

系统 prompt 包含：tool descriptions, skills metadata, workspace location, timestamps, 注入的 bootstrap 文件。

### 5.2 Workspace 文件注入

自动注入：AGENTS.md, SOUL.md, TOOLS.md, IDENTITY.md, USER.md, HEARTBEAT.md, BOOTSTRAP.md
- 单文件上限：`bootstrapMaxChars`（默认 20,000）
- 总 bootstrap 上限：150,000 字符

### 5.3 Compaction

接近 context window 阈值时自动激活，生成摘要。
- `/compact` 手动触发
- Compaction 前可执行 memory flush

---

## 6. Agent Workspace

来源：`/concepts/agent-workspace`

### 6.1 标准文件结构

```
workspace/
├── AGENTS.md          # 操作指令和行为准则
├── SOUL.md            # 人格、语气、边界
├── USER.md            # 用户身份和通讯偏好
├── IDENTITY.md        # Agent 名称和角色（自动生成）
├── TOOLS.md           # 本地工具文档
├── HEARTBEAT.md       # （可选）自动心跳检查清单
├── BOOT.md            # （可选）Gateway 重启程序
├── BOOTSTRAP.md       # （一次性）新 workspace 初始化
├── MEMORY.md          # （可选）长期记忆
├── memory/
│   └── YYYY-MM-DD.md  # 每日记忆日志
├── skills/            # （可选）workspace 级 skill 覆盖
└── canvas/            # （可选）Node UI 文件
```

Workspace 与 `~/.openclaw/` 分离。后者存储 config、credentials、sessions。

---

## 7. Multi-Agent Routing

来源：`/concepts/multi-agent`

### 7.1 隔离

每个 agent 维护完全隔离：独立 workspace、state 目录、session 存储。

**"Never reuse `agentDir` across agents (it causes auth/session collisions)."**

### 7.2 路由

按 binding 匹配：peer identity > parent peer > guild+role > guild > team > account > channel > default。最具体优先。

---

## 8. Compaction

来源：`/concepts/compaction`

"Summarizes older conversation into a compact summary entry and keeps recent messages intact."

- 自动触发：接近 model token 限制
- 手动触发：`/compact [instructions]`
- 摘要持久化到 session JSONL 历史

与 session pruning 区别：
- Compaction = 持久摘要写入 session 文件
- Pruning = 仅内存中裁剪旧 tool results，不改 session 文件

---

## 9. Session Pruning

来源：`/concepts/session-pruning`

移除旧 tool results（仅内存中），不动磁盘 session 历史。

- 模式：`cache-ttl`（基于 Anthropic API 缓存 TTL）
- 仅影响 `toolResult` 消息
- User 和 assistant 消息不裁剪
- 含图片的 tool results 始终保留

---

## 10. Sandboxing

来源：`/gateway/sandboxing`

Docker 容器隔离（可选）。

- `mode: "off" | "non-main" | "all"`
- `scope: "session" | "agent" | "shared"`
- `workspaceAccess: "none" | "ro" | "rw"`

**与 subagent tool deny 是两套机制。** Sandbox 控制 Docker 隔离，tool policy 控制工具可见性。

---

## 11. Gateway Protocol

来源：`/gateway/protocol`

WebSocket 协议，JSON 帧。

帧类型：
- Request：`{type:"req", id, method, params}`
- Response：`{type:"res", id, ok, payload|error}`
- Event：`{type:"event", event, payload, seq?, stateVersion?}`

---

## 12. Session Tools（完整参数定义）

来源：GitHub `docs/concepts/session-tool.md` + `src/agents/tools/sessions-spawn-tool.ts` + `src/agents/tools/sessions-send-tool.ts`

### 12.1 sessions_spawn

创建隔离 session 并在完成后向请求者通知结果。

**参数**：
- `task` (required)：任务描述
- `label?`：日志/UI 标签
- `runtime?`：`"subagent"` | `"acp"`（默认 subagent）
- `agentId?`：在其它 agent 下 spawn（需 allowlist 许可）
- `resumeSessionId?`：恢复已有 session（仅 `runtime="acp"`）
- `model?`：覆盖模型
- `thinking?`：覆盖思考级别
- `runTimeoutSeconds?`：超时秒数（默认由 config 决定，`0` = 无限）
- `thread?`：(default false) 请求 thread-bound 路由
- `mode?`：`"run"` | `"session"`（默认 `"run"`；`thread=true` 时默认 `"session"`；`"session"` 要求 `thread=true`）
- `cleanup?`：`"delete"` | `"keep"`（默认 `"keep"`）
- `sandbox?`：`"inherit"` | `"require"`（默认 `"inherit"`）
- `streamTo?`：`"parent"`（仅 `runtime="acp"`）
- `attachments?`：内联文件数组（仅 subagent runtime），每项 `{ name, content, encoding?, mimeType? }`，最多 50 个
- `attachAs?`：`{ mountPath? }` 提示

**行为**：
- **非阻塞**：立即返回 `{ status: "accepted", runId, childSessionKey }`
- Session key 格式：`agent:<agentId>:subagent:<uuid>`
- Sub-agent 获得完整工具集 **减去 session 工具**（可通过 `tools.subagents.tools` 配置）
- 不允许 sub-agent → sub-agent spawning（默认 depth 1）
- 完成后执行 announce step，向请求者 chat 通道发送结果
- 自动归档：`archiveAfterMinutes`（默认 60）

**Allowlist**：`agents.list[].subagents.allowAgents`（`["*"]` 允许所有）

### 12.2 sessions_send

向另一个 session 发送消息。

**参数**：
- `sessionKey?`：目标 session key 或 sessionId
- `label?`：按标签查找 session
- `agentId?`：配合 label 定位特定 agent 的 session
- `message` (required)：消息内容
- `timeoutSeconds?`：等待超时（`0` = fire-and-forget）

**行为**：
- `timeoutSeconds = 0`：入队返回 `{ runId, status: "accepted" }`
- `timeoutSeconds > 0`：等待完成返回 `{ runId, status: "ok", reply }`
- 超时：`{ runId, status: "timeout", error }`（run 继续，稍后用 `sessions_history` 查看）
- 失败：`{ runId, status: "error", error }`
- 消息标记 `message.provenance.kind = "inter_session"`
- **Reply-back loop**：完成后在请求者和目标间交替，`REPLY_SKIP` 停止，最多 `maxPingPongTurns` 轮（默认 5）
- **Announce step**：目标 agent 可发送通知到目标 channel

### 12.3 sessions_list

列出 session。

**参数**：
- `kinds?`：过滤类型 `"main" | "group" | "cron" | "hook" | "node" | "other"`
- `limit?`：最大行数
- `activeMinutes?`：仅 N 分钟内活跃的 session
- `messageLimit?`：0 = 不含消息（默认），>0 = 包含最近 N 条

### 12.4 sessions_history

获取 session 对话记录。

**参数**：
- `sessionKey` (required)：session key 或 sessionId
- `limit?`：最大消息数
- `includeTools?`：(default false) 是否包含 toolResult 消息

### 12.5 Session 可见性

- `tools.sessions.visibility`：`"self"` | `"tree"` | `"agent"` | `"all"`（默认 `"tree"`）
  - `self`：仅当前 session
  - `tree`：当前 + 从当前 spawn 的子 session
  - `agent`：同 agent 的所有 session
  - `all`：跨 agent（需 `tools.agentToAgent`）
- Sandbox 模式下 `sessionToolsVisibility` 可强制降级

### 12.6 Send Policy

基于 channel/chatType 的策略阻断（不是 per session id）：
```json
{
  "session": {
    "sendPolicy": {
      "rules": [{ "match": { "channel": "discord", "chatType": "group" }, "action": "deny" }],
      "default": "allow"
    }
  }
}
```

---

## 13. Subagent Tool Policy（源码确认）

来源：GitHub `src/agents/pi-tools.policy.ts`

### 13.1 SUBAGENT_TOOL_DENY_ALWAYS

**所有深度的 subagent 都被禁止的工具**：
```
gateway          # 系统管理
agents_list      # agent 发现
whatsapp_login   # 交互式登录
session_status   # 状态查询
cron             # 定时任务
memory_search    # 记忆搜索 ← 关键！
memory_get       # 记忆读取 ← 关键！
sessions_send    # 跨 session 发送 ← 关键！
```

### 13.2 SUBAGENT_TOOL_DENY_LEAF

**叶子 subagent（depth >= maxSpawnDepth）额外禁止**：
```
sessions_list
sessions_history
sessions_spawn
```

### 13.3 Orchestrator vs Leaf

- **Orchestrator**（depth 1, maxSpawnDepth >= 2）：可用 sessions_spawn/list/history 管理子 worker
- **Leaf**（depth >= maxSpawnDepth）：被禁止所有 session 工具 + always deny 列表

### 13.4 Tool Policy 配置覆盖

通过 `tools.subagents.tools` 配置可覆盖默认 deny：
- `allow`：白名单
- `alsoAllow`：追加白名单
- `deny`：追加黑名单
- `explicitAllow` 中的工具会从 `baseDeny` 中移除

---

## 14. 关键结论汇总（与 Daemon 重构直接相关）

1. **MEMORY.md 仅在 main private session 加载**，subagent 不加载
2. **Subagent 不能使用 memory_search/memory_get**（SUBAGENT_TOOL_DENY_ALWAYS，源码确认）
3. **Subagent 不能使用 sessions_send**（SUBAGENT_TOOL_DENY_ALWAYS，源码确认）
4. **没有 memory_write 工具**，模型通过 file write 工具写 memory
5. **同 session 内 run 串行执行**（session lane serialization）
6. **Compaction 前自动 memory flush**（full session only）
7. **向量索引** per-agent at `~/.openclaw/memory/<agentId>.sqlite`
8. **Leaf subagent 无法访问任何 session 工具**（sessions_spawn/send/list/history 全部被禁）
9. **Subagent 默认 maxSpawnDepth: 1**（叶子节点），不可嵌套
10. **每 session 最多 5 个子 agent，全局最多 8 个并发**
11. **Session 归档**：`archiveAfterMinutes` 默认 60 分钟
12. **sessions_spawn 是非阻塞的**：立即返回 runId，通过 announce 通知结果
13. **sessions_send 支持同步等待**：`timeoutSeconds > 0` 时等待完成返回 reply
14. **sessions_spawn cleanup 默认 "keep"**：不自动清理子 session → 我们的 session 泄漏来源
15. **Tool policy 可配置覆盖**：通过 `tools.subagents.tools.alsoAllow` 可把 memory_search 等加回来（但我们选择不这样做，走 persistent session 路线）
