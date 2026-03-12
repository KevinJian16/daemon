# Daemon 开源替代方案

> 日期：2026-03-13
> 状态：方案草案，待确认
> 目的：梳理 daemon 系统中哪些自造组件可以被成熟开源方案替代，降低维护成本，提升质量。

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

## 14. 下一步

1. **确认本方案**——尤其是 Writ/Deed 的适配策略
2. **搭建 Plane 本地实例**——验证对象映射是否真的可行
3. **设计 Plane ↔ Temporal 胶水层**——webhook handler + Deed 数据流向
4. **归档旧前端**——`interfaces/portal/` → `interfaces/portal_archived/`
5. **逐步迁移**——先 Plane + PG，再 Temporal Schedules，再 Langfuse + MinIO
