# daemon TODO

> Rewritten 2026-03-17. Source of truth: SYSTEM_DESIGN.md 七稿 + DD-78/79/80.
> Goal: complete all items → warmup Stage 1-4.

## Current State

- **Python 层 + OC agent 层**：Phase 0-5 代码实现完成
- **Docker**：21 容器运行中
- **MCP servers**：45 个已注册（config/mcp_servers.json），34 个 Python 脚本已写
- **Tauri 桌面客户端**：可构建运行（8MB .app），UI 设计完成（shadcn + Bricolage Grotesque）
- **Warmup 脚本**：Stage 0-4 框架就绪，未实际运行
- **§10 禁止事项**：48 条全部审计通过

---

## ❌ NOT DONE — Blocks warmup

### 1. Tauri P1（客户端完善）

- [ ] **菜单栏 tray icon（绿/黄/红状态指示）** — P0 声称完成但实际未实现，lib.rs 里只有窗口定位
- [ ] **4 个场景 panel（PG 数据驱动）** — 后端 API 就绪，前端 PanelView.jsx 是占位
- [ ] **菜单栏右键菜单**（Start/Stop、任务数、体检状态、Langfuse/Temporal UI 入口）
- [ ] **全局快捷键**（唤起/隐藏主窗口）

### 2. Mem0 集成验证

- [ ] **mem0_client.py 不存在** — mem0_config.py 有了，但没有实际调用 Mem0 API 的客户端封装
- [ ] **activity_post_job_learn 是否真正接上 Mem0** — 需要验证 Job 完成后 distillation（提取+整合）是否工作
- [ ] **Mem0 是否自动做 consolidation** — 查 Mem0 API 文档确认，如果自动做则 Background Maintenance 的记忆蒸馏可简化

### 3. Skill 可靠性（§9.5.1）— 暖机 Stage 3 前置依赖

- [ ] CI 脚本：YAML frontmatter 校验
- [ ] CI 脚本：description 格式校验（ALWAYS/NEVER 祈使句）
- [ ] CI 脚本：字符预算计算（< 30000）
- [ ] CI 脚本：SKILL.md 行数校验（< 500）
- [ ] OC 配置：SLASH_COMMAND_TOOL_CHAR_BUDGET=30000
- [ ] 所有 SKILL.md description 重写为祈使句
- [ ] Skill Activation 测试框架（每 skill ≥3 次触发，< 80% 阻断）
- [ ] 关键 skill Hook 强制（routing_decision / requires_review_judgment）

### 4. InfoPull Workflow（§2.7.1, 信息监控基础设施）

- [ ] Temporal Schedule `InfoPullWorkflow`
- [ ] Activity: `pull_sources`（direct，调 MCP 拉取）
- [ ] Activity: `triage_results`（agent，researcher 分析分级）
- [ ] Activity: `store_results`（direct，存 RAGFlow / knowledge_cache）
- [ ] Activity: `notify_urgent`（direct，紧急信息推 Telegram）
- [ ] PG 表 `info_subscriptions`
- [ ] 配置 `config/info_triage_rules.toml`

### 5. Background Maintenance（§5.9, 系统自维护）

- [ ] `BackgroundMaintenanceWorkflow`（Temporal Schedule，统一调度）
- [ ] **记忆整理**：取决于 Mem0 是否自动 consolidation。如果不自动，需 memory_merge + memory_gc
- [ ] **Persona 深度分析**：每周从近期交互提取偏好变化
- [ ] **规划经验整合**：合并 planning_experience 为策略级洞察
- [ ] **知识库维护**：knowledge_audit + source_credibility + artifact_review
- [ ] **系统自省 + 周期性快照**：收集本周 Job 执行记录 / agent 调用模式 / 失败率 → 存结构化快照 → 喂给自省任务 → 输出改进建议
- [ ] **Ollama 资源隔离**：队列串行 + 实时优先 + 30 分钟超时

### 6. RSSHub 部署

- [ ] Docker 容器 + MCP wrapper，解决 Reddit/知乎/小红书反爬

---

## ⏳ NOT DONE — Not blocking warmup

### 7. Tauri P2+

- [ ] [P2] iOS Tauri artifact 查看器（只读）— DD-79
- [ ] [P3] macOS 开机自启动（launchd plist 已创建，未验证）

### 8. Google MCP OAuth 补全

- [x] Google OAuth token 已获取（~/.daemon/google_token.json）
- [ ] Gmail MCP — 代码写好，OAuth 通了，未做端到端测试
- [ ] Google Calendar MCP — 同上
- [ ] Google Docs MCP — 同上
- [ ] Google Drive MCP — 同上

### 9. MCP servers 端到端验证

45 个已注册，代码已写，但大部分未做端到端测试：
- [ ] 逐个验证 Python MCP server 能启动、tool 能调用、返回正确结果
- [ ] 验证需要 API key 的 MCP（Twitter/Strava/intervals.icu/Dev.to/Hashnode/Libraries.io/NewsData/Kaggle）是否有对应 key 在 .env
- [ ] 验证 npm 包 MCP（zotero/academix/dblp/echarts/leetcode/openweathermap）能 npx 启动

### 10. 前端遗留

- [ ] Electron 残留目录 `interfaces/portal/electron/` — 可删除
- [ ] Panel 前端实现（目前 PanelView.jsx 只有 Digests/Decisions 占位，需按 CLIENT_SPEC §2.2 重写）

---

## ✅ DONE — Completed items（压缩）

### Python 层
- Phase 0-5 全部 🔴🟠🟡🟢🧹 代码实现 ✅
- 旧代码全部删除（spine/ psyche/ folio_writ cadence herald ether retinue cortex）✅
- 新胶水层（plane_client store event_bus session_manager minio_client ragflow_client quota）✅
- NeMo Guardrails 两层 ✅
- OAuth + JWT ✅
- Temporal workflows + activities 全套 ✅
- Langfuse trace ✅
- Ollama 本地 LLM（qwen2.5:32b/7b + nomic-embed）+ llm_local.py ✅

### OC Agent 层
- 10 agents workspace（SOUL.md/TOOLS.md/AGENTS.md/MEMORY.md/SKILL_GRAPH.md）✅
- Stage 0 Persona 采访完成 ✅
- Skills 结构创建 ✅

### 基础设施
- Docker Compose 21 容器 ✅
- Firecrawl 自建部署 + SSRF 修复 ✅
- Docker mem_limit 防护 ✅
- Embedding primary → nomic-embed-text ✅

### 桌面客户端
- Tauri 构建 + 8MB .app ✅
- UI：shadcn/ui + Bricolage Grotesque + 暖色 mauve 色板 ✅
- Zoom 1.25（Tauri 自动）✅
- 15% 左边距窗口定位 ✅
- OAuth branded 完成页 ✅
- Icon（淡紫渐变）✅

### MCP Servers
- 45 个注册到 mcp_servers.json ✅
- 34 个 Python 脚本写完 ✅
- 6 个 npm 包直接注册 ✅
- Google OAuth helper + token 获取 ✅

### 设计决策
- DD-78：Electron → Tauri + 原生应用调起 ✅
- DD-79：多平台（macOS Tauri + iOS Tauri + Telegram 信箱）✅
- DD-80：取消自动分屏，窗口布局交给 Stage Manager ✅
- §10 禁止事项 48 条审计 ✅

### 文件类型 → 应用映射
- PDF → Zotero ✅
- 图片 → Preview.app ✅
- Markdown/HTML → 系统浏览器 ✅
- 代码 → VS Code ✅

---

## ~~取消的项目~~

- ~~远程访问 + PWA~~ — DD-79：不做 Web 端
- ~~BrowserView / 阅读器 / Monaco~~ — DD-78：原生应用调起
- ~~自动分屏（macos-control 编排窗口）~~ — DD-80：与 Stage Manager 冲突
- ~~Electron~~ — DD-78：Tauri 替代

---

## Warmup（§7）— 上述 1-6 全部完成后

- [x] **Stage 0** — Persona 采访（`persona/stage0_interview.md`）✅
- [ ] **Stage 1** — Persona 校准：LLM 分析写作样本 → 生成 Persona → Mem0 → writer 试写 + reviewer 校验
- [ ] **Stage 2** — 链路验证：17 条数据链路端到端（`warmup/stage2_link_verification.py`）
- [ ] **Stage 3** — 测试任务 + Skill 校准：8-15 个真实任务（`warmup/stage3_runner.py`）
- [ ] **Stage 4** — 异常场景验证：10 个场景（`warmup/stage4_exceptions.py`）

**收敛标准**：pseudo-human — 连续 5 个不同类型任务的外部产出，与用户本人风格无法区分。
