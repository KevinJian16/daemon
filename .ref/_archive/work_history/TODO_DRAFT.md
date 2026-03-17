# TODO Draft — Requirements from SYSTEM_DESIGN.md

## §0 治理规则

- [§0.4] Implement sync enforcement: changes to terminology/object model/state machine/field tables must follow order: SYSTEM_DESIGN.md → config/lexicon.json + reference docs → code + tests
- [§0.5] Maintain `config/lexicon.json` with canonical English names; UI surfaces use formal Chinese display names
- [§0.6] Dual-layer validation: every code change must verify both Python layer (services/, temporal/, runtime/, config/) and OpenClaw layer (openclaw/workspace/*/TOOLS.md, skills/*/SKILL.md, openclaw.json)
- [§0.9] No blocking UX: creation + execution must be atomic; no "created task, click to execute" pattern; no user-facing rating/scoring prompts; no user-visible Job/Step state machine; no internal error stack traces shown to user
- [§0.10] Self-governance pipeline: admin proposes change → CC/Codex reviews → execute → scripts/verify.py validates; user only participates in persona style preference and external publication review
- [§0.11] Four discrete scenes (copilot/mentor/coach/operator) as independent conversations; user selects scene, system does not auto-switch; each scene defined by SOUL.md (philosophy) + SKILL.md (behavior)

## §1 术语与对象模型

### 1.1 Object Model
- [§1.1] Implement 6 formal objects: Project, Draft, Task, Job, Step, Artifact
- [§1.1] Project/Draft/Task mapped to Plane (Project, DraftIssue, Issue); Job/Step/Artifact managed by daemon
- [§1.1] Draft → Task requires explicit conversion, no auto-upgrade
- [§1.1] Task dependencies use Plane `IssueRelation(blocked_by)`, no custom Trigger entity

### 1.2 State Model
- [§1.2] Task/Project states: use Plane state groups directly (backlog/unstarted/started/completed/cancelled); daemon does not maintain its own state layer
- [§1.2] Job state machine: running(queued|executing|paused|retrying) → closed(succeeded|failed|cancelled)
- [§1.2] No `settling` state; default succeeded Job goes directly to closed/succeeded
- [§1.2] `requires_review=true`: L1 raises confirmation in conversation (§4.8); Job does not pause
- [§1.2] "Re-run" always creates new Job on same Task, never clones a new Task
- [§1.2] Step states: pending / running / completed / failed / skipped / pending_confirmation
- [§1.2] `pending_confirmation`: Step awaits user conversation confirmation; Job continues; other non-dependent Steps keep running

### 1.3 Execution Types
- [§1.3] Implement 4 execution_type: agent (OC session), direct (Python/shell/API/deterministic), claude_code (CC CLI subprocess), codex (Codex CLI subprocess)
- [§1.3] `direct` preferred when output is fully determined by input (shell commands, local app control, browser open, file I/O, format conversion, DB queries, API calls, process management)
- [§1.3] `claude_code`/`codex` run via Temporal Activity subprocess, bypass OC, no session management; Activity auto-injects MEMORY.md + skill content; subprocess output collected into Artifact

### 1.4 Agent Architecture
- [§1.4.1] Implement 4 L1 scene agents: copilot, mentor, coach, operator — each an OC agent with MCP/skill access, independent SOUL.md + SKILL.md
- [§1.4.1] L1 agents: single instance each, multi-session concurrent; managed by API process (persistent session, not Temporal)
- [§1.4.1] All L1 share base capabilities: routing decision, Job DAG planning, Replan Gate, user intent parsing (former counsel capabilities)
- [§1.4.2] Implement 6 L2 execution agents: researcher, engineer, writer, reviewer, publisher, admin — each with independent OC workspace, TOOLS.md, Mem0 memory bucket (agent_id isolated)
- [§1.4.2] L2: 1 Step = 1 Session, Temporal managed
- [§1.4.3] L1 → L2 flow: L1 outputs structured action → daemon creates Task/Job/Step → Temporal → L2 OC session; L2 results pushed to L1 conversation (no user prompt needed)
- [§1.4.3] L1 planning specifies `agent` (L2) + optional `model` override
- [§1.4.3] Fixed 4 L1 + 6 L2 = 10 agents; extend capabilities via skill/MCP, never dynamic agent creation
- [§1.4.3] reviewer only identifies issues, never directly fixes artifacts

### 1.5 Knowledge Hierarchy
- [§1.5] Enforce priority: Guardrails > External Facts > Persona > System Defaults

### 1.6 Infrastructure Components
- [§1.6] Integrate: Plane, Temporal, Langfuse, MinIO, RAGFlow, Mem0, NeMo Guardrails, pgvector, PG LISTEN/NOTIFY, Firecrawl

### 1.7 System Maintenance
- [§1.7] Implement daily cleanup Job (Temporal Schedule): clean knowledge_cache expired entries (sync delete RAGFlow docs), clean Mem0 memories >90 days untriggered (CC/Codex reviewed), archive expired Job/Artifact, quota reset
- [§1.7] Implement daily backup Job (Temporal Schedule): PG incremental backup, MinIO critical bucket snapshots

### 1.8 Terminology
- [§1.8] Remove all deprecated terms from codebase (Folio/Slip/Writ/Deed/Move/Brief/Wash/Offering/Psyche/Instinct/Voice/Preferences/Rations/Ledger/SourceCache/Spine/Nerve/Cortex/Ward/Canon/scout/sage/counsel/scholar/artificer/scribe/arbiter/envoy/steward/Herald/Cadence/Ether/Trail/Portal/Console/Vault/Memory/Lore etc.)

## §2 系统架构

### 2.2 Process Boundaries
- [§2.2] Two processes: daemon API (FastAPI) and daemon Worker (Temporal Worker)
- [§2.2] API process: webhook receiving, glue API, WebSocket, L1 OC session management (persistent conversations), lightweight query endpoints
- [§2.2] Worker process: Temporal activities, Plane writeback, L2 OC calls, Mem0, NeMo, MCP, MinIO, conversation compression
- [§2.2] API and Worker share no in-memory state; coordinate via PG, Temporal, Plane, MinIO
- [§2.2] Job-level logic owned by Worker + Temporal only, not in Plane webhook handlers
- [§2.2] No Temporal workflows or L2 execution chains in API process
- [§2.2] L1 session data flow: user message → WebSocket → API → sessions_send(L1 OC session) → streaming response → WebSocket → user; L1 structured action → API creates Temporal workflow → Worker executes L2

### 2.5 Plane Object Mapping
- [§2.5] Map Project→Plane Project, Draft→Plane DraftIssue, Task→Plane Issue; Job/Step stay in daemon PG + Temporal

### 2.6 External Outlets
- [§2.6] Telegram via OC native channel (announce); GitHub via MCP server; social media via MCP server per platform API; login-required platforms via Playwright MCP; local apps via direct Step
- [§2.6] publisher (L2) is the sole external outlet agent

### 2.7 External Knowledge Acquisition
- [§2.7] Knowledge pipeline: researcher → MCP search/Semantic Scholar → URL+summary; full text → PDF via RAGFlow, webpage via Firecrawl → clean Markdown → RAGFlow or knowledge_cache
- [§2.7] knowledge_cache in PG with TTL per source_tiers.toml (A=90d, B=30d, C=7d)
- [§2.7] Implement source_tiers.toml for external source trust grading (A/B/C)
- [§2.7] Implement sensitive_terms.json for privacy filtering via NeMo input rail
- [§2.7] Separation: external knowledge (factual, citable) vs internal knowledge (personal, Mem0)

### 2.8 Model Strategy
- [§2.8] Configure default models per agent: L1 fast(conversation)/analysis(planning); L2 researcher=analysis, engineer=fast, writer=creative, reviewer=review, publisher=fast, admin=analysis
- [§2.8] Model names/providers must be configurable, not hardcoded

### 2.9 Persistence Boundaries
- [§2.9] Plane holds Task/Project/Draft collaboration info
- [§2.9] daemon PG holds Job/Step/Artifact metadata, events, extension fields
- [§2.9] MinIO holds Artifact full objects, large objects, audit versions
- [§2.9] Langfuse holds traces (not business truth source)
- [§2.9] Mem0 holds Persona and memory (not business facts)

## §3 执行模型

### 3.1 Routing Decision
- [§3.1] L1 outputs structured routing decision with fields: intent, route, model, task/tasks
- [§3.1] Three route types only: direct (skip Project/Task, create single-Step ephemeral Job), task (create 1 Task + first Job), project (create Project + Task DAG + entry Task first Job)
- [§3.1] `route="direct"` creates 1-Step ephemeral Job persisted in `jobs` table with `is_ephemeral=true`
- [§3.1] `route="task"`: create Issue → write daemon_tasks → freeze first Job's `dag_snapshot`
- [§3.1] `route="project"`: create Project → batch create Tasks/dependencies → start entry Task's first Job
- [§3.1] Plane object creation responsibility belongs to L1 planning result; Worker executes Plane API/MCP calls
- [§3.1] Routing decision failure must not silently create a fourth path

### 3.2 Step Granularity
- [§3.2.1] 1 Step = 1 goal; can invoke any agent and tool
- [§3.2.1] Minimize Step count — each boundary is an info loss point (Artifact summary compression)
- [§3.2.1] Step upper bound = context window 100% minus ~800 token fixed overhead
- [§3.2.1] Deterministic operations must use `direct`, not `agent`

### 3.3 Session Model
- [§3.3.1] L1 Session: persistent OC session; daemon manages context; continuous conversation via `sessions_send`
- [§3.3.1] L1 proactive compression at 70% contextTokens (before OC compaction)
- [§3.3.1] L1 multi-session chaining: old sessions kept open (full text preserved), daemon controls routing
- [§3.3.1] Implement 4-layer conversation compression in PG: raw (conversation_messages), digest (conversation_digests), decisions (conversation_decisions), memory (Mem0)
- [§3.3.1] Scene is filter column, not hard partition; decisions table must be cross-scene queryable by project_id/tags
- [§3.3.2] L2 Session: 1 Step = 1 Session; `sessions_spawn` creates independent session, closed after Step completes
- [§3.3.2] Session key format: `{agent_id}:{job_id}:{step_id}`
- [§3.3.2] L2 session content injection ≤ 800 tokens: MEMORY.md (≤300) + Mem0 on-demand (50-200) + Step instruction (structured JSON) + upstream Artifact summary
- [§3.3.3] Each agent MEMORY.md ≤ 300 tokens; only identity + highest priority behavior rules; task preferences/style/planning experience go to Mem0
- [§3.3.1-sub] OC agent concurrency via `maxChildrenPerAgent` / `maxConcurrent` config
- [§3.3.1-sub] Step-internal subagent parallelism: Leaf mode (maxSpawnDepth=1, no subagent) vs Orchestrator mode (maxSpawnDepth=2, can spawn subagents)
- [§3.3.1-sub] Subagent constraints: no MEMORY.md, no Mem0; parent injects context via attachments; results via announce step; `cleanup: "delete"`; max nesting 5 layers, recommend ≤2

### 3.4 Token Management
- [§3.4] Configure `runTimeoutSeconds` per Step type (search:60s, writing:180s, review:90s)
- [§3.4] Step instructions include explicit token budget declaration
- [§3.4] OC quota per agent token daily limit in openclaw.json
- [§3.4] Langfuse monitoring: single Step token > threshold → alert
- [§3.4] `contextPruning: cache-ttl` = 5 min cache TTL
- [§3.4] `maxSpawnDepth` default 2, `maxChildrenPerAgent` default 5, `maxConcurrent` default 8

### 3.5 Job Lifecycle
- [§3.5] Job creation = atomic (create + immediately execute); no "create without execute"
- [§3.5] Same Task can have at most 1 non-closed Job at a time
- [§3.5] Rerun creates new Job; old Job preserved, never overwritten
- [§3.5] Step DAG snapshot frozen in `dag_snapshot` at Job creation; Task DAG changes don't affect running Jobs
- [§3.5] Plane writeback failure: retry 5 times; if still fails, set `plane_sync_failed=true` in PG; async compensation retries; never alter Job business result due to writeback failure
- [§3.5] `requires_review=true`: L1 raises confirmation in conversation + Telegram notification; Job does not pause; dependent Steps marked `pending_confirmation`; user denial → rework/terminate decision; long no-reply → L1 decides per Persona
- [§3.5] Re-execution intent: L1 judges from conversation context (denial/exploration/refinement); determines learning signal type + new Job planning context; old Job status never rewritten

### 3.6 Initial DAG & Context
- [§3.6] First Job DAG based on: Plane Issue description, Plane Issue Activity (conversation history), L1 Mem0 planning experience, Project known context
- [§3.6.1] Project-level context assembly: Project goal + completed Task list (title+status+final Artifact summary) + current Job result + incomplete Task list + Mem0 planning experience (~100-200 tokens)
- [§3.6.1] Token control: Artifact summary not full text (~50 tokens/Task); >20 Tasks: keep latest 5 completed + all incomplete
- [§3.6.2] Re-run minimizes redo scope: analyze prior Job DAG/Artifacts, only create Steps for changed parts, inject unchanged Artifacts via `input_artifacts`, final output is complete new version
- [§3.6.2] Re-run optimization rules must be encoded in L1 OC skill (§9.10)

### 3.7 Step Parallel Execution & Artifact Passing
- [§3.7] L1 outputs Step dependency graph; execution: topological sort into layers, same-layer Steps run in parallel
- [§3.7] Parallel Step failures must be aggregated before L1 judgment (no silent exception swallowing)
- [§3.7.1] Step→Step (same Job): Artifact stored in MinIO, metadata (path, type, summary) in PG `job_artifacts`; dependent Step reads upstream metadata, injects into agent prompt; large files pass MinIO path + summary only
- [§3.7.1] Job→Job (same Task): prior Job's final Artifact auto-becomes new Job's initial context
- [§3.7.1] Task→Task (same Project): chain trigger injects predecessor Task final Job Artifact summary; L1 specifies inter-Task data flow via `task_input_from`

### 3.8 Step Failure Handling
- [§3.8] Fixed failure handling order: Retry (Temporal RetryPolicy) → Retry exhausted → L1 judges: skip/replace/terminate → escalate with `requires_review: true`
- [§3.8] Temporal native checkpoint: each completed Activity recorded in event history; Worker crash → Workflow replay skips completed Steps
- [§3.8] reviewer rework: new Step uses fresh session; reviewer results injected as structured Artifact via `input_artifacts`
- [§3.8.1] reviewer trigger strategy: 3 tiers — (1) NeMo Guardrails output rail on all Steps (zero token), (2) reviewer session for `requires_review=true` Steps, (3) mandatory reviewer for all external-publish Steps

### 3.9 Dynamic Replanning
- [§3.9] Replan Gate inserted before chain trigger: L1 receives Project goal + completed Task summaries + current Job result; judges deviation; if no deviation → continue chain; if deviated → output Task DAG diff
- [§3.9] Replan diff schema: `operations[]` with `add/remove/update/reorder`, each with `op/target_task_id/after_task_id/payload` [DEFAULT]
- [§3.9] Replan batch writes: sequential execution + failure compensation; each operation independent write; failure → 5 retries + `plane_sync_failed` + async compensation
- [§3.9] Replan Gate uses analysis model

### 3.10 Task Triggers
- [§3.10] Three mutually exclusive trigger types: manual, timer (Temporal Schedule), chain (predecessor Job closed → Replan Gate)
- [§3.10] Chain requires predecessor's latest Job to be closed/succeeded; predecessor failure does not trigger downstream
- [§3.10] Dependency changes must go through Plane object change + activity stream record
- [§3.10] Trigger is hard constraint: unmet prerequisites → L1 rejects and explains (not silent ignore)

### 3.11 Runtime Defaults
- [§3.11] Step/Job time budgets, heartbeat, retry, quota params from reference doc Appendix B
- [§3.11] All tables reserve `user_id` column for future multi-user expansion

### 3.12 External Tool Handoff
- [§3.12] Handoff = last direct Step in Job DAG; context files (CLAUDE.md, AGENTS.md) auto-generated from prior Step Artifact summaries
- [§3.12] Handoff targets: Claude Code (write CLAUDE.md), Codex (write AGENTS.md), VSCode (open command), browser (webbrowser.open)
