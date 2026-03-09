# Daemon 设计问答录

> 目的：沿逻辑流逐阶段提问，用户回答即为设计约束。
> 方法：原则 × 组件 交叉检查，确保无遗漏。

## ⚠️ 修正说明

原 DESIGN_QA_SUPPLEMENT.md 的全部内容已合并到本文档各阶段末尾（标记为 S6-A ~ X-3）。
原文中与补充 QA 冲突的位置保留 `[⚠️ 已修正]` 标记，指向同阶段的合并内容。
DESIGN_QA_SUPPLEMENT.md 已删除。

**关键修正摘要**：
- delivery = 纯物流，零质量判断（S7-B）
- manifest.json 从 outcomes/ 移除，run↔outcome 映射走 state/delivery_log.jsonl（S6-A/B）
- 产出格式自适应，不硬编码（S6-D）
- chain_id 废弃，改 lane_id（S8-B）
- rework 由 review agent 驱动，不由 delivery 驱动（S7-B/C）

## ✅ 2026-03-08 全文审计确认

阶段 6-10 原始提议（"待用户确认"）经逐项审计，确认状态如下：

**已被补充 QA 覆盖（无需额外确认）**：Q6.1, Q6.2, Q6.4, Q6.5, Q7.1, Q7.4, Q8.1, Q10.1

**本轮确认无修改**：Q6.1b（archive 内容）, Q7.2(b)(d), Q7.3, Q7.5, Q8.2(b-e), Q9.1

**本轮修正后确认**：
- Q7.2(c)：原"以用户为准"改为"冲突=诊断事件"——review/用户冲突时 witness 用 LLM 分析原因，自适应选择纠正通道，不简单选边站
- Q8.2(a)：原"三种 trigger 类型"改为"统一事件订阅机制"——Lane 订阅 Nerve 事件触发，外部信号通过 adapter 归一化为事件，机制统一可扩展

**留待协作 session 确认（UI/交互相关）**：Q6.3, Q7.2(a)(e), Q8.4, Q8.5

---

## 阶段 1：系统大脑（Fabric: Memory / Playbook / Compass）

### Q1.1 Memory 容量与淘汰
Memory 条目会持续增长。是否需要容量上限？达到上限后的淘汰策略是什么？
（例如：按 recency 淘汰、按 relevance 评分淘汰、用户手动清理、还是无限增长？）

**答：** 需要容量上限，不手动清理。

**结论：** 热度衰减 + 合并压缩。每条记忆带 relevance_score，被引用时回升，长期不引用则衰减。达到上限时先合并相似低分记忆为摘要，仍超限才淘汰最低分的。

### Q1.2 Memory 冲突处理
新记忆与已有记忆矛盾时（例如用户偏好变化），系统应该怎么做？
（例如：新覆盖旧、保留两者并标记冲突、询问用户确认？）

**答：** 不要询问用户。

**结论：** 新记忆直接覆盖旧的矛盾记忆，不保留冲突历史。

### Q1.3 Playbook 策略退化
Playbook 记录的策略可能随时间失效（模型更新、外部环境变化）。是否需要策略过期/衰减机制？

**答：** 要有过期机制。

**结论：** Playbook 策略带时间戳和使用计数，长期未命中的策略自动衰减权重。衰减到阈值以下标记为 stale，不再参与决策（但保留，可被重新验证激活）。

### Q1.4 Playbook 冷启动
系统首次运行时 Playbook 为空。冷启动阶段的决策回退策略是什么？
（例如：内置默认策略、全部走用户确认、随机探索？）

**答：** 不走用户确认。用户不应感知 Playbook 的存在。Console 可修改。

**结论：** 冷启动时使用内置默认策略（硬编码合理默认值）。系统自主积累经验后逐步替代默认策略。Console 提供策略查看和手动调整能力。

### Q1.5 Compass 偏好的置信度
用户只做过一次评价就记录为偏好，和做过 50 次评价的偏好，权重应该一样吗？是否需要置信度机制？

**答：** 显然不应该一样。

**结论：** Compass 偏好带 confidence 字段（基于样本量）。低 confidence 偏好在决策中权重低，高 confidence 偏好权重高。具体：confidence = min(sample_count / threshold, 1.0)。

### Q1.6 知识源分级的动态性
知识源（如某个网站）的可信度可能随时间变化。分级是一次性的还是需要动态调整？谁来触发重新评估？

**答：** 不是用户触发，需要动态调整。

**结论：** 知识源分级由 Spine routine 自动维护。触发条件：引用该源的任务获得低评价时下调，高评价时上调。周期性 routine 也可主动检测源的可用性/质量变化。

### Q1.7 Fabric 三组件的一致性
Memory、Playbook、Compass 三者可能给出矛盾的指导（例如 Memory 说用户喜欢简洁，Compass 评分显示用户偏好详细）。冲突时的优先级是什么？

**答：** 需要讨论。

**结论：** 不做显式冲突检测。靠 prompt 组装顺序隐式解决：Compass 偏好（统计）放最后，权重最高。Memory 中的显式用户指令（"以后都用 X"）视为最高优先级。优先级：显式指令 > 统计偏好 > 单次观察 > 默认策略。零实现成本，只是 prompt 拼接约定。

### Q1.8 Fabric 的可观测性
用户是否需要能看到、理解、修改 Fabric 的内容？（Memory 条目、Playbook 策略、Compass 偏好）还是纯黑盒？

**答：** 用户不需要看到，纯黑盒。

**结论：** Fabric 对用户完全不可见。Console（治理观测端）可查看和修改 Fabric 内容。Portal/Telegram 不暴露任何 Fabric 细节。

### Q1.9 Fabric 的备份与恢复
Fabric 是系统的"大脑"，数据丢失等于失忆。备份策略是什么？是否需要版本化（回滚到某个时间点的认知状态）？

**答：** 需要版本管理。GitHub 会公开，个人数据不能推。

**结论：** state/ 目录内建独立 git repo，纯本地版本化。Spine 每次修改 Fabric 后自动 commit。有完整历史可 diff/回滚。不推到任何 remote。异地备份走 Time Machine 等本地工具。

### Q1.10 Fabric 跨 Track 隔离
不同 Track（如健身追踪 vs 技术前沿）的 Memory/Playbook 是否需要隔离？还是全局共享？共享的话如何避免跨领域污染？

**答：** Track 和 Memory 是两个层面，不做预定义分类。

**结论：** 全局共享，不做硬隔离，不做预定义 cluster 标签。Memory 引入 embedding 检索（cortex.embed 已有基础设施），靠语义相似度 + 阈值过滤自然解决跨领域污染。不预留"以后再做"——上线前必须实现。

### Q1.11 OpenClaw Agent 记忆与 Daemon Fabric 的对接

**背景：**
- openclaw 每个 agent 有独立 workspace/memory/ 目录（MEMORY.md + memory/YYYY-MM-DD.md + memory_search 语义检索）
- openclaw 没有记忆清理/淘汰机制，文件只增不删
- openclaw.json 支持热重载（默认 hybrid 模式），还有 RPC API `config.patch`（限流 3次/60秒）
- openclaw 的跨 session 共享记忆假设"agent = 人格"，但 daemon 中 agent = 流水线工位，跨任务共享记忆 = 污染

**核心设计：预创建 agent 池 + 主 session + subagent 执行**

添加 agent 在任何模式下都会触发 gateway restart，因此不能在运行时动态创建/销毁 agent。采用预创建池方案：启动时预注册 N 个实例，Run 分配空闲实例，结束后清理记忆归还。

agent 记忆是 per-agent 的（不是 per-session），context window 是硬物理上限（不能用 instruction 传递无限累积的上下文替代共享记忆），因此同 agent 多步骤的 Run 必须用 full mode session 共享 agent 记忆。并发 Run 必须使用不同的池实例以避免记忆污染。

每个池实例在 Run 期间运行一个**主 session**（full mode），管理 agent 记忆和 Fabric 快照。步骤通过主 session 发起 **subagent** 调用执行——subagent 在独立的 subagent lane 运行（默认并发 8），拥有独立 context window，提供并行执行能力和步骤间上下文隔离。

**系统启动时的 agent：**
- openclaw.json 中注册 **router**（常驻，用户对话 + DAG 中的 router 步骤，workspace 完整预定义）
- 6 个角色各预注册 N 个池实例（如 collect_0, collect_1, ..., collect_23），每个有独立 agentDir 和 workspace 目录（bootstrap 时为空目录，运行时按需填充）
- **N = 24**（默认，下限 16），写入 Compass 可调。总计 144 + 1 router = 145 个 agent
- 池实例在 bootstrap 时注册到 openclaw.json + 创建空目录结构，gateway restart 一次。运行期间不增不减
- 角色模板文件存放在 `templates/<role>/`（SOUL.md、TOOLS.md），分配时复制到池实例 agentDir

**openclaw 概念澄清：**
- **Agent**：配置实体（身份、模型、tools、workspace），定义在 openclaw.json。每个 agent 有独立的 memory 目录
- **Session**：agent 内的一次对话，有独立 .jsonl 记录。**full mode** 能读写 agent 记忆，**minimal mode** 不能
- **Subagent**：session 内发起的子任务调用，运行在独立的 subagent lane（默认并发 8），拥有独立 context window 和执行环境
- 池实例运行主 session（full mode），通过 subagent 执行各步骤。主 session 管理记忆累积，subagent 提供步骤间上下文隔离和并行执行能力

**生命周期：**

```
Run 启动（Allocation）：
  1. AgentPoolManager 为该 Run 用到的每种 agent 类型分配一个空闲池实例
  2. 从 templates/<role>/ 复制 SOUL.md、TOOLS.md → 实例 agentDir（每次分配使用最新模板）
  3. 将 Fabric 快照写入实例 workspace/memory/MEMORY.md
  4. 标记实例为 occupied
  5. 在池实例上创建主 session（full mode），作为该 Run 在该 agent 上的持久会话

Run 执行中：
  6. Temporal activity 向主 session 发送步骤指令
  7. 主 session 发起 subagent 调用执行该步骤（subagent 有独立 context window）
  8. subagent 在 subagent lane 运行，同一 agent 的多个步骤可通过各自的 subagent 并行执行
  9. subagent 完成后结果返回主 session，主 session 更新 agent 记忆（上下文连续）
  10. 跨 agent 步骤间数据传递：通过 run_root 文件系统（上一步产出写入 run_root/steps/{step_id}/output.md）

Run 结束（Return）：
  11. learn routine 从实例 workspace 提取有价值认知 → 写入 Fabric Memory
  12. 关闭主 session
  13. 清空实例 agentDir（删除 SOUL.md、TOOLS.md）和 workspace/memory/（恢复到空目录）
  14. 标记实例为 idle，归还池
```

**并发处理：**
- 多个 Run 同时启动：各自分配不同池实例，互不干扰
- 池耗尽时：Run 排队等待，不降级执行（保证记忆隔离）
- 同一 Run 内同一 agent 的多个步骤：通过主 session 发起多个 subagent 并行执行（subagent lane 默认并发 8）
- 跨 agent 步骤依赖：由 Temporal DAG 管理（步骤级粒度）

**数据流：**

```
下行（Allocation 时）：
  templates/<role>/ → SOUL.md/TOOLS.md 复制到池实例 agentDir
  Fabric → MEMORY.md 写入池实例 workspace/memory/ → 主 session 启动时加载

Run 执行中：
  subagent 执行产出返回主 session → 主 session 更新 agent 记忆 → 后续 subagent 通过 agent 记忆获取上下文
  产出同时写入 run_root/steps/ → 跨 agent 步骤读取

上行（Return 时）：
  实例 workspace 的记忆文件 → learn routine 提取 → Fabric Memory
  → 去重、冲突覆盖（按 Q1.2 规则）
  → 关闭主 session，清空 agentDir + workspace/memory/，归还池
```

**两层定位：**
- openclaw 池实例 = Run 级工作记忆（隔离、Run 生命周期内有效、利用 openclaw 原生记忆机制）
- Fabric = 系统级长期记忆（有淘汰/合并机制，跨 Run 积累）

**实现要点：**
- 新增 `AgentPoolManager`：负责池实例分配/归还、模板填充/清空、Fabric 快照写入、主 session 生命周期管理
- dispatch 模块：Run 启动时调 AgentPoolManager 获取各角色的池实例 id + 主 session
- Temporal activity：向主 session 发送步骤指令，主 session 通过 subagent 执行，Activity 阻塞等待返回
- learn routine：Run 结束时从池实例 workspace 提取认知
- bootstrap：首次启动时在 openclaw.json 中预注册 145 个 agent（6 角色 × 24 + router）+ 创建空目录结构 + gateway restart
- 角色模板管理：`templates/<role>/` 存放 SOUL.md、TOOLS.md，allocation 时复制到实例 agentDir，return 时清空。模板变更（skill campaign、self-improvement）自动在下次 allocation 生效
- 启动时检查：扫描所有池实例状态，将异常退出遗留的 occupied 实例清空 agentDir + workspace/memory/ 并归还

---

## 阶段 2：自主神经系统（Spine Routines + Nerve Events）

当前 11 个 Spine Routines：pulse（健康检查）、intake（收集入库）、record（执行记录）、witness（观察分析）、distill（记忆蒸馏）、learn（策略学习）、judge（策略晋升）、focus（注意力调整）、relay（快照推送）、tend（状态清理）、librarian（归档管理）。

Nerve 是进程内同步事件总线，handler 内联运行。

### Q2.1 Routine 故障隔离与自动排障

**答：** 会阻塞。需要自动排障机制接到 Claude Code。排障机制必须在运行中，系统才运行。

**结论：**
- 每个 routine 执行有超时保护（默认 120s，LLM 密集型如 learn 放宽到 300s）
- 失败后不阻塞下游：下游 routine 检查上游最近一次是否成功，没成功则跳过本轮
- **自动排障机制（详见 Q2.11）**：连续 3 次失败 → 触发排障 → Claude Code 诊断并修复

### Q2.2 Routine 执行可观测性

**答：** 按推荐做法来。

**结论：** 每次 routine 执行写一条到 `state/spine_log.jsonl`（routine 名、开始/结束时间、成功/失败、产出摘要）。tend routine 定期清理超过 30 天的旧记录。此日志也作为 depends_on 检查和排障机制的数据源。

### Q2.3 Routine 执行顺序与依赖

**答：** 按推荐做法来。

**结论：** 调度器真正强制 depends_on。downstream routine cron 到达时，检查 spine_log 中上游 routine 最近一次执行是否成功完成。未完成则跳过本轮，等下次 cron。

### Q2.4 Nerve 事件的可靠性

**答：** 不够用，依赖排障机制。

**结论：** Nerve emit 时同步写入 `state/events.jsonl`（event_id, event, payload, timestamp, consumed_utc）。handler 成功后标记 consumed_utc。进程重启时扫描未消费的事件，重新触发对应 handler（at-least-once 保证）。handler 连续失败走排障机制。

### Q2.5 Nerve 事件的持久化

**答：** 按推荐做法来。

**结论：** 同 Q2.4。Nerve 事件写入 `state/events.jsonl`，内存 deque 保留作为快速查询缓存，持久化文件作为可靠性保障和审计追溯。tend routine 清理超过 30 天的旧事件。

### Q2.6 Routine 与 Q1.11 预创建池的配合

**答：** 需要调整，所有依赖 agent 不变的机制都要改。

**结论：**（基于预创建 agent 池模型更新）
- **relay**：Run 启动时由 AgentPoolManager 调用，从 templates/ 填充 agentDir + 将 Fabric 快照写入 MEMORY.md。relay 作为 AgentPoolManager 的内部方法，不再是独立定时 routine。保留定期 relay 用于更新常驻 router agent
- **learn**：Run 结束时由 AgentPoolManager 触发，从池实例 workspace 提取认知。作为 Run 生命周期的一部分，不再是独立定时
- **tend**：session 清理覆盖池实例上的主 session 和 subagent 归档。idle 池实例的 agentDir 和 workspace/memory/ 应为空目录（tend 可检查并清理残留）
- **启动恢复**：daemon 启动时扫描所有池实例，将 occupied 状态的实例关闭主 session、清空 agentDir + workspace/memory/ 并归还（处理上次异常退出遗留）

### Q2.7 Routine 新增需求

**答：** 按推荐做法来，不引入不必要复杂度。

**结论：** 按执行频率和故障影响归入现有 routine：
- Memory embedding 索引维护 → nerve handler（Fabric Memory 变更时触发，不是独立 routine）
- daily log 清理 → tend routine 增加子任务
- state/ git commit → tend routine 增加子任务
- 知识源可信度调整 → witness routine 增加子任务
- Playbook 策略衰减 → librarian routine 增加子任务

### Q2.8 Adaptive 调度的反馈信号

**答：** 需要更多信号，要高度智能化和自动化。

**结论：** adaptive 调度引入多维信号：
- **Fabric 变更频率**：Memory/Playbook 近期写入密集 → 缩短间隔
- **用户活跃度**：近 N 小时有用户交互 → 缩短间隔
- **routine 产出质量**：上次无有效产出 → 拉长间隔；有有效产出 → 缩短间隔
- **错误率**：近期 Run 失败率高 → witness/learn 加速（需要快速诊断）
- **时段感知**：用户活跃时段（白天）routine 更频繁，夜间拉长间隔
- 各信号加权计算综合间隔，不是简单的 if-else

### Q2.9 Routine 的降级模式

**答：** 不通知用户/console。系统内部处理。Console 只做观测，交互极简。

**结论：**
- 降级状态记录在 `state/spine_status.json`，Console 可观测
- pulse routine 检测到连续降级 → 自动触发排障（Q2.11）
- Console 不推送通知，用户不感知降级。只有排障失败（系统无法自愈）才通过 Telegram 通知用户
- Console 可编辑功能限于：开关类（启用/禁用某 routine）、滑块类（调整阈值）、按钮类（手动触发某 routine）。不做复杂文本编辑

### Q2.10 Spine 与 Temporal 的边界

**答：** 按推荐做法来。

**结论：** routine 内 LLM 调用保持在 API 进程内，改为异步（asyncio）不阻塞 API 主循环。如果某个 routine 的 LLM 调用实测超过 60 秒，迁到 Temporal 作为 activity。当前不预迁移，按实测决定。

### Q2.11 自动排障机制

**触发条件：**
- 同一 routine 连续 3 次失败（从 spine_log 统计）
- 或 Nerve handler 连续 3 次失败（从 events.jsonl 统计）
- pulse routine 每 10 分钟检测

**排障流程：**

```
1. pulse 检测到连续故障
2. 故障 routine 进入 "repairing" 状态，暂停调度
3. Telegram 通知用户："系统检测到 [X] 故障，正在自动修复"
4. 调用 Claude Code（通过 CLI）：
   - 传入：故障 routine 名、最近 3 次错误日志、相关代码路径
   - Claude Code 诊断问题、修改代码、运行测试
5. 修复后重启受影响的模块
6. 重新执行故障 routine 验证
7a. 验证通过 → 恢复正常调度
    → Telegram 通知："自动修复完成，系统已恢复"
7b. 验证失败 → 标记 "repair_failed"
    → Telegram 通知："自动修复失败，需要人工介入"
    → 附带诊断摘要
```

**权限：** Claude Code 可直接修改代码并重启模块。修改通过 git commit 记录，可追溯可回滚。

**保护机制：**
- 单次排障超时上限（10 分钟）
- 同一故障 24 小时内最多排障 3 次，避免死循环
- 排障期间其他 routine 正常运行（故障隔离）

**用户感知：**
- 故障发生 → Telegram 通知
- 正在修复 → Telegram 通知
- 修复成功/失败 → Telegram 通知
- 修复过程细节 → 用户不感知，Console 可查看日志

### Q2.12 系统生命周期管理（Start / Pause / Restart / Shutdown）

**答：** 需要好好设计，当前没有这种设计。

**结论：**

**五个生命周期状态：**

| 状态 | 含义 | 行为 |
|---|---|---|
| `running` | 正常运行 | 接受新任务，routine 正常调度，agent 正常工作 |
| `paused` | 暂停 | 不接受新任务，运行中的 Run 继续完成，routine 继续运行（维护系统健康），新 Run 排队等待 |
| `restarting` | 重启中 | pause → 等待运行中 Run 完成（超时强制中断）→ 重新初始化 → running |
| `resetting` | 清零重启 | 停止所有进程 → 清理运行时状态（runs/traces/campaigns/池实例 agentDir + memory/sessions）→ bootstrap → 重启。现有 SystemResetManager 的 strict/light 模式保留 |
| `shutdown` | 关机 | pause → 等待运行中 Run 完成（超时强制中断）→ 保存状态 → 清空池实例 agentDir + memory 并归还 → 退出进程 |

**操作入口：**
- CLI：`daemon start / pause / restart / reset / shutdown`
- Console：状态显示 + 按钮操作（pause/resume/restart/reset/shutdown）
- API：`POST /system/{action}`（内部使用，reset 保留 challenge-confirm 安全门控）

**状态持久化：**
- 当前状态写入 `state/system_status.json`
- 异常退出后重启时，读取此文件恢复状态
- 如果上次是 `running` 状态异常退出 → 启动后自动扫描：清空 occupied 池实例的 agentDir + memory 并归还（Q1.11）、重放未消费事件（Q2.4）、恢复未完成 Run 的状态

**Graceful shutdown 流程：**
```
1. 标记 status = shutdown
2. 停止接受新 Run
3. 等待运行中 Run 完成（超时 5 分钟，超时则记录中断点到 state/）
4. 执行 tend routine 的清理逻辑（state/ git commit、池实例 agentDir + memory 清空并归还）
5. 关闭 Temporal worker 连接
6. 关闭 API server
7. 写入 system_status.json（status=stopped, stopped_utc, reason）
8. 退出
```

### Q2.13 排障机制自身故障（守望者问题）

**答：** 排障机制挂了，用户需要明确的、告诉他该怎么办的信息。

**结论：**

排障链依赖 pulse routine → 如果 pulse 本身挂了，整个自愈链路断裂。需要一个独立于 daemon 主进程的极简看门狗。

**看门狗设计（watchdog）：**
- **实现**：独立的 cron job（系统 crontab，每 5 分钟），一个 < 50 行的 shell 脚本
- **检查内容**：
  1. daemon 进程是否存活（`pgrep` 或检查 PID 文件）
  2. API 是否响应（`curl localhost:port/health`，超时 10 秒）
  3. `state/spine_log.jsonl` 最后一条 pulse 记录是否在 30 分钟内（pulse 每 10 分钟跑一次，30 分钟没跑 = 异常）
- **故障时通知（三层兜底）**：
  1. Telegram（直接 curl Bot API，不经过 daemon/openclaw）
  2. macOS 桌面通知（`osascript display notification`，Telegram 失败时）
  3. 本地日志（`~/daemon/alerts/`，始终写入）

- **通知内容**（包含具体操作步骤）：
```
⚠️ Daemon 系统异常

状态：[进程不存在 / API 无响应 / 内部调度停止]
最后正常时间：2026-03-07 14:30:00
持续异常时间：15 分钟

请执行以下操作：
1. 打开终端
2. 运行：cd ~/daemon && python bootstrap.py
3. 如果启动失败，运行：python scripts/state_reset.py --mode light --restart
4. 如果仍然失败，运行：cat state/spine_log.jsonl | tail -20
5. 将输出发给 Claude Code 诊断
```

**排障指南（`~/daemon/alerts/TROUBLESHOOTING.md`）：**

`~/daemon/alerts/` 是 daemon 与人类维护者唯一的系统级信息窗口。该目录在 daemon 首次启动时创建，并写入一份静态排障指南 `TROUBLESHOOTING.md`。指南内容：

1. **快速诊断清单**：进程是否在跑、API 是否响应、最近日志在哪看
2. **常见故障场景 + 对应操作**：
   - 进程不存在 → `cd ~/daemon && python bootstrap.py`
   - 进程在但 API 无响应 → 检查端口占用、重启
   - 调度停止（pulse 超时）→ `python scripts/state_reset.py --mode light --restart`
   - 全部失败 → `cat state/spine_log.jsonl | tail -20`，将输出发给 Claude Code
3. **日志位置索引**：spine_log.jsonl、events.jsonl、alerts/ 目录下的告警文件各是什么
4. **紧急联系**：将日志输出粘贴给 Claude Code 即可获得诊断

指南是**静态文件**，daemon 启动时写入（若已存在则不覆盖），不依赖运行时状态。人类维护者在任何情况下（包括 daemon 完全崩溃）都能打开这个文件获得操作指引。

**关键原则：**
- 看门狗不依赖 daemon 的任何模块（不导入 daemon 代码）
- 看门狗不做修复（它没有这个能力），只做通知
- 通知内容必须包含**具体的操作步骤**，用户照做即可
- 看门狗自身极简，几乎不可能挂（shell 脚本 + cron）
- Telegram 凭据（BOT_TOKEN、CHAT_ID）从 .env 读取
- `~/daemon/alerts/` 始终包含排障指南，即使 daemon 从未出过故障

---

## 阶段 3：用户意图理解（Dialog → Semantic → Weave DAG）

### 前置讨论：核心设计理念

在逐条提问之前，确立了以下核心设计理念作为阶段 3 所有问题的约束：

**理念 A：用户入口与行为明确绑定，做好分野。**
每个入口（Portal、Telegram、CLI、API）有明确的职责边界，不混淆。

**理念 B：废弃固定 cluster 分类，改为复杂度驱动的步数约束。**
"天气预报"和"写深度报告"能映射到同一个 cluster，说明 cluster 分类机制不可靠。LLM 做任务分解的痛点是：不能以必然收敛的方式在有限步数内分解任务。

**解决方案：**
- agent 类型是固定词汇表（collect/analyze/build/review/render/apply），不变
- LLM 自由组合 agent 生成步骤序列，但受复杂度对应的**步数上限**约束，不写死 DAG 形状
- Campaign（最复杂级别）：每阶段限制步数 + 限制阶段数 = 双层约束
- 复杂度判断是**自我学习机制**，暖机时构建初始模型，运行中持续修正

**理念 C：收敛性保障是分层的，不能只靠超时。**

1. **计划阶段拦截**：必然不收敛的任务不应进入执行。LLM 在步数预算内无法生成有限计划 = 任务不收敛，拒绝执行。计划阶段同时评估每一步的可行性（基于 Playbook 历史），不只检查总步数。

2. **执行阶段（openclaw 层）**：利用 openclaw 内建机制，不自己发明：
   - **Tool-Loop Detection**（默认关闭，需按 agent 开启）：三种检测器
     - Generic Repeat：同工具同参数重复调用
     - Known Poll No Progress：轮询无状态变化
     - Ping-Pong：两工具交替调用
   - **三档阈值**：warning(10) → critical(20) → circuit breaker(30)
   - **Session 观测**：`sessions_list` 暴露 contextTokens/totalTokens/abortedLastRun；`sessions_history` 可拉取交互记录
   - **Agent 执行约束**：`timeoutSeconds`(600s)、`contextTokens`(200k)、`maxConcurrent`(1)

3. **超时 ≠ 不收敛**：超时是故障检测（agent 挂了/卡死），不是收敛性判据。单步任务天然收敛（跑一次就结束），但复杂度被错误估计时，单步内 agent 可能不收敛（在工作但不会产出有效结果）。

4. **出错 vs 不收敛的区分与处理**：
   - openclaw 返回 error/exception → **出错** → rework（重试，可能换参数/换模型）
   - openclaw 触发 loop detection 或 circuit breaker → **不收敛** → 回到计划层重新分解（不是重试）
   - "在跑但没进展"的灰色地带 → `knownPollNoProgress` + circuit breaker + daemon 定期通过 session API 监控 token 增长趋势

**理念 D：学习机制基于 embedding 相似性，不基于分类。**

废弃 cluster 后，学习机制不需要任何形式的分类或分组。核心机制是 **Fabric Memory 的 embedding 检索**：
- 每次 run 完成后，记录任务的输入特征、plan 结构、执行效果
- 新任务到来时，通过 embedding 相似度找到最相似的历史任务，用其经验指导决策
- 相似性是连续的，不存在分类边界问题，天然处理全新类型的任务
- A/B 比较发生在"特征相似的任务之间"，不在"类别之间"

这意味着 Playbook 的策略组织、Dispatch 的模型路由、复杂度估计、质量评估等所有需要"经验"的环节，都统一基于 embedding 检索，不依赖任何预定义分类。embedding 是整个学习体系的核心机制。

---

### Q3.1 入口分野的具体边界

理念 A 确定了"入口与行为明确绑定"。当前系统的入口：
- **Portal**：完整 UI，可构造 plan JSON，POST /submit
- **Telegram**：纯通知推送（当前设计），不提交任务
- **CLI**：命令行参数提交
- **Dialog**：Router Agent 对话，可能产出 plan

**问题：** 每个入口的具体行为边界如何划定？
(a) Portal 是唯一可以提交任务的入口，还是 CLI/Dialog 也可以？
(b) Dialog（对话式交互）最终是否产出一个 plan 交给 submit 路径，还是有自己的独立执行路径？
(c) 如果 Telegram 未来要支持简单指令（如"取消任务"），这算不算破坏了"通知 only"的分野？

**答：**a Portal是唯一可以提交任务的入口。原理也很简单，如果portal打不开，修复的优先级显然更高，这里我也要问一下，portal或者系统任何部分出故障，都能报警吗？
b 这个具体是什么意思，展开讲讲，我没太看懂。
c 可以有这个功能，但是要做成严格的交互：/xxx命令+只有数字选项+数字。举个例子，先要取消任务，必须/cancel，然后telebot发当前运行任务列表1.title 2.title ……。只读取回复信息里的数字。这个机制如何实现，和telebot的机制很相关，你可以搜索查看对应的技术细节。

**结论：**

**(a) Portal 是唯一的任务提交入口。** CLI 和 Dialog 不独立提交任务。Dialog 是 Portal 的子功能（见 Q3.5），用户在 Portal 的 compose 界面通过对话式交互明确意图，最终由 Portal 界面提交。系统任何部分出故障的报警能力：已由 Q2.11（pulse 自动排障）+ Q2.13（watchdog 独立监控）覆盖，pulse 每 10 分钟检查所有服务健康状态（含 API、Temporal、openclaw gateway），watchdog 每 5 分钟从外部检查进程和 API 可达性。Portal 不可用属于 API 级故障，两层都能检测到。

**(b) Dialog 的含义：** 当前 Portal compose 界面有一个对话窗口（`#chat-history`），用户输入自然语言，系统通过 Router Agent 对话理解意图，Router 产出 plan JSON 后在 Portal 内显示 plan 卡片（`#plan-card`），用户确认后点击提交按钮，走 POST /submit 路径。所以 Dialog 不是独立入口，而是 Portal 提交流程的前置步骤。问题 (b) 原本在问 Dialog 是否可以绕过 Portal 直接触发执行——答案是不可以，Dialog 的产出必须经过 Portal 的 submit 路径。

**(c) Telegram 支持严格的命令式交互。** 不破坏"通知为主"的定位，因为命令交互是严格约束的，不是自由对话。

实现机制：Telegram Bot API 的 webhook 会把用户消息推送到 adapter。当前 adapter 的 `/webhook` 端点直接忽略所有用户输入（`"ignored": True`）。改造方案：
1. 解析 `message.text`，仅识别 `/cancel`、`/status` 等白名单命令
2. 收到 `/cancel` → 调 daemon API `GET /tasks?status=running` → 格式化为编号列表发回用户
3. 用户回复纯数字 → 调 daemon API 执行对应操作 → 发确认消息
4. 非命令、非数字的用户消息一律忽略（保持现有行为）
5. 用 adapter 内存中的简单状态机跟踪"等待用户选择"状态，超时 60 秒自动清除

### Q3.2 复杂度判断的具体机制

理念 B 确定了"复杂度驱动步数约束"。复杂度判断是自我学习机制，暖机时构建。

**问题：**
(a) 复杂度分几个等级？每个等级的步数上限是多少？（例如：简单=1-2步，中等=3-5步，复杂=6-10步，campaign=多阶段）
(b) 复杂度判断的输入是什么？纯文本分析、还是结合 Fabric 历史？
(c) 暖机时如何构建初始复杂度模型？没有历史数据时的回退策略是什么？
(d) 运行时复杂度修正：如果执行中发现复杂度被低估（如单步触发了 circuit breaker），系统如何"升级"复杂度并重新分解？这个升级有次数限制吗？

**答：**a 你也是llm，这个问题我看正适合交给你来定。暖机的时候，那些用来暖机的用例，也是你来设计，正好检测一下，你对人类复杂任务的理解
b 这里不是应该有一个学习机制吗？还是说这部分完全交给fabric存储？
c 同a
d circuit breaker是什么？我怎么从来没听说过？至于后面的问题，我知道尝试失败然后升级，升级有次数限制是一个不会错的方法。但是这方法太笨了。故障机制能这么做，但一个有学习机制的地方还这么做，我觉得学习机制被浪费了。

**结论：**

先解释术语：**circuit breaker（熔断器）** 是 openclaw 的 `globalCircuitBreakerThreshold` 配置项。当一个 agent session 连续发出 30 次工具调用但没有实质进展时，openclaw 自动终止该 session。它是 openclaw 内建的防失控机制，不是 daemon 自己的概念。

**(a) 复杂度等级与步数上限（初始方案，暖机时验证和调整）：**

| 复杂度等级 | 步数上限 | 典型任务 |
|-----------|---------|---------|
| pulse | 1 步 | 快速查询、简单问答、格式转换 |
| thread | 2–6 步 | 研究报告、代码开发、文档撰写 |
| campaign | 多阶段，每阶段 2–8 步，最多 5 阶段 | 系统设计、大型调研、多模块开发 |

注意：Track 不是复杂度等级，是组织层级（Track-Lane-Run 体系中的长期目标容器）。当 campaign 也无法收敛时，目标转为 Track 管理，系统为其规划多个可收敛的 run 逐步推进（见 Q3.4(a)）。

暖机用例设计是后续专门环节的工作，届时会覆盖各等级的边界情况。

**(b) 复杂度判断的学习机制：**

复杂度判断不是纯静态规则，也不完全交给 Fabric 被动存储。机制如下：
1. **初始判断**：LLM 根据用户输入 + agent 能力描述估算复杂度等级（冷启动阶段的唯一依据）
2. **运行积累**：每次 run 完成后，Playbook 记录 `{输入特征摘要, 预估复杂度, 实际步数, 是否触发熔断, 是否重新分解}`
3. **学习修正**：witness/learn routine 分析积累数据，发现"某类输入特征经常被低估"时，调整 Playbook 中的复杂度偏好权重
4. **查询反馈**：下次遇到相似输入时，LLM 的判断 prompt 中注入 Playbook 的历史修正建议

这形成了 `LLM 初始判断 → 执行验证 → Playbook 记录 → Spine 分析 → 反馈到下次判断` 的闭环。

**(d) 运行时复杂度修正——比"计数重试"更聪明的方式：**

当执行中发现复杂度被低估（如 openclaw 熔断触发、或 daemon 监控到 session token 持续增长无产出），不是简单地"升级复杂度 + 重试"。而是：

1. **诊断**：拉取 `sessions_history` 分析 session 的实际行为——它卡在什么地方？是某个子问题太复杂？还是整体方向有误？
2. **查 Playbook**：是否有相似任务的历史经验？之前类似情况是如何成功分解的？
3. **针对性重构**：基于诊断结果，只对失败的那个步骤进行更细粒度的分解，而不是重新分解整个任务
4. **学习写入**：这次修正的经验写入 Playbook，下次同类输入直接使用更合适的复杂度判断

没有计数器兜底。复杂度调整由系统自主完成，但**用用户语言告知用户任务的处理方式发生了变化**。用户不接触系统术语（pulse/thread/campaign/Track），但能感知到差异：

- 运行时升级复杂度 → 用户语言："这比预想的复杂一些，我调整了方案"
- 转为长期目标管理 → 用户语言："第一部分已完成，剩余部分需要继续吗？"（用户确认后续）

**统一行为原则：** 系统术语与用户严格隔离，但系统行为的变化通过自然语言传达给用户。用户始终知道自己的任务被怎样对待，只是不知道背后叫什么。分离的是术语，不是信息。

如果诊断 → 重构 → 复杂度升级到 campaign 后仍不收敛，Router 以自然语言向用户说明情况并建议分步推进。示例：

> 这个目标涉及多个独立方向：需求分析、架构设计、前端开发、后端开发、数据库设计、测试部署。一次完成不太现实，但可以分步推进。
>
> 我建议先从需求分析和架构设计开始。完成后你可以看到整体方案，再决定下一步做哪个部分。
>
> 要从这里开始吗？

不提 Track、campaign、复杂度等系统术语。用户听到的是"分步推进"、"先从这里开始"、"你来决定下一步"。系统永远不单方面终止——要么成功执行，要么回到用户。

### Q3.3 LLM 自由分解的约束框架

废弃固定 DAG 模板后，LLM 自由组合 agent 类型生成步骤序列。

**问题：**
(a) LLM 生成 plan 时，输入 prompt 需要包含哪些信息？（用户原始输入、agent 能力描述、步数上限、Playbook 历史、Fabric 记忆？）
(b) 生成的 plan 需要满足哪些结构性约束才能通过验证？（例如：DAG 无环、每步必须指定 agent 类型、depends_on 合法、总步数 ≤ 上限）
(c) 当前 Playbook 的 `BOOTSTRAP_METHODS`（4 个固定模板）还保留吗？作为 LLM 的参考示例？还是完全废弃？

**答：**
a 不知道，你想一个合适的方案，复杂度又不能太高
b 同上
c 暖机需要的用例，我认为应该比这个先进

**结论：**

**(a) Plan 生成的 prompt 构成（保持简单）：**

LLM 生成 plan 时的输入：
1. **用户原始输入**（必须）
2. **agent 词汇表**：每种 agent 的能力一句话描述（collect=信息采集, analyze=深度分析, build=代码构建, review=质量审查, render=格式渲染, apply=交付部署）
3. **步数预算**：当前复杂度等级对应的上限
4. **Playbook 参考**：最近 3 条相似任务的 plan（如果有），作为示例但不强制遵循

不注入完整 Fabric 记忆（那是执行阶段的事），不注入 Compass 偏好（那是 Dispatch enrich 的事）。保持 plan 生成环节的输入简洁。

**(b) Plan 验证约束：**

1. DAG 无环（拓扑排序通过）
2. 每步指定合法的 agent 类型（来自固定词汇表）
3. `depends_on` 引用的 step id 必须存在且在前序
4. 总步数 ≤ 当前复杂度等级的上限
5. 至少有一个 terminal 步骤（无后继）

验证失败 = plan 生成不合格，LLM 重新生成（最多 2 次），仍失败则回退到 Dialog 向用户要更多信息。

**(c) BOOTSTRAP_METHODS 的去留：**

当前 4 个固定模板不再作为运行时强制模板。它们的价值转化为：
- 暖机阶段的初始 Playbook 记录（作为 LLM 的历史参考示例）
- 冷启动时 LLM 没有 Playbook 历史可参考，这些模板提供起步基准

暖机用例会比这 4 个模板更丰富，覆盖各种复杂度等级和边界情况。暖机完成后，Playbook 中的真实执行记录逐步替代这些初始模板的参考作用。

### Q3.4 不收敛任务的用户体验

理念 C 确定了不收敛任务不进入执行。

**问题：**
(a) 计划阶段拒绝执行时，用户看到什么？只说"任务无法完成"是否足够，还是需要给出"为什么不收敛"以及"如何修改任务使其可执行"的建议？
(b) 执行中触发 circuit breaker（复杂度被低估导致的运行时不收敛），是自动重新分解还是通知用户？自动重新分解的次数上限？
(c) campaign 的阶段数上限和每阶段步数上限是固定值还是可由用户调整？

**答：**
a 实际上，计划阶段不应该拒绝执行。用户的任何需求都应该想办法被引导进入能够实施的程度。这里我们可以多谈谈。
b 这里还是和前面一样，设置一个最大尝试次数肯定不会错，但是太笨了，一定要和前面一起设计一个巧妙的办法
c 这里应该是可调整的，我认为console是可以调整这类选项的，console的编辑机制只做这类事。

**结论：**

**(a) 系统永远不拒绝用户需求。** 这是核心体验原则。不收敛的任务不进入执行，但系统也不说"做不了"。

当用户输入的任务在当前复杂度等级内无法生成收敛的 plan 时：

1. **引导补充**：通过 Dialog 对话引导用户明确模糊的部分，直到目标足够具体可以生成 plan
2. **自动缩窄**：将过于宽泛的目标拆解为多个可执行的子任务，升级为 campaign（多阶段）
3. **转为 Track 管理**：如果 campaign 级别仍无法收敛，说明这不是一次执行能完成的目标，而是一个**长期目标**。系统将其建立为 Track（组织层级，不是复杂度等级），拆出第一个可收敛的 campaign/thread 作为当前执行，后续阶段持续推进

引导补充 > 自动缩窄（campaign）> 转为 Track。**没有"降级执行"**——不收敛就不执行，而是在正确的组织层级承接目标。

**Track 的推进方式：**
- 每个阶段完成后，系统带着阶段成果和下一步建议回到 Dialog
- **用户有选择权**：确认下一阶段的方向、调整计划、或决定暂停
- 系统不自主推进 Track 的下一阶段，每次都需要用户确认

复杂度（pulse/thread/campaign）描述单次执行的复杂程度。Track 是跨时间的目标管理。两者是不同维度，不是同一光谱。

**(b) 运行时不收敛的处理：** 与 Q3.2(d) 统一设计。不是"重试 N 次然后放弃"，而是"诊断 → 查 Playbook → 针对性重构"的智能闭环。如果重构后仍不收敛，带着诊断结果回到 Dialog，由用户决定如何调整（而非系统单方面终止）。详见 Q3.2(d) 结论。

**(c) campaign 的阶段数和步数上限可通过 Console 调整。** Console 的编辑能力定位于此类系统运行参数的调优，不做任务级操作。默认值在暖机时校准，Console 提供人工覆盖能力。

### Q3.5 Dialog 的定位与生命周期

当前 `DialogService` 通过 Router Agent 对话，被动提取 JSON plan。

**问题：**
(a) Dialog 在入口分野中属于哪个入口？是 Portal 的子功能（Portal 内嵌对话窗口），还是独立入口？
(b) 对话的终止条件是什么？Router 何时判断"信息够了"生成 plan？是否有轮次上限？
(c) 对话中途用户离开（session 超时），已收集的信息如何处理？丢弃还是保存为草稿？

**答：**
a 是Portal的子功能，你可以去看看现在的portal设计，我喜欢这种claude风格的界面
b 这里也一样，设置最多几次太笨了。不过这里用户怎么给信息，默认选项之类的问题，我们可以多讲一讲。
c 回来时，应该有一个是否继续上次的问题这种情况。只要系统不关闭，这是用户发起下一次任务前一定会发生的事。注意，这里我想到一个问题，就是用户语言和系统语言要严格分离，”任务”/task是用户用语，而系统里我们说run、track之类的，用户不应该也没有途径知道，且系统内的用语只有英文，任何情况都不应该被翻译，后面我们规范化系统用语的时候会精心设计。

**结论：**

**(a) Dialog 是 Portal 的子功能。** 即当前 Portal compose 界面中的对话式交互区域（Claude 风格的聊天 UI）。用户在此描述需求，系统通过 Router Agent 理解意图，产出 plan 后在 Portal 内展示供用户确认提交。Dialog 不是独立入口。

**(b) Dialog 对话的终止——双重确认，不设轮次上限。**

Dialog 完成的标志是**双重确认**：
1. **系统侧**：生成了一个通过收敛性验证的 plan
2. **用户侧**：用户看到 plan 后明确同意执行

两个都满足才结束。缺任何一个都继续对话。

Dialog 的完整流程：`自由对话 → 系统判断信息足够 → 生成 plan + 收敛性验证（用户等待）→ Portal 内展示 plan → 用户确认/修改 → 确认则提交，修改则回到对话`

**”信息足够”的判定**：RunSpec 的基础字段（objective、language、format、depth 等）要么被用户提供，要么有来自 Compass 的可靠默认值。

**核心设计原则——系统耐心，适应人类用户：**

Q3.4(a)（引导不可执行的需求）和 Q3.5(b)（收集足够信息）是同一个过程，都由 Dialog 完成。设计要点：

1. **系统是耐心的一方**：不急于”凑够信息就跑”。用户说什么都接受，包括反复、改主意、说无关的话
2. **适应意图漂移**：人类用户经常中途改变方向（”算了，我不想做这个了”）。系统不假设对话过程中目标始终不变，随时接受用户推翻前面的讨论
3. **不被用户的急躁带偏**：用户因为急可能做大幅度调整试图”跳过”对话过程。系统保持自己的节奏——只有 RunSpec 基本完整且 plan 通过验证时才展示 plan
4. **plan 展示要优雅**：Portal 内以图形化方式展示 plan（节点+连线的可视化 DAG），不是 markdown 文本箭头

用户给信息的方式：
1. **自由输入**：用户直接描述需求，Router 自主判断是否需要追问
2. **引导选项**：当 Router 需要用户做选择时（如”侧重深度还是广度？”），以选项形式呈现，用户点选或输入均可
3. **快速提交**：用户输入足够明确时（如”写一份关于 X 的研究报告”），Router 直接生成 plan，跳过多轮对话

**状态反馈原则：** 用户每次发送消息后，系统都必须有明确响应，不让用户猜”系统在等我还是在工作”：
- 信息足够 → 立即反馈”正在生成方案，请稍候”→ 进入 plan 生成
- 信息不够 → 明确指出缺什么（针对 RunSpec 中未填充且无默认值的字段提问）

**Router 语言风格：** Router agent 虽然使用 MiniMax M2.5 模型，但必须通过 system prompt 模拟 Claude 的对话风格：简洁、直接、不用 emoji、不啰嗦、该问就问、不过度解释、耐心但不废话。暖机时校准 prompt 直到风格一致。

**(c) 未完成的 Dialog session 保留为草稿。**

用户离开后再次打开 Portal compose 界面时，如果存在未完成的 session，显示”继续上次的对话？”提示。用户可以选择继续或重新开始。session 在系统运行期间始终保留（内存中），系统重启时清除（对话内容是临时的，不持久化）。

**全局约束——用户语言与系统语言严格分离：**
- **用户语言**：”任务”、”目标”、”结果” — 面向用户的所有界面（Portal、Telegram 通知）使用
- **系统语言**：run、track、lane、step、plan、dispatch — 仅在代码、日志、Console 中出现，**全部英文，任何情况不翻译**
- 用户不应该知道也没有途径接触系统内部用语
- 这是一条全局原则，适用于所有阶段，后续在术语规范化（话题 2）中精心设计完整词表

### Q3.6 Semantic 层重构方向

废弃 cluster 后，当前的 `SemanticSpec`（cluster_id 为核心字段）、`capability_catalog.json`、`mapping_rules.json` 都需要重新设计。

**问题：**
(a) `SemanticSpec` 替换为什么数据结构？需要保留哪些字段（objective、artifact_types、risk_level、language）？需要新增什么（complexity_level、step_budget）？
(b) `capability_catalog.json` 和 `mapping_rules.json` 是否完全废弃？还是改为 LLM plan 生成的参考资料？
(c) Semantic confidence 在新设计中还有意义吗？如果 LLM 自由分解，confidence 应该度量什么？

**答：**
a 这个我不知道，你讲讲吧
b 看他的复杂程度，反正暖机的步骤、用例、测试等等都是你来设计
c 这个我也不知道，就看这里的学习机制是怎样的了

**结论：**

**(a) SemanticSpec 和 IntentContract 统一重构为 RunSpec：**

废弃 `SemanticSpec`（cluster 分类的产物）和 `IntentContract`（泛化三字段无实际结构化价值）。两者合并为 **RunSpec** — 每个 run 都需要的、系统可直接使用的结构化基础字段。命名遵循系统语言原则（"task"是用户语言，系统内用"run"）。

```python
@dataclass
class RunSpec:
    objective: str              # 用户目标（原文）
    complexity: str             # pulse | thread | campaign
    step_budget: int            # 当前复杂度等级的步数上限
    language: str               # zh | en | bilingual
    format: str                 # 用户偏好提示（可空）；实际产出格式由 task type + compass + playbook 自适应决定（S6-D）
    depth: str                  # brief | standard | thorough
    references: list[str]       # 用户提供的参考资料（URL、文件路径）
    confidence: str             # high | medium | low（对复杂度判断的置信度）
```

每个字段都有明确的行为意义：`language=bilingual` → render 产出两份；`format` 作为用户偏好提示（实际产出格式由自适应决策决定，S6-D）；`depth=thorough` → 步骤更多、分析更深；`complexity` + `step_budget` → plan 生成的硬约束。

Dialog 阶段的"信息基本足够"判定标准之一：RunSpec 的基础字段要么被用户提供，要么有来自 Compass 的可靠默认值。

字段列表是初步的，暖机时验证完整性，可能增减。

**(b) capability_catalog.json 和 mapping_rules.json 的处置：**

不完全废弃，但角色转变：
- `capability_catalog.json` → 改为 `agent_capabilities.json`，描述每种 agent 的能力边界（LLM 生成 plan 时的输入之一）
- `mapping_rules.json` → 废弃。关键字匹配分类被 LLM 直接判断取代

暖机阶段会验证 `agent_capabilities.json` 的描述是否足够让 LLM 正确组合 agent。

**(c) confidence 在新设计中的含义：**

不再度量"分类是否正确"（无分类了），而是度量**"复杂度判断的置信度"**。来源：
- Playbook 中有大量相似任务历史 → confidence=high（学习机制有经验）
- Playbook 中有少量类似历史 → confidence=medium
- 全新类型的任务，无历史参考 → confidence=low

confidence=low 时的处理：不拒绝（Q3.4 原则），但保守地选择较高复杂度等级（宁可多给步数预算，不要低估导致运行时不收敛）。这比"计数重试"更高效——一开始就给更宽松的预算。

### Q3.7 openclaw 收敛机制的配置策略

openclaw 的 Tool-Loop Detection 默认关闭，阈值可按 agent 配置。

**问题：**
(a) 是否所有 agent 类型都开启 loop detection？还是只对特定 agent（如 build、collect）开启？
(b) 默认阈值（warning=10, critical=20, breaker=30）是否合理？不同 agent 类型是否需要不同阈值？（build agent 用 opencode 可能合理地调用更多次工具）
(c) daemon 如何接收 openclaw 的 loop detection 事件？通过轮询 session 状态，还是通过 webhook/hook 回调？

**答：**
这三个问题是一个解决方案：去看openclaw的机制讲解，和大家的实际使用经验，需要你去广泛搜索了解。

**结论：**

经查阅 openclaw 官方文档，结论如下：

**(a) 所有 agent 类型都开启 loop detection。**

没有理由让任何 agent 无限循环。但不同 agent 的正常工具调用频率不同，需要差异化配置。

**(b) 阈值按 agent 类型差异化：**

| agent | warning | critical | breaker | 理由 |
|-------|---------|----------|---------|------|
| collect | 10 | 20 | 30 | 采集类工具调用多，但默认值已足够 |
| analyze | 8 | 16 | 24 | 分析以推理为主，工具调用较少 |
| build | 15 | 30 | 45 | 通过 opencode PTY 执行，合理的工具调用次数更多 |
| review | 8 | 16 | 24 | 同 analyze |
| render | 8 | 16 | 24 | 渲染步骤工具调用较少 |
| apply | 10 | 20 | 30 | 交付可能涉及多步操作 |

这些是初始值，暖机时根据实际行为校准，Playbook 记录各 agent 的正常工具调用分布。

**(c) daemon 通过轮询 session 状态获取 loop detection 结果。**

查阅发现：openclaw 的 internal hooks 没有 loop detection 专用事件，webhook 也不支持内部事件外推。因此 daemon 无法被动接收 loop detection 事件。

实现方式：daemon 在 Temporal activity 执行 agent 调用后，通过 `sessions_list` 检查 `abortedLastRun` 字段。如果为 true，再用 `sessions_history` 拉取最近消息判断终止原因（是 loop detection 还是其他原因）。这与 Q3.2(d) 的"诊断"步骤衔接：拉取 history → 分析失败原因 → 决定重构策略。

### Q3.8 IntentContract 与 Fabric 的关系

`IntentContract` 目前只有 objective/constraints/acceptance 三字段，Semantic 层不读取 Fabric。

**问题：**
(a) 在新的"复杂度驱动"模型下，IntentContract 还需要吗？还是被 LLM 的 plan 生成直接取代？
(b) Fabric 记忆（用户偏好、历史任务上下文）在意图理解阶段注入，还是在 Dispatch 的 enrich 阶段注入？
(c) 用户说"继续上次的"这类依赖上下文的指令，应该在哪一层解析？

**答：**
这三个问题我需要你仔细讲解才能明白，哪些内容是需要我决定的。我现在不理解你具体在问什么。

**结论：**

先用白话解释这三个问题的本质：

**(a) IntentContract 废弃，由 RunSpec 替代。**

IntentContract 的三个泛化字段（objective/constraints/acceptance）缺乏结构化价值，是 cluster 分类架构的产物。经后续讨论确认：每个任务都有一些系统可以直接使用的基础属性（语言、格式、深度等），这些才是真正需要的结构化信息。

IntentContract + SemanticSpec 统一重构为 **RunSpec**（详见 Q3.6(a)）。RunSpec 的每个字段都有明确的行为意义，不再是万能口袋。

**(b) Fabric 在哪个阶段注入？**

系统有两个阶段可以利用用户历史：
1. 意图理解阶段（Dialog/plan 生成）—— 帮助理解用户想要什么
2. Dispatch enrich 阶段 —— 帮助决定怎么执行（模型选择、质量参数、超时等）

**结论：分两层注入。**
- **意图理解阶段**：只注入轻量信息 — Playbook 的历史 plan 示例（Q3.3(a) 已确定），用于帮助 LLM 更准确地生成 plan。不注入完整 Memory。
- **Dispatch enrich 阶段**：注入 Compass 偏好（质量要求、模型选择、预算）和 Memory 相关记忆（用户偏好）。这些影响"怎么做"，不影响"做什么"。

这样 plan 生成保持简洁（只关心"做什么"），enrich 阶段补充执行细节（"怎么做"）。

**(c) "继续上次的"在哪一层解析？**

用户说"继续"时，系统需要知道"继续什么"。这需要最近任务的上下文。

**结论：在 Dialog 层解析。** 因为"继续"是意图层面的模糊表达，需要 Router Agent 结合当前 session 上下文（如果有）和最近任务列表来判断用户指的是什么。具体实现：
- Dialog session 内有历史消息 → Router 从对话上下文推断
- 新 session 且有未完成的草稿 → Q3.5(c) 的"继续上次对话？"提示
- 新 session 且无草稿 → Router 调 daemon API 获取最近任务列表，问用户"你想继续哪一个？"

## 阶段 4：决策（Dispatch → Playbook → Model → Budget）

### 前置：阶段 3 确立的设计基础

阶段 3 确立了四条理念和一系列具体结论，直接决定了 Dispatch 层的设计空间：

- **理念 B**：废弃 cluster 分类，改为复杂度驱动步数约束。RunSpec 替代 SemanticSpec + IntentContract
- **理念 D**：学习机制基于 embedding 相似性，不基于分类。Playbook、Compass 等所有需要"经验"的环节统一通过 embedding 检索
- **Plan 已前移**：Dialog 阶段由 LLM 生成 plan，用户双重确认后 submit。Dispatch 不再生成 plan，只补充执行参数
- **策略/模型/质量/预算**中所有依赖 cluster_id 的索引逻辑全部失效，需要重建

以下问题不再问"用什么替代 cluster"（答案统一是 embedding），而是聚焦每个决策环节在新架构下的**具体工作方式**。

---

### Q4.1 Dispatch 的新职责边界

Plan 前移到 Dialog 后，Dispatch 不再"理解意图 + 生成计划"，只做"补充执行参数后提交"。

当前 `enrich()` 的流程是：normalize → semantic derivation → playbook consult → quality profile → strategy → model routing → complexity probe → budget preflight → gate。其中 semantic derivation（产出 cluster_id）和 complexity probe（判断 work_scale）已由 Dialog 阶段的 RunSpec 完成。

**问题：**
(a) enrich 剩下的核心工作是什么？请逐一判断每个环节的去留：normalize / playbook consult / quality profile / strategy / model routing / budget preflight / gate。
(b) enrich 变简单后，当前 `dispatch.py` 中 400+ 行的 enrich 逻辑大部分要删掉。是简化为一个轻量函数，还是保持独立模块但内容精简？
(c) 有没有新增的职责？比如：RunSpec 完整性校验、plan DAG 验证（Q3.3(b) 的 5 条规则）是否应该在 Dispatch 做？还是在 Dialog 阶段已经做完了？

**答：**
a 这种技术细节一向由你决定
b 两种方案的优劣？比如文件结构是模块都是独立的？那是不是也重新设计模块的组织方式？
c 这部分我想听听你的意见

**结论：**

**(a) enrich 各环节去留判定：**

查看当前 `dispatch.py` enrich 流程（L140-182），逐一判断：

| 环节 | 去留 | 理由 |
|------|------|------|
| normalize | **保留，精简** | 字段规范化仍需要，但不再填充 cluster_id/run_type，改为校验 RunSpec 完整性 |
| semantic derivation | **废弃** | 已由 Dialog 阶段产出 RunSpec 替代 |
| playbook consult | **废弃（在 enrich 中）** | 执行参数由 complexity 默认值表决定（暖机阶段校准），不需要 embedding 检索。Playbook 检索只在 Dialog 阶段使用（plan 结构参考） |
| quality profile | **保留，重构** | 不再按 run_type 索引，改为 Compass 偏好 + RunSpec.depth 推断（详见 Q4.5） |
| strategy apply | **废弃** | 策略概念废弃（详见 Q4.3），执行参数由 complexity 默认值表提供 |
| model routing | **保留，精简** | agent_model_map 为主维度，去掉 by_semantic_cluster（详见 Q4.4） |
| complexity probe | **废弃** | RunSpec.complexity 已在 Dialog 阶段确定 |
| budget preflight | **保留** | 逻辑不变，估算基础从 work_scale 改为 RunSpec.complexity + step_budget |
| gate check | **保留** | 逻辑不变 |

新的 enrich 流程：`normalize(RunSpec 校验) → complexity defaults(填充执行参数) → quality profile → model routing → budget preflight → gate`

**(b) 模块组织方式：**

两种方案比较：

| 方案 | 优点 | 缺点 |
|------|------|------|
| 精简为一个轻量函数（全部回到 dispatch.py） | 逻辑集中，好理解 | dispatch.py 已有 700+ 行，加回来更臃肿 |
| 保持独立模块但内容精简 | 职责清晰，测试独立 | 文件数多，跳转多 |

**选择方案 2（保持独立模块），但重组文件结构：**

当前 `services/` 下 dispatch 相关文件：`dispatch.py`(700+行)、`dispatch_semantic.py`、`dispatch_steps.py`、`dispatch_model.py`。新设计中：

- `dispatch.py` — Dispatch 主类，enrich + submit 主流程（精简后约 200 行）
- `dispatch_enrich.py` — normalize + RunSpec 校验 + playbook 参数提取 + quality profile 注入（合并原 semantic/steps 的保留部分）
- `dispatch_model.py` — 模型路由（精简，去掉 cluster 维度）
- `dispatch_semantic.py` — **删除**（RunSpec 由 Dialog 产出，不再需要 Dispatch 侧的 semantic 解析）
- `dispatch_steps.py` — **删除**（complexity_probe 废弃，preflight_budget 移入 dispatch_enrich.py）

从 4 个文件减为 3 个文件，每个文件职责更清晰。

**(c) 新增职责：**

- **RunSpec 完整性校验**：在 Dispatch 的 normalize 阶段做。虽然 Dialog 阶段也做了（Q3.5(b) 双重确认），但 Dispatch 作为执行入口需要二次校验——防御性编程，且直接 API 调用（如果保留）不经过 Dialog。校验内容：RunSpec 所有必填字段非空、complexity 合法、step_budget 在范围内。
- **Plan DAG 验证**：Q3.3(b) 的 5 条规则（无环、agent 合法、depends_on 合法、步数 ≤ 上限、有 terminal 步骤）在 Dialog 阶段已验证。Dispatch 不重复验证 DAG 结构，只校验 RunSpec。原因：DAG 一旦生成并通过验证，用户确认后不应再被 Dispatch 拒绝，否则用户体验割裂。

### Q4.2 Playbook 的 embedding 检索机制

理念 D 确定了 Playbook 不再按 cluster 分组策略，而是通过 embedding 相似度匹配历史经验。

当前 `playbook.consult()` 按 cluster_id 查找 champion strategy，返回 DAG 模板。新设计中，consult 的输入是 RunSpec（含 objective 文本 + complexity），输出应该是什么？

**问题：**
(a) Playbook 存储的"历史经验"具体包含哪些字段？至少需要：任务的 embedding、plan 结构、执行结果、用户反馈。还有什么？
(b) 检索时，embedding 相似度是唯一的排序依据吗？还是需要叠加其他信号（如 complexity 必须匹配、recency 加权、用户反馈加权）？
(c) 检索结果如何使用？是作为"参考"注入 LLM prompt（Dialog 阶段已用），还是在 enrich 阶段提取具体参数（超时、并发度等执行参数）？两者都需要吗？
(d) 冷启动时 Playbook 为空，embedding 检索无结果。这时 enrich 的执行参数从哪来？硬编码默认值？RunSpec 的 complexity 字段推断？

**答：**
a 这个可以讨论一下
b 肯定要叠加，也要讨论
c 也要讨论，不同的参数，似乎权重也有区别？
d 这部分要设计好暖机的机制

**结论：**

经过讨论，Playbook embedding 检索的定位发生了重要简化：**检索只服务于 Dialog 阶段（plan 结构参考），不服务于 Dispatch enrich（执行参数）。**

核心发现：执行参数（concurrency、timeout、rework_limit、model_map）主要由 complexity 等级决定，与"任务是关于什么的"关系不大。同 complexity 的不同任务用几乎相同的执行参数，跨 complexity 的执行参数更不可借鉴。因此 Dispatch enrich 不需要 Playbook embedding 检索，直接用 complexity 默认值表即可。

**(a) 历史经验的存储字段：**

每条 Playbook 经验记录（一个完成的 run）包含：

| 字段 | 类型 | 用途 |
|------|------|------|
| `run_id` | str | 唯一标识 |
| `objective_embedding` | vector | 用于 Dialog 阶段 plan 参考检索 |
| `objective_text` | str | 原始用户目标文本（embedding 来源） |
| `complexity` | str | pulse/thread/campaign |
| `step_count` | int | 实际执行步数 |
| `plan_structure` | json | DAG 结构（步骤列表 + 依赖关系）— Dialog 阶段的核心参考 |
| `outcome_quality` | json | review agent 的质量评分 + 用户反馈选择（如有） |
| `token_consumption` | json | 各 provider 实际消耗 {provider: tokens} — 用于预算估算校准 |
| `success` | bool | 是否成功完成 |
| `duration_s` | float | 总执行时间 |
| `created_utc` | str | 时间戳 |
| `user_feedback` | json/null | 用户反馈选择题结果（选项式，非打分；可空） |
| `rework_history` | json/null | 如发生复杂度修正，记录修正路径 |

embedding 的生成：对 `objective_text` 做 embedding。不对 plan 结构做 embedding——plan 结构是产出不是输入特征，检索时应基于"用户想做什么"而非"系统做了什么"。

不再存储 `execution_params` 字段（concurrency/timeout/model_map），因为这些由 complexity 默认值表决定，不随任务内容变化。

**(b) 检索排序——仅用于 Dialog 阶段：**

检索目的变为单一的：为 Dialog 阶段的 plan 生成提供相似任务的 DAG 结构作为 LLM 参考。

排序公式简化为：

```
score = sim(embedding) × 0.6 + recency_decay × 0.2 + quality_bonus × 0.2
```

- `sim(embedding)`：cosine similarity，主信号
- `recency_decay`：`exp(-days_ago / 90)`，90 天半衰期
- `quality_bonus`：用户反馈选择正面选项加分，负面选项减分，无反馈=中性

**complexity 硬过滤**：只检索同 complexity 的历史经验。原因：plan 结构与复杂度强相关（pulse 的 1 步 plan 对 campaign 的多阶段 plan 没有参考意义），且跨级经验的执行参数也不可借鉴（已讨论确认）。

返回 top-3，作为 LLM 生成 plan 时的参考示例（Q3.3(a) 已确定）。

**(c) Dispatch enrich 不使用 Playbook 检索。**

执行参数直接由 complexity 默认值表提供：

| 参数 | pulse | thread | campaign |
|------|-------|--------|----------|
| concurrency | 1 | 2 | 4 |
| timeout_per_step_s | 120 | 300 | 600 |
| rework_limit | 0 | 1 | 2 |

这些值在暖机阶段通过真实任务执行校准。暖机前是代码中的初始猜测，暖机后更新为实测合理值，此后不再变动（除非 Console 手动调整）。

Dispatch enrich 的工作变为：读取 RunSpec.complexity → 查表填充执行参数 → 继续后续环节（quality profile / model routing / budget / gate）。极其简单。

**(d) 暖机的两个目标：**

1. **校准 complexity 默认值表**：暖机任务覆盖 pulse/thread/campaign，记录实际的 concurrency 效果、timeout 合理值、rework 频率，据此更新默认值表
2. **填充 Playbook 初始经验库**：暖机任务完成后写入 Playbook，为 Dialog 阶段的 plan 结构参考提供初始数据

暖机任务的设计原则：
- 覆盖 pulse/thread/campaign 三个复杂度等级
- 覆盖所有 agent 类型（collect/analyze/build/review/render/apply）
- 包含边界情况（如需要 rework 的任务、接近步数上限的任务）
- 暖机任务是阶段 5（执行）之后的专门环节，此处只确定数据结构准备

### Q4.3 策略（Strategy）在新架构中的角色

当前策略体系：strategy_candidates / strategy_experiments / strategy_promotions，每个策略绑定一个 cluster，有 champion/challenger 生命周期。

理念 D 后，"策略"这个概念是否还独立存在？还是被 Playbook 的 embedding 经验检索自然吸收了？

**问题：**
(a) 策略的本质是什么？当前策略的 spec 包含：concurrency、timeout_hints、rework_limit、model_overrides。这些是"策略"还是"执行参数"？如果只是执行参数，是否需要单独的策略概念，还是直接作为 Playbook 历史经验的一部分？
(b) A/B 测试（champion vs challenger）在 embedding 世界中如何工作？传统 A/B 需要固定分组，embedding 世界中"组"是动态的（相似任务的邻域）。这还能做 A/B 吗？如果不能，用什么替代？
(c) 策略生命周期（candidate → shadow → challenger → champion → retired）是否过重？如果策略被 Playbook 经验吸收，生命周期是否简化为"记录 → 衰减 → 淘汰"？

**答：**
a 需要讨论一下
b 我相信这个机制一定有成熟的方案。毕竟分组机制是过时的技术，但是选拔机制肯定没被淘汰。
c 可以简化，只要保证质量就行，你可以评估一下可行性。

**结论：**

**(a) "策略"不再作为独立概念存在，被 Playbook 经验吸收。**

当前策略的 spec 内容（查看 `playbook.py` L157-226）：
- `concurrency`：`{"max_parallel_steps": 4}` — 这是执行参数
- `rework_budget`：`2` — 这是执行参数
- `rework_strategy`：`"error_code_based"` — 这是执行参数
- `steps_template`：固定 DAG 模板 — 已由 Dialog 阶段 LLM 生成替代

结论：当前"策略"实质上就是执行参数 + DAG 模板。DAG 模板已前移到 Dialog，执行参数已被 Q4.2 的 Playbook 经验记录覆盖（`execution_params` 字段）。不需要一个独立的 strategy 概念把它们再打包一次。

废弃 `strategy_candidates`、`strategy_experiments`、`strategy_promotions` 三张表。执行参数的"好坏"通过 Playbook 经验的 `outcome_quality` 和 `user_feedback` 自然体现。

**(b) 不需要选拔机制。**

原来的 champion/challenger A/B 测试依赖 cluster 分组——同一 cluster 内的任务被视为"可比的"，两个策略在同组任务上竞争。cluster 废弃后，固定分组不存在了，传统 A/B 失去基础。

曾考虑用 Contextual Bandits（上下文赌博机）替代，但经讨论确认**这个场景根本不需要选拔机制**：

1. **任务不重复**：daemon 每天处理的任务类型高度多样（报告、代码、计划……），很少面对"同一个决策该选 A 还是 B"的问题。选拔的前提是同类问题反复出现，daemon 不满足这个前提
2. **参数空间小**：执行参数只有 concurrency（2/4）、timeout（几档）、model（几个选项），不需要复杂算法来寻找最优组合
3. **探索自然发生**：用户的需求多样性本身就是探索——每个新类型任务天然使用默认参数，效果被记录，就是一次"探索"。不需要人为注入随机性
4. **试错代价高**：每次"探索"消耗真实 token 和用户等待时间，不像广告推荐那样几乎零成本

**实际的参数优化路径**：Playbook 最近邻检索（Q4.2）已经足够。相似任务用历史最优参数，全新任务用默认值。随着数据积累，witness routine 可以发现全局层面的参数偏好趋势（如"concurrency=4 普遍比 2 效果好"），更新默认值即可。

**(c) 策略生命周期完全废弃。**

废弃 `candidate → shadow → challenger → champion → retired` 五阶段。不需要替代的生命周期。

Playbook 经验记录的自然过程已经覆盖了"好参数浮现、差参数沉底"的需求：

1. **记录**：每个 run 完成后，经验自动写入 Playbook（含执行参数和效果）
2. **浮现**：Q4.2(b) 的 quality_bonus 加权让高质量经验在检索时排名更高 → 好参数被更多复用
3. **衰减**：recency_decay（90 天半衰期）让过时经验自然失去影响力
4. **淘汰**：Playbook 容量上限时，淘汰综合分最低的记录（与 Q1.1 Memory 淘汰策略一致）

不需要显式的选拔、提拔、退役。参数的优劣通过 Playbook 经验的自然积累和检索排序体现。

### Q4.4 模型路由

当前模型路由四维度：`by_semantic_cluster`（废弃）、`by_risk_level`、`agent_model_map`、strategy spec。

**问题：**
(a) `agent_model_map`（agent 类型 → 模型）是模型路由的主维度。这是否足够？每种 agent 固定一个模型，还是同一 agent 在不同场景下可以用不同模型？
(b) 如果同一 agent 需要场景化模型选择（比如 analyze agent 处理简单 pulse 用轻量模型，处理 campaign 用重量模型），选择依据是什么？RunSpec.complexity？RunSpec.depth？Playbook 历史经验？
(c) `by_risk_level` 维度：RunSpec 当前没有 risk_level 字段。风险等级是否还需要？如果需要，谁来判定——LLM 在 Dialog 阶段判定，还是 Dispatch 根据 plan 内容推断？
(d) 模型选择的学习：某次 run 用模型 A 效果差，换模型 B 效果好。这个经验如何记录和复用？是 Playbook 经验的一部分（通过 embedding 检索），还是需要专门的模型偏好机制？

**答：**
a 这会增加复杂度吗？
b 和a一起讨论吧
c 风险等级是做什么的？
d 也讨论一下吧。我记得有个记录token的。在什么地方？

**结论：**

**(a+b) agent_model_map 为主，Playbook 经验为辅，不增加额外复杂度。**

当前 `agent_model_map`（`config/model_policy.json`）为每种 agent 指定一个默认模型：
- collect → MiniMax M2.5
- analyze → DeepSeek R1
- build → MiniMax M2.5（编排者）
- review → Qwen Max
- render → GLM Z1 Flash
- apply → MiniMax M2.5

**是否需要场景化模型选择？** 不主动增加这个维度。原因：

1. **增加复杂度有限收益**：场景化选择意味着需要维护"complexity × agent × depth"的组合矩阵，维护成本高但改善不明确
2. **Playbook 经验自然覆盖**：Q4.2 已经设计了 Playbook 检索时可提取 `model_map`。如果某次 run 中 analyze agent 用了 Qwen Max（替代默认的 DeepSeek R1）效果更好，这个经验会被记录。下次相似任务检索到这条经验时，自然会采用 Qwen Max → 场景化模型选择通过**学习**实现，不通过**规则**实现
3. **任务多样性自然覆盖**：用户的需求多样性意味着不同类型任务天然会使用不同的默认模型配置，效果被记录后，Playbook 自然积累了不同场景下的模型使用经验

所以模型路由保持简单：`agent_model_map`（默认值）→ Playbook 经验覆盖（如果有高 quality 的非默认选择）。不增加代码复杂度。

**(c) risk_level 废弃。**

risk_level 在当前设计中的作用：`model_policy.json` 的 `by_risk_level` 维度，当 `risk_level=medium/high` 时选择"更保守/更强"的模型。它来源于 `capability_catalog.json` 中每个 cluster 的 `risk_level` 字段（如 dev_project=medium）。

废弃原因：
1. cluster 已废弃，risk_level 没有来源
2. risk_level 的实际作用是"更重要的任务用更强的模型"——这与 RunSpec.depth（`brief/standard/thorough`）高度重叠
3. Playbook 经验学习已经覆盖了"什么场景该用什么模型"的问题

不在 RunSpec 中新增 risk_level 字段。如果需要区分"重要性"，RunSpec.depth 已足够。

**(d) 模型选择的学习——通过 Playbook 经验自然实现，不需要专门机制。**

用户提到的 token 记录机制在 `runtime/cortex.py` L435-464：每次 LLM 调用后，Cortex 将 `{provider, model, in_tokens, out_tokens, elapsed_s, success}` 写入 `state/cortex_usage.jsonl`。同时 `compass.consume_budget()` 扣减 provider 日预算。

模型选择学习的完整链路：
1. **记录**：cortex_usage.jsonl 已记录每次调用的 provider/model/tokens/success
2. **汇总**：run 完成时，Playbook 经验记录中的 `token_consumption` 和 `execution_params.model_map` 字段聚合该 run 的模型使用情况
3. **检索复用**：下次相似任务，Playbook 检索返回 top-K 经验中 quality 最高者的 model_map
不需要单独的"模型偏好表"，也不需要人为的探索机制。模型偏好是 Playbook 经验的一个字段，和 concurrency、timeout 一起，统一通过 embedding 检索获取。任务多样性本身提供了自然的模型尝试覆盖。

### Q4.5 质量要求的来源与传递

当前质量配置按 run_type 硬编码（min_sections=3, min_word_count=800 等）。cluster/run_type 废弃后，质量要求从哪来？

**问题：**
(a) 质量要求的来源有三个：用户在 Dialog 中显式说明（"至少 3000 字"）、Compass 中积累的用户偏好、系统默认值。优先级顺序是什么？
(b) 用户显式的质量要求写入 RunSpec（如新增 quality_hints 字段），还是作为 plan 的 metadata 传递？
(c) Compass 的质量偏好当前按 run_type 索引。废弃 run_type 后，Compass 如何积累和检索质量偏好？也走 embedding 相似度吗？
(d) 质量规则（如 min_word_count）是硬编码的"底线"，还是完全由学习机制动态调整？有没有不可协商的质量底线？

**答：**
a 显示说明 用户偏好 系统默认值 如果非要排，就这么排，但是只有这些吗？
b 两种方案的优劣？
c embedding可以解决这个问题吗？
d 质量底线应该有可以调整的部分，也有不可调整的部分。试想一个例子：学术文章的格式是不是有一个全世界统一的规则？（中文、英文都是有的）

**结论：**

**(a) 质量要求的来源——四层，不是三层：**

用户说得对，不只三个来源。完整优先级：

1. **用户显式说明**（最高）— Dialog 中用户直接说的质量要求（"至少 3000 字"、"要有参考文献"）
2. **Playbook 历史经验** — embedding 检索到的相似任务中，review agent 给出的质量评分 + 用户反馈选择形成的质量基线（Q4.2 已设计）。这是第四个来源，介于用户偏好和系统默认之间
3. **Compass 用户偏好** — 长期积累的个人偏好（如"我总是要求双语输出"、"我偏好深度分析"）
4. **系统默认值**（最低）— 格式规范硬底线（见 (d)）

优先级规则：高层覆盖低层的同名规则。不同名的规则叠加。

**(b) 用户显式质量要求写入 RunSpec。**

两种方案比较：

| 方案 | 优点 | 缺点 |
|------|------|------|
| 写入 RunSpec（如 `quality_hints: list[str]`） | 随 RunSpec 全生命周期可见，Dispatch/执行/review 都能读到 | RunSpec 字段会增长 |
| 作为 plan metadata 传递 | RunSpec 保持精简 | metadata 是非结构化的，下游可能忽略 |

**选择写入 RunSpec**，新增字段 `quality_hints: list[str]`。原因：
- 质量要求是 run 的核心属性，不是附属信息
- review agent 需要读到这些要求来评判产出质量
- RunSpec 字段增长可控（就一个 list 字段）

示例：用户说"至少 3000 字，要有参考文献" → `quality_hints: ["min_word_count:3000", "require_references:true"]`

**(c) Compass 质量偏好走 embedding 相似度。**

可以。Compass 当前按 run_type 索引质量规则（`compass.py` L84-114 的 `BOOTSTRAP_QUALITY_PROFILES`），这些 run_type（research_report / daily_brief / default）将被废弃。

新设计：Compass 不再维护静态的 quality_profiles 表。质量偏好通过两条路径获取：

1. **Playbook 经验中的 outcome_quality**：embedding 检索相似历史任务，提取其中 review agent 的质量评分和用户反馈。如果用户对类似任务一贯要求高字数，这个偏好自然浮现在 Playbook 经验中
2. **Compass 全局偏好**：与具体任务无关的全局偏好（如 `require_bilingual=true`）保留在 Compass 中，作为 key-value 存储，不按 run_type 索引

实现上：废弃 `quality_profiles` 表，保留 `preferences` 表（已有的 key-value 存储）。全局质量偏好作为 preference 存储。

**(d) 质量底线——不可协商的格式规范 + 可调整的内容规范。**

用户的例子很好。学术论文有全世界统一的格式规范（如 APA/MLA 引用格式、中文 GB/T 7714 引用格式），这是不可协商的。但"至少多少字"、"至少几个章节"是可调整的。

分两层：

**不可协商的格式底线（hardcoded，不随学习调整）：**
- `forbidden_markers`: 产出中不得包含系统内部标记（`<system>`, `[INTERNAL]`, `DRAFT` 等）
- `language_consistency`: 产出语言必须与 RunSpec.language 一致（bilingual 则两份各自语言纯粹）
- `format_compliance`: PDF 必须可渲染、code 必须语法正确、markdown 必须结构完整
- `academic_format`: 当 RunSpec.format 或 quality_hints 指明学术/正式文体时，强制执行对应的引用和格式规范（中文 GB/T 7714、英文 APA/Chicago）

**可调整的内容规范（学习机制动态调整）：**
- `min_word_count`: 初始默认按 depth（brief=200, standard=800, thorough=2000），随 Playbook 经验修正
- `min_sections`: 初始默认按 depth（brief=1, standard=3, thorough=5），随经验修正
- `min_domain_coverage`: 信息源覆盖度，随经验修正
- `require_references`: 默认 false，用户 quality_hints 或 Compass 偏好可覆盖

不可协商的底线在代码中硬编码为常量。可调整的规范从 Playbook 经验 + Compass 偏好 + 系统默认值三层获取（按 (a) 的优先级）。

### Q4.6 预算估算与管控

当前 `preflight_provider_budget` 按 work_scale 粗估 token（pulse=20k, thread=80k, campaign=160k）。

**问题：**
(a) RunSpec 的 complexity + step_budget 能提供更精确的估算基础（步数 × 每步均值）。Playbook 历史中相似任务的实际消耗能否进一步修正估算？
(b) 预算不足时的行为：当前是排队等待（daily budget reset）。但如果用户提交了一个 campaign 级任务而今日预算只够 thread，系统应该怎么做？排队等明天？告知用户？缩减 plan？
(c) 预算管控的粒度：当前按 provider 每日限额。是否需要按 run 限额（单个 run 最多消耗多少 token）？防止一个 campaign 吃掉全天预算。

**答：**
a 可以
b 其他模型的token用量放在portal显示，而minimax的计算方式好像不太一样。因为minimax好像是5h重置一次次数，所以应该有一些方法知道多长时间后可以重置？也显示在portal上。任何任务触发了用量超，直接排队等待有用量，并通知用户。至于这个时候能不能向系统提交任务，以及Track中的定时任务改怎么办，我还没想好。
c 有这个必要。超了预算也要停，等第二天用量。不过每日和每个run限额，你可以在暖机阶段测试得到结果。

**结论：**

**(a) 预算估算——区分两种计费模型。**

经检索确认，daemon 使用的 provider 有两种完全不同的计费模型：

**MiniMax Coding Plan（Plus 套餐）—— prompt 次数制：**
- 计费单位：prompt 次数（不是 token）
- 额度：**100 prompts / 5 小时滚动窗口**
- 滚动窗口：不是固定时段重置，而是 5 小时前的用量自动释放
- 1 prompt ≈ 15 次后台模型调用（MiniMax 内部打包逻辑，外部无法精确对应）
- 月费 49 元
- **官方额度查询接口**：`GET https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains`（Header: `Authorization: Bearer <API Key>`）

**其他 provider（DeepSeek/Qwen/Zhipu）—— token 制：**
- 计费单位：token 数量
- 按量付费（按百万 token 计价）
- 无固定窗口，但 daemon 自设每日 token 限额防止意外超支

这意味着预算估算需要两套逻辑：

- **MiniMax**：不自己计数，直接调用 `/coding_plan/remains` 接口查询实时剩余额度。原因：MiniMax 的 prompt 打包逻辑是内部的（1 prompt ≈ 15 次模型调用，但具体比例不固定），daemon 本地计数无法精确对应，实测也确认本地估算不准
- **其他 provider**：估算 token = `step_budget × per_step_avg_tokens`（按 agent 类型区分，暖机校准）

当前代码中 `compass.py` 把 MiniMax 当 token 日限额管理（`minimax_tokens: 20_000_000`）是错的。需要改为调用官方 remains 接口查询实时额度。

**(b) 预算不足时的行为：**

**MiniMax prompt 额度用尽时：**
- daemon 在 preflight 和执行间隙调用 `/coding_plan/remains` 查询实时剩余额度
- 不依赖本地计数（MiniMax 内部打包逻辑不透明，本地估算不准）
- 额度不足 → remains 接口返回剩余数和窗口信息 → 排队等待额度释放
- Portal 显示 remains 接口返回的实时数据（剩余次数 / 总额度 / 预计释放时间）
- pulse routine 每 10 分钟轮询一次 remains 接口，更新 Portal 显示和排队 run 的释放判断

**其他 provider token 额度用尽时：**
- 当日自设限额用完 → run 排队等待次日
- Portal 显示各 provider 的 `已用 / 日限额`
- 通知用户预计恢复时间

**统一行为：**
- **可以提交**新任务，但进入排队状态。提交不阻塞——用户可以继续用 Dialog 准备下一个任务
- 用户不会感到"系统拒绝工作"

**Track 中的定时任务预算不足时：**
- 定时任务到期但预算不足 → 排队，不跳过
- 不累积同一 chain 的多个待执行实例——上一个还在排队，下一个到期则跳过并记录 `skipped_reason: budget_queued`
- 通知用户

**(c) 单 run 预算上限。**

有必要。防止一个 campaign 级 run 吃掉所有配额。

- **MiniMax**：单 run prompt 上限 = 窗口限额 × 比例（默认 50%，即 50 prompts）
- **其他 provider**：单 run token 上限 = 日限额 × 比例（默认 50%）
- campaign 的每个 phase 间有检查点，检查剩余配额
- 触发单 run 上限 → 暂停该 run，通知用户。用户可选择"继续"或"等配额恢复后继续"
- 具体比例值在暖机阶段通过实际任务消耗测定

### Q4.7 Gate 与并发控制

当前 gate 三状态（GREEN/YELLOW/RED），pulse routine 设置。

**问题：**
(a) gate 状态的判断标准是什么？当前代码中 pulse 如何决定状态切换？是基于系统负载、运行中 run 数量、还是 provider 配额？
(b) 这个机制的目的是什么？防过载？限并发？省预算？明确目的后，当前设计是否匹配目的？
(c) 当前所有 run 共享一个 gate。是否需要按 complexity 区分——pulse 级别的快速任务不应该被 campaign 导致的 YELLOW gate 阻塞？

**答：**
a 这个我不知道机制，你给讲讲吧
b 好问题，我也不知道
c 其实我都不知道这个gate是干什么的

**结论：**

**先解释 gate 是什么以及当前实现：**

Gate 是 daemon 的**系统级熔断开关**，用来在基础设施不健康时阻止新 run 进入执行。查看 `spine/routines.py` L80-134 的 pulse routine：

```
pulse 每 10 分钟运行一次：
1. 探测 OpenClaw Gateway 是否可用（能否连接、能否创建 session）
2. 探测 Temporal 是否可用（能否连接 server）
3. 探测 LLM provider 是否可用（Cortex 是否有配置）
4. 根据探测结果设定 gate 状态：
   - GREEN：全部健康 → 所有 run 正常执行
   - YELLOW：LLM 不可用，或 gateway/temporal 之一不可用 → 低优先级 run 排队
   - RED：gateway 和 temporal 同时不可用 → 所有 run 排队
5. 写入 state/gate.json
```

Dispatch 在 enrich 的最后一步读取 gate.json，决定 run 是否排队（`dispatch.py` L171-180）。

**这个机制的目的：防止在基础设施故障时向不可用的服务提交任务。**

它不是"限并发"或"省预算"——限并发由 Temporal 的 worker 并发数控制，预算由 preflight_budget 控制。Gate 只关心"基础设施是否能正常工作"。

**(a) gate 状态判断标准（已如上所述）：**

| 条件 | gate | 效果 |
|------|------|------|
| 全部健康 | GREEN | 所有 run 正常 |
| LLM 不可用 | YELLOW | priority > 5 的 run 排队 |
| gateway 或 temporal 之一不可用 | YELLOW | 同上 |
| gateway 和 temporal 都不可用 | RED | 所有 run 排队 |

**(b) 这个机制在新设计中足够，但需要增加一个维度。**

当前 gate 只检查基础设施健康，这是对的。但新设计引入了预算管控（Q4.6），产生了两种不同性质的"排队"：
- **基础设施故障排队**（gate RED/YELLOW）— 恢复不可预期，需要等 pulse 检测恢复
- **预算排队**（provider 配额用尽）— 恢复时间可预期（次日/5小时窗口）

两者的处理方式不同（前者无法预估恢复时间，后者可以），但当前都写入 `plan["queued"]=True`。新设计中应区分排队原因：
- `queue_reason: "gate_red"` / `"gate_yellow_low_priority"` — 系统故障
- `queue_reason: "budget_exceeded"` — 预算不足
- Portal 和通知根据不同原因显示不同信息

不需要按 provider 分别设 gate。Provider 级别的限流已由 preflight_budget 处理（Q4.6 的 provider fallback 路由）。Gate 只管系统级健康。

**(c) pulse 级任务不应被 gate YELLOW 阻塞。**

当前 gate YELLOW 只阻塞 `priority > 5` 的 run。但更好的做法是：

- **pulse 级任务**：只被 RED 阻塞，YELLOW 时照常执行。原因：pulse 是 1 步快速任务，即使基础设施部分降级，大概率能完成
- **thread 级任务**：被 RED 阻塞，YELLOW 时低优先级排队（当前行为）
- **campaign 级任务**：YELLOW 和 RED 都排队。原因：campaign 耗时长、多阶段，降级环境下风险更大

这让 gate 的粒度更合理——按 complexity 区分，而不仅按 priority。实现：在 gate check 中读取 RunSpec.complexity，与 gate 状态交叉判断。

### Q4.8 Dialog → Dispatch 的数据传递

Dialog 产出 plan + RunSpec，用户确认后 POST /submit 进入 Dispatch。

**问题：**
(a) submit 的 payload 结构是什么？当前 POST /submit 接受自由格式的 plan JSON。新设计中需要规范化吗？（如明确要求包含 RunSpec + plan DAG + metadata）
(b) 用户在 Portal 看到 plan 后，能调整哪些内容？只能整体接受/拒绝，还是可以微调（如改优先级、删某个步骤、改语言）？微调后 plan 是否需要重新验证收敛性？
(c) 直接 API 调用（不经过 Dialog）是否还支持？如果支持，API 调用者需要自己提供完整的 RunSpec + plan，还是 Dispatch 可以做最小化的自动补全？

**答：**
API调用我从来没用过，可以取消这个机制。这个机制有保留的必要吗？

**结论：**

**直接 API 调用保留，但作为内部接口而非用户入口。**

用户不用直接 API，但系统内部需要它：
- **Recurring chain**（定时任务）的自动触发：scheduler 调用 `dispatch.submit(plan)` 提交 run，走的就是内部 API 路径
- **Track 自动推进**：Track 的下一阶段经用户确认后，系统内部提交 run
- **暖机任务**：批量提交测试任务
- **未来扩展**：如果接入其他前端（如移动端），需要 API

所以 POST /submit 接口保留，但明确两条路径的差异：

**(a) submit 的 payload 规范化：**

当前 POST /submit 接受任意 JSON。新设计中规范化 payload：

```json
{
  "run_spec": {
    "objective": "...",
    "complexity": "thread",
    "step_budget": 4,
    "language": "bilingual",
    "depth": "standard",
    "references": [],
    "quality_hints": [],
    "confidence": "high"
  },
  "plan": {
    "steps": [
      {"id": "collect", "agent": "collect", "depends_on": []},
      {"id": "analyze", "agent": "analyze", "depends_on": ["collect"]},
      ...
    ]
  },
  "metadata": {
    "source": "portal_dialog",
    "lane_id": null,
    "track_id": null,
    "priority": 5
  }
}
```

`source` 字段标识来源：`portal_dialog`（用户通过 Dialog 提交）、`lane_trigger`（Lane 触发自动提交）、`track_advance`（Track 推进）、`warmup`（暖机）。

**(b) 用户在 Portal 的两种调整方式：**

**方式 1 — 参数微调（不改 plan 结构）：**
- **优先级**：默认 5，可调 1-10
- **语言**：可在 zh/en/bilingual 间切换
- **depth**：可在 brief/standard/thorough 间切换
- 微调后不需要重新验证收敛性（DAG 结构和步数不变）

**方式 2 — 自然语言修改意见（改 plan 结构）：**

用户看到 plan 可视化后，如果对方案不满意，可以在 plan 下方直接输入修改意见（如"不需要审查步骤"、"采集部分我已经有资料了"）。Router 根据修改意见重新生成 plan，再次展示给用户确认。

这与"拒绝 plan 回到 Dialog 从头来"在系统层面走的是同一条路径（Router 重新生成 plan → 验证收敛性 → 展示），但用户体验截然不同：
- "回到 Dialog" → 用户感到方案被否，要从头来 → 挫败感
- "在 plan 下方提修改意见" → 用户感到在和系统协商调整方案 → 协作感

**用户不直接操作 plan 结构**（不能拖拽删除步骤、不能改 agent 类型）。修改通过自然语言传达，Router 负责将用户意图转化为合法的新 plan 并保证收敛性。这与 Q3.5(b) 的 Dialog 设计一致——系统耐心适应用户的改动，用户不接触系统概念。

**(c) 内部 API 调用的自动补全：**

- `source=portal_dialog`：RunSpec 和 plan 由 Dialog 完整生成，Dispatch 只做 enrich
- `source=lane_trigger`：RunSpec 由 Lane 定义提供（创建 Lane 时已构造），plan 由 Dispatch 调 Dialog 的 plan 生成逻辑自动生成
- `source=warmup`：RunSpec 和 plan 由暖机脚本完整提供

所有路径最终都走 Dispatch.enrich() → submit()，保持统一。

## 阶段 5：执行与用户干预（Agents → Skills → Temporal）

### 前置：已确立的执行层设计

- **理念 C**：收敛性分层保障。计划阶段拦截不收敛任务；执行阶段靠 openclaw Tool-Loop Detection + circuit breaker；超时只用于故障检测
- **Q3.2(d)**：运行时复杂度修正——诊断 session → 查 Playbook → 针对性重构失败步骤，不是计数重试
- **Q3.7**：openclaw loop detection 按 agent 差异化配置，收敛性检测由 openclaw 内建机制完成
- **Q4**：Dispatch enrich 后 plan 进入 Temporal workflow 执行

以下问题聚焦：plan 进入执行后，每一步具体怎么跑、用户怎么看到进度、出了问题怎么处理。

---

### Q5.1 步骤执行的完整生命周期

Temporal workflow 按 DAG 依赖顺序调度 activity，每个 activity 向 per-Run agent 实例的主 session 发指令，主 session spawn subagent 执行该步骤。

**问题：**
(a) 一个步骤从"开始执行"到"完成"的完整流程是什么？包括：session 创建、prompt 构造（用户目标 + 上一步产出 + agent 能力描述）、执行、产出提取、状态更新。当前实现和新设计有哪些差异？
(b) 步骤之间的数据传递：上一步的产出如何传给下一步？是通过文件系统（outcome 目录）、Temporal payload、还是 openclaw session 上下文？
(c) 并发步骤（DAG 中无依赖关系的步骤）如何调度？Temporal 自动并发，还是 daemon 控制并发度？

**答：**
a skill在哪里？
b 这个问题我也不知道，反正肯定不是outcome
c Temporal是内化机制，daemon如果控制并发度，也是控制temporal的机制

**结论：**（基于预创建 agent 池模型重写）

**Run 启动阶段（Allocation，在步骤执行前）：**
1. AgentPoolManager 为该 Run 用到的每种 agent 类型分配空闲池实例——router 除外，router 是常驻 agent，直接用
2. 从 `templates/<role>/` 复制 SOUL.md、TOOLS.md → 各池实例 agentDir
3. 将 Fabric 快照写入各池实例的 workspace/memory/MEMORY.md

**一个步骤的完整生命周期：**
1. **调度启动**：Workflow 的 Kahn 拓扑排序确定就绪步骤 → `_start()` 创建 Temporal Activity
2. **Checkpoint 恢复**：检查 `run_root/checkpoints/{step_id}.json`，若已有 ok/degraded 结果则直接返回（幂等性）
3. **Skill 注入**：由 Router 在 plan 生成阶段动态选择，写入 step 定义的 `skills` 字段（见 Q5.7）
4. **发送指令**：Activity 向该 agent 类型的池实例主 session 发送步骤指令（step instruction + context + skills 配置）
5. **Subagent 执行**：主 session 发起 subagent 调用执行该步骤（subagent 有独立 context window，运行在 subagent lane）
6. **等待返回**：Activity 阻塞等待调用返回（openclaw 内建 loop detection + circuit breaker 保障收敛性），通过后台线程发送 Temporal heartbeat
7. **返回后检查**：检查 `abortedLastRun` 判断是正常完成还是被熔断，据此走正常流程或诊断流程
8. **产出提取**：Activity 从返回结果中提取产出，写入 `run_root/steps/{step_id}/output.md`
9. **Checkpoint 写入**：写入结果到 checkpoint 文件，供后续步骤或恢复使用

**步骤间数据传递——两条通道：**
- **同 agent 内**（如 collect 的两个步骤）：通过 agent 记忆。主 session（full mode）读写 agent 记忆，后续步骤的 subagent 通过主 session 自动受益于已更新的记忆。上下文自然连续。
- **跨 agent**（如 collect → analyze）：通过 `run_root` 文件系统。上一步产出写入 `run_root/steps/{step_id}/output.md`，下一步 Activity 读取依赖步骤的输出文件，拼入 context。

不通过 Temporal payload（有大小限制），不通过 outcome 目录（outcome 是最终交付物）。

**并发控制——三层：**
- **Workflow DAG**：根据 depends_on 判断哪些步骤可以同时启动，`max_parallel_steps` 限制全局并发数
- **Temporal worker**：worker 线程池大小决定同时运行的 activity 数量上限
- **openclaw subagent lane**：subagent 并发度（默认 8），同一池实例上的多个步骤通过各自 subagent 并行执行

三层数值保持一致（见 V2 §18.1）。

**Run 结束阶段（Return）：**
1. learn routine 从各池实例 workspace 提取认知 → Fabric Memory
2. 关闭主 session
3. 清空各池实例的 agentDir + workspace/memory/（恢复到空目录）
4. 归还池实例（标记为 idle）

### Q5.2 用户可见的执行进度

Q3.5 确立了"状态反馈原则：用户每次都必须有明确响应"。执行阶段可能持续数分钟到数小时。

**问题：**
(a) 用户在 Portal 上能看到什么？每个步骤的状态（pending/running/done/failed）？当前正在执行的步骤的实时输出？还是只看到整体进度？
(b) Telegram 在执行过程中推送什么？每步完成推一次？只推最终结果？还是按时间间隔推进度摘要？
(c) 执行时间预估：能否基于 complexity 默认值表告诉用户"预计还需要 X 分钟"？这个预估值得做吗？

**答：**
a 用户能看到plan，就应该按plan显示进度
b 只在完成的时候推。不过这里当前的设计是campaign会不一样。不知道要不要改。
c 预估值得做，但是你知道假进度条吧。

**结论：**

**Portal 进度展示**：按 plan 的步骤结构显示进度，而非抽象百分比。具体：
- 展示 plan 的步骤列表，每步显示状态：⏳ pending → 🔄 running → ✅ done / ❌ failed
- running 步骤显示已运行时长（实时计时器）
- 不显示 agent 实时输出（agent 内部操作对用户无意义，且可能包含系统指令）
- Campaign 额外显示：当前所在阶段（milestone N/M）、已完成阶段的摘要

**Telegram 推送策略**：
- pulse/thread：仅在完成时推送一次（含结果摘要 + Portal 链接）
- campaign：每个 milestone 完成后推送一次（因为需要用户确认下一阶段）+ 最终完成推送
- 失败/需要干预时推送一次
- 不在执行过程中推送进度（用户说"会非常烦"）

**时间预估**：采用"假进度条"策略——
- 基于 complexity 默认值表的 timeout 值给出宽松预估（如 thread timeout=300s → 显示"约5分钟"）
- 进度条基于已完成步骤数/总步骤数，不基于时间
- 不承诺精确剩余时间（每步耗时差异大，精确预估不可能）
- 进度条的价值在于"系统还活着"的反馈，而非准确的时间预测

### Q5.3 用户干预正在执行的 run

用户提交 run 后，可能想取消、暂停、或调整正在执行的任务。

**问题：**
(a) 取消（cancel）：用户取消后，正在运行的 openclaw session 怎么处理？等它自然结束？强制终止？已完成的步骤产出保留还是丢弃？
(b) 暂停和恢复：是否需要"暂停"功能（暂停当前 run，释放资源，稍后继续）？还是只支持"取消 + 重新提交"？
(c) 干预的入口：Portal 按钮 + Telegram 命令（Q3.1(c) 已设计 /cancel）。还有其他入口吗？干预操作是否需要确认？

**答：**
a cancel的任务不能恢复，而pause的任务可以恢复，这就是区别。cancel的任务停止所有执行，消除所有产物和存在的痕迹。另外这个cancel后的任务，在portal上怎么表现？需要讨论一下。
b 同a
c 没有其他入口，cancel因为有代价，所以要二次确认。设计一个好看的二次确认机制。

**结论：**

**Cancel 与 Pause 是两个本质不同的操作：**

| 维度 | Cancel | Pause |
|------|--------|-------|
| 语义 | 终止并销毁 | 暂停并保留 |
| 可逆性 | 不可逆 | 可恢复（resume） |
| 产物处理 | 删除 run_root 下所有中间产出和 checkpoint | 原样保留 |
| Temporal | 发送 CancelWorkflow → 触发 `asyncio.CancelledError` | 发送 `pause_execution` signal → workflow 等待 `resume_execution` |
| 状态记录 | 从 tasks.json 中移除（或标记 cancelled 后定期清理）| 标记 paused，保留完整记录 |
| 确认要求 | **需要二次确认**（因为有代价：已消耗的 token/时间不可回收） | 无需确认 |

**Cancel 的执行流程：**
1. 用户发起 cancel → 弹出确认对话（Portal: modal 对话框；Telegram: "确认取消？回复 Y"）
2. 用户确认 → API 调用 Temporal `cancel_workflow_execution(workflow_id)`
3. Workflow 收到 `CancelledError` → 标记 run 状态为 cancelled → 清理 session
4. 异步清理：删除 `run_root/` 目录（所有中间文件、checkpoint、step outputs）
5. 从 Portal 移除任务卡片（不留痕迹）

**Portal 表现（待讨论的问题）：**
- Cancel 后的任务**完全从 Portal 消失**——用户说"消除所有痕迹"。不显示 cancelled 状态卡片。
- 如果用户需要查看历史操作记录，可通过 Console（管理后台），但 Portal（用户界面）不保留。

**入口：** Portal 的任务卡片上的取消按钮 + Telegram `/cancel <run_id>`。无其他入口。

### Q5.4 步骤失败与 rework

理念 C 区分了"出错"和"不收敛"。Q3.2(d) 设计了运行时复杂度修正。

**问题：**
(a) 出错（openclaw error/exception）时的 rework 具体怎么做？同 session 重试？新 session 重试？换模型重试？rework_limit 由 complexity 默认值表决定（pulse=0, thread=1, campaign=2），这个限制够用吗？
(b) 不收敛（loop detection / circuit breaker 触发）时，Q3.2(d) 说"针对性重构失败步骤"。这个重构在代码层面怎么实现？是 Temporal workflow 内部处理，还是需要退出 workflow 回到 Dispatch 重新提交？
(c) rework 过程中，用户看到什么？系统静默处理然后通知结果？还是实时告知"正在重试第 X 步"？

**答：**
a 这个要具体讨论一下
b 也要讨论
c 不要实时告知，否则用户会非常烦，只有系统陷入用户必须处理的情况，才能去通知用户。

**结论：**

**出错时的 rework 机制（Q5.4a，已确认）：**

~~当前实现按 error_code 查表选择固定 agent 类型集合重做——这是旧的分类逻辑（同 Principle B 废除的 cluster 分类是同一种思路）。~~

**新设计：基于步骤追溯的 rework**

~~改造 delivery quality gate 的返回结构，从单一 error_code 改为带步骤来源的 failures 列表：~~

> [⚠️ 已修正 → S7-B] **delivery 不再有 quality gate。** 以下原方案整体废弃。
> 新设计：review agent 在 workflow 内独立完成所有质量判断（结构+语义），delivery = 纯物流（文件搬运+索引+状态更新）。
> rework 由 review agent 的评估结果驱动，不经过 delivery。
> 详见本文 S7-B。

~~```~~
~~delivery 返回: {"ok": false, "failures": [...]}~~
~~```~~
~~Workflow 的 `_rework_steps()` 直接从 `failures[].source_steps` 提取要重做的 step_id，不经过分类查表。~~

~~**改造范围：**~~
~~1. `activities_delivery.py`：`run_finalize_delivery()` 入口处加逐步骤质量检查~~
~~2. `workflows.py`：`_rework_steps()` 从 failures 提取 step_id~~
~~3. rework instruction 注入~~

**review agent 补齐语义质量检查（已确认，S7-B 进一步明确）：**

~~当前 delivery quality gate 只做结构性检查~~。review agent 是唯一的质量判断方。

解决方案：**review agent 独立承担全部质量审查职责**。
- review 步骤对上游产出做语义质量评估（覆盖面、分析深度、逻辑一致性、来源多样性）
- review 输出结构化评分（如 `{"coverage": 0.6, "depth": 0.8, "coherence": 0.9}`）
- ~~delivery quality gate 的 `content_review` 维度从 review 步骤的评分中读取~~ [⚠️ delivery 无 quality gate]
- 质量兜底链条：skill 失败 → agent 产出低质量内容 → **review agent 语义+结构审查捕获** → 评分不达标 → workflow 内触发 rework → 基于步骤追溯定位到源步骤

**其他确认点：**
- **不换模型重试**：确认。review 不达标通常不是模型能力问题，换模型引入不确定性。
- **rework_budget 默认值**：pulse=0, thread=1, campaign=2。暖机阶段验证。

**旧代码清理**：`playbook.py` BOOTSTRAP_METHODS 中硬编码的 `"rework_strategy": "error_code_based"` 需一并移除（属于 Principle B 废除范围内的遗留分类逻辑）。

**不收敛时的处理（Q5.4b，已确认）：**

不收敛 = openclaw circuit breaker / loop detection 触发。与 rework 不同——rework 是"质量不够再做一次"，不收敛是"agent 陷入循环"。

处理策略：
1. openclaw circuit breaker 触发 → session 终止 → activity 收到 degraded 状态
2. Workflow 层面：degraded 步骤不触发普通 rework（不收敛的步骤重做也大概率不收敛）
3. 进入"诊断 session"流程（Q3.2d）：Router agent 分析失败步骤的日志 → 查 Playbook 是否有类似失败的解法 → 重构 instruction（简化目标、拆解子步骤、或换 agent）
4. 重构后作为新步骤在 Workflow 内部提交，而非退出 workflow 重新提交整个 plan
5. 诊断 session 本身也有超时保护（60s），防止诊断过程本身不收敛

**用户可见性（Q5.4c，已确认）：**

普通 rework 与不收敛诊断的用户可见性**区分对待**：

| 场景 | Portal | Telegram |
|------|--------|----------|
| 普通 rework（质量不达标） | 步骤状态保持 🔄，不区分首次执行和 rework | 不推送 |
| 不收敛诊断 | 步骤显示特殊状态（如 🔍"系统正在诊断"） | 不推送 |
| rework_budget 耗尽仍失败 | 步骤标红，显示失败原因 | 推送通知 |

理由：不收敛比普通 rework 不确定性更高、耗时更长。Portal 上显示"诊断中"让正好在看的用户知道发生了什么，但不主动推 Telegram 打扰用户。

- 用户在 budget 耗尽通知后可选择：cancel、手动调整 plan 重新提交、或接受 degraded 产出

### Q5.5 campaign 的阶段管理

campaign 是多阶段执行（最多 5 阶段，每阶段 2-8 步）。Q3.4(a) 确定每个阶段完成后需要用户确认下一阶段方向。

**问题：**
(a) 阶段之间的衔接：一个阶段完成后，系统如何"暂停等待用户确认"？Temporal workflow 如何实现这种"等待外部信号"的模式？
(b) 阶段的 plan 是一次性全部生成（Dialog 阶段生成 5 个阶段的完整 plan），还是逐阶段生成（第一阶段完成后，基于产出生成第二阶段的 plan）？
(c) 用户在阶段间可以做什么？只确认/取消？还是可以调整后续阶段的方向（类似 Q4.8(b) 的自然语言修改意见）？

**答：**
a 这就要使用temporal的机制了，去研究一下，temporal之外的系统行为，我们根据temporal机制来设计，有什么不确定的和我讨论
b 逐阶段生成
c 可以调整

**结论：**

**阶段间衔接的 Temporal 机制：**

Campaign milestone 间等待用户确认，使用 **Temporal `wait_condition` + Signal**：

1. Milestone 完成后 → workflow 内部 `await workflow.wait_condition(lambda: self._user_confirmed)`
2. Workflow 挂起，状态持久化到 Temporal 数据库，worker 线程释放（不占运行时资源）
3. 用户在 Portal/Telegram 确认后 → API 发送 Signal → workflow 恢复执行
4. Workflow 上下文连续，无需从文件系统重建状态

与 Q5.3 的 pause/resume 使用同一 Temporal 机制，保持一致。

**废弃 return + re-submit 方案。** 原有理由"workflow 长期存活占用 Temporal 资源"不成立——Temporal 的 wait_condition 只是一条数据库记录，等一天和等一秒资源消耗相同。return + re-submit 引入了不必要的状态序列化/重建复杂度。

**逐阶段生成 plan（Q5.5b）：**

当前实现中 milestones 在 bootstrap 时一次性生成。需改为逐阶段生成：
1. Dialog 阶段只生成第一个 milestone 的详细 steps + 后续 milestones 的粗略目标描述
2. 每个 milestone 完成后，基于产出（campaign_context）+ 用户反馈 → Router 生成下一个 milestone 的详细 steps
3. Workflow 上下文连续（wait_condition + Signal），不需要 bootstrap 重建状态，直接在 workflow 内生成下一 milestone 的 steps

**用户阶段间干预（Q5.5c）：**

用户在 milestone 间可以：
- **确认继续**：无修改，继续下一 milestone
- **调整方向**：用自然语言提修改意见（复用 Q4.8b 的机制），Router 据此调整下一 milestone 的 steps
- **取消整个 campaign**：二次确认后销毁（同 Q5.3 cancel 机制）
- **不做**：campaign 保持 paused，无超时限制（用户可能需要思考数天）

### Q5.6 openclaw session 管理

每个池实例在 Run 期间运行一个主 session（full mode），步骤通过主 session 发起 subagent 调用执行。daemon 管理池实例分配/归还、主 session 和 subagent 生命周期。

**问题：**
(a) session 的生命周期管理：session 创建时的配置（timeoutSeconds、contextTokens、loop detection 阈值）从哪来？complexity 默认值表 + Q3.7 的 agent 差异化配置？
(b) session 的监控：daemon 如何得知 session 的执行状态和结果？
(c) session 清理：run 完成/取消后，相关的 openclaw session 是否需要显式清理？还是 openclaw 自动回收？

**答：**
a 应该是吧。不是吗？
b openclaw应该有这个机制，之前说过，agent的行为，要多参考openclaw的机制
c 同b

**结论：**（基于预创建 agent 池模型重写）

**Session 架构——三层：**

| 层级 | 类型 | 创建时机 | 生命周期 |
|------|------|---------|---------|
| 池实例 | agent（bootstrap 预注册，agentDir/workspace 空目录） | 系统启动 | 常驻，Run 间复用 |
| 主 session | session（full mode） | Run 启动时创建 | Run 结束时关闭 |
| subagent | 主 session 内发起的子调用 | Activity 执行步骤时发起 | 步骤完成后自动结束 |

**配置来源：**
1. **池实例配置**：bootstrap 时写入 openclaw.json（注册 agent + 创建空目录）；agentDir 内容（SOUL.md、TOOLS.md 等）在分配时从 `templates/<role>/` 复制填充，归还时清理
2. **主 session 配置**：full mode，读写 agent 记忆，Run 期间持久存在
3. **Subagent 配置**：`runTimeoutSeconds` 从 plan 的 `default_step_timeout_s` 或 step 的 `timeout_s` 读取（不硬编码）
4. **Agent 差异化配置**（Q3.7）：loop detection 阈值、context window 大小 → 由池实例的 openclaw agent 配置决定

**监控——三层保障：**
1. **openclaw 内部**：subagent 自带 `runTimeoutSeconds` 超时保护 + loop detection（circuit breaker）。openclaw 的内建机制，daemon 不重复实现。
2. **Activity 阻塞等待**：Activity 阻塞等待 subagent 调用返回，调用返回后检查 `abortedLastRun` 判断是正常完成还是被熔断。收敛性检测完全由 openclaw 内建机制负责（Q3.7），daemon 不重复实现。
3. **Temporal heartbeat**：Activity 通过后台线程发送 heartbeat（间隔 < 90s），防止 Temporal 误判 activity 超时。

**清理：**
1. **Subagent**：步骤完成后自动结束，无需显式清理。
2. **主 session**：Run 结束时由 AgentPoolManager 关闭。
3. **池实例记忆**：Run 结束时由 AgentPoolManager 清理实例 memory 目录，恢复到空白状态后归还池。
4. **启动恢复**：daemon 启动时扫描所有池实例状态，将 occupied 实例关闭主 session、清理记忆并归还。

### Q5.7 skill 的选择与调用

当前每种 agent 有预装的 openclaw skills（如 build agent 有 coding_agent_v2、github_ops）。

**问题：**
(a) skill 的选择是静态的（agent 类型 → 固定 skill 集合）还是动态的（根据任务内容选择 skill）？
(b) skill 执行失败时的行为：是 agent 内部处理（openclaw session 内 retry），还是上报为步骤失败触发 rework？
(c) 未来的 skill 扩展（如用户安装新 skill）对执行流程有什么影响？需要在这个阶段考虑吗？

**答：**
a 必须是动态的
b 这个要讨论一下
c 需要考虑，因为skill扩展和修改会一直发生，skill的更新淘汰学习机制非常重要。不过这个和自我进化关系比较大。

**结论：**

**动态 Skill 选择（Q5.7a）：**

当前实现：每个 agent 在 TOOLS.md 中静态列出可用 skills。需改为动态选择：

1. **Skill 注册表**：`config/skill_registry.json`，列出所有已安装的 skills，每个 skill 声明：
   - `skill_id`、`display_name`、`description`
   - `compatible_agents`：哪些 agent 类型可以使用（如 `coding_agent_v2` 只对 build agent 有意义）
   - `capability_tags`：能力标签（如 `["code_generation", "github"]`）
   - `status`：active / deprecated / experimental

2. **选择时机**：Router 在 plan 生成阶段，根据任务 objective + 步骤 instruction，从 skill_registry 中匹配合适的 skills，写入 step 定义的 `skills` 字段
3. **选择依据**：skill 的 `capability_tags` 与步骤 instruction 的语义匹配（可用简单关键词匹配，不需要 embedding）
4. **传递方式**：step.skills → Activity 创建 session 时配置 agent 的可用 tools

**Skill 执行失败（Q5.7b，需讨论确认）：**

两层处理：
1. **Agent 内部处理**（openclaw session 内）：skill 调用失败 → agent 自行决定是否重试或换用其他 skill。这是 agent 自治范围内的事务，daemon 不干预。
2. **上报为步骤失败**（超出 agent 自治能力）：如果 agent 因 skill 故障导致整个步骤无法完成（timeout 或 circuit breaker 触发），则按 Q5.4 的 rework 机制处理。

原则：**单次 skill 调用失败 ≠ 步骤失败**。Agent 有多个 skill 可用，有自主判断力，应给 agent 空间处理局部故障。只有步骤整体产出质量不达标才触发 daemon 层面的 rework。

**Skill 扩展与进化（Q5.7c）：**

这是自我进化（阶段 9）的核心议题之一，此处只定义接口约束，不做完整设计：

1. **skill_registry.json 由 Claude Code 审批维护**。系统（Spine routine）可以发现和提议新 skill，Claude Code（Q2.11 排障通道）负责审批——评估安全性、兼容性、测试后决定是否安装。人类不参与 skill 审批流程。
2. **Skill 使用效果追踪**：每次 skill 被选用后，在 step 结果中记录 `skills_used` 字段。Playbook learn() 据此积累"哪些 skill 对哪类任务有效"的经验。
3. **Skill 淘汰信号**：如果某 skill 连续 N 次被选用但步骤产出都是 degraded/failed，Playbook 提议将其标记为 deprecated。Claude Code 审批淘汰决定。
4. **新 Skill 引入**：系统发现 → Claude Code 审批安装 → 注册到 skill_registry.json。暖机阶段覆盖现有 skill 集合的验证。

详细的 Skill Discovery → Benchmark → Deploy 流程在阶段 9 展开。

## 阶段 6：交付（Outcome → PDF → 通知 → Portal）

### 前置：已确立的交付相关设计

- **Q3.6(a) RunSpec**：`language=bilingual` → 两份完整文件（各自遵循本语言规范，不是翻译）；~~`format=pdf/markdown/code/text`~~ [⚠️ S6-D: format 不硬编码，由 task type + compass + playbook 自适应决定]
- **Q4.5**：质量底线分两层——不可协商的格式规范（hardcoded）+ 可调整的内容规范（学习调整）
- **Q5.1**：步骤产出写入 `run_root/steps/{step_id}/output.md`；outcome 目录是最终交付物，不用于步骤间传递
- **Q5.2**：Portal 按步骤展示进度；Telegram 完成时推送一次（含结果摘要 + Portal 链接）
- **Q5.4**：review agent 承担语义审查 ~~+ delivery quality gate 做结构检查，双层质量兜底~~ [⚠️ 已修正 → S7-B: delivery 无 quality gate，review agent 独立完成全部质量判断]
- **Outcome 存储位置**：outcomes 不在 daemon repo 内，在 `~/My Drive/daemon/outcomes/`（与 `archive/` 同级）。当前结构：按月分目录（`2026-03/`），每个 outcome 一个目录（`{date} {time} {title}/`），内含用户文档（.md / .pdf）+ summary.txt，零系统文件（S6-A: manifest.json 已移除）。该路径是 Google Drive 同步目录，自带云备份。daemon repo 的 state/ 不存储交付物文件。run↔outcome 映射走 state/delivery_log.jsonl

---

### Q6.1 Outcome 的纯净性与结构

当前 outcome 已有实际存储结构：`~/My Drive/daemon/outcomes/{YYYY-MM}/{YYYY-MM-DD HH.MM title}/`，每个目录含用户文档（.md / .pdf）+ summary.txt（S6-A: manifest.json 已移除，零系统文件）。

**核心约束（已确认）：** outcomes 是纯净的用户产出——零 run_id、零系统术语、零内部特征。用户打开 outcomes/ 看到的就是人类可读的文件，与 daemon 系统完全无关。

**问题：**
(a) 当前 manifest.json 包含 run_id、run_type、run_root 等系统内部信息，违反"零系统内痕迹"原则。manifest 是否应该从 outcomes/ 移除？还是保留但内容精简为纯用户信息（标题、日期）？
(b) 当前结构在 bilingual 场景下如何扩展？V2 设计为 `<运行标题>（中文）.md` + `<Run Title> (English).md` 两个独立文件（零系统标记，文件名只有人类可读的标题）。PDF 同理？
(c) outcome 是 render 步骤的直接产出，还是需要一个独立的"组装"环节？当前 `delivery.py` 的 `_archive()` 方法从 render output 复制文件到 outcomes/——这个环节是否需要做"系统痕迹清洗"（如去除 markdown 中的系统标记）？

**提议结论（待用户确认）：**

**(a) manifest.json 从 outcomes/ 移除。** [⚠️ S6-A 补充：run↔outcome 映射走 state/delivery_log.jsonl]

manifest.json 是系统内部元数据（run_id、run_type、run_root），在 outcomes/ 中违反零系统痕迹原则。

处理：
- outcomes/ 目录中不再写入 manifest.json
- ~~系统内部的 manifest 写入 archive/~~ → run↔outcome 映射记录到 `state/delivery_log.jsonl`
- outcomes/ 中只有人类可读文件：文档（.md / .pdf）和摘要（summary.txt）

outcome 目录结构变为：
```
~/My Drive/daemon/outcomes/2026-03/2026-03-07 14.30 研究报告/
  ├── 研究报告（中文）.md
  ├── 研究报告（中文）.pdf
  ├── Research Report (English).md
  ├── Research Report (English).pdf
  └── summary.txt
```

零 JSON、零 run_id、零系统术语。用户在 Google Drive 中看到的就是纯粹的文档。

**(b) bilingual 场景下四个文件。**

如上结构：中英各一份 markdown + PDF。文件名规范：
- 中文文件名：`{标题}（中文）.{ext}`
- 英文文件名：`{Title} (English).{ext}`

非 bilingual 时：只有一种语言的文件。文件名不带语言标记：`{标题}.md` + `{标题}.pdf`

**(c) delivery activity 负责"系统痕迹清洗"。**

render agent 产出的文件可能包含系统标记（如 markdown 中的 `<!-- step_id: xxx -->` 注释、`[DRAFT]` 标记）。delivery activity 在复制文件到 outcomes/ 前做一次清洗：

1. 去除 markdown 注释中的系统信息（`<!-- ... -->`）
2. 去除 Q4.5(d) 的 `forbidden_markers`（`<system>`、`[INTERNAL]`、`DRAFT` 等）
3. 验证清洗后的文件仍然结构完整

清洗逻辑是确定性的正则替换，不涉及 LLM。作为 delivery activity 的一个子步骤。

### Q6.1b Archive 的定位与内容

**核心约束（已确认）：** `~/My Drive/daemon/archive/` 是系统内部的执行痕迹存档。与 outcomes（用户产出）相对——archive 保存系统视角的运行记录，可以包含 run_id、step_id、score、agent 日志等系统内部信息。

**背景：** run 完成交付后，`state/runs/{run_id}/`（run_root）包含所有中间产物（步骤产出、checkpoint、session 日志）。run_root 不能永久保留（占磁盘、state/ git 负担）。但如果用户想追评一个过去完成的任务，或系统想回溯学习，需要能找到当时的执行痕迹。

**问题：**
(a) archive 具体保存 run_root 的哪些内容？完整拷贝（大）？精简快照（各步骤 output.md + manifest + quality score）？还是只保存元数据索引（可追溯但不保留原始产出）？
(b) archive 的目录结构：按 run 组织（`archive/{run_id}/`）？按时间组织（`archive/YYYY-MM/`）？还是按 Track 组织？
(c) run_root 清理的触发条件：交付后立即清理（只保留 archive）？延迟清理（如 7 天后）？librarian routine 负责？
(d) archive 与追评的关系：用户追评时，Portal 从 archive 中读取什么来展示？步骤级的中间产出？还是只展示 outcome + quality score 的汇总？
(e) archive 与学习的关系：learn/witness routine 在 run 完成时已经提取了认知写入 Fabric。archive 中的数据还会被 Spine routine 回溯分析吗？还是 archive 只用于用户追评和审计？
(f) failed run（rework 耗尽仍失败）不产出 outcome，但有执行痕迹。failed run 的 run_root 是否也归档到 archive？cancel 的 run 呢（Q5.3 说删除所有痕迹——是否包括不归档到 archive）？

**提议结论（待用户确认）：**

**(a) 精简快照，不完整拷贝。**

archive 保存内容：

| 内容 | 来源 | 用途 |
|------|------|------|
| `manifest.json` | delivery activity 生成 | run 元数据（run_id, objective, complexity, 步骤列表, 时间戳）——不含 quality_score（S7-B: delivery 不评分） |
| `steps/` | run_root/steps/ 精简拷贝 | 每个步骤的 `output.md`（产出）+ `meta.json`（agent 类型、耗时、状态） |
| `review_report.json` | review 步骤产出 | review agent 的完整评分和评语 |

不保存：checkpoint 文件（恢复用，归档后无意义）、session 日志原始文件（太大，认知已被 learn 提取）、render 中间产物（最终产出在 outcomes/）。

预估每个 archive 条目 50-200KB（主要是 output.md 文件）。

**(b) 按时间组织（`archive/YYYY-MM/run_id/`）。**

与 outcomes/ 的时间组织方式一致。不按 Track 组织——大多数 run 不属于 Track，且 Track 信息在 manifest.json 的 `track_id` 字段中已有。

**(c) librarian routine 延迟清理 run_root。**

- delivery activity 完成后，run_root 不立即清理（万一归档过程中断，还可从 run_root 恢复）
- librarian routine（Q2.7 已分配）定期扫描 run_root：
  - 已归档（archive_status=archived）且 run 完成超过 7 天 → 删除 run_root
  - 未归档 → 执行归档 → 标记 archived
  - archive_status=expired（超过 90 天）→ 删除 archive 目录

**(d) Portal 追评时展示步骤级信息。**

Portal 从 archive 读取并展示：
- 每个步骤的产出摘要（output.md 的前 500 字）
- review_report.json 的评分和评语（coverage/depth/coherence/accuracy/format_compliance）

用户据此做出反馈选择（"深度不够"、"遗漏信息"等）。不展示 agent 内部日志（系统语言隔离）。

**(e) archive 主要用于追评和审计，Spine 通常不回溯。**

- learn/witness/record routine 在 run 完成时已经提取了所有需要的信息写入 Fabric
- archive 是"以防万一"的存档，不是 Spine 的常规数据源
- 例外：如果 witness 发现某个系统性问题需要回溯分析（如"最近一个月的 collect 步骤都有覆盖面不足的问题"），witness 可以从 archive 读取历史步骤产出做深度分析。这是低频操作

**(f) failed run 归档，cancelled run 不归档。**

- **failed run**：归档到 archive。虽然没有 outcome，但执行痕迹对学习有价值（Playbook 记录 `success=false`，archive 保留步骤级失败详情供 witness 分析）
- **cancelled run**：不归档。Q5.3 已确认"删除所有痕迹"——包括不写入 archive。cancel 是用户主动放弃，执行痕迹没有学习价值

### Q6.2 渲染管线

> [⚠️ S6-D 修正] 产出格式不由 RunSpec.format 硬编码决定，而是由 task type + compass prefs + playbook 历史自适应决定。render agent 根据这些信息判断"一个人类做这种任务会交付什么"。以下讨论中涉及 PDF 的部分仍有效（PDF 是可能的产出格式之一），但 format 不再是离散枚举值。

render agent 使用 `nano_pdf_render` skill（GLM Z1 Flash 模型），负责最终格式化。

**问题：**
(a) 渲染的输入是什么？render agent 直接从 `run_root/steps/` 读取上游步骤产出，还是从某个"合并后的中间产物"读取？如果上游有多个步骤（collect + analyze），谁负责把它们合并为 render 的输入？
(b) bilingual 渲染：两份是同一个 render 步骤产出两份，还是两个独立的 render 步骤各产出一份？前者效率高但要求 agent 一次产出两份完整文件；后者清晰但步数翻倍。
(c) 渲染失败的处理：渲染是"结构性操作"（不太可能不收敛），但可能因格式错误失败。失败时走 rework 还是有专门的修复逻辑？
(d) render agent 负责所有格式的最终格式化，还是只处理 PDF？

**提议结论（待用户确认）：**

**(a) render agent 从合并后的中间产物读取。**

上游可能有多个步骤产出（如 collect_01 + collect_02 + analyze_01）。render agent 不应自己去收集和合并。

合并责任：**Temporal workflow 在启动 render activity 前，合并依赖步骤的产出**。具体：
1. Workflow 根据 plan DAG 找到 render 步骤的 `depends_on` 列表
2. 按顺序读取各依赖步骤的 `run_root/steps/{step_id}/output.md`
3. 拼接为一个 `run_root/render_input.md`
4. render activity 读取 `render_input.md` 作为输入

合并逻辑简单（按步骤顺序拼接，各步骤产出之间加分隔符），在 workflow 层面完成，不需要单独的"合并步骤"。

**(b) 同一 render 步骤产出两份。**

与 Q6.4(a) 一致。bilingual 时 render agent 一次产出中英两份，instruction 明确要求各自遵循本语言规范。步数不翻倍。

PDF 渲染：render agent 先产出两份 markdown（各自规范），然后调 `nano_pdf_render` skill 将 markdown 转 PDF。产出：
- `{title}（中文）.md` + `{title}（中文）.pdf`
- `{title} (English).md` + `{title} (English).pdf`

**(c) 渲染失败走 rework。**

render 失败主要是格式错误（如 markdown 结构不完整导致 PDF 转换失败）。不需要专门修复逻辑——rework 时 render agent 收到失败原因（"PDF 转换失败，第 42 行 markdown 语法错误"），自行修复后重新渲染。

rework_limit 同样受 complexity 默认值表控制（Q4.2(c)），render 的 rework 计入总 rework 预算。

**(d) render agent 负责所有非代码产出的最终格式化。** [⚠️ S6-D 修正：format 不再硬编码]

render agent 的职责是"最终格式化"，具体产出什么格式由自适应决策决定（task type + compass prefs + playbook 历史）：
- 需要 PDF 时：产出 markdown + PDF
- 纯文档时：产出最终格式化的 markdown（标题层级、段落结构、引用格式规范化）
- 纯文本时：产出纯文本（简化格式，去除 markdown 标记）
- 代码产出：不经过 render agent——code 由 build agent 直接产出，render 步骤跳过

代码产出是唯一不需要 render 步骤的情况。plan 生成时，Router 判断任务主要产出为代码时，plan 中不包含 render 步骤。

### Q6.3 交付通知与用户获取

Q5.2 确定了完成时通过 Telegram 推送摘要 + Portal 链接。

**问题：**
(a) Portal 上 outcome 的展示方式：用户点进一个已完成的 run，看到什么？直接预览内容（内嵌 PDF/markdown viewer）？还是只提供下载链接？
(b) Telegram 推送的"结果摘要"由谁生成？render agent 附带生成？还是交付阶段单独调 LLM 生成一句话摘要？摘要的长度和风格？
(c) 用户从 Telegram 点链接打开 Portal 查看结果——这个链接指向什么？一个带 run_id 的 Portal 页面？需要鉴权吗？（当前 Portal 无登录机制）
(d) 交付后用户是否需要"确认收货"？还是推送即完成？用户反馈（Q4.2 的 user_feedback，选择题形式）在什么时机收集？——已确认：Portal 主动弹出反馈选择界面，用户可直接关掉不回答。

**提议结论（待用户确认）：**

**(a) 内嵌预览 + 下载。**

- markdown 产出：Portal 内嵌 markdown viewer（渲染为 HTML 显示）
- PDF 产出：Portal 内嵌 PDF viewer（`<iframe>` 或 PDF.js）
- 同时提供"在文件管理器中打开"按钮（打开 `~/My Drive/daemon/outcomes/` 对应目录）
- bilingual 产出：两个 tab 切换（"中文版" / "English"）

**(b) render agent 附带生成摘要。**

不额外调 LLM——render agent 已经处理了完整内容，顺便生成摘要成本几乎为零。

在 render agent 的 instruction 中要求："产出完整文档后，额外生成一个不超过 100 字的中文摘要，写入 `summary.txt`。"

摘要风格：直接说结论/成果，不废话。示例："完成了 React 项目的性能优化方案，涵盖组件渲染优化、状态管理重构和 bundle 拆分三个方向。"

Telegram 推送格式：
```
✅ 任务完成：{title}
{summary}
查看详情：{portal_link}
```

**(c) Portal 链接指向带 run_id 的结果页。**

链接格式：`http://{host}:{port}/portal/result/{run_id}`

鉴权：当前无需鉴权（Portal 仅本地/内网访问）。未来通过 Tailscale 对外暴露时，走 Tailscale 的设备认证。不在 daemon 应用层做登录系统。

**(d) 推送即完成，反馈弹窗异步收集。**

- run 完成 = delivery activity 成功执行。不需要"确认收货"
- Portal 在用户下次打开时弹出反馈选择界面（如果有未反馈的 outcome）
- 弹窗出现时机：用户进入 Portal → 检查 delivery_log.jsonl 中 user_feedback=null 且 completed_utc 在最近 7 天内的记录 → 弹出最近一条的反馈界面
- 一次只弹一条（不堆叠多个弹窗）
- 用户关掉 = user_feedback 保持 null，不再弹出该条（但可在历史任务列表中追评，Q7.2(e)）

### Q6.4 bilingual 产出的质量保障

RunSpec.language=bilingual 要求中英一式两份，**内容相同，但各自遵循本语言的文档规范和格式**。"不是翻译"不是说内容不同，而是说直接翻译只换语言不换规范——中文遵循中文排版/引用规范（GB/T 7714），英文遵循英文排版/引用规范（APA/Chicago），格式、行文习惯、引用样式各自独立。

**问题：**
(a) 技术实现：中英两份是同一个 render 步骤先产出一份再按目标语言规范重写第二份？还是两个独立的 render 步骤各自产出？前者效率高但第二份可能沦为"格式翻译"；后者清晰但步数翻倍且内容一致性需要额外保证。
(b) review agent 审查 bilingual 产出时，是否需要对两份文件分别审查？审查重点不同——中文版检查中文规范合规性，英文版检查英文规范合规性？还是只审查内容质量一次，格式合规由 quality gate 结构检查分别处理？
(c) 内容一致性保证：两份文件内容应该相同（事实、论点、结论一致），但格式规范不同。如何验证内容一致性？需要一个专门的"cross-language consistency check"？还是 review agent 同时审查两份时自然覆盖？

**提议结论（待用户确认）：**

**(a) 同一 render 步骤产出两份，但 instruction 明确要求独立规范。**

两个独立 render 步骤的方案步数翻倍且内容一致性难保证（两个独立步骤可能产出不同内容）。

同一步骤产出两份的方案：
- render agent 的 instruction 明确要求："产出中文版和英文版各一份。中文版遵循中文排版/引用规范（GB/T 7714），英文版遵循英文排版/引用规范（APA/Chicago）。两份内容（事实、论点、结论）必须相同，格式和行文习惯各自独立。"
- 产出两个文件：`{title}（中文）.md` 和 `{title} (English).md`
- 防止"格式翻译"的关键在 render SOUL.md 的 prompt 设计——暖机阶段校准，确保两份产出各自符合本语言规范

**(b) review 审查内容 + 格式合规。** [⚠️ 已修正 → S7-B+S6-D]

> quality gate 已废弃。review agent 在 workflow 内同时审查内容质量和格式合规。
> 格式不硬编码（自适应 > 预设规则），由 task type + compass prefs + playbook 历史决定。

- review agent 审查内容质量（coverage/depth/coherence/accuracy）
- review agent 同时检查格式合规（中文/英文各自规范）
- ~~quality gate 的 `format_compliance` 维度~~ → review agent 的评分维度之一

**(c) review agent 同时审查两份时自然覆盖内容一致性。**

不需要专门的 cross-language consistency check。review agent 的 instruction 中包含："确认中英两份文件的事实、论点、结论一致。"review agent 能够双语阅读，自然发现内容不一致。

如果暖机阶段发现 review agent 无法可靠检测内容不一致，再引入专门的 consistency check 步骤。暖机前不预设复杂机制。

### Q6.5 Outcome 与 Archive 的生命周期管理

Q2.7 已将归档管理分配给 librarian routine。现在有三个存储位置需要协调生命周期：
- `state/runs/{run_id}/`（run_root）—— daemon 内部运行时目录
- `~/My Drive/daemon/outcomes/` —— 用户产出，零系统痕迹
- `~/My Drive/daemon/archive/` —— 系统执行痕迹存档

**问题：**
(a) 三者的生命周期时间线：run 完成后，run_root 何时清理？archive 何时写入？outcome 何时写入？是同步的（交付时一次性完成）还是异步的（交付写 outcome，librarian 稍后写 archive 并清理 run_root）？
(b) outcome 的清理：outcomes/ 永久保留（靠 Google Drive 空间）？还是有时间限制（如 V2 设计的 6 个月后删除）？用户可能想保留所有历史产出。
(c) archive 的清理：archive 中的执行痕迹保留多久？追评是否有时间窗口限制（如 30 天内可追评，之后 archive 清理）？
(d) state/ git repo 不应包含 outcome 和 archive 的内容（都在 `~/My Drive/` 下）。但 state/ 中是否需要保留一个轻量索引（如 `state/delivery_log.jsonl`）记录 run_id → outcome 路径 → archive 路径 的映射？

**提议结论（待用户确认）：**

**(a) 交付时同步写 outcome，librarian 异步写 archive 并清理 run_root。**

时间线：
```
run_completed 事件 →
  1. 同步：delivery activity 写 outcome 到 ~/My Drive/daemon/outcomes/（用户立即可见）
  2. 同步：delivery activity 写 delivery_log.jsonl 索引记录
  3. 同步：Nerve emit delivery_completed 事件
  4. 异步（librarian routine 下次运行时）：
     a. 从 run_root 提取执行痕迹 → 写入 ~/My Drive/daemon/archive/
     b. 清理 run_root 目录
```

为什么 outcome 同步、archive 异步：
- outcome 是用户交付物，必须在 run 完成时立即可用（Telegram 通知 + Portal 展示）
- archive 是系统内部存档，不面向用户，可以延迟处理。librarian 批量处理更高效

**(b) outcomes 永久保留。**

- outcomes/ 在 Google Drive 下，空间充足（Google One 2TB 方案）
- 用户的历史产出有长期价值（回顾、引用、对比）
- 不设自动清理——如果用户想清理旧 outcome，手动在 Google Drive 中操作
- V2 的 6 个月删除设计废弃

**(c) archive 保留 90 天。**

- 追评的合理时间窗口：90 天（3 个月）
- librarian routine 定期清理超过 90 天的 archive 条目
- 90 天后 archive 数据删除，但 Playbook 中的经验记录永久保留（经验是提炼后的，不依赖原始 archive）
- 追评仍可在 90 天后做（Q7.2(e)），只是无法查看步骤级详情

**(d) state/ 中保留轻量索引 `state/delivery_log.jsonl`。**

每条记录：
```json
{
  "run_id": "uuid",
  "completed_utc": "2026-03-07T14:30:00Z",
  "outcome_path": "~/My Drive/daemon/outcomes/2026-03/2026-03-07 14.30 Title/",
  "archive_path": "~/My Drive/daemon/archive/2026-03/run_uuid/",
  "archive_status": "pending|archived|expired",
  "lane_id": "uuid|null",
  "track_id": "uuid|null",
  "complexity": "thread",
  "user_feedback": null
}
```

用途：
- Portal 历史任务列表的数据源
- 追评时定位 archive 和 outcome
- Spine routine 的统计分析
- tend routine 清理超过 90 天的记录中的 archive_path（标记 expired）

### S6-A: outcomes/ 中的 manifest.json ✅ 已决定

**决策**：移除 manifest.json。outcomes/ 只放用户文档。run ↔ outcome 的映射走 state/delivery_log.jsonl。

### S6-B: 交付索引的存放位置 ✅ 已决定

**决策**：迁移到 state/delivery_log.jsonl（JSONL 格式，append-only）。目录名统一为 `outcomes`（复数），**系统内不再出现 `outcome`（单数）用法**——变量名、路径、注释、文档全部统一。

### S6-C: bilingual 两份文件由谁产出 ✅ 已决定

**核心讨论**：

用户确立 **"伪人"原则**——daemon 对外的行为逻辑应该和人类一致：
1. **产出格式因任务类型而异**：researcher 写论文，developer 写代码 + 文档，consultant 写报告……不是所有任务都产出 markdown + PDF。
2. **双语产出 = 人类双语工作者的行为**：同一份工作成果，用两种语言各自独立表达，每份遵循本语言的全部规范（中文 GB/T 7714 引用/中文排版 vs 英文 APA/Chicago 引用/英文排版）。"不是翻译"= 不能只换语言不换规范。
3. **对外不可分辨**：收到产出的人，看不出这是系统产出还是人类产出。

**决策**：
- render agent 产出，delivery 搬运
- 产物语言 = compass pref `output_languages`，默认 `["zh", "en"]`
- render agent 以"双语专业人士"的方式产出两份独立文件
- 产出的具体格式和文件组成**由任务类型决定**，不硬编码

### S6-D: 产出格式自适应 ✅ 已决定

**核心设计风格确认**：**自适应 > 预设规则**
- 可配置优先于硬编码。系统里几乎一切都是参数（compass pref），不是常量
- 上下文决定行为。不同任务类型的产出完全不同
- "伪人"原则。产出应该模仿人类行为
- 演化优先于一次性规定。从 playbook 经验中学习什么产出格式最有效

**决策**：产出格式由 **任务类型 + compass 偏好 + playbook 历史经验** 共同决定。render agent 根据这些信息判断"一个人类做这种任务会交付什么"，然后产出对应的东西。delivery 只负责搬运，不检查"你该产出什么"。

---

## 阶段 7：评价与学习（Review → Feedback → Spine 学习循环）

### 前置：已确立的评价与学习设计

- **Q4.2**：Playbook 经验记录含 `outcome_quality`（review 评分）+ `user_feedback`（用户反馈选择，非打分）；embedding 检索 + quality_bonus 加权
- **Q4.3**：策略废弃，参数优劣通过 Playbook 经验的自然积累体现（记录 → 浮现 → 衰减 → 淘汰）
- **Q4.5**：质量四层来源（用户显式 > Playbook 历史 > Compass 偏好 > 系统默认），review agent 承担语义审查
- **Q5.4**：review 输出结构化评分（coverage/depth/coherence），review 不达标在 workflow 内触发 rework（S7-B: delivery 无 quality gate）
- **Q1.1**：Memory 热度衰减 + 合并压缩；**Q1.3**：Playbook 策略带时间戳和使用计数，衰减到阈值标记 stale
- **Q1.5**：Compass 偏好带 confidence（基于样本量）

---

### Q7.1 review agent 的评分维度与标准

Q5.4 提到 review 输出 `{"coverage": 0.6, "depth": 0.8, "coherence": 0.9}`。但这只是示例。

**问题：**
(a) review agent 的完整评分维度是什么？coverage/depth/coherence 是否足够？是否需要加入 accuracy（事实准确性）、originality（非抄袭/重复）、actionability（实用性）？
(b) 每个维度的评分标准是什么？0-1 浮点？等级制（A/B/C/D）？review agent 如何保证评分的一致性（同类产出获得相似评分）？
(c) 评分维度是否与 RunSpec 相关？比如 RunSpec.depth=brief 时，depth 评分标准是否放宽？还是评分标准固定，RunSpec 只影响"是否触发 rework 的阈值"？
(d) review agent 使用 Qwen Max 模型——如果 review 的评分本身不准确怎么办？是否需要一个"review 的 review"校准机制？还是靠用户反馈选择来间接校准 review 模型的判断？

**提议结论（待用户确认）：**

**(a) 五个评分维度。**

| 维度 | 含义 | 适用场景 |
|------|------|---------|
| `coverage` | 信息覆盖面——是否遗漏关键方面 | 所有 |
| `depth` | 分析/论述深度——不是字数，是思考深度 | 所有 |
| `coherence` | 逻辑一致性——结构清晰、论证连贯 | 所有 |
| `accuracy` | 事实准确性——数据、引用、技术细节是否正确 | research/analysis 类 |
| `format_compliance` | 格式规范——排版、引用格式、双语规范 | 所有 |

不加 `originality`（daemon 产出本身是 LLM 生成的，非抄袭检测场景）和 `actionability`（太主观，review agent 难以判断"对用户是否实用"）。

**(b) 0-1 浮点，通过结构化 prompt 保证一致性。**

review agent 的 SOUL.md 中定义每个维度的评分锚点：
- 0.0-0.3：严重缺陷（大量遗漏/错误/逻辑混乱）
- 0.4-0.6：基本达标但有明显不足
- 0.7-0.8：良好，无重大问题
- 0.9-1.0：优秀，超出预期

每个维度的锚点描述具体到该维度（如 coverage 0.3 = "遗漏了超过一半的关键方面"）。

review agent 的输出格式固定：
```json
{"coverage": 0.7, "depth": 0.8, "coherence": 0.9, "accuracy": 0.75, "format_compliance": 0.85, "summary": "..."}
```

一致性保障：通过 SOUL.md 的详细锚点描述 + few-shot 示例（暖机阶段积累）。不做额外的校准机制。

**(c) RunSpec 影响 rework 阈值，不影响评分标准。**

评分标准固定（0-1 量表的锚点不变）。RunSpec.depth 影响的是"什么分数触发 rework"：
- `depth=brief`：coverage >= 0.5, depth >= 0.4 即通过
- `depth=standard`：coverage >= 0.6, depth >= 0.6 即通过
- `depth=thorough`：coverage >= 0.7, depth >= 0.7 即通过

这样，brief 任务允许浅层分析通过（因为用户明确要求简短），但评分仍然如实记录（不因 depth=brief 而给高分）。Playbook 中记录的 quality_score 是真实评分，不是相对于 RunSpec 的"满意度"。

**(d) 靠用户反馈间接校准，不做"review 的 review"。**

理由：
- "review 的 review"需要另一个 LLM 评审 review 的评分——成本翻倍，且两个 LLM 评审的标准可能同样漂移
- 用户反馈是唯一的真实信号（Q7.2(c)）
- witness routine 监控 review_score 与 user_feedback 的相关性（Q9.5(b)），发现漂移时调整阈值

### Q7.2 用户反馈的收集与使用

Q4.2 中 Playbook 记录 `user_feedback`（选择题结构，可空）。已确认：Portal 主动弹出反馈选择界面，用户可直接关掉不回答。不是打分（1-5），是做选择题。

**问题：**
(a) 选择题的具体设计：有哪些选项？单选还是多选？（如单选："满意 / 基本可用但需要修改 / 不符合预期 / 完全不对"？或多选标签式："内容准确 / 格式规范 / 深度不够 / 遗漏关键信息 / ..."？）选项设计决定了 Playbook 能从反馈中学到什么。
(b) 用户不回答的情况（大概率常态）：Playbook 中 `user_feedback=null` 的记录如何处理？只靠 review agent 评分？null 记录在 Q4.2(b) 的 quality_bonus 中如何计算？
(c) 用户反馈与 review agent 评分严重不一致时（如 review 打 0.9 但用户选了"完全不对"），系统如何解读？以用户为准？还是需要分析原因（可能用户对质量的定义与 review 不同）？
(d) 反馈的粒度：用户对整个 run 做反馈选择，还是可以对每个步骤分别反馈？run 级反馈在 Playbook 中如何与步骤级产出关联（rework 定位需要步骤级信息）？
(e) 追评场景：用户当时关掉了反馈弹窗，后来想追评——追评入口在哪？Portal 的历史任务列表中？追评是否有时间窗口限制（与 Q6.1b archive 追评数据保留相关）？

**提议结论（待用户确认）：**

**(a) 多选标签式 + 一个总体选项。**

反馈界面设计：

```
总体感受（单选）：
  ○ 满意   ○ 基本可用   ○ 不太满意   ○ 完全不对

如果不满意，哪些方面？（多选，仅在总体 != 满意时显示）：
  □ 内容不准确      □ 深度不够
  □ 遗漏关键信息    □ 格式不规范
  □ 不符合我的需求  □ 其他
```

设计原则：
- 总体单选：快速操作，1 秒完成（满意的用户只点一下就走）
- 细项多选：只在不满意时展开，帮助系统定位问题维度
- 不设开放式文本框（增加用户负担，且 LLM 解析不可靠）

Playbook 存储格式：`{"overall": "satisfactory", "issues": []}` 或 `{"overall": "unsatisfactory", "issues": ["depth_insufficient", "missing_info"]}`

**(b) user_feedback=null → quality_bonus=0（中性）。**

- null 记录在 Q4.2(b) 的检索排序中 quality_bonus = 0（不加分不减分）
- 只靠 review agent 评分决定经验的"质量信号"
- 这是合理的——大多数 run 不会有 user_feedback，系统主要依赖 review 评分运转
- user_feedback 是锦上添花的校准信号，不是必需的

**(c) review/用户冲突 = 诊断事件，不是覆盖事件。** [⚠️ 已修正：原方案"以用户为准"过于简单]

当 review_score 与 user_feedback 严重不一致时（如 review 0.9 + 用户"完全不对"）：

1. Playbook 中两个信号**原样保留**，不互相覆盖。冲突条目标记 `review_user_conflict: true`
2. quality_bonus 在冲突时 = 0（中性），不让任何一方单方面影响检索排序
3. **witness 用 LLM 分析冲突原因**（输入：review 各维度评分 + 用户反馈细项 + RunSpec + 任务上下文），判断走哪个纠正通道：
   - review 评分维度没覆盖用户真正在意的东西 → 进化 review SOUL.md（Q9.2 通道）
   - Dialog 阶段没捕获真实意图 → 反馈写入 Playbook，改进 Dialog 追问策略
   - 某维度阈值设置不合理 → 调整该维度的 rework 触发阈值
   - 偶发无模式 → 不做调整
   - 以上仅为可能的输出示例，不是 if-else 规则

原则：**用户不一定比 review 更专业，review 也不一定比用户更准确。冲突本身是最有价值的信号，诊断交给 LLM，纠正通道是固定的，选哪条路是自适应的。** 与 Q3.2(d) 运行时复杂度修正同一设计模式。

**(d) run 级反馈，不做步骤级。**

- 用户对整个 run 做反馈（一个 outcome 作为整体评价）
- 原因：用户不了解步骤分解（系统语言隔离），让用户对"collect 步骤"做反馈没有意义
- rework 定位不依赖用户反馈——review agent 在 workflow 内输出结构化评分，不达标时基于评分维度追溯到源步骤触发 rework（S7-B: delivery 无 quality gate），不需要用户指出哪个步骤有问题
- user_feedback 的细项（"深度不够"、"遗漏信息"）可以与 review 的维度评分（coverage、depth）关联——witness 分析时做这个映射

**(e) 追评在 Portal 历史任务列表中。**

- 历史任务列表中每条 run 旁边有"反馈"按钮
- 已做过反馈的显示反馈摘要（可修改）
- 未做过反馈的显示"添加反馈"
- 追评时间窗口 = archive 保留时间（Q6.5(c)）——archive 清理后，run 的详细信息不可追溯，但反馈仍可做（只是缺少详细上下文）
- 实际上追评无时间限制（feedback 写入 Playbook，不依赖 archive 存在），但超过 archive 保留期后 Portal 无法展示步骤级详情

### Q7.3 学习循环的完整链路

Q4.2-Q4.3 设计了 Playbook 记录和衰减。但 Fabric 三组件的学习循环还不完整。

**问题：**
(a) 一个 run 完成后，哪些信息写入 Fabric 的哪个组件？当前分布是否合理？
   - Memory：认知类信息（"用户 X 偏好 Y 格式"、"数据源 Z 质量不好"）—— 来自 learn routine
   - Playbook：经验类信息（plan 结构 + 效果 + 参数）—— 来自 record routine
   - Compass：偏好类信息（评分趋势、预算消耗趋势）—— 来自 witness routine
(b) learn routine（Q2.6 已确定由 AgentPoolManager 触发）从池实例 workspace 提取认知——具体提取什么？agent memory 中的哪些内容算"有价值认知"？提取逻辑是 LLM 判断还是规则匹配？
(c) witness routine 的分析对象是什么？分析 Playbook 中的最近 N 条记录发现趋势？分析频率？产出什么（调整建议写入 Playbook？直接修改 Compass 偏好？）？
(d) distill routine 和 learn routine 的区别是什么？当前 routines 列表中两者都存在，但职责似乎重叠（都与"从经验中提取知识"相关）。

**提议结论（待用户确认）：**

**(a) 分布合理，确认如下：**

| Fabric 组件 | 写入内容 | 写入时机 | 写入者 |
|-------------|---------|---------|--------|
| Memory | 认知（"源 X 质量差"、"任务 Y 的关键发现 Z"） | Run 结束时 | learn routine（AgentPoolManager 触发） |
| Playbook | 经验（RunSpec embedding + plan 结构 + quality + user_feedback + token_consumption） | Run 完成后立即 | record routine（Nerve `run_completed` 事件触发） |
| Compass | 全局偏好统计（default_depth/format/language 的趋势） | 定期批量 | witness routine |

三者职责清晰不重叠：Memory = 知识，Playbook = 经验，Compass = 偏好统计。

**(b) learn 提取逻辑——LLM 判断 + 结构化规则。**

learn routine 从池实例 workspace 提取认知的具体内容：

1. **结构化提取（规则）**：
   - agent 执行过程中发现的数据源质量问题（如某个 URL 返回 404、某个 API 超时）
   - skill 使用成功/失败记录

2. **语义提取（LLM 判断）**：
   - 将 agent memory 文件（workspace/memory/ 下的内容）交给 LLM
   - prompt："从以下 agent 执行记忆中，提取对未来任务有价值的认知。只提取可泛化的知识，不提取任务专有的细节。"
   - LLM 输出结构化的认知条目（每条含 content + tags）
   - 新条目按 Q1.2 规则处理（与已有 Memory 矛盾则覆盖）

LLM 调用使用 analyze agent 的模型（DeepSeek R1），消耗纳入 learn routine 的 token 预算。

**(c) witness routine 的分析对象和产出：**

- **分析对象**：Playbook 中最近 20 条经验记录
- **分析频率**：adaptive 调度（Q2.8），系统活跃时每 2 小时，不活跃时每 12 小时
- **分析内容**：
  1. quality_score 趋势（上升/下降/稳定）
  2. rework 率（最近 20 条中 rework_history 非空的比例）
  3. user_feedback 分布（正面/负面/null 的比例）
  4. 各 agent 类型的表现差异
  5. token 消耗趋势
- **产出**：
  - 写入 Compass 偏好：如果统计显示 depth=thorough 占比 > 70% → 更新 `default_depth=thorough`
  - 写入 `state/system_health.json`：整体健康指标（Q9.5(c)）
  - 异常信号写入 spine_log（如 quality_score 骤降 > 15%）→ pulse 检测

**(d) distill 和 learn 职责不同，不重叠。**

| routine | 输入 | 操作 | 输出 |
|---------|------|------|------|
| **learn** | 池实例 workspace（agent 执行记忆） | 从执行记忆中提取新认知 | Memory 新条目 |
| **distill** | Memory 全部条目 | Q1.1 的热度衰减 + 合并压缩 | Memory 条目减少/合并 |

learn = **生产**新知识（Run 结束时触发，不是定时 routine）
distill = **压缩**已有知识（定时 routine，如每天一次）

learn 让 Memory 增长，distill 让 Memory 保持健康（不超容量、去重、合并相似低分条目）。两者是互补关系。

### Q7.4 学习机制的冷启动（暖机设计）

Q4.2(d) 确定暖机有两个目标：校准 complexity 默认值表 + 填充 Playbook 初始经验库。

**问题：**
(a) 暖机任务集的设计原则：需要覆盖哪些维度？（复杂度 × agent 类型 × 格式 × 语言 × 边界情况）具体需要多少条暖机任务？
(b) 暖机任务由谁提交？自动批量运行？还是需要用户参与（提供真实需求作为种子）？
(c) 暖机的成功标准是什么？Playbook 中有 N 条记录？complexity 默认值表的值稳定（连续 K 次暖机任务不再调整）？还是其他指标？
(d) 暖机阶段的 review agent 评分——没有用户反馈校准，review 自评可靠吗？暖机结果是否需要人工抽查？

**提议结论（待用户确认）：**

**(a) 暖机任务集设计——约 25 条任务。**

覆盖维度矩阵：

| 维度 | 值域 | 覆盖要求 |
|------|------|---------|
| complexity | pulse / thread / campaign | 每种至少 5 条 |
| agent 类型 | collect / analyze / build / review / render / apply | 每种至少被 3 条任务使用 |
| format | pdf / markdown / code | 每种至少 3 条 |
| language | zh / en / bilingual | 每种至少 3 条 |
| 边界情况 | 接近步数上限、需要 rework、bilingual 格式规范差异 | 至少 5 条 |

总计约 25 条任务（维度交叉覆盖，不是笛卡尔积）。具体任务内容在暖机阶段设计，涵盖真实场景（如研究报告、代码开发、新闻摘要、文档撰写等）。

**(b) 自动批量运行，不需要用户参与。**

暖机任务的 RunSpec + plan 由系统预设（暖机脚本提供），`metadata.source = "warmup"`。批量提交到 Dispatch，自动执行。用户不需要提供种子——暖机的目的是校准系统参数和积累初始经验，不需要真实用户需求。

暖机脚本：`scripts/warmup.py`，包含 25 条预设任务的 RunSpec + objective。执行方式：`python scripts/warmup.py`（调用 `POST /submit`）。

**(c) 暖机成功标准——三个条件同时满足：**

1. **Playbook 填充**：至少 20 条成功完成的经验记录（pulse/thread/campaign 各至少 5 条）
2. **complexity 默认值稳定**：最后 5 条暖机任务的实际 timeout 和 concurrency 都在默认值范围内（无触发超时或超并发）
3. **全 agent 覆盖**：6 种 agent 类型都至少被成功调用过 3 次

如果 25 条任务执行完仍不满足，补充执行直到满足。标准检查由暖机脚本自动判断。

**(d) 暖机结果需要人工抽查。**

review agent 自评在无 user_feedback 校准时不完全可靠（review 和被审查对象用的是不同模型，但审查标准是否合适需要实际验证）。

暖机完成后：
- 系统自动将 5 条随机 outcome 的链接推送到 Telegram
- 用户抽查这 5 条的质量，如果满意 → 暖机通过；如果不满意 → 调整 review 的 SOUL.md prompt 或质量阈值后重跑
- 抽查是一次性的（暖机阶段），正式运行后 user_feedback 接管校准

### Q7.5 Compass 偏好的演化

Q1.5 确定偏好带 confidence（基于样本量）。Q4.5(c) 确定 Compass 废弃 quality_profiles 表，保留 preferences key-value 存储。

**问题：**
(a) Compass preferences 具体存储哪些 key-value？全局偏好（require_bilingual=true）之外，还有哪些需要长期积累的偏好？
(b) 偏好的更新频率：每次 run 完成后立即更新？还是 witness routine 定期批量分析后更新？
(c) 偏好冲突：用户在不同场景下表现出矛盾的偏好（如对技术文档偏好简洁，对报告偏好详细），embedding 检索如何区分场景？还是 Compass 只存储全局偏好，场景化偏好交给 Playbook 经验？

**提议结论（待用户确认）：**

**(a) Compass 全局偏好清单：**

| key | 类型 | 含义 | 来源 |
|-----|------|------|------|
| `require_bilingual` | bool | 默认双语产出 | 用户显式设定 |
| `default_depth` | str | 默认深度（brief/standard/thorough） | witness 从历史 RunSpec 统计 |
| `default_format` | str | 默认格式（pdf/markdown/text） | witness 从历史 RunSpec 统计 |
| `default_language` | str | 默认语言（zh/en/bilingual） | witness 统计 |
| `pool_size_n` | int | 池实例数量 | Console 调整 |
| `provider_daily_limits` | json | 各 provider 每日 token 限额 | Console 调整 |
| `run_budget_ratio` | float | 单 run 预算上限比例（Q4.6(c)） | Console 调整 |

这些都是与具体任务内容无关的全局设定。场景化偏好（如"技术文档要简洁"）不放 Compass（见 (c)）。

**(b) witness routine 定期批量分析后更新。**

不在每次 run 完成后立即更新 Compass。原因：
- 单次 run 的结果是噪声（可能是异常任务），需要多次统计才有意义
- witness routine 的 adaptive 调度（Q2.8）已经保证了系统活跃时更新更频繁
- witness 每次运行时，分析最近 20 条 Playbook 记录，统计 depth/format/language 的分布，如果某个选项占比超过 70% → 更新 Compass 对应的 default 值

**(c) Compass 只存储全局偏好，场景化偏好交给 Playbook。**

用户"对技术文档偏好简洁，对报告偏好详细"——这是场景化偏好，Compass 的 key-value 结构无法表达"在 X 场景下偏好 Y"。

场景化偏好的自然载体是 Playbook 经验：
- Playbook 记录每次 run 的 RunSpec.depth + outcome_quality + user_feedback
- 下次相似任务（embedding 检索），自然获取到该场景下的历史 depth 选择和效果
- Dialog 阶段注入 Playbook 参考时，Router 看到"类似的技术文档任务历史上 depth=brief 效果最好"→ 自动设置 depth=brief

不在 Compass 中做场景化索引——那等于重新引入分类（按场景分类），违反理念 D。

### S7-A: awaiting_eval 窗口过期行为 ✅ 已决定

**决策**：自动转 completed + feedback_expired=true。
四个用途：Playbook 学习权重、反馈率统计、自进化信号、审计区分。

### S7-B: delivery 质量门控 vs review agent 审查 ✅ 已决定

**核心原则：质量 = workflow 的事，物流 = delivery 的事。零重叠。**

```
workflow phase（DAG 内部）
├── collect → analyze → render → review
│   review agent 负责一切质量判断：
│   - 内容质量（coverage, depth, coherence, accuracy）
│   - 格式合规（bilingual 齐全、排版规范、引用格式）
│   - 完整性（文件数、文件结构）
│   不过 → 触发 rework
│   通过 → workflow 完成
│
post-workflow phase（delivery）
├── 纯物流操作，零质量判断：
│   - 从 run_root 复制文件到 outcomes/
│   - 写 state/delivery_log.jsonl
│   - 更新 run 状态（→ awaiting_eval）
│   - 归档到 Drive
```

**delivery 不再有 quality gate、quality_score、structural_check**。这些概念全部归属 review agent。delivery 是纯粹的文件搬运 + 状态更新服务。

"万一文件损坏了呢？"——那是 workflow 的 bug，修 workflow，不加 delivery 检查。

### S7-C: review step 在 plan 中的角色 ✅ 已决定

- **review step** = workflow 内的最终质量关卡，DAG 最后一步，负责所有质量判断。不达标 → rework。
- **delivery** = workflow 完成后的自动后续动作。不判断、不评分、不检查。
两者零重叠：review = 判断（够好吗？），delivery = 执行（送到用户手里）。

---

## 阶段 8：目标管理（Track → Lane → Run）

### 前置：已确立的目标管理设计

- **Track 是按需引入的**：大多数 run 不属于任何 Track。Track 只在需要时才出现——campaign 也无法收敛的长期目标（Q3.4(a)），或用户主动选择长期管理。Track 不是默认的组织层级
- **Q3.4(a)**：Track 推进方式——每阶段完成后带成果和建议回到 Dialog，用户确认后推进下一阶段。系统不自主推进
- **Q4.8**：submit payload 含 `metadata.track_id` 和 `metadata.lane_id`；source 区分 `portal_dialog` / `lane_trigger` / `track_advance`
- **Q4.6(b)**：定时任务到期但预算不足 → 排队不跳过；不累积同一 chain 的多个待执行实例
- **Q5.5**：campaign milestone 间用 Temporal wait_condition + Signal 等待用户确认

---

### Q8.1 Track 的引入条件与生命周期

Track 只在需要时引入。大多数任务（pulse/thread/campaign）直接作为独立 run 执行，不需要 Track。

**问题：**
(a) Track 的创建条件：目前已知的是"campaign 也无法收敛时系统自动创建"（Q3.4(a)）。用户是否也可以主动将任务纳入 Track 管理（如"我要做一个跨季度的项目"）？如果可以，入口在哪？
(b) Track 的状态：active / paused / completed / abandoned？状态转换的触发条件？用户手动标记完成，还是系统判断目标达成自动完成？
(c) Track 的删除/归档：完成或废弃的 Track 是否可删除？其下各 run 的 outcome 已经在 outcomes/ 独立存在（零系统痕迹），Track 删除只影响系统内部的关联关系？
(d) Track 有 metadata 吗？（如目标描述、创建时间、进度）这些信息由谁维护？

**提议结论（待用户确认）：**

**(a) 两种创建方式：系统自动 + 用户主动。**

- **系统自动创建**：Q3.4(a) 已确定——campaign 也无法收敛时，Router 以自然语言向用户建议"分步推进"，用户确认后系统在内部创建 Track
- **用户主动创建**：Portal 侧边栏"长期目标"页面有"创建"按钮。用户描述长期目标 → Dialog 帮助细化 → 用户定义 Lane（各阶段）→ 创建 Track

用户主动创建时的用户语言："创建长期目标"。系统内部创建 Track + Lane。

**(b) 四种状态，用户手动标记完成。**

| 状态 | 含义 | 转换条件 |
|------|------|---------|
| `active` | 正在推进 | 创建时默认状态 |
| `paused` | 暂停 | 用户手动暂停；或所有 Lane 都等待用户确认 |
| `completed` | 完成 | **用户手动标记**。系统不自动判断"目标达成"——长期目标的完成标准是主观的 |
| `abandoned` | 废弃 | 用户手动标记。与 completed 的区别：abandoned 意味着目标未达成但不再追求 |

不自动完成的原因：Track 的 objective 是自然语言描述的宏观目标（如"完成跨季度项目"），系统无法可靠判断何时"达成"。只有用户知道目标是否满足。

**(c) Track 删除只影响系统内部关联。**

- completed/abandoned 的 Track 可删除
- 删除操作：从 `state/tracks.json` 移除 Track 和关联 Lane 记录
- 关联 Run 的 `metadata.track_id` 保留（不改 Playbook 已记录的经验，但不再有 Track 实体可跳转）
- outcomes/ 中的文件不受影响（零系统痕迹原则——outcome 从不依赖 Track 存在）

**(d) Track 有 metadata。**

```python
@dataclass
class Track:
    track_id: str           # UUID
    objective: str          # 长期目标描述（用户原文）
    status: str             # active / paused / completed / abandoned
    created_utc: str
    updated_utc: str
    lanes: list[str]        # lane_id 列表
    progress_notes: list[dict]  # [{date, note}] — 每个阶段完成后 Router 生成的进度摘要
```

`progress_notes` 由系统维护（每个 Lane 的 Run 完成后，Router 生成一句话进度摘要追加）。用户在 Portal 的 Track 详情页可以看到这些进度摘要。

### Q8.2 Lane 与触发机制

Lane 是执行序列。在有 Track 的场景下，Lane 归属于 Track；周期任务（cron）也使用 Lane 但不一定需要 Track。

**问题：**
(a) Lane 的 trigger 类型有哪些？当前理解：`manual`（用户手动触发）、`cron`（定时触发）、`on_complete`（前一个 Run 完成后触发）。是否还有其他类型？
(b) cron Lane 是否必须归属于 Track？一个简单的周期任务（如"每周一生成新闻摘要"）看起来不需要 Track。如果 Lane 可以独立于 Track 存在，那 Lane 就不仅是"Track 内的执行序列"，而是更通用的调度单元？
(c) cron Lane 的 RunSpec 从哪来？用户创建 cron 任务时需要提供完整的 RunSpec + plan？还是只提供 objective，每次触发时由 Dialog 自动生成 plan？
(d) on_complete Lane：前一个 Run 完成后自动触发下一个 Run。这与 campaign 的 milestone 机制（Q5.5）有什么区别？campaign 是 workflow 内部的阶段衔接，on_complete Lane 是 workflow 之间的串联——两者是否有重叠？
(e) Lane 的并发：同一 Track 下的多条 Lane 可以同时运行吗？不同 Lane 的 Run 之间是否有数据依赖？

**提议结论（待用户确认）：**

**(a) 统一事件订阅机制，不枚举 trigger 类型。** [⚠️ 已修正：原方案枚举三种类型过于僵硬]

manual、cron、on_complete 本质都是事件。Lane 的触发方式统一为**订阅 Nerve 事件**：

```yaml
trigger:
  event: "run_completed"       # 订阅的事件名
  filter: {lane_id: "self"}    # 可选，事件 payload 过滤条件
  schedule: "0 9 * * 1"        # 可选，cron 表达式（scheduler 按时发出事件）
```

原有三种场景的表达：
- manual → 订阅 `lane_manual_trigger` 事件
- cron → scheduler 按 cron 表达式发出 `cron_fired` 事件
- on_complete → 订阅 `run_completed` 事件

**外部事件通过适配器（adapter）归一化为 Nerve 事件**。daemon API 提供事件注入端点：
```
POST /events/ingest
{"event": "page_changed", "payload": {...}, "source": "crawler_adapter"}
```

适配器是极简独立脚本/服务，监听外部信号源（邮件、爬虫、webhook 等），有变化就调注入端点。跟 watchdog 同一思路——极简、独立、几乎不会挂。Telegram adapter 已是这个模式的实例。

这样任何内部或外部事件都能触发 Lane，未来加新触发方式只需加适配器，不改 Lane 代码。适配器本身可以像 skill 一样被自进化 Track 管理。

**当前只建立 adapter 机制和统一触发接口，不实现其他外部适配器。**

**(b) cron Lane 可以独立于 Track 存在。**

Lane 是更通用的调度单元，不仅仅是"Track 内的执行序列"。两种用法：
- **独立 Lane**（`track_id=null`）：简单的周期任务。cron Lane 独立存在，不归属任何 Track
- **Track 内 Lane**（`track_id=xxx`）：长期目标下的执行序列，有 Track 的目标和进度上下文

数据模型上，Lane 有可选的 `track_id` 字段。独立 Lane 的 `track_id=null`。

这意味着 Lane 替代了当前代码中的 "chain" 概念。当前的 `chains.json` / `chain_id` 重命名为 `lanes.json` / `lane_id`。

**(c) cron Lane 存储 RunSpec 模板，每次触发时生成 plan。**

用户创建 cron 任务时的流程：
1. 在 Dialog 中描述需求，系统生成 plan 预览
2. 用户选择"定期执行" + 设置频率
3. 系统保存：RunSpec 模板 + cron 表达式 → Lane 记录

每次 cron 触发时：
1. 读取 Lane 的 RunSpec 模板
2. 由 Dialog 的 plan 生成逻辑自动生成 plan（不经过用户对话，直接用模板中的 objective + 最新 Playbook 经验）
3. `metadata.source = "cron_trigger"`，走 Dispatch enrich → Temporal workflow

不缓存上次的 plan——每次重新生成确保 plan 能利用最新的 Playbook 经验和 skill 集合。

**(d) on_complete Lane 与 campaign milestone 不重叠。**

| 维度 | campaign milestone | on_complete Lane |
|------|-------------------|-----------------|
| 层级 | 同一 Temporal workflow 内部 | 不同 Temporal workflow 之间 |
| 上下文共享 | workflow 内部状态连续 | 独立 run，通过 run_root 产出传递 |
| 用户确认 | 每个 milestone 需要确认（Q5.5） | 自动触发，不需要用户确认 |
| 典型场景 | 大型单一任务的多阶段执行 | Track 内多个独立任务的顺序编排 |

两者服务不同场景，不存在重叠。campaign 是"一个任务太大分阶段做"，on_complete Lane 是"多个不同任务有先后关系"。

**(e) 同一 Track 下的 Lane 可以并行运行。**

多条 Lane 默认可并行。数据依赖通过 Q8.5(c) 的 `depends_on_lane` 显式声明。无依赖声明的 Lane 独立运行，各自分配独立的池实例，互不干扰。

### Q8.3 Run 的组织与查询

大多数 run 是独立的（不属于任何 Track）。只有被 Track 管理的 run 才有 track_id/lane 归属。

**问题：**
(a) Run 的唯一标识：当前 run_id 是 UUID。独立 run 和 Track 下的 run 用同一种标识？还是 Track 下的 run 有额外的层级信息？
(b) Run 历史查询：用户在 Portal 上如何查看历史 run？独立 run 按时间线排列？Track 下的 run 按 Track 分组？两种视图并存？
(c) Run 之间的关系：rework 产生的重试是同一 run_id 的不同 attempt？还是独立的 run_id 但有 parent_run_id 链接？
(d) Portal 的"任务"列表主要展示独立 run（因为大多数任务不需要 Track）。Track 作为一个特殊的"长期目标"入口，在 Portal 哪里展示？是否需要一个独立的 Track 视图？

**提议结论（待用户确认）：**

**(a) 统一 UUID 标识，metadata 区分归属。**

所有 run 使用同一种 UUID 标识。Track 下的 run 通过 `metadata.track_id` 和 `metadata.lane_id` 关联到 Track/Lane，但 run_id 格式不变。原因：统一标识简化了所有读写 run 的代码路径（Temporal workflow、delivery、Playbook 记录），不需要根据是否属于 Track 走不同逻辑。

**(b) 两种视图并存。**

Portal 历史任务查看：
- **默认视图——时间线**：所有 run 按完成时间倒序排列，不区分独立 run 和 Track 下的 run。Track 下的 run 显示 Track 标签（可点击跳转到 Track 详情）
- **Track 视图**：点击 Track 入口（见 (d)）后，展示该 Track 下所有 Lane 和 Run 的树状结构

用户语言中：时间线视图 = "历史任务"；Track 视图 = "长期目标详情"。

**(c) rework 是同一 run_id 的不同 attempt。**

rework 不生成新 run_id。原因：
- rework 是同一个用户需求的再次尝试，不是新任务
- 用户视角只看到一个任务（running → 最终 completed 或 failed），不关心内部重试了几次
- run_root 下记录 `attempt` 序号（`run_root/attempts/{attempt_n}/`），每次 rework 的步骤产出归入新 attempt
- Playbook 经验记录中的 `rework_history` 字段记录各 attempt 的概要

**(d) Portal 侧边栏有"长期目标"入口。**

Portal 左侧导航：
- **对话**（默认页面）—— Dialog compose 区域
- **历史任务** —— 时间线视图
- **定期任务** —— cron Lane 列表（Q8.4）
- **长期目标** —— Track 列表（仅在有 active Track 时显示）

"长期目标"页面展示所有 Track：active 的在上方，paused/completed 的折叠在下方。点击某个 Track 进入详情页（展示 Lane 和 Run 的树状结构 + 推进建议卡片 Q8.5(a)）。

### Q8.4 周期任务的用户体验

用户创建一个定时任务（如"每周一早上生成本周技术新闻摘要"）。周期任务使用 cron Lane，但不一定需要 Track。

**问题：**
(a) 创建入口：用户在 Portal 的什么位置创建周期任务？是一个独立的"定时任务"页面？还是在提交任务时勾选"定期执行"？
(b) 周期任务的编辑：用户想修改定时任务的 objective 或频率，如何操作？修改后已排队的 Run 是否受影响？
(c) 周期任务的暂停与恢复：用户临时不想执行某个定时任务（如出差一周），暂停后恢复时是否补执行错过的周期？
(d) 周期任务的产出累积：每次执行产出的 outcome 在 outcomes/ 中是独立的目录（各自有时间戳）。用户能看到同一周期任务的历史产出列表吗？能对比（如"本周 vs 上周"）吗？

**提议结论（待用户确认）：**

**(a) 在提交任务时选择"定期执行"。**

不做独立的"定时任务"页面。用户的心智模型是"我想让这个任务定期执行"，不是"我要创建一个定时器"。

流程：
1. 用户在 Portal Dialog 完成对话，看到 plan 预览
2. plan 预览下方有选项："执行一次"（默认）/ "定期执行"
3. 选择"定期执行"→ 展开 cron 设置（频率选择器：每天/每周/每月/自定义 cron）
4. 用户确认 → 创建 cron Lane + 立即执行第一次

用户语言中称为"定期执行"，系统内部是 `cron Lane`。

**(b) 编辑通过 Portal 的"我的定期任务"列表。**

- Portal 侧边栏有"定期任务"入口，展示所有 active 的 cron Lane
- 点击某条 → 可修改 objective（触发 Dialog 重新生成 plan）或频率
- 修改后，已排队但未开始的 Run 使用新配置；正在执行的 Run 不受影响
- 每次修改生成新版本的 RunSpec 模板，下次 cron 触发时使用最新版本

**(c) 暂停后不补执行。**

- 用户暂停 cron Lane → 暂停期间的 cron 触发全部跳过
- 恢复后从下一个 cron 时间点开始执行
- 不补执行原因：周期任务通常是时效性的（如"本周新闻摘要"），补执行过去的周期没有意义
- 跳过的周期记录在 Lane 历史中（`skipped_reason: lane_paused`）

**(d) 同一 cron Lane 的历史产出列表——Portal 支持。**

- Portal 的"定期任务"详情页展示该 Lane 的所有历史 Run 和 outcome
- 每条显示执行时间 + outcome 标题 + review 评分摘要
- outcomes/ 中的独立目录通过 `state/delivery_log.jsonl` 中的 `lane_id` 字段关联
- 对比功能：初期不做。"本周 vs 上周"的对比需要内容级 diff，复杂度高且使用频率低。如果用户需要，可以手动打开两个 outcome 对比

### Q8.5 Track 推进的用户交互

Q3.4(a) 确定系统不自主推进 Track，每阶段需要用户确认。Track 是少数场景，但一旦引入，推进交互很重要。

**问题：**
(a) 系统向用户展示"下一阶段建议"的形式：在 Portal 中弹出一个类似 Dialog 的对话？还是在 Track 详情页中显示一个"建议的下一步"卡片？
(b) 用户长期不响应 Track 推进建议（如一个 Track 暂停了 3 个月），系统如何处理？定期提醒？沉默等待？自动归档？
(c) Track 的多条 Lane 之间有逻辑先后关系时（如 Lane A 是需求分析，Lane B 是架构设计，B 依赖 A 的产出），这个依赖由谁定义？用户手动设定？还是系统根据 objective 自动推断？

**提议结论（待用户确认）：**

**(a) Track 详情页中显示"建议的下一步"卡片。**

不弹出 Dialog 对话（那是新任务的入口）。Track 推进是在已有上下文中继续，UI 形式应体现这种连续性：
- Track 详情页显示已完成阶段的摘要 + "建议的下一步"卡片
- 卡片包含：Router 基于已完成阶段产出生成的下一步建议（自然语言描述）
- 用户可以：点击"开始"（进入 Dialog 补充细节并生成 plan）、点击"调整方向"（在卡片下方输入修改意见）、不操作（Track 保持 paused）
- 这与 Q5.5(c) 的 campaign milestone 间干预机制一致

**(b) 定期 Telegram 提醒，不自动归档。**

- Track paused 超过 7 天 → 首次 Telegram 提醒（"你有一个长期目标暂停中：{objective}。继续推进？"）
- 之后每 30 天提醒一次（频率递减，不骚扰）
- 不自动归档——用户可能只是暂时搁置。自动归档可能导致用户丢失长期目标的上下文
- 用户想归档时手动标记 abandoned（Portal Track 列表中的操作按钮）

**(c) Lane 依赖由用户在创建 Track 时手动设定。**

系统不自动推断 Lane 间依赖。原因：
- Track 是少数场景（大多数任务不需要 Track），引入复杂的自动依赖推断不值得
- Lane 的 objective 可能很抽象（"需求分析"），自动推断准确率不高
- 用户创建 Track 时对各阶段的先后关系有清晰认知

实现：Track 创建时，用户为每条 Lane 设置 `depends_on_lane: list[lane_id]`。Lane 的 trigger 为 `on_complete` 且 depends_on_lane 的所有 Lane 都完成时，才触发该 Lane。无依赖的 Lane 可并行运行。

### S8-A: 暖机需要 Track-Lane ✅ 已决定

暖机自己就要做第一个 Track。暖机结束后系统正式开启，同时自动开启一个常驻 Track：系统的自进化。

**QA 1-5 中需要在暖机阶段设置/校准的完整参数清单**：

| 层 | 参数 | 初始值 |
|----|------|--------|
| Fabric (Q1) | Memory 容量上限、衰减阈值、Compass confidence 阈值、require_bilingual、default_depth/format/language | 待暖机标定 |
| Spine (Q2) | Routine 执行超时、连续失败阈值、Pulse/Watchdog 频率、自适应调度权重 | 需暖机验证 |
| Dialog (Q3) | complexity 步数预算、OpenClaw 循环检测阈值、Agent 上下文窗口/步超时、Subagent 并发数 | 需暖机验证 |
| Dispatch (Q4) | pool_size_n (24→145实例)、模型路由映射、并发/超时/rework 表、质量门控阈值、Provider 日 token 限额 | 需暖机观察 |
| 执行 (Q5) | eval_window_hours (2h)、Playbook 检索公式权重 | 需暖机验证 |

**常驻自进化 Track**：
- **Lane A：能力优化**——skill 持续发现和优化、模型策略调优、质量阈值校准、memory/playbook 优化、agent prompt 演进
- **Lane B：机制迭代**——daemon 自己研究前沿机制 → 产出改进代码 → push 到 GitHub 独立仓库 `daemon-evolution` → Claude Code 审核 cherry-pick

**机制迭代关键设计**：
- 安全边界：daemon 不能直接改自己的代码。提出改进 → push → Claude Code 审核
- 触发方式：每周触发。witness 发现的问题可作为当周改进的优先任务
- 改进范围：全部模块
- 仓库结构：branch + commit 模式（非 PR），每个 commit = 一个改进提案 + PROPOSAL.md

### S8-B: chain_id 废弃 ✅ 已决定

chain 在当前代码里已经不存在。它是旧设计阶段的中间概念，在代码重构中被移除但文档未清理。Lane 是全新机制。文档中残留的 `chain_id` 在全系统重命名时清理。

---

## 阶段 9：自我进化（Skill Discovery → Benchmark → Deploy）

### 前置：已确立的自我进化设计

- **Q5.7(c)**：skill_registry.json 由 Claude Code 审批维护（非人类审批）；Skill 使用效果追踪 + 淘汰信号
- **Q2.11**：自动排障机制——Claude Code 可修改代码并通过 git commit 记录
- **Q1.11**：角色模板 `templates/<role>/` 存放 SOUL.md/TOOLS.md，allocation 时复制到池实例 agentDir。模板变更在下次 allocation 生效
- **Q4.4(b)**：模型选择通过 Playbook 经验学习实现，不通过规则
- **Q3.2(b)**：复杂度判断有学习闭环（LLM 初始判断 → 执行验证 → Playbook 记录 → Spine 分析 → 反馈）

---

### Q9.1 Skill 发现与评估

Q5.7(c) 定义了接口约束：系统发现和提议新 skill，Claude Code 负责审批安装（非人类审批）。

**问题：**
(a) 系统如何发现新的 skill？主动搜索（定期搜索 openclaw skill 市场/社区）？被动发现（执行中 agent 遇到能力缺口时标记"需要 XX 类 skill"）？两者都需要？
(b) 发现后如何评估 skill 的价值？需要一个 benchmark 流程吗？（下载 skill → 在沙盒中运行测试任务 → 与现有 skill 对比效果）Claude Code 审批时需要哪些评估数据？
(c) skill 来源的安全性：从社区/市场获取的 skill 是否需要安全审计？Claude Code 审批时是否做静态分析/沙盒测试？
(d) skill 与 agent 模板的关系：Claude Code 审批安装新 skill 后，`templates/<role>/TOOLS.md` 是否由 Claude Code 自动更新？

**提议结论（待用户确认）：**

**(a) 主动搜索 + 被动发现，两者都需要。**

- **主动搜索**：定期（每周，由 witness routine 或专门的 Spine 子任务触发）搜索 openclaw 的 skill 仓库/社区。搜索关键词来源：当前 agent_capabilities.json 中的 capability_tags（寻找增强现有能力的 skill）+ Playbook 中频繁出现的 rework 原因（寻找能解决已知问题的 skill）
- **被动发现**：agent 执行步骤时如果明确报告"缺少 XX 能力"（如 tool not found），record routine 记录此缺口。witness 分析积累的缺口列表，作为主动搜索的优先方向

**(b) Benchmark 流程必须有。**

Skill benchmark（V2 §21 已有要求）：
1. **下载 skill 到临时目录**（不直接安装到 agent 模板）
2. **静态审计**（见 (c)）
3. **沙盒测试**：在一个专用的测试池实例上运行 3-5 个预设的 benchmark 任务，覆盖 skill 声称的能力范围
4. **效果对比**：如果替换现有 skill，对比新旧 skill 在同一 benchmark 任务上的 review 评分
5. **Claude Code 审批数据**：静态审计报告 + benchmark 任务的 review 评分 + 对比结果 + skill 来源信誉

Claude Code 据此决定：安装（注册到 skill_registry.json + 更新模板）/ 拒绝（记录原因）/ 标记待人工复查。

**(c) 安全审计必须做。**

Claude Code 审批时执行：
- **静态分析**：检查 skill 代码是否包含危险操作（网络请求到非白名单地址、文件系统写入到非 workspace 路径、执行任意 shell 命令）
- **依赖审计**：检查 skill 的依赖项是否有已知安全漏洞
- **沙盒测试**：benchmark 任务在受限环境中运行（无外网访问、只能写入 workspace）
- **来源信誉**：优先选择官方维护的 skill，社区 skill 需要更严格审查

审计不通过 = 直接拒绝，不进入 benchmark。

**(d) Claude Code 自动更新 TOOLS.md。**

审批安装流程：
1. 注册到 `config/skill_registry.json`（skill_id、compatible_agents、capability_tags、status=active）
2. 更新对应 `templates/<role>/TOOLS.md`，添加新 skill 的使用说明
3. git commit（`[evolution] install skill: <skill_id> for <role>`）
4. Telegram 通知用户
5. 下次 allocation 时新模板生效

淘汰流程（Q5.7(c) 已定义信号）类似：从 skill_registry 标记 deprecated → 从 TOOLS.md 移除 → git commit → 通知。

### Q9.2 模板进化

templates/<role>/ 中的 SOUL.md 和 TOOLS.md 决定了 agent 的"人格"和能力。

**问题：**
(a) 模板是否会随系统运行自动进化？比如 learn routine 发现 collect agent 在某类任务中效果不佳，是否可以自动调整 SOUL.md 中的 system prompt？
(b) 如果允许模板自动进化，如何保证进化方向正确？（一次错误的 SOUL.md 修改可能影响所有后续使用该角色的 Run）需要 A/B 测试吗？还是靠 state/ git 回滚兜底？
(c) 模板进化与 Q2.11 自动排障的关系：排障是"修复 bug"，模板进化是"提升能力"——两者使用同一个 Claude Code 通道吗？还是需要区分？
(d) SOUL.md 和 TOOLS.md 之外，模板是否需要包含其他文件？（如 agent 特有的配置文件、参考文档、示例输出）

**提议结论（待用户确认）：**

**(a) 允许模板自动进化，但保守且有观察期。**

learn routine 和 witness routine 可以发现 agent 表现问题（如 collect agent 在特定类型任务中持续产出低质量结果）。发现后：
1. witness 产出分析报告（哪个 agent、什么类型任务、具体问题）
2. 报告提交给 Claude Code 进化通道
3. Claude Code 修改 `templates/<role>/SOUL.md`（调整 system prompt）
4. 修改通过 state/ git commit 记录（`[evolution] adjust collect SOUL.md`）
5. 下次 allocation 时新模板自动生效（Q1.11 已确认）

**(b) state/ git 回滚兜底，不做 A/B 测试。**

模板 A/B 测试需要同一角色同时维护两个版本的 SOUL.md，池实例分配时随机选版本——这增加了大量实现复杂度，且样本量小（daemon 每天任务量有限）导致统计结论不可靠。

实际保障：
- state/ git 有完整历史（Q1.9），任何模板修改可精确回滚
- Q9.4(b) 的效果观察期：修改后 N 次 run 的效果被 witness 跟踪，显著下降则自动回滚
- 模板修改通常是微调（增加/调整 prompt 中的一两句话），不是重写——影响面可控

**(c) 同一 Claude Code 通道，commit 前缀区分。**

排障和进化都通过 Claude Code CLI 执行。区别：
- 排障 commit：`[repair] fix spine pulse routine timeout`
- 进化 commit：`[evolution] adjust collect SOUL.md for better coverage`
- 排障是被动触发（故障发生）、紧急的
- 进化是主动触发（witness 分析）、非紧急的
- 两者不应同时运行——进化任务在系统无排障需求时才执行

**(d) 模板可以包含参考文档。**

`templates/<role>/` 目录结构：
- `SOUL.md`（必须）：agent 人格和行为规范
- `TOOLS.md`（必须）：可用工具和 skill 说明
- `REFERENCES/`（可选）：参考文档（如 render agent 的格式规范模板、build agent 的代码风格指南）
- 不包含示例输出（示例输出来自 Playbook 经验，allocation 时动态注入，不是模板的一部分）

REFERENCES/ 中的文件也在 allocation 时复制到池实例 agentDir，return 时清理。

### Q9.3 模型策略进化

Q4.4 确定 agent_model_map 为主、Playbook 经验为辅。但模型本身会更新迭代。

**问题：**
(a) 新模型上线时（如 MiniMax 发布 M3），系统如何知道？人工更新 model_registry.json？还是系统有能力自动检测 provider 的新模型？
(b) 新模型的引入流程：直接替换旧模型（风险高）？还是先作为实验模型在少量任务上试用，效果好再全面切换？如果需要试用，与 Q4.3(b) "不需要选拔机制" 的结论是否矛盾？
(c) model_policy.json 和 model_registry.json 的更新：由 Claude Code 自主修改（同 skill 审批模式）？还是这类核心配置需要更高的审批门槛？

**提议结论（待用户确认）：**

**(a) 人工更新为主，自动检测为辅。**

大多数 provider 没有标准化的"新模型上线通知 API"。实际路径：
- **主要方式**：Claude Code 在定期自我审视（Q9.4(d)）时，搜索各 provider 的最新模型公告/changelog，发现新模型后提议更新 model_registry.json
- **辅助方式**：如果某 provider 有 models list API（如 OpenAI 兼容接口的 `/v1/models`），可定期查询对比
- 新模型发现后不自动引入，走 (b) 的流程

**(b) 渐进式引入，不与 Q4.3 矛盾。**

Q4.3 废弃的是"同一场景下两个策略的持续 A/B 竞争"。新模型引入是一次性的"迁移决策"，不是持续选拔。

引入流程：
1. Claude Code 在 model_registry.json 中注册新模型（status=experimental）
2. 在 model_policy.json 中为目标 agent 类型添加 `experimental_model` 字段
3. 接下来的 5-10 个该 agent 类型的 run，随机 50% 使用新模型
4. witness routine 对比新旧模型的 quality_score 和 user_feedback
5. 新模型效果 >= 旧模型 → Claude Code 将其提升为默认 → Telegram 通知用户
6. 新模型效果差 → 移除 experimental 标记 → 保持旧模型

这是一次性决策流程（试用 → 决定 → 结束），不是持续的 A/B 竞争。

**(c) Claude Code 自主修改，同 skill 审批级别。**

model_policy.json 和 model_registry.json 的修改影响面与 skill 安装类似——都会改变 agent 的执行行为。统一由 Claude Code 自主决定 + Telegram 通知用户。不需要更高门槛，因为：
- 模型切换本身是可回滚的（git commit 记录）
- 有观察期机制（Q9.4(b) 的效果验证）
- 用户通过 Telegram 知情，可随时通过 Console 回退

### Q9.4 代码自修改的边界

Q2.11 的排障机制允许 Claude Code 修改代码。自我进化是否扩展这个能力？

**问题：**
(a) 自我进化可以修改的代码范围：只限于 config 文件（model_policy.json、skill_registry.json）？还是可以修改 Python 源码（如 routines.py、dispatch.py）？
(b) 如果允许修改源码，如何防止进化引入 bug？排障有"验证 → 不通过则回滚"的机制，进化的验证标准是什么？（比排障更难——排障有明确的"故障修复"标准，进化的"更好"怎么量化？）
(c) 进化修改的审批：Q5.7(c) 已确认 skill 由 Claude Code 审批（非人类）。代码修改也由 Claude Code 自主决定？还是源码修改（vs config 修改）需要更高门槛（如通知用户、等待确认）？
(d) 进化的频率：定期（如每周一次自我审视）？事件驱动（Playbook 中积累的负面反馈超过阈值时触发）？

**提议结论（待用户确认）：**

**(a) Config 和源码都可以修改，但分级管控。**

| 修改类型 | 范围 | 审批门槛 |
|---------|------|---------|
| config 修改 | model_policy.json, skill_registry.json, agent_capabilities.json | Claude Code 自主决定 |
| 模板修改 | templates/\<role\>/SOUL.md, TOOLS.md | Claude Code 自主决定 |
| 源码修改 | 任何 .py 文件 | Claude Code 决定 + Telegram 通知用户 |

源码修改不需要用户确认（等待确认会阻塞自动化），但必须通知用户（Telegram）并通过 git commit 记录，用户可事后审查和回滚。

**(b) 进化的验证标准——比排障更严格。**

排障验证："故障消失"（明确的 pass/fail）。进化验证分两层：

1. **必要条件（自动验证）**：
   - 修改后系统启动成功
   - pulse routine 探测全部通过
   - 如果有自动化测试（pytest），测试通过
   - 不引入新的 import 错误或语法错误

2. **充分条件（效果观察）**：
   - 进化修改标记为 `evolution_commit`，后续 N 次（默认 10 次）相关 run 的效果被 witness 跟踪
   - 如果这 N 次 run 的平均 quality_score 或用户反馈显著下降（> 15%）→ 自动回滚 commit + Telegram 通知
   - 如果无显著变化或改善 → 保留修改

**(c) Claude Code 自主决定源码修改，但通知用户。**

如上表。关键区别：
- 排障（Q2.11）：被动触发，修复已知故障，紧急性高 → 不通知直接修
- 进化（Q9.4）：主动触发，尝试改善，紧急性低 → 通知用户 + 观察期

两者使用同一个 Claude Code 通道（CLI 调用），但进化的 commit message 前缀为 `[evolution]`，与排障的 `[repair]` 区分。

**(d) 混合触发：定期 + 事件驱动。**

- **定期**：witness routine 每周产出一份"系统表现回顾"，如果发现持续的负面趋势（rework 率上升、quality_score 下降），标记为进化候选
- **事件驱动**：Playbook 中同一类问题（相似 embedding）的负面反馈累积超过 3 次 → 触发针对性进化
- 进化任务提交到 Claude Code 时，附带 witness 分析报告作为上下文

### Q9.5 暖机后的持续校准

Q7.4 设计暖机阶段的初始校准。但系统运行后，校准需要持续进行。

**问题：**
(a) complexity 默认值表（Q4.2(c)）在暖机后是否继续动态调整？还是暖机完成后固定，只能通过 Console 手动修改？
(b) review agent 的评分标准是否需要定期重新校准？（模型更新后评分尺度可能漂移）校准方法？
(c) 系统整体的"自我审视"：是否需要一个定期的 meta-routine，分析系统最近 N 天的整体表现（成功率、rework 率、用户反馈趋势），产出改进建议？这与 witness routine 是否重叠？

**提议结论（待用户确认）：**

**(a) 暖机后继续动态调整，但幅度受限。**

complexity 默认值表不锁定。witness routine 持续分析 Playbook 经验：
- 如果最近 20 条同 complexity 的 run 中，超过 30% 的 timeout 被触发 → 建议上调 timeout
- 如果 rework 率持续低于 5% → 建议下调 rework_limit（节省资源）
- 调整幅度每次不超过 ±20%（防止震荡）
- 调整建议写入 Compass，下次 Dispatch enrich 读取
- Console 可手动覆盖，手动值优先级高于自动调整

**(b) review 评分校准——靠用户反馈间接校准，不做独立校准流程。**

review agent 的评分尺度漂移问题真实存在，但独立校准流程（如让两个模型交叉评审）成本高且效果不确定。实际方案：
- 用户反馈（选择题）是校准 review 的唯一真实信号
- witness routine 监控 `review_score` 与 `user_feedback` 的相关性：如果 review 持续给高分但用户反馈负面 → 标记 review 评分偏高 → 调整 review 通过阈值上浮（而非调 review 本身）
- 模型更新时（Q9.3），新模型的首批 run 标记为 `calibration_period=true`，review 评分不参与 Playbook 的 quality_bonus 计算，等积累足够样本后恢复

**(c) 不需要独立 meta-routine，扩展 witness 即可。**

witness routine 的职责已覆盖"分析最近 N 条 Playbook 记录发现趋势"（Q7.3(c)）。将"系统整体表现分析"作为 witness 的一个子任务：
- witness 每次运行时，除了分析单条经验，还计算滑动窗口统计（最近 7 天成功率、rework 率、平均 quality_score、用户反馈分布）
- 统计写入 `state/system_health.json`，Console dashboard 读取展示
- 偏差超过阈值（如成功率骤降 20%）→ 写入 spine_log 作为异常信号 → pulse 检测到后触发排障

不新增 routine。witness 的运行频率已由 adaptive 调度控制（Q2.8），系统活跃时更频繁。

### S9-A: 暖机阶段启用 Claude Code 自动排障 ✅ 已决定

**决策**：暖机前搭好自动排障框架。

### S9-B: 暖机阶段 skill 发现 ✅ 已决定

**决策**：暖机阶段做 skill 发现，作为暖机 Track 的一条 Lane。

---

## 阶段 10：治理观测（Console）

### 前置：已确立的 Console 设计

- **Q1.8**：Fabric 对用户不可见；Console 可查看和修改 Fabric 内容
- **Q2.9**：Console 的编辑功能限于开关类、滑块类、按钮类，不做复杂文本编辑；Console 不推送通知
- **Q3.4(c)**：campaign 阶段数/步数上限可通过 Console 调整
- **Q3.5**：用户语言与系统语言严格分离——Console 使用系统语言（英文术语），Portal 使用用户语言
- **Q5.3**：cancelled run 在 Portal 消失，Console 可查看历史

---

### Q10.1 Console 的功能边界

Console 在多个阶段被引用为"治理观测端"。需要统一定义其完整功能范围。

**问题：**
(a) Console 的完整功能列表——基于前面所有阶段提到 Console 的地方，至少包括：
   - Fabric 查看/修改（Q1.8）
   - Routine 开关/阈值调整/手动触发（Q2.9）
   - 系统生命周期控制 pause/restart/reset/shutdown（Q2.12）
   - complexity 默认值表调整（Q3.4(c)）
   - 排障日志查看（Q2.11）
   - cancelled/failed run 历史查看（Q5.3）
   是否遗漏了什么？是否有不应该放在 Console 的功能？
(b) Console 的用户是谁？只有系统管理员（即你本人）？还是可能有其他人使用？这决定了是否需要权限控制。
(c) Console 与 Portal 的技术实现：两者是同一个 Web 应用的不同页面？还是完全独立的前端？共享同一个 API server？

**提议结论（待用户确认）：**

**(a) Console 完整功能列表：**

汇总前面所有阶段对 Console 的引用：

| 功能 | 来源 | 类型 |
|------|------|------|
| Fabric Memory 查看/删除 | Q1.8 | 观测+操作 |
| Fabric Playbook 查看/标记 stale | Q1.8 | 观测+操作 |
| Fabric Compass 偏好查看/编辑 | Q1.8, Q4.5(c) | 观测+操作 |
| Routine 开关/阈值/手动触发 | Q2.9 | 操作 |
| 系统生命周期 pause/restart/reset/shutdown | Q2.12 | 操作 |
| 排障日志查看 | Q2.11 | 观测 |
| Gate 状态查看/手动覆盖 | Q4.7 | 观测+操作 |
| complexity 默认值表调整 | Q3.4(c), Q4.2(c) | 操作 |
| Pool size N 调整 | Q1.11 | 操作 |
| Provider 配额查看/限额调整 | Q4.6 | 观测+操作 |
| agent_model_map 调整 | Q4.4 | 操作 |
| cancelled/failed Run 历史 | Q5.3 | 观测 |
| 系统日志查看（spine/events/cortex/audit） | Q2.2 | 观测 |
| Dashboard 概览 | — | 观测 |

不应放在 Console：任务提交、用户对话、outcome 文件管理、Track/Lane 的创建（这些是 Portal 职责或文件系统直接操作）。

**(b) Console 用户只有系统管理员（用户本人）。**

不需要权限控制系统（角色/ACL）。Console 的访问控制通过网络层实现（Q10.4(a) 的路由级隔离 + Tailscale 内网），不在应用层做鉴权。

**(c) 同一 Web 应用，不同路由，共享 API server。**

- 同一个 FastAPI 实例
- `/console/*` 路由服务 Console 前端资源和 API
- `/portal/*` 路由（或根路由 `/*`）服务 Portal 前端资源和 API
- 前端资源物理分离（`interfaces/console/` 和 `interfaces/portal/`），各自独立的 HTML + JS
- 共享后端逻辑（如 StateStore 读取、Temporal 客户端）

### Q10.2 Console 的可观测性仪表板

Console 需要展示系统运行状态。

**问题：**
(a) Console 首页（dashboard）应该展示哪些核心指标？系统状态（running/paused）？当前运行中的 Run 数？池实例使用率（occupied/total）？provider 配额剩余？最近 N 条 routine 执行记录？
(b) 实时性要求：dashboard 数据需要实时刷新（WebSocket 推送）？还是手动刷新 / 定时轮询足够？
(c) 历史数据可视化：是否需要图表（如过去 7 天的 Run 成功率趋势、token 消耗趋势）？还是纯文本/表格足够？
(d) 日志查看：Console 能查看哪些日志？spine_log.jsonl、events.jsonl、cortex_usage.jsonl 都能查看？需要搜索/过滤功能吗？

**提议结论（待用户确认）：**

**(a) Dashboard 核心指标：**

| 区域 | 指标 |
|------|------|
| 系统状态 | 当前状态（running/paused/...）、uptime、gate 状态 |
| Run 概览 | 运行中 Run 数、今日完成数、今日失败数 |
| 池实例 | 各角色 occupied/idle 数量（如 collect: 3/24） |
| Provider 配额 | MiniMax remains（实时查询）、其他 provider 已用/日限额 |
| Routine 健康 | 最近 5 条 routine 执行记录（routine 名、状态、耗时） |
| 排障 | 当前是否有 routine 在 repairing 状态 |

**(b) 定时轮询，不需要 WebSocket。**

Console 是管理面板，不是实时监控大屏。30 秒轮询 `GET /console/dashboard` 足够。页面上放一个手动刷新按钮。暖机后如果发现 30 秒太慢，可调整间隔。

**(c) 初期纯表格，不做图表。**

图表需要前端图表库（Chart.js 等），增加复杂度。初期用表格展示最近 7 天的每日统计即可。数据存在 `state/daily_stats.jsonl`（tend routine 每日写入一条汇总）。后续如果确实需要可视化，再引入。

**(d) 日志查看：三个 JSONL 都可查看。**

- `spine_log.jsonl`：routine 执行记录
- `events.jsonl`：Nerve 事件
- `cortex_usage.jsonl`：LLM 调用记录
- `console_audit.jsonl`：Console 操作审计

每个日志页面支持：按时间范围过滤、按关键字搜索、最近 N 条快速查看。实现方式：API 端点读取 JSONL 尾部 + 简单过滤，前端表格渲染。不做全文搜索索引。

### Q10.3 Console 的编辑能力

Q2.9 限定了 Console 的编辑能力：开关类、滑块类、按钮类。

**问题：**
(a) 可编辑参数的完整清单——基于前面所有阶段：
   - Routine 开关（启用/禁用）
   - Routine 阈值（如 adaptive 调度的信号权重）
   - complexity 默认值表（concurrency/timeout/rework_limit）
   - Gate 状态手动覆盖（如强制 GREEN/RED）
   - Pool size N 的调整（Q1.11，写入 Compass）
   - provider 每日 token 限额（Q4.6）
   - 单 run 预算上限比例（Q4.6(c)）
   是否还有其他？
(b) 编辑的生效方式：修改后立即生效？还是需要确认/重启？部分修改（如 pool size N）需要 gateway restart 才能生效——Console 是否应该警告用户影响？
(c) 编辑的审计：Console 上的每次修改是否记录审计日志（谁在什么时间改了什么）？

**提议结论（待用户确认）：**

**(a) 完整可编辑参数清单：**

列举中的 7 项已覆盖主要范围。补充：
- **Fabric Memory 条目管理**（Q1.8）：查看、删除（不编辑内容——Memory 由 Spine 写入，Console 只做清理）
- **Playbook 经验记录管理**：查看、标记 stale、删除（不编辑内容）
- **Compass 全局偏好**：key-value 编辑（如 `require_bilingual`, `default_depth`）
- **agent_model_map**：调整 agent 类型 → 模型映射

不应放在 Console 的：任务提交（Portal 职责）、用户对话（Portal 职责）、outcome 管理（文件系统直接操作）。

**(b) 生效方式——分三类：**

| 类别 | 参数 | 生效方式 |
|------|------|---------|
| 立即生效 | routine 开关、阈值、gate 覆盖、budget 限额、complexity 默认值 | 写入 state/ 文件，下次读取时生效 |
| 下次 Run 生效 | agent_model_map、Compass 偏好、quality 参数 | 写入 config/state，下次 Dispatch enrich 时读取 |
| 需要 restart | pool size N | Console 显示警告："修改 pool size 需要系统重启（gateway restart），确认？" |

Console 对需要 restart 的参数显示明确警告和确认对话。

**(c) 审计日志。**

每次 Console 编辑写入 `state/console_audit.jsonl`：`{timestamp, parameter, old_value, new_value}`。tend routine 清理超过 90 天的审计记录。审计日志本身在 Console 可查看。

### Q10.4 Console 与 Portal 的交互边界

两者面向不同用户群体（管理员 vs 终端用户），但共享同一个系统。

**问题：**
(a) 信息隔离：Portal 的用户永远无法通过 URL 访问 Console 页面吗？需要路由级别的隔离还是仅 UI 层面不展示 Console 入口？
(b) Console 上的操作（如 pause 系统）会影响 Portal 用户的体验——Portal 是否需要感知系统状态变化？（如系统 paused 时 Portal 显示"系统维护中"？）
(c) 当前 Console 和 Portal 的技术栈：两者都是单页面 HTML + vanilla JS？是否需要统一技术栈，还是各自独立更好？

**提议结论（待用户确认）：**

**(a) 路由级隔离。**

Console 和 Portal 是同一 API server 下的不同路由前缀：`/portal/*` 和 `/console/*`。隔离方式：
- Console 路由绑定 `127.0.0.1`（仅本地访问），或通过 Tailscale 内网鉴权（Q4 待做）
- Portal 路由可对外暴露（未来通过 Tailscale）
- 两者共享同一个 FastAPI 实例和 API 层，但前端资源完全独立
- Portal 页面中没有任何指向 Console 的链接或入口

**(b) Portal 感知系统状态。**

系统 paused/restarting/shutdown 时，Portal 需要告知用户：
- Portal 定期轮询 `GET /system/status`（每 30 秒）
- 系统非 running 状态时，Portal compose 区域显示友好提示（用户语言）："系统正在维护，暂时无法提交新任务。正在进行的任务不受影响。"
- 不阻止用户浏览历史任务和 outcome
- 系统恢复 running 后提示自动消失

**(c) 各自独立，不统一技术栈。**

当前两者都是单页面 HTML + vanilla JS，这个选择是对的：
- Console 和 Portal 的交互模式截然不同（Console 是数据密集型管理面板，Portal 是对话式交互）
- 两者独立开发、独立部署前端资源
- 共享的只有 API server（FastAPI）
- 不引入前端框架（React/Vue），保持轻量——daemon 的前端复杂度不需要框架

### S10-A: Console 审计日志 ✅ 已决定

**决策**：暖机前加。Console API 每个 endpoint 加一行 append 到 `state/console_audit.jsonl`。

### S10-B: daily_stats.jsonl ✅ 已决定

**决策**：暖机前加。

**补充生产机制清单**（用户确认全部做）：

| 机制 | 说明 | 状态 |
|------|------|------|
| API 限流/熔断 | 外部 API 被限速或宕机时的重试 + 熔断 | ✅ 已实现（gate + disk probe） |
| 并发写保护 | 两进程同时写 runs.json 的 RMW 竞争 | ✅ 已实现（fcntl.flock + threading.Lock） |
| 磁盘空间监控 | traces/events/runs 持续写入的空间监控 | ✅ 已实现（pulse _probe_disk） |
| 通知失败队列 | Telegram 发送失败时消息持久化重试 | ✅ 已实现（notify_queue.jsonl + scheduler retry） |
| 备份恢复 | Fabric 数据库等关键状态的定期备份 | ✅ 已实现（tend _backup_state，保留 7 份） |
| 配置迁移 | compass pref schema 变更时的版本迁移 | 待暖机前实现 |
| Run 超时通知 | timeout 走正常失败通知流程，不单独设计 | ✅ 由通知系统覆盖 |

---

## 补充议题

### X-1: warmup.py 的定位 ✅ 已决定

warmup.py 改造为暖机控制器。暖机设计文档在 QA 全部完成后专门写。

### X-2: embedding 不可用时的 Playbook consult 退化 ✅ 已决定

**决策**：暖机前必须确保 embedding 可用。

已完成代码改动：
1. `runtime/cortex.py` — `embed()` 方法改为优先使用 zhipu embedding-3，fallback 到 openai
2. `config/model_registry.json` — 新增 `embedding` 别名（zhipu, embedding-3, 1024维, 双语）

### X-3: Nerve 事件丢失可接受性 ✅ 已决定

**决策**：Nerve 保持易失，关键事件同时写 events.jsonl（write-through）。

**daemon 数据存储全景**（计算机存储分层类比）：

| 层级 | 类比 | daemon 对应 | 策略 |
|------|------|-------------|------|
| L0 寄存器/缓存 | 易失、微秒级 | Nerve 内存事件总线 | write-through（关键事件同时写 events.jsonl） |
| L1 热存储 | 持久、毫秒级 | state/*.json + Fabric SQLite | WAL 模式 / 变更立即写磁盘 |
| L2 温存储 | 持久、秒级 | snapshots、traces、events.jsonl、delivery_log.jsonl | 定期写入，tend 定期清理（traces 7天、events 30天） |
| L3 冷存储 | 持久、分钟级 | Drive archive | librarian 每6小时归档，90天后删除 |

**三个存储优化**（已决定全部暖机前做）：
1. **Trace 分层保留**：7天完整 → 7-90天摘要 → 90天后全删
2. **Archive 分层**：90天完整 → 90-365天只保留 manifest + outcomes → 365天后全删
3. **统一 GC**：tend 中统一协调所有清理操作，先检查可用空间 → 按优先级清理

**用户重要说明**：暖机 = 紧跟系统正式启用的阶段。暖机是自动化程序，使用者只需配好环境和接口，一键运行。**开发者的所有工作必须在暖机之前全部完成**。不再有"暖机后做"这个选项。
