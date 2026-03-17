# TODO Audit — Python Layer

Audited: 2026-03-16
Source: TODO_DRAFT.md (§0-§3), TODO_DRAFT_4_6.md (§4-§6), TODO_DRAFT_7_10.md (§7-§10), REFERENCE (B-I)

Legend:
- ✅ Implemented (function exists + logic correct)
- 🔨 Partial (framework exists but logic stub/incomplete)
- ❌ Not implemented (code doesn't exist)
- 🔧 Needs update (implementation exists but doesn't match spec)

---

## §0 — 治理规则

- 🔨 [§0.5] `config/lexicon.json` — file exists with 28 entries, covers core terms, but no runtime validation that code uses canonical names
- ❌ [§0.6] Dual-layer validation — no automated check that Python + OC layer are in sync
- 🔨 [§0.9] No blocking UX — routing logic in `scenes.py:61-102` creates+executes atomically, but no enforcement against showing internal error stack traces
- ❌ [§0.10] Self-governance pipeline — no `scripts/verify.py` integration for validating admin-proposed changes; verify.py only does health checks
- 🔨 [§0.11] Four discrete scenes — `session_manager.py:29` defines L1_SCENES tuple (copilot/mentor/coach/operator), sessions created per scene, but no SOUL.md/SKILL.md per-scene loading in Python layer

## §1 — 术语与对象模型

### 1.1 Object Model
- ✅ [§1.1] 6 objects implemented — `api.py:410-580` SCHEMA_SQL defines daemon_tasks, jobs, job_steps, job_artifacts; Draft/Project mapped to Plane via `plane_client.py`
- ✅ [§1.1] Project/Draft/Task → Plane mapping — `plane_client.py:84-161` has create_project, create_issue, create_draft, convert_draft_to_issue
- ✅ [§1.1] Task dependencies via Plane IssueRelation — `plane_client.py:167-189` create_relation with blocked_by

### 1.2 State Model
- ✅ [§1.2] Job state machine — `api.py:435-448` jobs table: status IN ('running','closed'), sub_status IN ('queued','executing','paused','retrying','succeeded','completed','failed','cancelled')
- ✅ [§1.2] No settling state — confirmed not present in schema or code
- 🔧 [§1.2] `requires_review=true` behavior — `api.py:443` column exists; `workflows.py` has no logic to handle requires_review (no pending_confirmation flow for dependent Steps)
- ✅ [§1.2] Rerun creates new Job — `store.py:82-105` create_job always INSERTs new row
- ✅ [§1.2] Step states — `api.py:461-462` CHECK constraint: pending/running/completed/failed/skipped/pending_confirmation
- ❌ [§1.2] `pending_confirmation` flow — Step status exists in schema but no workflow logic to mark Steps as pending_confirmation or handle confirmation_received

### 1.3 Execution Types
- ✅ [§1.3] 4 execution_type — `api.py:457-458` CHECK constraint: agent/direct/claude_code/codex
- ✅ [§1.3] `direct` via MCP — `activities_exec.py:339-407` run_direct_step dispatches through MCPDispatcher
- ✅ [§1.3] `claude_code`/`codex` via subprocess — `activities_exec.py:217-336` run_cc_step, injects MEMORY.md + Mem0 context
- ✅ [§1.3] Artifact collection from subprocess — `activities_exec.py:316-336` captures stdout as output

### 1.4 Agent Architecture
- ✅ [§1.4.1] 4 L1 scene agents — `session_manager.py:29` L1_SCENES
- ✅ [§1.4.1] L1 persistent session, API process managed — `session_manager.py:59-69` start() creates persistent sessions via OpenClawAdapter
- 🔨 [§1.4.1] L1 base capabilities (routing, DAG planning, Replan Gate, intent parsing) — `session_manager.py:155-184` _extract_action does basic JSON extraction but no structured routing decision parsing
- ✅ [§1.4.2] 6 L2 execution agents — supported via `activities_exec.py:38` agent_id passed to spawn_session
- ✅ [§1.4.2] L2: 1 Step = 1 Session — `activities_exec.py:131-138` spawn_session with cleanup="delete"
- 🔨 [§1.4.3] L1→L2 flow — `scenes.py:86-101` dispatches structured actions to Temporal, but routing decision parsing is rudimentary (checks action_type string)
- ❌ [§1.4.3] L1 planning specifies `agent` + optional `model` override — model_hint column exists in schema but not used in routing/dispatch
- ✅ [§1.4.3] Fixed 4+6=10 agents — no dynamic agent creation code

### 1.5 Knowledge Hierarchy
- 🔨 [§1.5] Priority: Guardrails > External Facts > Persona > System Defaults — Guardrails run first (`activities_exec.py:97-111`), Mem0 injected after, but no explicit priority enforcement logic

### 1.6 Infrastructure Components
- ✅ [§1.6] Plane — `plane_client.py` full CRUD
- ✅ [§1.6] Temporal — `runtime/temporal.py` + `temporal/worker.py`
- 🔨 [§1.6] Langfuse — `activities.py:82-98` init code exists, creates traces in `activities_exec.py:116-129`
- ❌ [§1.6] MinIO — no MinIO client code in Python layer; `job_artifacts` has minio_path column but no upload/download logic
- ❌ [§1.6] RAGFlow — no RAGFlow client code
- ✅ [§1.6] Mem0 — `config/mem0_config.py` full init + retrieve functions
- 🔨 [§1.6] NeMo Guardrails — `config/guardrails/actions.py` pattern-based validation exists, but not using actual `nemoguardrails` Python library; config.yml + safety.co exist as Colang definitions but never loaded by NeMo runtime
- ✅ [§1.6] pgvector — `api.py:411` CREATE EXTENSION IF NOT EXISTS vector; knowledge_cache has embedding column
- ✅ [§1.6] PG LISTEN/NOTIFY — `event_bus.py` full implementation
- ❌ [§1.6] Firecrawl — configured in `mcp_servers.json` but no Python integration code

### 1.7 System Maintenance
- ✅ [§1.7] Daily cleanup Job — `activities_maintenance.py:31-75` cleans knowledge_cache, old jobs, old messages
- ✅ [§1.7] Temporal Schedule for maintenance — `worker.py:73-76` daemon-maintenance every 6h
- ✅ [§1.7] Daily backup Job — `activities_health.py:466-518` activity_backup does pg_dump + 90-day pruning
- ✅ [§1.7] Temporal Schedule for backup — `worker.py:87-89` daemon-backup daily
- 🔧 [§1.7] Cleanup scope incomplete — no Mem0 90-day untriggered memory cleanup, no quota reset, no RAGFlow doc sync delete

### 1.8 Terminology
- 🔧 [§1.8] Deprecated terms in codebase — grep found 30 .py files still containing old terms (folio/writ/deed/slip/psyche/instinct/etc.), mostly in comments/docstrings explaining migration, but old service files still exist: `services/folio_writ.py`, `services/herald.py`, `services/cadence.py`, `services/voice.py`, `services/will.py`, `spine/` directory

## §2 — 系统架构

### 2.2 Process Boundaries
- ✅ [§2.2] Two processes — `services/api.py` (FastAPI) + `temporal/worker.py` (Temporal Worker)
- ✅ [§2.2] API: webhook, glue API, WebSocket, L1 session — all present in api.py startup
- ✅ [§2.2] Worker: activities, Plane writeback, L2 OC, Mem0, NeMo — `activities.py:56-98` DaemonActivities init
- ✅ [§2.2] No shared in-memory state — API and Worker share only PG, Temporal, Plane
- ✅ [§2.2] No Temporal workflows in API process — API only uses TemporalClient.start_job_workflow

### 2.5 Plane Object Mapping
- ✅ [§2.5] Project→Plane Project, Draft→DraftIssue, Task→Issue — `plane_client.py` methods
- ✅ [§2.5] Job/Step in daemon PG — `api.py:431-471` schema

### 2.6 External Outlets
- 🔨 [§2.6] Telegram via OC — `interfaces/telegram/adapter.py` sends notifications, supports chat forwarding to scene API, but not via OC native channel
- ❌ [§2.6] GitHub via MCP — configured in `mcp_servers.json` but no publishing workflow
- ❌ [§2.6] Social media via MCP — not implemented
- ❌ [§2.6] publisher as sole external outlet agent — no publisher-specific routing logic

### 2.7 External Knowledge Acquisition
- 🔨 [§2.7] Knowledge pipeline — `mcp_servers.json` has brave-search, semantic-scholar, firecrawl, paper-tools configured as MCP servers
- ✅ [§2.7] knowledge_cache in PG with TTL — `api.py:529-542` table, `store.py:387-424` upsert with expires_at
- ✅ [§2.7] source_tiers.toml — `config/source_tiers.toml` defines A/B/C tiers
- 🔨 [§2.7] sensitive_terms.json — file exists at `config/sensitive_terms.json` but is empty `[]`
- 🔨 [§2.7] NeMo input rail for sensitive terms — `guardrails/actions.py:93-101` filter_sensitive_outbound exists but no actual terms configured

### 2.8 Model Strategy
- ✅ [§2.8] Default models per agent — `config/model_policy.json` maps each agent to model alias
- ✅ [§2.8] Model names configurable — `config/model_registry.json` defines aliases (fast/analysis/review/creative/etc.)
- 🔧 [§2.8] researcher should use analysis model — `model_policy.json:12` maps researcher to "fast", spec says "analysis"

### 2.9 Persistence Boundaries
- ✅ [§2.9] Plane: Task/Project/Draft — via PlaneClient
- ✅ [§2.9] daemon PG: Job/Step/Artifact metadata — schema tables
- 🔨 [§2.9] MinIO: Artifact full objects — minio_path column exists but no MinIO client
- 🔨 [§2.9] Langfuse: traces — init code exists but may not be active
- ✅ [§2.9] Mem0: Persona + memory — `config/mem0_config.py`

## §3 — 执行模型

### 3.1 Routing Decision
- 🔨 [§3.1] L1 structured routing decision — `session_manager.py:155-184` extracts JSON from reply, `scenes.py:86-101` dispatches by action_type, but no formal schema validation for intent/route/model/task fields
- ✅ [§3.1] Three routes: direct/task/project — `scenes.py:89-93` handles create_job/task/project and direct
- ✅ [§3.1] `route="direct"` creates ephemeral Job — `scenes.py:221-258` _submit_direct_job, but `is_ephemeral` not set to true
- 🔧 [§3.1] `is_ephemeral` not set for direct Jobs — `scenes.py:252` create_job call missing `is_ephemeral=True`

### 3.2 Step Granularity
- ✅ [§3.2.1] 1 Step = 1 goal — enforced by schema (goal NOT NULL)
- ❌ [§3.2.1] Token budget declaration in Step instructions — not implemented
- ❌ [§3.2.1] Step upper bound = context window 100% minus ~800 token — no enforcement

### 3.3 Session Model
- ✅ [§3.3.1] L1 persistent OC session — `session_manager.py` uses sessions_send
- ✅ [§3.3.1] L1 compression at 70% — `session_manager.py:126-127` COMPRESSION_THRESHOLD = 0.70
- ✅ [§3.3.1] 4-layer compression in PG — `session_manager.py:186-331` messages→digests→decisions→Mem0
- 🔨 [§3.3.1] Scene as filter column not hard partition — decisions table has scene + project_id + tags columns, but no cross-scene query API endpoint
- ✅ [§3.3.2] L2: 1 Step = 1 Session — `activities_exec.py:131-138` spawn_session with cleanup="delete"
- 🔧 [§3.3.2] Session key format — `activities_exec.py:132` uses `{job_id[:8]}:{step_id}` instead of spec `{agent_id}:{job_id}:{step_id}`
- 🔨 [§3.3.2] L2 content injection ≤ 800 tokens — `activities_exec.py:81-94` injects Mem0 + upstream context but no token counting/enforcement
- ❌ [§3.3.3] MEMORY.md ≤ 300 tokens per agent — no validation of MEMORY.md token count

### 3.4 Token Management
- 🔨 [§3.4] `runTimeoutSeconds` per Step type — `workflows.py:300-307` _timeouts reads step.timeout_s or plan.default_step_timeout_s, but no per-type defaults (search:60s, writing:180s, review:90s)
- ❌ [§3.4] Step instructions include token budget declaration — not implemented
- ❌ [§3.4] Langfuse monitoring: single Step token > threshold → alert — Langfuse trace created but no alert logic
- ❌ [§3.4] `contextPruning: cache-ttl` = 5 min — OC config, not Python layer
- ❌ [§3.4] `maxSpawnDepth`/`maxChildrenPerAgent`/`maxConcurrent` — OC config, not Python layer

### 3.5 Job Lifecycle
- ✅ [§3.5] Job creation = atomic — `scenes.py:173-218` creates task+job+starts workflow in one flow
- ❌ [§3.5] Same Task max 1 non-closed Job — no constraint in schema or code
- ✅ [§3.5] Rerun creates new Job — `store.py:82` always INSERT
- ✅ [§3.5] DAG snapshot frozen — `api.py:441` dag_snapshot JSONB column, set at creation
- 🔨 [§3.5] Plane writeback failure handling — `api.py:443` plane_sync_failed column exists, but no retry/compensation logic implemented
- ❌ [§3.5] `requires_review=true` → L1 conversation + Telegram + pending_confirmation — no implementation
- ❌ [§3.5] Re-execution intent analysis — no L1 judgment logic for denial/exploration/refinement

### 3.6 Initial DAG & Context
- ❌ [§3.6] First Job DAG from Plane Issue description + Activity + Mem0 — L1 agent does planning but no structured context assembly in Python
- ❌ [§3.6.1] Project-level context assembly — not implemented
- ❌ [§3.6.2] Re-run minimize redo scope — not implemented

### 3.7 Step Parallel Execution & Artifact Passing
- ✅ [§3.7] Kahn topological sort + parallel execution — `workflows.py:105-120` cycle detection + `148-179` parallel step dispatch
- ✅ [§3.7] Parallel Step failure aggregation — `workflows.py:206-211` errors collected, `234-238` all errors reported
- 🔨 [§3.7.1] Step→Step artifact passing — `activities_exec.py:69-79` upstream_steps injected as context, but no MinIO storage; summary only
- ❌ [§3.7.1] Job→Job artifact chain — not implemented
- ❌ [§3.7.1] Task→Task artifact chain with `task_input_from` — not implemented

### 3.8 Step Failure Handling
- ✅ [§3.8] Retry via Temporal RetryPolicy — `workflows.py:269-270` RetryPolicy with max_attempts
- ❌ [§3.8] L1 judges: skip/replace/terminate after retry exhausted — not implemented
- ✅ [§3.8] Temporal checkpoint — native Temporal behavior, completed Activities replayed
- ❌ [§3.8.1] reviewer trigger strategy (3 tiers) — not implemented

### 3.9 Dynamic Replanning
- ✅ [§3.9] Replan Gate activity — `activities_replan.py:28-119` run_replan_gate with lightweight check
- ❌ [§3.9] Replan diff schema with operations[] — not implemented (only returns continue/replan/done)
- ❌ [§3.9] Replan batch writes with compensation — not implemented
- 🔨 [§3.9] Replan uses analysis model — replan uses send_to_session but doesn't specify model

### 3.10 Task Triggers
- ✅ [§3.10] Three trigger types in schema — `api.py:420-421` trigger_type CHECK (manual/timer/chain)
- ✅ [§3.10] Temporal Schedule for timer — `worker.py:62-118` _register_schedules
- ❌ [§3.10] Chain trigger: predecessor Job closed → Replan Gate → downstream — no chain trigger dispatch logic
- ❌ [§3.10] Trigger is hard constraint → L1 rejects unmet prerequisites — not implemented

### 3.11 Runtime Defaults
- 🔧 [§3.11] Appendix B defaults — RetryPolicy uses max_attempts=3 (correct), but no per-type Step timeouts
- ✅ [§3.11] `user_id` column — all tables have `user_id TEXT DEFAULT 'default'`

### 3.12 External Tool Handoff
- 🔨 [§3.12] CC/Codex handoff — `activities_exec.py:217-336` runs CC/Codex CLI but no CLAUDE.md/AGENTS.md auto-generation from prior Artifacts
- ❌ [§3.12] Handoff context files auto-generated — not implemented

## §4 — 交互与界面契约

### 4.1-4.2 界面架构 + 桌面客户端
- ❌ [§4.1-4.2] Electron desktop client — not implemented (portal/ has Vite/React but not Electron)
- ✅ [§4.1] 4 scene conversations — API supports 4 scenes
- ❌ [§4.2] Panel modes (conversation/scene panel/browser view) — panel endpoint exists but no structured panel data per scene type

### 4.3 Draft 语义与转正
- ✅ [§4.3] Draft→Task conversion — `plane_client.py:155-161` convert_draft_to_issue
- ❌ [§4.3] Auto-task via Draft first (except direct route) — no Draft creation in L1 flow

### 4.5 活动流
- ✅ [§4.5] conversation_messages PG table — `api.py:492-501`
- 🔨 [§4.5] Task activity flow API — `api.py:121-131` get_task_activity endpoint exists, `store.py:484-501` query joins steps+jobs, but no proper activity stream format (missing type/actor/metadata fields per D.4)

### 4.6 Artifact 呈现
- ❌ [§4.6] `GET /artifacts/{id}` — endpoint not implemented
- ❌ [§4.6] `GET /artifacts/{id}/download` — endpoint not implemented

### 4.8 非阻塞确认机制
- ❌ [§4.8] `requires_review` → conversation confirmation + Telegram — not implemented
- ❌ [§4.8] `pending_confirmation` Step handling — schema column exists but no logic

### 4.9 API 端点
- ✅ [§4.9] `POST /scenes/{scene}/chat` — `scenes.py:60-102`
- ✅ [§4.9] `GET /scenes/{scene}/chat/stream` (WebSocket) — `scenes.py:105-159`
- ✅ [§4.9] `GET /scenes/{scene}/panel` — `scenes.py:162-168`
- ✅ [§4.9] `GET /tasks/{id}/activity` — `api.py:121-131`
- ❌ [§4.9] `GET /artifacts/{id}` — missing
- ❌ [§4.9] `GET /artifacts/{id}/download` — missing
- ✅ [§4.9] `GET /status` — `api.py:81-92`
- ❌ [§4.9] `GET /auth/google` — missing
- ❌ [§4.9] `GET /auth/github` — missing
- ❌ [§4.9] `GET /auth/callback` — missing
- ✅ [§4.9] No pause/resume/cancel endpoints — correct, through conversation

### 4.10 Telegram
- ✅ [§4.10] 4 independent Bot Tokens — `adapter.py:35-39` BOT_TOKENS dict
- ✅ [§4.10] Notification support — `adapter.py:232-269` /notify endpoint
- ✅ [§4.10] Chat forwarding to scene API — `adapter.py:213-229` _forward_to_scene
- ✅ [§4.10] /scene command for scene switching — `adapter.py:299-308`
- 🔧 [§4.10] Not synced with desktop client — no sync mechanism; Telegram messages don't go through session_manager/PG

## §5 — 知识、Persona、Guardrails 与 Quota

### 5.2 Guardrails
- 🔧 [§5.2] NeMo Guardrails integration — `config/guardrails/` has config.yml + safety.co + actions.py, but `actions.py` is custom pattern-matching code, NOT using `nemoguardrails` Python library. Colang rules exist but are never loaded by NeMo runtime.
- ✅ [§5.2] Input/output rail (pattern-based) — `guardrails/actions.py:104-156` validate_output + validate_input
- ✅ [§5.2] Source tier compliance check — `guardrails/actions.py:69-90`
- ✅ [§5.2] Sensitive term filtering — `guardrails/actions.py:93-101`
- ✅ [§5.2] Mem0 write validation — `guardrails/actions.py:159-176` validate_mem0_write

### 5.3 Persona 双层结构
- ❌ [§5.3] File layer — no `persona/voice/` directory structure in Python layer
- ✅ [§5.3] Dynamic layer (Mem0) — `config/mem0_config.py` init + retrieval

### 5.4 Persona 更新责任
- ❌ [§5.4] User taste update chain — not implemented
- ❌ [§5.4.1] Drift detection (90-day unused memory cleanup) — not implemented

### 5.5 Mem0 注入
- ✅ [§5.5] On-demand retrieval, not full injection — `mem0_config.py:85-115` retrieve_agent_context searches by query
- 🔨 [§5.5] Per-agent retrieval focus — `mem0_config.py:95-98` searches with `query=f"agent:{agent_id} context"` but no agent-specific query customization (spec wants different focuses per agent)
- ✅ [§5.5] Default 5 results — `mem0_config.py:85` limit=5 default

### 5.6 External Knowledge Tools
- 🔨 [§5.6] MCP search — `mcp_servers.json` configures brave-search, semantic-scholar, firecrawl, github, paper-tools
- ❌ [§5.6] RAGFlow integration — not in Python code
- 🔨 [§5.6.1] knowledge_cache TTL — `store.py:387-424` upsert_knowledge with expires_at, but TTL values not automatically computed from source_tiers.toml
- ❌ [§5.6.1] Retrieval: project_id first, then global — no fallback logic in store

### 5.8 Quota
- ❌ [§5.8] Three-layer Quota — no quota enforcement code (OC/session, Job, system daily)

## §6 — 基础设施与运行时契约

### 6.2 daemon 自有进程
- ✅ [§6.2] API process — `services/api.py` FastAPI
- ✅ [§6.2] Worker process — `temporal/worker.py` Temporal Worker
- ✅ [§6.2] NeMo/Mem0 in Worker — `activities.py:72-98` (Mem0 init, Langfuse init)
- ✅ [§6.2] No Temporal workflows in API — API only submits via TemporalClient

### 6.3 OC Gateway & MCP
- ✅ [§6.3] OC Gateway lifecycle — `api.py:325-358` _start_openclaw_gateway as subprocess
- ✅ [§6.3] L1 persistent sessions — `session_manager.py`
- ✅ [§6.3] L2 session = Step level — `activities_exec.py:131-138` spawn_session
- ✅ [§6.3] MCP dispatch — `runtime/mcp_dispatch.py` full implementation with routing table
- ✅ [§6.3] MCP per-Worker persistent connections — `mcp_dispatch.py:102-115` _discover_all at first use
- ✅ [§6.3] MCP timeout protection — `mcp_dispatch.py:54` asyncio.wait_for with timeout
- ✅ [§6.3] MCP reconnect on failure — `mcp_dispatch.py:77-100` _reconnect_server

### 6.4 PG 事件总线
- ✅ [§6.4] event_log + NOTIFY dual write — `event_bus.py:105-120` publish inserts into event_log (trigger fires pg_notify)
- ✅ [§6.4] NOTIFY instant wakeup — `api.py:554-566` trigger function notify_event_log
- 🔨 [§6.4] Worker restart replay — EventBus reconnects (`event_bus.py:64-76`) but no unconsumed event replay logic
- ✅ [§6.4] Channels: job_events, step_events, webhook_events, system_events — used throughout activities

### 6.5 Temporal 约束
- ✅ [§6.5] Job = Workflow — `workflows.py:31` JobWorkflow
- ✅ [§6.5] Step = Activity — `activities.py:102-122` activity_execute_step / activity_direct_step / activity_cc_step
- ✅ [§6.5] timer = Temporal Schedule — `worker.py:62-118`
- ✅ [§6.5] pause/resume = Signal — `workflows.py:42-49` pause_execution/resume_execution signals

### 6.6 Plane 回写与补偿
- 🔨 [§6.6] plane_sync_failed column — `api.py:443` exists
- ❌ [§6.6] Retry 5 times with exponential backoff — no retry logic for Plane writeback
- ❌ [§6.6] Async compensation — no compensation flow

### 6.7 配置文件
- ✅ [§6.7] mcp_servers.json — `config/mcp_servers.json`
- ✅ [§6.7] source_tiers.toml — `config/source_tiers.toml`
- ✅ [§6.7] lexicon.json — `config/lexicon.json`
- ✅ [§6.7] guardrails/ — `config/guardrails/`
- 🔧 [§6.7] sensitive_terms.json — file exists but empty `[]`
- ✅ [§6.7] schedules.json — `config/schedules.json` with 3 schedules

### 6.9 启动与健康检查
- ✅ [§6.9] Startup sequence — `scripts/start.py` 7-step sequence: Docker→health→migrations→Temporal namespace→Worker→API→verify
- ✅ [§6.9] Docker Desktop auto-start on macOS — `start.py:65-73`
- ✅ [§6.9] Schedule definitions in config — `config/schedules.json`
- ❌ [§6.9] admin weekly schedule reconciliation — no code to compare config vs Temporal schedules

### 6.10 开机自启动 + 远程访问
- ❌ [§6.10.1] macOS launchd plist — no plist file
- ❌ [§6.10.2] Electron desktop app — not implemented
- ❌ [§6.10.3] Tailscale Funnel + OAuth — not implemented

### 6.11 备份制度
- ✅ [§6.11] PG dump — `activities_health.py:487-501` pg_dump via docker compose exec
- 🔨 [§6.11] MinIO backup — no MinIO backup (only PG)
- ✅ [§6.11] 90-day rolling prune — `activities_health.py:503-515`
- ✅ [§6.11] Temporal Schedule daily — `worker.py:87-89`
- ❌ [§6.11] `scripts/restore.py --date` — file does not exist

### 6.12 数据生命周期
- ✅ [§6.12.2] Old job cleanup (30 days) — `store.py:435-450`
- ✅ [§6.12.2] Old message cleanup (90 days) — `store.py:452-464`
- ✅ [§6.12.2] knowledge_cache TTL cleanup — `store.py:426-433`
- ❌ [§6.12.1] Google Drive sync — gdrive_synced column exists but no sync code
- ❌ [§6.12.2] Ephemeral Job 7-day delete — no differentiated retention for is_ephemeral
- ❌ [§6.12.2] event_log consumed cleanup (7 days) — not implemented

### 6.13 认证
- ❌ [§6.13.1] OAuth (Google/GitHub) — not implemented
- ✅ [§6.13.2] user_id column in all tables — present in all tables with DEFAULT 'default'
- 🔨 [§6.13.2] Workflow ID with user_id prefix — `scenes.py:202` uses `job-{uuid4()}`, no user prefix

## §7 — 暖机、可观测性与自愈

### 7.6 可追溯链
- 🔨 [§7.6] Job → Plane Issue writeback — PlaneClient has add_comment but no automatic Job result writeback
- 🔨 [§7.6] Langfuse trace per Step — trace created in `activities_exec.py:116-129` but may not be active

### 7.7 周度体检
- ✅ [§7.7] Temporal Schedule weekly — `worker.py:79-84` daemon-health-check every 7 days
- ✅ [§7.7.1] Infrastructure layer — `activities_health.py:60-91` runs verify.py
- 🔨 [§7.7.1] Quality layer — `activities_health.py:93-188` queries PG for job metrics, but no baseline task suite
- 🔨 [§7.7.1] Frontier scan — `activities_health.py:204-215` stub only ("frontier_scan_stub_pending_researcher_agent")
- ✅ [§7.7.4] Health report save + Telegram — `activities_health.py:218-262`

### 7.8 三层自愈
- ✅ [§7.8] SelfHealWorkflow — `workflows.py:392-468` 4-activity workflow
- ✅ [§7.8] Activity 1: diagnose → issue file — `activities_health.py:268-318`
- ✅ [§7.8] Activity 2: CC/Codex fix — `activities_health.py:321-396`
- ✅ [§7.8] Activity 3: restart — `activities_health.py:405-424`
- ✅ [§7.8] Activity 4: verify + notify — `activities_health.py:427-460`
- ✅ [§7.8] Layer 3: notify failure — `activities_health.py:450-460`

### 7.9 问题文件格式
- ✅ [§7.9] Issue file at state/issues/ — `activities_health.py:276-312` generates proper format

### 7.10 配套脚本
- ✅ [§7.10] `scripts/start.py` — full implementation, idempotent, 7-step recovery
- ✅ [§7.10] `scripts/stop.py` — graceful shutdown (Worker drain → API stop)
- ✅ [§7.10] `scripts/verify.py --issue` — full health check + issue verification + Telegram
- ❌ [§7.10] `scripts/restore.py --date` — file does not exist

## §8 — 学习机制

- ❌ [§8.1] Learn only from successful Jobs — no learning extraction code
- ❌ [§8.2] Planning experience to Mem0 — no post-Job learning pipeline
- ❌ [§8.3] Source markers [EXT:url]/[INT:persona]/[SYS:guardrails] — not implemented in Step output

## §9 — Skill 体系

- ❌ [§9.1-§9.10] Skill system — entirely OC layer concern; Python layer only needs to pass skill content for CC/Codex Steps, which `activities_exec.py:255-262` partially does (reads MEMORY.md)

## §10 — 禁止事项 Checklist

- ✅ [§10.1] Job ≠ Task — separate tables with FK
- ✅ [§10.3] Only Project/Task/Job three layers — no extra entity types
- ✅ [§10.6] No complexity grading — not present
- ✅ [§10.7] No Memory/Lore — uses Mem0
- ✅ [§10.8] No merged parallel Steps — each Step independent session
- ✅ [§10.11] No settling state — not in schema
- ✅ [§10.12] 1 Step = 1 goal — schema enforced
- 🔧 [§10.35] Herald still exists — `services/herald.py` file still present (should be deleted)
- 🔧 [§10.36] Spine routines still exist — `spine/` directory still present (should be deleted)
- 🔧 [§10.37] Old terminology files — `services/folio_writ.py`, `services/voice.py`, `services/will.py`, `services/cadence.py` still exist
- ✅ [§10.38] No memory in subagent — Python doesn't control this (OC layer)
- 🔨 [§10.40] All LLM calls through Guardrails — activities_exec.py calls validate_input/validate_output but uses custom code, not NeMo library
- ❌ [§10.42] Source markers on all Step output — not implemented
- 🔨 [§10.43] All LLM calls have Langfuse trace — trace created for agent steps, but not for CC/Codex steps or replan gate
- 🔨 [§10.44] Plane writeback failure → compensation queue — column exists but no compensation logic
- ✅ [§10.45] No hardcoded model IDs — model_registry.json + model_policy.json

## Appendix C — PG 表结构

- ✅ [C.1] daemon_tasks — `api.py:415-428`
- ✅ [C.2] jobs — `api.py:431-448`
- ✅ [C.3] job_steps — `api.py:451-471` (missing `skill_used` column vs spec)
- ✅ [C.4] job_artifacts — `api.py:474-490`
- 🔧 [C.5] knowledge_cache — `api.py:529-542` embedding is vector(1536) but spec says vector(1024); no ivfflat index
- ✅ [C.6] event_log — `api.py:545-552` (missing `consumed_at` column, has `consumed` boolean instead)
- ✅ [C.7] conversation_messages — `api.py:492-501`
- ✅ [C.8] conversation_digests — `api.py:504-514`
- ✅ [C.9] conversation_decisions — `api.py:517-527` (has extra project_id + tags columns, which is correct per spec)

## Appendix D — 接口契约与事件定义

### D.1 API 端点
- ✅ POST `/scenes/{scene}/chat` — `scenes.py:60`
- ✅ WS `/scenes/{scene}/chat/stream` — `scenes.py:105`
- ✅ GET `/scenes/{scene}/panel` — `scenes.py:162`
- ✅ GET `/tasks/{task_id}/activity` — `api.py:121`
- ❌ GET `/artifacts/{artifact_id}` — missing
- ❌ GET `/artifacts/{artifact_id}/download` — missing
- ✅ GET `/status` — `api.py:81`
- ❌ POST `/auth/login` — missing
- ✅ POST `/webhooks/plane` — `plane_webhook.py:40`

### D.2 Temporal Signals
- ✅ [D.2] pause_job — `workflows.py:42-44` (named `pause_execution`)
- ✅ [D.2] resume_job — `workflows.py:47-49` (named `resume_execution`)
- ✅ [D.2] cancel_job — via `temporal.py:68-69` TemporalClient.cancel
- ❌ [D.2] confirmation_received Signal — not implemented
- ❌ [D.2] confirmation_rejected Signal — not implemented

### D.3 PG NOTIFY Channels
- ✅ [D.3] job_events — used in `activities.py:140`
- ✅ [D.3] step_events — used in `activities_exec.py:48-57`
- ✅ [D.3] webhook_events — used in `plane_webhook.py:122`
- ✅ [D.3] system_events — used in `activities_maintenance.py:65`

### D.5 Job→Plane State Mapping
- ❌ [D.5] Automatic state writeback — no code to map Job status → Plane Issue state

### D.6 废弃术语
- 🔧 [D.6] Old files still present — `services/folio_writ.py`, `services/herald.py`, `services/cadence.py`, `services/voice.py`, `services/will.py`, `spine/` directory, `services/api_routes/basic.py`, `services/api_routes/console_admin.py`, `services/api_routes/console_runtime.py`, `services/api_routes/portal_shell.py`

## Appendix B — Runtime Parameter Defaults

- 🔧 [B.1] Step timeouts not per-type — `workflows.py:300-307` uses single default, not search:60s/writing:180s/review:90s
- ✅ [B.1] RetryPolicy — `workflows.py:269-270` max_attempts=3 (correct); initial_interval/backoff not explicitly set (Temporal defaults apply)
- ✅ [B.2] Session parameters — OC config layer, not Python
- ✅ [B.3] Mem0 retrieval limit = 5 — `mem0_config.py:85` default
- 🔨 [B.4] Plane writeback retry 5x — plane_sync_failed exists but no retry logic
- ✅ [B.5] knowledge_cache TTL tiers — source_tiers.toml configured
- ❌ [B.6] Health alert thresholds — no threshold-based alerting in quality check

---

## Summary Statistics

| Status | Count |
|--------|-------|
| ✅ Implemented | 88 |
| 🔨 Partial | 32 |
| ❌ Not implemented | 52 |
| 🔧 Needs update | 14 |

### Critical Gaps (blocking warmup)

1. **MinIO client** — no upload/download code; Artifacts can't be stored
2. **Artifact API endpoints** — GET /artifacts/{id} and /download missing
3. **requires_review + pending_confirmation flow** — schema exists but no logic
4. **Plane writeback compensation** — column exists but no retry/compensation
5. **Chain trigger dispatch** — predecessor Job closed → downstream not implemented
6. **OAuth authentication** — no auth endpoints at all
7. **restore.py** — backup exists but no restore script
8. **Old files cleanup** — deprecated service files and spine/ directory still present
9. **NeMo Guardrails** — using custom pattern code, not actual nemoguardrails library
10. **Learning mechanism** — no post-Job learning pipeline to Mem0
