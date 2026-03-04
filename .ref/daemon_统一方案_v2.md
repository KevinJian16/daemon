# Daemon 统一方案 V2（执行权威）

> 生效日期：2026-03-04
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
