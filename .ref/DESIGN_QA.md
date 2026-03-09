# Daemon 设计决策录

> 本文档是所有已确认设计决策的权威记录。每次新会话必须先读此文档。
> 旧版本（含完整讨论过程）保留在 `DESIGN_QA_v1_archive.md`。

## 待确认（留待协作 session）

以下为 UI/交互相关，尚未最终确认：
- Q8.4 周期任务的用户体验 — 已确认方向（自然语言对话式），细节待暖机验证
- Q8.5 Dominion 推进的用户交互 — 已确认方向（对用户不可见，witness 主动沟通），细节待暖机验证

已确认（2026-03-09 协作 session）：
- Q6.3 交付通知与用户获取 → 见下方 §6 已填入
- Q7.2(a) 用户反馈选择题设计 → 见下方 §7 已填入
- Q7.2(e) 追评入口 → 见下方 §7 已填入

---

## 阶段 1：系统大脑（Psyche: Memory / Lore / Instinct）

### Q1.1 Memory 容量与淘汰

热度衰减 + 合并压缩。每条记忆带 relevance_score，被引用时回升，长期不引用则衰减。达到上限时先合并相似低分记忆为摘要，仍超限才淘汰最低分的。

### Q1.2 Memory 冲突处理

新记忆直接覆盖旧的矛盾记忆，不保留冲突历史，不询问用户。

### Q1.3 Lore 策略退化

Lore 策略带时间戳和使用计数，长期未命中的策略自动衰减权重。衰减到阈值以下标记为 stale，不再参与决策（但保留，可被重新验证激活）。

### Q1.4 Lore 冷启动

冷启动时使用内置默认策略（硬编码合理默认值）。系统自主积累经验后逐步替代默认策略。Console 提供策略查看和手动调整能力。用户不感知 Lore 的存在。

### Q1.5 Instinct 偏好的置信度

Instinct 偏好带 confidence 字段（基于样本量）。低 confidence 偏好在决策中权重低，高 confidence 偏好权重高。confidence = min(sample_count / threshold, 1.0)。

### Q1.6 知识源分级的动态性

知识源分级由 Spine routine 自动维护。触发条件：引用该源的任务获得低评价时下调，高评价时上调。周期性 routine 也可主动检测源的可用性/质量变化。不是用户触发。

### Q1.7 Psyche 三组件的一致性

不做显式冲突检测。靠 prompt 组装顺序隐式解决：Instinct 偏好（统计）放最后，权重最高。Memory 中的显式用户指令（"以后都用 X"）视为最高优先级。

优先级：显式指令 > 统计偏好 > 单次观察 > 默认策略。零实现成本，只是 prompt 拼接约定。

### Q1.8 Psyche 的可观测性

Psyche 对用户完全不可见。Console（治理观测端）可查看和修改 Psyche 内容。Portal/Telegram 不暴露任何 Psyche 细节。

### Q1.9 Psyche 的备份与恢复

state/ 目录内建独立 git repo，纯本地版本化。Spine 每次修改 Psyche 后自动 commit。有完整历史可 diff/回滚。不推到任何 remote。异地备份走 Time Machine 等本地工具。

### Q1.10 Psyche 跨 Dominion 隔离

全局共享，不做硬隔离，不做预定义 cluster 标签。Memory 引入 embedding 检索（cortex.embed），靠语义相似度 + 阈值过滤自然解决跨领域污染。上线前必须实现。Memory 查询增加 `dominion_id` 过滤维度：同 Dominion 知识优先注入，独立 Deed 查全局（详见 DOMINION_WRIT_DEED.md §6.1）。

### Q1.11 OpenClaw Agent 记忆与 Daemon Psyche 的对接

**核心设计：预创建 Retinue + 主 session + subagent 执行**

添加 agent 在任何模式下都会触发 gateway restart，因此不能运行时动态创建/销毁 agent。

- 7 个 agent type 是静态配置模板（counsel/scout/sage/artificer/arbiter/scribe/envoy）
- agent memory 是 per-agent 的，不是 per-session → 共享 agent 会导致跨 Deed 记忆污染
- 采用预创建 Retinue 方案：启动时预注册 N 个实例，Deed 分配空闲实例，结束后清理记忆归还

**系统启动时的 agent：**

- openclaw.json 中注册 **counsel**（常驻，用户对话 + DAG 中的 counsel 步骤）
- 6 个角色各预注册 N 个 Retinue 实例（如 scout_0, scout_1, ..., scout_23），每个有独立 agentDir 和 workspace 目录
- **N = 24**（默认，下限 16），写入 Instinct 可调。总计 144 + 1 counsel = 145 个 agent
- Retinue 实例在 bootstrap 时注册到 openclaw.json + 创建空目录结构，gateway restart 一次
- 角色模板文件存放在 `templates/<role>/`（SOUL.md、TOOLS.md），分配时复制到 Retinue 实例 agentDir

**openclaw 概念：**

- **Agent**：配置实体（身份、模型、tools、workspace），定义在 openclaw.json。每个 agent 有独立 memory 目录
- **Session**：agent 内的一次对话。**full mode** 能读写 agent 记忆，**minimal mode** 不能
- **Subagent**：session 内发起的子任务调用，运行在独立 subagent lane（默认并发 8），拥有独立 context window

Retinue 实例运行主 session（full mode），通过 subagent 执行各步骤。主 session 管理记忆累积，subagent 提供步骤间上下文隔离和并行执行能力。

**生命周期：**

```
Deed 启动（Allocation）：
  1. RetinueManager 为该 Deed 用到的每种 agent 类型分配一个空闲 Retinue 实例
  2. 从 templates/<role>/ 复制 SOUL.md、TOOLS.md → 实例 agentDir
  3. 将 Psyche 快照写入实例 workspace/memory/MEMORY.md
  4. 标记实例为 occupied
  5. 创建主 session（full mode）

Deed 执行中：
  6. Temporal activity 向主 session 发送 Move 指令
  7. 主 session 发起 subagent 调用执行该 Move
  8. 同一 agent 的多个 Move 可通过各自 subagent 并行执行
  9. subagent 完成后结果返回主 session，主 session 更新 agent 记忆
  10. 跨 agent Move 间数据传递：通过 deed_root 文件系统

Deed 结束（Return）：
  11. learn routine 从实例 workspace 提取有价值认知 → 写入 Psyche Memory
  12. 关闭主 session
  13. 清空实例 agentDir 和 workspace/memory/
  14. 标记实例为 idle，归还 Retinue
```

**并发处理：**

- 多个 Deed 同时启动：各自分配不同 Retinue 实例，互不干扰
- Retinue 耗尽时：Deed 排队等待，不降级执行（保证记忆隔离）
- 同一 Deed 内同一 agent 的多个 Move：通过主 session 发起多个 subagent 并行执行
- 跨 agent Move 依赖：由 Temporal DAG 管理

**两层定位：**

- openclaw Retinue 实例 = Deed 级工作记忆（隔离、Deed 生命周期内有效）
- Psyche = 系统级长期记忆（有淘汰/合并机制，跨 Deed 积累）

**实现要点：**

- 新增 `RetinueManager`：负责 Retinue 实例分配/归还、模板填充/清空、Psyche 快照写入、主 session 生命周期管理
- Will 模块：Deed 启动时调 RetinueManager 获取各角色的 Retinue 实例
- 角色模板管理：`templates/<role>/` 存放 SOUL.md、TOOLS.md，allocation 时复制，return 时清空
- 启动时检查：扫描所有 Retinue 实例状态，将异常退出遗留的 occupied 实例清空并归还

---

## 阶段 2：自主神经系统（Spine Routines + Nerve Events）

11 个 Spine Routines：pulse、intake、record、witness、distill、learn、judge、focus、relay、tend、curate。Nerve 是进程内同步事件总线，handler 内联运行。

### Q2.1 Routine 故障隔离与自动排障

- 每个 routine 执行有超时保护（默认 120s，LLM 密集型如 learn 放宽到 300s）
- 失败后不阻塞下游：下游 routine 检查上游最近一次是否成功，没成功则跳过本轮
- 连续 3 次失败 → 触发排障（详见 Q2.11）

### Q2.2 Routine 执行可观测性

每次 routine 执行写一条到 `state/spine_log.jsonl`（routine 名、开始/结束时间、成功/失败、产出摘要）。tend routine 定期清理超过 30 天的旧记录。

### Q2.3 Routine 执行顺序与依赖

调度器强制 depends_on。downstream routine cron 到达时，检查 spine_log 中上游 routine 最近一次执行是否成功完成。未完成则跳过本轮。

### Q2.4 Nerve 事件的可靠性

Nerve emit 时同步写入 `state/events.jsonl`（event_id, event, payload, timestamp, consumed_utc）。handler 成功后标记 consumed_utc。进程重启时扫描未消费事件，重新触发对应 handler（at-least-once 保证）。handler 连续失败走排障机制。

### Q2.5 Nerve 事件的持久化

Nerve 事件写入 `state/events.jsonl`，内存 deque 保留作为快速查询缓存，持久化文件作为可靠性保障和审计追溯。tend routine 清理超过 30 天的旧事件。

### Q2.6 Routine 与预创建 Retinue 的配合

- **relay**：Deed 启动时由 RetinueManager 调用，从 templates/ 填充 agentDir + 将 Psyche 快照写入 MEMORY.md。保留定期 relay 用于更新常驻 counsel agent
- **learn**：Deed 结束时由 RetinueManager 触发，从 Retinue 实例 workspace 提取认知
- **tend**：session 清理覆盖 Retinue 实例上的主 session 和 subagent 归档。idle Retinue 实例的 agentDir 和 workspace/memory/ 应为空目录
- **启动恢复**：daemon 启动时扫描所有 Retinue 实例，将 occupied 状态的实例关闭主 session、清空并归还

### Q2.7 Routine 新增需求

按执行频率和故障影响归入现有 routine：

- Memory embedding 索引维护 → nerve handler（Psyche Memory 变更时触发）
- daily log 清理 → tend routine 增加子任务
- state/ git commit → tend routine 增加子任务
- 知识源可信度调整 → witness routine 增加子任务
- Lore 策略衰减 → curate routine 增加子任务

### Q2.8 Adaptive 调度的反馈信号

adaptive 调度引入多维信号：

- Psyche 变更频率：写入密集 → 缩短间隔
- 用户活跃度：有用户交互 → 缩短间隔
- routine 产出质量：无有效产出 → 拉长间隔
- 错误率：Deed 失败率高 → witness/learn 加速
- 时段感知：白天更频繁，夜间拉长间隔
- 各信号加权计算综合间隔，不是简单 if-else

### Q2.9 Routine 的降级模式

- 降级状态记录在 `state/spine_status.json`，Console 可观测
- pulse 检测到连续降级 → 自动触发排障
- Console 不推送通知，用户不感知降级。只有排障失败才通过 Telegram 通知
- Console 编辑功能限于：开关类、滑块类、按钮类。不做复杂文本编辑

### Q2.10 Spine 与 Temporal 的边界

routine 内 LLM 调用保持在 API 进程内，改为异步（asyncio）不阻塞 API 主循环。如果实测超过 60 秒，迁到 Temporal 作为 activity。当前不预迁移。

### Q2.11 自动排障机制

**触发条件：**

- 同一 routine 连续 3 次失败（从 spine_log 统计）
- 或 Nerve handler 连续 3 次失败（从 events.jsonl 统计）
- pulse routine 每 10 分钟检测

**排障流程：**

```
1. pulse 检测到连续故障
2. 故障 routine 进入 "repairing" 状态，暂停调度
3. Telegram 通知用户
4. 调用 Claude Code（通过 CLI）：传入故障信息，诊断+修改+测试
5. 修复后重启受影响的模块
6. 重新执行故障 routine 验证
7a. 验证通过 → 恢复正常调度 → Telegram 通知
7b. 验证失败 → 标记 "repair_failed" → Telegram 通知需人工介入
```

**保护机制：** 单次排障超时 10 分钟。同一故障 24 小时内最多排障 3 次。排障期间其他 routine 正常运行。Claude Code 修改通过 git commit 记录。

### Q2.12 系统生命周期管理

**五个状态：**

| 状态 | 含义 | 行为 |
|---|---|---|
| `running` | 正常运行 | 接受新任务，routine 正常调度 |
| `paused` | 暂停 | 不接受新任务，运行中 Deed 继续完成，routine 继续 |
| `restarting` | 重启中 | pause → 等待 → 重新初始化 → running |
| `resetting` | 清零重启 | 停止 → 清理运行时状态 → bootstrap → 重启 |
| `shutdown` | 关机 | pause → 等待 → 保存状态 → 清空 Retinue 实例 → 退出 |

操作入口：CLI、Console、API（`POST /system/{action}`）。当前状态写入 `state/system_status.json`。

### Q2.13 排障机制自身故障（守望者问题）

独立于 daemon 主进程的极简看门狗：

- **实现**：独立 cron job（系统 crontab，每 5 分钟），< 50 行 shell 脚本
- **检查**：进程存活、API 响应、spine_log 最后 pulse 记录是否在 30 分钟内
- **通知兜底**：Telegram（直接 curl Bot API）→ macOS 桌面通知 → 本地日志
- **通知内容包含具体操作步骤**，用户照做即可
- `~/daemon/alerts/TROUBLESHOOTING.md`：静态排障指南，daemon 启动时写入

**关键原则：** 看门狗不依赖 daemon 任何模块，不做修复只做通知，自身极简几乎不可能挂。

---

## 阶段 3：用户意图理解（Voice → Semantic → Design DAG）

### 核心设计理念

**理念 A：入口与行为明确绑定。** 每个入口（Portal、Telegram、CLI、API）有明确职责边界。

**理念 B：废弃固定 cluster 分类，改为复杂度驱动的步数约束。**

- agent 类型是固定词汇表（scout/sage/artificer/arbiter/scribe/envoy）
- LLM 自由组合 agent 生成步骤序列，受复杂度对应的步数上限约束
- Endeavor 有双层约束：每阶段限制步数 + 限制阶段数
- 复杂度判断是自我学习机制

**理念 C：收敛性保障是分层的。**

1. 计划阶段拦截：不收敛的任务不进入执行
2. 执行阶段：openclaw Tool-Loop Detection + circuit breaker
3. 超时 ≠ 不收敛：超时是故障检测，不是收敛性判据
4. 出错（error）→ rework 重试；不收敛（loop/breaker）→ 回到计划层重新分解

**理念 D：学习机制基于 embedding 相似性，不基于分类。** Lore、Instinct、Will 等所有需要"经验"的环节统一通过 embedding 检索。

### Q3.1 入口分野

**(a) Portal 是唯一的任务提交入口。** CLI 和 Voice 不独立提交任务。Voice 是 Portal 的子功能。系统故障报警由 pulse 自动排障 + watchdog 独立监控覆盖。

**(b) Voice 是 Portal 提交流程的前置步骤。** 用户在 Portal compose 界面通过对话理解意图，产出 Design 后用户确认提交。Voice 不绕过 Portal 直接执行。

**(c) Telegram 支持严格的命令式交互。** 白名单命令（/cancel、/status）+ 编号列表 + 数字选择。非命令消息一律忽略。adapter 内存状态机跟踪，超时 60 秒清除。

### Q3.2 复杂度判断

**(a) 复杂度等级与步数上限（暖机时验证调整）：**

| 复杂度 | 步数上限 | 典型任务 |
|--------|---------|---------|
| errand | 1 步 | 快速查询、简单问答 |
| charge | 2–6 步 | 研究报告、代码开发 |
| endeavor | 多阶段，每阶段 2–8 步，最多 5 阶段 | 系统设计、大型调研 |

Dominion 不是复杂度等级，是组织层级。

**(b) 复杂度判断的学习机制：**

1. 初始判断：LLM 根据用户输入估算
2. 运行积累：Lore 记录预估 vs 实际
3. 学习修正：witness/learn 分析积累数据，调整偏好权重
4. 查询反馈：下次注入 Lore 的历史修正建议

**(d) 运行时复杂度修正——诊断 → 查 Lore → 针对性重构：**

不是"计数重试"，而是：诊断 session 行为 → 查 Lore 历史解法 → 只对失败 Move 更细粒度分解 → 学习写入 Lore。用用户语言告知变化，不暴露系统术语。

如果仍不收敛，Counsel 以自然语言向用户建议分步推进。系统永远不单方面终止。

### Q3.3 LLM 自由分解的约束框架

**(a) Design 生成的 prompt 构成：** 用户原始输入 + agent 词汇表（一句话能力描述）+ 步数预算 + Lore 参考（最近 3 条相似 Design）。保持简洁，不注入完整 Psyche。

**(b) Design 验证约束：** DAG 无环、agent 类型合法、depends_on 引用合法、总步数 ≤ 上限、至少一个 terminal Move。验证失败 LLM 重生成（最多 2 次），仍失败则回退到 Voice。

**(c) BOOTSTRAP_METHODS 转为暖机初始 Lore 记录，不作为运行时强制模板。**

### Q3.4 不收敛任务的用户体验

**(a) 系统永远不拒绝用户需求。** 处理路径：引导补充 > 自动缩窄（endeavor）> 转为 Dominion 管理。没有"降级执行"。

Dominion 推进方式：每阶段完成后带成果和建议回到 Voice，用户确认后推进。系统不自主推进。

**(b) 运行时不收敛与 Q3.2(d) 统一设计。**

**(c) endeavor 阶段数和步数上限可通过 Console 调整。**

### Q3.5 Voice 的定位与生命周期

**(a) Voice 是 Portal 的子功能。**

**(b) Voice 对话终止——双重确认：** 系统生成通过收敛性验证的 Design + 用户明确同意执行。两个都满足才结束。

核心设计原则：系统耐心、适应意图漂移、不被用户急躁带偏、Design 展示可视化 DAG。

**Counsel 语言风格：** 虽使用 MiniMax M2.5 模型，但通过 system prompt 模拟 Claude 对话风格：简洁、直接、不用 emoji、不啰嗦。暖机时校准。

**(c) 未完成的 Voice session 保留为草稿。** 系统运行期间内存保留，重启时清除。

**全局约束——用户语言与系统语言严格分离：** 用户语言（任务/目标/结果）面向用户界面；系统语言（deed/dominion/writ/move/design/will）仅在代码/日志/Console，全部英文，任何情况不翻译。

### Q3.6 Semantic 层重构

**(a) SemanticSpec + IntentContract 统一重构为 Brief：**

```python
@dataclass
class Brief:
    objective: str              # 用户目标（原文）
    complexity: str             # errand | charge | endeavor
    step_budget: int            # 步数上限
    language: str               # zh | en | bilingual
    format: str                 # 用户偏好提示（可空）；实际产出格式由自适应决定
    depth: str                  # glance | study | scrutiny
    references: list[str]       # 用户提供的参考资料
    confidence: str             # high | medium | low（对复杂度判断的置信度）
```

**(b)** capability_catalog.json → 改为 agent_capabilities.json（agent 能力描述）。mapping_rules.json → 废弃。

**(c)** confidence 度量"复杂度判断的置信度"。confidence=low 时保守选择较高复杂度等级。

### Q3.7 openclaw 收敛机制

**(a) 所有 agent 类型都开启 loop detection。**

**(b) 阈值按 agent 类型差异化：**

| agent | warning | critical | breaker |
|-------|---------|----------|---------|
| scout | 10 | 20 | 30 |
| sage | 8 | 16 | 24 |
| artificer | 15 | 30 | 45 |
| arbiter | 8 | 16 | 24 |
| scribe | 8 | 16 | 24 |
| envoy | 10 | 20 | 30 |

**(c) 通过轮询 session 状态获取 loop detection 结果。** 检查 `abortedLastRun` 字段，再用 `sessions_history` 判断终止原因。

### Q3.8 IntentContract 废弃

IntentContract 废弃，由 Brief 替代。Psyche 注入分两层：意图理解阶段注入轻量 Lore Design 参考，Will enrich 阶段注入 Instinct 偏好和 Memory。"继续上次的"在 Voice 层解析。

---

## 阶段 4：决策（Will → Lore → Model → Ration）

### Q4.1 Will 的新职责边界

enrich 各环节去留：

| 环节 | 去留 | 理由 |
|------|------|------|
| normalize | 保留，精简 | 校验 Brief 完整性 |
| semantic derivation | 废弃 | 已由 Voice 产出 Brief |
| lore consult | 废弃（在 enrich 中） | 执行参数由 complexity 默认值表决定 |
| quality profile | 保留，重构 | Instinct 偏好 + Brief.depth 推断 |
| strategy apply | 废弃 | 策略概念废弃 |
| model routing | 保留，精简 | agent_model_map 为主 |
| complexity probe | 废弃 | Brief.complexity 已确定 |
| ration preflight | 保留 | 估算基础改为 complexity + step_budget |
| ward check | 保留 | 不变 |

**模块组织**：保持独立模块但重组——will.py（主流程）+ will_enrich.py（合并保留部分）+ will_model.py（精简）。删除 dispatch_semantic.py 和 dispatch_steps.py。

**新增职责**：Brief 完整性校验在 Will normalize 做（防御性编程）。Design DAG 验证在 Voice 阶段已完成，Will 不重复。

### Q4.2 Lore 的 embedding 检索机制

**关键简化：检索只服务于 Voice 阶段（Design 结构参考），不服务于 Will enrich。** 执行参数由 complexity 默认值表直接决定。

**(a) 历史经验存储字段：**

| 字段 | 用途 |
|------|------|
| `deed_id` | 唯一标识 |
| `objective_embedding` | Voice 阶段 Design 参考检索 |
| `objective_text` | embedding 来源 |
| `complexity` | errand/charge/endeavor |
| `move_count` | 实际执行步数 |
| `design_structure` | DAG 结构 |
| `offering_quality` | arbiter 评分 + 用户反馈 |
| `token_consumption` | 各 provider 实际消耗 |
| `success` | 是否成功 |
| `duration_s` | 总执行时间 |
| `user_feedback` | 用户反馈选择（可空） |
| `rework_history` | 修正路径（可空） |

**(b) 检索排序：**

```
score = sim(embedding) × 0.6 + recency_decay × 0.2 + quality_bonus × 0.2
```

complexity 硬过滤（只检索同 complexity）。返回 top-3。

**(c) Will enrich 不使用 Lore 检索。** 直接用 complexity 默认值表：

| 参数 | errand | charge | endeavor |
|------|--------|--------|----------|
| concurrency | 1 | 2 | 4 |
| timeout_per_move_s | 120 | 300 | 600 |
| rework_limit | 0 | 1 | 2 |

**(d) 暖机两个目标：** 校准 complexity 默认值表 + 填充 Lore 初始经验库。

### Q4.3 策略（Strategy）废弃

"策略"不再作为独立概念，被 Lore 经验吸收。废弃 strategy_candidates、strategy_experiments、strategy_promotions。不需要选拔机制（A/B 测试）——任务不重复、参数空间小、探索自然发生、试错代价高。策略生命周期完全废弃。

### Q4.4 模型路由

**(a+b) agent_model_map 为主，Lore 经验为辅：**

- scout → MiniMax M2.5
- sage → DeepSeek R1
- artificer → MiniMax M2.5（编排者）
- arbiter → Qwen Max
- scribe → GLM Z1 Flash
- envoy → MiniMax M2.5

不主动增加场景化模型选择维度。通过 Lore 经验学习实现，不通过规则。

**(c) risk_level 废弃。** Brief.depth 已足够。

**(d) 模型选择学习通过 Lore 经验自然实现，不需要专门机制。** token 记录在 cortex_usage.jsonl。

### Q4.5 质量要求

**(a) 四层来源：** 用户显式说明 > Lore 历史 > Instinct 偏好 > 系统默认值。高层覆盖低层同名规则，不同名叠加。

**(b) 用户显式质量要求写入 Brief。** 新增 `quality_hints: list[str]`。

**(c) Instinct 质量偏好走 embedding 相似度。** 废弃 quality_profiles 表，保留 preferences key-value 存储。

**(d) 质量底线分两层：**

**不可协商（hardcoded）：** forbidden_markers、language_consistency、format_compliance、academic_format（中文 GB/T 7714、英文 APA/Chicago）。

**可调整（学习动态调整）：** min_word_count、min_sections、min_domain_coverage、require_references。

### Q4.6 预算估算与管控

**(a) 两种计费模型：**

- **MiniMax**：prompt 次数制（100/5h 滚动窗口），调用 `/coding_plan/remains` 查询实时剩余额度，不自己计数
- **其他 provider**：token 制，daemon 自设每日限额

**(b) Ration 不足时：** 可以提交新任务但进入排队。Portal 显示实时配额信息。定时任务到期但 Ration 不足 → 排队不跳过。

**(c) 单 Deed Ration 上限：** MiniMax 和其他 provider 各有单 Deed 上限比例（默认 50%），暖机测定。

### Q4.7 Ward 与并发控制

Ward 是系统级熔断开关，只关心基础设施是否健康。不是限并发或省 Ration。

- 区分排队原因：`ward_red/yellow` vs `ration_exceeded`
- errand 级任务只被 RED 阻塞；charge YELLOW 时低优先级排队；endeavor YELLOW 和 RED 都排队

### Q4.8 Voice → Will 的数据传递

**(a) submit payload 规范化：** 包含 brief + design + metadata（source, writ_id, dominion_id, priority）。source 区分 portal_voice / writ_trigger / dominion_advance / warmup。

**(b) 用户在 Portal 的两种调整方式：** 参数微调（不改 Design 结构，不需重新验证）+ 自然语言修改意见（Counsel 重新生成 Design 并验证）。用户不直接操作 Design 结构。

**(c) API 调用保留为内部接口**（Cadence/Dominion/暖机/未来扩展），非用户入口。

---

## 阶段 5：执行与用户干预（Agents → Skills → Temporal）

### Q5.1 Move 执行的完整生命周期

**Deed 启动（Allocation）→ Move 执行 → Deed 结束（Return）。**

一个 Move 的生命周期：调度启动 → Checkpoint 恢复 → Skill 注入 → 发送指令 → Subagent 执行 → 等待返回 → 检查 abortedLastRun → 产出提取 → Checkpoint 写入。

**Move 间数据传递：** 同 agent 内通过 agent 记忆（主 session full mode）。跨 agent 通过 `deed_root/moves/{move_id}/output.md`。不通过 Temporal payload 或 Offering 目录。

**并发控制三层：** Workflow DAG（max_parallel_moves）+ Temporal worker（线程池）+ openclaw subagent lane（默认 8）。

### Q5.2 用户可见的执行进度

**Portal：** 按 Design Move 结构显示进度（pending → running → done/failed），不显示 agent 实时输出。Endeavor 额外显示当前阶段。

**Telegram：** errand/charge 仅完成时推一次。endeavor 每个 Passage + 最终完成。失败/需干预推一次。执行过程中不推送。

**时间预估：** "假进度条"——基于已完成步数/总步数，不承诺精确剩余时间。

### Q5.3 用户干预

| 维度 | Cancel | Pause |
|------|--------|-------|
| 语义 | 终止并销毁 | 暂停并保留 |
| 可逆性 | 不可逆 | 可恢复 |
| 产物处理 | 删除 deed_root 下所有产出 | 原样保留 |
| 确认要求 | 需要二次确认 | 无需确认 |

Cancel 后从 Portal 完全消失。入口：Portal 按钮 + Telegram /cancel。

### Q5.4 Move 失败与 rework

**arbiter agent 独立承担全部质量审查。Herald = 纯物流，无 quality gate。**

rework 由 arbiter agent 评估结果驱动。arbiter 输出结构化评分，不达标时基于评分维度追溯到源 Move 触发 rework。不换模型重试。rework_budget 默认值 errand=0, charge=1, endeavor=2。

**不收敛处理：** circuit breaker 触发 → 不触发普通 rework → 进入诊断 session（Counsel 分析 → 查 Lore → 重构 instruction）→ 新 Move 在 Workflow 内部提交。

**用户可见性：** 普通 rework 不通知；不收敛诊断 Portal 显示 🔍；rework_budget 耗尽 Telegram 推送。

### Q5.5 endeavor 的阶段管理

**Temporal `wait_condition` + Signal：** Passage 完成后 workflow 挂起，状态持久化到 Temporal 数据库，用户确认后 Signal 恢复。

**逐阶段生成 Design：** Voice 只生成第一个 Passage 详细 Moves + 后续粗略目标。每个 Passage 完成后基于产出生成下一个。

**用户可以：** 确认继续、调整方向、取消、不做（无超时限制）。

### Q5.6 openclaw session 管理

三层：Retinue 实例（常驻）→ 主 session（Deed 生命周期）→ subagent（Move 生命周期）。

监控三层保障：openclaw 内建（timeout + loop detection）→ Activity 阻塞等待检查 → Temporal heartbeat。

清理：subagent 自动结束、主 session Deed 结束时关闭、Retinue 实例 memory Deed 结束时清空、启动时恢复异常实例。

### Q5.7 skill 的选择与调用

**(a) skill_type 分类：** 每个 skill 必须在 SKILL.md 头部声明 `skill_type`：
- `capability`：能力增强——给 agent 带来新的能力（工具集成、新工作流、外部系统对接）
- `preference`：偏好编码——将行为规则、协议、质量门控编码为 agent 指令

**(b) 动态选择：** skill_registry.json 注册所有 skill（capability_tags + compatible_agents + status + skill_type）。Counsel 在 Design 生成阶段匹配 skill 写入 move.skills。

**(c) 失败处理两层：** agent 内部自主处理局部故障；只有 Move 整体不达标才触发 daemon 层 rework。单次 skill 失败 ≠ Move 失败。

**(d) 扩展与进化：** skill_registry.json 由 Claude Code 审批维护（非人类）。Skill 使用效果追踪。连续 N 次 degraded/failed → 提议 deprecated。详细流程见阶段 9。

---

## 阶段 6：交付（Offering → 通知 → Portal）

### 核心约束

- **offerings/ 零系统痕迹**：零 deed_id、零系统术语、零 JSON。用户看到纯粹的文档
- **"伪人"原则**：daemon 对外行为不可分辨于人类专业人士
- **产出格式自适应**：由 task type + instinct prefs + lore 历史决定，不硬编码
- **Herald = 纯物流**：零质量判断，arbiter agent 负责一切质量审查
- **存储位置**：`~/My Drive/daemon/offerings/{YYYY-MM}/{date time title}/`，Google Drive 同步
- **deed↔offering 映射**：`state/herald_log.jsonl`（JSONL append-only）
- **目录名统一 offerings（复数）**

### Q6.1 Offering 的纯净性与结构

**(a) manifest.json 从 offerings/ 移除。** deed↔offering 映射走 herald_log.jsonl。

Offering 目录结构：
```
~/My Drive/daemon/offerings/2026-03/2026-03-07 14.30 研究报告/
  ├── 研究报告（中文）.md
  ├── 研究报告（中文）.pdf
  ├── Research Report (English).md
  ├── Research Report (English).pdf
  └── summary.txt
```

**(b) bilingual 四个文件。** 非 bilingual 时文件名不带语言标记。

**(c) Herald activity 负责系统痕迹清洗。** 确定性正则替换，不涉及 LLM。

### Q6.1b Vault 的定位与内容

**(a) 精简快照：** manifest.json（Deed 元数据，不含 quality_score）+ moves/ 精简拷贝（output.md + meta.json）+ arbiter_report.json。

**(b) 按时间组织（`vault/YYYY-MM/deed_id/`）。**

**(c) curate routine 延迟清理 deed_root。** Herald 后不立即清理，curate 定期扫描处理。

**(d) Portal 追评时展示 Move 产出摘要 + arbiter 评分。** 不展示 agent 内部日志。

**(e) Vault 主要用于追评和审计，Spine 通常不回溯。** 例外：witness 回溯分析系统性问题。

**(f) failed Deed 归档，cancelled Deed 不归档。**

### Q6.2 渲染管线

**(a) scribe agent 从合并后的中间产物读取。** Workflow 在启动 scribe activity 前合并依赖 Move 产出为 `deed_root/render_input.md`。

**(b) 同一 scribe Move 产出两份。** instruction 明确要求各自遵循本语言规范。

**(c) 渲染失败走 rework。** rework_limit 计入总预算。

**(d) scribe agent 负责所有非代码产出的最终格式化。** 具体产出格式由自适应决定。代码产出不经过 scribe。

### Q6.3 交付通知与用户获取

**Portal（chat 消息）：**
- daemon 在对话中发送完成消息：摘要（1-3 句话）+ Offering 预览
- Offering 预览嵌入在消息中：文本类显示开头摘要，PDF 类显示缩略图，代码类显示 diff 摘要
- bilingual 产出两份并列展示
- 消息附带"查看完整结果"链接（展开 Offering 详情 / 下载文件）

**Telegram：**
- 推送完成通知。格式：简短摘要（1-2 句）+ Portal 链接。一条消息说清
- 不附带文件（文件在 Portal / Google Drive 获取）

**Offering 文件获取：**
- Portal API 端点：`GET /offerings/{deed_id}/files/` 列出文件，`GET /offerings/{deed_id}/files/{filename}` 下载文件
- 底层读取 Google Drive 本地路径（`~/My Drive/daemon/offerings/...`）
- Telegram 通知中的 Portal 链接格式：`http://{host}:{port}/offerings/{deed_id}`
- 通过 Tailscale 从任何设备访问

**通知时机：**
- Herald 完成交付后立即推送
- Portal = WebSocket 实时事件
- Telegram = Herald activity 内同步调用 Telegram API

详见 `INTERACTION_DESIGN.md` §1.4。

### Q6.4 bilingual 产出的质量保障

**(a) 同一 scribe Move 产出两份，instruction 要求独立规范。**

**(b) arbiter agent 同时审查内容质量和格式合规。** 产出格式由自适应决定。

**(c) arbiter agent 同时审查两份时自然覆盖内容一致性。** 暖机阶段验证可靠性。

### Q6.5 Offering 与 Vault 的生命周期

**(a)** Herald 同步写 Offering（用户立即可见），curate 异步写 Vault 并清理 deed_root。

**(b) offerings 永久保留**（Google Drive 空间充足）。V2 的 6 个月删除设计废弃。

**(c) Vault 保留 90 天。** curate 定期清理。

**(d) state/herald_log.jsonl 轻量索引：**

```json
{
  "deed_id": "uuid",
  "completed_utc": "...",
  "offering_path": "...",
  "vault_path": "...",
  "vault_status": "pending|archived|expired",
  "writ_id": "uuid|null",
  "dominion_id": "uuid|null",
  "complexity": "charge",
  "user_feedback": null
}
```

---

## 阶段 7：评价与学习（Arbiter → Feedback → Spine 学习循环）

### Q7.1 arbiter agent 的评分维度

**五个维度：** coverage（信息覆盖面）、depth（分析深度）、coherence（逻辑一致性）、accuracy（事实准确性，research/analysis 类）、format_compliance（格式规范）。

0-1 浮点，SOUL.md 中定义锚点描述。

**Brief 影响 rework 阈值，不影响评分标准：**
- depth=glance：coverage >= 0.5, depth >= 0.4
- depth=study：coverage >= 0.6, depth >= 0.6
- depth=scrutiny：coverage >= 0.7, depth >= 0.7

靠用户反馈间接校准，不做"arbiter 的 arbiter"。

### Q7.2 用户反馈的收集与使用

**(a) Chat 内 inline 选择组件（plan mode 风格）。**

Deed 完成 → 状态转 awaiting_eval → daemon 在 chat 中发送带 inline 选择组件的消息：

选项（单选）：
- 符合预期，质量满意 → `satisfactory`
- 基本达标，尚可接受 → `acceptable`
- 未达预期，存在明显问题 → `unsatisfactory`
- 方向偏离，需要重新审视 → `wrong`

选了"未达预期"或"方向偏离"时，展开问题多选：
- 关键信息缺失 → `missing_info`
- 分析深度不足 → `depth_insufficient`
- 存在事实性错误 → `factual_error`
- 格式或排版不当 → `format_issue`
- 偏离了原始需求方向 → `wrong_direction`

选择完成后 daemon 跟进"还有什么想说的吗？"，用户可写文字评语或直接离开。

不做选择就离开 = user_feedback=null, quality_bonus=0（中性）。

**Telegram 不提供反馈入口。** 反馈统一在 Portal chat 中完成。

**重要：awaiting_eval 只在整个 Deed 完成后触发。** Endeavor Passage 完成时只发轻量反馈（👍/👎），不阻塞后续执行。

详见 `INTERACTION_DESIGN.md` §1.6。

**(b) user_feedback=null → quality_bonus=0（中性）。** 系统主要依赖 arbiter 评分运转。

**(c) arbiter/用户冲突 = 诊断事件，不是覆盖事件。**

当 review_score 与 user_feedback 严重不一致时：

1. Lore 中两个信号**原样保留**，冲突条目标记 `review_user_conflict: true`
2. quality_bonus 冲突时 = 0（中性）
3. **witness 用 LLM 分析冲突原因**，判断走哪个纠正通道：
   - arbiter 评分维度没覆盖用户真正在意的 → 进化 arbiter SOUL.md
   - Voice 阶段没捕获真实意图 → 改进 Voice 追问策略
   - 某维度阈值设置不合理 → 调整阈值
   - 偶发无模式 → 不做调整
   - 以上仅为示例，不是 if-else 规则

**原则：用户不一定比 arbiter 更专业，arbiter 也不一定比用户更准确。冲突本身是最有价值的信号，诊断交给 LLM，纠正通道是固定的，选哪条路是自适应的。**

**(d) Deed 级反馈，不做 Move 级。** rework 定位由 arbiter agent 评分维度追溯，不需要用户指出。

**(e) 修改反馈 = 回到 chat 重新选择。**

- awaiting_eval 期间（48 小时）：用户回到已完成 Deed 的 chat，可重新选择或补充文字。新反馈覆盖旧反馈
- awaiting_eval 过期后：chat 只读，不可再修改反馈。自动转 completed + feedback_expired=true
- 过期前 12 小时 Telegram 提醒一次

详见 `INTERACTION_DESIGN.md` §1.7。

### Q7.3 学习循环的完整链路

**(a) 分布确认：**

| Psyche 组件 | 写入内容 | 写入者 |
|-------------|---------|--------|
| Memory | 认知（源质量、关键发现） | learn routine |
| Lore | 经验（Brief embedding + Design + quality + feedback + token） | record routine |
| Instinct | 全局偏好统计 | witness routine |

**(b) learn 提取逻辑：** 结构化提取（规则：数据源质量、skill 记录）+ 语义提取（LLM 从 agent memory 提取可泛化知识）。

**(c) witness 分析：** 最近 20 条 Lore，adaptive 调度频率。分析 quality 趋势、rework 率、feedback 分布、agent 表现、token 消耗。产出写入 Instinct 偏好 + system_health.json。

**(d) distill 和 learn 不重叠：** learn = 生产新知识（Deed 结束时），distill = 压缩已有知识（定时）。

### Q7.4 暖机设计

**(a) 约 25 条暖机任务。** 覆盖 complexity × agent × format × language × 边界情况。

**(b) 自动批量运行，不需要用户参与。** scripts/warmup.py。

**(c) 三个成功标准：** Lore ≥ 20 条 + complexity 默认值稳定 + 全 agent 覆盖 ≥ 3 次。

**(d) 暖机结果需要人工抽查。** 5 条随机 Offering 推送 Telegram。

### Q7.5 Instinct 偏好的演化

**(a) 全局偏好：** require_bilingual、default_depth/format/language、retinue_size_n、provider_daily_limits、deed_ration_ratio。

**(b) witness routine 定期批量更新。** 某选项占比 > 70% → 更新 default。

**(c) Instinct 只存储全局偏好，场景化偏好交给 Lore。** 不在 Instinct 做场景化索引（那等于重新引入分类）。

### 补充决策

**awaiting_eval 过期：** 自动转 completed + feedback_expired=true。四个用途：Lore 学习权重、反馈率统计、自进化信号、审计区分。

**arbiter vs Herald 分野：** arbiter = 判断（workflow 内），Herald = 执行（workflow 后）。零重叠。arbiter Move 是 DAG 最后一步，不达标 → rework。Herald 不判断、不评分、不检查。

---

## 阶段 8：目标管理（Dominion → Writ → Deed）

> 详细设计见 `.ref/DOMINION_WRIT_DEED.md`（该机制的唯一权威文档）。

### Q8.1 Dominion 的引入条件与生命周期

**(a) 创建由系统内部完成。** counsel 识别用户长期意图 / witness 发现主题聚类 → 用自然语言与用户确认意图 → 内部创建 Dominion。用户不接触"Dominion"概念（不可见原则）。

**(b) 四种状态：** active → paused → completed / abandoned。witness 检测到 objective 似乎已达成时提醒用户确认，用户有最终决定权。

**(c) Dominion 删除只影响系统内部关联。** offerings/ 不受影响。

**(d) Dominion metadata：** dominion_id、objective、status、writs、max_concurrent_deeds（默认 6）、max_writs（默认 8）、instinct_overrides（可选）、created/updated_utc、progress_notes。

### Q8.2 Writ 与触发机制

**(a) 统一事件订阅机制，不枚举 trigger 类型。** Writ 始终属于某个 Dominion。

Writ 的触发方式统一为订阅 Nerve 事件：

```yaml
# cron 触发：Cadence 产生 cadence.tick 事件
trigger:
  event: "cadence.tick"
  filter: {cron: "0 9 * * 1", tz: "Asia/Shanghai"}

# 因果串联：订阅另一条 Writ 的 Deed 完成事件
trigger:
  event: "deed_completed"
  filter: {writ_id: "writ_a_id"}
```

**外部事件通过适配器（adapter）归一化为 Nerve 事件：**

```
POST /events/ingest
{"event": "page_changed", "payload": {...}, "source": "crawler_adapter"}
```

适配器是极简独立脚本/服务，跟 watchdog 同一思路。当前只建立 adapter 机制和统一触发接口，不实现其他外部适配器。

**(b) Writ 之间的依赖通过事件订阅自然表达。** `deed_completed` + `filter: {writ_id: "xxx"}` 即依赖声明，不需要 `depends_on_writ` 字段。

**(c) Writ 存储 Brief 模板（brief_template），每次触发时由 dominion_writ.py 填充动态数据**（查 Psyche 拿最新 Lore 经验和前序 Deed 产出）。

**(d) on_complete Writ 与 endeavor Passage 不重叠。** endeavor = 同一 workflow 内部多阶段；Writ 因果串联 = 不同 workflow 之间串联。

**(e) Writ 关系结构 = DAG。** `split_from`（str）标记拆分来源，`merged_from`（list[str]）标记合并来源。级联禁用时，merge 节点需所有来源都禁用才级联。

**(f) 资源限制三级：** 系统（retinue_size=24, reserved_independent_slots=4）、Dominion（max_concurrent_deeds=6, max_writs=8）、Writ（max_pending_deeds=3）。设限制不建调度器。

**(g) 循环保护：** Writ 不消费由自身产生的 Deed 完成事件。

### Q8.3 Deed 的组织与查询

**(a) 统一 UUID 标识。** metadata.dominion_id/writ_id 区分归属。归属由 counsel 内部判断，用户不感知。

**(b) Dominion-Writ-Deed 结构对用户不可见。** Portal/Telegram 只呈现自然语言进展和结果。Console（运维视图）可展示内部结构。

**(c) rework 是同一 deed_id 的不同 attempt。** deed_root/attempts/{attempt_n}/。

### Q8.4 周期任务的用户体验

用户不接触"周期任务"概念。用户通过自然语言表达持续关注意图（如"每周帮我看看 X 的动态"），系统内部创建 cron Writ。进展通过自然语言汇报。详见 DOMINION_WRIT_DEED.md §7.2。

### Q8.5 Dominion 推进的用户交互

Dominion 推进对用户不可见。witness 观察进展 → 用自然语言与用户沟通（如"X 方面有新进展，要不要深入看看？"）→ 用户回应 → 系统内部调整 Writ 结构或触发新 Deed。详见 DOMINION_WRIT_DEED.md §7.2。

### 补充决策

**暖机需要 Dominion-Writ：** 暖机自己做第一个 Dominion。暖机结束后自动开启常驻自进化 Dominion：
- Writ A：能力优化（skill、模型、阈值、prompt）
- Writ B：机制迭代（daemon 研究前沿 → push 到 daemon-evolution 仓库 → Claude Code 审核 cherry-pick）

机制迭代：每周触发，branch+commit 模式，witness 发现的问题作为优先任务。daemon 不能直接改自己的代码。

**chain_id 废弃：** chain 是旧概念，已从代码中移除。Writ 是全新机制。

---

## 阶段 9：自我进化（Skill Discovery → Benchmark → Deploy）

### Q9.1 Skill 发现与评估

**(a) 主动搜索 + 被动发现。** 主动：每周搜索 openclaw skill 仓库。被动：agent 报告能力缺口。

**(b) Benchmark 流程：** 下载到临时目录 → 静态审计 → 沙盒测试（3-5 个 benchmark 任务）→ 效果对比 → Claude Code 审批。

**(c) 安全审计：** 静态分析（危险操作检查）+ 依赖审计 + 沙盒测试 + 来源信誉。审计不通过直接拒绝。

**(d) Claude Code 自动更新 TOOLS.md。** 安装和淘汰都通过 git commit 记录 + Telegram 通知。

### Q9.2 模板进化

**(a) 允许模板自动进化，保守且有观察期。** witness 发现问题 → 报告提交 Claude Code → 修改 SOUL.md → git commit → 下次 allocation 生效。

**(b) state/ git 回滚兜底，不做 A/B 测试。** 效果观察期：修改后 N 次 Deed 效果被 witness 跟踪，显著下降自动回滚。

**(c) 同一 Claude Code 通道，commit 前缀区分：** `[repair]` vs `[evolution]`。进化在系统无排障需求时才执行。

**(d) 模板可含参考文档。** templates/<role>/ 含 SOUL.md、TOOLS.md、可选 REFERENCES/。

### Q9.3 模型策略进化

**(a) 人工更新为主，自动检测为辅。** Claude Code 定期搜索 provider 新模型公告。

**(b) 渐进式引入：** 注册 experimental → 随机 50% 使用 → witness 对比 → 提升或移除。一次性迁移决策，不是持续 A/B。

**(c) Claude Code 自主修改 + Telegram 通知。** 可回滚，有观察期。

### Q9.4 代码自修改的边界

**(a) Config 和源码都可修改，分级管控：**

| 类型 | 审批门槛 |
|------|---------|
| config | Claude Code 自主 |
| 模板 | Claude Code 自主 |
| 源码 | Claude Code + Telegram 通知 |

**(b) 进化验证——比排障更严格：** 必要条件（启动成功、pulse 通过、测试通过）+ 充分条件（后续 10 次 Deed 效果跟踪，显著下降 >15% 自动回滚）。

**(c) 源码修改不需要用户确认**（阻塞自动化），但必须通知且 git commit 记录。

**(d) 混合触发：** 每周系统表现回顾 + 同类问题累积 >3 次事件驱动。

### Q9.5 暖机后的持续校准

**(a) complexity 默认值表暖机后继续动态调整，幅度 ±20%。** Console 手动值优先级高于自动调整。

**(b) arbiter 评分校准靠用户反馈间接校准。** witness 监控 review_score 与 user_feedback 相关性。模型更新时 calibration_period。

**(c) 不需要独立 meta-routine，扩展 witness 即可。** 滑动窗口统计写入 system_health.json。

### 补充决策

**暖机阶段启用 Claude Code 自动排障。** 暖机前搭好框架。

**暖机阶段做 skill 发现。** 作为暖机 Dominion 的一条 Writ。

---

## 阶段 10：治理观测（Console）

### Q10.1 Console 的功能边界

**Portal 和 Console 使用者不是同一个人，persona 不同。** Portal 使用者是 daemon 的主人（owner），通过自然语言表达意图和目标；Console 使用者是系统维护者（maintainer），对系统内部不一定有很好的理解，职责是保障系统运转，不替主人做决策。不需要权限控制。同一 FastAPI 实例，/console/* 和 /portal/* 路由隔离。

**隐私边界：** 主人的私人内容对维护者不可见。Psyche（Memory/Lore/Instinct）、Dominion objective、Deed Brief/内容、Writ brief_template、Move 产出、Offering 内容均属主人隐私，Console 不得展示。将主人的隐私交给维护者查看或修改是安全危险。

**可观测（运维数据）：**

| 功能 | 类型 |
|------|------|
| Dashboard 概览（健康/uptime/组件连通性） | 观测 |
| Routine 状态（运行/失败/上次执行时间） | 观测 |
| Deed 运行状态（数量/状态分布，不含任务内容） | 观测 |
| Retinue 占用率（agent 忙/闲，不含任务内容） | 观测 |
| Provider 调用统计（调用量/token 量/错误数） | 观测 |
| Ward 状态 | 观测 |
| 系统日志（spine_log/cortex_usage/events，运维指标） | 观测 |
| Dominion/Writ 运行状态（状态/数量，不含 objective/brief_template） | 观测 |

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

**不可观测/不可操作（主人隐私 + 主人决策）：**

| 功能 | 原因 |
|------|------|
| Psyche（Memory/Lore/Instinct）查看或编辑 | 主人隐私 |
| Dominion objective / Writ brief_template 查看或编辑 | 主人隐私 |
| Deed Brief/内容 / Move 产出 / Offering 内容 | 主人隐私 |
| Dominion/Writ 创建或内容编辑 | 主人决策 |
| Instinct 偏好修改 | 主人偏好 |
| Norm 质量配置 | 主人品质要求 |
| complexity 默认值表调整 | 影响主人产出品质 |

### Q10.2 Console 可观测性仪表板

**Dashboard 指标：** 系统状态+uptime、Deed 概览、Retinue 实例使用率、Provider 配额、Routine 健康、排障状态。

30 秒轮询，不需要 WebSocket。初期纯表格不做图表。

**日志查看：** spine_log.jsonl、events.jsonl、cortex_usage.jsonl、console_audit.jsonl。按时间过滤、关键字搜索、最近 N 条。

### Q10.3 Console 编辑能力

**生效方式分三类：** 立即生效（routine 开关、阈值、ward、ration）→ 下次 Deed 生效（model_map、Instinct、quality）→ 需要 restart（retinue size N，显示警告）。

**审计：** 每次编辑写入 console_audit.jsonl。tend 清理 90 天前记录。

### Q10.4 Console 与 Portal 的交互边界

**(a) 路由级隔离。** Console 绑定 127.0.0.1 或 Tailscale。Portal 无任何指向 Console 的链接。

**(b) Portal 感知系统状态。** 非 running 时 Portal 显示维护提示。

**(c) 各自独立，不统一技术栈。** 单页面 HTML + vanilla JS，不引入前端框架。

### 补充决策

**Console 审计日志 + daily_stats.jsonl：** 暖机前加。

**生产机制清单：** API 熔断（已实现）、并发写保护（已实现）、磁盘空间监控（已实现）、通知失败队列（已实现）、备份恢复（已实现）、配置迁移（待暖机前）。

---

## 补充议题

### warmup.py 的定位

warmup.py 改造为暖机控制器。暖机设计文档在 QA 全部完成后专门写。

### embedding 不可用时的退化

暖机前必须确保 embedding 可用。cortex.py embed() 优先 zhipu embedding-3，fallback 到 openai。

### Nerve 事件丢失可接受性

Nerve 保持易失（内存），关键事件同时写 events.jsonl（write-through）。

**数据存储分层：**

| 层级 | daemon 对应 | 策略 |
|------|-------------|------|
| L0 | Nerve 内存事件总线 | write-through 关键事件 |
| L1 | state/*.json + Psyche SQLite | WAL / 变更立即写磁盘 |
| L2 | snapshots、trails、events.jsonl | 定期写入，tend 清理 |
| L3 | Drive Vault | curate 归档，90 天后删除 |

**存储优化：** Trail 分层保留（7天完整→90天摘要→删除）。Vault 分层（90天完整→365天精简→删除）。统一 GC（tend 协调）。

**暖机 = 紧跟系统正式启用的阶段。** 暖机是自动化程序。开发者的所有工作必须在暖机之前全部完成。
