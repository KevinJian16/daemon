# 旧版 80 条覆盖核查报告

> 核查范围：原 GAPS.md 初稿中的旧版 80 条条目（现已移入本文附录）
> 参照文档：SYSTEM_DESIGN.md（四稿，唯一权威文档）
> 参照文档：SYSTEM_DESIGN.md（四稿，唯一权威文档）

## 核查结果汇总

- ✅ 已覆盖: 45 条
- ⚠ 部分覆盖: 18 条
- ❌ 未覆盖: 17 条

---

## 逐条核查

---

### 一、执行模型类

#### 1.1 Step 与 Session

**条目1** [EXECUTION_MODEL §2.2] → §3.2
DAG 快照细节：Task DAG 在 Job 创建时冻结，首次执行 counsel 从 Task 对话生成 DAG；后续执行基于同一 Task 生成新 Job；用户修改 DAG 只在下一个 Job 创建时生效
**判定**: ⚠ PARTIAL — §3.3 写了"Step DAG 在 Job 创建时快照，Task DAG 变更不影响进行中的 Job"，§3.5.2 写了"新 Job 基于最新信息全新规划"，但**首次执行 counsel 从哪里读取输入（Task 描述 + 对话历史）来生成初始 DAG** 未明确，counsel 在 Routing Decision 时创建 Task 后如何进入 Job 创建也不完全清晰。

**条目2** [EXECUTION_MODEL §2.3] → §3.2
session_seq 是否仍需要：1 Step = 1 Session 后，step_id 已唯一标识，session_seq 概念已废
**判定**: ✅ COVERED — §3.2 明确"Session key 格式：{agent_id}:{job_id}:{step_id}"，step_id 唯一确定。session_seq 不再出现，隐含废除。

**条目3** [EXECUTION_MODEL §7.1] → §3.7
Rework session 处理：替换 Step 的新 session 全新 context，arbiter 反馈以结构化 Artifact 方式传入新 Step 的 input，不保留原 context
**判定**: ⚠ PARTIAL — §3.7 写了 Step 失败后 counsel 可"替换 Step（换一种方式达成同目标）"，但**arbiter 反馈作为结构化 Artifact 传入替换 Step 的 input** 这一具体机制未明确写出。

**条目4** [EXECUTION_MODEL §2.4] → §5.6
counsel 规划对话 ≠ OC session：Plane Activity 与 counsel 的 OC session 是独立概念，两者不等同
**判定**: ✅ COVERED — §5.6.1 明确"Task 只有一条对话流（Plane Issue Activity）"，§3.2 明确"1 Step = 1 Session"，session 生命周期 = Step 级别。两者独立是架构基础，全文贯穿。

**条目5** [DESIGN_QA §Q12.6] → §3.3
DAG 快照的确切时机（三种情形：首次执行、用户对话修改、新 Job 执行）
**判定**: ⚠ PARTIAL — §3.3 写了"Step DAG 在 Job 创建时快照，Task DAG 变更不影响进行中的 Job"，§3.5.2 覆盖了"基于最新信息全新规划"，但三种情形的完整枚举（尤其是"用户修改 DAG 只在下一个 Job 创建时生效"）未单独列出。

**条目6** [DESIGN_QA §Q6.5] → §3.3
"再执行一次"的语义：基于同一个 Task 生成新的 Job，不是克隆新的 Task
**判定**: ✅ COVERED — §3.3 "创建 Job（= 原子操作：创建 + 立即执行）"，§3.5.2 "同一 Task 多次执行（re-run、失败重试、定期重跑）时，counsel 规划新 Job"，语义明确。

**条目7** [DESIGN_QA §Q11.2] → §3.2
并行 Step session 规则：同 Job 内不同 agent 的并行 Step 各自独立 session；同一 agent 的并行 Step 各自独立 session
**判定**: ✅ COVERED — §3.2 明确"并行 Step 各自独立 session，同时运行"，§3.2 Session key 包含 step_id 保证唯一性，同 agent 天然隔离（不同 step_id）。

---

#### 1.2 Direct Step

**条目8** [EXECUTION_MODEL §3.3] → §3.1
Direct Step 的判定标准细化：确定性≈不需要自然语言推理；示例 direct（文件读写、API 调用、格式转换等）；示例 agent（分析、写作、代码生成等）
**判定**: ✅ COVERED — §3.1 列出了 direct step 的完整覆盖范围（Shell 命令、文件读写、API 调用等），"规则三：确定性操作用 direct，不用 agent"。

**条目9** [EXECUTION_MODEL §3.3] → §3.7
Direct Step 失败处理：MCP server 不可用时 Temporal RetryPolicy 自动重试；重试耗尽 Step 标记 failed；不触发 agent 会话
**判定**: ✅ COVERED — §3.7 写了"Retry：Temporal RetryPolicy（已有机制），自动重试"，Step 失败后 counsel 判断，全机制覆盖 direct 和 agent step。

---

#### 1.3 Routing Decision

**条目10** [EXECUTION_MODEL §（无）] → §3.8
counsel 通过 MCP tool 调用 Plane API 创建 Task/Project；不是 Worker Activity 直接创建
**判定**: ❌ MISSING — §3.8 写了 routing decision 的输出格式和三条路径，但**谁负责实际创建 Plane 对象（counsel MCP 还是 Worker Activity）** 没有明确写出。这是执行责任归属问题，SYSTEM_DESIGN.md 中无定论。

**条目11** [EXECUTION_MODEL §（无）] → §3.8
route: "direct" 的执行方式：跳过 Project/Task 对象创建；counsel 直接创建一个临时 Job（无 Task 归属）；Job 执行完即丢弃，不持久化 Task
**判定**: ⚠ PARTIAL — §3.8 table 写了 `direct` = "跳过 Project/Task，直接创建单 Step Job"，但**"无 Task 归属""不持久化""执行完丢弃"** 这些关键约束未明确写出。

---

#### 1.4 Replan Gate

**条目12** [EXECUTION_MODEL §（无）] → §3.5
Replan Gate 触发职责：由 Temporal Workflow Activity 自动触发（在 chain trigger activity 前执行）；不是人工触发；偏离判定由 counsel 自动完成（analysis 模型）
**判定**: ✅ COVERED — §3.5 写了"实现位置：Temporal activity，在 chain trigger activity 前执行"，"Replan Gate 使用 analysis 模型"，自动触发逻辑清晰。

**条目13** [EXECUTION_MODEL §（无）] → §3.5
Replan 输出格式：diff（JSON patch 格式，对未执行 Task 列表的增删改）；不是全新 Task DAG；已完成的 Task 不变，已完成的 Artifact 自动写入新规划的上下文
**判定**: ⚠ PARTIAL — §3.5 写了"输出新的 Task DAG（diff，不是全新计划）""替换 Project 中尚未执行的 Task""已完成的 Task 不变"，但**具体是 JSON patch 格式**以及**已完成 Artifact 自动写入新规划上下文的机制**未明确。§3.5.1 写了"当前 Job 结果（Artifact 摘要，仅 Replan Gate）"，部分覆盖。

---

#### 1.5 Task 触发与依赖

**条目14** [DESIGN_QA §Q8.4-Q8.5] → §3.4
触发类型互斥的强制约束：数据模型层保证互斥；UI 层选择时三者互斥；不允许"手动 + 定时"同时存在
**判定**: ✅ COVERED — §3.4 "触发类型互斥——一个 Task 只有一种"，§11 禁止事项第 13 条"同一个 Task 可以同时具有多种触发类型"。

**条目15** [DESIGN_QA §Q3.7] → §3.4
定时任务的正确模式：一个 standing Task + Temporal Schedule + 多次 Job；禁止一个 Job 永久运行
**判定**: ✅ COVERED — §3.4 "timer：定时（Temporal Schedule）"，§11 禁止事项第 6 条 + §1.7 "Temporal Schedule 替代 Cadence"。§3.3 明确 Job 是有限期的 Temporal Workflow。

**条目16** [DESIGN_QA §Q8.3] → §3.4
触发的统一事件论：所有触发本质都是事件；事件源清单（time.tick / job.closed / user.manual）；统一由 Temporal Activity 处理
**判定**: ⚠ PARTIAL — §3.4 列出了三种触发类型（manual/timer/chain），§3.5 写了"Replan Gate"和 chain trigger，但**"本质都是事件，事件源清单"** 的统一抽象没有明确表达。

---

### 二、Session 与 Token 管控类

**条目17** [EXECUTION_MODEL §6.1] → §3.2
选择性注入规则（按 agent 角色差异化）：各 agent Mem0 检索量不同；direct step 完全不注入 Mem0
**判定**: ✅ COVERED — §4.8 "Mem0 按需注入"按 agent 分列检索 query 和约 token 量，§3.2 "Mem0 按需检索（50-200 tokens/次）"。direct step 零 LLM 故无注入，逻辑上覆盖。

**条目18** [EXECUTION_MODEL §6.3] → §4.8
planning_hints 的替代：旧架构 Ledger 统计摘要 → 新架构 Mem0 按需检索规划经验；检索结果直接注入 counsel session；不需要独立的 planning_hints 概念
**判定**: ✅ COVERED — §4.8 counsel 行，§8.2 "规划经验（历史 DAG 模式）存入 Mem0，counsel 按需检索"，§1.5 "Ledger → 删"。planning_hints 概念已删除。

**条目19** [EXECUTION_MODEL §（无）] → §3.2
token 管控优先级顺序：runTimeoutSeconds 最优先 → OC contextPruning → OC quota → Langfuse 监控告警
**判定**: ✅ COVERED — §3.2 Token 管控机制表格中列出了所有四项机制，其中 `runTimeoutSeconds` 排第一，描述为"硬超时，防止 agent 无限循环"，其余依次列出。

**条目20** [EXECUTION_MODEL §（无）] → §3.2
MEMORY.md 内容规范：禁止任务偏好/风格描述/历史经验/规划提示；允许身份定位 + 最高规则；与 guardrails.md 的区分
**判定**: ✅ COVERED — §3.2 "MEMORY.md 规则：每个 agent 的 MEMORY.md ≤ 300 tokens。只放：身份定义 + 最高优先级行为规则。任务偏好、风格、规划经验全部放 Mem0，不放 MEMORY.md"。与 guardrails.md 区分隐含在 §4.2 vs §3.2 的分节中，但未显式对比。

**条目21** [EXECUTION_MODEL §（无）] → §3.2
session 创建/销毁时机：创建=Temporal Activity 开始执行该 Step 时（sessions_spawn）；销毁=Step 完成后（sessions_close 或 TTL）；不跨 Step/Job 保留
**判定**: ✅ COVERED — §3.2 "每个 Step 执行时 sessions_spawn 创建独立 session，Step 完成后关闭"，"不积累前序 Step 的对话历史"。

**条目22** [EXECUTION_MODEL §（无）] → §3.2
Mem0 检索 vs OC session-memory hook 的关系：Mem0 在 session 创建前执行，结果注入首条消息；OC hook 仅在 /new 或 /reset 时触发；两套机制不冲突
**判定**: ✅ COVERED — §3.2 "OC 限制：Session-memory hook 仅在 /new 或 /reset 时触发"，Mem0 的注入在 §4.3.3 代码示例中表示"Step 执行前"检索。两套独立关系描述到位。

---

### 三、交互设计类

#### 3.1 按钮行为

**条目23** [INTERACTION_DESIGN §2.3] → §5.2
"执行"按钮原子性：执行=创建 Job + 立即运行；不存在"只创建 Job 不运行"；按钮 disabled 条件=Task 已有 running Job
**判定**: ✅ COVERED — §3.3 "创建 Job（= 原子操作：创建 + 立即执行）"，§3.3 "同一 Task 同一时刻只有一个非 closed 的 Job"，§5.2 "执行：创建 Job + 立即运行，原子操作"。

**条目24** [INTERACTION_DESIGN §2.3.1] → §5.3
Job 执行期间的按钮规则：开始/停止 toggle；多次开始/停止不创建新 Job；running 期间用户发消息不暂停执行
**判定**: ✅ COVERED — §5.3 "按钮：开始/停止（toggle）"，§5.6.3 "Job closed 后用户可在 Task 对话流中给出反馈"（隐含 running 期间对话不暂停）。但"多次开始/停止不创建新 Job"未显式写出，属于隐含。

**条目25** [INTERACTION_DESIGN §2.11] → §5.4
Project 结构视图中 Task 内联操作规则：有 running Job 时按钮变为"执行中"（disabled）；依赖未满足时 disabled；定时触发时显示下次时间无执行按钮
**判定**: ⚠ PARTIAL — §5.4 写了"Project 结构视图中，每个 Task 旁带内联操作区（按触发类型显示）"，§5.2 写了按触发类型的三种显示方式（含"定时触发：定时设置信息"），但**"有 running Job 时按钮变为 disabled"** 和**"依赖未满足时 disabled"** 的具体状态文字没有写出。

**条目26** [INTERACTION_DESIGN §2.7.1] → §5.6.2
按钮-对话等价的完整机制：按钮点击在活动流生成等价自然语言记录（role: system, event: operation）；counsel 处理对话和按钮走同一逻辑；按钮的独特作用是回溯定义边界
**判定**: ⚠ PARTIAL — §5.6.2 写了"所有非对话操作在活动流中生成自然语言记录"，§11 禁止事项第 16 条"按钮和对话是不同控制通道"。但**"role: system, event: operation"** 消息格式、**"回溯定义边界"** 的作用没有明确写出。

**条目27** [INTERACTION_DESIGN §2.7.2] → §5.6
操作记录消息格式：role: "system", event: "operation"；淡色标签样式渲染
**判定**: ❌ MISSING — §5.6.2 仅说"生成自然语言记录"，没有定义消息的 role/event 格式，也没有渲染样式规范。

---

#### 3.2 Task 页面结构

**条目28** [INTERACTION_DESIGN §2.3] → §5.2
Task 页面五个必须组件：标题区、plan card、统一活动流、内嵌 Job 执行块、底部输入区；plan card = DAG 可视化卡片
**判定**: ⚠ PARTIAL — §5.2 写了"Task 页面内容"包含：Issue 标题和描述、DAG/plan card、活动流、Job 执行块、动作区，共五项，与条目吻合。但**"plan card 必须有，不允许消失"** 和**"底部输入区始终可用"** 的强制性约束没有明确表达。

**条目29** [INTERACTION_DESIGN §2.3.2] → §5.3
Job 执行块冻结规则：Job closed 后执行块冻结为只读；过去 Job 执行块有保质期，过期视觉淡化；保质期待定
**判定**: ⚠ PARTIAL — §5.3 写了"Job closed 后：执行块冻结为只读（Artifact 标签 + 执行摘要）"，但**"过期从活动流淡出"**（视觉淡化，非删除）和**"保质期待暖机校准"** 未写出。

**条目30** [INTERACTION_DESIGN §2.5-2.6] → §5.2
plan card 强制性规则：每个 Task 必须有 plan card；不允许因任务轻重不同变成不同 UI 物种
**判定**: ❌ MISSING — §5.2 写了"DAG/plan card（Plane Issue 的 custom property 或 description 区域）"，但没有表达"每个 Task 必须有"的强制性，也没有"不允许变成不同 UI 物种"这条规则。

---

#### 3.3 Project 页面结构

**条目31** [INTERACTION_DESIGN §2.11] → §5.4
Project 页面骨架五个区域（标题/摘要、关系图、活跃 Task 列表、最近执行 Task 列表、最近 Artifact 摘要）；"打开一卷"的空间感
**判定**: ❌ MISSING — §5.4 只写了"Project 页面回答的四个问题"（what/which/active/results），没有具体定义页面骨架的五个区域，"打开一卷"的设计理念也未保留。

**条目32** [INTERACTION_DESIGN §2.7.3] → §5.7
Task 链 DAG 导航规则：线性链有上下 Task 标签；分支点有多个"下一个 Task"标签；合并点有多个"上一个 Task"标签
**判定**: ❌ MISSING — §5.7 写了"支持链内前后导航"，但没有定义具体的导航标签规则（分支/合并点的标签数量和语义）。

---

#### 3.4 对话流规则

**条目33** [INTERACTION_DESIGN §2.7.1] → §5.6.1
统一活动流的两种对话模式：无 Job 时调整 DAG；Job 运行期间执行调整和评价反馈；DAG 修改不走学习回路；Job 运行期间反馈走学习回路（Job 结束后询问是否写入 Persona）
**判定**: ✅ COVERED — §5.6.1 写了两种模式（无 Job/Job 运行期间），§5.6.3 写了"风格类反馈经用户确认后写入 Mem0"，§4.3.5 写了完整的更新机制。

**条目34** [FRONTEND_ALIGNMENT §2] → §5.2
统一活动流 API 规范：返回该 Task 下所有 Job 的合并活动流，按时间排序；每条消息带 job_id；Job 边界在活动流中可视化区分
**判定**: ❌ MISSING — §5.2 和 §5.6 描述了活动流概念，但**活动流 API 的返回格式规范（job_id 字段、时间排序、Job 边界的可视化区分）** 未写出。

**条目35** [FRONTEND_ALIGNMENT §3] → §5.6
running 期间发消息的行为：消息追加到活动流，当前 Job 执行继续（不暂停）；消息保留在活动流，Job 结束后作为反馈候选
**判定**: ✅ COVERED — §5.6.3 "Job closed 后，用户可在 Task 对话流中给出反馈"，但 running 期间发消息不暂停的规则已被 §3.3 Job 生命周期图（running 继续执行）和按钮-对话等价原则覆盖。

---

#### 3.5 Artifact 呈现

**条目36** [DESIGN_QA §Q7.1] → §5.3
Artifact 两层语义：对外版本（干净内容，Plane 活动流展示）；内部版本（含来源标记 [EXT/INT/SYS]，存 MinIO，用于审计）
**判定**: ⚠ PARTIAL — §8.3 写了来源标记（[EXT:url] / [INT:persona] / [SYS:guardrails]）用于审计追溯，"存储在 Step output 元数据中，不展示给用户"，但**两版本的存储位置（Plane 展示对外版本，MinIO 存内部版本）** 和**"Plane 活动流展示干净内容"** 没有明确分述。

**条目37** [FRONTEND_GUIDE §8.1] → §5.3
Artifact 在执行块中的呈现：Job 执行中=DAG 进度 + 实时 streaming；Job closed=Artifact 版本列表 + 最终交付物预览；"版本"=同一 Task 多次执行的列表
**判定**: ⚠ PARTIAL — §5.3 写了"执行块内容：DAG 进度（当前 Step 位置）、Artifact 版本和执行细节"，Job closed 后的冻结规则也写了。但**"streaming 实时输出"** 和**"版本 = 多次执行的列表（最新在前）"** 的展示规范没有明确表达。

---

#### 3.6 状态显示文案

**条目38** [FRONTEND_ALIGNMENT §7] → §5.9
Job 状态的正式中文显示文案（7 种状态的完整映射表）
**判定**: ❌ MISSING — §5.9 只写了"Plane 界面使用正式中文术语"，没有给出 Job 状态的中文文案对照表。§1.2 有状态定义但无中文显示名。

---

#### 3.7 Draft 交互

**条目39** [DESIGN_QA §Q3.2] → §5.5
Draft 的四种来源（对话/规则触发/外部事件/系统内部推进）；自动任务必须先经过 Draft
**判定**: ❌ MISSING — §5.5 只写了"Draft 使用 Plane DraftIssue，转换为 Task 即 DraftIssue → Issue"，没有定义四种来源，也没有"自动任务必须先经 Draft"的规则。

**条目40** [DESIGN_QA §Q3.1] → §5.5
Draft 的正式对象地位：不是临时聊天缓存；Draft → Task 的转换是有意识决策，不是自动升级
**判定**: ❌ MISSING — §5.5 未表达 Draft 的正式性，也未写明 Draft → Task 需要显式确认（非自动）。§1.1 写了 Draft 用 Plane DraftIssue，但 Draft 的地位规则不存在于 SYSTEM_DESIGN.md。

---

### 四、知识与记忆类

#### 4.1 Guardrails

**条目41** [DESIGN_QA §Q1.1.1] → §4.2
Guardrails 三层执行的代码层实现：Python pre/post check 在 NeMo 前执行；check 触发点（Quota 上限/token 预算/并发数/格式校验）
**判定**: ⚠ PARTIAL — §4.2 表格写了三层（硬规则/软规则/关键审查），每层实现方式，与条目基本吻合。但**"Python pre/post check 先执行，通过后才进入 NeMo 引擎"** 的顺序规则没有明确写出。

**条目42** [DESIGN_QA §Q1.1.2] → §4.2.1
Guardrails 作为信息门控的具体触发点：Persona 候选写入前 NeMo custom action 校验；外部知识引用前 source_tier 校验；用户反馈写入前 NeMo custom action 校验；"系统不假设用户善意"原则
**判定**: ✅ COVERED — §4.2.1 列出了三个触发点（Persona 候选写入、外部知识引用、用户反馈写入），§4.2.2 列出了 Custom action 实现，§4.2.3 guardrails.md 内容范围中体现了安全边界原则。

**条目43** [REFACTOR §3.3.1] → §4.2
NeMo 与代码层集成方式：Python 库嵌入 Worker 进程；调用方式 rails.generate(messages=[...])；自定义 action 通过 @action 装饰器注册；不需要独立服务进程
**判定**: ✅ COVERED — §4.2 "NeMo Guardrails（NVIDIA 开源，Apache 2.0）。Python 库嵌入 Worker 进程，零额外服务"，§6.2 Worker 进程包含 NeMo Guardrails。具体 API 调用方式未写但架构决定明确。

---

#### 4.2 Persona

**条目44** [daemon_实施方案 §6.2] → §4.3
Persona 文件结构（两层：初始化文件 psyche/voice/ 目录 + Mem0 动态层）；两层关系：文件层稳定基底，Mem0 动态演化
**判定**: ❌ MISSING — §4.3 描述了 Mem0 记忆类型，§4.3.4 冷启动方式，但**psyche/voice/ 目录结构（identity.md / common.md / zh.md / en.md / overlays/）** 和**"文件层 + Mem0 层双层"** 的架构没有在 SYSTEM_DESIGN.md 中写出。这是实现细节但影响部署。

**条目45** [DESIGN_QA §Q1.2] → §4.3
Persona 组件的内部三分：AI 身份和人格（semantic，agent 级）、写作风格（procedural，agent 级）、用户偏好（semantic，user 级）；用户偏好由哪个 agent 写入（counsel/scribe 在 Job 结束时确认）
**判定**: ⚠ PARTIAL — §4.3.2 写了记忆类型表（AI 身份/写作风格/用户偏好/规划经验），与三分吻合。但**"用户偏好由哪个 agent 写入（counsel/scribe 在 Job 结束时确认）"** 的责任归属没有明确写出。

**条目46** [REFACTOR §4] → §4.3.5
Persona 候选提取规则：触发时机（Job closed(succeeded) 后）；扫描活动流识别风格类反馈关键词；展示候选列表供用户勾选；确认后 NeMo custom action 校验写入 Mem0；在 Plane Issue Activity 中生成提示
**判定**: ✅ COVERED — §4.3.5 完整写出了更新机制（反馈 → 列出候选 → 用户勾选 → NeMo 校验 → 写入 Mem0），触发时机在 §5.6.3 写明"Job closed 后"。

**条目47** [DESIGN_QA §Q1.5] → §4.6.2
knowledge_cache embedding 检索策略：embedding 相似度为主；Project 级别加主题偏置（同 Project 内优先命中，无命中再全局）；偏置实现用 project_id 过滤
**判定**: ❌ MISSING — §4.6.2 描述了 knowledge_cache 表结构（有 project_id 概念？实际查看表 DDL 中没有 project_id 字段），§2.5 写了知识获取流程，但**"按 project_id 偏置检索"** 这一规则没有在 SYSTEM_DESIGN.md 中写出。knowledge_cache 表也没有 project_id 字段。

---

#### 4.3 学习机制

**条目48** [DESIGN_QA §Q1.4] → §8.2
规划经验合并规则：相似任务规划经验合并（cosine 相似度 > 0.85）；Mem0 自带去重，不需自建合并逻辑；冷启动=前 20 个成功 Job 后开始有参考价值
**判定**: ✅ COVERED — §8.2 写了"规划经验自动存入 Mem0 procedural memory"，"冷启动：前 20 个成功 Job 后开始有参考价值"，Mem0 自带去重在 §4.3.6 "Mem0 内置去重和冲突检测"。cosine 阈值 > 0.85 未写，但属于 Mem0 内部实现参数。

**条目49** [DESIGN_QA §Q1.6] → §8.2
规划经验的分级存储：Task 级别（Step DAG 结构）→ agent 级 procedural memory（counsel）；Project 级别背景信息 → 动态组装（§3.5.1），不持久化
**判定**: ✅ COVERED — §8.2 "counsel 的规划决策（DAG 结构、模型策略选择、Step 分解方式）自动存入 Mem0 procedural memory"，§3.5.1 写了项目级上下文是动态组装。两者明确区分。

**条目50** [DESIGN_QA §Q7.4] → §8
迟到反馈的语义：用户回到 Task 页面重新执行=对上次结果的隐式否定信号；不设回溯评价机制；不自动标记上次 Job 为"失败"
**判定**: ❌ MISSING — §8 未写迟到反馈的处理规则，SYSTEM_DESIGN.md 没有关于"重新执行"的语义定义。

**条目51** [DESIGN_QA §Q1.7] → §8
Task 依赖关系的版本化：不允许无声改写；正式变更必须通过 Plane UI 操作，操作记录在活动流中；Replan Gate 只能修改未执行的 Task
**判定**: ⚠ PARTIAL — §3.5 写了"Replan Gate 替换 Project 中尚未执行的 Task，已完成的 Task 不变"，但**"Task 依赖关系不允许无声改写，必须通过 Plane UI，记录在活动流"** 的规则没有明确写出。

---

### 五、基础设施类

#### 5.1 MCP 工具管理

**条目52** [EXECUTION_MODEL §3.4] → §6.3
MCP server 连接生命周期：进程级别持久化，不每次重连；首次连接构建 tool_name → server 路由表；每次 call_tool 带 asyncio.wait_for；故障恢复链路
**判定**: ❌ MISSING — §6.3 写了"MCP 分发：runtime/mcp_dispatch.py + config/mcp_servers.json"，但**连接生命周期、路由表构建、超时防护、故障恢复** 这些运行时细节没有写出。

**条目53** [EXECUTION_MODEL §3.4] → §6.7
mcp_servers.json 配置规范：env 中 ${VAR} 展开为环境变量；示例配置格式
**判定**: ⚠ PARTIAL — §6.7 "mcp_servers.json → config/mcp_servers.json → MCP server 注册"，但配置格式规范（${VAR} 展开规则、示例结构）没有写出。

**条目54** [SYSTEM_DESIGN §2.4] → §2.4
OC 原生 channel vs MCP server 选择标准（补充）：OC 原生 = Telegram；必须用 MCP = GitHub；未来 OC 增加原生支持后优先切换
**判定**: ✅ COVERED — §2.4 写了出口分工表（Telegram 用 OC 原生，GitHub 用 MCP server），"原则：OC 原生支持的出口用 OC channel，不支持的才用 MCP server"。

---

#### 5.2 PostgreSQL 事件总线

**条目55** [DESIGN_QA §Q2.2] → §6.6
PG LISTEN/NOTIFY 事件持久化：NOTIFY 不持久化；解决方案=event_log 表（持久化）+ NOTIFY 双写；重启恢复机制；event_log 表结构
**判定**: ❌ MISSING — §6.6 数据流表只写了"PG LISTEN/NOTIFY：事件总线（替代 Ether）"，没有写 event_log 表、双写机制、重启恢复。这是重要的可靠性设计。

**条目56** [EXECUTION_MODEL §（无）] → §6.6
PG LISTEN/NOTIFY channel 定义（job_events / step_events / webhook_events）及 payload 格式
**判定**: ❌ MISSING — §6.6 未定义 channel 名称和 payload 格式，仅提到 PG LISTEN/NOTIFY 作为事件总线。

---

#### 5.3 基础设施启动

**条目57** [EXECUTION_MODEL §（无）] → §6.1
Docker Compose 启动顺序与依赖（9 步严格顺序）；各阶段健康检查方式
**判定**: ⚠ PARTIAL — §6.1 列出了完整的 Docker Compose 服务清单，§6.4 列出了外部依赖，但**严格的启动顺序（哪个先哪个后）** 和**每步具体的健康检查方法** 没有写出。

---

#### 5.4 Plane 与 daemon 一致性

**条目58** [EXECUTION_MODEL §（无）] → §2.3
Task 进行中时的编辑约束：有 running Job 时 DAG 字段只读；daemon API 在 webhook 上检查 Job 状态拒绝 DAG 修改；文字描述等非执行字段仍可编辑
**判定**: ✅ COVERED — §11 禁止事项第 38 条"Task 进行中时允许修改其 DAG（有 running Job 时 DAG 字段只读）"，§3.3 "Step DAG 在 Job 创建时快照"。但**"通过 webhook 检查实现"** 的实现方式没有写出（仅写了规则）。

**条目59** [EXECUTION_MODEL §（无）] → §6.6
Plane API 写入失败处理：Temporal RetryPolicy 重试；重试耗尽记录错误不自动 fail Job；不自动标记 Job failed（因为 Job 本身可能成功）
**判定**: ❌ MISSING — §6.6 未写 Plane API 写入失败的处理策略。§3.7 写了 Step 失败处理，但没有覆盖 Plane API 这个外部依赖的写入失败场景。

---

#### 5.5 Artifact 生命周期

**条目60** [EXECUTION_MODEL §（无）] → §3.6.1
Artifact 版本控制：同一 Step 同一 Job 只有一个 Artifact；同一 Task 多次 Job 按 job_id 区分；MinIO 路径规范；历史版本保留不删除
**判定**: ⚠ PARTIAL — §3.6.1 写了 job_artifacts 表结构和 Artifact 传递机制，§6.7 关键配置包含 MinIO，但**MinIO 路径规范（artifacts/{task_id}/{job_id}/{step_id}/{artifact_type}）** 和**"历史版本不删除"** 的保留策略没有在 SYSTEM_DESIGN.md 中写出。

---

### 六、Agent 与规划类

#### 6.1 Agent 职责边界

**条目61** [TERMINOLOGY §2.5] → §1.4
7 个 agent 的完整职责定义（补充具体场景，含旧 scout/sage 描述）
**判定**: ✅ COVERED — §1.4 列出了 7 个 agent 的职责定义（含 scholar 合并了 scout+sage），§9.3 各 agent 的 Skill 域做了进一步细化。

**条目62** [DESIGN_QA §Q6.3] → §1.4
arbiter 的职责边界：只做质量判断，不做修复；输出通过/不通过 + 问题列表；不通过触发 Step 失败 → counsel 决定 retry 还是 replan
**判定**: ✅ COVERED — §1.4 "arbiter：质量审查"，§3.7 "替换 Step（换一种方式达成同目标）"，§11 禁止事项第 39 条"arbiter 产出修改后的版本（只标注问题，不修复）"。

**条目63** [DESIGN_QA §Q54] → §1.4 / §3.2
7 个 agent 是预创建固定实例；系统启动时所有 workspace 已存在；禁止动态创建新 agent；新能力通过 MCP tool 扩展
**判定**: ✅ COVERED — §2.2 "7 agents（counsel/scholar/artificer/scribe/arbiter/envoy/steward）"，§11 禁止事项第 35 条"动态创建新 agent（7 个固定预创建，能力扩展用 MCP tool）"。

---

#### 6.2 counsel 规划细节

**条目64** [DESIGN_QA §Q4.4] → §3.8
不满意 plan 的处理路径：优先通过对话修改；不向用户暴露结构化 DAG 编辑 UI；用户通过说话修改 DAG
**判定**: ✅ COVERED — §11 禁止事项第 40 条"向用户暴露结构化 DAG 编辑 UI（只允许通过对话修改 DAG）"，§5.6.1 "无 Job 时：调整 DAG"（对话调整）。

**条目65** [DESIGN_QA §Q4.5] → §3.8
任务路径收敛规则：不直接拒绝任务；Draft → Task → 按路由执行；描述不清则追问
**判定**: ✅ COVERED — §3.8 "意图不清时追问"，"一切由 counsel 自行决定"，counsel 系统 prompt 不定义拒绝逻辑。

---

### 七、数据结构与 API 类

#### 7.1 对象字段定义

**条目66** [daemon_实施方案 §3.2] → §1.1
Task daemon 侧补充字段（brief/dag/latest_job_id/trigger_type/trigger_config），存 PG 而非 Plane
**判定**: ❌ MISSING — §1.1 写了 Task 映射到 Plane Issue，但**daemon PG 中 Task 扩展表的具体字段定义** 没有在 SYSTEM_DESIGN.md 中写出。这是数据模型的基础细节。

**条目67** [daemon_实施方案 §3.1] → §1.1
Draft daemon 侧管理字段（intent_snapshot/candidate_brief/source/draft_status），存 PG
**判定**: ❌ MISSING — 同上，§1.1 提到 Draft 使用 Plane DraftIssue，但 daemon PG 中的 Draft 扩展字段没有写出。

---

#### 7.2 DAG 结构

**条目68** [FRONTEND_ALIGNMENT §9] → §3.6
Step DAG 节点的状态枚举（pending/running/completed/failed/skipped）；skipped = counsel 决定跳过；DAG 节点完整结构
**判定**: ⚠ PARTIAL — §3.6 代码示例中有 Step 结构（id/goal/model/depends_on），§3.7 写了"跳过此 Step 继续"（counsel 决定），但**step.status 枚举（pending/running/completed/failed/skipped）** 和**节点完整字段（含 agent、execution_type、status）** 没有正式列出。

---

#### 7.3 API 清单

**条目69** [FRONTEND_GUIDE §6] → §2.2
daemon 自建 API 端点清单（6 个端点：pause/resume/cancel/stream/artifacts/webhooks）
**判定**: ❌ MISSING — §2.2 写了 API 进程的职责（Plane webhook handler、Job 实时 WebSocket），但**具体 API 端点路径** 没有写出。

**条目70** [FRONTEND_ALIGNMENT §12] → §2.2
WebSocket 心跳契约：服务端 20 秒发 ping；客户端回 pong；断线重连由客户端负责，重连后从最新状态重放
**判定**: ❌ MISSING — §2.2 写了"Job 实时 WebSocket"，但 WebSocket 的心跳协议和断线重连约定没有写出。

**条目71** [FRONTEND_ALIGNMENT §11] → §5.2
Task 依赖状态 API 字段：返回 latest_job_status 和 next_trigger_utc；前端用于判断按钮是否 disabled
**判定**: ❌ MISSING — §5.2 写了"等待条件状态；条件未满足时按钮禁用"，但**API 返回字段规范（latest_job_status / next_trigger_utc）** 没有写出。

---

#### 7.4 管理界面隐私边界

**条目72** [FRONTEND_ALIGNMENT §15] → §5.1
Plane 管理界面的数据访问限制：不暴露 Task 对话正文（只暴露元数据）；Job 详情只返回 objective + Step 数量 + agent 列表；不返回 Step instruction 原文；Persona 文件允许管理员直接编辑
**判定**: ❌ MISSING — §5.1 写了 Plane 管理界面替代旧 Console，但**管理界面的数据访问限制规则** 没有写出。

---

### 八、术语与文档类

#### 8.1 术语精确定义

**条目73** [TERMINOLOGY §4.1] → §0.2
ID 语义规范：只承担身份意义，不承担顺序或数值语义；禁止用 ID 推断时间；使用 UUID 或 ULID
**判定**: ❌ MISSING — §0.2 只写了术语原则（一个术语只有一个含义等），没有写 ID/ULID 的技术规范。

**条目74** [TERMINOLOGY §4.2] → §0.2
Slug 规范：全局唯一；历史 slug 保留并重定向；旧 slug 不复用；Task 的 slug 由 Plane Issue key 承担
**判定**: ❌ MISSING — §0.2 无 Slug 规范，§1.1 提到 Task 映射到 Plane Issue，但 slug/key 管理规则没有写出。

**条目75** [TERMINOLOGY §3.2] → §0.2 / §5.9
Plane 界面正式中文术语映射表（9 个术语的中文显示名）
**判定**: ❌ MISSING — §5.9 写了"Plane 界面使用正式中文术语"，但没有给出正式的中文术语映射表。

**条目76** [TERMINOLOGY §3.3] → §0.2
不强行翻译的内容范围（外部专有名词/实现级标识/原始用户内容）
**判定**: ❌ MISSING — §0.2 未写翻译豁免规则。

---

#### 8.2 系统约束

**条目77** [DESIGN_QA §Q10.1] → §0.2
术语同步义务：config/lexicon.json 机器可读词典 + SYSTEM_DESIGN.md §1 人类可读规范；两者必须一致；变更流程（先改文档 → 再改 lexicon.json → 再改代码）
**判定**: ❌ MISSING — §0.2 写了"术语变更必须先更新本文档，再改代码"，但没有提到 lexicon.json 机器可读词典，也没有写三步变更流程。

**条目78** [DESIGN_QA §（多处）] → §9（禁止事项）
补充禁止事项 34-40（同 agent 并行 Step 合并；动态创建 agent；Job 永久运行；context 积累替代 Artifact 传递；DAG 只读约束；arbiter 不修复；DAG 只能通过对话修改）
**判定**: ✅ COVERED — §11 禁止事项已包含这些规则（第 4/35/6/37/38/39/40 条对应）。

---

### 九、暖机与验收类

**条目79** [WARMUP_AND_VALIDATION.md 全文] → §7
WARMUP_AND_VALIDATION.md 需更新的旧术语清单；Stage 2 链路逐通 L09/L05 需更新内容
**判定**: ✅ COVERED — §7 完整描述了暖机 5 个 Stage，使用了新术语（Persona/Guardrails/Artifact 等），§7.6 周度体检包含 17 条链路验证（缩减版）。旧术语到新术语的映射在 §1.8 废弃术语表中覆盖。

**条目80** [daemon_实施方案 §14] → §7
暖机目标的三个维度（单 Task 执行基线 / Trigger chain 命中 / 学习机制回路）
**判定**: ⚠ PARTIAL — §7.4 写了收敛标准（伪人度），§7.6.2 写了五个检测维度，但条目中"Trigger chain 命中"和"学习机制回路"这两个维度没有被显式列为暖机验收目标。部分体现在 Stage 3 测试任务套件中。

---

## 核查阶段整理出的待并入主题

> 最终编号与落位以 `GAPS.md` 为准。以下保留核查阶段整理出的主题清单，便于追溯判断过程。

### 执行模型类

- route="direct" 时的执行语义
- Plane 对象创建的执行责任归属
- Replan 输出的具体格式
- arbiter 失败反馈传入 rework session 的机制
- Job 初始 DAG 生成的输入来源

### 交互设计类

- 操作记录消息的结构规范
- Job 状态的正式中文显示文案
- plan card 强制性规则
- Project 页面骨架的五个区域
- Task 链 DAG 导航的详细规则
- Draft 的四种来源和正式对象地位
- 统一活动流的 API 返回格式规范

### 知识与记忆类

- Persona 文件层结构
- 用户偏好的写入责任
- knowledge_cache 的 Project 级偏置检索

### 基础设施类

- PG event_log 表与 NOTIFY 双写机制
- Plane API 写入失败的处理策略
- MCP server 连接生命周期管理

### 数据结构与 API 类

- Task / Draft 的 daemon PG 扩展字段定义
- Step DAG 节点的完整状态枚举
- daemon 自建 API 端点路径规范
- Task 依赖状态 API 返回字段
- Plane 管理界面的数据访问限制规则

### 术语类

- Plane 界面正式中文术语映射表
- 翻译豁免规则
- `config/lexicon.json` 机器可读词典规范

### 迟到反馈与版本化

- 迟到反馈的语义定义
- Task 依赖关系的变更保护

---

## 附录：旧版 80 条原文

> 以下内容原先保留在 `GAPS.md` 中部，现整体移入本文附录，供覆盖核查和历史对照使用。

> 以下为 GAPS.md 初稿（2026-03-13）的原始 80 条条目，保留供参考核查。
> 上方 G-1 至 G-11 的新条目已覆盖其中大部分。

---

## 一、执行模型类

### 1.1 Step 与 Session

```
[EXECUTION_MODEL §2.2] → §3.2
DAG 快照细节：Task DAG 在 Job 创建时冻结，但 counsel 何时生成初始 DAG？
  - 首次执行：counsel 从 Task 对话生成 DAG
  - 后续执行（re-run）：基于同一 Task 生成新 Job，不克隆 Task
  - 用户修改 DAG：通过 Task 对话增量调整，新 DAG 只在下一个 Job 创建时生效
```

```
[EXECUTION_MODEL §2.3] → §3.2
Session key 分配规则：改为 1 Step = 1 Session 后，session_seq 是否仍需要？
  当前 §3.2 说 session key = {agent_id}:{job_id}:{step_id}，step_id 已唯一标识，seq 概念已废
```

```
[EXECUTION_MODEL §7.1] → §3.7
Rework session 处理：Step 失败重规划时，替换 Step 的新 session 是全新 context 还是保留 arbiter 反馈？
  规则：新 session 全新，arbiter 反馈以结构化 Artifact 方式传入新 Step 的 input，不保留原 context
```

```
[EXECUTION_MODEL §2.4] → §5.6
counsel 规划对话 ≠ OC session：Task 对话流（Plane Activity）与 counsel 的 OC session 是独立概念
  - Plane Activity：用户界面的对话记录
  - OC session：counsel 的工作空间，执行完即关闭
  - 两者不等同，Plane Activity 不是 OC session 内容的镜像
```

```
[DESIGN_QA §Q12.6] → §3.3
DAG 快照的确切时机：
  1. 首次执行 → counsel 从 Task 描述 + 对话生成 DAG，Job 创建时冻结
  2. 用户对话修改 DAG → 更新 Task 的 DAG 定义，不影响正在运行的 Job
  3. 新 Job 执行时 → 使用最新 Task DAG 版本快照
```

```
[DESIGN_QA §Q6.5] → §3.3
"再执行一次"的语义：基于同一个 Task 生成新的 Job，不是克隆新的 Task
```

```
[DESIGN_QA §Q11.2] → §3.2
并行 Step session 的具体规则：
  - 并行 Step：每个 Step 独立 session，同时运行
  - 同一 Job 内不同 agent 的并行 Step：各自独立 session（不同 agent_id，天然隔离）
  - 同一 agent 的并行 Step：各自独立 session（不同 step_id）
```

### 1.2 Direct Step

```
[EXECUTION_MODEL §3.3] → §3.1
Direct Step 的判定标准细化：
  - 已有现成 MCP server 的操作优先使用 direct
  - 条件分支（if/else）仍可用 direct（Python Activity 可含逻辑）
  - "确定性"≈ 不需要自然语言推理，输出由代码完全确定
  - 示例 direct：文件读写、API 调用、格式转换、git 操作、数据库查询
  - 示例 agent：分析、写作、代码生成、规划
```

```
[EXECUTION_MODEL §3.3] → §3.7
Direct Step 失败处理：
  - MCP server 不可用：Temporal RetryPolicy 自动重试
  - 重试耗尽：Step 标记 failed，counsel 判断是否可跳过或替换
  - 不触发 agent 会话，不消耗 LLM token
```

### 1.3 Routing Decision

```
[EXECUTION_MODEL §（无）] → §3.8
Routing Decision 的执行职责：counsel 做出 routing decision 后，由谁创建 Plane 对象？
  规则：counsel 通过 MCP tool 调用 Plane API 创建 Task/Project；
  不是 Worker Activity 直接创建（counsel 是规划层，对象创建属于规划的一部分）
```

```
[EXECUTION_MODEL §（无）] → §3.8
route: "direct" 的执行方式：
  - 跳过 Project/Task 对象创建
  - counsel 直接创建一个临时 Job（无 Task 归属）
  - Job 执行完即丢弃，不持久化 Task
```

### 1.4 Replan Gate

```
[EXECUTION_MODEL §（无）] → §3.5
Replan Gate 触发职责：
  - 由 Temporal Workflow Activity 自动触发（在 chain trigger activity 前执行）
  - 不是人工触发，不是 counsel 主动发起
  - 偏离判定由 counsel 自动完成（analysis 模型）
```

```
[EXECUTION_MODEL §（无）] → §3.5
Replan 输出格式：
  - 输出类型：diff（JSON patch 格式，对未执行 Task 列表的增删改）
  - 不是全新 Task DAG
  - 已完成的 Task 不变，已完成的 Artifact 自动写入新规划的上下文
```

### 1.5 Task 触发与依赖

```
[DESIGN_QA §Q8.4-Q8.5] → §3.4
触发类型互斥的强制约束：
  - 数据模型层保证互斥：一个 Task 只能有一种触发类型字段非空
  - UI 层：选择触发类型时三者互斥（选一）
  - 不允许"手动触发 + 定时触发"同时存在
```

```
[DESIGN_QA §Q3.7] → §3.4
定时任务的正确模式：
  - 正确：一个 standing Task + Temporal Schedule + 多次 Job（每次触发创建新 Job）
  - 禁止：一个 Job 永久运行（Temporal Workflow 不能无限期活着）
```

```
[DESIGN_QA §Q8.3] → §3.4
触发的统一事件论：
  - 所有触发本质都是事件，差别只是事件源不同
  - 事件源清单：time.tick（定时）/ job.closed（前序 Job 完成）/ user.manual（手动）
  - 统一由 Temporal Activity 处理，不区分来源的处理逻辑
```

---

## 二、Session 与 Token 管控类

```
[EXECUTION_MODEL §6.1] → §3.2
选择性注入规则（按 agent 角色差异化）：
  - 所有 agent：MEMORY.md（身份 + 最高规则，≤300 tokens）
  - scout：+ Mem0 检索"搜索策略"（~50 tokens）
  - sage：+ Mem0 检索"分析框架"（~100 tokens）
  - scribe/envoy：+ Mem0 检索"写作风格 + 语言 + 任务类型"（~100-200 tokens）
  - arbiter：+ Mem0 检索"质量标准"（~50 tokens）
  - counsel：+ Mem0 检索"规划经验 + 历史 DAG 模式"（~100-200 tokens）
  某些场景可以完全不注入 Mem0：direct step（无 agent），短暂的 direct routing（counsel 快速判断）
```

```
[EXECUTION_MODEL §6.3] → §4.8
planning_hints 的替代：
  旧架构：counsel 注入 Ledger 统计摘要（planning_hints）
  新架构：Mem0 按需检索规划经验，检索 query = "任务类型 + 规划经验 + 历史 DAG 模式"
  检索结果直接注入 counsel session，不需要独立的 planning_hints 概念
```

```
[EXECUTION_MODEL §（无）] → §3.2
token 管控优先级：
  1. `runTimeoutSeconds` 最优先（硬截断，防止无限循环）
  2. OC `contextPruning: cache-ttl` 自动裁剪旧 tool results（OC 原生）
  3. OC quota 日上限（防止单 agent 失控）
  4. Langfuse 监控告警（暖机后发现异常，不是实时阻断）
  超时先触发，quota 其次，Langfuse 最后
```

```
[EXECUTION_MODEL §（无）] → §3.2
MEMORY.md 内容规范（每个 agent）：
  - 禁止：任务偏好、风格描述、历史经验、规划提示（这些放 Mem0）
  - 允许：agent 的身份定位（1-2 句）+ 最不可违背的行为规则（3-5 条）
  - 区分于 guardrails.md（guardrails.md 是系统规则文件，MEMORY.md 是 agent 人格文件）
```

```
[EXECUTION_MODEL §（无）] → §3.2
session 创建/销毁时机：
  - 创建：Temporal Activity 开始执行该 Step 时（`sessions_spawn`）
  - 销毁：Step 完成（成功或失败）后（`sessions_close` 或 TTL 自动关闭）
  - 不跨 Step 保留，不跨 Job 保留
```

```
[EXECUTION_MODEL §（无）] → §3.2
Mem0 检索 vs OC session-memory hook 的关系：
  - Mem0 按需检索：由 Temporal Activity 在 session 创建前执行，结果注入首条消息
  - OC session-memory hook：OC 原生机制，仅在 /new 或 /reset 时触发，与 Mem0 独立
  - 两套机制不冲突：OC hook 处理 OC 内部 memory，Mem0 处理 daemon 层记忆
```

---

## 三、交互设计类

### 3.1 按钮行为

```
[INTERACTION_DESIGN §2.3] → §5.2
"执行"按钮的原子性保证：
  - "执行" = 创建 Job + 立即运行（原子操作，不可拆分）
  - 不存在"只创建 Job 不运行"的状态
  - 按钮 disabled 条件：Task 已有 running 状态的 Job（防止重复执行）
```

```
[INTERACTION_DESIGN §2.3.1] → §5.3
Job 执行期间的按钮规则：
  - 执行块内有两个按钮：开始/停止（toggle）
  - 开始/停止是同一个 Job 的不同状态，多次开始/停止不创建新 Job
  - running 期间用户发消息不暂停执行（消息追加到 Task 活动流，当前执行继续）
```

```
[INTERACTION_DESIGN §2.11] → §5.4
Project 结构视图中 Task 内联操作规则：
  - 已有 running Job 的 Task → 按钮变为"执行中"状态（disabled）
  - 依赖未满足的 Task → 按钮 disabled，显示等待条件
  - 定时触发的 Task → 显示下次触发时间，无执行按钮
```

```
[INTERACTION_DESIGN §2.7.1] → §5.6.2
按钮-对话等价的完整机制：
  - 按钮点击在 Task 活动流中生成等价自然语言记录（role: system, event: operation）
  - counsel 处理对话消息和按钮操作时走同一逻辑，不区分来源
  - 按钮的独特作用：回溯定义边界——按下收束按钮，回溯决定前面对话段是"运行期间的反馈"
  - 所有非对话框操作（按钮/拖拽/姿态变更）必须在活动流中留下自然语言记录
```

```
[INTERACTION_DESIGN §2.7.2] → §5.6
操作记录消息格式：
  role: "system", event: "operation"
  格式示例："[操作] 暂停执行" / "[操作] 收束" / "[操作] 执行"
  建议：淡色标签样式渲染，与 agent 消息区分
```

### 3.2 Task 页面结构

```
[INTERACTION_DESIGN §2.3] → §5.2
Task(Slip) 页面的五个必须组件：
  1. 标题区（Plane Issue 标题）
  2. plan card（DAG 结构展示，简单任务短卡，复杂任务长卡，必须有，不允许消失）
  3. 统一活动流（所有交互记录，承载对话 + 操作记录 + Job 状态）
  4. 内嵌 Job 执行块（内嵌于活动流，不是独立页面）
  5. 底部输入区（对话框，始终可用）
  plan card 与 DAG 的关系：plan card = DAG 的可视化卡片，不是独立对象
```

```
[INTERACTION_DESIGN §2.3.2] → §5.3
Job 执行块冻结规则：
  - Job closed 后执行块冻结为只读：Artifact 标签 + 执行摘要 + 无操作按钮
  - 过去的 Job 执行块有保质期，过期从活动流中淡出（不是删除，是视觉淡化）
  - 保质期长度：待定（暖机阶段校准）
```

```
[INTERACTION_DESIGN §2.5-2.6] → §5.2
plan card 强制性规则：
  - 每个 Task 必须有 plan card（哪怕是最简单的单步任务）
  - 简单任务：短卡，紧凑
  - 复杂任务：长卡，展开
  - 不允许因为任务轻重不同变成不同的 UI 物种
```

### 3.3 Project 页面结构

```
[INTERACTION_DESIGN §2.11] → §5.4
Project(Folio) 页面骨架（五个区域）：
  1. 项目标题与摘要
  2. 项目内关系图/脉络图（Task DAG 可视化）
  3. 当前活跃 Task 列表
  4. 最近执行的 Task 列表
  5. 最近产出的 Artifact 摘要
  进入 Project 页更像"打开一卷"，而不是打开列表页面（空间感）
```

```
[INTERACTION_DESIGN §2.7.3] → §5.7
Task 链 DAG 导航规则：
  - 线性链：单个"上一个 Task"/"下一个 Task" 标签
  - 分支点（一个 Task 有多个下游）：多个"下一个 Task" 标签
  - 合并点（多个 Task 汇入一个）：多个"上一个 Task" 标签
  导航标签动态反映 DAG 结构
```

### 3.4 对话流规则

```
[INTERACTION_DESIGN §2.7.1] → §5.6.1
统一活动流的两种对话模式：
  - 无 Job 时：对话用于调整 DAG/Brief（counsel 修改 Task 规划）
  - Job 运行期间：对话用于执行调整和评价反馈
  - DAG 修改结果体现在 Task 的 DAG 定义上，不走学习回路
  - Job 运行期间的对话反馈走学习回路（Job 结束后系统询问是否写入 Persona）
```

```
[FRONTEND_ALIGNMENT §2] → §5.2
统一活动流 API 规范：
  - 返回该 Task 下所有 Job 的合并活动流，按时间排序
  - 每条消息带 job_id 字段（标识属于哪次 Job 执行）
  - Job 边界在活动流中可视化区分（执行块）
```

```
[FRONTEND_ALIGNMENT §3] → §5.6
running 期间发消息的行为：
  - 消息追加到活动流，当前 Job 执行继续（不暂停）
  - 消息保留在活动流，Job 结束后作为反馈候选
```

### 3.5 Artifact 呈现

```
[DESIGN_QA §Q7.1] → §5.3
Artifact 的两层语义（Offering vs Vault 的去向）：
  - Artifact 的对外版本：不携带系统痕迹，是给用户看的正式交付物
  - Artifact 的内部版本：包含来源标记 [EXT/INT/SYS]，存 MinIO，用于审计
  - Plane 活动流展示：对外版本（干净的内容）
  - MinIO 存储：内部版本（含元数据）
```

```
[FRONTEND_GUIDE §8.1] → §5.3
Artifact 在执行块中的呈现：
  - Job 执行中：DAG 进度 + 当前 Step 的实时输出（streaming）
  - Job closed：Artifact 版本列表 + 最终交付物预览
  - "版本"= 同一 Task 多次执行的 Artifact 列表（最新在前）
```

### 3.6 状态显示文案

```
[FRONTEND_ALIGNMENT §7] → §5.9
Job 状态的正式中文显示文案：
  | 状态 | sub_status | 中文显示 |
  | running | queued | 排队中 |
  | running | executing | 执行中 |
  | running | paused | 等待审查 |
  | running | retrying | 重试中 |
  | closed | succeeded | 已完成 |
  | closed | failed | 执行失败 |
  | closed | cancelled | 已取消 |
```

### 3.7 Draft 交互

```
[DESIGN_QA §Q3.2] → §5.5
Draft 的四种来源（对应到 Plane DraftIssue）：
  1. 用户对话（最常见，counsel 从对话创建 DraftIssue）
  2. 规则触发（NeMo Guardrails 或 Temporal 触发的系统建议）
  3. 外部事件（webhook 进来的任务建议）
  4. 系统内部推进（counsel 在规划时主动创建后续 Task 草稿）
  自动任务也必须先经过 Draft（不允许系统直接创建 Task 绕过 Draft 审查）
```

```
[DESIGN_QA §Q3.1] → §5.5
Draft 的正式对象地位：
  - Draft 不是临时聊天缓存
  - Draft 是正式对象：任何一件事在成为 Task 前都先以 Draft 形式存在
  - Draft → Task 的转换是有意识的决策（counsel 或用户确认），不是自动升级
```

---

## 四、知识与记忆类

### 4.1 Guardrails

```
[DESIGN_QA §Q1.1.1] → §4.2
Guardrails 三层执行的代码层实现：
  - 硬规则：NeMo input/output rail（Colang DSL）+ Python pre/post check
    Python check 的触发点：Quota 上限检查、token 预算检查、并发数检查、格式校验
  - 软规则：NeMo dialog rail + guardrails.md（~200 tokens，注入 agent prompt）
  - 关键审查：arbiter agent Step + NeMo output rail 双重校验
  Python pre/post check 与 NeMo 的关系：先跑 Python check，通过后才进入 NeMo 引擎
```

```
[DESIGN_QA §Q1.1.2] → §4.2.1
Guardrails 作为信息门控的具体触发点：
  - Persona 候选写入 Mem0 前：NeMo custom action 校验
  - 外部知识引用前：source_tier 校验（NeMo input rail）
  - 用户反馈写入前：用户确认 + NeMo custom action 校验
  "系统不假设用户善意"原则：用户可能无意侵蚀系统质量，门控为用户长期利益服务
```

```
[REFACTOR §3.3.1] → §4.2
NeMo 与代码层集成方式：
  - NeMo Guardrails 作为 Python 库嵌入 Worker 进程
  - 调用方式：`rails.generate(messages=[...])`
  - 自定义 action（如 Mem0 写入校验）通过 `@action` 装饰器注册
  - 不需要独立的 NeMo 服务进程
```

### 4.2 Persona

```
[daemon_实施方案 §6.2] → §4.3
Persona 文件结构（Mem0 + 文件两层）：
  第一层（初始化文件，暖机时生成）：
    psyche/voice/identity.md    （≤150 tokens，AI 身份）
    psyche/voice/common.md      （≤250 tokens，跨语言写作结构偏好）
    psyche/voice/zh.md          （≤250 tokens，中文风格）
    psyche/voice/en.md          （≤250 tokens，英文风格）
    psyche/voice/overlays/*.md  （≤50 tokens/个，任务类型覆盖）
  第二层（Mem0，动态更新）：
    semantic memory（user 级）：用户偏好
    procedural memory（agent 级）：写作风格、规划经验
  两层关系：文件层是稳定基底，Mem0 层是动态演化
```

```
[DESIGN_QA §Q1.2] → §4.3
Persona 组件的内部三分：
  - AI 身份和人格（semantic memory, agent 级）
  - 写作风格（procedural memory, agent 级，scribe/envoy 用）
  - 用户偏好（semantic memory, user 级，所有 agent 参考）
  SYSTEM_DESIGN.md §4.3.2 已有但需明确"用户偏好"由哪个 agent 写入（counsel/scribe 在 Job 结束时确认）
```

```
[REFACTOR §4] → §4.3.5
Persona 候选提取规则（Job 结束时）：
  - 触发时机：Job closed(succeeded) 后
  - 提取方式：系统扫描 Job 期间活动流，识别风格类反馈关键词（"太正式了""更简洁""不要用这个词"）
  - 提取结果：展示候选列表，用户勾选确认
  - 确认后：NeMo custom action 校验 → 写入 Mem0
  - 系统在 Plane Issue Activity 中生成提示："本次执行中有以下风格反馈，是否长期生效？"
```

```
[DESIGN_QA §Q1.5] → §4.6.2
knowledge_cache embedding 检索策略：
  - 查询时以 embedding 相似度为主
  - Project 级别的检索加主题偏置：同一 Project 内的缓存优先返回（无命中再看全局）
  - 偏置实现：检索时加 project_id 过滤，有命中直接返回；无命中去掉过滤全局检索
```

### 4.3 学习机制

```
[DESIGN_QA §Q1.4] → §8.2
规划经验合并规则：
  - 新 Job 成功后，counsel 的规划决策（DAG 结构 + Step 分解方式）存入 Mem0
  - 合并标准：相似任务的规划经验合并（cosine 相似度 > 0.85）
  - 实现：Mem0 自带去重，相似记忆自动合并，无需自建合并逻辑
  - 冷启动：前 20 个成功 Job 后开始有参考价值（§8.2 已有，需保留）
```

```
[DESIGN_QA §Q1.6] → §8.2
规划经验的分级存储：
  - Task 级别规划经验（Step DAG 结构）→ agent 级 procedural memory（counsel）
  - Project 级别背景信息（目标 + 已完成摘要）→ 动态组装（§3.5.1），不持久化到 Mem0
  两者不混用
```

```
[DESIGN_QA §Q7.4] → §8
迟到反馈的语义：
  - 用户回到 Task 页面重新执行 = 对上次 Job 结果的隐式否定信号
  - 不设专门回溯评价机制，新 Job 执行前可在对话流中说明原因
  - 不自动标记上次 Job 为"失败"，只是用户选择重做
```

```
[DESIGN_QA §Q1.7] → §8
Task 依赖关系的版本化：
  - Task 依赖关系（Plane IssueRelation）不应被无声改写
  - 正式变更必须通过 Plane UI 操作，操作记录在活动流中
  - Replan Gate 修改的 Task 列表：已完成的 Task 不变，只能修改未执行的
```

---

## 五、基础设施类

### 5.1 MCP 工具管理

```
[EXECUTION_MODEL §3.4] → §6.3
MCP server 连接生命周期：
  - 持久化：Worker 进程启动时连接所有 MCP server，进程级别复用（不是每次 call 重连）
  - 路由表：首次连接时调用 list_tools() 构建 tool_name → server 映射
  - 超时防护：每次 call_tool 带 asyncio.wait_for（防止 server hang 导致阻塞）
  - 故障恢复：server 超时/崩溃 → 标记不可用 → Step 失败 → Temporal RetryPolicy
```

```
[EXECUTION_MODEL §3.4] → §6.7
mcp_servers.json 配置规范：
  env 中 ${VAR} 会被展开为实际环境变量值
  示例：
    {"servers": {"github": {"transport": "stdio", "command": "node",
      "args": ["@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"}}}}
```

```
[SYSTEM_DESIGN §2.4] → §2.4
OC 原生 channel vs MCP server 的选择标准（补充说明）：
  - OC 原生支持的出口：Telegram announce（通知类）
  - 必须用 MCP 的：GitHub（操作类，OC 无原生 GitHub action channel）
  - 未来扩展：如 OC 增加原生支持，优先切换，删除对应 MCP server
```

### 5.2 PostgreSQL 事件总线

```
[DESIGN_QA §Q2.2] → §6.6
PG LISTEN/NOTIFY 事件持久化：
  - PG NOTIFY 是即时推送，不持久化（进程重启后丢失未消费事件）
  - 解决方案：关键事件写入 PG `event_log` 表（持久化），同时 NOTIFY 触发即时处理
  - 重启恢复：Worker 进程重启后，查询 event_log 中未消费的事件补处理
  - event_log 表：id, channel, payload(JSONB), created_at, consumed_at(nullable)
```

```
[EXECUTION_MODEL §（无）] → §6.6
PG LISTEN/NOTIFY channel 定义：
  - job_events：Job 状态变更（created/closed/failed）
  - step_events：Step 状态变更
  - webhook_events：Plane webhook 到达
  payload 格式：{"event_type": "job_closed", "job_id": "...", "task_id": "..."}
```

### 5.3 基础设施启动

```
[EXECUTION_MODEL §（无）] → §6.1
Docker Compose 启动顺序与依赖：
  1. PostgreSQL（最先启动，其他服务依赖）
  2. Redis（Plane 依赖）
  3. Temporal Server（依赖 PG）
  4. Plane API + Worker + Beat（依赖 PG + Redis）
  5. Langfuse + ClickHouse（独立）
  6. RAGFlow + Elasticsearch（独立）
  7. MinIO、Firecrawl（独立）
  8. daemon API 进程 + Worker 进程（最后启动，依赖所有上游服务）
  9. OC Gateway（daemon 进程启动后最后启动）
  健康检查：每个服务配置 Docker healthcheck，daemon 进程启动前验证所有依赖就绪
```

### 5.4 Plane 与 daemon 一致性

```
[EXECUTION_MODEL §（无）] → §2.3
Task 进行中时的编辑约束：
  - Task 有 running Job 时：Plane Issue 编辑受限（DAG 字段只读）
  - 实现：daemon API 在 Plane webhook 上检查 Job 状态，有 running Job 时拒绝 DAG 修改
  - 文字描述、标题等非执行字段仍可编辑
```

```
[EXECUTION_MODEL §（无）] → §6.6
Plane API 写入失败处理：
  - Plane API 不可用：Temporal RetryPolicy 自动重试（指数退避，最多 5 次）
  - 重试耗尽：Job 状态保持 running，记录错误到 PG，人工介入
  - 不自动将 Job 标记为 failed（因为 Job 本身可能成功了，只是状态回写失败）
```

### 5.5 Artifact 生命周期

```
[EXECUTION_MODEL §（无）] → §3.6.1
Artifact 版本控制：
  - 同一 Step 同一 Job：只有一个 Artifact（不覆盖，追加版本号）
  - 同一 Task 多次 Job：每次 Job 产生独立 Artifact，按 job_id 区分
  - MinIO 路径规范：artifacts/{task_id}/{job_id}/{step_id}/{artifact_type}
  - 历史版本保留：不删除，通过 job_artifacts 表查询历史
```

---

## 六、Agent 与规划类

### 6.1 Agent 职责边界

```
[TERMINOLOGY §2.5] → §1.4
7 个 agent 的完整职责定义（补充具体场景）：
  - scout：网页/学术/API 搜索，信息采集，不分析只采集
  - sage：文献综述，数据分析，论证评估，方案比较（分析不产出最终文本）
  - artificer：代码实现，调试，工具链操作，技术方案落地
  - scribe：论文写作，文章，报告，对外文本，风格适配用户
  - arbiter：事实校验，逻辑一致性检查，风格合规审查，不产出修改版本只标注问题
  - counsel：意图理解，DAG 规划，routing decision，Replan Gate 判断
  - envoy：发布到外部平台，格式转换，Telegram 通知，GitHub 操作
```

```
[DESIGN_QA §Q6.3] → §1.4
arbiter 的职责边界：
  - 只做质量判断，不做修复
  - 输出：通过/不通过 + 问题列表（不是修改后的版本）
  - 不通过 → 触发 Step 失败 → counsel 决定是 retry（重生成）还是 replan（换方案）
  - arbiter 不做"Herald"工作（Herald 已删，envoy 替代发布，不涉及）
```

```
[DESIGN_QA §Q54] → §1.4 / §3.2
7 个 agent 是预创建的固定实例（不动态创建）：
  - 系统启动时所有 agent workspace 已存在
  - 不允许运行时动态创建新 agent（禁止模式）
  - 如需新能力：通过 MCP tool 扩展，不通过新建 agent
```

### 6.2 counsel 规划细节

```
[DESIGN_QA §Q4.4] → §3.8
不满意 plan 的处理路径：
  - 优先通过对话修改（counsel 根据对话调整 DAG）
  - 不向用户暴露结构化 DAG 编辑 UI（用户通过说话修改，不是拖拽节点）
  - 用户说"把第 3 步拆成两步" → counsel 理解并修改 DAG，不是用户直接操作 DAG
```

```
[DESIGN_QA §Q4.5] → §3.8
任务路径收敛规则（counsel 的固定处理路径）：
  1. 继续收敛 Draft → 再尝试成为 Task
  2. 若成为 Task → 按 direct/task/project 路由执行
  3. 若描述仍不清楚 → 向用户追问，不拒绝任务
  不直接拒绝任务，最终一定走向某条执行路径
```

---

## 七、数据结构与 API 类

### 7.1 对象字段定义

```
[daemon_实施方案 §3.2] → §1.1
Task（对应 Plane Issue）的 daemon 侧补充字段：
  Plane 原生字段已足够管理 Task CRUD 和状态
  daemon 侧需要补充（存 PG，不在 Plane）：
    - brief：结构化任务描述（counsel 输出，JSON）
    - dag：Step DAG 定义（counsel 规划结果，JSON）
    - latest_job_id：最近一次 Job 的 ID
    - trigger_type：manual / timer / chain（互斥）
    - trigger_config：定时配置 or 前序 Task ID（根据 trigger_type）
```

```
[daemon_实施方案 §3.1] → §1.1
Draft 的 daemon 侧管理字段：
  Plane DraftIssue 承载标题和描述
  daemon 侧补充（存 PG）：
    - intent_snapshot：counsel 理解的用户意图（中间状态，JSON）
    - candidate_brief：候选的结构化描述（待用户确认）
    - source：对话/规则/外部/系统（触发来源）
    - draft_status：open / refining / crystallized / abandoned
```

### 7.2 DAG 结构

```
[FRONTEND_ALIGNMENT §9] → §3.6
Step DAG 节点的状态枚举：
  step.status: pending / running / completed / failed / skipped
  skipped = counsel 决定跳过（不影响后续）
  DAG 节点结构：{id, goal, agent, model, depends_on, status, execution_type}
```

### 7.3 API 清单

```
[FRONTEND_GUIDE §6] → §2.2（Process 模型补充）
daemon 自建 API 端点（FastAPI 胶水层，最小集）：
  POST /api/jobs/{job_id}/pause          → Temporal Signal（暂停）
  POST /api/jobs/{job_id}/resume         → Temporal Signal（恢复）
  POST /api/jobs/{job_id}/cancel         → Temporal Signal（取消）
  GET  /api/jobs/{job_id}/stream         → WebSocket（Job 实时流）
  GET  /api/tasks/{task_id}/artifacts    → Job Artifact 列表
  POST /api/webhooks/plane               → Plane webhook handler
```

```
[FRONTEND_ALIGNMENT §12] → §2.2
WebSocket 心跳契约（Job 实时面板）：
  - 服务端：等待客户端消息，超时 20 秒后发 {"event": "ping"}
  - 客户端：收到 ping 或主动发 "ping" → 服务端回 {"event": "pong"}
  - 断线重连：客户端负责重连，重连后从最新状态重放
```

```
[FRONTEND_ALIGNMENT §11] → §5.2
Task 依赖状态 API 字段：
  - 返回前序 Task 的最新 Job 状态（latest_job_status）
  - 返回定时触发的下次执行时间（next_trigger_utc）
  - 前端用于判断是否应 disabled 执行按钮
```

### 7.4 管理界面隐私边界

```
[FRONTEND_ALIGNMENT §15] → §5.1
Plane 管理界面（Console 替代）的数据访问限制：
  - 不暴露 Task 对话正文（只暴露元数据）
  - Job 详情只返回：objective（标题摘要）+ Step 数量 + agent 列表
  - 不返回 Step 内的具体 instruction 原文（防止内容泄露）
  - Persona 文件（psyche/voice/）允许管理员直接编辑（有意开放）
```

---

## 八、术语与文档类

### 8.1 术语精确定义

```
[TERMINOLOGY §4.1] → §0.2
ID 语义规范：
  - ID 只承担身份意义，不承担顺序或数值语义
  - 禁止用 ID 推断创建时间或排序
  - 使用 UUID 或 ULID（有序 ID 用 ULID，无序用 UUID）
```

```
[TERMINOLOGY §4.2] → §0.2
Slug 规范：
  - Slug 必须全局唯一（同类型对象内）
  - 历史 slug 保留并重定向（rename 后旧 slug 仍可访问）
  - 旧 slug 不复用（即使原对象已删除）
  - Task 映射到 Plane Issue 后，slug 由 Plane Issue key 承担（如 PROJ-123）
```

```
[TERMINOLOGY §3.2] → §0.2 / §5.9
Plane 界面的正式中文术语映射表：
  | 英文 canonical | Plane 界面中文 |
  | Project | 项目 |
  | Task | 任务 |
  | Job | 执行记录 |
  | Step | 步骤 |
  | Artifact | 产出 |
  | Draft | 草稿 |
  | Persona | 人格配置 |
  | Guardrails | 系统规则 |
  | Knowledge Base | 知识库 |
```

```
[TERMINOLOGY §3.3] → §0.2
不强行翻译的内容范围：
  - 外部专有名词（模型名、平台名）
  - 实现级标识（API endpoint、代码变量名）
  - 原始用户内容（用户输入的 Task 标题等）
```

### 8.2 系统约束

```
[DESIGN_QA §Q10.1] → §0.2
术语同步义务（补充）：
  - config/lexicon.json：机器可读词典（代码自动校验术语使用）
  - SYSTEM_DESIGN.md §1：人类可读规范
  - 两者必须一致
  - 变更流程：先改 SYSTEM_DESIGN.md → 再改 lexicon.json → 再改代码
```

```
[DESIGN_QA §（多处）] → §9（禁止事项）
补充禁止事项：
  34. 同 agent 并行 Step 合并为复合指令（每个 Step 独立 session，不合并）
  35. 动态创建新 agent（7 个固定预创建，能力扩展用 MCP tool）
  36. 一个 Job 永久运行（必须是有限期的 Temporal Workflow）
  37. 用 context 积累替代显式 Artifact 传递（禁止 session 共享）
  38. Task 进行中时允许修改其 DAG（有 running Job 时 DAG 字段只读）
  39. arbiter 产出修改后的版本（只标注问题，不修复）
  40. 向用户暴露结构化 DAG 编辑 UI（只允许通过对话修改 DAG）
```

---

## 九、暖机与验收类

```
[WARMUP_AND_VALIDATION.md 全文] → §7
WARMUP_AND_VALIDATION.md 需更新的旧术语清单：
  - Voice 标定 → Persona 标定
  - psyche/voice/ 目录 → 仍保留此目录结构（见四.2 Persona 文件结构）
  - scout/sage/artificer/scribe/arbiter → 同名 agent（直接对应，无需改名）
  - Instinct 硬规则 → Guardrails（NeMo）
  - SourceCache → Knowledge Base（RAGFlow + knowledge_cache）
  - Ledger → Langfuse + PG（统计）
  - Spine routines → 1 个定时清理 Job + Docker healthcheck
  - Writ 依赖链 → Task chain（Plane IssueRelation + Temporal Schedule）
  - Offering → Artifact
  - Folio → Project，Slip → Task，Deed → Job，Move → Step
  - arbiter review → arbiter agent Step（不变，但 arbiter 现在是保留的独立 agent）
  Stage 2 链路逐通的 L09（Ledger 统计）需替换为 Langfuse trace 验证
  Stage 2 链路逐通的 L05（Deed settling）需替换为 Job paused → Temporal Signal → closed
```

```
[daemon_实施方案 §14] → §7
暖机目标的三个维度（补充到 §7.4 收敛标准）：
  1. 单 Task 执行基线：counsel 规划的 Step 数量和模型策略选择符合任务复杂度
  2. Trigger chain 命中：Task 依赖链按预期顺序触发，无误触发和漏触发
  3. 学习机制回路：Job 成功后 Mem0 更新，下次相似任务规划质量提升
```

---
