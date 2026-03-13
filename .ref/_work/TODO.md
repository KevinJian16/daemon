# Daemon 系统重建 TODO

> 日期：2026-03-13
> 状态：进行中
> 依据：`.ref/_work/OPEN_SOURCE_REPLACEMENT_PLAN.md`

**核心方针**：用成熟开源方案替代自造组件，只保留最小胶水层。
**能力标杆**：daemon 能做出自己这个程度的项目，能写出人类水平的论文。
**决策标准**：只看能力和 token 的 tradeoff，硬件资源充足。
**净效果**：删除 ~7100 行自造代码，新增 ~800-1200 行胶水代码。

---

## 关键文档索引

| 文档 | 路径 | 用途 |
|---|---|---|
| 开源替代方案 | `.ref/_work/OPEN_SOURCE_REPLACEMENT_PLAN.md` | 所有替换决策的详细调查和技术方案 |
| 术语规范 | `.ref/TERMINOLOGY.md` | ⚠ 旧术语，以 SYSTEM_DESIGN.md §1 为准 |
| 交互设计 | `.ref/INTERACTION_DESIGN.md` | ⚠ 旧术语，以 SYSTEM_DESIGN.md §5 为准 |
| 执行模型 | `.ref/EXECUTION_MODEL.md` | ⚠ 旧术语，以 SYSTEM_DESIGN.md §3 为准 |
| 设计 QA | `.ref/DESIGN_QA.md` | 设计决策权威（冲突时优先） |
| 旧知识层方案 | `.ref/_work/REFACTOR_KNOWLEDGE_AND_WARMUP.md` | **已被本 TODO 取代**，仅供参考 |

---

## 术语速查（给后续模型用）

> **2026-03-13 四稿术语**：详见 SYSTEM_DESIGN.md §1。

| daemon 术语 | 含义 | Plane 映射 |
|---|---|---|
| **Project** | Task 容器 | `Project` / `Module` |
| **Task** | 核心工作单元 | `Issue` |
| **Job** | Task 的一次执行记录（running→closed） | 无映射，daemon PG + Temporal |
| **Step** | Job 中的一步（1 目标，可调用任意 agent/tool） | — |
| **Artifact** | Job 交付物 | — |
| Task 依赖 | Task 间依赖关系 | `IssueRelation(blocked_by)` |
| Draft | 草稿 | `DraftIssue` |
| **counsel** | 规划 agent | — |
| **worker** | 通用执行 agent | — |
| **envoy** | 对外出口 agent（可选） | — |
| **Guardrails** | 系统硬规则 | NeMo Guardrails |
| **Persona** | AI 人格 + 用户偏好 | Mem0 |
| **Quota** | 资源配额 | OC + Langfuse |
| **Knowledge Base** | 外部知识缓存 | RAGFlow + PG |

---

## Phase 0：准备工作

- [ ] **0.1** 归档旧前端
  - `mv interfaces/portal/ interfaces/portal_archived/`
  - 保留 `interfaces/portal_archived/` 直到 Phase 7 确认不需要后删除

- [ ] **0.2** 标注旧方案已过期
  - 在 `.ref/_work/REFACTOR_KNOWLEDGE_AND_WARMUP.md` 顶部加注：`> ⚠ 本方案已被开源替代方案取代，仅供参考。见 TODO.md`

- [ ] **0.3** 更新记忆系统
  - 更新 `/Users/kevinjian/.claude/projects/-Users-kevinjian-daemon/memory/MEMORY.md`
  - 记录：架构从"自造全栈"转向"开源基础设施 + 薄胶水层"

---

## Phase 1：基础设施（Docker Compose）

**目标**：`docker compose up -d` 一条命令拉起全部服务。

**产出文件**：`docker-compose.yml`、`.env.example`

### 服务清单

| 服务 | 镜像 | 端口 | 说明 |
|---|---|---|---|
| PostgreSQL | `pgvector/pgvector:pg16` | 5432 | Plane + Langfuse + daemon 共用，需 pgvector 扩展 |
| Redis | `redis:7-alpine` | 6379 | Plane + Langfuse 共用 |
| MinIO | `minio/minio` | 9000/9001 | Plane + Langfuse + daemon 共用 |
| Temporal Server | `temporalio/auto-setup` | 7233 | 已在用，保持 |
| Temporal UI | `temporalio/ui` | 8080 | 已在用，保持 |
| Plane API | `makeplane/plane-backend` | 8000 | Django + DRF |
| Plane Frontend | `makeplane/plane-frontend` | 3000 | React + TypeScript |
| Plane Worker | `makeplane/plane-worker` | — | Celery worker |
| Plane Beat | `makeplane/plane-beat` | — | Celery beat |
| Langfuse | `langfuse/langfuse` | 3001 | 含 Web UI |
| ClickHouse | `clickhouse/clickhouse-server` | 8123/9000 | Langfuse 必需 |

### 具体任务

- [ ] **1.1** 编写 `docker-compose.yml`
  - 参考 Plane 官方 `docker-compose.yml`：https://github.com/makeplane/plane → `deploy/selfhost/docker-compose.yml`
  - 参考 Langfuse 官方：https://github.com/langfuse/langfuse → `docker-compose.yml`
  - 合并共用的 PG/Redis/MinIO，避免重复实例
  - 网络：所有服务在同一 Docker network
  - Volume：PG data、Redis data、MinIO data、ClickHouse data 持久化

- [ ] **1.2** 编写 `.env.example`
  - `DATABASE_URL=postgresql://daemon:password@postgres:5432/daemon`
  - `REDIS_URL=redis://redis:6379/0`
  - `MINIO_ENDPOINT=minio:9000`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`
  - `TEMPORAL_ADDRESS=temporal:7233`
  - `PLANE_API_URL=http://plane-api:8000`、`PLANE_API_TOKEN`
  - `LANGFUSE_HOST=http://langfuse:3001`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`

- [ ] **1.3** 验证启动
  - `docker compose up -d` 后逐个检查健康状态
  - PG: `psql -c "SELECT 1"`、`CREATE EXTENSION vector` 验证 pgvector
  - MinIO: 访问 Console（:9001）
  - Plane: 访问前端（:3000），完成初始设置
  - Langfuse: 访问 Web UI（:3001）
  - Temporal: 访问 UI（:8080）

- [ ] **1.4** Plane 初始化
  - 创建 Workspace（名称：daemon）
  - 创建第一个 Project
  - 生成 API Token（存入 `.env`）
  - 配置 Webhook URL（指向 daemon API 的 webhook endpoint）

---

## Phase 2：对象映射 + 胶水层

**目标**：daemon 概念 ↔ Plane 概念双向打通。

**产出文件**：
- `services/plane_client.py` — Plane REST API 薄封装
- `services/plane_webhook.py` — Webhook handler
- `services/event_bus.py` — PG LISTEN/NOTIFY（替代 Ether）
- `services/store.py` — PG 数据层（替代 Ledger JSON）

### 设计决策（需先确定再写代码）

- [ ] **2.1** Task 依赖适配策略
  - **背景**：Task 依赖直接用 Plane `IssueRelation(blocked_by)`，不是独立实体
  - **需要验证**：Plane API 是否支持 `blocked_by` 创建时自动阻止状态流转
  - **定时触发**：用 Temporal Schedule，与 Plane 无关

- [ ] **2.2** Job 存放策略
  - **背景**：Job 有独立生命周期（running→closed），Plane 无等价物
  - **方案选项**：
    - A) Job 数据写入 Plane `IssueComment`（前端可见但不够结构化）
    - B) Job 数据保留在 daemon PG 表 + Temporal workflow history（Plane 只存引用 ID）
    - C) 混合：Job 元数据在 daemon PG，Job 活动流写入 Plane IssueComment
  - **决策依据**：参考 SYSTEM_DESIGN.md §3.3 Job 生命周期、§5.3 Job 交互

### 编码任务

- [ ] **2.3** `services/plane_client.py` — Plane API 客户端
  ```
  类：PlaneClient
  初始化：api_url, api_token, workspace_slug
  方法：
    # Task（Issue）
    create_issue(project_id, title, description, ...) → Issue
    get_issue(project_id, issue_id) → Issue
    update_issue(project_id, issue_id, **fields) → Issue
    list_issues(project_id, filters={}) → List[Issue]

    # Project
    create_project(name, description) → Project
    get_project(project_id) → Project
    list_projects() → List[Project]

    # Draft（DraftIssue）
    create_draft(title, description) → DraftIssue
    list_drafts() → List[DraftIssue]
    convert_draft_to_issue(draft_id, project_id) → Issue

    # Task 依赖（IssueRelation）
    create_relation(project_id, issue_id, related_issue_id, relation_type="blocked_by")
    list_relations(project_id, issue_id) → List[Relation]

    # Job 活动（IssueComment）
    add_comment(project_id, issue_id, body) → Comment
    list_comments(project_id, issue_id) → List[Comment]

    # Webhook
    create_webhook(url, events) → Webhook
  ```
  - 用 `httpx.AsyncClient`（daemon 已在用 httpx）
  - 错误处理：4xx/5xx → 自定义异常，带 response body
  - Plane API 文档：https://developers.plane.so/

- [ ] **2.4** `services/plane_webhook.py` — Webhook handler
  ```
  FastAPI router: /webhooks/plane
  处理事件：
    issue.created → 如果来源非 daemon，同步到内部状态
    issue.updated → 状态变更时，触发 Temporal workflow（如 counsel 生成 DAG）
    issue.deleted → 清理关联 Job/Trigger
  ```
  - 注册到 `services/api.py` 的 FastAPI app
  - Webhook 签名验证（Plane 用 HMAC-SHA256）
  - 防重放：检查 `X-Plane-Delivery` header

- [ ] **2.5** `services/event_bus.py` — PG LISTEN/NOTIFY
  ```
  替代：services/ether.py（当前 JSONL append + file watcher）

  类：EventBus
  方法：
    publish(channel, payload: dict)  # NOTIFY
    subscribe(channel, callback)     # LISTEN
    unsubscribe(channel)

  频道：
    job_events — Job 状态变更
    task_events — Task 状态变更
  ```
  - 用 `asyncpg`（支持 LISTEN/NOTIFY）
  - 参考：OPEN_SOURCE_REPLACEMENT_PLAN.md §9

- [ ] **2.6** `services/store.py` — PG 数据层
  ```
  替代：Ledger JSON 文件读写

  表结构：
    jobs — id, task_id, status, sub_status, dag, requires_review, created_utc, updated_utc, closed_utc
    job_artifacts — id, job_id, step_id, artifact_type, summary, minio_path, metadata(JSONB), created_at（见 SYSTEM_DESIGN.md §3.6.1）
    knowledge_cache — 见 SYSTEM_DESIGN.md §4.6.2

  迁移：用 alembic 或手写 SQL migration 文件
  ```
  - 用 `asyncpg`（与 event_bus 共享连接池）
  - 参考：OPEN_SOURCE_REPLACEMENT_PLAN.md §6

---

## Phase 3：执行层适配

**目标**：执行链路从 JSON 文件读写切换到 Plane API + PG。

**改动文件**：
- `temporal/activities.py` — 主要改动点
- `temporal/activities_exec.py` — Step 执行
- `temporal/activities_herald.py` — 删除
- `temporal/workflows.py` — 少量改动
- `services/cadence.py` — 删除
- `services/herald.py` — 删除
- `spine/routines_ops_*.py` — 删除（替换为 1 个定时清理 Job）

### 具体任务

- [ ] **3.1** Activities 改写
  - `temporal/activities.py` 和 `temporal/activities_exec.py`
  - 所有 `folio_writ.xxx()` 调用 → `plane_client.xxx()` 或 `store.xxx()`（Task/Project/Trigger/Job）
  - 所有 `ledger.xxx()` 调用 → `store.xxx()`
  - 所有 `ether.publish()` → `event_bus.publish()`
  - **逐个函数改，每改一个跑一次相关测试**

- [ ] **3.2** Cadence → Temporal Schedules
  - 删除 `services/cadence.py`（~400 行）
  - 在暖机/启动时注册 Temporal Schedules（参考 OPEN_SOURCE_REPLACEMENT_PLAN.md §4.3 的 Python SDK 示例）
  - 当前 Spine routines 及频率（参考 `config/spine_registry.json`）：
    - record: 30min — 记录系统状态
    - maintenance: 6h — 清理过期数据
    - ops_learn: 需要的话保留（但知识层重构后可能删）
  - 自适应调度：保留逻辑，通过 `handle.update()` 修改 Schedule spec

- [ ] **3.3** Herald → envoy（OC 原生 channel + MCP）
  - 删除 `services/herald.py`（~200 行）
  - 删除 `temporal/activities_herald.py`
  - 删除 `interfaces/telegram/adapter.py` 中的 Herald 依赖
  - **Telegram 通知**：envoy 直接用 OC 原生 Telegram channel（announce 机制），不需要 MCP server
  - **GitHub 操作**：envoy 通过 MCP server（`@modelcontextprotocol/server-github`）
  - **原则**：OC 原生支持的出口用 OC channel，不支持的才用 MCP server

- [ ] **3.4** Trail → Langfuse
  - 在 Worker 进程启动时初始化 Langfuse client
  - 在 Activity 中用 `langfuse.start_as_current_observation()` 包装 agent 调用
  - 参考 OPEN_SOURCE_REPLACEMENT_PLAN.md §5.3 的代码示例
  - 删除旧 Trail 代码

- [ ] **3.5** Vault/Offering → MinIO
  - 文件上传/下载改用 `minio` Python SDK 或 `boto3`
  - Bucket 结构：`offerings/{job_id}/{filename}`
  - MinIO endpoint 从 `.env` 读取

---

## Phase 4：知识层 + 记忆层

**目标**：Mem0 记忆 + NeMo Guardrails 安全 + RAGFlow 知识检索 + Firecrawl 网页获取。

**参考**：`OPEN_SOURCE_REPLACEMENT_PLAN.md` §14-§19（第二轮开源替代）

**产出文件**：
- `config/guardrails/` — NeMo Guardrails Colang 规则（替代 psyche/instinct.py）
- `config/mem0.py` — Mem0 配置和初始化
- PG migration: `knowledge_cache` 表

### 4A. NeMo Guardrails（替代 InstinctEngine）

- [ ] **4.1** 安装 NeMo Guardrails
  - `pip install nemoguardrails`
  - 在 Worker 进程启动时初始化

- [ ] **4.2** 翻译 Instinct 规则为 Colang DSL
  - 从 `.ref/DESIGN_QA.md` 和 SYSTEM_DESIGN.md §4.2 提取核心规则
  - 硬规则：安全边界、Tier C 来源检查、敏感词过滤、token 预算
  - 软规则：质量底线、专业标准
  - 写入 `config/guardrails/*.co`

- [ ] **4.3** 删除旧 InstinctEngine
  - 删除 `psyche/instinct.py`（如存在）
  - Worker 进程中所有 `instinct_engine.check_*()` 调用替换为 NeMo rail

### 4B. Mem0（承载 Persona）

- [ ] **4.4** 安装和配置 Mem0
  - `pip install mem0ai`
  - 配置使用现有 PG + pgvector 作为后端
  - `config/mem0.py`：初始化代码

- [ ] **4.5** Persona 冷启动内容写入 Mem0
  - AI 身份和人格 → Mem0 semantic memory（agent 级）
  - 写作风格 → Mem0 procedural memory（envoy agent 级）
  - 用户偏好 → Mem0 semantic memory（user 级）
  - 规划经验 → Mem0 procedural memory（counsel agent 级）

- [ ] **4.6** 按需注入逻辑
  - Step 执行前 Mem0 按需检索相关记忆（~50-200 tokens）
  - 删除旧 psyche/ 目录全部代码

### 4C. RAGFlow + Firecrawl（替代 SourceCache）

- [ ] **4.8** RAGFlow Docker 部署
  - 在 `docker-compose.yml` 中添加 RAGFlow + Elasticsearch
  - 验证启动和 API 可用

- [ ] **4.9** Firecrawl Docker 部署
  - 在 `docker-compose.yml` 中添加 Firecrawl
  - 验证网页抓取功能

- [ ] **4.10** 知识获取 MCP tools
  - 实现 `firecrawl_scrape(url)` MCP tool
  - 实现 `semantic_scholar_search(query)` MCP tool
  - 实现 `semantic_scholar_paper(paper_id)` MCP tool
  - 注册到 `config/mcp_servers.json`

- [ ] **4.11** knowledge_cache PG 表
  - 创建 migration（schema 见 SYSTEM_DESIGN.md §4.6.2）
  - tend routine 改为清理 knowledge_cache 过期条目 + 同步删除 RAGFlow 文档

- [ ] **4.12** 删除旧 SourceCache 代码

### 4D. 代码理解工具

- [ ] **4.13** tree-sitter 代码索引 MCP tool
  - Python 库 `tree-sitter` + 语言 parser
  - MCP tool：`code_functions(file)`, `code_callers(function_name)`, `code_structure(directory)`
  - 注册到 `config/mcp_servers.json`

### 4E. 论文输出工具

- [ ] **4.14** LaTeX 编译 MCP tool
  - shell command 封装
  - Direct Step（零 token）

- [ ] **4.15** BibTeX 引用管理 MCP tool
  - 工具函数：`bibtex_add(entry)`, `bibtex_format(style)`
  - Direct Step（零 token）

- [ ] **4.16** 图表生成 MCP tool
  - matplotlib / mermaid 封装
  - Direct Step（零 token）

### 4F. 清理

- [ ] **4.17** 1 个定时清理 Job（Temporal Schedule）
  - 清理 knowledge_cache 过期条目（同步删除 RAGFlow 文档）
  - 清理 Mem0 90 天未触发记忆（标记候选，用户确认后删除）
  - Quota reset
  - 替代原有 7 个 Spine routines

- [ ] **4.18** 删除旧代码
  - `spine/` 目录全部删除
  - `psyche/` 目录全部删除
  - `config/spine_registry.json` 删除
  - retinue.py 删除（OC 原生 session 替代）
  - 旧 Ledger JSON 文件操作删除
  - cadence.py（Phase 3 已删，确认清理干净）

---

## Phase 5：Agent 层

**目标**：7 agents 就绪，envoy 对外出口通畅，Mem0 记忆初始化。

**Agent 列表**：counsel / scout / sage / artificer / scribe / arbiter / envoy

**默认模型**（counsel 可覆盖）：
- scout → fast (MiniMax M2.5)
- sage → analysis (Qwen Max)
- artificer → fast (MiniMax M2.5)
- scribe → creative (GLM Z1 Flash)
- arbiter → review (Qwen Max)
- counsel → fast (routing) / analysis (项目规划，Qwen Max)
- envoy → fast (MiniMax M2.5)

### 具体任务

- [ ] **5.1** OC workspace 配置验证
  - 每个 agent 的 `openclaw/workspace/{agent}/TOOLS.md` 内容正确
  - 每个 agent 的 skills 配置正确
  - **注意**：openclaw/ 不在 git 里（含 API key），但必须检查

- [ ] **5.2** OC prompt caching 配置
  - `openclaw.json` 中配置 `cacheRetention: "long"`
  - 配置 heartbeat `every: "55m"`
  - 配置 contextPruning `mode: "cache-ttl", ttl: "5m"`
  - 验证缓存命中率（cache trace diagnostics）

- [ ] **5.3** envoy 出口配置
  - **Telegram**：通过 OC 原生 Telegram channel（announce），不需要 MCP server
  - **GitHub**：通过 MCP server（`@modelcontextprotocol/server-github`）
  - **其他出口**：按需加 MCP server（OC 原生不支持的才用 MCP）

- [ ] **5.4** envoy 端到端验证
  - envoy 通过 OC Telegram channel 发送一条测试通知
  - envoy 通过 GitHub MCP server 创建一个测试 issue
  - 确认两条链路都通畅

- [ ] **5.5** Mem0 agent 记忆初始化
  - 初始记忆从暖机 Stage 1 的 Persona 标定结果写入 Mem0
  - envoy：写作风格 → procedural memory
  - counsel：规划经验 → procedural memory
  - worker：identity 摘要 → semantic memory
  - **注意**：subagent 不加载 MEMORY.md，Mem0 记忆通过 Worker 注入 session context

- [ ] **5.6** MCP tools 端到端验证
  - Firecrawl：worker 抓取一个网页 → 干净 Markdown
  - Semantic Scholar：worker 搜索一篇论文 → 结构化结果
  - RAGFlow：上传一个 PDF → 分块 → 检索 → 命中
  - tree-sitter：worker 查询代码结构 → 函数列表
  - LaTeX：worker 编译一个测试文档 → PDF

---

## Phase 6：暖机 = 系统标定

**完整方案**：`.ref/_work/WARMUP_AND_VALIDATION.md`（已完成）

**暖机不是初始化，是图灵测试级标定。** 目标：daemon 所有对外输出达到"伪人"水准。

由 counsel 全程主导，5 个 Stage：
1. **信息采集**：收集用户身份/写作样本/偏好/平台/任务示例（~15min）
2. **Persona 标定**：LLM 分析样本 → Mem0 persona → 试写验证（~20min）
3. **链路逐通**：17 条数据链路逐条验证（~30min）
4. **测试任务套件**：8-15 个真实复合场景，迭代到连续 5 个通过（~2-3h）
5. **系统状态测试**：10 个异常场景（并发/超时/故障恢复/积压...）（~30min）

收敛标准：**伪人度** — 连续 5 个不同类型任务的对外产出与用户本人无法区分。

---

## Phase 3.5：执行模型改进

**目标**：补齐 4 项执行模型 gap，对齐前沿研究（LLMCompiler、GoalAct、Plan-and-Act）。

**参考**：SYSTEM_DESIGN.md §3.5-§3.8

**产出文件**：
- `temporal/workflows.py` — Job workflow 改造（Step 并行、Replan Gate）
- counsel system prompt — routing decision 输出格式 + replan prompt

### 3.5A. Routing Decision（任务复杂度自适应）

- [ ] **3.5.1** counsel routing decision prompt
  - counsel system prompt 增加 routing decision 输出格式
  - 三条路径：direct / task / project
  - **不硬编码决策逻辑**，counsel 自行判断
  - 参考 SYSTEM_DESIGN.md §3.8

- [ ] **3.5.2** API 层支持 routing
  - daemon API 接收用户输入 → 发给 counsel → 按 route 创建不同结构
  - direct: 直接创建单 Step Job
  - task: 创建 Task + Job
  - project: 创建 Project + Task DAG + 首个 Job

### 3.5B. Step 并行执行

- [ ] **3.5.3** counsel 输出 Step 依赖关系
  - counsel 规划 Job 时输出 `depends_on` 字段
  - 格式：`{"id": 1, "goal": "...", "model": "fast", "depends_on": []}`

- [ ] **3.5.4** Job Workflow 改造
  - `temporal/workflows.py` 中 Job Workflow 从串行改为 DAG 并行
  - 按 `depends_on` 拓扑排序分层，同层并行执行
  - Temporal 原生支持，用 `asyncio.gather`

### 3.5C. Dynamic Replanning

- [ ] **3.5.5** Replan Gate Activity
  - 新建 `temporal/activities_replan.py`
  - Job closed → counsel 轻量判断（偏离了吗？~200 tokens）
  - 偏离 → counsel 完整重规划（输出 Task DAG diff ~800 tokens）
  - 未偏离 → 继续触发下游 Task

- [ ] **3.5.6** Project Task DAG 动态修改
  - `store.py` 支持替换 Project 中未执行的 Task
  - Plane API 同步（创建新 Issue、删除/归档旧 Issue）

### 3.5D. Step 失败处理

- [ ] **3.5.7** Step 级别重试 + counsel 判断
  - Temporal RetryPolicy 配置（自动重试）
  - Retry exhausted → counsel 判断：跳过 / 替换 / 终止
  - counsel 标记 requires_review 时支持 Temporal Signal 人工介入

---

## 删除清单（随各 Phase 执行）

### 第一轮（Phase 0-3）

| 文件/模块 | 行数 | 替换为 | Phase |
|---|---|---|---|
| `interfaces/portal/` | ~3500 | Plane 前端 | 0（归档） |
| `services/folio_writ.py` | ~800 | `plane_client.py` + `store.py`（Task/Project/Trigger CRUD） | 2 |
| `services/cadence.py` | ~400 | Temporal Schedules | 3 |
| `services/herald.py` | ~200 | envoy + MCP | 3 |
| `temporal/activities_herald.py` | ~100 | envoy + MCP | 3 |
| `services/api_routes/portal_shell.py` | ~300 | Plane API | 2 |
| `services/api_routes/console_*.py` | ~600 | Plane 管理界面 | 2 |
| Ledger JSON 读写逻辑 | ~600 | `store.py`（PG） | 2 |
| Ether JSONL 事件 | ~300 | `event_bus.py`（PG LISTEN/NOTIFY） | 2 |
| Trail 追踪 | ~200 | Langfuse | 3 |

### 第二轮（Phase 4-5）

| 文件/模块 | 替换为 | Phase |
|---|---|---|
| `psyche/` 目录全部 | NeMo Guardrails + Mem0 | 4 |
| `spine/` 目录全部 | 1 个定时清理 Job（Temporal Schedule） | 4 |
| `config/spine_registry.json` | 删除 | 4 |
| `retinue.py` | OC 原生 session | 4 |
| SourceCache 自写 RAG 代码 | RAGFlow + knowledge_cache | 4 |
| 旧 Ledger JSON 操作 | Langfuse + PG | 4 |

---

## 注意事项

### 执行顺序
- **Phase 0 → 1 → 2 → 3**：严格顺序，每步依赖前一步
- **Phase 3.5**：执行模型改进，依赖 Phase 3 完成
- **Phase 4 和 5**：可并行，不依赖 Phase 3 的完成
- **Phase 6**：暖机+诊断，单独文档，Phase 0-5 + 3.5 全部完成后执行

### 双层系统
- 每改一处 Python 代码，检查 `openclaw/workspace/*/TOOLS.md` 和 `openclaw/openclaw.json` 是否需要同步
- openclaw/ 不在 git 里，但它是代码库的一部分

### 测试
- 每个 Phase 完成后跑 `pytest tests/`
- Phase 2-3 期间旧测试会大面积失败——这是预期的，边改边修
- Phase 6 的诊断测试是最终验证（数百个检查点，详见暖机文档）

### 许可证
- Plane: AGPL-3.0（自用无限制，修改源码对外服务须开源）
- MinIO: AGPL-3.0（同上）
- Langfuse: MIT（ee/ 目录除外）

### 模型使用提示
- 本文档设计为可被不同 AI 模型阅读和执行
- 每个任务包含具体文件路径、代码结构、参考文档
- 如果不确定某个设计决策，优先查阅 SYSTEM_DESIGN.md
- 术语不确定时查 SYSTEM_DESIGN.md §1（旧术语表 `.ref/TERMINOLOGY.md` 已过期）
