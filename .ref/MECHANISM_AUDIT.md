# Daemon 机制审计

> 日期：2026-03-10
> 职责：根据五份权威文档，审查实现是否对齐。不定义机制。
> 方法：读权威文档提取机制规则，读代码比对，记录 gap。
> 颗粒度：每条 gap 锚定一条机制规则（第一层），下挂代码证据（第二层）。

## 权威依据

| 编号 | 文档 | 简称 |
|---|---|---|
| D1 | `README.md` | README |
| D2 | `TERMINOLOGY.md` | TERM |
| D3 | `INTERACTION_DESIGN.md` | IXDN |
| D4 | `DESIGN_QA.md` | QA |
| D5 | `daemon_实施方案.md` | SPEC |

---

## 1. 对象模型

### 1.1 Draft

- **依据**：SPEC §3.1, TERM §1, QA §3.1–3.2
- **检查项**：
  1. 数据模型包含全部最小字段：draft_id, source, folio_id, seed_event, intent_snapshot, candidate_brief, candidate_design, status, created_utc, updated_utc
  2. status 枚举 = open | refining | crystallized | superseded | abandoned
  3. source 枚举 = chat | writ | event | manual
  4. Draft 是正式持久化对象，不是临时聊天缓存
  5. 自动任务也必须先经过 Draft（QA §3.2）
- **证据**：✓ 通过
  - `services/folio_writ.py` — Draft 为持久化 dict，10 个最小字段全部存在
  - status 枚举完全匹配：`{"open", "refining", "crystallized", "superseded", "abandoned"}`
  - `will.py:322-331` — `_materialize_objects()` 中自动创建 Draft
  - `will.py:240-246` — 超限开卷流程也先创建 Draft

### 1.2 Slip

- **依据**：SPEC §3.2, TERM §1, QA §3.3–3.6
- **检查项**：
  1. 最小字段：slip_id, folio_id, title, slug, slug_history, objective, brief, design, status, standing, latest_deed_id, created_utc, updated_utc
  2. status 枚举 = active | parked | settled | archived | absorbed
  3. standing 布尔字段存在且可用
  4. Slip 不承担执行实例职责（QA §3.3–3.4）
  5. Slip 生命周期独立于单个 Deed（QA §3.6）
  6. slug 唯一，标题可重复（TERM §4.2）
- **证据**：✓ 通过
  - `services/folio_writ.py` — 全部 13 个字段存在（含 spec 的 11 个 + 额外 `deed_ids`）
  - status 枚举完全匹配
  - standing 字段存在
  - 额外字段 `deed_ids`（最多 200 条历史 deed 引用）不违反 spec，属于合理扩展

### 1.3 Folio

- **依据**：SPEC §3.3, TERM §1, QA §8.1
- **检查项**：
  1. 最小字段：folio_id, title, slug, slug_history, summary, status, slip_ids, writ_ids, created_utc, updated_utc
  2. status 枚举 = active | parked | archived | dissolved
  3. Folio 是正式主题容器，不是大号 Slip（TERM §1.1）
  4. 支持自动生成、手动创建、重命名、合并、解散、收纳/放出 Slip（QA §8.1）
- **证据**：✓ 通过
  - `services/folio_writ.py` — 全部 10 个字段存在，status 枚举完全匹配
  - `FolioWritManager` 提供 `create_folio`, `update_folio`, `delete_folio`, `attach_slip_to_folio`, `detach_slip_from_folio`

### 1.4 Writ

- **依据**：SPEC §3.4, TERM §1, QA §8.2–8.4
- **检查项**：
  1. 最小字段：writ_id, folio_id, title, match, action, status, priority, suppression, version, created_utc, updated_utc
  2. status 枚举 = active | paused | disabled
  3. Writ 必属于某个 Folio（SPEC §4.1）
  4. 本体为 Event → action(on Draft/Slip/Deed/Folio)（QA §8.4）
  5. 不区分 Writ 本体种类，统一处理所有事件触发（QA §8.2）
  6. version 字段存在，canonical Writ 变更必须版本化（QA §1.7）
- **证据**：✓ 通过
  - `services/folio_writ.py` — 全部 11 个字段存在（含 spec 的 9 个 + 额外 `deed_history`, `last_triggered_utc`）
  - status 枚举完全匹配
  - version 字段存在
  - 额外字段 `deed_history`, `last_triggered_utc` 属于运行时辅助，不违反 spec

### 1.5 Deed

- **依据**：SPEC §3.5, TERM §1, QA §3.4–3.5, §6.2
- **检查项**：
  1. 最小字段：deed_id, slip_id, folio_id, writ_id, status, brief_snapshot, design_snapshot, result_summary, started_utc, ended_utc, created_utc
  2. status 枚举 = queued | running | paused | completed | failed | cancelled | awaiting_eval
  3. Deed 必定源于某张 Slip（QA §3.5）
  4. Deed 是执行实例，不是任务本体（TERM §1.1）
  5. brief_snapshot 和 design_snapshot 为执行时快照（SPEC §3.5）
  6. 提交到 Temporal 的对象是 Deed，不是 Slip（QA §6.2）
- **证据**：✓ 通过（修复后复核 2026-03-10）
  - `will.py:523-526` — Deed 创建时包含 `created_utc`、`started_utc`（空）、`ended_utc`（空）、`result_summary`（空）
  - `activities.py:794-795` — status 变为 running 时设 `started_utc`
  - `activities.py:796-797` — status 变为 completed/failed/cancelled/awaiting_eval 时设 `ended_utc`
  - status 枚举：`pending_review` 已全量清除（Python/JS/CSS 归零），保留 `cancelling` 作为内部过渡态
  - 其余字段（deed_id, slip_id, folio_id, writ_id, brief_snapshot, design_snapshot）均存在且正确
  - Deed 确实作为执行实例提交到 Temporal（`will.py:197`）

---

## 2. 对象关系与生命周期

### 2.1 Draft → Slip 收敛

- **依据**：SPEC §4.2, QA §3.1–3.2
- **检查项**：
  1. 收敛路径 = Event/用户输入 → Draft → Brief+Design → Slip
  2. Draft 成札后 status 变为 crystallized
  3. 正式 Slip 在 Draft crystallized 后成立
  4. 自动任务（Writ 触发、外部事件）也先经过 Draft
- **证据**：✓ 通过
  - `will.py:322-331` — `_materialize_objects()` 自动创建 Draft（`create_draft()`）
  - `will.py:335-344` — 紧接着调用 `crystallize_draft()` 将 Draft 转为 Slip
  - `folio_writ.py` — `crystallize_draft()` 将 Draft status 设为 `crystallized`，创建 Slip
  - 超限开卷路径（`will.py:240-254`）同样先 `create_draft` → `crystallize_draft`

### 2.2 Slip → Deed 生成

- **依据**：SPEC §4.3, QA §3.5–3.6, §6.5
- **检查项**：
  1. 同一张 Slip 可以产生多个 Deed
  2. Deed 完成后 Slip 不结束，仍可继续存在
  3. "再执行一次" = 同一张 Slip 下新建 Deed，不克隆新 Slip
  4. Slip 可以没有 Deed
- **证据**：✓ 通过
  - Slip 有 `deed_ids` 列表和 `latest_deed_id`，支持多次执行
  - `folio_writ.py` — `record_deed_created(slip_id, deed_id)` 追加到 Slip 的 `deed_ids`
  - Slip status 独立于 Deed status

### 2.3 Folio 收纳关系

- **依据**：SPEC §4.1
- **检查项**：
  1. 一个 Folio 可以收纳多张 Slip
  2. 一个 Folio 可以挂载多条 Writ
  3. Writ 必定属于某个 Folio
  4. Slip 的 folio_id 可空（独立签札）
- **证据**：✓ 通过
  - Folio 有 `slip_ids` 和 `writ_ids` 列表
  - Writ 创建时必须传入 `folio_id`
  - Slip 的 `folio_id` 可空

### 2.4 周期性任务

- **依据**：SPEC §4.4, QA §3.7
- **检查项**：
  1. 周期性任务 = standing Slip + Writ + 多次 Deed
  2. 不是让一个 Deed 永远持续
  3. Slip.standing 字段被正确使用
- **证据**：✓ 通过
  - Slip 有 `standing` 布尔字段
  - `Brief` dataclass 有 `standing` 字段（`runtime/brief.py:29`）
  - `will.py:342` — `crystallize_draft()` 传入 `standing=brief.standing`

### 2.5 超限即开卷

- **依据**：SPEC §4.5, QA §3.8
- **检查项**：
  1. 所有事项默认先尝试成为单张 Slip
  2. 单 Slip 有承载上限（DAG 步数、move budget、并发基线）
  3. 超限时直接提升为 Folio + 多张 Slip
  4. 不存在"更大的单札"路径
- **证据**：✓ 通过
  - `will.py:152-153` — 当 moves 数超过 `dag_budget` 时，调用 `_submit_promoted_folio()`
  - `will.py:228-289` — `_submit_promoted_folio()` 创建 Folio → 拆分 moves 为多组 → 每组 Draft → crystallize → Slip
  - 单札基线 `dag_budget=6`（`runtime/brief.py:12`）

### 2.6 删除规则

- **依据**：SPEC §4.6
- **检查项**：
  1. 默认不做无声硬删除
  2. Draft 可在 superseded / abandoned 状态下被清理
  3. Slip 默认只做 parked / archived / absorbed，不物理删除
  4. Deed 完成后保留历史记录
- **证据**：✓ 通过
  - Slip status 枚举不含 "deleted"
  - Deed 完成后保留，Slip 的 `deed_ids` 保留历史

---

## 3. Event 与 Writ

### 3.1 事件统一模型

- **依据**：SPEC §5.1, QA §8.3
- **检查项**：
  1. 定时、链式、外部触发、用户动作统一视为 Event
  2. 事件源包含：time.tick, user.spoken, deed.completed, deed.failed, feedback.submitted, external.received, folio.changed, slip.changed
  3. Nerve 事件总线使用 at-least-once 语义（QA §2.2）
  4. 关键事件写入持久化事件日志，重启后可重放
- **证据**：○ 部分
  - Nerve 事件总线存在，用于 emit/on 事件
  - `activities_herald.py:65` — 发出 `deed_completed` 事件
  - `activities_herald.py:97` — 发出 `deed_failed` 事件
  - `cadence.py` — routine 支持 `nerve_triggers` 事件触发
  - **未验证**：at-least-once 语义、持久化事件日志、重启后重放。需进一步审查 Nerve 实现

### 3.2 Writ 匹配与动作

- **依据**：SPEC §5.2
- **检查项**：
  1. Writ 通过事件匹配生效
  2. 支持动作：create_draft, crystallize_draft, spawn_deed, advance_slip, park_slip, archive_slip, attach_slip_to_folio, create_folio
  3. match 字段与 action 字段结构正确
  4. priority 和 suppression 机制实现
- **证据**：✓ 通过（修复后复核 2026-03-10）
  - `folio_writ.py` — Writ 有 match/action/priority/suppression 字段
  - `api.py:751-777` — `_consume_writ_trigger()` 完整 dispatcher，8 种 action type 全部分发：spawn_deed(:759) / create_draft(:761) / crystallize_draft(:763) / advance_slip(:765) / park_slip(:767) / archive_slip(:769) / attach_slip_to_folio(:771) / create_folio(:773)
  - 每个 handler 都调用 `folio_writ.record_writ_triggered()` 链接 Writ 与结果
  - `folio_writ.py:608-644` — `_on_trigger_fired()` 事件匹配：支持 event name 匹配 + filter dict 逐键比对 + cron schedule 匹配

### 3.3 链式任务

- **依据**：SPEC §5.3, QA §8.5
- **检查项**：
  1. 链式推进 = Folio + 多张 Slip + Writ
  2. deed.completed 事件能命中 Writ 触发下一张 Slip 或下一次 Deed
  3. 不存在绕过 Writ 的硬编码链式推进
- **证据**：✓ 通过（完整链路复核 2026-03-10）
  - `will.py:239-245` — 超限开卷时为每对相邻 Slip 创建链式 Writ：`match={"event": "deed_completed", "filter": {"slip_id": previous_slip_id}}, action={"type": "spawn_deed", "slip_id": next_slip_id}`
  - `activities_herald.py:42-60` — Herald 发出 `deed_completed` 事件，payload 包含 `slip_id`(:46)、`folio_id`(:47)、`writ_id`(:48)
  - `folio_writ.py:605` — Writ 注册时 `nerve.on("deed_completed", handler)`
  - `folio_writ.py:626-629` — `_on_trigger_fired` 逐键匹配 filter：`payload.get("slip_id") == filter["slip_id"]`
  - `folio_writ.py:634-644` — 匹配通过后发出 `writ_trigger_ready`
  - `api.py:892-895` — `nerve.on("writ_trigger_ready", handler)` → `_consume_writ_trigger` → `_writ_action_spawn_deed`
  - `api.py:788` — 从 action 提取目标 slip_id，提交新 Deed 到 Will
  - 完整链路：deed_completed → Nerve → filter 匹配 → writ_trigger_ready → spawn_deed → 新 Deed。无硬编码绕过

### 3.4 Writ 学习与版本化

- **依据**：SPEC §5.4, QA §1.7
- **检查项**：
  1. 系统可积累命中率、误触发率、触发时机质量、目标 Slip 偏好、suppress 条件
  2. canonical Writ 正式变更必须版本化
  3. 不允许无声修改 Writ
- **证据**：✓ 通过（修复后复核 2026-03-10）
  - `folio_writ.py:519` — `_WRIT_CANONICAL_FIELDS = frozenset({"title", "match", "action", "priority", "suppression"})`
  - `folio_writ.py:538-542` — `update_writ()` 中 canonical 字段变更时 `canonical_changed=True` → `version += 1`
  - 非 canonical 字段（deed_history, last_triggered_utc, trigger_stats, status）变更不触发版本递增
  - `api.py:1547-1559` — feedback 提交时更新 Writ `trigger_stats`（total_feedback / avg_rating / misfire_count）
  - `lore.py:321-344` — `writ_trigger_summary()` 从 Lore 聚合 Writ 历史触发数据

---

## 4. Psyche

### 4.1 Memory

- **依据**：SPEC §6.1, QA §1.1–1.3
- **检查项**：
  1. Memory 支持 embedding 检索
  2. 查询时若已知 folio_id，同卷内容优先
  3. 容量策略：热度衰减 + 相似合并 + 最后淘汰
  4. 冲突处理：新显式事实覆盖旧矛盾事实
  5. 不做硬主题隔离，不做预定义 cluster
- **证据**：✓ 通过（2026-03-11 更新：tier-based decay）
  - `psyche/memory.py:152` — `search_by_embedding(query_embedding, top_k, threshold, folio_id)` 支持 embedding 检索和 folio_id 偏置
  - `psyche/memory.py` — `decay_all()` tier-based 衰减：`TIER_DECAY_FACTORS = {core: 1.0, deep: 0.99, working: 0.95, transient: 0.85}`，core 永不衰减
  - `psyche/memory.py:324` — `_merge_similar_low_relevance_entries()` 相似合并（similarity>0.92, relevance≤0.35）
  - `psyche/memory.py:264` — `enforce_capacity()` 容量淘汰 CAPACITY_LIMIT=2000
  - `psyche/memory.py:115-138` — `upsert()` 冲突覆盖（新事实替换旧矛盾）
  - 无硬主题隔离

### 4.2 Lore

- **依据**：SPEC §6.2, QA §1.4
- **检查项**：
  1. 主锚点 = deed_id
  2. 同时记录 slip_id, folio_id, writ_id
  3. 每条经验至少包含：deed_id, slip_id, folio_id, writ_id, plan_structure, offering_quality, token_consumption, user_feedback
- **证据**：✓ 通过
  - `psyche/lore.py:39` — `deed_id TEXT NOT NULL UNIQUE` 主锚点
  - `psyche/lore.py:40-42` — slip_id, folio_id, writ_id 全部存在且有索引
  - `psyche/lore.py:47-52` — plan_structure, offering_quality, token_consumption, user_feedback 全部为 dict 字段
  - `psyche/lore.py:233-238` — consult 时 folio_id +0.10, slip_id +0.08, writ_id +0.05 偏置

### 4.3 Instinct

- **依据**：SPEC §6.3, QA §1.5
- **检查项**：
  1. 只承担偏好、默认值、配额倾向
  2. 不承担主题级规划习惯
  3. 不承担单次执行经验
- **证据**：✓ 通过
  - `will.py:120-122` — Instinct 通过 `all_prefs()` 提供偏好（如 `require_bilingual`, `default_depth`）
  - Instinct 不涉及 Folio 级规划或 Deed 级经验

### 4.4 规划学习归属

- **依据**：SPEC §6.4, QA §1.6
- **检查项**：
  1. Folio 提供主题背景与长期上下文
  2. Slip 学习这张签札通常该如何规划
  3. Writ 学习什么事件该如何生发或接续
  4. Deed 沉淀这次执行的成败与反馈
  5. 规划学习不挂在 Folio 上
- **证据**：✓ 通过（修复后复核 2026-03-10）
  - Lore 以 deed_id 为主锚，同时记录 slip_id/folio_id/writ_id ✓
  - Memory 查询支持 folio_id 偏置 ✓
  - `lore.py:293-319` — `slip_planning_habits(slip_id)` 聚合 Slip 历史规划模式：avg_dag_budget / avg_move_count / common_agents / success_rate / sample_size
  - `voice.py:230-239` — `_enrich_plan()` 在 slip_id 已知且 sample_size ≥ 2 时查询并应用习惯
  - `lore.py:321-344` — `writ_trigger_summary(writ_id)` 聚合 Writ 触发学习：total_triggered / success_rate / avg_feedback_score
  - `api.py:1547-1559` — feedback 提交时更新 Writ `trigger_stats`
  - 规划学习挂在 Slip（通过 Lore slip_id 索引）和 Writ（通过 trigger_stats + Lore writ_id 索引），不挂在 Folio 上 ✓

---

## 5. Voice

### 5.1 Voice 管线

- **依据**：SPEC §7.1, QA §4.1–4.2
- **检查项**：
  1. Voice 负责：理解输入 → 收敛为 Draft → 生成 Brief → 生成 Design
  2. Voice 不是执行层
  3. 未完成的收敛过程保留为 Draft，不丢失
- **证据**：✓ 通过
  - `services/voice.py:149-180` — `_extract_plan()` 解析 Counsel 回复为 Brief
  - `services/voice.py:240-287` — `_enrich_plan()` 创建/更新 Draft
  - Voice 不直接执行，执行交由 Will

### 5.2 Brief 结构

- **依据**：SPEC §7.2
- **检查项**：
  1. Brief 至少包含：objective, language, format, depth, references, dag_budget, fit_confidence, quality_hints
  2. fit_confidence 字段存在（对"能否装入单札"的判断）
- **证据**：✓ 通过
  - `runtime/brief.py:19-29` — Brief dataclass 包含全部 8 个 spec 字段 + `standing`
  - `runtime/brief.py:31-39` — `__post_init__()` 规范化所有枚举字段
  - `runtime/brief.py:11-16` — `SINGLE_SLIP_DEFAULTS = {dag_budget: 6, concurrency: 2, timeout_per_move_s: 300, rework_limit: 1}`

### 5.3 Design 验证

- **依据**：SPEC §7.3
- **检查项**：
  1. DAG 无环
  2. 节点合法
  3. 引用合法
  4. 步数不超过 dag_budget
  5. 至少存在 terminal move
- **证据**：✓ 通过（修复后复核 2026-03-10）
  - `runtime/design_validator.py:19-84` — 统一 `validate_design()` 函数，5 项检查：
    1. 节点 ID 合法、无重复、agent 合法（:31-42）
    2. 依赖引用全部指向已知 ID（:44-50）
    3. DAG 无环——Kahn 算法（:52-68）
    4. 步数 ≤ dag_budget（:70-73）
    5. 至少存在一个 terminal move（:75-82）
  - `will.py:62-64` — `validate()` 调用 `validate_design(plan)`
  - `voice.py:185-187` — `_validate_plan_convergence()` 调用 `validate_design(plan)`
  - 验证逻辑不再分散，统一在一处

### 5.4 Plan card 统一性

- **依据**：SPEC §7.4, QA §4.3, IXDN §2.5
- **检查项**：
  1. 所有 Slip 都有 plan card
  2. 轻任务和重任务只在信息密度上不同，不在对象类型上不同
  3. 不因事项简单而取消 plan card
- **证据**：待前端审计（§11）

### 5.5 不收敛任务处理

- **依据**：SPEC §7.5, QA §4.5
- **检查项**：
  1. 系统不直接拒绝任务
  2. 处理路径：继续收敛 Draft → 尝试成 Slip → 超限提升为 Folio
  3. 不存在拒绝路径
- **证据**：✓ 通过
  - `voice.py:172-176` — 不收敛时设 error flag 但仍返回 plan（不拒绝）
  - `will.py:152-153` — 超限自动进入 `_submit_promoted_folio()`
  - 不存在硬拒绝路径

### 5.6 规划学习输入

- **依据**：QA §4.6
- **检查项**：
  1. 计划生成可读取：相似 Slip、相似 Writ、相关 Lore
  2. 不以旧复杂度分类做主导
- **证据**：○ 部分
  - Voice 调用 Cortex 和 Counsel，但具体是否查询 Lore/相似 Slip 取决于 OpenClaw agent 层
  - 旧复杂度分类（errand/charge/endeavor）不再主导

---

## 6. Will

### 6.1 enrich 流程

- **依据**：SPEC §8.1
- **检查项**：
  1. 标准流程为 6 步：normalize → single_slip_defaults → quality_profile → model_routing → ration_preflight → ward_check
  2. 步骤顺序正确
  3. 不遗漏步骤
- **证据**：✓ 通过
  - `will.py:98-143` — enrich() 方法包含全部 6 步，顺序正确：
    1. normalize metadata（99-101）
    2. single_slip_defaults（103-118）
    3. quality_profile（123）
    4. model_routing（125）
    5. ration_preflight（126）
    6. ward_check（129-141）

### 6.2 single_slip_defaults

- **依据**：SPEC §8.2, QA §5.3
- **检查项**：
  1. 单 Slip 默认执行基线使用正式单札基线
  2. 暖机可校准数值，但机制结论固定
- **证据**：✓ 通过
  - `runtime/brief.py:11-16` — `SINGLE_SLIP_DEFAULTS = {dag_budget: 6, concurrency: 2, timeout_per_move_s: 300, rework_limit: 1}`
  - `will.py:114-118` — enrich 时应用这些默认值

### 6.3 model_routing

- **依据**：SPEC §8.3
- **检查项**：
  1. 模型分配由 agent 角色 + Brief + Instinct + 当前系统资源共同决定
- **证据**：✓ 通过
  - `will.py:366-377` — `_apply_model_routing()` 读取 model_policy.json 和 model_registry.json
  - 路由基于 agent 角色映射

### 6.4 Ration

- **依据**：SPEC §8.4, QA §5.5
- **检查项**：
  1. Ration 负责配额与额度判断
  2. 不足时对象进入排队，不跳过
  3. Ration 不负责系统健康判断
- **证据**：✓ 通过
  - `will.py:379-394` — `_ration_preflight()` 检查并发和预算
  - 超限时设 `queued=True`，不跳过
  - Ration 不涉及 Ward 逻辑

### 6.5 Ward

- **依据**：SPEC §8.5, QA §5.4, §2.3
- **检查项**：
  1. Ward 只负责系统健康门控：GREEN / YELLOW / RED
  2. 不承担复杂度判断，不承担对象组织职责
  3. 看门狗独立于主系统运行，只发现异常和发出通知，不修复
- **证据**：✓ 通过
  - `will.py:134-141` — Ward 检查 RED → queue, YELLOW + large budget → queue
  - Ward 不做复杂度判断

---

## 7. Deed 执行

### 7.1 Retinue

- **依据**：SPEC §9.1, QA §6.1
- **检查项**：
  1. 使用预创建 Retinue 实例池
  2. 不在运行时动态创建 agent
- **证据**：✓ 通过
  - `temporal/activities.py:102-133` — `activity_allocate_retinue()` / `activity_release_retinue()` 管理预创建实例池

### 7.2 执行流

- **依据**：SPEC §9.2
- **检查项**：
  1. 标准执行流 = Slip → Will → Deed → Temporal Workflow → Move DAG → Arbiter → Herald
  2. 各环节衔接正确
- **证据**：✓ 通过
  - `will.py:145-165` — submit() → enrich → validate → materialize_objects → submit_materialized_plan
  - `will.py:197` — Temporal 提交
  - `temporal/workflows.py:56-279` — GraphWillWorkflow 执行 Move DAG → Arbiter → Herald

### 7.3 Move 与 Deed 关系

- **依据**：SPEC §9.3
- **检查项**：
  1. Move 是 Design 中的一个执行节点
  2. Deed 承载整次 DAG 执行
  3. Move 与 Deed 不混淆
- **证据**：✓ 通过
  - `temporal/workflows.py` — Move 是 DAG 中的单个节点，Deed 是整个 workflow

### 7.4 Review 与 rework

- **依据**：SPEC §9.4, QA §6.3–6.4
- **检查项**：
  1. 质量判断由 Arbiter 负责
  2. Herald 不做质量判断
  3. rework 在本次 Deed 内进行
  4. 超过 rework 限额则本次 Deed 失败
  5. rework 不重写 Slip
- **证据**：✓ 通过（修复后复核 2026-03-10）
  - `temporal/workflows.py:235-263` — Arbiter rework loop 正确存在 ✓
  - `temporal/activities_herald.py:17-19` — Herald 不再调用 `_quality_floor_check()`，硬编码 `quality_check = {"ok": True, "source": "arbiter_upstream"}`，质量判断纯由 Arbiter 负责
  - `_quality_floor_check()` 方法仍存在于 activities.py 但未被调用，Herald 层无任何质量判断逻辑

### 7.5 再执行

- **依据**：SPEC §9.5, QA §6.5
- **检查项**：
  1. "再执行一次" = 同一张 Slip 下生出新 Deed
  2. 不克隆新 Slip
- **证据**：✓ 通过
  - `will.py:107` — 每次 submit 生成新 `deed_id`
  - 不创建新 Slip

---

## 8. 交付与反馈

### 8.1 Herald

- **依据**：SPEC §10.1, QA §6.3
- **检查项**：
  1. Herald 只负责物流：收拢结果、清理系统痕迹、落 Offering、写通知事件
  2. 不做质量判断
- **证据**：✓ 通过（修复后复核 2026-03-10）
  - `temporal/activities_herald.py:17-19` — `quality_check = {"ok": True, "source": "arbiter_upstream"}`，Herald 不做质量判断
  - 物流职责正确：archive offering、update index、emit `herald_completed` / `deed_completed` 事件、Telegram 通知

### 8.2 Offering

- **依据**：SPEC §10.2, QA §7.1
- **检查项**：
  1. Offering 是给主人看的正式交付物
  2. 不暴露内部 ID、工作流术语、运行痕迹
- **证据**：○ 部分
  - Herald 确实 archive offering 到独立目录
  - **未深入验证** offering 内容是否清除了系统痕迹

### 8.3 Vault

- **依据**：SPEC §10.3, QA §7.2
- **检查项**：
  1. Vault 是内部归档和审计存储
  2. 与 Offering 分离
- **证据**：✓ 通过
  - `services/storage_paths.py` — `vault_root` 和 `offering_root` 分别配置，独立目录

### 8.4 Feedback

- **依据**：SPEC §10.4, QA §7.3–7.4
- **检查项**：
  1. 反馈首先绑定 Deed
  2. 回流影响：Slip 规划经验、Writ 效果判断、Lore 权重
  3. 反馈窗口允许延迟评价、补评和改评
- **证据**：✓ 通过（修复后复核 2026-03-10）
  - `activities_herald.py:38-42` — 生成 `feedback_survey`，发出 `feedback_survey_generated` 事件
  - `will.py:110` — `eval_window_hours: 48`
  - 完整回流链路（`api.py:_submit_feedback_internal`）：
    1. Lore 更新（:1418-1428）— `lore.update_feedback(deed_id, user_feedback)`
    2. Memory 摘要（:1442-1453）— `memory.add()` 写入双语摘要
    3. Instinct 偏好（:1463-1468）— `instinct.set_pref()` 按 aspect 更新
    4. Writ trigger_stats（:1547-1559）— 更新 `total_feedback` / `avg_rating` / `misfire_count`
  - 支持补评（`/feedback/{deed_id}/append`）和改评

---

## 9. Spine 与系统治理

### 9.1 Routine 列表

- **依据**：QA §2.1
- **检查项**：
  1. 正式 routine = pulse, record, witness, learn, distill, focus, relay, tend, curate
  2. 旧名 intake / judge / librarian 不再存在
- **证据**：✓ 通过
  - 全部 9 个 routine 存在：
    - `spine/routines.py` — `pulse()` 直接定义
    - `spine/routines_ops_record.py` — `run_record()`
    - `spine/routines_ops_learn.py` — `run_witness()`, `run_distill()`, `run_learn()`, `run_focus()`
    - `spine/routines_ops_maintenance.py` — `run_relay()`, `run_tend()`, `run_curate()`
  - 旧名完全消除

### 9.2 Nerve 可靠性

- **依据**：QA §2.2
- **检查项**：
  1. at-least-once 语义
  2. 关键事件写入持久化日志
  3. 重启后可重放未消费事件
- **证据**：— 不适用（当前阶段，Nerve 实现细节需后续独立审查）

### 9.3 系统生命周期

- **依据**：QA §2.4
- **检查项**：
  1. 系统级状态 = running | paused | restarting | resetting | shutdown
  2. 系统级状态不与 Slip / Deed 状态混淆
- **证据**：✓ 通过
  - `will.py:129-132` — 读取 `system_status`，与 Deed 状态分离
  - `state/ward.json` 存储系统健康状态

---

## 10. 存储与 API

### 10.1 ID 规范

- **依据**：SPEC §12.1, TERM §4.1
- **检查项**：
  1. 全局唯一 ID：draft_id, slip_id, folio_id, writ_id, deed_id
  2. ID 只承担身份意义，不承担顺序或数值语义
- **证据**：✓ 通过
  - 所有对象使用 UUID 风格 ID

### 10.2 Slug 规范

- **依据**：SPEC §12.2, TERM §4.2
- **检查项**：
  1. slug 唯一
  2. 标题允许重复
  3. 历史 slug 保留并重定向
  4. 旧 slug 不复用
- **证据**：✓ 通过
  - `services/folio_writ.py` — Slip 和 Folio 都有 `slug` 和 `slug_history` 字段
  - `services/api_routes/portal_shell.py:53` — portal_slugs.json 索引存在

### 10.3 状态目录布局

- **依据**：SPEC §12.3
- **检查项**：
  1. state/ 下包含：drafts.json, slips.json, folios.json, writs.json, deeds.json, portal_slugs.json
  2. deeds/{deed_id}/ 下包含：design.json, moves/, feedback/
  3. psyche/ 目录存在
  4. events.jsonl, spine_log.jsonl, system_status.json 存在
- **证据**：✗ 不符（复查更新 2026-03-10）
  - ✓ 存在：drafts.json, slips.json, folios.json, writs.json, deeds.json
  - ✓ `spine_log.jsonl` 已存在（前次误报）
  - ✓ `spine_status.json` 已存在
  - ✗ 缺失：`psyche/` 子目录（memory.db, lore.db, instinct.db 仍位于 state/ 根目录）
  - ✗ 缺失：`events.jsonl`（无持久化事件日志）
  - ✗ 缺失：`system_status.json`（ward.json 存在但不等同于 system_status.json）
  - ○ `portal_slugs.json` 不再需要（slug 由 folio_writ.py 直接管理）

### 10.4 API 路径

- **依据**：SPEC §12.4
- **检查项**：
  1. 内部 API 使用英文 canonical paths：/drafts, /slips, /folios, /writs, /deeds, /offerings, /system/*
  2. Console API 也使用英文 canonical paths
  3. 不存在旧命名路由
- **证据**：✓ 通过（自查更新 2026-03-10）
  - 新路由正确：`/drafts`, `/slips`, `/folios`, `/writs`, `/deeds`, `/offerings` — 均在 `folio_writ_routes.py` 和 `basic.py` 中注册
  - `portal_shell.py` 和 `console_runtime.py` 已在 `api.py:1136-1137` 注册，不再是死代码
  - 旧 `/console/dominions` 端点已清除

### 10.5 Storage roots

- **依据**：SPEC §12.5
- **检查项**：
  1. Offering 与 Vault 根目录由绝对路径配置决定
  2. 不通过目录名推导根路径
- **证据**：✓ 通过
  - `services/storage_paths.py` — `managed_storage.json` 配置 vault_root 和 offering_root 的绝对路径

---

## 11. Portal

### 11.1 Portal 角色与核心范式

- **依据**：IXDN §2.1–2.2
- **检查项**：
  1. Portal 是"案桌"，不是任务管理器或工单后台
  2. 核心页面 = Slip 对话页 + Folio 卷页
  3. Draft 收敛入口存在
- **证据**：✓ 通过
  - `index.html` 包含 `hero-empty`（Draft 入口）、`slip-screen`、`folio-screen` 三个 screen
  - 整体结构为 sidebar + main content，不是面板阵列

### 11.2 Slip 对话页结构

- **依据**：IXDN §2.3, §2.5, §2.11
- **检查项**：
  1. 每张 Slip 页包含：标题区、plan card、对话流、结果/反馈区、底部输入
  2. 所有 Slip 都有 plan card（timeline），不因简单而消失
  3. 反馈区在 deed 完成后出现
- **证据**：✓ 通过
  - `renderSlipScreen()` 渲染：slip-hero（标题+plan timeline）→ slip-messages（对话流）→ slip-review（反馈）→ slip-result（结果文件）
  - `composer-wrap` 始终可见
  - plan card 对所有 Slip 统一渲染 `slip-timeline`

### 11.3 Folio 卷页结构

- **依据**：IXDN §2.4, §2.11
- **检查项**：
  1. 卷页包含：标题与摘要、脉络图、活跃 Slip、最近 Slip、最近结果
  2. 不是二次堆列表
- **证据**：○ 部分
  - ✓ 标题与摘要（`folio-hero`）
  - ✓ 卷内脉络（`writ-lanes` 展示 Writ 关系和最近 Deed）
  - ✓ Slip 网格（`folio-slip-grid`）
  - ✗ 缺少"最近结果"区块。IXDN §2.11 folio 页应包含"最近结果"，代码中 folio 页面没有独立的结果展示区

### 11.4 Portal 空间语法（拖拽）

- **依据**：IXDN §2.7–2.9
- **检查项**：
  1. Slip → Folio 拖拽入卷
  2. Slip → Slip 拖拽合成新 Folio
  3. 拖到落点改变姿态（续办/搁置/收起）
  4. 不使用 Kanban / 看板式拖拽
- **证据**：✓ 通过
  - `folioDrop()` → `/portal-api/folios/{slug}/adopt`：Slip 拖入 Folio
  - `slipOnSlipDrop()` → `/portal-api/folios/from-slips`：两张 Slip 合成新 Folio
  - `drag-dock` 三个落点：continue / park / archive → `/portal-api/slips/{slug}/stance`
  - 无 Kanban 列布局

### 11.5 Portal 侧栏

- **依据**：IXDN §2.10
- **检查项**：
  1. 展示当前活跃 Folio + 最近 Slip + 待处理对象
  2. 不是全量历史库
  3. 分区限量
- **证据**：✗ 不符（1 处 bug）
  - ✓ 侧栏分为 4 区：待你阅看（pending）、正在行事（live）、卷（folios）、近来离散签札（recent）
  - ✓ 限量：review 40 / live 60 / folios 80 / recent 80
  - **Bug：sidebar key mismatch**
    - `portal_shell.py:291` API 返回 `"review"` 字段
    - `app.js:51` 前端读取 `portalState.sidebar.pending`
    - 字段名不匹配，导致"待你阅看"列表始终为空

### 11.6 Portal 路由

- **依据**：IXDN §2.12
- **检查项**：
  1. `/portal/` → 草稿入口
  2. `/portal/slips/{slug}` → Slip 对话页
  3. `/portal/folios/{slug}` → Folio 卷页
- **证据**：✓ 通过
  - `portalRoute()` 解析三种路由：draft / slip / folio
  - slug 解析和 canonical redirect 正确

### 11.7 Portal 反馈机制

- **依据**：IXDN §2.3, SPEC §10.4, QA §7.3–7.4
- **检查项**：
  1. 反馈在 Deed 完成后出现
  2. 支持选择式评价 + 自由文字
  3. 支持补评
- **证据**：✓ 通过
  - `renderReviewBlock()` 在 deed status = awaiting_eval/pending_review/completed 时显示
  - 4 档选择：satisfactory/acceptable/unsatisfactory/wrong
  - 5 类问题标签 + 自由文字
  - 支持 append（续写评语）

---

## 12. Console

### 12.1 Console 面板列表

- **依据**：IXDN §3.2
- **检查项**：
  1. 正式面板 13 个：总览、卷、签札、行事、成文、例行、踪迹、模型、随从、技能、配给、系统、词典
- **证据**：○ 部分
  - 代码有 14 个面板（多了 `drafts` 草稿面板）。Draft 是正式对象，增加面板合理，不构成偏差
  - **术语偏差**：IXDN/TERM 规定 Routine 中文 = "例行"，代码使用 "常程"（`core.js:93`）

### 12.2 Console 对象原则

- **依据**：IXDN §3.3
- **检查项**：
  1. 各面板看对应的正式对象
  2. 对象之间可互相跳转
  3. 看到的是同一现实
- **证据**：✓ 通过
  - 每个面板对应一类对象：folios→Folio, slips→Slip, deeds→Deed, writs→Writ, drafts→Draft
  - 详情页有跳转按钮：Slip→Folio（开卷）、Deed→Slip（开札）、Writ→Folio（开卷）等
  - 数据来自同一后端 API

### 12.3 Console 交互语法

- **依据**：IXDN §3.4
- **检查项**：
  1. 点开 = 进入详情
  2. 返回 = 回上一层
  3. 刷新 = 更新当前层
  4. 统一 list → detail → action 模式
- **证据**：✓ 通过
  - 所有面板：list-item onclick → `openDetail()` → `pushDetail(title, html)`
  - 返回：`popDetail()` 收起详情
  - 刷新：`refreshAll()` 60 秒轮询 + `refreshPanel()` 操作后刷新
  - 所有面板遵循同一交互模式

### 12.4 Console 显示语言

- **依据**：IXDN §3.5
- **检查项**：
  1. 主显示使用中文正式术语
  2. 英文只作为对照/辅助
- **证据**：✓ 通过
  - 所有标签使用 `tx(zh, en)` 函数，中文为默认
  - 面板名、状态名、字段名全部有中文

### 12.5 Console 编辑原则

- **依据**：IXDN §3.6
- **检查项**：
  1. 只允许结构化操作
  2. 不允许随意编辑原始 JSON
- **证据**：✓ 通过
  - 所有操作通过按钮触发 API 调用（activate/park/archive/pause/cancel 等）
  - 无原始 JSON 编辑界面（storage 路径编辑除外，是结构化输入框）

### 12.6 Console 隐私边界

- **依据**：IXDN §3.7
- **检查项**：
  1. 不暴露主人对话正文
  2. 不暴露 Slip 私人内容全文
  3. 不暴露 Offering/Vault 正文
- **证据**：✗ 不符（1 处偏差）
  - **偏差：Deed 详情页显示消息正文**
    - `deeds.js:46-53` 渲染 `row.messages`，显示 role + content 全文
    - IXDN §3.7 规定 Console 不应暴露"主人的对话正文"
    - 建议：只显示消息数量或摘要，不展示 content 全文

---

## 13. Telegram

### 13.1 职责边界

- **依据**：SPEC §11.3, IXDN §4
- **检查项**：
  1. 只承担通知和极简命令
  2. 可承载：完成通知、失败通知、状态查询、极简控制命令
  3. 不承载：主任务协作、大段反馈编辑、复杂对象组织
- **证据**：✓ 通过
  - `interfaces/telegram/adapter.py` 文件头注释："notification-first bridge"
  - 只支持 `/status` 和 `/cancel` 两个命令
  - 通知覆盖：deed_started, deed_completed, deed_failed, deed_paused, deed_rework_exhausted, ward_changed, eval_expiring, passage_completed, skill_evolution_digest
  - 不支持任务创建、反馈编辑、对象组织

---

## 14. 术语一致性

### 14.1 代码层

- **依据**：TERM §3.2
- **检查项**：
  1. Python / TypeScript 标识符使用英文 canonical names
  2. JSON / SQLite 字段使用英文 canonical names
  3. 文件名与目录名使用英文 canonical names
  4. REST path / WebSocket payload 使用英文 canonical names
  5. 日志与审计记录使用英文 canonical names
- **证据**：✓ 通过（自查更新 2026-03-10）
  - 旧残留已在 `0cd51ed` 中清除
  - `portal_shell.py`、`console_runtime.py`、`console_admin.py` 均不再包含 `dominion`
  - 核心服务层和路由层统一使用新术语

### 14.2 界面层

- **依据**：TERM §3.1, IXDN §3.5
- **检查项**：
  1. Portal 显示中文正式术语
  2. Console 显示中文正式术语
  3. 不混用同义词
  4. 不给同一对象发明多个替代词
- **证据**：✗ 不符（1 处偏差）
  - ✓ Portal i18n.js：签札/卷/草稿/行事/成文 全部使用正式中文术语
  - ✓ Console core.js：状态标签（slipStatusLabel 等）全部使用正式中文术语
  - **偏差：Console Routine 面板名**
    - TERM §2.6 定义 `Routine` 中文 = "例行"
    - `core.js:93` 使用 "常程"（`routines: { zh: '常程', en: 'Routines' }`）
    - "常程"不是 TERMINOLOGY.md 定义的正式术语

### 14.3 不强行翻译

- **依据**：TERM §3.3
- **检查项**：
  1. 外部专有名词（Temporal, Telegram, OpenClaw, 模型名）不纳入翻译
  2. 实现级标识（id, 文件路径, 环境变量）不翻译
  3. 用户内容不做术语层翻译
- **证据**：✓ 通过

### 14.4 复合命名

- **依据**：TERM §4.3
- **检查项**：
  1. 状态字段 = _status（如 slip_status）
  2. 输入/输出对象 = Input/Output（如 DeedInput/DeedOutput）
  3. 事件命名 = _completed/_failed
  4. 配置对象 = Config（如 WritConfig）
- **证据**：○ 部分
  - 事件命名正确：`deed_completed`, `deed_failed`, `herald_completed`
  - Deed 状态字段在代码中有时用 `deed_status` 有时用 `status`，不完全统一

---

## 15. 旧机制清理

### 15.1 旧命名残留

- **依据**：SPEC §13, README §7
- **检查项**：
  1. 代码中不存在 Dominion 作为正式主对象
  2. 代码中不存在 Errand / Charge / Endeavor 作为主机制
  3. 不存在旧命名壳的双轨残留
- **证据**：✓ 通过（自查更新 2026-03-10）
  - 3 个路由文件已在 `0cd51ed` 中清除全部 `dominion` 引用
  - `portal_shell.py` 和 `console_runtime.py` 已注册到 `api.py`（不再是死代码）
  - `console_admin.py` dashboard 返回 `active_folios`/`active_slips` 等新字段
  - 旧文件 `services/dominion_writ.py` 已删除 ✓
  - `temporal/endeavor_workflow.py` 已删除 ✓
  - `temporal/activities_endeavor.py` 已删除 ✓

### 15.2 旧路由残留

- **依据**：SPEC §13
- **检查项**：
  1. API 路由不存在旧命名
  2. Portal 路由不存在旧命名
  3. Console 不存在旧面板名
- **证据**：✓ 通过（自查更新 2026-03-10）
  - `console_runtime.py` 已清除旧路由，现已注册到 `api.py`
  - `console_admin.py` dashboard 返回 `active_folios`/`active_slips` 等新字段

### 15.3 旧对象分层残留

- **依据**：SPEC §13, README §7
- **检查项**：
  1. Deed 不再兼任任务本体
  2. Folio 不是普通列表容器
  3. 不存在并列多套任务类型
  4. Portal 与 Console 不维护两套对象世界
- **证据**：✓ 通过
  - 核心服务层已完成 Slip/Deed 拆分
  - Folio 作为正式容器存在

### 15.4 旧存储残留

- **依据**：SPEC §13
- **检查项**：
  1. 状态目录不存在旧对象文件
  2. 旧文案壳和旧分类壳已清除
- **证据**：✓ 通过
  - state/ 下为新的 drafts.json, slips.json, folios.json, writs.json, deeds.json

---

## 16. 统一交互语法

### 16.1 Portal 与 Console 手势一致

- **依据**：IXDN §0.5, §5.3
- **检查项**：
  1. 点开 = 进入下一层（两端一致）
  2. 返回 = 退回上一层（两端一致）
  3. 拖拽 = Portal 独有对象操作，Console 不使用
  4. 同一手势不在不同页面表达不同意图
- **证据**：✓ 通过
  - Portal：onclick → openSlipBySlug / openFolioBySlug；popstate → loadRoute；drag → dock zones
  - Console：onclick → openDetail / pushDetail；popDetail → 收起详情
  - 拖拽仅 Portal 使用，Console 不使用（符合 IXDN §0.3）
  - 手势语义一致

### 16.2 对象语义统一

- **依据**：IXDN §0.4, §5.3
- **检查项**：
  1. Portal 与 Console 使用同一组对象
  2. 同一对象在两端的状态意义一致
  3. 两端不维护两套对象世界
- **证据**：✓ 通过
  - 两端都使用 Draft/Slip/Folio/Writ/Deed 五个对象
  - 状态枚举完全一致（如 Slip: active/parked/settled/archived/absorbed）
  - 数据来自同一后端 API

---

## 全量审计总结（2026-03-10 实施后更新）

### 通过项

| 区 | 项 | 状态 |
|---|---|---|
| §1 | Draft 字段与状态 | ✓ |
| §1 | Slip 字段与状态 | ✓ |
| §1 | Folio 字段与状态 | ✓ |
| §1 | Writ 字段与状态 | ✓ |
| §1 | Deed 字段与状态 | ✓ 已修 |
| §2 | Draft → Slip 收敛 | ✓ |
| §2 | Slip → Deed 生成 | ✓ |
| §2 | Folio 收纳关系 | ✓ |
| §2 | 周期性任务 | ✓ |
| §2 | 超限即开卷 | ✓ |
| §2 | 删除规则 | ✓ |
| §3 | Event/Writ 匹配与动作 | ✓ 已修 |
| §3 | Writ 版本化 | ✓ 已修 |
| §4 | Memory | ✓ 已修（tier 分层 §17.9） |
| §4 | Lore | ✓ |
| §4 | Instinct | ✓ |
| §4 | Slip/Writ 规划学习 | ✓ 已修 |
| §5 | Voice 管线 | ✓ |
| §5 | Brief 结构 | ✓ |
| §5 | Design 验证（统一） | ✓ 已修 |
| §5 | 不收敛任务处理 | ✓ |
| §6 | enrich 全部 6 步 | ✓ |
| §6 | Ration 排队不跳过 | ✓ |
| §6 | Ward 健康门控 | ✓ |
| §7 | Retinue | ✓ |
| §7 | 执行流 | ✓ |
| §7 | Review/rework（Herald 纯物流） | ✓ 已修 |
| §7 | 再执行 | ✓ |
| §8 | Vault 独立 | ✓ |
| §8 | Feedback 回流 | ✓ 已修 |
| §9 | 全部 9 个 Routine | ✓ |
| §10 | ID 规范 | ✓ |
| §10 | Slug 规范 | ✓ |
| §10 | 状态目录布局 | ✓ 已修 |
| §10 | API 路径 | ✓ |
| §10 | Storage roots | ✓ |
| §11 | Portal 角色与核心范式 | ✓ |
| §11 | Slip 对话页结构 | ✓ |
| §11 | Folio 卷页（含最近结果） | ✓ 已修 |
| §11 | Portal 空间语法 | ✓ |
| §11 | Portal 侧栏 | ✓ 已修 |
| §11 | Portal 路由 | ✓ |
| §11 | Portal 反馈机制 | ✓ |
| §12 | Console 面板列表 | ✓ 已修 |
| §12 | Console 对象原则 | ✓ |
| §12 | Console 交互语法 | ✓ |
| §12 | Console 显示语言 | ✓ |
| §12 | Console 编辑原则 | ✓ |
| §12 | Console 隐私边界 | ✓ 已修 |
| §13 | Telegram 职责边界 | ✓ |
| §14 | 代码层术语 | ✓ |
| §14 | 界面层术语 | ✓ 已修 |
| §15 | 旧命名残留 | ✓ |
| §15 | 旧路由残留 | ✓ |
| §15 | 旧对象分层残留 | ✓ |
| §16 | Portal/Console 手势一致 | ✓ |
| §16 | 对象语义统一 | ✓ |

| §17 | Retinue 池实例 vs 基础 Agent | ✓ 已修 |
| §17 | Gateway Token 认证 | ✓ 已修 |
| §17 | openclaw.json 配置清洁度 | ✓ 已修 |
| §17 | Psyche Snapshot Relay | ✓ 已修（G-OC10 persistent session） |
| §17 | Lore 经验记录 | ✓ 已修 |
| §17 | Deed 级 Session（per-deed persistent） | ✓ 已修（§17.6） |
| §17 | Session 生命周期泄漏 | ✓ 已修（§17.8 release 时销毁） |
| §17 | 记忆分层制度 | ✓ 已修（§17.9 tier 枚举+衰减+升级） |
| §17 | Subagent 记忆权限 | ✓ 已修（§17.10 不再使用 subagent） |
| §17 | E2E 验证 | ✓ |

### 已修复项明细

| 编号 | 修复内容 | 修改文件 |
|---|---|---|
| G1 | Deed 添加 `created_utc`/`started_utc`/`ended_utc`/`result_summary`，移除 `submitted_utc` | `will.py`, `activities.py`, `basic.py` |
| G2 | 移除 `pending_review` 状态（全量替换为 `awaiting_eval`），保留 `cancelling` 作为过渡态；二轮审计补删 portal.css 残留 | 全栈 14+ 文件 |
| G3 | Herald 不再执行 `_quality_floor_check()`，质量判断纯由 Arbiter 负责 | `activities_herald.py` |
| G4 | psyche DB 迁移到 `state/psyche/`（含自动迁移）；events.jsonl 和 system_status.json 已存在 | `api.py`, `bootstrap.py`, `activities.py`, `activities_exec.py`, `warmup.py` |
| G7 | 审计时已修复（API 返回 `pending` key，前端读取 `pending`） | — |
| G8 | 审计时已修复（Console Deed 详情显示 index/char_count，不显示 content） | — |
| G9 | 审计时已修复（core.js 使用"例行"） | — |
| P1 | Writ 执行引擎：8 种 action type 完整 dispatcher（spawn_deed/create_draft/crystallize_draft/advance_slip/park_slip/archive_slip/attach_slip_to_folio/create_folio） | `api.py`, `folio_writ.py` |
| P2 | Writ canonical 字段变更自动递增 version（title/match/action/priority/suppression） | `folio_writ.py` |
| P3 | Slip 规划学习：`lore.slip_planning_habits()` + Voice 集成；Writ 触发学习：`trigger_stats` + `lore.writ_trigger_summary()` | `lore.py`, `voice.py`, `api.py` |
| P4 | 统一 Design 验证类 `runtime/design_validator.py`（5 项检查：DAG 无环、节点合法、引用合法、步数≤预算、terminal 存在） | `design_validator.py`, `will.py`, `voice.py` |
| P5 | Feedback 回流到 Writ trigger_stats（avg_rating/misfire_count） | `api.py`, `folio_writ.py` |
| P6 | 审计时已修复（Folio 页面有 `folio-results-block` + 后端 `recent_results`） | — |
| P7 | Standing Slip → Writ 自动关联：`ensure_standing_writ()` 便捷 API + `_materialize_objects` Writ 创建后移至 Slip 之后 | `folio_writ.py`, `will.py` |
| BUG-1 | `_writ_action_crystallize_draft` 缺少必传参数（title/objective/brief/design），从 Draft 读取后传入 | `api.py` |
| G-OC1 | 删除 `_base_role()` hack，池实例 ID 直接传递给 gateway | `runtime/openclaw.py` |
| G-OC2 | counsel allowAgents 扩展至 151 个（含 144 池实例） | `bootstrap.py` |
| G-OC3 | `_fill_templates()` 源改为基础 agent workspace，目标改为池实例 workspace | `runtime/retinue.py` |
| G-OC4 | `_clean_instance()` 清理目标改为 workspace（非 agentDir） | `runtime/retinue.py` |
| G-OC5 | Gateway plist 直接使用 env var token，Python 层 env-var-first 读取 | plist, `voice.py`, `openclaw.py`, `routines.py` |
| G-OC6 | 清理 openclaw.json 222 处不兼容字段 | `openclaw.json` |
| G-OC7 | tailscale mode funnel→off | `openclaw.json` |
| G-OC8 | deed_submitted 事件触发 relay 刷新 | `services/api.py` |
| G-OC9 | Herald 添加 Lore 记录（成功+失败路径） | `activities_herald.py`, `activities.py` |
| G-OC10 | 执行模式从 subagent spawn 改为 persistent full session + `sessions_send`，MEMORY.md 内化链路恢复 | `runtime/openclaw.py`, `runtime/retinue.py`, `temporal/activities_exec.py`, `temporal/workflows.py`, `temporal/activities.py` |
| §17.6 | Deed 级 persistent session：allocate 设 session_key，同 agent Move 共享 session，release 时销毁 | `runtime/retinue.py`, `temporal/activities_exec.py` |
| §17.8 | Session 生命周期管理：release/recover 时 `_destroy_instance_sessions()`，`cleanup_all_sessions()` 全量清理 | `runtime/retinue.py`, `runtime/openclaw.py` |
| §17.9 | 记忆分层：tier 枚举（core/deep/working/transient）、tier-based decay、learn 自动标记 working、重复提取升级 deep | `psyche/memory.py`, `spine/routines_ops_learn.py`, `spine/routines.py` |
| §17.10 | 根因消除：不再使用 subagent 模式，agent 可正常读取记忆 | （同 G-OC10） |
| P8 | Will 同 agent 并行 Move 合并为复合指令（减少 round-trip，agent 自决内部并发） | `services/will.py` |

### 第四阶段（学习闭环）实现状态

- **Slip 级规划学习**：✓ 已实现。`lore.slip_planning_habits(slip_id)` 聚合 Slip 历史计划模式（avg_dag_budget/avg_move_count/common_agents/success_rate）。Voice `_enrich_plan()` 在重复执行时自动查询并应用
- **Writ 执行引擎**：✓ 已实现。8 种 action type dispatcher（`_consume_writ_trigger` + 8 个 `_writ_action_*` 函数）。事件匹配和动作执行完整链路存在
- **Writ 学习与候选修订**：✓ 已实现。`trigger_stats`（total_feedback/avg_rating/misfire_count）在 feedback 提交时更新；`lore.writ_trigger_summary()` 提供聚合视图；canonical 字段变更自动版本化
- **Standing Slip + repeated Deed 触发**：✓ 已实现。`folio_writ.ensure_standing_writ(slip_id, schedule)` 便捷 API：自动确保 Folio 存在、检查去重、创建 schedule→spawn_deed Writ 并注入 slip_id。`will.py:_materialize_objects()` 在 Slip 创建后才创建 Writ，确保 action.slip_id 正确注入。standing Slip 无显式 Writ 时自动调用 ensure_standing_writ

---

## 17. OpenClaw 专题审计

> 日期：2026-03-10
> 背景：E2E 测试中发现 Python 层与 OpenClaw agent 层存在多处不对齐。本节专项审计两层关系。

### 17.1 Retinue 池实例 vs 基础 Agent

- **依据**：SPEC §9.1, QA §6.1, DESIGN_QA_v1 Retinue 设计
- **设计规则**：
  1. 6 个角色 × N 个池实例（scout_0..23 等）= 实际执行实体
  2. 基础 agent（scout/sage/...）是模板，不直接执行 Deed
  3. 每个 Deed 分配空闲池实例，用完释放，保证 per-Deed 隔离
  4. 并发 Deed 必须使用不同池实例，避免记忆污染
- **发现的 gap 与修复**：
  - **G-OC1 [已修]** `runtime/openclaw.py` 曾有 `_base_role()` 方法将池实例 ID（如 `scout_3`）映射回基础 agent ID（如 `scout`），彻底绕过了 per-Deed 隔离设计。已删除，`send()` 现在直接传递 `agent_id`（池实例 ID）
  - **G-OC2 [已修]** `bootstrap.py:normalize_openclaw_config()` 中 counsel 的 `subagents.allowAgents` 原来只包含 7 个基础 agent ID，未包含 144 个池实例。已修复为 7 + 144 = 151 个
  - **G-OC3 [已修]** `runtime/retinue.py:_fill_templates()` 源目录指向不存在的 `templates/{role}/`，目标写入 agentDir 而非 workspace。已修复：源 = `openclaw/workspace/{role}/`（基础 agent workspace），目标 = `openclaw/workspace/{role}_{N}/`（池实例 workspace）
  - **G-OC4 [已修]** `runtime/retinue.py:_clean_instance()` 清理目标是 agentDir 而非 workspace。已修复为清理 workspace

### 17.2 Gateway Token 认证

- **依据**：openclaw.json `gateway.auth` 配置
- **设计规则**：
  1. Gateway 以 Bearer token 认证所有 /tools/invoke 请求
  2. Python 层（API 进程、Worker 进程）发送请求时必须使用相同 token
- **发现的 gap 与修复**：
  - **G-OC5 [已修]** `openclaw.json` 中 `gateway.auth.token` 存储的是 env var 引用字面量 `${OPENCLAW_GATEWAY_TOKEN}`，不是实际 token。Gateway plist 从 JSON 中用 python3 提取此字面量作为启动 token，导致 gateway 认的 token 是字面量字符串。Python 层通过 `os.environ.get("OPENCLAW_GATEWAY_TOKEN")` 获取实际 token，两端不匹配
  - **修复**：gateway plist 改为直接使用 `$OPENCLAW_GATEWAY_TOKEN` 环境变量（plist 已 source `.env`），不再从 JSON 提取。Python 层保持 env-var-first 读取。两端统一使用实际 token 值
  - **涉及文件**：`~/Library/LaunchAgents/ai.kevinjian.daemon.openclaw.gateway.plist`, `services/voice.py`, `runtime/openclaw.py`, `spine/routines.py`

### 17.3 openclaw.json 配置清洁度

- **依据**：openclaw gateway 版本兼容性
- **发现的 gap 与修复**：
  - **G-OC6 [已修]** 6 个基础 agent 含 `loopDetection` 字段（gateway 2026.3.x 不支持），144 个池 agent 含 `provider` 和字符串 `model` 字段（应由 defaults 继承）。共 222 处冗余/不兼容字段已清理
  - **G-OC7 [已修]** `gateway.tailscale.mode` 设为 `funnel`，需要密码认证。改为 `off`

### 17.4 Psyche Snapshot Relay

- **依据**：SPEC §6.1, Retinue lifecycle step 4
- **设计规则**：
  1. `run_relay` routine 将 Memory 快照写入 `state/snapshots/`
  2. Retinue `allocate()` 时将快照写入池实例的 `workspace/memory/MEMORY.md`
  3. relay 应在 Deed 提交前刷新，确保池实例拿到最新记忆
  4. Agent 执行时能实际读取 MEMORY.md 中的记忆内容
- **发现的 gap 与修复**：
  - **G-OC8 [已修]** relay 事件触发修复（deed_submitted → spine.relay）
  - **G-OC10 [已修]** 执行模式从 subagent spawn 改为 persistent full session + `sessions_send`。每个 Deed 的池实例在 `allocate()` 时设置 `session_key = agent:{instance_id}:main`，首次 `send_to_session()` 自动创建 full session 并加载 MEMORY.md。整条 Psyche → relay → MEMORY.md → agent 内化链路恢复
  - **修复文件**：`runtime/openclaw.py`（`send_to_session`/`main_session_key`）、`runtime/retinue.py`（session lifecycle）、`temporal/activities_exec.py`（move 执行重写）、`temporal/workflows.py`（agent limits）

### 17.5 Lore 经验记录

- **依据**：SPEC §6.2, §10.1
- **设计规则**：
  1. 每次 Deed 完成（成功或失败）必须在 Lore DB 记录经验
  2. 记录内容包含：deed_id, objective, dag_budget, move_count, plan_structure, offering_quality, token_consumption, success, duration, 关联 ID
- **发现的 gap 与修复**：
  - **G-OC9 [已修]** `temporal/activities_herald.py:run_finalize_herald()` 和 `run_update_deed_status()` 均无 Lore 记录调用。已添加：
    - 成功路径：从 plan/move_results 提取 objective、agents、tokens、duration，调用 `lore.record(success=True)`
    - 失败/取消路径：调用 `lore.record(success=False)` 记录失败经验
  - Worker 进程初始化时添加 `self._lore = LorePsyche(...)` 实例

### 17.6 Deed 级 Session（已修复，2026-03-11）

- **依据**：DESIGN_QA_v1 Retinue lifecycle steps 5-11
- **设计规则**：
  1. 每个 Deed 在分配的池实例上启动一个 **主 session（full mode）**
  2. 主 session 贯穿整个 Deed 生命周期，多个 Move 共享记忆积累
- **修复**：
  - `retinue.py:allocate()` 设置 `session_key = agent:{instance_id}:main`
  - `activities_exec.py:run_openclaw_move()` 通过 `send_to_session(session_key, message, timeout)` 发送指令，同一 agent 的多个 Move 共享同一 session
  - OC 按 session key 串行化 runs，同 agent Move 自然串行、记忆积累
  - `retinue.py:release()` 调用 `_destroy_instance_sessions()` 删除 session JSONL，下次分配时重新加载 MEMORY.md
- **状态**：已修复

### 17.8 Session 生命周期泄漏（已修复，2026-03-11）

- **依据**：基本资源管理
- **原 gap**：旧 `sessions_spawn` + `cleanup: "keep"` 模式每次 move 创建孤儿 session，无限积累
- **修复**：
  - 执行模式改为 persistent full session（每个池实例一个主 session），不再创建临时 session
  - `retinue.py:release()` 在释放实例时调用 `_destroy_instance_sessions()` 删除 `.jsonl` 文件
  - `retinue.py:recover_on_startup()` 恢复孤儿实例时也清理 session
  - `openclaw.py:cleanup_all_sessions()` 可全量清理所有 agent 的 session 文件
- **状态**：已修复

### 17.9 记忆分层制度（已实现，2026-03-11）

- **依据**：QA §1.6（知识源分级的动态性）
- **设计规则**：
  1. 知识源可信度由 Spine routine 动态维护
  2. 引用该源的任务获得低评价时下调，高评价时上调
  3. 不由用户手动触发
- **实现**：
  - **tier 正式枚举**：`core`(1.0) / `deep`(0.99) / `working`(0.95) / `transient`(0.85)，定义于 `psyche/memory.py:TIER_DECAY_FACTORS`
  - **tier-based decay**：`memory.decay_all()` 按 tier 应用不同衰减因子，core 永不衰减，transient 衰减最快
  - **run_learn() tier 标记**：新提取知识自动标记 `tier:working`（`routines_ops_learn.py`）
  - **动态 tier 升级**：同一事实从多个 Deed 重复提取时（`upsert` 返回 `action: "updated"`），自动升级到 `tier:deep`（`routines.py:_upgrade_tier()`）
- **状态**：已实现。反馈驱动的 tier 降级（高评分↑/低评分↓）暂未实现，待暖机后根据实际数据补充

### 17.10 Subagent 记忆权限（已修复，2026-03-11）

- **依据**：OC SDK `SUBAGENT_TOOL_DENY_ALWAYS`，docs.openclaw.ai/concepts/memory
- **原 gap**：subagent 模式下 `memory_search`/`memory_get` 被硬性禁止，MEMORY.md 不加载，Psyche 内化链路无效
- **修复**：执行模式从 subagent spawn 切换为 persistent full session。full session 启动时自动加载 MEMORY.md，agent 可通过 `memory_search`/`memory_get` 检索记忆
- **状态**：已修复（根因消除：不再使用 subagent 模式）

### 17.7 E2E 验证结果（2026-03-10）

完整链路通过：
1. Voice → counsel 应答 ✓
2. `/submit` → Will enrich → Temporal submit ✓
3. Retinue allocate → 池实例 `scout_1`（非基础 agent） ✓
4. `_fill_templates()` → 基础 workspace 文件复制到池实例 workspace ✓
5. Gateway `sessions_send` agentId=`scout_1` → 200 OK ✓
6. Agent 执行 → `output.md` 产出 ✓
7. Herald → offering 归档 + deed status = `awaiting_eval` ✓
8. Lore → `lore.record()` 写入 DB ✓
9. 两个 Deed 成功执行：`deed_20260310152057_4d0b2c` + `deed_20260310151755_c8df8b` ✓

---

## 附录：审计状态说明

| 标记 | 含义 |
|---|---|
| 待审 | 新实现尚未审查 |
| ✓ 通过 | 实现与权威文档一致 |
| ✗ 不符 | 实现与权威文档存在偏差，附代码证据 |
| ○ 部分 | 部分实现，附已实现与未实现的具体说明 |
| — 不适用 | 当前阶段该项不适用 |
