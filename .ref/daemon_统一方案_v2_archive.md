# Daemon 统一方案 V2（实施规范）

> 更新日期：2026-03-08
> 设计依据：`.ref/DESIGN_QA.md`（QA 1-10 全部阶段确认决策）
> 本文档是 QA 确认决策的实施规范。设计理由和讨论过程见 QA 文档。

---

## 0. 文档治理

1. **权威关系**：`DESIGN_QA.md`（设计决策记录）+ 本文档（实施规范）共同构成权威。两者冲突时以 QA 为准。
2. **废弃文档**：`gap_analysis.md`、`action_plan.md`、旧方案文档均不作为实施依据。
3. **系统语言约定**：代码、日志、Console 中全部使用英文术语（run, track, lane, step, plan, dispatch），任何情况不翻译。用户界面（Portal、Telegram）使用用户语言（"任务"、"目标"、"结果"），不暴露系统术语。

---

## 1. 核心原则

1. **质量 + 稳定** 双目标优先，其次优化延迟与成本。
2. **系统永远不拒绝**：用户任何需求都引导到可执行的程度（Q3.4）。
3. **学习基于 embedding 相似性**，不基于分类（理念 D）。
4. **收敛性分层保障**：计划阶段拦截 → openclaw 内建机制 → 诊断重构（理念 C）。
5. **用户语言与系统语言严格分离**（Q3.5）。
6. **Outcome 零系统痕迹**：outcomes/ 中只有人类可读文件（Q6.1）。
7. **Track 按需引入**：大多数 run 不属于 Track（Q8 前置）。
8. **Skill 由 Claude Code 审批**，人类不参与（Q5.7c）。
9. **fail-closed**：关键链路失败则停止；非关键链路可降级但标注 `degraded=true`。

---

## 2. 架构概览

### 2.1 两个进程

| 进程 | 组件 | 职责 |
|------|------|------|
| API 进程 | FastAPI + Scheduler + Spine + Fabric | 接受请求、调度 routine、管理状态 |
| Worker 进程 | Temporal Worker + Activities | 执行 run 的步骤、调用 openclaw agent |

两进程不直接通信，通过 Temporal 和共享文件系统（`state/`、`~/My Drive/daemon/`）协作。

### 2.2 端到端数据流

```
用户 → Portal Dialog → Router Agent → RunSpec + Plan → 用户确认
→ POST /submit → Dispatch.enrich() → Temporal Workflow
→ AgentPoolManager 分配池实例 → 步骤执行（subagent）
→ review 审查 → delivery quality gate → outcome 写入
→ Nerve emit → record/learn/witness routine → Fabric 更新
```

### 2.3 废弃概念

以下概念在 QA 中已被废弃，代码中不得使用：

| 废弃概念 | 替代 |
|---------|------|
| cluster / cluster_id | embedding 相似性检索 |
| SemanticSpec | RunSpec |
| IntentContract | RunSpec |
| Strategy (champion/challenger) | Playbook 经验自然积累 |
| run_type（作为分类键） | RunSpec.complexity |
| work_scale | RunSpec.complexity |
| semantic_cluster | 废弃，无替代 |
| strategy_candidates/experiments/promotions | 废弃 |
| quality_contracts/*.json（按 cluster） | Compass 偏好 + RunSpec.depth |
| mapping_rules.json | 废弃 |
| capability_catalog.json | agent_capabilities.json |
| user_rating (int 1-5) | user_feedback (json, 选择题) |

---

## 3. Fabric（系统大脑）

三组件：Memory（知识）、Playbook（经验）、Compass（偏好）。对用户不可见（Q1.8），Console 可查看修改。

### 3.1 Memory

- 存储：`state/memory.db`（SQLite + embedding 向量）
- 条目结构：`{id, content, tags, embedding, relevance_score, created_utc, updated_utc}`
- **容量上限 + 热度衰减**（Q1.1）：被引用时 relevance 回升，长期不引用则衰减。超限时先合并相似低分条目，仍超限淘汰最低分
- **冲突处理**（Q1.2）：新记忆直接覆盖旧的矛盾记忆
- **embedding 检索**（Q1.10）：通过 cortex.embed 生成向量，语义相似度 + 阈值过滤
- **版本化**（Q1.9）：state/ 目录内建独立 git repo，Spine 修改后自动 commit

### 3.2 Playbook

- 存储：`state/playbook.db`（SQLite）
- 经验记录结构（Q4.2a）：

```python
PlaybookRecord = {
    "run_id": str,
    "objective_embedding": vector,
    "objective_text": str,
    "complexity": str,           # pulse/thread/campaign
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

- **检索**（Q4.2b）：仅在 Dialog 阶段使用，score = sim(embedding) × 0.6 + recency × 0.2 + quality_bonus × 0.2。complexity 硬过滤。返回 top-3
- **衰减**（Q1.3）：带时间戳和使用计数，长期未命中自动衰减权重

### 3.3 Compass

- 存储：`state/compass.db`（SQLite）
- 全局偏好 key-value（Q7.5a）：`require_bilingual`, `default_depth`, `default_format`, `default_language`, `pool_size_n`, `provider_daily_limits`, `run_budget_ratio`
- **偏好 confidence**（Q1.5）：`confidence = min(sample_count / threshold, 1.0)`
- **不按 cluster 索引**：废弃 quality_profiles 表（Q4.5c）

### 3.4 Fabric 一致性

不做显式冲突检测（Q1.7）。优先级：显式指令 > 统计偏好 > 单次观察 > 默认策略。通过 prompt 拼接顺序隐式解决。

---

## 4. Spine（自主神经系统）

### 4.1 Routine 列表

| Routine | 频率 | 职责 |
|---------|------|------|
| pulse | 10 min | 健康检查（gateway/temporal/LLM），gate 设定，排障检测 |
| record | 事件驱动 | run_completed 时写 Playbook 经验 |
| witness | adaptive | 分析 Playbook 趋势，更新 Compass 偏好，系统健康统计 |
| learn | 事件驱动 | Run 结束时从池实例 workspace 提取认知 → Memory |
| distill | 每日 | Memory 热度衰减 + 合并压缩（Q1.1） |
| focus | adaptive | 注意力调整（embedding 索引维护等） |
| relay | 事件驱动 | 池实例分配时 Fabric 快照写入；定期更新 router agent |
| tend | 每日 | state/ git commit、日志清理、池实例残留检查、archive GC |
| librarian | 每 6h | run_root → archive 归档、archive 过期清理 |

### 4.2 Routine 执行保障

- **超时**（Q2.1）：默认 120s，LLM 密集型 300s
- **depends_on**（Q2.3）：下游检查上游最近一次是否成功
- **日志**（Q2.2）：`state/spine_log.jsonl`（routine 名、时间、成功/失败、产出摘要）
- **adaptive 调度**（Q2.8）：多维信号加权（Fabric 变更频率、用户活跃度、产出质量、错误率、时段）

### 4.3 Nerve 事件总线

- 进程内同步事件总线
- 持久化：`state/events.jsonl`（event_id, event, payload, timestamp, consumed_utc）
- at-least-once：进程重启时扫描未消费事件重触发（Q2.4）
- tend routine 清理超过 30 天旧事件

### 4.4 自动排障（Q2.11）

- 触发：同一 routine 连续 3 次失败
- 流程：暂停 routine → Telegram 通知 → Claude Code CLI 诊断修复 → 验证 → 恢复
- 保护：单次 10 分钟超时，24h 内最多排障 3 次

### 4.5 看门狗（Q2.13）

- 独立 cron job（每 5 分钟），< 50 行 shell 脚本
- 检查：进程存活、API 响应、pulse 最后执行时间
- 通知：Telegram → macOS 桌面通知 → `~/daemon/alerts/` 日志
- `~/daemon/alerts/TROUBLESHOOTING.md`：静态排障指南

### 4.6 系统生命周期（Q2.12）

五状态：`running` → `paused` → `restarting` / `resetting` / `shutdown`

操作入口：CLI (`daemon start/pause/restart/reset/shutdown`)、Console、API (`POST /system/{action}`)

状态持久化：`state/system_status.json`

---

## 5. Dialog（用户意图理解）

### 5.1 入口分野（Q3.1）

| 入口 | 职责 |
|------|------|
| Portal | 唯一任务提交入口。内嵌 Dialog 对话 |
| Telegram | 通知推送 + 严格命令式交互（/cancel、/status） |
| Console | 系统治理观测，不提交任务 |

### 5.2 Dialog 流程（Q3.5）

Portal 内嵌对话式交互（Claude 风格），由 Router Agent 驱动。

完成标志 = 双重确认：系统生成通过收敛性验证的 plan + 用户确认执行。

核心设计：系统是耐心的一方，适应意图漂移，不被用户急躁带偏。

### 5.3 RunSpec（Q3.6a）

替代 SemanticSpec + IntentContract：

```python
@dataclass
class RunSpec:
    objective: str          # 用户目标（原文）
    complexity: str         # pulse | thread | campaign
    step_budget: int        # 步数上限
    language: str           # zh | en | bilingual
    format: str             # pdf | markdown | code | text
    depth: str              # brief | standard | thorough
    references: list[str]   # 用户提供的参考资料
    confidence: str         # high | medium | low
    quality_hints: list[str] # 用户显式质量要求（Q4.5b）
```

### 5.4 复杂度等级（Q3.2a）

| 复杂度 | 步数上限 | 典型任务 |
|--------|---------|---------|
| pulse | 1 | 快速查询、格式转换 |
| thread | 2-6 | 研究报告、代码开发 |
| campaign | 多阶段，每阶段 2-8 步，最多 5 阶段 | 系统设计、大型调研 |

### 5.5 Plan 验证（Q3.3b）

1. DAG 无环
2. 每步 agent 类型合法（collect/analyze/build/review/render/apply）
3. depends_on 引用合法
4. 总步数 ≤ step_budget
5. 至少一个 terminal 步骤

---

## 6. Dispatch（决策层）

### 6.1 enrich 流程（Q4.1a）

```
normalize(RunSpec 校验)
→ complexity_defaults(填充执行参数)
→ quality_profile(Compass 偏好 + RunSpec.depth)
→ model_routing(agent_model_map)
→ budget_preflight(估算 + 配额检查)
→ gate_check(系统健康)
```

### 6.2 Complexity 默认值表（Q4.2c）

| 参数 | pulse | thread | campaign |
|------|-------|--------|----------|
| concurrency | 1 | 2 | 4 |
| timeout_per_step_s | 120 | 300 | 600 |
| rework_limit | 0 | 1 | 2 |

暖机阶段校准，此后 Compass 可调。

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

废弃 `by_semantic_cluster`、`by_risk_level` 维度。

### 6.4 预算管控（Q4.6）

- **MiniMax**：prompt 次数制（100/5h 滚动窗口），调用 `/coding_plan/remains` 查询实时额度
- **其他 provider**：token 制，daemon 自设每日限额
- **单 run 上限**：窗口/日限额 × 50%
- 预算不足 → run 排队，Portal 显示预计恢复时间

### 6.5 Gate（Q4.7）

| 条件 | gate | 行为 |
|------|------|------|
| 全部健康 | GREEN | 所有 run 正常 |
| 部分不可用 | YELLOW | pulse 照常，thread 低优先排队，campaign 排队 |
| 全部不可用 | RED | 所有 run 排队 |

### 6.6 Submit Payload（Q4.8a）

```json
{
  "run_spec": { ... },
  "plan": { "steps": [...] },
  "metadata": {
    "source": "portal_dialog | cron_trigger | track_advance | warmup",
    "lane_id": null,
    "track_id": null,
    "priority": 5
  }
}
```

---

## 7. 执行层

### 7.1 Agent 池模型（Q1.11）

- **池实例预注册**：bootstrap 时在 openclaw.json 注册 145 个 agent（6 角色 × 24 + router）
- **N = 24**（默认，下限 16），写入 Compass 可调
- **模板目录**：`templates/<role>/`（SOUL.md、TOOLS.md、REFERENCES/）
- **AgentPoolManager**：负责分配/归还、模板填充/清空、Fabric 快照写入、主 session 管理

### 7.2 Run 生命周期

```
Allocation:
  1. AgentPoolManager 分配空闲池实例
  2. templates/<role>/ → 复制到实例 agentDir
  3. Fabric 快照 → 实例 workspace/memory/MEMORY.md
  4. 创建主 session（full mode）

Execution:
  5. Activity 向主 session 发步骤指令
  6. 主 session 发起 subagent 执行
  7. 产出写入 run_root/steps/{step_id}/output.md

Return:
  8. learn routine 提取认知 → Memory
  9. 关闭主 session
  10. 清空 agentDir + workspace/memory/
  11. 归还池实例
```

### 7.3 步骤执行（Q5.1）

1. Workflow Kahn 拓扑排序确定就绪步骤
2. Checkpoint 恢复（幂等性）
3. Skill 注入（Router 在 plan 生成阶段动态选择）
4. 向池实例主 session 发指令 → subagent 执行
5. 等待返回 + Temporal heartbeat
6. 检查 `abortedLastRun`（正常完成 vs 熔断）
7. 产出写入 `run_root/steps/{step_id}/output.md`

### 7.4 步骤间数据传递（Q5.1）

- 同 agent 内：通过 agent 记忆（主 session full mode）
- 跨 agent：通过 `run_root/steps/{step_id}/output.md`

### 7.5 Rework 机制（Q5.4a）

基于步骤追溯：delivery quality gate 返回 `failures[].source_steps`，直接定位要重做的步骤。

不收敛（circuit breaker 触发）→ 诊断 session → 查 Playbook → 针对性重构（Q3.2d）。

### 7.6 Campaign 阶段管理（Q5.5）

- Temporal `wait_condition` + Signal 等待用户确认
- 逐阶段生成 plan（不一次性生成全部 milestone）
- 用户可确认/调整/取消/不做

### 7.7 用户干预（Q5.3）

| 操作 | Cancel | Pause |
|------|--------|-------|
| 可逆性 | 不可逆 | 可恢复 |
| 产物 | 删除 run_root | 保留 |
| Portal | 从任务列表消失 | 标记 paused |
| 确认 | 需二次确认 | 不需要 |

### 7.8 Skill 管理（Q5.7）

- **动态选择**：Router 在 plan 生成时从 `config/skill_registry.json` 匹配
- **注册表字段**：skill_id, display_name, description, compatible_agents, capability_tags, status
- **审批**：Claude Code（Q5.7c），非人类
- **淘汰**：连续 N 次 degraded/failed → Claude Code 审批淘汰

### 7.9 openclaw 收敛配置（Q3.7）

| agent | warning | critical | breaker |
|-------|---------|----------|---------|
| collect | 10 | 20 | 30 |
| analyze | 8 | 16 | 24 |
| build | 15 | 30 | 45 |
| review | 8 | 16 | 24 |
| render | 8 | 16 | 24 |
| apply | 10 | 20 | 30 |

---

## 8. 交付层

### 8.1 三个存储位置

| 位置 | 内容 | 保留期 |
|------|------|--------|
| `state/runs/{run_id}/`（run_root） | 运行时中间产物 | 归档后 7 天清理 |
| `~/My Drive/daemon/outcomes/` | 用户产出（零系统痕迹） | 永久 |
| `~/My Drive/daemon/archive/` | 系统执行痕迹 | 90 天 |

### 8.2 Outcome 结构（Q6.1）

```
outcomes/YYYY-MM/YYYY-MM-DD HH.MM 标题/
  ├── 标题（中文）.md
  ├── 标题（中文）.pdf
  ├── Title (English).md
  ├── Title (English).pdf
  └── summary.txt
```

零 JSON、零 run_id、零系统术语。delivery activity 写入前做系统痕迹清洗。

### 8.3 Archive 结构（Q6.1b）

```
archive/YYYY-MM/run_id/
  ├── manifest.json    (run 元数据)
  ├── steps/           (各步骤 output.md + meta.json)
  └── review_report.json
```

### 8.4 Delivery 流程

1. 同步：delivery activity 写 outcome → `~/My Drive/daemon/outcomes/`
2. 同步：写 `state/delivery_log.jsonl` 索引
3. 同步：Nerve emit `delivery_completed`
4. 异步：librarian routine 归档 run_root → archive，然后清理 run_root

### 8.5 Bilingual 产出（Q6.4）

同一 render 步骤产出两份，各自遵循本语言规范：
- 中文：GB/T 7714 引用/中文排版
- 英文：APA/Chicago 引用/英文排版
- 内容相同，格式规范独立

### 8.6 Review 评分维度（Q7.1）

| 维度 | 含义 |
|------|------|
| coverage | 信息覆盖面 |
| depth | 分析深度 |
| coherence | 逻辑一致性 |
| accuracy | 事实准确性 |
| format_compliance | 格式规范 |

0-1 浮点。RunSpec.depth 影响 rework 阈值，不影响评分标准。

### 8.7 用户反馈（Q7.2）

选择题形式，非打分：

```json
{
  "overall": "satisfactory | acceptable | unsatisfactory | wrong",
  "issues": ["depth_insufficient", "missing_info", ...]
}
```

Portal 主动弹出，用户可关掉不回答（user_feedback=null）。

### 8.8 Telegram 推送

- pulse/thread：完成时推一次（摘要 + Portal 链接）
- campaign：每个 milestone 完成后推一次 + 最终推送
- 失败/需干预时推一次

---

## 9. 学习循环

### 9.1 Run 完成后的数据流

| 目标 | 写入者 | 内容 |
|------|--------|------|
| Playbook | record routine | 经验记录（embedding + plan + quality + feedback） |
| Memory | learn routine | 从池实例 workspace 提取的认知 |
| Compass | witness routine | 全局偏好统计更新 |

### 9.2 Learn Routine（Q7.3b）

- 结构化提取：数据源质量问题、skill 使用记录
- 语义提取：LLM 判断 agent memory 中的可泛化知识
- 使用 analyze agent 模型（DeepSeek R1）

### 9.3 Witness Routine（Q7.3c）

- 分析最近 20 条 Playbook 经验
- 计算 quality_score 趋势、rework 率、user_feedback 分布
- 更新 Compass 偏好、写入 `state/system_health.json`

### 9.4 Distill Routine（Q7.3d）

- Memory 热度衰减 + 合并压缩
- learn = 生产新知识，distill = 压缩已有知识

---

## 10. 目标管理（Track-Lane-Run）

### 10.1 Track（Q8.1）

- **按需引入**：大多数 run 不属于 Track
- **创建条件**：campaign 无法收敛时系统自动创建 / 用户主动创建
- **状态**：active / paused / completed / abandoned（用户手动标记完成）
- **数据**：`state/tracks.json`

### 10.2 Lane（Q8.2）

- 更通用的调度单元，可独立于 Track（`track_id=null`）
- **trigger 类型**：manual / cron / on_complete
- **独立 Lane** = 当前代码中的 chain（重命名）
- **cron Lane**：存储 RunSpec 模板，每次触发时 Dialog 生成 plan
- **数据**：`state/lanes.json`

### 10.3 Run 标识（Q8.3）

- 统一 UUID，metadata 区分归属（track_id, lane_id）
- rework = 同一 run_id 的不同 attempt

### 10.4 周期任务 UX（Q8.4）

- Portal 提交时选择"定期执行"→ 创建 cron Lane
- 暂停后不补执行
- Portal"定期任务"页面展示所有 cron Lane

---

## 11. 自我进化

### 11.1 Skill 发现与 Benchmark（Q9.1）

- 主动搜索（每周）+ 被动发现（agent 能力缺口）
- benchmark 必须通过：下载 → 静态审计 → 沙盒测试 → 效果对比
- Claude Code 审批安装

### 11.2 模板进化（Q9.2）

- templates/ 可自动进化（Claude Code 修改 SOUL.md/TOOLS.md）
- state/ git 回滚兜底
- 修改通过 `[evolution]` 前缀 commit

### 11.3 模型策略进化（Q9.3）

- Claude Code 搜索 provider 新模型公告
- 渐进式引入：试用 5-10 次 → witness 对比 → 决定切换
- model_policy.json 由 Claude Code 自主修改

### 11.4 代码自修改（Q9.4）

| 修改类型 | 审批 |
|---------|------|
| config 修改 | Claude Code 自主 |
| 模板修改 | Claude Code 自主 |
| 源码修改 | Claude Code 自主 + Telegram 通知 |

效果观察期：修改后 10 次相关 run，quality 下降 > 15% → 自动回滚。

---

## 12. Console（治理观测）

### 12.1 功能（Q10.1）

- Fabric 查看/管理
- Routine 开关/阈值/手动触发
- 系统生命周期控制
- complexity 默认值表调整
- Pool size 调整
- Provider 配额查看/调整
- agent_model_map 调整
- Gate 查看/覆盖
- 日志查看（spine_log/events/cortex_usage/audit）
- cancelled/failed Run 历史

### 12.2 Dashboard（Q10.2）

系统状态、Run 概览、池实例使用率、Provider 配额、Routine 健康。30 秒轮询。

### 12.3 Portal 与 Console 隔离（Q10.4）

- 路由级隔离：`/portal/*` vs `/console/*`
- 前端资源独立，共享 API server
- 系统非 running 时 Portal 显示维护提示

---

## 13. 数据模型与存储

### 13.1 state/ 目录结构

```
state/
  ├── memory.db              # Memory（SQLite + embedding）
  ├── playbook.db            # Playbook（SQLite）
  ├── compass.db             # Compass（SQLite）
  ├── tracks.json            # Track 定义
  ├── lanes.json             # Lane 定义
  ├── runs/                  # 运行时目录
  │   └── {run_id}/
  │       ├── plan.json
  │       ├── status.json
  │       ├── render_input.md
  │       └── steps/{step_id}/output.md
  ├── spine_log.jsonl        # Routine 执行日志
  ├── events.jsonl           # Nerve 事件
  ├── cortex_usage.jsonl     # LLM 调用记录
  ├── delivery_log.jsonl     # 交付索引
  ├── system_status.json     # 系统状态
  ├── system_health.json     # 健康统计
  ├── gate.json              # Gate 状态
  ├── console_audit.jsonl    # Console 操作审计
  ├── pool_status.json       # 池实例状态
  └── .git/                  # 独立 git（本地版本化）
```

### 13.2 外部存储

```
~/My Drive/daemon/
  ├── outcomes/              # 用户产出（永久）
  │   └── YYYY-MM/{date time title}/
  └── archive/               # 系统执行痕迹（90 天）
      └── YYYY-MM/{run_id}/
```

### 13.3 delivery_log.jsonl 记录结构

```json
{
  "run_id": "uuid",
  "completed_utc": "iso",
  "outcome_path": "path",
  "archive_path": "path",
  "archive_status": "pending|archived|expired",
  "lane_id": "uuid|null",
  "track_id": "uuid|null",
  "complexity": "thread",
  "quality_score": 0.82,
  "user_feedback": null
}
```

---

## 14. API 接口

### 14.1 Portal API

| 端点 | 方法 | 用途 |
|------|------|------|
| `/submit` | POST | 提交 run（RunSpec + plan + metadata） |
| `/dialog` | POST | Dialog 对话（Router Agent） |
| `/tasks` | GET | 历史任务列表（从 delivery_log） |
| `/tasks/{run_id}` | GET | 任务详情 |
| `/tasks/{run_id}/feedback` | POST | 用户反馈提交 |
| `/tasks/{run_id}/cancel` | POST | 取消 run |
| `/tasks/{run_id}/pause` | POST | 暂停 run |
| `/tasks/{run_id}/resume` | POST | 恢复 run |
| `/tracks` | GET/POST | Track CRUD |
| `/tracks/{id}` | GET/PUT/DELETE | Track 操作 |
| `/lanes` | GET/POST | Lane CRUD |
| `/lanes/{id}` | GET/PUT/DELETE | Lane 操作 |
| `/system/status` | GET | 系统状态（Portal 轮询） |
| `/portal/result/{run_id}` | GET | 结果页面 |

### 14.2 Console API

| 端点 | 方法 | 用途 |
|------|------|------|
| `/console/dashboard` | GET | Dashboard 数据 |
| `/console/fabric/{component}` | GET | Fabric 查看 |
| `/console/fabric/{component}/{id}` | DELETE | Fabric 条目删除 |
| `/console/compass/preferences` | GET/PUT | Compass 偏好编辑 |
| `/console/routines` | GET | Routine 状态 |
| `/console/routines/{name}/toggle` | POST | Routine 开关 |
| `/console/routines/{name}/trigger` | POST | 手动触发 |
| `/console/config/{key}` | GET/PUT | 可调参数编辑 |
| `/console/logs/{type}` | GET | 日志查看 |
| `/console/pool` | GET | 池实例状态 |
| `/system/{action}` | POST | 生命周期操作 |

### 14.3 Telegram

- Webhook 端点：`/telegram/webhook`
- 白名单命令：`/cancel`、`/status`
- 命令 + 数字选项交互模式

---

## 15. Config 文件

### 15.1 config/model_policy.json

```json
{
  "agent_model_map": {
    "router": "fast",
    "collect": "fast",
    "analyze": "analysis",
    "build": "fast",
    "review": "review",
    "render": "glm",
    "apply": "fast"
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
  "glm": {"provider": "zhipu", "model_id": "glm-z1-flash"}
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
4. 初始化 Fabric DB（memory.db, playbook.db, compass.db）
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
4. 启动 Spine scheduler
5. 启动 API server
6. 启动 Temporal worker

### 16.3 暖机（Q7.4）

- `scripts/warmup.py`：约 25 条预设任务
- 覆盖 complexity × agent × format × language
- 成功标准：Playbook ≥ 20 条，全 agent 覆盖，默认值稳定
- 完成后推送 5 条随机 outcome 到 Telegram，用户抽查

---

## 17. 质量保障

### 17.1 质量四层来源（Q4.5a）

1. 用户显式说明（最高）
2. Playbook 历史经验
3. Compass 用户偏好
4. 系统默认值（最低）

### 17.2 不可协商底线（Q4.5d）

- `forbidden_markers`：产出不得包含系统标记
- `language_consistency`：语言与 RunSpec.language 一致
- `format_compliance`：格式可用（PDF 可渲染、code 语法正确）
- `academic_format`：学术文体强制对应引用规范

### 17.3 Rework 阈值（按 RunSpec.depth）

| depth | coverage ≥ | depth ≥ |
|-------|-----------|---------|
| brief | 0.5 | 0.4 |
| standard | 0.6 | 0.6 |
| thorough | 0.7 | 0.7 |
