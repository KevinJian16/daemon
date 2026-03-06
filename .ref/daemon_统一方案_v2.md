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
| Console API 基集 | 保留并扩展 | 新增 strategies/semantics/model-routing |
| `run_type` 执行模板键 | 保留并重定位 | 主入口升级为 `semantic_spec + intent_contract`；执行模板键统一用 `run_type` |
| Gate/replay 机制 | 保留并细化 | 纳入统一失败语义与发布治理 |

## 3. 统一架构（骨架 + 进化控制层）

### 3.1 三层统一模型

1. Semantic Layer（开放语义层）
- 输入用户目标，输出 `semantic_spec` 与 `intent_contract`。
- 不要求先命中固定 `run_type`。

2. Strategy Layer（策略演化层）
- 每个语义簇维护 1 个 `champion` 与最多 3 个 `challenger`。
- 使用目标函数与置信度规则做晋升/降级。

3. Execution Layer（执行层）
- Temporal + OpenClaw 执行能力图。
- Router 通过 **Weave 机制**将语义意图动态编织为可执行 DAG（Weave Plan）。
- Spine/Fabric 记录证据并驱动下一轮策略更新。

#### Weave 机制定义

**Weave** 是 Daemon 的动态执行图规划机制，不依赖任何第三方图框架（非 Python langgraph 库）。

- **核心职责**：Router agent 基于 `semantic_spec` 与 `intent_contract`，调用 `router_weave_plan` skill 动态生成步骤 DAG（Weave Plan JSON）。
- **与 `semantic_to_capability_graph()` 的关系**：`semantic_to_capability_graph()` 完成语义→能力图的高层映射；Weave 在此之后生成具体可执行的步骤序列（agent、instruction、depends_on、shard 合同）供 Temporal 消费。两者串联，不互相替代。
- **学习闭环**：Spine.learn 提炼执行证据 → 写入 Playbook → Spine.relay 导出到 `workspace/router/memory/weave_patterns/` → Router 下次规划时读取，实现 Weave Plan 自我演化。
- **命名规范**：所有相关 skill 以 `weave` 为前缀（`router_weave_plan`、`router_weave_revise`）；学习模式存储目录统一为 `weave_patterns/`。禁止在新代码中使用 `langgraph` 命名。

### 3.2 端到端数据流（固定实现顺序）

1. `/submit` 接收请求并做 fail-closed 前置校验。
2. `router_intake` 产出 `semantic_spec`、`intent_contract`。
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
  - `semantic_spec`（可选，允许调用方直传）
- `run_type` 为执行模板键，作为模板选择键独立保留。

2. 语义规格生成（Semantic Spec）
- 先走确定性解析（关键词、风险词、产物类型、时效性）。
- 缺失槽位再走 Cortex 结构化补全。
- Cortex 不可用时保留确定性结果并标注 `semantic_confidence=low`。

3. 能力图映射
- 读取 `config/semantics/capability_catalog.json` 与 `mapping_rules.json`。
- DAG 节点必须附带 `capability_id` 与 `quality_contract_id`。
- 映射失败直接返回 `semantic_mapping_failed`，不得回退为伪 `run_type`。

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
- `config/model_routing.json` — 路由策略：by_capability / by_semantic_cluster / by_risk_level / agent_model_map

2. 路由维度（优先级由高到低）
- `by_capability`：Spine routine 级别路由（witness → analysis，quality_gate → review，code_execute → qwen）
- `by_semantic_cluster`：语义簇级别路由（clst_dev_project → qwen，clst_knowledge_synthesis → glm）
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
  - `semantic_spec`
- 任意缺失视为治理缺陷。

3. Replay/Gate 统一
- Gate 恢复后 replay 仅处理窗口内 queued 运行。
- 过窗运行标记 `expired`，不得无限重放。

### 4.5 发布治理（沙箱 -> 影子 -> 生产）

1. 沙箱阶段
- 新策略仅在回放或隔离运行中执行，不影响生产结果。

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
| `POST /submit` | 支持 `intent_contract` 与 `semantic_spec`；执行模板键使用 `run_type` |
| `GET /runs/{run_id}` | 返回 `semantic_cluster`, `strategy_id`, `strategy_stage`, `global_score_components` |
| `GET /console/strategies` | 新增，列 champion/challenger 与风险 |
| `POST /console/strategies/{id}/promote` | 新增，人工或系统闸门晋升 |
| `POST /console/strategies/{id}/rollback` | 新增，回滚到上一冠军 |
| `GET /console/semantics` | 新增，查看语义簇与映射规则 |
| `PUT /console/model-routing` | 新增，更新模型路由与预算 |
| `GET /console/model-usage` | 新增，按语义簇/能力/provider 聚合 |

### 5.2 核心类型（新增）

- `SemanticSpec`
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
- 新增目标函数、预算策略、模型路由版本表。

2. `playbook.db`
- 新增候选策略、实验结果、晋升历史表。

3. `state/` 快照
- `semantic_snapshot.json`
- `strategy_snapshot.json`
- `model_routing_snapshot.json`

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
| semantic 映射失败 | Fail-Closed | 禁止回退伪 `run_type` |
| Delivery 结构质量门失败 | Fail-Closed | 不允许写成功 outcome |
| witness/learn 的 LLM 调用失败 | Degrade | 走确定性路径并标注 degraded |
| PDF 生成失败 | Degrade | 不阻塞主交付，记录告警 |
| Telegram 推送失败 | Degrade | 运行成功不回滚，记录重试与告警 |

## 8. 验收矩阵（全部通过才算完成）

1. 新需求不命中既有 `run_type`，系统仍能完成交付。
2. 同语义簇学习后出现策略替换，质量与稳定提升且可解释。
3. 挑战策略劣化自动回退冠军，业务不中断。
4. 影子实验不污染生产结果，并有完整对照记录。
5. Portal/CLI/Telegram/Console 展示同一状态机与同一时间字段。
6. 关键失败可追溯到 `trace_id + strategy_id + semantic_spec`。
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

1. 保留现有 4 类初始运行模式作为初始语义簇，不作为边界上限。
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
| `empirical` | 从真实运行执行中观察到的 | 最高 |
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

### 13.4 运行产出物清理（outcome GC）

Memory/Weave GC 管知识层，outcome GC 管运行产出物层，两套机制独立运行。

| 阶段 | 时间 | 本地 | Drive | Portal 可见 |
|---|---|---|---|---|
| 活跃 | 0–7 天 | 完整 | — | 是，完整输出 |
| Drive 归档 | 7–30 天 | 本地删除 | 已上传 | 是，按需从 Drive 拉取 |
| Drive 保留 | 30 天–6 个月 | — | 保留 | 是，按需从 Drive 拉取 |
| 完全清理 | 6 个月后 | — | 删除 | 否，从 Portal 消失 |

- outcome index（`state/outcomes/index.json`）与运行记录同步清理，6 个月后删除对应条目
- 学习效果在运行完成时已写入 playbook，清理不影响已学到的内容
- 6 个月阈值写入 Compass，可配置

### 13.4.1 Drive 目录结构

Drive 内两个顶级目录，职责严格分离：

```
daemon/
  outcomes/                              ← 用户产出，结构对人友好，用户可直接浏览
    YYYY-MM/
      YYYY-MM-DD HH:MM <运行标题>/        ← 含时间，永不冲突，标题由 render agent 从内容提取
        <运行标题>（中文）.md
        <Run Title> (English).md

  archive/                               ← 系统内部，用户无需打开
    memory/YYYY-MM/                      ← memory units JSONL
    weave/YYYY-MM/                       ← weave patterns JSONL
```

规则：
- **零内部 ID、零系统参数**出现在 outcomes/ 路径和文件名中
- 目录名含时间（HH:MM），天然唯一，无需去重逻辑；文件名仅含标题，不带时间
- 评分、元数据等内部数据**不上传 Drive**，仅保留在本地 result.json 和 playbook
- 系统内部通过 outcome index 的 `run_id → drive_path` 映射定位文件；用户不感知此映射

### 13.5 实现位置

- `spine/routines.py`：`librarian()` 新增 `_cold_export_memory()` 与 `_cleanup_local_jsonl()` helper；新增 `_cleanup_outcomes()` helper（扫描 outcome index，清理 6 个月以上条目）
- `spine/nerve.py`：新增 `memory_pressure` 事件类型
- `config/spine_registry.json`：librarian 的 `nerve_triggers` 加入 `memory_pressure`
- apply agent `TOOLS.md`：新增 `google_drive_upload` skill 说明

---

## 14. 运行准入与并发隔离

### 14.1 Budget 预检（Pre-flight Check）

Router 生成 Weave Plan 前必须先做 provider budget 预检：

1. 查询 Compass 中各 provider 当日剩余配额
2. 若 primary provider 余量不足：按 `fallback_chain` 顺序切换（minimax → qwen → zhipu → deepseek）
3. 所有 provider 余量均不足：运行进入 `queued` 状态，Telegram 告警，不得伪装成 running
4. 预检结果写入 plan 的 `provider_routing` 字段，供后续步骤参照

失败码：`provider_budget_insufficient`（与已有 `provider_budget_exceeded` 区分：前者是准入拒绝，后者是执行中触发）。

### 14.2 Spine 例程逻辑隔离

- `distill` / `learn` 在运行开始时对相关数据做 snapshot，处理过程中不再读最新状态
- 避免与并发运行写操作产生逻辑冲突（SQLite WAL 保护物理一致性，不保护逻辑一致性）
- snapshot 写入临时文件（`state/tmp/spine_<routine>_<ts>.json`），routine 结束后清理

---

## 15. 自适应调度与自我升级

### 15.1 Adaptive 调度实现

`spine_registry.json` 中声明 `adaptive:4h:2h-12h` 的例程（witness/learn）实现动态间隔：

- **调度因子**：gate 状态（open/closed）+ 当前运行队列深度
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

proposals 积累 ≥5 条时，Telegram 推送摘要给用户，用户打开 Portal 对话页回复意见后系统采纳或忽略（Telegram 仅推通知，不接受输入）。

**Skill 改动生效前必须通过 §21 定义的 Skill Benchmark 验证，不得跳过。**

---

## 16. 运行规模分级（Pulse / Thread / Campaign）

### 16.0 三级命名

| 级别 | 名称 | 隐喻 | plan.work_scale 值 |
|---|---|---|---|
| 1 | **Pulse** | 单次脉冲，原子级，快进快出 | `pulse` |
| 2 | **Thread** | 一条线索，多步骤但单次 workflow 内完成 | `thread` |
| 3 | **Campaign** | 持续战线，多 milestone，用户逐步参与 | `campaign` |

### 16.1 运行规模判定

Router 在生成 Weave Plan 前，先做规模评估（analyze 第一步 complexity probe）：

| work_scale | 判断依据 | 执行模式 |
|---|---|---|
| `pulse` | estimated_phases ≤ 2，estimated_hours ≤ 1 | 标准单步，快速交付，完成后一次性用户评价 |
| `thread` | estimated_phases ≤ 4，estimated_hours ≤ 4 | 多步 DAG，单次 workflow 内完成，完成后一次性用户评价 |
| `campaign` | estimated_phases > 4 或 estimated_hours > 4 | 多 milestone，per-milestone 评价，见 §17 |

规模评估结果写入 `plan.work_scale`，不得跳过。

### 16.2 中间产出 Checkpoint 持久化

每个 activity 完成后，中间产出必须写入 `state/runs/<run_id>/steps/<step_id>/output.json`，不只存 Temporal activity result cache。Worker 重启后可从文件系统恢复，无需重跑已完成步骤。

### 16.3 Context Window 容量检查

render 步骤开始前，做 context window 预检：

- 统计所有上游步骤产出的 token 估算
- 若超过目标模型 context window 的 70%：先对各步骤输出做结构化摘要压缩，再传入 render
- 压缩动作由 analyze agent 执行，压缩后附原始产出路径供溯源
- 不允许静默截断

---

## 17. Campaign 模式

### 17.1 触发条件

`plan.work_scale == 'campaign'` 时自动进入 Campaign 模式，无需用户显式声明。

### 17.2 Milestone 定义

Milestone 按**语义相变点**划分，而非按大小机械切分——即产出的性质发生转变的地方（如从"信息采集"到"论点分析"）。

每个 milestone 必须满足：
- 有独立可评价的产出（不是"完成了一半"的中间状态）
- 自身复杂度在 Thread 级别以内（可在单次 workflow 内完成）
- 有明确的输入依赖（依赖哪些前序 milestone 的产出）

Milestone 列表由 analyze agent 在 Phase 0 规划阶段生成，每条包含：`名称 + 预期产出描述 + 输入依赖`。用户在确认计划表时看到的就是这个列表。

**结构约束：**
- Milestone 之间严格线性顺序，不引入 DAG / 并行分支
- "同时抓取多个来源"属于单个 milestone 内部的并行 activity，不提升为并行 milestone
- 条件分支通过继续/中止门控（见 §17.3）实现，不做 milestone 级别的 if/else

**Campaign context 传递：**
每个 milestone 完成后，review agent 生成的摘要写入 `manifest.json` 的 `campaign_context` 累积字段。下一个 milestone 执行时，Campaign context 作为额外输入注入其 Weave Plan，使后续 milestone 能在前序产出基础上推进（显式、可追溯）。Memory fabric 负责跨 Campaign 的长期学习，Campaign context 只在当次 Campaign 内传递。

### 17.3 执行流程

```
Phase 0  规划（analyze complexity probe）
  → 生成结构化计划（milestone 列表）
  → Portal 对话框呈现计划表 → 等用户一次性确认（唯一主动门控点）
  → 用户拒绝 → campaign 取消

Phase 1..N  逐 milestone 执行（每个 milestone 行为 = Thread，Campaign 全程常驻运行中页）
  执行中
  → Portal 运行中页显示"执行中 · milestone N/总数"，有取消整个 Campaign 按钮

  执行失败（review 不通过，超出 rework 预算）
  → Telegram 告警"milestone N 执行失败"
  → Portal 运行中页显示 milestone 失败状态，出现**重试 / 中止 Campaign** 按钮
  → 用户选重试 → milestone 重新执行（视为新的执行实例）
  → 用户选中止 → campaign 取消，状态写 `cancelled`
  → 用户不操作 → Campaign 保持暂停，等待人工介入

  执行成功
  → review rubric 评分通过 → 生成 milestone 摘要 → 追加到 manifest.campaign_context
  → milestone 产出写入 Drive
  → Telegram 推送"里程碑 N 完成"通知
  → milestone 独立进入待评价页（行为与 Thread 完全相同）：
      Portal 运行中页同步显示"等待 milestone N 评价 · 剩余 Xh Xm"
      用户在窗口期内评价并选择继续 → 自动开始下一个 milestone
      用户在窗口期内评价并选择中止 → campaign 取消
      窗口期到期无操作 → 自动继续下一个 milestone，Telegram 告知已自动推进

Phase N+1  Synthesis（强制，不可省略）
  analyze + review → 连贯性检查 + 最终质量分
  render → 统一交付物
  apply → 交付 + Telegram 完成通知（用户去 Portal 历史页查看）
```

### 17.4 Campaign State 结构

```
state/campaigns/<campaign_id>/
  manifest.json          # 计划表、milestone 列表、当前 phase、用户确认记录、campaign_context
  milestones/
    <n>/
      result.json        # 执行结果、review 评分、用户反馈、最终决策、rework 次数
```

`manifest.json` 的 `campaign_context` 字段（累积追加，只增不删）：
```json
"campaign_context": [
  {
    "milestone_n": 1,
    "summary": "review agent 生成的简述，含关键发现",
    "drive_links": ["https://drive.google.com/..."],
    "completed_utc": "2026-03-06T10:00:00Z"
  }
]
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

- milestone 执行失败（超出 rework 预算）→ Telegram 告警 → Campaign 暂停 → 用户在 Portal 运行中页选择**重试或中止**
- synthesis 质量门失败 → 不交付，Telegram 告警
- 用户拒绝计划确认 → campaign 取消，状态写 `cancelled`
- 用户在评价窗口期选择中止 → campaign 取消，状态写 `cancelled`
- 用户不操作（窗口期到期）→ 自动继续，**不视为失败**

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
- 不同 SOUL/TOOLS 配置（不同运行域的行为规范差异大）

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

问卷通过 **Portal 待评价页**呈现，不使用固定模板，每次问题内容随产出内容不同。Telegram 仅推完成通知，不推问卷本身。

### 19.2 反馈写入规则

用户回答后：
1. 写入 `milestones/<n>/result.json`（即时决策）
2. 调用 `playbook.evaluate()`，`outcome=pass/fail` 由用户满意度决定（即使 review rubric 客观通过，用户不满意也记为 fail）
3. 用户反馈的文本 hint 写入下一步 rework 的 instruction，不丢弃

### 19.3 整体质量学习位置

用户对整体 campaign 的最终评分（synthesis 结束后）写入 `fabric/memory.py` 作为一条 `human` 来源的 Memory unit，摘要格式：运行类型 + 关键策略 + 用户评分 + 主要反馈。这是最高质量的学习输入。

### 19.4 用户评价对系统校验的影响

用户评价永远是 optional 附加输入：
- 未评价、部分作答、超窗口期——均不影响 run 的 `completed` 状态
- `POST /runs/{run_id}/feedback` 接受 partial payload，无必填约束
- Spine learn 例程遇到空或不完整用户反馈时静默跳过，不报错

**系统内置 review（review agent）与用户评价严格分离**：review agent 是 pipeline 必要步骤，通不过则进入 rework/fail 流程，与用户评价无关。

---

## 19A. 评价窗口期机制（Eval Window）

### 19A.1 规则

run 执行完成 → 进入评价窗口期（`awaiting_eval` 状态）→ 窗口期内用户可在 Portal 做完整评价：

| 情形 | 结果 |
|---|---|
| 用户在窗口期内完成评价 | 评价数据写入 Memory，run 立即 `completed` |
| 用户在窗口期内部分回答 | 已回答部分写入，run 立即 `completed` |
| 窗口期到期，无任何评价 | run 自动 `completed`，无评价数据 |
| Campaign milestone 窗口期到期 | milestone 自动 `passed`，Campaign 继续，Telegram 推送告知 |

**窗口期时长**：Norm 配置项 `eval_window_hours`，默认 2 小时，在 Console Norm 面板修改。

### 19A.2 Circuit 特殊行为

Circuit 每个实例执行完成 → 立即 `completed`（不被窗口期阻塞），但在窗口期内出现在 Portal 待评价页供用户可选评价。窗口期过后移入历史页。

### 19A.3 Portal 三页结构

| 页面 | 包含内容 |
|---|---|
| **运行中** | `run_status = running` 的 run |
| **待评价** | 处于评价窗口期内的 run（含 Circuit 实例），显示倒计时 |
| **历史** | 已过窗口期的所有 run，可追加纯文字评语 |

详见 `.ref/INTERFACE_DESIGN.md`。

---

## 20. Activity 内部执行模型：迭代报告（Iter-Report）

### 20.1 问题背景

Activity 内部若需要多轮工具调用（如 collect 抓取 10 个 URL、analyze 多轮比较），传统 ReAct 模式会在 session 中累积完整历史，导致：

- 早期工具结果淡出注意力窗口，后期回答质量下降
- 上下文 token 随步骤数线性增长，不可控
- activity 本身是有状态的，但状态散落在对话历史中，无法追溯

### 20.2 Iter-Report 模式（参考 iterResearch）

对需要多轮迭代的 activity，采用**马尔可夫式状态压缩**替代完整历史累积：

```
每轮输入 = [System Prompt] + [当前 Report_v_n] + [上一轮工具结果]
每轮输出 = think → 更新 Report_v_{n+1} + 下一个 Action
终止条件 = Report 标记 done=true 或达到最大步数
```

与传统 ReAct 对比：

| | 传统 ReAct | Iter-Report |
|---|---|---|
| 每轮上下文 | System + 全部历史 | System + Report + 上轮结果 |
| 上下文增长 | 线性（O(n)） | 有界（O(1)） |
| 状态可读性 | 分散在历史中 | Report 即状态快照 |
| 适用场景 | 短对话、低轮次 | 多轮工具调用、长研究 |

**Report 结构**（最小约束，activity 可扩展）：

```json
{
  "version": 3,
  "done": false,
  "findings": [...],
  "gaps": [...],
  "next_action_rationale": "还需要抓取 URL #4，因为..."
}
```

### 20.3 适用范围

| Activity | 是否适用 | 说明 |
|---|---|---|
| collect | ✅ 优先适用 | 多 URL 抓取时，每轮积累 findings |
| analyze | ✅ 优先适用 | 多轮比较推理时，Report 承载分析进度 |
| review | 按需 | 通常单轮，不需要 |
| render | 否 | 单轮生成，不需要 |
| build | ✅ 适用 | 多文件编辑时，Report 记录已完成/待完成项 |

### 20.4 实施策略

- 实现为 `weave_patterns/iter_report` Weave pattern，不改变 pipeline 结构
- Activity 在 Weave Plan 中通过 `execution_mode: iter_report` 声明使用此模式
- 触发条件：Weave Plan 预估该 activity 工具调用轮次 ≥ 4
- Report 的每个版本写入 `state/runs/<run_id>/steps/<step_id>/report_v<n>.json`，供溯源
- 暖机阶段不强制启用，待 collect/analyze activity 出现上下文质量下降信号后按需引入

---

## 21. Skill 分类与评测机制

### 21.1 Skill 两类分法

所有 skill 按其核心价值分为两类，分类决定评测标准和改动风险等级。

| 类型 | 定义 | 移除后果 | 评测维度 |
|---|---|---|---|
| **能力增强型**（Capability） | 让系统能做原本做不到的事 | 功能缺失，运行失败 | 正确性、可靠性、延迟 |
| **偏好编码型**（Preference） | 让事情按标准流程、风格、规范执行 | 质量下降，但不会崩溃 | 质量评分、用户满意度相关性 |

**当前 skill 分类示例：**

| Skill | 类型 | 说明 |
|---|---|---|
| `url_summarize`, `xurl_collect` | Capability | 没有则无法抓取外部内容 |
| `coding_agent_v2`, `github_ops` | Capability | 没有则无法写代码/操作 GitHub |
| `nano_pdf_render` | Capability | 没有则无法产出 PDF |
| `router_weave_plan` | Preference | 编码 Router 规划风格与流程 |
| `generate_user_feedback_survey` | Preference | 编码反馈问卷的生成标准 |
| review rubric skills | Preference | 编码质量评审标准 |

分类必须在 skill 的 `SKILL.md` 中声明 `skill_type: capability | preference`。

### 21.2 Skill Benchmark 机制

每个 skill 必须附带 benchmark，改动 skill 后必须通过 benchmark 对比才能上线。

**Benchmark 结构**（存放位置：`workspace/<agent>/skills/<skill_name>/benchmark/`）：

```
benchmark/
  cases.json          # 测试用例列表（输入 + 期望输出描述）
  rubric.json         # 评分维度与权重
  baseline.json       # 当前版本得分基线（自动维护）
  history.jsonl       # 历次改动的评测记录
```

**`cases.json` 结构：**
```json
[
  {
    "case_id": "c001",
    "input": {...},
    "expected_behavior": "应返回结构化摘要，包含来源、主要发现、置信度",
    "must_not": ["不得截断超过50%的原文信息", "不得忽略日期字段"]
  }
]
```

**`rubric.json` 结构（能力增强型 vs 偏好编码型 rubric 不同）：**

能力增强型：
```json
{"correctness": 0.5, "completeness": 0.3, "latency_p95_ok": 0.2}
```

偏好编码型：
```json
{"style_compliance": 0.4, "user_satisfaction_proxy": 0.4, "consistency": 0.2}
```

### 21.3 Skill 改动工作流

```
1. 提出改动（skill_evolution_proposals.json 或 Skills Campaign 产出）
2. 运行 benchmark：analyze agent 对改动前后各跑全部 cases，产出对比报告
3. 对比规则：
   - 所有维度得分 ≥ baseline → 允许上线
   - 任意维度下降 > 5% → 必须人工审批
   - 总分提升 > 10% → 记录为"重大改进"，写入 Playbook
4. 结果写入 benchmark/history.jsonl，更新 baseline.json
5. Telegram 推送对比摘要
```

### 21.4 Skills Campaign 的 Benchmark 建立流程

Skills Campaign（§NEXT_PHASE_PLAN 阶段二）运行时，对每个引入或修改的 skill：

1. **Milestone 1（collect）**：收集 skill 的代表性使用场景
2. **Milestone 2（analyze）**：基于使用场景生成 `cases.json` + `rubric.json`，运行初次评测建立 baseline
3. **Milestone 3（review）**：确认 benchmark 覆盖度和 rubric 合理性
4. **Milestone 4（build）**：将 benchmark 文件写入 skill 目录，PR 合并后生效

此后每次 skill 改动必须先跑 benchmark，不允许跳过。

---

## 22. Circuit（持续执行回路）

### 22.0 命名与定位

**Circuit** 是 Daemon 的第四种执行单元，与 Pulse / Thread / Campaign 并列：

| 单元 | 隐喻 | 执行模式 |
|---|---|---|
| Pulse | 单次脉冲 | 一次触发，原子完成 |
| Thread | 一条线索 | 多步骤，单次 workflow 内完成 |
| Campaign | 持续战线 | 多 milestone，用户逐步参与 |
| **Circuit** | **持续回路** | **模板 + 触发策略，循环执行直到断路** |

Circuit 本身不是新的执行方式——每次触发仍然产出一个 Pulse / Thread / Campaign 实例。Circuit 是纯粹的**调度原语**：持有模板 + cron 表达式，按时间自动提交运行。实例间的记忆和质量演化由 Memory fabric 负责，Circuit 自身无状态。

### 22.1 数据结构

```json
{
  "circuit_id": "circuit_20260306_abc123",
  "name": "每日简报",
  "prompt": "生成今日简报…",
  "run_type": "research_report",
  "cron": "0 8 * * *",
  "tz": "Asia/Shanghai",
  "status": "active",
  "created_utc": "2026-03-06T12:00:00Z",
  "last_triggered_utc": "",
  "last_instance_id": "",
  "run_count": 0
}
```

**status 生命周期：**
```
active ⇄ paused    （暂停/恢复，保留配置）
active → cancelled  （永久断路，不可恢复）
```

### 22.2 API 接口

```
GET    /circuits               列出所有 Circuit
POST   /circuits               新建 Circuit
PUT    /circuits/{id}          更新（改名 / 改 cron / 暂停 / 恢复）
DELETE /circuits/{id}          取消（永久断路）
POST   /circuits/{id}/trigger  手动立即触发一次
```

### 22.3 用户交互入口

- **Portal Circuit 页**：Circuit 列表，含状态、最近触发时间、次数、暂停 / 立即触发 / 删除；创建通过对话框发起（Router 识别 Circuit 意图）
- **Console Schedules 面板**：Circuit 列表只读，供运维观察

Telegram 不接受 Circuit 操作命令，仅推送实例完成通知。

### 22.4 实施状态

| 功能 | 状态 |
|---|---|
| cron 触发 + CRUD API | ✅ 已实现（代码待从 chains 重命名为 circuits） |
| Console UI（Schedules 面板 Circuit 区块，只读） | ✅ 已实现 |
| Portal Circuit 页（CRUD） | ❌ 待实现 |
| Telegram Circuit 命令 | ❌ 废弃（Telegram 改为纯推送）|
