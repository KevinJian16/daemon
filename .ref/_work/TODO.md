# Daemon 系统重建 TODO

> 日期：2026-03-13
> 状态：进行中
> 依据：`.ref/_work/OPEN_SOURCE_REPLACEMENT_PLAN.md`

**核心方针**：用成熟开源方案替代自造组件，只保留领域核心（agent 编排、执行策略、AI 人格）。
**净效果**：删除 ~7100 行自造代码，新增 ~800-1200 行胶水代码。

---

## 关键文档索引

| 文档 | 路径 | 用途 |
|---|---|---|
| 开源替代方案 | `.ref/_work/OPEN_SOURCE_REPLACEMENT_PLAN.md` | 所有替换决策的详细调查和技术方案 |
| 术语规范 | `.ref/TERMINOLOGY.md` | 全系统术语唯一依据 |
| 交互设计 | `.ref/INTERACTION_DESIGN.md` | Slip/Deed/Folio 交互行为规范 |
| 执行模型 | `.ref/EXECUTION_MODEL.md` | Move/Session/Deed/Folio 运行机制 |
| 设计 QA | `.ref/DESIGN_QA.md` | 设计决策权威（冲突时优先） |
| 旧知识层方案 | `.ref/_work/REFACTOR_KNOWLEDGE_AND_WARMUP.md` | **已被本 TODO 取代**，仅供参考 |

---

## 术语速查（给后续模型用）

| daemon 术语 | 含义 | Plane 映射 |
|---|---|---|
| Slip | 任务卡（核心工作单元） | `Issue` |
| Folio | 卷/项目（Slip 容器） | `Project` 或 `Module` |
| Draft | 草稿（未成形的 Slip） | `DraftIssue` |
| Writ | 排序/依赖链（Slip 执行顺序） | `IssueRelation(blocked_by)` + `sort_order`（弱映射） |
| Deed | 执行记录（running→settling→closed） | **无映射**，需自建 |
| Brief | 执行规格 | — |
| Move | DAG 中的一步（1 agent + 1 交付物） | — |
| Retinue | 7 个 agent 集合 | — |
| envoy | 唯一对外出口 agent | — |
| counsel | 规划 agent | — |
| Instinct | 系统硬规则（Python if/else） | — |
| Voice | AI 人格（Identity + Style markdown） | — |
| Spine | 系统维护 routines | — |
| Cadence | 定时调度（将被 Temporal Schedules 替代） | — |
| Herald | 通知投递（将被 envoy + MCP 替代） | — |
| Ether | 事件总线（将被 PG LISTEN/NOTIFY 替代） | — |
| Ledger | 状态/统计存储（将被 PostgreSQL 替代） | — |
| Trail | LLM 追踪（将被 Langfuse 替代） | — |

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
  - 创建第一个 Project（映射为默认 Folio）
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

- [ ] **2.1** Writ 适配策略
  - **背景**：Writ 是 daemon 的一等实体（有序依赖链），Plane 只有 `IssueRelation`（无序关系）
  - **方案选项**：
    - A) Plane `IssueRelation(blocked_by)` + 自定义 `sort_order` 字段 + webhook 同步
    - B) Writ 数据保留在 daemon PG 表，Plane 只管 Slip/Folio
  - **决策依据**：参考 `.ref/INTERACTION_DESIGN.md` 中 Writ 强约束规则、`.ref/EXECUTION_MODEL.md` 中下游触发机制
  - **需要验证**：Plane API 是否支持 `blocked_by` 创建时自动阻止状态流转

- [ ] **2.2** Deed 存放策略
  - **背景**：Deed 有独立生命周期（running→settling→closed），Plane 无等价物
  - **方案选项**：
    - A) Deed 数据写入 Plane `IssueComment`（前端可见但不够结构化）
    - B) Deed 数据保留在 daemon PG 表 + Temporal workflow history（Plane 只存引用 ID）
    - C) 混合：Deed 元数据在 daemon PG，Deed 活动流写入 Plane IssueComment
  - **决策依据**：参考 `.ref/EXECUTION_MODEL.md` §状态两层模型、`.ref/INTERACTION_DESIGN.md` §评价链

### 编码任务

- [ ] **2.3** `services/plane_client.py` — Plane API 客户端
  ```
  类：PlaneClient
  初始化：api_url, api_token, workspace_slug
  方法：
    # Slip（Issue）
    create_issue(project_id, title, description, ...) → Issue
    get_issue(project_id, issue_id) → Issue
    update_issue(project_id, issue_id, **fields) → Issue
    list_issues(project_id, filters={}) → List[Issue]

    # Folio（Project）
    create_project(name, description) → Project
    get_project(project_id) → Project
    list_projects() → List[Project]

    # Draft（DraftIssue）
    create_draft(title, description) → DraftIssue
    list_drafts() → List[DraftIssue]
    convert_draft_to_issue(draft_id, project_id) → Issue

    # Writ（IssueRelation）
    create_relation(project_id, issue_id, related_issue_id, relation_type="blocked_by")
    list_relations(project_id, issue_id) → List[Relation]

    # Deed 活动（IssueComment）
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
    issue.deleted → 清理关联 Deed/Writ
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
    deed_events — Deed 状态变更
    slip_events — Slip 状态变更
    spine_events — Spine routine 事件
  ```
  - 用 `asyncpg`（支持 LISTEN/NOTIFY）
  - 参考：OPEN_SOURCE_REPLACEMENT_PLAN.md §9

- [ ] **2.6** `services/store.py` — PG 数据层
  ```
  替代：Ledger JSON 文件读写

  表结构：
    deeds — id, slip_id, status, sub_status, dag, brief, created_utc, updated_utc, closed_utc
    writ_order — id, folio_id, slip_id, position, trigger_type, trigger_config
    skill_stats — agent, skill, total, accepted, avg_duration
    agent_stats — agent, total_deeds, total_moves, total_tokens
    preferences — key, value, updated_utc

  迁移：用 alembic 或手写 SQL migration 文件
  ```
  - 用 `asyncpg`（与 event_bus 共享连接池）
  - 参考：OPEN_SOURCE_REPLACEMENT_PLAN.md §6

---

## Phase 3：执行层适配

**目标**：执行链路从 JSON 文件读写切换到 Plane API + PG。

**改动文件**：
- `temporal/activities.py` — 主要改动点
- `temporal/activities_exec.py` — Move 执行
- `temporal/activities_herald.py` — 删除
- `temporal/workflows.py` — 少量改动
- `services/cadence.py` — 删除
- `services/herald.py` — 删除
- `spine/routines_ops_*.py` — 适配新数据层

### 具体任务

- [ ] **3.1** Activities 改写
  - `temporal/activities.py` 和 `temporal/activities_exec.py`
  - 所有 `folio_writ.xxx()` 调用 → `plane_client.xxx()` 或 `store.xxx()`
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

- [ ] **3.3** Herald → envoy + MCP
  - 删除 `services/herald.py`（~200 行）
  - 删除 `temporal/activities_herald.py`
  - 删除 `interfaces/telegram/adapter.py` 中的 Herald 依赖
  - 通知发送改为：在 Move 中指派 envoy agent，envoy 通过 MCP server 调用 Telegram API
  - MCP server 配置写入 `config/mcp_servers.json`（当前为空 `{"servers": {}}`）

- [ ] **3.4** Trail → Langfuse
  - 在 Worker 进程启动时初始化 Langfuse client
  - 在 Activity 中用 `langfuse.start_as_current_observation()` 包装 agent 调用
  - 参考 OPEN_SOURCE_REPLACEMENT_PLAN.md §5.3 的代码示例
  - 删除旧 Trail 代码

- [ ] **3.5** Vault/Offering → MinIO
  - 文件上传/下载改用 `minio` Python SDK 或 `boto3`
  - Bucket 结构：`offerings/{deed_id}/{filename}`
  - MinIO endpoint 从 `.env` 读取

---

## Phase 4：知识层

**目标**：新 Psyche = Instinct + Voice + Preferences + Ledger(PG) + SourceCache。

**参考**：`.ref/_work/REFACTOR_KNOWLEDGE_AND_WARMUP.md`（旧方案，架构思路仍有效，存储层需改为 PG）

**产出文件**：
- `psyche/instinct.py` — 硬规则
- `psyche/voice/identity.md` — 身份画像
- `psyche/voice/style.md` — 写作风格（scribe/envoy 用）
- `psyche/preferences.py` — 用户偏好读写（PG）

### 具体任务

- [ ] **4.1** Instinct（系统本能）
  - Python if/else 硬规则，不依赖 LLM
  - 从旧代码 `psyche/instinct.py`（如果存在）或 `.ref/DESIGN_QA.md` 提取核心规则
  - 规则类别：安全边界、质量底线、资源限制

- [ ] **4.2** Voice（AI 人格）
  - `psyche/voice/identity.md`：身份画像，注入所有 agent 的 system prompt
  - `psyche/voice/style.md`：写作风格，仅注入 scribe 和 envoy
  - 参考 `.ref/daemon_实施方案.md` 中 agent psyche injection 部分

- [ ] **4.3** Preferences（用户偏好）
  - PG 表 `preferences`（key-value）
  - 读写接口：`get_preference(key)`、`set_preference(key, value)`
  - 注入 agent context 时从 PG 读取

- [ ] **4.4** Ledger 统计层
  - PG 表 `skill_stats`、`agent_stats`
  - 只学 accepted（不学失败）— 参考 MEMORY.md "学习机制"
  - 学模式不学实例 — dag_templates + folio_templates

- [ ] **4.5** Lore → pgvector
  - PG 表 `lore_entries`（id, content, embedding vector(1024), created_utc）
  - Embedding 模型：智谱 embedding-3（见 MEMORY.md "模型策略"）
  - 搜索：余弦相似度 `1 - (embedding <=> query_vector)`
  - 参考 OPEN_SOURCE_REPLACEMENT_PLAN.md §6.2 的 SQL 示例

- [ ] **4.6** Spine routines 精简
  - 当前 9 个 → 删除 learn、distill → 7 个
  - 更新 `config/spine_registry.json`
  - 更新 `spine/routines_ops_learn.py`（删除或重写为纯统计）

- [ ] **4.7** 删除旧代码
  - 旧 Psyche Memory/Lore 实现
  - 旧 Ledger JSON 文件操作
  - 旧 SourceCache（如果有）

---

## Phase 5：Agent 层

**目标**：7 agents 就绪，envoy 对外出口通畅。

**Agent 列表**（参考 `config/system.json`）：
counsel, scout, sage, artificer, arbiter, scribe, envoy

**模型策略**（参考 MEMORY.md）：
- counsel/scout/artificer/envoy → MiniMax M2.5
- sage → DeepSeek R1
- arbiter → Qwen Max
- scribe → GLM Z1 Flash

### 具体任务

- [ ] **5.1** OC workspace 配置验证
  - 每个 agent 的 `openclaw/workspace/{agent}/TOOLS.md` 内容正确
  - 每个 agent 的 skills 配置正确
  - **注意**：openclaw/ 不在 git 里（含 API key），但必须检查

- [ ] **5.2** MCP servers 配置
  - 编辑 `config/mcp_servers.json`（当前为空）
  - 添加：
    ```json
    {
      "servers": {
        "github": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-github"],
          "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}" }
        },
        "telegram": {
          "command": "...",
          "args": ["..."],
          "env": { "TELEGRAM_BOT_TOKEN": "${TELEGRAM_BOT_TOKEN}" }
        }
      }
    }
    ```
  - Telegram MCP server：找社区方案或自己写薄包装（<100 行）
  - 验证 `runtime/mcp_dispatch.py` 能正确加载和调用

- [ ] **5.3** envoy 端到端验证
  - envoy 通过 GitHub MCP server 创建一个测试 issue
  - envoy 通过 Telegram MCP server 发送一条测试消息
  - 确认 MCP tool call → 外部 API → 结果返回完整链路

- [ ] **5.4** Agent psyche 注入
  - 每个 agent 的 MEMORY.md 内容（~25-30 行）：instinct 摘要 + identity 摘要 + 任务偏好
  - scribe/envoy 额外加 style 摘要
  - counsel 额外加 planning hints
  - **注意**：subagent 不加载 MEMORY.md（OC 限制，见 MEMORY.md "OpenClaw 关键机制备忘"）

---

## Phase 6：暖机流程

**目标**：`scripts/warmup.py`，从零到可用的一键初始化。

- [ ] **6.1** 服务连通性检查
  - PG: `SELECT 1` + `SELECT * FROM pg_extension WHERE extname='vector'`
  - Redis: `PING`
  - MinIO: `list_buckets()`
  - Temporal: `client.get_system_info()`
  - Plane: `GET /api/v1/users/me/`
  - Langfuse: health check endpoint

- [ ] **6.2** 初始化数据
  - PG: 执行 migration（创建 deeds, writ_order, skill_stats 等表）
  - MinIO: 创建 `offerings` bucket
  - Plane: 如果 Workspace 不存在则创建，如果默认 Project 不存在则创建
  - Temporal: 注册所有 Spine routine Schedules

- [ ] **6.3** Agent 暖机
  - 每个 OC agent 执行一次 `/health` 或空 prompt 验证连通
  - 验证模型策略：确认每个 agent 调用的模型正确

- [ ] **6.4** 诊断测试 `tests/test_diagnostics.py`
  - 不是单元测试，是系统级诊断
  - 检查所有外部服务连通
  - 检查 Plane 对象映射正确
  - 检查 MCP server 可调用
  - 检查 Temporal Schedule 已注册

---

## Phase 7：端到端验证

**目标**：全链路跑通，确认系统可用于实际工作。

- [ ] **7.1** 场景 A：手动 Slip 执行
  - 在 Plane 创建 Issue（Slip）→ Webhook 触发 → counsel 生成 DAG → agents 执行 Moves → Deed 完成 → 用户在 Plane 收束
  - 验证：Deed 状态变更在 Plane 可见，Langfuse 有完整 trace

- [ ] **7.2** 场景 B：Folio + Writ 依赖链
  - 创建 Folio（Project）+ 多个 Slip + Writ 依赖 → 按序执行
  - 验证：前序 Deed 未 closed 时，后序 Slip 不触发

- [ ] **7.3** 场景 C：定时触发
  - 创建一个 timer 类型 Slip → Temporal Schedule 注册 → 到时间自动执行
  - 验证：Schedule 在 Temporal UI 可见，触发正确

- [ ] **7.4** 场景 D：envoy 对外出口
  - 一个 Deed 的 Move 指派 envoy → envoy 调 GitHub MCP push 代码 + 调 Telegram MCP 发通知
  - 验证：GitHub 有 commit，Telegram 收到消息

- [ ] **7.5** 场景 E：可观测性
  - Langfuse Dashboard 可见：workflow → activity → agent session → LLM generation
  - Token 消耗、延迟、成本自动统计

- [ ] **7.6** 性能基线
  - 记录各场景端到端耗时
  - 确认 PG LISTEN/NOTIFY 延迟 < 100ms
  - 确认 Plane API 响应 < 500ms

---

## 删除清单（随各 Phase 执行）

| 文件/模块 | 行数 | 替换为 | Phase |
|---|---|---|---|
| `interfaces/portal/` | ~3500 | Plane 前端 | 0（归档） |
| `services/folio_writ.py` | ~800 | `plane_client.py` + `store.py` | 2 |
| `services/cadence.py` | ~400 | Temporal Schedules | 3 |
| `services/herald.py` | ~200 | envoy + MCP | 3 |
| `temporal/activities_herald.py` | ~100 | envoy + MCP | 3 |
| `services/api_routes/portal_shell.py` | ~300 | Plane API | 2 |
| `services/api_routes/console_*.py` | ~600 | Plane 管理界面 | 2 |
| Ledger JSON 读写逻辑 | ~600 | `store.py`（PG） | 2 |
| Ether JSONL 事件 | ~300 | `event_bus.py`（PG LISTEN/NOTIFY） | 2 |
| Trail 追踪 | ~200 | Langfuse | 3 |
| **合计** | **~7100** | | |

---

## 注意事项

### 执行顺序
- **Phase 0 → 1 → 2 → 3**：严格顺序，每步依赖前一步
- **Phase 4 和 5**：可并行，不依赖 Phase 3 的完成
- **Phase 6 → 7**：顺序执行

### 双层系统
- 每改一处 Python 代码，检查 `openclaw/workspace/*/TOOLS.md` 和 `openclaw/openclaw.json` 是否需要同步
- openclaw/ 不在 git 里，但它是代码库的一部分

### 测试
- 每个 Phase 完成后跑 `pytest tests/`
- Phase 2-3 期间旧测试会大面积失败——这是预期的，边改边修
- Phase 7 的诊断测试是最终验证

### 许可证
- Plane: AGPL-3.0（自用无限制，修改源码对外服务须开源）
- MinIO: AGPL-3.0（同上）
- Langfuse: MIT（ee/ 目录除外）

### 模型使用提示
- 本文档设计为可被不同 AI 模型阅读和执行
- 每个任务包含具体文件路径、代码结构、参考文档
- 如果不确定某个设计决策，优先查阅 `.ref/DESIGN_QA.md`
- 术语不确定时查 `.ref/TERMINOLOGY.md`
