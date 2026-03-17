# TODO Draft — §7-§10 + Reference

---

## §7 暖机、可观测性与自愈

### 7.1 暖机本质

- [§7.1] 暖机目标：daemon 所有对外输出达到"伪人"水准（与用户本人亲手做的无法区分）
- [§7.1] 暖机分工：Stage 0-2 由 CC 主导，Stage 3+ 由 admin 主导

### 7.2 暖机前提（Phase 0-5 完成才能开始暖机）

- [§7.2] Phase 1 前提：Docker Compose 全部服务运行且健康
- [§7.2] Phase 1 前提：`.env` 文件所有连接信息正确
- [§7.2] Phase 1 前提：宿主机 → Docker 网络连通
- [§7.2] Phase 2 前提：Plane API 客户端可用
- [§7.2] Phase 2 前提：Webhook handler 就绪
- [§7.2] Phase 2 前提：PG 事件总线就绪
- [§7.2] Phase 2 前提：PG 数据层就绪，所有表已创建（附录 C 全部表）
- [§7.2] Phase 2 前提：Plane Workspace + 默认 Project 已初始化
- [§7.2] Phase 2 前提：Plane webhook 指向 daemon API 且签名验证通过
- [§7.2] Phase 3 前提：Temporal Activities 读写 Plane API + PG
- [§7.2] Phase 3 前提：Temporal Schedules 已注册
- [§7.2] Phase 3 前提：publisher 出口就绪
- [§7.2] Phase 3 前提：Langfuse 接收 trace 数据
- [§7.2] Phase 3 前提：MinIO 文件上传/下载正常
- [§7.2] Phase 4 前提：NeMo Guardrails 规则配置就绪
- [§7.2] Phase 4 前提：Persona 初始模板文件存在
- [§7.2] Phase 4 前提：Mem0 服务可用，agent_id 隔离正常
- [§7.2] Phase 4 前提：pgvector knowledge_cache 表就绪
- [§7.2] Phase 4 前提：RAGFlow 服务运行正常
- [§7.2] Phase 4 前提：source_tiers.toml 和 sensitive_terms.json 配置完成
- [§7.2] Phase 5 前提：10 个 OC agent workspace 配置正确（4 L1 + 6 L2）
- [§7.2] Phase 5 前提：L2 agent 可被 Temporal Activity 调用
- [§7.2] Phase 5 前提：L1 agent 可由 API 进程管理 session
- [§7.2] Phase 5 前提：publisher 可通过 OC Telegram channel 发送消息
- [§7.2] Phase 5 前提：每个 agent 至少有 3-5 个核心 skill 草稿就绪
- [§7.2] Phase 5 前提：所有 LLM provider API key 已配置且可用

### 7.3 暖机五阶段

#### Stage 0：信息采集

- [§7.3/S0] 收集用户身份信息（职业、专业领域、日常工作内容）
- [§7.3/S0] 收集写作风格样本（≥3-5 篇，放入 `warmup/writing_samples/`）
- [§7.3/S0] 收集用户自我描述（`warmup/about_me.md`）
- [§7.3/S0] 收集外部平台账号信息
- [§7.3/S0] 收集偏好与禁忌
- [§7.3/S0] 收集真实任务示例（3-5 个）

#### Stage 1：Persona 标定

- [§7.3/S1] 分析写作样本 → LLM 一次性生成 Persona → 写入 Mem0（agent_id=user_persona）
- [§7.3/S1] Persona 内容：身份画像、跨语言写作结构偏好、中文风格特征、英文风格特征
- [§7.3/S1] 写入每个 Agent MEMORY.md（≤300 tokens）：Guardrails 核心规则摘要 + identity 摘要 + 任务偏好
- [§7.3/S1] writer/publisher 额外加 style 摘要，L1 额外加 planning hints
- [§7.3/S1] Persona 验证：writer 写短文 + publisher 写对外消息 → 对比用户原始风格 → 不通过则调整 Mem0 重试

#### Stage 2：链路逐通（17 条链路）

- [§7.3/S2-L01] 核心执行：用户对话 → L1 创建 Plane Issue → Job 执行
- [§7.3/S2-L02] 核心执行：daemon 触发 Temporal Workflow → Activity 执行
- [§7.3/S2-L03] 核心执行：Activity 调用 OC agent → agent 返回结果
- [§7.3/S2-L04] 核心执行：Job 状态写回 Plane
- [§7.3/S2-L05] 核心执行：requires_review → 对话确认 + Telegram 通知 → 用户回复 → L1 处理
- [§7.3/S2-L06] 知识链路：researcher 搜索 → Knowledge Base 写入 → 下次命中
- [§7.3/S2-L07] 知识链路：Persona 注入 → agent 产出风格一致
- [§7.3/S2-L08] 知识链路：Guardrails 拦截 → 违规操作被阻止
- [§7.3/S2-L09] 知识链路：Mem0 写入 → Job 完成后记忆条目可查
- [§7.3/S2-L10] 外部出口：publisher → OC Telegram channel → 用户收到消息
- [§7.3/S2-L11] 外部出口：publisher → GitHub MCP → repo 有变更
- [§7.3/S2-L12] 外部出口：Artifact → MinIO → 可下载
- [§7.3/S2-L13] 外部出口：Job 执行 → Langfuse 有完整 trace
- [§7.3/S2-L14] 调度链路：Temporal Schedule 触发 → 定时清理 Job 执行
- [§7.3/S2-L15] 调度链路：Task 依赖链 → 前序 Job closed 后触发后序
- [§7.3/S2-L16] 事件链路：PG LISTEN/NOTIFY → 订阅方收到事件
- [§7.3/S2-L17] 事件链路：Plane webhook 签名验证 → 伪造请求被拒绝

#### Stage 3：测试任务套件 + Skill 校准

- [§7.3/S3] 测试任务必须覆盖 4 个 L1 场景（对话体验、L1→L2 调度、场景切换）
- [§7.3/S3] Skill 校准：每个 Step 通过 Langfuse 检查（token 超标？步骤按 skill 执行？reviewer 接受？）
- [§7.3/S3] 不达标 Step → 定位具体 skill → 修改后重跑同类任务 → 迭代到稳定
- [§7.3/S3] 任务设计原则：真实场景、复合性、覆盖面（每 agent 多任务、每 skill 至少触发一次）、领域多样、对外发布
- [§7.3/S3] 测试矩阵维度：领域（≥3 不同领域）、Agent 组合（单/双/全链路）、触发方式（手动/定时/链）、产出类型（代码/文档/报告/发布内容）、外部出口（GitHub/Telegram/其他）、持续性（一次性/长期跟踪）

#### Stage 4：异常场景验证

- [§7.3/S4] 验证 10 个异常场景：并发 Job、Step 超时、Agent 不可用、Worker 崩溃恢复、PG 连接断开恢复、Plane API 不可用时补偿、Guardrails 拦截、Quota 耗尽、Schedule 积压、大文件 Artifact 处理

### 7.4 收敛标准

- [§7.4] 伪人度：连续 5 个不同类型任务的对外产出与用户本人无法区分
- [§7.4] 单 Task 执行基线稳定
- [§7.4] chain trigger 命中正确
- [§7.4] 学习机制形成闭环
- [§7.4] 对外产出达到可接受的"伪人度"

### 7.5 暖机目录结构

- [§7.5] 创建 `warmup/writing_samples/`、`warmup/about_me.md`、`warmup/results/`

### 7.6 可追溯链

- [§7.6] 每个 Job 必须有完整可追溯链：Plane Issue → Job ID（写回 Plane comment）→ PG job/step 记录 → Langfuse trace → Temporal workflow history
- [§7.6] FINAL：排障必须能从任一端点追到整条链，不允许"只有日志里看得到、数据库里没有"的关键状态

### 7.7 周度体检

- [§7.7] 体检由 Temporal Schedule 每周自动执行，无需用户触发
- [§7.7] FINAL：体检不只检查偏移，还驱动系统自我迭代

#### 7.7.1 三层检测

- [§7.7.1] 基础设施层：17 条数据链路验证（Stage 2 缩减版），全自动脚本，~10min
- [§7.7.1] 质量层：固定基准任务套件（暖机时选定 5-8 个代表性任务），admin 主导半自动，~1h
- [§7.7.1] 前沿扫描层：researcher 扫描各 agent 领域最新研究和最佳实践，researcher 搜索 + admin 评估，~30min

#### 7.7.2 检测内容

- [§7.7.2] 检测伪人度：admin 评估基准任务产出，对比暖机 baseline
- [§7.7.2] 检测风格一致性：writer/publisher 产出与 Persona 比对
- [§7.7.2] 检测 Skill token 效率：Langfuse 查各 skill 对应 Step 的 token 用量趋势
- [§7.7.2] 检测 reviewer 通过率：统计基准任务中 reviewer 审查通过率
- [§7.7.2] 检测外部平台格式：验证 GitHub/Telegram 产出格式仍符合平台要求
- [§7.7.2] 前沿对标：researcher 搜索各领域最新最佳实践，对比当前 skill 是否过时

#### 7.7.3 前沿驱动的自我迭代

- [§7.7.3] 无显著变化 → 记录"已扫描，无更新"
- [§7.7.3] 发现更好做法 → admin 评估 → engineer 起草更新方案 → CC/Codex 审查 → 更新 SKILL.md → 下周基准验证
- [§7.7.3] Langfuse 对比更新前后 token 用量 / reviewer 通过率
- [§7.7.3] FINAL：每一个功能设计决策，都先看前沿怎么说，再决定怎么做

#### 7.7.4 体检结果处置

- [§7.7.4] 全部通过 + 无前沿更新 → 生成周报 `state/health_reports/YYYY-MM-DD.json`
- [§7.7.4] 质量指标下滑（未跌破阈值）→ 周报标注，admin 记录趋势，暂不干预
- [§7.7.4] 任意指标跌破阈值 → admin 定位 skill/参数 → 触发自愈 Workflow → publisher 推送 Telegram
- [§7.7.4] 前沿扫描发现更新 → admin 提出 skill 更新提案 → CC/Codex 审查 → 自动更新 → 下周验证
- [§7.7.4] 告警三档：GREEN / YELLOW / RED
- [§7.7.4] reviewer 通过率 < 80% → 告警
- [§7.7.4] 单 skill 平均 token 用量 > baseline 150% → 告警
- [§7.7.4] 伪人度评分 < 4/5 → 告警

### 7.8 三层自愈流程

- [§7.8] Layer 1（admin 自动修复）：规则明确的问题 → admin 直接修改 SKILL.md → verify.py 验证 → 通过则静默记录
- [§7.8] Layer 2（自愈 Temporal Workflow）：FINAL — 自愈流程本身是 Temporal Workflow，拆分为 4 个独立 Activity
- [§7.8] Layer 2 Activity 1：admin 生成问题文件 `state/issues/YYYY-MM-DD-HHMM.md`
- [§7.8] Layer 2 Activity 2：CC/Codex 读问题文件 → 应用修复（只改文件/配置，不重启服务）
- [§7.8] Layer 2 Activity 3：scripts/start.py 重启服务（幂等，Temporal 自动 retry）
- [§7.8] Layer 2 Activity 4：scripts/verify.py 验证修复 → 通过则 Telegram「已自动修复」→ 失败进 Layer 3
- [§7.8] Layer 3（通知用户）：自愈 Workflow 失败 → publisher 推送 Telegram：「自动修复失败，请把问题文件发给 Claude Code」
- [§7.8] FINAL：正常情况下用户只需知道"系统正常"或"系统已修好"

### 7.9 问题文件格式

- [§7.9] 问题文件位置：`state/issues/YYYY-MM-DD-HHMM.md`
- [§7.9] 格式包含：你需要做什么、背景、具体问题、当前文件内容、期望行为、执行步骤
- [§7.9] 不使用系统内部术语（不写 Job/Step/Artifact）
- [§7.9] CC/Codex 只读这一个文件就能完成修复
- [§7.9] 验证脚本负责发 Telegram 通知，CC/Codex 不需要告知用户
- [§7.9] 问题文件不承担状态机职责（Temporal Workflow 负责编排）

### 7.10 配套脚本

- [§7.10] `scripts/start.py`：万能恢复点，从任意状态拉起 daemon 到正常运行（Docker Compose up → 健康检查 → PG migration → Temporal namespace → OC Gateway → Worker → API）。幂等。
- [§7.10] `scripts/stop.py`：优雅停止（Worker drain → API shutdown → Docker 保持运行）
- [§7.10] `scripts/verify.py --issue <id>`：读 issue 文件 → 运行验证 → 通过发「已修复」→ 失败发「修复失败」
- [§7.10] `scripts/restore.py --date <date>`：从备份恢复 PG + MinIO 到指定日期

### 7.11 用户操作边界

- [§7.11] 正常运行：用户无操作
- [§7.11] 自动修复成功：收到通知，无需操作
- [§7.11] 自动修复失败：把指定文件发给 CC
- [§7.11] 系统完全不响应：打开菜单栏 app 点 Start（或手动 `scripts/start.py`）

### 7.12 灾难恢复

- [§7.12] macOS 开机 → launchd 触发 `scripts/start.py`
- [§7.12] start.py 拉起 Docker Compose → 等待所有服务健康
- [§7.12] Temporal Server 恢复 → replay 中断的 Workflow
- [§7.12] Worker 恢复 → 继续中断的自愈 Workflow
- [§7.12] admin 下一次体检检测残留异常 → 正常自愈流程
- [§7.12] Temporal/PG 损坏：start.py 检测到 PG 损坏 → 自动调用 restore.py 从最近备份恢复
- [§7.12] FINAL：`scripts/start.py` 必须能处理冷启动场景——从刚开机的机器把整个 daemon 拉到正常运行状态

### 7.13 学习与漂移

- [§7.13] FINAL：学习只影响未来，不回写历史结果
- [§7.13] 规划经验、风格偏好、渠道格式都可积累，但必须来源可追溯
- [§7.13] Mem0 冲突和漂移由 CC/Codex 在体检时自动处理，涉及用户品味的冲突推送 Telegram 通知

---

## §8 学习机制

### 8.1 核心原则

- [§8.1] 只从成功的 Job 中学习（不学失败）
- [§8.1] 规划经验、风格偏好、对话记忆全部存入 Mem0，按需检索
- [§8.1] 不自动更新 Persona（系统级修改经 CC/Codex 审查，品味类修改经用户对话确认）
- [§8.1] 迟到反馈只影响未来，不回写改造旧 Job 结果

### 8.2 规划经验学习

- [§8.2] Job 成功后，L1 规划决策（DAG 结构、模型策略、Step 分解方式）自动存入 Mem0 procedural memory
- [§8.2] 消费路径：新任务 → Mem0 检索相关规划经验 → 注入 L1 prompt → L1 参考生成 DAG
- [§8.2] 冷启动：没有历史经验时 L1 从零规划，前 20 个成功 Job 后开始有参考价值

### 8.3 来源标记

- [§8.3] Agent 执行 Step 时注入来源标记：`[EXT:url]` / `[INT:persona]` / `[SYS:guardrails]`
- [§8.3] 标记不展示给用户，存储在 Step output 元数据中，供审计追溯

### 8.4 学习机制总结

- [§8.4] 不自建 dag_templates / project_templates → 用 Mem0 procedural memory
- [§8.4] 不自建 Extract 机制 → Langfuse 自动追踪 + Mem0 自动提取记忆候选
- [§8.4] 不自建 eval_chain → 用户反馈通过 Mem0 更新机制处理
- [§8.4] 不自建 skill_stats / agent_stats → Langfuse traces + PG 聚合

---

## §9 Skill 体系

### 9.1 Skill 结构规范

- [§9.1] 每个 SKILL.md 存放位置：`openclaw/workspace/{agent_id}/skills/{skill_name}/SKILL.md`
- [§9.1] SKILL.md 必须包含 6 个 section：适用场景、输入、执行步骤、质量标准、常见失败模式、输出格式
- [§9.1] 步骤必须可执行（"做好"不是步骤，"用 researcher 搜索 X 并提取 Y" 才是）
- [§9.1] 必须覆盖正常路径 + 已知失败模式
- [§9.1] 每个 skill 聚焦一件事，复合任务拆成多个 skill 组合

### 9.2 Skill 粒度原则

- [§9.2] 合适粒度：一个 Step 内可以完整执行
- [§9.2] 太粗（禁止）：需要多个 agent 协作（那是 Job，不是 skill）
- [§9.2] 太细（禁止）：只是一次工具调用（写 TOOLS.md 即可）
- [§9.2] 同一 agent 的多个 skill 应该可组合

#### 9.2.1 L1 与 skill 的关系

- [§9.2.1] FINAL：L1 不感知 skill，只指定 goal + agent
- [§9.2.1] skill 匹配在 agent 侧：session 启动时 TOOLS.md 列出可用 skill，agent 根据目标自行匹配

### 9.3 各 Agent Skill 域

- [§9.3] L1（共享）：规划、任务分解、Replan 判断、用户意图解析
- [§9.3] researcher：搜索策略、信息提取、深度分析、推理框架、Knowledge Base 管理
- [§9.3] engineer：编码规范、调试流程、技术决策
- [§9.3] writer：写作结构、风格适配、格式规范
- [§9.3] reviewer：审查维度、评分标准
- [§9.3] publisher：各平台发布规范、格式要求
- [§9.3] admin：系统诊断、体检流程、skill 评估方法

### 9.4 Skill 生命周期

- [§9.4] Phase 5：researcher 搜索前沿 → engineer 改写为 SKILL.md → 每 agent ≥ 3-5 个核心 skill 草稿
- [§9.4] 暖机 Stage 3：用真实任务跑 → Langfuse 观察 → 不达标则修改重跑迭代
- [§9.4] 生产使用：Langfuse 持续监控 → 定位 skill 问题 → 修改 SKILL.md → 下一个 session 立即生效
- [§9.4] 迭代：外部最佳实践更新 → researcher 定期重扫 → engineer 适配 → 更新 skill

### 9.5 暖机前 Skill 准备

- [§9.5] 暖机前 skill 必须是"有内容的草稿"，不能是空白文件
- [§9.5] FINAL：先看前沿，再设计 Skill — 每个 skill 设计必须先由 researcher 搜索最新研究和最佳实践
- [§9.5] 准备流程：确定需要哪些 skill → researcher 搜索 → engineer 编写 → CC/Codex 审查 → 进入暖机验证

### 9.6 Skill 与 Token 效率

- [§9.6] FINAL：Skill 质量是 token 效率最大的单一决定因素

### 9.7 Skill 更新规则

- [§9.7] Skill 文件纳入 git 管理，修改有 commit 记录
- [§9.7] 修改 skill 不需要重启服务，下一个 session spawn 时自动加载新版本
- [§9.7] 所有 skill 修改必须经 CC/Codex 审查（不自动更新）
- [§9.7] 更新流程：admin/engineer 提案 → CC/Codex 审查 → commit → 下一 session 生效
- [§9.7] Langfuse 中 skill 相关 Step token 超标或失败率 > 20% 时触发 skill 审查
- [§9.7] 涉及用户品味的 skill 调整经用户确认后由 CC 执行

### 9.8 Skill 与 execution_type 的关系

- [§9.8] agent：OC session 加载 workspace 下 skills/ 目录，agent 自行匹配
- [§9.8] claude_code/codex：Temporal Activity 注入 MEMORY.md 和相关 skill 内容到 prompt
- [§9.8] direct：无 LLM，不需要 skill

### 9.9 Skill 持续演进

- [§9.9] FINAL：Skill 是随前沿研究持续演进的活文档
- [§9.9] 性能驱动（被动）：Langfuse 监测失败率 > 20% 或 token 异常上升 → 触发更新
- [§9.9] 前沿驱动（主动）：每周体检 researcher 搜索最新成果 → admin 对比 → 识别可改进之处
- [§9.9] 更新流程：researcher 搜索 → admin 评估差距 → engineer 起草 → CC/Codex 审查 → commit → 下周验证
- [§9.9] 约束：每次只更新 1-2 个 skill
- [§9.9] 约束：更新前后必须有 Langfuse 可量化对比基线
- [§9.9] 约束：更新后指标恶化 → CC 自动 revert 并记录失败原因到 Mem0

### 9.10 方法论必须落地到 OC 配置

- [§9.10] FINAL：设计文档中所有对 agent 行为的方法论要求必须编码到对应 agent 的 OC 配置中

#### 9.10.1 两层方法论架构

- [§9.10.1] 哲学层（SOUL.md）：价值取向、认知原则、审美标准 — general 共享 + agent 专属
- [§9.10.1] 行为层（SKILL.md）：执行策略、判断标准、具体步骤 — agent 专属
- [§9.10.1] AGENTS.md 保留为通用行为规范；TOOLS.md 保留为工具清单 + 约定
- [§9.10.1] FINAL：哲学层必须可操作化（"追求真实"不够，要"事实必须有来源，推测必须标明是推测"）
- [§9.10.1] general 哲学（所有 agent 共享 SOUL.md）：认知诚实、先看前沿再行动、最小必要行动、质量 > 速度
- [§9.10.1] agent 专属哲学清单：
  - L1 copilot：规划审慎性（宁可少做不可乱做）
  - L1 mentor/coach/operator：各场景侧重不同，共享规划审慎性
  - researcher：知识可靠性（多源交叉验证、标注置信度）
  - engineer：工程简洁性（最简实现、可读性优先）
  - writer：写作真实性（准确表达，风格服务于内容）
  - reviewer：评判公正性（基于标准非偏好，给可行改进建议）
  - publisher：传播负责任（发出去的代表用户）
  - admin：维护谨慎性（先诊断再动手，小改动优于大重构）

#### 9.10.2 各 agent 行为层方法论清单

- [§9.10.2] L1（4 场景共享）：Routing Decision 判断、DAG 规划策略、Re-run 最小化重做范围、Replan Gate 判断、requires_review 判断、rerun 意图判断、用户意图解析
- [§9.10.2] researcher：搜索策略（何时停止、多源交叉验证、source_tier 判断）、分析框架（结构化整理）、前沿扫描方法论
- [§9.10.2] engineer：编码方法论（架构选择、测试策略、质量标准）、CC/Codex handoff 上下文准备
- [§9.10.2] writer：写作方法论（结构设计、风格适配、自迭代策略）、多格式输出选择逻辑、Persona 风格应用方式
- [§9.10.2] reviewer：审查方法论（评分维度、通过/不通过判断标准）、rework 反馈格式、不同任务类型审查侧重
- [§9.10.2] publisher：平台适配方法论（不同平台格式/长度/风格）、发布前检查清单、用户确认触发判断
- [§9.10.2] admin：诊断方法论（指标异常→根因推理）、体检流程执行方式、自愈判断（何时自修/何时升级 CC）

#### 9.10.3 方法论设计原则

- [§9.10.3] FINAL：绝不在没有知识基础的情况下设计方法论，绝不重复造轮子
- [§9.10.3] 流程：researcher 搜索前沿 → 基于外部知识编写 → CC/Codex 审查
- [§9.10.3] 参考领域：L1→agent orchestration/HTN planning/LLMCompiler；researcher→信息检索/系统综述方法学；writer→写作理论/修辞学；reviewer→代码审查/同行评审/rubric 设计；admin→故障诊断学/SRE 实践

#### 9.10.4 方法论持续演进

- [§9.10.4] FINAL：每周体检前沿扫描覆盖 SOUL.md + SKILL.md（不只 skill）
- [§9.10.4] 哲学层演进比行为层更慎重（需更强证据，CC 评估对整体一致性的影响）
- [§9.10.4] 两层演进遵循 §9.9 约束（每次 1-2 项、Langfuse 基线对比、恶化自动 revert）

---

## §10 禁止事项与边界（CHECKLIST）

### 10.1 架构与对象模型

- [§10.1] PROHIBITION: Job 不可兼任任务本体（Job 是 Task 的执行实例，不是 Task 本身）
- [§10.2] PROHIBITION: 前端不可各自维护一套对象规则（统一用 Plane）
- [§10.3] PROHIBITION: 不可维护并列多套正式任务类型（只有 Project / Task / Job 三层）
- [§10.4] PROHIBITION: Draft 不可作为 daemon 自管独立对象（用 Plane DraftIssue）
- [§10.5] PROHIBITION: Trigger 不可作为一等实体（降级为 Plane IssueRelation + Temporal Schedule 组合）
- [§10.6] PROHIBITION: 不可使用复杂度分级（errand/charge/endeavor 已删除，L1 自行判断）
- [§10.7] PROHIBITION: 不可使用 Memory/Lore 向量知识库（用 Mem0 替代）

### 10.2 执行模型

- [§10.8] PROHIBITION: 不可将同 agent 并行 Step 合并为复合指令（每个 Step 独立 session）
- [§10.9] PROHIBITION: Project 晋升不可由 step count 超过 dag_budget 触发（L1 routing decision 时直接决定）
- [§10.10] PROHIBITION: 不可使用 `job_completed` 事件触发下游（使用 `job_closed` 经 Replan Gate）
- [§10.11] PROHIBITION: 不可使用 settling 窗口 + 超时自动关闭（默认 no-wait，需审查时用 requires_review）
- [§10.12] PROHIBITION: 1 Step 不等于 1 Agent + 1 交付物（1 Step = 1 目标，可调用任意 agent/tool）
- [§10.13] PROHIBITION: Task DAG 不可视为不可变（Replan Gate 允许动态修改未执行 Task）
- [§10.14] PROHIBITION: Task 不可晋升为 Project（L1 在 routing decision 时直接决定类型）
- [§10.15] PROHIBITION: agent 角色不可与模型死绑定（L1 动态指定 agent + 可选 model override）

### 10.3 Skill 与学习

- [§10.16] PROHIBITION: L1 不可知道 agent 有哪些 skill（L1 只指定 goal + agent）
- [§10.17] PROHIBITION: Skill 不可自动更新（所有修改必须经 CC/Codex 审查）
- [§10.18] PROHIBITION: 不可自建 Extract 机制（用 Langfuse + Mem0 替代）
- [§10.19] PROHIBITION: 不可自建 dag_templates / project_templates 表（用 Mem0）
- [§10.20] PROHIBITION: 不可自建 Ledger 统计表（用 Langfuse traces + PG 聚合）
- [§10.21] PROHIBITION: Persona 不可自动修改（系统级经 CC/Codex 审查，品味相关经用户确认）

### 10.4 规则与安全

- [§10.22] PROHIBITION: Instinct 规则执行不可依赖 LLM 遵守 prompt（用 NeMo Guardrails 在 LLM 调用前/后拦截）
- [§10.23] PROHIBITION: 不可假设用户行为总是善意的（NeMo Guardrails 检查所有输入）
- [§10.24] PROHIBITION: 不可用规则/关键词分类任务复杂度（L1 自行判断，不硬编码）

### 10.5 界面与交互

- [§10.25] PROHIBITION: 不可存在独立评价表单/UI（反馈通过 Task page 对话框处理）
- [§10.26] PROHIBITION: 调整和评价不可作为两种不同对话类型（统一为交互行为）
- [§10.27] PROHIBITION: Slash command 不可作为对话框正式入口（自然语言对话为唯一入口）
- [§10.28] PROHIBITION: 同一 Task 不可同时具有多种触发类型（触发方式互斥）
- [§10.29] PROHIBITION: Trigger 排序不可视为建议性的（不存在排序概念，触发即执行）
- [§10.30] PROHIBITION: Task 和 Job 不可各有独立对话框（反馈统一在 Task 活动流处理）
- [§10.31] PROHIBITION: 用户不可需要通过按钮操作系统（所有操作通过对话完成）
- [§10.32] PROHIBITION: 信息提取不可由按钮触发（信息提取是 Step 行为，非 UI 操作）
- [§10.33] PROHIBITION: 用户不可直接使用 Plane（Plane 是后端数据层，用户界面是自建桌面客户端）
- [§10.34] PROHIBITION: requires_review 不可阻塞 Job 等待用户（非阻塞对话确认，系统级审查由 CC/Codex 执行）

### 10.6 基础设施

- [§10.35] PROHIBITION: Herald 不可作为独立通知服务（publisher 通过 OC Telegram channel）
- [§10.36] PROHIBITION: Spine routines 不可维护系统（1 个定时清理 Job 替代 7 个 routines）
- [§10.37] PROHIBITION: 不可使用自造隐喻术语（Psyche/Instinct/Voice/Rations 等全部替换为业界通用术语）

### 10.7 实现红线（编码时绝对禁止）

- [§10.38] PROHIBITION: 不可在 subagent 中读写 memory（subagent 不加载 MEMORY.md，无 memory_write tool）
- [§10.39] PROHIBITION: 不可用 LLM 做可以用规则/SQL 完成的事（admin 诊断用 PG 查询，不用 LLM 分析）
- [§10.40] PROHIBITION: 不可跳过 NeMo Guardrails 直接调用 LLM（所有 Step 的 LLM 调用都必须过 Guardrails）
- [§10.41] PROHIBITION: 不可在 Step 之间传递 session 历史（1 Step = 1 Session，独立不共享）
- [§10.42] PROHIBITION: 不可有不标 source marker 的 Step output（所有外部引用必须标 `[EXT:url]`）
- [§10.43] PROHIBITION: 不可有没有 Langfuse trace 的 LLM 调用（所有 LLM 调用必须在 Langfuse 可追溯）
- [§10.44] PROHIBITION: Plane 写回失败时不可静默忽略（必须进入补偿队列重试）
- [§10.45] PROHIBITION: 不可硬编码模型 ID（模型映射在 config 中管理，L1 指定 agent + 可选 model_hint）

---

## REFERENCE 附录 B-I 可实现需求

### 附录 B：运行时参数默认值

#### B.1 Temporal / Step 时间参数

- [B.1] Step timeout（search 类）= 60s，`runTimeoutSeconds`
- [B.1] Step timeout（writing 类）= 180s，`runTimeoutSeconds`
- [B.1] Step timeout（review 类）= 90s，`runTimeoutSeconds`
- [B.1] Job Workflow execution_timeout = 暖机时校准
- [B.1] Step Activity schedule_to_close_timeout = 暖机时校准
- [B.1] Step Activity start_to_close_timeout = 暖机时校准
- [B.1] RetryPolicy initial_interval = 1s
- [B.1] RetryPolicy backoff_coefficient = 2.0
- [B.1] RetryPolicy maximum_interval = 60s
- [B.1] RetryPolicy maximum_attempts = 3
- [B.1] Temporal Schedule timezone = UTC
- [B.1] Temporal Schedule jitter_window = 60s
- [B.1] Temporal Schedule catch_up_window = 1h

#### B.2 OC / Session 参数

- [B.2] maxSpawnDepth = 2（orchestrator 模式）
- [B.2] maxChildrenPerAgent = 5
- [B.2] maxConcurrent = 8（全局并发 session 上限）
- [B.2] contextPruning cache-ttl = 5 min
- [B.2] MEMORY.md 上限 ≤ 300 tokens
- [B.2] Session 固定 overhead 上限 ≤ 800 tokens（MEMORY.md + Mem0 + Step 指令）

#### B.3 Mem0 参数

- [B.3] 单次检索上限 = 5 条（暖机后可调）
- [B.3] 记忆清理阈值 = 90 天未触发（标记候选，用户确认后删除）
- [B.3] agent_id 枚举 = copilot / mentor / coach / operator / researcher / engineer / writer / reviewer / publisher / admin / user_persona

#### B.4 Plane 回写参数

- [B.4] 回写重试次数 = 5（指数退避）
- [B.4] 回写失败标记字段 = `plane_sync_failed`

#### B.5 知识层参数

- [B.5] knowledge_cache TTL Tier A = 90 天（arxiv、官方文档）
- [B.5] knowledge_cache TTL Tier B = 30 天（Wikipedia、MDN）
- [B.5] knowledge_cache TTL Tier C = 7 天（Reddit、匿名来源）
- [B.5] 检索偏置 = 先 project_id 再全局

#### B.6 体检与告警阈值

- [B.6] reviewer 通过率告警 < 80%（YELLOW/RED）
- [B.6] Skill token 超标告警 > baseline 150%
- [B.6] 伪人度评分告警 < 4/5
- [B.6] Skill 失败率审查线 > 20%
- [B.6] 体检周期 = 每周（Temporal Schedule）

### 附录 C：PG 表结构

- [C.1] 实现 `daemon_tasks` 表（task_id, plane_issue_id, project_id, trigger_type, schedule_id, chain_source_task_id, dag, timestamps）
- [C.2] 实现 `jobs` 表（job_id, task_id, workflow_id, status, sub_status, is_ephemeral, requires_review, dag_snapshot, plane_sync_failed, timestamps）
- [C.3] 实现 `job_steps` 表（step_id, job_id, step_index, goal, agent_id, execution_type, model_hint, depends_on, status, skill_used, input_artifacts, token_used, timestamps, error_message）
- [C.4] 实现 `job_artifacts` 表（artifact_id, job_id, step_id, artifact_type, title, summary, minio_path, mime_type, size_bytes, source_markers, timestamp）
- [C.5] 实现 `knowledge_cache` 表（cache_id, source_url, source_tier, project_id, title, content_summary, ragflow_doc_id, embedding vector(1024), expires_at, timestamp）+ ivfflat 索引
- [C.6] 实现 `event_log` 表（event_id, channel, event_type, payload, consumed_at, timestamp）+ 未消费事件索引
- [C.7] 实现 `conversation_messages` 表（message_id, scene, role, content, token_count, timestamp）
- [C.8] 实现 `conversation_digests` 表（digest_id, scene, time_range_start/end, summary, token_count, source_message_count, timestamp）
- [C.9] 实现 `conversation_decisions` 表（decision_id, scene, decision_type, content, context_summary, timestamp）

### 附录 D：接口契约与事件定义

#### D.1 daemon API 端点

- [D.1] POST `/scenes/{scene}/chat` — 场景对话输入
- [D.1] GET `/scenes/{scene}/chat/stream` — WebSocket 场景实时对话流（双向）
- [D.1] GET `/scenes/{scene}/panel` — 场景面板数据
- [D.1] GET `/tasks/{task_id}/activity` — Task 活动流
- [D.1] GET `/artifacts/{artifact_id}` — Artifact 内容
- [D.1] GET `/artifacts/{artifact_id}/download` — Artifact 下载
- [D.1] GET `/status` — 系统整体状态
- [D.1] POST `/auth/login` — 远程访问登录
- [D.1] POST `/webhooks/plane` — Plane webhook handler（签名验证）
- [D.1] 操作类动作（pause/resume/cancel/review）不再有独立端点，通过 `/scenes/{scene}/chat` 自然语言 → L1 解析 → Temporal Signal

#### D.2 Temporal Signal 枚举

- [D.2] 实现 `pause_job` Signal（L1 触发，Job → running/paused）
- [D.2] 实现 `resume_job` Signal（L1 触发，paused → running/executing）
- [D.2] 实现 `cancel_job` Signal（L1/admin 触发，Job → closed/cancelled）
- [D.2] 实现 `confirmation_received` Signal（L1 触发，pending_confirmation → 继续执行）
- [D.2] 实现 `confirmation_rejected` Signal（L1 触发，pending_confirmation → rework/terminate）

#### D.3 PG NOTIFY Channel

- [D.3] `job_events` channel：job_created, job_closed, job_paused → daemon API（WebSocket → 客户端）
- [D.3] `step_events` channel：step_started, step_completed, step_failed, step_pending_confirmation → daemon API
- [D.3] `webhook_events` channel：plane_webhook_received → daemon Worker
- [D.3] `system_events` channel：health_check_completed, schedule_fired → daemon Worker

#### D.4 活动流记录格式

- [D.4] 活动流记录字段：id, task_id, job_id, type, scene, content, actor, timestamp, metadata
- [D.4] type 枚举：user_message / agent_result / job_boundary / step_status / action_record
- [D.4] FINAL：所有用户对话和 daemon 回复写入活动流
- [D.4] FINAL：系统操作写入活动流，type = "action_record"
- [D.4] FINAL：每条记录显式携带 job_id

#### D.5 Job 状态 → Plane Issue 状态映射

- [D.5] running/queued|executing|retrying → Plane "started"
- [D.5] running/paused → Plane "started"（保持）
- [D.5] closed/succeeded → Plane "completed"
- [D.5] closed/failed → Plane "started"（不自动标完成）
- [D.5] closed/cancelled → Plane "cancelled"

#### D.6 废弃术语映射表

- [D.6] 代码中搜索并替换所有旧术语：folio→project, slip→task, writ→删除, deed→job, move→step, offering→artifact, psyche→persona/guardrails, instinct→guardrails, rations→quota, ledger→删除, herald→删除, cadence→删除, ether→删除, trail→删除, scout/sage/scholar→researcher, counsel→L1, artificer→engineer, scribe→writer, arbiter→reviewer, envoy→publisher, steward→admin

### 附录 E：DEFAULT 条目（仍有效，未升级为 FINAL）

- [E/D-01] 模型名称和 provider 绑定配置化，不硬编码到厂商 SKU
- [E/D-06] Replan Gate 输出格式：`operations[]` diff（add / remove / update / reorder）
- [E/D-12] Mem0 单次检索上限 = 5 条
- [E/D-14] Quota 阈值 = 保守默认值，暖机后校准
- [E/D-21] 备份保留策略：增量备份，90 天滚动，每日一次
- [E/D-22] 数据生命周期：Ephemeral 7d / Regular 30→90d / Artifact 本地 30d + Google Drive 永久 / event_log 7d / traces 90d
- [E/D-24] 对话流传输方案：WebSocket 或 SSE + POST（实现阶段决定）
- [E/D-27] OAuth 实现：FastAPI + authlib 或 python-social-auth，Google + GitHub provider

### 附录 F：UNRESOLVED 条目

- [F] 当前无 UNRESOLVED 条目（全部已解决）

### 附录 G-H：Gap 覆盖

- [G] 870 条 Gap（G-1 至 G-13）已在七稿中覆盖，完整注册表在 `.ref/_work/GAPS.md`
- [G] 实现每个模块前应查阅对应 Gap 组

### 附录 I：设计决策日志

- [I] 67 条设计决策（DD-01 至 DD-67），全部 FINAL 或 DEFAULT
- [I] 实现时如遇设计疑问，先查决策日志确认理由
- [I/DD-58] DEFAULT：多用户扩展路径 — 所有表预留 user_id，基础设施按需扩展，不本轮实现
