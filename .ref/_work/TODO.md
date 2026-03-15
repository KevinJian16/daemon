# Daemon 系统重建 TODO

> 日期：2026-03-16（更新）
> 状态：Phase 0-5 + 3.5 代码结构完成，进入 gap 修复 + 暖机阶段
> 依据：`.ref/SYSTEM_DESIGN.md`（七稿，唯一权威文档）

**核心方针**：用成熟开源方案替代自造组件，只保留最小胶水层。

---

## 关键文档索引

| 文档 | 路径 | 用途 |
|---|---|---|
| 系统设计总纲 | `.ref/SYSTEM_DESIGN.md` | **唯一权威设计文档**（七稿） |
| 配套参考文档 | `.ref/SYSTEM_DESIGN_REFERENCE.md` | 附录 B-I，查表用 |
| 实施记录 | `.ref/_work/IMPLEMENTATION_PLAN.md` | Phase 0-5 实施状态记录 |
| OC 文档缓存 | `.ref/_work/OC_DOCS_REFERENCE.md` | OpenClaw 平台机制参考 |
| 自我检讨 | `.ref/_work/SELF_REVIEW_2026-03-15.md` | 03-15 事故教训 |
| 旧文档 | `.ref/_archive/` | 仅供参考，术语已过期 |

---

## 术语速查

> 详见 SYSTEM_DESIGN.md §1。

| daemon 术语 | 含义 | Plane 映射 |
|---|---|---|
| **Project** | Task 容器 | `Project` / `Module` |
| **Draft** | 草稿 | `DraftIssue` |
| **Task** | 核心工作单元 | `Issue` |
| **Job** | Task 的一次执行记录（running→closed） | 无映射，daemon PG + Temporal |
| **Step** | Job 中的一步（1 目标，可调用任意 agent/tool） | — |
| **Artifact** | Job 交付物 | — |
| **L1 agent** | 场景 agent（4 个：copilot/mentor/coach/operator） | — |
| **L2 agent** | 执行 agent（6 个：researcher/engineer/writer/reviewer/publisher/admin） | — |

---

## 已完成 Phase（Phase 0-5 + 3.5）

以下 Phase 已于 2026-03-15 完成代码结构。详细实施记录见 `IMPLEMENTATION_PLAN.md`。

### Phase 0：准备工作 ✅

- [x] 旧模块删除（spine/ psyche/ folio_writ cadence herald voice will ether retinue cortex）
- [x] 旧前端 Console 路由删除
- [x] Portal 重写为 Vite + React + Tailwind（注：未归档，而是就地重写）
- [x] MEMORY.md 更新架构转向记录

### Phase 1：基础设施 ✅

- [x] `docker-compose.yml` — 18 个容器（PG/Redis/MinIO/Temporal/Plane 全家桶/Langfuse/ClickHouse/Elasticsearch/RAGFlow）
- [x] `.env.example`
- [x] Plane 初始化（workspace: daemon，API Token，登录流程已修通）
- [x] Langfuse 初始化（auto-provision daemon project）

### Phase 2：对象映射 + 胶水层 ✅

- [x] `services/plane_client.py` — Plane REST API 客户端
- [x] `services/store.py` — PG 数据层（daemon_tasks/jobs/job_steps/job_artifacts/knowledge_cache/event_log/conversation_*）
- [x] `services/event_bus.py` — PG LISTEN/NOTIFY（替代 Ether）
- [x] `services/plane_webhook.py` — Webhook handler + 签名验证
- [x] `migrations/001_initial_schema.sql` + `scripts/init-databases.sql`
- [x] 旧 API 路由删除（console_admin/console_runtime/portal_shell/folio_writ_routes）
- [x] `services/api_routes/scenes.py` — 场景 API 端点

### Phase 3：执行层适配 ✅

- [x] `temporal/workflows.py` — 5 个 workflow（Job/HealthCheck/Maintenance/Backup/Warmup）
- [x] `temporal/activities.py` + `activities_exec.py` — 全部改用 plane_client/store
- [x] `temporal/worker.py` — 3 个 Temporal Schedules（maintenance 6h/health-check 7d/backup 1d）
- [x] Langfuse tracing 接入（activities_exec.py 每个 step 创建 trace）
- [x] 旧模块删除（cadence.py/herald.py/activities_herald.py）

### Phase 3.5：执行模型改进 ✅

- [x] L1 routing decision（direct/task/project 三条路径）
- [x] Step DAG 并行执行（depends_on 拓扑排序）
- [x] `temporal/activities_replan.py` — Replan Gate
- [x] Step 失败处理（RetryPolicy + L1 判断）

### Phase 4：知识层 + 记忆层 ✅

- [x] NeMo Guardrails（`config/guardrails/` — config.yml/safety.co/actions.py）
- [x] Mem0 配置（`config/mem0_config.py`）+ 冷启动脚本
- [x] MCP tools（4 个 server：firecrawl_scrape/semantic_scholar/paper_tools/code_tools）
- [x] `config/sensitive_terms.json`
- [x] 1 个定时清理 Job（activities_maintenance.py）

### Phase 5：Agent 层 ✅

- [x] 10 agents OC workspace 配置（copilot/mentor/coach/operator/researcher/engineer/writer/reviewer/publisher/admin）
- [x] 30 个 SKILL.md
- [x] `services/session_manager.py` — L1 持久 session + 4 层压缩
- [x] `runtime/mcp_dispatch.py` — MCP tool 调度
- [x] `config/skill_registry.json`
- [x] Telegram adapter 支持对话转发 + /scene 切换

---

## 当前待做

### Gap 修复（9/10 已修，1 个待做）

已修复的 9 个 gap 见 MEMORY gap 清单。剩余：

- [ ] **G-10** RAGFlow 启用
  - Docker VM 磁盘扩容到 30GB+
  - 取消 docker-compose.yml 中 RAGFlow 相关注释
  - 验证：上传 PDF → 分块 → 检索 → 命中

### 文档修复

- [ ] **D-1** SYSTEM_DESIGN_REFERENCE.md 修复
  - DD-12 "对象模型精简 5→3" → 实际七稿有 6 个对象
  - 附录 G 正文 4 处 "v6" → "v7"
  - D-05 "arbiter" → "reviewer"

- [ ] **D-2** IMPLEMENTATION_PLAN.md 更新
  - §3.2 session key 描述过期（旧 `agent:{agent_id}:main` → 实际用 `spawn_session`）
  - Phase 6 "下一步" 过期（Stage 0 已完成）
  - 行数统计过期（activities_exec.py 220→407 等）
  - 29 vs 30 SKILL.md 内部矛盾

- [ ] **D-3** 代码中旧术语注释清理
  - `temporal/activities_exec.py` 和 `activities.py` 中 "deed→job, move→step, folio→project, writ→task" 旧术语注释

### 代码提交

- [ ] **C-1** 提交所有未 commit 的改动
  - ⚠ 当前所有 Phase 0-5 改动都是 unstaged 状态
  - `git checkout .` 会丢失全部工作成果
  - 需要整理后分批或一次性 commit

### Phase 6：暖机 = 系统标定

**完整方案**：SYSTEM_DESIGN.md §7

**暖机不是初始化，是图灵测试级标定。** 目标：daemon 所有对外输出达到"伪人"水准。

暖机分工：**CC 主导 Stage 0-2**（admin 不能暖机自己），**admin 主导 Stage 3+**。

- [x] **Stage 0** 信息采集（已完成 — persona/stage0_interview.md）
- [ ] **Stage 1** Persona 标定 — LLM 分析样本 → Mem0 persona → 试写验证
- [ ] **Stage 2** 链路逐通 — 17 条数据链路逐条验证
- [ ] **Stage 3** 测试任务套件 — 8-15 个真实复合场景，覆盖 4 个 L1 场景
- [ ] **Stage 4** 系统状态测试 — 10 个异常场景（并发/超时/故障恢复/积压）

收敛标准：**伪人度** — 连续 5 个不同类型任务的对外产出与用户本人无法区分。

---

## 注意事项

### 双层系统
- 每改一处 Python 代码，检查 `openclaw/workspace/*/TOOLS.md` 和 `openclaw/openclaw.json` 是否需要同步
- openclaw/ 不在 git 里，但它是代码库的一部分

### 测试
- `pytest tests/` — 当前 68 个测试
- Phase 6 的诊断测试是最终验证

### 许可证
- Plane: AGPL-3.0（自用无限制）
- MinIO: AGPL-3.0（同上）
- Langfuse: MIT（ee/ 目录除外）
