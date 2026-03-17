# TODO Audit — OpenClaw Layer

审计日期：2026-03-16
审计依据：SYSTEM_DESIGN.md 七稿 §1.4 / §3 / §6.3 / §9 / §10

---

## openclaw.json 整体评估

### Agent 配置
- ✅ 10 agents 全部注册（4 L1 + 6 L2），ID 与 §1.4 一致
- ✅ 每个 agent 有独立 workspace 路径
- ✅ 每个 agent 有独立 agentDir
- 🔧 `maxConcurrent` 设为 4，§B.2 要求默认 8（`agents.defaults.maxConcurrent`）
- 🔧 `subagents.maxConcurrent` 设为 8，正确——但缺少 `maxChildrenPerAgent`（§B.2 要求默认 5）和 `maxSpawnDepth`（§B.2 要求默认 2）
- 🔧 缺少 L1 agent 的 `compaction` 配置差异化——§3.3.1 要求 L1 proactive compression at 70% contextTokens，当前全局只有 `"mode": "safeguard"`
- ✅ `contextPruning` cache-ttl = 5m，与 §B.2 一致

### Model 配置
- ✅ 4 个 provider（minimax-cn, deepseek, zhipu, qwen）已注册
- ✅ researcher 使用 deepseek-reasoner（analysis 模型）
- ✅ writer 使用 zhipu/glm-z1-flash（creative 模型）
- ✅ reviewer 使用 qwen/qwen-max（review 模型）
- 🔧 L1 agents 缺少双模型配置：§2.8 要求 L1 有 fast（conversation）和 analysis（planning）两个模型，当前只有全局 primary（minimax M2.5）
- ✅ publisher/engineer/admin 使用默认 fast 模型，与 §2.8 一致

### Telegram 配置
- ✅ 4 个 Telegram bot token（copilot/mentor/coach/operator）
- ✅ bindings 将 4 个 L1 agent 绑定到各自 Telegram accountId
- ✅ dmPolicy = "pairing"，符合 §4.10 DM 独立对话

### Gateway 配置
- ✅ auth mode = token
- ✅ gateway tools 包含 sessions_spawn / sessions_send / sessions_history / session_status
- 🔧 gateway tools 包含 `whatsapp_login`——七稿无 WhatsApp 需求，多余
- 🔧 缺少 `sessions_close` 在 gateway tools 白名单中（L2 session 关闭需要）

### 其他
- 🔧 `.openclaw/agents/` 目录有遗留 agent：counsel, scout, scout_0, scout_1, ghost, router, main, analyze, apply, build, collect, render, review, nonexistent_agent_xyz——全部是旧术语或测试残留，应清理（§1.8 术语清理要求）

---

## Agent: copilot (L1)

### SOUL.md
- 🔧 使用 OC 默认模板（"You're not a chatbot. You're becoming someone."），未包含 §9.10.1 要求的 agent 专属哲学
- ❌ 缺少 §9.10.1 要求的 general 共享哲学：认知诚实、先看前沿再行动、最小必要行动、质量 > 速度
- ❌ 缺少 copilot 专属哲学：规划审慎性（宁可少做不可乱做）
- ❌ 与 mentor/coach/operator/researcher/engineer/writer/reviewer/publisher/admin 的 SOUL.md 完全相同——违反 §9.10.1 "agent 专属哲学" 要求

### TOOLS.md
- ✅ 正确标注角色为 L1 Scene Agent — Work Collaboration
- ✅ 包含 Routing Decision 三条路线（direct/task/project）
- ✅ L2 agents 列表完整（6 个）
- ✅ Skills 引用了 task_decomposition 和 replan_assessment
- 🔧 Routing Decision 引用 "§3.8" 应为 "§3.1"
- 🔧 缺少 §3.1 routing decision 输出格式中的 `model` 字段（L1 可选 model override）
- 🔧 缺少 §9.10.2 要求的 L1 行为层方法论引用：requires_review 判断、rerun 意图判断、用户意图解析

### IDENTITY.md
- ✅ 存在，角色描述正确
- ✅ 提到 4-layer compression 和 Mem0

### AGENTS.md
- 🔧 使用 OC 默认模板，大量内容与 daemon 架构无关（Discord/WhatsApp 格式化、heartbeat 检查邮箱/日历/天气等）。§9.10.1 说 "AGENTS.md 保留为通用行为规范"，但当前内容是 OC 通用模板而非 daemon 定制的通用行为规范

### Skills
- ✅ task_decomposition — 6 sections 完整，内容合理
- ✅ replan_assessment — 6 sections 完整，内容合理
- 🔧 缺少 §9.10.2 L1 要求的更多行为层 skill：Routing Decision 判断（独立 skill）、requires_review 判断、rerun 意图判断、用户意图解析。当前只有 2 个 skill，§7.2 Phase 5 要求每 agent ≥ 3-5 个核心 skill

---

## Agent: mentor (L1)

### SOUL.md
- 🔧 与 copilot 完全相同的 OC 默认模板——缺少 §9.10.1 mentor 专属哲学

### TOOLS.md
- ✅ 正确标注角色为 L1 Scene Agent — Learning & Growth
- ✅ Routing Decision 包含三条路线
- ✅ L2 agents 列表（researcher, writer, reviewer）
- 🔧 L2 agents 列表不完整——mentor 场景也可能需要 engineer（技术学习）、publisher（发布学习成果）、admin
- 🔧 与 copilot 相同的 §3.8 引用错误

### Skills
- ✅ task_decomposition — 与 copilot 完全相同（L1 共享）
- ✅ replan_assessment — 与 copilot 完全相同（L1 共享）
- 🔧 只有 2 个 skill，低于 §7.2 要求的 3-5 个

### 缺少
- ❌ AGENTS.md 不存在（copilot/operator/engineer/publisher/researcher/reviewer/writer/admin 都有，mentor 和 coach 没有）
- ❌ IDENTITY.md 存在但未验证（已知存在）
- ❌ USER.md 不存在（copilot/operator 等有 USER.md，mentor 没有）

---

## Agent: coach (L1)

### SOUL.md
- 🔧 与 copilot 完全相同的 OC 默认模板——缺少 §9.10.1 coach 专属哲学

### TOOLS.md
- ✅ 正确标注角色为 L1 Scene Agent — Life Management
- ✅ Routing Decision 包含三条路线
- 🔧 L2 agents 列表只有 admin 和 publisher——缺少 researcher/writer/reviewer
- 🔧 与 copilot 相同的 §3.8 引用错误

### Skills
- ✅ task_decomposition — L1 共享
- ✅ replan_assessment — L1 共享
- 🔧 只有 2 个 skill，低于 §7.2 要求的 3-5 个

### 缺少
- ❌ AGENTS.md 不存在
- ❌ USER.md 不存在

---

## Agent: operator (L1)

### SOUL.md
- 🔧 与 copilot 完全相同的 OC 默认模板——缺少 §9.10.1 operator 专属哲学

### TOOLS.md
- ✅ 正确标注角色为 L1 Scene Agent — System Operations
- ✅ Routing Decision 包含三条路线
- 🔧 L2 agents 只列了 admin——缺少 engineer（技术操作）
- 🔧 与 copilot 相同的 §3.8 引用错误

### Skills
- ✅ task_decomposition — L1 共享
- ✅ replan_assessment — L1 共享
- 🔧 只有 2 个 skill，低于 §7.2 要求的 3-5 个

---

## Agent: researcher (L2)

### SOUL.md
- 🔧 与所有 agent 完全相同的 OC 默认模板——缺少 §9.10.1 researcher 专属哲学：知识可靠性（多源交叉验证、标注置信度）

### TOOLS.md
- ✅ 正确标注角色为 L2 Execution Agent
- ✅ MCP tools 列表完整（brave_search, semantic_scholar_*, firecrawl_*, code_*)
- ✅ Skills 引用了 4 个（academic_search, web_research, literature_review, source_evaluation）
- ✅ 执行模型说明正确（1 Step = 1 Session）
- 🔧 Session key 格式为 "agent:researcher:main"——§3.3.2 要求 `{agent_id}:{job_id}:{step_id}`

### Skills (4 个，达标)
- ✅ academic_search — 6 sections 完整，步骤可执行，引用 semantic_scholar MCP tools
- ✅ web_research — 6 sections 完整，包含交叉验证、source_tier 意识
- ✅ literature_review — 6 sections 完整，含效率指导
- ✅ source_evaluation — 6 sections 完整，Tier A/B/C 评估逻辑正确
- 🔧 缺少 §9.3 提到的 "Knowledge Base 管理" skill 和 "推理框架" skill

---

## Agent: engineer (L2)

### SOUL.md
- 🔧 与所有 agent 完全相同的 OC 默认模板——缺少 §9.10.1 engineer 专属哲学：工程简洁性（最简实现、可读性优先）

### TOOLS.md
- ✅ 正确标注角色为 L2 Execution Agent
- ✅ MCP tools 列表合理（code_functions, code_structure, code_imports, read_file, write_file, Shell, Git）
- ✅ Skills 引用 4 个
- ✅ 执行模型说明正确
- 🔧 Session key 格式与 §3.3.2 不一致

### Skills (4 个，达标)
- ✅ code_review — 6 sections 完整
- ✅ debug_locate — 6 sections 完整，根因分析链路追踪方法论
- ✅ implementation — 6 sections 完整
- ✅ refactor — 6 sections 完整
- 🔧 缺少 §9.10.2 提到的 "CC/Codex handoff 上下文准备" skill

---

## Agent: writer (L2)

### SOUL.md
- 🔧 与所有 agent 完全相同的 OC 默认模板——缺少 §9.10.1 writer 专属哲学：写作真实性（准确表达，风格服务于内容）

### TOOLS.md
- ✅ 正确标注角色为 L2 Execution Agent
- ✅ MCP tools 列表合理（latex_compile, bibtex_format, chart_matplotlib, chart_mermaid, read_file, write_file）
- ✅ Skills 引用 5 个
- ✅ 默认模型标注 creative（GLM Z1 Flash）
- ✅ 提到 Persona/Mem0 style 注入
- 🔧 Session key 格式与 §3.3.2 不一致

### Skills (5 个，超标)
- ✅ tech_blog — 6 sections 完整
- ✅ academic_paper — 6 sections 完整
- ✅ documentation — 6 sections 完整，含多种 doc_type
- ✅ data_visualization — 6 sections 完整，含 matplotlib/mermaid MCP 调用
- ✅ announcement — 6 sections 完整

---

## Agent: reviewer (L2)

### SOUL.md
- 🔧 与所有 agent 完全相同的 OC 默认模板——缺少 §9.10.1 reviewer 专属哲学：评判公正性（基于标准非偏好，给可行改进建议）

### TOOLS.md
- ✅ 正确标注角色为 L2 Execution Agent
- ✅ MCP tools 合理（semantic_scholar_paper, firecrawl_scrape, brave_search, code_functions）
- ✅ Skills 引用 3 个
- ✅ 默认模型标注 review（Qwen Max）
- ✅ Review Checklist 5 维度（准确性、一致性、风格、格式、完整性）
- ✅ 输出格式 JSON（passed/issues/suggestions）
- 🔧 §1.4.3 要求 "reviewer 只 identifies issues，不 directly fixes artifacts"——TOOLS.md 未明确声明此约束
- 🔧 Session key 格式与 §3.3.2 不一致

### Skills (3 个，达标)
- ✅ fact_check — 6 sections 完整，Tier A/B/C 分类正确
- ✅ code_review — 6 sections 完整（注意：engineer 也有 code_review skill，reviewer 版本独立）
- ✅ quality_audit — 6 sections 完整
- 🔧 缺少 §9.10.2 提到的 "rework 反馈格式" 和 "不同任务类型审查侧重" 的方法论

---

## Agent: publisher (L2)

### SOUL.md
- 🔧 与所有 agent 完全相同的 OC 默认模板——缺少 §9.10.1 publisher 专属哲学：传播负责任（发出去的代表用户）

### TOOLS.md
- ✅ 正确标注角色为 L2 Execution Agent
- ✅ 提到 Telegram OC native channel 和 GitHub MCP
- ✅ Skills 引用 3 个
- ✅ Delivery Rules 合理
- 🔧 §2.6 要求 publisher 是 sole external outlet agent——TOOLS.md 未明确声明此独占职责
- 🔧 缺少 §2.6 提到的社交媒体 MCP tools
- 🔧 Session key 格式与 §3.3.2 不一致

### Skills (3 个，达标)
- ✅ telegram_notify — 6 sections 完整，MarkdownV2 格式化
- ✅ github_publish — 6 sections 完整
- ✅ release_checklist — 6 sections 完整
- 🔧 缺少 §9.10.2 提到的 "各平台适配方法论" skill（不同平台格式/长度/风格）
- 🔧 缺少 §6.12.1 Google Drive 同步 skill

---

## Agent: admin (L2)

### SOUL.md
- 🔧 与所有 agent 完全相同的 OC 默认模板——缺少 §9.10.1 admin 专属哲学：维护谨慎性（先诊断再动手，小改动优于大重构）

### TOOLS.md
- ✅ 正确标注角色为 L2 Execution Agent
- ✅ Available Tools 合理（scripts/verify.py, scripts/start.py, Langfuse API, PG, code_structure）
- ✅ Skills 引用 3 个
- ✅ Responsibilities 包含 weekly health check, issue file generation, skill calibration, schedule verification, Mem0 cleanup
- ✅ Health Check Thresholds 与 §B.6 一致
- 🔧 Session key 格式与 §3.3.2 不一致

### Skills (3 个，达标)
- ✅ health_check — 6 sections 完整，含 3 层状态判定
- ✅ incident_response — 6 sections 完整，止血优先方法论
- ✅ skill_audit — 6 sections 完整，基于 Langfuse trace 数据驱动
- 🔧 缺少 §9.10.2 提到的 "体检流程执行方式" skill（3 层检测：基础设施+质量+前沿扫描）
- 🔧 缺少 §7.7.3 "前沿驱动的自我迭代" 判断 skill

---

## Skills 总览

### 结构合规性
- ✅ 所有 SKILL.md 都存放在 `openclaw/workspace/{agent_id}/skills/{skill_name}/SKILL.md`——与 §9.1 一致
- ✅ 所有 SKILL.md 都包含 6 个 section（适用场景、输入、执行步骤、质量标准、常见失败模式、输出格式）——与 §9.1 一致
- ✅ 步骤具体可执行，不是 "做好" 式的空话
- ✅ 每个 skill 聚焦一件事（§9.2）

### Skill 数量
| Agent | 当前 | §7.2 要求 (≥3-5) | 状态 |
|-------|------|-------------------|------|
| copilot | 2 | 3-5 | 🔧 不足 |
| mentor | 2 | 3-5 | 🔧 不足 |
| coach | 2 | 3-5 | 🔧 不足 |
| operator | 2 | 3-5 | 🔧 不足 |
| researcher | 4 | 3-5 | ✅ 达标 |
| engineer | 4 | 3-5 | ✅ 达标 |
| writer | 5 | 3-5 | ✅ 达标 |
| reviewer | 3 | 3-5 | ✅ 达标 |
| publisher | 3 | 3-5 | ✅ 达标 |
| admin | 3 | 3-5 | ✅ 达标 |

### 缺失的 Skill（§9.3 + §9.10.2 要求但不存在）
| Agent | 缺失 Skill | 来源 |
|-------|-----------|------|
| L1 (all) | routing_decision | §9.10.2 — Routing Decision 判断独立 skill |
| L1 (all) | requires_review_judgment | §9.10.2 — requires_review 判断 |
| L1 (all) | rerun_intent_parsing | §9.10.2 — rerun 意图判断 |
| L1 (all) | user_intent_parsing | §9.10.2 — 用户意图解析 |
| researcher | knowledge_base_mgmt | §9.3 — Knowledge Base 管理 |
| engineer | cc_codex_handoff | §9.10.2 — CC/Codex handoff 上下文准备 |
| reviewer | rework_feedback | §9.10.2 — rework 反馈格式 |
| publisher | platform_adaptation | §9.10.2 — 各平台适配方法论 |
| admin | health_check_3layer | §7.7.1 — 三层检测流程（当前 health_check 只覆盖基础设施层）|

---

## 横切问题

### SOUL.md 全局问题
- ❌ 所有 10 个 agent 的 SOUL.md 完全相同（OC 默认模板）
- ❌ §9.10.1 要求 general 共享哲学 + agent 专属哲学，当前两者都缺失
- ❌ 当前 SOUL.md 内容（"Have opinions", "Be the assistant you'd actually want to talk to"）是 OC 通用 AI companion 设定，不是 daemon 的执行 agent 哲学
- 🔧 需要：(1) 编写 general 共享 SOUL.md 内容（认知诚实/先看前沿/最小行动/质量>速度），(2) 每个 agent 追加专属哲学 section

### AGENTS.md 全局问题
- 🔧 只有 copilot/operator/engineer/publisher/researcher/reviewer/writer/admin 有 AGENTS.md（8/10）
- ❌ mentor 和 coach 缺少 AGENTS.md
- 🔧 现有 AGENTS.md 全部是 OC 默认模板（Discord/WhatsApp 格式化、heartbeat 检查邮箱、voice storytelling 等），与 daemon 架构无关，需要定制化

### MEMORY.md
- ❌ 没有任何 agent 有 MEMORY.md 文件——§3.3.3 要求每个 agent MEMORY.md ≤ 300 tokens（identity + 最高优先行为规则）
- 这是 §7.3/S1 Stage 1 Persona 标定的产出，暖机前暂可接受，但 Phase 5 前提要求至少有草稿

### Session Key 格式
- 🔧 所有 L2 agent TOOLS.md 中 session key 写为 "agent:{id}:main"，§3.3.2 要求 `{agent_id}:{job_id}:{step_id}`——属于文档不匹配，实际 session key 由 Python 层控制

### .openclaw/agents/ 残留
- 🔧 `.openclaw/agents/` 目录有 25 个 agent 目录，只有 10 个是有效的。以下 15 个应清理：
  - counsel（旧 L1 术语）
  - scout, scout_0, scout_1（旧 researcher 术语）
  - ghost, router, main（测试/内部）
  - analyze, apply, build, collect, render, review（旧 subagent）
  - nonexistent_agent_xyz（测试残留）

### MCP 配置
- ✅ config/mcp_servers.json 包含：brave-search, filesystem, semantic-scholar, code-functions, firecrawl, github, paper-tools
- 🔧 缺少 Playwright MCP（§2.6 login-required 平台需要）
- 🔧 TOOLS.md 中提到的 `latex_compile`, `bibtex_format`, `chart_matplotlib`, `chart_mermaid` 工具不在 mcp_servers.json 中——可能是写入 workspace 的内置 tool 或尚未实现
- 🔧 缺少 Google Drive MCP（§6.12.1 Artifact 同步到 Google Drive）

---

## 总结

| 类别 | ✅ | 🔧 | ❌ |
|------|----|----|---|
| openclaw.json agent 注册 | 10/10 | — | — |
| openclaw.json 参数配置 | 3 | 5 | — |
| SOUL.md 存在 | 10/10 | — | — |
| SOUL.md 内容匹配 §9.10.1 | 0/10 | 10/10 | — |
| TOOLS.md 存在 | 10/10 | — | — |
| TOOLS.md 内容基本正确 | 10/10 | 多处细节 | — |
| AGENTS.md 存在 | 8/10 | — | 2 (mentor, coach) |
| IDENTITY.md 存在 | 10/10 | — | — |
| MEMORY.md 存在 | 0/10 | — | 10/10 |
| Skills 存在且 6-section | 30/30 | — | — |
| Skills 数量 ≥ 3 | 6/10 | 4 (L1) | — |
| Skills 覆盖 §9.10.2 | 部分 | 需补 ~9 个 | — |
| .openclaw 清理 | — | 15 残留 | — |

### 关键行动项
1. **CRITICAL**: 重写所有 SOUL.md — 从 OC 默认模板替换为 daemon general 共享哲学 + agent 专属哲学
2. **HIGH**: 为 4 个 L1 agent 补充 skill 到 ≥ 3 个（routing_decision, user_intent_parsing, requires_review_judgment）
3. **HIGH**: 为每个 agent 创建 MEMORY.md 草稿（≤ 300 tokens）
4. **MEDIUM**: 修正 openclaw.json 参数（maxConcurrent=8, 补 maxChildrenPerAgent, maxSpawnDepth）
5. **MEDIUM**: 清理 .openclaw/agents/ 15 个残留 agent 目录
6. **MEDIUM**: 定制 AGENTS.md（去掉 OC 默认的 Discord/WhatsApp/heartbeat 内容，写 daemon 通用行为规范）
7. **LOW**: 修正 TOOLS.md 中 session key 格式、§3.8→§3.1 引用错误
8. **LOW**: 补充 TOOLS.md 中缺失的约束声明（reviewer 不直接修复、publisher 独占外部出口）
