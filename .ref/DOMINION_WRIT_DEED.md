# Dominion-Writ-Deed 机制设计

> 本文档定义 daemon 的任务组织核心层：Dominion-Writ-Deed 三级结构。
> 状态：已定稿。
>
> **术语说明：** Dominion / Writ / Deed 均为系统内部术语（代码/日志/Console）。
> 用户界面术语见 TERMINOLOGY.md 的映射表。
>
> **不可见原则：** Dominion-Writ-Deed 及其所有内部机制对终端用户不可见。用户通过自然语言看到进展和结果，不接触 Dominion/Writ/Deed 等系统概念。Console（运维视图）可展示内部结构，Portal/Telegram（用户视图）只呈现自然语言。

---

## 一、核心概念

### 1.1 Dominion — 主题容器

Dominion 是一个长期目标或主题的容器。类比 Claude/ChatGPT 的 Project：为一组相关工作提供统一上下文。

**关键特性：**
- Deed 可以独立存在，不属于任何 Dominion
- Deed 也可以归属于某个 Dominion，共享该 Dominion 的主题上下文
- Dominion 不只是被动分组——它可以主动控制其下 Deed 的执行
- Dominion 的生命周期长于单个 Deed，可能持续数周甚至更久

**Dominion metadata：**
- dominion_id
- objective（主题/目标描述）
- status（active / paused / completed / abandoned）
- writs（所属 Writ 列表）
- max_concurrent_deeds（可配置，默认 6）
- max_writs（可配置，默认 8）
- instinct_overrides（dict，可选，覆写全局 Instinct 偏好）
- created_utc / updated_utc
- progress_notes

### 1.2 Writ — 工作线

Writ 是 Dominion 内的一条独立工作线。它定义了 Deed 的生成规则和 Deed 之间的因果关系。

**关键特性：**
- 一条 Writ 可以承载定时触发的周期性 Deed（如：每周监控某个领域动态）
- 一条 Writ 可以承载有因果承接关系的一组 Deed（如：收集 → 分析 → 产出）
- Writ 之间在运行层面互不影响，可以独立增删。管理层面，有拆合关系的 Writ 遵循 DAG 级联规则（见 §7.1）
- 同一 Dominion 下的多条 Writ 共享 Dominion 的主题上下文
- Writ 是活的——可以随 Dominion 推进动态拆分或合并

**Writ 的拆合示例：**
- 拆分：一条"监控 async 生态"的 Writ → 拆成"跟踪 tokio"、"跟踪 io_uring RFC"、"跟踪社区讨论"三条
- 合并：两条分别收集 Calico 和 Cilium 资料的 Writ → 合成"CNI 方案对比跟踪"

**Writ metadata：**
- writ_id
- dominion_id（所属 Dominion）
- label（描述）
- status（active / paused / disabled）
- brief_template（Deed 生成模板）
- trigger（触发规则）
- max_pending_deeds（默认 3）
- deed_history（该 Writ 产生的 Deed 列表）
- split_from（str，可选，拆分来源 Writ ID）
- merged_from（list[str]，可选，合并来源 Writ ID 列表）
- created_utc / updated_utc

### 1.3 Deed — 执行实例

Deed 是具体的任务执行实例。每个 Deed 是一次完整的 submit → design → execute → deliver 流程。

**Deed 的来源：**
- 用户直接提交（可归属 Dominion，也可独立）
- Writ 定时触发
- Writ 因果承接（前一个 Deed 完成后自动触发）
- 系统主动发起（daemon 判断 Dominion 需要更新）
- 用户追问（相关问题归入 Dominion）

**Deed 与 Dominion 的关系：**
- Deed 可以不属于任何 Dominion（独立 Deed）
- Deed 可以属于某个 Dominion 但不属于特定 Writ（用户临时追问）
- Deed 可以属于 Dominion 下某条 Writ（按规则生成的 Deed）

---

## 二、结构关系

```
Dominion (主题容器)
├── Writ A: 周期性监控（每周触发一个 Deed）
│   ├── Deed 1 (week 1)
│   ├── Deed 2 (week 2)
│   └── ...
├── Writ B: 研究流程（因果串联）
│   ├── Deed 3: 收集资料
│   ├── Deed 4: 深度分析（依赖 Deed 3）
│   └── Deed 5: 生成报告（依赖 Deed 4）
├── Writ C: 技术验证
│   └── Deed 6: 搭建 benchmark 环境
└── (unassigned deeds)
    └── Deed 7: 用户临时追问
```

独立 Deed（不属于任何 Dominion）：
```
Deed 8: 用户发起的一次性任务
Deed 9: 快速查询
```

---

## 三、Writ 的触发机制

Writ 的触发统一为**事件订阅**。Writ 订阅 Nerve 事件，事件到达时生成新 Deed。

没有 trigger "类型"的枚举——所有触发都是事件，只是事件的来源不同：

### 3.1 统一事件模型

所有触发归结为 Writ 订阅一个 Nerve 事件名 + 可选过滤条件：

```json
{
  "trigger": {
    "event": "cadence.tick",
    "filter": {"cron": "0 9 * * 1", "tz": "Asia/Shanghai"}
  }
}
```

```json
{
  "trigger": {
    "event": "deed_completed",
    "filter": {"writ_id": "writ_id_xxx"}
  }
}
```

```json
{
  "trigger": {
    "event": "user.manual_trigger",
    "filter": {"writ_id": "self"}
  }
}
```

### 3.2 事件来源

| 事件来源 | 说明 | 示例事件名 |
|---------|------|-----------|
| Cadence | 定时器 tick 产生的时间事件 | `cadence.tick` |
| Deed 生命周期 | Deed 完成/失败等状态变化 | `deed_completed`, `deed_failed` |
| 外部 Adapter | 外部信号（邮件/webhook 等）经 adapter 归一化 | `external.email_received` |
| 用户操作 | 用户在 Portal/Telegram 触发 | `user.manual_trigger` |
| 系统内部 | daemon 自身判断（witness 发现等） | `system.dominion_needs_update` |

cron 不是触发"类型"——它是 Cadence 根据 cron 表达式定时产生 `cadence.tick` 事件，Writ 订阅这个事件。

**cron 匹配机制：** Cadence 每分钟 tick 一次，评估所有注册的 cron 表达式。匹配的 cron 发出 `cadence.tick` 事件，payload 带上匹配的 cron 表达式（如 `{cron: "0 9 * * 1", tz: "Asia/Shanghai"}`）。Writ 的 filter 做简单等值比较。cron 评估是 Cadence 的职责，filter 系统保持通用。Writ 创建/更新时向 Cadence 注册 cron，删除/暂停时注销。

### 3.3 Deed 生成

事件到达且过滤条件匹配时，Writ 使用 `brief_template` 生成新的 Brief，经 Will 进入执行流程。每次生成可以利用最新的 Lore 经验和前序 Deed 的产出。

**模板填充职责：** dominion_writ.py 负责填充。它有 Writ 上下文（模板、dominion_id、deed_history），查 Psyche（Memory/Lore）拿动态数据，填完后产出完整 Brief 交给 Will。Will 收到完整 Brief，不关心来源是用户提交还是 Writ 触发。组织层准备，执行层处理。

### 3.4 循环保护

Writ 订阅 `deed_completed` 时存在自循环风险：Writ A 产生的 Deed 完成后发出 `deed_completed` 事件，如果 Writ A 自己的 filter 匹配该事件，则再次触发，形成无限循环。

**保护规则：** 事件的 `writ_id`（产生该 Deed 的 Writ）等于订阅方 Writ 自身时，跳过。触发入口处检查，一条规则阻断自循环。

### 3.5 事件规范

**标准 payload 字段：**

| 事件 | payload 字段 |
|------|-------------|
| `deed_completed` / `deed_failed` | deed_id, dominion_id, writ_id, status, emitted_at |
| `cadence.tick` | cron, tz, emitted_at |
| `user.manual_trigger` | writ_id, emitted_at |
| `external.*` | adapter 自定义字段 + emitted_at |

**跨进程事件流：** API 进程（Nerve）和 Worker 进程（Temporal）不直接通信，通过共享文件系统协作。Deed 完成时的事件路径：Worker 完成 Deed → 写最终状态到 state/ → API 侧 Cadence 轮询检测状态变化 → 发 `deed_completed` 到 Nerve。几秒延迟可接受。

---

## 四、Dominion 的控制能力

Dominion 不只是分组，它具备对 Deed 的控制权：

### 4.1 已确认的控制能力

- **暂停/恢复**：暂停 Dominion 会暂停其下所有 Writ 的触发
- **上下文注入**：Dominion 的主题上下文会注入到其下所有 Deed 的执行中

### 4.2 资源限制

每一层设限制，不建调度器。限制在入口处检查，执行交给已有机制（Retinue 分配 + Temporal 调度）。

**系统级：**

| 限制 | 默认值 | 说明 |
|------|--------|------|
| retinue_size | 24 | 最大并发 Deed 数（已有） |
| reserved_independent_slots | 4 | 为独立 Deed 保留的 Retinue 槽位，无论 Dominion 多忙都保障 |

**Dominion 级（per Dominion，可配置）：**

| 限制 | 默认值 | 说明 |
|------|--------|------|
| max_concurrent_deeds | 6 | 单个 Dominion 最多同时运行的 Deed 数，防止单 Dominion 垄断 Retinue |
| max_writs | 8 | 单个 Dominion 最多活跃 Writ 数，限制 Deed 生成源 |

**Writ 级：**

| 限制 | 默认值 | 说明 |
|------|--------|------|
| max_pending_deeds | 3 | 单条 Writ 最多积压待执行 Deed 数，到达上限暂停触发 |

**执行优先级：** retinue_size 是硬天花板 → reserved_independent_slots 优先保障 → 各 Dominion 在剩余容量内按 max_concurrent_deeds 竞争。Deed 到 Retinue 先到先得，Retinue 满则排队。

**不需要跨 Dominion 调度器。** 限制本身保证公平性（无单 Dominion 垄断）。Deed 内部的 subagent 并发由 Temporal 管理，不需要自己调度。

### 4.3 其他控制能力

**Dominion 终止时的 Deed 处理：** 已运行的 Deed 继续完成（不杀进行中的工作）。暂停所有 Writ 的新触发。用户可以显式取消正在运行的 Deed，但系统不自动取消。

**Dominion 之间的依赖：** 不支持。Dominion 是独立的组织单元。如果两个 Dominion 有关联，用户自行管理或合并为一个 Dominion。保持简单。

**progress_notes 自动更新：** witness routine（Spine）在每个 Deed 完成后审视产出，为所属 Dominion 追加 progress note。这复用现有 Spine 机制，不需要新组件。

---

## 五、与现有系统的关系

### 5.1 Endeavor 与 Dominion-Writ-Deed

Endeavor 是**单个 Deed 内部的多阶段执行**（一个 Temporal workflow 内的多 Passage）。
Writ 的因果串联是**不同 Deed 之间的串联**（不同 workflow 之间）。

两者不重叠：
- Endeavor = Deed 内部结构
- Writ = Deed 之间结构

### 5.2 废弃概念

| 废弃概念 | 原本用途 | 替代 |
|---------|---------|------|
| Circuit | 独立定期任务 | Writ（订阅 `cadence.tick` 事件） |
| chain / chain_id | 任务串联 | Writ（订阅 `deed_completed` 事件） |

### 5.3 不变的部分

- Deed 的内部执行机制不变（Design → Moves → DAG → Temporal workflow）
- Will 管线不变
- Agent 角色和 Retinue 机制不变
- Herald 机制不变

---

## 六、与其他层的集成

**核心原则：Dominion-Writ-Deed 是组织层，不是执行层。** 所有集成方式都是给现有机制加 `dominion_id` / `writ_id` 维度，不发明新机制。

### 6.1 Psyche 层

**Memory Dominion-scoped 查询：** Memory 查询增加 `dominion_id` 过滤维度。同一 Dominion 下积累的知识自动注入该 Dominion 后续 Deed，不污染其他 Dominion。独立 Deed 查全局 Memory。不需要新存储结构——现有 Memory 条目加 `dominion_id` 标签即可。

**Lore 按 Dominion 聚合：** Lore 经验条目携带 `dominion_id`。brief_template 填充时，优先取同 Dominion 的经验，其次取全局经验。这是查询优先级，不是隔离——跨 Dominion 的通用经验仍然可用。

**Instinct Dominion-level 覆写：** Dominion 可以携带局部偏好覆写（如 `output_languages: ["en"]`）。优先级：Dominion 覆写 > 全局 Instinct。不设覆写则用全局。类似 CSS specificity，不需要新机制。

### 6.2 Will / Planning 层

**上下文自然流动：** brief_template 填充时，Dominion objective + Writ 前序 Deed 产出作为动态数据注入。这就是第三节 3.3 描述的"利用前序 Deed 产出"——不需要额外的"传参"机制，模板填充本身就是上下文传递。

**复杂度估计：** Will 估算新 Deed 复杂度时，可参考同 Writ 历史 Deed 的实际复杂度。如果这条 Writ 前 5 个 Deed 都是 charge 级，下一个大概率也是。这是 Lore 查询加了 Writ 维度，不是新逻辑。

### 6.3 Review / Quality 层

**Dominion 级质量趋势：** Witness 在 Deed 完成后审视产出时，额外看同 Dominion 的历史质量轨迹。质量是在上升还是下降？这为 progress_notes 提供依据。复用现有 witness 机制，增加聚合视角。

**Review 侧重可配置：** 通过 Instinct Dominion-level 覆写实现。研究 Dominion 可以 `review_emphasis: "depth"`，监控 Dominion 可以 `review_emphasis: "timeliness"`。Arbiter agent 从 Instinct 读取侧重，不需要 review 机制本身改动。

### 6.4 Herald 层

**Offerings 按 Dominion 组织：** herald_log.jsonl 条目已有 deed_id，加 dominion_id 字段。Portal 按 Dominion 分组展示。Herald 机制不变——它只是搬运，多带一个标签。

**Dominion 阶段性汇总：** 不需要 Herald 层做这件事。这本身就是一个 Deed——一条 Writ 订阅 `deed_completed` 事件，定期生成"Dominion 进展摘要"。用机制自身解决机制的需求。

### 6.5 Spine / Witness 层

**Dominion objective 进展评估：** Witness 已在每个 Deed 完成后运行。增加的逻辑：如果 Deed 属于某 Dominion，审视其产出与 Dominion objective 的关系，更新 progress_notes。如果发现 objective 似乎已达成，提醒用户确认。这是 witness routine 的自然扩展。

**Focus 优先级：** Focus routine 决定下一步关注什么时，活跃 Dominion 的紧迫性是一个信号。多个 Dominion 活跃时，哪个更需要推进？Focus 可以基于 Dominion 的 progress_notes 和最近活动时间判断。

### 6.6 Agent 上下文注入

**执行时上下文：** `_build_move_context`（activities_exec.py）构建 Move 执行上下文时，如果 Deed 属于某 Dominion，注入：Dominion objective、Writ label、前序 Deed 的关键产出摘要。Agent 因此知道：自己在做什么（Move instruction）、为什么做（Dominion objective）、之前做到了哪里（前序产出）。

---

## 七、设计决策

### 7.1 Writ 的数据模型

**拆分/合并时的 Deed 历史：** Deed 历史留在原 Writ（保持历史准确性）。新 Writ 从零开始。在新 Writ 的 metadata 中标记来源关系（`split_from` / `merged_from`），保留可追溯性，但不迁移 Deed 记录。

**Writ 之间的依赖声明：** 通过事件订阅自然表达。Writ B 订阅 `deed_completed` + `filter: {writ_id: "writ_a_id"}` 就构成了对 Writ A 的依赖。不需要额外的 `depends_on` 字段——事件订阅本身就是依赖声明。

**brief_template 的性质：** 模板 + 变量填充。模板定义任务骨架（prompt、complexity、depth 等），触发时填入动态数据（前序 Deed 产出、最新 Lore 经验、当前时间上下文）。不是冻结的静态配置——否则无法利用系统学到的经验。

**Writ 关系结构 = DAG：** `split_from` 是单值（一个父节点），`merged_from` 是列表（多个父节点）。仅有 split 时结构为树（forest），引入 merge 后成为 DAG（有向无环图）。实际使用中 merge 节点很少，绝大多数操作等同于树操作。

**级联操作规则：** 禁用一条 Writ 时，其子 Writ 按以下规则级联：
- 普通子节点（`split_from` 指向被禁用 Writ）：自动级联禁用
- merge 节点（`merged_from` 包含被禁用 Writ）：仅当其所有 `merged_from` 来源 Writ 都已禁用时才级联禁用；部分来源仍活跃时，merge 节点保持当前状态

max_writs=8 的规模下，DAG 遍历直接递归即可，不需要图算法库。

### 7.2 Dominion-Writ-Deed 的生命周期管理

用户不接触 Dominion/Writ/Deed 概念（不可见原则）。所有结构的创建和调整由系统内部完成，用户通过自然语言表达意图。

**Dominion 创建：** 用户表达长期意图（如"帮我持续跟踪 Rust async 生态"）→ counsel 识别为长期目标 → 内部创建 Dominion。或 witness 发现用户近期多次提交同主题任务 → 用自然语言建议"我注意到你在持续关注 X，要不要帮你长期跟踪？" → 用户确认意图 → 内部创建 Dominion。用户确认的是意图，不是"创建 Dominion"这个操作。

**Writ 生成：** Dominion 创建后，counsel 分析 objective → 分解为工作线 → 内部创建 Writ 并配置触发规则和 brief_template。用户说"也帮我关注一下社区讨论" → 系统新增一条 Writ。用户说"tokio 那条不用跟了" → 系统 disable 对应 Writ。

**Writ DAG 调整：** Dominion-Writ-Deed 结构是活的 DAG，随项目推进持续调整。witness 观察到某条 Writ 产出越来越杂 → 建议拆分（用自然语言告知用户）→ 内部执行 split。用户说"把这两个方向合在一起看" → 内部执行 merge。所有 DAG 操作（split、merge、disable 及其级联）对用户不可见。

**Dominion 完成：** witness 检测到 objective 似乎已达成 → 用自然语言提醒用户确认 → 用户确认 → 内部标记 completed/abandoned。用户有最终决定权，但不直接操作 Dominion 状态。

**常驻 Dominion：** 不需要特殊机制。一个 status=active 的 Dominion 配合持续运行的 Writ（如 cron 触发）自然形成常驻效果。自进化 Dominion 就是一个普通 Dominion，只是 Writ 的生命周期很长。

### 7.3 Deed 归属

**归属决策：** counsel 在处理用户消息时，根据语义相似度判断是否归入某个活跃 Dominion。归属在内部完成，用户不感知"归属"操作。默认 = 独立 Deed（不归属任何 Dominion）。

**事后移动：** 允许。Dominion 是组织层，不是执行层。移动 Deed 不改变其执行历史和产出，只改变组织归属。

### 7.4 代码重构范围

已完成：
- `services/api_routes/circuits.py` — 已删除
- `services/cadence.py` — Circuit 代码已清除
- `TERMINOLOGY.md` — Circuit 已删除，Writ 定义已修正
- Console/Portal — Strategy 面板、Semantics 管理、Circuit UI 全部清除

待实施：
- `services/dominion_writ.py` — Writ 重写（工作线模型，非触发器模型）
- `services/api_routes/dominions.py` — Writ API 重新设计

---

## 修订记录

| 日期 | 内容 |
|------|------|
| 2026-03-08 | 初稿：基于设计讨论建立，核心概念对齐。第六节提案待用户确认 |
| 2026-03-08 | 修正：触发机制统一为事件订阅（非枚举类型）；标注系统术语与用户术语分离 |
| 2026-03-08 | 新增第六节：与其他层的集成（Psyche/Will/Review/Herald/Spine/Agent 上下文） |
| 2026-03-08 | §7.4 更新已完成/待实施清单；全系统废弃代码清理（Circuit/Strategy/Semantics） |
| 2026-03-08 | §4.2 资源限制确认：系统/Dominion/Writ 三级限制，设限制不建调度器；原"预算/资源上限暂不做"移除 |
| 2026-03-08 | §3.4 新增循环保护：Writ 不消费由自身产生的 Deed 完成事件 |
| 2026-03-08 | 全文定稿：§4.3/§6/§7 提案全部确认；§1.1 加 instinct_overrides；§3.2 加 cron 匹配机制；§3.3 加模板填充职责；§3.5 新增事件规范（payload + 跨进程流） |
| 2026-03-08 | §7.1 新增 Writ DAG 结构定义及级联操作规则；§1.2 明确 split_from/merged_from 数据类型；头部加不可见原则 |
| 2026-03-08 | §7.2 重写为完整生命周期管理：Dominion/Writ/Deed 的创建和调整全部由系统内部完成，用户通过自然语言表达意图；§7.3 归属决策改为 counsel 内部判断 |
| 2026-03-09 | 全文术语更新：Track→Dominion, Lane→Writ, Run→Deed, 及所有相关派生术语（详见 TERMINOLOGY.md） |
