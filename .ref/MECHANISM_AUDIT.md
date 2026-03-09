# 机制审计：方案 × QA × 代码 三层对齐

> 日期：2026-03-09
> 目的：逐条核对方案、QA、代码三层之间的 gap（遗漏、矛盾、幽灵残留）
> 方法：按方案章节逐条过，每条标注三层状态，发现 gap 立即记录决策
> 执行人：另行安排，本文档只记录发现和决策
> 专属文档深度对照：DOMINION_WRIT_DEED.md（§10 已展开）、INTERACTION_DESIGN.md（§ID 已展开）

---

## 审计规则

- **方案** = `daemon_实施方案.md`（实施规范）
- **QA** = `DESIGN_QA.md`（设计决策，冲突时以 QA 为准）
- **代码** = Python + config + openclaw workspace
- 三层都对齐 = ✅
- 有 gap = ❌ 标注具体差异 + 决策
- 方案术语问题单独记（§0），不在每条重复

---

## §0 方案术语批量更新（已确认，待执行）

实施方案有 ~60 处旧术语未更新，DESIGN_QA 已全部更新。需批量替换：

| 旧 | 新 | 估计处数 |
|----|-----|---------|
| pulse/thread (复杂度) | errand/charge | ~8 |
| brief/standard/thorough (深度) | glance/study/scrutiny | ~4 |
| router/collect/analyze/build/review/render/apply | counsel/scout/sage/artificer/arbiter/scribe/envoy | ~15 |
| Plan/steps/步骤 (DAG) | Design/moves/Move | ~20 |
| outcomes/ | offerings/ | ~10 |
| Gate | Ward | ~5 |
| Archive/librarian | Vault/curate | ~8 |
| pool/池实例 | Retinue/Retinue 实例 | ~10 |
| review agent | arbiter agent | ~10 |
| render agent | scribe agent | ~5 |
| TRACK_LANE_RUN.md | DOMINION_WRIT_DEED.md | 1 |
| schedule.tick | cadence.tick | 1 |
| deed.completed | deed_completed | 1 |
| step_count (Lore) | move_count | 1 |
| outcome_quality (Lore) | offering_quality | 1 |
| pool_size_n | retinue_size_n | 1 |
| plan.json (deed 目录) | design.json | 1 |
| steps/{step_id} (deed 目录) | moves/{move_id} | 1 |
| gate.json | ward.json | 1 |
| outcome_path (herald_log) | offering_path | 1 |
| archive_path/archive_status | vault_path/vault_status | 2 |

**决策：** 批量执行，不逐条讨论。

---

## §1 设计原则

### 1-1 原则 8："Outcome 零系统痕迹"
- **方案**: "Outcome 零系统痕迹：outcomes/ 中只有人类可读文件"
- **QA**: "offerings/ 零系统痕迹"
- **代码**: `_clean_system_markers()` 存在，写入路径用 `offerings/`
- **Gap**: 方案术语问题（→ §0）。机制本身 ✅

### 1-2 原则 9："Herald = 纯物流"
- 三层一致 ✅

### 1-3 原则 10："Dominion 按需引入"
- 三层一致 ✅

---

## §2 架构

### 2-1 两个进程
- **方案**: API 进程（FastAPI + Cadence + Spine + Psyche）+ Worker 进程（Temporal Worker + Activities）
- **QA**: 一致
- **代码**: api.py + worker.py，一致 ✅

### 2-2 端到端数据流
- **方案**: 用户 → Portal Voice → Router Agent → Brief + Plan → ...
- **Gap**: 术语问题（→ §0）。流程本身 ✅

### 2-3 废弃概念表
- 三层一致 ✅（cluster/SemanticSpec/IntentContract/Strategy/chain 等均已清除）

---

## §3 Psyche

### 3-1 Memory

#### 3-1a 存储与 schema
- **方案**: `{id, content, tags, embedding, relevance_score, created_utc, updated_utc}`
- **代码**: schema = `{entry_id, content, tags, embedding, relevance_score, source, created_utc, updated_utc}`
- **Gap**: 代码多一个 `source` 字段，方案没提。方案没提 domain/tier/confidence 字段
- **❌ warmup.py 传入 domain/tier/confidence/provider/url，schema 无这些列**
- **决策**: warmup.py 的 intake 调用需要重写为使用 `add()` 接口。Memory schema 保持简洁（当前实现），不加 domain/tier 字段——方案和 QA 都没有要求这些字段，是 warmup.py 的旧代码遗留

#### 3-1b intake() 和 query() 方法
- **方案**: 未明确定义 intake/query 方法签名
- **QA**: 未提及
- **代码**: warmup.py 调 `memory.intake()`，console 调 `memory.query()`，均不存在
- **❌ 方法缺失**
- **决策**:
  - `intake()` → warmup.py 改为调用 `memory.add()` 或 `memory.upsert()`，不新增 intake 方法
  - `query()` → 在 MemoryPsyche 上实现，基于现有 `search_by_tags()` + `search_by_embedding()` 组合查询，服务 Console 端点
  - api.py:1313 的 `memory.intake()` 同理改为 `memory.add()`

#### 3-1c 热度衰减 + 合并压缩
- **方案**: 被引用时 relevance 回升，长期不引用衰减。超限先合并再淘汰
- **代码**: `touch()` 回升 ✅，`decay_all()` 衰减 ✅，`enforce_capacity()` 淘汰 ✅，`distill()` 组合 ✅
- **Gap**: 没有"合并相似低分条目"的逻辑，只有淘汰
- **❌ 合并机制缺失**
- **决策**: 暖机前实现。distill() 中加入合并步骤：embedding 相似度 > 阈值的低分条目合并为摘要

#### 3-1d embedding 检索
- **代码**: `search_by_embedding()` 存在 ✅
- **cortex.embed()** 存在 ✅

#### 3-1e 版本化（state/ git repo）
- **方案/QA**: state/ 内建独立 git repo，Spine 修改后自动 commit
- **代码**: tend routine 中有 `_git_commit_state()` ✅
- 三层一致 ✅

### 3-2 Lore

#### 3-2a LoreRecord 结构
- **方案**: `{deed_id, objective_embedding, objective_text, complexity, step_count, plan_structure, outcome_quality, ...}`
- **代码**: 全部字段存在，但名称有差异：`step_count` → `move_count`，`outcome_quality` → `offering_quality`
- **Gap**: 方案用旧名（→ §0 术语更新）。代码用新名，是正确的
- **决策**: 方案术语更新时同步修正 ✅

#### 3-2b 检索公式
- **方案/QA**: `score = sim(embedding) × 0.6 + recency × 0.2 + quality_bonus × 0.2`
- **代码**: `consult()` 方法完全匹配 ✅

#### 3-2c 衰减机制
- **方案**: 带时间戳和使用计数，长期未命中自动衰减
- **代码**: LorePsyche 无显式衰减方法
- **❌ Lore 衰减未实现**
- **决策**: 方案 §4.1 原说"Lore 策略衰减 → librarian"，现改为 curate 职责。需在 curate routine 中加入 Lore 记录衰减逻辑

### 3-3 Instinct

#### 3-3a 全局偏好 key-value
- **方案**: require_bilingual, default_depth, default_format, default_language, pool_size_n, provider_daily_limits, deed_ration_ratio, output_languages
- **代码 bootstrap**: require_bilingual ✅, default_depth ✅, default_format ✅, default_language ✅, pool_size_n ✅, telegram_enabled（方案没提）, pdf_enabled（方案没提）
- **❌ 缺失**: provider_daily_limits, deed_ration_ratio, output_languages 未在 bootstrap 中初始化
- **❌ 名称**: pool_size_n 应为 retinue_size_n
- **决策**:
  - 补充 3 个缺失 key 的 bootstrap 默认值
  - pool_size_n → retinue_size_n（代码和文档同步改）
  - telegram_enabled / pdf_enabled 保留（运行时需要，方案未列但不矛盾）

#### 3-3b 置信度
- **方案/QA**: `confidence = min(sample_count / threshold, 1.0)`
- **代码**: 实现正确 ✅

---

## §4 Spine

### 4-1 Routine 列表

- **方案**: 9 个 routine（漏了 intake 和 judge）
- **QA**: 11 个 routine（含 intake 和 judge）
- **代码**: spine_registry.json 11 个；routines.py 实现了 9 个（无 intake/judge）
- **❌ 三层不一致**
- **决策**（已确认）:
  - **judge → 废弃**：策略概念已废弃（Q4.3），judge 职责无对象。清除 registry + QA
  - **intake → 吸收进 learn**：scout 产出提取归入 learn 子任务。清除 registry + QA
  - **最终 10 个 routine**：pulse, record, witness, learn, distill, focus, relay, tend, curate + （注：方案说 librarian，已改名 curate）
  - 方案和 QA 同步更新为 10 个

### 4-2 Routine 执行保障

#### 4-2a 超时保护
- **方案/QA**: 默认 120s，LLM 密集型 300s
- **代码**: 完全未实现
- **❌ 缺失**
- **决策**: 在 Cadence._run_routine() 中加 asyncio.wait_for() 超时包装。从 spine_registry.json 读取每个 routine 的 timeout 配置

#### 4-2b depends_on
- **代码**: Cadence._check_upstream_deps() 存在 ✅（检查 spine_log 中上游最近状态）

#### 4-2c 故障隔离
- 三层一致 ✅

#### 4-2d 日志
- spine_log.jsonl ✅

#### 4-2e adaptive 调度
- **方案**: 多维信号加权（Psyche 变更频率、用户活跃度、产出质量、错误率、时段感知）
- **代码**: 只用了 2 个信号（learning_rhythm + queue_depth）
- **❌ 信号不足**
- **决策**: 暖机前补充。当前 2 信号可工作，暖机阶段校准后逐步加入更多信号

#### 4-2f 降级记录
- **代码**: `_update_spine_status()` 写 spine_status.json ✅
- **Gap**: degraded_mode 定义在 registry 中但未实际应用
- **决策**: 暖机前完善降级模式应用逻辑

### 4-3 Nerve 事件总线
- 三层一致 ✅（持久化、at-least-once、replay、30 天清理）

### 4-4 自动排障
- 基本一致 ✅
- **Gap**: 排障前应暂停 routine，代码未做
- **决策**: 在 `_run_auto_diagnosis()` 开头加入 routine 暂停逻辑

### 4-5 看门狗
- 基本一致 ✅
- **❌ 文件名错误**: watchdog.sh 检查 `schedule_history.json`，应为 Cadence 实际写入的文件名
- **决策**: 修正 watchdog.sh 中的文件名

### 4-6 系统生命周期
- 三层一致 ✅（5 状态、持久化、API 入口）
- **Gap**: CLI 入口未实现
- **决策**: CLI 生命周期操作不急，暖机后补

---

## §5 Voice

### 5-1 入口分野
- 三层一致 ✅（Portal 唯一提交入口，Telegram 命令式，Console 不提交）

### 5-2 Voice 流程

#### 5-2a Counsel agent 驱动
- **代码**: voice.py 通过 OpenClaw 调 counsel agent ✅

#### 5-2b 双重确认
- **代码**: Voice 做收敛性验证 + 返回 plan 供用户确认 ✅

#### 5-2c Brief 理解摘要
- **方案/QA**: "每轮回复附带当前对 Brief 的理解摘要"
- **代码**: Voice 响应只返回 Counsel 原文，无 Brief 摘要
- **❌ 缺失**
- **决策**: 在 Counsel system prompt 中要求每轮附带 Brief 摘要，或在 voice.py 后处理中提取。暖机时校准

#### 5-2d 草稿保留
- **代码**: _sessions 内存字典，重启清除 ✅

### 5-3 Brief dataclass
- 全部 9 个字段存在 ✅（含别名兼容）

### 5-4 复杂度等级
- 三层一致 ✅（方案术语需更新 → §0）

### 5-5 Plan/Design 验证
- **代码**: Voice 做收敛验证，Will 做结构验证 ✅
- 5 条约束全部实现 ✅

### 5-7 openclaw 收敛配置
- **方案/QA**: 按 agent 类型差异化 loop detection 阈值
- **代码**: 未在代码中找到阈值配置
- **❌ 可能缺失** — 需确认是否在 openclaw.json 中配置
- **决策**: 检查 openclaw.json 中各 agent 的 loopDetection 配置

### 5-8 复杂度特异的 Design 格式（ID §1.2）
- **INTERACTION_DESIGN §1.2**: Errand 无计划组件；Charge 纵向时间线卡片；Endeavor 分段式阶段卡片
- **代码**: voice.py 对所有复杂度返回相同的 plan dict 结构，无格式区分
- **❌ 缺失**
- **决策**: plan dict 中增加复杂度特异的展示元数据。Errand: moves 数组但无 timeline；Charge: 增加 timeline 元数据；Endeavor: 增加 passages 分段元数据

### 5-9 Voice session 无 TTL
- **INTERACTION_DESIGN §1.1**: "未完成的 Voice session 内存保留，重启清除"
- **代码**: voice.py `_sessions: dict` 重启清除 ✅，但无 TTL/过期清理
- **Gap**: 长期不活动的 session 永不清理（内存泄漏）
- **决策**: 加入 TTL 过期机制（如 24h 无活动自动清除）

---

## §6 Will

### 6-1 enrich 流程
- **代码**: 6 阶段全部实现，顺序正确 ✅
  - normalize → complexity_defaults → quality_profile → model_routing → ration_preflight → ward_check

### 6-2 模块组织
- **方案**: will.py + will_enrich.py + will_model.py
- **代码**: 全部合并在 will.py
- **Gap**: 文件拆分未做
- **决策**: 功能完整，文件拆分为低优先级。暖机后如 will.py 膨胀再拆

### 6-3 模型路由
- **代码**: model_policy.json + model_registry.json + cortex.py 完整实现 ✅

### 6-4 Ration 管控
- **代码**: InstinctPsyche 有 consume_ration / all_rations ✅
- **Gap**: MiniMax prompt 次数制（调 /coding_plan/remains）未在代码中找到
- **❌ MiniMax 实时额度查询未实现**
- **决策**: 暖机前实现。cortex.py 中加入 MiniMax remains 查询

### 6-5 Ward
- **代码**: ward.json 读写 ✅，enrich 中 ward_check ✅
- 三层一致 ✅

---

## §7 执行层

### 7-1 Retinue 池
- **代码**: 完整实现（分配/归还/启动恢复/模板填充） ✅
- **Gap**: bootstrap 检查 `retinue_status.json` 但代码写 `pool_status.json`
- **❌ 文件名不一致**
- **决策**: bootstrap.py 改为检查 `pool_status.json`（或两边统一为 `retinue_status.json`）

### 7-2 Deed 生命周期

#### 7-2a Allocation
- **方案**: 分配 → 模板复制 → Psyche 快照写入 → 标记 occupied → 创建主 session
- **代码**: 分配 ✅，模板复制 ✅，标记 occupied ✅
- **❌ Psyche 快照写入未调用**: `write_psyche_snapshot()` 存在但 allocation 流程中未调用
- **决策**: 在 `allocate()` 流程中加入 `write_psyche_snapshot()` 调用

#### 7-2b Execution
- 三层一致 ✅

#### 7-2c Return
- 三层一致 ✅

### 7-3 Move 执行
- Kahn 排序 ✅，checkpoint ✅，heartbeat ✅，abortedLastRun ✅
- **代码路径**: `deed_root/moves/{move_id}/output/output.md`
- **方案路径**: `deed_root/steps/{step_id}/output.md`
- **Gap**: 方案术语问题（→ §0）。代码路径正确

### 7-5 Rework
- 5 维评分 ✅，depth 阈值 ✅，rework_ration ✅
- 三层一致 ✅

### 7-6 Endeavor 阶段管理
- 代码完整实现 ✅（Temporal wait_condition + Signal）

### 7-8 Skill 管理
- **方案**: skill_registry.json 动态选择
- **代码**: config/skill_registry.json 存在，Console 有 skill evolution 端点 ✅

### 7-9 openclaw session 管理
- 三层一致 ✅

### 7-10 Routine 与池配合
- **方案**: relay 在 allocation 时填充 + 定期更新 counsel
- **代码**: relay routine 存在，但 allocation 时是否调用 relay 需确认
- **决策**: 确认 relay 与 allocate 的集成点

---

## §8 交付层

### 8-1 核心约束
- Herald = 纯物流 ✅，零系统痕迹清洗 ✅

### 8-2 Offering 结构
- **代码**: offerings/{YYYY-MM}/{timestamp title}/ ✅
- **方案**: 术语问题（→ §0）

### 8-3 Vault 结构
- **方案**: 说 "Archive"，应为 "Vault"（→ §0）
- **代码**: routines_ops_maintenance.py 用 vault ✅
- **Gap**: curate routine 的 vault 清理逻辑是否完整待确认
- **决策**: 确认 curate 是否实现了 90 天过期清理

### 8-4 Herald 流程
- 代码完整 ✅（写 offering → 写 herald_log → emit herald_completed）

### 8-5 Arbiter 评分
- 5 维 ✅，depth 阈值 ✅

### 8-9 Telegram 推送
- **方案**: errand/charge 完成推一次，endeavor 每 Passage + 最终
- **代码**: telegram adapter 存在，但与主 API 是独立进程
- **Gap**: Telegram webhook 未集成到主 API（`/telegram/webhook` 端点缺失）
- **❌ Telegram adapter 是独立 FastAPI app，非主 API 的一部分**
- **决策**: 当前架构（独立 adapter）是可行的。只需确认 adapter 能正确接收 Nerve 事件。如果是独立进程，它如何得知 deed_completed 事件？→ 需要确认事件传播路径

---

## §9 评价与学习

### 9-1 用户反馈
- **方案/QA**: Chat 内 inline 选择组件
- **代码**: feedback.py 有完整端点（state/submit/questions/append） ✅
- **Gap**: inline 选择组件是前端实现问题，后端 API 支持 ✅

### 9-2 Review/用户冲突
- **方案/QA**: witness 用 LLM 分析冲突
- **代码**: witness routine 存在但冲突分析逻辑待确认
- **决策**: 确认 witness 实现中是否有 review_user_conflict 检测

### 9-4 Deed 完成后的数据流
- record → Lore ✅, learn → Memory ✅, witness → Instinct ✅

### 9-8 暖机
- warmup.py 存在但调用了不存在的 `memory.intake()` → 需修复（见 §3-1b）

---

## §10 Dominion-Writ-Deed

> 权威文档：`.ref/DOMINION_WRIT_DEED.md`。以下按该文档逐节对照代码。

### 10-1 Dominion CRUD
- **代码**: dominion_writ.py CRUD 完整（create/get/update/delete/list）✅
- **Gap**: API 路径在 `/dominions` 而非 `/console/dominions`
- **❌ 路径不符方案 §14.2**
- **决策**: 添加 /console/dominions 路由

### 10-2 Dominion metadata 缺失字段（DWD §1.1）
- **文档要求**: dominion_id, objective, status, writs, max_concurrent_deeds, max_writs, instinct_overrides, created_utc, updated_utc, progress_notes
- **代码实际**:

  | 字段 | 状态 |
  |------|------|
  | dominion_id | ✅ |
  | objective | ✅ |
  | status | ✅ (active/paused/completed/abandoned) |
  | writs | ✅ |
  | created_utc / updated_utc | ✅ |
  | progress_notes | ✅ |
  | `max_concurrent_deeds` | ❌ 缺失（warmup.py 有同名 Instinct pref，但 Dominion 级未存储） |
  | `max_writs` | ❌ 缺失 |
  | `instinct_overrides` | ❌ 缺失 |

- **决策**: create_dominion 的默认值中补入 3 个字段

### 10-3 Writ CRUD
- **代码**: dominion_writ.py CRUD 完整 ✅
- **Gap**: API 路径在 `/writs` 而非 `/console/writs`
- **决策**: 同 10-1

### 10-4 Writ metadata 缺失字段（DWD §1.2）
- **文档要求**: writ_id, dominion_id, label, status, brief_template, trigger, max_pending_deeds, deed_history, split_from, merged_from, created_utc, updated_utc
- **代码实际**:

  | 字段 | 状态 |
  |------|------|
  | writ_id, dominion_id, label, status | ✅ |
  | brief_template, trigger | ✅ |
  | created_utc, updated_utc | ✅ |
  | last_triggered_utc, deed_count | ⊕ 额外字段，合理 |
  | depends_on_writ | ⊕ 实现了依赖机制 |
  | `max_pending_deeds` | ❌ 缺失 |
  | `deed_history` | ❌ 缺失（只有 deed_count 计数，无列表） |
  | `split_from` | ❌ 缺失 |
  | `merged_from` | ❌ 缺失 |

- **决策**: 补入 4 个字段。deed_history 存 deed_id 列表，split_from/merged_from 支持 DAG 拆合

### 10-5 触发链路断裂（DWD §3）

#### 10-5a `cadence.tick` 事件不存在
- **文档 §3.1-3.2**: Cadence 每分钟 tick 一次，评估 cron 表达式，匹配时 emit `cadence.tick`
- **代码**: Cadence 无 `cadence.tick` 产生逻辑
- **❌ cron 触发的 Writ 完全不工作**
- **决策**: 在 Cadence 调度循环中增加 cron 评估 → emit cadence.tick

#### 10-5b `writ_trigger_ready` 无消费者
- **代码**: dominion_writ.py:284 emit `writ_trigger_ready`，但全代码库无 handler 消费此事件
- **❌ Writ 触发后没有任何代码创建 Deed**
- **决策**: 实现 writ_trigger_ready handler：接收 brief_template → 填充 → 调用 Will.enrich() → 提交 Temporal workflow

#### 10-5c brief_template 填充未实现（DWD §3.3）
- **文档**: "dominion_writ.py 负责填充。查 Psyche 拿动态数据，填完后产出完整 Brief 交给 Will"
- **代码**: _on_trigger_fired 只是原样传出 brief_template，未填充任何动态数据
- **❌ 模板填充逻辑缺失**
- **决策**: 在 writ_trigger_ready handler 或 _on_trigger_fired 中实现填充（前序 Deed 产出 + Lore 经验 + Memory 知识 + 时间上下文）

#### 10-5d 自循环保护
- **代码**: filter 中 `"self"` 替换为 writ_id，匹配时跳过 ✅
- **文档**: 一致 ✅

### 10-6 资源限制未实现（DWD §4.2）

| 限制 | 默认值 | 代码状态 |
|------|--------|---------|
| `reserved_independent_slots` | 4 | ❌ 缺失 |
| `max_concurrent_deeds` per Dominion | 6 | ❌ 入口检查缺失 |
| `max_writs` per Dominion | 8 | ❌ 入口检查缺失 |
| `max_pending_deeds` per Writ | 3 | ❌ 入口检查缺失 |

- **决策**: 在 Writ 触发和 Deed 提交入口处加入限制检查。reserved_independent_slots 在 Retinue allocate() 中检查

### 10-7 Dominion 生命周期行为（DWD §4.1, §4.3）

#### 10-7a Dominion pause → Writ 级联
- **文档**: "暂停 Dominion 会暂停其下所有 Writ 的触发"
- **代码**: update_dominion 只改 Dominion status，不级联到 Writ
- **❌ 缺失**
- **决策**: update_dominion 中 status→paused 时自动 pause 所有子 Writ

#### 10-7b Dominion 终止时 Deed 处理
- **文档**: "已运行的 Deed 继续完成。暂停所有 Writ 的新触发"
- **代码**: delete_dominion 直接删除，不处理在运行 Deed
- **❌ 缺失**
- **决策**: Dominion completed/abandoned 时：暂停子 Writ，不杀在运行 Deed

#### 10-7c progress_notes 自动更新
- **文档 §4.3**: "witness routine 在每个 Deed 完成后审视产出，为所属 Dominion 追加 progress note"
- **代码**: witness routine 无 Dominion 相关逻辑
- **❌ 缺失**
- **决策**: witness 中加入 Dominion progress 评估

### 10-8 Psyche 层集成（DWD §6.1）

#### 10-8a Memory dominion-scoped 查询
- **文档**: "Memory 查询增加 dominion_id 过滤维度"
- **代码**: Memory.search_by_tags/search_by_embedding 无 dominion_id 过滤
- **❌ 缺失**
- **决策**: Memory 条目 tags 支持 dominion_id 标签，查询时可按 dominion_id 过滤

#### 10-8b Lore 按 Dominion 聚合
- **文档**: "Lore 经验条目携带 dominion_id。优先取同 Dominion 经验，其次全局"
- **代码**: Lore.consult() 无 dominion_id 过滤
- **❌ 缺失**
- **决策**: Lore record_experience 时写入 dominion_id，consult 时加权优先同 Dominion

#### 10-8c Instinct Dominion-level 覆写
- **文档**: "Dominion 可携带局部偏好覆写。优先级：Dominion 覆写 > 全局 Instinct"
- **代码**: Will.enrich() 只读全局 Instinct
- **❌ 缺失**
- **决策**: Will.enrich() 中检测 dominion_id → 读取 Dominion.instinct_overrides → 覆写对应字段

### 10-9 Will/Planning 层集成（DWD §6.2）

#### 10-9a 复杂度估计
- **文档**: "Will 估算新 Deed 复杂度时，可参考同 Writ 历史 Deed 的实际复杂度"
- **代码**: Will.enrich() 的 complexity_defaults 不考虑 Writ 历史
- **❌ 缺失**
- **决策**: complexity_defaults 阶段加入 Writ 历史查询

### 10-10 Review/Quality 层集成（DWD §6.3）

#### 10-10a Dominion 级质量趋势
- **文档**: "Witness 额外看同 Dominion 的历史质量轨迹"
- **代码**: witness 不区分 Dominion
- **❌ 缺失**
- **决策**: witness 中增加 per-Dominion 质量统计

#### 10-10b Review 侧重可配置
- **文档**: "通过 Instinct Dominion-level 覆写。Arbiter 从 Instinct 读取侧重"
- **代码**: arbiter SOUL.md 无 review_emphasis 机制
- **❌ 缺失**
- **决策**: 依赖 10-8c instinct_overrides 实现，arbiter prompt 中注入 review_emphasis

### 10-11 Herald 层集成（DWD §6.4）
- **文档**: "herald_log.jsonl 条目加 dominion_id 字段"
- **代码**: herald_log 无 dominion_id（已在 §13-4 记录）
- **❌ 缺失**
- **决策**: 见 §13-4

### 10-12 Spine/Witness 层集成（DWD §6.5）

#### 10-12a Dominion objective 进展评估
- **文档**: "如果 Deed 属于某 Dominion，审视产出与 objective 的关系，更新 progress_notes"
- **代码**: witness 无此逻辑
- **❌ 缺失（同 10-7c）**

#### 10-12b Focus 优先级
- **文档**: "Focus routine 决定关注什么时，活跃 Dominion 的紧迫性是一个信号"
- **代码**: focus routine 不考虑 Dominion
- **❌ 缺失**
- **决策**: focus 中加入活跃 Dominion 信号

### 10-13 Agent 上下文注入（DWD §6.6）
- **文档**: "_build_move_context 注入 Dominion objective、Writ label、前序 Deed 关键产出摘要"
- **代码**: _build_move_context 无 dominion/writ 相关逻辑
- **❌ 完全缺失**
- **决策**: 在 _build_move_context 中注入。前提：plan dict 需携带 dominion_id/writ_id

### 10-14 Writ DAG 操作（DWD §7.1）

#### 10-14a Split/Merge
- **文档**: Writ 可拆分/合并，metadata 标记 split_from/merged_from
- **代码**: 无 split/merge 方法
- **❌ 缺失**
- **决策**: dominion_writ.py 加入 split_writ() 和 merge_writs() 方法

#### 10-14b 级联 disable
- **文档**: "禁用 Writ 时子 Writ 级联禁用；merge 节点仅当所有来源都禁用时才级联"
- **代码**: update_writ 只改单条 Writ，无级联
- **❌ 缺失**
- **决策**: update_writ status→disabled 时递归级联子 Writ

### 10-15 生命周期管理（DWD §7.2-7.3）

#### 10-15a Counsel 创建 Dominion
- **文档**: "用户表达长期意图 → counsel 识别 → 内部创建 Dominion"
- **代码**: counsel agent SOUL.md 无 Dominion 创建指令
- **❌ 缺失**
- **决策**: counsel SOUL.md + TOOLS.md 中加入 Dominion 创建/Writ 生成能力

#### 10-15b Counsel 归属决策
- **文档 §7.3**: "counsel 根据语义相似度判断是否归入某个活跃 Dominion"
- **代码**: Voice/counsel 流程不考虑 Dominion 归属
- **❌ 缺失**
- **决策**: Voice 流程中 counsel 判断 Deed 是否应归属某个活跃 Dominion

#### 10-15c Witness 建议完成
- **文档 §7.2**: "witness 检测到 objective 已达成 → 提醒用户确认"
- **代码**: witness 无此逻辑
- **❌ 缺失**
- **决策**: witness 中加入 Dominion objective 达成检测

### 10-16 代码重构状态（DWD §7.4）
- circuits.py 已删除 ✅
- Cadence Circuit 代码已清除 ✅
- dominion_writ.py Writ 重写为工作线模型 — **部分完成**（CRUD 有，行为逻辑缺）
- API 路由重新设计 — **未完成**

---

## §ID 交互设计（对照 INTERACTION_DESIGN.md 全量）

> 权威文档：`.ref/INTERACTION_DESIGN.md`。以下按该文档逐节对照代码。

### ID-1 Portal 范式：Deed = Chat Session（ID §1）

#### ID-1a WebSocket 实时推送
- **文档 §2.1**: "WebSocket 推送，daemon 的进度消息实时出现在 chat 中，计划组件原地刷新"
- **代码**: api.py 无 `@app.websocket("/ws")` 端点。前端 sync.js 仅有 `checkWard()` 轮询
- **❌ 完全缺失**
- **决策**: 实现 WebSocket 端点，订阅 Nerve 事件后推送到前端。事件列表：deed_completed, deed_failed, passage_completed, deed_rework_exhausted, ward_changed, eval_expiring, 常规进度消息

#### ID-1b Deed 聊天消息端点
- **文档 §1.5**: "用户随时可以在 chat 中打字——调整方向、追问进度"
- **代码**: 只有 `POST /deeds/{deed_id}/append`（append_requirement 信号）和 `/redirect`（别名）
- **❌ 无通用聊天消息端点**
- **决策**: 实现 `POST /deeds/{deed_id}/message`，支持自由文本消息（不仅是 requirement 追加）

#### ID-1c Offering 按 deed_id 列举文件
- **文档 §1.4**: "`GET /offerings/{deed_id}/files/` 列出文件，`GET /offerings/{deed_id}/files/{filename}` 下载文件"
- **代码**: 只有 `GET /offerings/{path:path}` 按文件系统路径访问，无 deed_id 映射
- **❌ 缺失**
- **决策**: 实现 deed_id → offering 路径映射端点

#### ID-1d 计划组件原地刷新
- **文档 §1.2**: "组件在 chat 中原地刷新（状态变化时节点颜色 morphing 过渡），不重发消息"
- **代码**: 无原地刷新机制（无 WebSocket = 无实时推送）
- **❌ 缺失（依赖 ID-1a WebSocket）**

#### ID-1e 侧边栏自动聚类
- **文档 §2.1**: "daemon 自动将相关 Deed 归组，用自然语言标签呈现（不暴露 Dominion 术语）"
- **代码**: Portal 侧边栏无归组逻辑
- **❌ 缺失**
- **决策**: Portal API 需提供 Deed 归组信息（按 Dominion 归组 + daemon 生成的自然语言标签）

#### ID-1f Deed 标题自动生成
- **文档 §2.1**: "Deed 标题 = daemon 根据对话内容自动生成"
- **代码**: Deed 记录中标题来自 plan dict，Voice 不自动生成标题
- **❌ 缺失**
- **决策**: Voice 或 Will 流程中自动生成 Deed 标题

### ID-2 执行控制（ID §1.5）

#### ID-2a Pause/Resume/Cancel/Retry
- **代码**: 全部实现 ✅
  - `POST /deeds/{deed_id}/pause` → Temporal signal → 当前 Move 完毕后挂起
  - `POST /deeds/{deed_id}/resume` → 恢复
  - `POST /deeds/{deed_id}/cancel` → Temporal cancel → 已完成产出保留
  - `POST /deeds/{deed_id}/retry` → 新 Deed ID 重新执行

#### ID-2b 用户消息自动暂停
- **文档 §1.5**: "daemon 收到用户消息后自动暂停当前执行、理解调整意图、重新规划、展示新计划"
- **代码**: append_requirement 注入下一个 Move 指令，不暂停执行
- **❌ 缺失**
- **决策**: 收到用户消息时自动暂停（除非是简单追问），处理完成后自动恢复

#### ID-2c 异常处理流程
- **文档 §1.5**: 局部异常 → 自行绕过告知；致命异常 → rework 预算耗尽 → failed → chat 消息
- **代码**: rework 机制存在 ✅，但 chat 消息发送依赖 WebSocket（ID-1a）
- **Gap**: 异常发生时无法实时通知用户（无 WebSocket）

### ID-3 反馈机制（ID §1.6-1.7）

#### ID-3a Inline 选择组件数据映射
- **文档 §1.6**: 4 级选择 → satisfactory/acceptable/unsatisfactory/wrong；5 项问题多选
- **代码**: feedback.py 有完整端点（state/submit/questions/append）✅
- **Gap**: 后端 API 支持完整，前端 inline 组件是 UI 实现问题

#### ID-3b Passage 级轻量反馈（👍/👎）
- **文档 §1.3**: "Passage 完成消息末尾附加 👍/👎 按钮…此信号记入 Lore 供 Arbiter 参考，但不计为 user_feedback"
- **代码**: 无 Passage 级反馈机制，只有 Deed 级 feedback
- **❌ 缺失**
- **决策**: 实现 Passage 级反馈端点 + Lore 存储

#### ID-3c awaiting_eval 时间窗口
- **文档 §1.7**: "awaiting_eval 过期（48 小时后自动转 completed + feedback_expired=true）"
- **代码**: 默认 eval_window_hours = 2（不是 48），且过期时不设 `feedback_expired=true` 标志（只删除 eval_deadline_utc）
- **❌ 默认值不符文档；feedback_expired 标志缺失**
- **决策**: 默认值改为 48 小时；过期时设置 `feedback_expired: true`

#### ID-3d 过期前 12 小时 Telegram 提醒
- **文档 §1.7**: "过期前 12 小时 Telegram 提醒一次"
- **代码**: adapter.py 定义了 `eval_expiring` 事件格式，但 Cadence 无任何触发逻辑
- **❌ 事件已定义但从未触发**
- **决策**: Cadence._tick_eval_windows() 中加入 12 小时预警检查 + emit eval_expiring

### ID-4 Telegram 通道（ID §2.2）

#### ID-4a /status 命令
- **文档 §2.2**: "/status → 当前进行中的 Deed 列表"
- **代码**: adapter.py webhook 显式忽略所有用户输入（`return {"ok": True, "ignored": True}`）
- **❌ 完全缺失**
- **决策**: adapter.py 实现 /status 命令处理

#### ID-4b /cancel 命令
- **文档 §2.2**: "/cancel → 取消指定 Deed（弹出编号选择）"
- **代码**: 同上，webhook 忽略所有输入
- **❌ 完全缺失**
- **决策**: adapter.py 实现 /cancel 命令处理 + 内存状态机

#### ID-4c 状态机与超时
- **文档 §2.2**: "adapter 内存状态机，超时 60 秒清除"
- **代码**: 无状态机实现
- **❌ 缺失**
- **决策**: 实现命令交互状态机（/cancel 选择编号流程），60 秒超时自动清除

#### ID-4d 非命令消息处理
- **文档 §2.2**: "非命令消息一律忽略"
- **代码**: webhook 忽略所有消息（包括命令）✅ — 但过度忽略
- **Gap**: 应区分命令和非命令，命令要处理

### ID-5 通知路由（ID §3）

#### ID-5a 事件→通道路由表
- **文档 §3.1**: 定义了 7 个 Nerve 事件 → Portal + Telegram 的路由规则
- **代码**: Telegram 推送通过 `_notify_via_adapter()` 实现 ✅；Portal 推送完全缺失（无 WebSocket）
- **❌ Portal 侧通知路由完全缺失**

#### ID-5b 通知失败降级链
- **文档 §3.2**: "Telegram 重试 3 次指数退避 → macOS 桌面通知 → ~/daemon/alerts/ 日志 → 失败队列"
- **代码**:
  - 重试 3 次 ✅（cadence.py:555-581），但无指数退避（线性重试）
  - macOS 桌面通知 ❌ 完全缺失
  - ~/daemon/alerts/ 日志 ❌ 完全缺失
  - 失败队列 ✅（ledger.py notify_queue.jsonl）
- **❌ 降级链只有首尾，中间两级缺失；重试无退避**
- **决策**: 实现指数退避；实现 macOS 通知（`osascript -e 'display notification'`）；实现 alerts/ 文件兜底

#### ID-5c Dominion 主动沟通
- **文档 §3.3**: "witness routine 发现值得沟通的进展 → Nerve 事件 → Voice 生成自然语言 → Herald 推送"
- **代码**: witness 无 Dominion 主动沟通逻辑（同 10-7c）
- **❌ 缺失**

### ID-6 周期任务用户感知（ID §4）

#### ID-6a 自然语言创建 cron Writ
- **文档 §4**: "用户在 Portal 对话中自然表达持续关注意图 → daemon 内部创建 cron Writ"
- **代码**: counsel agent 无 Writ 创建能力（同 10-15a）
- **❌ 缺失**

#### ID-6b 自然语言停止/调整 Writ
- **文档 §4**: "用户在 Portal 对话中说'X 不用看了' → daemon 内部 disable Writ"
- **代码**: counsel agent 无 Writ 管理能力
- **❌ 缺失**

### ID-7 Dominion 推进用户交互（ID §5）
- **文档 §5**: "Dominion 推进对用户不可见。witness 观察 → Voice 生成自然语言 → Telegram 推送"
- **代码**: 同 10-7c + ID-5c，witness 无此逻辑
- **❌ 缺失**

### ID-8 进度消息（ID §1.3）

#### ID-8a 执行中进度消息格式
- **文档 §1.3**: 6 种情况定义了 Portal（chat 消息）和 Telegram 推送的分别行为
- **代码**: 进度消息依赖 WebSocket（ID-1a），当前无实时推送
- **❌ 后端需生成进度消息事件，前端需 WebSocket 接收**

#### ID-8b Endeavor Passage 完成通知
- **文档 §1.3**: "Endeavor Passage 完成 → daemon 发消息：阶段摘要 + 下一阶段计划 + 👍/👎 → Telegram 推送摘要"
- **代码**: activities_endeavor.py:171 emit `endeavor_passage_recorded` ✅；adapter.py 有 `passage_completed` 格式 ✅
- **Gap**: 摘要内容生成、下一阶段计划描述、👍/👎 组件均缺失

### ID-9 完成通知格式（ID §1.4）

#### ID-9a Portal 完成消息格式
- **文档 §1.4**: "摘要 + Offering 预览（文本显示开头摘要，PDF 显示缩略图，代码显示 diff 摘要）+ bilingual 并列 + '查看完整结果'链接"
- **代码**: herald_completed 事件有 summary 字段 ✅，但无预览差异化（文本/PDF/代码）、无 bilingual 并列
- **❌ 预览差异化和 bilingual 并列缺失**

#### ID-9b Telegram 完成通知格式
- **文档 §1.4**: "做好了。\n\n[1-2句摘要]\n\n完整结果：[Portal 链接]"
- **代码**: adapter.py:110-116 格式匹配 ✅

#### ID-9c 通知时机
- **文档 §1.4**: "Herald 完成交付后立即推送。Portal = WebSocket 实时。Telegram = Herald activity 内同步调用"
- **代码**: Telegram 通过 Herald → adapter POST ✅；Portal 无 WebSocket（ID-1a）
- **Gap**: Portal 推送依赖 WebSocket

---

## §12 Console + Portal 设计原则审计

### 12-P1 设计原则（用户确认）

1. **Portal 和 Console 使用者不是同一个人，persona 不同**：Portal 使用者是 daemon 的主人（owner），通过自然语言表达意图；Console 使用者是系统维护者（maintainer），对系统内部不一定有很好的理解，职责是保障系统运转，不替主人做决策
2. **隐私边界**：主人的私人内容对维护者不可见。Psyche（Memory/Lore/Instinct）、Dominion objective、Deed Brief/内容、Writ brief_template、Move 产出、Offering 内容均属主人隐私。Console 只展示运维所需的系统数据（健康/状态/资源/日志）。将主人的隐私交给维护者查看或修改是安全危险
3. **Console 和 Portal 统一设计风格**
4. **Console 禁止原始文件编辑**：不出现编辑 JSON/Markdown/文档文件的方式。用选项、按钮、下拉栏，简洁美观
5. **原因**：维护者对系统内部不一定有很好的理解。随便改了出问题不会解决
6. **Console 可操作范围**：Routine 开关/触发、系统生命周期、Ward 手动覆盖、Provider 模型分配/配额、Retinue size、Dominion/Writ 运维（暂停/恢复/删除）
7. **Console 不可操作**：Dominion/Writ 创建和内容编辑、Psyche 任何查看或编辑、Instinct 偏好、Norm 质量配置、任务提交
8. **双语**：Portal 和 Console 同步切换。系统术语不翻译（Deed, Writ, Dominion, Spine 等），其余部分翻译
9. **术语词典**：Console 内置术语说明

### 12-P2 设计风格一致性

#### ✅ 已满足

- **配色完全统一**：Console 和 Portal 使用相同 CSS 变量（--bg: #faf9f7, --accent: #c96940 等）
- **暖色调 Claude 风格**：陶土/沙色 accent，米色背景，圆角卡片（6-14px），微阴影
- **字体一致**：system-ui sans-serif + SF Mono 代码字体
- **深色模式**：两端同步支持
- **状态徽标**：统一配色（green=ok, red=error, amber=warning）

### 12-P3 双语支持

#### ✅ 已满足

- **Portal**: `interfaces/portal/js/i18n.js`（92 行），~45 个翻译条目
- **Console**: `interfaces/console/js/core.js:63-243`，80+ 个翻译条目
- **跨窗口同步**：localStorage `d_lang` 键 + storage 事件监听，Portal 和 Console 切换同步
- **系统术语不翻译** ✅：Deed, Spine, Psyche, Nerve, Ward, Offering 等在中英文界面中均保持英文原文
- **非系统文本翻译** ✅："待处理/Pending"、"进行中/Running"、"编辑/Edit" 等

### 12-P4 术语词典

#### ✅ 已满足

- **Lexicon 面板**：`interfaces/console/js/panels/lexicon.js`，~50 个术语条目
- **每个条目包含**：term（英文术语）、type（分类）、zh（中文定义）、en（英文定义）、exZh（中文示例）、exEn（英文示例）
- **支持搜索和过滤**
- **随语言切换自动切换定义语言**

### 12-P5 ❌ Console 原始编辑违反设计原则

**核心问题**：Console 有一个 `<textarea id="unified-editor-text">` 统一编辑器（index.html:503），用于原始 JSON/Markdown 编辑。以下编辑流程直接暴露原始文件内容：

| 编辑对象 | API 端点 | 违反方式 |
|---------|---------|---------|
| Norm 质量配置 | `PUT /console/norm/quality/{key}` | textarea 编辑原始 JSON 规则对象 |
| Model Policy | `PUT /console/model-policy`（UI 就绪但后端未实现） | textarea 编辑 model_policy.json |
| Model Canon | `PUT /console/model-canon`（UI 就绪但后端未实现） | textarea 编辑 model_registry.json |
| Agent SKILL.md | `PUT /console/agents/{agent}/skills/{skill}` | textarea 编辑原始 Markdown |

**问题具体表现**：
1. 用户看到的是 JSON 文本块，不知道哪些字段可以改、哪些不能改
2. 改错 JSON 格式（漏逗号、多引号）→ 提交后报错，但错误信息不够指导性
3. SKILL.md 是 Markdown 自由文本，改了可能导致 agent 行为异常
4. 没有"这个改动会产生什么后果"的提示

**应改为**：

| 编辑对象 | 应有的交互方式 |
|---------|-------------|
| Norm 质量配置 | 表格形式：每个 key 一行，值用 input/select/slider，字段说明 tooltip |
| Norm 偏好 | key + 值输入框（已基本满足，但需加选项提示） |
| Norm 配额 | resource_type + 数字输入 + 单位说明（已基本满足） |
| Model Policy | agent 列表 × 模型下拉选择器，不暴露 JSON 结构 |
| Model Canon | 模型卡片列表，每个模型的参数用表单控件编辑 |
| Agent SKILL.md | **Console 不应提供 SKILL.md 编辑**。这是 agent 行为定义，应由开发者维护，不由维护者改 |

**决策**：
1. 移除 unified-editor-text textarea 的原始 JSON 编辑模式
2. 所有配置编辑改为结构化表单（输入框 + 下拉 + 开关 + 滑块）
3. Agent SKILL.md 编辑从 Console 移除（或改为只读查看）
4. Model Policy/Canon 改为表格选择器
5. 每个可编辑字段加简短说明，告知用户改动影响

### 12-P6 ❌ Console 缺少操作确认和影响提示

- 编辑操作无"你确定要修改 X 吗？这会影响 Y"的确认
- 无改动前后对比（diff 预览）
- 无"恢复默认值"按钮（有版本回滚但不够直观）
- **决策**：所有修改操作加二次确认 + 影响说明 + diff 预览

### 12-P8 ❌ Console 用语未完全对齐系统术语

**原则**：Console 面向系统操作者，必须使用系统术语，不用用户面语言。系统术语全部英文，不翻译。

#### 12-P8a Lexicon 定义文本混用用户面中文

| lexicon.js 行 | 术语 | 问题文本 | 应改为 |
|---------------|------|---------|--------|
| ~37 | Errand | "**步骤**短" | "Move 少" |
| ~45 | Charge | "多**步骤**但仍是单次闭环交付" | "多 Move 但仍是单次闭环交付" |
| ~53 | Endeavor | "**阶段确认**、**段落反馈**" | "Passage 确认、Passage 反馈" |
| ~93 | passage_status | "Endeavor **段落**结果状态" | "Endeavor Passage 结果状态" |
| ~117 | Weave Plan | "Counsel **产出**的具体执行图" | "Counsel 生成的具体执行图" |

**决策**：Lexicon 定义中的中文描述，凡涉及系统概念的词一律用英文系统术语原文（Move, Passage, Offering, Design 等），不翻译为"步骤/段落/产出/计划"

#### 12-P8b Lexicon 缺失核心术语条目

| 缺失术语 | 说明 |
|---------|------|
| Move | DAG 中的执行单元 |
| Arbiter | 质量审查 agent |
| Design | Counsel 生成的执行方案 |
| Dominion | 长期目标容器 |
| Writ | Dominion 下的工作线 |
| Will | Brief 富化流程 |
| Passage | Endeavor 的阶段单元 |
| Herald | 交付物流 |
| Counsel | 对话收敛 agent |
| Retinue | Agent 实例池 |
| Cadence | 调度器 |
| Cortex | LLM 调用层 |

**决策**：补全所有系统术语。Lexicon 应是系统术语的完整参考手册

#### 12-P8c trails.js 后端字段兼容

- `trails.js:56`：`t.moves || t.steps`——代码兼容旧字段名 `steps`
- 如果后端已统一为 `moves`，前端应移除 `t.steps` 回退
- **决策**：确认后端字段名，前端移除兼容代码

### 12-P7 缺失端点汇总

| 端点 | 状态 |
|------|------|
| `/console/dashboard` | ❌ 缺失 |
| `/console/retinue` | ❌ 缺失 |
| `/console/routines` + toggle | ❌ 缺失（有 /console/schedules 但名称不一致） |
| `/console/logs/{type}` | ❌ 缺失 |
| `/console/psyche/{component}/{id}` DELETE | ❌ 缺失 |
| `/console/config/{key}` GET/PUT | ❌ 只有 rollback |
| `/console/dominions` | ❌ 路径在 / 下而非 /console/ 下 |
| `/console/writs` | ❌ 路径在 / 下而非 /console/ 下 |
| `PUT /console/model-policy` | ❌ UI 就绪但后端未实现 |
| `PUT /console/model-canon` | ❌ UI 就绪但后端未实现 |
| `POST /console/model-policy/rollback/{version}` | ❌ UI 就绪但后端未实现 |
| `POST /console/model-canon/rollback/{version}` | ❌ UI 就绪但后端未实现 |

---

## §14 API

### 缺失端点汇总

| 端点 | 状态 | 优先级 |
|------|------|--------|
| `/ws` WebSocket | ❌ 缺失 | 暖机前 |
| `/deeds/{deed_id}/message` | ❌ 缺失 | 暖机前 |
| `/telegram/webhook` | ❌ 独立 adapter | 确认架构 |

---

## §16 Bootstrap

### 16-1 retinue 状态文件名
- **代码**: bootstrap 检查 `retinue_status.json`，retinue.py 写 `pool_status.json`
- **❌ 不一致**
- **决策**: 统一为一个文件名

---

## §11 自我进化

### 11-1 §11 整体状态
- **方案**: 5 个子系统（Skill 发现、模板进化、模型进化、代码自修改、持续校准）
- **代码**: 几乎完全未实现
- **预期**: §11 属于暖机/暖机后功能，当前不实现是合理的

### 11-2 具体对齐

| 子系统 | 代码状态 | 说明 |
|--------|----------|------|
| Skill 发现 + benchmark | ❌ 无 | 暖机后功能 |
| 模板进化（[evolution] commit） | ❌ 无 | 暖机后功能 |
| 模型策略进化（experimental → promote） | ❌ 无 | 暖机后功能 |
| 代码自修改 + Claude Code 通道 | ❌ 无 | 暖机后功能 |
| system_health.json 写入 | ✅ `routines_ops_learn.py:56` | witness 写入 |
| calibration_period | ❌ 无 | 暖机后功能 |

- **决策**: §11 不列为 gap。暖机前只需确保 system_health.json 写入正常（已实现）。其余暖机后按方案逐步搭建

---

## §13 数据模型与存储

### 13-1 state/ 目录结构

| 方案中的文件 | 代码实际 | 状态 |
|-------------|---------|------|
| `memory.db` | `memory.db` | ✅ |
| `lore.db` | `lore.db` | ✅ |
| `instinct.db` | `instinct.db` | ✅ |
| `dominions.json` | `dominions.json` | ✅ |
| `writs.json` | `writs.json` | ✅ |
| `deeds/{deed_id}/plan.json` | `plan.json` | ❌ 方案说 plan.json，§0 说应为 design.json |
| `deeds/{deed_id}/steps/{step_id}/output.md` | `moves/{move_id}/output/output.md` | ❌ 方案用旧路径。代码用新路径但内部不一致（见 13-2） |
| `spine_log.jsonl` | `spine_log.jsonl` | ✅ |
| `spine_status.json` | `spine_status.json` | ✅ |
| `events.jsonl` | `events.jsonl` | ✅ |
| `cortex_usage.jsonl` | `cortex_usage.jsonl` | ✅ |
| `herald_log.jsonl` | `herald_log.jsonl` | ✅ |
| `system_status.json` | `system_status.json` | ✅ |
| `system_health.json` | `system_health.json` | ✅ |
| `gate.json` | `ward.json` | ✅ 代码已改名，方案需改（→ §0） |
| `console_audit.jsonl` | ❌ 不存在 | ❌ 完全未实现 |
| `daily_stats.jsonl` | ❌ 不存在 | ❌ 完全未实现 |
| `pool_status.json` | `pool_status.json` | ✅ |

### 13-2 Move 输出路径不一致（BUG）
- **写入方**（activities.py:307-311）: `moves/{move_id}/output/output.md` ✅
- **读取方 1**（activities.py:288）: `moves/*/output/output.md` ✅
- **读取方 2**（routines_ops_learn.py:102）: `moves/*/output.md` ❌
- **❌ BUG：learn routine 用错误路径读取，永远找不到 move 产出**
- **决策**: P0 修复。`routines_ops_learn.py:102` 改为 `deed_root.glob("moves/*/output/output.md")`

### 13-3 Deed plan 存储方式
- **方案 §13.2**: `deeds/{deed_id}/plan.json`（per-deed 文件）
- **代码**: plan 存储在全局 `state/deeds.json`（ledger.py:29），非 per-deed 文件
- **代码**: vault 归档时复制 `plan.json`（routines_ops_maintenance.py:181），但运行时 deed_root 下无 plan.json
- **§0 术语**: plan.json → design.json
- **❌ 方案和代码存储方式不同；方案和代码都用旧名**
- **决策**: 保持代码当前设计（全局 deeds.json），方案 §13.2 更新目录结构（移除 per-deed plan.json）。vault 归档中的文件名改为 design.json

### 13-4 herald_log 字段
- **方案 §13.4**:

  | 方案字段 | 代码实际字段 | 状态 |
  |---------|------------|------|
  | `outcome_path` | `path` | ❌ 字段名不同 |
  | `completed_utc` | `delivered_utc` | ❌ 字段名不同 |
  | `archive_path` | 无 | ❌ 缺失（vault 独立管理） |
  | `archive_status` | 无 | ❌ 缺失 |
  | `complexity: "thread"` | `complexity: "charge"/"errand"/"endeavor"` | ❌ 方案用旧值 |
  | `writ_id` | 无 | ❌ 缺失 |
  | `dominion_id` | 无 | ❌ 缺失 |
  | `user_feedback` | 无 | ❌ 缺失（feedback_surveys/ 独立存储） |
  | — | `title` | ⊕ 代码额外字段 |
  | — | `deed_id` | ⊕ 代码额外字段 |

- **决策**: 方案 §13.4 需重写以匹配代码实际结构。代码字段名（`path`, `delivered_utc`）是合理的设计。`writ_id`/`dominion_id` 应补入 herald_log 以支持 Dominion 查询

### 13-5 外部存储路径
- **方案 §13.3**: `~/My Drive/daemon/outcomes/` + `~/My Drive/daemon/archive/`
- **代码**: 使用 `offerings/` ✅
- **Gap**: 方案术语问题（→ §0）

### 13-6 存储层次
- **方案 §13.1**: L0 Nerve → L1 state/ → L2 snapshots/traces → L3 Drive archive
- **方案 §13.1**: "L3 Drive archive — librarian 归档"
- **Gap**: 方案 L3 用 "librarian" → 应为 "curate"（→ §0）

### 13-7 console_audit.jsonl 未实现
- **方案 §12.3**: "每次编辑写入 console_audit.jsonl。tend 清理 90 天前记录"
- **代码**: 无任何 console_audit 写入或读取
- **❌ 完全缺失**
- **决策**: 暖机前实现。Console 编辑操作通过 Ledger 写入 console_audit.jsonl

### 13-8 daily_stats.jsonl 未实现
- **方案 §17.4**: daily_stats.jsonl 列为暖机前必做
- **代码**: 无任何 daily_stats 写入或读取
- **❌ 完全缺失**
- **决策**: 暖机前实现。tend routine 每日聚合生成

---

## §15 Config 文件

### 15-1 model_policy.json
- 三层一致 ✅（agent_model_map 使用新术语：counsel/scout/sage/artificer/arbiter/scribe/envoy）

### 15-2 model_registry.json
- 三层一致 ✅（fast/analysis/review/glm/embedding 全部存在）

### 15-3 skill_registry.json
- **方案**: `compatible_agents: ["build"]`
- **代码**: `compatible_agents: ["artificer"]` ✅
- **Gap**: 方案术语问题（→ §0）

### 15-4 agent_capabilities.json
- **方案 §15.4**: "每种 agent 的能力描述（LLM plan 生成时的输入）"
- **代码**: 文件不存在
- **❌ 缺失**
- **决策**: 暖机前创建。内容 = 每种 agent 角色的能力描述，供 Counsel 在 design 生成时参考

---

## §17 质量保障

### 17-1 质量四层来源
- **方案**: 用户显式 > Lore > Instinct > 系统默认
- **代码**: Will.enrich() 中有 complexity_defaults + quality_profile 阶段，Lore.consult() 存在
- **Gap**: 优先级顺序未在代码中显式执行（隐式通过 enrich 阶段顺序实现）
- **决策**: 当前可接受。暖机时观察是否需要显式优先级

### 17-2 不可协商底线
- **方案**: forbidden_markers、language_consistency、format_compliance、academic_format
- **代码**: `format_compliance` 仅作为 arbiter 评分维度名（workflows.py:386），非独立检查
- **❌ 四项底线检查均未实现为独立机制**
- **决策**: 暖机前实现。在 Herald activity（delivery 前）加入底线检查：
  - `forbidden_markers`: 确定性正则检查（已有 `_clean_system_markers()`，需加 fail-if-found）
  - `language_consistency`: Brief.language 与产出语言一致性
  - `format_compliance`: PDF 可渲染、code 语法正确
  - `academic_format`: 学术文体检查引用规范

### 17-3 Rework 阈值
- **方案**: `brief/standard/thorough`（旧术语）
- **代码**: `glance/study/scrutiny` ✅（workflows.py:376-379，值完全匹配）
- **Gap**: 方案术语问题（→ §0）。机制本身 ✅

### 17-4 必做的生产机制

| 机制 | 方案要求 | 代码状态 |
|------|---------|---------|
| API 熔断 | 暖机前 | ✅ 部分（openclaw abortedLastRun 检测） |
| 磁盘空间监控 | 暖机前 | ✅ 部分（routines.py:211 shutil.disk_usage） |
| 配置迁移 | 暖机前 | ✅（instinct.py config_versions） |
| 通知失败队列 | 暖机前 | ✅（ledger.py notify_queue.jsonl） |
| 备份恢复 | 暖机前 | ✅（routines_ops_maintenance.py _backup_state） |
| Console 审计日志 | 暖机前 | ❌ console_audit.jsonl 未实现 |
| daily_stats.jsonl | 暖机前 | ❌ 未实现 |

---

## 代码层独立问题（不对应方案章节）

### X-1 console_spine_fabric.py 文件名
- "fabric" 应为 "psyche"
- **决策**: 重命名为 `console_spine_psyche.py`，更新 api.py import

### X-2 _utc() 重复定义
- 7+ 个文件独立定义相同的 `_utc()` 函数
- **决策**: 低优先级，暖机后统一

### X-3 test_temporal.py 测试问题
- setup_method 多余参数 tmp_path_factory
- DAEMON_HOME 环境变量未清理
- **决策**: 修复测试

---

## §0 方案术语补充（逐节定位）

在 §0 批量替换表的基础上，以下是按节定位的具体旧术语出处（确保执行人不遗漏）：

| 方案节 | 行号区间 | 旧术语 | 说明 |
|--------|---------|--------|------|
| §4.1 | L135 | "gate 设定" | → "ward 设定" |
| §4.1 | L141 | "router agent" | → "counsel agent" |
| §4.1 | L143 | "librarian" routine 名 | → "curate" |
| §4.1 | L150 | "Lore 策略衰减 → librarian" | → "→ curate" |
| §7.1 | L421 | "6 角色 × 24 + router" | → "+ counsel" |
| §7.3 | L472 | "Router 在 plan 生成阶段" | → "Counsel 在 design 生成阶段" |
| §7.3 | L476 | `deed_root/steps/{step_id}/output.md` | → `moves/{move_id}/output/output.md` |
| §7.3 | L478 | `max_parallel_steps` | → `max_parallel_moves` |
| §7.4 | L483 | `deed_root/steps/{step_id}/output.md` | → `moves/{move_id}/output/output.md` |
| §7.5 | L488-490 | "review agent"、`pulse=0, thread=1` | → "arbiter agent"、`errand=0, charge=1` |
| §7.5 | L492 | "Router 分析" | → "Counsel 分析" |
| §7.8 | L518 | "Router 在 plan 生成时" | → "Counsel 在 design 生成时" |
| §7.10 | L532 | "router agent" | → "counsel agent" |
| §8.1 | L543-549 | "outcomes/"（多处） | → "offerings/" |
| §8.1 | L545-546 | "review agent" | → "arbiter agent" |
| §8.2 | L551-554 | "Outcome 结构"、"outcomes/" | → "Offering"、"offerings/" |
| §8.3 | L564-577 | "Archive 结构"、"archive/"、"librarian" | → "Vault"、"vault/"、"curate" |
| §8.4 | L582-585 | "outcome"、"librarian" | → "offering"、"curate" |
| §8.5 | L588-607 | "review agent"、`brief/standard/thorough` | → "arbiter agent"、`glance/study/scrutiny` |
| §8.6 | L618-620 | "render agent" | → "scribe agent" |
| §8.8 | L629-633 | "Outcome"、"Archive"、"outcomes"、"archive"、"librarian" | → 新术语 |
| §8.9 | L637 | `pulse/thread` | → `errand/charge` |
| §9.7 | L720 | `pool_size_n` | → `retinue_size_n` |
| §10 | L736 | `TRACK_LANE_RUN.md` | → `DOMINION_WRIT_DEED.md` |
| §12.1 | L859 | "Gate 状态查看" | → "Ward 状态查看" |
| §12.1 | L861 | "Pool size N 调整" | → "Retinue size N 调整" |
| §13.1 | L907 | "librarian 归档" | → "curate 归档" |
| §13.2 | L922 | `plan.json` | → `design.json` |
| §13.2 | L925 | `steps/{step_id}/output.md` | → `moves/{move_id}/output/output.md` |
| §13.2 | L933 | `gate.json` | → `ward.json` |
| §13.3 | L944 | `outcomes/` | → `offerings/` |
| §13.3 | L946 | `archive/` | → `vault/` |
| §13.4 | L957-961 | `outcome_path`、`archive_path`、`archive_status`、`"thread"` | → `offering_path`、`vault_path`、`vault_status`、`"errand"/"charge"` |
| §15.3 | L1063 | `compatible_agents: ["build"]` | → `["artificer"]` |
| §16.1 | L1084 | "6 角色 × N + router" | → "+ counsel" |
| §17.3 | L1131-1133 | `brief/standard/thorough` | → `glance/study/scrutiny` |

---

## 跨层机制审计 ①：系统错误处理全链路

> 本章按用户思路（跨层功能链路）组织，不按文档章节。
> 设计意图：Claude Code 是系统出错时的第一响应者，人类维护者是最后手段。

### 现状：错误处理完整链路追踪

#### E-1 Move 执行失败（activities_exec.py）

| 场景 | 返回状态 | 处理方式 | 后续 |
|------|---------|---------|------|
| OpenClaw agent 调用成功 | `ok` | 写 checkpoint，继续 | — |
| 超时（默认 480s） | `degraded` | 保存部分内容到 checkpoint | workflow 继续（不算失败） |
| 循环检测（abortedLastRun） | `circuit_breaker` | 保存部分内容 | workflow 继续 |
| Deed 被取消 | `cancelled` | 写 checkpoint，释放 retinue | 重新抛出 CancelledError |
| 发送/轮询异常 | `error` | 累积到 errors 列表 | workflow 看全部 Move 结果 |

- 轮询间隔：5s 起，poll 失败时 ×1.2，上限 30s（指数退避 ✅）
- checkpoint 路径：`deed_root/moves/{move_id}/output.json`，重试时恢复

#### E-2 Workflow 错误汇总（workflows.py）

| 阶段 | 错误类型 | 处理 |
|------|---------|------|
| DAG 校验 | 缺 move / 重复 ID / 自依赖 / 环 | `ApplicationError(non_retryable=True)` → deed failed |
| Retinue 分配 | 无可用实例 | `ApplicationError(non_retryable=True)` → deed failed |
| Move 执行 | 个别 Move error | 累积到 errors 列表，不立即终止 workflow |
| 死锁检测 | 无可运行 Move 但未完成 | `ApplicationError("deadlock")` → deed failed |
| 全部 Move 失败 | errors 非空且无成功完成 | `ApplicationError` → deed failed |
| 未预期异常 | 任何 Exception | 标记 deed failed + 释放 retinue |
| 取消 | CancelledError | 标记 cancelled + 释放 retinue + 重新抛出 |

- Retinue 释放始终在 finally 路径（`_release_retinue_safe()`，best-effort，失败不抛）

#### E-3 Arbiter 驱动的 Rework（workflows.py:246-270）

| 步骤 | 代码位置 | 行为 |
|------|---------|------|
| 找到 arbiter 结果 | `_last_arbiter_result()` | 从 results 反向搜索 agent=="arbiter" |
| 判断是否需要 rework | `_needs_rework()` | 3 种判据：显式 verdict / 结构化评分 / 状态字段 |
| 评分阈值 | workflows.py:376-380 | glance: cov≥0.5 depth≥0.4；study: 0.6/0.6；scrutiny: 0.7/0.7 |
| 选择 rework moves | `_rework_moves()` | 按错误类别选 agent：收集问题→scout+sage+scribe，其他→arbiter+scribe |
| 重试次数 | `plan["rework_ration"]` | 默认 2 次 |
| **预算耗尽** | **循环结束** | **❌ 不失败，直接继续到 Herald** |

- **Gap E-3a**: rework 预算耗尽后 deed 不失败——arbiter 仍然认为质量不合格，但 Herald 照常交付。文档 §1.5 说"rework 预算耗尽 → Deed 状态转 failed"，代码未执行此逻辑
- **❌ rework 耗尽应导致 deed failed + 通知用户，当前静默交付低质量产出**

#### E-4 Endeavor Passage 失败（endeavor_workflow.py）

| 场景 | 处理 |
|------|------|
| Passage 内所有 Move ok/degraded | passage = passed，继续下一个 |
| Passage 有 error/circuit_breaker | 重试（最多 passage.objective_rework_ration 次，默认 2） |
| 重试耗尽仍失败 | 状态 → `awaiting_intervention`，等待用户决定 |

- Endeavor 的错误处理比单次 Deed 更完善——失败时不静默继续，而是暂停等待用户

#### E-5 Spine Routine 失败 → 自动诊断（routines.py:293-434）

| 步骤 | 行为 |
|------|------|
| 检测 | 扫描 spine_log.jsonl，找连续 3 次 error 的 routine |
| 冷却 | 每个 routine 24 小时内最多 3 次诊断（`auto_diagnosis_cooldown.json`） |
| 诊断 | 调用 Claude Code CLI：`claude --print -p "{prompt}"`，超时 600s |
| 验证 | 诊断成功后重跑该 routine，确认修复 |
| 报告 | emit `auto_diagnosis_completed` 事件 |

Claude Code 诊断的错误模式：
- `diagnosis_timeout`：超过 10 分钟
- `claude_cli_not_found`：CLI 未安装
- `diagnosis_error`：其他异常

**Gap E-5a**: 诊断失败后的后续处理 = **无**。冷却到期后会重试，但如果连续 3 次诊断都失败（24h 内），该 routine 就停在 broken 状态，无人类通知
**Gap E-5b**: Claude Code 只用于 Spine routine 失败。Move 执行失败、通知失败、gateway 故障等均无 Claude Code 介入
**Gap E-5c**: 排障前未暂停该 routine（已在 §4-4 记录）

#### E-6 Ward 系统（routines.py + will.py + cadence.py）

**探针（pulse routine 调用）：**

| 探针 | 检查内容 | 判定 |
|------|---------|------|
| gateway | GET /health → 回退 sessions_history RPC | ok / error |
| temporal | socket connect 127.0.0.1:7233 (3s) | ok / error |
| disk | shutil.disk_usage | ok / low (<5GB 或 <15%) / critical (<1GB 或 <5%) |
| llm | cortex.is_available() | ok / unavailable |

**状态决策：**
```
gateway/temporal 有一个 degraded → YELLOW
gateway/temporal 两个 degraded → RED
disk critical → RED
llm/disk degraded → YELLOW
全部 ok → GREEN
```

**Ward 对系统的影响：**

| Ward | 对新 Deed | 对 Spine | 对已运行 Deed |
|------|----------|---------|-------------|
| GREEN | 正常提交 | 正常调度 | 继续执行 |
| YELLOW | Endeavor 排队，errand/charge 继续 | 自适应 routine 暂停 | 继续执行 |
| RED | 全部排队 | 自适应 routine 暂停 | 继续执行 |

**Gap E-6a**: Ward RED 时已运行 Deed 继续执行——但如果 RED 原因是 gateway down，这些 Deed 的 Move 必然会失败。应该至少暂停而非让它们自然失败
**Gap E-6b**: Ward 恢复后排队 Deed 如何释放？未找到自动释放逻辑
**Gap E-6c**: Ward 变化通知依赖 Telegram adapter，但 adapter 本身可能是故障点

#### E-7 看门狗（scripts/watchdog.sh）

| 检查项 | 阈值 | 通知方式 |
|--------|-----|---------|
| API 进程存活 | uvicorn 进程不存在 | Telegram + macOS + 文件日志 |
| Worker 进程存活 | worker 进程不存在 | 同上 |
| API 响应 | GET /system/status 5s 超时 | 同上 |
| Pulse 新鲜度 | schedule_history.json 中 pulse 超过 30 分钟 | 同上 |

- 通知三通道：`alerts/watchdog.log` ✅、Telegram ✅、macOS osascript ✅
- **注意**：watchdog.sh 实现了 macOS 通知和 alerts/ 日志，但 Herald/Cadence 的通知降级链没有调用这些——两套独立的通知机制

**Gap E-7a**: watchdog 检测到进程死亡后不重启——只通知。需要人类手动重启
**Gap E-7b**: watchdog 检查 `schedule_history.json`，但 Cadence 实际写入的文件名需要确认一致性（已在 §4-5 记录）

#### E-8 Cortex LLM 错误处理（cortex.py）

| 机制 | 行为 |
|------|------|
| 多 provider 回退 | minimax → zhipu → qwen → deepseek → openai → anthropic，依次尝试 |
| 单 provider 失败 | 捕获异常，记录 usage，尝试下一个 |
| Ration 超限 | 跳过该 provider，尝试下一个 |
| 全部失败 | 抛出 CortexError（带完整 provider_route 链路） |
| 结构化 JSON 失败 | 抛出 CortexError |
| 降级模式 | `try_or_degrade(fn, fallback)` 返回 fallback 值 |

- 每次调用（成功/失败）写入 `cortex_usage.jsonl`

#### E-9 通知失败处理

**当前实现的链路：**
```
Herald 推送失败
  → enqueue_failed_notification() → state/notify_queue.jsonl
  → Cadence 每 30s 重试 → 最多 3 次
  → 3 次后 → logger.warning → 丢弃
```

**文档要求的链路：**
```
推送失败
  → 重试 3 次（指数退避）
  → macOS 桌面通知
  → ~/daemon/alerts/ 日志文件
  → 失败队列
```

**Gap E-9a**: 重试无指数退避（线性 30s 间隔）— 已在 ID-5b-1 记录
**Gap E-9b**: macOS 通知和 alerts/ 兜底只在 watchdog.sh 中存在，Herald/Cadence 的通知路径中不存在 — 已在 ID-5b-2、ID-5b-3 记录
**Gap E-9c**: 3 次重试后通知彻底丢失，无死信队列、无人类告警、无审计记录

### 设计意图 vs 现状对照

**用户期望：Claude Code = 第一响应者，人类 = 最后手段**

| 场景 | 设计意图 | 当前实现 | Gap |
|------|---------|---------|-----|
| Spine routine 连续失败 | Claude Code 自动修复 | ✅ 调用 Claude CLI | 诊断失败后无后续 |
| Move 执行失败 | Claude Code 介入？ | ❌ 只靠 rework 循环 | 无 Claude Code 介入 |
| 通知系统故障 | Claude Code 修复？ | ❌ 3 次重试后丢弃 | 无 Claude Code 介入 |
| Gateway 崩溃 | Claude Code 重启？ | ❌ Ward RED + watchdog 通知人类 | 无自动恢复 |
| 进程死亡 | Claude Code 重启？ | ❌ watchdog 通知人类 | 无自动重启 |
| SQLite 损坏 | Claude Code 修复？ | ❌ 无检测机制 | 无检测也无修复 |
| 磁盘满 | Claude Code 清理？ | ❌ Ward RED 阻止新 deed | 无自动清理 |

**结论：Claude Code 作为第一响应者的覆盖面极其有限。只覆盖 Spine routine 故障这一条路径。其他所有故障场景要么靠内置回退（LLM provider 切换、rework 循环），要么直接通知人类，要么静默丢弃。**

### 全链路 Gap 清单

| # | Gap | 决策 |
|---|-----|------|
| E-3a | rework 耗尽后不 fail deed，静默交付低质量产出 | rework_ration 耗尽 → deed failed + 通知用户 |
| E-5a | Spine 诊断失败后无人类通知 | 3 次诊断都失败时 emit 事件 + Telegram 通知 |
| E-5b | Claude Code 只覆盖 Spine routine 失败 | 扩展到更多场景（至少：进程重启、通知修复） |
| E-6a | Ward RED 时已运行 Deed 继续执行（gateway 可能已不可用） | RED 时自动暂停 running deeds |
| E-6b | Ward 恢复后排队 Deed 无自动释放 | Ward GREEN 时自动释放排队 deed |
| E-7a | watchdog 不重启死掉的进程 | 加入进程重启逻辑（或用 systemd/launchd） |
| E-9c | 通知 3 次重试后彻底丢失 | 死信队列 + 人类告警 |
| E-10 | 无 SQLite 完整性检查 | tend routine 中加入 PRAGMA integrity_check |
| E-11 | 无内存监控 | Ward 探针增加进程 RSS 检测 |
| E-12 | 无结构化崩溃日志 | uncaught exception handler 写 crash dump |
| E-13 | 两套独立通知机制（watchdog vs Herald/Cadence）不统一 | 统一通知路径或互相调用 |

---

## 跨层机制待审计清单

> 以下跨层机制尚未展开审计。每条都可能像 ① 错误处理那样在展开后发现大量 gap。
> 回来后逐条展开，按 ① 的格式写入。

| # | 跨层机制 | 一句话描述 | 涉及层 |
|---|---------|-----------|--------|
| ② | **Deed 端到端生命周期** | 用户输入 → Voice → Will → Temporal → Activities → Herald → 通知 → 反馈 → Lore，完整链路每一步的数据传递和状态转换 | Voice, Will, Temporal, Herald, Feedback |
| ③ | **Psyche 读写全链路** | Memory/Lore/Instinct 在哪些环节被读、被写、被衰减、被合并。relay 填充 agent context、learn 提取知识、distill 压缩、focus 聚焦——完整数据流 | Psyche, Spine, Will, Activities |
| ④ | **Agent 上下文组装** | 从 Brief → Design → Move instruction → _build_move_context → Psyche snapshot → SOUL.md/TOOLS.md → OpenClaw session，agent 看到的完整上下文是怎么拼出来的 | Will, Activities, Retinue, OpenClaw |
| ⑤ | **质量保障全链路** | 质量标准定义（Instinct/Lore/Brief）→ 执行（agent 遵守）→ 检查（Arbiter 评分）→ 纠正（rework）→ 底线拦截（Herald）→ 反馈（用户）→ 学习（witness/Lore）→ 演化（Instinct 置信度） | Will, Arbiter, Herald, Feedback, Spine |
| ⑥ | **状态持久化与恢复** | state/ git repo、备份/恢复、崩溃后恢复、Temporal checkpoint、Retinue 重启恢复、deeds.json 一致性 | Ledger, Spine, Temporal, Bootstrap |
| ⑦ | **双语产出全链路** | Brief.output_languages → Counsel 理解 → Design 是否拆双语 Move → Scribe 产出 → Arbiter 检查双语一致 → Herald 并列展示 → Portal bilingual 预览 | Voice, Will, Scribe, Arbiter, Herald, Portal |
| ⑧ | **资源管控全链路** | Ration 定义（Instinct）→ Will preflight → Cortex consume → 实时额度查询 → 超限降级 → Ward 联动 → 统计（daily_stats）| Will, Cortex, Instinct, Ward, Cadence |
| ⑨ | **可观测性** | 操作者通过 Console 看到什么 → spine_log / events.jsonl / cortex_usage / herald_log / system_health 各自覆盖什么 → 哪些关键事件没有日志 → 排查问题时信息是否够用 | 全部 |
| ⑩ | **安全与访问控制** | Portal/Console/Telegram/CLI 四个入口各自的认证机制、操作权限边界、Console 审计日志 | API, Telegram, Console, CLI |
| ⑪ | **Dominion 自动化编排** | 用户表达长期意图 → Counsel 创建 Dominion → Writ cron/事件触发 → 自动生成 Deed → 进度追踪 → witness 评估 → 主动沟通。区别于②：② 是单次 Deed，这是跨 Deed 的长期自动化 | Voice, Dominion, Cadence, Witness, Telegram |
| ⑫ | **OpenClaw agent 实例生命周期** | bootstrap 模板创建 → Retinue 池初始化 → 按 Deed 分配 → session 创建 → memory 隔离 → 执行 → session 清理 → memory 清理 → 归还池。区别于④：④ 是上下文内容，这是实例管理 | Bootstrap, Retinue, OpenClaw, Activities |
| ⑬ | **配置传播与生效** | 配置变更（Instinct pref / model_policy / skill_registry / spine_registry）→ 何时生效？需要重启？哪些组件启动时读一次 vs 每次调用时读？热更新 vs 冷更新 | Instinct, Config, Cadence, Cortex, Will |
| ⑭ | **Nerve 事件全图** | 谁 emit 什么事件 → 谁 subscribe → 哪些事件有 handler → 哪些事件无消费者（孤儿事件）→ 事件持久化 → 事件 replay → 30 天清理 | Nerve, 全部 |
| ⑮ | **反馈→学习闭环** | 用户反馈 → feedback 存储 → witness 分析 → review/user 冲突检测 → Lore 更新 → Instinct 置信度调整 → 质量 profile 演化。区别于⑤：⑤ 是单次执行的质量保障，这是跨次的学习闭环 | Feedback, Witness, Lore, Instinct |
| ⑯ | **Vault 归档生命周期** | Offering 产出 → 老化 → curate routine 归档到 vault → 90 天清理 → Google Drive 同步 → 归档后的可访问性 | Herald, Curate, Drive, Ledger |
| ⑰ | **多进程协作** | API 进程 + Worker 进程：共享状态方式（文件系统 + Temporal）、一个进程挂了另一个的行为、启动顺序依赖、优雅关闭 | API, Worker, Bootstrap |
| ⑱ | **Temporal 容错** | workflow replay、activity retry policy、heartbeat 超时、signal 可靠性、workflow versioning、worker 重启后恢复、sticky execution | Temporal, Workflows, Activities |
| ⑲ | **并发控制** | 多 Deed 同时运行：Retinue 竞争、Ration 共享、Move 并行度、跨 Deed 资源隔离、Dominion max_concurrent_deeds 执行 | Retinue, Will, Temporal, Dominion |
| ⑳ | **启动序列与就绪判定** | bootstrap 顺序：Temporal server → Worker → API → Cadence → 池初始化 → Ward 首次检查 → 系统 ready。各步骤依赖关系、某步失败时的行为 | Bootstrap, API, Worker, Cadence |
| ㉑ | **外部服务依赖图** | OpenClaw gateway / Temporal server / LLM provider / Google Drive / Telegram API——每个外部服务不可用时的独立影响和降级方式 | Cortex, OpenClaw, Temporal, Herald, Telegram |
| ㉒ | **进度追踪与呈现** | 内部进度（Move checkpoint、Passage 完成）→ 翻译为用户可理解的进度描述 → 推送到 Portal（WebSocket）和 Telegram → 计划组件原地更新 | Activities, Workflows, WebSocket, Portal, Telegram |
| ㉓ | **Offering 格式流水线** | Brief 中的格式要求 → Design 中的 Scribe 指令 → Scribe 实际渲染（PDF/MD/code）→ Herald 打包清洗 → Portal 按类型差异化预览（文本摘要/PDF 缩略图/code diff） | Will, Scribe, Herald, Portal |
| ㉔ | **时间管理** | UTC 归一化、cron 表达式评估、eval 窗口计算、Lore/Memory 衰减时间戳、事件 30 天清理、vault 90 天过期——全系统时间相关逻辑的一致性 | 全部 |
| ㉕ | **"伪人"原则端到端执行** | daemon 对外行为不可分辨于人类：Voice 对话语气、进度消息措辞、Offering 格式模仿人类产出、通知口吻、零系统痕迹。原则如何在每一层落地？哪些层泄露了机器感？ | Voice, Activities, Scribe, Herald, Portal, Telegram |
| ㉖ | **复杂度路由影响链** | Errand/Charge/Endeavor 一旦确定，影响所有下游：Design 结构、Move 数量、Arbiter 阈值、rework 预算、通知策略、Passage 管理、Retinue 占用时长、计划组件形态。一个值如何扇出到全系统 | Will, Workflows, Arbiter, Herald, Portal |
| ㉗ | **模型路由与 provider 策略** | agent 角色 → model_policy 映射 → provider 选择 → 回退链 → Ration 检查 → 实验模型 promote。区别于⑧：⑧ 是用量管控，这是"用哪个模型"的决策链 | Cortex, Will, Config |
| ㉘ | **Skill 选择与组合** | skill_registry → 按 agent/任务类型匹配 → agent TOOLS.md 注入 → 执行 → 效果追踪。Skill 从哪来、怎么选、怎么传到 agent、效果怎么反馈 | Config, Will, Activities, OpenClaw |
| ㉙ | **存储层次间数据一致性** | L0 Nerve（内存）→ L1 state/（文件）→ L2 traces/events → L3 Drive archive。数据在层间如何流动、有无丢失窗口、崩溃时哪层数据可信 | Nerve, Ledger, Curate, Drive |
| ㉚ | **用户意图保真度** | 用户原话 → Voice 多轮对话 → Brief 结构化提取 → Design DAG → Move instruction → agent 执行。每一步变换丢了什么？哪里最容易走偏？有无回溯机制？ | Voice, Will, Activities |
| ㉛ | **暖机全流程** | 前提条件检查 → 种子数据注入 → 系统功能验证 → 校准期 → 生产就绪。一次性但关键的跨层流程。warmup.py 是否覆盖了所有需要验证的机制？ | Bootstrap, Warmup, 全部 |
| ㉜ | **优雅降级组合效应** | 单组件降级（LLM 换 provider / OpenClaw circuit breaker / 磁盘 low）各自有处理。但多个同时降级时会怎样？Ward 是否能正确反映组合降级？降级状态之间是否有级联？ | Ward, Cortex, OpenClaw, Cadence |
| ㉝ | **Deed 排队与释放** | Ward RED/Ration 耗尽/Dominion max_concurrent → Deed 排队。排队优先级？FIFO 还是按复杂度/Dominion？恢复后自动释放？释放顺序？过期清理？ | Will, Cadence, Ward, Dominion |
| ㉞ | **Agent SOUL.md 人格一致性** | 模板 SOUL.md → Retinue 复制 → 运行时是否被修改 → 跨 Deed 是否保持一致 → skill evolution 是否影响 SOUL.md → 版本管理 | OpenClaw, Retinue, Bootstrap |
| ㉟ | **Witness 全系统观察覆盖** | witness routine 应观察：Deed 产出质量、Dominion 进展、review/user 冲突、系统健康趋势、能力演化信号。实际观察了哪些？遗漏了哪些？观察结果流向哪里？ | Witness, Lore, Instinct, Dominion |
| ㊱ | **Console 操作者工作流** | 典型场景：发现异常 → 定位问题 → 调整配置 → 验证修复。Console 能否支撑完整排查流程？信息是否够用？操作是否顺畅？是否需要跳出 Console 去看日志文件？ | Console, API, Ledger |
| ㊲ | **JSONL 日志轮转与清理** | events.jsonl / herald_log.jsonl / spine_log.jsonl / cortex_usage.jsonl / console_audit.jsonl 等全部 JSONL 文件的增长控制、轮转策略、过期清理、磁盘监控。单文件无限增长 = 磁盘炸弹 | Ledger, Cadence, Ward |
| ㊳ | **Brief 完整性与验证链** | 用户模糊输入 → Voice 提取 → Brief 结构化。Brief 必填字段是否齐全？缺字段时回退默认还是追问用户？Brief 到 Will 传递中哪些字段被忽略？enrichment 补了什么？ | Voice, Will, Instinct |
| ㊴ | **Design (DAG) 结构验证** | Counsel 生成 Design → 结构是否合法（无环、依赖可解、Move 类型合法）→ 执行时 Move 顺序如何确定 → 动态插入 rework Move 是否破坏 DAG → Design 修订的版本管理 | Will, Workflows, Activities |
| ㊵ | **Passage 分割与渡越策略** | 长 Move 按 Passage 分割：分割依据是什么（token 数 / 章节 / agent 自决）→ Passage 间上下文传递 → Passage 完成时的中间产出处理 → 失败时回退到哪个 Passage | Activities, OpenClaw |
| ㊶ | **Cortex LLM 调用抽象** | 所有 LLM 调用经 Cortex → provider 选择 → 格式适配 → 调用 → 响应归一化 → 计量。不同 provider API 差异（MiniMax native vs Anthropic-compat vs OpenAI-compat）如何抹平？错误码映射是否完整？ | Cortex, Config |
| ㊷ | **文件系统目录契约** | deeds/ / offerings/ / state/ / traces/ / vault/ 各目录的预期结构、文件命名规则、由谁创建、由谁清理。目录缺失/权限错误时的行为。哪些模块假设目录已存在而不检查？ | Ledger, Herald, Will, Bootstrap |
| ㊸ | **日志可关联性（trace_id 贯穿）** | 一次 Deed 执行涉及多模块日志。deed_id / move_id / trace_id 是否在所有日志条目中一致标记？排查问题时能否通过一个 ID 关联出全链路所有日志？ | 全部 |
| ㊹ | **系统升级与数据迁移** | state/ 文件格式变更（如新增字段）→ 旧数据兼容性 → config 版本管理（model_registry v1.2 → v1.3）→ 迁移脚本 → 回滚方案。没有迁移策略 = 每次升级手动修数据 | Config, Ledger, Bootstrap |
| ㊺ | **任务类型对下游的扇出** | Brief.task_type（研究/写作/编码/分析…）确定后影响：agent 选择 / Design 模式 / 质量标准 / 产出格式 / review 侧重 / 通知措辞。类型的影响是否在每个节点都被正确传递？ | Voice, Will, Activities, Arbiter, Scribe, Herald |
| ㊻ | **Ward 探针设计与组合** | Ward 靠探针判定系统健康：磁盘/Temporal/OpenClaw/内存/API 熔断。探针列表是否完整？探针结果如何组合为 GREEN/YELLOW/RED？单探针误报时的影响？探针执行频率和超时？ | Ward, Cadence |
| ㊼ | **Cadence 调度全图** | 所有 routine 的 cron 表达式 / 间隔 / 触发条件。routine 之间是否有时间冲突？高密度时段（多 routine 同时触发）的资源竞争？调度失败的补偿？ | Cadence, Spine |
| ㊽ | **Deed 中间产出可见性** | 执行中用户能看到什么？Move 级状态文字、partial offering 预览、agent 正在做什么的描述。信息从 Activity → Workflow signal → API → WebSocket → Portal 的完整链路 | Activities, Workflows, API, Portal |
| ㊾ | **用户多入口同步** | 用户同时在 Portal 和 Telegram 操作同一 Deed（发消息/给反馈/取消）。两个入口的操作是否互斥？状态是否实时同步？冲突（Portal 取消 + Telegram 追加需求）如何处理？ | Portal, Telegram, API, Voice |
| ㊿ | **Agent 外部工具调用管控** | agent 通过 skill 调用外部系统（GitHub push / URL fetch / opencode 写代码 / PDF 渲染）。调用权限控制？副作用管理？超时保护？费用计量？失败回退？ | Activities, OpenClaw, Skills |
| 51 | **Counsel 对话策略** | Counsel 何时追问、何时直接执行？追问轮数上限？用户不耐烦时的降级？Brief 信息足够的判定标准？多轮对话的上下文累积与截断？ | Voice, Counsel Agent |
| 52 | **评估窗口与用户节奏** | awaiting_eval 48h → 12h 提醒 → 过期自动完成。但用户响应速度不同：有人 5 分钟回、有人 3 天回。系统是否根据历史响应速度调整评估窗口？是否影响下次 Deed 的通知策略？ | Cadence, Lore, Herald |
| 53 | **Retinue 模板完整性** | 模板 agent 目录必须包含：SOUL.md / TOOLS.md / SKILL.md / 正确的 provider 配置。模板不完整时 bootstrap 是否检测到？Retinue 实例复制后是否验证？模板更新后已有实例是否同步？ | Bootstrap, Retinue, OpenClaw |
| 54 | **state/ git 提交策略** | state/ 是 git repo：谁 commit？什么频率？commit message 规范？两进程同时写是否冲突？git 历史膨胀的控制？是否有 gc/repack？state/ git 和主仓库 git 的关系？ | Ledger, API, Worker |
| 55 | **Herald 多通道交付适配** | 同一 Offering 交付到不同通道需要适配：Portal（文件预览 + 下载链接）/ Telegram（摘要 + 关键段落）/ CLI（路径输出）。每个通道的格式转换是否完整？遗漏了哪些通道？ | Herald, Portal, Telegram, CLI |
| 56 | **Move checkpoint 与恢复** | 单个 Move 执行中进度保存：Temporal activity heartbeat / agent session 状态 / 中间文件。Activity timeout 后 retry 时是否从断点恢复还是从头开始？Passage 级恢复是否实现？ | Activities, Temporal, OpenClaw |
| 57 | **跨 Deed 知识传递** | Deed A 的产出/经验如何影响 Deed B？路径：Lore 记录 → relay 注入 → agent 上下文。但 Lore 记录了什么、relay 注入了多少、注入是否相关——每一步的选择和过滤逻辑 | Lore, Spine, Activities |
| 58 | **OpenClaw gateway 生命周期** | gateway 启动 → agent 注册 → session 管理 → 热加载 → 重启影响。gateway 挂了时的检测和恢复？Retinue 创建触发的 restart 对在运行 session 的影响？ | OpenClaw, Bootstrap, Ward |
| 59 | **OpenClaw session 并发限制** | gateway 同时能维持多少 agent session？Retinue 池大小 × 并行 Deed 数 = 峰值 session 数。超限时的表现？session 泄漏（未正确关闭）的检测？长时间 idle session 的回收？ | OpenClaw, Retinue, Activities |
| 60 | **同一 Deed 内 agent 间信息传递** | scout 找到的信息 → sage 的分析输入 → artificer 的构建指令。Move 产出存在哪？下一个 Move 怎么读到上一个的产出？产出格式是否有契约？大产出（如完整代码库）如何传递？ | Activities, Will, OpenClaw, 文件系统 |
| 61 | **Offering 版本管理** | Arbiter 拒绝 → rework → 新版本产出。旧版本保留还是覆盖？用户能看到版本历史吗？Herald 交付的是最终版还是全部版本？Offering 目录下文件命名是否区分版本？ | Herald, Arbiter, Activities, Portal |
| 62 | **用户中断与恢复** | 用户取消正在执行的 Deed 后又想恢复。已完成的 Move 产出是否保留？Temporal workflow cancel 后能否 resume？Retinue 实例是否已归还？需要重新分配？从哪个 Move 继续？ | Portal, Telegram, Temporal, Retinue, Will |
| 63 | **Brief 修改与 Design 重规划** | Deed 执行中用户发来新需求（/deeds/{id}/message）。追加到 Brief？触发 Design 重规划？已完成的 Move 怎么办？正在执行的 Move 中断还是完成后再调整？ | Voice, Will, Workflows, Activities |
| 64 | **Agent 输出解析与结构化** | agent 返回自由文本。Arbiter 评分如何从文本中提取？Design 从 Counsel 回复中如何解析为 JSON DAG？解析失败时的回退？哪些地方用正则、哪些用 LLM 二次解析？ | Activities, Will, Arbiter, OpenClaw |
| 65 | **Instinct 演化全链路** | bootstrap 初始值 → witness 观察 → 置信度调整 → preference drift → 自进化 Track 提议修改。Instinct 变化速率有无限制？异常值检测？回滚机制？变更历史追踪？ | Instinct, Witness, Spine, 自进化 |
| 66 | **系统冷启动 vs 热重启** | 首次启动（空 state/）vs 带存量数据重启。重启后：pending deeds 恢复？awaiting_eval 状态重算？Cadence 错过的 cron tick 补偿？Retinue 池重建 vs 复用？ | Bootstrap, Temporal, Cadence, Ledger |
| 67 | **Deed 间依赖与排序** | 同一 Dominion 下 Deed B 依赖 Deed A 的产出。Writ 定义中有无显式依赖？依赖 Deed 未完成时新 Deed 阻塞还是跳过？循环依赖检测？ | Dominion, Writ, Will, Cadence |
| 68 | **LLM 幻觉防护** | agent 产出可能包含虚构信息。哪些环节有事实验证？Arbiter 是否检查引用有效性？scout 采集的 URL 是否验证可达？artificer 生成的代码是否有编译/运行验证？ | Activities, Arbiter, Skills, OpenClaw |
| 69 | **Portal WebSocket 连接生命周期** | 连接建立 → 认证 → 事件订阅 → 心跳保活 → 断线重连 → 重连后补发错过的事件 → 多标签页同时连接。客户端和服务端两侧的完整状态机 | Portal, API, Nerve |
| 70 | **成本追踪与预算** | per-deed / per-agent / per-provider / per-day 的 LLM 调用成本。cortex_usage.jsonl 记录了什么？聚合为什么报表？Console 能看到什么？超预算预警？ | Cortex, Cadence, Console, Ledger |
| 71 | **Offering 交付确认** | Herald 发出交付后，如何确认用户收到？Portal 有下载/查看事件？Telegram 有已读回执？交付失败（文件损坏/链接过期）的检测？ | Herald, Portal, Telegram, Ledger |
| 72 | **Agent 模型回退链** | 主模型不可用（限流/宕机/超时）→ 回退到备选模型 → 备选也不可用 → 进一步降级。回退时 prompt 是否需要适配不同模型的能力？回退是否影响质量评估基线？ | Cortex, Config, Activities, Arbiter |
| 73 | **自然语言→系统操作翻译** | 用户在 Portal 说"暂停那个项目"→ Counsel 需理解"那个"指哪个 Dominion → 调用系统 API 暂停。Voice 层的意图识别准确率？歧义时的确认机制？误操作的撤回？ | Voice, Counsel, API, Dominion |
| 74 | **跨 Dominion 资源公平** | 多个活跃 Dominion 共享 Ration 和 Retinue。资源分配策略：平均？按优先级？按 deadline？一个 Dominion 高频触发是否饿死其他 Dominion？ | Dominion, Ration, Retinue, Cadence |
| 75 | **产出引用与溯源链** | Offering 中的信息来自哪里？scout 采集的原始 URL → sage 分析时的引用 → scribe 渲染时的参考文献。引用链是否完整保留？用户能否追溯到原始来源？ | Activities, Scribe, Herald, Portal |
| 76 | **系统基线与异常检测** | 正常运行时各指标（LLM 调用频率/Move 平均耗时/错误率/磁盘增速）的基线。偏离基线多少触发告警？基线随系统演化自动调整？ | Ward, Cadence, Witness, Ledger |
| 77 | **Agent context window 管理** | 不同模型 context 上限不同（MiniMax 1M / DeepSeek 64K / Qwen 128K）。_build_move_context 是否考虑目标模型的 token 限制？超限时的截断策略？截断会丢失关键信息吗？ | Activities, Cortex, Config |
| 78 | **密钥轮转与凭据安全** | .env 中的 API key 过期/泄露时：轮转流程？无缝切换还是需要重启？OpenClaw gateway token 的刷新？Temporal 认证？敏感信息是否出现在日志中？ | Config, Bootstrap, 全部日志 |
| 79 | **OpenClaw workspace 隔离验证** | Retinue 实例各自 workspace 是否真正隔离？共享文件系统上的竞态？一个实例写入是否可能影响另一个？workspace 清理是否彻底（无残留文件影响下次使用）？ | OpenClaw, Retinue, Bootstrap |
| 80 | **大文件与长文本处理** | 用户提交大文档（100 页 PDF / 大代码库）。Voice 如何处理？Brief 如何存储？agent context 能否容纳？分块策略？跨块一致性？Scribe 渲染大产出时的内存/时间？ | Voice, Will, Activities, Scribe |
| 81 | **Deed 取消后的全链路清理** | 用户取消 Deed → Temporal workflow cancel → 正在运行的 Activity 中断 → OpenClaw session 关闭 → Retinue 归还 → 部分产出删除/保留 → 状态更新 → 通知用户。每一步的清理是否完整？ | Temporal, Activities, Retinue, Herald, Ledger |
| 82 | **通知频率与疲劳控制** | 高密度触发（多 Writ 同时触发 / 多 Deed 同时完成）时的通知爆炸。批量合并？静默时段？每通道频率上限？用户可配置的通知偏好？ | Herald, Cadence, Instinct, Telegram |
| 83 | **系统自描述与可解释性** | 操作者问"这个 Deed 为什么失败了"——系统能否自动串联相关日志、事件、agent 输出，给出可读的解释？还是操作者必须手动翻日志？ | Console, Ledger, Witness |
| 84 | **Deed 模板与快捷触发** | 除 Writ brief_template 外，是否支持独立 Deed 模板？用户说"再来一次和上次一样的"→ 系统能否从历史 Deed 复制 Brief？快捷方式的管理和演化？ | Voice, Will, Lore |
| 85 | **Nerve 事件风暴防护** | 某组件短时间内 emit 大量事件（如批量 Move 完成）。Nerve 内存是否扛得住？subscriber 处理速度跟不上时的背压？事件丢弃策略？风暴期间 JSONL 写入的 I/O 压力？ | Nerve, Cadence, Ledger |
| 86 | **JSONL 并发写入原子性** | API 进程和 Worker 进程同时 append 同一 JSONL（如 events.jsonl）。行级原子性？文件锁？crash 时的 partial line？读端遇到截断行的容错？ | Ledger, API, Worker |
| 87 | **Deed 状态机完整性** | pending → running → awaiting_eval → completed/failed/cancelled。每条转换是否在代码中有唯一入口？非法转换（如 completed → running）是否被拦截？所有转换是否都 emit Nerve 事件？ | Will, Workflows, Ledger, Nerve |
| 88 | **幂等性保证** | Temporal retry = Activity 可能重复执行。Move 执行幂等？Offering 写入幂等？Herald 交付幂等？Lore 记录幂等？非幂等操作在 retry 时 = 重复交付/重复通知/数据膨胀 | Activities, Herald, Lore, Temporal |
| 89 | **配置文件间交叉一致性** | model_registry + model_policy + openclaw.json + skill_registry + agent_capabilities 五文件必须互相一致。agent 引用不存在的 model？skill 引用不存在的 agent？启动时校验还是运行时才报错？ | Config, Bootstrap, Cortex, OpenClaw |
| 90 | **API 响应格式一致性** | 所有端点的错误格式、分页方式、时间戳格式、字段命名风格是否统一？Portal/Console JS 代码假设了什么响应结构？不一致 = 前端 silent failure | API, Portal, Console |
| 91 | **进程优雅关闭链** | SIGTERM → API 进程（drain HTTP/WebSocket 连接、flush 日志）→ Worker 进程（等待 running Activity 完成、归还 Retinue、flush heartbeat）。关闭顺序？超时强杀？状态持久化 checkpoint？ | Bootstrap, API, Worker, Temporal, Retinue |
| 92 | **Deed 元数据全链路传播** | deed_id / writ_id / dominion_id 从创建到归档全程传播。哪些模块接收这些 ID？哪些日志/文件缺少关联 ID（导致无法追溯）？断链点在哪？ | Will, Activities, Herald, Ledger, 全部日志 |
| 93 | **多语言编码与路径安全** | UTF-8 everywhere？CJK 字符在文件名/路径中（offerings/ 下的中文文件名）？API URL encoding？agent 产出中的特殊字符转义？路径拼接的 injection 风险？ | Herald, Activities, API, 文件系统 |
| 94 | **内存缓存与失效策略** | 哪些数据被缓存在内存中（Instinct 值？config 文件？Lore 查询结果）？缓存过期时间？config 变更后缓存是否失效？两进程各自缓存的一致性？ | Instinct, Config, Cortex, Lore |
| 95 | **外部 API 速率限制适配** | 每个 LLM provider 的 rate limit（RPM/TPM）不同。Cortex 是否追踪？并发 Deed 导致的突发请求？Telegram API 限制（30 msg/sec）？Google Drive API 限制？超限后的排队/退避？ | Cortex, Herald, Telegram, Drive |
| 96 | **Design 内 Move 并行执行** | DAG 允许无依赖 Move 并行。Temporal 如何调度并行 Activity？并行 Move 共享 Retinue 实例？并行 Arbiter review？并行 Move 的产出合并？失败一个时其他怎么办？ | Workflows, Activities, Retinue, Arbiter |
| 97 | **Offering 完整性校验** | 交付前验证：文件存在？非空？格式正确（PDF 可打开 / JSON 合法 / 代码可编译）？双语对完整（中英都有）？缺项时 Herald 拒绝交付还是标记 incomplete？ | Herald, Arbiter, Activities |
| 98 | **Brief enrichment 叠加顺序** | 用户原始输入 → Voice 提取 → Instinct 默认值填充 → Lore 历史信息补充 → Dominion 配置覆写 → 复杂度校准。各层叠加顺序是否固定？后叠加层覆盖前层时的冲突解决？最终 Brief 的可追溯性？ | Voice, Will, Instinct, Lore, Dominion |
| 99 | **手动 vs 自动 Deed 优先级** | 用户直接对话触发 = 手动 Deed；Writ cron 触发 = 自动 Deed。手动 Deed 优先级更高？资源竞争时手动 Deed 抢占自动 Deed？自动 Deed 是否可以被手动 Deed 打断？ | Will, Cadence, Retinue, Dominion |
| 100 | **各环节延迟预算** | Voice 首次响应（< 3s？）→ Design 生成（< 30s？）→ 单 Move 执行（< 5min？）→ 全 Deed 端到端。各环节有无明确预算？超预算的检测和告警？慢操作的用户感知体验？ | Voice, Will, Activities, Herald, Portal |
| 101 | **Agent 错误信息脱敏** | agent 内部报错（Python traceback / OpenClaw session error / provider API error）→ 向上传播过程中是否脱敏？技术细节是否泄露到 Portal 用户消息？错误消息是否符合"伪人"原则？ | Activities, Workflows, Herald, Portal |
| 102 | **单用户假设的边界** | daemon 是单用户系统。但 API 无认证 = 任何能访问端口的人都是"用户"。Telegram bot 收到非主人消息？Portal 被他人打开？CLI 在其他账户运行？单用户假设在哪些地方被隐式依赖？ | API, Telegram, Portal, CLI |
| 103 | **Deed 历史搜索与索引** | deeds.json 无限增长。按关键词 / 日期范围 / Dominion / 状态搜索过去的 Deed。有无索引？全文扫描的性能？历史 Deed 的 Brief 和产出路径是否仍然可访问？ | Ledger, API, Console, Portal |
| 104 | **系统版本与能力自省** | daemon 知道自己的版本号吗？config 文件有 version 字段但谁检查？Console 的"关于"信息？/health 端点返回什么？启动时的 banner 显示什么系统信息？ | Bootstrap, API, Console |
| 105 | **Rework 上下文累积** | 第 1 次 rework：agent 看到 Arbiter 反馈。第 2 次：看到两轮反馈 + 两个旧版本。第 N 次：上下文线性膨胀。是否有截断/摘要？rework 次数多时 agent context 溢出？ | Activities, Arbiter, OpenClaw, Cortex |
| 106 | **系统内部标识的对外泄露** | Retinue 实例名（counsel_0）、Move ID、内部状态码、文件系统路径——哪些会出现在用户可见的消息中？每个出口（Portal/Telegram/Offering）的过滤是否完整？ | Herald, Portal, Telegram, Activities |
| 107 | **Dominion/Writ 变更的运行时影响** | 修改活跃 Dominion 的配置（max_concurrent / instinct_overrides）→ 正在运行的 Deed 是否受影响？Writ 修改 cron 表达式 → 下次触发时间重算？删除 Writ → 已排队的 Deed 怎么办？ | Dominion, Writ, Cadence, Will |
| 108 | **文件路径引用的跨模块一致性** | 模块 A 用 `DAEMON_HOME / "deeds" / deed_id` 创建目录，模块 B 用 `state_dir / "deeds" / deed_id` 引用。路径基准是否统一？硬编码路径？路径中的变量替换规则？ | 全模块, Ledger, Herald, Activities |
| 109 | **Writ cron 首次触发与补偿** | 新注册 Writ 的 cron：首次触发等下一个时间点还是立即执行？Cadence 重启后错过的 cron 执行是否补偿（catch-up）？补偿时的资源争抢？ | Cadence, Writ, Will |
| 110 | **Witness 与 Arbiter 的信息共享** | 都做"评价"但维度不同：Arbiter = 单次产出质量门控，Witness = 跨次趋势观察。Witness 是否读 Arbiter 历史评分？Arbiter 阈值是否受 Witness 建议调整？两者标准是否可能矛盾？ | Witness, Arbiter, Instinct, Lore |
| 111 | **反馈环路稳定性** | Instinct 演化 → 质量标准漂移 → Arbiter 评分变化 → 用户反馈变化 → Witness 观察 → Instinct 再演化。正反馈失控（标准越来越松/越来越严）？阻尼机制？置信度变化速率上限？回滚触发条件？ | Instinct, Witness, Arbiter, Lore |
| 112 | **复合任务拆分** | 用户一句话包含"调研+写代码+出报告"。单 Deed 多类型 Move？还是拆成多 Deed？拆分判断在 Voice 层还是 Will 层？拆出的多 Deed 之间有无依赖？用户对拆分结果有无确认权？ | Voice, Will, Counsel, Dominion |
| 113 | **Adapter 模式通用契约** | Telegram adapter 是唯一实例，但设计上 adapter 是通用机制（邮件/webhook/爬虫→Nerve 事件）。通用 adapter 必须实现什么接口？健康检查？认证？消息格式归一化规范？新 adapter 的接入 checklist？ | Telegram, Nerve, API, Bootstrap |
| 114 | **单进程内 asyncio 并发安全** | Cadence 多 routine 并发执行、Nerve subscriber callback 并发触发、API 并发请求处理。共享内存数据结构（dict/list）的竞态？asyncio.Lock 的使用？CPU-bound 操作阻塞 event loop？ | Cadence, Nerve, API, Spine |
| 115 | **宿主 OS 集成** | macOS 环境：launchd 自启动配置、文件描述符上限（ulimit）、进程优先级、端口冲突检测、日志输出目标（stdout vs 文件 vs syslog）、磁盘休眠对 JSONL 写入的影响 | Bootstrap, 全部进程 |
| 116 | **备份与灾难恢复流程** | 完整备份范围（state/ + config/ + openclaw/ + vault/ + .env）→ 备份频率 → 恢复步骤 → 恢复后验证（数据一致性 + 功能测试）→ 部分恢复（只恢复 config 不恢复 state）。区别于 ㊹（格式迁移），这是操作流程 | Ledger, Config, Bootstrap, 全部 |
| 117 | **可测试性边界** | 无 LLM 的集成测试怎么做？Mock 切入点（Cortex？OpenClaw？Activity？）。测试 fixture（假 Brief / 假 Design / 假 Offering）的生成。端到端测试的最小可运行配置。CI 中的测试策略 | Cortex, Activities, 全部 |
| 118 | **新能力扩展路径** | 加新 agent 角色 / 新 skill / 新通知通道 / 新 LLM provider / 新 Ward 探针——每种扩展触及哪些文件（代码 + config + openclaw + 文档）？有无扩展 checklist？遗漏一个文件 = 运行时报错 | Config, OpenClaw, Activities, Bootstrap |
| 119 | **Voice 单 session 多 Deed** | 一次对话中用户提了两个无关需求。Counsel 识别为两个独立任务？生成两个 Brief？同时提交还是顺序提交？用户说"还有一件事"的处理？session 内 Deed 之间的隔离？ | Voice, Counsel, Will |
| 120 | **OpenClaw agent 文件读取时机** | SOUL.md / TOOLS.md / SKILL.md 何时被 agent 读取？session 创建时一次性加载？每次 message 时重读？运行中修改这些文件是否即时生效？Retinue 实例复制后模板更新的同步？ | OpenClaw, Retinue, Bootstrap |
| 121 | **state/ 运行时数据格式版本化** | deeds.json / instinct.json / lore.jsonl 的 schema 演进。新版本代码读旧格式数据？缺字段的默认值填充？字段类型变更？区别于 ㊹（config 版本），这是运行时持久化数据 | Ledger, Bootstrap, 全模块 |
| 122 | **系统实时指标采集** | 区别于日志（事后审计），实时指标：当前活跃 Deed 数 / Retinue 使用率 / LLM 调用延迟 P95 / 队列深度。指标暴露方式（API /metrics？Console dashboard？）。趋势存储？ | API, Console, Cadence, Ward |
| 123 | **Counsel 上下文窗口与历史管理** | Voice 多轮对话中 Counsel 的 context 累积。长对话截断策略？关键信息（已确认的 Brief 字段）是否显式保留？用户回来续谈时上次对话的恢复？ | Voice, Counsel, OpenClaw |
| 124 | **Deed 产出的长期可访问性** | Deed 完成 3 个月后，offerings/ 归档到 vault/，原路径失效。用户通过 Portal 查看历史 Deed 时如何访问产出？redirect 到 vault？按需解档？Google Drive 链接？ | Herald, Vault, Portal, API |
| 125 | **全系统术语一致性执行** | §0 定义了术语映射，但代码/config/openclaw/UI/文档五层都需要同步。术语变更后的全量扫描机制？CI 检查？新贡献者（或新 session 的 LLM）引入旧术语的防护？ | 全部 |

---

## 全量 Gap 清单

> 不分轻重，全量记录。每一条未修复都是隐患。

### §3 Psyche

| # | Gap | 决策 |
|---|-----|------|
| 3-1b | memory.intake() 不存在 | warmup.py 和 api.py 改用 memory.add() |
| 3-1b | memory.query() 不存在 | 实现 MemoryPsyche.query() 方法 |
| 3-1c | Memory 合并机制缺失 | distill() 中加入合并步骤 |
| 3-2c | Lore 衰减未实现 | curate routine 中加入 |
| 3-3a | Instinct 缺 3 个 bootstrap key | 补充 provider_daily_limits, deed_ration_ratio, output_languages |
| 3-3a | pool_size_n → retinue_size_n | 代码 + 文档同步改 |

### §4 Spine

| # | Gap | 决策 |
|---|-----|------|
| 4-1 | intake/judge routine 无实现 | judge 废弃，intake 吸收进 learn，清理 registry + QA |
| 4-2a | routine 超时保护缺失 | Cadence 加 asyncio.wait_for |
| 4-2e | adaptive 调度信号不足 | 逐步补充 |
| 4-2f | 降级模式未应用 | 完善 |
| 4-4 | 排障前未暂停 routine | 加入 |
| 4-5 | watchdog 文件名错误 | 修正 |
| 4-6 | CLI 生命周期操作未实现 | 补充 |

### §5 Voice

| # | Gap | 决策 |
|---|-----|------|
| 5-2c | Voice 缺 Brief 摘要 | Counsel prompt 或后处理 |

### §6 Will

| # | Gap | 决策 |
|---|-----|------|
| 6-2 | will.py 文件拆分未做 | 膨胀时拆 |
| 6-4 | MiniMax 实时额度查询未实现 | cortex.py 加入 |

### §7 执行层

| # | Gap | 决策 |
|---|-----|------|
| 7-1 | retinue 状态文件名不一致 | 统一文件名 |
| 7-2a | Psyche 快照写入未调用 | allocate() 中加入 |

### §10 Dominion-Writ-Deed（对照 DWD 专属文档全量）

| # | Gap | 决策 |
|---|-----|------|
| 10-1 | API 路径不符方案 | 添加 /console/dominions 和 /console/writs 路由 |
| 10-2 | Dominion 缺 max_concurrent_deeds/max_writs/instinct_overrides | 补入默认字段 |
| 10-4 | Writ 缺 max_pending_deeds/deed_history/split_from/merged_from | 补入字段 |
| 10-5a | cadence.tick 事件不存在 | Cadence 加 cron 评估 → emit cadence.tick |
| 10-5b | writ_trigger_ready 无消费者 | 实现 handler：template → fill → Will → Temporal |
| 10-5c | brief_template 填充未实现 | 实现动态数据填充（Lore/Memory/前序 Deed 产出） |
| 10-6 | 资源限制全部未实现 | 入口检查：reserved_independent_slots / max_concurrent / max_writs / max_pending |
| 10-7a | Dominion pause 不级联到 Writ | update_dominion 中加级联 |
| 10-7b | Dominion 终止不处理在运行 Deed | completed/abandoned 时暂停子 Writ |
| 10-7c | progress_notes 自动更新缺失 | witness 加 Dominion progress 评估 |
| 10-8a | Memory 无 dominion_id 过滤查询 | tags 支持 dominion_id，查询加过滤 |
| 10-8b | Lore 无 Dominion 聚合优先 | record + consult 加 dominion_id |
| 10-8c | Instinct Dominion-level 覆写缺失 | Will.enrich 读 Dominion.instinct_overrides |
| 10-9a | 复杂度估计不参考 Writ 历史 | complexity_defaults 加 Writ 历史查询 |
| 10-10a | Dominion 级质量趋势缺失 | witness 加 per-Dominion 统计 |
| 10-10b | Review 侧重不可配置 | arbiter prompt 注入 review_emphasis |
| 10-11 | herald_log 缺 dominion_id | 见 §13-4 |
| 10-12a | Dominion objective 进展评估缺失 | 同 10-7c |
| 10-12b | Focus 不考虑 Dominion 优先级 | focus 加活跃 Dominion 信号 |
| 10-13 | Agent 上下文注入缺失 | _build_move_context 加 dominion/writ 上下文 |
| 10-14a | Writ split/merge 方法不存在 | 实现 split_writ() + merge_writs() |
| 10-14b | Writ disable 无级联 | update_writ 加递归级联 |
| 10-15a | Counsel 不能创建 Dominion | counsel SOUL.md/TOOLS.md 加能力 |
| 10-15b | Counsel 不做 Deed 归属决策 | Voice 流程加 Dominion 归属判断 |
| 10-15c | Witness 不检测 objective 达成 | witness 加达成检测 |

### §12 Console + Portal

| # | Gap | 决策 |
|---|-----|------|
| 12-P5 | Console 原始 JSON/MD 编辑违反设计原则 | 移除 textarea 原始编辑，改结构化表单 |
| 12-P5a | Model Policy 编辑应为 agent×模型下拉选择器 | 改为表格选择器 |
| 12-P5b | Model Canon 编辑应为模型卡片表单 | 改为结构化卡片 |
| 12-P5c | Agent SKILL.md 不应由维护者编辑 | 移除或改只读 |
| 12-P5d | Norm 质量配置应为结构化表单 | 每 key 一行，用 input/select/slider |
| 12-P6 | Console 缺操作确认和影响提示 | 二次确认 + 影响说明 + diff 预览 |
| 12-P7 | 缺失端点（dashboard/retinue/routines/logs 等 + model 后端） | 逐个实现 |
| 12-P8a | Lexicon 定义混用用户面中文（步骤/段落/产出） | 系统概念一律用英文术语原文 |
| 12-P8b | Lexicon 缺 12 个核心术语（Move/Arbiter/Design/Dominion/Writ 等） | 补全为完整参考手册 |
| 12-P8c | trails.js 兼容旧字段名 steps | 确认后端后移除 |

### §13 数据模型

| # | Gap | 决策 |
|---|-----|------|
| 13-2 | learn routine 读取路径错误（BUG） | `routines_ops_learn.py:102` 改 glob |
| 13-3 | deed plan 存储 + plan.json → design.json | 方案更新 + vault 文件名改 |
| 13-4 | herald_log 字段与方案不符 | 方案重写 + 补入 writ_id/dominion_id |
| 13-7 | console_audit.jsonl 未实现 | Ledger 写入 |
| 13-8 | daily_stats.jsonl 未实现 | tend routine 聚合 |

### §14 API

| # | Gap | 决策 |
|---|-----|------|
| 14 | WebSocket /ws 缺失 | 实现 |
| 14 | /deeds/{deed_id}/message 缺失 | 实现 |

### §15 Config

| # | Gap | 决策 |
|---|-----|------|
| 15-4 | agent_capabilities.json 缺失 | 创建 |

### §16 Bootstrap

| # | Gap | 决策 |
|---|-----|------|
| 16-1 | retinue 状态文件名不一致 | 统一 |

### §17 质量

| # | Gap | 决策 |
|---|-----|------|
| 17-2 | 四项不可协商底线未实现 | Herald delivery 前加入检查 |

### §ID 交互设计（对照 INTERACTION_DESIGN.md 全量）

| # | Gap | 决策 |
|---|-----|------|
| ID-1a | WebSocket /ws 端点完全缺失 | 实现 WebSocket + Nerve 事件订阅 |
| ID-1b | POST /deeds/{deed_id}/message 通用聊天缺失 | 实现（不同于 append_requirement） |
| ID-1c | GET /offerings/{deed_id}/files/ 缺失 | 实现 deed_id → offering 路径映射 |
| ID-1d | 计划组件原地刷新缺失 | 依赖 WebSocket（ID-1a） |
| ID-1e | 侧边栏自动聚类缺失 | 按 Dominion 归组 + 自然语言标签 |
| ID-1f | Deed 标题自动生成缺失 | Voice 或 Will 流程中生成 |
| ID-2b | 用户消息自动暂停未实现 | 收到消息时暂停→处理→恢复 |
| ID-3b | Passage 级 👍/👎 反馈缺失 | 实现端点 + Lore 存储 |
| ID-3c | awaiting_eval 默认 2h（应 48h）+ feedback_expired 标志缺失 | 改默认值 + 加标志 |
| ID-3d | eval_expiring 提醒从未触发 | Cadence 加 12h 预警 |
| ID-4a | Telegram /status 命令缺失 | adapter.py 实现 |
| ID-4b | Telegram /cancel 命令缺失 | adapter.py 实现 |
| ID-4c | Telegram 状态机 + 60s 超时缺失 | 实现 |
| ID-5b-1 | 通知重试无指数退避 | 改为指数退避 |
| ID-5b-2 | macOS 桌面通知降级缺失 | 实现 osascript 调用 |
| ID-5b-3 | ~/daemon/alerts/ 文件降级缺失 | 实现 |
| ID-8a | 执行中进度消息无实时推送 | 依赖 WebSocket（ID-1a） |
| ID-8b | Passage 完成摘要 + 下阶段计划缺失 | 生成内容 |
| ID-9a | Offering 预览差异化 + bilingual 并列缺失 | 实现 |
| 5-8 | 复杂度特异 Design 格式缺失 | plan dict 增加展示元数据 |
| 5-9 | Voice session 无 TTL | 加 24h 过期清理 |

### §0 方案

| # | Gap | 决策 |
|---|-----|------|
| §0 | 实施方案术语（~100 处） | 批量替换（见上方逐节定位表） |

### 代码层

| # | Gap | 决策 |
|---|-----|------|
| X-1 | console_spine_fabric.py 改名 | 重命名 + 更新 import |
| X-2 | _utc() 重复定义 | 统一 |
| X-3 | test_temporal.py 测试问题 | 修复 |

### 跨层①：系统错误处理全链路

| # | Gap | 决策 |
|---|-----|------|
| E-3a | rework 耗尽后不 fail deed，静默交付低质量产出 | deed failed + 通知用户 |
| E-5a | Spine 诊断失败后无人类通知 | 3 次诊断失败 → Telegram 通知 |
| E-5b | Claude Code 只覆盖 Spine routine 失败 | 扩展覆盖面 |
| E-6a | Ward RED 时已运行 Deed 继续执行 | RED 时自动暂停 running deeds |
| E-6b | Ward 恢复后排队 Deed 无自动释放 | GREEN 时释放 |
| E-7a | watchdog 不重启进程 | 加进程重启或用 launchd |
| E-9c | 通知 3 次重试后彻底丢失 | 死信队列 + 人类告警 |
| E-10 | 无 SQLite 完整性检查 | tend 加 PRAGMA integrity_check |
| E-11 | 无内存监控 | Ward 探针加 RSS 检测 |
| E-12 | 无结构化崩溃日志 | uncaught exception handler |
| E-13 | watchdog 和 Herald/Cadence 通知机制不统一 | 统一或互调 |

### §11 自我进化

| # | Gap | 决策 |
|---|-----|------|
| 11 | §11 全部 5 个子系统未实现 | 暖机后按方案逐步搭建 |
