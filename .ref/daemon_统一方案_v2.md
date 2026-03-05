# Daemon 统一方案 V2（执行权威）

> 生效日期：2026-03-05
> 文档级别：后续实现唯一权威
> 关系说明：本文件统一并继承 `.ref/daemon_系统设计方案_ddbc4981.plan.md`（骨架）与 `~/Downloads/daemon充盈血肉.md`（进化控制层）。

---

## 0. 文档治理与权威层级

1. 权威顺序固定为：`daemon_统一方案_v2.md` > `daemon_系统设计方案_ddbc4981.plan.md` > `action_plan.md`/`gap_analysis.md`。
2. 旧方案地位：定义基础架构与边界，属于“平台骨架规范”，继续有效。
3. 充盈血肉地位：定义进化控制平面，属于“能力增强规范”，用于扩展骨架。
4. 冲突裁决规则：
- 同一能力若口径冲突，按 V2 为准。
- 若 V2 未覆盖，按旧方案执行。
- `action_plan` 与 `gap_analysis` 仅作历史证据，不作新增功能判定依据。

## 1. 统一目标与不可妥协原则

1. 北极星目标：`质量 + 稳定` 双目标优先，其次优化延迟与成本。
2. 能力边界：函数/方法用于系统正确运转，不用于限制 Agent 思考空间。
3. 学习原则：策略必须可学习、可解释、可回滚，不允许黑箱替换生产策略。
4. 失败语义：关键链路 fail-closed；非关键链路可降级但必须显式标注 `degraded=true`。
5. MAS 关系：仅内化经验，不复制 MAS 旧架构、旧 API、旧数据路径。

## 2. 旧方案在 V2 的地位（逐章映射）

| 旧方案域 | 在 V2 的地位 | 处理方式 |
|---|---|---|
| 指导思想（LLM 非系统、知识闭环、透明内化） | 保留 | 作为 V2 基础原则 |
| 三层 Fabric（Memory/Playbook/Compass） | 保留 | 作为统一数据基座 |
| 10 个 Spine Routine | 保留并增强 | 增加策略演化职责与状态字段 |
| OpenClaw/Temporal 边界 | 保留 | Agent 执行归 OpenClaw，治理归 Daemon |
| Console API 基集 | 保留并扩展 | 新增 strategies/semantics/model-policy |
| `task_type` 主入口 | 降级为兼容字段 | 主入口升级为 `semantic_fingerprint + intent_contract` |
| Gate/replay 机制 | 保留并细化 | 纳入统一失败语义与发布治理 |

## 3. 统一架构（骨架 + 进化控制层）

### 3.1 三层统一模型

1. Semantic Layer（开放语义层）
- 输入用户目标，输出 `semantic_fingerprint` 与 `intent_contract`。
- 不要求先命中固定 `task_type`。

2. Strategy Layer（策略演化层）
- 每个语义簇维护 1 个 `champion` 与最多 3 个 `challenger`。
- 使用目标函数与置信度规则做晋升/降级。

3. Execution Layer（执行层）
- Temporal + OpenClaw 执行能力图。
- Router 通过 **Weave 机制**将语义意图动态编织为可执行 DAG（Weave Plan）。
- Spine/Fabric 记录证据并驱动下一轮策略更新。

#### Weave 机制定义

**Weave** 是 Daemon 的动态执行图规划机制，不依赖任何第三方图框架（非 Python langgraph 库）。

- **核心职责**：Router agent 基于 `semantic_fingerprint` 与 `intent_contract`，调用 `router_weave_plan` skill 动态生成步骤 DAG（Weave Plan JSON）。
- **与 `semantic_to_capability_graph()` 的关系**：`semantic_to_capability_graph()` 完成语义→能力图的高层映射；Weave 在此之后生成具体可执行的步骤序列（agent、instruction、depends_on、shard 合同）供 Temporal 消费。两者串联，不互相替代。
- **学习闭环**：Spine.learn 提炼执行证据 → 写入 Playbook → Spine.relay 导出到 `workspace/router/memory/weave_patterns/` → Router 下次规划时读取，实现 Weave Plan 自我演化。
- **命名规范**：所有相关 skill 以 `weave` 为前缀（`router_weave_plan`、`router_weave_revise`）；学习模式存储目录统一为 `weave_patterns/`。禁止在新代码中使用 `langgraph` 命名。

### 3.2 端到端数据流（固定实现顺序）

1. `/submit` 接收请求并做 fail-closed 前置校验。
2. `router_intake` 产出 `semantic_fingerprint`、`intent_contract`。
3. `semantic_to_capability_graph()` 生成能力图；Router `router_weave_plan` skill 产出具体 Weave Plan。
4. Dispatch 读取 champion 策略并注入参数（模型、超时、重试、预算、质量合同）。
5. Temporal 执行；Worker 通过事件桥回传结构化事件。
6. `spine.record` 写评估与 trace 摘要。
7. `spine.witness` 聚合全谱证据；`spine.learn` 产候选；`spine.judge` 做晋升/降级。
8. `spine.relay` 回写 `semantic_snapshot`、`strategy_snapshot`、`runtime_hints` 给 Agent 与服务层。

## 4. 功能实现细则（可直接编码）

### 4.1 Semantic Layer

1. 请求入参升级（`POST /submit`）
- 新增：
  - `intent_contract.objective`
  - `intent_contract.constraints`
  - `intent_contract.acceptance`
  - `semantic_fingerprint`（可选，允许调用方直传）
- `task_type` 保留兼容，不作为决策主键。

2. 语义指纹生成
- 先走确定性解析（关键词、风险词、产物类型、时效性）。
- 缺失槽位再走 Cortex 结构化补全。
- Cortex 不可用时保留确定性结果并标注 `semantic_confidence=low`。

3. 能力图映射
- 读取 `config/semantics/capability_catalog.json` 与 `mapping_rules.json`。
- DAG 节点必须附带 `capability_id` 与 `quality_contract_id`。
- 映射失败直接返回 `semantic_mapping_failed`，不得回退为伪 `task_type`。

### 4.2 Strategy Layer

1. 数据实体（Playbook/State）
- `semantic_clusters`
- `strategy_candidates`
- `strategy_experiments`
- `strategy_promotions`

2. 生命周期
- `candidate -> shadow -> challenger -> champion -> retired`
- 每次状态变更必须写 `state/telemetry/strategy_events.jsonl`。

3. 目标函数
- `global_score = 0.45*quality + 0.35*stability + 0.10*latency + 0.10*cost`
- 每次评估必须落 `global_score_components`，不可只写总分。

4. 晋升条件（默认）
- `quality >= champion + 3`
- `stability >= champion - 1`
- `latency` 不劣于 `+20%`
- `cost` 不劣于 `+25%`
- `confidence >= 95%`

5. 降级条件（默认）
- 连续两个窗口显著劣化则自动回退冠军。
- 回退后写 `promotion_decision=rollback_auto` 与原因码。

### 4.3 Model Control Plane

1. 配置文件
- `config/model_registry.json` — 别名 → provider/model_id 映射，含上下文窗口与能力注记
- `config/model_policy.json` — 路由策略：by_capability / by_semantic_cluster / by_risk_level / agent_model_map

2. 路由维度（优先级由高到低）
- `by_capability`：Spine routine 级别路由（witness → analysis，quality_gate → review，code_execute → qwen）
- `by_semantic_cluster`：任务簇级别路由（clst_dev_project → qwen，clst_knowledge_synthesis → glm）
- `by_risk_level`：风险级别路由（high → review，medium → analysis，low → fast）
- `agent_model_map`：OpenClaw agent 静态默认，与 openclaw.json 保持同步

3. 确定的模型别名与分配

| 别名 | Provider | 模型 | 负责 Agent / 场景 |
|---|---|---|---|
| `fast` | MiniMax | MiniMax-M2.5 | router / collect / build / apply — 编排与高频 ops |
| `analysis` | DeepSeek | deepseek-reasoner (R1) | analyze — witness / learn / distill / clst_research_report |
| `review` | Qwen | qwen-max | review — quality_gate_hard / review_mentor_rubric |
| `qwen` | Qwen | qwen-max | opencode 子进程 — clst_dev_project 实际代码生成 |
| `glm` | 智谱 | glm-z1-flash | render — 双语渲染 / clst_knowledge_synthesis |
| `fallback` | MiniMax | MiniMax-M2.5 | 任意 provider 不可用时的兜底 |

**opencode 子进程**独立于 OpenClaw agent，模型配置位于 `~/.config/opencode/opencode.json`，使用 `qwen` 别名（qwen-max）。

4. 统一别名约定
- Cortex 与 OpenClaw 使用同一模型意图别名，禁止同策略在两层使用不同 provider 语义。
- `review` 与 `qwen` 别名当前均指向 qwen-max，未来可独立演化。

5. 预算与熔断
- 各 provider 每日 token 限额写入 Compass（minimax 200万，qwen 100万，deepseek/zhipu 各 50万）。
- 命中熔断触发 `provider_budget_exceeded`，按 fallback_chain 顺序切换：minimax → qwen → zhipu → deepseek。
- 回退不可伪成功，必须携带 `fallback_chain` 字段。

### 4.4 执行与质量治理

1. 质量门升级
- 从静态阈值升级为“语义簇合同 + 漂移检测”。
- 合同定义存放在 `config/semantics/quality_contracts/*.json` 并版本化。

2. 关键失败追溯
- 关键失败必须携带：
  - `trace_id`
  - `strategy_id`
  - `semantic_fingerprint`
- 任意缺失视为治理缺陷。

3. Replay/Gate 统一
- Gate 恢复后 replay 仅处理窗口内 queued 任务。
- 过窗任务标记 `expired`，不得无限重放。

### 4.5 发布治理（沙箱 -> 影子 -> 生产）

1. 沙箱阶段
- 新策略仅在回放或隔离任务运行，不影响生产结果。

2. 影子阶段
- 默认 10% 影子流量。
- 生成与冠军策略对照报告并落审计。

3. 生产阶段
- 必须满足晋升门槛与审计完整性。
- 切换自动生成回滚点。

## 5. 公共 API / 接口 / 类型变更

### 5.1 API 变更

| API | 变更 |
|---|---|
| `POST /submit` | 支持 `intent_contract` 与 `semantic_fingerprint`；`task_type` 仅兼容 |
| `GET /tasks/{task_id}` | 返回 `semantic_cluster`, `strategy_id`, `strategy_stage`, `global_score_components` |
| `GET /console/strategies` | 新增，列 champion/challenger 与风险 |
| `POST /console/strategies/{id}/promote` | 新增，人工或系统闸门晋升 |
| `POST /console/strategies/{id}/rollback` | 新增，回滚到上一冠军 |
| `GET /console/semantics` | 新增，查看语义簇与映射规则 |
| `PUT /console/model-policy` | 新增，更新模型路由与预算 |
| `GET /console/model-usage` | 新增，按语义簇/能力/provider 聚合 |

### 5.2 核心类型（新增）

- `SemanticFingerprint`
- `IntentContract`
- `StrategyCandidate`
- `ExperimentRun`
- `PromotionDecision`
- `GlobalScoreBreakdown`

### 5.3 错误码（新增）

- `semantic_mapping_failed`
- `strategy_guard_blocked`
- `promotion_confidence_low`
- `provider_budget_exceeded`
- 统一保留 `temporal_unavailable`

## 6. 数据层与存储变更

1. `compass.db`
- 新增目标函数、预算策略、模型策略版本表。

2. `playbook.db`
- 新增候选策略、实验结果、晋升历史表。

3. `state/` 快照
- `semantic_snapshot.json`
- `strategy_snapshot.json`
- `model_policy_snapshot.json`

4. 审计日志
- 强制落盘：`state/telemetry/strategy_events.jsonl`

5. 事件桥协议
- 固定键：`event_id,event,payload,source,created_utc,consumed_utc,status`
- 消费语义：`offset + pending + acked`

## 7. Fail-Closed 与 Degrade 分层矩阵

| 链路 | 策略 | 规则 |
|---|---|---|
| submit 前置校验失败 | Fail-Closed | 直接失败并返回明确错误码 |
| Temporal 不可达 | Fail-Closed | 禁止伪 `running` |
| semantic 映射失败 | Fail-Closed | 禁止回退伪 `task_type` |
| Delivery 结构质量门失败 | Fail-Closed | 不允许写成功 outcome |
| witness/learn 的 LLM 调用失败 | Degrade | 走确定性路径并标注 degraded |
| PDF 生成失败 | Degrade | 不阻塞主交付，记录告警 |
| Telegram 推送失败 | Degrade | 任务成功不回滚，记录重试与告警 |

## 8. 验收矩阵（全部通过才算完成）

1. 新需求不命中既有 `task_type`，系统仍能完成交付。
2. 同语义簇学习后出现策略替换，质量与稳定提升且可解释。
3. 挑战策略劣化自动回退冠军，业务不中断。
4. 影子实验不污染生产结果，并有完整对照记录。
5. Portal/CLI/Telegram/Console 展示同一状态机与同一时间字段。
6. 关键失败可追溯到 `trace_id + strategy_id + semantic_fingerprint`。
7. 模型供应商不可用时按策略回退，不出现伪成功。
8. 质量门失败必须 fail-closed，不得自动补写伪完成。
9. Gate 恢复后 replay 收敛，无幽灵队列。
10. 语义映射规则改动后可一键回滚。
11. 策略晋升/降级都具备审计记录与责任主体。
12. 系统重启后策略与 trace 可恢复查询。

## 9. 运行依赖与启动顺序

1. 依赖就绪
- Python venv
- Temporal Server
- Daemon 专用 OpenClaw Gateway
- 至少一个可用模型 key

2. 启动顺序
- OpenClaw Gateway -> Worker -> API -> 可选 Telegram Adapter

3. 自启动要求
- 仅允许 daemon 相关 plist/service 常驻。
- mas 旧 plist 必须清除并禁用。

4. 观测基线
- `/health`
- `/console/overview`
- `/console/traces`
- `/console/model-usage`

## 10. 交接包规范（给下一执行者）

1. ADR 至少 12 条，覆盖语义层、策略层、模型层、发布层。
2. API 变更与兼容说明。
3. 数据迁移与回滚说明。
4. 验收矩阵与证据模板。
5. 未完成项登记模板（原因、影响、下一步）。
6. 外部测试清理记录（仅 daemon 外产物）。

## 11. 默认值与假设

1. 保留现有 4 类任务作为初始语义簇，不作为边界上限。
2. 探索预算默认 15%。
3. 影子流量默认 10%。
4. 全谱证据学习默认开启。
5. 后续开发以本 V2 为唯一口径。

---

## 12. 知识质量：来源区分

### 12.1 source_type 枚举

Memory unit 必须携带 `source_type` 与 `source_agent` 两个字段：

| source_type | 含义 | 可信度 |
|---|---|---|
| `empirical` | 从真实任务执行中观察到的 | 最高 |
| `synthetic` | distill/witness LLM 生成 | 中（有幻觉风险）|
| `collected` | collect agent 从外部抓取 | 低（质量不可控）|
| `human` | 用户直接输入 | 权威但主观 |

`source_agent` 记录写入该 unit 的 agent id（如 `collect`、`spine.distill`）。

### 12.2 来源规则

- **Router 引用**：优先引用 `empirical` 和 `human`，`collected` 仅在无更高质量来源时使用。
- **tend/librarian TTL**：`collected` 类 unit 的有效窗口比 `empirical` 短 50%。
- **distill dedup**：两条内容相近的 unit 合并时，`empirical` 胜 `synthetic`；`human` 胜一切。
- **暖机评估**：来源字段是判断"系统学到了什么"的必要依据，无 source 字段的 unit 视为 synthetic。

### 12.3 实现位置

- `fabric/memory.py` SCHEMA：`methods` 与 `units` 表新增 `source_type TEXT` + `source_agent TEXT`
- `_init_db()` 用 ALTER TABLE 做迁移（已有模式）
- `store()` 与 `update()` 接口增加对应参数

---

## 13. 归档与清理制度

### 13.1 三级 GC（Memory + Weave 统一）

| 阶段 | 触发条件 | 动作 |
|---|---|---|
| **Soft-archive** | judge/librarian 评估后 | status='archived'，不参与 query |
| **Cold export** | archived 满 7 天且未被引用 | 导出 JSONL → 上传 Google Drive → 从 SQLite 删除 |
| **Hard delete（本地）** | cold export 后本地 JSONL 满 30 天 | 删除本地 JSONL 文件；Drive 端保留时间用户自行在 Drive 设置 |

### 13.2 Google Drive 上传

- 执行者：`librarian` routine 调用 apply agent 的 `google_drive_upload` skill（或内置 google 工具）
- 上传路径：Drive 内 `daemon/archive/<year>/<month>/` 结构
- 上传内容：JSONL 文件，含原始 unit/pattern 数据与元数据
- 上传失败：降级为仅本地保留，记录 `archive_upload_failed` 告警，不阻断主流程

### 13.3 Memory 容量上限

- `total_units_cap` 默认 10,000（写入 Compass）
- 超限触发 `memory_pressure` nerve 事件，librarian 收到后优先清理 `collected` 类和最老的 `synthetic`
- Weave patterns 上限 200（已实现），Memory units 上限 10,000，共用同一 pressure 触发机制

### 13.4 任务产出物清理（outcome GC）

Memory/Weave GC 管知识层，outcome GC 管任务产出物层，两套机制独立运行。

| 阶段 | 时间 | 本地 | Drive | Portal 可见 |
|---|---|---|---|---|
| 活跃 | 0–7 天 | 完整 | — | 是，完整输出 |
| Drive 归档 | 7–30 天 | 本地删除 | 已上传 | 是，按需从 Drive 拉取 |
| Drive 保留 | 30 天–6 个月 | — | 保留 | 是，按需从 Drive 拉取 |
| 完全清理 | 6 个月后 | — | 删除 | 否，从 Portal 消失 |

- outcome index（`state/outcomes/index.json`）与任务记录同步清理，6 个月后删除对应条目
- 学习效果在任务完成时已写入 playbook，清理不影响已学到的内容
- 6 个月阈值写入 Compass，可配置

### 13.4.1 Drive 目录结构

Drive 内两个顶级目录，职责严格分离：

```
daemon/
  outcomes/                              ← 用户产出，结构对人友好，用户可直接浏览
    YYYY-MM/
      YYYY-MM-DD HH:MM <任务标题>/        ← 含时间，永不冲突，标题由 render agent 从内容提取
        <任务标题>（中文）.md
        <Task Title> (English).md

  archive/                               ← 系统内部，用户无需打开
    memory/YYYY-MM/                      ← memory units JSONL
    weave/YYYY-MM/                       ← weave patterns JSONL
```

规则：
- **零内部 ID、零系统参数**出现在 outcomes/ 路径和文件名中
- 目录名含时间（HH:MM），天然唯一，无需去重逻辑；文件名仅含标题，不带时间
- 评分、元数据等内部数据**不上传 Drive**，仅保留在本地 result.json 和 playbook
- 系统内部通过 outcome index 的 `task_id → drive_path` 映射定位文件；用户不感知此映射

### 13.5 实现位置

- `spine/routines.py`：`librarian()` 新增 `_cold_export_memory()` 与 `_cleanup_local_jsonl()` helper；新增 `_cleanup_outcomes()` helper（扫描 outcome index，清理 6 个月以上条目）
- `spine/nerve.py`：新增 `memory_pressure` 事件类型
- `config/spine_registry.json`：librarian 的 `nerve_triggers` 加入 `memory_pressure`
- apply agent `TOOLS.md`：新增 `google_drive_upload` skill 说明

---

## 14. 任务准入与并发隔离

### 14.1 Budget 预检（Pre-flight Check）

Router 生成 Weave Plan 前必须先做 provider budget 预检：

1. 查询 Compass 中各 provider 当日剩余配额
2. 若 primary provider 余量不足：按 `fallback_chain` 顺序切换（minimax → qwen → zhipu → deepseek）
3. 所有 provider 余量均不足：任务进入 `queued` 状态，Telegram 告警，不得伪装成 running
4. 预检结果写入 plan 的 `provider_routing` 字段，供后续步骤参照

失败码：`provider_budget_insufficient`（与已有 `provider_budget_exceeded` 区分：前者是准入拒绝，后者是执行中触发）。

### 14.2 Spine 例程逻辑隔离

- `distill` / `learn` 在运行开始时对相关数据做 snapshot，处理过程中不再读最新状态
- 避免与并发任务写操作产生逻辑冲突（SQLite WAL 保护物理一致性，不保护逻辑一致性）
- snapshot 写入临时文件（`state/tmp/spine_<routine>_<ts>.json`），routine 结束后清理

---

## 15. 自适应调度与自我升级

### 15.1 Adaptive 调度实现

`spine_registry.json` 中声明 `adaptive:4h:2h-12h` 的例程（witness/learn）实现动态间隔：

- **调度因子**：gate 状态（open/closed）+ 当前任务队列深度
- **规则**：
  - 队列空 + gate open → 缩短间隔（趋向 2h 下限）
  - 队列繁忙（>3 个 running）→ 拉长间隔（趋向 12h 上限）
  - gate closed → 暂停，等 gate 恢复后重置为默认间隔
- **实现位置**：`services/scheduler.py`，spine routine 注册时传入 adaptive 计算函数

### 15.2 自我升级边界

`spine.learn` 产出的 `skill_evolution_proposals.json` 处理规则：

| 改动类型 | 允许模式 | 审批要求 |
|---|---|---|
| SKILL.md / SOUL.md 内容 | sandbox 自动尝试，测试通过后写回 | 无需人工，Telegram 告知 |
| Python 代码（activities/routines 等） | 仅写入 proposals，不自动执行 | 必须人工审批 |
| config/*.json | sandbox 自动尝试，测试通过后写回 | 无需人工，Telegram 告知 |

proposals 积累 ≥5 条时，Telegram 推送摘要给用户，用户回复后系统采纳或忽略。

---

## 16. 任务规模分级（Pulse / Thread / Campaign）

### 16.0 三级命名

| 级别 | 名称 | 隐喻 | plan.task_scale 值 |
|---|---|---|---|
| 1 | **Pulse** | 单次脉冲，原子级，快进快出 | `pulse` |
| 2 | **Thread** | 一条线索，多步骤但单次 workflow 内完成 | `thread` |
| 3 | **Campaign** | 持续战线，多 milestone，用户逐步参与 | `campaign` |

### 16.1 任务规模判定

Router 在生成 Weave Plan 前，先做规模评估（analyze 第一步 complexity probe）：

| task_scale | 判断依据 | 执行模式 |
|---|---|---|
| `pulse` | estimated_phases ≤ 2，estimated_hours ≤ 1 | 标准单步，快速交付，完成后一次性用户评价 |
| `thread` | estimated_phases ≤ 4，estimated_hours ≤ 4 | 多步 DAG，单次 workflow 内完成，完成后一次性用户评价 |
| `campaign` | estimated_phases > 4 或 estimated_hours > 4 | 多 milestone，per-milestone 评价，见 §17 |

规模评估结果写入 `plan.task_scale`，不得跳过。

### 16.2 中间产出 Checkpoint 持久化

每个 activity 完成后，中间产出必须写入 `state/runs/<task_id>/steps/<step_id>/output.json`，不只存 Temporal activity result cache。Worker 重启后可从文件系统恢复，无需重跑已完成步骤。

### 16.3 Context Window 容量检查

render 步骤开始前，做 context window 预检：

- 统计所有上游步骤产出的 token 估算
- 若超过目标模型 context window 的 70%：先对各步骤输出做结构化摘要压缩，再传入 render
- 压缩动作由 analyze agent 执行，压缩后附原始产出路径供溯源
- 不允许静默截断

---

## 17. Campaign 模式

### 17.1 触发条件

`plan.task_scale == 'campaign'` 时自动进入 Campaign 模式，无需用户显式声明。

### 17.2 Milestone 定义

Milestone 按**语义相变点**划分，而非按大小机械切分——即产出的性质发生转变的地方（如从"信息采集"到"论点分析"）。

每个 milestone 必须满足：
- 有独立可评价的产出（不是"完成了一半"的中间状态）
- 自身复杂度在 Thread 级别以内（可在单次 workflow 内完成）
- 有明确的输入依赖（依赖哪些前序 milestone 的产出）

Milestone 列表由 analyze agent 在 Phase 0 规划阶段生成，每条包含：`名称 + 预期产出描述 + 输入依赖`。用户在确认计划表时看到的就是这个列表。

### 17.3 执行流程

```
Phase 0  规划（analyze complexity probe）
  → 生成结构化计划（milestone 列表）
  → Telegram 推送计划表 → 等用户一次性确认（唯一主动门控点）

Phase 1..N  逐 milestone 执行（每个 milestone = Thread 级 workflow）
  执行完成
  → step 1: review rubric 评分（系统自动）
      客观不通过 → 直接 rework，不打扰用户（最多 2 次）
      超出 rework 预算 → Telegram 告警，campaign 暂停等人工介入
  → step 2（仅客观通过后）: generate_user_feedback_survey → Telegram/Portal 推送
      用户满意 → Telegram 播报进度，自动开始下一个 milestone
      用户不满意 → rework（用户反馈作为 hint，最多 1 次）
      用户不满意且已 rework → Telegram 告警，暂停等人工介入

Phase N+1  Synthesis（强制，不可省略）
  analyze + review → 连贯性检查 + 最终质量分
  → Telegram 推送最终评价问卷（用户对整体 campaign 评价）
  render → 统一交付物
  apply → 交付 + Telegram 完成通知
```

### 17.4 Campaign State 结构

```
state/campaigns/<campaign_id>/
  manifest.json          # 计划表、milestone 列表、当前 phase、用户确认记录
  milestones/
    <n>/
      result.json        # 执行结果、review 评分、用户反馈、最终决策、rework 次数
```

### 17.5 评分体系（三层，严格先后）

| 顺序 | 层 | 执行者 | 时机 | 用途 |
|---|---|---|---|---|
| 1 | 系统客观评分 | review agent rubric | milestone 完成后立即 | 客观质量门控，不过不推问卷 |
| 2 | 用户主观评价 | `generate_user_feedback_survey` | 客观通过后推送 | 主观验收，即时决策 + 长期学习 |
| 3 | 连贯性检查 | synthesis（analyze + review）| campaign 结束 | 跨 milestone 一致性 |

用户反馈双写：
- ① 写入 `milestones/<n>/result.json`，影响即时 rework 决策
- ② 调用 `playbook.evaluate()`，用户不满意强制记为 `fail`（无视客观评分）

用户对整体 campaign 的最终评价写入 `fabric/memory.py` 作为 `human` 来源 Memory unit（最高质量学习输入）。

### 17.6 Fail-Closed 规则

- milestone 客观评分超出 rework 预算（默认 2 次）→ campaign 暂停，Telegram 告警
- 用户评价不满意超出 rework 预算（默认 1 次）→ campaign 暂停，Telegram 告警
- synthesis 质量门失败 → 不交付，Telegram 告警
- 用户拒绝计划确认 → campaign 取消，状态写 `cancelled`

---

## 18. Agent 扩容策略

### 18.1 横向扩容

**标准做法：调整 `maxConcurrent`**，不新增命名 agent。

同一 agent 的并发 session 共享 SOUL/TOOLS/fabric 下发的记忆，行为完全一致，是真正的无状态横向扩容。修改点：
- `openclaw.json`：对应 agent 的 `maxConcurrent`
- `services/dispatch.py` `_agent_limits()`：对应 agent 的并发配额

**当前默认并发配额**：

| agent | maxConcurrent | 说明 |
|---|---|---|
| collect | 8 | IO 密集，可高并发 |
| analyze | 4 | 最贵模型，限流保护成本 |
| build | 2 | opencode 子进程耗时不可预测 |
| review | 2 | gate 角色，不需高吞吐 |
| render | 2 | 生成密集，适度并发 |
| apply | 1 | 不可逆操作，必须序列化 |
| router | 1 | 入口串行，避免决策冲突 |
| spine | 2 | 后台维护，不在关键路径 |

### 18.2 专化扩容

**仅在需要不同专化时引入新命名 agent**，例如：
- 不同模型（如 `analyze-code` 用 Qwen，`analyze-research` 用 DeepSeek R1）
- 不同 SOUL/TOOLS 配置（不同任务域的行为规范差异大）

当前阶段不需要专化扩容，标准并发配额已满足需求。

---

## 19. 用户反馈闭环

### 19.1 问卷生成原则

`generate_user_feedback_survey` skill 由 review agent 执行，生成本次专属问卷：

- **输入**：milestone 产出摘要 + cluster 类型 + 评分维度锚点
- **输出**：3-5 个动态生成的自然语言问题 + 量化选项
- **锚点维度**（方向固定，具体问题动态生成）：
  1. 产出是否符合预期意图
  2. 质量/深度是否足够
  3. 有无明显遗漏或偏差
  4. 是否需要调整下一个 milestone 的方向

问卷通过 Portal 或 Telegram 推送，不使用固定模板，每次问题内容随产出内容不同。

### 19.2 反馈写入规则

用户回答后：
1. 写入 `milestones/<n>/result.json`（即时决策）
2. 调用 `playbook.evaluate()`，`outcome=pass/fail` 由用户满意度决定（即使 review rubric 客观通过，用户不满意也记为 fail）
3. 用户反馈的文本 hint 写入下一步 rework 的 instruction，不丢弃

### 19.3 整体质量学习位置

用户对整体 campaign 的最终评分（synthesis 结束后）写入 `fabric/memory.py` 作为一条 `human` 来源的 Memory unit，摘要格式：任务类型 + 关键策略 + 用户评分 + 主要反馈。这是最高质量的学习输入。
