> ⚠️ 警告：此文档已作废，禁止查看。请仅以 `/.ref/daemon_统一方案_v2.md` 为唯一权威来源。

# Daemon 全量实现行动计划（全映射版）

> 状态声明（2026-03-04）  
> 本文档是阶段性实施与验收记录，不再作为后续新增开发规范。  
> 新增功能与架构演进请遵循 `.ref/daemon_统一方案_v2.md`。  
> 本文仅用于历史追溯与证据索引。

> 目的：把「方案文档」与「gap 文档」统一映射到一个可执行、可追踪、可反推的行动计划。  
> 本文档是执行事实源（action source of truth），不以工程量为边界，按方案全量对齐。

---

## 0. 执行守则（不可妥协）

1. **MAS 仅可内化，不可搬运**：只提炼行为模式和失败经验，不复制旧架构/旧 API/旧数据路径。
2. **测试隔离**：任何测试脚本与结果文件必须在 `daemon/` 外执行与存放；用完即删。
3. **完成度优先**：禁止以降级、伪状态、临时绕过换取“看起来可运行”。
4. **全量映射优先**：行动计划必须覆盖方案与 gap 的全部显式条目，允许标记未完成，但不允许漏记。

---

## 1. 映射模型（保证可反推）

### 1.1 ID 体系

- `S-xxx`：方案需求项（来源：`.ref/daemon_系统设计方案_ddbc4981.plan.md`）
- `G-xxx`：Gap 缺口项（来源：`.ref/gap_analysis.md`）
- `A-xxx`：执行动作项（本计划定义）
- `U-xxx`：未完成登记项（必须给出原因、影响、后继）

### 1.2 反推规则

1. 从任一 `S-xxx` 必须能定位到 `A-xxx`（执行动作）和 `G-xxx`（若有缺口）。
2. 从任一 `G-xxx` 必须能定位到 `A-xxx`，且当前状态明确为 `已完成/部分完成/未完成`。
3. 凡 `部分完成/未完成`，必须映射到 `U-xxx`。
4. `U-xxx` 必须能反推到对应 `S-xxx` 与 `G-xxx`。

### 1.3 颗粒度定义（你关心的“能不能真正工作”）

- `L0`：愿景级（只有方向）
- `L1`：模块级（只有大块能力）
- `L2`：能力级（有 API/模块映射，但缺可执行验收）
- `L3`：功能级（每个方案功能有可执行验收场景）
- `L4`：运维级（含监控、回归、演练、SLO）

本计划当前已达到 `L3`：每个 `S-xxx` 都要对应可执行验收场景（见 `C-xxx` 矩阵）。  
**完成定义锁定为**：仅当 `S-001~S-025` 全部为“已完成”且 `C-xxx` 全部通过，才算“方案功能全部可工作”。

---

## 2. 动作目录（A Catalog）

| 动作ID | 动作内容 | 当前状态 |
|---|---|---|
| A-001 | `/submit` 真实性修复（Temporal 不可用即失败） | 已完成 |
| A-002 | Worker→API 跨进程事件桥（JSONL + cursor + ack） | 已完成 |
| A-003 | `spine.record` 自动触发（由完成事件驱动） | 已完成 |
| A-004 | `task_replay` 消费与重提交通道 | 已完成 |
| A-005 | Scheduler pre/post Contract 强制执行 | 已完成 |
| A-006 | Cron 精确解析与 `next_run_utc` | 已完成 |
| A-007 | registry `nerve_triggers` 自动接线 | 已完成 |
| A-008 | witness 透明内化全源接入（OpenClaw/trace/日志/行为） | 已完成 |
| A-009 | learn 读取 `langgraph_patterns` 并产出提案 | 已完成 |
| A-010 | relay 回写 `runtime_hints.txt` | 已完成 |
| A-011 | Cortex usage trace 持久化并可查询 | 已完成 |
| A-012 | activities 统一复用 `OpenClawAdapter` | 已完成 |
| A-013 | Outcome 时间字段统一 `delivered_utc`（Portal/CLI/Telegram一致） | 已完成 |
| A-014 | Portal 预览修复（优先 html，回退 md/manifest） | 已完成 |
| A-015 | Portal Timeline 独立视图 + 聚合 API | 已完成 |
| A-016 | Console API 方案清单补齐（12.2） | 已完成 |
| A-017 | Agent Manager：Skill 列表/启停/编辑 UI | 已完成 |
| A-018 | Skill Evolution 提案审批面板与流程 | 已完成 |
| A-019 | Schedule Manager 完整能力（编辑/启停/next_run/历史） | 已完成 |
| A-020 | Spine Dashboard 依赖关系可视化 | 已完成 |
| A-021 | Policy Editor 全量（quality/budget/preferences） | 已完成 |
| A-022 | Config Versions diff + rollback 可视化 | 已完成 |
| A-023 | Fabric Explorer 深度能力（usage/links/audit/history/compare） | 已完成 |
| A-024 | Trace Viewer 详情（步骤时间线 + Cortex 摘要） | 已完成 |
| A-025 | Console Cortex Usage 专面 | 已完成 |
| A-026 | Delivery PDF best-effort 生成链路 | 已完成 |
| A-027 | 双语质量门检查（bilingual pairing） | 已完成 |
| A-028 | Dispatch 从 Compass/Playbook 注入策略（含 agent limits） | 已完成 |
| A-029 | 关键路径去静默吞错并记录错误上下文 | 已完成 |
| A-030 | 外部测试执行与清理闭环（daemon 外） | 已完成 |

### 2.1 功能可工作五元组（每个动作都必须满足）

1. **入口可达**：API/调度/事件触发路径可执行。
2. **结果可见**：UI 或状态存储中可看到结果。
3. **状态可追溯**：落盘到明确 state/fabric 路径并可查询。
4. **失败可解释**：失败有明确 error_code 与上下文，不得伪成功。
5. **链路可观测**：trace/log/事件流可定位到执行与失败点。

任一条不满足，该动作不得标记“已完成”。

---

## 3. 方案需求全量映射（S -> A/G）

| 方案ID | 方案需求（摘要） | 方案定位 | 对应动作 | 关联缺口 | 状态 |
|---|---|---|---|---|---|
| S-001 | Nerve 事件链路：`task_completed/delivery_completed -> spine.record` | 行 222, 372-387, 823 | A-002,A-003 | G-001 | 已完成 |
| S-002 | Contracts 前后置检查 | 行 643 | A-005 | G-002 | 已完成 |
| S-003 | Gate 恢复后 replay 队列任务 | 行 229, 866 | A-004 | G-003 | 已完成 |
| S-004 | Scheduler：cron + 自适应节奏 +可解释下一次触发 | 行 223-234, 757, 1019 | A-006,A-007,A-019 | G-014,G-015,G-030 | 已完成 |
| S-005 | Dispatch 从 Compass/Playbook 注入参数 | 行 521, 1319, 895 | A-028 | G-045 | 已完成 |
| S-006 | Delivery 结构门 + outcome/index + 交付完成事件 | 行 810-823, 829 | A-013,A-029 | G-004 | 已完成 |
| S-007 | Delivery 渠道路由（Telegram/PDF） | 行 820-821, 1320 | A-026 | G-043 | 已完成 |
| S-008 | witness 透明内化（会话、模式、日志、自观察） | 行 496-499, 517, 559, 572 | A-008 | G-005,G-006,G-007,G-008,G-009 | 已完成 |
| S-009 | learn：模式提炼 + Skill Evolution 提议 | 行 225, 497, 724, 728-735 | A-009,A-018 | G-010,G-029 | 已完成 |
| S-010 | relay：snapshot + `skill_index` + `runtime_hints.txt` | 行 473, 497, 714, 881 | A-010 | G-011 | 已完成 |
| S-011 | Cortex 用量与 trace 可追溯 | 行 415, 425, 1080 | A-011,A-025 | G-012,G-027,G-039 | 已完成 |
| S-012 | Console API 全集（12.2） | 行 1038-1080 | A-016 | G-016,G-017,G-018,G-019,G-020,G-021,G-022,G-023,G-024,G-025,G-026,G-027 | 已完成 |
| S-013 | Portal：Chat + Outcome + Timeline | 行 964-967, 1326 | A-014,A-015 | G-040,G-041,G-042 | 已完成 |
| S-014 | Spine Dashboard：状态、手动触发、Nerve流、依赖图 | 行 987-993 | A-020 | G-031,G-032 | 已完成 |
| S-015 | Fabric Explorer 深度浏览 | 行 996-999 | A-023 | G-035,G-036,G-037 | 已完成 |
| S-016 | Policy Editor 全量与版本化 | 行 1000-1009 | A-021,A-022 | G-022,G-033,G-034,G-038 | 已完成 |
| S-017 | Agent Manager：Skill 管理与执行表现 | 行 1011-1015 | A-017 | G-028 | 已完成 |
| S-018 | Schedule Manager：可视化编辑、启停、历史、手动触发 | 行 1017-1022 | A-019 | G-030 | 已完成 |
| S-019 | Trace Viewer：步骤展开 + Cortex 调用摘要 | 行 1024-1030 | A-024 | G-025 | 已完成 |
| S-020 | Config Versions 专面（diff + rollback） | 行 1031-1036 | A-022 | G-038 | 已完成 |
| S-021 | OpenClaw 统一适配器（单一通道） | 行 614, 622, 662, 1143 | A-012 | G-013 | 已完成 |
| S-022 | Outcome index 支撑 Timeline/Console 查询 | 行 816 | A-013,A-015 | G-040,G-041 | 已完成 |
| S-023 | 双语配对质量门 | 行 811, 829 | A-027 | G-044 | 已完成 |
| S-024 | PDF best-effort | 行 821 | A-026 | G-043 | 已完成 |
| S-025 | Console：Skill Evolution 面板（审批写回） | 行 734-735, 1325 | A-018 | G-029 | 已完成 |

---

## 4. Gap 全覆盖映射（G -> A/S/U）

> 说明：以下条目覆盖 `.ref/gap_analysis.md` 的全部显式缺口。

| GapID | Gap 条目（摘要） | Gap定位 | 对应方案ID | 对应动作ID | 状态 | 未完成登记 |
|---|---|---|---|---|---|---|
| G-001 | Nerve 跨进程断裂导致 record 不触发 | §一.1 | S-001 | A-002,A-003 | 已完成 | - |
| G-002 | Contracts 定义存在但未调用 | §一.2 | S-002 | A-005 | 已完成 | - |
| G-003 | replay 无 handler | §一.3 | S-003 | A-004 | 已完成 | - |
| G-004 | delivery `_update_index` 静默 except | §一.4 | S-006 | A-029 | 已完成 | - |
| G-005 | witness 未读会话日志 | §二.5 | S-008 | A-008 | 已完成 | - |
| G-006 | witness 未读 `langgraph_patterns` | §二.5 | S-008 | A-008 | 已完成 | U-011 |
| G-007 | witness 未读 Cortex 历史 trace | §二.5 | S-008,S-011 | A-008,A-011 | 已完成 | - |
| G-008 | witness 未读 Telegram/Portal 访问日志 | §二.5 | S-008 | A-008 | 已完成 | U-011 |
| G-009 | witness 自我观察不足（Spine trace） | §二.5 | S-008 | A-008 | 已完成 | U-011 |
| G-010 | learn 不读 `langgraph_patterns` | §二.6 | S-009 | A-009 | 已完成 | - |
| G-011 | relay 缺少 `runtime_hints.txt` | §二.7 | S-010 | A-010 | 已完成 | - |
| G-012 | Cortex trace 不持久化 | §二.8 | S-011 | A-011 | 已完成 | - |
| G-013 | activities 未复用 OpenClawAdapter | §二.9 | S-021 | A-012 | 已完成 | U-001 |
| G-014 | cron 解析错误 | §三.10 | S-004 | A-006 | 已完成 | - |
| G-015 | Nerve trigger 未注册 | §三.11 | S-004 | A-007 | 已完成 | - |
| G-016 | 缺 `GET /console/fabric/memory` | §四 | S-012 | A-016 | 已完成 | - |
| G-017 | 缺 `GET /console/fabric/memory/{unit_id}` | §四 | S-012 | A-016 | 已完成 | - |
| G-018 | 缺 `GET /console/fabric/playbook` | §四 | S-012 | A-016 | 已完成 | - |
| G-019 | 缺 `GET /console/fabric/playbook/{method_id}` | §四 | S-012 | A-016 | 已完成 | - |
| G-020 | 缺 `GET /console/fabric/compass/budgets` | §四 | S-012 | A-016 | 已完成 | - |
| G-021 | 缺 `GET /console/fabric/compass/signals` | §四 | S-012 | A-016 | 已完成 | - |
| G-022 | 缺 policy GET/PUT/versions/rollback | §四 | S-012,S-016 | A-016 | 已完成（API） | U-006 |
| G-023 | 缺 agent skills 管理接口 | §四 | S-012,S-017 | A-016 | 已完成（API） | U-004 |
| G-024 | 缺 `PUT /console/schedules/{job_id}` | §四 | S-012,S-018 | A-016 | 已完成（API） | U-005 |
| G-025 | 缺 `GET /console/traces/{trace_id}` | §四 | S-012,S-019 | A-016 | 已完成（API） | U-009 |
| G-026 | 缺 `GET /console/spine/nerve/events` | §四 | S-012,S-014 | A-016 | 已完成 | - |
| G-027 | 缺 `GET /console/cortex/usage` | §四 | S-012,S-011 | A-016 | 已完成（API） | U-010 |
| G-028 | Agent Manager 缺 Skill 操作 UI | §五.Agent | S-017 | A-017 | 已完成 | U-004 |
| G-029 | 缺 Skill Evolution 面板 | §五.Agent | S-025 | A-018 | 已完成 | U-003 |
| G-030 | Schedule Manager 缺完整编辑/启停/next_run | §五.Schedule | S-018 | A-019 | 已完成 | U-005 |
| G-031 | Spine Dashboard 缺 Nerve 实时流 | §五.Spine | S-014 | A-016 | 已完成 | - |
| G-032 | Spine Dashboard 缺依赖关系可视化图 | §五.Spine | S-014 | A-020 | 已完成 | U-007 |
| G-033 | Policy Editor 缺 quality/budget/preferences 全量编辑 | §五.Policy | S-016 | A-021 | 已完成 | U-006 |
| G-034 | Policy 缺版本历史 diff+回滚 UI 能力 | §五.Policy | S-016,S-020 | A-022 | 已完成 | U-006 |
| G-035 | Fabric Memory 缺 usage/links/audit 详情 | §五.Fabric | S-015 | A-023 | 已完成 | U-008 |
| G-036 | Fabric Playbook 缺评估历史/版本对比 | §五.Fabric | S-015 | A-023 | 已完成 | U-008 |
| G-037 | Fabric Compass 缺 signals 时间线等可视化 | §五.Fabric | S-015 | A-023 | 已完成 | U-008 |
| G-038 | Config Versions 面板缺失 | §五.完全缺失 | S-020 | A-022 | 已完成 | U-006 |
| G-039 | Cortex Usage 面板缺失（仅有总览统计） | §五.完全缺失 | S-011 | A-025 | 已完成 | U-010 |
| G-040 | Portal 缺 Timeline 视图 | §六 | S-013,S-022 | A-015 | 已完成 | U-002 |
| G-041 | Portal 读取错误时间字段 | §六 | S-013,S-022 | A-013 | 已完成 | - |
| G-042 | Portal HTML 预览失败 | §六 | S-013 | A-014 | 已完成 | - |
| G-043 | PDF 生成未实现 | §七 | S-007,S-024 | A-026 | 已完成 | U-012 |
| G-044 | bilingual 质量门未检查 | §七 | S-023 | A-027 | 已完成 | - |
| G-045 | Dispatch 未从 Compass 注入并发限制 | §七 | S-005 | A-028 | 已完成 | U-013 |

---

## 5. 分阶段执行（全量，不计工程量）

### Phase P0（闭环真实性）

- A-001, A-002, A-003, A-004, A-005, A-006, A-007, A-029
- 验收：`/submit` 无伪运行；Worker 完成后 API 可触发 `spine.record`；replay 生效；Contract fail-fast。

### Phase P1（治理与透明内化）

- A-008, A-009, A-010, A-011, A-028
- 验收：witness/learn/relay 数据闭环成立，Cortex trace 可跨重启追溯。

### Phase P2（管理能力与交互一致性）

- A-013, A-014, A-016, A-017, A-019, A-021, A-023, A-024, A-025
- 验收：API 完整可用；Portal/CLI/Telegram 字段一致；Console 关键面板可操作。

### Phase P3（方案剩余全量补齐）

- A-012, A-015, A-018, A-020, A-022, A-026
- 验收：Timeline、Skill Evolution、Config Versions、依赖图、PDF 全落地。

### 5.1 功能验收场景矩阵（C Matrix）

> 说明：`C-xxx` 是“是否可工作”的最终判据。所有场景必须在 daemon 外部测试目录完成验证。

| 场景ID | 对应方案 | 场景定义（通过标准） | 当前结论 |
|---|---|---|---|
| C-001 | S-001,S-003 | Temporal 不可用时 `/submit` 返回失败，且不写伪 running | 通过 |
| C-002 | S-001 | Worker 完成交付后，API 可消费 bridge 事件并触发 `spine.record` | 通过 |
| C-003 | S-003 | Gate 恢复 GREEN 后 queued 任务 replay 并正确迁移状态 | 通过 |
| C-004 | S-002 | routine pre/post contract 失败时 fail-fast 且返回 contract_failed | 通过 |
| C-005 | S-004 | 5 段 cron 计算 `next_run_utc` 与真实触发一致 | 通过 |
| C-006 | S-004 | registry `nerve_triggers` 自动注册并触发 routine | 通过 |
| C-007 | S-005 | Dispatch 读取策略并注入 plan（含并发/质量） | 通过 |
| C-008 | S-006,S-022 | outcome/index 与任务结果一致，字段标准为 `delivered_utc` | 通过 |
| C-009 | S-007 | Telegram 路由可用；PDF best-effort 不阻塞交付 | 通过 |
| C-010 | S-008 | witness 能读取 OpenClaw 会话/运行痕迹并产出观察 | 通过 |
| C-011 | S-008 | witness 能读取 Telegram/Portal 行为日志并纳入分析 | 通过 |
| C-012 | S-009 | learn 读取 `langgraph_patterns` 并输出提案 | 通过 |
| C-013 | S-010 | relay 写出 `skill_index.json` + `runtime_hints.txt` | 通过 |
| C-014 | S-011 | Cortex trace 重启后可查询（含时间过滤） | 通过 |
| C-015 | S-012 | 方案 12.2 API 全部存在且返回语义正确 | 通过 |
| C-016 | S-013 | Portal Outcome 预览优先 html，回退 md/manifest | 通过 |
| C-017 | S-013,S-022 | Portal Timeline 可按时间流查看产出 | 通过 |
| C-018 | S-017 | Agent Manager UI 可查看/启停/编辑 Skill | 通过 |
| C-019 | S-025 | Skill Evolution 面板支持提案审批并回写 `SKILL.md` | 通过 |
| C-020 | S-018 | Schedule Manager 含编辑、启停、next_run、执行历史 | 通过 |
| C-021 | S-016,S-020 | Policy Editor 全量可编辑，支持 versions diff 与 rollback | 通过 |
| C-022 | S-015 | Fabric Explorer 可看 memory usage/links/audit 与 playbook 历史对比 | 通过 |
| C-023 | S-019 | Trace Viewer 可展开步骤时间线与 Cortex 调用摘要 | 通过 |
| C-024 | S-024 | PDF 生成为 best-effort，失败不阻塞且有明确日志 | 通过 |
| C-025 | S-023 | 双语质量门能拦截不满足 bilingual 的交付内容 | 通过 |

---

## 6. 当前执行结论（截至本轮）

1. **P0 主闭环已打通**：事件桥、record 自动触发、replay、contracts、cron 语义、submit 真实性均已落地。
2. **API 方案清单已补齐**：`12.2` 列出的端点已实现。
3. **透明内化闭环已验证**：OpenClaw 会话/Router patterns/Cortex trace/Portal&Telegram 行为日志/trace 自观察均已在外部影子环境通过验收。
4. **UI 与管理面闭环已验证**：Timeline、Skill Evolution、Config Versions、依赖图、Policy 全量编辑、Trace/Cortex 面板均已完成外部验收。
5. **外部验收与清理闭环已执行**：所有验收均在 daemon 外影子目录执行，执行后已清理临时目录与结果产物。
6. **按“功能全部可工作”标准，当前已达成**：`C-001` 到 `C-025` 全部通过。

---

## 附录 A：MAS 内化清单

> 仅内化原理，不复用旧架构。

### 卡片 A：Workflow 调度与返工

- 旧行为：DAG + 并发控制 + 返工链路
- 可复用原理：拓扑调度、结构化错误码驱动返工
- Daemon 重写：保留 `GraphDispatchWorkflow`，返工按 error_code 路由
- 拒绝复用：字符串匹配返工、硬编码超时

### 卡片 B：OpenClaw 调用与会话治理

- 旧行为：HTTP/CLI 双通道混用
- 可复用原理：session_key 规范、轮询窗口
- Daemon 重写：统一 Gateway 通道 + 事件桥分离进程通信
- 拒绝复用：CLI fallback、路径硬编码

### 卡片 C：质量门与交付审计

- 旧行为：交付阶段结构检查
- 可复用原理：禁用标记、最小结构、失败即显式状态
- Daemon 重写：Delivery/Activities 双点一致质量门 + 错误上下文记录
- 拒绝复用：静默吞错、伪成功

### 卡片 D：学习内化路径

- 旧行为：学习数据多轨断裂
- 可复用原理：单一学习写入口、回写 runtime hints
- Daemon 重写：Playbook 为学习中枢，relay 回写 `runtime_hints.txt`
- 拒绝复用：分散元数据源、不可追踪中间态

---

## 附录 B：未完成项登记（全量）

> 当前无未完成项；以下为历史 U 项关闭记录。

| U-ID | 主题 | 对应 | 当前状态 | 关闭说明 |
|---|---|---|---|---|
| U-001 | activities 统一复用 `OpenClawAdapter` | S-021/G-013/A-012 | 已关闭 | 影子环境验证 activities 通过 `OpenClawAdapter` 完成发送与轮询 |
| U-002 | Portal Timeline | S-013,S-022/G-040/A-015 | 已关闭 | `/outcome/timeline` 返回分日数据，Portal Timeline 面板可加载并跳转 |
| U-003 | Skill Evolution 审批面板 | S-025/G-029/A-018 | 已关闭 | 提案可审批并回写 `SKILL.md`（含 proposal marker） |
| U-004 | Agent Manager Skill 管理 UI | S-017/G-028/A-017 | 已关闭 | Skills 列表/启停/编辑接口与 UI 均通过外部验收 |
| U-005 | Schedule Manager 完整能力 | S-018/G-030/A-019 | 已关闭 | schedule 编辑、启停、`next_run_utc`、history 均验证通过 |
| U-006 | Policy Editor 与 Config Versions | S-016,S-020/G-033,G-034,G-038/A-021,A-022 | 已关闭 | quality/preference/budget 全量编辑 + versions/diff/rollback 均通过 |
| U-007 | Spine 依赖关系可视化 | S-014/G-032/A-020 | 已关闭 | `/console/spine/dependencies` 与 Console 依赖视图验收通过 |
| U-008 | Fabric Explorer 深度能力 | S-015/G-035,G-036,G-037/A-023 | 已关闭 | memory usage/links/audit、playbook 历史对比、signals timeline 均通过 |
| U-009 | Trace Viewer 详情 | S-019/G-025/A-024 | 已关闭 | trace detail 包含步骤展开与 `cortex_summary` 聚合 |
| U-010 | Cortex Usage 专面 | S-011/G-039/A-025 | 已关闭 | 时间范围筛选、记录表、provider 汇总均通过 |
| U-011 | witness 全源透明内化 | S-008/G-006,G-008,G-009/A-008 | 已关闭 | witness 读取会话/模式/行为日志/trace 自观察并输出统计 |
| U-012 | PDF best-effort 交付 | S-007,S-024/G-043/A-026 | 已关闭 | service/activity 均验证“PDF失败不阻塞交付” |
| U-013 | Dispatch 注入并发限制 | S-005/G-045/A-028 | 已关闭 | `/submit` 真实失败语义与 plan 注入字段均验证通过 |

---

## 附录 C：外部测试清理记录模板

> 仅允许在 daemon 外执行；执行结束必须清理。

```markdown
### 测试批次
- 时间：
- 执行人：
- 临时目录：
- 测试范围：
  - [ ] 单元
  - [ ] 集成
  - [ ] 接口契约
  - [ ] UI 字段一致性
  - [ ] 事件桥回放
  - [ ] 质量门失败路径

### 关键结果
- 通过项：
- 失败项：
- 结论：

### 清理确认
- [ ] 临时测试脚本已删除
- [ ] 结果文档已删除（仅保留结论摘录到 .ref）
- [ ] daemon 目录无测试残留产物
```

---

## 7. 本轮执行说明

- 本轮继续遵守约束：未在 `daemon/` 下创建测试脚本与测试结果文档。  
- 本轮核心修复（对齐 `S-001/S-002/S-018/S-019` 等执行真实性条目）：
  - `runtime/event_bridge.py`：游标从“offset-only”升级为 `offset+pending+acked`，修复进程崩溃场景的事件丢失风险。
  - `services/scheduler.py`：adaptive 节奏按 `learning_rhythm + routine offset` 计算；cron 的 DOM/DOW 语义修正为标准 OR。
  - `temporal/__init__.py`：移除重导入副作用，修复 Worker 启动时 workflow sandbox 校验失败。
  - `interfaces/cli/main.py`：修复 `health/chat` 命令直接失败。
- 本轮外部验收（均在 daemon 外进程执行）：
  - Daemon OpenClaw Gateway（18790）可启动并可被 Daemon token 访问。
  - Worker/API/Telegram Adapter 均可启动并提供健康响应。
  - `POST /submit` 语义双向验证：Temporal 可用返回 `running`；不可用返回 `503 + temporal_unavailable`。
  - `GET /console/schedules` 返回可解释 `next_run_utc`；`/console/traces/{trace_id}` 返回 `cortex_summary`。
  - 事件桥验证：写入 `task_completed` 后，API 侧消费并触发 `spine.record`（Playbook evaluation 增长可观测）。
- 清理确认：
  - `/tmp` 验收日志与结果文件已删除。
  - daemon 内 probe 任务、trace、telemetry、临时 policy 项已清理。
  - `daemon/` 目录未残留测试脚本与验收结果文档。
