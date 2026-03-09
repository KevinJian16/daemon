# Daemon 实施方案

> 日期：2026-03-08
> 设计依据：`.ref/DESIGN_QA.md`（全部 10 阶段确认决策）
> 本文档是唯一实施规范。

---

## 0. 文档治理

1. **权威关系**：`DESIGN_QA.md`（设计决策记录）+ 本文档（实施规范）共同构成权威。两者冲突时以 QA 为准。
2. **废弃文档**：`gap_analysis.md`、`action_plan.md`、`daemon_统一方案_v2_archive.md` 及 `_archive/` 内所有文档均不作为实施依据。
3. **系统语言约定**：代码、日志、Console 全部使用英文术语（deed, dominion, writ, step, plan, will），任何情况不翻译。用户界面（Portal、Telegram）使用用户语言（"任务"、"目标"、"结果"），不暴露系统术语。

---

## 1. 设计原则

1. **质量 + 稳定** 双目标优先，其次优化延迟与成本。
2. **系统永远不拒绝**：用户任何需求都引导到可执行的程度（Q3.4）。
3. **"伪人"原则**：daemon 对外行为不可分辨于人类专业人士。产出格式因任务类型而异，模仿对应人类行为。
4. **自适应 > 预设规则**：可配置 > 硬编码。演化 > 一次性规定。不框死产出格式。
5. **学习基于 embedding 相似性**，不基于分类（Q1.10, Q3 理念 D）。
6. **收敛性分层保障**：计划阶段拦截 → openclaw 内建机制 → 诊断重构（Q3 理念 C）。
7. **用户语言与系统语言严格分离**（Q3.5）。
8. **Outcome 零系统痕迹**：outcomes/ 中只有人类可读文件（Q6.1）。
9. **Herald = 纯物流**：零质量判断。review agent 负责一切质量审查（Q6, Q7）。
10. **Dominion 按需引入**：大多数 Deed 不属于 Dominion（Q8）。
11. **Skill 由 Claude Code 审批**，人类不参与（Q5.7c）。
12. **fail-closed**：关键链路失败则停止；非关键链路可降级但标注 `degraded=true`。

---

## 2. 架构概览

### 2.1 两个进程

| 进程 | 组件 | 职责 |
|------|------|------|
| API 进程 | FastAPI + Cadence + Spine + Psyche | 接受请求、调度 routine、管理状态 |
| Worker 进程 | Temporal Worker + Activities | 执行 Deed 的步骤、调用 openclaw agent |

两进程不直接通信，通过 Temporal 和共享文件系统（`state/`、`~/My Drive/daemon/`）协作。

### 2.2 端到端数据流

```
用户 → Portal Voice → Router Agent → Brief + Plan → 用户确认
→ POST /submit → Will.enrich() → Temporal Workflow
→ RetinueManager 分配池实例 → 步骤执行（subagent）
→ review agent 审查（rework if needed）→ Herald 搬运 → outcome 写入
→ Nerve emit → record/learn/witness routine → Psyche 更新
```

### 2.3 废弃概念

| 废弃概念 | 替代 |
|---------|------|
| cluster / cluster_id | embedding 相似性检索 |
| SemanticSpec | Brief |
| IntentContract | Brief |
| Strategy (champion/challenger) | Lore 经验自然积累 |
| deed_type（作为分类键） | Brief.complexity |
| work_scale | Brief.complexity |
| semantic_cluster | 废弃，无替代 |
| strategy_candidates/experiments/promotions | 废弃 |
| quality_contracts/*.json（按 cluster） | Instinct 偏好 + Brief.depth |
| mapping_rules.json | 废弃 |
| capability_catalog.json | agent_capabilities.json |
| user_rating (int 1-5) | user_feedback (json, 选择题) |
| chain / chain_id | Writ |
| Herald quality gate | review agent（workflow 内）|
| trigger 类型枚举 (manual/cron/on_complete) | 统一事件订阅 |

---

## 3. Psyche（系统大脑）

三组件：Memory（知识）、Lore（经验）、Instinct（偏好）。对用户不可见（Q1.8），Console 可查看修改。

### 3.1 Memory

- 存储：`state/memory.db`（SQLite + embedding 向量）
- 条目结构：`{id, content, tags, embedding, relevance_score, created_utc, updated_utc}`
- **容量上限 + 热度衰减**（Q1.1）：被引用时 relevance 回升，长期不引用则衰减。超限时先合并相似低分条目，仍超限淘汰最低分
- **冲突处理**（Q1.2）：新记忆直接覆盖旧的矛盾记忆
- **embedding 检索**（Q1.10）：通过 cortex.embed 生成向量，语义相似度 + 阈值过滤。废弃固定 cluster 标签
- **版本化**（Q1.9）：state/ 目录内建独立 git repo，Spine 修改后自动 commit

### 3.2 Lore

- 存储：`state/lore.db`（SQLite）
- 经验记录结构（Q4.2a）：

```python
LoreRecord = {
    "deed_id": str,
    "objective_embedding": vector,
    "objective_text": str,
    "complexity": str,           # pulse/thread/endeavor
    "step_count": int,
    "plan_structure": dict,      # DAG（steps + depends_on）
    "outcome_quality": dict,     # review 评分
    "token_consumption": dict,   # {provider: tokens}
    "success": bool,
    "duration_s": float,
    "created_utc": str,
    "user_feedback": dict | None, # 选择题结果
    "rework_history": dict | None,
}
```

- **检索**（Q4.2b）：仅在 Voice 阶段使用，score = sim(embedding) × 0.6 + recency × 0.2 + quality_bonus × 0.2。complexity 硬过滤。返回 top-3
- **衰减**（Q1.3）：带时间戳和使用计数，长期未命中自动衰减权重。衰减到阈值以下标记为 stale

### 3.3 Instinct

- 存储：`state/instinct.db`（SQLite）
- 全局偏好 key-value（Q7.5a）：`require_bilingual`, `default_depth`, `default_format`, `default_language`, `pool_size_n`, `provider_daily_limits`, `deed_ration_ratio`, `output_languages`
- **偏好 confidence**（Q1.5）：`confidence = min(sample_count / threshold, 1.0)`
- **不按 cluster 索引**：废弃 quality_profiles 表（Q4.5c）。场景化偏好交给 Lore（Q7.5c）

### 3.4 Psyche 一致性

不做显式冲突检测（Q1.7）。优先级：显式指令 > 统计偏好 > 单次观察 > 默认策略。通过 prompt 拼接顺序隐式解决。

---

## 4. Spine（自主神经系统）

### 4.1 Routine 列表

| Routine | 频率 | 职责 |
|---------|------|------|
| pulse | 10 min | 健康检查（gateway/temporal/LLM），gate 设定，排障检测 |
| record | 事件驱动 | deed_completed 时写 Lore 经验 |
| witness | adaptive | 分析 Lore 趋势，更新 Instinct 偏好，系统健康统计 |
| learn | 事件驱动 | Deed 结束时从池实例 workspace 提取认知 → Memory |
| distill | 每日 | Memory 热度衰减 + 合并压缩（Q1.1） |
| focus | adaptive | 注意力调整（embedding 索引维护等） |
| relay | 事件驱动 | 池实例分配时 Psyche 快照写入；定期更新 router agent |
| tend | 每日 | state/ git commit、日志清理（30 天）、池实例残留检查、archive GC |
| librarian | 每 6h | deed_root → archive 归档、archive 过期清理（90 天） |

新增子任务归入（Q2.7）：
- Memory embedding 索引维护 → nerve handler（Psyche Memory 变更时触发）
- daily log 清理 → tend
- state/ git commit → tend
- 知识源可信度调整 → witness
- Lore 策略衰减 → librarian

### 4.2 Routine 执行保障

- **超时**（Q2.1）：默认 120s，LLM 密集型 300s
- **depends_on**（Q2.3）：下游检查上游最近一次是否成功，未成功则跳过本轮
- **故障隔离**（Q2.1）：失败后不阻塞下游。连续 3 次失败 → 排障
- **日志**（Q2.2）：`state/spine_log.jsonl`（routine 名、时间、成功/失败、产出摘要）
- **adaptive 调度**（Q2.8）：多维信号加权（Psyche 变更频率、用户活跃度、产出质量、错误率、时段感知）
- **降级**（Q2.9）：记录在 `state/spine_status.json`，Console 可观测。pulse 检测连续降级 → 自动排障。用户不感知降级

### 4.3 Nerve 事件总线

- 进程内同步事件总线，handler 内联运行
- **持久化**：`state/events.jsonl`（event_id, event, payload, timestamp, consumed_utc）
- **at-least-once**：进程重启时扫描未消费事件重触发（Q2.4）
- tend routine 清理超过 30 天旧事件
- **存储定位**：Nerve = L0 易失层（内存），关键事件 write-through 到 events.jsonl

### 4.4 自动排障（Q2.11）

- **触发**：同一 routine 连续 3 次失败（spine_log 统计），或 Nerve handler 连续 3 次失败（events.jsonl 统计）。pulse 每 10 分钟检测
- **流程**：暂停 routine → Telegram 通知 → Claude Code CLI 诊断修复 → 验证 → 恢复/标记 repair_failed
- **保护**：单次 10 分钟超时，24h 内最多排障 3 次。排障期间其他 routine 正常运行。修改通过 git commit 记录

### 4.5 看门狗（Q2.13）

- 独立 cron job（每 5 分钟），< 50 行 shell 脚本
- 检查：进程存活、API 响应、pulse 最后执行时间（30 分钟内）
- 通知兜底：Telegram（直接 curl Bot API）→ macOS 桌面通知 → `~/daemon/alerts/` 日志
- `~/daemon/alerts/TROUBLESHOOTING.md`：静态排障指南，daemon 启动时写入
- **关键原则**：看门狗不依赖 daemon 任何模块，不做修复只做通知

### 4.6 系统生命周期（Q2.12）

| 状态 | 含义 | 行为 |
|------|------|------|
| `running` | 正常运行 | 接受新任务，routine 正常调度 |
| `paused` | 暂停 | 不接受新任务，运行中 Deed 继续完成，routine 继续 |
| `restarting` | 重启中 | pause → 等待 → 重新初始化 → running |
| `resetting` | 清零重启 | 停止 → 清理运行时状态 → bootstrap → 重启 |
| `shutdown` | 关机 | pause → 等待 → 保存状态 → 清空池实例 → 退出 |

操作入口：CLI、Console、API（`POST /system/{action}`）。状态持久化：`state/system_status.json`。

### 4.7 Spine 与 Temporal 的边界（Q2.10）

routine 内 LLM 调用保持在 API 进程内，改为异步（asyncio）不阻塞 API 主循环。如果实测超过 60 秒，迁到 Temporal 作为 activity。当前不预迁移。

---

## 5. Voice（用户意图理解）

> 详见 `INTERACTION_DESIGN.md`（交互设计的唯一权威文档）。

### 5.1 入口分野（Q3.1）

| 入口 | 职责 |
|------|------|
| Portal | 唯一任务提交入口。**Deed = Chat Session**（对话 + 任务状态 + 产出展示三合一） |
| Telegram | 通知推送 + 严格命令式交互（/cancel、/status）。白名单命令 + 编号列表 + 数字选择。非命令消息一律忽略。adapter 内存状态机，超时 60 秒清除。**不提供反馈入口** |
| Console | 系统治理观测，不提交任务 |
| CLI | 不独立提交任务 |

### 5.2 Voice 流程（Q3.5）

Portal 核心范式：**Deed = Chat Session**。每个 Deed 是一个 chat session，100% 复刻 Claude 网页端对话行为。对话从任务提交开始，贯穿执行、完成、反馈的全过程。

由 Counsel agent（MiniMax M2.5）驱动。通过 system prompt 模拟 Claude Opus 语气。暖机时校准。

**完成标志 = 双重确认**：Design 通过收敛性验证 + 用户确认执行。

**核心设计**：daemon 是耐心的一方，适应意图漂移，不被用户急躁带偏。追问不超过必要程度。每轮回复附带当前对 Brief 的理解摘要。

**Design 展示 = 富 UI 计划组件**（圆角卡片，不是 markdown 文本），按 Deed 复杂度分三种形态：
- Errand：无计划组件，一句话描述
- Charge：纵向时间线卡片（圆点节点 + 连接线 + 顶部进度条）
- Endeavor：分段式阶段卡片（顶部分段进度条 + 当前 Passage 展开为时间线）

计划组件在 chat 中**原地刷新**，daemon 的文字进度消息独立。

**草稿保留**：未完成的 Voice session 保留为草稿。系统运行期间内存保留，重启时清除。

**执行控制**：chat 顶栏按钮（暂停/继续/取消/重新执行）+ 用户在 chat 中直接打字调整方向。

**设计准则**：静态学 Claude，动态学 Apple。5 个关键转场动效（T1-T5）全部有流畅过渡。

### 5.3 Brief（Q3.6a）

替代 SemanticSpec + IntentContract：

```python
@dataclass
class Brief:
    objective: str          # 用户目标（原文）
    complexity: str         # pulse | thread | endeavor
    step_budget: int        # 步数上限
    language: str           # zh | en | bilingual
    format: str             # 用户偏好提示（可空）；实际产出格式由自适应决定
    depth: str              # brief | standard | thorough
    references: list[str]   # 用户提供的参考资料
    confidence: str         # high | medium | low（对复杂度判断的置信度）
    quality_hints: list[str] # 用户显式质量要求（Q4.5b）
```

confidence 度量"复杂度判断的置信度"。confidence=low 时保守选择较高复杂度等级（Q3.6c）。

### 5.4 复杂度等级（Q3.2a）

| 复杂度 | 步数上限 | 典型任务 |
|--------|---------|---------|
| pulse | 1 | 快速查询、简单问答 |
| thread | 2-6 | 研究报告、代码开发 |
| endeavor | 多阶段，每阶段 2-8 步，最多 5 阶段 | 系统设计、大型调研 |

Dominion 不是复杂度等级，是组织层级。Endeavor 有双层约束：每阶段限制步数 + 限制阶段数。

**复杂度判断的学习机制**（Q3.2b）：初始 LLM 估算 → Lore 记录预估 vs 实际 → witness/learn 分析 → 下次注入修正建议。

### 5.5 Plan 验证（Q3.3b）

1. DAG 无环
2. 每步 agent 类型合法（collect/analyze/build/review/render/apply）
3. depends_on 引用合法
4. 总步数 ≤ step_budget
5. 至少一个 terminal 步骤

验证失败 LLM 重生成（最多 2 次），仍失败则回退到 Voice。

**Plan 生成的 prompt 构成**（Q3.3a）：用户原始输入 + agent 词汇表（一句话能力描述）+ 步数预算 + Lore 参考（最近 3 条相似 plan）。保持简洁，不注入完整 Psyche。

**BOOTSTRAP_METHODS 转为暖机初始 Lore 记录**，不作为运行时强制模板（Q3.3c）。

### 5.6 不收敛任务的处理（Q3.4）

系统永远不拒绝用户需求。处理路径：引导补充 > 自动缩窄（endeavor）> 转为 Dominion 管理。没有"降级执行"。

**运行时复杂度修正**（Q3.2d）：不是"计数重试"，而是诊断 session 行为 → 查 Lore 历史解法 → 只对失败步骤更细粒度分解 → 学习写入 Lore。用用户语言告知变化。

如果仍不收敛，Router 以自然语言向用户建议分步推进。系统永远不单方面终止。

### 5.7 openclaw 收敛配置（Q3.7）

所有 agent 类型都开启 loop detection。阈值按 agent 类型差异化：

| agent | warning | critical | breaker |
|-------|---------|----------|---------|
| collect | 10 | 20 | 30 |
| analyze | 8 | 16 | 24 |
| build | 15 | 30 | 45 |
| review | 8 | 16 | 24 |
| render | 8 | 16 | 24 |
| apply | 10 | 20 | 30 |

通过轮询 session 状态获取结果，检查 `abortedLastRun` 字段（Q3.7c）。

### 5.8 Semantic 层重构（Q3.6）

capability_catalog.json → agent_capabilities.json（agent 能力描述）。mapping_rules.json → 废弃。IntentContract → 废弃，由 Brief 替代。Psyche 注入分两层：意图理解阶段注入轻量 Lore plan 参考，Will enrich 阶段注入 Instinct 偏好和 Memory（Q3.8）。

---

## 6. Will（决策层）

### 6.1 enrich 流程（Q4.1）

```
normalize(Brief 校验)
→ complexity_defaults(填充执行参数)
→ quality_profile(Instinct 偏好 + Brief.depth)
→ model_routing(agent_model_map)
→ ration_preflight(估算 + 配额检查)
→ gate_check(系统健康)
```

废弃环节：semantic derivation（已由 Voice 产出 Brief）、lore consult in enrich（Will 不使用 Lore 检索）、strategy apply（策略概念废弃）、complexity probe（Brief.complexity 已确定）。

**模块组织**：will.py（主流程）+ will_enrich.py（合并保留部分）+ will_model.py（精简）。删除 will_semantic.py 和 will_steps.py。

**新增职责**：Brief 完整性校验在 normalize 做（防御性编程）。Plan DAG 验证在 Voice 阶段已完成，Will 不重复。

### 6.2 Complexity 默认值表（Q4.2c）

| 参数 | pulse | thread | endeavor |
|------|-------|--------|----------|
| concurrency | 1 | 2 | 4 |
| timeout_per_step_s | 120 | 300 | 600 |
| rework_limit | 0 | 1 | 2 |

暖机阶段校准，此后 Instinct 可调（Q4.2d）。暖机两个目标：校准默认值表 + 填充 Lore 初始经验库。

### 6.3 模型路由（Q4.4）

主维度：`agent_model_map`（config/model_policy.json）

| agent | 模型 | Provider |
|-------|------|----------|
| router | MiniMax M2.5 | minimax-cn |
| collect | MiniMax M2.5 | minimax-cn |
| analyze | DeepSeek R1 | deepseek |
| build | MiniMax M2.5 | minimax-cn |
| review | Qwen Max | qwen |
| render | GLM Z1 Flash | zhipu |
| apply | MiniMax M2.5 | minimax-cn |

废弃 `by_semantic_cluster`、`by_risk_level` 维度。不主动增加场景化模型选择维度——通过 Lore 经验学习实现，不通过规则（Q4.4b）。token 记录在 cortex_usage.jsonl（Q4.4d）。

### 6.4 Ration 管控（Q4.6）

- **MiniMax**：prompt 次数制（100/5h 滚动窗口），调用 `/coding_plan/remains` 查询实时额度，不自己计数
- **其他 provider**：token 制，daemon 自设每日限额
- **单 Deed 上限**：窗口/日限额 × 50%（暖机测定）
- ration 不足 → Deed 排队，Portal 显示配额信息。定时任务到期但 ration 不足 → 排队不跳过（Q4.6b）

### 6.5 Gate（Q4.7）

Gate 是系统级熔断开关，只关心基础设施是否健康。不是限并发或省预算。

| 条件 | gate | 行为 |
|------|------|------|
| 全部健康 | GREEN | 所有 Deed 正常 |
| 部分不可用 | YELLOW | pulse 照常，thread 低优先排队，endeavor 排队 |
| 全部不可用 | RED | 所有 Deed 排队 |

区分排队原因：`gate_red/yellow` vs `ration_exceeded`（Q4.7）。

### 6.6 Submit Payload（Q4.8）

```json
{
  "brief": { ... },
  "plan": { "steps": [...] },
  "metadata": {
    "source": "portal_voice | writ_trigger | dominion_advance | warmup",
    "writ_id": null,
    "dominion_id": null,
    "priority": 5
  }
}
```

用户在 Portal 的两种调整方式（Q4.8b）：参数微调（不改 plan 结构，不需重新验证）+ 自然语言修改意见（Router 重新生成 plan 并验证）。用户不直接操作 plan 结构。

API 调用保留为内部接口（Cadence/Dominion/暖机），非用户入口（Q4.8c）。

### 6.7 策略废弃（Q4.3）

"策略"不再作为独立概念，被 Lore 经验吸收。废弃 strategy_candidates、strategy_experiments、strategy_promotions。不需要选拔机制（A/B 测试）——任务不重复、参数空间小、探索自然发生、试错代价高。

### 6.8 质量要求（Q4.5）

**四层来源**：用户显式说明 > Lore 历史 > Instinct 偏好 > 系统默认值。高层覆盖低层同名规则，不同名叠加。

用户显式质量要求写入 Brief.quality_hints（Q4.5b）。Instinct 质量偏好走 embedding 相似度（Q4.5c）。

**质量底线分两层**（Q4.5d）：

不可协商（hardcoded）：forbidden_markers、language_consistency、format_compliance、academic_format（中文 GB/T 7714、英文 APA/Chicago）。

可调整（学习动态调整）：min_word_count、min_sections、min_domain_coverage、require_references。

---

## 7. 执行层

### 7.1 Retinue 池模型（Q1.11）

**核心设计：预创建 agent 池（Retinue）+ 主 session + subagent 执行。**

添加 agent 在任何模式下都会触发 gateway restart，因此不能运行时动态创建/销毁 agent。

- **池实例预注册**：bootstrap 时在 openclaw.json 注册 145 个 agent（6 角色 × 24 + router）
- **N = 24**（默认，下限 16），写入 Instinct 可调
- **模板目录**：`templates/<role>/`（SOUL.md、TOOLS.md、可选 REFERENCES/）
- **RetinueManager**：负责分配/归还、模板填充/清空、Psyche 快照写入、主 session 管理

**openclaw 概念**：

- **Agent**：配置实体（身份、模型、tools、workspace），定义在 openclaw.json。每个 agent 有独立 memory 目录
- **Session**：agent 内的一次对话。full mode 能读写 agent 记忆，minimal mode 不能
- **Subagent**：session 内发起的子任务调用，运行在独立 subagent lane（默认并发 8），拥有独立 context window

### 7.2 Deed 生命周期

```
Allocation:
  1. RetinueManager 为该 Deed 用到的每种 agent 类型分配一个空闲池实例
  2. 从 templates/<role>/ 复制 SOUL.md、TOOLS.md → 实例 agentDir
  3. 将 Psyche 快照写入实例 workspace/memory/MEMORY.md
  4. 标记实例为 occupied
  5. 创建主 session（full mode）

Execution:
  6. Temporal activity 向主 session 发送步骤指令
  7. 主 session 发起 subagent 调用执行该步骤
  8. 同一 agent 的多个步骤可通过各自 subagent 并行执行
  9. subagent 完成后结果返回主 session，主 session 更新 agent 记忆
  10. 跨 agent 步骤间数据传递：通过 deed_root 文件系统

Return:
  11. learn routine 从实例 workspace 提取有价值认知 → 写入 Psyche Memory
  12. 关闭主 session
  13. 清空实例 agentDir 和 workspace/memory/
  14. 标记实例为 idle，归还池
```

**并发处理**：

- 多个 Deed 同时启动：各自分配不同池实例，互不干扰
- 池耗尽时：Deed 排队等待，不降级执行（保证记忆隔离）
- 同一 Deed 内同一 agent 的多个步骤：通过主 session 发起多个 subagent 并行执行
- 跨 agent 步骤依赖：由 Temporal DAG 管理

**两层定位**：

- openclaw 池实例 = Deed 级工作记忆（隔离、Deed 生命周期内有效）
- Psyche = 系统级长期记忆（有淘汰/合并机制，跨 Deed 积累）

### 7.3 步骤执行（Q5.1）

1. Workflow Kahn 拓扑排序确定就绪步骤
2. Checkpoint 恢复（幂等性）
3. Skill 注入（Router 在 plan 生成阶段动态选择）
4. 向池实例主 session 发指令 → subagent 执行
5. 等待返回 + Temporal heartbeat
6. 检查 `abortedLastRun`（正常完成 vs 熔断）
7. 产出写入 `deed_root/steps/{step_id}/output.md`

**并发控制三层**：Workflow DAG（max_parallel_steps）+ Temporal worker（线程池）+ openclaw subagent lane（默认 8）。

### 7.4 步骤间数据传递（Q5.1）

- 同 agent 内：通过 agent 记忆（主 session full mode）
- 跨 agent：通过 `deed_root/steps/{step_id}/output.md`
- 不通过 Temporal payload 或 outcome 目录

### 7.5 Rework 机制（Q5.4）

**review agent 独立承担全部质量审查。Herald = 纯物流，无任何质量判断。**

rework 由 review agent 评估结果驱动。review 输出结构化评分（§8.5），不达标时基于评分维度追溯到源步骤触发 rework。不换模型重试。rework_ration 默认值 pulse=0, thread=1, endeavor=2。

**不收敛处理**：circuit breaker 触发 → 不触发普通 rework → 进入诊断 session（Router 分析 → 查 Lore → 重构 instruction）→ 新步骤在 Workflow 内部提交（Q3.2d）。

**用户可见性**：普通 rework 不通知；不收敛诊断 Portal 显示；rework_ration 耗尽 Telegram 推送。

### 7.6 Endeavor 阶段管理（Q5.5）

- **Temporal `wait_condition` + Signal**：Passage 完成后 workflow 挂起，状态持久化到 Temporal 数据库，用户确认后 Signal 恢复
- **逐阶段生成 plan**：Voice 只生成第一个 Passage 详细 steps + 后续粗略目标。每个 Passage 完成后基于产出生成下一个
- **用户可以**：确认继续、调整方向、取消、不做（无超时限制）

### 7.7 用户干预（Q5.3）

| 维度 | Cancel | Pause |
|------|--------|-------|
| 语义 | 终止并销毁 | 暂停并保留 |
| 可逆性 | 不可逆 | 可恢复 |
| 产物 | 删除 deed_root 下所有产出 | 原样保留 |
| 确认 | 需二次确认 | 不需要 |

Cancel 后从 Portal 完全消失。入口：Portal 按钮 + Telegram /cancel。

### 7.8 Skill 管理（Q5.7）

- **skill_type 分类**：每个 skill 必须在 SKILL.md 头部声明 `skill_type`
  - `capability`：能力增强——给 agent 带来新的能力（工具集成、新工作流、外部系统对接）
  - `preference`：偏好编码——将行为规则、协议、质量门控编码为 agent 指令
- **动态选择**：Router 在 plan 生成时从 `config/skill_registry.json` 匹配（capability_tags + compatible_agents + status + skill_type）
- **失败处理两层**：agent 内部自主处理局部故障；只有步骤整体不达标才触发 daemon 层 rework。单次 skill 失败 ≠ 步骤失败
- **审批**：Claude Code（非人类）。连续 N 次 degraded/failed → 提议 deprecated

### 7.9 openclaw session 管理（Q5.6）

三层：池实例（常驻）→ 主 session（Deed 生命周期）→ subagent（步骤生命周期）。

监控三层保障：openclaw 内建（timeout + loop detection）→ Activity 阻塞等待检查 → Temporal heartbeat。

清理：subagent 自动结束、主 session Deed 结束时关闭、池实例 memory Deed 结束时清空、启动时恢复异常实例。

### 7.10 Routine 与池的配合（Q2.6）

- **relay**：Deed 启动时由 RetinueManager 调用，从 templates/ 填充 agentDir + Psyche 快照写入。定期 relay 用于更新常驻 router agent
- **learn**：Deed 结束时由 RetinueManager 触发，从池实例 workspace 提取认知
- **tend**：session 清理覆盖池实例上的主 session 和 subagent 归档。idle 池实例的 agentDir 和 workspace/memory/ 应为空目录
- **启动恢复**：daemon 启动时扫描所有池实例，将 occupied 状态的实例关闭主 session、清空并归还

---

## 8. 交付层

### 8.1 核心约束

- **outcomes/ 零系统痕迹**：零 deed_id、零系统术语、零 JSON。用户看到纯粹的文档
- **"伪人"原则**：产出格式自适应，由 task type + instinct prefs + lore 历史决定，不硬编码
- **Herald = 纯物流**：零质量判断。review agent 负责一切质量审查
- **review vs Herald 分野**：review = 判断（workflow 内），Herald = 执行（workflow 后）。零重叠
- **存储位置**：`~/My Drive/daemon/outcomes/{YYYY-MM}/{date time title}/`，Google Drive 同步
- **deed↔outcome 映射**：`state/herald_log.jsonl`（JSONL append-only）
- **目录名统一 outcomes（复数）**

### 8.2 Outcome 结构（Q6.1）

```
outcomes/YYYY-MM/YYYY-MM-DD HH.MM 标题/
  ├── 标题（中文）.md
  ├── 标题（中文）.pdf
  ├── Title (English).md
  ├── Title (English).pdf
  └── summary.txt
```

零 JSON、零 deed_id、零系统术语。Herald activity 写入前做系统痕迹清洗（确定性正则替换，不涉及 LLM）。bilingual 四个文件，非 bilingual 时文件名不带语言标记（Q6.1b）。

### 8.3 Archive 结构（Q6.1b）

精简快照，按时间组织：

```
archive/YYYY-MM/deed_id/
  ├── manifest.json    (Deed 元数据，不含 quality_score)
  ├── steps/           (各步骤 output.md + meta.json)
  └── review_report.json
```

- librarian routine 延迟清理 deed_root（Herald 后不立即清理）
- Portal 追评时展示步骤产出摘要 + review 评分，不展示 agent 内部日志
- archive 主要用于追评和审计，Spine 通常不回溯（例外：witness 回溯分析系统性问题）
- failed Deed 归档，cancelled Deed 不归档

### 8.4 Herald 流程

1. 同步：Herald activity 写 outcome → `~/My Drive/daemon/outcomes/`
2. 同步：写 `state/herald_log.jsonl` 索引
3. 同步：Nerve emit `herald_completed`
4. 异步：librarian routine 归档 deed_root → archive，然后清理 deed_root

### 8.5 Review 评分维度（Q7.1）

review agent 是 DAG 的最后一步（在 Herald 之前），独立承担全部质量审查。

| 维度 | 含义 |
|------|------|
| coverage | 信息覆盖面 |
| depth | 分析深度 |
| coherence | 逻辑一致性 |
| accuracy | 事实准确性（research/analysis 类） |
| format_compliance | 格式规范 |

0-1 浮点，SOUL.md 中定义锚点描述。

**Brief.depth 影响 rework 阈值，不影响评分标准**：

| depth | coverage ≥ | depth ≥ |
|-------|-----------|---------|
| brief | 0.5 | 0.4 |
| standard | 0.6 | 0.6 |
| thorough | 0.7 | 0.7 |

靠用户反馈间接校准，不做"review 的 review"。

### 8.6 Bilingual 产出（Q6.4）

同一 render 步骤产出两份，各自遵循本语言规范：
- 中文：GB/T 7714 引用/中文排版
- 英文：APA/Chicago 引用/英文排版
- 内容相同，格式规范独立

render agent 负责所有非代码产出的最终格式化。代码产出不经过 render。review agent 同时审查两份时自然覆盖内容一致性（Q6.4c）。

双语产出由 render agent 负责，Herald 只搬运。instinct pref `output_languages` 可配置，默认 `["zh","en"]`。

### 8.7 渲染管线（Q6.2）

- Workflow 在启动 render activity 前合并依赖步骤产出为 `deed_root/render_input.md`
- 同一 render 步骤产出两份
- 渲染失败走 rework，rework_limit 计入总预算
- render agent 负责所有非代码产出的最终格式化。具体产出格式由自适应决定

### 8.8 Outcome 与 Archive 的生命周期（Q6.5）

- Herald 同步写 outcome，librarian 异步写 archive 并清理 deed_root
- **outcomes 永久保留**（Google Drive 空间充足）
- **archive 保留 90 天**，librarian 定期清理

### 8.9 Telegram 推送（Q5.2）

- pulse/thread：完成时推一次（摘要 + Portal 链接）
- endeavor：每个 Passage 完成后推一次 + 最终推送
- 失败/需干预时推一次
- 执行过程中不推送

### 8.10 用户进度可见性（Q5.2）

- **Portal**：按 plan 步骤结构显示进度（pending → running → done/failed），不显示 agent 实时输出。Endeavor 额外显示当前阶段
- **时间预估**："假进度条"——基于已完成步数/总步数，不承诺精确剩余时间

---

## 9. 评价与学习

### 9.1 用户反馈（Q7.2）

**Chat 内 inline 选择组件**（plan mode 风格），非打分。Deed 级反馈，不做步骤级（Q7.2d）。

Deed 完成 → 状态转 awaiting_eval → daemon 在 chat 中发送带 inline 选择组件的消息：

**单选**：符合预期(`satisfactory`) / 基本达标(`acceptable`) / 未达预期(`unsatisfactory`) / 方向偏离(`wrong`)

**多选**（未达预期/方向偏离时展开）：关键信息缺失(`missing_info`) / 分析深度不足(`depth_insufficient`) / 存在事实性错误(`factual_error`) / 格式或排版不当(`format_issue`) / 偏离原始需求(`wrong_direction`)

选择完成后 daemon 跟进"还有什么想说的吗？"，用户可写文字评语(`comment`)或直接离开。

```json
{
  "overall": "satisfactory | acceptable | unsatisfactory | wrong",
  "issues": ["depth_insufficient", "missing_info", ...],
  "comment": "自由文本或 null"
}
```

不做选择就离开 = user_feedback=null → quality_bonus=0（中性）。系统主要依赖 review 评分运转（Q7.2b）。

**Telegram 不提供反馈入口。** 反馈统一在 Portal chat 中完成。

**修改反馈**（Q7.2e）：awaiting_eval 期间（48h）用户可回到 chat 重新选择，新反馈覆盖旧反馈。过期后 chat 只读。过期前 12h Telegram 提醒。

**Endeavor Passage 轻量反馈**：Passage 完成消息末尾附加 👍/👎 按钮（记入 Lore，不计为 user_feedback，不阻塞执行）。

### 9.2 Review/用户冲突 = 诊断事件（Q7.2c）

当 review_score 与 user_feedback 严重不一致时：

1. Lore 中两个信号**原样保留**，冲突条目标记 `review_user_conflict: true`
2. quality_bonus 冲突时 = 0（中性）
3. **witness 用 LLM 分析冲突原因**，判断走哪个纠正通道：
   - review 评分维度没覆盖用户真正在意的 → 进化 review SOUL.md
   - Voice 阶段没捕获真实意图 → 改进 Voice 追问策略
   - 某维度阈值设置不合理 → 调整阈值
   - 偶发无模式 → 不做调整
   - 以上仅为示例，不是 if-else 规则

**原则**：用户不一定比 review 更专业，review 也不一定比用户更准确。冲突本身是最有价值的信号。诊断交给 LLM，纠正通道是固定的，选哪条路是自适应的。

### 9.3 awaiting_eval 过期

自动转 completed + `feedback_expired=true`。四个用途：Lore 学习权重、反馈率统计、自进化信号、审计区分。

### 9.4 Deed 完成后的数据流

| 目标 | 写入者 | 内容 |
|------|--------|------|
| Lore | record routine | 经验记录（embedding + plan + quality + feedback） |
| Memory | learn routine | 从池实例 workspace 提取的认知 |
| Instinct | witness routine | 全局偏好统计更新 |

### 9.5 Learn Routine（Q7.3b）

- 结构化提取：数据源质量问题、skill 使用记录
- 语义提取：LLM 判断 agent memory 中的可泛化知识
- learn = 生产新知识（Deed 结束时），distill = 压缩已有知识（定时）——不重叠（Q7.3d）

### 9.6 Witness Routine（Q7.3c）

- 分析最近 20 条 Lore 经验，adaptive 调度频率
- 计算 quality_score 趋势、rework 率、user_feedback 分布、agent 表现、token 消耗
- 更新 Instinct 偏好、写入 `state/system_health.json`

### 9.7 Instinct 偏好演化（Q7.5）

- 全局偏好列表（Q7.5a）：require_bilingual、default_depth/format/language、pool_size_n、provider_daily_limits、deed_ration_ratio
- witness 定期批量更新，某选项占比 > 70% → 更新 default（Q7.5b）
- Instinct 只存储全局偏好，场景化偏好交给 Lore（Q7.5c）

### 9.8 暖机设计（Q7.4）

- `scripts/warmup.py`：约 25 条预设任务
- 覆盖 complexity × agent × format × language × 边界情况
- 三个成功标准：Lore ≥ 20 条 + complexity 默认值稳定 + 全 agent 覆盖 ≥ 3 次
- 完成后推送 5 条随机 outcome 到 Telegram，用户抽查
- 暖机 = 开发完成后的最后阶段，是自动化程序。一切功能必须暖机前就绪

---

## 10. 目标管理（Dominion-Writ-Deed）

> 详细设计见 `.ref/TRACK_LANE_RUN.md`（该机制的唯一权威文档）。以下为摘要与实施要点。

### 10.1 Dominion（Q8.1）

- **按需引入**：大多数 Deed 不属于 Dominion
- **创建由系统内部完成**：router 识别用户长期意图 / witness 发现主题聚类 → 用自然语言与用户确认意图 → 内部创建 Dominion。用户不接触"Dominion"概念（不可见原则）
- **状态**：active / paused / completed / abandoned（witness 提醒，用户确认意图，系统执行状态变更）
- **删除**：只影响系统内部关联，outcomes/ 不受影响
- **数据**：`state/dominions.json`
- **metadata**：dominion_id、objective、status、writs、max_concurrent_deeds（默认 6）、max_writs（默认 8）、instinct_overrides（可选）、created/updated_utc、progress_notes

### 10.2 Writ 与统一事件触发（Q8.2）

**统一事件订阅机制，不枚举 trigger 类型。**

Writ 始终属于某个 Dominion。触发方式统一为订阅 Nerve 事件：

```yaml
# cron 触发：Cadence 产生 schedule.tick 事件
trigger:
  event: "schedule.tick"
  filter: {cron: "0 9 * * 1", tz: "Asia/Shanghai"}

# 因果串联：订阅另一条 Writ 的 Deed 完成事件
trigger:
  event: "deed.completed"
  filter: {writ_id: "writ_a_id"}
```

**外部事件通过适配器（adapter）归一化为 Nerve 事件**：

```
POST /events/ingest
{"event": "page_changed", "payload": {...}, "source": "crawler_adapter"}
```

适配器是极简独立脚本/服务，跟 watchdog 和 Telegram adapter 同一思路。当前只建立 adapter 机制和统一触发接口，不实现其他外部适配器。

- Writ 之间的依赖通过事件订阅自然表达（`deed.completed` + filter），不需要 `depends_on_writ` 字段
- Writ 关系结构 = DAG（`split_from`: str, `merged_from`: list[str]），级联禁用时 merge 节点需所有来源都禁用才级联
- 模板填充由 dominion_writ.py 负责，查 Psyche（Memory/Lore）拿动态数据
- 循环保护：Writ 不消费自身产生的 Deed 完成事件
- **on_complete Writ 与 endeavor Passage 不重叠**：endeavor = 同一 workflow 内部多阶段；Writ 因果串联 = 不同 workflow 之间串联
- 资源限制三级：系统（pool_size=24, reserved_independent_slots=4）、Dominion（max_concurrent_deeds=6, max_writs=8）、Writ（max_pending_deeds=3）。设限制不建调度器
- **数据**：`state/writs.json`

### 10.3 Deed 标识（Q8.3）

- 统一 UUID，metadata 区分归属（dominion_id, writ_id），归属由 router 内部判断
- rework = 同一 deed_id 的不同 attempt（`deed_root/attempts/{attempt_n}/`）
- Dominion-Writ-Deed 结构对用户不可见（不可见原则），Portal/Telegram 只呈现自然语言进展和结果

### 10.4 自进化 Dominion（补充决策）

暖机自己做第一个 Dominion。暖机结束后自动开启常驻自进化 Dominion：

- **Writ A：能力优化**——skill、模型、阈值、prompt
- **Writ B：机制迭代**——daemon 研究前沿 → push 到 daemon-evolution 仓库 → Claude Code 审核 cherry-pick

机制迭代：每周触发，全模块可提议改进，branch+commit 模式，witness 发现的问题作为优先任务。daemon 不能直接改自己的代码。

---

## 11. 自我进化

### 11.1 Skill 发现与 Benchmark（Q9.1）

- 主动搜索（每周）+ 被动发现（agent 能力缺口）
- benchmark 必须通过：下载 → 静态审计（危险操作检查 + 依赖审计）→ 沙盒测试（3-5 个 benchmark 任务）→ 效果对比
- Claude Code 审批安装。安装和淘汰都通过 git commit 记录 + Telegram 通知
- Claude Code 自动更新 TOOLS.md

### 11.2 模板进化（Q9.2）

- templates/ 可自动进化（Claude Code 修改 SOUL.md/TOOLS.md）
- witness 发现问题 → 报告提交 Claude Code → 修改 → git commit → 下次 allocation 生效
- state/ git 回滚兜底，不做 A/B 测试
- 效果观察期：修改后 N 次 Deed 效果被 witness 跟踪，显著下降自动回滚
- 模板可含参考文档：templates/<role>/ 含 SOUL.md、TOOLS.md、可选 REFERENCES/
- 修改通过 `[evolution]` 前缀 commit

### 11.3 模型策略进化（Q9.3）

- 人工更新为主，自动检测为辅。Claude Code 定期搜索 provider 新模型公告
- 渐进式引入：注册 experimental → 随机 50% 使用 → witness 对比 → 提升或移除。一次性迁移决策，不是持续 A/B
- model_policy.json 由 Claude Code 自主修改 + Telegram 通知。可回滚，有观察期

### 11.4 代码自修改（Q9.4）

| 修改类型 | 审批 |
|---------|------|
| config 修改 | Claude Code 自主 |
| 模板修改 | Claude Code 自主 |
| 源码修改 | Claude Code 自主 + Telegram 通知 |

**进化验证——比排障更严格**：必要条件（启动成功、pulse 通过、测试通过）+ 充分条件（后续 10 次 Deed 效果跟踪，quality 下降 > 15% 自动回滚）。

源码修改不需要用户确认（阻塞自动化），但必须通知且 git commit 记录。

**混合触发**：每周系统表现回顾 + 同类问题累积 > 3 次事件驱动。

**通道共享**（Q9.2c）：排障和进化同一 Claude Code 通道，commit 前缀区分 `[repair]` vs `[evolution]`。进化在系统无排障需求时才执行。

### 11.5 持续校准（Q9.5）

- complexity 默认值表暖机后继续动态调整，幅度 ±20%。Console 手动值优先级高于自动调整
- review 评分校准靠用户反馈间接校准。witness 监控 review_score 与 user_feedback 相关性。模型更新时 calibration_period
- 不需要独立 meta-routine，扩展 witness 即可。滑动窗口统计写入 system_health.json

---

## 12. Console（治理观测）

### 12.1 功能（Q10.1）

**Portal 和 Console 使用者不是同一个人，persona 不同。** Portal 使用者是 daemon 的主人（owner），通过自然语言表达意图和目标；Console 使用者是系统维护者（maintainer），对系统内部不一定有很好的理解，职责是保障系统运转，不替主人做决策。不需要权限控制。同一 FastAPI 实例，/console/* 和 /portal/* 路由隔离。

**隐私边界：** 主人的私人内容对维护者不可见。Psyche（Memory/Lore/Instinct）、Dominion objective、Deed Brief/内容、Writ brief_template、Move 产出、Offering 内容均属主人隐私，Console 不得展示。

Console 编辑功能限于：开关类、滑块类、按钮类。不做复杂文本编辑（Q2.9）。禁止原始文件编辑（JSON/Markdown/文档），所有配置编辑使用结构化控件。

**Console UI 设计约束（详见 INTERACTION_DESIGN.md §0、DESIGN_QA.md Q10.5）：**

- 使用者是"修车工"，做模块化操作，不看系统内部。严格压缩交互，原则上不出现文本输入框，不直接展示系统内文件
- 所有页面遵循同一套交互模式（列表 → 详情 → 操作）。静态学 Claude（克制、内容至上），动态学 Apple（统一交互语法、渐进式披露）
- 可读性（>3 条重复即分组）+ 可理解性（操作者抽象层级）

**可观测（运维数据）：**

| 功能 | 类型 |
|------|------|
| Dashboard 概览（健康/uptime/组件连通性） | 观测 |
| Routine 状态 | 观测 |
| Deed 运行状态（数量/状态分布，不含任务内容） | 观测 |
| Retinue 占用率 | 观测 |
| Provider 调用统计 | 观测 |
| Ward 状态 | 观测 |
| 系统日志（运维指标） | 观测 |
| Dominion/Writ 运行状态（不含 objective/brief_template） | 观测 |

**可操作（运维控制）：**

| 功能 | 类型 |
|------|------|
| Routine 开关/手动触发 | 操作 |
| 系统生命周期 pause/restart/reset/shutdown | 操作 |
| Ward 手动覆盖 | 操作 |
| Provider 模型分配（agent_model_map） | 操作 |
| Provider 配额调整 | 操作 |
| Retinue size N 调整 | 操作 |
| Dominion/Writ 运维（暂停/恢复/删除） | 操作 |

**不可观测/不可操作（主人隐私 + 主人决策）：** Psyche 查看或编辑、Dominion/Writ 创建或内容编辑、Instinct 偏好、Norm 质量配置、complexity 默认值表、Deed/Offering 内容、任务提交。

### 12.2 Dashboard（Q10.2）

系统状态+uptime、Deed 概览、池实例使用率、Provider 配额、Routine 健康、排障状态。

30 秒轮询，不需要 WebSocket。初期纯表格不做图表。

日志查看：spine_log.jsonl、events.jsonl、cortex_usage.jsonl、console_audit.jsonl。按时间过滤、关键字搜索、最近 N 条。

### 12.3 编辑能力（Q10.3）

**生效方式分两类**：
- 立即生效：routine 开关、Ward 覆盖、Provider 配额
- 需要 restart：Retinue size N、Provider 模型分配（显示警告）

审计：每次编辑写入 console_audit.jsonl。tend 清理 90 天前记录。

### 12.4 Portal 与 Console 隔离（Q10.4）

- 路由级隔离：`/portal/*` vs `/console/*`。Console 绑定 127.0.0.1 或 Tailscale
- Portal 无任何指向 Console 的链接
- 系统非 running 时 Portal 显示维护提示
- 各自独立，不统一技术栈。单页面 HTML + vanilla JS，不引入前端框架

---

## 13. 数据模型与存储

### 13.1 存储层次

| 层级 | daemon 对应 | 策略 |
|------|-------------|------|
| L0 | Nerve 内存事件总线 | write-through 关键事件 |
| L1 | state/*.json + Psyche SQLite | WAL / 变更立即写磁盘 |
| L2 | snapshots、traces、events.jsonl | 定期写入，tend 清理 |
| L3 | Drive archive | librarian 归档，90 天后删除 |

**存储优化**：Trace 分层保留（7天完整 → 90天摘要 → 删除）。Archive 分层（90天完整 → 365天精简 → 删除）。统一 GC（tend 协调）。

### 13.2 state/ 目录结构

```
state/
  ├── memory.db              # Memory（SQLite + embedding）
  ├── lore.db                # Lore（SQLite）
  ├── instinct.db            # Instinct（SQLite）
  ├── dominions.json         # Dominion 定义
  ├── writs.json             # Writ 定义
  ├── deeds/                 # 运行时目录
  │   └── {deed_id}/
  │       ├── plan.json
  │       ├── status.json
  │       ├── render_input.md
  │       └── steps/{step_id}/output.md
  ├── spine_log.jsonl        # Routine 执行日志
  ├── spine_status.json      # Routine 降级状态
  ├── events.jsonl           # Nerve 事件
  ├── cortex_usage.jsonl     # LLM 调用记录
  ├── herald_log.jsonl       # 交付索引
  ├── system_status.json     # 系统状态
  ├── system_health.json     # 健康统计
  ├── gate.json              # Gate 状态
  ├── console_audit.jsonl    # Console 操作审计
  ├── daily_stats.jsonl      # 每日统计
  ├── pool_status.json       # 池实例状态
  └── .git/                  # 独立 git（本地版本化）
```

### 13.3 外部存储

```
~/My Drive/daemon/
  ├── outcomes/              # 用户产出（永久）
  │   └── YYYY-MM/{date time title}/
  └── archive/               # 系统执行痕迹（90 天）
      └── YYYY-MM/{deed_id}/
```

### 13.4 herald_log.jsonl 记录结构

```json
{
  "deed_id": "uuid",
  "completed_utc": "iso",
  "outcome_path": "path",
  "archive_path": "path",
  "archive_status": "pending|archived|expired",
  "writ_id": "uuid|null",
  "dominion_id": "uuid|null",
  "complexity": "thread",
  "user_feedback": null
}
```

---

## 14. API 接口

### 14.1 Portal API

| 端点 | 方法 | 用途 |
|------|------|------|
| `/submit` | POST | 提交 Deed（Brief + Plan + metadata） |
| `/voice` | POST | Voice 对话（Counsel agent） |
| `/deeds` | GET | 历史 Deed 列表（从 herald_log） |
| `/deeds/{deed_id}` | GET | Deed 详情（chat 历史 + 状态） |
| `/deeds/{deed_id}/feedback` | POST | 用户反馈提交（inline 选择 + 可选 comment） |
| `/deeds/{deed_id}/cancel` | POST | 取消 Deed |
| `/deeds/{deed_id}/pause` | POST | 暂停 Deed |
| `/deeds/{deed_id}/resume` | POST | 恢复 Deed |
| `/deeds/{deed_id}/message` | POST | 用户在执行中的 chat 中发消息（调整方向等） |
| `/offerings/{deed_id}/files/` | GET | Offering 文件列表 |
| `/offerings/{deed_id}/files/{filename}` | GET | 下载 Offering 文件 |
| `/system/status` | GET | 系统状态 |
| `/ws` | WebSocket | 实时推送（chat 消息、计划组件刷新、状态变化） |

### 14.2 Console API

| 端点 | 方法 | 用途 |
|------|------|------|
| `/console/dashboard` | GET | Dashboard 数据 |
| `/console/psyche/{component}` | GET | Psyche 查看 |
| `/console/psyche/{component}/{id}` | DELETE | Psyche 条目删除 |
| `/console/instinct/preferences` | GET/PUT | Instinct 偏好编辑 |
| `/console/routines` | GET | Routine 状态 |
| `/console/routines/{name}/toggle` | POST | Routine 开关 |
| `/console/routines/{name}/trigger` | POST | 手动触发 |
| `/console/config/{key}` | GET/PUT | 可调参数编辑 |
| `/console/logs/{type}` | GET | 日志查看 |
| `/console/retinue` | GET | Retinue 实例状态 |
| `/console/dominions` | GET | Dominion 列表（只读） |
| `/console/dominions/{id}` | GET/PUT/DELETE | Dominion 观测与运维控制（暂停/恢复/删除，不可创建或编辑内容） |
| `/console/writs` | GET | Writ 列表（只读） |
| `/console/writs/{id}` | GET/PUT/DELETE | Writ 运维控制（启用/停用/删除，不可创建或编辑内容） |
| `/system/{action}` | POST | 生命周期操作 |

### 14.3 事件注入

```
POST /events/ingest
{"event": "page_changed", "payload": {...}, "source": "crawler_adapter"}
```

外部 adapter 通过此端点将外部信号归一化为 Nerve 事件（Q8.2a）。

### 14.4 Telegram

- Webhook 端点：`/telegram/webhook`
- 白名单命令：`/cancel`、`/status`
- 命令 + 数字选项交互模式

---

## 15. Config 文件

### 15.1 config/model_policy.json

```json
{
  "agent_model_map": {
    "counsel": "fast",
    "scout": "fast",
    "sage": "analysis",
    "artificer": "fast",
    "arbiter": "review",
    "scribe": "glm",
    "envoy": "fast"
  },
  "fallback_chain": ["fast", "review", "glm", "analysis"]
}
```

### 15.2 config/model_registry.json

```json
{
  "fast": {"provider": "minimax-cn", "model_id": "MiniMax-M2.5"},
  "analysis": {"provider": "deepseek", "model_id": "deepseek-reasoner"},
  "review": {"provider": "qwen", "model_id": "qwen-max"},
  "glm": {"provider": "zhipu", "model_id": "glm-z1-flash"},
  "embedding": {"provider": "zhipu", "model_id": "embedding-3"}
}
```

### 15.3 config/skill_registry.json

```json
[
  {
    "skill_id": "coding_agent_v2",
    "display_name": "Coding Agent",
    "compatible_agents": ["build"],
    "capability_tags": ["code_generation", "github"],
    "status": "active"
  }
]
```

### 15.4 config/agent_capabilities.json

每种 agent 的能力描述（LLM plan 生成时的输入）。替代废弃的 capability_catalog.json。

---

## 16. Bootstrap 与启动

### 16.1 首次启动

1. 确认 `.env` 存在且包含必要 API keys
2. 创建 `state/` 目录及子目录
3. 初始化 state/ 内建 git repo
4. 初始化 Psyche DB（memory.db, lore.db, instinct.db）
5. 在 openclaw.json 中注册 145 个 agent（6 角色 × N + router）
6. 创建对应的 agentDir 和 workspace 空目录
7. Gateway restart（一次）
8. 写入 `~/daemon/alerts/TROUBLESHOOTING.md`
9. 安装 watchdog cron job
10. 启动 API 进程 + Worker 进程

### 16.2 正常启动

1. 读取 `state/system_status.json`
2. 扫描池实例状态，清理异常退出遗留的 occupied 实例
3. 重放未消费的 Nerve 事件
4. 启动 Spine Cadence
5. 启动 API server
6. 启动 Temporal worker

### 16.3 暖机

- `scripts/warmup.py`：约 25 条预设任务
- 覆盖 complexity × agent × format × language
- 成功标准：Lore ≥ 20 条，全 agent 覆盖，默认值稳定
- 完成后推送 5 条随机 outcome 到 Telegram，用户抽查
- 暖机阶段启用 Claude Code 自动排障。暖机前搭好框架
- 暖机阶段做 skill 发现，作为暖机 Dominion 的一条 Writ

---

## 17. 质量保障

### 17.1 质量四层来源（Q4.5a）

1. 用户显式说明（最高）
2. Lore 历史经验
3. Instinct 用户偏好
4. 系统默认值（最低）

### 17.2 不可协商底线（Q4.5d）

- `forbidden_markers`：产出不得包含系统标记
- `language_consistency`：语言与 Brief.language 一致
- `format_compliance`：格式可用（PDF 可渲染、code 语法正确）
- `academic_format`：学术文体强制对应引用规范

### 17.3 Rework 阈值（按 Brief.depth）

| depth | coverage ≥ | depth ≥ |
|-------|-----------|---------|
| brief | 0.5 | 0.4 |
| standard | 0.6 | 0.6 |
| thorough | 0.7 | 0.7 |

### 17.4 必做的生产机制

| 机制 | 状态 |
|------|------|
| API 熔断 | 暖机前完成 |
| 磁盘空间监控 | 暖机前完成 |
| 配置迁移 | 暖机前完成 |
| 通知失败队列 | 暖机前完成 |
| 备份恢复 | 暖机前完成 |
| Console 审计日志 | 暖机前完成 |
| daily_stats.jsonl | 暖机前完成 |
