# TODO Draft — §4-§6

## §4 交互与界面契约

### 4.1 界面架构
- [§4.1] 自建桌面客户端作为主交互入口，提供 4 个场景对话（copilot/mentor/coach/operator）
- [§4.1] 4 个 Telegram bot（独立 DM），与桌面客户端完全同步
- [§4.1] Plane 仅作为后端数据层，用户不直接使用

### 4.2 桌面客户端
- [§4.2] 实现三种展示模式：对话（纯文本）、场景 panel（PG 数据驱动自研 UI）、浏览器 view（Electron BrowserView/WebView）
- [§4.2] 4 个场景各自独立对话，类似微信多个聊天
- [§4.2] mentor panel：当前学习计划、assignment 列表（待交/已交/已评）、学习进度
- [§4.2] coach panel：本周计划执行率、最近训练数据摘要、下次评估时间
- [§4.2] copilot panel：活跃 Project 列表、进行中 Task 状态、最近产出
- [§4.2] operator panel：各平台运营数据、待审内容、自动发布日志
- [§4.2] Web 平台（Google Docs, intervals.icu, 社媒后台）在浏览器 view 内嵌打开
- [§4.2] VS Code 通过系统调起（`code` CLI / `vscode://` URI），不嵌入
- [§4.2] 轻量代码查看/编辑使用 panel 内嵌 Monaco Editor
- [§4.2] 技术选型 Electron（Chromium 内核），前端代码同时用于桌面和远程 Web 访问
- [§4.2] 客户端没有按钮操作，所有操作通过对话完成（"做 X"→创建+执行原子化，"先停"→pause Signal，"算了"→cancel Signal，"重新来"→新 Job）
- [§4.2] assignment 系统是 panel 功能，提交入口指向外部工具（Google Docs/GitHub），daemon 通过 webhook 或轮询感知提交
- [§4.2] 对话和展示严格分离：对话里不出现链接和富内容

### 4.3 Draft 语义与转正
- [§4.3] Draft 是正式对象，来源四类：用户对话、规则触发、外部事件、系统内部推进
- [§4.3] 自动任务也必须先形成 Draft（除 route="direct"）
- [§4.3] Draft 转 Task 由 L1 自行判断，用户意图明确时自动转正，无需用户额外确认

### 4.4 任务信息呈现
- [§4.4] 用户问"进展怎么样"→ daemon 用对话回复当前任务状态
- [§4.4] 用户问"这个项目整体情况"→ daemon 汇总 Project 下各 Task 状态
- [§4.4] 用户问"上次的结果呢"→ daemon 在阅读器 view 中展示 Artifact
- [§4.4] 结构化信息只在用户明确问到时以自然语言或简洁摘要呈现，不默认展示

### 4.5 活动流
- [§4.5] 场景对话流存储在 `conversation_messages` PG 表，客户端 4 个对话 view 直接消费
- [§4.5] Task 活动流（面向 CC/admin）记录 L2 执行事件：Job 边界、Step 关键状态、agent 产出摘要
- [§4.5] Task 活动流 API 保留：返回同 Task 下所有 Job 的合并活动流，按时间排序，每条消息携带 `job_id`

### 4.6 Artifact 呈现
- [§4.6] 文本类 Artifact 在阅读器 view 中 Markdown 渲染展示
- [§4.6] 需要浏览器的 Artifact 在浏览器 view 中打开
- [§4.6] 文件类 Artifact 提供下载入口
- [§4.6] Artifact 呈现在对话流中自然引出（"写好了，你看看"→阅读器 view 自动打开）

### 4.7 反馈与 Persona 回路
- [§4.7] 反馈完全对话式：用户说"这里不好"就是反馈，沉默=accepted
- [§4.7] Persona 品味类更新自然嵌入对话（"我注意到你喜欢这种写法"），用户不回复=确认，用户说"不对"=调整
- [§4.7] L1 agent 负责从对话中提取反馈信号和最终写入流程
- [§4.7] writer/publisher 可提出候选但不直接落库

### 4.8 非阻塞确认机制
- [§4.8] daemon 不阻塞等待用户确认（不使用 paused 状态等 Temporal Signal）
- [§4.8] 系统级审查（质量/安全/技术）由 CC/Codex 自动完成，不涉及用户
- [§4.8] 品味类确认在对话中自然提出，不暂停 Job；用户长时间未回复时 L1 根据 Persona 自行决定
- [§4.8] 高风险操作（不可逆对外动作）在对话中知会用户并等待回复，但 Job 可继续执行不依赖确认的 Step
- [§4.8] `requires_review=true` → L1 在对话中提出确认请求 + Telegram 通知，Job 不进入 paused
- [§4.8] 确认结果影响的 Step 标记为 `pending_confirmation`，确认后继续

### 4.9 API 端点
- [§4.9] `POST /scenes/{scene}/chat` — 场景对话输入（scene=copilot/mentor/coach/operator）
- [§4.9] `GET /scenes/{scene}/chat/stream` (WebSocket) — 场景实时对话流
- [§4.9] `GET /scenes/{scene}/panel` — 场景 panel 数据
- [§4.9] `GET /tasks/{id}/activity` — Task 活动流（后台，面向 CC/admin）
- [§4.9] `GET /artifacts/{id}` — Artifact 内容
- [§4.9] `GET /artifacts/{id}/download` — Artifact 下载
- [§4.9] `GET /status` — 系统整体状态
- [§4.9] `GET /auth/google` — Google OAuth 登录
- [§4.9] `GET /auth/github` — GitHub OAuth 登录
- [§4.9] `GET /auth/callback` — OAuth 回调
- [§4.9] 不提供 pause/resume/cancel 操作端点，这些通过对话自然语言完成
- [§4.9] [DEFAULT] 对话流传输：WebSocket 或 SSE+POST，消息可携带多种类型（文本、panel 更新指令、浏览器导航指令），客户端根据类型分发

### 4.10 Telegram
- [§4.10] 4 个独立 Bot Token，4 个独立 DM（copilot/mentor/coach/operator）
- [§4.10] 与桌面客户端 4 个聊天页面完全同步
- [§4.10] 承载：完成/失败/告警通知
- [§4.10] 承载：品味类确认请求推送（用户可直接在 Telegram 回复）
- [§4.10] 承载：移动端完整对话交互（与桌面同步）
- [§4.10] 不承载：复杂结构化编辑（引导到客户端）
- [§4.10] 不承载：场景 panel 展示

### 4.11 管理界面
- [§4.11] Plane 管理界面面向 CC/admin，暴露 Task/Job/Step 元数据和执行摘要、agent 列表和状态、状态机信息、Persona 文件只读呈现
- [§4.11] Persona 文件路径：`persona/voice/*.md`（identity.md、common.md、zh.md、en.md、overlays/*.md）
- [§4.11] Persona 修改由 CC/Codex 通过 git commit 管理，不通过 UI 编辑

---

## §5 知识、Persona、Guardrails 与 Quota

### 5.1 层级
- [§5.1] 实现正式层级：Guardrails > External Facts > Persona > System Defaults
- [§5.1] 冲突处理代码逻辑：Guardrails vs Persona→Guardrails 赢；External facts vs 用户→External facts 赢；Persona vs defaults→Persona 赢

### 5.2 Guardrails
- [§5.2] 集成 NeMo Guardrails（Python 库嵌入 Worker 进程，零额外服务）
- [§5.2] 硬规则：NeMo input/output rail（Colang DSL），覆盖安全边界、隐私泄露检测、格式校验、Quota 上限、token 预算
- [§5.2] 软规则：NeMo dialog rail + guardrails.md 注入，覆盖质量底线、专业标准
- [§5.2] 关键审查：L1 安排审查 Step + NeMo output rail，覆盖对外发布内容和高风险操作

#### 5.2.1 信息门控
- [§5.2.1] Persona 候选写入前过 Guardrails 代码校验（用户确认不等于免检）
- [§5.2.1] 外部知识引用过 source_tier 校验

#### 5.2.2 NeMo 配置
- [§5.2.2] Input rail：过滤外发 query 中的敏感词（sensitive_terms.json）
- [§5.2.2] Output rail：检查输出是否违反硬规则
- [§5.2.2] Custom action：Mem0 写入前校验、source_tier 校验
- [§5.2.2] Colang 规则文件位置：`config/guardrails/`

#### 5.2.3 guardrails.md
- [§5.2.3] 编写 guardrails.md 内容：输出质量底线、信息完整性、安全边界、专业标准、冲突处理规则
- [§5.2.3] 可降级冲突流程：提醒→确认→标注 user_override
- [§5.2.3] 不可降级冲突流程：拒绝→解释

#### 5.2.4 演进
- [§5.2.4] guardrails.md 纳入 git 管理，不由用户或 LLM 自动更新

### 5.3 Persona 双层结构
- [§5.3] 文件层（稳定基底）：`persona/voice/identity.md`, `common.md`, `zh.md`, `en.md`, `overlays/*.md`
- [§5.3] 动态层（运行期记忆）：Mem0 semantic/procedural memory

#### 5.3.1 Mem0 记忆类型
- [§5.3.1] AI 身份和人格 → semantic memory（agent 级）
- [§5.3.1] 写作风格 → procedural memory（agent 级，writer/publisher 用）
- [§5.3.1] 用户偏好 → semantic memory（user 级）
- [§5.3.1] 规划经验 → procedural memory（agent 级，L1 共享）

#### 5.3.2 冷启动
- [§5.3.2] 冷启动通过对话完成，用户不需要准备任何材料
- [§5.3.2] 通用流程：用户对话→writer 生成写作样本→reviewer 校验→daemon 展示→用户调整→写入 Mem0
- [§5.3.2] CC 预置快捷路径：CC 直接生成 Persona 材料预置到系统
- [§5.3.2] 最小启动：无输入→中性风格→随反馈积累
- [§5.3.2] 冷启动能力必须保留（Persona 丢失后重建场景）

### 5.4 Persona 更新责任
- [§5.4] 用户品味类更新链路：Job closed→L1 列出风格类反馈候选→用户确认→NeMo 校验→写入 Mem0
- [§5.4] 系统级调整链路：admin 提出→CC/Codex 审查→执行→verify.py 验证
- [§5.4] writer/publisher 负责提出候选，L1 负责确认闭环和最终写入

#### 5.4.1 漂移检测
- [§5.4.1] 超过 90 天未触发的记忆由 CC/Codex 审查后自动清理
- [§5.4.1] 矛盾检测结果由 admin 在体检时发现，CC/Codex 审查后合并或删除
- [§5.4.1] 品味矛盾（如风格偏好冲突）推送 Telegram 通知，用户回复确认

### 5.5 Mem0 注入
- [§5.5] Mem0 只做按需检索，不做全量注入
- [§5.5] 实现各 agent 的检索重点配置（L1: 规划经验/DAG 模式/场景上下文; researcher: 搜索策略; engineer: 技术偏好; writer: 写作风格+语言+task_type; reviewer: 质量标准; publisher: 发布风格+渠道; admin: 运维经验）
- [§5.5] [DEFAULT] 单次检索上限默认 5 条
- [§5.5] NeMo Guardrails 规则在引擎层执行，不注入 prompt（零 token）

### 5.6 外部知识获取工具链
- [§5.6] 集成通用 MCP search（网页搜索）→ researcher
- [§5.6] 集成 Semantic Scholar API（学术论文搜索）→ MCP tool → researcher
- [§5.6] 集成 Firecrawl（网页→干净 Markdown）→ Docker 自部署，MCP tool → L2 agent
- [§5.6] 集成 RAGFlow（PDF/文档→语义分块→向量检索）→ Docker 服务
- [§5.6] 外部知识必须能追溯回 URL/文档来源，无来源内容不算 External Facts

#### 5.6.1 knowledge_cache
- [§5.6.1] 实现 knowledge_cache 外部知识 TTL 与二级缓存
- [§5.6.1] 实现 source_tiers.toml：Tier A（arxiv/Semantic Scholar/官方文档，90 天 TTL，单源可引）、Tier B（Wikipedia/MDN/主流媒体，30 天 TTL，关键数据需交叉验证）、Tier C（Reddit/SO 评论/匿名来源，7 天 TTL，必须交叉验证）
- [§5.6.1] NeMo 硬规则：Tier C 来源数据不得作为事实性主张的唯一支撑
- [§5.6.1] 检索时先查同一 `project_id` 范围，再回退到全局

#### 5.6.2 隐私边界
- [§5.6.2] 维护 `config/sensitive_terms.json` 敏感词列表
- [§5.6.2] NeMo input rail 在 MCP 调用前过滤
- [§5.6.2] 被过滤的词替换为通用描述

### 5.7 内外知识分野
- [§5.7] 实现三类知识的分野逻辑：外部知识（有 source_url/source_tier，引用时标注来源）、内部知识（Mem0，塑造风格不塑造事实）、系统知识（NeMo Guardrails，最高信任）

### 5.8 Quota 与运行预算
- [§5.8] 实现三层 Quota：OC/session 层预算、Job 层预算、系统日预算
- [§5.8] [DEFAULT] 配额阈值和告警先走保守默认值（见附录 B），暖机后按 Langfuse 数据校准

---

## §6 基础设施与运行时契约

### 6.1 Docker 服务清单
- [§6.1] PostgreSQL 16 + pgvector — 主数据库（Plane + daemon + Mem0 共用），端口 5432
- [§6.1] Redis 7 — 缓存+消息队列（Plane + Langfuse 共用），端口 6379
- [§6.1] Plane API（Django+DRF）— Issue/Project/DraftIssue CRUD + Webhook，端口 8000
- [§6.1] Plane 前端（React+TypeScript）— 管理界面（CC/admin），端口 3000
- [§6.1] Plane Worker（Celery）— 异步任务
- [§6.1] Temporal Server — Workflow 编排 + Schedules，端口 7233
- [§6.1] Temporal UI — 运维 Dashboard，端口 8080
- [§6.1] MinIO — S3 兼容对象存储，端口 9000/9001
- [§6.1] Langfuse — LLM 追踪+评估，端口 3001
- [§6.1] ClickHouse — Langfuse 分析后端，端口 8123
- [§6.1] RAGFlow — 文档解析+分块+向量检索，端口 9380
- [§6.1] Elasticsearch 8 — RAGFlow 全文索引后端，端口 9200
- [§6.1] Firecrawl — 网页→干净 Markdown，端口 3002
- [§6.1] 这些服务只解决基础设施能力，不承担业务状态机

### 6.2 daemon 自有进程
- [§6.2] API 进程（FastAPI/uvicorn）：L1 OC session 管理（4 个持久对话）、WebSocket、Plane webhook handler、胶水 API
- [§6.2] Worker 进程（Temporal Python Worker）：L2 Activities（调 OC agent、写 Plane API、写 PG）、定时清理 Job、对话压缩、NeMo Guardrails、Mem0
- [§6.2] 两进程不直接通信，通过 Temporal workflow + PG 协作
- [§6.2] NeMo Guardrails 和 Mem0 作为 Python 库嵌入 Worker 进程
- [§6.2] API 进程负责边界接入、L1 对话、查询接口；L1 session 是 API 进程正式职责
- [§6.2] Worker 进程负责 L2 执行、Plane 回写、MCP、Mem0、NeMo、MinIO、对话压缩
- [§6.2] 不允许在 API 进程里运行 Temporal workflow 或 L2 执行链

### 6.3 OC Gateway 与 MCP 生命周期
- [§6.3] 10 agents 配置：L1（copilot/mentor/coach/operator）、L2（researcher/engineer/writer/reviewer/publisher/admin）
- [§6.3] L1 Session 持久，API 进程管理，daemon 控制压缩
- [§6.3] L2 Session：1 Step = 1 Session，生命周期 = Step 级别
- [§6.3] 并发配置：`maxChildrenPerAgent`（默认 5）/ `maxConcurrent`（默认 8），暖机时校准
- [§6.3] Subagent 深度：`maxSpawnDepth: 2`（orchestrator 模式），支持 Step 内并行
- [§6.3] MCP 分发：runtime/mcp_dispatch.py + config/mcp_servers.json
- [§6.3] `~/.openclaw → daemon/openclaw/` 软链接必须存在
- [§6.3] Session 生命周期 = Step 生命周期
- [§6.3] subagent 不加载 Mem0 / MEMORY.md
- [§6.3] tool routing 由 MCP dispatcher 统一分发
- [§6.3] MCP server 连接按 Worker 进程级持久化复用
- [§6.3] Worker 启动时连接并构建 tool 路由表
- [§6.3] 每次 MCP 调用带超时保护
- [§6.3] MCP server 崩溃/超时后标记不可用，让 Step 走失败/重试逻辑

### 6.4 PostgreSQL 事件总线
- [§6.4] PG 事件总线采用 `event_log + NOTIFY` 双写
- [§6.4] `event_log` 提供持久化与重放能力
- [§6.4] `NOTIFY` 提供即时唤醒能力
- [§6.4] Worker 重启后先补消费 `event_log` 未完成事件，再恢复监听
- [§6.4] channels 统一为：`job_events`、`step_events`、`webhook_events`、`system_events`

### 6.5 Temporal 约束
- [§6.5] Job = Workflow
- [§6.5] Step = Activity（或少数 runtime 包装 activity）
- [§6.5] timer = Temporal Schedule
- [§6.5] pause/resume/cancel = Signal / Workflow 控制
- [§6.5] 时间预算、retry policy、catch-up window 见附录 B，不得自行发明第二套调度系统

### 6.6 Plane 回写与补偿
- [§6.6] Plane 是协作真相源，但不是 Job 执行真相源
- [§6.6] Job 真实执行状态先落 daemon PG，再尝试回写 Plane
- [§6.6] Plane 回写失败时：先重试（最多 5 次，指数退避）→写 `plane_sync_failed` →补偿流程异步追平
- [§6.6] 不允许把 Job 标成 failed 来掩盖 Plane 同步失败

### 6.7 配置文件
- [§6.7] 正式配置文件：`config/mcp_servers.json`、`config/source_tiers.toml`、`config/lexicon.json`、`config/guardrails/`、`config/sensitive_terms.json`、`openclaw/openclaw.json`
- [§6.7] 配置默认值必须与参考文档附录 B/C/D 一致

### 6.8 外部依赖
- [§6.8] Python 3.11+（API + Worker）
- [§6.8] Node.js（MCP servers 运行时）
- [§6.8] LLM Provider API Keys：MiniMax、Qwen（analysis+review）、智谱（embedding）、GLM（creative）
- [§6.8] Telegram Bot Token：OC 原生 Telegram channel 配置
- [§6.8] GitHub Token：MCP server（@modelcontextprotocol/server-github）
- [§6.8] Semantic Scholar API Key（免费，可选）
- [§6.8] mem0ai Python 库
- [§6.8] nemoguardrails Python 库

### 6.9 启动与健康检查
- [§6.9] 启动顺序可验证：Docker 基础服务→PG/Temporal/Plane 就绪→OC Gateway→daemon Worker→daemon API
- [§6.9] Schedule 丢失自动恢复：所有 Schedule 定义存在 `config/schedules.json`
- [§6.9] admin 每周体检对比配置中应有的 Schedule 与 Temporal 中实际存在的 Schedule，缺失自动重建，多出标记给 CC 审查

### 6.10 开机自启动、桌面客户端与远程访问

#### 6.10.1 开机自启动
- [§6.10.1] macOS launchd plist（`~/Library/LaunchAgents/com.daemon.startup.plist`）
- [§6.10.1] 开机自动执行 `scripts/start.py`（拉起 Docker Compose + daemon 进程）
- [§6.10.1] start.py 检测 Docker Desktop 未运行时先启动 Docker Desktop

#### 6.10.2 桌面客户端
- [§6.10.2] Electron 桌面应用，同一套前端代码
- [§6.10.2] 菜单栏图标：状态指示（绿/黄/红）+ 点击打开主窗口 + 右键菜单
- [§6.10.2] 右键菜单：Start/Stop daemon、今日任务数、本周体检状态、打开 Langfuse/Temporal UI
- [§6.10.2] 菜单栏图标与桌面应用同一进程，菜单栏常驻，主窗口按需打开/关闭

#### 6.10.3 远程访问
- [§6.10.3] Tailscale Funnel + OAuth 认证，无需 VPN
- [§6.10.3] daemon API 进程（FastAPI）同时 serve 前端静态文件 + API
- [§6.10.3] Tailscale Funnel 将本地服务暴露为 HTTPS URL（免费，端到端加密，无需开端口）
- [§6.10.3] 认证统一使用 OAuth（Google/GitHub），登录后 JWT token 持久化
- [§6.10.3] 手机端：浏览器访问 HTTPS URL 或 PWA（加到主屏幕），可选 WebView 轻壳 app
- [§6.10.3] 前端同构：桌面 Electron 和远程浏览器使用完全相同的前端代码

### 6.11 备份制度
- [§6.11] PostgreSQL：`pg_dump` 到本地备份目录，每日，90 天滚动保留
- [§6.11] MinIO（artifacts bucket）：[DEFAULT] 增量备份（restic/rsync/MinIO versioning），每日，90 天滚动
- [§6.11] 配置文件（config/）：git 管理，每次变更，永久保留
- [§6.11] Persona 文件（persona/）：git 管理，每次变更，永久保留
- [§6.11] Skill 文件（openclaw/workspace/）：git 管理，每次变更，永久保留
- [§6.11] MinIO 备份必须增量，不做全量镜像（本机 460GB SSD 空间限制）
- [§6.11] 备份目录：`DAEMON_HOME/backups/`（可配置为外置硬盘路径）
- [§6.11] 备份 Job：Temporal Schedule 每日执行
- [§6.11] 恢复流程：`scripts/restore.py --date YYYY-MM-DD`

### 6.12 数据生命周期

#### 6.12.1 Artifact 存储策略
- [§6.12.1] Google Drive 是最终 Artifact 持久存储层，本地 MinIO 只做缓存
- [§6.12.1] 最终交付物同步到 Google Drive（永久，2TB），本地保留 30 天缓存
- [§6.12.1] 中间产物不同步 Google Drive，跟随 Job 生命周期（90 天后删除）
- [§6.12.1] 同步流程：Job closed→写入 MinIO→publisher 同步到 Google Drive→标记 `gdrive_synced=true`→30 天后清理 Job 删除本地副本（仅限已同步的）
- [§6.12.1] Key 标记保留：publisher 对外发布→自动标记 key；用户说"这个留着"→标记 key；同步到 Google Drive 的→自动标记 key

#### 6.12.2 其他数据生命周期
- [§6.12.2] Ephemeral Job（route=direct）：7 天后删除
- [§6.12.2] 常规 Job：30 天活跃→30-90 天归档（PG 保留，标记 archived）→90 天后删除
- [§6.12.2] Langfuse trace：90 天（Langfuse retention 配置）
- [§6.12.2] event_log（consumed）：7 天后删除
- [§6.12.2] 体检报告：52 周后删除
- [§6.12.2] 问题文件（resolved）：30 天后删除
- [§6.12.2] Mem0 记忆：永久，90 天未触发→CC 审查后清理
- [§6.12.2] PG 备份：90 天滚动
- [§6.12.2] 归档和删除由清理 Job 自动执行，不需要用户参与
- [§6.12.2] 本地 Artifact 删除前必须确认 `gdrive_synced=true`，未同步的不删

### 6.13 认证与多用户扩展

#### 6.13.1 认证
- [§6.13.1] OAuth 认证（Google/GitHub），首版即实现，不使用简单用户名密码
- [§6.13.1] 本地 Electron：OAuth 登录，token 持久化，不需每次登录
- [§6.13.1] 远程 Web 访问（Tailscale Funnel）：OAuth 登录，session 管理
- [§6.13.1] Telegram：绑定 OAuth 账号，首次关联后免登录
- [§6.13.1] API 调用：JWT token（OAuth 登录后颁发）
- [§6.13.1] [DEFAULT] 实现方式：FastAPI + authlib 或 python-social-auth

#### 6.13.2 多用户扩展（不堵死规则）
- [§6.13.2] PG 表结构预留 `user_id` 字段，单用户时用默认值
- [§6.13.2] API 层实现不硬编码"只有一个用户"
- [§6.13.2] Persona/Skill 路径用配置变量，不硬编码绝对路径
- [§6.13.2] Temporal Workflow ID 带 user_id 前缀
