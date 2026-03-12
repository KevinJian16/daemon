# Daemon 实施方案

> 日期：2026-03-10  
> 本文档是 Daemon 当前唯一的机制说明书与实施规范。  
> 术语以 `TERMINOLOGY.md` 为准，交互以 `INTERACTION_DESIGN.md` 为准，细节裁定以 `DESIGN_QA.md` 为准。

---

## 0. 文档治理

六份权威文档（冲突优先级从高到低）：

1. `TERMINOLOGY.md` — 术语权威
2. `INTERACTION_DESIGN.md` — 交互权威
3. `DESIGN_QA.md` — 机制细节，与本文件冲突时以 QA 为准
4. `EXECUTION_MODEL.md` — 执行模型权威
5. 本文件（`daemon_实施方案.md`）— 全机制说明书与实施规范
6. `README.md` — 文档治理入口

---

## 1. 设计原则

1. **统一对象机制**：系统内外只承认同一组正式对象：`Draft / Slip / Folio / Writ / Deed`。
2. **先成札，超限开卷**：所有事项先尝试成为单张 `Slip`；超出承载上限才提升为 `Folio`。
3. **Deed 不是任务本体**：`Slip` 是任务载体，`Deed` 是一次执行实例。
4. **一切触发都是事件**：时间、链式推进、外部输入、用户动作，本质上都视为 `Event`。
5. **Writ 是规则层**：`Writ` 统一承担事件到对象动作的转换。
6. **前后台同一现实**：Portal 与 Console 只是不同视图，不允许各自维护另一套对象世界。
7. **中文正式显示、英文 canonical 实现**：Portal 与 Console 显示中文正式术语；代码、字段、存储、API 使用英文 canonical names。
8. **删除旧壳，不留双轨**：旧命名、旧对象分层、旧任务分类都必须移除，不继续与当前机制并存。
9. **前端表现语言是硬约束**：Portal 使用 Claude 静态 + Apple app 层级动态 + 文件系统式对象组织；Console 使用 Claude 静态 + Apple app 层级动态。

---

## 2. 系统总览

### 2.1 两个进程

| 进程 | 职责 |
|---|---|
| API 进程 | Portal / Console / Telegram 接入、Voice、Will、Cadence、Spine、Psyche、Nerve |
| Worker 进程 | Temporal workflow / activities、Retinue 执行、Herald 物流 |

两进程通过：

- Temporal
- 共享状态目录
- 事件桥

协同工作。

### 2.2 三个主要表面

| 表面 | 角色 |
|---|---|
| Portal | 主人和 Daemon 共用的案桌 |
| Console | 维护者的治理面 |
| Telegram | 通知与极简命令面 |

### 2.3 前端表现层约束

#### Portal

- 静态层尽量贴近 Claude 网页端的内容产品秩序
- 页面层级动态尽量贴近 Apple 原生 app
- `Slip / Folio` 的组织动态尽量贴近文件系统式对象操作

#### Console

- 静态层尽量贴近 Claude 网页端的内容产品秩序
- 页面层级动态尽量贴近 Apple 原生 app
- 不采用文件系统式对象组织感，不做 Finder / Files 味

#### 通用要求

- 所有会动的东西都按 Apple 动态语言设计
- 不允许普通 web app 式硬切、瞬切、后台面板切换感
- 不允许把 Portal 做成任务控制台，不允许把 Console 做成开发者后台

---

## 3. 正式对象模型

当前系统内只有五个正式事项对象。

### 3.1 Draft

`Draft` 是尚未成札、但已经被系统识别为候选事项的对象。

它承载：

- 初始意图
- 候选 `Brief`
- 候选 `Design`
- 收敛过程
- 修订历史

`Draft` 是正式对象，不是临时聊天缓存。

#### 最小字段

| 字段 | 含义 |
|---|---|
| `draft_id` | 全局唯一 ID |
| `source` | `chat | writ | event | manual` |
| `folio_id` | 所属 `Folio`，可空 |
| `seed_event` | 触发它的事件，允许为空 |
| `intent_snapshot` | 当前理解到的目标 |
| `candidate_brief` | 当前候选简报 |
| `candidate_design` | 当前候选方案 |
| `status` | `open | refining | crystallized | superseded | abandoned` |
| `created_utc` | 创建时间 |
| `updated_utc` | 更新时间 |

### 3.2 Slip

`Slip` 是持续存在的签札，是最小可持久化任务对象。

它承载：

- 标题
- 目标
- 正式 `Brief`
- 正式 `Design`
- 所属 `Folio`
- 生命周期
- 历史 `Deed`

#### 最小字段

| 字段 | 含义 |
|---|---|
| `slip_id` | 全局唯一 ID |
| `folio_id` | 所属 `Folio`，可空 |
| `title` | 签札标题 |
| `slug` | Portal 公开路由 slug |
| `slug_history` | 历史 slug |
| `objective` | 目标摘要 |
| `brief` | 正式 `Brief` |
| `design` | 正式 `Design` |
| `status` | `active | archived | deleted`（两层模型，见 `EXECUTION_MODEL.md` §5.3） |
| `sub_status` | `active` → `{normal, parked}`；`archived` → `{settled, archived}`；`deleted` → `{absorbed}` |
| `standing` | 是否常驻签札 |
| `latest_deed_id` | 最近一次 `Deed` |
| `created_utc` | 创建时间 |
| `updated_utc` | 更新时间 |

### 3.3 Folio

`Folio` 是卷，是收纳并组织若干 `Slip` 的主题容器。

#### 最小字段

| 字段 | 含义 |
|---|---|
| `folio_id` | 全局唯一 ID |
| `title` | 卷标题 |
| `slug` | Portal 公开路由 slug |
| `slug_history` | 历史 slug |
| `summary` | 卷摘要 |
| `status` | `active | archived | deleted`（两层模型，见 `EXECUTION_MODEL.md` §5.4） |
| `sub_status` | `active` → `{normal, parked}`；`deleted` → `{dissolved}` |
| `slip_ids` | 所属签札列表 |
| `writ_ids` | 所属成文列表 |
| `created_utc` | 创建时间 |
| `updated_utc` | 更新时间 |

### 3.4 Writ

`Writ` 是写在 `Folio` 中的成文规则。

它不是任务，不是容器，不是执行实例。

它的本体是：

`Event -> action(on Draft / Slip / Deed / Folio)`

#### 最小字段

| 字段 | 含义 |
|---|---|
| `writ_id` | 全局唯一 ID |
| `folio_id` | 所属卷 |
| `title` | 规则名 |
| `match` | 事件匹配条件 |
| `action` | 命中后的动作定义 |
| `status` | `active | paused | disabled` |
| `priority` | 匹配优先级 |
| `suppression` | 去重 / 抑制条件 |
| `version` | 规则版本 |
| `created_utc` | 创建时间 |
| `updated_utc` | 更新时间 |

### 3.5 Deed

`Deed` 是据某张 `Slip` 发生的一次具体行事。

它是一次执行实例，而不是任务本体。

#### 最小字段

| 字段 | 含义 |
|---|---|
| `deed_id` | 全局唯一 ID |
| `slip_id` | 来源签札 |
| `folio_id` | 所属卷，可空 |
| `writ_id` | 触发它的成文，可空 |
| `status` | `running | settling | closed`（两层模型，见 `EXECUTION_MODEL.md` §5.5） |
| `sub_status` | `running` → `{queued, executing, paused, retrying}`；`settling` → `{reviewing}`；`closed` → `{succeeded, failed, cancelled, timed_out}` |
| `brief_snapshot` | 本次执行时使用的简报快照 |
| `design_snapshot` | 本次执行时使用的方案快照 |
| `result_summary` | 本次结果摘要 |
| `started_utc` | 开始时间 |
| `ended_utc` | 结束时间 |
| `created_utc` | 创建时间 |

---

## 4. 对象关系与生命周期

### 4.1 基本关系

- 一个 `Folio` 可以收纳多张 `Slip`
- 一个 `Folio` 可以挂载多条 `Writ`
- 一张 `Slip` 可以生出多个 `Deed`
- 一个 `Deed` 必定源于某张 `Slip`
- 一个 `Writ` 必定属于某个 `Folio`

### 4.2 从 Draft 到 Slip

一件事的正式起点是 `Draft`。

收敛路径为：

`Event / 用户输入 -> Draft -> Brief + Design -> Slip`

`Draft` 成札后转为 `crystallized`，正式 `Slip` 成立。

### 4.3 从 Slip 到 Deed

`Slip` 不等于执行。

只有当系统或用户决定“据此行事”时，才生成新的 `Deed`。

因此：

- 同一张 `Slip` 可以多次执行
- “再执行一次”意味着新建一个 `Deed`
- `Slip` 的生命周期长于单个 `Deed`

### 4.4 周期性任务

周期性任务采用：

- standing `Slip`
- 一条或多条 `Writ`
- 多个历史 `Deed`

不是让一个 `Deed` 永远持续。

### 4.5 超限即开卷

所有事项默认先尝试成为单张 `Slip`。

单 `Slip` 承载上限采用当前正式单札基线：

- DAG 步数上限
- move budget
- 默认并发基线

若超出该上限：

- 不再扩成“更大的单札”
- 直接提升为 `Folio`
- 由多张 `Slip` 共同组织

### 4.6 删除规则

默认不做无声硬删除。

#### `Draft`

可在以下状态中被清理：

- `superseded`
- `abandoned`

#### `Slip`

默认只做：

- `parked`
- `archived`
- `absorbed`

不应物理删除，除非显式永久删除或系统级 purge。

#### `Deed`

完成后进入历史记录，不再活跃，但默认保留。

---

## 5. Event 与 Writ

### 5.1 一切触发都是 Event

系统不再把“定时”“链式”“外部触发”当作三套不同本体。

它们统一视为事件。

常见事件源包括：

- `time.tick`
- `user.spoken`
- `deed.completed`
- `deed.failed`
- `feedback.submitted`
- `external.received`
- `folio.changed`
- `slip.changed`

### 5.2 Writ 的匹配方式

`Writ` 统一通过事件匹配生效。

命中后，它可以执行以下动作之一或组合：

- `create_draft`
- `crystallize_draft`
- `spawn_deed`
- `advance_slip`
- `park_slip`
- `archive_slip`
- `attach_slip_to_folio`
- `create_folio`

### 5.3 触发类型排他性

对于给定的一张 `Slip`，触发类型是排他的（详见 `DESIGN_QA.md` Q8.5）：

- **手动触发**：用户按「执行」按钮
- **定时触发**：时间到达自动触发
- **前序事件触发**：Writ chain 中前序 `Deed` closed 后触发

三种触发类型互斥。Slip 页面和 Folio 结构视图按触发类型动态显示不同的按钮/信息。

### 5.4 Writ 是强约束

Writ 的排序是强制执行的，不是建议性的。前序条件未满足时，被约束的 Slip 的执行按钮禁用或隐藏。

### 5.5 链式任务

它由：

- 一卷 `Folio`
- 多张 `Slip`
- 一条或多条 `Writ`

共同表达。

例如：

- 某张 `Slip` 的 `Deed` closed
- 触发事件 `deed_closed`
- 相关 `Writ` 命中
- 生发下一张 `Slip` 或下一次 `Deed`

### 5.6 Writ 的学习

`Writ` 是可学习对象。

系统可以积累：

- 命中率
- 误触发率
- 触发时机质量
- 目标 `Slip` 选择偏好
- suppress 条件

但 canonical `Writ` 的正式变更必须版本化，不允许无声修改。

---

## 6. Psyche（心智层）

Psyche 由六个组件构成（详见 `DESIGN_QA.md` §1）：

| 组件 | 实现 | 职责 |
|------|------|------|
| Instinct | `InstinctEngine` + `instinct.md` | 不可覆盖的硬规则（代码执行）+ 软规则（prompt ~200 tokens） |
| Voice（画像） | `psyche/voice/` markdown 文件 | 身份画像（所有 agent）+ 写作风格（scribe/envoy） |
| Preferences | `PsycheConfig` TOML | 用户可调整的系统偏好 |
| Rations | `PsycheConfig` TOML | 资源额度与配额 |
| Ledger | `LedgerStats` SQLite | 机械统计：dag_templates / folio_templates / skill_stats / agent_stats |
| SourceCache | `SourceCache` SQLite + embedding | 外部知识 TTL 缓存 |

> 旧 Memory 和 Lore 已废除。不再有 LLM 学习循环。

### 6.1 Instinct（本能）

Instinct 是系统不可被用户覆盖的原则，代码层确定性执行。

三层：硬规则（Python pre/post check）→ 软规则（instinct.md prompt injection）→ 关键审查（arbiter）。

所有信息流入系统都必须过 Instinct 代码校验。

### 6.2 Voice（画像）

Voice 是系统的身份与写作风格，markdown 文件，不用数据库。

- `identity.md`：身份画像，注入所有 agent（≤150 tokens）
- `common.md` / `zh.md` / `en.md`：写作风格，只注入 scribe/envoy（≤250 tokens）
- `overlays/*.md`：任务类型覆盖（≤50 tokens）

> Voice（画像）是 Psyche 组件，与 §7 Voice（对话服务）不同。

### 6.3 Ledger（统计）

Ledger 只做机械统计，不做 LLM 语义学习。学习原则：只学 accepted，不学失败；学模式不学实例。

- **dag_templates**：accepted Deed 的 DAG 模板，embedding 相似度合并（cosine > 0.85），供 counsel few-shot 参考
- **folio_templates**：归档 Folio 的结构模板（accepted_ratio > 0.5）
- **skill_stats** / **agent_stats**：技能和 agent 表现的元数据统计

### 6.4 SourceCache（源缓存）

SourceCache 存放外部知识的 TTL 缓存，支持 embedding 检索。查询时 `folio_id` 作为主题偏置（同卷优先）。

### 6.5 选择性注入

Move 执行时按 agent 角色选择性注入 Psyche 内容（见 `DESIGN_QA.md` Q1.8）：

- 所有 agent → instinct + identity（~300 tokens）
- scribe/envoy → + style + overlay（~550 tokens）
- counsel → + planning_hints（~400 tokens）

### 6.6 规划学习归属

- `Folio`：主题背景与长期上下文
- `Slip`：通过 `dag_templates` 学习类似任务该如何规划
- `Writ`：学习触发效果（命中率、误触发率等）
- `Deed`：执行元数据写入 Ledger 统计

---

## 7. Voice

### 7.1 Voice 的职责

Voice 负责：

- 理解用户输入
- 将输入收敛为 `Draft`
- 生成 `Brief`
- 生成 `Design`

它不是执行层。

### 7.2 Brief

正式 `Brief` 至少包含：

| 字段 | 含义 |
|---|---|
| `objective` | 目标 |
| `language` | 语言要求 |
| `format` | 输出偏好 |
| `depth` | 深度要求 |
| `references` | 用户参考资料 |
| `dag_budget` | 单札 DAG 预算 |
| `fit_confidence` | 对“能否装入单札”的判断置信度 |
| `quality_hints` | 显式质量要求 |

### 7.3 Design

`Design` 是正式执行方案。

它必须满足：

- DAG 无环
- 节点合法
- 引用合法
- 步数不超过 `dag_budget`
- 至少存在 terminal move

### 7.4 plan card

所有 `Slip` 都必须拥有 plan card。

它是统一前台原件，不随事项轻重消失。

### 7.5 不收敛任务

系统不直接拒绝任务。

固定处理路径为：

1. 继续收敛 `Draft`
2. 尝试成为单张 `Slip`
3. 超上限则提升为 `Folio`

---

## 8. Will

### 8.1 enrich 流程

Will 的标准流程为：

1. `normalize`
2. `single_slip_defaults`
3. `quality_profile`
4. `model_routing`
5. `ration_preflight`
6. `ward_check`

### 8.2 single_slip_defaults

单 `Slip` 默认执行基线采用当前正式单札基线。

具体数值由暖机校准；机制结论固定。

### 8.3 model_routing

模型分配由：

- agent 角色
- `Brief`
- `PsycheConfig`（偏好与配额）
- 当前系统资源

共同决定。

### 8.4 Ration

`Ration` 负责配额与额度判断。

它不足时，对象进入排队，不跳过。

### 8.5 Ward

`Ward` 只负责系统健康门控：

- `GREEN`
- `YELLOW`
- `RED`

它不承担复杂度判断，也不承担对象组织职责。

---

## 9. Deed 执行

### 9.1 Retinue

系统使用预创建 `Retinue` 实例池，不在运行时动态创建 agent。

每个 `Deed` 分配空闲池实例，用完释放。实例生命周期：

1. `allocate(role, deed_id)` — 设置 `session_key`（格式：`{agent_id}:{deed_id}:{session_seq}`），写入选择性 Psyche 上下文，复制 workspace 模板
2. 执行期间 — 池实例持有一个 persistent full session（OC full mode），多个 Move 共享同一 session，记忆在 session 内累积
3. `release(instance_id)` — 销毁 session 文件，清理 workspace

### 9.2 执行流

标准执行流为：

`Slip -> Will -> Deed -> Temporal Workflow -> Move DAG -> Arbiter -> Herald`

### 9.3 Deed 与 Move

`Move` 是 `Design` 中的一个执行节点。
`Deed` 承载整次 DAG 执行。

每个 Move 通过 `sessions_send` 发送到池实例的主 session。OC 按 session key 串行化 runs，同 agent 的多个 Move 自然串行。不同 agent 的 Move 可并行（受 DAG 依赖约束）。

> 旧 `_consolidate_same_agent_moves()` 机制已废止（详见 `EXECUTION_MODEL.md` §1.2）。1 Move = 1 Agent + 1 交付物，不合并不拆分。

### 9.4 Review 与 rework

质量判断由 `Arbiter` 负责。

若不达标：

- 在本次 `Deed` 内触发 rework
- 超过 rework 限额则本次 `Deed` 失败

### 9.5 再执行一次

“再执行一次”不克隆新的 `Slip`。

它只是在同一张 `Slip` 下生出新的 `Deed`。

---

## 10. Herald、Offering、Vault、Feedback

### 10.1 Herald

`Herald` 只负责物流：

- 收拢结果
- 清理系统痕迹
- 落 `Offering`
- 写通知事件

它不做质量判断。

### 10.2 Offering

`Offering` 是给主人看的正式交付物。

它不应暴露：

- 内部 ID
- 工作流术语
- 运行痕迹

### 10.3 Vault

`Vault` 是内部归档和审计存储。

它与 `Offering` 分离。

### 10.4 Feedback 与评价链

反馈绑定 `Deed`。不存在独立的评价问卷或表单。

**评价链机制**（详见 `DESIGN_QA.md` Q7.5）：

评价以**运行周期**为单位。一段评价 = 一次运行开始到下一次运行开始之间的所有对话内容（包含 running 和 settling 两个阶段的对话）。评价链的头 = Slip 的「执行」按钮，尾 = 「收束」按钮。

**洗信息**在每个运行周期边界触发（机械提取，不用 LLM）：

- 压缩对话段 → 喂给下次运行的 Brief 补充（同时保留一份压缩结果）
- 客观数字 → `Ledger` 统计（rework 次数、时长、token 消耗）
- 关键词匹配 → Voice 候选（写入前须用户确认）

收束时串联所有运行周期的压缩结果，作为完整评价，写入 `dag_templates`（accepted Deed 的 DAG 模式合并）。

**操作-自然语言对应**：所有非对话操作（按钮、拖拽、姿态变更）在对话流中生成自然语言记录。Slash command 已取消。

所有洗出物流入系统前必须过 Instinct 代码门控。

---

## 11. Portal / Console / Telegram 映射

### 11.1 Portal

Portal 的核心对象是：

- `Draft`
- `Slip`
- `Folio`

公开路由：

- `/portal/`
- `/portal/slips/{slug}`
- `/portal/folios/{slug}`

Portal 的实现要求：

- `Slip` 页必须像内容对象页，而不是任务详情页
- `Folio` 页必须像卷页，而不是大号列表页
- 打开、返回、展开、收束采用 Apple 原生 app 式层级动态
- 入卷、出卷、成卷、吸附、重排采用文件系统式对象操作感
- 对象控制优先通过对话与直接操作表达，不靠按钮阵列

### 11.2 Console

Console 至少应提供以下正式面板：

- `总览`
- `卷`
- `签札`
- `行事`
- `成文`
- `例行`
- `踪迹`
- `模型`
- `随从`
- `技能`
- `配给`
- `系统`
- `词典`

Console 的实现要求：

- 列表 -> 详情 -> 子详情采用 Apple 原生 app 式层级动态
- 静态秩序保持 Claude 式克制，不做彩色后台
- 不把文件系统式对象拖拽作为主要治理方式
- Console 中看到的对象必须与 Portal 为同一现实

### 11.3 Telegram

Telegram 只承担：

- 通知
- 极简命令

不承担完整任务协作。

---

## 12. 存储与 API 规范

### 12.1 全局唯一 ID

正式对象均使用全局唯一 ID：

- `draft_id`
- `slip_id`
- `folio_id`
- `writ_id`
- `deed_id`

### 12.2 slug 规范

公开地址使用 `slug`：

- 标题允许重复
- `slug` 必须唯一
- 历史 `slug` 保留并重定向
- 旧 `slug` 不复用

### 12.3 状态目录

状态层建议按如下对象布局组织：

```text
state/
  drafts.json
  slips.json
  folios.json
  writs.json
  deeds.json
  portal_slugs.json
  deeds/
    {deed_id}/
      design.json
      moves/
      feedback/
  psyche/
  events.jsonl
  spine_log.jsonl
  system_status.json
```

### 12.4 对象 API

内部 canonical API 以英文对象名命名：

- `/drafts`
- `/slips`
- `/folios`
- `/writs`
- `/deeds`
- `/offerings`
- `/system/*`

Console API 也使用英文 canonical paths；界面显示中文。

### 12.5 Storage roots

`Offering` 与 `Vault` 根目录由绝对路径配置决定。

系统不再通过“目录名”推导根路径。

---

## 13. 删除原则

一旦新对象模型落地：

- 旧命名壳
- 旧路由壳
- 旧文案壳
- 旧对象分层壳
- 旧任务分类壳

都必须被删除，不留“以后再说”的双轨残留。

---

## 14. 暖机与就绪

暖机阶段的目标只有三类：

1. 校准单 `Slip` 上限与默认执行基线
2. 校准 `Writ` 的命中与 suppress 规则
3. 校准 `Slip` 规划学习与反馈回流

暖机不改变机制结构，只校准参数。

---

## 15. 当前正式结论

从本文件起，Daemon 的正式事项机制就是：

`Draft -> Slip -> Deed`

以及：

`Folio` 收纳 `Slip`，`Writ` 响应事件并决定 `Draft / Slip / Deed / Folio` 如何生发与接续。

并应成为后续实现、交互、审计的唯一依据。
