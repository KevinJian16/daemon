# Daemon File Structure

> Generated 2026-03-17. Describes every directory and key file in `/Users/kevinjian/daemon/`.

---

## 1. Root Files

```
daemon/
  .env                          # Environment variables (secrets, API keys, ports)
  .env.example                  # Template for .env
  .gitignore                    # Git ignore rules
  alembic.ini                   # Alembic migration config (PG connection, script location)
  bootstrap.py                  # Cold-start bootstrap: validate OC environment, create directories, normalize 10-agent config
  daemon_env.py                 # Minimal .env loader (no third-party dependency)
  docker-compose.yml            # All infrastructure services (21 containers): PG, Redis, MinIO, Temporal, Plane, Langfuse, Firecrawl, RAGFlow, Ollama, etc.
  pyproject.toml                # Python package definition: dependencies (FastAPI, Temporal, httpx, OpenAI, Anthropic, MCP, asyncpg, Mem0, NeMo, etc.)
```

---

## 2. .ref/ -- Design Documents

```
.ref/
  SYSTEM_DESIGN.md              # System design master document (7th draft, sole authority)
  SYSTEM_DESIGN.review.html     # Color-coded review version (FINAL/DEFAULT/UNRESOLVED tags)
  SYSTEM_DESIGN_REFERENCE.md    # Appendices B-I: schemas, SQL DDL, configuration tables
  _archive/                     # Old design drafts and deprecated docs (read-only reference)
  _work/
    CLIENT_SPEC.md              # Tauri desktop client specification (DD-78)
    EXTERNAL_INTEGRATIONS.md    # 44 MCP server integration plan (P0/P1/P2 tiers)
    FILE_STRUCTURE.md           # This file
    IMPLEMENTATION_PLAN.md      # Implementation plan
    INFO_ARCHITECTURE.md        # Information monitoring architecture (InfoPullWorkflow)
    OC_DOCS_REFERENCE.md        # OpenClaw documentation cache
    SELF_REVIEW_2026-03-15.md   # Self-review audit notes
    SKILL_IMPLEMENTATION.md     # Skill implementation details
    SKILL_TODO_UPDATE.md        # Skill-related TODO updates
    SOP.md                      # Standard operating procedures
    TODO.md                     # Master task list (Phase 0-6 + Phase 3.5)
    TODO_AUDIT_OPENCLAW.md      # OC layer audit checklist
    TODO_AUDIT_PYTHON.md        # Python layer audit checklist
    TODO_DRAFT.md               # TODO drafting notes
    TODO_DRAFT_4_6.md           # TODO draft for phases 4-6
    TODO_DRAFT_7_10.md          # TODO draft for phases 7-10
    TODO_PROGRESS.md            # Progress tracking
    gen_review_html.py          # Script to generate SYSTEM_DESIGN.review.html
```

---

## 3. config/ -- Configuration Files

```
config/
  __init__.py                   # Package init
  com.daemon.startup.plist      # macOS launchd plist for auto-start
  lexicon.json                  # Machine-readable terminology dictionary (canonical terms with zh/en definitions)
  mcp_servers.json              # MCP server registry (transport, command, args, env for each server)
  mem0_config.py                # Mem0 initialization and memory retrieval helpers (PG + pgvector backend)
  model_policy.json             # Model routing policy: per-agent and per-task model assignments
  model_registry.json           # Model definitions: aliases (fast/analysis/creative/review/local), providers, context windows
  plane-nginx.conf              # Nginx reverse proxy config for Plane
  schedules.json                # Temporal Schedule definitions (maintenance 6h, health weekly, backup daily)
  sensitive_terms.json          # PII regex patterns for output redaction (SSN, passport, etc.)
  skill_registry.json           # Skill-to-agent mapping with descriptions
  source_tiers.toml             # Source credibility tiers (A: academic, B: mainstream, C: forums)
  system.json                   # Core system config: agent lists (L1/L2), Temporal namespace, concurrency defaults
  guardrails/
    __init__.py                 # Package init
    actions.py                  # NeMo Guardrails custom actions: validate_input, validate_output, source tier checks, PII filtering
    config.yml                  # NeMo Guardrails config (zero-token, pattern-based only, no LLM)
    safety.co                   # Colang safety rules: instruction override blocking, output filtering
  plane-patches/
    redirection_path.py         # Plane API entrypoint patch for OAuth redirection
  ragflow/
    service_conf.yaml           # RAGFlow service configuration
  temporal-dynamicconfig/
    development-sql.yaml        # Temporal dynamic config for SQL persistence
```

---

## 4. services/ -- API Process (FastAPI + Glue Services)

```
services/
  __init__.py                   # Package init
  api.py                        # FastAPI application: mounts routes, CORS, static files, startup/shutdown hooks
  event_bus.py                  # PG LISTEN/NOTIFY event bus for real-time inter-process events
  llm_local.py                  # Ollama local LLM client for internal tasks (triage, replan, compression)
  minio_client.py               # MinIO object storage client for Artifacts
  plane_client.py               # Plane REST API thin client (issues, drafts, modules, webhooks)
  plane_webhook.py              # Plane webhook handler (issue state changes -> Temporal workflow triggers)
  quota.py                      # Three-layer token quota enforcement (per-session, per-Job, daily system)
  ragflow_client.py             # RAGFlow integration client (document upload, search, delete)
  session_manager.py            # L1 session manager: persistent OC sessions for 4 scenes, 4-layer conversation compression
  store.py                      # PG data layer (asyncpg): CRUD for Projects, Tasks, Jobs, Steps, Artifacts, messages, digests
  api_routes/
    __init__.py                 # Package init
    auth.py                     # OAuth routes: Google + GitHub login, JWT callback, /auth/me
    scenes.py                   # Scene API: POST /scenes/{scene}/chat, WebSocket stream, GET panel data
    system.py                   # System routes placeholder (management via admin agent + scripts)
```

---

## 5. temporal/ -- Worker Process (Temporal Workflows + Activities)

```
temporal/
  __init__.py                   # Package init
  worker.py                     # Worker process entry point: registers workflows/activities, connects to Temporal
  workflows.py                  # Workflow definitions: JobWorkflow (DAG steps), HealthCheckWorkflow, SelfHealWorkflow, MaintenanceWorkflow, BackupWorkflow
  activities.py                 # Core activities: Job/Step lifecycle, OC session dispatch, Mem0 + Guardrails integration
  activities_exec.py            # Step execution activities: 4 execution types (agent/direct/claude_code/codex), heartbeat loop, quota check
  activities_health.py          # Health check + self-heal activities: infrastructure probes, service restart, Telegram alerts
  activities_maintenance.py     # Scheduled maintenance: clean expired knowledge, old Jobs, old messages, emit health events
  activities_replan.py          # Replan Gate: post-Job-close evaluation, deviation detection, Task DAG revision
```

---

## 6. runtime/ -- Runtime Utilities

```
runtime/
  __init__.py                   # Package init
  mcp_code_exec.py              # MCP server wrapper for Claude Code / Codex CLI execution (Semaphore-gated)
  mcp_dispatch.py               # MCP tool dispatcher: programmatic tool calls to MCP servers (zero LLM)
  openclaw.py                   # OpenClaw Gateway adapter: HTTP bridge to OC agent sessions and file system
  temporal.py                   # Temporal client wrapper: workflow submission, querying, signal sending
```

---

## 7. mcp_servers/ -- MCP Server Scripts (35 servers)

Custom MCP server implementations exposing tools to agents. 35 Python files organized by domain:

| Category | Servers | Count |
|---|---|---|
| **Academic / Research** | arxiv_search, core_api (CORE), crossref, openalex, semantic_scholar, unpaywall, paper_tools | 7 |
| **Google Workspace** | gmail, google_calendar, google_docs, google_drive, google_auth_helper | 5 |
| **Social / Content** | devto, hackernews, hashnode, reddit, twitter, rss_reader, newsdata | 7 |
| **Visualization / Rendering** | excalidraw_export, kroki, matplotlib_chart, mermaid_render | 4 |
| **Document / Writing** | languagetool, latex, typst | 3 |
| **Code / Engineering** | code_functions (tree-sitter), docker_control, libraries_io | 3 |
| **ML / Data** | huggingface, kaggle | 2 |
| **Web / Scraping** | firecrawl_scrape | 1 |
| **Fitness / Personal** | intervals_icu, strava | 2 |
| **macOS** | macos_control (window management, app launch, screen split) | 1 |

```
mcp_servers/
  __init__.py                   # Package init (registers all servers)
  arxiv_search.py               # arXiv paper search
  code_functions.py             # tree-sitter code analysis (Python, JS, Rust, Go)
  core_api.py                   # CORE open-access research API
  crossref.py                   # Crossref metadata lookup
  devto.py                      # DEV.to article publishing
  docker_control.py             # Docker container management
  excalidraw_export.py          # Excalidraw diagram export
  firecrawl_scrape.py           # Firecrawl web page -> Markdown
  gmail.py                      # Gmail send/read/search
  google_auth_helper.py         # Google OAuth token management
  google_calendar.py            # Google Calendar events
  google_docs.py                # Google Docs read/write
  google_drive.py               # Google Drive file management
  hackernews.py                 # Hacker News top stories/search
  hashnode.py                   # Hashnode blog publishing
  huggingface.py                # HuggingFace model/dataset search
  intervals_icu.py              # Intervals.icu training data
  kaggle.py                     # Kaggle dataset/competition search
  kroki.py                      # Kroki diagram rendering (PlantUML, Mermaid, etc.)
  languagetool.py               # LanguageTool grammar/style check
  latex.py                      # LaTeX compilation
  libraries_io.py               # Libraries.io package metadata
  macos_control.py              # macOS window management and app control
  matplotlib_chart.py           # Matplotlib chart generation
  mermaid_render.py             # Mermaid diagram rendering
  newsdata.py                   # NewsData.io news search
  openalex.py                   # OpenAlex scholarly data
  paper_tools.py                # Academic paper utility tools
  reddit.py                     # Reddit post/comment search
  rss_reader.py                 # RSS/Atom feed reader
  semantic_scholar.py           # Semantic Scholar paper search
  strava.py                     # Strava activity data
  twitter.py                    # Twitter/X post search
  typst.py                      # Typst document compilation
  unpaywall.py                  # Unpaywall open-access PDF finder
```

---

## 8. interfaces/ -- Client Interfaces

### 8.1 Portal (Desktop + Web Frontend)

Vite + React + Tailwind CSS application. Runs inside Tauri (desktop) or Electron, and as standalone web app.

```
interfaces/portal/
  index.html                    # HTML entry point
  package.json                  # npm dependencies (React, Tailwind, Vite, Electron, Tauri)
  package-lock.json             # Lock file
  vite.config.js                # Vite config: dev proxy to API, path aliases
  components.json               # shadcn/ui component config
  jsconfig.json                 # JS path aliases
  public/
    favicon.png                 # App favicon (PNG)
    favicon.svg                 # App favicon (SVG)
  src/
    main.jsx                    # React entry point
    App.jsx                     # Root component: sidebar (4 scenes) + SceneChat + PanelView
    styles.css                  # Global styles (Tailwind base + custom animations)
    components/
      AppSidebarFooter.jsx      # Sidebar footer: system status indicator (green/yellow/red)
      Composer.jsx              # Message input textarea with send button
      JobNotice.jsx             # Active/recent Job status banner per scene
      MessageThread.jsx         # Scrollable conversation message list with pulse animation
      PanelView.jsx             # Right panel: messages, digests, decisions, artifacts
      SceneChat.jsx             # Scene chat view: MessageThread + Composer + JobNotice
      Sidebar.jsx               # Scene selector sidebar with status dots
      ui/                       # shadcn/ui primitives (7 components)
        button.jsx
        input.jsx
        separator.jsx
        sheet.jsx
        sidebar.jsx
        skeleton.jsx
        tooltip.jsx
    hooks/
      use-mobile.js             # Mobile viewport detection hook
    lib/
      api.js                    # API client: sendMessage, getPanel, listJobs, getStatus (JWT-aware)
      platform.js               # Platform detection: Electron IPC bridge vs browser fallback
      utils.js                  # Utility functions (cn class merger)
  electron/
    main.cjs                    # Electron main process: tray icon, OAuth flow, status polling
    preload.cjs                 # Electron preload: exposes IPC bridge to renderer
    gen-icons.cjs               # Tray icon generation script
    icons/
      tray-green.png            # Tray icon: healthy
      tray-yellow.png           # Tray icon: degraded
      tray-red.png              # Tray icon: error
      tray-unknown.png          # Tray icon: unknown state
      tray-template.png         # macOS template tray icon
  src-tauri/
    tauri.conf.json             # Tauri app config: window size, identifier (com.daemon.desktop)
    Cargo.toml                  # Rust dependencies for Tauri
    Cargo.lock                  # Cargo lock file
    build.rs                    # Tauri build script
    capabilities/
      default.json              # Tauri capability permissions
    gen/schemas/                # Auto-generated Tauri schemas (ACL, capabilities, platform)
    icons/                      # App icons for all platforms (macOS .icns, Windows .ico, various PNGs)
    src/
      main.rs                   # Tauri entry point
      lib.rs                    # Tauri lib
```

### 8.2 Telegram Adapter

```
interfaces/telegram/
  adapter.py                    # Telegram bot adapter: 4 bots (one per L1 scene), event notifications (job_started/completed/failed), /status command
```

### 8.3 CLI

```
interfaces/cli/
  main.py                       # Command-line interface to Daemon API: scene chat, job status, system info
```

---

## 9. openclaw/ -- OpenClaw Agent Workspace

Root-level OpenClaw configuration and runtime data:

```
openclaw/
  .gitignore                    # Ignore session data, node_modules
  openclaw.json                 # Master agent configuration (10 agents, models, tools, skills)
  package.json                  # OpenClaw npm package
  package-lock.json             # Lock file
  update-check.json             # OC update check timestamp
  .openclaw/
    update-check.json           # OC runtime metadata
  credentials/
    telegram-*-allowFrom.json   # Telegram bot allow-lists (per L1 scene)
    telegram-pairing.json       # Telegram pairing config
  cron/
    jobs.json                   # OC cron job definitions
  identity/
    device.json                 # Device identity
    device-auth.json            # Device authentication
  subagents/
    runs.json                   # Subagent execution history
  telegram/
    update-offset-*.json        # Telegram polling offsets (per L1 scene)
```

### 9.1 Per-Agent Workspace Structure (Template)

Each of the 10 agents follows this structure:

```
openclaw/workspace/{agent}/
  .openclaw/
    workspace-state.json        # OC workspace runtime state
  SOUL.md                       # Agent identity, personality, communication style, constraints
  AGENTS.md                     # Subagent delegation rules and available agents
  TOOLS.md                      # Available MCP tools and usage patterns
  MEMORY.md                     # Daemon-injected persistent memory (Mem0 snapshot, role-specific context)
  SKILL_GRAPH.md                # Skill dependency graph and activation paths
  IDENTITY.md                   # OC-managed identity file
  HEARTBEAT.md                  # OC-managed heartbeat/status
  USER.md                       # User interaction preferences (present on most agents)
  skills/
    {skill_name}/
      SKILL.md                  # Skill definition: goal, steps, constraints, output format
  memory/                       # Agent-specific knowledge files (present on some agents, e.g. researcher)
```

### 9.2 All 10 Agents and Their Skills

**L1 Scene Agents** (4) -- persistent sessions, intent routing, task decomposition:

| Agent | Skills |
|---|---|
| **copilot** | routing_decision, task_decomposition, requires_review_judgment, replan_assessment |
| **mentor** | routing_decision, task_decomposition, requires_review_judgment, replan_assessment |
| **coach** | routing_decision, task_decomposition, requires_review_judgment, replan_assessment |
| **operator** | routing_decision, task_decomposition, requires_review_judgment, replan_assessment |

All 4 L1 agents share the same 4 skills (formerly counsel's exclusive capabilities, now generalized).

**L2 Execution Agents** (6) -- ephemeral sessions, domain-specific execution:

| Agent | Skills |
|---|---|
| **researcher** | academic_search, web_research, literature_review, source_evaluation, knowledge_base_mgmt, reasoning_framework |
| **engineer** | code_review, debug_locate, refactor, implementation, cc_codex_handoff |
| **writer** | academic_paper, tech_blog, documentation, announcement, data_visualization |
| **reviewer** | code_review, fact_check, quality_audit, rework_feedback |
| **publisher** | github_publish, telegram_notify, release_checklist, platform_adaptation |
| **admin** | health_check, health_check_3layer, incident_response, skill_audit, frontier_iteration |

---

## 10. scripts/ -- Operational Scripts

```
scripts/
  setup.sh                      # Fresh Mac setup: install Homebrew deps, Docker, Python venv, npm, etc.
  start.py                      # Universal recovery: Docker up, health checks, migrations, start Worker + API
  stop.py                       # Graceful shutdown: drain Worker, stop API (Docker stays running)
  warmup.py                     # Warmup orchestrator: Stage 2 link verification (programmatic)
  verify.py                     # Health verification + Telegram notification; also verifies specific issue fixes
  verify_sync.py                # Dual-layer validation: Python layer <-> OC layer sync check
  validate_lexicon.py           # Grep codebase for deprecated terminology violations
  watchdog.sh                   # Independent cron watchdog (5 min): process alive, API responsive, alerts
  restore.py                    # Restore from backup: PG + MinIO, by date
  state_reset.py                # Runtime state reset: clean PG state, OC sessions, optionally restart
  mem0_coldstart.py             # Mem0 memory seeding: initial agent + user persona memories
  run_warmup_tasks.py           # Run warmup Stage 3 test tasks via API
  run_exception_tests.py        # Run warmup Stage 4 exception scenarios
  clean_openclaw_residual.sh    # Remove non-canonical agent directories from ~/.openclaw/agents/
  plane-api-entrypoint.sh       # Plane API Docker entrypoint wrapper
  init-databases.sql            # PG init: create separate databases for Plane, Langfuse, Temporal
  init-firecrawl.sql            # PG init: Firecrawl NUQ schema (job queue tables)
```

---

## 11. warmup/ -- Warmup Test Framework

System calibration framework (5 stages, per SYSTEM_DESIGN.md SS7):

```
warmup/
  persona_analysis.md           # Stage 0/1 persona analysis results
  stage2_link_verification.py   # Stage 2: end-to-end verification of all 17 data links
  stage3_runner.py              # Stage 3: skill calibration test harness (submit tasks, poll, collect Langfuse traces)
  stage3_test_tasks.json        # Stage 3: test task definitions (per-scene, per-skill)
  stage4_exceptions.py          # Stage 4: 10 exception scenario tests (concurrency, timeout, crash recovery, etc.)
  results/
    stage1_verification.md      # Stage 1 verification output
    stage2_*.json               # Stage 2 link verification results
    stage3/
      run_*.json                # Stage 3 individual test run results
    stage3_results.json         # Stage 3 aggregated results
    stage4/
      run_*.json                # Stage 4 exception test results
```

---

## 12. persona/ -- User Persona Data

```
persona/
  stage0_interview.md           # Stage 0 warmup interview: 6 sections covering user identity, goals, preferences
```

---

## 13. assets/ -- Static Assets

```
assets/
  icon.svg                      # Daemon icon (SVG source)
  icon-120.png                  # Daemon icon 120x120
  icon-128.png                  # Daemon icon 128x128
```

---

## 14. state/ -- Runtime State

Runtime data generated during operation (not committed to git):

```
state/
  artifacts/
    references.bib              # Collected BibTeX references
  backups/
    {date}/                     # Legacy daily backups (deeds, herald_log, schedule_history, ward)
  health_reports/
    {date}.json                 # Health check reports
  mem0_qdrant/
    collection/                 # Qdrant vector DB data (Mem0 backend)
    meta.json                   # Qdrant metadata
  service_logs/
    api.out.log                 # API process stdout
    api.err.log                 # API process stderr
    worker.out.log              # Worker process stdout
    worker.err.log              # Worker process stderr
    openclaw_gateway.out.log    # OC gateway stdout
    openclaw_gateway.err.log    # OC gateway stderr
    telegram_adapter.out.log    # Telegram adapter stdout
    telegram_adapter.err.log    # Telegram adapter stderr
  telemetry/
    portal_events.jsonl         # Portal frontend telemetry events
    telegram_events.jsonl       # Telegram adapter telemetry events
```

---

## 15. tests/ -- Test Suite

```
tests/
  __init__.py                   # Package init
  conftest.py                   # Shared pytest fixtures for new architecture modules
  test_diagnostics.py           # Core glue layer unit tests (Store, PlaneClient, EventBus, etc.)
  test_guardrails.py            # NeMo Guardrails action tests (pattern validation, PII filtering, source tiers)
  test_mcp_servers.py           # Custom MCP server import + functionality tests
```

---

## 16. migrations/ -- Database Migrations

Alembic-managed PostgreSQL schema migrations:

```
migrations/
  env.py                        # Alembic environment config
  script.py.mako                # Migration script template
  001_initial_schema.sql        # Raw SQL: initial daemon schema (projects, tasks, jobs, steps, artifacts, messages, etc.)
  002_add_message_source.sql    # Raw SQL: add source column to conversation_messages
  versions/
    001_initial_schema.py       # Alembic Python migration: initial schema
```

---

## 17. Other Directories

```
.github/
  workflows/
    ci.yml                      # GitHub Actions CI: lint + test on push/PR to main

.vscode/
  settings.json                 # VS Code workspace settings (exclude node_modules, openclaw, state from search/watch)

alerts/
  TROUBLESHOOTING.md            # Troubleshooting guide for common issues
  watchdog.log                  # Watchdog alert history

backups/
  {date}/
    daemon.sql.gz               # Daily PG backup (compressed)

docs/
  api_scenes.md                 # Scene API endpoint documentation

vendor/
  firecrawl/                    # Firecrawl git submodule (self-hosted web scraping service)
```
