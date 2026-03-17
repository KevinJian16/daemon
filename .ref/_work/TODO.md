# daemon TODO

> Rewritten 2026-03-17. Method: SYSTEM_DESIGN.md every section audited against actual code.
> Goal: fix all issues → warmup Stage 1-4 → production.

---

## 🔴 CRITICAL — Runtime crashes or broken data paths

### C1. Worker missing 4 activity registrations
**Section**: §3.5, §3.6.2, §3.8, §8.1
**Problem**: `JobWorkflow` calls 4 activities that are NOT registered in `temporal/worker.py`: `activity_post_job_learn`, `activity_persona_taste_update`, `activity_minimize_redo_scope`, `activity_l1_failure_judgment`. Any Job that completes/fails/re-runs will crash with `ActivityNotRegisteredError`.
**Fix**: In `temporal/worker.py`, add these 4 to the `activities=` list in `Worker()` constructor. They already exist in `DaemonActivities` class — just not registered.
**Files**: `temporal/worker.py`
**Effort**: 10 minutes

### C2. Chain trigger has no downstream handler
**Section**: §3.10
**Problem**: `activity_trigger_chain` publishes `chain_triggered` event to PG EventBus, but nothing subscribes to this event to create the downstream Job. Chain triggers are fire-and-forget.
**Fix**: Add an event handler in the API process (or Worker) that listens for `chain_triggered` events and calls `_submit_job()` to start the downstream Task's Job.
**Files**: `services/api.py` or `temporal/worker.py` (subscriber), `services/event_bus.py`
**Effort**: 2 hours

### C3. Auth not enforced on API endpoints
**Section**: §6.13.1
**Problem**: OAuth flow exists but scene/chat/panel endpoints have no `Depends(get_current_user)`. Anyone on the local network can use the API.
**Fix**: Add `current_user: User = Depends(get_current_user)` to all scene/panel/job/artifact endpoints in `api_routes/scenes.py`. Keep `/status` and `/health` public.
**Files**: `services/api_routes/scenes.py`, `services/api.py`
**Effort**: 1 hour

### C4. Panel structured data — 5 Store methods missing
**Section**: §4.2
**Problem**: `_copilot_structured()`, `_mentor_structured()`, `_coach_structured()` call Store methods that don't exist: `list_projects()`, `list_active_tasks()`, `list_tasks_by_source()`, `list_jobs_by_source()`, `get_job_metrics()`. Panels silently return empty data.
**Fix**: Implement 5 methods in `services/store.py`:
- `list_projects()` → `SELECT * FROM daemon_tasks WHERE task_type='project' AND status!='closed'`
- `list_active_tasks(project_id?)` → `SELECT * FROM daemon_tasks WHERE status IN ('open','in_progress')`
- `list_tasks_by_source(source)` → filter by `source` column (instructor assignments etc.)
- `list_jobs_by_source(source)` → filter jobs by source metadata
- `get_job_metrics(scene, days=7)` → aggregate job success/fail/duration stats
**Files**: `services/store.py`
**Effort**: 3 hours

---

## 🟠 HIGH — Core features not implemented

### H1. Project route not implemented
**Section**: §3.1
**Problem**: L1 routing decision `action: "project"` is treated identically to `task` — no Plane Project creation, no multi-Task DAG, no IssueRelation dependencies.
**Fix**: Create `_submit_project()` in `services/api_routes/scenes.py`:
1. `plane_client.create_project(title)` → get project_id
2. Loop over `tasks[]` array: `plane_client.create_issue()` per task
3. Create `IssueRelation` (blocked_by) between tasks based on dependencies
4. Start entry task's first Job via `_submit_job()`
**Files**: `services/api_routes/scenes.py`, `services/plane_client.py` (may need `create_project()`)
**Effort**: 4 hours

### H2. WebSocket message type protocol
**Section**: §4.9
**Problem**: Server sends raw `{type: "reply"}` messages. Design requires 6 typed messages: `text`, `panel_update`, `native_open`, `artifact_show`, `status_update`, `notification`. Frontend has no type-based dispatch.
**Fix**:
- Server: In `scenes.py` WebSocket handler, wrap all outgoing messages with the type field per §4.9 table
- Client: In `SceneChat.jsx` or a new message dispatcher, route by type: `text` → message thread, `panel_update` → refresh panel, `native_open` → call Tauri open command, etc.
**Files**: `services/api_routes/scenes.py`, `interfaces/portal/src/components/SceneChat.jsx`
**Effort**: 4 hours

### H3. native_open implementation
**Section**: §4.2, DD-78, DD-80
**Problem**: No mechanism for daemon to open external apps. No Tauri shell command, no frontend handler, no window positioning.
**Fix**:
1. Tauri: Add `shell` plugin to `Cargo.toml`, expose `open_url` and `open_file` commands
2. Frontend: On receiving `native_open` message type, call Tauri `invoke('open_file', {path})` or `invoke('open_url', {url})`
3. Window positioning: After open, run AppleScript via Tauri command to position at 15% left margin
4. Register `tauri-plugin-shell` in capabilities
**Files**: `src-tauri/Cargo.toml`, `src-tauri/src/lib.rs`, `src-tauri/capabilities/default.json`, `interfaces/portal/src/lib/api.js`
**Effort**: 6 hours

### H4. Tray icon + right-click menu
**Section**: §4.2, §6.10.2
**Problem**: Tauri app has no system tray. Design requires green/yellow/red status icon + right-click menu.
**Fix**:
1. Add `tauri-plugin-tray-icon` to `Cargo.toml`
2. In `lib.rs`: create tray with icon, poll `/status` every 15s, swap icon (green=connected, yellow=degraded, red=disconnected)
3. Right-click menu items: Start/Stop daemon, task count, health status, Open Langfuse UI, Open Temporal UI
4. Generate tray icons (green/yellow/red variants) from SVG
**Files**: `src-tauri/Cargo.toml`, `src-tauri/src/lib.rs`, `src-tauri/icons/tray-*.png`
**Effort**: 6 hours

### H5. Persona file layer missing
**Section**: §5.3
**Problem**: `persona/voice/` directory and all persona files don't exist. Design requires: `identity.md`, `common.md`, `zh.md`, `en.md`, `overlays/*.md`.
**Fix**: Create from Stage 0 interview data:
1. `persona/voice/identity.md` — core identity from interview §1
2. `persona/voice/common.md` — shared behavioral norms from interview §6
3. `persona/voice/en.md` — English output style from interview §2
4. `persona/voice/zh.md` — Chinese explanation style
5. `persona/voice/overlays/` — per-scene tone adjustments
**Files**: `persona/voice/` (new directory)
**Effort**: 2 hours

### H6. Mem0 client wrapper missing
**Section**: §5.4, §5.5, §8.1
**Problem**: `mem0_config.py` initializes Mem0, but there's no `mem0_client.py` service wrapper. `activity_post_job_learn` calls Mem0 but the distillation (Extraction + Consolidation) flow is not verified end-to-end.
**Fix**:
1. Create `services/mem0_client.py` wrapping Mem0 API: `add_memory()`, `search()`, `get_all()`, `delete()`, `healthy()`
2. Verify `activity_post_job_learn` actually calls Mem0 write after Job completion
3. Check if Mem0's built-in Update phase handles consolidation automatically (read Mem0 docs)
**Files**: `services/mem0_client.py` (new), `temporal/activities.py`
**Effort**: 3 hours

### H7. Background Maintenance Workflow (§5.9)
**Section**: §5.9.1-§5.9.4
**Problem**: `BackgroundMaintenanceWorkflow` doesn't exist. 13 background tasks not implemented. Current `MaintenanceWorkflow` only does basic cleanup.
**Fix**: Create `temporal/workflows_background.py`:
```
BackgroundMaintenanceWorkflow (Temporal Schedule, weekly)
  ├─ activity_system_snapshot — collect week's Job/agent/failure stats → state/background_reports/
  ├─ activity_skill_effectiveness — analyze skill usage success rates via Langfuse
  ├─ activity_failure_pattern — find common failure patterns across Jobs
  ├─ activity_writing_style_update — update Persona writing traits from recent outputs
  ├─ activity_persona_deep_analysis — extract preference changes from interactions
  ├─ activity_planning_consolidate — merge planning_experience into strategy insights
  └─ activity_knowledge_audit — check knowledge_cache staleness + RAGFlow sync
```
All activities use Ollama 32b (local-heavy). Add schedule to `config/schedules.json`.
**Files**: `temporal/workflows_background.py` (new), `temporal/activities_background.py` (new), `config/schedules.json`, `temporal/worker.py`
**Effort**: 12 hours

### H8. InfoPull Workflow (§2.7.1)
**Section**: §2.7.1
**Problem**: Entire InfoPull system missing — no workflow, no activities, no PG table, no triage config.
**Fix**:
1. PG migration: `CREATE TABLE info_subscriptions (id, source_type, source_url, pull_frequency, last_pulled, scene, active)`
2. Config: `config/info_triage_rules.toml` with classification rules
3. Workflow: `InfoPullWorkflow` in `temporal/workflows.py` (Temporal Schedule)
4. Activities:
   - `pull_sources` (direct): call RSS/arXiv/HN MCP servers, collect raw items
   - `triage_results` (agent): researcher classifies by urgency/relevance
   - `store_results` (direct): store in RAGFlow/knowledge_cache by tier
   - `notify_urgent` (direct): push urgent items to Telegram
5. Register schedule in `config/schedules.json`
**Files**: `scripts/init-databases.sql`, `config/info_triage_rules.toml` (new), `temporal/workflows.py`, `temporal/activities_infopull.py` (new), `config/schedules.json`
**Effort**: 10 hours

### H9. Telegram architecture fix
**Section**: §4.10, DD-79
**Problem**: Single bot with scene-switching command, not 4 independent DMs. Also `/events/publish` endpoint doesn't exist (desktop sync broken).
**Fix**:
1. Either refactor adapter to run 4 webhook handlers (one per bot token) OR document current scene-switching as accepted deviation
2. Add `POST /events/publish` endpoint to `api.py` for Telegram→desktop sync
3. Ensure one-way sync: Telegram messages → PG → desktop client (DD-79)
**Files**: `interfaces/telegram/adapter.py`, `services/api.py`
**Effort**: 4 hours

### H10. Obsidian vault integration
**Section**: §5.7.1, DD-81
**Problem**: Design says Markdown outputs go to Obsidian vault. No vault writing, no vault path config, MCP registered but not wired.
**Fix**:
1. Add `OBSIDIAN_VAULT_PATH` to `.env` (Google Drive path)
2. In publisher/writer post-step activities: if output is Markdown, write to vault via `obsidian-vault` MCP
3. Vault structure: `daily/`, `references/`, `projects/`, `research/`, `drafts/`, `knowledge/`, `templates/`, `attachments/`
4. Install Obsidian + Zotero Integration plugin on user's Mac
**Files**: `.env`, `temporal/activities_exec.py` (post-step hook), vault directory structure
**Effort**: 4 hours

---

## 🟡 MEDIUM — Incomplete features

### M1. Skill Graph completeness
**Section**: §9.2.1
**Problem**: 15 of 45 skills missing from SKILL_GRAPH.md files. L1 agents' `routing_decision` and `requires_review_judgment` are ungraphed. Only writer is fully covered.
**Fix**: Update all 10 SKILL_GRAPH.md files to include every skill in the agent's `skills/` directory. Add appropriate edges.
**Files**: `openclaw/workspace/*/SKILL_GRAPH.md`
**Effort**: 2 hours

### M2. skill_registry.json broken
**Section**: §9
**Problem**: 15 skills missing from registry, 10 have naming mismatches (e.g. `task_decomposition_copilot` vs actual dir `task_decomposition`).
**Fix**: Regenerate `skill_registry.json` from actual workspace directory structure. Script: scan `openclaw/workspace/*/skills/*/SKILL.md`, extract name from frontmatter, write registry.
**Files**: `config/skill_registry.json`, `scripts/validate_skills.py` (new)
**Effort**: 1 hour

### M3. Skill Graph injection broken in activities_exec.py
**Section**: §9.2.1
**Problem**: `step.get("skill")` is never populated by L1 routing — the field doesn't exist in routing decision schema. So `_current_skill` is always empty and no neighbors are injected.
**Fix**: Add fallback logic: if no explicit `skill` field, match step goal against SKILL_GRAPH.md entry point trigger patterns to find the best-matching skill, then inject its neighbors.
**Files**: `temporal/activities_exec.py`
**Effort**: 3 hours

### M4. Skill reliability CI scripts (§9.5.1)
**Section**: §9.5.1
**Problem**: No CI validation for SKILL.md files. No char budget check. No activation test framework.
**Fix**: Create `scripts/validate_skills.py`:
1. Parse all SKILL.md YAML frontmatters — fail on invalid YAML
2. Check description contains ALWAYS/NEVER — fail if not
3. Sum all descriptions per agent — fail if > 30000 chars
4. Check SKILL.md line count — warn if > 500
5. Optionally: activation test framework that issues targeted prompts and checks Langfuse
**Files**: `scripts/validate_skills.py` (new)
**Effort**: 3 hours

### M5. SLASH_COMMAND_TOOL_CHAR_BUDGET not configured
**Section**: §9.5.1
**Problem**: OC config doesn't have this setting. Skills may be silently truncated.
**Fix**: Add to `openclaw/openclaw.json` under workspace config: `"SLASH_COMMAND_TOOL_CHAR_BUDGET": 30000`. Verify OC respects this setting.
**Files**: `openclaw/openclaw.json`
**Effort**: 30 minutes

### M6. L1 multi-session chaining
**Section**: §3.3.1
**Problem**: Design says L1 can have multiple sessions chained. Code only tracks one session per scene.
**Fix**: In `SessionManager`, when current session approaches context limit, create a new session and link via `previous_session_key`. Carry forward compressed context.
**Files**: `services/session_manager.py`
**Effort**: 4 hours

### M7. Artifact Google Drive sync lifecycle
**Section**: §6.12.1
**Problem**: `gdrive_synced` field exists but no sync workflow. Artifacts never reach Google Drive.
**Fix**: Add post-Job activity: for each artifact in the completed Job, if it's a user-facing output, upload to Google Drive via `google-drive` MCP, mark `gdrive_synced=True`. After 30 days, delete local MinIO copy of synced artifacts.
**Files**: `temporal/activities.py`, `services/store.py`
**Effort**: 4 hours

### M8. Plane writeback retry/compensation
**Section**: §6.6
**Problem**: No explicit 5-retry with exponential backoff on Plane writeback. No compensation for failed syncs.
**Fix**: Wrap `activity_plane_writeback` with proper Temporal RetryPolicy: `initial_interval=2s, backoff_coefficient=2, maximum_attempts=5`. On final failure, publish `plane_sync_failed` event and queue for manual review.
**Files**: `temporal/workflows.py`, `temporal/activities.py`
**Effort**: 2 hours

### M9. launchd plist fix
**Section**: §6.10.1
**Problem**: Plist runs `docker compose up -d` directly, not `scripts/start.py`. Worker and API not started on boot.
**Fix**: Change plist `ProgramArguments` to `["python3", "/Users/kevinjian/daemon/scripts/start.py"]`.
**Files**: `config/com.daemon.startup.plist`
**Effort**: 10 minutes

### M10. Schedule auto-recreation
**Section**: §6.9
**Problem**: `activity_schedule_reconciliation` detects drift but doesn't auto-fix.
**Fix**: When a schedule is missing, recreate it from `config/schedules.json` via `temporal_client.create_schedule()`.
**Files**: `temporal/activities_health.py`
**Effort**: 2 hours

### M11. Job sub_status inconsistency
**Section**: §1.2
**Problem**: Code uses both `completed` and `succeeded` interchangeably.
**Fix**: Canonicalize to `succeeded` everywhere. Update PG CHECK constraint if needed.
**Files**: `services/store.py`, `temporal/workflows.py`, `temporal/activities.py`, `scripts/init-databases.sql`
**Effort**: 1 hour

### M12. Stage 0 artifacts incomplete
**Section**: §7.3
**Problem**: `warmup/writing_samples/` and `warmup/about_me.md` don't exist.
**Fix**: Create from interview data. Copy writing sample from interview §5 to `warmup/writing_samples/`. Generate `about_me.md` from interview §1.
**Files**: `warmup/writing_samples/` (new), `warmup/about_me.md` (new)
**Effort**: 30 minutes

### M13. stage3_test_tasks.json references dead "counsel" agent
**Section**: §7.3
**Problem**: T10 lists "counsel" in expected_agents. counsel was removed in seven-draft.
**Fix**: Replace "counsel" with appropriate L1 agent (likely "copilot").
**Files**: `warmup/stage3_test_tasks.json`
**Effort**: 5 minutes

---

## 🟢 LOW — Polish, not blocking

### L1. openclaw.json model overrides stale
**Problem**: `openclaw.json` has model overrides (researcher→deepseek-reasoner, writer→glm-z1-flash, reviewer→qwen-max) that may not match model_policy.json v7.
**Fix**: Align or remove OC-level model overrides — Python layer's model_policy should be authoritative.
**Files**: `openclaw/openclaw.json`

### L2. Electron directory cleanup
**Problem**: `interfaces/portal/electron/` still exists (Electron has been replaced by Tauri).
**Fix**: `rm -rf interfaces/portal/electron/`
**Files**: `interfaces/portal/electron/`

### L3. MCP servers end-to-end verification
**Problem**: 46 MCP servers registered, most never tested. API keys for some (Twitter/Strava/intervals.icu/Dev.to/Hashnode/Libraries.io/NewsData/Kaggle) may not be in .env.
**Fix**: Write a verification script that starts each MCP server and calls a basic tool. Check .env for all required keys.
**Files**: `scripts/verify_mcp.py` (new), `.env`

### L4. UserPromptSubmit hooks for critical skills
**Section**: §9.5.1
**Problem**: No OC hooks for `routing_decision` and `requires_review_judgment`.
**Fix**: Add `UserPromptSubmit` hook configuration in openclaw.json or agent workspace config.
**Files**: `openclaw/openclaw.json` or workspace config

### L5. RSSHub deployment
**Problem**: Design mentions RSSHub for Reddit/知乎/小红书 anti-scraping. Not in Docker Compose.
**Fix**: Add `rsshub` service to `docker-compose.yml`. Write MCP wrapper or configure RSS Reader MCP to use RSSHub endpoints.
**Files**: `docker-compose.yml`, `mcp_servers/rss_reader.py`

---

## 📐 INFRASTRUCTURE — New systems to build

### I1. Neo4j + openclaw-graph (DD-82)
**Section**: §9.2.1.1
**Problem**: Skill Graph is flat files. Token waste + scalability limit + activation accuracy.
**Fix**:
1. Add Neo4j to `docker-compose.yml`
2. Write seed script: parse 45 SKILL.md → create Skill nodes + SkillCluster nodes + IN_CLUSTER/RELATED_TO edges
3. Replace SKILL_GRAPH.md with Cypher query directives in workspace files
4. Patch OC workspace.ts (or write Python-side query resolution in activities_exec.py)
5. Write Rust or Python sync daemon for bidirectional file↔graph sync
6. Verify token savings (target 60-70%)
**Files**: `docker-compose.yml`, `scripts/seed_neo4j.py` (new), `temporal/activities_exec.py`, workspace files
**Effort**: 20 hours

### I2. SOP-driven skill creation
**Section**: `.ref/_work/SOP.md`
**Problem**: SOP designed 3 work lines (Research/Engineering/Life) with specific workflows, but no corresponding skills exist for many steps.
**Fix**: Create new skills for:
- `researcher/cfp_tracking` — monitor conference deadlines
- `researcher/literature_mapping` — systematic lit review after build cycle
- `researcher/peer_review_simulation` — simulate reviewer critique
- `instructor/code_review_teaching` — teach user to do code review (not just do it for them)
- `instructor/english_correction` — LanguageTool + error pattern tracking
- `writer/arxiv_paper` — arXiv-specific paper structure
- `navigator/exercise_plan` — weekly plan generation from Strava/intervals.icu data
- `copilot/build_cycle_reminder` — detect build completion, trigger lit mapping
- `publisher/blog_cross_post` — cross-post to Dev.to + Hashnode with canonical URL
**Files**: `openclaw/workspace/*/skills/*/SKILL.md` (new skills)
**Effort**: 8 hours

### I3. §5.10 主动触发工作流
**Section**: §5.10
**Problem**: 8 个主动触发工作流和三层推送模型全部未实现。这些是系统需求，不是建议。
**Fix**:
1. **Build 周期检测 + literature mapping 提醒**：copilot L1 在对话逻辑中检测连续 engineer step 完成 → 主动提出 "Time for literature mapping"
   - Files: `services/session_manager.py`（L1 对话逻辑）
2. **CFP deadline 监控**：Temporal Schedule 定期检查 mldeadlines .ics 日历 → T-8 周提醒
   - Files: `temporal/activities_infopull.py`（新增 cfp_check activity）, `config/schedules.json`
3. **日报推送**：InfoPullWorkflow triage 结果 → 每天固定时间汇总 → Telegram 推送
   - Files: `temporal/activities_infopull.py`, `interfaces/telegram/adapter.py`
4. **周报推送**：BackgroundMaintenanceWorkflow system_snapshot → 各 L1 场景生成周报 → Telegram
   - Files: `temporal/activities_background.py`
5. **英文 LanguageTool post-hook**：writer/publisher 英文产出后自动触发 LanguageTool MCP 检查 → instructor 解读
   - Files: `temporal/activities_exec.py`（post-step hook）
6. **GitHub profile + 博客提醒**：copilot L1 检测 build+write 周期完成 → 提醒
   - Files: `services/session_manager.py`
7. **Code review 教学**：GitHub webhook 收到 PR → instructor L1 session 引导用户 review
   - Files: `services/plane_webhook.py` or new GitHub webhook handler
8. **三层推送模型**：实时（0-2/天 Telegram 即时）+ 日报（每天固定时间）+ 周报（每周趋势分析 Telegram + Obsidian）
   - Depends on: H8 InfoPull + H7 Background Maintenance + H9 Telegram
**Effort**: 15 hours (after H7/H8/H9 are done)

---

## ~~取消的项目~~

- ~~远程访问 + PWA~~ — DD-79
- ~~BrowserView / 阅读器 / Monaco~~ — DD-78
- ~~自动分屏~~ — DD-80
- ~~Electron~~ — DD-78
- ~~Skim PDF viewer~~ — 改用 Zotero
- ~~XnView MP~~ — 改用 Preview.app

---

## ✅ DONE（压缩）

- Phase 0-5 Python 层代码框架 ✅
- 10 agents OC workspace (SOUL/TOOLS/AGENTS/MEMORY/SKILL_GRAPH) ✅
- 45 SKILL.md + Agent Skills 标准 frontmatter ✅
- Docker Compose 21 容器 ✅
- Tauri 桌面客户端 (8MB .app, zoom 1.25, 15% margin, icon) ✅
- UI: shadcn/ui + Bricolage Grotesque + mauve palette ✅
- 46 MCP servers 注册 + 34 Python scripts ✅
- Google OAuth Desktop + branded page ✅
- Model policy v7 ✅
- §10 禁止事项 48 条审计 ✅
- DD-78/79/80/81/82 设计决策 ✅
- SOP 设计 (Research/Engineering/Life) ✅
- 基础设施健康检查通过 ✅
- Warmup Stage 0-4 脚本框架 ✅

---

## Warmup（§7）— C1-C4 + H1-H10 完成后

- [x] **Stage 0** — Persona 采访 ✅
- [ ] **Stage 1** — Persona 校准 (需要 H5 persona 文件 + H6 Mem0 验证)
- [ ] **Stage 2** — 17 链路验证 (需要 C1 worker 修复 + C2 chain 修复)
- [ ] **Stage 3** — Skill 校准 (需要 M1-M5 skill 修复 + M13 test task 修复)
- [ ] **Stage 4** — 异常场景验证

**收敛标准**：pseudo-human — 连续 5 个不同类型任务的外部产出，与用户本人风格无法区分。
