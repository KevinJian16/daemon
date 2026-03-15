# Daemon 系统重建 TODO

> 日期：2026-03-16
> 依据：`SYSTEM_DESIGN.md`（七稿）+ `SYSTEM_DESIGN_REFERENCE.md`（附录 B-I）
> 方法：逐节审计设计文档 → 对照代码库 → 按设计要求列出所有待做

**本文档从设计文档出发，不从已有代码出发。** 每一条都对应 SYSTEM_DESIGN.md 或 REFERENCE 中的具体条款。

---

## 文档索引

| 文档 | 路径 | 用途 |
|---|---|---|
| 系统设计总纲 | `.ref/SYSTEM_DESIGN.md` | **唯一权威文档**（七稿） |
| 配套参考文档 | `.ref/SYSTEM_DESIGN_REFERENCE.md` | 附录 B-I |
| 实施记录 | `.ref/_work/IMPLEMENTATION_PLAN.md` | Phase 0-5 实施状态 |

---

## 已完成（Phase 0-5 + 3.5 + Gap 修复 + 文档清理）

详见本文件末尾「已完成记录」。

---

## 待做清单

> 按设计文档章节排列。每条标注来源章节。
> 优先级：🔴 阻塞暖机 / 🟡 暖机前应完成 / 🟢 暖机后或并行

---

### A. 对象模型与数据层（§1, §6, 附录 C）

- [ ] 🔴 **A-01** PG 两套 schema 对齐（§1.1, 附录 C）
  - `migrations/001_initial_schema.sql` 与 `api.py` 内联 SQL 有多处不一致：
    - `daemon_tasks.task_id` 类型（SERIAL vs UUID）
    - `jobs.dag_snapshot` 字段缺失（内联 SQL 用 `dag`）
    - `job_artifacts` 缺少 `source_markers JSONB` 字段
    - `knowledge_cache.embedding` 维度（768 vs 1024，§2.8 指定智谱 embedding-3 = 1024）
    - `event_log` 缺少 `consumed_at` 字段
  - 统一以附录 C 为准，通过 alembic migration 对齐

- [ ] 🟡 **A-02** `daemon_tasks` 缺失字段（附录 C.1）
  - `trigger_type`（manual/timer/chain）— 代码中无此字段
  - `schedule_id`（Temporal Schedule ID，timer 类型时）
  - `chain_source_task_id`（前序 Task，chain 类型时）
  - `dag`（Task 级 DAG 定义）

- [ ] 🟡 **A-03** `jobs` 缺失字段（附录 C.2）
  - `is_ephemeral BOOLEAN`（route="direct" 时为 true）
  - `requires_review BOOLEAN`
  - `plane_sync_failed BOOLEAN`
  - `started_at TIMESTAMPTZ`

- [ ] 🟡 **A-04** `job_steps` 缺失字段（附录 C.3）
  - `model_hint TEXT`
  - `skill_used TEXT`
  - `input_artifacts TEXT[]`
  - `token_used INTEGER`

- [ ] 🟡 **A-05** `job_artifacts` 缺失字段（附录 C.4）
  - `source_markers JSONB`（[EXT:url] / [INT:persona] 标记）
  - `mime_type TEXT`
  - `size_bytes BIGINT`

- [ ] 🟡 **A-06** PG 表预留 `user_id` 字段（§6.13.2）
  - 所有 daemon 表加 `user_id` 字段，单用户时用默认值
  - 不堵死多用户扩展

---

### B. 执行模型（§3）

- [ ] 🔴 **B-01** Routing Decision 结构化输出（§3.1）
  - L1 输出结构化 JSON routing decision（intent/route/model/task）
  - 当前 L1 session 管理存在但 routing decision 格式未定义

- [ ] 🔴 **B-02** Project 级创建逻辑（§3.1, §3.5）
  - `route="project"` 路径：创建 Project → 批量创建 Task + 依赖关系 → 启动入口 Task 首个 Job
  - 当前 `plane_client.py` 无 Project 创建 API

- [ ] 🔴 **B-03** Draft 工作流（§4.3）
  - Draft（Plane DraftIssue）创建、展示、转正为 Task
  - L1 自行判断何时自动转正
  - 当前无 Draft 相关代码

- [ ] 🔴 **B-04** Chain 触发机制（§3.10）
  - `trigger_type="chain"` 时，前序 Job closed(succeeded) 后自动触发下游 Task
  - 经过 Replan Gate（§3.9）
  - 当前 chain 触发链路不完整

- [ ] 🔴 **B-05** Artifact 持久化到 MinIO（§3.7.1）
  - Step 完成后 Artifact 存 MinIO，元数据写 PG `job_artifacts`
  - 当前 Artifact 只写 PG 元数据，未写 MinIO

- [ ] 🟡 **B-06** Artifact 跨 Step/Job/Task 传递（§3.7.1）
  - Step 间：`input_artifacts` 引用上游 Artifact
  - Job 间：前序 Job 最终 Artifact 自动注入
  - Task 间：chain 触发时前序 Artifact 摘要注入

- [ ] 🟡 **B-07** Session key 格式（§3.3.2）
  - L2 session key 应为 `{agent_id}:{job_id}:{step_id}`
  - 检查当前 `activities_exec.py` 是否匹配

- [ ] 🟡 **B-08** Replan Gate 结构化输出（§3.9, D-06）
  - 输出 `operations[]` diff：add / remove / update / reorder
  - 当前 `activities_replan.py` 需检查是否符合

- [ ] 🟡 **B-09** Temporal Signal 支持（附录 D.2）
  - `pause_job` / `resume_job` / `cancel_job` / `confirmation_received` / `confirmation_rejected`
  - 检查 `workflows.py` 中 Signal handler 是否完整

- [ ] 🟡 **B-10** Step 超时按类别设定（附录 B.1）
  - search: 60s, writing: 180s, review: 90s
  - 当前是否按类别设定

- [ ] 🟡 **B-11** Ephemeral Job 统一走 Job 表（§3.5）
  - `route="direct"` 生成 1 Step ephemeral Job，`is_ephemeral=true`
  - 保留 trace、失败补偿和审计能力

---

### C. Plane 集成（§6.6, §2.5）

- [ ] 🔴 **C-01** Plane 回写 + 补偿机制（§6.6）
  - Job 状态先落 daemon PG，再回写 Plane
  - 回写失败 → 重试 5 次（指数退避）→ `plane_sync_failed=true` → 补偿流程异步追平
  - 当前无补偿队列

- [ ] 🟡 **C-02** Job 状态 → Plane Issue 状态映射（附录 D.5）
  - running → started, closed/succeeded → completed, closed/cancelled → cancelled
  - 检查 plane_client 是否实现状态回写

- [ ] 🟡 **C-03** Plane Issue Activity 写入（§4.5）
  - Job 边界 + Step 关键状态写入 Plane Issue Activity
  - 面向 CC/admin 审计追溯

---

### D. 用户界面（§4）

- [ ] 🔴 **D-01** Electron 桌面客户端（§4.2, §6.10.2）
  - 三种 view：对话 / 场景 panel / 浏览器
  - 4 个场景各自独立对话
  - 菜单栏图标（绿/黄/红状态指示）+ 右键菜单
  - 无按钮操作，全部通过对话完成
  - 前端代码同时用于桌面和远程 Web 访问
  - 注：当前有 Portal（Vite + React + Tailwind），需评估是否可作为 Electron 前端基础

- [ ] 🔴 **D-02** API 端点实现（§4.9, 附录 D.1）
  - `POST /scenes/{scene}/chat` — 场景对话
  - `GET /scenes/{scene}/chat/stream` — WebSocket 实时对话流
  - `GET /scenes/{scene}/panel` — 场景面板数据
  - `GET /tasks/{task_id}/activity` — Task 活动流
  - `GET /artifacts/{artifact_id}` — Artifact 内容
  - `GET /artifacts/{artifact_id}/download` — Artifact 下载
  - `GET /status` — 系统状态
  - 当前 `scenes.py` 有部分端点，需对照完整列表

- [ ] 🟡 **D-03** 场景 Panel 数据（§4.2）
  - copilot: 活跃 Project、进行中 Task、最近产出
  - mentor: 学习计划、assignment 列表、学习进度
  - coach: 计划执行率、训练数据摘要、下次评估时间
  - operator: 运营数据、待审内容、自动发布日志

- [ ] 🟡 **D-04** Artifact 呈现（§4.6）
  - 文本类 → 阅读器 view（Markdown 渲染）
  - 需要浏览器的 → 浏览器 view
  - 文件类 → 下载入口
  - 对话流中自然引出

---

### E. 认证与远程访问（§6.10, §6.13）

- [ ] 🔴 **E-01** OAuth 认证（§6.13.1, DD-57）
  - Google + GitHub OAuth provider
  - FastAPI + authlib（或 python-social-auth）
  - JWT token 颁发 + 持久化
  - 本地 Electron / 远程 Web / Telegram / API 统一认证

- [ ] 🟡 **E-02** Tailscale Funnel 远程访问（§6.10.3）
  - 将本地 daemon API 暴露为 HTTPS URL
  - 远程设备浏览器直接访问

- [ ] 🟡 **E-03** macOS 开机自启动（§6.10.1）
  - launchd plist（`~/Library/LaunchAgents/com.daemon.startup.plist`）
  - 开机执行 `scripts/start.py`
  - 如果 Docker Desktop 未运行，先启动 Docker Desktop

---

### F. Telegram（§4.10）

- [ ] 🔴 **F-01** 4 个独立 Bot Token + 4 个独立 DM（§4.10, DD-63）
  - copilot / mentor / coach / operator 各一个 Bot
  - 当前 `interfaces/telegram/adapter.py` 是单 bot 模式，需改为 4 bot
  - 与桌面客户端完全同步

- [ ] 🟡 **F-02** Telegram 完整对话交互（§4.10）
  - 通知 + 品味确认 + 移动端完整对话
  - 品味类确认请求用户可直接在 Telegram 回复

---

### G. Persona（§5.3）

- [ ] 🔴 **G-01** Persona 文件层创建（§5.3, §4.11）
  - `persona/voice/identity.md`
  - `persona/voice/common.md`
  - `persona/voice/zh.md`
  - `persona/voice/en.md`
  - `persona/voice/overlays/*.md`
  - 当前 `persona/` 目录只有 `stage0_interview.md`，无 `voice/` 子目录

- [ ] 🟡 **G-02** Persona 更新链路（§5.4）
  - 品味类：Job closed → L1 列出风格类反馈候选 → 用户确认 → NeMo 校验 → 写入 Mem0
  - 系统级：admin 提出变更 → CC/Codex 审查 → 执行 → verify.py 验证

- [ ] 🟡 **G-03** Persona 漂移检测（§5.4.1）
  - 90 天未触发 Mem0 记忆 → CC/Codex 审查后清理
  - 矛盾检测 → admin 体检时发现 → CC/Codex 合并或删除

---

### H. 知识层（§5.6, §5.7, §8.3）

- [ ] 🟡 **H-01** RAGFlow 端到端验证
  - 上传 PDF → 分块 → 检索 → 命中
  - RAGFlow 容器已运行，API 已响应

- [ ] 🟡 **H-02** 来源标记 source markers（§8.3）
  - `[EXT:url]` / `[INT:persona]` / `[SYS:guardrails]`
  - 注入 agent prompt，存储在 Step output 元数据和 Artifact `source_markers` 字段
  - 当前无实现

- [ ] 🟡 **H-03** knowledge_cache TTL 分级（§5.6.1）
  - Tier A（arxiv/官方文档）= 90 天
  - Tier B（Wikipedia/MDN）= 30 天
  - Tier C（Reddit/匿名）= 7 天
  - 检查 `activities_maintenance.py` 清理逻辑是否按 tier 执行

- [ ] 🟡 **H-04** 隐私边界 NeMo input rail（§5.6.2）
  - MCP 调用前过滤 `sensitive_terms.json`
  - 被过滤词替换为通用描述

---

### I. 学习机制（§8）

- [ ] 🟡 **I-01** 规划经验学习（§8.2）
  - Job 成功后，L1 的规划决策（DAG 结构、模型策略、Step 分解方式）→ Mem0 procedural memory
  - 新任务时 Mem0 检索相关规划经验 → 注入 L1 prompt

- [ ] 🟡 **I-02** 反馈提取（§4.7）
  - L1 从对话中自然提取反馈信号
  - 用户说"不好" = 反馈，沉默 = accepted
  - 品味类 Persona 更新自然嵌入对话

---

### J. Quota（§5.8）

- [ ] 🟡 **J-01** 三层 Quota 机制（§5.8）
  - OC / session 层预算
  - Job 层预算
  - 系统日预算
  - NeMo Guardrails 硬规则执行 Quota 上限
  - 保守默认值，暖机后校准

---

### K. 基础设施脚本（§7.10, §6.9, §6.11）

- [ ] 🔴 **K-01** `scripts/start.py` 完善（§7.10）
  - 万能恢复点：从任意状态拉起 daemon 到正常运行
  - 包括：Docker Compose up → 等待健康检查 → PG migration → Temporal namespace → OC Gateway → Worker → API
  - 幂等，处理冷启动场景
  - 检测 PG 损坏 → 自动调用 restore.py
  - 当前 `scripts/start.py` 存在但需验证完整性

- [ ] 🟡 **K-02** `scripts/restore.py` 实现（§6.11）
  - `restore.py --date YYYY-MM-DD`
  - 从备份恢复 PG + MinIO 到指定日期状态
  - 当前文件是否存在需检查

- [ ] 🟡 **K-03** Schedule 丢失自动恢复（§6.9）
  - 所有 Schedule 定义存在 `config/schedules.json`
  - admin 体检时对比配置 vs Temporal 实际 → 缺失自动重建
  - 当前 `schedules.json` 存在，需检查体检逻辑是否包含此检查

- [ ] 🟡 **K-04** 备份 Job 完善（§6.11）
  - PG: `pg_dump` 到备份目录，每日，90 天滚动
  - MinIO: 增量备份（restic / rsync / MinIO versioning）
  - 当前 `activities_maintenance.py` 只 75 行，需验证备份逻辑

- [ ] 🟡 **K-05** `scripts/verify.py` 完善（§7.10）
  - 读取 issue 文件 → 运行验证用例 → 通过发 Telegram「已修复」/ 失败发「修复失败」

---

### L. 自愈与体检（§7）

- [ ] 🟡 **L-01** 三层自愈 Workflow（§7.8）
  - Layer 1: admin 自动修复（规则明确的问题）
  - Layer 2: SelfHealWorkflow（4 个 Activity：问题文件 → CC/Codex 修复 → start.py → verify.py）
  - Layer 3: publisher 推 Telegram 通知用户转发给 CC
  - 当前 `activities_health.py` 有 stub，需按 §7.8 完善

- [ ] 🟡 **L-02** 问题文件格式（§7.9）
  - `state/issues/YYYY-MM-DD-HHMM.md`
  - 自解释格式，CC/Codex 只读此文件即可修复

- [ ] 🟡 **L-03** 周度体检三层检测（§7.7）
  - 基础设施层：17 条数据链路验证
  - 质量层：固定基准任务套件
  - 前沿扫描层：researcher 扫描各领域最新最佳实践
  - 告警三档：GREEN / YELLOW / RED

- [ ] 🟡 **L-04** 体检报告存储（§7.7.4）
  - `state/health_reports/YYYY-MM-DD.json`
  - 目录已存在

---

### M. 数据生命周期（§6.12）

- [ ] 🟡 **M-01** Google Drive Artifact 同步（§6.12.1, DD-55）
  - 最终交付物 → MinIO → publisher 自动同步 → Google Drive → `gdrive_synced=true`
  - 30 天后清理已同步本地副本
  - 中间产物不同步，90 天后删除

- [ ] 🟡 **M-02** 数据清理 Job 完善（§6.12.2）
  - Ephemeral Job: 7 天后删除
  - 常规 Job: 30 天归档 → 90 天删除
  - event_log(consumed): 7 天删除
  - 体检报告: 52 周删除
  - Quota reset（§1.7）
  - 当前 `activities_maintenance.py` 需扩展

---

### N. 事件总线（§6.4）

- [ ] 🟡 **N-01** event_log 重放能力（§6.4）
  - Worker 重启后先补消费 `event_log` 未完成事件（`consumed_at IS NULL`），再恢复 NOTIFY 监听
  - 当前 `event_bus.py` 是否实现

- [ ] 🟡 **N-02** PG NOTIFY channel 对齐（附录 D.3）
  - `job_events` / `step_events` / `webhook_events` / `system_events`
  - 检查 event_bus.py channels 是否完整

---

### O. 外部工具与 Handoff（§3.12, §2.6）

- [ ] 🟡 **O-01** Handoff 机制（§3.12）
  - Claude Code: 写 `CLAUDE.md` + 打开 VSCode
  - Codex: 写 `AGENTS.md` + 打开 VSCode
  - 浏览器: `webbrowser.open(url)`
  - Handoff 是 Job DAG 最后一个 direct Step

- [ ] 🟡 **O-02** MCP server 补全（§2.6, §2.7）
  - 当前 4 个（firecrawl/semantic_scholar/paper_tools/code_tools）
  - 设计中还需要：GitHub MCP / Playwright MCP / Google Docs MCP / 社媒平台 MCP
  - 按暖机 Stage 0 确认的平台按需配置

---

### P. 配置文件（§6.7）

- [ ] 🟡 **P-01** `config/lexicon.json` 验证（§0.4）
  - 术语映射是否与 §1 一致
  - 当前文件存在

- [ ] 🟢 **P-02** 模型策略配置（§2.8）
  - 模型映射配置化，不硬编码
  - 当前 `config/model_registry.json` + `config/model_policy.json` 存在，需验证

---

### Q. OC Agent 层同步

- [ ] 🟡 **Q-01** SOUL.md 编写（§9.10.1）
  - general 哲学（所有 agent 共享）+ agent 专属哲学
  - 必须可操作化（不是抽象原则）

- [ ] 🟡 **Q-02** 方法论落地到 SKILL.md（§9.10.2）
  - L1: Routing Decision / DAG 规划 / Re-run 最小化 / Replan Gate / requires_review 判断
  - researcher: 搜索策略 / 分析框架 / 前沿扫描
  - engineer: 编码方法论 / CC/Codex handoff 上下文
  - writer: 写作方法论 / 多格式输出 / Persona 风格应用
  - reviewer: 审查方法论 / rework 反馈格式
  - publisher: 平台适配 / 发布前检查清单
  - admin: 诊断方法论 / 体检流程 / 自愈判断

- [ ] 🟡 **Q-03** MEMORY.md 每 agent ≤ 300 tokens（§3.3.3）
  - 检查 10 个 agent workspace 的 MEMORY.md 是否符合

---

### R. 代码清理

- [ ] 🟢 **R-01** 旧术语注释清理
  - `temporal/activities_exec.py` 和 `activities.py` 中 "deed→job, move→step" 旧术语注释

---

### S. 暖机（§7，Phase 6）

**前提**：A-01 ~ F-01 中的 🔴 项全部完成。

- [x] **Stage 0** 信息采集（已完成 — `persona/stage0_interview.md`）
- [ ] 🔴 **Stage 1** Persona 标定（§7.3 Stage 1）
  - LLM 分析写作样本 → 生成 Persona → Mem0 写入
  - writer 试写 + reviewer 校验
  - 用户确认
- [ ] 🔴 **Stage 2** 链路逐通（§7.3 Stage 2）
  - 17 条数据链路逐条验证（L01-L17）
  - 源头写入 → 传输 → 读取 → 消费 → 外部可见结果
- [ ] **Stage 3** 测试任务套件 + Skill 校准（§7.3 Stage 3）
  - 8-15 个真实复合场景，覆盖 4 个 L1 场景
  - Langfuse 检查每个 Step 的 token / 步骤 / reviewer 通过率
  - 不达标 → 修改 skill → 重跑
- [ ] **Stage 4** 系统状态与异常场景验证（§7.3 Stage 4）
  - 10 个异常场景（并发/超时/Agent 不可用/Worker 崩溃恢复/PG 断连/Plane 不可用/Guardrails 拦截/Quota 耗尽/Schedule 积压/大文件 Artifact）

**收敛标准**：伪人度 — 连续 5 个不同类型任务的对外产出与用户本人无法区分。

---

## 已完成记录

<details>
<summary>Phase 0-5 + 3.5 + Gap 修复 + 文档清理（点击展开）</summary>

### Phase 0：准备工作 ✅

- [x] 旧模块删除（spine/ psyche/ folio_writ cadence herald voice will ether retinue cortex）
- [x] 旧前端 Console 路由删除
- [x] Portal 重写为 Vite + React + Tailwind
- [x] MEMORY.md 更新架构转向记录

### Phase 1：基础设施 ✅

- [x] `docker-compose.yml` — 18 个容器
- [x] `.env.example`
- [x] Plane 初始化（workspace: daemon，API Token，登录流程已修通）
- [x] Langfuse 初始化
- [x] Redis 统一密码（`daemon-redis`）
- [x] RAGFlow 配置修复（DB_TYPE=postgres，service_conf.yaml mount，ragflow DB 创建）

### Phase 2：对象映射 + 胶水层 ✅

- [x] `services/plane_client.py` — Plane REST API 客户端
- [x] `services/store.py` — PG 数据层
- [x] `services/event_bus.py` — PG LISTEN/NOTIFY
- [x] `services/plane_webhook.py` — Webhook handler + 签名验证
- [x] `migrations/001_initial_schema.sql` + `scripts/init-databases.sql`
- [x] 旧 API 路由删除
- [x] `services/api_routes/scenes.py` — 场景 API 端点

### Phase 3：执行层适配 ✅

- [x] `temporal/workflows.py` — 5 个 workflow
- [x] `temporal/activities.py` + `activities_exec.py`
- [x] `temporal/worker.py` — 3 个 Temporal Schedules
- [x] Langfuse tracing 接入
- [x] 旧模块删除

### Phase 3.5：执行模型改进 ✅

- [x] L1 routing decision（direct/task/project 三条路径）
- [x] Step DAG 并行执行（depends_on 拓扑排序）
- [x] `temporal/activities_replan.py` — Replan Gate
- [x] Step 失败处理（RetryPolicy + L1 判断）

### Phase 4：知识层 + 记忆层 ✅

- [x] NeMo Guardrails（config/guardrails/）
- [x] Mem0 配置 + 冷启动脚本
- [x] MCP tools（4 个 server）
- [x] `config/sensitive_terms.json`
- [x] 1 个定时清理 Job

### Phase 5：Agent 层 ✅

- [x] 10 agents OC workspace 配置
- [x] 30 个 SKILL.md
- [x] `services/session_manager.py` — L1 持久 session + 4 层压缩
- [x] `runtime/mcp_dispatch.py` — MCP tool 调度
- [x] `config/skill_registry.json`
- [x] Telegram adapter 对话转发 + /scene 切换

### Gap 修复 ✅（10/10）

- [x] G-01 ~ G-10 全部完成

### Plane 登录修复 ✅（2026-03-16）

- [x] redirection_path.py / nginx CSRF / 移除 email.py 补丁

### 文档清理 ✅（2026-03-16）

- [x] SYSTEM_DESIGN.md §0.11 补充 / REFERENCE 修复 / IMPLEMENTATION_PLAN 更新 / MEMORY.md 修正 / TWO_LAYER 归档 / commit `21fedf8`

</details>

---

## 注意事项

### 双层系统
- 每改一处 Python 代码，检查 `openclaw/workspace/*/TOOLS.md` 和 `openclaw/openclaw.json` 是否需要同步
- openclaw/ 不在 git 里，但它是代码库的一部分

### 测试
- `pytest tests/` — 当前 68 个测试

### 许可证
- Plane: AGPL-3.0（自用无限制）
- MinIO: AGPL-3.0（同上）
- Langfuse: MIT（ee/ 目录除外）
