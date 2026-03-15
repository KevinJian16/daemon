# Daemon 开源替代方案

> 日期：2026-03-13
> 状态：方案草案，待确认
> 目的：梳理 daemon 系统中哪些自造组件可以被成熟开源方案替代，降低维护成本，提升质量。
>
> **⚠ 术语注意（2026-03-13）**：本文档使用旧术语（Folio/Slip/Writ/Deed/Move/Brief/Wash）。
> 新术语（Project/Task/Trigger/Job/Step/Context/Extract）以 SYSTEM_DESIGN.md §1 为准。
> 本文档内容仍有参考价值，但术语映射请查 SYSTEM_DESIGN.md §1.8 废弃术语表。

---

## 0. 核心判断

当前 daemon 代码库中，大约 60-70% 的 Python 代码在重造已有的轮子。真正的领域核心（agent 编排、执行策略、AI 人格）只占少部分。

**原则：有现成的就用现成的，不原创。**

---

## 1. 保留不动的（领域核心）

| 组件 | 理由 |
|---|---|
| Temporal workflows + activities | 已经在用，执行引擎的正确选择 |
| OpenClaw agent 编排 | 已经在用，agent 编排层 |
| Instinct（本能规则） | Python if/else 硬规则，必须自己写 |
| Voice / Preferences | AI 人格层，markdown 文件 → agent context |
| Spine routines（核心几个） | 系统维护逻辑，收敛后保留 |

---

## 2. 替代方案总表

| 当前自造 | 替换为 | 适配度 | 节省代码量 |
|---|---|---|---|
| Portal 前端 | **Plane 前端** | 高 | ~3000 行 JSX 全部替换 |
| FolioWrit（CRUD + 状态机） | **Plane 后端** | 中高 | ~800 行 |
| Ledger（JSON 文件 + fcntl 锁） | **PostgreSQL**（Plane 自带） | 高 | ~600 行 |
| Ether（JSONL 事件总线） | **PostgreSQL LISTEN/NOTIFY** 或 **Redis pub/sub** | 高 | ~300 行 |
| Cadence（定时调度） | **Temporal Schedules** | 中高 | ~400 行 |
| Herald（通知投递） | **删除，envoy + MCP servers 替代**（见 §8） | 高 | ~200 行 |
| Trail（追踪） | **Langfuse** | 高 | ~200 行 |
| Vault / Offering 文件存储 | **MinIO** | 高 | ~150 行 |
| Lore 向量搜索 | **pgvector** | 高 | 不用自写相似度检索 |
| Console 前端 | 删除，Plane 管理界面覆盖 | 高 | ~1000 行 |

---

## 3. Plane — 任务管理 + 前端

### 3.1 基本信息

| 项目 | 值 |
|---|---|
| 仓库 | https://github.com/makeplane/plane |
| Stars | 46,515 |
| 协议 | AGPL-3.0 |
| 技术栈 | React + TypeScript + MobX + Tailwind（前端），Django + DRF（后端），PostgreSQL + Redis |
| 最近版本 | v1.2.3（2026-03-05） |
| 部署方式 | Docker Compose / Kubernetes / AIO |

### 3.2 对象映射

| Daemon 概念 | Plane 等价物 | 适配度 | 说明 |
|---|---|---|---|
| **Draft** | `DraftIssue` 或 `Issue.is_draft=True` | **好** | Plane 有独立的 DraftIssue 模型（workspace 级）和 Issue 上的 is_draft 标志，概念一致 |
| **Slip**（任务） | `Issue`（Work Item） | **好** | 核心工作单元。有状态组（backlog/unstarted/started/completed/cancelled）、优先级、标签、父子层级、日期 |
| **Folio**（卷/项目） | `Project` 或 `Module` | **中** | Project 是硬容器，Module 是软分组（有自己的状态生命周期）。但没有 Folio 的"从 Slip 晋升"概念 |
| **Writ**（排序/依赖链） | `IssueRelation`（blocked_by, start_before, finish_before）+ `sort_order` | **弱** | Plane 有 issue 依赖关系，但没有一等公民的有序链对象。排序是视图级的，不是结构实体 |
| **Deed**（执行记录） | 无直接等价 | **无** | Plane 有 `IssueActivity`（审计日志）和 `IssueVersion`（快照），但没有独立的执行记录概念（running/settling/closed 生命周期） |

### 3.3 需要扩展的部分

**Writ（排序/依赖链）**：
- Plane 的 `IssueRelation` 支持 `blocked_by`、`start_before`、`finish_before` 关系类型
- 可以用 `blocked_by` 链 + 自定义 `sort_order` 模拟 Writ 的强排序语义
- 但 Writ 在 daemon 里是一等实体（有独立 ID、有自己的创建/删除逻辑），Plane 里是关系记录
- **方案**：在 Plane 的 Issue 关系之上，用 webhook + 胶水代码维护 Writ 语义

**Deed（执行记录）**：
- Plane 完全没有这个概念
- **方案**：Deed 的生命周期由 Temporal Workflow 管理，数据写入 Plane 的 `IssueComment` 或自定义属性（Custom Property），前端通过 Plane 的活动流展示
- 或者：Deed 数据保留在 Temporal 侧（workflow execution history），Portal 通过 Temporal API 读取，不进 Plane

### 3.4 Plane 前端能力

- 看板视图、列表视图、电子表格视图、日历视图、甘特图
- 活动流（Issue 的所有变更历史）
- 实时协作编辑（Hocuspocus + Yjs，限于文档/页面）
- Issue 更新不是 WebSocket 推送，用 SWR 轮询刷新（聚焦/定时）
- 动效水准：专业但不算精致，Tailwind transition + Headless UI，没有 Framer Motion
- 国际化支持（有 i18n 包）

### 3.5 Plane 的局限

1. **Issue 更新没有 WebSocket 推送**——用 SWR 轮询。对于 Deed 执行中的实时进度（move 级别），需要自己补 WebSocket
2. **没有 Apple 级别的转场动效**——和现有 Portal 一样，需要自己加
3. **AGPL-3.0 协议**——如果修改源码并对外提供服务，必须开源修改部分。自用无影响
4. **Writ 和 Deed 需要扩展**——不是开箱即用

### 3.6 集成架构

```
用户 → Plane 前端 → Plane Django API → PostgreSQL
                                          ↕ webhook
                              Temporal Schedules（定时）
                              Temporal Workflows（执行）
                                    ↓
                              OpenClaw Agents
                                    ↓
                              写回 Plane API（状态/结果/活动）
```

---

## 4. Temporal Schedules — 替代 Cadence

### 4.1 当前 Cadence 的问题

| 问题 | 严重程度 |
|---|---|
| 跑在 API 进程里的 `asyncio.sleep(30)` 循环——进程挂了调度就停了 | 高 |
| 没有 catchup——错过的任务不会补执行 | 高 |
| 手写 cron 解析 ~120 行，重造 Temporal 已有功能 | 中 |
| 没有重叠策略——多个触发撞车无处理 | 中 |
| 自适应调度逻辑 ~60 行（动态间隔） | 低（需保留） |

### 4.2 Temporal Schedules 提供的

- **服务端调度**：进程重启不丢失，server 自动管理
- **Catchup 窗口**：默认 1 年，server 宕机恢复后自动补执行
- **6 种重叠策略**：SKIP / BUFFER_ONE / BUFFER_ALL / CANCEL_OTHER / TERMINATE_OTHER / ALLOW_ALL
- **Cron / Calendar / Interval 三种规格**，可混合
- **暂停/恢复**：一等操作，带备注
- **Backfill**：指定时间范围补执行
- **Jitter**：内置随机偏移，避免同时触发
- **时区支持**：任意 IANA 时区
- **Web UI 可见**：Temporal Dashboard 里可以看到所有 schedule 的下次/最近执行

### 4.3 Python SDK 用法

```python
from temporalio.client import (
    Client, Schedule, ScheduleActionStartWorkflow,
    ScheduleSpec, ScheduleIntervalSpec,
)
from datetime import timedelta

handle = await client.create_schedule(
    "spine-routine-record",
    Schedule(
        action=ScheduleActionStartWorkflow(
            SpineRoutineWorkflow.run,
            "record",
            id="spine-record",
            task_queue="daemon-worker",
        ),
        spec=ScheduleSpec(
            intervals=[ScheduleIntervalSpec(every=timedelta(minutes=30))]
        ),
    ),
)

# 暂停
await handle.pause(note="维护中")

# 恢复
await handle.unpause()

# 删除
await handle.delete()
```

### 4.4 需要保留的

- **自适应调度逻辑**（`_adaptive_interval`）：Temporal Schedules 的 spec 是静态的，动态间隔需要外部逻辑定期调用 `handle.update()` 修改 spec
- **Nerve 事件触发**：Temporal Schedules 纯时间驱动，事件触发仍需 Nerve/Signal 机制
- **评价窗口 ticking / running TTL**：这不是调度问题，是状态管理，保留在 Spine routine 或独立 workflow 里

### 4.5 已知限制

- `day_of_month` 和 `day_of_week` 同时设置时是 AND 语义（不是 Vixie cron 的 OR）
- 没有动态/自适应间隔——spec 是静态的
- 内部实现为 Workflow——Standard Visibility 下会在 UI 里看到内部 workflow（有 Elasticsearch 时自动隐藏）

---

## 5. Langfuse — 替代 Trail

### 5.1 基本信息

| 项目 | 值 |
|---|---|
| 仓库 | https://github.com/langfuse/langfuse |
| Stars | ~23,100 |
| 协议 | MIT（ee/ 目录除外） |
| 技术栈 | React + TypeScript（前端），Node.js（后端），PostgreSQL + ClickHouse + Redis + MinIO |
| 部署 | Docker Compose / Kubernetes (Helm) |

### 5.2 核心能力

- **Tracing**：嵌套层级（trace > span > generation），自动记录 LLM 调用的 token、延迟、成本
- **Prompt 管理**：版本控制、协作迭代
- **评估**：LLM-as-judge、用户反馈、人工标注
- **数据集**：构建测试集和基准
- **Dashboard**：质量/成本/延迟总览

### 5.3 Temporal 集成

Langfuse 有**官方 Temporal 集成文档**。路径：

1. Python SDK 基于 OpenTelemetry 构建
2. 添加 `LangfuseSpanProcessor` 到 OTEL setup
3. 用 trace ID 关联跨进程（API 进程 ↔ Worker 进程）的调用链
4. Temporal workflow execution = 顶层 trace，activities = 嵌套 span，LLM 调用 = generation

```python
from langfuse import get_client
langfuse = get_client()

# 在 Temporal Activity 里
with langfuse.start_as_current_observation(as_type="span", name="scout-move") as span:
    # 调用 OpenClaw agent
    result = await openclaw_session.send(message)
    span.update(output=result)
```

### 5.4 替代 Trail 的收益

| Trail 自造 | Langfuse 提供 |
|---|---|
| 手写 trace 记录 | 自动捕获 LLM 调用链 |
| 手写 token 统计 | 自动统计 + 成本计算 |
| 无可视化 | Web Dashboard，trace 时间线视图 |
| 无评估框架 | LLM-as-judge + 人工标注 |
| 无 prompt 管理 | 版本控制 + playground |

### 5.5 部署依赖

PostgreSQL、ClickHouse、Redis、MinIO。其中 PostgreSQL 和 MinIO 如果已经部署（Plane 带了 PG，MinIO 单独部署），只需额外加 ClickHouse 和 Redis。

---

## 6. PostgreSQL + pgvector — 替代 Ledger + Lore 向量搜索

### 6.1 替代 Ledger

当前 Ledger 用 JSON 文件 + `threading.Lock` + `fcntl.flock` 实现并发安全。P6 诊断测试刚发现并修复了 `_attach_slip_to_folio` 的 TOCTOU 竞态条件。

PostgreSQL 天生解决这些问题：
- ACID 事务替代文件锁
- 并发安全不需要手写
- 查询能力远超 JSON 文件遍历
- Plane 自带 PostgreSQL，不需要额外部署

### 6.2 pgvector 替代自写向量搜索

```sql
CREATE EXTENSION vector;

CREATE TABLE lore_entries (
    id SERIAL PRIMARY KEY,
    content TEXT,
    embedding vector(1024),  -- 智谱 embedding-3 维度
    created_utc TIMESTAMPTZ DEFAULT now()
);

-- 余弦相似度搜索
SELECT id, content, 1 - (embedding <=> query_vector) AS similarity
FROM lore_entries
ORDER BY embedding <=> query_vector
LIMIT 10;

-- HNSW 索引
CREATE INDEX ON lore_entries USING hnsw (embedding vector_cosine_ops);
```

### 6.3 性能

- <100K 向量：精确搜索（无索引）毫秒级完成
- 有 HNSW 索引：亚毫秒
- 不需要 Qdrant/Chroma 等独立向量数据库——PG 一个服务全覆盖

### 6.4 Python 集成

```python
pip install pgvector psycopg2
```

pgvector-python 注册向量类型到 psycopg，也提供 SQLAlchemy `Vector` 列类型。

---

## 7. MinIO — 替代自管文件存储

### 7.1 基本信息

| 项目 | 值 |
|---|---|
| 仓库 | https://github.com/minio/minio |
| 协议 | AGPL-3.0 |
| 功能 | S3 兼容对象存储 |
| 部署 | `docker run minio/minio server /data` |

### 7.2 收益

- Offering/Vault 文件不用自己管路径和目录结构
- S3 API 标准，Python 用 `boto3` 或 `minio` SDK
- Plane 支持 S3/MinIO 作为文件存储后端——共用一个实例
- Langfuse 也用 MinIO——三个服务共享一个 MinIO

---

## 8. Herald（通知投递）— envoy + MCP servers 替代

### 8.1 调查结论

调查了 Novu（开源通知基础设施，~38,700 stars）：
- **不支持 Telegram**——内置 chat 渠道只有 Slack、Discord、Teams、WhatsApp、Mattermost、Zulip
- **依赖重**——需要 MongoDB + 2x Redis + S3，Node.js 服务栈
- **结论：Novu 不适合**

### 8.2 正确方案：envoy agent + MCP servers

Herald 不应该是一个独立的 Python service。**所有对外出口行为都应该是 envoy agent 的职责。**

envoy 是 daemon 的唯一对外出口 agent，负责：
- 发布产出（git push、PR 创建）
- 发送通知（Telegram、邮件）
- 调用外部 API（任何需要把结果推到外部的操作）

实现方式：**每个外部出口 = 一个 MCP server**。已有基础设施：`runtime/mcp_dispatch.py` + `config/mcp_servers.json`。

### 8.3 具体映射

| 出口能力 | MCP server | 说明 |
|---|---|---|
| GitHub（commit/push/PR/issue） | `@modelcontextprotocol/server-github` | 官方 MCP server |
| Telegram 通知 | 自包装薄 MCP server 或社区方案 | 包装 Telegram Bot API |
| Slack 通知 | `@modelcontextprotocol/server-slack` | 官方 MCP server |
| 邮件 | 社区 MCP server | 包装 SMTP/SendGrid |
| 任意 REST API | 通用 HTTP MCP server | fetch/POST 到任意端点 |
| 文件上传到 MinIO | S3 MCP server | 包装 S3 API |

### 8.4 收益

- **Herald 删除**——不再需要独立的通知投递服务
- **Telegram adapter 简化**——从"service + adapter"变成"MCP server"
- **出口能力无限扩展**——加一个出口 = 在 `mcp_servers.json` 里加一行配置，不写代码
- **envoy 的能力与配置成正比**——MCP server 越多，envoy 能投递的出口越多
- **架构一致性**——所有对外行为都走 agent → MCP tool → 外部 API，没有绕过 agent 的后门

### 8.5 Novu 调查备忘（存档，不采用）

Novu（https://github.com/novuhq/novu，~38,700 stars，MIT/商业双授权）：
- 支持 Email/SMS/Push/Slack/Discord/Teams/WhatsApp/Mattermost/Zulip
- 不支持 Telegram
- 依赖 MongoDB + 2x Redis + S3 + Node.js
- Python SDK 可用（`novu-py`）
- 不采用原因：不支持 Telegram + 依赖太重 + envoy + MCP 方案更优

---

## 9. Ether（事件总线）— PostgreSQL LISTEN/NOTIFY

### 9.1 当前问题

Ether 是自造的跨进程事件总线：JSONL append + file watcher。

### 9.2 替代方案

如果已经用 PostgreSQL（Plane 自带），直接用 PG 的 `LISTEN/NOTIFY`：

```python
# 发布
await conn.execute("NOTIFY deed_events, $1", json.dumps(payload))

# 订阅
await conn.add_listener("deed_events", callback)
```

优点：
- 零额外依赖——PG 已经在运行
- 原子性——可以在事务里发事件，事务回滚事件也不发
- 比 JSONL append + file watch 可靠得多

如果需要更高吞吐或持久化队列，用 Redis pub/sub。但 daemon 的事件量级用 PG LISTEN/NOTIFY 绑绑有余。

---

## 10. 替换后的系统架构

```
┌─────────────────────────────────────────────────────────┐
│                     用户界面                              │
│  Plane 前端（React + TypeScript + Tailwind + MobX）      │
│  + 自定义 Deed 实时面板（WebSocket 补充）                  │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                  Plane Django API                         │
│  Issue(Slip) / Project(Folio) / DraftIssue(Draft)        │
│  IssueRelation(Writ) / Webhook(→Temporal)                │
│  + 薄 FastAPI 胶水层（Deed 实时、Voice、Instinct）         │
└──────────┬───────────────────────┬──────────────────────┘
           │                       │
┌──────────▼──────────┐  ┌────────▼─────────────────────┐
│    PostgreSQL        │  │   Temporal Server             │
│  + pgvector          │  │   Schedules（替代 Cadence）    │
│  + LISTEN/NOTIFY     │  │   Workflows + Activities      │
│  （替代 Ledger）      │  │   （执行 + OpenClaw 调用）      │
└──────────────────────┘  └────────┬─────────────────────┘
                                   │
                          ┌────────▼─────────────────────┐
                          │   OpenClaw Agents              │
                          │   7 agents × persistent session│
                          └────────┬─────────────────────┘
                                   │
┌──────────────────────┐  ┌────────▼─────────────────────┐
│    MinIO              │  │   Langfuse                    │
│  （文件存储）          │  │   （LLM 追踪 + 评估）          │
│  Plane/Langfuse 共用  │  │   PostgreSQL + ClickHouse     │
└──────────────────────┘  └──────────────────────────────┘

保留自造：
  - Instinct（本能规则）    → Python if/else
  - Voice / Preferences    → markdown → agent context
  - Spine routines（精简）  → Temporal Workflows
  - 胶水层                  → Plane webhook ↔ Temporal

envoy 对外出口（MCP servers）：
  - GitHub MCP server      → commit/push/PR/issue
  - Telegram MCP server    → 通知投递（替代 Herald）
  - Slack/邮件/任意 API    → 按需加 MCP server 配置
```

---

## 11. 自造代码删减估算

| 当前文件/模块 | 行数 (约) | 替换后 | 说明 |
|---|---|---|---|
| `interfaces/portal/` 全部 | ~3500 | 删除 | Plane 前端替代 |
| `services/folio_writ.py` | ~800 | 删除 | Plane Issue/Project API |
| `services/cadence.py` | ~400 | 删除 | Temporal Schedules |
| `services/herald.py` | ~200 | 删除 | envoy + Telegram MCP server 替代 |
| `services/api_routes/portal_shell.py` | ~300 | 删除 | Plane API 替代 |
| `services/api_routes/console_*.py` | ~600 | 删除 | Plane 管理界面替代 |
| Ledger JSON 读写逻辑 | ~600 | 删除 | PostgreSQL |
| Ether | ~300 | 删除 | PG LISTEN/NOTIFY |
| Trail | ~200 | 删除 | Langfuse |
| **合计删除** | **~7100** | | |
| **新增胶水代码** | **~800-1200** | | Plane webhook handler + Deed 实时面板 + Temporal Schedule 管理 + Telegram MCP server 薄包装 |
| **净删减** | **~5900-6300 行** | | |

---

## 12. 部署依赖变化

| 服务 | 当前 | 替换后 |
|---|---|---|
| Python API 进程 | 有 | **瘦身**（只剩胶水层 + Instinct + Voice） |
| Python Worker 进程 | 有 | 保留（Temporal Activities） |
| Temporal Server | 有 | 保留 |
| PostgreSQL | 无 | **新增**（Plane 必需，同时替代 Ledger + Ether + pgvector） |
| Redis | 无 | **新增**（Plane 必需，也可供 Langfuse 用） |
| Plane Django API | 无 | **新增** |
| Plane 前端 | 无 | **新增**（替代 Portal） |
| ClickHouse | 无 | **新增**（Langfuse 必需） |
| MinIO | 无 | **新增**（Plane + Langfuse 共用） |
| Langfuse | 无 | **新增** |

新增 6 个服务，但删除了大量自造代码和它们的维护负担。全部可以用一个 `docker-compose.yml` 统一管理。

---

## 13. 风险与注意事项

### 13.1 Plane AGPL-3.0

- 自用不受限制
- 如果修改 Plane 源码并对外提供服务，必须开源修改部分
- MinIO 同为 AGPL-3.0，同理

### 13.2 Writ 和 Deed 的适配成本

- Writ 没有 Plane 一等实体——需要用 `IssueRelation` + webhook 模拟
- Deed 完全没有 Plane 等价——需要决定：Deed 数据放 Plane（作为 comment/activity）还是放 Temporal（workflow history）
- 这是集成中最需要设计的部分

### 13.3 Plane 前端二次开发

- Plane 前端足够好但不是 Apple 级别动效——转场动画需要自己加
- Deed 实时进度面板（move 级别 WebSocket 推送）Plane 没有——需要自己补一个组件
- 但起点比从零写好得多

### 13.4 运维复杂度

- 从"两个 Python 进程 + Temporal"变成"两个 Python 进程 + Temporal + Plane 全套 + Langfuse 全套 + MinIO"
- 总共 ~10 个容器。需要一个清晰的 docker-compose.yml
- 但每个服务都是成熟项目，比自造代码的维护成本低

---

## 14. 第二轮开源替代（2026-03-13 讨论确认）

> **评判标准**：daemon 要能做出自己这个程度的项目，能写出人类水平的论文。只看能力和 token 的 tradeoff，其他一概不管，硬件资源充足。

### 14.1 替代方案总表（第二轮）

| 自写组件 | 替换为 | token 影响 | 能力变化 | 结论 |
|---|---|---|---|---|
| psyche snapshot → MEMORY.md 管线 | **Mem0**（记忆层） | 省 90%（按需检索 vs 全量注入） | 自动提取/去重/更新记忆 | ✅ 通过 |
| InstinctEngine（Python 类） | **NeMo Guardrails**（NVIDIA） | 零 token（规则引擎替代 LLM 审查） | 60+ 预置 validator + Colang DSL | ✅ 通过 |
| SourceCache（PG+pgvector 自写 RAG） | **RAGFlow**（文档解析+分块+检索） | 省（精准分块 → 精准检索 → 少 token） | PDF 表格/图表/公式理解 | ✅ 通过 |
| 无（网页只有搜索摘要） | **Firecrawl**（网页→干净 Markdown） | 省 80%+（去 HTML 噪音） | 全文获取能力 | ✅ 通过 |
| 通用 MCP search | **Semantic Scholar API** | 省（精准学术搜索，少走弯路） | 学术论文专用搜索 + 引用关系 | ✅ 通过 |
| 无 | **tree-sitter 代码索引**（MCP tool） | 省大量（结构化查询 vs grep 全项目） | 函数/类/调用关系图谱 | ✅ 通过 |
| SourceCache | **RAGFlow** | 不省 token，运维成本高 | 文档解析分块 | ❌ 最初否决 |
| — | 后经深入讨论确认 RAGFlow 对论文写作不可或缺 | 省（精准检索）| PDF 深度理解 | ✅ 最终通过 |

### 14.2 不引入的

| 方案 | 理由 |
|---|---|
| **Dify** | 第二代 workflow 平台，理念落后于 OC 的 Agent OS 范式 |
| **LangGraph / CrewAI** | 代码框架，需要自己写更多代码，与"用现成的"原则矛盾 |
| **Coze Studio** | 开源较新（2025-07），成熟度不如 OC |

### 14.3 Voice 处理

Voice（写作风格）并入 Mem0 的 procedural memory，不再单独维护 `psyche/voice/` 目录。理由：
- Voice 本质是"怎么做"的记忆 → Mem0 procedural memory 类型
- 注入方式从全量改为按需检索 → 省 token
- Mem0 可自动从 scribe 输出中提取风格模式 → 减少手动维护

### 14.4 新增 MCP tools（零 token 能力扩展）

| 工具 | 作用 | 说明 |
|---|---|---|
| tree-sitter 代码索引 | 函数列表、调用关系、类结构 | Python 库，作为 MCP tool 暴露 |
| LaTeX 编译 | 论文 PDF 输出 | shell command，Direct Move |
| BibTeX 引用管理 | 论文引用格式 | 工具函数，Direct Move |
| matplotlib/mermaid 图表 | 论文图表生成 | Python 库，Direct Move |

---

## 15. Mem0 — 替代 psyche snapshot + MEMORY.md 管线

### 15.1 基本信息

| 项目 | 值 |
|---|---|
| 仓库 | https://github.com/mem0ai/mem0 |
| Stars | 大量（Netflix、Lemonade、Rocket Money 已采用） |
| 协议 | Apache 2.0 |
| 论文 | arXiv:2504.19413 |
| 部署 | Python 库 + PG + pgvector（可自部署） |

### 15.2 核心能力

- 自动从对话中提取记忆（Extraction + Update 两阶段管线）
- 分层记忆：user / session / **agent** 级别
- 四种记忆类型：episodic（情景）、semantic（语义）、procedural（程序性）、associative（关联）
- Graph Memory（知识图谱形式存储）
- 按需检索相关记忆（不是全量注入）

### 15.3 性能数据

- LOCOMO benchmark 上比 OpenAI Memory **准确率高 26%**
- 比全量上下文注入 **快 91%、省 90% token**

### 15.4 替代映射

| daemon 原有组件 | Mem0 替代 |
|---|---|
| psyche snapshot → MEMORY.md | Mem0 自动提取 + agent 级记忆 |
| Voice identity.md | Mem0 semantic memory（agent 级） |
| Voice style files | Mem0 procedural memory（agent 级） |
| Preferences | Mem0 user 级记忆 |
| retinue.write_psyche_snapshot() | 删除，Mem0 自动管理 |

### 15.5 集成方式

Mem0 作为 Python 库运行在 Worker 进程中，使用现有 PG + pgvector 作为后端。不需要额外 Docker 服务。

```python
from mem0 import Memory

config = {
    "vector_store": {
        "provider": "pgvector",
        "config": {"connection_string": DATABASE_URL}
    }
}
m = Memory.from_config(config)

# 写入记忆（自动提取）
m.add("用户偏好简洁风格，避免冗余修辞", agent_id="scribe", metadata={"type": "voice"})

# 按需检索
results = m.search("写论文时的风格偏好", agent_id="scribe", limit=5)
```

---

## 16. NeMo Guardrails — 替代 InstinctEngine

### 16.1 基本信息

| 项目 | 值 |
|---|---|
| 仓库 | https://github.com/NVIDIA-NeMo/Guardrails |
| 协议 | Apache 2.0 |
| 技术栈 | Python，Colang DSL |
| 部署 | Python 库（不是独立服务） |

### 16.2 替代 InstinctEngine 的映射

| InstinctEngine 方法 | NeMo 替代 |
|---|---|
| `check_outbound_query()` | Input rail（过滤外发 query） |
| `check_output()` | Output rail（检查输出违规） |
| `check_wash_output()` | Custom action + validation rail |
| `check_voice_update()` | Custom action + validation rail |
| `prompt_fragment()` | 不再需要（规则在引擎层执行，不注入 prompt） |

### 16.3 Colang 规则示例

```colang
# 硬规则：Tier C 不可作唯一来源
define flow check_source_tier
  when bot_said "..."
  if only_source_tier == "C"
    bot refuse with explanation "Tier C 来源不可作为事实性主张的唯一支撑"

# 硬规则：敏感词过滤
define flow check_outbound_query
  when user_query contains sensitive_term
  bot replace sensitive_term with generic_description
```

### 16.4 收益

- **零 token**：规则匹配在 Python 层执行，不调 LLM
- **Colang DSL**：比 Python if/else 更可读、更易维护
- **60+ 预置 validator**：常见检查不用自己写
- **与 Guardrails AI 互补**：NeMo 做对话流控制，Guardrails AI 做结构化输出验证

---

## 17. RAGFlow — 替代 SourceCache 的文档解析和检索

### 17.1 基本信息

| 项目 | 值 |
|---|---|
| 仓库 | https://github.com/infiniflow/ragflow |
| 协议 | Apache 2.0 |
| 技术栈 | Python + Elasticsearch + MinIO |
| 部署 | Docker Compose |

### 17.2 为什么需要（通过 tradeoff 的理由）

daemon 要写人类水平的论文。论文需要：
- 精确引用论文中的具体段落、表格、实验数据
- 不能只靠搜索摘要（200 字）写论文

RAGFlow 提供：
- PDF 深度解析（布局分析、表格提取、公式保留、多栏阅读顺序）
- 语义分块（按段落/章节切，不按字数切）
- 向量检索（精准命中相关分块）

**token tradeoff**：50 页论文 ≈ 25000 token。分块后检索 3 个相关块 ≈ 1500 token。**省 94%。**

### 17.3 知识流程

```
scout → MCP search → URL + 摘要
  ↓ 需要全文时
下载 PDF → RAGFlow 解析/分块/存储
  ↓
scribe/sage → RAGFlow 检索 → 精确命中具体段落/表格
```

### 17.4 TTL 过期管理

RAGFlow 不管 TTL。过期管理仍在 PG 层：

```sql
-- knowledge_cache 表增加 ragflow_doc_id 字段
-- tend routine 清理过期条目时，同步调用 RAGFlow API 删除文档
```

source_tiers.toml TTL 策略不变：
- Tier A（论文/官方文档）：90 天
- Tier B（技术博客）：30 天
- Tier C（搜索结果/新闻）：7 天

---

## 18. Firecrawl — 网页全文获取

### 18.1 基本信息

| 项目 | 值 |
|---|---|
| 仓库 | https://github.com/mendableai/firecrawl |
| 协议 | AGPL-3.0 |
| 功能 | 网页 → 干净 Markdown，支持 JS 渲染 |
| 部署 | Docker 自部署 |

### 18.2 为什么需要

MCP search 返回搜索摘要（200 字）。但很多知识在网页全文里：
- 技术文档的具体章节
- 博客的代码示例
- 教程的操作步骤

网页原始 HTML 几万 token（导航栏、广告、侧边栏...）。Firecrawl 转成干净 Markdown：**省 80%+ token**。

### 18.3 集成方式

作为 MCP tool 暴露给 scout：
- `firecrawl_scrape(url)` → 返回干净 Markdown
- 结果可直接存入 RAGFlow 或 knowledge_cache

---

## 19. Semantic Scholar API — 学术搜索

### 19.1 基本信息

| 项目 | 值 |
|---|---|
| API | https://api.semanticscholar.org/ |
| 费用 | 免费（有速率限制，可申请 API key 提升） |
| 数据 | 2 亿+ 学术论文 |

### 19.2 为什么需要

通用搜索（Google/Bing MCP）搜学术论文效率低：
- 混杂非学术结果
- 没有引用关系
- 没有 PDF 直链

Semantic Scholar 提供：
- 精准学术搜索
- 论文引用/被引关系图
- PDF 链接（可直接传给 RAGFlow 解析）
- 论文摘要 + 关键信息结构化返回

### 19.3 集成方式

作为 MCP tool 暴露给 scout：
- `semantic_scholar_search(query)` → 结构化论文列表
- `semantic_scholar_paper(paper_id)` → 论文详情 + 引用关系
- `semantic_scholar_citations(paper_id)` → 引用图谱

---

## 20. 更新后的完整架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        用户界面                                   │
│  Plane 前端 + 自定义 Deed 实时面板（WebSocket）                    │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                     Plane Django API                              │
│  + 薄 FastAPI 胶水层                                              │
└──────────┬────────────────────────────┬─────────────────────────┘
           │                            │
┌──────────▼──────────┐      ┌──────────▼──────────────────────┐
│    PostgreSQL        │      │   Temporal Server                │
│  + pgvector          │      │   Schedules + Workflows          │
│  + LISTEN/NOTIFY     │      └──────────┬─────────────────────┘
│  + knowledge_cache   │                 │
│    (TTL 管理)        │      ┌──────────▼──────────────────────┐
└──────────────────────┘      │   OpenClaw Agents                │
                              │   7 agents × persistent session  │
                              │   + NeMo Guardrails（嵌入）       │
                              │   + Mem0（嵌入）                  │
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
  - Firecrawl           → 网页全文获取
  - Semantic Scholar     → 学术搜索
  - tree-sitter 代码索引 → 代码理解
  - GitHub MCP server    → Git 操作
  - Telegram OC channel  → 通知
  - LaTeX / BibTeX       → 论文输出
  - matplotlib / mermaid → 图表生成

彻底删除的自写代码：
  - retinue.py           → OC 原生 session
  - InstinctEngine       → NeMo Guardrails
  - SourceCache 自写 RAG → RAGFlow
  - Voice 文件管理       → Mem0 procedural memory
  - Preferences 文件     → Mem0 user memory
  - Ledger JSON          → Langfuse + PG
  - Rations              → OC 原生 + Langfuse
  - herald.py            → OC Telegram channel
  - cadence.py           → Temporal Schedules

保留的自写代码（最小胶水层）：
  - Plane ↔ Temporal ↔ OC 胶水
  - Temporal workflow 定义（Slip → Deed 分解）
  - PG knowledge_cache TTL 管理（一张表 + cron）
  - instinct.md 内容（纳入 NeMo Colang 规则）
```

---

## 21. 下一步

1. **确认本方案**——尤其是 Writ/Deed 的适配策略
2. **搭建 Plane 本地实例**——验证对象映射是否真的可行
3. **设计 Plane ↔ Temporal 胶水层**——webhook handler + Deed 数据流向
4. **归档旧前端**——`interfaces/portal/` → `interfaces/portal_archived/`
5. **逐步迁移**——先 Plane + PG，再 Temporal Schedules，再 Langfuse + MinIO
6. **第二轮集成**——Mem0 + NeMo Guardrails + RAGFlow + Firecrawl + Semantic Scholar + tree-sitter tools
