# Daemon 系统设计参考文档

> **状态**：七稿配套（两层 agent 架构）
> **日期**：2026-03-15
> **定位**：`SYSTEM_DESIGN.md` 的查表用配套文档。包含参数表、字段表、接口契约、标签汇总、Gap 注册表和设计决策日志。
> **权威关系**：如本文与 `SYSTEM_DESIGN.md` 正文矛盾，以正文为准。

---

## 附录 B：运行时参数默认值

### B.1 Temporal / Step 时间参数

| 参数 | 默认值 | 来源 | 说明 |
|---|---|---|---|
| Step timeout（search 类） | 60s | §3.4 | `runTimeoutSeconds` |
| Step timeout（writing 类） | 180s | §3.4 | `runTimeoutSeconds` |
| Step timeout（review 类） | 90s | §3.4 | `runTimeoutSeconds` |
| Job Workflow execution_timeout | 暖机时校准 | G-2-013 | 防止 Workflow 永远不结束 |
| Step Activity schedule_to_close_timeout | 暖机时校准 | G-2-014 | 含排队时间 |
| Step Activity start_to_close_timeout | 暖机时校准 | G-2-014 | 不含排队时间 |
| RetryPolicy initial_interval | 1s | G-2-015 | 首次重试间隔 |
| RetryPolicy backoff_coefficient | 2.0 | G-2-015 | 指数退避 |
| RetryPolicy maximum_interval | 60s | G-2-015 | 最大退避 |
| RetryPolicy maximum_attempts | 3 | G-2-015 | 最大重试次数 |
| Temporal Schedule timezone | UTC | G-2-016 | 统一时区 |
| Temporal Schedule jitter_window | 60s | G-2-017 | 防止批量同时触发 |
| Temporal Schedule catch_up_window | 1h | G-2-076 | 宕机恢复后补执行窗口 |

### B.2 OC / Session 参数

| 参数 | 默认值 | 来源 | 说明 |
|---|---|---|---|
| `maxSpawnDepth` | 2 | §3.4 | orchestrator 模式 |
| `maxChildrenPerAgent` | 5 | §3.4 | 每 session 最大并发子 agent |
| `maxConcurrent` | 8 | §3.4 | 全局并发 session 上限 |
| `contextPruning` cache-ttl | 5 min | §3.4 | 裁剪旧 tool results |
| MEMORY.md 上限 | ≤ 300 tokens | §3.3 | 每 agent 静态内容 |
| SKILL_GRAPH.md | 每 agent 1 份 | §9.2.1 | 有向导航图，session 注入当前 skill 邻居 |
| Session 固定 overhead 上限 | ≤ 800 tokens | §3.3 | MEMORY.md + Mem0 + Step 指令 + Skill Graph 邻居 |

### B.2.1 模型路由配置

运行时配置文件（§2.8）：

| 配置文件 | 路径 | 用途 |
|---|---|---|
| `model_registry.json` | `config/model_registry.json` | 模型定义：alias → provider + model_id + endpoint |
| `model_policy.json` | `config/model_policy.json` | 路由策略：agent_model_map + task_model_map + budget_limits |

云端模型（API）：

| 别名 | Provider | 模型 | Agent | 计费 |
|---|---|---|---|---|
| `fast` | MiniMax | MiniMax-M2.5 | L1×4, engineer, publisher | Coding Plan ¥49/月 |
| `analysis` | 阿里云 | Qwen3.5-Plus | researcher | 按 token |
| `review` | 智谱 | GLM-5 | reviewer, admin | 按 token |
| `creative` | 智谱 | GLM-5 | writer | 按 token（同 review） |
| `fallback` | MiniMax | MiniMax-M2.5 | — | 包月 |

本地模型（Ollama，原生安装，非 Docker）：

| 别名 | 模型 | 用途 | 速度（M4 Pro） |
|---|---|---|---|
| `local-heavy` | qwen2.5:32b | triage, replan, compression, extraction | ~10 tok/s |
| `local-light` | qwen2.5:7b | classification, guardrails, quick judgment | ~35 tok/s |
| `local-embedding` | nomic-embed-text | embedding primary（768d） | ~47ms |

DeepSeek（dormant）：registry 保留 `deepseek-reasoner` 条目，但不在 `provider_route` 中，无 agent 使用。65K context + 无 temperature，适用场景已被 Qwen3.5-Plus（1M context）覆盖。

Python 调用入口：`services/llm_local.py`（chat / generate / embed / healthy / resolve_task_model）。

### B.3 Mem0 参数

| 参数 | 默认值 | 来源 | 说明 |
|---|---|---|---|
| 单次检索上限 | 5 条 | §5.5 | 暖机后可调 |
| 记忆清理阈值 | 90 天未触发 | §1.7 | 标记候选，用户确认后删除 |
| agent_id 枚举 | copilot / mentor / coach / operator / researcher / engineer / writer / reviewer / publisher / admin / user_persona | §1.4, G-2-043 | 4 L1 + 6 L2 + user_persona 供全局检索 |

### B.4 Plane 回写参数

| 参数 | 默认值 | 来源 | 说明 |
|---|---|---|---|
| 回写重试次数 | 5 | §6.6 | 指数退避 |
| 回写失败标记字段 | `plane_sync_failed` | §3.5 | 补偿流程异步追平 |

### B.4.1 本地后台任务参数

| 参数 | 默认值 | 来源 | 说明 |
|---|---|---|---|
| 蒸馏频率（merge） | 每日 | §5.9.1 | memory_merge + memory_gc |
| 蒸馏频率（distill） | 每周 | §5.9.1 | memory_distill + persona_deep_analysis + planning_consolidate |
| 知识审查频率 | 每周 | §5.9.2 | knowledge_audit + artifact_review |
| 信源可靠性评估 | 每月 | §5.9.2 | source_credibility + cross_project_mining |
| 系统自省频率 | 每周 | §5.9.3 | skill_effectiveness + failure_pattern + weekly_digest |
| 任务超时 | 30 分钟 | §5.9.4 | 超时跳过，不阻塞 |
| 资源优先级 | 实时 > 后台 | §5.9.4 | Ollama 队列串行，实时优先 |
| 报告存储路径 | `state/background_reports/` | §5.9.3 | admin 体检读取 |

### B.5 知识层参数

| 参数 | 默认值 | 来源 | 说明 |
|---|---|---|---|
| knowledge_cache TTL Tier A | 90 天 | §5.6.1 | arxiv、官方文档 |
| knowledge_cache TTL Tier B | 30 天 | §5.6.1 | Wikipedia、MDN |
| knowledge_cache TTL Tier C | 7 天 | §5.6.1 | Reddit、匿名来源 |
| 检索偏置 | 先 project_id 再全局 | §5.6.1 | 减少跨项目污染 |

### B.6 体检与告警阈值

| 参数 | 默认值 | 来源 | 说明 |
|---|---|---|---|
| reviewer 通过率告警 | < 80% | §7.7.3 | YELLOW/RED |
| Skill token 超标告警 | > baseline 150% | §7.7.3 | 需定位具体 skill |
| 伪人度评分告警 | < 4/5 | §7.7.3 | 触发 skill 重校准 |
| Skill 失败率审查线 | > 20% | §9.7 | 触发 skill 审查 |
| Skill activation rate 合格线 | ≥ 80% | §9.5.1 | 暖机 Stage 3 前置检查，< 80% 必须修改 description |
| Skill description 字符预算 | 30000 | §9.5.1 | `SLASH_COMMAND_TOOL_CHAR_BUDGET`，默认 15000 不够 |
| SKILL.md 行数上限 | 500 行 | §9.5.1 | 超过则拆分为多个 skill |
| Skill activation 测试次数 | ≥ 3 次/skill | §9.5.1 | 暖机 Stage 3 前置，Langfuse 确认实际执行 |
| 体检周期 | 每周 | §7.7 | Temporal Schedule |

### B.7 MCP Server 配置

完整 MCP server 清单（§2.6.1）。配置文件：`config/mcp_servers.json`。

| MCP Server | 传输方式 | 命令/包 | 环境变量 | 优先级 |
|---|---|---|---|---|
| brave-search | stdio | `@anthropic-ai/mcp-server-brave-search` | `BRAVE_API_KEY` | P0 |
| semantic-scholar | stdio | `mcp_servers/semantic_scholar.py` | `S2_API_KEY` | P0 |
| firecrawl | stdio | `mcp_servers/firecrawl_scrape.py` | `FIRECRAWL_URL` | P0 |
| github | stdio | `@modelcontextprotocol/server-github` | `GITHUB_TOKEN` | P0 |
| filesystem | stdio | `@anthropic-ai/mcp-server-filesystem` | — | P0 |
| code-functions | stdio | `mcp_servers/code_functions.py` | — | P0 |
| paper-tools | stdio | `mcp_servers/paper_tools.py` | — | P0 |
| playwright | stdio | `@anthropic-ai/mcp-server-playwright` | — | P0 |
| google-calendar | stdio | `mcp_servers/google_calendar.py` | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | P0 |
| google-docs | stdio | `mcp_servers/google_docs.py` | （共享 Google OAuth） | P0 |
| google-drive | stdio | `mcp_servers/google_drive.py` | （共享 Google OAuth） | P0 |
| gmail | stdio | `mcp_servers/gmail.py` | （共享 Google OAuth） | P1 |
| rss-reader | stdio | `mcp_servers/rss_reader.py` | — | P1 |
| zotero | stdio | 社区包 `mcp-server-zotero`（npm） | `ZOTERO_API_KEY` | P1 |
| openalex | stdio | `mcp_servers/openalex.py` | —（免费无 auth） | P1 |
| intervals-icu | stdio | `mcp_servers/intervals_icu.py` | `INTERVALS_API_KEY` | P1 |
| twitter-x | stdio | `mcp_servers/twitter.py` | `TWITTER_BEARER_TOKEN` | P1 |
| reddit | stdio | `mcp_servers/reddit.py` | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET` | P1 |
| hackernews | stdio | `mcp_servers/hackernews.py` | — | P1 |
| arxiv | stdio | `mcp_servers/arxiv.py` | — | P1 |
| matplotlib | stdio | `mcp_servers/matplotlib_chart.py` | — | P1 |
| mermaid | stdio | `mcp_servers/mermaid_chart.py` | — | P1 |
| echarts | stdio | `apache/echarts-mcp`（npm 官方包） | — | P1 |
| kroki | stdio | `mcp_servers/kroki_chart.py` | `KROKI_URL`（默认 `https://kroki.io`，可自部署） | P1 |
| languagetool | stdio | `mcp_servers/languagetool.py` | `LANGUAGETOOL_URL`（self-hosted Docker） | P1 |
| devto | stdio | `mcp_servers/devto.py` | `DEVTO_API_KEY` | P1 |
| hashnode | stdio | `mcp_servers/hashnode.py` | `HASHNODE_TOKEN` | P1 |
| unpaywall | stdio | `mcp_servers/unpaywall.py` | `UNPAYWALL_EMAIL`（免费，需邮箱） | P1 |
| crossref | stdio | `mcp_servers/crossref.py` | —（免费无 auth） | P1 |
| openweathermap | stdio | 社区包 `mcp-openweathermap`（npm） | `OPENWEATHERMAP_API_KEY` | P1 |
| strava | stdio | `mcp_servers/strava.py` | `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET` | P1 |
| dblp | stdio | 社区包 `mcp-dblp`（npm） | — | P1 |
| academix | stdio | 社区包 `Academix`（npm） | — | P1 |
| huggingface | stdio | `mcp_servers/huggingface.py` | —（推荐 `HF_TOKEN`） | P1 |
| libraries-io | stdio | `mcp_servers/libraries_io.py` | `LIBRARIES_IO_API_KEY` | P1 |
| leetcode | stdio | 社区包 `@jinzcdev/leetcode-mcp-server`（npm） | `LEETCODE_SESSION`（可选，提交历史用） | P1 |
| macos-control | stdio | `mcp_servers/macos_control.py` | — | P1 |
| latex | stdio | `mcp_servers/latex_compile.py` | — | P2 |
| typst | stdio | `mcp_servers/typst_compile.py` | — | P2 |
| docker | stdio | `mcp_servers/docker_ctl.py` | — | P2 |
| core | stdio | `mcp_servers/core.py` | `CORE_API_KEY` | P2 |
| excalidraw | stdio | 社区包 `excalidraw-mcp`（npm） | — | P2 |
| newsdata | stdio | `mcp_servers/newsdata.py` | `NEWSDATA_API_KEY` | P2 |
| kaggle | stdio | `mcp_servers/kaggle.py` | `KAGGLE_USERNAME`, `KAGGLE_KEY` | P2 |

Google 四件套共享同一个 GCP project OAuth credential。小红书/微信公众号通过 playwright MCP 处理（无独立 MCP server）。

### B.8 信息监控参数

| 参数 | 默认值 | 来源 | 说明 |
|---|---|---|---|
| 学术/博客拉取频率 | 每 4 小时 | §2.7.1 | arXiv, 业界博客, 技术博客, 权威机构 |
| 社区拉取频率 | 每 2 小时 | §2.7.1 | HN, Reddit, Twitter/X |
| 开源拉取频率 | 每 6 小时 | §2.7.1 | GitHub releases/trending |
| 天气拉取频率 | 每 3 小时 | §2.7.1 | OpenWeatherMap（户外运动天气） |
| 运动数据拉取频率 | 每日 | §2.7.1 | intervals.icu |
| 权威机构拉取频率 | 每日 | §2.7.1 | NIST, IEEE, ACM |

---

## 附录 C：PG 表结构（草案）

> 以下为实现时的参考结构。字段类型和约束以实际迁移文件为准。

### C.1 daemon_tasks

Task 扩展表，与 Plane Issue 一对一关联。

```sql
CREATE TABLE daemon_tasks (
    task_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plane_issue_id  UUID NOT NULL UNIQUE,       -- Plane Issue UUID
    project_id      UUID,                        -- 关联 Project（可选）
    trigger_type    TEXT NOT NULL DEFAULT 'manual',  -- manual / timer / chain
    schedule_id     TEXT,                        -- Temporal Schedule ID（timer 类型时）
    chain_source_task_id UUID,                   -- 前序 Task（chain 类型时）
    dag             JSONB,                       -- Task 级 DAG 定义（Project 内）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### C.2 jobs

```sql
CREATE TABLE jobs (
    job_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES daemon_tasks(task_id),
    workflow_id     TEXT NOT NULL,                -- Temporal Workflow ID
    status          TEXT NOT NULL DEFAULT 'running',   -- running / closed
    sub_status      TEXT NOT NULL DEFAULT 'queued',    -- queued / executing / paused(资源等待) / retrying / succeeded / failed / cancelled
    is_ephemeral    BOOLEAN NOT NULL DEFAULT false,    -- route="direct" 时为 true
    requires_review BOOLEAN NOT NULL DEFAULT false,
    dag_snapshot    JSONB NOT NULL,               -- Job 创建时快照，不可变
    plane_sync_failed BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ
);

CREATE INDEX idx_jobs_task_id ON jobs(task_id);
CREATE INDEX idx_jobs_status ON jobs(status);
```

### C.3 job_steps

```sql
CREATE TABLE job_steps (
    step_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(job_id),
    step_index      INTEGER NOT NULL,             -- DAG 中的 Step 序号
    goal            TEXT NOT NULL,
    agent_id        TEXT,                          -- 执行 agent（agent 类型时）
    execution_type  TEXT NOT NULL DEFAULT 'agent', -- agent / direct / claude_code / codex
    model_hint      TEXT,                          -- 可选 model override
    depends_on      INTEGER[] DEFAULT '{}',        -- 依赖的 step_index 列表
    status          TEXT NOT NULL DEFAULT 'pending', -- pending / running / completed / failed / skipped / pending_confirmation
    skill_used      TEXT,                          -- 实际使用的 skill 名称（agent 记录）
    input_artifacts TEXT[],                        -- 上游 Artifact 引用
    token_used      INTEGER,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    error_message   TEXT
);

CREATE INDEX idx_job_steps_job_id ON job_steps(job_id);
```

### C.4 job_artifacts

```sql
CREATE TABLE job_artifacts (
    artifact_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id          UUID NOT NULL REFERENCES jobs(job_id),
    step_id         UUID REFERENCES job_steps(step_id),
    artifact_type   TEXT NOT NULL,                 -- text / code / document / data / image
    title           TEXT,
    summary         TEXT,                          -- ≤ 200 tokens 摘要
    minio_path      TEXT NOT NULL,                 -- MinIO 对象路径
    mime_type       TEXT,
    size_bytes      BIGINT,
    source_markers  JSONB,                         -- [EXT:url] / [INT:persona] 标记
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_job_artifacts_job_id ON job_artifacts(job_id);
```

### C.5 knowledge_cache

```sql
CREATE TABLE knowledge_cache (
    cache_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url      TEXT NOT NULL,
    source_tier     CHAR(1) NOT NULL,              -- A / B / C
    project_id      UUID,                          -- 项目偏置（可选）
    title           TEXT,
    content_summary TEXT,
    ragflow_doc_id  TEXT,                          -- RAGFlow 文档 ID
    embedding       vector(1024),                  -- 智谱 embedding-3
    expires_at      TIMESTAMPTZ NOT NULL,           -- TTL 按 source_tier 计算
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_kc_source_url ON knowledge_cache(source_url);
CREATE INDEX idx_kc_project ON knowledge_cache(project_id);
CREATE INDEX idx_kc_expires ON knowledge_cache(expires_at);
CREATE INDEX idx_kc_embedding ON knowledge_cache USING ivfflat (embedding vector_cosine_ops);
```

### C.6 event_log

```sql
CREATE TABLE event_log (
    event_id        BIGSERIAL PRIMARY KEY,
    channel         TEXT NOT NULL,                  -- job_events / step_events / webhook_events / system_events
    event_type      TEXT NOT NULL,                  -- 具体事件类型
    payload         JSONB NOT NULL,
    consumed_at     TIMESTAMPTZ,                    -- NULL = 未消费
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_event_log_channel ON event_log(channel) WHERE consumed_at IS NULL;
```

### C.7 conversation_messages

L1 场景对话的完整消息记录（4 层压缩的第 1 层）。

```sql
CREATE TABLE conversation_messages (
    message_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene           TEXT NOT NULL,                  -- copilot / mentor / coach / operator
    role            TEXT NOT NULL,                  -- user / assistant / system
    content         TEXT NOT NULL,
    token_count     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_conv_msg_scene ON conversation_messages(scene, created_at);
```

### C.8 conversation_digests

L1 对话摘要（4 层压缩的第 2 层）。当 conversation_messages 超过阈值时，daemon 压缩为摘要。

```sql
CREATE TABLE conversation_digests (
    digest_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene           TEXT NOT NULL,
    time_range_start TIMESTAMPTZ NOT NULL,
    time_range_end  TIMESTAMPTZ NOT NULL,
    summary         TEXT NOT NULL,                  -- 压缩后的摘要
    token_count     INTEGER,
    source_message_count INTEGER,                   -- 原始消息数
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_conv_digest_scene ON conversation_digests(scene, created_at);
```

### C.9 conversation_decisions

L1 对话中的关键决策记录（4 层压缩的第 3 层）。从 digests 中提取的结构化决策。

```sql
CREATE TABLE conversation_decisions (
    decision_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene           TEXT NOT NULL,
    decision_type   TEXT NOT NULL,                  -- routing / preference / plan / confirmation
    content         TEXT NOT NULL,
    context_summary TEXT,                           -- 决策时的上下文摘要
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_conv_decision_scene ON conversation_decisions(scene, created_at);
```

### C.10 info_subscriptions

信息监控订阅源（§2.7.1）。全局表，不按场景分区。

```sql
CREATE TABLE info_subscriptions (
    subscription_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type     TEXT NOT NULL,                  -- rss / arxiv / github_release / hackernews / reddit / twitter / intervals
    source_url      TEXT,                            -- RSS feed URL / subreddit / repo name 等
    source_config   JSONB DEFAULT '{}',              -- 类型特定配置（关键词、分类等）
    category        TEXT,                            -- academic / industry / opensource / community / blog / social / sport / authority
    pull_interval   INTERVAL NOT NULL DEFAULT '4 hours',
    enabled         BOOLEAN NOT NULL DEFAULT true,
    last_pulled_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_info_sub_type ON info_subscriptions(source_type) WHERE enabled = true;
```

---

## 附录 D：接口契约与事件定义

### D.1 daemon API 端点

面向自建桌面客户端（§4.9）。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/scenes/{scene}/chat` | 场景对话输入（L1 agent 解析意图并执行） |
| GET | `/scenes/{scene}/chat/stream` | WebSocket：场景实时对话流（双向） |
| GET | `/scenes/{scene}/panel` | 场景面板数据（进行中任务、最近产出等） |
| GET | `/tasks/{task_id}/activity` | Task 活动流（合并所有 Job，后台数据） |
| GET | `/artifacts/{artifact_id}` | Artifact 内容 |
| GET | `/artifacts/{artifact_id}/download` | Artifact 下载 |
| GET | `/status` | 系统整体状态（客户端状态指示用） |
| GET | `/auth/google` | Google OAuth 登录 |
| GET | `/auth/github` | GitHub OAuth 登录 |
| GET | `/auth/callback` | OAuth 回调 |
| POST | `/webhooks/plane` | Plane webhook handler（签名验证，内部用） |

操作类动作（pause/resume/cancel/review）不再有独立端点。用户通过 `/scenes/{scene}/chat` 用自然语言表达，L1 解析后发送 Temporal Signal。

### D.2 Temporal Signal 枚举

| Signal 名称 | 触发者 | 作用 |
|---|---|---|
| `pause_job` | L1（用户对话触发） | Job → running/paused |
| `resume_job` | L1（用户对话触发） | running/paused → running/executing |
| `cancel_job` | L1（用户对话触发）/ admin（系统级） | Job → closed/cancelled |
| `confirmation_received` | L1（用户对话确认后） | pending_confirmation Step → 继续执行 |
| `confirmation_rejected` | L1（用户对话否定后） | pending_confirmation Step → rework / terminate |

### D.3 PG NOTIFY Channel

| Channel | 事件示例 | 订阅者 |
|---|---|---|
| `job_events` | job_created, job_closed, job_paused | daemon API (WebSocket → 客户端对话流) |
| `step_events` | step_started, step_completed, step_failed, step_pending_confirmation | daemon API (WebSocket → 客户端对话流) |
| `webhook_events` | plane_webhook_received | daemon Worker |
| `system_events` | health_check_completed, schedule_fired | daemon Worker |

### D.4 活动流记录格式

```json
{
    "id": "uuid",
    "task_id": "uuid",
    "job_id": "uuid",
    "type": "user_message | agent_result | job_boundary | step_status | action_record",
    "scene": "copilot | mentor | coach | operator",
    "content": "...",
    "actor": "user | copilot | mentor | coach | operator | researcher | ...",
    "timestamp": "ISO 8601",
    "metadata": {}
}
```

FINAL 规则（§4.5）：
- 所有用户对话和 daemon 回复写入活动流
- 系统操作（暂停、恢复、取消等由 L1 执行的动作）写入活动流，`type = "action_record"`
- 每条记录显式携带 `job_id`

### D.5 Job 状态 → Plane Issue 状态映射

| Job 主状态 | Job 子状态 | Plane Issue 状态组 |
|---|---|---|
| running | queued / executing / retrying | started |
| running | paused | started（保持，paused 仅用于资源/依赖等待，不用于用户确认） |
| closed | succeeded | completed |
| closed | failed | started（不自动标完成） |
| closed | cancelled | cancelled |

### D.7 对话流消息协议

WebSocket / SSE 对话流消息格式（§4.9）。客户端根据 `type` 字段分发到对应 view。

```json
{
    "id": "uuid",
    "scene": "copilot | mentor | coach | operator",
    "type": "text | panel_update | native_open | artifact_show | status_update | notification",
    "content": "...",
    "metadata": {}
}
```

| type | 目标 view | content 说明 | metadata 示例 |
|---|---|---|---|
| `text` | 对话 view | 对话文本 | `{"role": "assistant"}` |
| `panel_update` | 场景 panel | 更新数据 | `{"section": "tasks", "action": "refresh"}` |
| `native_open` | 原生应用 + 分屏 | URL 或文件路径 | `{"url": "https://...", "app": "browser"}` 或 `{"path": "/path/to/project", "app": "vscode"}` |
| `artifact_show` | 原生应用 + 分屏 | artifact_id（API 渲染为 HTML → 系统浏览器打开） | `{"artifact_id": "uuid", "title": "...", "render_url": "/artifacts/{id}/render"}` |
| `status_update` | 菜单栏 | 状态描述 | `{"level": "green|yellow|red"}` |
| `notification` | macOS 通知 | 通知文本 | `{"title": "...", "subtitle": "..."}` |

### D.6 废弃术语映射表

完整映射见 `SYSTEM_DESIGN.md` §1.8。此处列出代码中可能残留的旧标识符：

| 旧标识符 | 新标识符 | 搜索正则 |
|---|---|---|
| `folio` | `project` | `folio\|Folio` |
| `slip` | `task` | `slip\|Slip` |
| `writ` | （删除） | `writ\|Writ` |
| `deed` | `job` | `deed\|Deed` |
| `move` | `step` | `move\|Move` |
| `offering` | `artifact` | `offering\|Offering` |
| `psyche` | `persona` (目录) / `guardrails` (规则) | `psyche\|Psyche` |
| `instinct` | `guardrails` | `instinct\|Instinct` |
| `voice` | `persona/voice/` | 保留路径名 |
| `rations` | `quota` | `rations\|Rations` |
| `ledger` | （删除，用 Langfuse） | `ledger\|Ledger` |
| `herald` | （删除，用 publisher） | `herald\|Herald` |
| `cadence` | （删除，用 Temporal Schedule） | `cadence\|Cadence` |
| `ether` | （删除，用 PG event） | `ether\|Ether` |
| `trail` | （删除，用 Langfuse） | `trail\|Trail` |
| `scout` | `researcher`（scout→scholar→researcher） | `scout\|Scout` |
| `sage` | `researcher`（sage→scholar→researcher） | `sage\|Sage` |
| `counsel` | L1 agent（能力泛化为 4 L1 共享） | `counsel\|Counsel` |
| `scholar` | `researcher` | `scholar\|Scholar` |
| `artificer` | `engineer` | `artificer\|Artificer` |
| `scribe` | `writer` | `scribe\|Scribe` |
| `arbiter` | `reviewer` | `arbiter\|Arbiter` |
| `envoy` | `publisher` | `envoy\|Envoy` |
| `steward` | `admin` | `steward\|Steward` |

---

## 附录 E：DEFAULT 条目汇总

以下条目标记为 **[DEFAULT]**，可直接实现，参数可调但不能改语义。

| # | 章节 | 条目 | 默认值 |
|---|---|---|---|
| D-01 | §2.8 | 模型名称和 provider 绑定 | 配置化，不硬编码到厂商 SKU |
| ~~D-02~~ | ~~§3.1~~ | ~~route="direct" 的 ephemeral Job~~ | 已升级为 FINAL |
| ~~D-03~~ | ~~§3.5~~ | ~~Plane 回写失败处理~~ | 已升级为 FINAL |
| ~~D-04~~ | ~~§3.5~~ | ~~用户重新执行的语义~~ | 已升级为 FINAL（DD-47） |
| ~~D-05~~ | ~~§3.8~~ | ~~reviewer（旧称 arbiter）rework 时的 session 策略~~ | 已升级为 FINAL |
| D-06 | §3.9 | Replan Gate 输出格式 | `operations[]` diff：add / remove / update / reorder |
| ~~D-07~~ | ~~§3.11~~ | ~~Step / Job 时间预算等参数~~ | 已升级为 FINAL |
| ~~D-08~~ | ~~§4.9~~ | ~~daemon API 端点集合~~ | 已升级为 FINAL |
| ~~D-09~~ | ~~§4.2~~ | ~~桌面客户端技术选型~~ | 已升级为 FINAL |
| ~~D-10~~ | ~~§4.11~~ | ~~管理界面暴露范围（面向 CC/admin）~~ | 已升级为 FINAL |
| ~~D-11~~ | ~~§4.11~~ | ~~Persona 文件路径~~ | 已升级为 FINAL |
| D-12 | §5.5 | Mem0 单次检索上限 | 5 条 |
| ~~D-13~~ | ~~§5.6.1~~ | ~~knowledge_cache 检索偏置~~ | 已升级为 FINAL |
| D-14 | §5.8 | Quota 阈值 | 保守默认值，暖机后校准 |
| ~~D-15~~ | ~~§6.3~~ | ~~MCP server 连接策略~~ | 已升级为 FINAL |
| ~~D-16~~ | ~~§6.4~~ | ~~PG 事件总线 channels~~ | 已升级为 FINAL |
| ~~D-17~~ | ~~§6.4~~ | ~~PG 事件总线方案~~ | 已升级为 FINAL |
| ~~D-18~~ | ~~§6.5~~ | ~~Temporal 时间预算/retry~~ | 已升级为 FINAL |
| ~~D-19~~ | ~~§6.6~~ | ~~Plane 回写补偿~~ | 已升级为 FINAL |
| ~~D-20~~ | ~~§6.10~~ | ~~桌面客户端 + 菜单栏实现方式~~ | 已升级为 FINAL |
| D-21 | §6.11 | 备份保留策略 | 增量备份，90 天滚动，每日一次 |
| D-22 | §6.12 | 数据生命周期时间表 | Ephemeral 7d / Regular 30→90d / Artifact 本地 30d 缓存 + Google Drive 永久 / event_log 7d / traces 90d |
| ~~D-23~~ | ~~§6.10, §6.13~~ | ~~远程访问方案~~ | 已升级为 FINAL |
| D-24 | §4.9 | 对话流传输方案 | WebSocket 或 SSE + POST，实现阶段决定 |
| ~~D-25~~ | ~~§3.9~~ | ~~Replan 批量写入策略~~ | 已升级为 FINAL（原 U-01） |
| ~~D-26~~ | ~~§6.9~~ | ~~Schedule 丢失恢复~~ | 已升级为 FINAL（原 U-03） |
| D-27 | §6.13.1 | OAuth 实现方式 | FastAPI + authlib 或 python-social-auth，Google + GitHub provider |

---

## 附录 F：UNRESOLVED 条目汇总

以下条目标记为 **[UNRESOLVED]**，实现时不可自行发明方案，应跳过或使用最小实现并标注 TODO。

| # | 章节 | 条目 | 当前状态 |
|---|---|---|---|
| ~~U-01~~ | ~~§3.9~~ | ~~Replan 批量写入一致性~~ | 已降级为 DEFAULT（D-25） |
| ~~U-02~~ | ~~§3.11~~ | ~~多用户扩展~~ | 已正式设计（§6.13），认证首版实现，多租户路径已定 |
| ~~U-03~~ | ~~§6.9~~ | ~~Schedule 丢失恢复~~ | 已降级为 DEFAULT（D-26） |

**当前无 UNRESOLVED 条目。**

---

## 附录 G：Gap 吸收情况

GAPS.md 共 870 条实施细节 Gap（G-1 至 G-13）。以下标注各组在七稿中的覆盖情况。

| Gap 组 | 条目数 | 七稿覆盖情况 | 说明 |
|---|---|---|---|
| G-1 系统架构总览 | 25 | §2 + §6 覆盖架构与启动 | 具体参数值大部分进入附录 B 或标注"暖机时校准" |
| G-2 基础设施层 | 110 | §6 覆盖框架 | 具体 API 参数/配置值属于实现阶段细节 |
| G-3 执行层 | ~80 | §3 覆盖核心机制 | Job/Step/Task 生命周期和状态机已明确 |
| G-4 对象模型 | ~60 | §1 覆盖对象定义 | 字段级细节见附录 C |
| G-5 Agent 层 | ~50 | §1.4 + §9 覆盖 | 10 agent 规格（4 L1 + 6 L2）+ Skill 体系 |
| G-6 OC Gateway / 通信 | ~40 | §6.3 覆盖 | Session 管理和 MCP 分发 |
| G-7 暖机与体检 | ~80 | §7 完整覆盖 | 5 阶段 + 17 链路 + 体检 + 自愈 |
| G-8 安全与配额 | ~50 | §5.2 + §5.8 覆盖 | Guardrails + Quota |
| G-9 Skill 体系 | ~60 | §9 完整覆盖 | Skill 结构/粒度/生命周期/更新规则 |
| G-10 可观测性与自愈 | ~60 | §7.6-§7.12 覆盖 | 追溯链 + 自愈三层 + 问题文件 |
| G-11 禁止事项与边界 | ~35 | §10 完整覆盖 | 43 条禁止事项 |
| G-12 交互与界面契约 | ~120 | §4 覆盖 | Task/Project 页面骨架 + API 契约 |
| G-13 术语与文档规范 | ~100 | §0 + §1.8 覆盖 | 治理规则 + 废弃术语 |

**Gap 状态定义**：
- **设计已覆盖**：七稿正文或本附录已给出明确方案或默认值
- **实现阶段决定**：七稿定义了框架和语义，具体参数/格式在编码时确定
- **暖机时校准**：需要真实环境数据才能确定的参数

完整 Gap 注册表见 `.ref/_work/GAPS.md`。

---

## 附录 H：完整 Gap 注册表

> 完整内容（870 条）存放在 `.ref/_work/GAPS.md`，不在本文内联。
>
> 格式：`G-{章节}-{序号}: 描述`
>
> 实现者在编码每个模块前，应查阅对应 Gap 组，确认每条 Gap 的处理策略（设计已覆盖 / 实现阶段决定 / 暖机时校准）。

---

## 附录 I：设计决策日志

每条记录格式：`决策编号 | 日期 | 决策内容 | 理由 | 状态`

| # | 日期 | 决策 | 理由 | 状态 |
|---|---|---|---|---|
| DD-01 | 2026-03-13 | Plane 替代自建 Portal/Console | 减少 70% 前端代码，获得成熟的 Project/Issue 管理 | FINAL |
| DD-02 | 2026-03-13 | PostgreSQL 替代 Ledger JSON + Ether JSONL | 事务一致性、查询能力、与 Plane 共用实例 | FINAL |
| DD-03 | 2026-03-13 | Temporal 替代 Cadence | 行业标准 workflow 编排，原生支持 Schedule/Signal/Retry | FINAL |
| DD-04 | 2026-03-13 | Langfuse 替代 Trail | 专业 LLM 可观测性，零自建成本 | FINAL |
| DD-05 | 2026-03-13 | MinIO 替代 Vault 自管路径 | S3 兼容，Plane/Langfuse 可共用 | FINAL |
| DD-06 | 2026-03-13 | PG LISTEN/NOTIFY 替代 Ether | 零额外服务，event_log 提供持久化 | FINAL |
| DD-07 | 2026-03-13 | publisher 通过 OC 原生 Telegram channel | 有原生出口就用原生，不自建旁路 | FINAL |
| DD-08 | 2026-03-13 | Mem0 替代 psyche snapshot + Voice + Preferences | 省 90% token，统一记忆管理 | FINAL |
| DD-09 | 2026-03-13 | NeMo Guardrails 替代 InstinctEngine | 零 token，代码层确定性执行 | FINAL |
| DD-10 | 2026-03-13 | RAGFlow 替代 SourceCache 自写 RAG | 专业文档解析，支持表格/图表/公式 | FINAL |
| DD-11 | 2026-03-13 | Firecrawl 网页→干净 Markdown | 省 80%+ token vs 原始 HTML | FINAL |
| DD-12 | 2026-03-13 | 对象模型精简为 6 个（Project/Draft/Task/Job/Step/Artifact） | Draft 用 Plane DraftIssue，Trigger 降级为组合实现 | FINAL |
| DD-13 | 2026-03-13 | scout + sage 合并为 researcher | 搜索+分析是连续认知动作，分拆增加信息损耗 | FINAL |
| DD-14 | 2026-03-13 | 新增 admin agent（原 steward） | 系统自维护独立为 L2 agent | FINAL |
| DD-15 | 2026-03-13 | 删除 settling 状态 | 默认 no-wait，需审查时 L1 标记 requires_review | FINAL |
| DD-16 | 2026-03-13 | 1 Step = 1 目标（非 1 Agent + 1 交付物） | Step 粒度按语义边界分，不按 agent 分 | FINAL |
| DD-17 | 2026-03-13 | 删除自建 Extract/dag_templates/project_templates | Mem0 + Langfuse 替代 | FINAL |
| DD-18 | 2026-03-13 | 7 Spine routines → 1 定时清理 Job | Temporal Schedule 统一调度 | FINAL |
| DD-19 | 2026-03-13 | 全部自造隐喻术语替换为业界通用 | 降低认知负担，消除翻译歧义 | FINAL |
| DD-20 | 2026-03-14 | L1 自行判断 routing（不硬编码规则） | LLM 擅长语义判断，规则分类反而脆弱 | FINAL |
| DD-21 | 2026-03-14 | Step 依赖关系 DAG + 并行执行 | 减少总执行时间，参考 LLMCompiler | FINAL |
| DD-22 | 2026-03-14 | Replan Gate（动态重规划） | 防止偏离后仍按原计划浪费 token | FINAL |
| DD-23 | 2026-03-14 | Step 失败 Temporal 原生 checkpoint | Worker crash 后已完成 Step 不重复执行 | FINAL |
| DD-24 | 2026-03-14 | 新增 claude_code / codex execution_type | 复杂修复/编码场景直接调用 CLI，绕过 OC | FINAL |
| DD-25 | 2026-03-14 | cc/codex Activity 注入 MEMORY.md + skill | 绕过 OC 但保持上下文精准 | FINAL |
| DD-26 | 2026-03-14 | reviewer 三层触发策略 | NeMo(全量零token) + L1标记 + 对外强制，平衡成本和质量 | FINAL |
| DD-27 | 2026-03-14 | L1 不感知 skill | 解耦规划层和执行层，skill 增删不影响 L1 | FINAL |
| DD-28 | 2026-03-14 | Persona 路径 persona/voice/*.md | 不是 psyche/voice/，psyche 已废弃 | FINAL |
| DD-29 | 2026-03-14 | 三层自愈（admin→CC/Codex→用户转发） | 用户操作最小化，系统尽量自己解决 | FINAL |
| DD-30 | 2026-03-14 | 用户体验原则（§0.9）：无阻塞、无段落感、无内部感知 | 用户说做 X，X 就做了，不需要了解系统如何运作 | FINAL |
| DD-31 | 2026-03-14 | 自治原则（§0.10）：系统级变更由 CC/Codex 审查 | 没有可靠的人做系统审查，用户只管品味和形象 | FINAL |
| DD-32 | 2026-03-14 | 外部工具 Handoff 机制（§3.12） | daemon 生成 CLAUDE.md/AGENTS.md，通过 direct Step 打开 VSCode | FINAL |
| DD-33 | 2026-03-14 | 自愈拆分为 4 个 Temporal Activity | 解决 CC 重启服务时杀掉自身宿主进程的耦合问题 | FINAL |
| DD-34 | 2026-03-14 | 灾难恢复链（§7.12）：launchd→start.py→Docker→Temporal replay | start.py 为万能冷启动恢复点 | FINAL |
| DD-35 | 2026-03-14 | 前沿驱动自我迭代（§7.7.3 + §9.9） | 每周体检先查最新研究再决策，避免凭经验闭门造车 | FINAL |
| DD-36 | 2026-03-14 | macOS 自启动 + menu bar app（§6.10） | launchd plist 开机启动，menu bar 提供最简交互 | FINAL |
| DD-37 | 2026-03-14 | 备份系统（§6.11）：PG + MinIO + git，30 天滚动 | 类 Time Machine 策略，Temporal Schedule 触发 | FINAL |
| DD-38 | 2026-03-14 | 数据生命周期（§6.12）：分层归档删除 | ~25 tasks/day 量级，防止存储无限增长 | FINAL |
| DD-39 | 2026-03-14 | Skill 先看前沿再设计（§9.5） | 禁止凭经验从零设计 skill，必须先 researcher 搜索 | FINAL |
| DD-40 | 2026-03-14 | Skill 持续演进（§9.9）：性能驱动+前沿驱动双触发 | Skill 是活文档，不是写完就结束 | FINAL |
| DD-41 | 2026-03-14 | 用户界面 = 自建极简桌面客户端，Plane 降级为后端 | 用户不需要知道 Plane 存在，对话是唯一操作通道 | FINAL |
| DD-42 | 2026-03-14 | ~~客户端三 view：对话+浏览器+阅读器~~ | ~~覆盖所有用户场景，无需其他 UI~~ → **已被 DD-78 取代**（Tauri + 原生应用打开，不再内嵌 view） | SUPERSEDED |
| DD-43 | 2026-03-14 | 删除所有操作按钮，全部通过对话完成 | 符合 §0.9 用户体验原则，消除段落感和系统感知 | FINAL |
| DD-44 | 2026-03-14 | requires_review 非阻塞化（§4.8） | Job 不暂停，对话中自然确认，超时由 L1 自决 | FINAL |
| DD-45 | 2026-03-14 | 冷启动通过对话完成，CC 可预置 Persona（§5.3.2） | 用户不需要准备材料，对话即初始化 | FINAL |
| DD-46 | 2026-03-14 | 远程访问：Tailscale Funnel + 密码认证（§6.10.3） | 零额外基础设施，远程设备无需装 VPN | FINAL |
| DD-47 | 2026-03-14 | rerun 意图由 L1 自行判断，不硬编码为否定（§3.5） | 意图是连续谱，LLM 擅长语义判断 | FINAL |
| DD-48 | 2026-03-14 | Re-run 最小化重做范围（§3.6.2） | 不重跑整个流程，只做需要改的部分 | FINAL |
| DD-49 | 2026-03-14 | 两层方法论架构：SOUL.md（哲学）+ SKILL.md（行为）（§9.10.1） | 哲学指导行为，两层都必须可操作化 | FINAL |
| DD-50 | 2026-03-14 | 方法论必须落地到 OC 配置（§9.10） | 设计文档写了但 OC 没写等于没写 | FINAL |
| DD-51 | 2026-03-14 | 方法论设计必须先看前沿（§9.10.3） | 与 §9.5 同一原则，覆盖哲学层和行为层 | FINAL |
| DD-52 | 2026-03-14 | 每周体检覆盖 SOUL.md + SKILL.md（§9.10.4） | 哲学层也需要演进，但比行为层更慎重 | FINAL |
| DD-53 | 2026-03-14 | ~~桌面客户端改用 Electron（§4.2）~~ | ~~浏览器 view 需 Chromium 兼容性~~ → **已被 DD-78 取代**（Tauri + 原生分屏） | SUPERSEDED |
| DD-54 | 2026-03-14 | 备份改增量 + 90 天保留（§6.11） | 全量 × 90 天占用过大（460GB SSD），增量控制总量 | FINAL |
| DD-55 | 2026-03-14 | Google Drive 为 Artifact 持久存储层（§6.12.1） | 2TB Google Drive 空间，本地 MinIO 只做 30 天缓存 | FINAL |
| DD-56 | 2026-03-14 | 常规 Job 生命周期缩短到 90 天（§6.12.2） | Key Artifact 在 Google Drive 永久保留，Job 元数据 90 天足够 | FINAL |
| DD-57 | 2026-03-14 | OAuth 认证为首版必备（§6.13.1） | Google/GitHub OAuth，不做简单密码；远程访问安全性要求 | FINAL |
| DD-58 | 2026-03-14 | 多用户扩展路径设计（§6.13.2） | 所有表预留 user_id，基础设施按需扩展；不堵死但不本轮实现 | DEFAULT |
| DD-59 | 2026-03-15 | 两层 agent 架构：4 L1 场景 + 6 L2 执行 | 场景-角色-行为分离，L1 面向用户持久对话，L2 面向任务一次性执行 | FINAL |
| DD-60 | 2026-03-15 | counsel 消失，能力泛化为 L1 共享基础 | routing/DAG/Replan/意图解析不再由单一 agent 持有 | FINAL |
| DD-61 | 2026-03-15 | L1 session 在 API 进程持久运行 | 非 Temporal，daemon 管理 OC session 压缩，70% contextTokens 触发 | FINAL |
| DD-62 | 2026-03-15 | 4 层对话压缩：messages→digests→decisions→Mem0 | L1 持久对话需要压缩管理，4 层逐级提炼 | FINAL |
| DD-63 | 2026-03-15 | 4 个独立 Telegram Bot（每场景一个） | 4 Bot Token，4 DM 联系人，与桌面端完全同步 | FINAL |
| DD-64 | 2026-03-15 | ~~桌面客户端 3 显示模式：对话/场景面板/浏览器~~ | ~~对话是主要交互，面板提供场景概览，浏览器处理外部内容~~ → **已被 DD-78 取代**（2 展示模式：对话+panel，外部内容由原生应用打开） | SUPERSEDED |
| DD-65 | 2026-03-15 | scene 作为过滤列而非硬分区 | 跨场景查询（daemon 注入等）需要，不做物理隔离 | FINAL |
| DD-66 | 2026-03-15 | 暖机分工：CC 主导 Stage 0-2，admin 主导 Stage 3+ | admin 不能暖机自己，基础设施验证由 CC 完成 | FINAL |
| DD-67 | 2026-03-15 | L2 agent 重命名为业界通用角色名 | scholar→researcher, artificer→engineer 等，降低认知负担 | FINAL |

| DD-68 | 2026-03-16 | 信息监控是系统级基础设施，不属于任何场景（§2.7.1） | 场景定义关系不定义职责（§0.11），信息不应按场景硬分区 | FINAL |
| DD-69 | 2026-03-16 | InfoPullWorkflow：direct(拉取) → agent(筛选) → direct(存储/通知)（§2.7.1） | 拉取和存储零 token，只有筛选需要 LLM | FINAL |
| DD-70 | 2026-03-16 | 46 个 MCP server 分 P0/P1/P2 三批（§2.6.1） | P0=系统核心，P1=核心场景，P2=按需（含 DD-77 扩展后总计 46 个） | FINAL |
| DD-71 | 2026-03-16 | 对话流消息协议：type 字段分发到不同 view（§4.9） | 统一协议覆盖对话/panel/浏览器/阅读器/编辑器/通知 | FINAL |
| DD-72 | 2026-03-16 | Zotero + RAGFlow 互补文献管理（§2.7.1） | Zotero 管元数据(收藏/引用)，RAGFlow 管全文检索，全局基础设施 | FINAL |
| DD-73 | 2026-03-16 | 桌面客户端规格确定（§4.2, §6.10.2） | 同构前端，P0-P3 分阶段交付，零按钮设计（DD-78 更新为 Tauri） | FINAL |
| DD-74 | 2026-03-16 | Skill Graph：per-agent 有向导航图（§9.2.1） | skill 从 flat list 变有向图，入口匹配+沿边走，session 注入当前 skill+邻居，不跨 agent | FINAL |
| DD-75 | 2026-03-16 | code_exec MCP tool：Step 内代码执行（§3.13） | 封装 CC/Codex CLI，按 skill 需要配置，CC/Codex 各限 1 并发，初始配 engineer/researcher/admin | FINAL |
| DD-76 | 2026-03-17 | Skill 可靠性保障机制（§9.5.1） | OC 架构 skill activation rate ~50%（已知问题），强制祈使句 description 提升至 ~95%，CI 校验 YAML + 字符预算 + 行数上限，暖机前置 activation 测试 | FINAL |
| DD-77 | 2026-03-17 | 外部资源扩展（§2.6.1, §5.6） | +10 MCP servers（LanguageTool/OpenWeatherMap/Dev.to/Hashnode/ECharts/Kroki/Unpaywall/CrossRef），博客三渠道发布，英文写作辅助闭环 | FINAL |
| DD-78 | 2026-03-17 | 桌面客户端 Electron→Tauri + 原生应用调起（§4.2, §6.10.2） | Tauri（系统 WKWebView，~10MB）替代 Electron（~200MB）。外部内容不再内嵌（BrowserView/阅读器/Monaco 全部取消），改用系统浏览器/VS Code/Preview.app 原生调起。消息协议 browser_navigate/editor_open/vscode_launch 统一为 native_open | FINAL |
| DD-79 | 2026-03-17 | 多平台策略：macOS + iOS + Telegram（§4.10, §6.10.3） | 不做 Web 端/PWA/远程浏览器访问。macOS Tauri = 完整主控台；iOS Tauri = Artifact 只读查看器（类 Steam app）；Telegram = 信箱+对讲机（daemon→用户通知，用户→daemon 快捷回复）。单向同步：Telegram→本地（本地对话不推送到 Telegram） | FINAL |
| DD-80 | 2026-03-17 | 取消自动分屏，窗口布局交给 Stage Manager（§4.2） | 自动分屏（macos-control MCP 编排窗口位置）与 macOS Stage Manager 冲突：多个 scene 同时打开不同应用时分屏逻辑不清晰。daemon 只负责 open 目标应用/文件，窗口布局由用户通过 Stage Manager 自行管理。macos-control MCP 从"窗口编排"降级为"应用调起"（仅 open 命令） | FINAL |
| DD-81 | 2026-03-17 | Obsidian vault 作为用户知识图谱（§5.7.1） | Markdown 产出（报告/文章/笔记）写入 Obsidian vault（Google Drive），二进制文件留 MinIO。只放用户产出（researcher/writer/engineer/mentor），不放系统产出（admin/operator → state/background_reports/）。MCP: @bitbonsai/mcpvault（文件系统直接操作）。Zotero Integration 插件联动论文标注 | FINAL |
| DD-82 | 2026-03-17 | Graph-native Skill 存储：openclaw-graph（§9.2.1.1） | Skill Graph 从平面 SKILL_GRAPH.md 迁移到 Neo4j 图数据库。参考 alphaonedev/openclaw-graph。动机：平面文件全量加载 token 浪费（25K→660 bytes）、SKILL_GRAPH.md 不可扩展（100+ skill）、activation rate 问题。Skill/SkillCluster 节点 + IN_CLUSTER/RELATED_TO 边 + Cypher 按需查询。Neo4j 加入 Docker Compose | FINAL |

---

*参考文档结束。正文见 `SYSTEM_DESIGN.md`。*
