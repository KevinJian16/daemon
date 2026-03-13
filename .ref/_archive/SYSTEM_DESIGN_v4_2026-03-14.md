# Daemon 系统设计总纲

> **状态**：四稿（全量审计 + 大幅精简）
> **日期**：2026-03-13
> **定位**：daemon 系统的唯一权威设计文档。所有设计决策、术语、机制规则以本文档为准。
> **合并来源**：TERMINOLOGY.md, DESIGN_QA.md, INTERACTION_DESIGN.md, EXECUTION_MODEL.md, daemon_实施方案.md, README.md, OPEN_SOURCE_REPLACEMENT_PLAN.md, REFACTOR_KNOWLEDGE_AND_WARMUP.md

---

## §0 治理规则

### 0.1 本文档的权威性

本文档是 daemon 系统设计的唯一权威来源。原有六份设计文档（TERMINOLOGY.md, DESIGN_QA.md, INTERACTION_DESIGN.md, EXECUTION_MODEL.md, daemon_实施方案.md, README.md）仍保留在 `.ref/` 中供参考，但不再具有权威性。

如有冲突，以本文档为准。

### 0.2 术语原则

- 一个术语只有一个含义，系统内不存在同义词
- 代码、存储、API 使用英文 canonical name
- 用户界面使用中文显示名
- 术语变更必须先更新本文档，再改代码

### 0.3 双层系统

daemon 是双层系统，两层必须同步更新：

1. **Python 层**：services/, temporal/, runtime/
2. **OpenClaw agent 层**：openclaw/workspace/\*/TOOLS.md, skills/\*/SKILL.md, openclaw.json

openclaw/ 不在 git 中（含 API key），但它是代码库的一部分。每次改代码都必须检查两层。

### 0.4 工作原则

- **认真读文档，认真读代码，认真写代码，认真写文档。不图快，不自以为是。**
- **有现成的就用现成的，不原创。**
- 审计时必须做链路追踪（源头→传输→终点→消费），不能只看函数存在就标通过。
- 跨系统边界必查外部文档。

### 0.5 高风险陷阱

1. **只验结构不验行为**——函数存在 ≠ 数据流通。必须验证完整链路。
2. **修了一环就标已修**——下游必须全部通畅才算修好。
3. **假设外部系统行为**——去查文档确认，不猜。
4. **文档和代码不同步**——改一个必须改另一个。

---

## §1 术语表

> **四稿精简原则（2026-03-13）**：删除所有自造隐喻术语，只用业界通用术语。
> 能用一个现成概念说清的，不造新词。

### 1.1 三个正式对象

| 英文 | 定义 | Plane 映射 |
|---|---|---|
| **Project** | Task 的组织容器。项目/主题级 | Plane Project / Module |
| **Task** | 核心工作单元 | Plane Issue |
| **Job** | Task 的一次执行记录。daemon 自管生命周期 | 无映射，daemon PG + Temporal |

Draft 不是独立对象——直接使用 Plane DraftIssue，转换为 Issue 即可。

层次关系：
```
Project（目标 + 任务分解）
  └─ Task（工作单元，Plane Issue，Task 间依赖用 Plane IssueRelation）
       └─ Job（Task 的一次运行实例，daemon 自管）
            └─ Step（1 目标，可调用任意 agent/tool）
```

边界规则：
- Task 和 Project 的状态、CRUD、依赖关系全部由 Plane 管理。daemon 不维护自己的状态层。
- Job 是 daemon 自管对象（Plane 没有等价物），生命周期由 Temporal Workflow 管理。
- Task 间依赖用 Plane `IssueRelation(blocked_by)` + Temporal Schedule（定时触发），不是独立实体。

### 1.2 状态模型

**只有 Job 有 daemon 自管状态。** Task 和 Project 直接用 Plane 的状态组（backlog / unstarted / started / completed / cancelled）。

**Job 状态：**

| 主状态 | sub_status | 说明 |
|---|---|---|
| running | queued | 排队等待 |
| running | executing | 正在执行 |
| running | paused | 暂停（等待人工 review） |
| running | retrying | 重试中 |
| closed | succeeded | 成功 |
| closed | failed | 失败 |
| closed | cancelled | 取消 |

> **三稿 → 四稿变更**：删除 settling 状态。Job 完成后默认直接 closed(succeeded)，不等人。
> 需要人工审查时，counsel 在规划时标记 `requires_review: true`，Job 进入 paused 等待 Temporal Signal。
> 删除 timed_out 子状态（不需要超时自动关闭，由 Temporal Workflow timeout 处理）。

### 1.3 执行层术语

| 英文 | 定义 |
|---|---|
| **Step** | Job DAG 中的一步。1 Step = 1 目标（可调用任意 agent 和 tool） |
| **Artifact** | Job 执行的交付物（通用 CI/CD 术语） |

> **三稿 → 四稿变更**：
> - Step 从"1 Agent + 1 交付物"改为"1 目标"。agent 和 tool 选择由 step 内部决定。
> - Offering → **Artifact**（CI/CD 通用术语）
> - 删除 Context（Job 执行规格直接是 Temporal Workflow input，不需要独立名字）
> - 删除 Design（DAG 结构就是 JSON，不需要独立名字）
> - 删除 Retinue（agent 列表就是 agent 列表）

### 1.4 Agent 角色

| 英文 | 职责 | 默认模型 | Mem0 积累内容 |
|---|---|---|---|
| **counsel** | 用户对话、路由决策、Job DAG 规划、Replan Gate | routing 用 fast，项目级规划用 analysis | 规划经验、DAG 结构偏好 |
| **scholar** | 搜索 + 分析 + 推理一体（外部信息获取、RAGFlow 检索、深度分析、方案论证） | analysis | 信源可靠性、搜索策略、分析框架 |
| **artificer** | 编码与技术任务（实现功能、调试、工具链） | fast | 代码风格、技术决策偏好 |
| **scribe** | 写作与内容生产（论文、文章、报告、对外文本） | creative | 写作风格、格式偏好 |
| **arbiter** | 质量审查（事实校验、逻辑一致性、风格合规） | review | 质量标准、常见失败模式 |
| **envoy** | 对外出口（发布产出、GitHub、Telegram 通知） | fast | 各平台格式规范 |
| **steward** | 系统自维护（暖机主导、周度体检、skill 管理、诊断告警） | analysis | 系统基线、体检历史、参数校准记录 |

**各 agent 独立配置**：每个 agent 有独立的 OC workspace、TOOLS.md、Mem0 memory bucket（`agent_id` 隔离）。记忆、工具、人格不混用。

**counsel 规划时指定 `agent` + 可选 `model` override**：
```json
{"id": 3, "goal": "write literature review", "agent": "scribe", "depends_on": [1, 2]}
{"id": 4, "goal": "verify key claims", "agent": "arbiter", "depends_on": [3]}
```
`model` 字段省略时使用 agent 默认模型；指定时通过 OC `sessions_spawn model?` 参数覆盖。

> **架构修订（2026-03-14）**：scout + sage 合并为 **scholar**。搜索与分析是一个连续认知动作，分拆为两个 agent 会在 session 边界产生不必要的信息损耗。新增 **steward** 专职系统自维护，将暖机主导、周度体检、skill 管理从 counsel 分离出来。counsel 职责收窄为纯用户任务规划。

### 1.5 知识与配额

| 英文 | 定义 | 承载 |
|---|---|---|
| **Guardrails** | 系统硬规则，不依赖 LLM，不可被用户覆盖 | NeMo Guardrails（Colang DSL） |
| **Persona** | AI 人格 + 用户偏好 | Mem0（按需检索） |
| **Quota** | 资源配额（token 预算、并发限制） | OC 原生 + Langfuse |
| **Knowledge Base** | 外部知识缓存 | RAGFlow + PG knowledge_cache |

> **三稿 → 四稿变更**：
> - 删除 Psyche umbrella term（没有实际意义）
> - Instinct → **Guardrails**（NeMo 已经叫这个名字）
> - Voice + Preferences → **Persona**（业界通用）
> - Rations → **Quota**
> - Ledger → 删（Langfuse + PG 自动处理，不需要独立名字）
> - SourceCache → **Knowledge Base**

### 1.6 基础设施

| 英文 | 说明 |
|---|---|
| **Plane** | 开源任务管理平台。Task/Project CRUD + 前端 + 管理界面 |
| **Temporal** | Workflow 编排 + Schedules（定时调度） |
| **Langfuse** | LLM 可观测性（追踪 + 统计 + 评估） |
| **MinIO** | S3 兼容对象存储 |
| **RAGFlow** | 文档解析 + 分块 + 向量检索 |
| **Mem0** | 统一记忆层（persona + 规划经验 + 对话记忆） |
| **NeMo Guardrails** | 安全规则引擎（Colang DSL，零 token） |
| **pgvector** | PostgreSQL 向量搜索扩展 |
| **PG LISTEN/NOTIFY** | PostgreSQL 原生事件通知 |

### 1.7 系统维护

一个定时清理 Job（Temporal Schedule）：
- 清理 knowledge_cache 过期条目（同步删除 RAGFlow 文档）
- 清理 Mem0 中 90 天未触发的记忆（标记候选，用户确认后删除）
- Quota reset

> **三稿 → 四稿变更**：
> - 删除 Spine / Nerve / Cortex / Ward / Canon（过度隐喻）
> - 7 个 Spine routines → 1 个定时清理 Job
> - pulse（健康检查）→ Docker healthcheck + Temporal 心跳
> - record / witness / relay → Langfuse + PG 自动记录
> - focus → Plane 优先级
> - curate → Mem0 自动管理

### 1.8 废弃术语

| 旧术语 | 替代 | 说明 |
|---|---|---|
| Folio / Slip / Writ / Deed / Move / Brief / Wash | Project / Task / (删除) / Job / Step / (删除) / (删除) | 三稿术语对齐 |
| Draft（daemon 自管） | Plane DraftIssue | 四稿：不自管，用 Plane 原生 |
| Trigger（一等实体） | Plane IssueRelation + Temporal Schedule | 四稿：降级为组合实现 |
| Offering | Artifact | 四稿：用 CI/CD 通用术语 |
| Retinue / Context / Design | 删除 | 四稿：不需要独立名字 |
| Psyche / Instinct / Voice / Preferences / Rations / Ledger / SourceCache | Guardrails / Persona / Quota / (Langfuse) / Knowledge Base | 四稿：用通用术语 |
| Spine / Nerve / Cortex / Ward / Canon | 删除 | 四稿：过度隐喻 |
| scout / sage | scholar（合并）| 2026-03-14：搜索+分析是一个认知动作，分拆增加信息损耗 |
| steward | 新增，见 §1.4 | 2026-03-14：系统自维护从 counsel 分离 |
| artificer / scribe / arbiter / envoy | 保留，见 §1.4 | 四稿曾合并为 worker，已恢复 |
| Herald / Cadence / Ether / Trail / Portal / Console / Vault / Memory / Lore | 见三稿 | 已废弃 |
| errand / charge / endeavor / glance / study / scrutiny / Pact | 删除 | 已废弃 |

---

## §2 系统架构

### 2.1 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户界面                                   │
│  Plane 前端（React + TypeScript + Tailwind + MobX）              │
│  + 自定义 Job 实时面板（WebSocket，Plane 不提供）                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                     Plane Django API                              │
│  Issue(Task) / Project(Project) / DraftIssue(Draft)              │
│  IssueRelation(Trigger) / Webhook → daemon                       │
│  + 薄 FastAPI 胶水层（Job 实时 WebSocket）                         │
└──────────┬────────────────────────────┬─────────────────────────┘
           │                            │
┌──────────▼──────────┐      ┌──────────▼──────────────────────┐
│    PostgreSQL        │      │   Temporal Server                │
│  + pgvector          │      │   Schedules（定时调度）           │
│  + LISTEN/NOTIFY     │      │   Workflows + Activities          │
│  + knowledge_cache   │      │   （执行 + OC 调用）               │
│    (TTL 管理)        │      └──────────┬─────────────────────┘
└──────────────────────┘                 │
                              ┌──────────▼──────────────────────┐
                              │   OpenClaw Agents                │
                              │   7 agents × persistent session  │
                              │   + NeMo Guardrails（嵌入进程）   │
                              │   + Mem0（嵌入进程）              │
                              └──────────┬──────────────────────┘
                                         │
           ┌─────────────────────────────┼───────────────────┐
           │                             │                   │
┌──────────▼──────┐  ┌──────────────────▼───┐  ┌───────────▼──────┐
│  RAGFlow         │  │  MinIO                │  │  Langfuse         │
│  (文档解析+检索)  │  │  (文件存储)            │  │  (LLM 追踪)       │
│  + Elasticsearch │  │  Plane/Langfuse 共用   │  │  + ClickHouse     │
└─────────────────┘  └──────────────────────┘  └──────────────────┘

MCP Tools（零 token 能力扩展）：
  Firecrawl(网页全文) / Semantic Scholar(学术搜索) / tree-sitter(代码索引)
  GitHub MCP / Telegram OC channel / LaTeX+BibTeX / matplotlib+mermaid
```

### 2.2 进程模型

| 进程 | 技术栈 | 职责 |
|---|---|---|
| **API 进程** | FastAPI | 胶水层：Plane webhook handler、Job 实时 WebSocket |
| **Worker 进程** | Temporal Worker | 执行：Activities（调 OC agent、写 Plane API、写 PG）、定时清理 Job、NeMo Guardrails、Mem0 |
| **OC Gateway** | OpenClaw | Agent 编排：7 agents（counsel/scholar/artificer/scribe/arbiter/envoy/steward）、session 管理、MCP 分发 |
| **RAGFlow** | Docker 服务 | 文档解析、分块、向量检索 |

两个 Python 进程不直接通信，通过 Temporal workflow + PG 协作。NeMo Guardrails 和 Mem0 作为 Python 库嵌入 Worker 进程。

### 2.3 Plane 对象映射

| daemon 概念 | Plane 映射 | 适配度 | 说明 |
|---|---|---|---|
| Draft | DraftIssue | 好 | Plane 有独立 DraftIssue 模型 |
| Task | Issue | 好 | 核心工作单元直接映射 |
| Project | Plane Project 或 Module | 好 | 直接映射 |
| Task 依赖 | IssueRelation(blocked_by) | 好 | Plane 原生支持 |
| Job | **无映射，需自建** | 无 | Job 数据在 daemon PG 表 + Temporal workflow history |

### 2.4 外部出口分工

| 出口 | 通道 | 说明 |
|---|---|---|
| Telegram | OC 原生 channel（announce） | envoy 直接通过 OC 平台发送 |
| GitHub | MCP server（@modelcontextprotocol/server-github） | envoy 通过 MCP 工具调用 |
| 其他 API | 按需加 MCP server | OC 原生不支持的才用 MCP |

**原则**：OC 原生支持的出口用 OC channel，不支持的才用 MCP server。envoy 是唯一对外出口 agent。

### 2.5 外部知识获取

| 组件 | 说明 |
|---|---|
| 搜索 MCP servers | scholar 通过 MCP 工具搜索外部信息（通用搜索 + Semantic Scholar 学术搜索） |
| Playwright MCP | 浏览器自动化（需要登录、JS 渲染、点击交互的页面）。scholar 在 Firecrawl 无法处理时使用 |
| Firecrawl | 网页 → 干净 Markdown（去 HTML 噪音，省 80%+ token），自部署 Docker。优先于 Playwright |
| RAGFlow | PDF/文档全文解析 → 语义分块 → 向量检索。论文写作必需（表格/图表/公式理解） |
| knowledge_cache（PG） | TTL 过期管理。按 source_tiers.toml 分级（A=90天, B=30天, C=7天） |
| source_tiers.toml | 外部源信任分级（A/B/C），NeMo Guardrails 规则依赖 |
| sensitive_terms.json | 隐私过滤，NeMo Guardrails input rail 执行 |

**知识获取流程**：
```
scholar → MCP search / Semantic Scholar → URL + 摘要
  ↓ 需要全文时
  ├── PDF → RAGFlow 解析/分块/存储
  └── 网页 → Firecrawl → 干净 Markdown → RAGFlow 或直接存 knowledge_cache
  ↓
其他 agent → RAGFlow 检索 / knowledge_cache 向量检索 → 精确命中
```

**内外分野**：
- **外部知识**：事实性的、可引用的、可验证的。来源 = MCP search → RAGFlow/knowledge_cache。有 source_url、source_tier。
- **内部知识**：个人化的、累积的。来源 = Mem0（agent memory）。塑造风格和方式，不塑造内容和事实。

### 2.6 模型策略

每个 agent 有默认模型。counsel 可在规划时通过 `model` 字段覆盖（OC `sessions_spawn model?`）：

| Agent | 默认模型 | 理由 |
|---|---|---|
| **counsel** | fast（routing）/ analysis（项目规划） | routing 快判断，DAG 设计需推理 |
| **scholar** | Qwen Max（analysis） | 搜索+深度分析，质量优先 |
| **artificer** | MiniMax M2.5（fast） | 编码通用，speed 优先 |
| **scribe** | GLM Z1 Flash（creative） | 写作创意，文风优先 |
| **arbiter** | Qwen Max（review） | 审查严谨，质量优先 |
| **envoy** | MiniMax M2.5（fast） | 发布动作，speed 优先 |
| **steward** | Qwen Max（analysis） | 系统评估需要判断力 |
| — | 智谱 embedding-3 | Embedding |

**模型标签对应**：fast = MiniMax M2.5，analysis = Qwen Max，creative = GLM Z1 Flash，review = Qwen Max。

**OC model override**：OC `sessions_spawn` 支持 `model?` 参数，counsel 规划时可按需覆盖任意 agent 的默认模型。

---

## §3 执行模型

> **理论背景**：本执行模型属于 HTN（Hierarchical Task Network）+ Orchestration 范式。
> 参考：LLMCompiler（Berkeley, DAG 并行执行）、GoalAct（全局规划+分层执行, NCIIP 2025 Best Paper）、
> Plan-and-Act（动态重规划, ICML 2025）、AgentOrchestra + TEA Protocol（层次化多 Agent, GAIA SOTA）。

### 3.1 Step 粒度

**1 Step = 1 目标。** 可调用任意 agent 和 tool。

Step 有四种执行类型：

| 类型 | 说明 | Token 成本 |
|---|---|---|
| `"agent"` | OC session，消耗 daemon API 预算 | 中-高 |
| `"direct"` | Python activity，零 LLM | 零 |
| `"claude_code"` | 本地 Claude Code CLI subprocess | 用户 Claude Code 额度 |
| `"codex"` | 本地 Codex CLI subprocess | 用户 Codex 额度 |

**direct step 覆盖范围**（凡是输出由输入完全决定的操作）：
- Shell 命令（git、npm、pip、任意 CLI）
- 本地应用控制（`open`、VS Code、Xcode 等）
- 浏览器打开（`webbrowser.open()`）
- 文件读写、格式转换、数据库查询
- API 调用（已知 endpoint + schema）
- 进程管理、端口检查

**claude_code / codex 适用场景**：
- `claude_code`：arbiter 审查对外发布内容、复杂 Project 初始规划、steward 自愈修复
- `codex`：artificer 遇到复杂实现时
- 两者均通过 Temporal Activity subprocess 调用，绕过 OC，不需要 session 管理
- 调用前 Activity 自动注入必要上下文（MEMORY.md 内容 + skill 内容），context 保持精准最小

#### 3.1.1 粒度原则

**context 窗口是 Step 粒度的硬上界，不是目标大小。**

Step 粒度遵循三条规则：

**规则一：能在一个 context 内完成的，不拆。**
每个 Step 边界都是信息损耗点——Step A 的产出必须压缩为 Artifact 摘要才能传给 Step B，压缩必然有损。Step 越少，摘要边界越少，信息损耗越小。counsel 应按**语义边界**分 Step（什么逻辑上属于一起），不按大小分。

**规则二：上界 = context 窗口 100%（减固定 overhead）。**
固定 overhead（MEMORY.md + Mem0 注入 + Step 指令）约 800 tokens，其余全部可用于任务。不人为预留缓冲——任务大小是变量，静态预留只会让缓冲永远闲置。溢出由运行时动态监测处理（见 §3.2 token 管控），不靠提前缩水。

**规则三：确定性操作用 direct，不用 agent。**
如果一个操作的输出完全由输入决定（文件读写、API 调用、格式转换），用 `direct`，零 token。LLM 只处理需要推理的部分。

### 3.2 Session 模型

**核心原则：1 Step = 1 Session。**

context 窗口大小 = 任务粒度上限。每个 Step 在全新 context 内完成，不积累前序 Step 的对话历史。串行/并行 Step 均独立 session，不共享。

- 7 个 OC agent，每个 1 个 instance（counsel / scholar / artificer / scribe / arbiter / envoy / steward）
- 每个 Step 执行时 `sessions_spawn` 创建独立 session，Step 完成后关闭
- Session key 格式：`{agent_id}:{job_id}:{step_id}`
- 并行 Step 各自独立 session，同时运行

**Session 内容构成**（每次 session 启动时注入，total ≤ 800 tokens）：
```
MEMORY.md（≤ 300 tokens，只放每次都必须的身份+最高优先级规则）
+ Mem0 按需检索（50-200 tokens，当前任务相关记忆）
+ Step 指令（结构化 JSON，目标明确）
+ 上游 Artifact 摘要（如有依赖，见 §3.6.1）
```

**Token 管控机制**（主动参与，不被动等 context 满）：

| 机制 | 配置 | 作用 |
|---|---|---|
| `runTimeoutSeconds` | 按 Step 类型设定（search: 60s, writing: 180s, review: 90s） | 硬超时，防止 agent 无限循环 |
| token budget 声明 | Step 指令中明确："请在 X tokens 内完成" | agent 自律收敛 |
| OC quota | `openclaw.json` 配置每 agent 的 token 日上限 | 防止单 agent 失控 |
| Langfuse 监控 | 单 Step token 消耗 > 阈值（按类型定）→ 告警 | 暖机后用于发现异常 Step |
| `contextPruning: cache-ttl` | 5 分钟 cache TTL | 裁剪旧 tool results，减少无效 context |
| `maxSpawnDepth` | 默认 1（leaf-only）；设为 2 启用 Step 内 subagent 并行 | 见下方 Subagent 并行模式 |
| `maxChildrenPerAgent` | 默认 5，可调高 | 每个 session 的最大并发子 agent 数 |
| `maxConcurrent` | 默认 8，可调高 | 全局并发 session 上限，按机器和 LLM rate limit 校准 |

**MEMORY.md 规则**：每个 agent 的 MEMORY.md ≤ 300 tokens。只放：身份定义 + 最高优先级行为规则。任务偏好、风格、规划经验全部放 Mem0，不放 MEMORY.md。MEMORY.md 是跨任务静态内容，任务执行期间不写入，不存在并行任务污染问题。

**OC 限制**：
- Subagent 不加载 MEMORY.md，不能读写 Mem0
- 不存在 memory_write tool
- Session-memory hook 仅在 `/new` 或 `/reset` 时触发

#### 3.2.1 Step 内 Subagent 并行模式

**不需要 agent 池。** 7 个 OC agent workspace，每个 workspace 可同时运行多个 session，并发度由 `maxChildrenPerAgent` / `maxConcurrent` 控制，暖机时校准。

agent 在执行 Step 时，可以通过 `sessions_spawn` 在 Step 内部并行处理子任务，而不需要 counsel 把它拆成多个 Step。这是 skill-based 模式：agent 自己决定是否并行，counsel 只负责 Step 级别的任务分解。

| 模式 | `maxSpawnDepth` | 行为 |
|---|---|---|
| Leaf（默认） | 1 | agent 不 spawn subagent，所有工具调用在主 session 内串行 |
| Orchestrator | 2 | agent 可 spawn subagent 并行处理子任务，自己作编排器 |

**Subagent 限制**：
- Subagent 不加载 MEMORY.md，不能读 Mem0 → 父 session 必须通过 `attachments` 或任务描述注入必要上下文
- 结果通过 announce step 异步回传父 session
- spawn 立即返回（非阻塞），父 session 等待 announce
- `cleanup: "delete"` 避免 session 泄漏（默认 `"keep"`）
- 最大嵌套 5 层，推荐不超过 2 层

### 3.3 Job 生命周期

```
创建 Job（= 原子操作：创建 + 立即执行）
  │
  ▼
running（sub: queued → executing）
  │ Step 按 DAG 依赖执行（无依赖的 Step 并行，见 §3.6）
  │ 如果 Step 失败 → retry / replan / terminate（见 §3.7）
  │ 如果超时 → failed
  ▼
closed（sub: succeeded / failed / cancelled）
  │ 默认直接 closed(succeeded)，不等人
  │ counsel 标记 requires_review: true 时 → running(paused)，等待 Temporal Signal
  ▼
Replan Gate（见 §3.5）→ 触发下游 Task
```

关键规则：
- 执行 = 原子操作。不存在"只创建不执行"。
- 同一 Task 同一时刻只有一个非 closed 的 Job。
- Step DAG 在 Job 创建时快照。Task DAG 变更不影响进行中的 Job。

#### 3.3.1 arbiter 触发策略

arbiter 不审查每个 Step（会使 token 翻倍且无必要）。三层分级：

| 层级 | 覆盖范围 | 机制 | Token 成本 |
|---|---|---|---|
| **1. 基础校验** | 所有 Step 输出 | NeMo Guardrails output rail 自动执行 | 零 |
| **2. 关键审查** | counsel 标记 `requires_review: true` 的 Step | arbiter session 独立审查 | 中 |
| **3. 对外强制审查** | 所有发布到外部平台的 Step | Guardrails 规则强制触发 arbiter | 中 |

**arbiter 独立性**是其存在的核心价值——与产出 agent 完全隔离，消除自我审批偏差。arbiter 的 Mem0 积累质量标准和常见失败模式，与生产 agent 的记忆完全分离。

### 3.4 Task 触发

Task 间依赖用 Plane `IssueRelation(blocked_by)` + Temporal Schedule 实现，不是独立实体。

触发类型互斥——一个 Task 只有一种：
- **manual**：手动执行
- **timer**：定时（Temporal Schedule）
- **chain**：前序 Job closed 后自动触发（经过 Replan Gate）

触发是硬约束：前序未满足时，按钮禁用（不是建议性的）。

### 3.5 Dynamic Replanning（动态重规划）

> 参考：GoalAct（持续更新全局计划）、Plan-and-Act（环境变化后动态生成新计划）

**问题**：Task DAG 在 Job 创建时快照不可变。如果某个 Job 结果偏离 Project 目标，后续 Task 仍按原计划执行——浪费 token，产出无用。

**机制**：在 Trigger chain 触发前插入 **Replan Gate**。

```
Job closed 事件
  │
  ▼
Replan Gate
  │ counsel 收到：Project goal + 已完成 Task 摘要 + 当前 Job 结果
  │ counsel 判断：结果是否偏离 Project goal？
  │
  ├─ 未偏离 → 继续触发下游 Trigger chain（现有逻辑不变）
  │
  └─ 偏离 → counsel 输出新的 Task DAG（diff，不是全新计划）
       │ 替换 Project 中尚未执行的 Task
       │ 已完成的 Task 不变
       └─ 新 DAG 继续走 Trigger chain
```

设计要点：
- Replan 不是每次都完整规划。counsel 先做轻量判断（~200 tokens），偏离时才做完整重规划（~800 tokens）
- Replan 粒度 = Task 级别。Step 级别的调整由 Job 内 agent 自己处理
- Replan 输出是 diff（"修改后续 Task 列表"），不是从零规划
- 实现位置：Temporal activity，在 chain trigger activity 前执行
- **Replan Gate 使用 analysis 模型**（见 §2.6），因为需要理解项目全局

#### 3.5.1 项目级上下文组装

counsel 做项目级决策（初始规划、Replan Gate）时，需要看到项目全貌。上下文组装规则：

```
counsel 项目级 prompt =
  Project goal（Plane Issue description）
  + 已完成 Task 列表（标题 + 状态 + 最终 Artifact 摘要）
  + 当前 Job 结果（Artifact 摘要，仅 Replan Gate）
  + 未完成 Task 列表（标题 + 依赖关系）
  + Mem0 规划经验（按需检索，~100-200 tokens）
```

**token 控制**：
- Artifact 摘要而非全文（~50 tokens/Task vs ~2000 tokens/Task）
- 10 个 Task 的 Project：~800 tokens context vs ~20000 tokens 全文
- 超过 20 个 Task 的 Project：只保留最近 5 个已完成 + 全部未完成

#### 3.5.2 Task 跨 Job 上下文连续性

同一 Task 多次执行（re-run、失败重试、定期重跑）时，**不需要特殊上下文机制**。counsel 规划新 Job 时已经能拿到足够的上下文：

- 上一个 Job 的最终 Artifact（做了什么、产出是什么、失败原因）
- Task 对话历史（用户反馈，Plane Issue activity）
- Mem0 规划经验（counsel 从历史 Job 中积累的规划模式）

**上下文在规划时重新组装，不靠 session 保活积累。** 每次 Job 基于最新信息全新规划，不受上一个 Job 执行过程的噪声污染。session 生命周期维持 1 Step = 1 Session，不按 Job 或 Task 延伸。

### 3.6 Step 并行执行

> 参考：LLMCompiler（DAG Planner + 并行 Executor，延迟降低 3.7x，成本降低 6.7x）

counsel 在规划 Job 的 Step 列表时，输出 Step 之间的依赖关系：

```json
{
  "steps": [
    {"id": 1, "goal": "search related work", "model": "fast", "depends_on": []},
    {"id": 2, "goal": "search methodology", "model": "fast", "depends_on": []},
    {"id": 3, "goal": "search datasets", "model": "fast", "depends_on": []},
    {"id": 4, "goal": "synthesize findings", "model": "creative", "depends_on": [1, 2, 3]}
  ]
}
```

执行逻辑：按依赖拓扑排序分层，同层 Step 并行执行。

```python
# Temporal Job Workflow
async def job_workflow(ctx, job_input):
    layers = topological_sort(job_input.steps)
    for layer in layers:
        # 同层无依赖，并行执行
        results = await asyncio.gather(*[
            workflow.execute_activity(execute_step, step)
            for step in layer
        ])
    return results
```

Temporal 原生支持此模式，不需要额外基础设施。

### 3.6.1 Artifact 在 Step/Job 间传递

Step 的产出（Artifact）是后续 Step 的输入。传递机制：

**Step 间（同 Job）**：
- Step 完成后，Artifact 存入 MinIO，元数据（path、type、summary）写入 PG `job_artifacts` 表
- 依赖 Step 启动时，从 `job_artifacts` 读取上游 Artifact 元数据，注入 agent prompt
- 大文件（PDF、代码仓库）只传 MinIO path + 摘要，不传全文（省 token）

```json
{
  "id": 4,
  "goal": "synthesize findings into literature review",
  "model": "creative",
  "depends_on": [1, 2, 3],
  "input_artifacts": ["step:1:search_results", "step:2:methodology_notes", "step:3:dataset_list"]
}
```

**Job 间（同 Task 的多次执行）**：
- 前一个 Job 的最终 Artifact 自动成为新 Job 的初始上下文
- counsel 在 Replan Gate 时可以看到前序 Job 的 Artifact 摘要

**Task 间（同 Project）**：
- chain 触发时，前序 Task 最终 Job 的 Artifact 摘要注入下游 Task 的首个 Job
- counsel 在项目级规划时指定 Task 间数据流：`task_input_from: ["task:T1:final_artifact"]`

```sql
CREATE TABLE job_artifacts (
    id          SERIAL PRIMARY KEY,
    job_id      TEXT NOT NULL,
    step_id     INT NOT NULL,
    artifact_type TEXT NOT NULL,    -- 'text', 'file', 'structured'
    summary     TEXT,               -- 摘要（注入 prompt 用）
    minio_path  TEXT,               -- MinIO 存储路径
    metadata    JSONB,              -- 额外元数据
    created_at  TIMESTAMPTZ DEFAULT now()
);
```

### 3.7 Step 失败处理与 Checkpoint

> 参考：Microsoft Agent Framework（checkpointing + resume）、Temporal replay

Temporal 原生提供 checkpoint：每个 Activity（= Step）完成后自动记录 event history。Worker crash 后 Workflow replay 时，已完成 Step 不重新执行。

Step 失败策略：
1. **Retry**：Temporal RetryPolicy（已有机制），自动重试
2. **Retry exhausted → counsel 判断**：
   - 跳过此 Step 继续（如果不影响后续）
   - 替换 Step（换一种方式达成同目标）
   - 终止 Job（无法挽救）
3. **人工介入**：counsel 标记 `requires_review: true` 时，Job 进入 paused，等待 Temporal Signal

### 3.8 Routing Decision（任务复杂度自适应）

> 参考：GoalAct（Skill 层按任务类型选择执行粒度）、AgentOrchestra（Planning Agent 任务分流）

用户输入是任意的——模糊、中英混杂、甚至是情绪表达。counsel 的第一步是理解意图、决定执行路径。

**不使用规则分类。** counsel 作为 LLM 自行判断，输出结构化 routing decision：

```json
{
  "intent": "用户想知道明天有没有雨",
  "route": "direct",
  "model": "fast",
  "task": "查询天气"
}
```

或复杂任务：

```json
{
  "intent": "写一篇关于 LLM agent 执行模型的综述论文",
  "route": "project",
  "tasks": [...]
}
```

或意图不清时追问、或判断为简单直接执行——**一切由 counsel 自行决定。**

| route | 行为 | 说明 |
|---|---|---|
| `direct` | 跳过 Project/Task，直接创建单 Step Job | 一步能完成 |
| `task` | 创建 Task + Job（无 Project） | 多步但目标明确 |
| `project` | 创建 Project + Task DAG | 长期、多阶段 |

三条路径使用同一个执行引擎（Job → Step），只是入口点不同。counsel 的 system prompt 定义输出格式，不定义决策逻辑。

---

## §4 知识体系

知识体系由开源方案承载，daemon 只写胶水代码：

| 组件 | 承载 | 说明 |
|---|---|---|
| **Guardrails** | NeMo Guardrails | 零 token 规则引擎，Colang DSL |
| **Persona** | Mem0 | 按需检索（省 90% token），自动提取/更新 |
| **Quota** | OC 原生 + Langfuse | 配额监控 |
| **Knowledge Base** | RAGFlow + PG knowledge_cache | 文档解析+分块+检索+TTL |
| 追踪统计 | Langfuse + PG | 自动记录，无独立名字 |

### 4.1 优先级层次

```
Guardrails（系统硬规则）> External Facts（外部事实）> Persona（用户偏好）> System Defaults
```

- Guardrails 与 Persona 冲突 → Guardrails 赢（系统原则不可被用户覆盖）
- External facts 与用户主张冲突 → External facts 赢（不替用户歪曲事实）
- Persona 与 System defaults 冲突 → Persona 赢（用户偏好优先于默认值）

### 4.2 Guardrails（系统硬规则）

**定义**：系统不可被用户覆盖的原则。代码层确定性执行，不依赖 LLM 遵守指令。

**实现方式**：NeMo Guardrails（NVIDIA 开源，Apache 2.0）。Python 库嵌入 Worker 进程，零额外服务。

| 层级 | 执行方式 | 成本 | 覆盖范围 |
|---|---|---|---|
| **硬规则** | NeMo input/output rail（Colang DSL） | 零 | 安全边界、隐私泄露检测、格式校验、Quota 上限、token 预算 |
| **软规则** | NeMo dialog rail + guardrails.md 注入 | 极低 | 质量底线、专业标准 |
| **关键审查** | counsel 安排审查 Step + NeMo output rail | 中 | 对外发布内容、高风险操作 |

#### 4.2.1 信息门控

所有信息流入系统都必须过 Guardrails 代码校验：

- Persona 候选写入 → 写入前过校验（用户确认 ≠ 免检）
- 外部知识引用 → source_tier 校验

#### 4.2.2 NeMo Guardrails 配置

| Rail 类型 | 作用 |
|---|---|
| Input rail | 过滤外发 query 中的敏感词（sensitive_terms.json） |
| Output rail | 检查输出是否违反硬规则 |
| Custom action | Mem0 写入前校验、source_tier 校验 |

Colang 规则文件位置：`config/guardrails/`。

#### 4.2.3 guardrails.md 内容范围

- **输出质量底线**：事实有来源、不伪造、不抄袭
- **信息完整性**：内外不混淆、关键事实交叉验证（Tier C 不算独立来源）
- **安全边界**：不执行有害指令、外部输入视为不可信、不泄露内部信息
- **专业标准**：冲突时先提醒 → 用户坚持 → 执行并标注 user_override → 安全边界内拒绝
- **冲突处理**：可降级冲突（提醒→确认→标注）vs 不可降级冲突（拒绝→解释）

#### 4.2.4 演进

guardrails.md 由系统维护者更新，纳入 git 管理。不由用户更新，不由 LLM 自动更新。

### 4.3 Persona（Mem0 记忆层）

**Mem0**（Apache 2.0）作为统一记忆层，承载 Persona（AI 人格 + 用户偏好 + 规划经验）。

#### 4.3.1 为什么用 Mem0

- 比全量上下文注入 **省 90% token**（按需检索 vs 全量注入）
- 比全量注入 **快 91%**
- 自动从对话中提取记忆，减少手动维护

#### 4.3.2 记忆类型

| 内容 | Mem0 记忆类型 | 级别 |
|---|---|---|
| AI 身份和人格 | semantic memory | agent 级 |
| 写作风格 | procedural memory | agent 级（envoy 用） |
| 用户偏好 | semantic memory | user 级 |
| 规划经验 | procedural memory | agent 级（counsel 用） |

#### 4.3.3 注入方式

Mem0 按需检索相关记忆（~50-100 tokens/次），不全量注入。

```python
# Step 执行前，检索与当前任务相关的记忆
results = mem0.search(
    query=f"{task_objective} {task_type}",
    agent_id=agent_role,
    limit=5
)
# 只注入相关条目，不是全量
```

#### 4.3.4 冷启动

- **方式 A（推荐）**：用户提供 3-5 篇写作样本 + 简要自我描述 → LLM 分析 → 写入 Mem0（一次性成本）。在暖机 Stage 1 执行。
- **方式 B**：什么都不提供 → 中性风格 → 随反馈逐渐积累。

#### 4.3.5 更新机制

1. 用户在 Job 过程中给出风格类反馈（"太正式了"）
2. Job 结束时系统列出本次反馈，问："这些里面有没有你希望以后都遵守的？"
3. 用户勾选 → NeMo Guardrails 校验 → 写入 Mem0

**不自动更新。** 所有 Persona 修改都经过用户确认。Mem0 的自动提取仅用于辅助建议，不直接写入。

#### 4.3.6 漂移检测

Mem0 内置去重和冲突检测。额外：
- 超过 90 天未触发的记忆标记为候选清理项
- 矛盾检测结果在 Plane 管理界面展示，用户手动解决

### 4.4 Quota（配额）

OC 原生配额 + Langfuse token 统计。

- 每日 token 限额（按模型分）——Langfuse Dashboard 监控
- 并发 Job 上限——Temporal 层控制
- 单 Job 最大消耗 = 日配额 × ratio

### 4.5 追踪统计（Langfuse + PG）

Langfuse 自动记录 LLM 调用追踪（token/延迟/成本），无需自建统计层。

规划经验（历史 DAG 模式）存入 Mem0，counsel 按需检索。详见 §8。

### 4.6 知识层（RAGFlow + knowledge_cache）

外部知识的获取、解析、存储、检索。

#### 4.6.1 RAGFlow（文档深度解析）

RAGFlow（Apache 2.0）提供：
- PDF 深度解析：布局分析、表格提取、公式保留、多栏阅读顺序
- 语义分块：按段落/章节切，不按字数切
- 向量检索：精准命中相关分块

**token tradeoff**：50 页论文 ≈ 25000 token → 分块后检索 3 个相关块 ≈ 1500 token（省 94%）。

#### 4.6.2 knowledge_cache（TTL 过期管理）

RAGFlow 不管 TTL。过期管理在 PG 层：

```sql
CREATE TABLE knowledge_cache (
    id          SERIAL PRIMARY KEY,
    source_url  TEXT NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(1024),
    source_tier CHAR(1) NOT NULL,  -- A/B/C
    ragflow_doc_id TEXT,           -- RAGFlow 文档 ID（全文解析时）
    fetched_at  TIMESTAMPTZ DEFAULT now(),
    expires_at  TIMESTAMPTZ NOT NULL
);
```

TTL 按来源分级（source_tiers.toml）：

| 级别 | 来源示例 | TTL | 验证要求 |
|---|---|---|---|
| **Tier A** | arxiv、Semantic Scholar、官方文档 | 90 天 | 单源即可引用 |
| **Tier B** | Wikipedia、MDN、主流媒体 | 30 天 | 关键数据需交叉验证 |
| **Tier C** | Reddit、StackOverflow 评论、匿名来源 | 7 天 | 必须交叉验证，不可作唯一来源 |

NeMo Guardrails 硬规则：**Tier C 来源的数据不得作为事实性主张的唯一支撑。**

#### 4.6.3 知识获取工具链

| 工具 | 作用 | 集成方式 |
|---|---|---|
| **通用 MCP search** | 网页搜索 | MCP tool → scholar |
| **Semantic Scholar API** | 学术论文搜索（2亿+论文） | MCP tool → scholar |
| **Firecrawl** | 网页 → 干净 Markdown（省 80%+ token） | Docker 自部署，MCP tool → worker |
| **RAGFlow** | PDF/文档 → 语义分块 → 向量检索 | Docker 服务 |

#### 4.6.4 隐私边界

- `config/sensitive_terms.json`：维护敏感词列表
- NeMo Guardrails input rail 在 MCP 调用前过滤
- 被过滤的词替换为通用描述（如 "项目X" → "某软件项目"）

### 4.7 内外知识分野

```
外部知识（External）—— 事实性的、可引用的、可验证的
  来源：scholar → MCP search / Semantic Scholar → RAGFlow / knowledge_cache
  特点：有 source_url、有 source_tier
  使用：引用时标注来源
  信任：按 tier 分级

内部知识（Internal）—— 个人化的、累积的、可调整的
  来源：Mem0（agent memory / user memory）
  特点：无"对错"，只有"符不符合用户"
  使用：塑造风格和方式，不塑造内容和事实
  信任：用户权威（NeMo Guardrails 边界内）

系统知识（System）—— 内置的、不可覆盖的
  来源：NeMo Guardrails Colang 规则（config/guardrails/）
  使用：输出校验、冲突裁决
  信任：最高
```

### 4.8 Mem0 按需注入

Step 执行时，从 Mem0 按需检索相关记忆注入：

| Agent | 检索 query | 约 token |
|---|---|---|
| scholar / artificer | 任务目标 | ~50-100 |
| scribe | + "写作风格" + 语言 + task_type | ~100-200 |
| arbiter | + "质量标准" + task_type | ~50-100 |
| counsel | + "规划经验" + 历史 DAG 模式 | ~100-200 |
| envoy | + "发布风格" + 渠道 | ~100-200 |

**对比全量注入**：~300-550 tokens → Mem0 按需 ~50-200 tokens。

NeMo Guardrails 的规则在引擎层执行，**不注入 prompt**（零 token）。

---

## §5 交互设计

> **注意**：前端由 Plane 替代自造 Portal/Console。本节定义 Plane 适配后的交互规则。

### 5.1 界面角色

| 界面 | 角色 | 说明 |
|---|---|---|
| **Plane 前端** | 任务管理主界面 | Issue(Task) / Project / DraftIssue(Draft) 的查看和操作 |
| **Job 实时面板** | 执行监控 | WebSocket 推送，Plane 不提供，需自建 |
| **Plane 管理界面** | 系统治理 | 替代旧 Console |
| **Telegram** | 通知 + 极简命令 | envoy 通过 OC 原生 channel 发送 |

### 5.2 Task 交互（映射到 Plane Issue）

Task 是核心工作单元，映射到 Plane Issue。

**Task 页面内容**：
- Issue 标题和描述
- DAG / plan card（Plane Issue 的 custom property 或 description 区域）
- 活动流（Plane Activity，承载交互记录）
- Job 执行块（自建 WebSocket 面板，内嵌于 Issue 详情）
- 动作区（按触发类型动态显示）

**按触发类型显示**（三种互斥）：

| 触发类型 | 显示 |
|---|---|
| 手动触发 | 「执行」按钮（创建 Job + 立即运行，原子操作） |
| 定时触发 | 定时设置信息（下次触发时间、周期） |
| 前序事件触发（Trigger chain） | 等待条件状态；条件未满足时按钮禁用 |

### 5.3 Job 交互

Job 不是独立页面，是 Task 内的执行块。

**执行块内容**：
- DAG 进度（当前 Step 位置）
- Artifact 版本和执行细节
- 按钮：开始/停止（toggle）

**Job closed 后**：执行块冻结为只读（Artifact 标签 + 执行摘要）。

### 5.4 Project 交互（映射到 Plane Project/Module）

Project 页面回答：
1. 这个项目最近在推进什么
2. 里面有哪些 Task
3. 哪些 Task 正在活跃
4. 最近收束出了什么结果

Project 结构视图中，每个 Task 旁带内联操作区（按触发类型显示）。

### 5.5 Draft 交互（映射到 Plane DraftIssue）

Draft 使用 Plane DraftIssue。转换为 Task 即 DraftIssue → Issue。

### 5.6 对话与反馈

#### 5.6.1 统一对话流

Task 只有一条对话流（Plane Issue Activity），承载所有交互：
- 无 Job 时：调整 DAG
- Job 运行期间：执行调整和评价

#### 5.6.2 按钮-对话等价

按钮和对话是同一控制通道的两种表达。所有非对话操作在活动流中生成自然语言记录。

#### 5.6.3 反馈收集

Job closed 后，用户可在 Task 对话流中给出反馈。风格类反馈经用户确认后写入 Mem0（Persona）。无 settling 窗口，无超时自动关闭。

### 5.7 Task 依赖交互

Task 依赖在 Plane 中通过 IssueRelation（blocked_by）+ 胶水代码实现。

- 依赖是**强约束**：前序未满足时按钮禁用
- Project 内 Task 通过依赖关系形成 DAG，支持链内前后导航

### 5.8 Telegram 交互

通过 envoy 的 OC 原生 Telegram channel（announce 机制）：
- 完成通知、失败通知
- 状态查询
- 极简控制命令

**不承载**：主任务协作、大段反馈、复杂对象组织。

### 5.9 显示语言

- Plane 界面使用正式中文术语
- 英文 canonical name 保留给代码、API、调试

---

## §6 基础设施

### 6.1 Docker Compose 服务清单

| 服务 | 镜像/技术栈 | 职责 | 端口 |
|---|---|---|---|
| **PostgreSQL** | postgres:16 + pgvector | 主数据库（Plane + daemon + Mem0 共用） | 5432 |
| **Redis** | redis:7 | 缓存 + 消息队列（Plane + Langfuse 共用） | 6379 |
| **Plane API** | Django + DRF | Issue/Project/DraftIssue CRUD + Webhook | 8000 |
| **Plane 前端** | React + TypeScript | 用户界面 | 3000 |
| **Plane Worker** | Celery | 异步任务（邮件、导出等） | — |
| **Temporal Server** | temporalio/server | Workflow 编排 + Schedules | 7233 |
| **Temporal UI** | temporalio/ui | 运维 Dashboard | 8080 |
| **MinIO** | minio/minio | S3 兼容对象存储（Plane + Langfuse + RAGFlow + daemon 共用） | 9000/9001 |
| **Langfuse** | langfuse/langfuse | LLM 追踪 + 评估 | 3001 |
| **ClickHouse** | clickhouse/clickhouse-server | Langfuse 分析后端 | 8123 |
| **RAGFlow** | infiniflow/ragflow | 文档解析 + 分块 + 向量检索 | 9380 |
| **Elasticsearch** | elasticsearch:8 | RAGFlow 全文索引后端 | 9200 |
| **Firecrawl** | mendableai/firecrawl | 网页 → 干净 Markdown | 3002 |

### 6.2 daemon 自有进程（非 Docker）

| 进程 | 技术栈 | 职责 |
|---|---|---|
| **API 进程** | FastAPI（uvicorn） | 胶水层：Plane webhook handler、Job 实时 WebSocket |
| **Worker 进程** | Temporal Python Worker | Activities（调 OC agent、写 Plane API、写 PG）、定时清理 Job、NeMo Guardrails、Mem0 |

两个 Python 进程不直接通信，通过 Temporal workflow + PG 协作。NeMo Guardrails 和 Mem0 作为 Python 库嵌入 Worker 进程，不是独立服务。

### 6.3 OC Gateway

| 组件 | 说明 |
|---|---|
| **OpenClaw** | Agent 编排平台 |
| **7 agents** | counsel / scholar / artificer / scribe / arbiter / envoy / steward |
| **Session 管理** | 1 Step = 1 Session，生命周期 = Step 级别 |
| **并发配置** | `maxChildrenPerAgent`（默认 5）/ `maxConcurrent`（默认 8），暖机时按实际 rate limit 调高 |
| **Subagent 深度** | `maxSpawnDepth: 2`（orchestrator 模式），支持 Step 内并行 |
| **MCP 分发** | runtime/mcp_dispatch.py + config/mcp_servers.json |

`~/.openclaw → daemon/openclaw/` 软链接必须存在。

### 6.4 外部依赖

| 组件 | 说明 |
|---|---|
| **Python 3.11+** | API 进程 + Worker 进程 |
| **Node.js** | MCP servers 运行时 |
| **LLM Provider API Keys** | MiniMax、DeepSeek、Qwen（analysis + review）、智谱（embedding） |
| **Telegram Bot Token** | OC 原生 Telegram channel 配置 |
| **GitHub Token** | MCP server（@modelcontextprotocol/server-github） |
| **Semantic Scholar API Key** | 学术搜索（免费，可选，提升速率限制） |

### 6.4.1 Python 依赖（第二轮新增）

| 库 | 用途 |
|---|---|
| `mem0ai` | 记忆层（替代 psyche snapshot） |
| `nemoguardrails` | 安全规则引擎（替代 InstinctEngine） |

### 6.5 网络拓扑

```
                    ┌──── 用户 ────┐
                    │              │
              ┌─────▼──────┐  ┌───▼───┐
              │ Plane 前端  │  │ Telegram│
              │ :3000      │  │ (OC)   │
              └─────┬──────┘  └───┬───┘
                    │              │
              ┌─────▼──────┐  ┌───▼──────────┐
              │ Plane API   │  │ OC Gateway    │
              │ :8000      │  │              │
              └──┬────┬────┘  └──────┬───────┘
                 │    │              │
     webhook ────┘    │         ┌────▼─────┐
                 │    │         │ MCP servers│
          ┌──────▼────▼──┐     └────┬─────┘
          │ daemon API    │         │
          │ (FastAPI)     │    外部 API
          │ :8100         │   (GitHub/etc)
          └──────┬────────┘
                 │
          ┌──────▼────────┐
          │ Temporal Server│
          │ :7233          │
          └──────┬────────┘
                 │
          ┌──────▼────────┐
          │ daemon Worker  │
          │ (Temporal)     │
          └──────┬────────┘
                 │
     ┌───────────┼───────────┐
     │           │           │
┌────▼───┐ ┌────▼───┐ ┌─────▼────┐
│ PG     │ │ MinIO  │ │ Langfuse │
│ :5432  │ │ :9000  │ │ :3001    │
└────────┘ └────────┘ └──────────┘
```

### 6.6 数据流

| 链路 | 说明 |
|---|---|
| 用户 → Plane 前端 → Plane API → PG | Task/Project/Draft CRUD |
| Plane API → webhook → daemon API | Issue 状态变更通知 |
| daemon API → Temporal → Worker | Job 创建和执行 |
| Worker → OC Gateway → agents | Agent 调用（persistent session） |
| Worker → Plane API | 写回状态和结果 |
| Worker → PG | knowledge_cache、Job 数据 |
| Worker → Langfuse | LLM 调用追踪 |
| Worker → MinIO | Artifact 文件存储 |
| envoy → OC Telegram channel | 通知发布 |
| envoy → MCP server → GitHub | GitHub 操作 |
| PG LISTEN/NOTIFY | 事件总线（替代 Ether） |
| Temporal Schedules → Worker | 定时清理 Job |

### 6.7 关键配置

| 配置 | 位置 | 说明 |
|---|---|---|
| DAEMON_HOME | 环境变量 / 默认 `Path(__file__).parent` | daemon 根目录 |
| openclaw.json | openclaw/openclaw.json | OC agent 配置 |
| mcp_servers.json | config/mcp_servers.json | MCP server 注册 |
| source_tiers.toml | config/source_tiers.toml | 外部源信任分级 + TTL |
| sensitive_terms.json | config/sensitive_terms.json | 隐私过滤词 |
| guardrails/ | config/guardrails/ | NeMo Guardrails Colang 规则 |

---

## §7 暖机与系统标定

> **完整方案**：`.ref/_work/WARMUP_AND_VALIDATION.md`

### 7.1 定位

**暖机不是初始化，是图灵测试级系统标定。**

目标：daemon 所有对外输出达到"伪人"水准——与用户本人无法区分。

### 7.2 前提

Phase 0-5 全部完成。所有基础设施运行正常，所有代码部署完毕。

### 7.3 五个 Stage

| Stage | 名称 | 时间 | 说明 |
|---|---|---|---|
| 0 | 信息采集 | ~15min | 收集用户身份、写作样本、偏好、平台、任务示例 |
| 1 | Persona 标定 | ~20min | LLM 分析样本 → Mem0 persona → 试写验证 |
| 2 | 链路逐通 | ~30min | 17 条数据链路逐条验证 |
| 3 | 测试任务套件 | ~2-3h | 8-15 个真实复合场景，迭代到连续 5 个通过 |
| 4 | 系统状态测试 | ~30min | 10 个异常场景（并发/超时/故障恢复/积压…） |

### 7.4 收敛标准

**伪人度**——连续 5 个不同类型任务的对外产出与用户本人无法区分。

由 **steward** 全程主导：设计测试任务、评估产出质量、调整 skill 和参数、决定是否收敛。

### 7.5 暖机目录结构

```
warmup/
  writing_samples/   ← 用户提供的写作样本
  about_me.md        ← 用户自我描述
  results/           ← 暖机过程记录
```

### 7.6 周度体检

暖机完成后，系统进入生产状态。**steward** 通过 Temporal Schedule 每周自动执行体检，无需用户触发。

#### 7.6.1 两层检测

| 层 | 内容 | 执行方式 | 时长 |
|---|---|---|---|
| **基础设施层** | 17 条数据链路验证（Stage 2 缩减版） | 全自动脚本 | ~10min |
| **质量层** | 固定基准任务套件（暖机时选定） | steward 主导，半自动 | ~1h |

**基准任务**：暖机 Stage 3 结束时选定 5-8 个代表性任务，固定下来作为每周基准。每次用同一套，结果可横向对比，趋势可见。

#### 7.6.2 检测内容

| 维度 | 检测方法 |
|---|---|
| 伪人度 | steward 评估基准任务产出，对比暖机 baseline |
| 风格一致性 | scribe/envoy 产出与 Persona 比对 |
| Skill token 效率 | Langfuse 查各 skill 对应 Step 的 token 用量趋势 |
| arbiter 通过率 | 统计基准任务中 arbiter 审查通过率 |
| 外部平台格式 | 验证 GitHub/Telegram 产出格式仍符合平台要求 |

#### 7.6.3 体检结果处置

```
体检完成
  │
  ├─ 全部通过 → 生成周报，存入 state/health_reports/YYYY-MM-DD.json
  │
  ├─ 质量指标下滑（未跌破阈值）→ 周报标注，steward 记录趋势，暂不干预
  │
  └─ 任意指标跌破阈值
       │ envoy 推送 Telegram 告警（不打扰用户则不发）
       │ steward 定位问题 skill / 参数
       └─ 触发针对性 skill 重校准（不是重跑完整暖机）
```

**阈值参考**（暖机时基于 baseline 设定）：
- arbiter 通过率 < 80% → 告警
- 单 skill 平均 token 用量 > baseline 150% → 告警
- 伪人度评分 < 4/5 → 告警

---

## §8 学习机制

### 8.1 核心原则

| 原则 | 说明 |
|---|---|
| **只学 accepted** | 只从成功的 Job 中学习。不学失败。 |
| **Mem0 统一管理** | 规划经验、风格偏好、对话记忆全部存入 Mem0，按需检索。 |
| **不自动更新 Persona** | 所有 Persona 修改都经过用户确认。 |

> **三稿 → 四稿变更**：
> - 删除自建 dag_templates / project_templates PG 表。规划经验存入 Mem0 procedural memory（counsel 级别）。
> - 删除 Extract 机制。Langfuse 自动记录追踪数据，Mem0 自动从对话中提取记忆候选。
> - 删除 eval_chain。用户反馈直接通过 Mem0 更新机制处理（见 §4.3.5）。
> - 删除 skill_stats / agent_stats 自建表。Langfuse traces + PG 聚合即可。

### 8.2 规划经验学习

Job 成功后，counsel 的规划决策（DAG 结构、模型策略选择、Step 分解方式）自动存入 Mem0 procedural memory。

**消费**：新任务 → Mem0 按需检索相关规划经验 → 注入 counsel prompt，counsel 参考生成 DAG。

**冷启动**：没有历史经验时，counsel 从零规划。前 20 个成功 Job 后开始有参考价值。

### 8.3 来源标记

Agent 执行 Step 时，prompt 注入来源标记要求：
- `[EXT:url]` = 来自外部搜索
- `[INT:persona]` = 来自用户风格偏好
- `[SYS:guardrails]` = 来自系统规则

标记不展示给用户，存储在 Step output 元数据中，供审计追溯。

---

## §9 Skill 体系

**Skill 是系统完成工作质量的核心保障机制。**

一个 session 拿到任务有两条路：没有 skill 时，agent 花大量 token 自己推理做法，输出质量不稳定；有好的 skill 时，agent 按已验证的流程执行，token 花在做事上而不是想怎么做。一个写得好的 200 token skill 能省掉 2000 token 的摸索，同时输出质量更高、更稳定。

### 9.1 Skill 结构规范

每个 SKILL.md 文件描述一种可复用的执行过程。结构如下：

```markdown
# Skill 名称

## 适用场景
什么情况下调用这个 skill（trigger 条件）

## 输入
需要什么信息才能开始

## 执行步骤
1. 步骤一（调用什么工具 / 产出什么）
2. 步骤二
3. ...

## 质量标准
产出必须满足什么条件才算合格（arbiter 审查的基准）

## 常见失败模式
已知的坑和规避方法

## 输出格式
产出的结构和格式要求
```

规范要求：
- **清晰**：步骤可执行，不含模糊指令（"做好"不是步骤，"用 scholar 搜索 X 并提取 Y" 才是）
- **完整**：覆盖正常路径 + 已知失败模式
- **简洁**：每个 skill 聚焦一件事，复合任务拆成多个 skill 组合

### 9.2 Skill 粒度原则

| 粒度 | 判断标准 | 示例 |
|---|---|---|
| 合适 | 一个 Step 内可以完整执行 | "搜索并提取某领域最新论文摘要" |
| 太粗 | 需要多个 agent 协作才能完成 | "做一个完整的市场调研报告"（这是 Job，不是 skill） |
| 太细 | 只是一次工具调用 | "调用 search MCP"（直接写 TOOLS.md 即可）|

同一 agent 的多个 skill 应该是**可组合的**：一个 Step 的目标可以隐含调用一个或多个 skill。

#### 9.2.1 counsel 与 skill 的关系

**counsel 不感知 skill，只负责目标和 agent。**

```json
{"id": 3, "goal": "write tech blog post", "agent": "scribe", "depends_on": [1, 2]}
```

counsel 规划时只指定目标（goal）和执行 agent，不指定 skill。skill 的选择完全在 agent 侧：session 启动时 TOOLS.md 列出该 agent 所有可用 skill，agent 根据 Step 目标自己匹配调用。

**理由**：
- counsel 无需维护"哪个 agent 有哪些 skill"的知识，负担最小
- skill 增删改不影响 counsel 的规划逻辑，两者解耦
- agent 比 counsel 更了解自己的能力边界，匹配更准确

### 9.3 各 Agent 的 Skill 域

| Agent | Skill 域 | 示例 skill |
|---|---|---|
| counsel | 规划、任务分解、Replan 判断 | 如何分解研究类 Project、如何判断 Replan 必要性 |
| scholar | 搜索策略、信息提取、深度分析、推理框架、Knowledge Base 管理 | 学术搜索流程、技术文档检索、信源可信度评估、文献综述结构、方案对比论证 |
| artificer | 编码规范、调试流程、技术决策 | 代码审查清单、调试定位方法、重构步骤 |
| scribe | 写作结构、风格适配、格式规范 | 技术博客结构、学术摘要写法、对外公告措辞 |
| arbiter | 审查维度、评分标准 | 事实核查清单、逻辑一致性检查、风格合规审查 |
| envoy | 各平台发布规范、格式要求 | GitHub PR 描述规范、Telegram 消息格式、发布前检查清单 |
| steward | 系统诊断、体检流程、skill 评估方法 | 体检基准任务设计、skill 质量评估方法、参数校准流程 |

### 9.4 Skill 生命周期

```
Phase 5（Agent 层实现阶段）
  │ scholar 搜索各 agent 领域最新最佳实践
  │ artificer 改写为 daemon SKILL.md 格式
  │ 产出：每个 agent 有至少 3-5 个核心 skill 草稿
  ▼
暖机 Stage 3（校准）
  │ 用真实任务跑每个 skill
  │ Langfuse 观察：token 用量 / 产出被 arbiter 接受率 / 步骤完成度
  │ 不达标 → 修改 skill → 重跑，迭代到稳定
  ▼
生产使用
  │ Langfuse 持续监控异常 Step（超 token / arbiter 拒绝频繁）
  │ 定位到具体 skill 问题
  │ 修改 SKILL.md → 下一个 session 立即生效（无需重启）
  ▼
迭代
  │ 外部最佳实践更新 → scholar 定期重扫 → artificer 适配 → 更新 skill
  │ 用户反馈 → 经确认 → 写入对应 skill 的"常见失败模式"
```

### 9.5 暖机前 Skill 准备（Phase 5 收尾）

暖机开始前，skill 必须是"有内容的草稿"，不能是空白文件。暖机只做校准，不从零写。

**准备流程**：
1. 确定每个 agent 需要哪些 skill（参考用户在 Stage 0 提供的真实任务示例）
2. scholar 针对每个 skill 域搜索：当前业界最佳实践、工具使用指南、常见失败模式
3. artificer 把外部资料改写为符合 §9.1 规范的 SKILL.md
4. 用户审阅，确认方向正确后进入暖机

**注意**：skill 内容应基于外部最新资讯，不是凭空设计。scholar 在准备阶段搜索的内容直接成为 skill 的知识基础。

### 9.6 Skill 与 Token 效率

| 场景 | 无 skill | 有好的 skill |
|---|---|---|
| agent 如何开始 | 在 context 里推理做法 | 直接按 skill 步骤执行 |
| token 用量 | 高且不可预测 | 低且稳定 |
| 输出一致性 | 每次不同 | 跨 session 稳定 |
| 失败模式 | 随机出现 | 已知且被覆盖 |
| arbiter 通过率 | 低 | 高 |

**Skill 质量是 token 效率最大的单一决定因素。** 暖机期间对 skill 的投入直接决定生产阶段的运行成本。

### 9.7 Skill 更新规则

- Skill 文件纳入 git 管理，修改有 commit 记录
- 修改 skill 不需要重启服务，下一个 session spawn 时自动加载新版本
- **不自动更新 skill**：所有 skill 修改经过人工审查（用户或 artificer 提案 + 用户确认）
- Langfuse 中 skill 相关 Step 的 token 超标或失败率 > 20% 时，触发 skill 审查

---

## §10 可观测性与自愈

### 10.1 设计原则

**用户只需要知道两件事：系统在正常工作，或者修好了。** 正常情况下没有用户的事。问题发生时，系统先自己解决；解决不了，生成一个用户能直接转发给 Claude Code / Codex 的问题文件，用户只做传话人。

### 10.2 可追溯数据链

每个 Job 产生一条完整可追溯链：

```
Plane Issue（用户视角）
  → Job ID（daemon 写回 Plane comment）
  → PG job / step 记录（每个 Step 的 skill、input、output、token、executor）
  → Langfuse trace（完整推理过程、token 用量趋势）
  → Temporal workflow history（执行时序、retry 记录）
```

steward 通过查询这条链做规则驱动诊断，无需 LLM。

### 10.3 三层自愈流程

```
问题检测（steward 规则驱动，零 LLM）
  │
  ▼
Layer 1：steward 自动修复
  │ 规则明确的问题（skill 步骤缺失、token 超标、格式错误）
  │ 直接修改 SKILL.md → 运行 verify.py 验证
  │
  ├─ 通过 → 静默记录，不通知用户
  │
  └─ 失败 ↓

Layer 2：生成问题文件，自动调用 Claude Code / Codex
  │ steward 生成 state/issues/YYYY-MM-DD-HHMM.md（自解释，见 §10.4）
  │ Temporal Activity subprocess 调用 claude_code 或 codex
  │ CC/Codex 读文件 → 修复 → 运行 scripts/start.py（确保进程就绪）→ 运行 scripts/verify.py
  │
  ├─ 通过 → Telegram 简短通知「已自动修复」
  │
  └─ 失败 ↓

Layer 3：通知用户（最后手段）
  Telegram：「自动修复失败，请把 state/issues/YYYY-MM-DD-HHMM.md 发给 Claude Code」
  用户转发文件 → CC 执行修复流程（同 Layer 2）
```

### 10.4 问题文件格式

`state/issues/YYYY-MM-DD-HHMM.md` — 对 Claude Code / Codex 自解释，用户无需理解内容：

```markdown
# 问题报告

## 你需要做什么
[一句话说明需要什么操作，不使用系统内部术语]

## 背景
daemon 是一个自动化助手系统。skill 文件是 agent 的操作指南。

## 具体问题
文件：[文件绝对路径]
问题：[具体描述，附相关错误信息]

## 当前文件内容
[文件全文]

## 期望行为
[修复后应该达到的效果]

## 执行步骤（修复完成后按顺序运行）
1. python scripts/start.py          # 确保所有进程就绪
2. python scripts/verify.py --issue YYYY-MM-DD-HHMM  # 自动验证并发送通知
```

**问题文件设计要求**：
- 不使用系统内部术语（不写 Job/Step/Artifact）
- CC/Codex 只读这一个文件就能完成修复，不需要额外上下文
- 验证脚本负责发 Telegram 通知，CC/Codex 不需要告知用户任何事

### 10.6 配套脚本

| 脚本 | 职责 |
|---|---|
| `scripts/start.py` | 检查所有进程是否就绪（API 进程、Worker 进程、OC Gateway、Docker 服务），未启动的自动拉起 |
| `scripts/verify.py --issue <id>` | 读取对应 issue 文件，运行验证用例，通过则发 Telegram「已修复」，失败则发「修复失败」 |
| `scripts/self_heal.py` | steward 触发 Layer 2 自动修复的入口，调用 CC/Codex subprocess，传入 issue 文件路径 |

### 10.5 用户操作边界

| 场景 | 用户操作 |
|---|---|
| 正常运行 | 无 |
| 自动修复成功 | 收到「已自动修复」通知，无需操作 |
| 自动修复失败 | 收到通知 → 把指定文件发给 Claude Code → 等通知 |
| 系统完全正常 | 只看周度体检通知（GREEN/YELLOW/RED） |

---

## §11 禁止事项

以下理解已被正式否决：

1. Job 仍兼任任务本体
2. Portal 与 Console 可以各自维护一套对象规则
3. 系统仍需要并列的多套正式任务类型
4. 同 agent 的并行 Step 合并为复合指令
5. Project 晋升由 step count 超过 dag_budget 触发
6. `job_completed` 事件用于下游 Trigger 触发
7. Instinct 规则执行依赖 LLM 遵守 prompt
8. 存在独立的评价表单/UI
9. 调整和评价是两种不同的对话类型
10. 系统假设用户行为总是善意的
11. 评价只发生在 settling 阶段
12. Slash command 是对话框的正式入口
13. 同一个 Task 可以同时具有多种触发类型
14. Trigger 排序是建议性的
15. Task 和 Job 各有独立对话框
16. 按钮和对话是不同控制通道
17. 信息提取由按钮触发
18. 复杂度分级（errand/charge/endeavor）仍有效
19. Memory/Lore 向量知识库仍有效
20. Herald 是独立通知服务
21. 用规则/关键词分类任务复杂度（counsel 自行判断，不硬编码决策逻辑）
22. Task DAG 不可变（Replan Gate 允许动态修改未执行 Task）
23. Draft 是 daemon 自管独立对象（直接用 Plane DraftIssue）
24. Trigger 是一等实体（降级为 Plane IssueRelation + Temporal Schedule 组合）
25. agent 角色与模型死绑定（counsel 动态指定 agent + 可选 model override，不死绑）
26. settling 窗口 + 超时自动关闭（删除，默认 no-wait，需要审查时 counsel 标记 requires_review）
27. 自建 Extract 机制提取信息（Langfuse 自动追踪 + Mem0 自动提取）
28. 自建 dag_templates / project_templates 表（规划经验存 Mem0）
29. 自建 Ledger 统计表（Langfuse traces + PG 聚合）
30. Task 可晋升为 Project（counsel 在 routing decision 时直接决定）
31. 1 Step = 1 Agent + 1 交付物（1 Step = 1 目标）
32. Spine routines 维护系统（1 个定时清理 Job 替代 7 个 routines）
33. 自造隐喻术语（Psyche/Instinct/Voice/Rations 等全部用业界通用术语）
