# Daemon 系统设计总纲

> **状态**：五稿（重构交接版）
> **日期**：2026-03-14
> **定位**：daemon 系统的唯一权威设计文档；目标是让另一位实现者只靠本文即可完成大部分重构工作。
> **配套阅读**：`SYSTEM_DESIGN.review.html`（彩色审阅版）、`GAPS.md`（独立 gap 工作台）、`GAPS_OLD_COVERAGE.md`（旧版覆盖核查）
> **归档来源**：四稿已归档到 `.ref/_archive/SYSTEM_DESIGN_v4_2026-03-14.md`

---

## §0 治理规则

### 0.1 本文档的权威性

本文档是 daemon 系统的唯一权威设计来源。实现、重构、测试、暖机、前端适配、Glue API 和 OpenClaw agent 层都以本文为准。

如本文与以下文档冲突，一律以本文为准：
- `.ref/_work/GAPS.md`
- `.ref/_work/GAPS_OLD_COVERAGE.md`
- `.ref/_archive/*`
- 代码中的旧注释、旧命名、旧脚本说明

### 0.2 本文档如何使用

实现者按以下顺序阅读：
1. 正文 `§0-§8`：确定系统规则和主行为。
2. 附录 B / C / D：查字段、参数、接口、事件和状态映射。
3. 附录 E / F：检查所有 `DEFAULT` 和 `UNRESOLVED`。
4. 附录 G / H：对照与 gap 的关系。

**要求**：实现者不得绕过正文直接从 `GAPS.md` 里挑方案自定。正文没有明确授权的地方，不得自行改写架构语义。

### 0.3 状态标签

- `FINAL`：已经拍板，必须按此实现。
- `DEFAULT`：当前默认方案，可据此开工；若后续校准，只能调参数，不能悄悄改外部语义。
- `UNRESOLVED`：本轮仍未定；实现者不能自行发挥，只能保留接口或等待下一轮定稿。

正文中出现 `**[DEFAULT]**` 和 `**[UNRESOLVED]**` 的位置，都是刻意保留下来的显著提醒点，不是普通备注。

### 0.4 文档与代码的同步顺序

术语、对象模型、状态机、字段表、接口契约的变更顺序固定为：
1. 先改 `SYSTEM_DESIGN.md`
2. 再改 `config/lexicon.json` 与附录表格
3. 再改代码和测试

禁止“先把代码做了，设计文档以后再补”。

### 0.5 术语、翻译与豁免规则

- 一个术语只能有一个正式含义。
- 代码、存储、API 使用英文 canonical name。
- 面向用户的 Plane / Telegram / review HTML 使用正式中文显示名。
- 外部专有名词、实现级标识、用户原始输入，不强制翻译。

FINAL 的术语映射见 `§1` 和附录 D；文档同步要求见附录 G。

### 0.6 工作原则

- 认真读设计、认真读代码、认真做链路核查。
- 函数存在不等于链路成立；必须追踪“输入 → 传递 → 存储 → 消费 → 输出”。
- 能复用成熟组件就复用，不为追求完整性自造基础设施。
- 跨系统边界要写清归属：谁创建对象、谁写回状态、谁负责补偿。

---

## §1 术语与对象模型

### 1.1 正式对象

| 对象 | 定义 | Plane 映射 | 说明 |
|---|---|---|---|
| `Project` | Task 的组织容器 | Plane Project | 长周期主题 / 项目 |
| `Draft` | 尚未转正的候选工作项 | Plane DraftIssue | 是正式对象，不是临时聊天缓存 |
| `Task` | 核心工作单元 | Plane Issue | 用户主要协作对象 |
| `Job` | Task 的一次执行记录 | daemon 自管 | Plane 无等价对象 |
| `Step` | Job DAG 中的一步 | 无 Plane 对象 | 1 Step = 1 目标 |
| `Artifact` | Step / Job 的交付产物 | 无 Plane 对象 | 存 MinIO + PG 元数据 |

FINAL 规则：
- `Project / Draft / Task` 的状态、标题、描述、依赖关系由 Plane 负责持有与展示。
- `Job / Step / Artifact` 由 daemon 持有。
- `Draft → Task` 必须经过明确转换，不允许自动升级。
- Task 间依赖用 Plane `IssueRelation(blocked_by)` 表示，不再自造一等 Trigger 对象。

### 1.2 状态模型

Task 和 Project 直接使用 Plane 的状态组；daemon 不再复制一套自管状态层。

Job 的正式状态机如下：

| 主状态 | 子状态 | 说明 |
|---|---|---|
| `running` | `queued` | 已创建，等待执行资源 |
| `running` | `executing` | 正在跑 Step |
| `running` | `paused` | 等待人工 review 或明确恢复信号 |
| `running` | `retrying` | Temporal / 运行时重试中 |
| `closed` | `succeeded` | 执行成功 |
| `closed` | `failed` | 执行失败 |
| `closed` | `cancelled` | 用户或系统取消 |

FINAL 规则：
- 默认成功 Job 直接 `closed/succeeded`，没有旧版 `settling` 窗口。
- `requires_review=true` 时，Job 进入 `running/paused`，等待 Signal。
- “再执行一次”始终表示基于同一 Task 创建一个新的 Job，不克隆新 Task。

### 1.3 执行类型

| execution_type | 作用 | 成本模型 |
|---|---|---|
| `agent` | OpenClaw session | 使用 daemon 统一预算 |
| `direct` | Python / shell / API / deterministic activity | 零 LLM token |
| `claude_code` | 本地 Claude Code subprocess | 用户 Claude Code 配额 |
| `codex` | 本地 Codex subprocess | 用户 Codex 配额 |

FINAL 规则：
- 只要输出完全由输入决定，就优先用 `direct`。
- 只有需要自然语言推理、分析、写作、规划、审查时才用 `agent` / `claude_code` / `codex`。

### 1.4 Agent 角色

| agent | 职责 | 默认模型方向 | 累积记忆 |
|---|---|---|---|
| `counsel` | 用户对话、routing、Job DAG 规划、Replan Gate | fast / analysis | 规划经验、任务分解模式 |
| `scholar` | 搜索、信息获取、分析、知识抽取 | analysis | 信源策略、分析框架 |
| `artificer` | 编码、调试、技术实现 | fast | 技术决策偏好 |
| `scribe` | 写作、结构化输出、风格适配 | creative | 写作风格、格式偏好 |
| `arbiter` | 质量审查、问题定位 | review | 质量标准、常见失败模式 |
| `envoy` | 对外发布、消息整理、通知 | creative / review | 渠道格式、发布风格 |
| `steward` | 体检、诊断、自愈 | analysis | 系统运维经验 |

FINAL 规则：
- 7 个 agent 是固定预创建集合；扩能力靠 skill / MCP，不靠动态生 agent。
- arbiter 只指出问题，不直接修复产物。

### 1.5 知识层级

正式优先级：

`Guardrails > External Facts > Persona > System Defaults`

含义：
- Guardrails 决定安全、隐私、底线，不被用户偏好覆盖。
- 外部事实决定可验证事实，不被 Persona 改写。
- Persona 只塑造风格与选择，不塑造事实。
- 默认值只在没有更高优先级约束时生效。

### 1.6 废弃术语

以下旧词一律只留在 archive / coverage 中，不再在正文使用：
- `Psyche`、`Instinct`、`Voice`、`Rations`
- `Offering`（统一改为 `Artifact`）
- `Deed`（统一改为 `Job`）
- `Move`（统一改为 `Step`）
- `Folio` / `Slip`（统一改为 `Project` / `Task`）

---

## §2 系统架构

### 2.1 总体目标

daemon 是一个“Plane 作为协作前端 + daemon 作为执行内核 + OpenClaw 作为 agent runtime”的双层系统。它的目标不是提供另一套 UI，而是把任务组织、执行、知识、反馈、追踪、暖机和自愈统一成一条可追溯链路。

### 2.2 双层系统

daemon 永远有两层，必须同步演进：

1. Python 执行层
- `services/`
- `temporal/`
- `runtime/`
- `config/`

2. OpenClaw agent 层
- `openclaw/workspace/*`
- `TOOLS.md`
- `SKILL.md`
- `openclaw.json`

FINAL 规则：任何改动如果只改一层、不验证另一层的联动，都不算完成。

### 2.3 进程与职责边界

| 组件 | 职责 |
|---|---|
| Plane 前端 / API | Task / Project / Draft 的主协作界面和持久对象 |
| daemon API | webhook 接收、胶水 API、WebSocket、轻量查询接口 |
| daemon Worker | Temporal activities、Plane 回写、OC 调用、Mem0、NeMo、MCP、MinIO |
| Temporal | Job / Step 编排、重试、暂停、调度 |
| OpenClaw | agent session runtime |
| PostgreSQL | daemon 数据、Plane 数据、event_log |
| MinIO | Artifact 全文对象存储 |
| Langfuse | LLM trace / 监控 |

FINAL 规则：
- API 进程与 Worker 进程不直接共享内存状态。
- 两者通过 PG、Temporal、Plane、MinIO 这些正式边界协同。
- Job 级逻辑只能由 Worker + Temporal 持有，不能散落在 Plane webhook handler 中。

### 2.4 Plane 对象映射

| daemon 对象 | Plane 对象 | 说明 |
|---|---|---|
| `Project` | `Project` | 正式承载对象 |
| `Draft` | `DraftIssue` | 转正前候选项 |
| `Task` | `Issue` | 用户主要编辑对象 |
| `Job` | 无 | daemon PG + Temporal |
| `Step` | 无 | Job 内部执行单元 |

**[UNRESOLVED]** Plane 管理界面是否允许直接编辑 `psyche/voice/*` 文件。

当前正文默认管理界面只做“查看、导出、比较、审计”，不把 Persona 文件直接暴露成可编辑主界面。若后续要开放编辑，必须补审计与回滚。

### 2.5 外部出口分工

| 出口 | 方式 | 规则 |
|---|---|---|
| Telegram | OpenClaw 原生 channel | 有原生就优先原生 |
| GitHub | MCP server | OC 无原生时走 MCP |
| 其他网页 / 文档 | scholar + Firecrawl / RAGFlow | 以获取和引用为主 |

FINAL 规则：能用 OC 原生出口的，不再自建旁路通知服务。

### 2.6 模型策略

| 场景 | 模型策略 |
|---|---|
| routing decision | fast |
| Project 初始规划 / Replan 全局判断 | analysis |
| scholar 深分析 | analysis |
| scribe / envoy 产出 | creative |
| arbiter 审查 | review |
| steward 诊断 | analysis |

**[DEFAULT]** 模型名称和 provider 绑定保持配置化，不在正文硬编码到具体厂商 SKU。当前只要求能力等级和调用位置固定；具体模型表见附录 B 和运行时配置。

### 2.7 持久化边界

FINAL 规则：
- Plane 持 Task / Project / Draft 的协作面信息。
- daemon PG 持 Job / Step / Artifact 元数据、事件、扩展字段。
- MinIO 持 Artifact 全文、大对象、审计版本。
- Langfuse 持 trace，不作为业务真相源。
- Mem0 持 Persona 和记忆，不持业务事实。

---

## §3 执行模型

### 3.1 Routing Decision 与入口路径

所有入口都先经过 counsel 的 routing decision。输出只允许三类路径：
- `direct`
- `task`
- `project`

FINAL 规则：
- `direct`：一步能完成，不创建 Task / Project。
- `task`：创建 1 个 Task，再立即创建其首个 Job。
- `project`：先创建 Project，再创建 Task 集合与依赖关系，然后按入口 Task 启动首个 Job。

FINAL 规则：Plane 对象的创建责任属于 counsel 的规划结果；Worker 负责执行对应的 Plane API / MCP 调用，不在 webhook handler 中偷偷生成对象。

**[DEFAULT]** `route="direct"` 统一生成 1 个 Step 的 ephemeral Job，并持久化进 `jobs` 表，使用 `is_ephemeral=true` 标记；这样保留 trace、失败补偿和审计能力，同时不污染用户的 Task 列表。

FINAL 规则：
- `route="task"` 时：先创建 Issue，再写入 daemon_tasks，再冻结首个 Job 的 `dag_snapshot`。
- `route="project"` 时：先创建 Project，再批量创建 Task / 依赖关系，再启动入口 Task 的首个 Job。
- routing decision 失败时，不允许系统静默自创第四条路径。

### 3.2 Job 生命周期

Job 生命周期如下：

`create -> queued -> executing -> (paused|retrying)* -> closed(succeeded|failed|cancelled)`

FINAL 规则：
- “执行”按钮 = 创建 Job + 立即运行，是原子操作。
- 同一 Task 同时最多只有一个非 closed Job。
- rerun 始终创建新 Job；旧 Job 保留不覆盖。
- Job 成功默认直接关闭，不再等待旧式 settling 窗口。

**[DEFAULT]** Plane 回写失败默认重试 5 次；若仍失败，则把 `plane_sync_failed=true` 写入 PG，并由补偿任务异步重试，不得因为单次回写失败篡改 Job 的业务结果。

FINAL 规则：
- `requires_review=true` 时，Job 在对应 Step 结束后转为 `running/paused`。
- review 通过后走 `review_approved` / `resume_job`，继续原 Workflow。
- review 拒绝后走 `review_rejected`，进入 rework / terminate 决策。

**[DEFAULT]** 用户回到 Task 页面重新执行，默认视为对上次结果的隐式否定信号，但不会反向把旧 Job 改成 failed；系统只把该信号纳入新的规划上下文和学习回路。

### 3.3 Step 模型与 Session 规则

FINAL 规则：**1 Step = 1 目标 = 1 Session**。

每个 Step 在自己的全新 context 中完成，不保留前序 Step 的对话历史。Session key 采用：

`{agent_id}:{job_id}:{step_id}`

FINAL 的 Step 状态枚举：
- `pending`
- `running`
- `completed`
- `failed`
- `skipped`

FINAL 规则：
- `skipped` 表示 counsel 明确判定可以跳过，不能由实现者随意使用。
- 同一 agent 的并行 Step 也必须各自独立 session。
- direct Step 不加载 Memory，不经过 OC session。

Step 输入只允许以下四部分：
1. MEMORY.md 的静态最小规则
2. Mem0 按需检索结果
3. 结构化 Step 指令
4. 上游 Artifact 摘要 / 路径

### 3.4 初始 DAG、上下文与 Re-run 规划

FINAL 规则：Task 的首个 Job 不是用空白上下文生成 DAG，而是基于：
- Plane Issue description
- Plane Issue Activity（对话历史）
- counsel 的 Mem0 规划经验
- 对应 Project 的已知上下文（如有）

counsel 每次规划新 Job 时，都重新组装上下文；不允许依靠旧 session 挂着不关来延续上下文。

### 3.5 Step 失败、arbiter 与 Rework

失败处理顺序固定：
1. Temporal RetryPolicy 自动重试
2. 重试耗尽后，counsel 判断 `skip / replace / terminate`
3. 需要人工介入时再 pause

FINAL 规则：arbiter 的职责是指出问题，不直接生成修复版。

**[DEFAULT]** 当 arbiter 审查失败并触发 rework 时，新 Step 使用全新 session；arbiter 结果以结构化 Artifact 注入 `input_artifacts`，而不是把旧 session 全量上下文复制过去。

### 3.6 DAG 执行、Artifact 传递与 Replan Gate

FINAL 规则：Job 的执行 DAG 在 Job 创建时冻结到 `dag_snapshot`；Task 的逻辑 DAG 更新不影响进行中的 Job。

并行执行原则：
- 依赖为空的 Step 可并行。
- 同层 Step 通过拓扑排序分层后并行执行。
- 并行 Step 的失败要统一汇总后交 counsel 判断，不能各自偷偷吞异常。

Artifact 传递原则：
- Step 完成后把 Artifact 元数据写 PG，把正文或大文件写 MinIO。
- 下游 Step 只拿摘要 + 路径，不拿上游 session 历史。
- Task 间数据流通过 `task_input_from` 明确声明。

Replan Gate 原则：
- 触发位置：chain trigger 前。
- 粒度：Task 级，不在运行中的 Job 内重写 Step DAG。
- 已完成 Task 不可变，未执行 Task 才能被 diff 修改。

**[DEFAULT]** Replan Gate 输出使用 `operations[]` diff，而不是整棵新 DAG。当前默认 schema：
- `add`
- `remove`
- `update`
- `reorder`

每个 operation 至少包含：
- `op`
- `target_task_id`
- `after_task_id`
- `payload`

**[UNRESOLVED]** Replan 结果对多个 Plane Issue 的批量写入如何保证事务一致性。当前定义了目标语义和 diff 结构，但多对象写入失败时的回滚机制仍保留在附录 F / Appendix H 中。

### 3.7 Task 触发

FINAL 规则：Task 触发类型互斥，只允许以下三种之一：
- `manual`
- `timer`
- `chain`

FINAL 规则：
- `chain` 默认要求前序 Task 的最近一个 Job 为 `closed/succeeded`。
- 前序失败不触发下游 Task，除非以后专门加“失败也触发”的设计，不允许实现者私自放宽。
- 触发本质上都是事件，只是事件源不同：`user.manual`、`time.tick`、`job.closed`。

FINAL 规则：Task 的依赖关系不允许无声改写。任何正式变更都必须通过 Plane 对象变更 + 活动流记录体现出来。

### 3.8 运行时默认值与保留边界

**[DEFAULT]** Step / Job 时间预算、heartbeat、retry、quota 等参数统一进入附录 B；实现者应先按附录值完成重构，再通过暖机校准，而不是实现阶段自行拍脑袋。

**[UNRESOLVED]** 多用户扩展不在本轮交付范围。实现时只要不堵死未来扩展即可，不要求本轮补完。

---

## §4 交互与界面契约

### 4.1 界面角色

| 界面 | 作用 |
|---|---|
| Plane | Task / Project / Draft 主界面 |
| Job 实时面板 | WebSocket 驱动的执行监视区 |
| Plane 管理界面 | 面向维护者的治理入口 |
| Telegram | 通知和极简控制 |
| review HTML | 审阅 / handoff 用彩色只读视图 |

FINAL 规则：不再维护独立 Portal / Console 语义层。所有正式产品交互都以 Plane 为中心适配。

### 4.2 Task 页面骨架

FINAL 的 Task 页面必须稳定包含五个部分：
1. 标题与描述区
2. plan card
3. 统一活动流
4. Job 执行块
5. 底部输入区

FINAL 规则：plan card 不能因任务轻重不同而消失或换物种。简单任务可以是短卡，但仍然是 plan card。

### 4.3 Draft 语义与转正流程

FINAL 规则：Draft 是正式对象，不是临时聊天缓存。

Draft 的正式来源有四类：
- 用户对话
- 规则触发
- 外部事件
- 系统内部推进

FINAL 规则：自动任务也必须先形成 Draft，除非是明确的 `route="direct"`。Draft 转 Task 必须是有意识的转换动作，不能无声升级。

### 4.4 Project 页面骨架

FINAL 的 Project 页面固定回答五个问题：
1. 这个项目是什么
2. 当前脉络是什么
3. 哪些 Task 正在活跃
4. 最近执行了哪些 Task
5. 最近产出了什么结果

对应五个固定区域：
- 标题 / 摘要
- 关系图 / 脉络图
- 当前活跃 Task 列表
- 最近执行 Task 列表
- 最近 Artifact 摘要

### 4.5 Task 依赖导航

FINAL 规则：Task 页面内必须支持依赖链导航。

- 线性链：显示单个“上一个 / 下一个 Task”
- 分支点：显示多个“下一个 Task”标签
- 合并点：显示多个“上一个 Task”标签

标签语义必须真实反映 DAG 结构，不能伪装成线性顺序。

### 4.6 活动流与操作记录

FINAL 规则：Task 只有一条统一活动流，所有交互都落进这条流。

活动流承载：
- 用户自然语言输入
- agent 产生的关键可见结果摘要
- Job 边界
- Step 关键状态
- 非对话操作记录

FINAL 规则：按钮和对话是同一控制通道的两种表达。按钮操作必须写入活动流，格式见附录 D。

FINAL 规则：统一活动流 API 必须：
- 返回同一 Task 下所有 Job 的合并活动流
- 按时间排序
- 每条消息显式携带 `job_id`
- 用显式边界表明属于哪个 Job

### 4.7 Job 执行块与 Artifact 呈现

FINAL 规则：Job 不单独成为 Plane 一级页面，而是 Task 内的执行块。

Job 执行中至少显示：
- 当前 DAG 进度
- 当前 / 最近 Step 状态
- 新产生的 Artifact 摘要

Job 结束后：
- 执行块冻结为只读
- 保留版本列表
- 展示最终交付物预览或下载入口

### 4.8 反馈与 Persona 回路

FINAL 规则：
- 无 Job 时，对话用于改 Task 目标和 DAG 定义。
- Job 运行或结束后，对话用于反馈结果和风格。
- Persona 更新必须在 Job closed 后，由系统提出候选，用户明确确认后再写入 Mem0。

FINAL 责任归属：
- counsel 负责发起确认与最终写入流程。
- scribe / envoy 可以提出候选，但不直接落库。

### 4.9 API / WebSocket 摘要契约

**[DEFAULT]** daemon 提供最小胶水端点集合：`pause / resume / cancel / stream / artifacts / webhooks / dependency-state / activity-stream`。正式路径和字段见附录 D。

**[DEFAULT]** 前端判断按钮是否禁用时，至少依赖：
- `latest_job_status`
- `next_trigger_utc`
- `dependency_blockers`

### 4.10 Telegram 与极简控制

FINAL 规则：Telegram 只承载：
- 完成 / 失败 / 告警通知
- 极简控制命令
- 用户无法方便打开 Plane 时的 fallback 交互

不承载：
- 复杂 Draft / Task / Project 结构化编辑
- 长反馈主流程

### 4.11 管理界面与隐私边界

**[DEFAULT]** Plane 管理界面默认只暴露：
- Task / Job / Step 的元数据
- 执行摘要
- agent 列表
- 关键状态机信息

默认不直接暴露：
- Task 全量对话正文
- Step instruction 原文
- Persona 文件全文编辑能力

若后续开放更深权限，必须先补权限模型、审计记录和回滚方案。

---

## §5 知识、Persona、Guardrails 与 Quota

### 5.1 正式层级

正式层级固定为：

`Guardrails > External Facts > Persona > System Defaults`

这条层级同时适用于：
- 输出冲突处理
- 引用优先级
- Persona 更新权限
- 自动化决策冲突裁定

### 5.2 Persona 双层结构

FINAL 规则：Persona 不是单一文件，也不是纯 Mem0；它是双层结构。

1. 文件层（稳定基底）
- `psyche/voice/identity.md`
- `psyche/voice/common.md`
- `psyche/voice/zh.md`
- `psyche/voice/en.md`
- `psyche/overlays/*.md`

2. 动态层（运行期记忆）
- Mem0 semantic / procedural memory

文件层负责稳定的身份、语言、全局表达边界；Mem0 动态层负责用户偏好、风格演化、规划经验。

### 5.3 Persona 更新责任

FINAL 规则：Persona 不自动写入。

更新链路固定为：
1. Job closed 后抽取候选
2. counsel 向用户发起确认
3. NeMo Guardrails 校验
4. 写入 Mem0

scribe / envoy 负责提出候选，counsel 负责确认闭环和最终写入。

### 5.4 Mem0 注入

FINAL 规则：Mem0 只做按需检索，不做全量注入。

| agent | 默认检索重点 |
|---|---|
| counsel | 规划经验、历史 DAG 模式 |
| scholar | 搜索策略、分析框架 |
| artificer | 技术偏好、代码风格 |
| scribe | 写作风格、语言偏好 |
| arbiter | 审查标准、失败模式 |
| envoy | 渠道格式、发布风格 |
| steward | 运维经验、诊断线索 |

**[DEFAULT]** 单次检索上限默认 5 条；超过这个值是否提升，只能由暖机结果驱动。

### 5.5 Guardrails 分层

Guardrails 由 NeMo Guardrails 提供，分三层：
- input / output rails
- dialog rails
- custom actions

FINAL 规则：
- Persona 候选写入前必须过 Guardrails。
- 外部事实引用前必须过 source tier 规则。
- Tier C 不得成为事实性主张的唯一来源。

### 5.6 外部知识获取工具链

正式工具链：
- scholar + MCP search
- Semantic Scholar
- Firecrawl
- RAGFlow
- knowledge_cache

FINAL 规则：外部知识必须能追溯回 URL / 文档来源；没有来源的内容不算 External Facts，只能算工作缓存。

### 5.7 knowledge_cache 与 Project 偏置

knowledge_cache 用于外部知识 TTL 与二级缓存，不替代 RAGFlow，也不替代 Mem0。

**[DEFAULT]** 检索时默认先查同一 `project_id` 范围，再回退到全局；这样既减少跨项目污染，又不至于完全错失全局经验。

### 5.8 Quota 与运行预算

Quota 分三层：
- OC / session 层预算
- Job 层预算
- 系统日预算

**[DEFAULT]** 配额阈值和告警先走保守默认值，记录在附录 B；暖机完成后再按 Langfuse 数据校准。

### 5.9 学习机制

FINAL 规则：
- 只从 accepted / 成功 Job 中学习。
- 规划经验存 Mem0 procedural memory。
- 风格和偏好必须用户确认后再写入。
- 迟到反馈只影响未来，不回写改造旧 Job 结果。

---

## §6 基础设施与运行时契约

### 6.1 Docker 服务清单

基础 Docker 服务集：
- PostgreSQL + pgvector
- Redis
- Plane API / 前端 / Worker
- Temporal Server / UI
- MinIO
- Langfuse + ClickHouse
- RAGFlow + Elasticsearch
- Firecrawl

FINAL 规则：这些服务只解决“基础设施能力”，不承担 daemon 的业务状态机。

### 6.2 daemon 自有进程

daemon 只正式持有两个 Python 进程：
- FastAPI API 进程
- Temporal Worker 进程

FINAL 规则：
- API 进程负责边界接入和查询接口。
- Worker 进程负责执行语义、Plane 回写、MCP、Mem0、NeMo、MinIO。
- 不允许在 API 进程里偷偷跑长执行链。

### 6.3 网络拓扑与对象流向

核心拓扑：
- 用户通过 Plane / Telegram 输入意图
- Plane webhook / API 把对象变化送到 daemon API
- daemon API 触发 Temporal
- Worker 驱动 OC / MCP / RAG / MinIO / Plane 回写
- Langfuse 负责 trace，不作为业务真相源

### 6.4 PostgreSQL 事件总线

**[DEFAULT]** PG 事件总线采用 `event_log + NOTIFY` 双写。

FINAL 语义：
- `event_log` 提供持久化与重放能力
- `NOTIFY` 提供即时唤醒能力
- Worker 重启后先补消费 `event_log` 未完成事件，再恢复监听

**[DEFAULT]** channels 统一为：
- `job_events`
- `step_events`
- `webhook_events`
- `system_events`

### 6.5 OC Gateway 与 MCP 生命周期

FINAL 规则：
- Session 生命周期 = Step 生命周期。
- subagent 不加载 Mem0 / MEMORY.md。
- tool routing 由 MCP dispatcher 统一分发。

**[DEFAULT]** MCP server 连接按 Worker 进程级持久化复用：
- Worker 启动时连接并构建 tool 路由表
- 每次调用都带超时保护
- server 崩溃或超时后标记不可用，让 Step 走失败 / 重试逻辑

### 6.6 Temporal 约束

FINAL 规则：
- Job = Workflow
- Step = Activity（或少数 runtime 包装 activity）
- timer = Temporal Schedule
- pause / resume / cancel = Signal / Workflow 控制

**[DEFAULT]** 时间预算、retry policy、catch-up window 见附录 B；实现者不得自行发明第二套调度系统。

### 6.7 Plane 回写与补偿

FINAL 规则：Plane 是协作真相源，但不是 Job 执行真相源。Job 的真实执行状态先落 daemon PG，再尝试回写 Plane。

**[DEFAULT]** Plane 回写失败时：
- 先重试
- 再写 `plane_sync_failed`
- 再由补偿流程异步追平

不允许直接把 Job 标成 failed 来掩盖 Plane 同步失败。

### 6.8 配置文件

正式配置位于：
- `config/mcp_servers.json`
- `config/source_tiers.toml`
- `config/lexicon.json`
- `config/guardrails/*`
- `openclaw/openclaw.json`

FINAL 规则：配置表述的默认值必须与附录 B / C / D 一致。

### 6.9 启动与健康检查

FINAL 规则：启动顺序必须可验证，不能依赖“本机刚好都起来了”。

推荐顺序：
1. Docker 基础服务
2. PostgreSQL / Temporal / Plane 就绪
3. OC Gateway
4. daemon Worker
5. daemon API

**[UNRESOLVED]** Schedule 丢失后的自动恢复脚本是否纳入首版交付。当前要求 steward 在体检中检测并告警，但恢复脚本本身仍保留为后续议题。

---

## §7 暖机、可观测性、自愈与学习

### 7.1 暖机目标

暖机不是初始化，而是交付前的系统标定。目标是让系统在任务执行、风格输出、审查判断和自愈上达到可生产状态。

### 7.2 暖机前提

暖机开始前必须满足：
- 基础设施全部可用
- skill 草稿已经具备可运行内容
- Persona 文件层有初始版本
- review / telemetry / notification 链路都可跑通

### 7.3 暖机阶段

保留五阶段结构：
1. 信息采集
2. Persona 标定
3. 链路逐通
4. 测试任务套件
5. 系统状态与异常场景验证

### 7.4 收敛标准

FINAL 收敛目标：
- 单 Task 执行基线稳定
- chain trigger 命中正确
- 学习机制形成闭环
- 对外产出达到可接受的“伪人度”

### 7.5 周度体检

steward 每周自动执行两层检测：
- 基础设施层：缩减版链路验证
- 质量层：固定基准任务回归

告警只分 `GREEN / YELLOW / RED` 三档，具体阈值见附录 B。

### 7.6 可追溯链

每个 Job 必须有完整可追溯链：

`Plane Task -> Job ID -> PG job/step/artifact -> Langfuse trace -> Temporal history`

FINAL 规则：排障必须能从任一端点追到整条链，不允许存在“只有日志里看得到、数据库里没有”的关键状态。

### 7.7 学习与漂移

FINAL 规则：
- 学习只影响未来，不回写历史结果。
- 规划经验、风格偏好、渠道格式都可积累，但都必须来源可追溯。
- Mem0 的冲突和漂移必须可在管理界面中查看候选项。

### 7.8 自愈流程

保留三层自愈：
1. steward 规则驱动修复
2. 自动生成 issue 文件并调用 Claude Code / Codex
3. 最后才通知用户转交 issue 文件

FINAL 规则：正常情况下，用户只需要知道“系统正常”或“系统已经修好”。

### 7.9 问题文件格式

问题文件必须做到“被转发给外部 coding agent 后，单文件即可开始修复”。

问题文件至少包含：
- 你需要做什么
- 背景
- 具体问题
- 当前文件内容或关键路径
- 期望行为
- 修复后验证步骤

### 7.10 用户操作边界

用户只承担：
- 提供目标和反馈
- 在必要时确认 Persona / review / 重跑
- 当自动修复失败时转交 issue 文件

用户不承担：
- 诊断复杂运行时错误
- 手动拼接日志
- 解释内部对象模型

---

## §8 禁止事项与边界

以下行为被正式否决：

1. 把 Job 当作 Task 本体。
2. 在 Plane 之外再维护一套正式门户语义。
3. 同一个 Task 同时挂多种触发类型。
4. 把多个并行 Step 合并成同一个 session。
5. 用上下文积累替代显式 Artifact 传递。
6. 让 arbiter 直接生成修复版内容。
7. 让按钮和对话走两套逻辑。
8. 在运行中的 Job 上直接改写已冻结的 `dag_snapshot`。
9. 把 Tier C 来源当作唯一事实来源。
10. 自动写 Persona 而不经用户确认。
11. 通过规则硬编码替代 counsel 的 routing decision。
12. 动态创建新的 agent 身份。
13. 在 API 进程里直接跑长执行链。
14. 把 Langfuse 当作业务真相源。
15. 隐式创建 / 删除 Task 依赖关系而不留下活动流记录。
16. 在正文之外另造一份权威性更高的 HTML / review 说明。

---
---

## 附录 A：阅读与状态标签说明

### A.1 文档阅读顺序

1. 正文 `§0` 到 `§8`：先理解系统是什么、怎么实现。
2. 附录 B / C / D：查参数、字段、接口、事件、状态映射。
3. 附录 E / F：扫描所有 `DEFAULT` 和 `UNRESOLVED`，识别哪些地方还能调整、哪些地方不能自行发挥。
4. 附录 G / H：查看与 `GAPS.md` 的逐条关系和完整 backlog。

### A.2 标签含义

- `FINAL`：已经拍板，按本文实现。
- `DEFAULT`：当前默认方案，可以按此施工；若后续校准，只能在不改变外部契约的前提下调整。
- `UNRESOLVED`：本轮设计仍未拍板，不能由实现者自行发挥；要么保留接口，要么等待下一轮设计确认。

### A.3 文档权威边界

- `SYSTEM_DESIGN.md`：唯一权威设计文档。
- `SYSTEM_DESIGN.review.html`：同一内容的彩色审阅视图，不单独承载设计决策。
- `GAPS.md`：独立维护的实施差距清单。
- `GAPS_OLD_COVERAGE.md`：旧版 80 条与覆盖判断记录。
- `.ref/_archive/*`：历史参考文档，不再具备权威性。

---

## 附录 B：运行时默认参数表

> 说明：本附录中的值只要带 `DEFAULT`，就表示“当前可施工默认值”，不是永久不可修改的架构常量。

### B.1 Step / Job 时间预算

| 项目 | 默认值 | 说明 | 状态 |
|---|---|---|---|
| `direct_step_timeout` | `30s` | shell / API / 文件操作默认超时 | **[DEFAULT]** |
| `search_step_timeout` | `60s` | scholar 搜索 / 轻分析 | **[DEFAULT]** |
| `review_step_timeout` | `90s` | arbiter / 审查型 Step | **[DEFAULT]** |
| `writing_step_timeout` | `180s` | scribe / envoy / 长写作 | **[DEFAULT]** |
| `replan_light_timeout` | `60s` | Replan 轻量判断 | **[DEFAULT]** |
| `replan_full_timeout` | `180s` | 完整 Replan | **[DEFAULT]** |
| `job_execution_timeout` | `30m` | 单 Job 总上限 | **[DEFAULT]** |
| `activity_heartbeat_timeout` | `30s` | 长 Activity heartbeat | **[DEFAULT]** |
| `queued_wait_timeout` | `10m` | Job 在 `running/queued` 最长等待时间 | **[DEFAULT]** |

### B.2 Retry / Schedule

| 项目 | 默认值 | 说明 | 状态 |
|---|---|---|---|
| `retry.initial_interval` | `5s` | Temporal RetryPolicy | **[DEFAULT]** |
| `retry.backoff_coefficient` | `2.0` | 指数退避 | **[DEFAULT]** |
| `retry.maximum_interval` | `60s` | 单次最大等待 | **[DEFAULT]** |
| `retry.maximum_attempts` | `5` | 默认重试次数 | **[DEFAULT]** |
| `schedule.timezone` | `用户工作区时区` | 单用户环境默认沿用用户时区 | **[DEFAULT]** |
| `schedule.jitter_window` | `60s` | 避免集中触发 | **[DEFAULT]** |
| `schedule.catch_up_window` | `24h` | 超出窗口不补执行 | **[DEFAULT]** |

### B.3 Session / OC / WebSocket

| 项目 | 默认值 | 说明 | 状态 |
|---|---|---|---|
| `contextPruning.cache_ttl` | `5m` | 清理旧 tool result | FINAL |
| `maxSpawnDepth` | `2` | orchestrator 模式上限 | FINAL |
| `maxChildrenPerAgent` | `5` | 单 session 子 agent 数 | FINAL |
| `maxConcurrent` | `8` | 全局并发 session 上限 | FINAL |
| `ws.ping_interval` | `20s` | WebSocket ping | **[DEFAULT]** |
| `ws.pong_timeout` | `10s` | 等待 pong | **[DEFAULT]** |
| `ws.reconnect_backoff` | `1s~30s` | 客户端指数退避 | **[DEFAULT]** |

### B.4 知识 / 缓存 / TTL

| 项目 | 默认值 | 说明 | 状态 |
|---|---|---|---|
| `mem0.search_limit` | `5` | 单次记忆检索条数 | **[DEFAULT]** |
| `ragflow.top_k` | `3` | 文档分块召回数 | **[DEFAULT]** |
| `knowledge_cache.embedding_dim` | `1024` | 向量维度 | **[DEFAULT]** |
| `knowledge_cache.tier_a_ttl` | `90d` | 官方 / 学术源 | FINAL |
| `knowledge_cache.tier_b_ttl` | `30d` | 主流二手源 | FINAL |
| `knowledge_cache.tier_c_ttl` | `7d` | 低信任源 | FINAL |
| `knowledge_cache.cleanup_interval` | `1h` | 清理过期缓存 | **[DEFAULT]** |
| `knowledge_cache.project_bias` | `same-project first` | 同 Project 优先 | **[DEFAULT]** |

### B.5 配额与告警

| 项目 | 默认值 | 说明 | 状态 |
|---|---|---|---|
| `quota.warn_threshold` | `80%` | 达到日配额告警 | **[DEFAULT]** |
| `quota.block_threshold` | `100%` | 超过日配额阻止新 Step | **[DEFAULT]** |
| `quota.deed_ration_ratio` | `0.5` | 单 Job 最大消耗比例 | **[DEFAULT]** |
| `langfuse.token_spike` | `baseline * 1.5` | 异常 token 告警 | **[DEFAULT]** |
| `arbiter.warn_threshold` | `80%` | 周度通过率阈值 | **[DEFAULT]** |

---

## 附录 C：核心数据结构与字段表

### C.1 daemon_tasks

| 字段 | 类型 | 约束 / 说明 | 状态 |
|---|---|---|---|
| `task_id` | `TEXT` | 主键；与 Plane Issue UUID / key 做稳定映射 | FINAL |
| `plane_issue_id` | `TEXT` | Plane Issue 主键 | FINAL |
| `project_id` | `TEXT NULL` | 可空；无 Project 的 Task 为空 | FINAL |
| `brief` | `JSONB` | 任务目标、语言、格式、深度、引用要求 | FINAL |
| `dag` | `JSONB` | 当前 Task 的逻辑 DAG 定义 | FINAL |
| `latest_job_id` | `TEXT NULL` | 最近一次 Job | FINAL |
| `trigger_type` | `TEXT` | `manual / timer / chain`，互斥 | FINAL |
| `trigger_config` | `JSONB NULL` | timer / chain 配置 | FINAL |
| `draft_origin_id` | `TEXT NULL` | 来自哪个 Draft | FINAL |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | 时间戳 | FINAL |
| `deleted_at` | `TIMESTAMPTZ NULL` | 软删除 | FINAL |

### C.2 daemon_drafts

| 字段 | 类型 | 约束 / 说明 | 状态 |
|---|---|---|---|
| `draft_id` | `TEXT` | 主键；映射 Plane DraftIssue | FINAL |
| `plane_draft_id` | `TEXT` | Plane DraftIssue 主键 | FINAL |
| `intent_snapshot` | `TEXT` | counsel 首次理解到的意图快照 | FINAL |
| `candidate_brief` | `JSONB NULL` | 生成 Task 前的 brief 草稿 | FINAL |
| `source` | `TEXT` | `conversation / rule / external_event / system` | FINAL |
| `draft_status` | `TEXT` | `open / converted / discarded` | FINAL |
| `created_at` / `updated_at` | `TIMESTAMPTZ` | 时间戳 | FINAL |

### C.3 jobs

| 字段 | 类型 | 约束 / 说明 | 状态 |
|---|---|---|---|
| `job_id` | `TEXT` | 主键 | FINAL |
| `task_id` | `TEXT NULL` | `route="direct"` 时可空 | FINAL |
| `workflow_id` | `TEXT` | 对应 Temporal workflow_id | FINAL |
| `status` | `TEXT` | `running / closed` | FINAL |
| `sub_status` | `TEXT` | `queued / executing / paused / retrying / succeeded / failed / cancelled` | FINAL |
| `dag_snapshot` | `JSONB` | Job 创建时冻结的执行 DAG | FINAL |
| `requires_review` | `BOOLEAN` | Job 级审查标志 | FINAL |
| `is_ephemeral` | `BOOLEAN` | direct route 的临时 Job 标识 | **[DEFAULT]** |
| `plane_sync_failed` | `BOOLEAN` | Plane 回写失败补偿标记 | **[DEFAULT]** |
| `result_summary` | `TEXT NULL` | 用户可见执行摘要 | FINAL |
| `total_token_usage` | `INTEGER NULL` | 汇总 token 用量 | **[DEFAULT]** |
| `created_at` / `started_at` / `closed_at` | `TIMESTAMPTZ` | 生命周期时间戳 | FINAL |

### C.4 job_steps

| 字段 | 类型 | 约束 / 说明 | 状态 |
|---|---|---|---|
| `step_id` | `TEXT` | Job 内唯一，也建议全局唯一 | FINAL |
| `job_id` | `TEXT` | 外键指向 jobs | FINAL |
| `seq` | `INTEGER` | DAG 展示序 | FINAL |
| `goal` | `TEXT` | 1 Step = 1 目标 | FINAL |
| `agent` | `TEXT NULL` | `direct` 可空 | FINAL |
| `execution_type` | `TEXT` | `agent / direct / claude_code / codex` | FINAL |
| `model` | `TEXT NULL` | 使用的模型 | FINAL |
| `depends_on` | `TEXT[]` | 依赖 step_id 列表 | FINAL |
| `status` | `TEXT` | `pending / running / completed / failed / skipped` | FINAL |
| `input_artifacts` | `JSONB` | 上游 Artifact 引用 | FINAL |
| `output_artifact_id` | `TEXT NULL` | 主输出 Artifact | FINAL |
| `token_usage` | `JSONB NULL` | `prompt / completion / total` | FINAL |
| `error_message` | `TEXT NULL` | 错误摘要 | FINAL |
| `started_at` / `completed_at` | `TIMESTAMPTZ` | 时间戳 | FINAL |

### C.5 job_artifacts

| 字段 | 类型 | 约束 / 说明 | 状态 |
|---|---|---|---|
| `artifact_id` | `TEXT` | 主键 | FINAL |
| `job_id` | `TEXT` | 所属 Job | FINAL |
| `step_id` | `TEXT` | 所属 Step | FINAL |
| `artifact_type` | `TEXT` | `text / file / structured / report / code` | **[DEFAULT]** |
| `summary` | `TEXT` | 注入 prompt 用摘要 | FINAL |
| `minio_path` | `TEXT NULL` | 大对象路径 | **[DEFAULT]** |
| `metadata` | `JSONB` | 来源标记、mime、size 等 | FINAL |
| `content_hash` | `TEXT NULL` | SHA-256 | **[DEFAULT]** |
| `created_at` | `TIMESTAMPTZ` | 时间戳 | FINAL |

### C.6 knowledge_cache

| 字段 | 类型 | 约束 / 说明 | 状态 |
|---|---|---|---|
| `cache_id` | `TEXT` | 主键 | FINAL |
| `project_id` | `TEXT NULL` | Project 偏置检索辅助字段 | **[DEFAULT]** |
| `source_url` | `TEXT` | 来源 URL | FINAL |
| `content` | `TEXT` | 清洗后的内容 | FINAL |
| `embedding` | `vector(1024)` | 向量 | **[DEFAULT]** |
| `source_tier` | `CHAR(1)` | `A / B / C` | FINAL |
| `ragflow_doc_id` | `TEXT NULL` | RAGFlow 文档 ID | FINAL |
| `fetched_at` | `TIMESTAMPTZ` | 抓取时间 | FINAL |
| `expires_at` | `TIMESTAMPTZ` | TTL 到期时间 | FINAL |

### C.7 event_log

| 字段 | 类型 | 约束 / 说明 | 状态 |
|---|---|---|---|
| `event_id` | `TEXT` | 主键 | FINAL |
| `channel` | `TEXT` | `job_events / step_events / webhook_events / system_events` | **[DEFAULT]** |
| `payload` | `JSONB` | 事件内容 | FINAL |
| `created_at` | `TIMESTAMPTZ` | 写入时间 | FINAL |
| `consumed_at` | `TIMESTAMPTZ NULL` | 消费完成时间 | **[DEFAULT]** |

---

## 附录 D：接口、事件与显示契约

### D.1 daemon API 端点

| 端点 | 方法 | 作用 | 状态 |
|---|---|---|---|
| `/api/jobs/{job_id}/pause` | POST | 将 running Job 置为 `running(paused)` | **[DEFAULT]** |
| `/api/jobs/{job_id}/resume` | POST | 从 review / pause 恢复 Job | **[DEFAULT]** |
| `/api/jobs/{job_id}/cancel` | POST | 取消 Job 与其 Temporal Workflow | **[DEFAULT]** |
| `/api/jobs/{job_id}/stream` | WS | 实时推送 Step / Artifact / 状态变化 | **[DEFAULT]** |
| `/api/jobs/{job_id}/artifacts` | GET | 返回当前 Job 的 Artifact 列表与签名 URL | **[DEFAULT]** |
| `/api/plane/webhooks` | POST | 接收 Plane webhook，做去重并落 event_log | FINAL |
| `/api/tasks/{task_id}/dependency-state` | GET | 返回按钮禁用判断所需字段 | **[DEFAULT]** |
| `/api/tasks/{task_id}/activity-stream` | GET | 返回合并活动流和 Job 边界元数据 | FINAL |

### D.2 WebSocket 契约

**[DEFAULT]** 心跳策略：服务端每 20s 发送 `ping`，客户端必须在 10s 内回 `pong`。

**[DEFAULT]** 重连策略：客户端负责指数退避重连；重连后请求 `since_event_id`，服务端按最新 Job 状态 + 最近事件窗口重放。

**[DEFAULT]** 事件类型：

| type | 字段 | 说明 |
|---|---|---|
| `job.status` | `job_id`, `status`, `sub_status`, `updated_at` | Job 状态变化 |
| `step.status` | `job_id`, `step_id`, `status`, `updated_at` | Step 状态变化 |
| `artifact.created` | `job_id`, `step_id`, `artifact_id`, `summary`, `artifact_type` | 新 Artifact 生成 |
| `job.log` | `job_id`, `level`, `message` | 用户可见的简要执行日志 |

### D.3 操作记录消息格式

FINAL 约束：所有非对话操作都要写入 Task 活动流，并使用统一格式。

```json
{
  "role": "system",
  "event": "operation",
  "operation": "pause_job",
  "label": "[操作] 暂停执行",
  "job_id": "job_xxx",
  "created_at": "2026-03-14T09:00:00Z"
}
```

### D.4 PG `event_log` / NOTIFY channels

**[DEFAULT]** channels：`job_events`、`step_events`、`webhook_events`、`system_events`。

```json
{
  "id": "evt_xxx",
  "channel": "job_events",
  "entity_id": "job_xxx",
  "event_type": "job.closed",
  "payload": {"status": "closed", "sub_status": "succeeded"},
  "created_at": "2026-03-14T09:00:00Z"
}
```

### D.5 Signal 名称

| signal | 作用 | 状态 |
|---|---|---|
| `pause_job` | 进入 review / manual pause | FINAL |
| `resume_job` | 继续执行 | FINAL |
| `cancel_job` | 取消 Workflow | FINAL |
| `review_approved` | 审查通过后继续 | FINAL |
| `review_rejected` | 审查拒绝后走 rework / terminate | FINAL |

### D.6 中文显示文案

| canonical | 中文显示 | 状态 |
|---|---|---|
| `Project` | `项目` | FINAL |
| `Task` | `任务` | FINAL |
| `Draft` | `草稿` | FINAL |
| `Job` | `执行记录` | FINAL |
| `Step` | `步骤` | FINAL |
| `Artifact` | `产出` | FINAL |
| `Persona` | `人格配置` | FINAL |
| `Guardrails` | `系统规则` | FINAL |
| `Knowledge Base` | `知识库` | FINAL |

| Job 状态 | 中文显示 | 状态 |
|---|---|---|
| `running/queued` | `排队中` | FINAL |
| `running/executing` | `执行中` | FINAL |
| `running/paused` | `等待审查` | FINAL |
| `running/retrying` | `重试中` | FINAL |
| `closed/succeeded` | `已完成` | FINAL |
| `closed/failed` | `执行失败` | FINAL |
| `closed/cancelled` | `已取消` | FINAL |

---

## 附录 E：正文中的 DEFAULT 清单

### D-001

**[DEFAULT]** `route="direct"` 生成 1 个 Step 的 ephemeral Job，并持久化到 `jobs` 表。

保留审计、追踪和重放能力；使用 `is_ephemeral=true` 区分，不创建 Task / Project。

对应 gap：G-3-041、G-3-042、G-3-096

### D-002

**[DEFAULT]** Replan Gate 输出采用 `operations[]` diff。

默认字段：`op`, `target_task_id`, `after_task_id`, `payload`；后续如需 JSON Patch，可在不改变语义的前提下替换。

对应 gap：G-3-055、G-3-136

### D-003

**[DEFAULT]** Job / Step 时间预算先给默认值再暖机校准。

search 60s、review 90s、writing 180s、replan 60/180s、heartbeat 30s。

对应 gap：G-3-017、G-3-018、G-3-108、G-3-124、G-3-131

### D-004

**[DEFAULT]** PG 事件总线采用 `event_log + NOTIFY` 双写。

默认 channels：`job_events`、`step_events`、`webhook_events`、`system_events`。

对应 gap：G-6-021~025、G-6-065

### D-005

**[DEFAULT]** knowledge_cache 检索优先同 Project，再回退全局。

默认按 `project_id` 精确过滤优先，空结果再做全局召回。

对应 gap：G-4-070

### D-006

**[DEFAULT]** WebSocket 心跳默认 20s ping / pong。

客户端负责断线重连，重连后请求最新 Job 状态和事件窗口。

对应 gap：G-12-006、G-6-061

### D-007

**[DEFAULT]** Plane API 回写失败默认重试 5 次。

指数退避后仍失败则标记 `plane_sync_failed` 并留待异步补写，不直接改变 Job 业务结果。

对应 gap：G-3-012

### D-008

**[DEFAULT]** Quota 与运行时配额的阈值先走保守默认值。

阈值进入附录参数表，暖机完成后再按 Langfuse 真实数据校准。

对应 gap：G-8-009~014、G-8-040~048


---

## 附录 F：正文中的 UNRESOLVED 清单

### U-001

**[UNRESOLVED]** Plane 管理界面是否允许直接编辑 `psyche/voice/*` 文件。

当前设计默认只读呈现并允许导出；若要开放直接编辑，需要补齐审计、回滚和 owner 确认机制。

对应 gap：G-12-010、G-11-029、G-11-041

### U-002

**[UNRESOLVED]** 多用户扩展何时进入主设计。

当前系统仍以单用户为前提，Mem0、Plane Project 命名和 Telegram 通知均按单用户闭环设计；多用户不在本次重构交付范围。

对应 gap：G-11-056、G-2-044、G-5-144

### U-003

**[UNRESOLVED]** Replan 结果对 Plane 批量写入的事务性边界。

当前正文定义了目标语义和 diff 格式，但跨多个 Issue 的部分失败回滚策略仍保留在运行时实现阶段再定。

对应 gap：G-3-106、G-3-107、G-11-050

### U-004

**[UNRESOLVED]** Temporal Schedule 丢失后的自动恢复脚本。

正文要求 steward 体检检测并告警，但恢复脚本是否自动生成仍未拍板。

对应 gap：G-11-030、G-11-058

### U-005

**[UNRESOLVED]** 未来是否保留 Plane Module 作为 Project 的替代承载。

当前正文统一按 Plane Project 设计；是否兼容 Module 只作为迁移兼容议题保留。

对应 gap：G-2-082


---

## 附录 G：已吸收 / 默认吸收的 Gap 清单

| Gap | 状态 | 覆盖位置 |
|---|---|---|
| `G-12-001` | `FINAL` | §4.2 |
| `G-12-002` | `FINAL` | §4.4 |
| `G-12-003` | `FINAL` | §4.5 |
| `G-12-004` | `FINAL` | §4.6 + 附录 D |
| `G-12-005` | `FINAL` | §4.3 |
| `G-12-008` | `FINAL` | §4.6 + 附录 D |
| `G-12-009` | `FINAL` | §4.10 + 附录 D |
| `G-13-001` | `FINAL` | §1.1 + 附录 D |
| `G-13-002` | `FINAL` | §0.5 + 附录 D |
| `G-13-003` | `FINAL` | §0.4 + 附录 G |
| `G-3-016` | `FINAL` | §3.3 + 附录 C |
| `G-3-041` | `FINAL` | §3.1 |
| `G-3-042` | `FINAL` | §3.1 |
| `G-3-045` | `FINAL` | §3.1 |
| `G-3-046` | `FINAL` | §3.1 |
| `G-3-058` | `FINAL` | §3.6 |
| `G-3-059` | `FINAL` | §3.6 |
| `G-3-060` | `FINAL` | §3.6 + 附录 D |
| `G-3-061` | `FINAL` | §3.6 + 附录 D |
| `G-3-062` | `FINAL` | §3.6 |
| `G-3-063` | `FINAL` | §3.6 |
| `G-3-064` | `FINAL` | §3.6 |
| `G-3-135` | `FINAL` | §3.1 |
| `G-3-137` | `FINAL` | §3.5 |
| `G-3-138` | `FINAL` | §3.4 |
| `G-3-139` | `FINAL` | §3.1 |
| `G-3-140` | `FINAL` | §3.2 |
| `G-4-001` | `FINAL` | §2.3 + 附录 C |
| `G-4-002` | `FINAL` | 附录 C |
| `G-4-003` | `FINAL` | 附录 C |
| `G-4-004` | `FINAL` | §3.6 + 附录 C |
| `G-4-005` | `FINAL` | 附录 C |
| `G-4-006` | `FINAL` | 附录 C |
| `G-4-011` | `FINAL` | 附录 C |
| `G-4-012` | `FINAL` | §3.2 + 附录 C |
| `G-4-013` | `FINAL` | 附录 C |
| `G-4-014` | `FINAL` | 附录 B |
| `G-4-015` | `FINAL` | 附录 C |
| `G-4-016` | `FINAL` | 附录 C |
| `G-4-017` | `FINAL` | 附录 C |
| `G-4-018` | `FINAL` | 附录 C |
| `G-4-019` | `FINAL` | 附录 C |
| `G-4-024` | `FINAL` | §1.2 |
| `G-4-025` | `FINAL` | §1.2 |
| `G-4-026` | `FINAL` | §1.2 |
| `G-4-027` | `FINAL` | §1.2 |
| `G-4-028` | `FINAL` | §1.2 |
| `G-4-029` | `FINAL` | §1.2 |
| `G-4-069` | `FINAL` | 附录 C |
| `G-5-146` | `FINAL` | §5.2 |
| `G-5-147` | `FINAL` | §5.3 |
| `G-6-065` | `FINAL` | §6.4 |
| `G-6-066` | `FINAL` | §6.5 |
| `G-12-006` | `DEFAULT` | §4.9 + 附录 D |
| `G-12-007` | `DEFAULT` | §4.9 + 附录 D |
| `G-12-010` | `DEFAULT` | §4.11 + 附录 D |
| `G-2-004` | `DEFAULT` | 附录 B |
| `G-2-010` | `DEFAULT` | 附录 B |
| `G-2-015` | `DEFAULT` | 附录 B |
| `G-2-016` | `DEFAULT` | 附录 B |
| `G-2-017` | `DEFAULT` | 附录 B |
| `G-2-045` | `DEFAULT` | 附录 B |
| `G-2-060` | `DEFAULT` | 附录 B |
| `G-3-012` | `DEFAULT` | §6.4 + 附录 B |
| `G-3-017` | `DEFAULT` | 附录 B |
| `G-3-018` | `DEFAULT` | 附录 B |
| `G-3-019` | `DEFAULT` | 附录 B |
| `G-3-055` | `DEFAULT` | §3.5 + 附录 D |
| `G-3-096` | `DEFAULT` | §3.1 + 附录 C |
| `G-3-108` | `DEFAULT` | 附录 B |
| `G-3-124` | `DEFAULT` | 附录 B |
| `G-3-125` | `DEFAULT` | §3.6 + 附录 D |
| `G-3-133` | `DEFAULT` | 附录 B |
| `G-4-014` | `DEFAULT` | 附录 B |
| `G-4-020` | `DEFAULT` | 附录 B |
| `G-4-021` | `DEFAULT` | 附录 B |
| `G-4-022` | `DEFAULT` | 附录 B |
| `G-4-023` | `DEFAULT` | 附录 D |
| `G-4-064` | `DEFAULT` | 附录 C |
| `G-4-065` | `DEFAULT` | 附录 C |
| `G-4-066` | `DEFAULT` | 附录 C |
| `G-4-068` | `DEFAULT` | 附录 C |
| `G-4-070` | `DEFAULT` | §5.7 + 附录 B |
| `G-6-021` | `DEFAULT` | §6.4 + 附录 D |
| `G-6-022` | `DEFAULT` | §6.4 + 附录 D |
| `G-6-023` | `DEFAULT` | §6.4 + 附录 D |
| `G-6-024` | `DEFAULT` | §6.4 + 附录 D |
| `G-6-025` | `DEFAULT` | §6.4 + 附录 D |
| `G-6-057` | `DEFAULT` | 附录 D |
| `G-6-058` | `DEFAULT` | 附录 B |
| `G-6-060` | `DEFAULT` | 附录 B |
| `G-6-061` | `DEFAULT` | 附录 D |
| `G-8-009` | `DEFAULT` | §5.8 + 附录 B |
| `G-8-010` | `DEFAULT` | §5.8 + 附录 B |
| `G-8-011` | `DEFAULT` | §5.8 + 附录 B |
| `G-8-012` | `DEFAULT` | §5.8 + 附录 B |
| `G-8-013` | `DEFAULT` | §5.8 + 附录 B |
| `G-8-014` | `DEFAULT` | §5.8 + 附录 B |
| `G-8-040` | `DEFAULT` | 附录 B |
| `G-8-041` | `DEFAULT` | 附录 B |
| `G-8-042` | `DEFAULT` | 附录 B |
| `G-8-043` | `DEFAULT` | 附录 B |
| `G-8-044` | `DEFAULT` | 附录 B |
| `G-8-045` | `DEFAULT` | 附录 B |
| `G-8-046` | `DEFAULT` | 附录 B |
| `G-8-047` | `DEFAULT` | 附录 B |
| `G-8-048` | `DEFAULT` | 附录 B |


---

## 附录 H：完整 Gap 注册表（逐条映射）

> 说明：除非某条 gap 在本附录中被明确标为 `FINAL` 或 `DEFAULT` 并给出覆盖位置，否则一律视为 `UNRESOLVED`。

### G-1 系统架构总览

#### G-1-1 系统边界与启动编排

- **[UNRESOLVED]** `G-1-001` — daemon API 进程的默认监听端口（SYSTEM_DESIGN.md 网络拓扑图标注 :8100，是否为最终确认值）
- **[UNRESOLVED]** `G-1-002` — API 进程与 Worker 进程之间"不直接通信"的硬性约束——是否有 watchdog 检测违规直连
- **[UNRESOLVED]** `G-1-003` — `~/.openclaw → daemon/openclaw/` 软链接的创建方式——scripts/start.py 自动创建还是手动创建
- **[UNRESOLVED]** `G-1-004` — DAEMON_HOME 环境变量与 `Path(__file__).parent` 回退的优先级——环境变量为主还是代码路径为主
- **[UNRESOLVED]** `G-1-005` — 两个 Python 进程的进程管理方式——systemd unit、supervisord、还是直接 nohup 运行
- **[UNRESOLVED]** `G-1-006` — 进程崩溃后的自动重启策略（API 进程/Worker 进程各自的重启策略）
- **[UNRESOLVED]** `G-1-007` — OC Gateway 的启动命令和工作目录（是否通过 scripts/start.py 统一管理）
- **[UNRESOLVED]** `G-1-008` — 同一宿主机上 Docker 服务与非 Docker Python 进程之间的网络访问方式（localhost vs host.docker.internal）
- **[UNRESOLVED]** `G-1-009` — Docker Compose 文件的健康检查 `healthcheck` 参数值（interval、timeout、retries 各服务的具体值）
- **[UNRESOLVED]** `G-1-010` — daemon 启动时依赖的服务健康检查顺序——scripts/start.py 等待所有 Docker 服务就绪的具体检查逻辑
- **[UNRESOLVED]** `G-1-011` — Temporal Worker 注册的 Task Queue 名称（代码中用什么 queue name）
- **[UNRESOLVED]** `G-1-012` — Temporal Worker 的 max_concurrent_activities 和 max_concurrent_workflow_tasks 默认值
- **[UNRESOLVED]** `G-1-013` — 系统级别状态（running/paused/restarting/resetting/shutdown）的存储位置（SYSTEM_DESIGN.md 未明确）
- **[UNRESOLVED]** `G-1-014` — 系统级 paused 状态下，Temporal Worker 是否停止 poll（还是继续 poll 但拒绝新 Job）
- **[UNRESOLVED]** `G-1-015` — Worker 进程内 NeMo Guardrails 和 Mem0 的初始化顺序及失败处理（初始化失败时 Worker 能否仍然启动）
- **[UNRESOLVED]** `G-1-016` — 系统级状态（running/paused/restarting/resetting/shutdown）的变更权限——哪些 API 端点或 CLI 命令可以触发状态变更，是否需要认证
- **[UNRESOLVED]** `G-1-017` — DAEMON_HOME 下的标准目录结构（state/、warmup/、config/、openclaw/、runtime/、temporal/、services/ 等目录的完整枚举）
- **[UNRESOLVED]** `G-1-018` — Worker 进程启动时对 PG 连接池的初始化时序——是否阻塞等待 PG 就绪才继续
- **[UNRESOLVED]** `G-1-019` — API 进程与 Worker 进程同时运行时共享同一个 PG 连接池还是各自独立连接池
- **[UNRESOLVED]** `G-1-020` — scripts/start.py 的启动顺序规范——Docker services → PG 就绪 → OC Gateway → Worker 进程 → API 进程的严格顺序及每步检查的具体方法
- **[UNRESOLVED]** `G-1-021` — Worker 进程多实例（水平扩展）时，Temporal Worker 的 max_concurrent_workflow_tasks 应如何配置以避免重复处理
- **[UNRESOLVED]** `G-1-022` — API 进程的 uvicorn worker 数量配置（单进程单 worker 还是多 worker，asyncio event loop 兼容性要求）
- **[UNRESOLVED]** `G-1-023` — daemon 是否有 CLI 入口点（除 scripts/start.py 外，是否有 CLI 工具供用户直接与 daemon 交互）
- **[UNRESOLVED]** `G-1-024` — NeMo Guardrails LLMRails 实例在 Worker 进程中是否为单例，以及是否线程安全（Temporal Activity 可能并发调用）
- **[UNRESOLVED]** `G-1-025` — Temporal Client 连接对象的生命周期管理——每个 Activity 复用同一个 Client 还是每次创建新连接
### G-2 基础设施层（开源组件集成）

#### G-2-1 PostgreSQL

- **[UNRESOLVED]** `G-2-001` — daemon 自建 PG 表的完整列表（job、job_artifacts、job_steps、knowledge_cache、event_log 等，完整枚举）
- **[UNRESOLVED]** `G-2-002` — PG 表的迁移策略——Alembic、手动 SQL、还是 Temporal Activity 初次运行时建表
- **[UNRESOLVED]** `G-2-003` — Plane 共用同一个 PG 实例时，daemon 使用独立 schema 还是独立表前缀（防止命名冲突）
- **[DEFAULT]** `G-2-004` — PG connection pool 配置——asyncpg pool 的 min_size、max_size、max_inactive_connection_lifetime 值 · 覆盖：附录 B
- **[UNRESOLVED]** `G-2-005` — knowledge_cache 表的索引设计（source_url 唯一索引？embedding 向量索引的 ivfflat 参数？）
- **[UNRESOLVED]** `G-2-006` — event_log 表的 consumed_at 字段——NULL 表示未消费，更新机制由谁负责（Worker 进程处理后 UPDATE）
- **[UNRESOLVED]** `G-2-007` — PG LISTEN/NOTIFY channel 的命名规范（job_events、step_events、webhook_events 是否全部确认）
- **[UNRESOLVED]** `G-2-008` — NOTIFY payload 的 JSON 最大长度限制（PG NOTIFY payload 上限 8000 字节，超出时的处理策略）
- **[UNRESOLVED]** `G-2-009` — event_log 的清理策略——consumed 事件保留多久后删除（属于定时清理 Job 的职责范围）
- **[DEFAULT]** `G-2-010` — PG pgvector 扩展版本要求和 embedding 维度（SYSTEM_DESIGN.md 说 1024 维，pgvector 索引类型：ivfflat 还是 hnsw） · 覆盖：附录 B
- **[UNRESOLVED]** `G-2-065` — daemon PG 表的完整建表 SQL——是否有统一的 schema migration 文件（migrations/）或者 CREATE TABLE IF NOT EXISTS 写在 startup 脚本里
- **[UNRESOLVED]** `G-2-066` — daemon_tasks 表（Task 扩展表）与 Plane issues 表的关联字段——是否用 Plane issue_id（UUID）作为外键
- **[UNRESOLVED]** `G-2-067` — jobs 表的索引设计——task_id 索引、status 索引、created_at 索引的具体定义
- **[UNRESOLVED]** `G-2-068` — PG asyncpg 连接池的命令超时（command_timeout）配置——默认值是否覆盖慢查询场景
- **[UNRESOLVED]** `G-2-069` — PG schema 升级时（添加列/修改类型）的零停机策略——daemon 是否支持在线滚动升级
- **[UNRESOLVED]** `G-2-070` — knowledge_cache 表的 embedding BLOB 存储格式——是 float32 序列化的 bytes 还是 JSON 数组
- **[UNRESOLVED]** `G-2-071` — knowledge_cache 表中 source_url 是否有唯一约束（防止同一 URL 多次写入）
- **[UNRESOLVED]** `G-2-072` — event_log 表的行级锁实现（FOR UPDATE SKIP LOCKED）的具体 SELECT 语句格式
#### G-2-2 Temporal

- **[UNRESOLVED]** `G-2-011` — Temporal namespace 名称（default 还是 daemon 专用 namespace）
- **[UNRESOLVED]** `G-2-012` — Temporal workflow retention period 配置（workflow history 保留多长时间）
- **[UNRESOLVED]** `G-2-013` — Job Workflow 的 execution_timeout 默认值（防止 Workflow 永远不结束）
- **[UNRESOLVED]** `G-2-014` — Step Activity 的 schedule_to_close_timeout 与 start_to_close_timeout 的区别及各自默认值
- **[DEFAULT]** `G-2-015` — Temporal RetryPolicy 默认参数：initial_interval、backoff_coefficient、maximum_interval、maximum_attempts · 覆盖：附录 B
- **[DEFAULT]** `G-2-016` — Temporal Schedules 的 timezone 配置（默认 UTC 还是用户本地时区） · 覆盖：附录 B
- **[DEFAULT]** `G-2-017` — Temporal Schedule 的 jitter_window 配置（防止大量定时任务同时触发） · 覆盖：附录 B
- **[UNRESOLVED]** `G-2-018` — Worker 进程 graceful shutdown 时，正在执行的 Activity 如何处理（等待完成 vs 取消）
- **[UNRESOLVED]** `G-2-019` — Temporal Server 与 daemon Worker 的认证方式（mTLS 还是无认证的本地部署）
- **[UNRESOLVED]** `G-2-020` — Temporal Signal 的 signal name 枚举（pause_job、resume_job、cancel_job、review_approved 等完整列表）
- **[UNRESOLVED]** `G-2-021` — `asyncio.gather` 并行执行 Step Activities 时，单个 Activity 失败是否立即取消其他并行 Activity
- **[UNRESOLVED]** `G-2-073` — Temporal Worker 注册 Activity 的方式——是 `@activity.defn` 装饰器还是显式 `register_activity`
- **[UNRESOLVED]** `G-2-074` — Temporal Workflow 的 `workflow.logger` 与 Python logging 的集成——日志是否写入统一日志文件
- **[UNRESOLVED]** `G-2-075` — Temporal Activity 的 heartbeat 机制——长时间运行的 Activity（如 agent session）是否需要定期调用 `activity.heartbeat()`
- **[UNRESOLVED]** `G-2-076` — Temporal Schedule 的 `catch_up_window` 配置——系统宕机恢复后，积压的定时任务是否补执行（catch-up）
- **[UNRESOLVED]** `G-2-077` — Temporal Workflow 的 `id_reuse_policy`——同一 workflow_id 是否允许重用（Job 重试时）
- **[UNRESOLVED]** `G-2-078` — Temporal Worker 的 `sticky_schedule_to_start_timeout` 配置——防止 sticky execution 超时导致 Activity 卡住
- **[UNRESOLVED]** `G-2-079` — Temporal 本地开发环境使用 temporalio[sandbox] 还是真实 Temporal Server（docker-compose 中是否包含 Temporal）
#### G-2-3 Plane

- **[UNRESOLVED]** `G-2-022` — Plane Workspace slug 的配置方式（hardcoded 还是环境变量）
- **[UNRESOLVED]** `G-2-023` — Plane webhook secret 的存储位置（.env 文件还是其他 secret 管理）
- **[UNRESOLVED]** `G-2-024` — Plane webhook 事件类型过滤——daemon 只监听哪些事件（issue.created、issue.updated、issue.status_updated 等）
- **[UNRESOLVED]** `G-2-025` — Plane API 认证方式（API token 还是 session cookie，token 存储在哪里）
- **[UNRESOLVED]** `G-2-026` — Plane API rate limit——daemon 在写回 Job 状态时的限流策略
- **[UNRESOLVED]** `G-2-027` — Plane Issue 的 custom field 方案——daemon 需要的额外字段（dag、brief、trigger_type 等）存在 Plane 哪里
- **[UNRESOLVED]** `G-2-028` — Plane DraftIssue 的完整 API 路径（Plane 文档中 DraftIssue endpoint 的具体 URL）
- **[UNRESOLVED]** `G-2-029` — Plane webhook 签名验证算法（HMAC-SHA256 标准，secret key 名称、header 名称）
- **[UNRESOLVED]** `G-2-030` — Plane IssueRelation type 枚举——`blocked_by` 是否为 Plane 正式支持的 relation type
- **[UNRESOLVED]** `G-2-080` — Plane Issue 的 `state_id`（状态组 ID）与 daemon Job 状态的映射表——每种 Job 状态对应哪个 Plane state
- **[UNRESOLVED]** `G-2-081` — Plane Project 的 `identifier` 字段（短前缀）是否需要 daemon 在创建 Project 时配置
- **[UNRESOLVED]** `G-2-082` — Plane Module（对应 daemon Project 的备选）与 Plane Project 的差异——daemon 最终选择哪个，以及选择依据
- **[UNRESOLVED]** `G-2-083` — Plane webhook 超时重试机制——Plane 如果没收到 200 响应，会重试几次，daemon 如何处理重复 webhook
- **[UNRESOLVED]** `G-2-084` — Plane API 的分页参数格式（cursor-based 还是 offset-based，默认 page_size）
- **[UNRESOLVED]** `G-2-085` — Plane DraftIssue 转正式 Issue 的 API 调用——转换后 issue_id 是否变化（是否需要 daemon 更新引用）
- **[UNRESOLVED]** `G-2-086` — Plane IssueRelation 创建 API 的请求体格式（`issue_id`、`related_issue_id`、`relation_type` 字段名）
#### G-2-4 Langfuse

- **[UNRESOLVED]** `G-2-031` — Langfuse trace 的层级结构——Trace > Span > Generation 如何对应 Job > Step > LLM call
- **[UNRESOLVED]** `G-2-032` — Langfuse SDK 初始化参数（public_key、secret_key、host 的配置位置）
- **[UNRESOLVED]** `G-2-033` — Langfuse trace 中 job_id、task_id、agent_id 作为 metadata 的字段名（标准化命名）
- **[UNRESOLVED]** `G-2-034` — Langfuse generation 的 model 字段格式（与 OC model name 的映射关系）
- **[UNRESOLVED]** `G-2-035` — Langfuse 告警阈值（单 Step token 消耗 > X tokens 触发告警）的具体数值由谁配置、存在哪里
- **[UNRESOLVED]** `G-2-036` — Langfuse 与 Worker 进程的集成方式——是否使用 Langfuse Python SDK 的 @observe 装饰器
- **[UNRESOLVED]** `G-2-087` — Langfuse SDK 的 `flush_at` 和 `flush_interval` 配置——Temporal Activity 完成后是否需要显式调用 `langfuse.flush()`
- **[UNRESOLVED]** `G-2-088` — Langfuse trace 的 `session_id` 字段是否映射到 OC session key（`{agent_id}:{job_id}:{step_id}`）
- **[UNRESOLVED]** `G-2-089` — Langfuse 在 Activity 超时或崩溃时，未完成 generation 的 end 时间如何处理（是否有 TTL 自动结束）
- **[UNRESOLVED]** `G-2-090` — Langfuse self-hosted 版本的 `NEXTAUTH_SECRET` 和 `ENCRYPTION_KEY` 的生成和存储位置
#### G-2-5 MinIO

- **[UNRESOLVED]** `G-2-037` — MinIO bucket 命名规范（artifacts、knowledge-cache、plane-uploads 等 bucket 的完整列表）
- **[UNRESOLVED]** `G-2-038` — Artifact MinIO 路径规范的完整定义（artifacts/{task_id}/{job_id}/{step_id}/{artifact_type} 已有，但 artifact_type 的枚举值需确认）
- **[UNRESOLVED]** `G-2-039` — MinIO 对象的 presigned URL 过期时间（用于临时共享时）
- **[UNRESOLVED]** `G-2-040` — MinIO 访问策略（bucket policy）——artifacts bucket 是否设置公开读还是全程 presigned URL
- **[UNRESOLVED]** `G-2-041` — 大文件上传的 multipart 阈值（超过多少 MB 使用 multipart upload）
- **[UNRESOLVED]** `G-2-091` — MinIO bucket 的 versioning 设置——Artifact 是否开启对象版本控制
- **[UNRESOLVED]** `G-2-092` — MinIO bucket 的 lifecycle 规则——Artifact 是否设置自动过期删除策略
- **[UNRESOLVED]** `G-2-093` — MinIO 与 Langfuse/Plane 共用同一个实例时，bucket 间的访问隔离（是否使用不同 access key）
- **[UNRESOLVED]** `G-2-094` — Artifact 下载时的认证方式——是 presigned URL 还是通过 daemon API 代理转发
#### G-2-6 Mem0

- **[UNRESOLVED]** `G-2-042` — Mem0 的存储后端配置——使用本地 SQLite 还是 PostgreSQL（与现有 PG 实例共用）
- **[UNRESOLVED]** `G-2-043` — Mem0 `agent_id` 的完整枚举（counsel、scholar、artificer、scribe、arbiter、envoy、steward + user 级别的 user_persona）
- **[UNRESOLVED]** `G-2-044` — Mem0 `user_id` 的值（系统只有单用户时固定为什么值）
- **[DEFAULT]** `G-2-045` — Mem0 search 的 limit 参数默认值（SYSTEM_DESIGN.md 示例代码中是 5，是否为最终值） · 覆盖：附录 B
- **[UNRESOLVED]** `G-2-046` — Mem0 记忆条目的 metadata 字段设计（task_type、created_at 等附加元数据）
- **[UNRESOLVED]** `G-2-047` — Mem0 的版本要求（mem0ai 库版本，API 兼容性）
- **[UNRESOLVED]** `G-2-048` — Mem0 自动提取记忆候选的触发方式——是否在每次 session 结束时调用 m.add()，还是只在明确的 Persona 更新时调用
- **[UNRESOLVED]** `G-2-095` — Mem0 在同一进程内的并发安全性——多个 Temporal Activity 并发调用 `m.search()` 是否线程安全
- **[UNRESOLVED]** `G-2-096` — Mem0 `add()` 的去重机制——相同内容重复写入时的行为（覆盖 vs 追加 vs 忽略）
- **[UNRESOLVED]** `G-2-097` — Mem0 对 `agent_id` 为 `user_persona` 的特殊处理——所有 agent 都可检索，是否需要特别配置
- **[UNRESOLVED]** `G-2-098` — Mem0 记忆的元数据（metadata）字段在检索时是否可过滤（如按 task_type 过滤记忆）
- **[UNRESOLVED]** `G-2-099` — Mem0 的 `run_id` 参数是否对应 job_id（用于按 Job 隔离单次执行的上下文）
#### G-2-7 NeMo Guardrails

- **[UNRESOLVED]** `G-2-049` — NeMo Guardrails config 目录结构（config/guardrails/ 下的文件组织）
- **[UNRESOLVED]** `G-2-050` — Colang 规则文件的命名约定（input_rails.co、output_rails.co 等）
- **[UNRESOLVED]** `G-2-051` — NeMo rails.generate() 调用的 messages 格式（role/content 列表还是单字符串）
- **[UNRESOLVED]** `G-2-052` — NeMo custom action 的注册方式（@action 装饰器，注册时机是 Worker 启动时还是每次调用时）
- **[UNRESOLVED]** `G-2-053` — NeMo Guardrails 在 Worker 进程中的单例模式（全局一个 LLMRails 实例还是每次 Activity 创建）
- **[UNRESOLVED]** `G-2-054` — source_tiers.toml 的文件格式（TOML 结构：domain → tier 映射，还是 URL 前缀 → tier 映射）
- **[UNRESOLVED]** `G-2-055` — sensitive_terms.json 的格式（字符串数组还是对象结构）
- **[UNRESOLVED]** `G-2-100` — NeMo Guardrails 的 `config.yml` 文件的完整结构（models 配置、rails 配置、instructions 配置）
- **[UNRESOLVED]** `G-2-101` — Colang 规则中 `define flow` 的命名约定（如 `input check sensitive terms`）
- **[UNRESOLVED]** `G-2-102` — NeMo custom action 中调用 Mem0 的方式——action 函数签名和注册方式
- **[UNRESOLVED]** `G-2-103` — NeMo Guardrails 检测到违规时的返回格式——`output["content"]` 是被替换的安全响应还是空字符串
- **[UNRESOLVED]** `G-2-104` — NeMo Guardrails 在 Worker 进程中使用哪个 LLM provider 作为 rails 判断模型（是否使用 fast 模型降低成本）
#### G-2-8 RAGFlow

- **[UNRESOLVED]** `G-2-056` — RAGFlow 的 API endpoint 格式（/api/v1/* 路径，用于上传/检索文档）
- **[UNRESOLVED]** `G-2-057` — RAGFlow 的认证方式（API key 或 Bearer token）
- **[UNRESOLVED]** `G-2-058` — RAGFlow knowledge base 的创建方式——daemon 自动创建还是手动创建后配置 ID
- **[UNRESOLVED]** `G-2-059` — RAGFlow 文档分块参数（chunk_size、chunk_overlap 的默认值）
- **[DEFAULT]** `G-2-060` — RAGFlow 检索的 top_k 默认值（返回几个相关分块注入 prompt） · 覆盖：附录 B
- **[UNRESOLVED]** `G-2-061` — RAGFlow 与 knowledge_cache PG 表的同步关系（ragflow_doc_id 字段如何维护）
- **[UNRESOLVED]** `G-2-105` — RAGFlow API 的分块检索返回格式（content、score、source_url 字段的具体结构）
- **[UNRESOLVED]** `G-2-106` — RAGFlow 的 knowledge base 是按 Job 隔离还是全局共享（scholar 搜索的结果是否跨 Job 共用）
- **[UNRESOLVED]** `G-2-107` — RAGFlow 文档 ID（ragflow_doc_id）写入 knowledge_cache PG 表的时机（上传时还是首次检索时）
#### G-2-9 Firecrawl

- **[UNRESOLVED]** `G-2-062` — Firecrawl 的 API endpoint 和认证方式（自部署版本的 URL 格式）
- **[UNRESOLVED]** `G-2-063` — Firecrawl 的 crawl vs scrape 选择规则（单页用 scrape，多页用 crawl）
- **[UNRESOLVED]** `G-2-064` — Firecrawl 返回的 Markdown 的最大长度处理（超长时如何截断或分段存储）
- **[UNRESOLVED]** `G-2-108` — Firecrawl 自部署时的 Docker Compose 配置（是否单独运行还是集成在 daemon docker-compose.yml 中）
- **[UNRESOLVED]** `G-2-109` — Firecrawl 返回内容的 `metadata` 字段（title、description、og_image 等）是否需要提取和存储
- **[UNRESOLVED]** `G-2-110` — Firecrawl 失败（目标网站不可达、超时）时，scholar 的降级策略（直接跳过该 URL 还是通知 Job 失败）
#### G-2-10 部署与运行环境

- **[UNRESOLVED]** `G-2-111` — daemon 的 Docker Compose 文件（docker-compose.yml）中 Plane 服务的 volume 挂载策略——Plane 数据库是否与宿主机目录绑定挂载
- **[UNRESOLVED]** `G-2-112` — Temporal Server 在 Docker 中是否需要 PostgreSQL 作为 backend（Temporal 默认使用 SQLite 还是 PG）
- **[UNRESOLVED]** `G-2-113` — Langfuse 在 Docker 中依赖 ClickHouse 的服务名称和端口——daemon Worker 是否需要直接访问 ClickHouse
- **[UNRESOLVED]** `G-2-114` — RAGFlow 在 Docker 中的服务名称和 HTTP API 端口——daemon Worker 通过什么 URL 访问 RAGFlow
- **[UNRESOLVED]** `G-2-115` — Firecrawl 在 Docker 中的服务名称——是集成在 docker-compose.yml 还是单独部署
- **[UNRESOLVED]** `G-2-116` — 所有 Docker 服务的日志驱动配置（json-file with rotation 还是 syslog）
- **[UNRESOLVED]** `G-2-117` — MinIO 的 Console UI 端口（9001）是否需要对外暴露，还是只需要 API 端口（9000）
- **[UNRESOLVED]** `G-2-118` — Plane 的 Worker 和 Beat 服务（Celery）的 Redis 配置——daemon 是否可以共用同一个 Redis 实例
### G-3 执行层（Step/Job/Task/Project）

#### G-3-1 Job 生命周期

- **[UNRESOLVED]** `G-3-001` — Job 在 PG 中的完整字段定义（job_id、task_id、workflow_id、status、sub_status、dag_snapshot、requires_review、created_at、started_at、closed_at 等）
- **[UNRESOLVED]** `G-3-002` — Job 创建时的原子操作边界——"创建 + 立即执行"是在同一个数据库事务中完成，还是先写 PG 再异步启动 Temporal
- **[UNRESOLVED]** `G-3-003` — Job ID 的格式规范（UUID v4 还是 ULID 还是其他格式）
- **[UNRESOLVED]** `G-3-004` — 同一 Task 同一时刻只有一个非 closed Job 的并发控制机制（数据库唯一约束还是应用层检查）
- **[UNRESOLVED]** `G-3-005` — Job 进入 running(paused) 状态的 Temporal Signal name（pause_for_review 还是 awaiting_review）
- **[UNRESOLVED]** `G-3-006` — Job paused 状态下用户批准后发送什么 Signal（review_approved 还是 resume_job）
- **[UNRESOLVED]** `G-3-007` — Job cancelled 状态的触发来源（用户主动取消 vs 系统错误取消，sub_status 是否相同）
- **[UNRESOLVED]** `G-3-008` — Job closed(failed) 后是否允许重新执行（创建新 Job 还是直接拒绝）
- **[UNRESOLVED]** `G-3-009` — Job Workflow 的 Temporal workflow_id 格式（是否包含 job_id 以便追溯）
- **[UNRESOLVED]** `G-3-010` — Job 的 dag_snapshot 字段存储 Step DAG 的完整 JSON（schema 定义：steps 数组，每个 step 的字段）
- **[UNRESOLVED]** `G-3-011` — Job closed 后写回 Plane Issue Activity 的内容格式（comment 还是 activity，包含哪些信息）
- **[DEFAULT]** `G-3-012` — Plane API 状态回写失败的补偿策略——重试耗尽后记录 `plane_sync_failed` / 错误详情，并定义人工补写或异步重放的恢复路径（不因单次回写失败直接改写 Job 业务结果） · 覆盖：§6.4 + 附录 B
- **[UNRESOLVED]** `G-3-013` — Job Workflow execution_timeout 与 Step Activity timeout 的层级关系（Job 超时是否自动取消正在执行的 Step）
- **[UNRESOLVED]** `G-3-085` — Job 的 `workflow_id` 在 Temporal 中的格式（`job-{job_id}` 还是直接使用 job_id）
- **[UNRESOLVED]** `G-3-086` — Job 创建失败（如 Temporal Server 不可达）时，PG 中已写入的 Job 记录如何处理（是否有回滚机制）
- **[UNRESOLVED]** `G-3-087` — `requires_review: true` 的 Job 进入 `running(paused)` 状态时，通知用户的方式（envoy Telegram 通知还是 Plane comment）
- **[UNRESOLVED]** `G-3-088` — `requires_review: true` 是在 Job 整体创建时决定，还是在某个 Step 开始执行前检查（counsel 可否在执行中途标记某 Step 需要 review）
- **[UNRESOLVED]** `G-3-089` — Job closed 后向 Plane 写回的具体内容——comment 的 markdown 格式，包括 Job ID、执行时间、Step 摘要的模板
- **[UNRESOLVED]** `G-3-090` — Plane comment 写回失败（API 超时、rate limit）时的重试次数上限和补偿策略
- **[UNRESOLVED]** `G-3-091` — Job 超时（`execution_timeout` 到达）时，正在执行的 Step Activity 如何被取消（Temporal Workflow cancel → Activity cancel）
- **[UNRESOLVED]** `G-3-092` — Job cancelled 时（用户主动取消），Temporal Workflow cancel signal 的发送路径（API 进程收到请求 → 直接调 Temporal cancel 还是通过 PG 事件通知 Worker）
- **[UNRESOLVED]** `G-3-093` — 同一 Task 的并发控制——数据库唯一约束的具体实现（`UNIQUE (task_id) WHERE status != 'closed'` 是否 PostgreSQL 支持这种部分唯一约束）
- **[FINAL]** `G-3-139` — 迟到反馈的语义——用户回到 Task 页面重新执行时，是否视为对上次 Job 结果的隐式否定，以及该信号如何进入后续执行与学习回路 · 覆盖：§3.1
#### G-3-2 Step 执行

- **[UNRESOLVED]** `G-3-014` — Step 在 PG / `dag_snapshot.steps` 中的完整字段定义（step_id、job_id、goal、agent、model、execution_type、depends_on、status、input_artifacts、output_artifact_id、started_at、completed_at、token_usage、error_message）
- **[UNRESOLVED]** `G-3-015` — Step ID 是否全局唯一（还是仅在 Job 内唯一）
- **[FINAL]** `G-3-016` — Step status 的完整枚举（pending/running/completed/failed/skipped）和 skipped 的触发条件 · 覆盖：§3.3 + 附录 C
- **[DEFAULT]** `G-3-017` — direct Step 的执行超时默认值（不同操作类型的超时：shell 命令 vs API 调用 vs 文件操作） · 覆盖：附录 B
- **[DEFAULT]** `G-3-018` — agent Step 的 runTimeoutSeconds 按类型设定的完整表（search:60s、writing:180s、review:90s 已有，其他类型的值） · 覆盖：附录 B
- **[DEFAULT]** `G-3-019` — Step 重试的 RetryPolicy 具体参数（initial_interval=5s、backoff_coefficient=2、maximum_attempts=3 等） · 覆盖：附录 B
- **[UNRESOLVED]** `G-3-020` — Step 失败后 counsel 判断的触发方式——由哪个 Temporal Activity 发起 counsel session
- **[UNRESOLVED]** `G-3-021` — counsel 判断 Step 失败时的输入 prompt 格式（提供什么信息：目标、错误信息、已完成 Step 摘要）
- **[UNRESOLVED]** `G-3-022` — counsel 判断 Step 失败时的输出格式（decision: skip/replace/terminate + reason）
- **[UNRESOLVED]** `G-3-023` — Step 被 counsel 决定 skip 后，依赖该 Step 的下游 Step 如何处理（是否传空 Artifact）
- **[UNRESOLVED]** `G-3-024` — Step 被 counsel 决定 replace 时，新 Step 的 session key 格式（与原 Step 的 step_id 关系）
- **[UNRESOLVED]** `G-3-025` — claude_code Step 的具体调用方式（subprocess 命令行参数，传入什么 context）
- **[UNRESOLVED]** `G-3-026` — codex Step 的具体调用方式（subprocess 命令行参数）
- **[UNRESOLVED]** `G-3-027` — claude_code/codex Step 的工作目录（DAEMON_HOME 还是临时目录）
- **[UNRESOLVED]** `G-3-028` — claude_code/codex subprocess 的超时时间和输出捕获方式（stdout/stderr 如何处理）
- **[UNRESOLVED]** `G-3-029` — direct Step 执行 shell 命令的方式（subprocess.run 还是 asyncio.create_subprocess_shell）
- **[UNRESOLVED]** `G-3-030` — direct Step shell 命令失败（非零退出码）的处理规则（是否触发 Temporal retry）
- **[UNRESOLVED]** `G-3-065` — Step Activity 在 Temporal 中的实现方式——是否所有 Step 类型（agent/direct/claude_code/codex）都在同一个 Activity 函数中用 `execution_type` 分支，还是每种类型一个独立 Activity
- **[UNRESOLVED]** `G-3-066` — agent Step 的完整执行流程——`sessions_spawn` → `sessions_send`（注入指令）→ `sessions_receive`（轮询结果）→ `sessions_close` 的每一步的 API 路径和参数
- **[UNRESOLVED]** `G-3-067` — Step 指令（结构化 JSON）注入 OC session 的方式——作为首条 user message 发送，还是通过 session attachments 注入
- **[UNRESOLVED]** `G-3-068` — Mem0 检索结果注入 Step 的位置——是放在 MEMORY.md 内容之后、Step 指令之前，还是嵌入 Step 指令的 context 字段
- **[UNRESOLVED]** `G-3-069` — `runTimeoutSeconds` 在 OC sessions_spawn 中的参数名——是 `run_timeout_seconds` 还是其他字段名
- **[UNRESOLVED]** `G-3-070` — Step 完成后 Artifact 提取的具体方式——从 OC session 的最后一条 assistant message 提取，还是 agent 通过特定格式（如 ```artifact...```）标记输出
- **[UNRESOLVED]** `G-3-071` — Artifact 摘要的生成方式——是 agent 自动生成（在 Step 指令中要求），还是 Activity 层对输出做机械截断
- **[UNRESOLVED]** `G-3-072` — 上游 Artifact 摘要注入下游 Step 时的格式——作为 Step 指令中的 `context.artifacts` 字段还是单独的 user message
- **[UNRESOLVED]** `G-3-073` — direct Step 中 MCP tool 调用的参数格式——`MCPDispatcher.call_tool(tool_name, arguments)` 中 `arguments` 的类型（dict 还是 JSON 字符串）
- **[UNRESOLVED]** `G-3-074` — direct Step 执行 shell 命令的工作目录默认值（DAEMON_HOME 还是由 Step 指令中的 `cwd` 字段指定）
- **[UNRESOLVED]** `G-3-075` — direct Step 成功的判定标准——shell 命令退出码为 0，还是由 Step 指令中的 `success_condition` 字段定义
- **[UNRESOLVED]** `G-3-076` — claude_code subprocess 的启动参数——是 `claude --dangerously-skip-permissions` 还是其他参数组合
- **[UNRESOLVED]** `G-3-077` — claude_code subprocess 的输入传递方式——通过 stdin pipe 还是临时文件 + `-f` 参数
- **[UNRESOLVED]** `G-3-078` — claude_code subprocess 的输出解析方式——如何从 stdout 中提取最终 Artifact（是否有固定格式标记）
- **[UNRESOLVED]** `G-3-079` — codex subprocess 的等价启动参数和输出解析方式
- **[UNRESOLVED]** `G-3-080` — Step Activity 崩溃（Python exception，非 timeout）时，Temporal 的 retry 行为——是否立即重试还是等待 initial_interval
- **[UNRESOLVED]** `G-3-081` — Step Activity 的 Temporal heartbeat 超时与 `start_to_close_timeout` 的关系——heartbeat 超时是否触发 Activity 重试
- **[UNRESOLVED]** `G-3-082` — agent Step 中 OC session 返回错误（非 200）时，Activity 抛出哪种 exception（让 Temporal 重试）
- **[UNRESOLVED]** `G-3-083` — 并行 Step 的 `asyncio.gather` 中，部分失败时已完成的并行 Step 的 Artifact 是否保留（等待 counsel 决策时仍可用）
- **[UNRESOLVED]** `G-3-084` — DAG 执行引擎的实现位置——是在 Temporal Workflow 代码中（Python `asyncio.gather` + topological sort）还是在独立的 Activity 中
- **[FINAL]** `G-3-137` — arbiter 审查失败后传入 rework session 的机制——替换 Step 的新 session 如何接收结构化审查结果，而不是复用旧对话上下文 · 覆盖：§3.5
#### G-3-3 Artifact 机制

- **[UNRESOLVED]** `G-3-031` — job_artifacts PG 表的完整 schema（已有定义，确认是否需要 content_hash 字段用于去重）
- **[UNRESOLVED]** `G-3-032` — Artifact 的 artifact_type 完整枚举（text、file、structured、code、report 等）
- **[UNRESOLVED]** `G-3-033` — Artifact summary 的最大长度限制（注入 prompt 时的 token 预算）
- **[UNRESOLVED]** `G-3-034` — Artifact 全文存 MinIO、摘要存 PG 的边界——什么情况下不存 MinIO 仅存 PG（纯文本短 Artifact 的阈值）
- **[UNRESOLVED]** `G-3-035` — 同一 Step 产出多个 Artifact 时的处理规则（是否允许，如何在 job_artifacts 中区分）
- **[UNRESOLVED]** `G-3-036` — Job 间 Artifact 传递时，`task_input_from: ["task:T1:final_artifact"]` 的语法解析规则
- **[UNRESOLVED]** `G-3-037` — Artifact 内部版本（含来源标记 [EXT/INT/SYS]）的格式规范和存储位置
- **[UNRESOLVED]** `G-3-038` — Artifact 保留策略——Artifact 文件存 MinIO 多久后可以删除（或永久保留）
- **[UNRESOLVED]** `G-3-039` — 来源标记的注入规范——agent 在 prompt 中何时写 [EXT:url]、[INT:persona]、[SYS:guardrails]
#### G-3-4 Routing Decision

- **[UNRESOLVED]** `G-3-040` — counsel routing decision 输出的完整 JSON schema（route/intent/task/project 等字段的完整定义）
- **[FINAL]** `G-3-041` — route: "direct" 时的临时 Job 语义——是否跳过 Project/Task 对象创建、是否仅创建无 Task 归属的 ephemeral Job，以及该 Job 是否在 PG 中持久化 · 覆盖：§3.1
- **[FINAL]** `G-3-042` — route: "direct" 时 Step DAG 只有一个 Step 还是可能有多个 Step · 覆盖：§3.1
- **[UNRESOLVED]** `G-3-043` — counsel 判断追问还是执行的时机——追问次数上限（防止无限追问循环）
- **[UNRESOLVED]** `G-3-044` — counsel 追问的结果存储位置（Plane DraftIssue 的 activity 还是 daemon PG）
- **[FINAL]** `G-3-045` — route: "task" 时，counsel 创建 Plane Issue 的 API 调用序列（先创建 Issue 还是先规划 DAG） · 覆盖：§3.1
- **[FINAL]** `G-3-046` — route: "project" 时，counsel 创建 Plane Project + Issue 的顺序和事务性 · 覆盖：§3.1
- **[UNRESOLVED]** `G-3-047` — counsel 在 routing 时使用 fast 模型，在 project 规划时使用 analysis 模型——切换时机的代码实现（同一 Activity 中切换还是不同 Activity）
- **[UNRESOLVED]** `G-3-048` — 用户意图模糊时 counsel 的追问格式（多问题一次问完 vs 逐步追问）
- **[UNRESOLVED]** `G-3-094` — counsel routing decision session 的 session key 格式（不属于任何 Job 的 session，如 `counsel:routing:{request_id}`）
- **[UNRESOLVED]** `G-3-095` — counsel routing decision 的输出 JSON 解析失败时（LLM 返回非法 JSON）的处理——重试还是回退到追问
- **[DEFAULT]** `G-3-096` — route: "direct" 的 temporary Job 在 PG 中的标记（是否有 `is_ephemeral: true` 字段） · 覆盖：§3.1 + 附录 C
- **[UNRESOLVED]** `G-3-097` — counsel 追问次数计数的存储位置（PG session 记录还是 Plane DraftIssue 的 metadata）
- **[UNRESOLVED]** `G-3-098` — route: "task" 时，counsel 如何确定目标 Plane Project（默认 Project 还是根据意图选择）
- **[UNRESOLVED]** `G-3-099` — route: "project" 时，counsel 创建的 Plane Project 的 identifier 字段如何生成（基于 Project title 的缩写还是自动生成）
- **[UNRESOLVED]** `G-3-100` — Routing Decision 在 Temporal Activity 中执行还是在 API 进程中直接调用 OC（不通过 Temporal）
- **[UNRESOLVED]** `G-3-101` — counsel 在 routing 时读取 Mem0 的 agent_id 参数（用 `counsel` 还是 `user_persona`）
- **[UNRESOLVED]** `G-3-102` — 用户通过 Telegram 发送指令时，routing decision 的触发路径（Telegram webhook → API 进程 → counsel session）
- **[FINAL]** `G-3-135` — Plane 对象创建的执行责任归属——routing decision 落地时，由 counsel 通过 MCP / Plane API 创建 Task / Project，还是由 Worker Activity 代执行 · 覆盖：§3.1
- **[FINAL]** `G-3-138` — 新 Task 首个 Job 的初始 DAG 生成输入——Plane Issue description、Issue Activity、Mem0 规划经验各自的读取顺序与组装规则 · 覆盖：§3.4
#### G-3-5 Replan Gate

- **[UNRESOLVED]** `G-3-103` — Replan Gate 在哪个 Temporal 组件中执行——是 Job Workflow 内的 Activity 还是独立的 Workflow
- **[UNRESOLVED]** `G-3-104` — Replan Gate 的 counsel session 的输入内容格式（Project goal 摘要的 token 预算限制）
- **[UNRESOLVED]** `G-3-105` — Replan Gate 判断"偏离"的标准——counsel 的 prompt 中如何描述"偏离"条件（量化标准还是语义判断）
- **[UNRESOLVED]** `G-3-106` — Replan Gate 输出新 DAG 时，Plane Issue 的创建/删除操作是否有事务性保证（部分 Issue 创建失败时的回滚）
- **[UNRESOLVED]** `G-3-107` — Replan Gate 的结果存储位置——是写入 PG 的 jobs 表（replan_count 字段）还是独立的 replanning_history 表
- **[DEFAULT]** `G-3-108` — Replan Gate 执行时间预算——counsel 轻量判断的 `runTimeoutSeconds`（~60s）和完整重规划的 `runTimeoutSeconds`（~180s） · 覆盖：附录 B
- **[UNRESOLVED]** `G-3-136` — Replan Gate 输出的具体格式——对未执行 Task 列表使用何种 diff / patch schema，以及已完成 Artifact 摘要如何自动注入新规划上下文
#### G-3-6 Step 并行与 DAG

- **[UNRESOLVED]** `G-3-049` — topological_sort 实现——如何处理有环 DAG（防御性检测，发现环时立即 fail Job）
- **[UNRESOLVED]** `G-3-050` — 并行 Step 中某个失败时是否等待其他并行 Step 完成（还是立即取消所有并行 Step）
- **[UNRESOLVED]** `G-3-051` — Step 依赖的 depends_on 字段类型（step_id 列表还是整数序号列表）
- **[UNRESOLVED]** `G-3-052` — `asyncio.gather` 执行并行 Step 时的 return_exceptions 参数（True 还是 False）
- **[UNRESOLVED]** `G-3-053` — 超过 20 个 Task 的 Project 的 Artifact 摘要截断规则——"只保留最近 5 个已完成"的排序依据（按完成时间还是按 DAG 层级）
- **[UNRESOLVED]** `G-3-054` — Replan Gate 判断用的 counsel session 的 session key 格式（不属于某个 Job 的 Step）
- **[DEFAULT]** `G-3-055` — Replan Gate 输出的 diff 格式（JSON patch 格式的完整 schema：add/remove/modify 操作） · 覆盖：§3.5 + 附录 D
- **[UNRESOLVED]** `G-3-056` — Replan Gate 修改 Task 列表后，如何更新 Plane 中的 Issue（通过 Plane API 还是仅存 PG）
- **[UNRESOLVED]** `G-3-057` — Replan Gate 是否有最大重规划次数限制（防止反复偏离 → 反复重规划的无限循环）
- **[UNRESOLVED]** `G-3-109` — `topological_sort` 的具体 Python 实现——是使用 `graphlib.TopologicalSorter`（Python 3.9+）还是自定义 Kahn 算法
- **[UNRESOLVED]** `G-3-110` — 并行 Step 中某 Step 超时（timeout）与某 Step 失败（exception）对 Job 的影响是否相同（都触发 counsel 失败判断？）
- **[UNRESOLVED]** `G-3-111` — `asyncio.gather(return_exceptions=True)` 时，各 Step 的异常如何汇总给 counsel 判断（传递所有异常的 error_message）
- **[UNRESOLVED]** `G-3-112` — Step 的 `depends_on` 字段中，依赖的是 `step_id`（UUID）还是 `seq`（步骤序号）——counsel 规划时输出哪种格式
- **[UNRESOLVED]** `G-3-113` — DAG 中存在无依赖（独立）Step 与有依赖 Step 混合时，无依赖 Step 是否立即并行执行（不等待任何前序）
- **[UNRESOLVED]** `G-3-114` — Project 中 20 个以上 Task 时 Artifact 摘要截断的具体截断算法——按字符数截断（前 N 字符）还是按 token 数截断
#### G-3-7 Task 触发

- **[FINAL]** `G-3-058` — chain 触发时，前序 Task 的"最终 Job closed"是指最近一个 Job 还是任意一个 Job 的 closed · 覆盖：§3.6
- **[FINAL]** `G-3-059` — chain 触发时，前序 Task 的 Job 必须是 closed(succeeded) 还是任意 closed（包含 failed） · 覆盖：§3.6
- **[FINAL]** `G-3-060` — Temporal Schedule 的触发事件如何通知 daemon Worker（Schedule 内置 Workflow 还是定时 Signal） · 覆盖：§3.6 + 附录 D
- **[FINAL]** `G-3-061` — 手动触发（用户在 Plane 点击执行）的 webhook 事件到达 daemon 的完整路径 · 覆盖：§3.6 + 附录 D
- **[FINAL]** `G-3-062` — chain 触发时，Replan Gate 在哪个 Activity 中执行（在触发前序 chain 的同一 Activity 中还是独立 Activity） · 覆盖：§3.6
- **[FINAL]** `G-3-063` — Task 触发类型变更（手动→定时）时，Temporal Schedule 的创建/删除逻辑 · 覆盖：§3.6
- **[FINAL]** `G-3-064` — 定时触发的 Task，手动也触发一次时的处理规则（是否允许，是否跳过下一次定时触发） · 覆盖：§3.6
- **[FINAL]** `G-3-140` — Task 依赖关系的变更保护——依赖边是否必须通过 Plane UI / 显式操作变更，如何记录到 Activity，并禁止对已完成 Task 做无声改写 · 覆盖：§3.2
#### G-3-8 执行引擎与运行时实现

- **[UNRESOLVED]** `G-3-115` — counsel 规划输出的 `steps` 数组中，每个 Step 的 `id` 字段是序号（1, 2, 3）还是语义名称（还是 counsel 随机生成的 UUID）
- **[UNRESOLVED]** `G-3-116` — Step 完成后 Artifact 写入 job_artifacts PG 表时，`created_at` 字段使用数据库 `NOW()` 还是 Activity 的 Python `datetime.utcnow()`
- **[UNRESOLVED]** `G-3-117` — Temporal Workflow 代码中的 DAG 执行循环是否有无限循环保护（防止 topological_sort 出现 bug 导致 Workflow hang）
- **[UNRESOLVED]** `G-3-118` — Job DAG 中的 Step 数量是否有硬上限校验（在 Job 创建时检查 `dag_snapshot.steps` 长度 ≤ N）
- **[UNRESOLVED]** `G-3-119` — agent Step 在 OC session 中发送的消息格式——是 JSON 字符串直接作为文本消息，还是使用 OC 特定的结构化格式
- **[UNRESOLVED]** `G-3-120` — Step 级别的 NeMo Guardrails 检查时机——是在 `sessions_spawn` 之前（检查 Step 指令），还是在 `sessions_receive` 之后（检查产出）
- **[UNRESOLVED]** `G-3-121` — 执行类型为 `direct` 的 Step，其 `goal` 字段的格式——是自然语言描述还是结构化的操作定义（如 `{action: "run_shell", command: "git commit ..."}`)
- **[UNRESOLVED]** `G-3-122` — Job 的 `result_summary` 的生成逻辑——是最后一个 Step 的 Artifact 摘要，还是 counsel 对所有 Step 结果的综合摘要
- **[UNRESOLVED]** `G-3-123` — 当 Job 包含需要 `requires_review` 的 Step 时，Job 在哪个 Step 之后进入 `running(paused)` 状态（Step 完成后立即 paused，还是所有 Step 完成后 paused）
- **[DEFAULT]** `G-3-124` — Replan Gate 的最大执行时间上限——counsel 完整重规划的 `runTimeoutSeconds` 是否有 Job-level 的时间预算约束 · 覆盖：附录 B
- **[DEFAULT]** `G-3-125` — Temporal Schedule 的触发是否直接在 Temporal Workflow 中实现，还是 Temporal Schedule 触发一个独立的 "trigger" Workflow 再启动 Job Workflow · 覆盖：§3.6 + 附录 D
- **[UNRESOLVED]** `G-3-126` — chain 触发时，Replan Gate 的 counsel session 的 Mem0 查询类型（查询规划经验还是查询 Project 历史）
- **[UNRESOLVED]** `G-3-127` — `sessions_spawn` 失败后的 Activity retry 是否会尝试使用相同 session key（如果 OC 已经有该 key 的 session，是否会冲突）
- **[UNRESOLVED]** `G-3-128` — Job 的 `dag_snapshot` 字段在 PG 中存储为 JSONB 类型时，是否需要添加 GIN 索引（用于 JSON path 查询）
- **[UNRESOLVED]** `G-3-129` — `asyncio.gather` 并行 Step 执行时，每个 Step 使用独立的 `asyncio.Task`，超时控制是在 Activity 层用 `asyncio.wait_for` 还是在 Temporal `start_to_close_timeout`
- **[UNRESOLVED]** `G-3-130` — Job 在 `running(paused)` 状态等待 Signal 时，Temporal Workflow 是否消耗任何资源（Temporal Workflow 的 blocking wait 的资源成本）
- **[UNRESOLVED]** `G-3-131` — Temporal Activity 的 `heartbeat_timeout` 设置——对于长时间运行的 agent Step（如 writing: 180s），heartbeat_timeout 应设为多少
- **[UNRESOLVED]** `G-3-132` — `asyncio.gather` 中某个 Step Task 抛出 `asyncio.CancelledError` 时的处理（与普通 Exception 的区分）
- **[DEFAULT]** `G-3-133` — Job 的 `running(queued)` 状态的最大等待时间——是否有超时机制（等待 Temporal Worker 资源过久时从 queued 变 failed） · 覆盖：附录 B
- **[UNRESOLVED]** `G-3-134` — Artifact 的 `content_hash`（SHA-256）在 Artifact 写入时是否计算并存储（用于去重和完整性验证）
### G-4 对象模型（数据结构/字段/状态）

#### G-4-1 Task（Plane Issue 扩展）

- **[FINAL]** `G-4-001` — daemon 在 PG 中维护的 Task 扩展表（daemon_tasks）的完整字段定义——至少覆盖 `brief / dag / latest_job_id / trigger_type / trigger_config` 及其约束 · 覆盖：§2.3 + 附录 C
- **[FINAL]** `G-4-002` — `brief` 字段的 JSON schema（SYSTEM_DESIGN 提到 objective/language/format/depth/references 等） · 覆盖：附录 C
- **[FINAL]** `G-4-003` — `dag` 字段的 JSON schema（steps 数组，每个 step 的 id/goal/agent/model/depends_on/execution_type 字段） · 覆盖：附录 C
- **[FINAL]** `G-4-004` — `trigger_type` 字段的枚举值（manual/timer/chain）和互斥约束的数据库层实现（CHECK 约束） · 覆盖：§3.6 + 附录 C
- **[FINAL]** `G-4-005` — `trigger_config` 字段的 JSON schema（timer 时包含 cron 表达式，chain 时包含前序 task_id 列表） · 覆盖：附录 C
- **[FINAL]** `G-4-006` — `latest_job_id` 字段的更新时机（每次创建新 Job 时 UPDATE） · 覆盖：附录 C
- **[UNRESOLVED]** `G-4-007` — Task 在 Plane 侧的状态与 daemon 侧状态的同步规则（Job closed 后是否自动更新 Plane Issue 状态）
- **[UNRESOLVED]** `G-4-008` — Task 有 running Job 时，`dag` 字段的只读保护在 API 层的具体实现（HTTP 409 还是 Plane webhook 拦截）
- **[UNRESOLVED]** `G-4-009` — 首次创建 Task 时 `dag` 字段为空的处理——counsel 第一次规划时 Task 已在 Plane 存在，dag 如何写入
- **[UNRESOLVED]** `G-4-010` — Task 删除时，关联 Job 的处理规则（是否先取消运行中的 Job）
- **[UNRESOLVED]** `G-4-030` — daemon_tasks 表的 PG 表名（`daemon_tasks` 还是 `tasks`，避免与 Plane 内部表冲突的命名策略）
- **[UNRESOLVED]** `G-4-031` — `brief` 字段存储在 daemon_tasks 表还是单独的 task_briefs 表（JSONB 嵌入 vs 独立表）
- **[UNRESOLVED]** `G-4-032` — `dag` 字段中每个 Step 的 `model` 字段为 `null` 时的语义——使用 agent 默认模型，代码层如何处理 null
- **[UNRESOLVED]** `G-4-033` — Task 的 `brief.objective` 字段的最大长度限制（token 预算角度：注入 Replan Gate 时不能太长）
- **[UNRESOLVED]** `G-4-034` — Task 的 `brief.references` 字段的格式——字符串列表还是对象列表（包含 title 和 url）
- **[UNRESOLVED]** `G-4-035` — Task 的 `brief.dag_budget`（最大 Step 数）的默认值——是否从 Plane Issue 的某个 custom field 读取
- **[UNRESOLVED]** `G-4-036` — Task 首次被 Plane webhook 触发时，daemon_tasks 表的记录是否立即创建（还是在第一次执行时懒创建）
- **[UNRESOLVED]** `G-4-037` — daemon_tasks 表的 `updated_at` 字段的更新触发器——是 PG trigger 还是 ORM 层更新
- **[UNRESOLVED]** `G-4-038` — Task 的 `trigger_config.timer.timezone` 字段——Temporal Schedule 的 timezone 是否从这里读取
- **[UNRESOLVED]** `G-4-039` — Task 的 `trigger_config.chain.predecessor_task_ids` 字段——列表中 task_id 是 daemon 内部 ID 还是 Plane issue_id
- **[UNRESOLVED]** `G-4-063` — daemon_tasks 表是否有 `plane_project_id` 字段（存储 Plane Project 的 UUID）以便反向查询
- **[UNRESOLVED]** `G-4-067` — daemon_tasks 表的软删除实现——是否有 `deleted_at` 字段（Plane Issue 删除时设置）
#### G-4-2 Draft

- **[FINAL]** `G-4-069` — daemon 在 PG 中维护的 Draft 扩展表字段定义——至少覆盖 `intent_snapshot / candidate_brief / source / draft_status` 及其与 Plane DraftIssue 的关联 · 覆盖：附录 C
#### G-4-3 Job

- **[FINAL]** `G-4-011` — Job 的完整字段定义（超出 G-3-001 的补充字段：trigger_source、counsel_session_id、replan_count） · 覆盖：附录 C
- **[FINAL]** `G-4-012` — `requires_review` 字段由 counsel 在 DAG 规划时标记——标记的是 Job 级别还是 Step 级别（SYSTEM_DESIGN.md 两处都有提及） · 覆盖：§3.2 + 附录 C
- **[FINAL]** `G-4-013` — Job 的 `result_summary` 字段内容格式（由谁写入、何时写入） · 覆盖：附录 C
- **[FINAL]** `G-4-014` — Job 历史记录的保留策略（closed Job 在 PG 中保留多久） · 覆盖：附录 B
- **[FINAL]** `G-4-015` — 同一 Task 的多个历史 Job 中，latest_job_id 的语义（最新创建还是最新关闭） · 覆盖：附录 C
- **[UNRESOLVED]** `G-4-040` — Job 的 `trigger_source` 字段枚举值（`manual`/`timer`/`chain`/`replan` 等）
- **[UNRESOLVED]** `G-4-041` — Job 的 `counsel_session_id` 字段格式（与 OC session key 格式一致：`counsel:{job_id}:planning`）
- **[UNRESOLVED]** `G-4-042` — Job 的 `dag_snapshot` 字段与 Task 的 `dag` 字段的差异——`dag_snapshot` 是否包含执行时的 model override
- **[UNRESOLVED]** `G-4-043` — Job 的 `result_summary` 字段由哪个 Activity 写入（herald Activity 还是专门的 summarize Activity）
- **[UNRESOLVED]** `G-4-044` — Job 的 `error_message` 字段的内容格式（是最后一个失败 Step 的 error 还是 counsel 判断的终止原因）
- **[UNRESOLVED]** `G-4-045` — Job 历史的保留策略——closed Job 超过 N 天后是否物理删除 PG 记录（还是永久保留）
- **[UNRESOLVED]** `G-4-046` — Job `closed_at` 与 `result_summary` 的写入是否在同一个数据库事务中
- **[DEFAULT]** `G-4-066` — jobs 表中是否有 `total_token_usage` 字段（汇总所有 Step 的 token 消耗） · 覆盖：附录 C
#### G-4-4 Step（PG 记录）

- **[FINAL]** `G-4-016` — Step 在 PG 的存储方案——独立 job_steps 表还是嵌入 Job 的 JSONB 字段 · 覆盖：附录 C
- **[FINAL]** `G-4-017` — job_steps 表存在时的完整字段（step_id、job_id、seq、goal、agent、execution_type、model、status、started_at、completed_at、token_usage、error） · 覆盖：附录 C
- **[FINAL]** `G-4-018` — Step 的 `token_usage` 字段格式（prompt_tokens/completion_tokens/total_tokens 分开存，还是只存 total） · 覆盖：附录 C
- **[FINAL]** `G-4-019` — 多次重试的 Step，token_usage 是累计值还是最后一次的值 · 覆盖：附录 C
- **[UNRESOLVED]** `G-4-047` — job_steps 表是否使用独立的递增 `seq` 整数（1, 2, 3...）还是 UUID step_id 作为主键
- **[UNRESOLVED]** `G-4-048` — Step 的 `token_usage` 字段在 direct Step 中的值（直接存 0 还是 NULL）
- **[UNRESOLVED]** `G-4-049` — Step 的多次重试中，每次重试是否创建新的 job_steps 行，还是覆盖原行（通过 `retry_count` 字段记录）
- **[UNRESOLVED]** `G-4-050` — Step 的 `output_artifact_id` 字段——Step 没有输出时（如 pure direct Step）是否为 NULL
- **[UNRESOLVED]** `G-4-051` — job_steps 表中 Step 的顺序——`seq` 字段是 DAG 中的序号还是执行开始时间排序
- **[UNRESOLVED]** `G-4-052` — Step 的 `error_message` 字段的最大长度限制（异常堆栈可能很长，是否截断）
- **[UNRESOLVED]** `G-4-053` — Step `started_at` 的写入时机——Activity 开始执行时（Temporal Activity start）还是 OC session 创建时
- **[UNRESOLVED]** `G-4-054` — 并行执行的 Step 各自独立写入 job_steps 表，并发写入时是否需要行级锁
- **[DEFAULT]** `G-4-068` — job_steps 表中 `depends_on` 字段的存储格式（`INTEGER[]` 数组存 seq 还是 `TEXT[]` 存 step_id） · 覆盖：附录 C
#### G-4-5 Artifact

- **[DEFAULT]** `G-4-064` — job_artifacts 表的 `artifact_type` 字段是 ENUM 类型还是 VARCHAR（ENUM 修改需要 migrate，VARCHAR 更灵活） · 覆盖：附录 C
- **[DEFAULT]** `G-4-065` — `job_artifacts.minio_path` 字段的格式（`s3://artifacts/{task_id}/{job_id}/{step_id}/{filename}` 还是相对路径） · 覆盖：附录 C
#### G-4-6 知识缓存

- **[DEFAULT]** `G-4-020` — knowledge_cache 的向量索引参数（ivfflat lists 值，或 hnsw m/ef_construction 值） · 覆盖：附录 B
- **[DEFAULT]** `G-4-021` — knowledge_cache 的相似度阈值（embedding cosine 相似度 > 多少才视为命中） · 覆盖：附录 B
- **[DEFAULT]** `G-4-022` — knowledge_cache TTL 过期的检查频率（定时清理 Job 的间隔） · 覆盖：附录 B
- **[DEFAULT]** `G-4-023` — source_tiers.toml 的具体格式示例（域名白名单还是 URL 前缀，还是规则函数） · 覆盖：附录 D
- **[UNRESOLVED]** `G-4-055` — knowledge_cache 表中 `source_tier` 字段的枚举值（`A`/`B`/`C` 还是完整域名）
- **[UNRESOLVED]** `G-4-056` — knowledge_cache 的 `ttl_hours` 字段的默认值——A/B/C 三级各自的默认 TTL 小时数（如 A=2160h, B=720h, C=168h）
- **[UNRESOLVED]** `G-4-057` — knowledge_cache 中同一 URL 的内容更新策略——是否支持 `force_refresh` 强制重新抓取并覆盖
- **[UNRESOLVED]** `G-4-058` — knowledge_cache 的 embedding 向量使用 pgvector 的 `vector` 类型还是 `bytea` 存储
- **[UNRESOLVED]** `G-4-059` — knowledge_cache 的相似度查询是否有 cosine 相似度下限过滤（如 `WHERE embedding <=> $1 < 0.2`）
- **[UNRESOLVED]** `G-4-060` — knowledge_cache 的 `chunk_content` 字段的最大字符数限制（单个分块的大小上限）
- **[UNRESOLVED]** `G-4-061` — `source_tiers.toml` 的匹配规则——是精确域名匹配还是 URL 前缀匹配还是正则
- **[UNRESOLVED]** `G-4-062` — knowledge_cache 清理时，与 RAGFlow 同步删除的顺序——是先删 RAGFlow 文档再删 PG 记录，还是并行删除
- **[DEFAULT]** `G-4-070` — knowledge_cache 的 Project 级偏置检索——是否在同 Project 范围优先命中，再回退到全局检索，以及 `project_id` 是否进入表结构 / 索引设计 · 覆盖：§5.7 + 附录 B
#### G-4-7 状态机细节

- **[FINAL]** `G-4-024` — Job running(queued) 状态的含义——等待 Temporal Worker 资源，还是等待前序 Job 完成 · 覆盖：§1.2
- **[FINAL]** `G-4-025` — Job running(retrying) 状态的触发条件（Step 重试时 Job 级别状态是否变为 retrying） · 覆盖：§1.2
- **[FINAL]** `G-4-026` — Job 从 running(paused) 到 running(executing) 的转换触发（Signal 到达后立即变 executing 还是延迟） · 覆盖：§1.2
- **[FINAL]** `G-4-027` — Job closed(cancelled) 的触发路径（用户信号 + Temporal Workflow cancel） · 覆盖：§1.2
- **[FINAL]** `G-4-028` — Task 在 Plane 中状态变更的时机（Job 创建时 Task started？Job closed(succeeded) 时 Task completed？） · 覆盖：§1.2
- **[FINAL]** `G-4-029` — 当 Job closed(failed) 时，Task 在 Plane 中的状态是否变更（还是保持 started 等待重试） · 覆盖：§1.2

#### G-4-8 存储与索引实现

`GAPS.md` 当前在该小节下暂无独立条目。新版设计保留这个编号，只用于维持附录映射的结构完整性；后续若补充索引策略或对象级存储优化，统一挂回对象模型附录。

### G-5 Agent 层（7个 Agent 规格）

#### G-5-1 counsel

- **[UNRESOLVED]** `G-5-001` — counsel 的 OC workspace 目录名（openclaw/workspace/counsel/）
- **[UNRESOLVED]** `G-5-002` — counsel 的 MEMORY.md 最大 token 数（≤300 tokens，内容分类：身份 + 最高优先级规则）
- **[UNRESOLVED]** `G-5-003` — counsel 规划 Job DAG 时的完整输出 schema（steps 数组 + 可选的 requires_review 标记）
- **[UNRESOLVED]** `G-5-004` — counsel 在 `fast` 模式（routing decision）和 `analysis` 模式（project 规划）下的 OC model override 代码实现
- **[UNRESOLVED]** `G-5-005` — counsel routing decision 的输入 prompt 结构（用户消息 + 历史对话摘要 + Mem0 规划经验注入）
- **[UNRESOLVED]** `G-5-006` — counsel 对于无法理解的输入的标准响应格式（追问 template）
- **[UNRESOLVED]** `G-5-007` — counsel 在 Replan Gate 时的轻量判断 prompt（~200 tokens 的偏离判定 prompt 格式）
- **[UNRESOLVED]** `G-5-008` — counsel 的规划经验 Mem0 query（查询字符串格式）
- **[UNRESOLVED]** `G-5-009` — counsel 规划产生的 Task DAG（multi-task project）如何写入 Plane IssueRelation
- **[UNRESOLVED]** `G-5-049` — counsel 的 MEMORY.md 内容模板——身份定义的具体文字（约 200 tokens），以及最高优先级行为规则的格式
- **[UNRESOLVED]** `G-5-050` — counsel 在 routing decision 模式下使用 `fast`（MiniMax M2.5）模型时，OC `sessions_spawn` 的 `model` 参数的具体字符串值
- **[UNRESOLVED]** `G-5-051` — counsel 规划 Job DAG 时的 Step 数量限制——是否有硬上限（如 dag_budget 字段），超过时如何处理
- **[UNRESOLVED]** `G-5-052` — counsel 规划时，Mem0 查询的具体 query 字符串格式（如 `"project planning {task_type} dag structure"` 或类似）
- **[UNRESOLVED]** `G-5-053` — counsel 的 planning 输出 JSON 格式验证——如何确保 agent 输出可解析的 JSON（prompt 中的 system 指令还是 OC output schema 约束）
- **[UNRESOLVED]** `G-5-054` — counsel 的 routing decision 输出中 `route: "direct"` 时，生成的 DAG steps 结构（只有一个 direct Step 还是可以有多个）
- **[UNRESOLVED]** `G-5-055` — counsel 追问次数上限的具体数值（如最多追问 3 次，第 4 次无论如何都执行或拒绝）
- **[UNRESOLVED]** `G-5-056` — counsel 在 Replan Gate 时，"轻量判断"（~200 tokens）的 prompt 模板（偏离/未偏离的判断标准是否量化）
- **[UNRESOLVED]** `G-5-057` — counsel 写入 Mem0 的时机——每次 planning session 结束后自动调用 `m.add()`，还是仅在明确学习到有价值经验时
- **[UNRESOLVED]** `G-5-058` — counsel 的规划输出是否包含 `arbiter_trigger` 字段（指定哪些 Step 需要 arbiter 审查）
#### G-5-2 scholar

- **[UNRESOLVED]** `G-5-010` — scholar 的默认搜索策略（先通用 MCP search 还是先 Semantic Scholar，判断切换的规则）
- **[UNRESOLVED]** `G-5-011` — scholar 搜索 → knowledge_cache 写入的触发条件（所有搜索结果都缓存 vs 只缓存用到的）
- **[UNRESOLVED]** `G-5-012` — scholar 调用 Firecrawl 的时机（URL 已知需要全文，Firecrawl 无法处理时才用 Playwright MCP）
- **[UNRESOLVED]** `G-5-013` — scholar 的 TOOLS.md 列出的工具完整清单（MCP search、Semantic Scholar、Firecrawl、RAGFlow 等）
- **[UNRESOLVED]** `G-5-014` — scholar 分析时的 Mem0 查询内容（信源可靠性 + 搜索策略 + 分析框架）
- **[UNRESOLVED]** `G-5-059` — scholar 的 Mem0 初始化——agent_id 是 `scholar` 还是带前缀（如 `agent_scholar`）
- **[UNRESOLVED]** `G-5-060` — scholar 调用 Firecrawl 的具体 MCP tool 名称（`firecrawl_scrape` 还是 `firecrawl_crawl`）
- **[UNRESOLVED]** `G-5-061` — scholar 调用 Semantic Scholar 的 MCP tool 名称和参数格式（query 字符串参数名）
- **[UNRESOLVED]** `G-5-062` — scholar 搜索结果写入 knowledge_cache 的触发条件——是搜索后立即写入，还是等到该结果被实际使用后再写入
- **[UNRESOLVED]** `G-5-063` — scholar 的 TOOLS.md 中各工具的优先级排序（general search MCP → Semantic Scholar → Firecrawl → RAGFlow → Playwright）
- **[UNRESOLVED]** `G-5-064` — scholar 分析任务（analysis 模式）时 Qwen Max 的 `runTimeoutSeconds`（分析类 Step 通常比搜索类耗时更长）
- **[UNRESOLVED]** `G-5-065` — scholar 的 Orchestrator 模式（maxSpawnDepth=2）中，subagent 如何获得父 session 的搜索结果（通过 `attachments` 注入）
- **[UNRESOLVED]** `G-5-066` — scholar 访问 RAGFlow 知识库时，使用哪种检索模式（semantic search vs hybrid search）
#### G-5-3 artificer

- **[UNRESOLVED]** `G-5-015` — artificer 调用 codex 的触发规则（任务复杂度指标：什么情况下 Step 类型升级为 codex）
- **[UNRESOLVED]** `G-5-016` — artificer 在 Orchestrator 模式下（maxSpawnDepth=2）并行处理子任务的典型场景
- **[UNRESOLVED]** `G-5-017` — artificer 的代码风格偏好 Mem0 查询格式
- **[UNRESOLVED]** `G-5-067` — artificer 使用 `codex` Step 的判断阈值——什么样的任务特征触发升级（如代码行数估计 > N，还是"需要多文件修改"）
- **[UNRESOLVED]** `G-5-068` — artificer 在 Orchestrator 模式下并行子任务的具体场景——是否有文档化的使用规范
- **[UNRESOLVED]** `G-5-069` — artificer 调用 `tree-sitter` MCP server 的具体 tool 名称和用途（代码索引/分析）
- **[UNRESOLVED]** `G-5-070` — artificer 代码输出的 Artifact 格式——是 markdown code block，还是文件路径列表，还是 diff patch
#### G-5-4 scribe

- **[UNRESOLVED]** `G-5-018` — scribe 的 Mem0 检索内容（写作风格 + 语言 + task_type 的查询格式）
- **[UNRESOLVED]** `G-5-019` — scribe 调用 GLM Z1 Flash 时，OC sessions_spawn 的 model 参数格式
- **[UNRESOLVED]** `G-5-020` — scribe 的风格注入方式（Mem0 检索结果直接拼入 prompt 还是结构化插入）
- **[UNRESOLVED]** `G-5-071` — scribe 的 GLM Z1 Flash 在 OC sessions_spawn 的 `model` 参数值（具体模型 ID）
- **[UNRESOLVED]** `G-5-072` — scribe 注入写作风格的 prompt 结构——Mem0 检索结果是直接拼入 MEMORY.md 之后，还是作为 Step 指令的 context 字段
- **[UNRESOLVED]** `G-5-073` — scribe 处理多语言输出时，中英文 Persona（style）的分别注入方式（从 Mem0 按 language key 检索）
- **[UNRESOLVED]** `G-5-074` — scribe 产出的 Artifact 是否包含结构化 front matter（用于 Plane 或对外平台的 metadata）
- **[UNRESOLVED]** `G-5-075` — scribe 与 envoy 协作时，scribe 产出的"初稿"和 envoy 的"最终发布版"之间的 Artifact 传递格式
#### G-5-5 arbiter

- **[UNRESOLVED]** `G-5-021` — arbiter 审查输出的标准格式（通过：{passed: true}，不通过：{passed: false, issues: [...]}）
- **[UNRESOLVED]** `G-5-022` — arbiter 审查 Step 时的输入内容（Step 目标 + 产出全文 + 质量标准来自 Mem0）
- **[UNRESOLVED]** `G-5-023` — arbiter 不通过后，feedback 如何传递给 counsel 做 retry/replan 决策（Artifact 格式还是直接 JSON）
- **[UNRESOLVED]** `G-5-024` — arbiter 层级 3（对外强制审查）的触发判断——哪些 Step 被认定为"对外"（envoy Step 全部，还是有额外条件）
- **[UNRESOLVED]** `G-5-025` — arbiter 审查通过率统计的存储方式（Langfuse 还是 PG 聚合）
- **[UNRESOLVED]** `G-5-076` — arbiter 审查通过的标准——是 binary pass/fail 还是有评分（1-5），以及 pass threshold 的具体值
- **[UNRESOLVED]** `G-5-077` — arbiter 审查不通过时，`issues` 数组的每条问题的格式（`severity`/`location`/`suggestion` 字段结构）
- **[UNRESOLVED]** `G-5-078` — arbiter 审查结果（{passed, issues}）写入 job_steps 表的哪个字段（`output_artifact_id` 还是单独的 `review_result` 字段）
- **[UNRESOLVED]** `G-5-079` — arbiter 对 envoy Step 的"对外强制审查"的触发方式——是 Job DAG 规划时 counsel 自动插入 arbiter Step，还是 envoy Step 执行前 Guardrails 规则拦截
- **[UNRESOLVED]** `G-5-080` — arbiter 在审查失败时，反馈给 counsel 的 Artifact 格式——是否有固定的 JSON schema（`{decision: "retry", reason: "...", issues: [...]}`）
- **[UNRESOLVED]** `G-5-081` — arbiter 的最大 rework 次数限制——是从 Guardrails 配置读取还是从 openclaw.json 读取
- **[UNRESOLVED]** `G-5-082` — arbiter 的 Mem0 质量标准是否按 agent 分开存储（如 arbiter 对 scribe 的质量标准 vs 对 artificer 的质量标准）
#### G-5-6 envoy

- **[UNRESOLVED]** `G-5-026` — envoy 通过 OC Telegram channel 发送消息的具体 API 调用方式（OC 平台 announce 机制的 API）
- **[UNRESOLVED]** `G-5-027` — envoy 通过 GitHub MCP server 操作的具体 tool 名称（create_issue、create_pull_request 等）
- **[UNRESOLVED]** `G-5-028` — envoy 的对外平台格式规范 Mem0 查询（渠道名称作为查询 key）
- **[UNRESOLVED]** `G-5-029` — Telegram 通知的内容规范（字数限制、格式限制、图片支持情况）
- **[UNRESOLVED]** `G-5-030` — envoy 作为唯一对外出口的强制机制——其他 agent 是否有技术限制无法直接发出外部消息
- **[UNRESOLVED]** `G-5-083` — envoy 通过 OC Telegram channel 发送消息的具体 OC API 调用方式——是 `sessions_spawn` 时指定 channel 还是使用专门的 announce API
- **[UNRESOLVED]** `G-5-084` — envoy 通过 OC Telegram channel 发送的消息长度限制（Telegram 单条消息 4096 字符，envoy 如何处理超长内容——分段还是截断）
- **[UNRESOLVED]** `G-5-085` — envoy 通过 GitHub MCP 创建 PR 时的 `base_branch` 参数来源（从 Step 指令中指定还是从 Mem0 读取项目配置）
- **[UNRESOLVED]** `G-5-086` — envoy 是否有"发布前最后检查"机制——NeMo output rail 在 envoy 发出内容前是否强制执行
- **[UNRESOLVED]** `G-5-087` — envoy 发布失败（外部 API 错误）时的重试策略——是在 Activity 层 retry 还是在 envoy session 内部 retry
- **[UNRESOLVED]** `G-5-088` — envoy 的对外平台格式 Mem0 条目的 key 格式（如 `telegram_format`、`github_pr_format`）
- **[UNRESOLVED]** `G-5-089` — envoy 在无可用发布渠道时（Telegram 不可用且 GitHub MCP 不可用）的 Job 失败模式
#### G-5-7 steward

- **[UNRESOLVED]** `G-5-031` — steward 的体检自动执行时间（每周几、几点，Temporal Schedule 的 cron 表达式）
- **[UNRESOLVED]** `G-5-032` — steward 体检结果的存储路径（state/health_reports/YYYY-MM-DD.json 是否为最终路径）
- **[UNRESOLVED]** `G-5-033` — steward 触发 Layer 2 自愈时，生成的问题文件路径格式（state/issues/YYYY-MM-DD-HHMM.md）
- **[UNRESOLVED]** `G-5-034` — steward 调用 Layer 2 自愈的 Temporal Activity 类型（claude_code Step 还是专用 Activity）
- **[UNRESOLVED]** `G-5-035` — steward 体检的基准任务选定时机（暖机 Stage 3 结束时，如何持久化基准任务列表）
- **[UNRESOLVED]** `G-5-036` — steward 的规则驱动诊断逻辑（判断 skill 是否需要修复的具体条件：arbiter 拒绝率 > 20%？）
- **[UNRESOLVED]** `G-5-037` — steward Layer 1 自动修复的具体操作（修改 SKILL.md 的内容是 steward LLM 产出还是 hardcoded 模板）
- **[UNRESOLVED]** `G-5-090` — steward 体检 Temporal Schedule 的 schedule_id 命名（如 `steward-weekly-health-check`）
- **[UNRESOLVED]** `G-5-091` — steward 体检开始时发送给用户的 Telegram 通知内容格式（提前告知即将开始体检）
- **[UNRESOLVED]** `G-5-092` — steward 的 Layer 1 自动修复操作的完整清单——仅限修改 SKILL.md 内容，还是也包括 MEMORY.md、openclaw.json 参数调整
- **[UNRESOLVED]** `G-5-093` — steward Layer 2 调用 claude_code 时传入的问题文件格式（state/issues/ 目录的 markdown 文件结构）
- **[UNRESOLVED]** `G-5-094` — steward 判断 skill 需要修复的规则——arbiter 拒绝率 > 20% 是基于最近多少次调用的滑动窗口
- **[UNRESOLVED]** `G-5-095` — steward 的诊断日志存储位置（state/health_reports/ 还是 Langfuse trace）
- **[UNRESOLVED]** `G-5-096` — steward 完成体检后写入 `state/health_reports/YYYY-MM-DD.json` 的完整 schema
- **[UNRESOLVED]** `G-5-097` — steward 在 Stage 3 暖机时确定"基准任务"的标准（从测试任务中选 5-8 个的选择标准）
- **[UNRESOLVED]** `G-5-098` — steward 识别"token 用量超 baseline 150%"时，baseline 值是从 Langfuse 查询还是从 `state/warmup_report.json` 读取
- **[UNRESOLVED]** `G-5-099` — steward 向用户发送 YELLOW/RED 告警时，Telegram 消息中包含的具体指标数值格式
#### G-5-8 通用 Agent 规格

- **[UNRESOLVED]** `G-5-038` — OC sessions_spawn 的参数格式（session_key、model、attachments、system_prompt 等字段）
- **[UNRESOLVED]** `G-5-039` — OC sessions_send 的参数格式（message 文本，是否支持附件）
- **[UNRESOLVED]** `G-5-040` — OC sessions_close 的参数和时机（Step Activity finally 块调用）
- **[UNRESOLVED]** `G-5-041` — Session cleanup 策略（cleanup: "delete" 还是 cleanup: "keep"，何时使用哪个）
- **[UNRESOLVED]** `G-5-042` — Subagent `attachments` 字段的内容格式（父 session 如何注入 MEMORY.md 内容给 Subagent）
- **[UNRESOLVED]** `G-5-043` — 7 个 agent workspace 的目录结构（openclaw/workspace/{agent_id}/TOOLS.md, skills/*.md, MEMORY.md）
- **[UNRESOLVED]** `G-5-044` — TOOLS.md 的标准格式（每个工具的名称、用途、使用条件 section）
- **[UNRESOLVED]** `G-5-045` — agent 在 session 启动时加载 TOOLS.md 的机制（OC 原生支持还是注入 system prompt）
- **[UNRESOLVED]** `G-5-046` — agent 的默认模型与 OC workspace 配置的关系（默认模型是在 openclaw.json 还是在 TOOLS.md 中指定）
- **[UNRESOLVED]** `G-5-047` — Temporal Activity 中 Mem0 检索的完整流程（创建 session 之前查询 Mem0，结果如何注入首条消息）
- **[UNRESOLVED]** `G-5-048` — Step 指令（结构化 JSON）的完整格式（goal、context、constraints、output_format 等字段）
- **[UNRESOLVED]** `G-5-100` — OC `sessions_spawn` API 调用的完整 HTTP 请求格式（URL、header、request body 字段名）
- **[UNRESOLVED]** `G-5-101` — OC `sessions_send` API 调用的请求体格式（`message` 字段是否支持 markdown，是否有 `role` 字段）
- **[UNRESOLVED]** `G-5-102` — OC `sessions_receive`（获取 agent 响应）的 API 调用方式——是轮询（polling）还是 WebSocket 还是 SSE
- **[UNRESOLVED]** `G-5-103` — OC `sessions_close` 与 `sessions_destroy` 的区别——前者保留历史，后者物理删除
- **[UNRESOLVED]** `G-5-104` — OC session 的 `attachments` 字段格式——是文件路径列表还是 base64 编码内容还是 URL 引用
- **[UNRESOLVED]** `G-5-105` — 7 个 OC agent workspace 的初始化脚本——MEMORY.md、TOOLS.md、skills/ 目录的创建方式（手动创建还是 Phase 5 自动化）
- **[UNRESOLVED]** `G-5-106` — TOOLS.md 的标准 section 结构——`## 可用工具` section 的格式，每个工具的名称/用途/使用条件的模板
- **[UNRESOLVED]** `G-5-107` — OC workspace 中 `skills/*.md` 文件是否需要 front matter（YAML header 指定 skill_name、version、applicable_tasks）
- **[UNRESOLVED]** `G-5-108` — 当 agent Step 的 `model` override 指定了 OC 不支持的模型 ID 时的 fallback 处理
- **[UNRESOLVED]** `G-5-109` — Temporal Activity 中调用 OC API 时使用的 HTTP client（`httpx.AsyncClient` 还是其他），以及连接复用策略
- **[UNRESOLVED]** `G-5-110` — Mem0 检索结果注入 Step 的 token 上限（50-200 tokens 的范围如何动态确定——是固定上限还是按 Step 类型调整）
- **[UNRESOLVED]** `G-5-111` — agent 在 session 中产生 subagent（Orchestrator 模式）时，父 session 等待子 session 结果的超时设置
- **[UNRESOLVED]** `G-5-112` — subagent 通过 `announce` 回传结果时，父 session 接收结果的 OC API 调用方式
- **[UNRESOLVED]** `G-5-113` — Step 指令 JSON 的完整字段定义（`goal`/`context`/`constraints`/`output_format`/`token_budget` 等字段的类型和是否必填）
- **[UNRESOLVED]** `G-5-114` — Agent Mem0 的 `run_id` 参数使用规范——是否在每个 Step 创建一个新的 run_id（= step_id）以区分不同 Step 的记忆
- **[UNRESOLVED]** `G-5-115` — 7 个 agent workspace 的默认模型是在 `openclaw.json` 中配置还是在每个 workspace 的 `config.json` 中配置
- **[UNRESOLVED]** `G-5-116` — OC gateway 是否支持 per-request 的模型 override（`sessions_spawn model?` 参数），还是只能通过修改 workspace 配置实现
- **[UNRESOLVED]** `G-5-117` — MEMORY.md 中 agent 的"身份定义"应包含哪些必要字段（agent_id、role、primary_tasks、constraints 等）
- **[UNRESOLVED]** `G-5-118` — agent Step 失败后（Activity 抛出异常），Temporal 重试前是否需要清理上次失败的 OC session（防止 session key 冲突）
- **[UNRESOLVED]** `G-5-119` — Step 执行中 OC session 意外关闭（OC Gateway 重启）的检测机制和 Activity 的处理方式
- **[UNRESOLVED]** `G-5-120` — MEMORY.md 的更新触发时机——是否由 steward 在体检后批量更新，还是 counsel 在每次 warmup 迭代后更新
- **[UNRESOLVED]** `G-5-121` — agent Mem0 中的规划经验条目的 TTL——是否有过期机制（90 天未触发的记忆清理策略）
- **[UNRESOLVED]** `G-5-122` — 多个并行 Step 使用同一 agent（如两个 scholar Step 并行）时，session key 如何区分（`{agent_id}:{job_id}:{step_id}` 中 step_id 不同即可区分）
- **[UNRESOLVED]** `G-5-123` — counsel 规划时，`requires_review: true` 的标记粒度——是 Job 级别（整个 Job 完成后 review）还是 Step 级别（某步骤完成后立即 review）
- **[UNRESOLVED]** `G-5-124` — arbiter 审查通过率 Langfuse score 的写入方式——是在 arbiter Activity 结束后通过 Langfuse SDK `score()` 接口写入，score 名称和值域的约定
- **[UNRESOLVED]** `G-5-125` — envoy 发送 Telegram 消息时，是否支持发送 Artifact 文件（如 PDF）作为附件，还是只能发送文本
- **[UNRESOLVED]** `G-5-126` — steward 调用 Layer 2 self-healing（claude_code subprocess）的 Temporal Activity 类型——是否复用现有的 Step Activity，还是独立的 steward_heal Activity
- **[UNRESOLVED]** `G-5-127` — 7 个 agent 的 TOOLS.md 是否有统一模板，还是各自完全自由格式
- **[UNRESOLVED]** `G-5-128` — 每个 agent 的 Mem0 bucket 是否允许跨 agent 读取（如 counsel 是否可以查询 scholar 的 Mem0 记忆）
- **[FINAL]** `G-5-146` — Persona 的文件层结构——`psyche/voice/identity.md / common.md / zh.md / en.md / overlays/*.md` 与 Mem0 动态层的边界、加载顺序与覆盖规则 · 覆盖：§5.2
- **[FINAL]** `G-5-147` — 用户偏好写入 Persona 的责任归属——由 counsel、scribe 还是其他 agent 发起确认流程，并在 Job closed 后写入 user 级语义记忆 · 覆盖：§5.3
#### G-5-9 运行时与冷启动

- **[UNRESOLVED]** `G-5-129` — counsel 在 analysis 模式（项目规划）时，OC sessions_spawn 的 `model` 参数从哪里读取（是 `openclaw.json` 中 counsel 的配置，还是在代码中 hardcode 为 `qwen-max`）
- **[UNRESOLVED]** `G-5-130` — scribe 在多语言任务（中英文都需要产出）时，是否需要两个独立 Step（一个中文 Step + 一个英文 Step），还是在单个 Step 中完成双语产出
- **[UNRESOLVED]** `G-5-131` — arbiter 层级 2 审查的 Step 选择——counsel 在规划时通过什么字段标记某 Step 需要 arbiter 审查（是 `requires_review: true` 还是 `arbiter: true`）
- **[UNRESOLVED]** `G-5-132` — envoy 在执行"对外发布"Step 时，如果 arbiter 审查不通过，是否允许 counsel 决定直接发布（overriding arbiter）还是必须修改后重审
- **[UNRESOLVED]** `G-5-133` — steward 的 `analysis` 模型（Qwen Max）与 counsel 的 `analysis` 模型相同，是否在 openclaw.json 中分别配置还是共享同一配置
- **[UNRESOLVED]** `G-5-134` — 7 个 agent workspace 的 TOOLS.md 初始化内容——Phase 5 中 artificer 生成 SKILL.md 后，TOOLS.md 是 artificer 自动生成还是手动编写
- **[UNRESOLVED]** `G-5-135` — agent 在 Step 执行失败（LLM 返回了格式错误的输出）时，是否有 self-correction 机制（agent 在 session 内部重新请求），还是直接让 Activity 失败触发 Temporal retry
- **[UNRESOLVED]** `G-5-136` — scholar 调用 Playwright MCP 时，是否需要在 mcp_servers.json 中预配置 Playwright MCP server，还是按需启动
- **[UNRESOLVED]** `G-5-137` — 暖机 Stage 3 中，每次测试任务的 Langfuse trace 是否打上 `warmup: true` 标签以便区分生产 trace
- **[UNRESOLVED]** `G-5-138` — counsel 的 session（routing decision 模式）是否在 API 进程中直接通过 HTTP 调用 OC Gateway，还是通过 Temporal Activity（后者增加延迟但保持一致性）
- **[UNRESOLVED]** `G-5-139` — scribe 的 overlay 机制（task_type → overlays/*.md）在 Step 指令中如何传递给 Activity 层（Step 的 `context.task_type` 字段）
- **[UNRESOLVED]** `G-5-140` — steward 在体检中执行"固定基准任务"时，这些任务是否通过正常的 Job 提交流程（走 Plane webhook + Temporal），还是有绕过流程的快速路径
- **[UNRESOLVED]** `G-5-141` — 每个 agent 的 MEMORY.md 的初始版本（暖机前）是否有默认模板，还是完全为空（冷启动时）
- **[UNRESOLVED]** `G-5-142` — OC `sessions_spawn` 的参数中是否支持 `system_prompt` 字段（覆盖 workspace 默认设置），daemon 在什么情况下使用此参数
- **[UNRESOLVED]** `G-5-143` — agent 使用 Orchestrator 模式（maxSpawnDepth=2）时，父 session 通过哪种方式等待所有子 session 完成（OC 是否有 barrier/await-all 机制）
- **[UNRESOLVED]** `G-5-144` — 7 个 agent 的 Mem0 `user_id` 是否统一使用一个固定值（如 `daemon_user`），或者每个 agent 使用不同 `user_id`
- **[UNRESOLVED]** `G-5-145` — steward 的"周度体检"与"暖机 Stage 3"的测试任务集合是否有重叠——体检是否重用 `warmup/results/baseline_tasks.json` 中的任务
### G-6 OC Gateway / 通信

#### G-6-1 OC 配置

- **[UNRESOLVED]** `G-6-001` — openclaw.json 的完整字段结构（agents 列表、全局设置、quota 配置）
- **[UNRESOLVED]** `G-6-002` — 每个 agent 的 quota 配置格式（daily_token_limit、max_concurrent_sessions 等）
- **[UNRESOLVED]** `G-6-003` — `contextPruning: cache-ttl` 的配置位置（全局配置还是 per-agent）
- **[UNRESOLVED]** `G-6-004` — `maxSpawnDepth` 的配置级别（全局默认值 + per-agent 覆盖的支持情况）
- **[UNRESOLVED]** `G-6-005` — `maxConcurrent: 8` 的含义——是全局 session 并发还是单 agent 并发（与 maxChildrenPerAgent=5 的关系）
- **[UNRESOLVED]** `G-6-006` — OC Gateway 的健康检查 endpoint（暖机 Stage 2 中 XS-10 验证的 /health 路径）
- **[UNRESOLVED]** `G-6-007` — OC Gateway 的 API base URL 配置（Worker 进程通过什么 URL 访问 OC）
- **[UNRESOLVED]** `G-6-026` — `openclaw.json` 中 `agents` 数组的每个 agent 对象的完整字段定义（id、workspace_path、default_model、quota 等）
- **[UNRESOLVED]** `G-6-027` — `openclaw.json` 中全局 `maxConcurrent: 8` 的暖机校准方法——是逐步增加并发观察错误率还是基于 LLM provider rate limit 计算
- **[UNRESOLVED]** `G-6-028` — `openclaw.json` 中 `contextPruning: "cache-ttl"` 模式的具体行为——5 分钟 TTL 后哪些内容被裁剪（tool call results vs 对话历史）
- **[UNRESOLVED]** `G-6-029` — OC agent workspace 中 `skills/` 目录的文件加载方式——OC 是自动扫描还是在 `TOOLS.md` 中显式列出
- **[UNRESOLVED]** `G-6-030` — OC `sessions_spawn` 中 `system_prompt` 参数是否覆盖 MEMORY.md 内容，还是追加到 MEMORY.md 之后
- **[UNRESOLVED]** `G-6-031` — OC gateway 的日志级别和日志路径配置
- **[UNRESOLVED]** `G-6-032` — OC gateway 的认证机制——daemon Worker 进程访问 OC API 是否需要 API key（是否有 token 验证）
- **[UNRESOLVED]** `G-6-033` — OC gateway 的端口号配置（是否与 daemon API 进程的 8100 端口在同一宿主机上运行，用哪个端口）
#### G-6-2 Session 管理

- **[UNRESOLVED]** `G-6-008` — sessions_spawn 的具体 API 路径（/sessions/new 还是 /api/sessions 等）
- **[UNRESOLVED]** `G-6-009` — Session 创建失败（OC 不可用）时，Temporal Activity 的错误处理（重试 vs 立即失败）
- **[UNRESOLVED]** `G-6-010` — Session 的 persistent full session 与 ephemeral session 的区别（从 OC 角度，两者的 API 参数差异）
- **[UNRESOLVED]** `G-6-011` — Session context 在 session 结束后是否可以查询（用于 Artifact 提取）
- **[UNRESOLVED]** `G-6-012` — 并发 session 超过 maxConcurrent 时的行为（队列等待还是立即失败）
- **[UNRESOLVED]** `G-6-013` — OC session TTL（session 若无消息，多久后自动关闭）
- **[UNRESOLVED]** `G-6-014` — Worker Activity 崩溃后遗留的 unclosed session 的处理机制（steward 定期清理还是 OC TTL 自动处理）
- **[UNRESOLVED]** `G-6-034` — OC session 创建成功的响应体格式（`session_id` 字段名，以及其他返回字段）
- **[UNRESOLVED]** `G-6-035` — OC session 列表 API（如果存在）——是否可以查询某个 agent 的所有活跃 session（用于 steward 清理僵尸 session）
- **[UNRESOLVED]** `G-6-036` — Worker Activity 崩溃后，僵尸 OC session 的清理时机——是 steward 周度体检时清理，还是每次 Worker 启动时清理
- **[UNRESOLVED]** `G-6-037` — OC session 的 `full` 模式与 `ephemeral` 模式在 API 参数层面的区别（是否有 `persist: true/false` 参数）
- **[UNRESOLVED]** `G-6-038` — `sessions_spawn` 的同步/异步行为——调用是否阻塞等待 agent 准备好（session ready 状态），还是立即返回 session_id
- **[UNRESOLVED]** `G-6-039` — 当 `maxConcurrent` 达到上限时，`sessions_spawn` 的具体错误响应（HTTP 状态码和错误体格式）
- **[UNRESOLVED]** `G-6-040` — OC session 的 `cleanup: "delete"` 在 sessions_close 时的行为——是否立即删除 session 历史还是等待 GC
- **[UNRESOLVED]** `G-6-041` — OC 的 session token 计数方式——是按 input+output 计费还是只计 input
- **[UNRESOLVED]** `G-6-042` — OC 对 `maxSpawnDepth: 2` 的 Orchestrator 模式的并发限制——每个父 session 最多同时运行多少 subagent
- **[UNRESOLVED]** `G-6-043` — OC sessions 的 `idle_timeout` 配置——session 无活动多久后自动关闭（防止 Activity 崩溃后 session 泄漏）
#### G-6-3 MCP 分发

- **[UNRESOLVED]** `G-6-015` — MCPDispatcher 初始化时连接所有 MCP server 的超时设置（连接超时 vs 操作超时）
- **[UNRESOLVED]** `G-6-016` — MCP server 不可用时的路由表降级（从路由表中移除还是标记为不可用但保留）
- **[UNRESOLVED]** `G-6-017` — MCP server 重连策略（标记不可用后是否定期尝试重连）
- **[UNRESOLVED]** `G-6-018` — call_tool 的 asyncio.wait_for 超时值（按工具类型区分还是统一超时）
- **[UNRESOLVED]** `G-6-019` — mcp_servers.json 的 ${VAR} 环境变量展开时机（MCPDispatcher 初始化时展开）
- **[UNRESOLVED]** `G-6-020` — MCPDispatcher 的单例模式（Worker 进程级别单例还是 Activity 级别实例化）
- **[UNRESOLVED]** `G-6-044` — MCPDispatcher 的工具路由表（`tool_name → server_name` mapping）的缓存失效时机——是否支持热更新
- **[UNRESOLVED]** `G-6-045` — MCP server 连接使用的协议版本（MCP spec 2024-11-05 还是更新版本）
- **[UNRESOLVED]** `G-6-046` — MCP server stdio transport 的进程管理方式——是 Worker 进程启动时启动所有 MCP server 进程，还是按需启动
- **[UNRESOLVED]** `G-6-047` — MCP HTTP transport server 的认证方式（Bearer token 还是无认证的本地回环地址）
- **[UNRESOLVED]** `G-6-048` — `mcp_servers.json` 的热更新支持——steward 修改配置后是否需要重启 Worker 进程
- **[UNRESOLVED]** `G-6-049` — call_tool 的默认超时值按工具类型的具体配置表（search: Xs, web_scrape: Xs, git: Xs 等）
- **[UNRESOLVED]** `G-6-050` — MCPDispatcher 在发现工具名冲突（多个 server 提供同名 tool）时的解决策略
- **[FINAL]** `G-6-066` — MCP server 连接生命周期——Worker 是否在进程级复用连接、何时构建 tool 路由表、每次调用的超时保护与不可用标记策略 · 覆盖：§6.5
#### G-6-4 PG 事件总线

- **[DEFAULT]** `G-6-021` — Worker 进程订阅 PG LISTEN channel 的实现方式（asyncpg 的 add_listener 还是 psycopg） · 覆盖：§6.4 + 附录 D
- **[DEFAULT]** `G-6-022` — PG NOTIFY 触发的时机与事务的关系（在 COMMIT 前 NOTIFY 还是 COMMIT 后 NOTIFY） · 覆盖：§6.4 + 附录 D
- **[DEFAULT]** `G-6-023` — event_log 表的写入与 NOTIFY 的原子性保证（是否在同一事务中） · 覆盖：§6.4 + 附录 D
- **[DEFAULT]** `G-6-024` — Worker 进程启动时，如何处理 event_log 中未消费的历史事件（查询 consumed_at IS NULL 并重放） · 覆盖：§6.4 + 附录 D
- **[DEFAULT]** `G-6-025` — 多个 Worker 进程实例时（scale-out），event 消费的幂等性保证（行级锁 FOR UPDATE SKIP LOCKED） · 覆盖：§6.4 + 附录 D
- **[UNRESOLVED]** `G-6-051` — PG LISTEN 在 Worker 进程启动时的具体实现——是否在主事件循环中注册 `asyncpg.add_listener`
- **[UNRESOLVED]** `G-6-052` — Worker 进程有多个 Activity 协程并发时，PG LISTEN 的事件分发机制——是否有单一的 listener 协程分发到各 Activity
- **[UNRESOLVED]** `G-6-053` — PG NOTIFY payload 超过 8000 字节时的处理——是否截断、还是不 NOTIFY 仅写 event_log（下游轮询）
- **[UNRESOLVED]** `G-6-054` — `FOR UPDATE SKIP LOCKED` 查询的并发行数配置——每次查询获取多少未消费事件
- **[UNRESOLVED]** `G-6-055` — event_log 表的 `consumed_at` 更新时机——是处理完 event 后立即 UPDATE，还是在事务内和业务操作一起 UPDATE
- **[UNRESOLVED]** `G-6-056` — Worker 进程异常退出后，已 LISTEN 未 ACK 的 PG 事件的重放机制——是否有心跳检测 + 超时重放
- **[FINAL]** `G-6-065` — PG `event_log` 与 NOTIFY 双写机制——关键事件如何持久化、如何定义 `job_events / step_events / webhook_events` payload，以及 Worker 重启后的补处理流程 · 覆盖：§6.4
#### G-6-5 运行时协议细节

- **[DEFAULT]** `G-6-057` — OC gateway 是否暴露 `/metrics` 端点（Prometheus 格式），供 daemon 监控 OC session 并发数 · 覆盖：附录 D
- **[DEFAULT]** `G-6-058` — OC `sessions_spawn` 的 `attachments` 参数是否有大小限制（注入 MEMORY.md 内容 + Mem0 结果的总字节上限） · 覆盖：附录 B
- **[UNRESOLVED]** `G-6-059` — OC 内部的 tool result 缓存（`contextPruning: cache-ttl`）在 TTL 到期后如何影响 session 的后续请求（是否会重新调用 tool 还是视为 context 丢失）
- **[DEFAULT]** `G-6-060` — Worker 进程与 OC Gateway 之间的通信是否需要重试（OC Gateway 临时不可用时，Activity 是否有专门的 retry 策略区别于其他错误） · 覆盖：附录 B
- **[DEFAULT]** `G-6-061` — OC `sessions_send` 是否支持流式响应（streaming SSE）——Temporal Activity 是否需要处理流式输出还是等待完整响应 · 覆盖：附录 D
- **[UNRESOLVED]** `G-6-062` — mcp_servers.json 中，哪些 MCP server 是 daemon 必须预置的（required）哪些是可选的（optional）
- **[UNRESOLVED]** `G-6-063` — MCPDispatcher 在 Worker 进程中是否以 singleton 模式存在（全局单例通过 `asynccontextmanager` 管理）
- **[UNRESOLVED]** `G-6-064` — OC 的 `maxChildrenPerAgent: 5` 设置中，"children" 是 subagent session 数量还是 tool call 并发数
### G-7 暖机与体检

#### G-7-1 暖机阶段

- **[UNRESOLVED]** `G-7-001` — Stage 0 信息采集的输出存储位置（warmup/about_me.md + warmup/writing_samples/ 目录结构）
- **[UNRESOLVED]** `G-7-002` — Stage 1 Persona 标定时，LLM 分析写作样本的模型选择（用哪个 agent 和模型做初始分析）
- **[UNRESOLVED]** `G-7-003` — Stage 1 Persona 初始写入 Mem0 时的 agent_id 参数（user_persona 还是各 agent 分别写入）
- **[UNRESOLVED]** `G-7-004` — Stage 1 Persona 验证失败（风格不匹配）的判定标准（steward 如何评估"风格一致"）
- **[UNRESOLVED]** `G-7-005` — Stage 2 链路验证的 17 条链路与 WARMUP_AND_VALIDATION.md 中 15 条链路的对应关系（L01-L17）
- **[UNRESOLVED]** `G-7-006` — Stage 2 L05（Job paused → Signal → job_closed）的验证步骤的具体操作
- **[UNRESOLVED]** `G-7-007` — Stage 2 L09（Mem0 写入验证）的查询方式（用什么 API 查询 Mem0 中的记忆条目）
- **[UNRESOLVED]** `G-7-008` — Stage 3 测试任务的"伪人度"评分标准的量化定义（1-5 分的评分维度）
- **[UNRESOLVED]** `G-7-009` — Stage 3 收敛条件——"连续 5 个不同类型任务通过"的通过标准是 arbiter 通过 + steward 评分 ≥ 4？
- **[UNRESOLVED]** `G-7-010` — Stage 3 skill 校准的迭代流程（Langfuse 查询 → 定位问题 → 修改 SKILL.md → 重跑的操作步骤）
- **[UNRESOLVED]** `G-7-011` — Stage 4 系统状态测试的 10 个异常场景的完整列表
- **[UNRESOLVED]** `G-7-012` — 暖机完成的标志——是否有正式的"暖机完成"状态写入（类似 state/warmup_complete.json）
- **[UNRESOLVED]** `G-7-021` — Stage 0 向用户收集信息的工具——是通过 Telegram 对话还是通过 Plane DraftIssue 填写结构化表单
- **[UNRESOLVED]** `G-7-022` — Stage 0 的写作样本存储路径 `warmup/writing_samples/` 的文件格式要求（.txt、.md、.docx 均可？）
- **[UNRESOLVED]** `G-7-023` — Stage 0 产出的 `warmup/about_me.md` 的结构模板（包含哪些 section：职业、专业领域、质量标准、工作偏好等）
- **[UNRESOLVED]** `G-7-024` — Stage 1 调用 LLM 分析写作样本的具体 prompt 模板（提取 identity + 中英文 style 的 prompt 结构）
- **[UNRESOLVED]** `G-7-025` — Stage 1 初始 Persona 写入 Mem0 时，每条记忆的格式（是否是结构化 JSON 还是自然语言描述）
- **[UNRESOLVED]** `G-7-026` — Stage 1 Persona 验证时，scribe 写短文的 Step 指令格式（任务描述的具体内容）
- **[UNRESOLVED]** `G-7-027` — Stage 1 Persona 验证失败时的最大迭代次数（防止无限循环）
- **[UNRESOLVED]** `G-7-028` — Stage 2 链路验证 L01-L17 的执行方式——由 steward 自动执行还是由暖机脚本（scripts/warmup.py）执行
- **[UNRESOLVED]** `G-7-029` — Stage 2 L02（Temporal Workflow 提交）的验证 Job 内容（最简单 Job 的具体 DAG 结构）
- **[UNRESOLVED]** `G-7-030` — Stage 2 L05 验证（Job paused → Signal）的具体操作步骤（如何发送 Temporal Signal）
- **[UNRESOLVED]** `G-7-031` — Stage 2 L06 验证（knowledge_cache 命中检测）的查询方式（是 PG SQL 还是通过 daemon API）
- **[UNRESOLVED]** `G-7-032` — Stage 2 L09 验证（Mem0 写入验证）的查询方式——调用 `m.search()` 还是 `m.get_all()` 查询
- **[UNRESOLVED]** `G-7-033` — Stage 2 链路验证的结果记录格式（pass/fail 写入 `warmup/validation_results.json` 还是写入 Langfuse）
- **[UNRESOLVED]** `G-7-034` — Stage 3 测试任务的设计者——是 steward 基于用户在 Stage 0 提供的信息自动设计，还是用户手动设计
- **[UNRESOLVED]** `G-7-035` — Stage 3 "连续 5 个不同类型任务通过"的"类型"定义——是 agent 组合类型还是任务领域类型
- **[UNRESOLVED]** `G-7-036` — Stage 3 skill 校准迭代中，Langfuse 查询的具体指标（哪些 trace metadata 用于判断 skill 问题）
- **[UNRESOLVED]** `G-7-037` — Stage 3 收敛后，"基准任务"的存储格式（`warmup/results/baseline_tasks.json` 的 schema）
- **[UNRESOLVED]** `G-7-038` — Stage 4 S01（并发参数校准）的具体步骤——从多少并发开始，每次增加多少，观察哪些指标
- **[UNRESOLVED]** `G-7-039` — Stage 4 S07（Temporal Worker 重启）验证的操作步骤（如何优雅重启，如何验证 workflow 恢复）
- **[UNRESOLVED]** `G-7-040` — Stage 4 S09（定时任务积压）验证的时间模拟方式（是否有加速时钟机制或手动触发 Temporal Schedule）
- **[UNRESOLVED]** `G-7-041` — 暖机报告 `state/warmup_report.json` 的写入时机——是每个 Stage 结束后更新，还是全部完成后一次性写入
- **[UNRESOLVED]** `G-7-042` — 暖机报告中 `baseline_token_usage` 字段的计算方式（各 agent 各 task_type 的平均 token 消耗，从 Langfuse 查询）
- **[UNRESOLVED]** `G-7-043` — 暖机完成状态标志——`state/warmup_report.json` 中 `status: "ready"` 字段是否在 Worker 启动时检查（防止在未暖机的系统上运行）
- **[UNRESOLVED]** `G-7-044` — 暖机失败（如 Stage 2 链路不通）时的处理——是否有 resume 机制（从失败的 Stage 继续，不重头来）
- **[UNRESOLVED]** `G-7-045` — Stage 3 "伪人度"评估的评分主体——是 steward 通过 arbiter session 评估，还是需要人类检查
- **[UNRESOLVED]** `G-7-046` — Stage 3 每个测试任务执行后写入 `warmup/results/` 目录的结果文件格式（task_id、steps、artifacts、评分等字段）
- **[UNRESOLVED]** `G-7-047` — Stage 5 "Degraded"状态下系统对用户的限制如何实现——是通过 NeMo Guardrails 限制请求类型，还是通过 Will 中的 ward_check 排队
- **[UNRESOLVED]** `G-7-048` — 暖机阶段的所有操作是否通过 Temporal Workflow 编排（保证失败可恢复），还是脚本线性执行
- **[UNRESOLVED]** `G-7-049` — Stage 3 skill 迭代中 SKILL.md 的版本管理——是否通过 git commit 记录每次修改，还是仅写入文件无版本记录
- **[UNRESOLVED]** `G-7-050` — 多次暖机（重新暖机）时，旧的 `warmup/` 目录和 `state/warmup_report.json` 的处理（覆盖还是归档）
- **[UNRESOLVED]** `G-7-051` — Stage 2 L17（Plane webhook 签名验证）的测试方法——使用错误的 HMAC 签名，期望返回 403（daemon API 端点路径）
- **[UNRESOLVED]** `G-7-052` — Stage 3 对外发布测试（示例 B：GitHub PR）是否需要使用专用测试仓库以避免污染真实 repo
- **[UNRESOLVED]** `G-7-053` — 暖机期间 Langfuse 中的 trace 是否与生产 trace 混合，还是使用单独的暖机 project（tag 或 project 隔离）
- **[UNRESOLVED]** `G-7-054` — 周度体检的 steward 基准任务执行方式——steward 是否直接 spawn Job，还是通过 daemon API 提交请求
- **[UNRESOLVED]** `G-7-055` — 周度体检中 17 条链路的"缩减版"验证——缩减后保留哪些关键链路（至少包含 L01、L02、L03、L10、L13）
- **[UNRESOLVED]** `G-7-056` — 周度体检的 RED 告警（arbiter 通过率 < 80% 等）触发后，是否自动暂停新 Job 的创建
- **[UNRESOLVED]** `G-7-057` — 周度体检发现问题后"针对性 skill 重校准"的具体操作——是否重新运行 Stage 3 中该 skill 对应类型的测试任务
- **[UNRESOLVED]** `G-7-058` — steward 体检评分 < 4/5 时，"伪人度下降"的追踪机制——是否记录历史趋势（state/health_reports/ 中的 series 数据）
- **[UNRESOLVED]** `G-7-059` — 体检 YELLOW 与 RED 的界定标准（除 arbiter 通过率 < 80% 和 token 超 baseline 150%，还有哪些指标）
- **[UNRESOLVED]** `G-7-060` — 体检报告中"外部出口链路"（L10-L11）的验证是否每周执行（需要实际向 Telegram/GitHub 发送测试消息）
#### G-7-2 周度体检

- **[UNRESOLVED]** `G-7-013` — 周度体检的 Temporal Schedule cron 表达式（建议 0 6 * * 1 即每周一 UTC 6:00）
- **[UNRESOLVED]** `G-7-014` — 基准任务的选定和存储方式（暖机时从 Stage 3 选 5-8 个，存 warmup/results/baseline_tasks.json）
- **[UNRESOLVED]** `G-7-015` — 体检结果的存储 schema（state/health_reports/YYYY-MM-DD.json 的 JSON 结构）
- **[UNRESOLVED]** `G-7-016` — 体检告警的 Telegram 消息格式（包含哪些指标、如何区分 YELLOW/RED）
- **[UNRESOLVED]** `G-7-017` — 体检发现问题后"针对性 skill 重校准"的定义和操作流程
- **[UNRESOLVED]** `G-7-018` — arbiter 通过率 < 80% 告警阈值——基于什么时间窗口内的统计（本次体检 vs 过去 7 天）
- **[UNRESOLVED]** `G-7-019` — 单 skill 平均 token 用量 > baseline 150% 的 baseline 从哪里读取（暖机时记录到哪里）
- **[UNRESOLVED]** `G-7-020` — 伪人度评分 < 4/5 的具体评分主体（steward 自评还是通过 arbiter 专项评估）
### G-8 安全与配额

#### G-8-1 Guardrails 集成

- **[UNRESOLVED]** `G-8-001` — NeMo rails.generate() 调用的返回格式解析（如何判断是"通过"还是"被拦截"）
- **[UNRESOLVED]** `G-8-002` — Guardrails 拦截后返回给用户的错误消息格式（通用"违反规则"还是具体说明原因）
- **[UNRESOLVED]** `G-8-003` — NeMo input rail 在 MCP tool 调用前的具体触发点（MCPDispatcher.call_tool 的 pre-check）
- **[UNRESOLVED]** `G-8-004` — NeMo output rail 在 agent session 返回后的具体触发点（Artifact 写入前还是 session 返回时）
- **[UNRESOLVED]** `G-8-005` — NeMo custom action 的 Mem0 写入校验——检查 Persona 候选的哪些属性（内容长度、语义一致性）
- **[UNRESOLVED]** `G-8-006` — sensitive_terms.json 的初始内容（项目代号、内部系统名等敏感词的初始化）
- **[UNRESOLVED]** `G-8-007` — Guardrails 与 Job 执行的集成位置——是 Worker Activity 层还是 OC session 层
- **[UNRESOLVED]** `G-8-008` — guardrails.md 的版本化管理（git commit 即版本，是否需要额外 changelog）
- **[UNRESOLVED]** `G-8-015` — NeMo input rail 在 `MCPDispatcher.call_tool()` 之前的具体调用代码（同步调用还是异步）
- **[UNRESOLVED]** `G-8-016` — NeMo output rail 在 agent Step 完成后、Artifact 写入 PG 之前的具体调用位置（在哪个函数中）
- **[UNRESOLVED]** `G-8-017` — Colang 规则文件的版本管理策略——是否与 SKILL.md 一样通过 git 管理，steward 是否可以修改
- **[UNRESOLVED]** `G-8-018` — NeMo Guardrails 在 input rail 拦截时，原始请求内容是否记录到 Langfuse（用于审计）
- **[UNRESOLVED]** `G-8-019` — NeMo Guardrails 在 output rail 拦截时，被拦截的内容是否写入 event_log（供后续分析）
- **[UNRESOLVED]** `G-8-020` — `sensitive_terms.json` 的更新流程——是 steward 提案 + 用户确认，还是用户直接编辑文件
- **[UNRESOLVED]** `G-8-021` — NeMo Guardrails 的 `config.yml` 中 `models` 字段使用哪个 LLM 做 rails 判断（是否可以是 zero-token 的纯 Colang 规则，不需要 LLM）
- **[UNRESOLVED]** `G-8-022` — Guardrails 在 Worker 进程崩溃重启后的重新初始化时间（是否影响 Worker 可用性）
- **[UNRESOLVED]** `G-8-023` — 对于长文本输出（如 scribe 产出的 3000 字报告），NeMo output rail 的检查范围——是全文检查还是采样检查
- **[UNRESOLVED]** `G-8-024` — source_tiers.toml 的 `verify_required` 字段（cross_check/mandatory）在 scholar Step 指令中如何体现（是否自动注入 prompt）
- **[UNRESOLVED]** `G-8-025` — instinct.md 的"专业标准冲突"处理中，`user_override` 标记存储在 Artifact 的哪个字段（PG job_artifacts 表的 metadata JSONB 字段）
- **[UNRESOLVED]** `G-8-026` — NeMo Guardrails 阻止对外操作（如 envoy 发 Telegram）时，envoy Activity 的 Temporal 行为——是 Activity fail 还是 skip
- **[UNRESOLVED]** `G-8-027` — "所有 Persona 修改经用户确认"的实现——NeMo custom action 在验证通过前返回什么值（pending 状态如何存储）
- **[UNRESOLVED]** `G-8-028` — Guardrails 检查外部 MCP 结果（MCP server 返回可疑数据）的具体检查项（JSON 格式合法、内容无 SQL 注入、大小限制）
- **[UNRESOLVED]** `G-8-029` — NeMo Guardrails 与 Temporal Activity retry 的交互——Guardrails 拦截导致的 Activity 失败是否触发 retry（应该不触发，是不同类型的失败）
- **[UNRESOLVED]** `G-8-030` — source_tiers.toml 的 tier 判断是否实时执行（每次 scholar 搜索时查询）还是在写入 knowledge_cache 时批量处理
- **[UNRESOLVED]** `G-8-031` — Tier C 来源"不可作为唯一来源"的强制机制——是 NeMo Guardrails 规则还是 scholar Step 的 prompt 指令
- **[UNRESOLVED]** `G-8-032` — sensitive_terms.json 的大小写不敏感检测实现方式（lower-case 标准化 + 子串匹配）
- **[UNRESOLVED]** `G-8-033` — envoy 在通过 NeMo output rail 后，如何记录"已过 Guardrails 审查"的证明（是否写入 event_log）
- **[UNRESOLVED]** `G-8-034` — 系统 paused 状态时，已在 running 的 Job 是否继续执行还是暂停（paused 仅影响新 Job 创建）
- **[UNRESOLVED]** `G-8-035` — Temporal Worker 的 sticky 模式下，Activity 的隔离性——同一个 workflow 的多个 Activity 是否在同一个 Worker thread 执行（影响 Guardrails 单例安全性）
- **[UNRESOLVED]** `G-8-036` — Guardrails 规则配置文件变更时的热加载策略——是否需要重启 Worker 进程，或者有 steward 触发的热重载机制
- **[UNRESOLVED]** `G-8-037` — 敏感词过滤后的"脱敏词"如何标记——外发的 outbound query 中被替换为"某软件项目"后，scholar 是否知道发生了替换（防止混淆）
- **[UNRESOLVED]** `G-8-038` — `instinct.md` 的 token 预算限制（DIAGNOSTIC_TEST_SUITE.md 中 PC-10 指出 ≤ 400 tokens）——是否有校验脚本
#### G-8-2 Quota 配额

- **[DEFAULT]** `G-8-009` — OC 原生 quota 配置的字段名（openclaw.json 中 per-agent 的 daily_token_limit 字段） · 覆盖：§5.8 + 附录 B
- **[DEFAULT]** `G-8-010` — Quota 重置时间（每天 UTC 00:00 重置还是按用户时区） · 覆盖：§5.8 + 附录 B
- **[DEFAULT]** `G-8-011` — Quota 达上限时的用户通知方式（Telegram 通知 + Temporal 信号） · 覆盖：§5.8 + 附录 B
- **[DEFAULT]** `G-8-012` — 单 Job 最大消耗 = 日配额 × ratio 的 ratio 值（0.2？0.5？） · 覆盖：§5.8 + 附录 B
- **[DEFAULT]** `G-8-013` — 并发 Job 上限的具体数值（默认 maxConcurrent=8 是 session 并发，不等于 Job 并发上限） · 覆盖：§5.8 + 附录 B
- **[DEFAULT]** `G-8-014` — Job 级别的 token 预算检查在 Temporal Activity 中的具体位置（创建 Job 时预检查还是执行中动态检查） · 覆盖：§5.8 + 附录 B
- **[UNRESOLVED]** `G-8-039` — OC openclaw.json 中 `daily_token_limit` 的重置机制——是 OC 内置每日重置，还是 daemon 定时 Job 调用 OC API 重置
- **[DEFAULT]** `G-8-040` — Quota 告警的触发阈值——是达到日限额的 80% 就告警还是达到 100% 才告警 · 覆盖：附录 B
- **[DEFAULT]** `G-8-041` — 单 Job 最大消耗的计算公式——`daily_token_limit × deed_ration_ratio`，`deed_ration_ratio` 的默认值（0.75？0.5？） · 覆盖：附录 B
- **[DEFAULT]** `G-8-042` — Job 执行中途 Quota 耗尽时的行为——已完成的 Step Artifact 是否保留，Job 状态设为 `failed` 还是 `paused` · 覆盖：附录 B
- **[DEFAULT]** `G-8-043` — 多个并行 Job 的 token 消耗计数是否共享同一个 daily_token_limit 计数器（还是每个 agent 独立计数） · 覆盖：附录 B
- **[DEFAULT]** `G-8-044` — Quota 重置（每日 00:00 UTC）时，正在执行的 Job 是否受影响（不影响，仅影响新 Step 的预检查） · 覆盖：附录 B
#### G-8-3 系统状态与运行边界

- **[DEFAULT]** `G-8-045` — quota 的 token 计量单位——是按字符数估算还是实际 token 数，使用哪个 tokenizer（tiktoken 或 provider 提供的） · 覆盖：附录 B
- **[DEFAULT]** `G-8-046` — NeMo Guardrails 的 output rail 是否对所有 agent 都启用，还是只对 envoy 和 arbiter 触发的内容启用 · 覆盖：附录 B
- **[DEFAULT]** `G-8-047` — 系统 paused 状态写入的具体存储——是 PG 表中的配置记录还是文件系统中的 `state/system_status.json` · 覆盖：附录 B
- **[DEFAULT]** `G-8-048` — daily token limit 重置时的行为——当前正在执行的 Job 消耗的 token 是否计入新的一天 · 覆盖：附录 B
### G-9 Skill 体系

#### G-9-1 Skill 文件规范

- **[UNRESOLVED]** `G-9-001` — SKILL.md 文件名的命名规范（kebab-case？如 academic-search.md、code-review.md）
- **[UNRESOLVED]** `G-9-002` — 每个 agent 的 skills/ 目录路径（openclaw/workspace/{agent_id}/skills/*.md）
- **[UNRESOLVED]** `G-9-003` — TOOLS.md 中 skill 引用的方式（完整路径还是 skill 名称，agent 如何自动发现可用 skill）
- **[UNRESOLVED]** `G-9-004` — Skill 文件大小上限（单个 SKILL.md 建议的 token 上限，确保总 TOOLS.md 不过载）
- **[UNRESOLVED]** `G-9-005` — agent 在 session 中自动匹配 skill 的机制（agent 读 TOOLS.md 后自己判断，还是 step 指令中提示）
- **[UNRESOLVED]** `G-9-006` — TOOLS.md 的 token 上限（所有 skill 摘要列表注入 session 的 token 预算）
- **[UNRESOLVED]** `G-9-007` — Skill 文件的 git 提交规范（skill 更新的 PR 审查流程，还是 steward 提案 + 用户确认后 commit）
- **[UNRESOLVED]** `G-9-021` — SKILL.md 文件的完整 section 结构（`## 适用场景`、`## 执行步骤`、`## 输出格式`、`## 注意事项` 等 section 名称和格式）
- **[UNRESOLVED]** `G-9-022` — SKILL.md 中"执行步骤"section 是否使用 markdown checklist（`- [ ] 步骤`）还是有序列表
- **[UNRESOLVED]** `G-9-023` — SKILL.md 的`## 质量标准` section（arbiter 评审时参考的质量要求）的格式——是定量指标还是定性描述
- **[UNRESOLVED]** `G-9-024` — SKILL.md 中"适用模型"的声明方式——是显式写 `model: analysis` 还是隐含在场景描述中
- **[UNRESOLVED]** `G-9-025` — TOOLS.md 中 skill 列表的格式——每个 skill 是一行摘要（`- academic-search.md: 学术文献搜索流程`）还是完整引用 SKILL.md 内容
- **[UNRESOLVED]** `G-9-026` — TOOLS.md 的总 token 上限（所有 skill 摘要加上工具说明，注入 session 时的 token 预算）
- **[UNRESOLVED]** `G-9-027` — skill 文件名大小写规范（全小写 kebab-case：`academic-search.md` 不是 `AcademicSearch.md`）
- **[UNRESOLVED]** `G-9-028` — 每个 agent 的初始 skill 数量下限（Phase 5 要求每个 agent 至少 3-5 个核心 skill）
- **[UNRESOLVED]** `G-9-029` — SKILL.md 文件的最大 token 数（单个 skill 文件大小上限，防止注入时 overflow）
#### G-9-2 Skill 生命周期

- **[UNRESOLVED]** `G-9-008` — Phase 5 skill 准备时，scholar 搜索的具体 query 模板（按 agent 领域）
- **[UNRESOLVED]** `G-9-009` — skill 草稿审阅流程（artificer 写草稿 → 用户审阅 → 写入 skills/ 目录）
- **[UNRESOLVED]** `G-9-010` — 生产阶段 skill 的问题检测阈值——arbiter 拒绝率 > 20% 的统计周期（最近 N 次调用）
- **[UNRESOLVED]** `G-9-011` — skill 修改后的验证方式（scripts/verify.py 如何针对特定 skill 运行验证）
- **[UNRESOLVED]** `G-9-012` — 外部最佳实践更新的触发频率（scholar 定期重扫的 Temporal Schedule 间隔）
- **[UNRESOLVED]** `G-9-013` — skill 废弃的流程（是否需要从 TOOLS.md 中显式移除）
- **[UNRESOLVED]** `G-9-030` — Phase 5 skill 准备时，scholar 搜索最佳实践的 query 模板（按 agent 领域，如 scholar: `"LLM agent academic research best practices 2024"`)
- **[UNRESOLVED]** `G-9-031` — artificer 将外部资料改写为 SKILL.md 格式时的转换 prompt 模板（保留关键步骤，适配 SKILL.md 结构）
- **[UNRESOLVED]** `G-9-032` — 用户审阅 skill 草稿的操作流程——是通过 Console 界面还是直接编辑文件，审阅结果如何记录
- **[UNRESOLVED]** `G-9-033` — skill 更新后的验证流程——`scripts/verify.py --skill academic-search` 的实现方式（运行哪种测试用例）
- **[UNRESOLVED]** `G-9-034` — skill 更新后是否需要重启 OC Gateway（TOOLS.md 修改是否热加载）
- **[UNRESOLVED]** `G-9-035` — skill 废弃的标记方式——是物理删除文件还是在文件中加 `deprecated: true` 标记
- **[UNRESOLVED]** `G-9-036` — skill 迭代提案（state/skill_proposals/）的文件格式（包含当前 SKILL.md 内容 + 修改建议 + rejection 原话的结构）
- **[UNRESOLVED]** `G-9-037` — 外部最佳实践重扫的 Temporal Schedule interval（每月一次？每季度一次？）
- **[UNRESOLVED]** `G-9-038` — skill 文件的 git 提交规范——commit message 中是否需要包含 skill_name 和版本号
- **[UNRESOLVED]** `G-9-039` — 多个 skill 对应同一任务类型时，agent 如何选择（TOOLS.md 中是否有优先级标注）
- **[UNRESOLVED]** `G-9-040` — skill 调用统计写入哪里——是 Langfuse trace metadata 还是单独的 skill_stats 表（以前的 LedgerStats 被 Langfuse 替代后）
- **[UNRESOLVED]** `G-9-041` — steward 在 Layer 1 修复 SKILL.md 时，修改的内容由 steward LLM 根据 rejection feedback 生成——修改后的内容是否需要 diff review 再写入
- **[UNRESOLVED]** `G-9-042` — skill 文件中是否允许内嵌代码示例（如 Python 代码块），代码示例的 token 消耗是否纳入 skill 大小上限
- **[UNRESOLVED]** `G-9-043` — agent 在 session 执行中"隐式匹配"skill 的实现——是 TOOLS.md 列出后 agent 自行阅读判断，还是 Step 指令中明确写 `use_skill: academic-search`
- **[UNRESOLVED]** `G-9-044` — SKILL.md 中是否有"失败处理"section（描述当 skill 执行步骤失败时的降级方法）
- **[UNRESOLVED]** `G-9-045` — scholar 的 `source-eval.md` skill 中，Tier C 来源的交叉验证步骤应如何描述（具体的"至少两个独立来源"验证流程）
- **[UNRESOLVED]** `G-9-046` — arbiter 的 `fact-check.md` skill 中，"事实性主张必须有来源"的验证步骤格式
- **[UNRESOLVED]** `G-9-047` — envoy 的 `github-pr-publish.md` skill 中，PR 模板（title/body/labels）的格式规范
- **[UNRESOLVED]** `G-9-048` — counsel 的 `replan-judgment.md` skill 中，偏离判断的决策树格式
- **[UNRESOLVED]** `G-9-049` — steward 的 `skill-calibration.md` skill 的内容——包含哪些校准步骤和判断规则
- **[UNRESOLVED]** `G-9-050` — artificer 调用 `codex` 时，codex skill（`codex-implementation.md`）中 context 注入的具体内容（项目文件树、相关代码等的获取方式）
- **[UNRESOLVED]** `G-9-051` — scribe 的写作 skill 中，是否有"语言检测"步骤（根据 Brief 的 language 字段选择中文还是英文 skill）
- **[UNRESOLVED]** `G-9-052` — arbiter 的 review skill 是否按 agent 类型分化（对 scribe 产出用 `style-review.md`，对 artificer 产出用 `code-review.md`，选择逻辑）
- **[UNRESOLVED]** `G-9-053` — counsel 的 `task-decomposition.md` skill 中，Step 粒度判断的规则（何时拆 Step 何时不拆的决策原则）
- **[UNRESOLVED]** `G-9-054` — envoy 的 `telegram-announce.md` skill 中，对不同类型通知（告警/完成通知/日报）的格式区分
- **[UNRESOLVED]** `G-9-055` — scholar 的 `web-research.md` skill 中，Firecrawl vs Playwright 的选择规则（具体的"需要登录或 JS 渲染"判断标准）
- **[UNRESOLVED]** `G-9-056` — steward 的 `health-check.md` skill 中，体检步骤的执行顺序和每步的 pass/fail 判断标准
- **[UNRESOLVED]** `G-9-057` — artificer 的 `debugging.md` skill 中，错误定位步骤（日志分析 → 代码定位 → 修复验证的流程）
- **[UNRESOLVED]** `G-9-058` — scribe 的 `academic-abstract.md` skill 中，摘要的结构要求（background/methods/results/conclusions 格式还是自由格式）
- **[UNRESOLVED]** `G-9-059` — arbiter 的 `logic-consistency.md` skill 中，逻辑一致性检查的具体维度（前后矛盾、因果错误、统计滥用等）
- **[UNRESOLVED]** `G-9-060` — counsel 的 `project-planning.md` skill 中，Folio 结构（多 Task 项目）的规划步骤
#### G-9-3 Skill 内容规范

- **[UNRESOLVED]** `G-9-014` — scholar 的核心 skill 清单（academic-search.md、web-research.md、source-eval.md 等命名）
- **[UNRESOLVED]** `G-9-015` — counsel 的核心 skill 清单（project-planning.md、task-decomposition.md、replan-judgment.md 等）
- **[UNRESOLVED]** `G-9-016` — artificer 的核心 skill 清单（code-implementation.md、debugging.md、code-review.md 等）
- **[UNRESOLVED]** `G-9-017` — scribe 的核心 skill 清单（tech-blog.md、academic-abstract.md、executive-summary.md 等）
- **[UNRESOLVED]** `G-9-018` — arbiter 的核心 skill 清单（fact-check.md、logic-consistency.md、style-review.md 等）
- **[UNRESOLVED]** `G-9-019` — envoy 的核心 skill 清单（github-pr-publish.md、telegram-announce.md、format-convert.md 等）
- **[UNRESOLVED]** `G-9-020` — steward 的核心 skill 清单（health-check.md、skill-calibration.md、issue-diagnosis.md 等）
### G-10 可观测性与自愈

#### G-10-1 Langfuse 追踪

- **[UNRESOLVED]** `G-10-001` — Langfuse trace 的完整属性注入（job_id、task_id、step_id、agent_id、skill_name 等的注入点）
- **[UNRESOLVED]** `G-10-002` — Langfuse generation 记录时机（是在 session spawn 后、messages send 后，还是 session close 后）
- **[UNRESOLVED]** `G-10-003` — Langfuse 的 score 功能使用方式（arbiter 通过/不通过是否写入 Langfuse score）
- **[UNRESOLVED]** `G-10-004` — 单 Step token 消耗告警阈值的配置位置（SYSTEM_DESIGN 说"按类型定"，各类型的具体值）
- **[UNRESOLVED]** `G-10-005` — Langfuse Dashboard 的访问控制（是否需要认证，默认用户名密码）
- **[UNRESOLVED]** `G-10-021` — Langfuse trace 的创建时机——是在 Job Activity 开始时创建，还是在第一个 Step Activity 开始时创建
- **[UNRESOLVED]** `G-10-022` — Langfuse span（Step 层级）的 `name` 字段命名规范（`{agent_id}:{step_id}` 还是 `step_{seq}`）
- **[UNRESOLVED]** `G-10-023` — Langfuse generation（LLM 调用层级）的 `model` 字段格式——是 OC 的 model alias（`fast`）还是实际 model ID（`minimax-m2.5`）
- **[UNRESOLVED]** `G-10-024` — Langfuse trace 的 `user_id` 字段——daemon 是单用户系统，统一使用什么值（`user` 还是 `daemon`）
- **[UNRESOLVED]** `G-10-025` — Langfuse 的 `score()` API 调用格式——arbiter 写入 score 时的 `name`、`value`、`data_type` 参数值约定
- **[UNRESOLVED]** `G-10-026` — Langfuse trace 与 PG jobs/job_steps 记录的关联——`trace_id` 字段存在 PG 的哪个表（jobs 表还是 job_steps 表）
- **[UNRESOLVED]** `G-10-027` — Langfuse 的异步 flush 策略——Activity 结束前是否显式 await `langfuse.async_flush()`
- **[UNRESOLVED]** `G-10-028` — steward 查询 Langfuse 数据使用 Langfuse Python SDK 的哪个方法（`get_generations()`、`get_traces()` 等）
- **[UNRESOLVED]** `G-10-029` — Langfuse 体检数据的时间范围查询参数（`from_timestamp`、`to_timestamp`）的具体格式
- **[UNRESOLVED]** `G-10-030` — Langfuse 的 `metadata` 字段中是否包含 `skill_name`——agent 执行 Step 时是否记录使用了哪个 skill
#### G-10-2 可追溯链

- **[UNRESOLVED]** `G-10-006` — Job ID 写回 Plane Issue 的方式（Plane comment API 还是 custom field）
- **[UNRESOLVED]** `G-10-007` — PG job/step 记录与 Langfuse trace 的关联字段（trace_id 存入 PG 的哪个字段）
- **[UNRESOLVED]** `G-10-008` — Temporal workflow_id 与 Job ID 的关系（1:1 还是有额外映射表）
#### G-10-3 自愈机制

- **[UNRESOLVED]** `G-10-009` — steward 规则驱动诊断的具体规则清单（判断 skill 问题、token 超标、arbiter 拒绝高的规则）
- **[UNRESOLVED]** `G-10-010` — 问题文件（state/issues/）的保留策略（已解决的 issue 文件移到 state/issues/resolved/ 还是原地保留）
- **[UNRESOLVED]** `G-10-011` — scripts/verify.py 的功能实现（如何运行验证用例并发 Telegram 通知）
- **[UNRESOLVED]** `G-10-012` — scripts/start.py 的服务检查顺序（Docker healthcheck + Python 进程 + OC Gateway 的检查顺序）
- **[UNRESOLVED]** `G-10-013` — Layer 2 自愈 subprocess 调用 CC 时，传入的参数格式（是文件路径还是通过 stdin 传入）
- **[UNRESOLVED]** `G-10-014` — Layer 2 自愈失败判定标准（verify.py 返回非零退出码，还是产出中有 error 关键词）
- **[UNRESOLVED]** `G-10-015` — Layer 3 用户通知后，用户执行 CC 修复的工作流（用户如何把 issue 文件发给 CC）
- **[UNRESOLVED]** `G-10-016` — steward 诊断时查询 Langfuse 数据的 API（Langfuse Python SDK 的 trace 查询接口）
- **[UNRESOLVED]** `G-10-031` — steward 规则驱动诊断的完整规则清单的来源——是硬编码的 Python 规则还是从 `steward_rules.json` 配置文件加载
- **[UNRESOLVED]** `G-10-032` — Layer 1 自动修复的边界——修改 SKILL.md 的最大变更量（修改字节数上限，防止 steward 大幅改写 skill）
- **[UNRESOLVED]** `G-10-033` — Layer 2 自愈时，claude_code subprocess 的工作目录（DAEMON_HOME 还是临时目录）
- **[UNRESOLVED]** `G-10-034` — Layer 2 自愈成功的判定标准——`scripts/verify.py` 的返回码为 0 即成功，还是需要额外验证
- **[UNRESOLVED]** `G-10-035` — Layer 3 用户介入时，state/issues/ 目录的问题文件通过什么渠道通知用户（Telegram 附带文件 vs 在 Telegram 中说明）
- **[UNRESOLVED]** `G-10-036` — state/issues/ 目录中已解决的问题文件的归档策略——移到 state/issues/resolved/ 还是物理删除
- **[UNRESOLVED]** `G-10-037` — 自愈操作的 Langfuse 记录方式——Layer 1/2/3 的每次操作是否创建独立的 Langfuse trace
- **[UNRESOLVED]** `G-10-038` — 体检脚本的执行位置——是 steward OC session（消耗 LLM token）还是 Temporal Activity 直接 Python 执行
- **[UNRESOLVED]** `G-10-039` — steward 在 Activity 中查询 Langfuse 数据的具体 API 调用（Python SDK 的 `Langfuse(...)` 初始化参数）
- **[UNRESOLVED]** `G-10-040` — scripts/verify.py 的具体实现——是运行一组 pytest 测试用例还是执行特定的 link test suite
- **[UNRESOLVED]** `G-10-041` — steward 体检结果存入 state/health_reports/ 时的写入原子性（是否有 tmp 文件 + rename 机制）
- **[UNRESOLVED]** `G-10-042` — 自愈操作（Layer 1 修改 SKILL.md）是否记录到 event_log 表（用于审计），还是仅在 Langfuse 记录
- **[UNRESOLVED]** `G-10-043` — Layer 2 claude_code 子进程的超时设置（自愈操作可能需要多长时间，设置合理的 subprocess timeout）
- **[UNRESOLVED]** `G-10-044` — steward 在发现多个问题时的优先级排序规则——哪类问题优先触发自愈（外部出口失败 > skill 拒绝率高 > token 超标）
- **[UNRESOLVED]** `G-10-045` — 自愈操作日志（Layer 1/2/3）的最大保留数量（state/health_reports/ 目录的文件数上限）
- **[UNRESOLVED]** `G-10-046` — 周度体检对"外部出口链路"（Telegram/GitHub）的验证方式——是否每周实际发送测试消息到真实平台
- **[UNRESOLVED]** `G-10-047` — steward 体检中"Langfuse 查询过去 7 天数据"的时间窗口边界（UTC 周一 00:00 到周日 23:59 还是相对 7 天）
- **[UNRESOLVED]** `G-10-048` — 体检失败告警的 Telegram 消息发送失败时（Telegram 不可用）的回退方案（写入 event_log 等待恢复后补发）
- **[UNRESOLVED]** `G-10-049` — steward 的 analysis 模型（Qwen Max）的 token 消耗是否纳入 daily_token_limit 配额（steward 有独立配额还是共享）
- **[UNRESOLVED]** `G-10-050` — 自愈 Layer 2 时，issue 文件中必须包含哪些信息（错误类型、受影响的 skill/agent、Langfuse 链接、建议修复方向）
- **[UNRESOLVED]** `G-10-051` — 体检报告的版本追踪——是否将 state/health_reports/ 纳入 git 管理，或者是 steward 仅保留最近 N 份
- **[UNRESOLVED]** `G-10-052` — steward 在诊断时访问 PG 数据的方式——是通过 daemon 内部的 store.py 模块还是直接使用 asyncpg 查询
- **[UNRESOLVED]** `G-10-053` — 体检过程中如果 Langfuse 不可用（宕机），steward 如何处理（跳过 Langfuse 相关检查，仍执行其他检查）
- **[UNRESOLVED]** `G-10-054` — 单个 skill 的"最近 N 次调用"中 N 的值（arbiter 拒绝率 > 20% 的统计基准，N=5 还是 N=10）
- **[UNRESOLVED]** `G-10-055` — steward 在发现 skill 问题时，提案文件（state/skill_proposals/）的写入是否通过 Plane Issue 通知用户审阅
- **[UNRESOLVED]** `G-10-056` — Layer 1 自愈后的验证步骤——steward 修改 SKILL.md 后，是否立即运行一个该 skill 的轻量测试任务验证效果
- **[UNRESOLVED]** `G-10-057` — steward 的体检 Temporal Schedule 如果在上一次体检还在进行时到达，如何处理（跳过还是排队）
- **[UNRESOLVED]** `G-10-058` — 体检告警的 YELLOW/RED 升降级逻辑——从 YELLOW 降回 GREEN 的条件（连续 N 次体检通过？）
- **[UNRESOLVED]** `G-10-059` — steward 诊断"arbiter 拒绝率"的计算方式——是 skill_stats 表的 rejected/invocations 比率，还是 Langfuse score 中低分比率
- **[UNRESOLVED]** `G-10-060` — 系统历史 health_reports 中的趋势分析——steward 是否在体检报告中包含与上次体检的对比
#### G-10-4 周度体检脚本

- **[UNRESOLVED]** `G-10-017` — 体检脚本的实现位置（是 Temporal Activity 还是独立脚本 scripts/health_check.py）
- **[UNRESOLVED]** `G-10-018` — 17 条链路验证（Stage 2 缩减版）的缩减规则（缩减后保留哪几条，判断依据）
- **[UNRESOLVED]** `G-10-019` — 质量层体检（steward 主导）的"固定基准任务"的执行方式（steward 直接提交还是通过 Job 机制）
- **[UNRESOLVED]** `G-10-020` — 体检报告中"伪人度评分"的测量方法（steward 看产出并给分，prompt 模板）
#### G-10-5 查询与告警格式

- **[UNRESOLVED]** `G-10-061` — Langfuse 中"skill_name"的提取方式——是 agent 在 session 中输出特定格式的 skill reference，还是由 Temporal Activity 在调用 OC 前注入到 trace metadata
- **[UNRESOLVED]** `G-10-062` — steward 通过 Langfuse API 批量查询 N 天内的 generations 时，分页处理策略（每页多少条，如何遍历所有页）
- **[UNRESOLVED]** `G-10-063` — 周度体检的告警消息（Telegram）格式模板——YELLOW 告警和 RED 告警的消息内容区别（是否包含问题细节 vs 仅告警级别）
### G-11 禁止事项与边界

#### G-11-1 已确认禁止行为（需验证机制实现）

- **[UNRESOLVED]** `G-11-001` — "不允许直接 session 共享"的技术强制机制——是否有 session key 冲突检测
- **[UNRESOLVED]** `G-11-002` — "不允许动态创建新 agent"的技术强制机制——Worker 进程是否有 agent_id 白名单验证
- **[UNRESOLVED]** `G-11-003` — "dag 字段有 running Job 时只读"的 API 层实现——`PATCH /api/tasks/{id}/dag` 返回 409 的条件
- **[UNRESOLVED]** `G-11-004` — "counsel 不感知 skill"的设计边界——counsel 的 MEMORY.md 中是否明确禁止引用 skill 名称
- **[UNRESOLVED]** `G-11-005` — "所有 Persona 修改经用户确认"的技术门控——NeMo custom action 的返回值如何阻止 Mem0 写入
- **[UNRESOLVED]** `G-11-006` — "不自动更新 skill"的 steward Layer 1 修复的边界——Layer 1 自动修复的操作仅限哪些
- **[UNRESOLVED]** `G-11-007` — "envoy 是唯一对外出口"的技术强制机制——其他 agent 的 MCP server 配置是否排除外部发布工具
- **[UNRESOLVED]** `G-11-008` — "subagent 不加载 MEMORY.md"的机制——是 OC 原生行为还是需要在 sessions_spawn 时显式不传
- **[UNRESOLVED]** `G-11-009` — "subagent 不能读写 Mem0"的强制机制——是 OC 原生限制还是需要在 Activity 中 workaround
#### G-11-2 边界情形处理

- **[UNRESOLVED]** `G-11-010` — Project 中某个 Task 已 completed，但 Replan Gate 判断需要"重做"该 Task——是否允许，处理规则
- **[UNRESOLVED]** `G-11-011` — Temporal Workflow 意外终止（Worker crash）后，Job 状态如何从 running 变为正确状态（replay 后继续 or failed）
- **[UNRESOLVED]** `G-11-012` — Plane webhook 重复投递同一事件时的幂等处理（基于 webhook event_id 去重）
- **[UNRESOLVED]** `G-11-013` — Mem0 检索返回空结果时，Session 注入内容的降级处理（不注入 Mem0 部分，仅注入 MEMORY.md）
- **[UNRESOLVED]** `G-11-014` — OC Gateway 宕机期间，提交到 Temporal 的 Job 如何处理（等待 OC 恢复，Temporal Activity 自动重试）
- **[UNRESOLVED]** `G-11-015` — RAGFlow 宕机期间，知识检索降级到什么（直接跳过 RAGFlow，只用 Mem0 + Step 指令）
- **[UNRESOLVED]** `G-11-016` — 所有 Step 完成但最后一个 Step 的 Artifact 写入 MinIO 失败时，Job 的最终状态
- **[UNRESOLVED]** `G-11-017` — scholar 搜索到的内容与 sensitive_terms.json 匹配时，是替换关键词后存 knowledge_cache 还是不存
- **[UNRESOLVED]** `G-11-018` — counsel 规划产出的 DAG 中包含未知 agent_id（非 7 个合法 agent）时的处理
- **[UNRESOLVED]** `G-11-019` — Temporal 重放时，Artifact 已存在 MinIO 的 Step 是否需要重新执行（Temporal 原生 checkpoint 跳过）
- **[UNRESOLVED]** `G-11-020` — 定时触发 Task 与手动触发冲突（定时触发时已有 running Job）的处理规则
- **[UNRESOLVED]** `G-11-021` — Plane 侧 Issue 被用户直接删除时，daemon 侧的 Task 数据如何处理（Plane webhook issue.deleted 事件）
- **[UNRESOLVED]** `G-11-022` — scholar 调用 Firecrawl 抓取页面需要登录时的处理（回退到 Playwright MCP 还是标记无法访问）
- **[UNRESOLVED]** `G-11-023` — Job 并发上限（maxConcurrent）触发时，新 Job 进入排队队列还是立即返回 429
- **[UNRESOLVED]** `G-11-024` — "subagent 不能读写 Mem0"的强制机制——OC 是否在 subagent session 中自动禁用所有 Mem0 相关 tool，还是通过 TOOLS.md 不包含 Mem0 工具来实现
- **[UNRESOLVED]** `G-11-025` — agent 被 counsel 在规划时分配了超出其能力的 Step（如分配给 scribe 一个编码任务）时，Step 失败的处理（counsel 判断 replace 并换 agent）
- **[UNRESOLVED]** `G-11-026` — 用户通过 Telegram 发送超长指令（超过 Telegram 消息限制）时的处理（截断还是要求通过 Plane 提交）
- **[UNRESOLVED]** `G-11-027` — 两个 Step 的 session key 碰撞（相同 `{agent_id}:{job_id}:{step_id}`）的防御机制（step_id 是否保证全局唯一）
- **[UNRESOLVED]** `G-11-028` — Temporal Workflow 意外终止后重启，部分 Step 的 Artifact 已写入 MinIO 但 job_steps 状态未更新时的一致性恢复机制
- **[UNRESOLVED]** `G-11-029` — Plane webhook 中 issue_id 不在 daemon_tasks 表中（Plane 创建了非 daemon 管理的 Issue）时的处理（忽略还是自动注册）
- **[UNRESOLVED]** `G-11-030` — 定时触发 Task 的 Temporal Schedule 被手动删除（在 Temporal UI 操作）后，daemon 如何检测和重建（steward 体检中包含 Schedule 存在性验证）
- **[UNRESOLVED]** `G-11-031` — RAGFlow 返回的检索结果包含非预期内容（如另一个 Job 的文档）时的隔离验证（knowledge_base_id 的 Job 隔离还是全局共享）
- **[UNRESOLVED]** `G-11-032` — OC Gateway 版本升级期间，已在 session 的 OC sessions 是否持续有效（版本兼容性保证）
- **[UNRESOLVED]** `G-11-033` — Plane API token 过期时（401 响应），daemon 的自动刷新机制——是否有 token 刷新逻辑，还是直接告警
- **[UNRESOLVED]** `G-11-034` — MinIO 存储空间不足时（上传 Artifact 失败），Job 的处理方式（Step failed，还是等待清理后重试）
- **[UNRESOLVED]** `G-11-035` — PG 连接池耗尽（所有连接都在使用中）时，新的 Activity 请求的处理方式（等待超时还是立即失败）
- **[UNRESOLVED]** `G-11-036` — 用户同时触发多个 Task（Plane 中快速点击执行）时，如果总 Quota 不足，排队顺序由什么决定（FIFO 还是优先级）
- **[UNRESOLVED]** `G-11-037` — steward 体检时运行的基准任务与生产任务混合在 Temporal 中，如何区分（是否有 `is_health_check: true` 标记）
- **[UNRESOLVED]** `G-11-038` — Mem0 服务宕机时，依赖 Mem0 的 Step（需要注入 Persona 的 agent Step）的降级行为（跳过 Mem0 注入继续执行，还是 Step failed）
- **[UNRESOLVED]** `G-11-039` — NeMo Guardrails 拦截了 counsel 的 routing decision 输出时（counsel 输出触发 output rail），系统如何恢复（counsel 重试还是 Job 创建失败）
- **[UNRESOLVED]** `G-11-040` — 并行 Step 中，一个 Step 写入 knowledge_cache 的内容是否对同一 Job 的其他并行 Step 立即可见（PG 事务可见性）
- **[UNRESOLVED]** `G-11-041` — 用户在 Plane 中将 Issue 从一个 Project 移到另一个 Project 时，daemon_tasks 表中的 project 关联如何更新
- **[UNRESOLVED]** `G-11-042` — Temporal Schedule catchup（积压补执行）时，同一 Task 的多个补执行 Job 如何处理并发约束（仍然保持同一 Task 只有一个非 closed Job）
- **[UNRESOLVED]** `G-11-043` — `dag_snapshot` 中引用的 Step 依赖 Artifact（`input_artifacts` 字段）在 Job 重试时是否需要重新生成，还是复用上次成功 Step 的 Artifact
- **[UNRESOLVED]** `G-11-044` — Langfuse SDK 初始化失败（Langfuse 服务不可用）时，Temporal Activity 是否继续执行（降级模式：不记录 trace 但继续执行）
- **[UNRESOLVED]** `G-11-045` — PG LISTEN/NOTIFY 连接断开后的自动重连——Worker 进程是否有重连逻辑，重连后是否回放断开期间的 event_log 未消费事件
- **[UNRESOLVED]** `G-11-046` — steward 的 Layer 1 修复与 Layer 2 自愈的触发条件是否有优先级（先尝试 Layer 1，失败后升级 Layer 2）
- **[UNRESOLVED]** `G-11-047` — 用户在暖机完成前提交 Job 时（`state/warmup_report.json` 不存在或 `status != "ready"`），daemon 的响应（警告但允许还是拒绝执行）
- **[UNRESOLVED]** `G-11-048` — Task 的 `brief.dag_budget` 超过 Guardrails 设置的最大 Step 数时（恶意或失控的超大 DAG），Guardrails 在哪个阶段拦截（counsel 规划阶段还是 Activity 执行前）
- **[UNRESOLVED]** `G-11-049` — Job 执行过程中，用户修改了 Task 的 `brief` 字段（通过 Plane 更新 Issue description），进行中的 Job 是否受影响（不影响，`dag_snapshot` 已在 Job 创建时冻结）
- **[UNRESOLVED]** `G-11-050` — Replan Gate 产生新 DAG 后，如果新 DAG 的 Task 数超过 Plane Project 的 Issue 配额，创建失败的处理方式
- **[UNRESOLVED]** `G-11-051` — 多个并发 Job 写入同一 knowledge_cache 条目（相同 source_url）时的冲突处理（`INSERT ... ON CONFLICT DO UPDATE` 的 upsert 策略）
- **[UNRESOLVED]** `G-11-052` — OC session 内部的 tool call（agent 调用 MCP tool）超过 `maxChildrenPerAgent` 限制时的行为（OC 内部排队还是返回 error）
- **[UNRESOLVED]** `G-11-053` — Telegram Bot 在 daemon 启动前已有积压的未读消息时的处理（是否回放处理，还是忽略启动前的消息）
- **[UNRESOLVED]** `G-11-054` — Plane Issue 被用户通过 Plane UI 直接编辑 custom field（如 dag 字段）时，daemon 是否通过 webhook 检测并阻止（返回 Plane comment 说明）
- **[UNRESOLVED]** `G-11-055` — Job 执行超过 `execution_timeout` 后，Temporal Workflow cancel 与正在执行的 OC session 的关系——cancel Workflow 是否同时 close OC session
- **[UNRESOLVED]** `G-11-056` — 多用户场景（未来扩展）下，当前单用户假设的哪些地方需要变更（如 Mem0 `user_id` 硬编码问题，提前识别以便未来改造）
- **[UNRESOLVED]** `G-11-057` — NeMo Guardrails 版本升级时（Python 包升级），Colang 规则是否需要迁移（语法兼容性问题的检测方法）
- **[UNRESOLVED]** `G-11-058` — 如果 Temporal Schedules 全部丢失（如 Temporal namespace reset），daemon 的恢复程序——scripts/recover_schedules.py 是否存在
- **[UNRESOLVED]** `G-11-059` — Langfuse project 被意外清空时，steward 体检能否优雅降级（缺少 Langfuse 历史不影响基本功能运行）
- **[UNRESOLVED]** `G-11-060` — Plane webhook secret 轮换时，daemon 的处理流程——更新 .env 文件 + 重启 API 进程，是否有零停机轮换方案
### G-12 交互与界面契约

#### G-12-1 页面结构与导航

- **[FINAL]** `G-12-001` — plan card 的强制性规则——每个 Task 必须稳定展示 plan card，不能因任务轻重切换成不同的 UI 物种 · 覆盖：§4.2
- **[FINAL]** `G-12-002` — Project 页面骨架——标题 / 摘要、关系图、当前活跃 Task、最近执行 Task、最近 Artifact 摘要这五个区域的固定布局与信息职责 · 覆盖：§4.4
- **[FINAL]** `G-12-003` — Task 链 DAG 导航规则——线性链、分支点、合并点分别如何展示“上一个 / 下一个 Task”标签与跳转入口 · 覆盖：§4.5
#### G-12-2 活动流、操作记录与 Draft 流程

- **[FINAL]** `G-12-004` — 操作记录消息的结构规范——按钮 / 拖拽 / 状态切换等非对话操作写入 Plane Activity 时的 `role / event / content` 格式与渲染区分 · 覆盖：§4.6 + 附录 D
- **[FINAL]** `G-12-005` — Draft 的来源与对象地位——用户对话、规则触发、外部事件、系统内部推进四种来源，以及 Draft 不是临时聊天缓存的正式定义 · 覆盖：§4.3
#### G-12-3 API 与 WebSocket 契约

- **[DEFAULT]** `G-12-006` — daemon 胶水层的最小 API 端点集合——`pause / resume / cancel / stream / artifacts / webhooks` 的路径命名与职责边界，以及 Job 实时面板的 WebSocket 心跳契约 · 覆盖：§4.9 + 附录 D
- **[DEFAULT]** `G-12-007` — Task 依赖状态 API 字段——前端判断按钮 disabled 需要返回哪些字段（如 `latest_job_status`、`next_trigger_utc`）及其语义 · 覆盖：§4.9 + 附录 D
- **[FINAL]** `G-12-008` — 统一活动流 API 返回格式——Task 下所有 Job 的合并活动流如何排序、如何携带 `job_id`，以及 Job 边界如何在响应中显式表达 · 覆盖：§4.6 + 附录 D
#### G-12-4 状态文案与呈现规范

- **[FINAL]** `G-12-009` — Job 状态的正式中文显示文案——排队中 / 执行中 / 等待审查 / 重试中 / 已完成 / 执行失败 / 已取消等状态的固定映射 · 覆盖：§4.10 + 附录 D
#### G-12-5 管理界面与隐私边界

- **[DEFAULT]** `G-12-010` — Plane 管理界面的数据访问限制——哪些元数据可以暴露，哪些对话正文 / Step instruction / Persona 内容必须受限或做特意开放 · 覆盖：§4.11 + 附录 D
### G-13 术语与文档规范

#### G-13-1 中文术语映射

- **[FINAL]** `G-13-001` — Plane 界面的正式中文术语映射表——Project / Task / Job / Step / Artifact / Draft / Persona / Guardrails / Knowledge Base 的固定中文显示名 · 覆盖：§1.1 + 附录 D
#### G-13-2 翻译豁免与写作规则

- **[FINAL]** `G-13-002` — 翻译豁免规则——哪些外部专有名词、实现级标识、用户原始输入不得被系统强行翻译或改写 · 覆盖：§0.5 + 附录 D
#### G-13-3 词典同步与变更流程

- **[FINAL]** `G-13-003` — `config/lexicon.json` 与 `SYSTEM_DESIGN.md` 的同步规范——术语变更的文档优先级、校对顺序与代码落地流程 · 覆盖：§0.4 + 附录 G
