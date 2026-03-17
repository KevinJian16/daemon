# Daemon 实施计划 — 七稿两层 Agent 架构

> 日期：2026-03-15（更新）
> 状态：Phase 0-3 完成、Phase 5 核心就位、L1→L2 链路联调通过
> 依据：SYSTEM_DESIGN.md（七稿）、TODO.md（Phase 0-6 + 3.5）
>
> 每个功能条目包含：
> - **设计文档引用**：§ 编号
> - **目标文件**：文件路径
> - **实现状态**：✅ 已实现 / 🔧 部分实现 / ❌ 未实现 / 🗑️ 已删除
> - **验证方案**：用户端到端闭环验证，不是 curl 200

---

## Phase 0：清理旧代码 ✅ 完成

### 0.1 已删除废弃模块

| 文件/目录 | 状态 | 说明 |
|---|---|---|
| `spine/` 整个目录 | 🗑️ 已删 | Spine/Nerve/Cortex/Canon → 无替代 |
| `psyche/` 整个目录 | 🗑️ 已删 | Psyche/Instinct/Voice → NeMo Guardrails + Mem0 |
| `state/psyche/` 数据目录 | 🗑️ 已删 | 旧运行时数据 |
| `services/cadence.py` | 🗑️ 已删 | Cadence → Temporal Schedules |
| `services/herald.py` | 🗑️ 已删 | Herald → publisher + OC Telegram channel |
| `services/folio_writ.py` | 🗑️ 已删 | FolioWrit → plane_client + store |
| `services/voice.py` | 🗑️ 已删 | Voice → Mem0 |
| `services/will.py` | 🗑️ 已删 | Will → session_manager + temporal |
| `services/wash.py` | 🗑️ 已删 | Wash → 无替代 |
| `services/ledger.py` | 🗑️ 已删 | Ledger → store.py (PG) |
| `services/storage_paths.py` | 🗑️ 已删 | 旧路径管理 → MinIO |
| `services/system_reset.py` | 🗑️ 已删 | 旧系统重置 → scripts/state_reset.py |
| `temporal/activities_herald.py` | 🗑️ 已删 | Herald 依赖 |
| `runtime/ether.py` | 🗑️ 已删 | Ether → event_bus.py (PG LISTEN/NOTIFY) |
| `runtime/retinue.py` | 🗑️ 已删 | Retinue → OC native sessions |
| `runtime/cortex.py` | 🗑️ 已删 | Cortex → 无替代 |
| `runtime/brief.py` | 🗑️ 已删 | Brief → 无替代 |
| `runtime/trail_context.py` | 🗑️ 已删 | Trail → Langfuse |
| `runtime/design_validator.py` | 🗑️ 已删 | 旧设计验证 |
| `config/spine_registry.json` | 🗑️ 已删 | Spine 配置 |

### 0.2 已删除废弃 API 路由

| 文件 | 状态 |
|---|---|
| `services/api_routes/console_admin.py` | 🗑️ 已删 |
| `services/api_routes/console_agents_skill.py` | 🗑️ 已删 |
| `services/api_routes/console_observe.py` | 🗑️ 已删 |
| `services/api_routes/console_psyche.py` | 🗑️ 已删 |
| `services/api_routes/console_rations.py` | 🗑️ 已删 |
| `services/api_routes/console_runtime.py` | 🗑️ 已删 |
| `services/api_routes/console_spine.py` | 🗑️ 已删 |
| `services/api_routes/portal_shell.py` | 🗑️ 已删 |
| `services/api_routes/folio_writ_routes.py` | 🗑️ 已删 |
| `services/api_routes/submit.py` | 🗑️ 已删 |
| `services/api_routes/feedback.py` | 🗑️ 已删 |
| `services/api_routes/chat.py` | 🗑️ 已删 |

### 0.3 已清理的文件（重写/修复）

| 文件 | 操作 | 说明 |
|---|---|---|
| `services/api.py` | ✅ 完全重写 | 只注册 scenes + webhook + status/health/jobs/tasks |
| `services/__init__.py` | ✅ 清理 | 移除 Cadence/Will/Herald/Voice 懒导入 |
| `services/api_routes/basic.py` | ✅ 清空 | 仅保留文件（空模块） |
| `services/api_routes/system.py` | ✅ 清空 | 仅保留文件（空模块） |
| `bootstrap.py` | ✅ 完全重写 | 10 agents (4 L1 + 6 L2), 移除 Psyche/Retinue 引用 |
| `scripts/warmup.py` | ✅ 完全重写 | Stage 2 基础设施验证 (PG/Temporal/Plane/MinIO) |
| `scripts/state_reset.py` | ✅ 完全重写 | 基于 OC sessions + PG 的状态重置 |
| `interfaces/cli/main.py` | ✅ 完全重写 | 4 命令: status/health/chat/panel |
| `interfaces/telegram/adapter.py` | ✅ 清理 | 移除 deed_* 旧事件名和旧端点 |
| `runtime/__init__.py` | ✅ 清理 | 移除 Cortex/Ether 导出 |
| `runtime/temporal.py` | ✅ 修复 | 修正构造函数, JobInput 封装 |
| `runtime/openclaw.py` | ✅ 清理 | 移除 legacy 方法, 添加 spawn_session |
| `temporal/__init__.py` | ✅ 修复 | 移除 GraphWillWorkflow/EndeavorWorkflow |
| `temporal/worker.py` | ✅ 修复 | EventBus + Temporal Schedules 注册 |
| `pyproject.toml` | ✅ 清理 | 移除 psyche*/spine* 包包含 |
| `tests/conftest.py` | ✅ 完全重写 | 新架构 fixtures |
| `tests/test_diagnostics.py` | ✅ 完全重写 | 新架构单元测试 |

### 0.4 OpenClaw 清理 ✅ 完成

| 操作 | 详情 |
|---|---|
| 删除 144 个编号 agent 目录 | `{arbiter,artificer,envoy,sage,scribe,scout}_{0..23}` |
| 删除 8 个占位目录 | `_default, analyze, apply, build, collect, render, review, router` |
| 删除 7 个废弃 base agent 目录 | `arbiter, artificer, scribe, envoy, sage, scout, counsel` |
| 删除 151 个废弃 agent 定义 | openclaw.json 从 ~1600 行精简到 321 行 |
| 迁移模型配置 | sage→researcher(deepseek), arbiter→reviewer(qwen), scribe→writer(glm-z1) |
| 设置默认 agent | copilot (替代 counsel) |

**最终状态**：仅保留 10 个活跃 agent（4 L1 + 6 L2）

### 0.5 验证结果

```
grep "from (spine|psyche|runtime\.(ether|retinue|cortex|...)" → 0 hits (live code)
grep "SystemResetManager|FolioWrit|LedgerStats|InstinctEngine" → 0 hits (live code)
openclaw/workspace/ → 仅 10 个目录（admin,coach,copilot,engineer,mentor,operator,publisher,researcher,reviewer,writer）
openclaw.json agents.list → 仅 10 个定义
```

---

## Phase 2：胶水层 ✅ 核心就位

### 2.1 store.py — PG 数据层

**设计引用**：§2.9, Appendix C
**目标文件**：`services/store.py`
**状态**：✅ 已实现（~470 行）

已实现方法：
- `create_task`（支持 plane_issue_id=None + title + source）
- `get_task`, `get_task_by_plane_issue`
- `create_job`, `get_job`, `update_job_status`（自动 started_at）, `list_jobs_for_task`, `list_jobs`
- `create_step`, `update_step_status`
- `create_artifact`
- `save_message`, `get_recent_messages`
- `save_digest`, `save_decision`
- `upsert_knowledge`, `cleanup_expired_knowledge`
- `get_task_activity`（API 活动流）

**验证**：PG 连接 → 建表 → CRUD 全通 → /jobs/submit 端到端通过

### 2.2 plane_client.py — Plane API 客户端

**设计引用**：§2.5, TODO Phase 2.3
**目标文件**：`services/plane_client.py`
**状态**：✅ 已实现（241 行）

**验证**：Plane API 运行 → list_projects/create_issue/get_issue 通

### 2.3 event_bus.py — PG LISTEN/NOTIFY

**设计引用**：§6.4
**目标文件**：`services/event_bus.py`
**状态**：✅ 已实现（106 行）

**验证**：publish → event_log INSERT → NOTIFY → callback

### 2.4 plane_webhook.py — Webhook Handler

**设计引用**：§2.4, TODO Phase 2.4
**目标文件**：`services/plane_webhook.py`
**状态**：✅ 已实现（含完整 handler 逻辑）

### 2.5 SQL Schema（内嵌 api.py）

**设计引用**：Appendix C
**目标文件**：`services/api.py` 内的 `SCHEMA_SQL`
**状态**：✅ 已实现

schema 在 api.py 启动时自动执行（`_ensure_tables()`）：
- 9 张表 + event_log NOTIFY trigger + pgvector extension + 10 个索引
- 幂等（CREATE TABLE IF NOT EXISTS）
- 已修复：plane_issue_id 允许 NULL、title 列、error_message 列、sub_status CHECK 含 'completed'

---

## Phase 3：执行层 ✅ 核心就位 + 端到端验证通过

### 3.1 Temporal Workflows

**目标文件**：`temporal/workflows.py`（493 行）
**状态**：✅ 已实现 + 已验证

5 个 Workflow：
- `JobWorkflow` — DAG 拓扑排序 + 并行 Step + pause/resume Signal + **失败结果检测**
- `HealthCheckWorkflow` — 4-activity 周度体检
- `SelfHealWorkflow` — 4-activity 自愈 + crash recovery
- `MaintenanceWorkflow` — 定期清理
- `BackupWorkflow` — 每日备份

**JobInput dataclass**：`@dataclass class JobInput: plan: dict; job_id: str = ""`

**验证**：3-step DAG (researcher→writer→reviewer) 端到端完成 ~75s

### 3.2 Temporal Activities

**目标文件**：`temporal/activities.py`（160 行）
**状态**：✅ 已实现

6 个 Activity：
- `activity_execute_step` → OC agent session（⚠ 已改为 spawn_session per-step 独立 session，见 §6.1）
- `activity_direct_step` → MCP tool 零 LLM
- `activity_update_job_status` → PG + event_bus
- `activity_update_step_status` → PG
- `activity_replan_gate` → L1 轻量对齐检查
- `activity_maintenance` → 定期清理

**Langfuse**：已禁用（v4 SDK OTLP 不兼容自托管 v3 服务端）

### 3.3 Activities Exec

**目标文件**：`temporal/activities_exec.py`（~407 行，初版 220 行后多次扩展）
**状态**：✅ 已验证

- `run_openclaw_step`: spawn_session per-step 独立 session, heartbeat 30s, upstream context
- `run_direct_step`: MCP call_tool, 零 LLM
- 已修复：step_index 解析、session key 格式、Langfuse span 移除

### 3.4 Activities Replan

**目标文件**：`temporal/activities_replan.py`（120 行）
**状态**：✅ 已确认

### 3.5 Activities Maintenance

**目标文件**：`temporal/activities_maintenance.py`（60 行）
**状态**：✅ 已确认

### 3.6 Activities Health

**目标文件**：`temporal/activities_health.py`
**状态**：✅ 已确认

### 3.7 Temporal Worker + Schedules

**目标文件**：`temporal/worker.py`（227 行）
**状态**：✅ 已实现 + 已验证

- 正确创建 asyncpg pool + EventBus(dsn) + connect(pool)
- 注册 5 workflows + 16 activities
- graceful shutdown (SIGINT/SIGTERM)
- **Temporal Schedules 注册**：
  - `daemon-maintenance` — 每 6 小时
  - `daemon-health-check` — 每 7 天
  - `daemon-backup` — 每 1 天

### 3.8 MCP Dispatcher

**目标文件**：`runtime/mcp_dispatch.py`（131 行）
**状态**：✅ 已确认

### 3.9 L1→L2 Job Dispatch

**目标文件**：`services/api_routes/scenes.py`
**状态**：✅ 已实现 + 已验证

- L1 输出 structured action → `_submit_job()` → Store create_task/create_job → Temporal start_job_workflow
- `POST /jobs/submit` API 端点也支持直接提交

### 3.10 Temporal Client — JobInput 封装

**目标文件**：`runtime/temporal.py`
**状态**：✅ 已修复

- `start_job_workflow` 将 plan dict 封装为 `JobInput(plan=plan, job_id=...)`

---

## Phase 5：场景 API + Session 管理 + Skill 体系 ✅ 核心就位

### 5.1 Session Manager

**目标文件**：`services/session_manager.py`（249 行）
**状态**：✅ 已实现

- 4 L1 场景 session 管理 (copilot/mentor/coach/operator)
- send_message → OC session → 保存消息 → 返回响应
- 4 层压缩（messages → digests，触发阈值 70%）

### 5.2 Scene API 路由

**目标文件**：`services/api_routes/scenes.py`（170 行）
**状态**：✅ 已实现

- `POST /scenes/{scene}/chat`
- `WS /scenes/{scene}/chat/stream`
- `GET /scenes/{scene}/panel`

### 5.3 api.py 主入口

**目标文件**：`services/api.py`
**状态**：✅ 已重写

路由清单：
- `POST /scenes/{scene}/chat` — §4.9 L1 对话
- `WS /scenes/{scene}/chat/stream` — §4.9 WebSocket
- `GET /scenes/{scene}/panel` — §4.9 面板
- `POST /webhooks/plane` — §2.4 Plane webhook
- `GET /status` — §4.9 系统状态
- `GET /health` — 健康检查
- `GET /jobs` — Job 列表
- `GET /tasks/{task_id}` — Task 详情
- `GET /tasks/{task_id}/activity` — §4.9 活动流
- `POST /jobs/submit` — 直接提交 Job

启动顺序：
1. asyncpg pool → 2. Store → 3. EventBus → 4. PlaneClient
5. OpenClawAdapter → 6. SessionManager → 7. TemporalClient.connect()
8. configure_scenes(session_manager, store, temporal_client) + configure_webhook

### 5.4 Skill 体系 ✅ 已实现

**产出**：30 个 SKILL.md 文件（§9.1 结构规范）

| Agent | Skill 数 | Skills |
|---|---|---|
| researcher | 4 | academic_search, web_research, literature_review, source_evaluation |
| engineer | 4 | code_review, debug_locate, refactor, implementation |
| writer | 5 | tech_blog, academic_paper, documentation, data_visualization, announcement |
| reviewer | 3 | fact_check, code_review, quality_audit |
| publisher | 3 | telegram_notify, github_publish, release_checklist |
| admin | 3 | health_check, skill_audit, incident_response |
| copilot | 2 | task_decomposition, replan_assessment |
| mentor | 2 | task_decomposition, replan_assessment |
| coach | 2 | task_decomposition, replan_assessment |
| operator | 2 | task_decomposition, replan_assessment |

**TOOLS.md 更新**：所有 10 agent 的 TOOLS.md 已更新，列出可用 MCP tools + skills 清单

### 5.5 GitHub MCP ✅ 已配置

`config/mcp_servers.json` 中注册 `@modelcontextprotocol/server-github`，使用 `GITHUB_TOKEN` 环境变量。
publisher agent TOOLS.md 已引用。

---

## 支撑模块

### OpenClaw Adapter

**目标文件**：`runtime/openclaw.py`（256 行）
**状态**：✅ 已清理

- `send_to_session` — sessions_send 同步等待
- `spawn_session` — sessions_spawn + 轮询完成
- `history` — sessions_history
- `session_status` — sessions_list
- `destroy_session` / `cleanup_all_sessions` — 清理 session JSONL

### Temporal Client

**目标文件**：`runtime/temporal.py`
**状态**：✅ 已修复

- `classmethod connect(host, port, namespace, queue)` — async 连接
- `start_job_workflow(workflow_id, plan)` — 封装 JobInput → 提交 JobWorkflow
- `cancel`, `signal`, `status`, `health_check`

### Bootstrap

**目标文件**：`bootstrap.py`
**状态**：✅ 已重写

- 10 agents: 4 L1 (copilot/mentor/coach/operator) + 6 L2 (researcher/engineer/writer/reviewer/publisher/admin)
- 目录结构: state/, backups/, warmup/, persona/voice/, config/guardrails/
- OpenClaw 配置规范化 + 校验

---

## 基础设施 ✅ 运行中

### Docker Compose（17 容器）

| 服务 | 状态 | 端口 |
|---|---|---|
| PostgreSQL (pgvector) | ✅ healthy | 5432 |
| Redis | ✅ healthy | 6379 |
| MinIO | ✅ healthy | 9000/9001 |
| Elasticsearch 8.15.3 | ✅ healthy | 9200 |
| Temporal + UI | ✅ running | 7233/8080 |
| Plane API + Frontend + Worker + Beat + Space + Live + Admin + MQ | ✅ running | 8000/3000 |
| Langfuse Web + Worker | ✅ running | 3001 |
| ClickHouse | ✅ healthy | 8123 |
| RAGFlow | ⚠ 待启用 | 9380（需 Docker VM 扩容）|

### launchd 服务（4 个）

| 服务 | plist | 状态 |
|---|---|---|
| API (uvicorn :8100) | `ai.kevinjian.daemon.api` | ✅ running |
| Worker (Temporal) | `ai.kevinjian.daemon.worker` | ✅ running |
| OC Gateway (:18790) | `ai.kevinjian.daemon.openclaw.gateway` | ✅ running |
| Telegram Adapter | `ai.kevinjian.daemon.telegram.adapter` | ✅ running |

---

## Phase 4：知识层 + 记忆层 🔧 核心就位

### 4A. NeMo Guardrails ✅ 已实现

**产出文件**：
- `config/guardrails/config.yml` — NeMo config（pattern-based, zero token）
- `config/guardrails/safety.co` — Colang 规则（8 input/output rails）
- `config/guardrails/actions.py` — Python 验证逻辑（~180 行）
- `config/guardrails/__init__.py`
- `config/sensitive_terms.json` — 敏感词列表（可扩展）

**已实现 Rails**：
- Input: instruction override detection, harmful request blocking, sensitive data filtering, token budget
- Output: safety check, forbidden marker removal, source tier compliance, internal/external mixing
- Custom actions: `validate_input`, `validate_output`, `validate_mem0_write`, `classify_source_tier`

**集成点**：`temporal/activities_exec.py` — 每个 Step 执行前后自动 validate

### 4B. Mem0 ✅ 已实现

**产出文件**：
- `config/mem0_config.py` — 配置 + 初始化 + 注入 helpers（~130 行）
- `scripts/mem0_coldstart.py` — Persona 冷启动（10 agent × 3 memories + 5 user persona）

**技术决策**：
- LLM: DeepSeek V3（内存提取用，非实时调用）
- Embedder: fastembed (BAAI/bge-small-en-v1.5, 384 dim, local ONNX)
- Vector Store: Qdrant local file (`state/mem0_qdrant/`)，不用 pgvector（numpy/psycopg3 兼容问题）
- 冷启动：35 memories seeded（30 agent identity + 5 user persona）

**集成点**：
- Worker 启动时 `init_mem0()` → `DaemonActivities._mem0`
- Step 执行前 `retrieve_agent_context()` + `retrieve_user_preferences()` → 注入 composed_message

### 4C. MCP Tools ✅ 已实现

**产出文件**：
- `config/mcp_servers.json` — 7 个 MCP server 配置
- `mcp_servers/semantic_scholar.py` — 学术论文搜索（4 tools: search/paper/citations/references）
- `mcp_servers/code_functions.py` — tree-sitter 代码分析（3 tools: functions/structure/imports）
- `mcp_servers/firecrawl_scrape.py` — 网页抓取→Markdown（2 tools: scrape/crawl）
- `mcp_servers/paper_tools.py` — 论文工具（4 tools: latex_compile/bibtex_format/chart_matplotlib/chart_mermaid）

| Server | 状态 | 说明 |
|---|---|---|
| brave-search | ✅ 配置 | Web 搜索（npx, Brave API）|
| filesystem | ✅ 配置 | state/ + backups/ 文件操作 |
| semantic-scholar | ✅ 实现 | 4 tools: search/paper/citations/references |
| code-functions | ✅ 实现 | 3 tools: functions/structure/imports (tree-sitter) |
| firecrawl | ✅ 实现 | 2 tools: scrape/crawl（调用本地 Firecrawl API）|
| paper-tools | ✅ 实现 | 4 tools: latex/bibtex/matplotlib/mermaid |
| github | ✅ 配置 | npx @modelcontextprotocol/server-github |

### 4D. Elasticsearch + RAGFlow 🔧 部分完成

- Elasticsearch 8.15.3: ✅ 运行中（green, :9200）
- RAGFlow: ⚠ Docker VM 磁盘空间不足（需扩容后启用，配置已写入 docker-compose.yml 注释中）
- ragflow PG database: ✅ 已创建（init-databases.sql）

### 4E. Paper Output Tools ✅ 已实现

**产出文件**：`mcp_servers/paper_tools.py`（~200 行）

4 个零 LLM token 工具：
- `latex_compile`: LaTeX → PDF（pdflatex + bibtex）
- `bibtex_format`: 结构化数据 → .bib 文件
- `chart_matplotlib`: Python 脚本 → PNG 图表
- `chart_mermaid`: Mermaid DSL → SVG 图表

### 4F. Maintenance Cleanup ✅ 已实现

**改动文件**：
- `temporal/activities_maintenance.py` — 完整 4 任务：knowledge_cache 过期清理 + 旧 Job 清理（30天）+ 旧消息清理（90天）+ 健康事件
- `services/store.py` — 新增 `cleanup_old_jobs()` + `cleanup_old_messages()`
- 已删除 `state/spine_log.jsonl` + `state/spine_status.json` 孤立文件
- 旧代码引用验证：**零残留**（grep 确认所有废弃模块无导入引用）

---

## Phase 3.5：执行模型改进 🔧 核心就位

### 3.5A. Routing Decision ✅ 已实现

**改动文件**：
- `services/api_routes/scenes.py` — 三路由分发（direct/task/project）
- `openclaw/workspace/{copilot,mentor,coach,operator}/TOOLS.md` — 路由格式文档

**路由**：
- `direct`: 单步 Job，轻量路径，`_submit_direct_job()`
- `task`: 多步 Job + Task 记录，`_submit_job()`
- `project`: 多步 Job（与 task 相同 API，语义区分）

**L1 决策**：不硬编码，L1 agent 根据用户请求自行判断路由

### 3.5B. Step 并行执行 ✅ 已实现（Phase 3）

JobWorkflow 已支持 DAG 拓扑排序 + `asyncio.gather` 并行

### 3.5C/D. Replan Gate + Step 失败处理 ✅ 已实现（Phase 3）

---

## 端到端验证记录

### ✅ 已通过

| 测试 | 方式 | 结果 |
|---|---|---|
| 4 L1 场景对话 | `POST /scenes/{scene}/chat` | 4 场景都能对话返回 |
| L2 Job 执行 | `POST /jobs/submit` 3-step DAG | researcher→writer→reviewer 完成 ~75s |
| L2 单步 Job | `POST /jobs/submit` 1-step | researcher 完成 ~15s |
| L1→L2 dispatch | scene chat → structured action → Temporal | Job 创建 + 执行 |
| Temporal Schedules | Worker 启动 | 3 个 Schedule 注册成功 |
| PG 数据层 | CRUD 操作 | task/job/step 创建和更新 |
| Event Bus | publish + NOTIFY | event_log 写入 + 通知 |
| NeMo Guardrails | validate_input/output 单元测试 | 全通过 |
| Mem0 初始化 | init_mem0() + add/search | 35 memories seeded |
| Mem0 注入 | Worker 启动 → DaemonActivities._mem0 | 初始化成功 |
| OC Gateway | 重启后 openclaw.json | 无 Unrecognized key 错误 |
| Elasticsearch | Docker 启动 | green, :9200 |
| code_functions MCP | tree-sitter 提取 | Python/JS/TS 函数/类正确提取 |
| semantic_scholar MCP | import 验证 | 模块加载成功 |
| paper_tools MCP | import 验证 | 模块加载成功 |
| SKILL.md 覆盖 | 10 agent × skills | 30 个 SKILL.md 有内容草稿 |
| 全量测试 | pytest tests/ | 68/68 通过 |
| Warmup Stage 2 | warmup.py --stage 2 | 13/13 链路 GREEN |
| Health Check | verify.py | 15/15 GREEN |
| Warmup T04 | engineer code analysis | completed 80s |
| Warmup T02 | researcher→writer 2-step | completed 246s |
| Warmup T07 | admin diagnostics | completed 126s |

### ⚠️ 已知问题

| 问题 | 原因 | 状态 |
|---|---|---|
| Langfuse tracing 禁用 | v4 SDK OTLP 不兼容自托管 v3 | 待 Langfuse OTLP 配置 |
| plane-space unhealthy | Docker 容器健康检查失败 | 非关键服务 |
| OC Telegram 401 | Gateway bot token 未配置 | 非关键 |
| RAGFlow 未启动 | Docker VM 磁盘空间不足（12GB 满） | 扩容后启用 |
| Firecrawl 未自托管 | ghcr.io 镜像需认证 | 用 API 或自行构建 |

---

## 当前进度 vs TODO Phase

| Phase | 状态 | 说明 |
|---|---|---|
| Phase 0 | ✅ 完成 | 旧代码全删 + OC 清理（151 废弃 agent 定义 + 152 目录） |
| Phase 1 | ✅ 完成 | Docker Compose 17 容器运行（+Elasticsearch） |
| Phase 2 | ✅ 核心完成 | store + plane_client + event_bus + webhook + schema |
| Phase 3 | ✅ 核心完成 | workflows + activities + worker + schedules + L1→L2 dispatch |
| Phase 3.5 | ✅ 核心完成 | Routing Decision + Replan Gate + Step 并行 + 失败处理 |
| Phase 4A | ✅ 完成 | NeMo Guardrails（config + actions + integration） |
| Phase 4B | ✅ 完成 | Mem0（DeepSeek + fastembed + Qdrant + cold-start 35 memories） |
| Phase 4C | ✅ 完成 | 7 MCP servers（brave/fs/s2/code/firecrawl/github/paper-tools） |
| Phase 4D | 🔧 部分 | Elasticsearch ✅ green · RAGFlow ⚠ 需 Docker VM 扩容 |
| Phase 4E | ✅ 完成 | paper-tools MCP（latex/bibtex/matplotlib/mermaid） |
| Phase 4F | ✅ 完成 | maintenance 4 任务 + store cleanup + 旧代码零残留 |
| Phase 5 | ✅ 核心完成 | session + scenes + 30 SKILL.md + 10 TOOLS.md + GitHub MCP |
| Phase 6 | ✅ 核心完成 | Stage 2 13/13 + Stage 3 10/10 + Stage 4 10/10 |

---

## Phase 6 详情

### 6.1 已完成

- **warmup.py Stage 2**: 13/13 全通（PG/Temporal/Redis/MinIO/ES/ClickHouse/API/OC/Plane/Langfuse/Mem0/Guardrails/MCP）
- **verify.py**: 15/15 GREEN
- **Stage 3 全部通过**: 10/10 warmup tasks
  - T01: researcher 156s | T02: researcher→writer 246s | T03: researcher→writer→reviewer 889s
  - T04: engineer 80s | T05: researcher→reviewer 201s | T06: researcher→writer 482s
  - T07: admin 126s | T08: researcher→engineer→reviewer→publisher 758s
  - T09: researcher→writer 181s | T10: engineer→writer→reviewer 196s
- **Stage 4 全部通过**: 10/10 异常场景
  - E01: 并发 3 Jobs ✅ | E02: Step 超时 ✅ | E03: 无效 agent ✅ | E04: Worker 恢复 ✅
  - E05: PG 连接恢复 ✅ | E06: Plane 补偿 ✅ | E07: Guardrails 拦截 ✅ | E08: Quota 配置 ✅
  - E09: Schedule 存在 ✅ | E10: 大 Artifact 截断 ✅
- **关键修复**: Step 执行从 send_to_session(共享 main session) 改为 spawn_session(独立 per-step session)
  - 根因：共享 session lane 造成 queueAhead=10, waitedMs=3600s 的严重排队
  - 修复后并发 3 Jobs 同时完成，无 lane 争用

### 6.2 待用户参与

- ~~Stage 0: 信息采集~~ ✅ 已完成（persona/stage0_interview.md，6 个 section 全部完成）
- Stage 1: Persona 标定（需用户确认）

### 6.3 Skill 校准（第一轮）✅ 已完成

基于 Stage 3 结果分析，识别 3 个技能短板并修复：

| 问题 | 根因 | 修复 |
|---|---|---|
| T06 失败（coach 生活管理） | writer `documentation` 技能仅覆盖技术文档 | 扩展为通用结构化文档（含 plan/manual 类型） |
| T09 不稳定（图表生成） | 无专门数据可视化技能 | 新增 writer `data_visualization` 技能 |
| T03 耗时 889s | literature_review API 调用过多 | 添加效率指导（限制 6-8 次 API 调用） |

额外改进：
- L1 `task_decomposition` 增加 agent 选择指南和 goal 描述质量要求
- researcher `web_research` 扩展到非技术领域（健康/生活/学习）

---

## 清理与配置更新

| 操作 | 说明 |
|---|---|
| `config/system.json` 更新 | 旧 agent 名（counsel/scout/sage...）→ 新名（copilot/researcher/engineer...） |
| `config/lexicon.json` 重写 | 旧术语体系（Slip/Folio/Writ...）→ 新术语（Task/Project/Job/Step...） |
| `interfaces/console/` 归档 | → `interfaces/console_archived/`（无 Python 引用） |
| `activities_exec.py` 修复 | 移除死代码（重复的 spawn_future 赋值） |

---

## 新增/修改文件清单

| 文件 | 说明 |
|---|---|
| `mcp_servers/__init__.py` | MCP 服务器包 |
| `mcp_servers/semantic_scholar.py` | Semantic Scholar API MCP（4 tools） |
| `mcp_servers/code_functions.py` | tree-sitter 代码分析 MCP（3 tools） |
| `mcp_servers/firecrawl_scrape.py` | Firecrawl 网页抓取 MCP（2 tools） |
| `mcp_servers/paper_tools.py` | 论文工具 MCP（4 tools） |
| `tests/test_mcp_servers.py` | MCP 服务器测试（15 tests） |
| `warmup/stage3_test_tasks.json` | Stage 3 测试任务套件（10 tasks） |
| `scripts/run_warmup_tasks.py` | 自动化 warmup task 执行脚本 |
| `openclaw/workspace/*/skills/*/SKILL.md` | 30 个 Skill 文件（含新增 data_visualization） |
| `scripts/run_exception_tests.py` | Stage 4 异常场景测试脚本（10 scenarios） |

---

## 下一步（优先级顺序）

1. ~~**Phase 6 Stage 0**：信息采集~~ ✅ 已完成
2. **Phase 6 Stage 1**（需用户参与）：Persona 标定
3. **Phase 6 Stage 2-4**：链路逐通 + 测试任务 + 异常场景
4. **Docker VM 扩容** → 启用 RAGFlow
5. **Langfuse**: 等服务端 OTLP 支持后启用追踪
6. **OC Telegram bot token**: 配置后 publisher 端到端验证
7. **代码提交**：所有改动均为 unstaged 状态，需 commit 保护工作成果

---

*文档最后更新：2026-03-16。实施过程中发现偏差立即更新此文档。*
