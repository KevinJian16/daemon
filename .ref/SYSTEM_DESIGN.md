# Daemon 系统设计总纲

> **状态**：七稿（两层 agent 架构）
> **日期**：2026-03-15
> **定位**：daemon 系统的唯一权威设计文档。实现者只靠本文 + 配套参考文档即可完成系统重构。
> **配套文档**：`SYSTEM_DESIGN_REFERENCE.md`（附录 B-I，查表用）、`SYSTEM_DESIGN.review.html`（彩色审阅版）
> **归档来源**：五稿已归档到 `.ref/_archive/SYSTEM_DESIGN_v5_2026-03-14.md`，四稿已归档到 `.ref/_archive/SYSTEM_DESIGN_v4_2026-03-14.md`

---

## §0 治理规则

### 0.1 本文档的权威性

本文档是 daemon 系统的唯一权威设计来源。实现、重构、测试、暖机、前端适配、Glue API 和 OpenClaw agent 层都以本文为准。

如本文与以下文档冲突，一律以本文为准：
- `.ref/_archive/*`（历史参考文档）
- 代码中的旧注释、旧命名、旧脚本说明

配套参考文档 `SYSTEM_DESIGN_REFERENCE.md` 包含附录 B-I（参数表、字段表、接口契约、Gap 注册表、设计决策日志）。参考文档的内容与本文一致；如有矛盾，以本文正文为准。

### 0.2 本文档如何使用

实现者按以下顺序阅读：
1. 正文 `§0-§10`：确定系统规则和主行为。
2. 参考文档附录 B / C / D：查字段、参数、接口、事件和状态映射。
3. 参考文档附录 E / F：检查所有 `DEFAULT` 和 `UNRESOLVED`。
4. 参考文档附录 I：查阅设计决策日志，理解每条决策的理由。

**要求**：实现者不得绕过正文直接从附录里挑方案自定。正文没有明确授权的地方，不得自行改写架构语义。

### 0.3 状态标签

- `FINAL`：已拍板，必须按此实现。
- `DEFAULT`：当前默认方案，可据此开工；后续校准只能调参数，不能改外部语义。
- `UNRESOLVED`：本轮仍未定；实现者不能自行发挥，只能保留接口或等待下一轮定稿。

正文中出现 `**[DEFAULT]**` 和 `**[UNRESOLVED]**` 的位置，都是刻意保留的显著提醒点。没有标签的规则默认为 FINAL。

### 0.4 文档与代码的同步顺序

术语、对象模型、状态机、字段表、接口契约的变更顺序固定为：
1. 先改 `SYSTEM_DESIGN.md`
2. 再改 `config/lexicon.json` 与参考文档附录表格
3. 再改代码和测试

禁止"先把代码做了，设计文档以后再补"。

### 0.5 术语、翻译与豁免规则

- 一个术语只能有一个正式含义。
- 代码、存储、API 使用英文 canonical name。
- 面向用户的桌面客户端 / Telegram 使用正式中文显示名。
- 外部专有名词、实现级标识、用户原始输入，不强制翻译。

FINAL 的术语映射见 `§1` 和参考文档附录 D。

### 0.6 双层系统

daemon 是双层系统，两层必须同步更新：

1. **Python 层**：services/, temporal/, runtime/, config/
2. **OpenClaw agent 层**：openclaw/workspace/\*/TOOLS.md, skills/\*/SKILL.md, SKILL_GRAPH.md, openclaw.json

openclaw/ 不在 git 中（含 API key），但它是代码库的一部分。每次改代码都必须检查两层。

FINAL 规则：任何改动如果只改一层、不验证另一层的联动，都不算完成。

### 0.7 工作原则

- **认真读设计、认真读代码、认真做链路核查。**
- 函数存在不等于链路成立；必须追踪"输入 → 传递 → 存储 → 消费 → 输出"。
- 能复用成熟组件就复用，不为追求完整性自造基础设施。
- 跨系统边界要写清归属：谁创建对象、谁写回状态、谁负责补偿。

### 0.8 高风险陷阱

1. **只验结构不验行为**——函数存在 ≠ 数据流通。必须验证完整链路。
2. **修了一环就标已修**——下游必须全部通畅才算修好。
3. **假设外部系统行为**——去查文档确认，不猜。
4. **文档和代码不同步**——改一个必须改另一个。

### 0.9 用户体验原则

**FINAL 规则：用户与 daemon 的一切交互，必须是绝对顺畅无阻塞、无段落感、用户对系统内部实现无感的。**

含义：
- 用户说"做 X"，系统就做。不存在"已创建任务，请点击执行"——创建和执行是原子操作（§3.5），用户不感知这两个阶段。
- 反馈自然发生。不存在"任务完成，请打分"——用户觉得不好就说哪里不好，沉默就是 accepted。系统从对话中自己提取反馈，不制造评价环节。
- 任务类型无限多样。用户可以说"发小红书"、"帮我学一个概念并用 VSCode 实验"、"每周自动追踪某个领域进展"。系统的 execution_type 组合（agent/direct/claude_code/codex）+ 外部出口（MCP/OC channel）+ 本地应用控制覆盖这些场景，用户不需要知道背后用了什么。
- 所有系统内部概念（Job/Step/Artifact/DAG/Replan）都是实现细节。用户只看到：任务在进行、任务完成了、结果在这里。

**反例清单**（实现时严格禁止）：
- 要求用户打分/评价
- 要求用户在"创建"和"执行"之间做选择
- 要求用户选择 agent 或模型
- 要求用户配置触发类型（L1 agent 自行判断）
- 要求用户理解 Job/Step 状态机
- 展示内部错误堆栈（只说"出了问题，正在修"或"修好了"）

### 0.9.1 系统工作语言

**FINAL 规则：daemon 的系统工作语言是英文。**

- 所有 agent 配置文件（SOUL.md / TOOLS.md / SKILL.md / AGENTS.md / MEMORY.md）全英文
- 所有 SKILL.md 遵循 Agent Skills 标准（agentskills.io/specification）：YAML frontmatter + 英文 description
- daemon 对用户的技术/专业输出全英文（日报、论文摘要、code review、写作初稿）
- 用户输入不限语言，daemon 英文回复
- 不懂的地方用户主动问，daemon 用中文解释具体概念（不整篇翻译）
- 所有对外产出（论文、博客、GitHub）全英文
- 系统有帮助用户使用英文表述的倾向——不是强制，是引导

来源：Stage 0 Interview §3 渐进式英文浸泡策略。

### 0.10 自治原则

**FINAL 规则：daemon 是自治系统。系统级变更的审核由 Claude Code / Codex 执行，不由用户执行。**

用户不是系统工程师，不能审查 skill 改动、评估 Mem0 记忆质量、判断参数校准是否合理。所有系统级自我改进链路：

```
admin 提出变更 → Claude Code / Codex 审查 → 执行 → scripts/verify.py 验证
```

**用户只在涉及个人品味和对外形象时参与**：
- Persona 风格偏好（"我喜欢这种写法"）→ 用户确认
- 对外发布内容的最终审阅 → 用户可选择介入

**以下全部由 CC/Codex 审查，不问用户**：
- Skill 更新
- 系统参数校准
- Mem0 记忆清理
- 体检后的修复和改进
- 进程重启、服务恢复

CC/Codex 执行审查时的上下文保障见 §7.8（自愈 Workflow）和 §7.9（问题文件格式）。

### 0.11 场景认知原则

**FINAL 规则：daemon 的交互架构是场景导向的，不是任务导向的。**

核心观察：人类不是任务执行器。当人类被置于不同场景下，思维模式会切换——在教室里会主动提问、接受不懂；面对教练会逼自己、关注数据；和同事协作会主导决策、关注效率。**场景触发认知切换，认知切换决定行为质量。**

因此 daemon 的面向用户层（L1）按场景而非任务来划分。每个 L1 agent 不是一个"功能模块"，而是一个**认知触发器**——用户进入某个对话的那一刻，不只是 daemon 切换了行为模式，**用户自己的思维模式也切换了**。

daemon 定义四个场景，区分依据是**用户与 daemon 之间的主导权关系**：

| 场景 | 关系动态 | 用户的认知模式 |
|---|---|---|
| copilot | 用户主导，daemon 执行+建议 | 指挥、决策、关注结果 |
| mentor | daemon 引导，用户学习 | 学习、探索、接受评价 |
| coach | daemon 规划，用户表现 | 执行、突破、关注表现 |
| operator | daemon 自主，用户监督 | 监督、审视、关注策略 |

FINAL 规则：
- 场景定义关系和氛围，不定义"做什么"。任何场景里什么都可能发生，但权力关系始终由场景决定。
- 四个场景是四个独立对话，不混在一起。用户自己选择去哪个场景，系统不替用户切换。
- 每个场景通过 SOUL.md 定义关系动态，通过 SKILL.md 定义工作方法。同一套执行基础设施（OC + L2 agent + MCP），不同的上层行为。
- 这个设计的理论基础是 situated cognition（情境认知）：认知不是脱离环境的抽象过程，而是被情境塑造的。离散的场景比连续的自主性滑块更符合人类认知方式。

**与市面角色扮演 chatbot 的本质区别**：市面角色扮演产品（Character.ai 等）做的是**表演层的角色扮演**——换名字、换语气、换人设，但底层机制一样。daemon 的场景设计不同：**场景不只改变 agent 怎么说话，而是改变整个系统怎么运作。** mentor 场景下系统会布置作业、创建文档、等待用户提交、评估产出；coach 场景下系统会设定量化目标、定期拉取数据、生成表现分析；operator 场景下系统会自主行动、定期汇报。从 prompt 到 session 到 Job 到 Temporal workflow，整条链路都跟着场景变。这是"表演层角色扮演"和"架构层场景设计"的本质区别。

---

## §1 术语与对象模型

### 1.1 正式对象

| 对象 | 定义 | Plane 映射 | 说明 |
|---|---|---|---|
| `Project` | Task 的组织容器 | Plane Project | 长周期主题 / 项目 |
| `Draft` | 尚未转正的候选工作项 | Plane DraftIssue | 是正式对象，不是临时聊天缓存 |
| `Task` | 核心工作单元 | Plane Issue | 用户主要协作对象 |
| `Job` | Task 的一次执行记录 | daemon 自管 | Plane 无等价对象 |
| `Step` | Job DAG 中的一步 | 无 Plane 对象 | 1 Step = 1 目标 |
| `Artifact` | Step / Job 的交付产物 | 无 Plane 对象 | 存 MinIO + PG 元数据 |

层次关系：
```
Project（目标 + 任务分解）
  └─ Task（工作单元，Plane Issue，Task 间依赖用 Plane IssueRelation）
       └─ Job（Task 的一次运行实例，daemon 自管）
            └─ Step（1 目标，可调用任意 agent/tool）
                 └─ Artifact（交付产物，存 MinIO + PG 元数据）
```

FINAL 规则：
- `Project / Draft / Task` 的状态、标题、描述、依赖关系由 Plane 负责持有与展示。
- `Job / Step / Artifact` 由 daemon 持有。
- `Draft → Task` 必须经过明确转换，不允许自动升级。
- Task 间依赖用 Plane `IssueRelation(blocked_by)` 表示，不再自造一等 Trigger 对象。

### 1.2 状态模型

Task 和 Project 直接使用 Plane 的状态组（backlog / unstarted / started / completed / cancelled）；daemon 不维护自己的状态层。

Job 的正式状态机如下：

| 主状态 | 子状态 | 说明 |
|---|---|---|
| `running` | `queued` | 已创建，等待执行资源 |
| `running` | `executing` | 正在跑 Step |
| `running` | `paused` | 等待外部条件（资源不足、依赖服务不可用等），不用于等待用户确认 |
| `running` | `retrying` | Temporal / 运行时重试中 |
| `closed` | `succeeded` | 执行成功 |
| `closed` | `failed` | 执行失败 |
| `closed` | `cancelled` | 用户或系统取消 |

FINAL 规则：
- 默认成功 Job 直接 `closed/succeeded`，没有旧版 `settling` 窗口。
- `requires_review=true` 时，L1 agent 在对话中提出确认请求（见 §4.8），Job 不暂停，继续执行不依赖确认的后续 Step。
- "再执行一次"始终表示基于同一 Task 创建一个新的 Job，不克隆新 Task。

Step 的正式状态枚举：`pending` / `running` / `completed` / `failed` / `skipped` / `pending_confirmation`。

- `skipped` 表示 L1 agent 明确判定可以跳过，不能由实现者随意使用。
- `pending_confirmation` 表示 Step 等待用户对话确认（§4.8），Job 不暂停，其他不依赖此 Step 的后续 Step 继续执行。

### 1.3 执行类型

| execution_type | 作用 | 成本模型 |
|---|---|---|
| `agent` | OpenClaw session | 使用 daemon 统一预算 |
| `direct` | Python / shell / API / deterministic activity | 零 LLM token |
| `claude_code` | 本地 Claude Code CLI subprocess | 用户 Claude Code 配额 |
| `codex` | 本地 Codex CLI subprocess | 用户 Codex 配额 |

FINAL 规则：
- 只要输出完全由输入决定，就优先用 `direct`。
- 只有需要自然语言推理、分析、写作、规划、审查时才用 `agent` / `claude_code` / `codex`。

**direct Step 覆盖范围**（凡是输出由输入完全决定的操作）：
- Shell 命令（git、npm、pip、任意 CLI）
- 本地应用控制（`open`、VS Code、Xcode 等）
- 浏览器打开（`webbrowser.open()`）
- 文件读写、格式转换、数据库查询
- API 调用（已知 endpoint + schema）
- 进程管理、端口检查

**execution_type 判断标准（L1 routing decision 时使用）**：

| 判断条件 | execution_type | 配额来源 |
|---|---|---|
| 输出由输入完全决定（shell/API/文件操作/DB 查询） | `direct` | 零 token |
| 需要 LLM 推理，但范围是单次生成/分析/搜索/写作 | `agent` | daemon API token 预算 |
| 需要**写代码** + 读写多文件 + 理解项目结构 + 运行测试 | `codex` | 用户 Codex Plus 配额 |
| 需要**审查/规划/修复** + 对照多文件判断质量/正确性 | `claude_code` | 用户 Claude Code Max 5x 配额 |

**codex 典型场景**（engineer 写代码）：
- 创建/修改 3 个以上文件的功能实现
- 需要理解项目目录结构的重构
- 需要运行测试验证的 bug 修复
- 从零实现一个模块

**claude_code 典型场景**（审查/规划/修复）：
- reviewer 审查要发布的完整产出（对照多文件判断质量）
- 复杂 Project 初始规划（读现有代码库理解上下文）
- admin 自愈修复（读日志 + 改配置 + 验证）
- 系统级 Persona / 记忆 / Skill 修改审查（§0.10）

**agent 典型场景**（其余所有 LLM 任务）：
- 搜索、分析、写作、翻译、摘要
- 单文件生成
- 对话式交互、问答

**机制**：
- `codex` / `claude_code` 均通过 Temporal Activity subprocess 调用，**绕过 OC，不需要 session 管理**
- 调用前 Activity 自动注入必要上下文（MEMORY.md 内容 + 对应 skill 内容 + Skill Graph 邻居列表），context 保持精准最小
- subprocess 完成后 Activity 收集输出，写入 Artifact

### 1.4 Agent 架构：两层分离

daemon 采用两层 agent 架构：**L1 场景 agent**（面向用户）和 **L2 执行 agent**（面向任务）。

#### 1.4.1 L1 场景 agent

L1 agent 按场景划分，每个场景定义用户与 daemon 之间的主导权关系（见 §0.11 场景认知原则）。

| agent | 场景 | 关系动态 | 用户认知模式 | Mem0 积累内容 |
|---|---|---|---|---|
| `copilot` | 日常工作 | 用户主导，daemon 执行+建议 | 指挥、决策、关注结果 | 工作偏好、项目上下文、规划经验 |
| `mentor` | 学习指导 | daemon 引导，用户学习 | 学习、探索、接受评价 | 学习进度、理解水平、教学经验、英文写作纠正记录 |
| `coach` | 计划表现 | daemon 规划，用户执行 | 执行、突破、关注表现 | 训练数据、计划执行历史 |
| `operator` | 持续运营 | daemon 自主，用户监督 | 监督、审视、关注策略 | 运营策略、平台经验 |

L1 agent 特性：
- 4 个 L1 agent 并列，没有谁是"主"。用户自己选择去哪个场景。
- 每个 L1 是 OC agent，有 MCP/skill 访问权限，有独立的 SOUL.md（哲学层）和 SKILL.md（行为层）。
- 每个单实例，可多 session 并发。
- L1 session 由 API 进程管理（持久 session），不走 Temporal（见 §2.2, §3.3）。
- 所有 L1 共享基础能力：routing decision、Job DAG 规划、Replan Gate、用户意图解析。这些是原 counsel 的能力泛化，不再由单一 agent 持有。

#### 1.4.2 L2 执行 agent

L2 agent 按能力划分，执行具体任务。

| agent | 能力 | 默认模型方向 | Mem0 积累内容 |
|---|---|---|---|
| `researcher` | 搜索 + 分析 + 推理（外部信息获取、RAGFlow 检索、深度分析、方案论证） | analysis | 信源策略、搜索策略、分析框架 |
| `engineer` | 编码与技术任务（实现功能、调试、工具链） | analysis | 代码风格、技术决策偏好 |
| `writer` | 写作与内容生产（论文、文章、报告、对外文本） | creative | 写作风格、格式偏好 |
| `reviewer` | 质量审查（事实校验、逻辑一致性、风格合规） | review | 质量标准、常见失败模式 |
| `publisher` | 对外发布（Dev.to/Hashnode/GitHub Pages）、消息整理、通知 | local-light | 渠道格式、发布风格、跨平台适配 |
| `admin` | 体检、诊断、自愈、暖机主导（Stage 3+）、skill 管理 | local-heavy | 系统基线、体检历史、参数校准记录 |

L2 agent 特性：
- L2 机制不变：1 Step = 1 Session，Temporal 管理（见 §3.3）。
- 每个 L2 有独立的 OC workspace、TOOLS.md、Mem0 memory bucket（`agent_id` 隔离）。

#### 1.4.3 两层关系

- L1 定义"怎么和用户协作"，L2 定义"怎么把事情做出来"。
- L1 简单任务自己做（route=`direct`），复杂任务派给 L2。
- L1→L2 不走 OC spawn；L1 输出结构化动作 → daemon 创建 Task/Job/Step → Temporal → L2 OC session。
- L2 结果完成后，daemon 主动往 L1 对话推消息，不需要用户先说话。

L1 规划时指定 `agent`（L2）+ 可选 `model` override：
```json
{"id": 3, "goal": "write literature review", "agent": "writer", "depends_on": [1, 2]}
{"id": 4, "goal": "verify key claims", "agent": "reviewer", "depends_on": [3]}
```
`model` 字段省略时使用 L2 agent 默认模型；指定时通过 OC `sessions_spawn model?` 参数覆盖。

FINAL 规则：
- 4 L1 + 6 L2 = 10 个 agent 是固定预创建集合；扩能力靠 skill / MCP，不靠动态生 agent。
- reviewer 只指出问题，不直接修复产物。
- counsel 消失，其能力（routing decision、DAG 规划、Replan Gate、用户意图解析）泛化为所有 L1 的共享基础能力。
- L1 不按"规划什么"区分——那是任务导向思维。L1 按场景区分，底层机制完全一样（OC session + MCP + L2 调度 + Temporal），上层行为由 SOUL.md + SKILL.md 决定。

### 1.5 知识层级

正式优先级：

`Guardrails > External Facts > Persona > System Defaults`

含义：
- Guardrails 决定安全、隐私、底线，不被用户偏好覆盖。
- 外部事实决定可验证事实，不被 Persona 改写。
- Persona 只塑造风格与选择，不塑造事实。
- 默认值只在没有更高优先级约束时生效。

### 1.6 基础设施组件

| 组件 | 说明 |
|---|---|
| **Plane** | 开源任务管理平台。Task/Project CRUD + 前端 + 管理界面 |
| **Temporal** | Workflow 编排 + Schedules（定时调度） |
| **Langfuse** | LLM 可观测性（追踪 + 统计 + 评估） |
| **MinIO** | S3 兼容对象存储 |
| **RAGFlow** | 文档解析 + 分块 + 向量检索 |
| **Mem0** | 统一记忆层（persona + 规划经验 + 对话记忆） |
| **NeMo Guardrails** | 安全规则引擎（Colang DSL，零 token） |
| **pgvector** | PostgreSQL 向量搜索扩展 |
| **PG LISTEN/NOTIFY** | PostgreSQL 原生事件通知 |
| **Firecrawl** | 网页 → 干净 Markdown（省 80%+ token） |

### 1.7 系统维护

三类定时 Job（Temporal Schedule）：

**清理 Job**（每日）：
- 清理 knowledge_cache 过期条目（同步删除 RAGFlow 文档）
- 清理 Mem0 中 90 天未触发的记忆（CC/Codex 审查后自动清理，见 §0.10）
- 归档过期 Job/Artifact（见 §6.12 数据生命周期）
- Quota reset

**备份 Job**（每日）：
- PG 增量备份（见 §6.11 备份制度）
- MinIO 关键 bucket 快照

**本地后台任务**（每日/每周/每月，见 §5.9）：
- 记忆蒸馏（合并、提炼、淘汰碎片记忆）
- 知识库维护（审查、交叉验证、信源可靠性）
- 系统自省（skill 效果分析、失败 pattern、写作风格更新、周期性系统快照）
- 全部由本地 Ollama 执行，零 API 成本

不再使用旧版 7 个 Spine routines。

### 1.8 废弃术语

以下旧词只留在 archive 中，不再在正文和代码中使用：

| 旧术语 | 替代 |
|---|---|
| Folio / Slip / Writ / Deed / Move | Project / Task / (删除) / Job / Step |
| Brief / Wash | (删除) |
| Offering | Artifact |
| Psyche / Instinct / Voice / Preferences / Rations | Guardrails / Persona / Quota |
| Ledger / SourceCache | (Langfuse + PG) / Knowledge Base |
| Spine / Nerve / Cortex / Ward / Canon | 删除 |
| scout / sage | scholar → researcher（合并后再改名） |
| counsel | L1 agent（能力泛化为 4 个 L1 共享基础） |
| scholar | researcher |
| artificer | engineer |
| scribe | writer |
| arbiter | reviewer |
| envoy | publisher |
| steward | admin |
| Herald / Cadence / Ether / Trail / Portal / Console / Vault / Memory / Lore | 见历史文档 |
| errand / charge / endeavor / glance / study / scrutiny / Pact | 删除 |
| Draft（daemon 自管） | Plane DraftIssue |
| Trigger（一等实体） | Plane IssueRelation + Temporal Schedule |
| Retinue / Context / Design | 删除（不需要独立名字） |

---

## §2 系统架构

### 2.1 总体目标

daemon 是一个"Plane 作为协作前端 + daemon 作为执行内核 + OpenClaw 作为 agent runtime"的双层系统。它的目标不是提供另一套 UI，而是把任务组织、执行、知识、反馈、追踪、暖机和自愈统一成一条可追溯链路。

### 2.2 进程与职责边界

| 组件 | 职责 |
|---|---|
| Plane 前端 / API | Task / Project / Draft 的主协作界面和持久对象 |
| daemon API（FastAPI） | webhook 接收、胶水 API、WebSocket、L1 OC session 管理（持久对话）、轻量查询接口 |
| daemon Worker（Temporal Worker） | Temporal activities、Plane 回写、L2 OC 调用、Mem0、NeMo、MCP、MinIO、对话压缩 |
| Temporal Server | Job / Step 编排、重试、暂停、调度 |
| OpenClaw Gateway | agent session runtime，4 L1 + 6 L2 agents |
| PostgreSQL + pgvector | daemon 数据、Plane 数据、event_log、knowledge_cache |
| MinIO | Artifact 全文对象存储 |
| Langfuse + ClickHouse | LLM trace / 监控 |
| RAGFlow + Elasticsearch | 文档解析 + 分块 + 向量检索 |
| Firecrawl | 网页 → 干净 Markdown |

FINAL 规则：
- API 进程与 Worker 进程不直接共享内存状态。
- 两者通过 PG、Temporal、Plane、MinIO 这些正式边界协同。
- Job 级逻辑只能由 Worker + Temporal 持有，不能散落在 Plane webhook handler 中。
- 不允许在 API 进程里运行 Temporal workflow 或 L2 执行链。L1 对话不算"长执行链"——L1 session 由 API 进程持有是正式设计。
- L1 session 数据流：用户消息 → WebSocket → API 进程 → `sessions_send`(L1 OC session) → 流式响应 → WebSocket → 用户。L1 输出 structured action → API 创建 Temporal workflow → Worker 执行 L2。

### 2.3 架构总览图

```
┌────────────────────────────────────────────────────────────────────┐
│                          用户界面                                    │
│  桌面客户端（Tauri）：4 个场景对话 + 场景 panel                      │
│  Telegram：4 个独立 bot DM（copilot / mentor / coach / operator）   │
└──────────┬──────────────────────────────┬──────────────────────────┘
           │ WebSocket × 4                │ Telegram API × 4
┌──────────▼──────────────────────────────▼──────────────────────────┐
│                      daemon API（FastAPI）                           │
│  L1 OC session × 4（copilot / mentor / coach / operator）          │
│  持久 session，daemon 管理压缩                                       │
│  + Plane webhook handler + 胶水 API                                 │
│  L1 输出 structured action → 创建 Temporal workflow                 │
└──────────┬────────────────────────────┬───────────────────────────┘
           │                            │
┌──────────▼──────────┐      ┌──────────▼──────────────────────┐
│    PostgreSQL        │      │   Temporal Server                │
│  + pgvector          │      │   Schedules（定时调度）           │
│  + LISTEN/NOTIFY     │      │   Workflows + Activities          │
│  + conversation_*    │      │   （L2 执行 + OC 调用）           │
│  + knowledge_cache   │      └──────────┬─────────────────────┘
└──────────────────────┘                 │
                              ┌──────────▼──────────────────────┐
                              │   daemon Worker（Temporal）       │
                              │   L2 OC agents × 6               │
                              │   (researcher/engineer/writer/    │
                              │    reviewer/publisher/admin)      │
                              │   1 Step = 1 Session              │
                              │   + NeMo Guardrails（嵌入进程）   │
                              │   + Mem0（嵌入进程）              │
                              └──────────┬──────────────────────┘
                                         │
           ┌─────────────────────────────┼───────────────────┐
           │                             │                   │
┌──────────▼──────┐  ┌──────────────────▼───┐  ┌───────────▼──────┐
│  RAGFlow         │  │  MinIO                │  │  Langfuse         │
│  (文档解析+检索)  │  │  (文件存储)            │  │  (LLM 追踪)       │
│  + Elasticsearch │  │  Plane/Langfuse 共用   │  │  + ClickHouse     │
└─────────────────┘  └──────────────────────┘  └──────────────────┘

Plane（后端数据层，用户不直接使用）：
  Task / Project / Draft 持久对象存储 + 管理界面（面向 CC/admin）

MCP Tools（零 token 能力扩展）：
  Firecrawl(网页全文) / Semantic Scholar(学术搜索) / tree-sitter(代码索引)
  GitHub MCP / Telegram OC channel / LaTeX+BibTeX / matplotlib+mermaid
  Google Docs / intervals.icu / 社媒平台 API（按场景配置）
```

### 2.4 网络拓扑

```
                    ┌──── 用户 ────┐
                    │              │
          ┌─────────▼─────────┐  ┌▼──────────────┐
          │ 桌面客户端(Tauri)   │  │ 4× Telegram Bot│
          │ 4 场景对话+panel   │  │ (独立 DM)      │
          └─────────┬─────────┘  └┬──────────────┘
                    │ WebSocket    │
          ┌─────────▼─────────────▼──────────────┐
          │ daemon API (FastAPI) :8100             │
          │ 4× L1 OC session（持久）               │
          │ Plane webhook handler                  │
          └──────┬──────────┬───────────────────┘
                 │          │
     Plane ──────┘   ┌──────▼────────┐
     webhook         │ Temporal Server│
                     │ :7233          │
                     └──────┬────────┘
                            │
                     ┌──────▼────────┐    ┌──────────┐
                     │ daemon Worker  │────│ OC Gateway│
                     │ (Temporal)     │    │ 6× L2    │
                     └──────┬────────┘    └────┬─────┘
                            │                  │
              ┌─────────────┼──────────┐  ┌────▼─────┐
              │             │          │  │MCP servers│
         ┌────▼───┐  ┌─────▼──┐  ┌───▼──────┐  └──────────┘
         │ PG     │  │ MinIO  │  │ Langfuse │
         │ :5432  │  │ :9000  │  │ :3001    │
         └────────┘  └────────┘  └──────────┘
```

### 2.5 Plane 对象映射

| daemon 对象 | Plane 对象 | 说明 |
|---|---|---|
| `Project` | `Project` | 正式承载对象 |
| `Draft` | `DraftIssue` | 转正前候选项 |
| `Task` | `Issue` | 用户主要编辑对象 |
| `Job` | 无 | daemon PG + Temporal |
| `Step` | 无 | Job 内部执行单元 |

### 2.6 外部出口分工

| 出口 | 方式 | 规则 |
|---|---|---|
| Telegram | OpenClaw 原生 channel（announce） | 有原生就优先原生 |
| GitHub | MCP server（@modelcontextprotocol/server-github） | OC 无原生时走 MCP |
| 社交媒体（X/Twitter 等） | MCP server（API 可用的平台） | 按平台 API 封装 MCP tool |
| 需登录平台（小红书等） | Playwright MCP（浏览器自动化） | 无 API 的平台走浏览器 |
| 本地应用 | direct Step（`open`、VS Code 等） | 零 token |
| 其他网页 / 文档 | researcher + Firecrawl / RAGFlow | 以获取和引用为主 |

FINAL 规则：能用 OC 原生出口的，不再自建旁路通知服务。publisher（L2）是唯一对外出口 agent。

**[DEFAULT]** 出口平台列表不固定。暖机 Stage 0 信息采集时确认用户实际使用的发布平台，Phase 5 按需配置对应 MCP server 或 Playwright 流程。上表只是预置项，不是完整清单。

#### 2.6.1 MCP Server 完整清单

MCP server 是 daemon 连接外部世界的标准接口。完整列表见参考文档附录 B.7。按功能分类：

| 类别 | MCP Server | 方案 | 优先级 |
|---|---|---|---|
| **搜索** | brave-search | `@anthropic-ai/mcp-server-brave-search` | P0 |
| **搜索** | semantic-scholar | 自写（S2 API，无需 key，共享 1000 req/s 池） | P0 |
| **网页** | firecrawl | 自写（自部署 Docker） | P0 |
| **网页** | playwright | `@anthropic-ai/mcp-server-playwright` | P0 |
| **代码** | github | `@modelcontextprotocol/server-github` | P0 |
| **代码** | filesystem | `@anthropic-ai/mcp-server-filesystem` | P0 |
| **代码** | code-functions | 自写 | P0 |
| **Google** | google-calendar | Google Calendar API（自写） | P0 |
| **Google** | google-docs | Google Docs API（自写） | P0 |
| **Google** | google-drive | Google Drive API（自写） | P0 |
| **Google** | gmail | Gmail API（自写） | P1 |
| **学术** | paper-tools | 自写 | P0 |
| **学术** | arxiv | 自写（arXiv API） | P1 |
| **学术** | openalex | 自写（OpenAlex REST API，免费无 auth） | P1 |
| **文献** | zotero | 社区包（mcp-server-zotero） | P1 |
| **信息源** | rss-reader | 自写（feedparser + OPML） | P1 |
| **信息源** | hackernews | 自写（Firebase API） | P1 |
| **社媒** | twitter-x | 自写（Twitter API v2） | P1 |
| **社媒** | reddit | 自写（praw） | P1 |
| **运动** | intervals-icu | 自写（REST API） | P1 |
| **可视化** | matplotlib | 自写（Python） | P1 |
| **可视化** | mermaid | 自写（mermaid-cli） | P1 |
| **可视化** | echarts | `apache/echarts-mcp`（官方） | P1 |
| **可视化** | kroki | 自写（Kroki API，统一 20+ 图表格式） | P1 |
| **英文写作** | languagetool | 自写（self-hosted Docker，REST API） | P1 |
| **博客发布** | devto | 自写（Forem API v1） | P1 |
| **博客发布** | hashnode | 自写（GraphQL API） | P1 |
| **学术** | unpaywall | 自写（DOI→免费 PDF，100K/天） | P1 |
| **学术** | crossref | 自写（1.8B 引用元数据，免费） | P1 |
| **天气** | openweathermap | 社区包（`mcp-openweathermap`） | P1 |
| **运动** | strava | 自写（REST API，OAuth 2.0） | P1 |
| **学术** | dblp | 社区包（`mcp-dblp`，npm） | P1 |
| **学术** | academix | 社区包（`Academix`，npm，聚合 OpenAlex+DBLP+S2+arXiv+CrossRef） | P1 |
| **ML** | huggingface | 自写（HuggingFace Hub API，模型/数据集/Spaces） | P1 |
| **开发** | libraries-io | 自写（依赖监控，40M+ 包，跨平台） | P1 |
| **刷题** | leetcode | 社区包（`@jinzcdev/leetcode-mcp-server`，题库搜索/出题） | P1 |
| **系统** | macos-control | 自写（AppleScript/osascript） | P1 |
| **排版** | latex | 自写（tectonic/pdflatex） | P2 |
| **排版** | typst | 自写（typst CLI，现代 LaTeX 替代） | P2 |
| **容器** | docker | 自写（Docker Engine API） | P2 |
| **学术** | core | 自写（4.3 亿 OA 论文，REST API） | P2 |
| **可视化** | excalidraw | 社区包（excalidraw-mcp，白板/手绘） | P2 |
| **信息源** | newsdata | 自写（NewsData.io，新闻聚合） | P2 |
| **ML** | kaggle | 自写（数据集/竞赛/Notebook） | P2 |

Google 四件套（Calendar/Docs/Drive/Gmail）共享同一个 GCP project 的 OAuth credential。

### 2.7 外部知识获取

| 组件 | 说明 |
|---|---|
| 搜索 MCP servers | researcher 通过 MCP 工具搜索外部信息（通用搜索 + Semantic Scholar 学术搜索） |
| Playwright MCP | 浏览器自动化（需要登录、JS 渲染、点击交互的页面）。researcher 在 Firecrawl 无法处理时使用 |
| Firecrawl | 网页 → 干净 Markdown（去 HTML 噪音，省 80%+ token），自部署 Docker。优先于 Playwright |
| RAGFlow | PDF/文档全文解析 → 语义分块 → 向量检索。论文写作必需（表格/图表/公式理解） |
| knowledge_cache（PG） | TTL 过期管理。按 source_tiers.toml 分级（A=90天, B=30天, C=7天） |
| source_tiers.toml | 外部源信任分级（A/B/C），NeMo Guardrails 规则依赖 |
| sensitive_terms.json | 隐私过滤，NeMo Guardrails input rail 执行 |

知识获取流程：
```
researcher → MCP search / Semantic Scholar → URL + 摘要
  ↓ 需要全文时
  ├── PDF → RAGFlow 解析/分块/存储
  └── 网页 → Firecrawl → 干净 Markdown → RAGFlow 或直接存 knowledge_cache
  ↓
其他 agent → RAGFlow 检索 / knowledge_cache 向量检索 → 精确命中
```

内外分野：
- **外部知识**：事实性的、可引用的、可验证的。来源 = MCP search → RAGFlow/knowledge_cache。有 source_url、source_tier。
- **内部知识**：个人化的、累积的。来源 = Mem0（agent memory）。塑造风格和方式，不塑造内容和事实。

#### 2.7.1 信息监控基础设施

**FINAL 规则：信息监控是系统级基础设施，不属于任何一个场景。** 与 Temporal、PG、Mem0 同层级。4 个 L1 平等地从全局存储中检索信息，在各自对话中根据关系动态自然使用。

信息监控 = 定时从外部源拉取信息 → 筛选分级 → 存储到全局可查的知识库。

```
Temporal Schedule（定时触发 InfoPullWorkflow）
    │
    ├── Activity: pull_sources（direct 类型，零 token）
    │   调 MCP tools 拉取各信息源原始数据
    │
    ├── Activity: triage_results（agent 类型，调 researcher）
    │   分析内容与用户上下文的关联性，打标分级
    │
    ├── Activity: store_results（direct 类型，零 token）
    │   🔴紧急 → 全文存 RAGFlow
    │   🟡相关 → 全文存 RAGFlow
    │   🔵有价值 → 摘要存 knowledge_cache
    │   ⚪低价值 → 丢弃
    │
    └── Activity: notify_urgent（direct 类型，零 token）
        🔴紧急 → Telegram 通知
```

**信息源分类与拉取频率**：

| 类别 | 来源 | 频率 |
|---|---|---|
| 学术 | arXiv, Semantic Scholar alerts, OpenAlex | 每 4 小时 |
| 业界 | Google AI Blog, Meta AI, Anthropic, OpenAI, DeepMind 等 | 每 4 小时 |
| 开源 | GitHub releases（关注的 repo）, GitHub trending | 每 6 小时 |
| 技术社区 | HN, Reddit | 每 2 小时 |
| 技术博客 | 个人博客, Substack, 知乎专栏 | 每 4 小时 |
| 社媒 | Twitter/X 关注列表 | 每 2 小时 |
| 反爬平台 | Reddit, 知乎, 小红书（via RSSHub） | 每 2 小时 |
| 权威机构 | NIST, IEEE, ACM, Nature, Science | 每日 |
| 天气 | OpenWeatherMap（户外运动天气） | 每 3 小时 |
| 运动 | intervals.icu | 每日 |

**订阅管理**：用户在任何场景对话中都可以管理订阅（"帮我关注这个库的 release"），订阅存入 PG 表 `info_subscriptions`（全局，不按场景分区）。

**4 个 L1 如何使用信息**取决于各自的关系动态，不取决于信息分类。同一条信息（比如"依赖库有 breaking change"），copilot 以协作者身份提出，mentor 借机教学，coach 关注计划影响，operator 可能已自动处理。

**文献管理**：Zotero（元数据管理：收藏/标注/分组/引用格式）+ RAGFlow（全文检索：PDF 解析/语义搜索/跨文献检索），两者互补，全局基础设施，不按场景分区。

**博客发布基础设施**：writer 产出 Markdown → publisher 跨平台发布。渠道优先级：① Hugo + GitHub Pages（canonical，完全所有权）② Dev.to（Forem API v1，技术社区）③ Hashnode（GraphQL API，开发者社区）。publisher 写一次 Markdown，自动适配各平台格式和 front matter。

**英文写作辅助**：mentor 场景集成 LanguageTool（self-hosted Docker，零 API 成本，无限调用）。用户每次英文输出（论文、博客、GitHub）均经过 LanguageTool 检查语法/风格/学术用词 → mentor 解释错误模式 → Mem0 记录用户常犯错误 → 逐步减少同类问题。与 Stage 0 采访确认的"渐进式英文浸泡"策略配合。

### 2.8 模型策略

每个 agent 有默认模型。L1 可在规划时通过 `model` 字段覆盖（OC `sessions_spawn model?`）：

| 层级 | Agent | 默认模型 | 理由 |
|---|---|---|---|
| L1 | copilot / mentor / coach / operator（对话） | MiniMax M2.5（fast） | 对话快响应，用户在等，Coding Plan 包月 |
| L1 | copilot / mentor / coach / operator（routing） | Qwen3.5-Plus（analysis） | 规划质量优先，routing 是执行链起点，选错全白做 |
| L2 | researcher | Qwen3.5-Plus（analysis） | 搜索+深度分析，强推理 |
| L2 | engineer | Qwen3.5-Plus（analysis） | 代码质量需要强推理，Step 异步执行不需要秒回 |
| L2 | writer | GLM-5（creative） | 写作人感最强 |
| L2 | reviewer | GLM-5（review） | 审查严谨，需要判断力 |
| L2 | publisher | Ollama qwen2.5:7b（local-light） | 格式化+发布，简单执行任务 |
| L2 | admin | Ollama qwen2.5:32b（local-heavy） | 深度诊断+改进建议，后台运行不需要速度 |
| — | — | 本地 nomic-embed-text（primary）/ 智谱 embedding-3（fallback） | Embedding |
| Internal | （无 agent session） | Ollama 本地模型 | 内部任务零 API 成本（6 类任务走 32b，2 类走 7b） |

**[DEFAULT]** 模型名称和 provider 绑定保持配置化，不在正文硬编码到具体厂商 SKU。上表记录当前选择，具体模型表见参考文档附录 B 和运行时配置 `config/model_policy.json` v7。

**成本模型**：
- **MiniMax M2.5**：Coding Plan 包月（¥49/月），4 agent（L1×4 对话），边际成本为零。
- **Qwen3.5-Plus**：按 token 计费，3 agent（L1 routing + researcher + engineer），估算 ¥40-80/月。Coding Plan 有货时可切换。
- **智谱 GLM-5**：按 token 计费，2 agent（writer + reviewer），估算 ¥20-50/月。Coding Plan 有货时可切换。
- **Ollama**：本地模型，零成本。publisher（7b）+ admin（32b）+ 6 类内部任务（32b/7b）+ embedding primary。
- **CC/Codex**：Max 5x / Plus 订阅配额，仅限 §1.3 定义的 execution_type 场景（复杂规划/审查/编码）。
- **DeepSeek**：dormant（备用），无 agent 使用，registry 保留但不在 provider_route 中。

#### 2.8.1 内部任务本地模型路由

系统内部任务（triage、guardrails、replan gate、compression 等）不需要 API 级模型质量，使用本地 Ollama 模型执行，零 API 成本：

| 任务 | 模型别名 | 说明 |
|---|---|---|
| infopull_triage | local-heavy（32B） | 信息分级需要理解力 |
| infopull_classify | local-light（7B） | 简单分类 |
| guardrails_check | local-light（7B） | NeMo 后的二次检查 |
| replan_gate | local-heavy（32B） | 偏离判断需要推理 |
| knowledge_extract | local-heavy（32B） | 结构化提取 |
| feedback_classify | local-light（7B） | 反馈分类 |
| health_check_quality | local-light（7B） | 体检指标评估 |
| session_compress | local-heavy（32B） | 会话压缩需要总结能力 |
| l1_failure_judgment | local-heavy（32B） | 失败原因分析 |

路由逻辑：`config/model_policy.json` 的 `task_model_map` 定义任务→模型映射，`services/llm_local.py` 封装 Ollama API 调用。本地模型优先，失败时 fallback 到云端模型。

Ollama 原生安装（非 Docker），利用 Apple Silicon Metal GPU 加速。模型：
- `local-heavy`：qwen2.5:32b（~10 tok/s on M4 Pro）
- `local-light`：qwen2.5:7b（~35 tok/s on M4 Pro）
- `local-embedding`：nomic-embed-text（768d，47ms on M4 Pro，embedding primary）

### 2.9 持久化边界

FINAL 规则：
- Plane 持 Task / Project / Draft 的协作面信息。
- daemon PG 持 Job / Step / Artifact 元数据、事件、扩展字段。
- MinIO 持 Artifact 全文、大对象、审计版本。
- Langfuse 持 trace，不作为业务真相源。
- Mem0 持 Persona 和记忆，不持业务事实。

---

## §3 执行模型

> **理论背景**：本执行模型属于 HTN（Hierarchical Task Network）+ Orchestration 范式。
> 参考：LLMCompiler（Berkeley, DAG 并行执行）、GoalAct（全局规划+分层执行, NCIIP 2025 Best Paper）、
> Plan-and-Act（动态重规划, ICML 2025）、AgentOrchestra + TEA Protocol（层次化多 Agent, GAIA SOTA）。

### 3.1 Routing Decision 与入口路径

用户消息发送到对应场景的 L1 agent 后，L1 自行做 routing decision。L1 作为 LLM 自行判断，不使用规则分类，输出结构化 routing decision：

```json
{
  "intent": "用户想知道明天有没有雨",
  "route": "direct",
  "model": "fast",
  "task": "查询天气"
}
```

或复杂任务：
```json
{
  "intent": "写一篇关于 LLM agent 执行模型的综述论文",
  "route": "project",
  "tasks": [...]
}
```

输出只允许三类路径：

| route | 行为 | 说明 |
|---|---|---|
| `direct` | 跳过 Project/Task，直接创建单 Step ephemeral Job | 一步能完成 |
| `task` | 创建 1 个 Task + 首个 Job | 多步但目标明确 |
| `project` | 创建 Project + Task DAG + 入口 Task 首个 Job | 长期、多阶段 |

三条路径使用同一个执行引擎（Job → Step），只是入口点不同。L1 的 SKILL.md 定义输出格式，不定义决策逻辑。

FINAL 规则：
- `direct`：一步能完成，不创建 Task / Project。
- `task`：创建 1 个 Task，再立即创建其首个 Job。
- `project`：先创建 Project，再创建 Task 集合与依赖关系，然后按入口 Task 启动首个 Job。
- routing decision 失败时，不允许系统静默自创第四条路径。

FINAL 规则：Plane 对象的创建责任属于 L1 的规划结果；Worker 负责执行对应的 Plane API / MCP 调用，不在 webhook handler 中偷偷生成对象。

FINAL 规则：`route="direct"` 统一生成 1 个 Step 的 ephemeral Job，并持久化进 `jobs` 表，使用 `is_ephemeral=true` 标记；这样保留 trace、失败补偿和审计能力，同时不污染用户的 Task 列表。

FINAL 规则：
- `route="task"` 时：先创建 Issue，再写入 daemon_tasks，再冻结首个 Job 的 `dag_snapshot`。
- `route="project"` 时：先创建 Project，再批量创建 Task / 依赖关系，再启动入口 Task 的首个 Job。

### 3.2 Step 粒度与执行原则

**1 Step = 1 目标。** 可调用任意 agent 和 tool。

#### 3.2.1 粒度原则

context 窗口是 Step 粒度的硬上界，不是目标大小。

**规则一：能在一个 context 内完成的，不拆。**
每个 Step 边界都是信息损耗点——Step A 的产出必须压缩为 Artifact 摘要才能传给 Step B，压缩必然有损。Step 越少，摘要边界越少，信息损耗越小。L1 应按**语义边界**分 Step（什么逻辑上属于一起），不按大小分。

**规则二：上界 = context 窗口 100%（减固定 overhead）。**
固定 overhead（MEMORY.md + Mem0 注入 + Step 指令）约 800 tokens，其余全部可用于任务。不人为预留缓冲——任务大小是变量，静态预留只会让缓冲永远闲置。溢出由运行时动态监测处理（见 §3.4 token 管控），不靠提前缩水。

**规则三：确定性操作用 direct，不用 agent。**
如果一个操作的输出完全由输入决定（文件读写、API 调用、格式转换），用 `direct`，零 token。LLM 只处理需要推理的部分。

### 3.3 Session 模型

daemon 有两种截然不同的 session 模型，分别服务 L1 和 L2。

#### 3.3.1 L1 Session（持久对话）

**核心原则：持久 OC session，daemon 全权管理上下文。**

- 4 个 L1 agent，每个 1 个 instance，由 API 进程管理
- 连续对话中：直接 `sessions_send`，零额外开销
- session 接近上限时：daemon 做压缩（不等 OC compaction），开新 session 接上
- 一个 L1 agent 可以有多个 OC session 串联，等效于 context 容量翻倍
- 旧 session 保持不关闭，原文完整保留

daemon 在 OC 触发 compaction 之前主动介入（`contextTokens` 到 70% 时），防止 OC 自带压缩丢失重要信息。

**多 session 串联方案**：
```
copilot session 1 (满了，保持，原文完整)
copilot session 2 (满了，保持，原文完整)
copilot session 3 (当前活跃)
```
daemon 控制当前消息发到哪个 session、什么时候开新 session、需要引用历史时从 PG 拉。

**对话历史 4 层压缩**（daemon 侧）：

| 层 | 内容 | 存储 |
|---|---|---|
| 原文层 | 最近 N 轮完整对话 | PG `conversation_messages` |
| 摘要层 | 较早对话的压缩摘要 | PG `conversation_digests` |
| 决策层 | 承诺、决策、行动项单独提取 | PG `conversation_decisions` |
| 记忆层 | 跨会话长期经验 | Mem0 |

**scene 是过滤列，不是硬分区。** 正常操作查本 scene，daemon 注入层可跨 scene 查（按 project_id / tags）。decisions 表尤其需要跨 scene 可查——一个决策和哪个主题相关比它在哪个场景产生更重要。

#### 3.3.2 L2 Session（短命执行）

**核心原则：1 Step = 1 Session。**

context 窗口大小 = 任务粒度上限。每个 Step 在全新 context 内完成，不积累前序 Step 的对话历史。串行/并行 Step 均独立 session，不共享。

- 6 个 L2 OC agent，每个 1 个 instance
- 每个 Step 执行时 `sessions_spawn` 创建独立 session，Step 完成后关闭
- Session key 格式：`{agent_id}:{job_id}:{step_id}`
- 并行 Step 各自独立 session，同时运行

**L2 Session 内容构成**（每次 session 启动时注入，total ≤ 800 tokens）：
```
MEMORY.md（≤ 300 tokens，只放每次都必须的身份+最高优先级规则）
+ Mem0 按需检索（50-200 tokens，当前任务相关记忆）
+ Step 指令（结构化 JSON，目标明确）
+ 上游 Artifact 摘要（如有依赖）
```

#### 3.3.3 通用规则

**MEMORY.md 规则**：每个 agent（L1/L2）的 MEMORY.md ≤ 300 tokens。只放：身份定义 + 最高优先级行为规则。任务偏好、风格、规划经验全部放 Mem0，不放 MEMORY.md。MEMORY.md 是跨任务静态内容，任务执行期间不写入，不存在并行任务污染问题。

**OC 限制**：
- Subagent 不加载 MEMORY.md，不能读写 Mem0
- 不存在 memory_write tool
- Session-memory hook 仅在 `/new` 或 `/reset` 时触发

#### 3.3.1 Step 内 Subagent 并行模式

**不需要 agent 池。** 10 个 OC agent workspace（4 L1 + 6 L2），每个 workspace 可同时运行多个 session，并发度由 `maxChildrenPerAgent` / `maxConcurrent` 控制，暖机时校准。

agent 在执行 Step 时，可以通过 `sessions_spawn` 在 Step 内部并行处理子任务。这是 skill-based 模式：agent 自己决定是否并行，L1 只负责 Step 级别的任务分解。

| 模式 | `maxSpawnDepth` | 行为 |
|---|---|---|
| Leaf（默认） | 1 | agent 不 spawn subagent，所有工具调用在主 session 内串行 |
| Orchestrator | 2 | agent 可 spawn subagent 并行处理子任务，自己作编排器 |

Subagent 限制：
- Subagent 不加载 MEMORY.md，不能读 Mem0 → 父 session 必须通过 `attachments` 或任务描述注入必要上下文
- 结果通过 announce step 异步回传父 session
- spawn 立即返回（非阻塞），父 session 等待 announce
- `cleanup: "delete"` 避免 session 泄漏（默认 `"keep"`）
- 最大嵌套 5 层，推荐不超过 2 层

### 3.4 Token 管控机制

主动参与，不被动等 context 满。

| 机制 | 配置 | 作用 |
|---|---|---|
| `runTimeoutSeconds` | 按 Step 类型设定（search: 60s, writing: 180s, review: 90s） | 硬超时，防止 agent 无限循环 |
| token budget 声明 | Step 指令中明确："请在 X tokens 内完成" | agent 自律收敛 |
| OC quota | `openclaw.json` 配置每 agent 的 token 日上限 | 防止单 agent 失控 |
| Langfuse 监控 | 单 Step token 消耗 > 阈值（按类型定）→ 告警 | 暖机后用于发现异常 Step |
| `contextPruning: cache-ttl` | 5 分钟 cache TTL | 裁剪旧 tool results，减少无效 context |
| `maxSpawnDepth` | 默认 2（orchestrator 模式） | 见 §3.3.1 |
| `maxChildrenPerAgent` | 默认 5，可调高 | 每个 session 的最大并发子 agent 数 |
| `maxConcurrent` | 默认 8，可调高 | 全局并发 session 上限，按机器和 LLM rate limit 校准 |

### 3.5 Job 生命周期

```
创建 Job（= 原子操作：创建 + 立即执行）
  │
  ▼
running（sub: queued → executing）
  │ Step 按 DAG 依赖执行（无依赖的 Step 并行，见 §3.7）
  │ 如果 Step 失败 → retry / replan / terminate（见 §3.8）
  │ 如果超时 → failed
  ▼
closed（sub: succeeded / failed / cancelled）
  │ 默认直接 closed(succeeded)，不等人
  │ requires_review: true 时 → 对话中提出确认，Job 不暂停（§4.8）
  ▼
Replan Gate（见 §3.9）→ 触发下游 Task
```

FINAL 规则：
- 执行 = 原子操作。不存在"只创建不执行"。
- 同一 Task 同一时刻只有一个非 closed 的 Job。
- rerun 始终创建新 Job；旧 Job 保留不覆盖。
- Job 成功默认直接关闭，不再等待旧式 settling 窗口。
- Step DAG 在 Job 创建时快照到 `dag_snapshot`。Task DAG 变更不影响进行中的 Job。

FINAL 规则：Plane 回写失败默认重试 5 次；若仍失败，则把 `plane_sync_failed=true` 写入 PG，并由补偿任务异步重试，不得因为单次回写失败篡改 Job 的业务结果。

FINAL 规则：
- `requires_review=true` 时，L1 agent 在对话中提出确认请求 + Telegram 通知（§4.8）。Job 不暂停，继续执行不依赖确认的后续 Step。
- 依赖确认结果的 Step 标记为 `pending_confirmation`，用户确认后继续。
- 用户否定后走 rework / terminate 决策。
- 长时间未确认时，L1 agent 根据 Persona 和历史偏好自行决定。

FINAL 规则：用户在对话中要求重新执行时，L1 agent 从对话上下文自行判断意图（否定/探索/细化等），据此决定学习信号类型和新 Job 的规划上下文。不硬编码为隐式否定。唯一硬约束：旧 Job 状态不回写，不管什么意图。

### 3.6 初始 DAG、上下文与 Re-run 规划

FINAL 规则：Task 的首个 Job 不是用空白上下文生成 DAG，而是基于：
- Plane Issue description
- Plane Issue Activity（对话历史）
- L1 的 Mem0 规划经验
- 对应 Project 的已知上下文（如有）

L1 每次规划新 Job 时，都重新组装上下文；L1 的对话上下文已在持久 session 中，规划上下文额外从 PG 和 Mem0 拉取。

#### 3.6.1 项目级上下文组装

L1 做项目级决策（初始规划、Replan Gate）时，需要看到项目全貌：

```
L1 项目级 prompt =
  Project goal（Plane Issue description）
  + 已完成 Task 列表（标题 + 状态 + 最终 Artifact 摘要）
  + 当前 Job 结果（Artifact 摘要，仅 Replan Gate）
  + 未完成 Task 列表（标题 + 依赖关系）
  + Mem0 规划经验（按需检索，~100-200 tokens）
```

token 控制：
- Artifact 摘要而非全文（~50 tokens/Task vs ~2000 tokens/Task）
- 10 个 Task 的 Project：~800 tokens context vs ~20000 tokens 全文
- 超过 20 个 Task 的 Project：只保留最近 5 个已完成 + 全部未完成

#### 3.6.2 Task 跨 Job 上下文连续性

同一 Task 多次执行（re-run、失败重试、定期重跑）时，不需要特殊上下文机制。L1 规划新 Job 时已经能拿到：
- 上一个 Job 的最终 Artifact（做了什么、产出是什么、失败原因）
- Task 对话历史（用户反馈）
- Mem0 规划经验（L1 从历史 Job 中积累的规划模式）

上下文在规划时重新组装，不靠 session 保活积累。

**FINAL 规则：Re-run 时最小化重做范围。** L1 规划 re-run Job 时，必须：
1. 分析前序 Job 的 DAG 和 Artifact，识别用户要求改动的部分
2. 只为需要重做的部分创建 Step，不重跑整个流程
3. 不需要重做的前序 Artifact 通过 `input_artifacts` 直接注入新 Step
4. 最终产物是完整的新版本（未改动部分 + 重做部分），不是补丁

示例：用户说"其他部分都挺好，就第三章重写一下" → L1 创建 1 个 Step（重写第三章），把前序 Job 的完整 Artifact 作为 input，指令明确"保留其他章节，只重写第三章"。不需要重跑研究、大纲、其他章节的 Step。

**此规则必须编码到 L1 的 OC skill 中（§9.10）**，不能只靠设计文档——LLM 不会自动执行未写入 prompt 的方法论。

### 3.7 Step 并行执行与 Artifact 传递

L1 在规划 Job 的 Step 列表时，输出 Step 之间的依赖关系：

```json
{
  "steps": [
    {"id": 1, "goal": "search related work", "agent": "researcher", "depends_on": []},
    {"id": 2, "goal": "search methodology", "agent": "researcher", "depends_on": []},
    {"id": 3, "goal": "search datasets", "agent": "researcher", "depends_on": []},
    {"id": 4, "goal": "synthesize findings", "agent": "writer", "depends_on": [1, 2, 3]}
  ]
}
```

执行逻辑：按依赖拓扑排序分层，同层 Step 并行执行。

```python
# Temporal Job Workflow
async def job_workflow(ctx, job_input):
    layers = topological_sort(job_input.steps)
    for layer in layers:
        results = await asyncio.gather(*[
            workflow.execute_activity(execute_step, step)
            for step in layer
        ])
    return results
```

并行执行原则：
- 依赖为空的 Step 可并行。
- 同层 Step 通过拓扑排序分层后并行执行。
- 并行 Step 的失败要统一汇总后交 L1 判断，不能各自偷偷吞异常。

#### 3.7.1 Artifact 传递

**Step 间（同 Job）**：
- Step 完成后，Artifact 存入 MinIO，元数据（path、type、summary）写入 PG `job_artifacts` 表
- 依赖 Step 启动时，从 `job_artifacts` 读取上游 Artifact 元数据，注入 agent prompt
- 大文件（PDF、代码仓库）只传 MinIO path + 摘要，不传全文（省 token）

```json
{
  "id": 4,
  "goal": "synthesize findings into literature review",
  "agent": "writer",
  "depends_on": [1, 2, 3],
  "input_artifacts": ["step:1:search_results", "step:2:methodology_notes", "step:3:dataset_list"]
}
```

**Job 间（同 Task 的多次执行）**：
- 前一个 Job 的最终 Artifact 自动成为新 Job 的初始上下文
- L1 在 Replan Gate 时可以看到前序 Job 的 Artifact 摘要

**Task 间（同 Project）**：
- chain 触发时，前序 Task 最终 Job 的 Artifact 摘要注入下游 Task 的首个 Job
- L1 在项目级规划时指定 Task 间数据流：`task_input_from: ["task:T1:final_artifact"]`

### 3.8 Step 失败处理

失败处理顺序固定：
1. **Retry**：Temporal RetryPolicy 自动重试
2. **Retry exhausted → L1 判断**：skip（不影响后续）/ replace（换方式）/ terminate（无法挽救）
3. **升级处理**：L1 标记 `requires_review: true` 时，在对话中提出确认请求（见 §4.8 非阻塞确认），Job 不暂停

Temporal 原生提供 checkpoint：每个 Activity（= Step）完成后自动记录 event history。Worker crash 后 Workflow replay 时，已完成 Step 不重新执行。

FINAL 规则：reviewer 的职责是指出问题，不直接生成修复版。

FINAL 规则：当 reviewer 审查失败并触发 rework 时，新 Step 使用全新 session；reviewer 结果以结构化 Artifact 注入 `input_artifacts`，而不是把旧 session 全量上下文复制过去。

#### 3.8.1 reviewer 触发策略

reviewer 不审查每个 Step（会使 token 翻倍且无必要）。三层分级：

| 层级 | 覆盖范围 | 机制 | Token 成本 |
|---|---|---|---|
| **1. 基础校验** | 所有 Step 输出 | NeMo Guardrails output rail 自动执行 | 零 |
| **2. 关键审查** | L1 标记 `requires_review: true` 的 Step | reviewer session 独立审查 | 中 |
| **3. 对外强制审查** | 所有发布到外部平台的 Step | Guardrails 规则强制触发 reviewer | 中 |

reviewer 独立性是其存在的核心价值——与产出 agent 完全隔离，消除自我审批偏差。reviewer 的 Mem0 积累质量标准和常见失败模式，与生产 agent 的记忆完全分离。

### 3.9 Dynamic Replanning（动态重规划）

**问题**：Task DAG 在 Job 创建时快照不可变。如果某个 Job 结果偏离 Project 目标，后续 Task 仍按原计划执行——浪费 token，产出无用。

**机制**：在 chain trigger 触发前插入 Replan Gate。

```
Job closed 事件
  │
  ▼
Replan Gate
  │ L1 收到：Project goal + 已完成 Task 摘要 + 当前 Job 结果
  │ L1 判断：结果是否偏离 Project goal？
  │
  ├─ 未偏离 → 继续触发下游 chain（现有逻辑不变）
  │
  └─ 偏离 → L1 输出 Task DAG diff
       │ 替换 Project 中尚未执行的 Task
       │ 已完成的 Task 不变
       └─ 新 DAG 继续走 chain
```

设计要点：
- Replan 不是每次都完整规划。L1 先做轻量判断（~200 tokens），偏离时才做完整重规划（~800 tokens）
- Replan 粒度 = Task 级别。Step 级别的调整由 Job 内 agent 自己处理
- Replan 输出是 diff（"修改后续 Task 列表"），不是从零规划
- 实现位置：Temporal activity，在 chain trigger activity 前执行
- Replan Gate 轻量判断优先使用本地模型（local-heavy via Ollama，零 API 成本），偏离时 fallback 到 analysis 模型做完整重规划

**[DEFAULT]** Replan Gate 输出使用 `operations[]` diff，默认 schema：`add` / `remove` / `update` / `reorder`，每个 operation 至少包含 `op` / `target_task_id` / `after_task_id` / `payload`。

FINAL 规则：Replan 批量写入采用顺序执行 + 失败补偿。Plane REST API 不支持事务，不追求原子性。每个 operation 独立写入，失败走已有的 5 次重试 + `plane_sync_failed` + 异步补偿机制（§6.6）。admin 体检可检测 Plane/daemon 状态漂移并修复。

### 3.10 Task 触发

FINAL 规则：Task 触发类型互斥，只允许以下三种之一：
- `manual`：手动执行
- `timer`：定时（Temporal Schedule）
- `chain`：前序 Job closed 后自动触发（经过 Replan Gate）

FINAL 规则：
- `chain` 默认要求前序 Task 的最近一个 Job 为 `closed/succeeded`。
- 前序失败不触发下游 Task，除非以后专门加"失败也触发"的设计，不允许实现者私自放宽。
- 触发本质上都是事件，只是事件源不同：`user.manual`、`time.tick`、`job.closed`。
- Task 的依赖关系不允许无声改写。任何正式变更都必须通过 Plane 对象变更 + 活动流记录体现出来。
- 触发是硬约束：前序未满足时，用户说"执行"会被 L1 拒绝并解释原因（不是静默忽略）。

### 3.11 运行时默认值与保留边界

FINAL 规则：Step / Job 时间预算、heartbeat、retry、quota 等参数统一进入参考文档附录 B；实现者应先按附录值完成重构，再通过暖机校准，而不是实现阶段自行拍脑袋。

FINAL 规则：多用户扩展路径见 §6.13.2。本轮所有表预留 `user_id`，不堵死未来扩展，但不实现完整多租户。

### 3.12 外部工具 Handoff 机制

daemon 的任务不一定以 Artifact 交付结束。有些任务的终态是**用户环境的状态变化**——项目在 VSCode 里打开了、浏览器打开了某个页面、本地应用处于可用状态。

**handoff = daemon 完成自己的工作后，把上下文无缝移交给外部工具，用户在新环境中继续。**

典型场景：
- 学习任务：daemon 搜索+写讲解+创建实验项目 → 打开 VSCode → Claude Code 已准备好学习上下文
- 编码任务：daemon 规划+脚手架 → 打开 VSCode → Claude Code / Codex 已准备好实现上下文
- 写作任务：daemon 搜索+结构化 → 打开本地编辑器 → 文档已准备好

**handoff 实现方式**：

| 目标工具 | handoff 步骤 | execution_type |
|---|---|---|
| Claude Code | 在项目根目录写 `CLAUDE.md`（注入任务上下文、背景、建议） | direct |
| Codex | 在项目根目录写 `AGENTS.md` 或等价上下文文件 | direct |
| VSCode | `open -a "Visual Studio Code" /path/to/project` | direct |
| 浏览器 | `webbrowser.open(url)` | direct |

FINAL 规则：
- handoff 是 Job DAG 的最后一个 direct Step，不是 Job 之外的附加动作。
- 上下文文件（CLAUDE.md 等）由前序 Step 的 Artifact 摘要自动生成，不需要用户手动编辑。
- 用户感知到的是"说了一句话 → 环境准备好了"，不感知 daemon 和外部工具之间的交接边界。

### 3.13 Step 内代码执行工具（code_exec）

§3.12 的 handoff 是"daemon 做完 → 移交给外部工具"。但有些场景下，agent 在 Step 内部就需要写代码并执行——不是移交，而是作为完成目标的手段。

**典型场景**：
- researcher 分析数据需要写 Python 脚本
- admin 诊断问题需要写修复脚本
- engineer 验证方案需要写原型代码

**FINAL 规则：代码执行是工具能力（MCP tool），不是角色定义。按 skill 需要在 TOOLS.md 中声明，不按 agent 身份限制。**

**实现**：`code_exec` MCP tool，封装 Claude Code CLI 和 Codex CLI。

```json
{"tool": "code_exec", "params": {"engine": "codex|claude_code", "prompt": "...", "cwd": "/path"}}
```

agent 在 OC session 中调用此 tool，由 MCP server 通过 subprocess 执行 `codex exec` 或 `claude -p`，返回结果。

**与 execution_type 的关系**：
| 场景 | 用什么 |
|---|---|
| 整个 Step 就是写代码 | L1 规划为 `execution_type: codex / claude_code` |
| Step 目标不是写代码，但过程中需要写一段 | agent 在 session 内调用 `code_exec` tool |

两者互补，不冲突。L1 不需要预判 agent 会不会写代码——如果 skill 需要，agent 自己调用。

**并发限制**：

FINAL 规则：CC 和 Codex CLI 各自最多 1 个并发实例。原因：
- Codex（GPT Plus plan）有 rate limit，并行调用会被限流
- Claude Code（Pro/Max plan）同理
- CC + Codex 可以同时各跑 1 个（不同 provider，不冲突）

实现：`code_exec` MCP server 内部维护信号量（`asyncio.Semaphore(1)` per engine），超出排队等待。此限制独立于 OC 的 `maxConcurrent`。

**暖机校准**：Stage 3 校准 skill 时自然发现哪些 agent 需要 `code_exec`，哪些不需要。初始建议配置：engineer、researcher、admin。

---

## §4 交互与界面契约

### 4.1 界面架构

**FINAL 规则：用户不直接使用 Plane。用户界面是自建桌面客户端 + 4 个 Telegram bot。**

| 层级 | 组件 | 面向 | 说明 |
|---|---|---|---|
| **用户层** | daemon 桌面客户端（4 个场景对话） | 用户 | 主交互入口 |
| **用户层** | 4 个 Telegram bot（独立 DM） | 用户 | 通知 + 移动端交互，与桌面完全同步 |
| **后端层** | Plane | CC/admin | 数据层 + 管理界面（Task/Project/Issue 存储与治理） |
| **后端层** | Langfuse / Temporal UI | CC/admin | 可观测性与调度管理 |

Plane 是后端数据基础设施，不是用户产品。用户不需要知道 Plane 存在。

### 4.2 桌面客户端

**FINAL 规则：客户端提供两种展示模式，4 个场景各自独立对话。外部内容通过原生应用打开（不分屏）。**

**原则：专业工具外部调起，客户端只做对话和状态聚合。窗口布局由用户通过 Stage Manager 自行管理（DD-80）。**

| 模式 | 技术 | 用途 |
|---|---|---|
| **对话** | 纯文本 | 和 L1 agent 交流（4 个独立对话） |
| **场景 panel** | 自研 UI（PG 数据驱动） | 状态总览 + 入口聚合 |

各场景的 panel 设计：

| 场景 | panel 内容（示例） |
|---|---|
| mentor | 当前学习计划、assignment 列表（待交/已交/已评）、学习进度 |
| coach | 本周计划执行率、最近训练数据摘要、下次评估时间 |
| copilot | 活跃 Project 列表、进行中的 Task 状态、最近产出 |
| operator | 各平台运营数据、待审内容、自动发布日志 |

外部工具的打开方式（**原生应用调起，用户自行管理窗口布局**）：

| 工具类型 | 方案 |
|---|---|
| Web 平台（Google Docs, intervals.icu, 社媒后台） | 系统浏览器打开 |
| VS Code / LeetCode | `code` CLI 调起 |
| Artifact（Markdown） | API 渲染为 HTML → 系统浏览器 |
| Artifact（PDF） | Zotero（内置阅读器） |
| Artifact（图片） | Preview.app |
| Artifact（代码） | VS Code |
| 移动端 | Telegram DM + 链接跳转 |

daemon 打开目标应用/文件后，自动将其窗口定位为：左边距 15% 屏幕宽度（给 Stage Manager 缩略图留位置），上/下/右贴屏幕边缘。该布局按比例计算，不绑定屏幕分辨率。不做多窗口分屏编排（DD-80）。

**技术选型**：**Tauri**（系统 WebView：macOS WKWebView）。客户端不需要内嵌浏览器（BrowserView），Tauri 的单 WebView 架构完全满足对话 + panel 需求，体积 ~10MB（vs Electron ~200MB）。

**FINAL 规则：客户端没有按钮操作。** 不存在"执行"按钮、pause/resume/cancel 按钮、触发按钮。所有操作通过对话完成：
- 用户说"做 X" → L1 创建 Task + Job + 执行（原子，用户无感）
- 用户说"先停一下" → L1 发送 pause Signal
- 用户说"算了不做了" → L1 发送 cancel Signal
- 用户说"重新来" → L1 创建新 Job

关键设计决策：
- **客户端不替代专业工具**，只做入口和聚合。用户在 Google Docs 里写作业，不在客户端里写。
- **客户端不内嵌外部网页**，通过系统浏览器打开，窗口布局交给用户和 Stage Manager。
- **assignment 系统是 panel 功能**，不是独立应用。mentor panel 显示作业列表和状态，提交入口指向外部工具（Google Docs / GitHub），daemon 通过 webhook 或轮询感知提交。
- **对话和展示严格分离**。对话里不出现链接和富内容，该看什么、在哪看，用户和 agent 心里都清楚。

### 4.3 Draft 语义与转正流程

FINAL 规则：Draft 是正式对象，不是临时聊天缓存。

Draft 的正式来源有四类：
- 用户对话
- 规则触发
- 外部事件
- 系统内部推进

FINAL 规则：自动任务也必须先形成 Draft，除非是明确的 `route="direct"`。Draft 转 Task 由 L1 自行判断——用户意图明确可执行时自动转正，无需用户做额外的"确认执行"动作。用户感知到的是"说了一句话 → 事情在做了"。

### 4.4 任务信息呈现

用户不需要看到 Plane 风格的 Task 页面或 Project 页面。客户端对话 view 内，daemon 用自然语言呈现任务相关信息：

- 用户问"进展怎么样" → daemon 用对话回复当前任务状态
- 用户问"这个项目整体情况" → daemon 汇总 Project 下各 Task 状态
- 用户问"上次的结果呢" → daemon 在阅读器 view 中展示 Artifact

**FINAL 规则：** 任务的结构化信息（DAG 依赖、执行历史、版本列表）存在于 Plane 后端，但只在用户明确问到时以自然语言或简洁摘要呈现，不默认展示。

### 4.5 活动流

**FINAL 规则：场景对话流是用户看到的主流，Task 活动流降为后台数据。**

用户体验 = "和 mentor 聊天"，不是"查看 Task A 的活动记录"。一次对话可能跨多个 Project/Task，甚至纯闲聊。L2 执行结果由 L1 在对话里自然汇报，用户不直接看 Task 活动流。

**场景对话流**（面向用户）：
- 存储在 `conversation_messages` PG 表（见 §3.3.1）
- 客户端 4 个对话 view 直接消费
- 用户看到的是和 L1 agent 的连续对话

**Task 活动流**（面向 CC/admin）：
- 每个 Task 在后端仍有活动流，记录 L2 执行事件
- 承载：Job 边界与 Step 关键状态、agent 产出摘要
- 面向 CC/admin 的审计追溯，不面向用户

FINAL 规则：Task 活动流 API 保留，用于后台管理：
- 返回同一 Task 下所有 Job 的合并活动流
- 按时间排序
- 每条消息显式携带 `job_id`

### 4.6 Artifact 呈现

Job 产生的 Artifact 通过两种方式呈现：

- **文本类**：在阅读器 view 中直接展示（Markdown 渲染）
- **需要浏览器的**：在浏览器 view 中打开（网页预览、在线文档等）
- **文件类**：提供下载入口

FINAL 规则：Artifact 呈现在对话流中自然引出（"写好了，你看看"→ 阅读器 view 自动打开），不需要用户去某个列表里找。

### 4.7 反馈与 Persona 回路

FINAL 规则：
- 反馈完全是对话式的。用户说"这里不好"就是反馈，daemon 自然回应并调整。沉默 = accepted。
- Persona 品味类更新自然嵌入对话："我注意到你喜欢这种写法，以后我会这样写。" 用户不回复 = 确认，用户说"不对" = 调整。不制造独立的确认环节。
- 系统级 Persona 调整由 CC/Codex 审查（§0.10），不问用户。

FINAL 责任归属：
- L1 agent 负责从对话中提取反馈信号和最终写入流程。
- writer / publisher 可以提出候选，但不直接落库。

### 4.8 非阻塞确认机制

**FINAL 规则：daemon 不阻塞等待用户确认。**

旧设计中 `requires_review=true` 会让 Job 进入 `paused` 等待 Temporal Signal。这违反 §0.9（阻塞）和 §0.10（让用户做系统审查）。

新机制：
- **系统级审查**（质量/安全/技术正确性）：CC/Codex 自动完成，不涉及用户（§0.10）
- **品味类确认**（对外发布内容、风格选择）：daemon 在对话中自然提出（"这是准备发布的版本，你看看"），**不暂停 Job**。用户随时回复，daemon 据此调整。如果用户长时间未回复，L1 根据 Persona 和历史偏好自行决定。
- **高风险操作**（不可逆的对外动作，如公开发布）：daemon 在对话中知会用户并等待回复，但这是对话层面的等待，不是 Job 状态机层面的 paused。Job 可以继续执行后续不依赖该确认的 Step。

`requires_review` 字段保留，但语义变化：
- `requires_review=true` → L1 在对话中提出确认请求 + Telegram 通知
- Job **不进入 paused**，继续执行不依赖确认结果的后续 Step
- 确认结果影响的 Step 标记为 `pending_confirmation`，确认后继续

### 4.9 API 端点集合

FINAL 规则：daemon API 面向自建客户端，按场景路由，提供以下端点：

| 类别 | 端点 | 说明 |
|---|---|---|
| 对话 | `POST /scenes/{scene}/chat` | 场景对话输入（scene = copilot/mentor/coach/operator） |
| 对话 | `GET /scenes/{scene}/chat/stream` (WebSocket) | 场景实时对话流 |
| 场景 | `GET /scenes/{scene}/panel` | 场景 panel 数据 |
| 活动流 | `GET /tasks/{id}/activity` | Task 活动流（后台，面向 CC/admin） |
| 产物 | `GET /artifacts/{id}` | Artifact 内容 |
| 产物 | `GET /artifacts/{id}/download` | Artifact 下载 |
| 状态 | `GET /status` | 系统整体状态（客户端状态指示用） |
| 认证 | `GET /auth/google` | Google OAuth 登录 |
| 认证 | `GET /auth/github` | GitHub OAuth 登录 |
| 认证 | `GET /auth/callback` | OAuth 回调 |

不再提供 `pause / resume / cancel` 等操作端点——这些操作通过场景对话的自然语言完成，由 L1 解析并执行。

**[DEFAULT]** 对话流传输方案：WebSocket（双向）或 SSE（服务端推送）+ POST（客户端发送）。WebSocket 开销小（每帧 2-14 字节头），SSE 更简单。具体选型在实现阶段决定。

**FINAL 规则：对话流消息携带类型字段，客户端根据类型分发到对应 view。**

| 消息类型 | 处理方式 | 说明 |
|---|---|---|
| `text` | 对话 view 显示 | 普通对话消息 |
| `panel_update` | 场景 panel 刷新 | Task 状态变更、数据刷新 |
| `native_open` | 调起原生应用 | 打开 URL / VS Code / Zotero / Preview（DD-78：统一替代 browser_navigate/editor_open/vscode_launch） |
| `artifact_show` | 调起渲染 | 展示 Markdown Artifact（API `/artifacts/{id}/render` → 系统浏览器） |
| `status_update` | 菜单栏图标更新 | 系统状态变化（绿/黄/红） |
| `notification` | 系统通知 | macOS 原生通知（Tauri notification 插件） |

消息格式见参考文档附录 D.7。

### 4.10 Telegram

**FINAL 规则：4 个独立 Bot Token，4 个独立 DM。**

用户在 Telegram 里看到 4 个联系人（copilot / mentor / coach / operator），各自 DM。场景之间无协作关系，不放在同一个群里。

**定位：信箱 + 对讲机**（DD-79）。Telegram 不是桌面客户端的镜像，是 daemon 的对外通知渠道和用户的快捷回复入口。

Telegram 承载：
- daemon → 用户：完成/失败/告警通知、品味类确认请求
- 用户 → daemon：简短回复（"可以"/"等我回去再说"等）

**单向同步：Telegram → 本地**。用户在 Telegram 的回复同步到本地客户端对话流。本地桌面客户端的对话**不**推送到 Telegram。

不承载：
- 本地对话的实时同步（不是聊天镜像）
- 复杂结构化编辑（引导到客户端）
- 场景 panel 展示（Telegram 无 UI）
- Artifact 查看（用 iOS app）

### 4.11 管理界面（面向 CC/admin）

FINAL 规则：Plane 管理界面面向 CC/Codex 和 admin，不面向用户。暴露：
- Task / Job / Step 的元数据和执行摘要
- agent 列表和状态
- 关键状态机信息
- Persona 文件只读呈现

FINAL 规则：Persona 文件路径为 `persona/voice/*.md`（identity.md、common.md、zh.md、en.md、overlays/*.md）。Persona 修改由 CC/Codex 通过 git commit 管理，不通过 UI 编辑。

---

## §5 知识、Persona、Guardrails 与 Quota

### 5.1 正式层级

正式层级固定为：

`Guardrails > External Facts > Persona > System Defaults`

这条层级同时适用于：
- 输出冲突处理
- 引用优先级
- Persona 更新权限
- 自动化决策冲突裁定

冲突处理规则：
- Guardrails 与 Persona 冲突 → Guardrails 赢（系统原则不可被用户覆盖）
- External facts 与用户主张冲突 → External facts 赢（不替用户歪曲事实）
- Persona 与 System defaults 冲突 → Persona 赢（用户偏好优先于默认值）

### 5.2 Guardrails（系统硬规则）

**定义**：系统不可被用户覆盖的原则。代码层确定性执行，不依赖 LLM 遵守指令。

**实现方式**：NeMo Guardrails（NVIDIA 开源，Apache 2.0）。Python 库嵌入 Worker 进程，零额外服务。

| 层级 | 执行方式 | 成本 | 覆盖范围 |
|---|---|---|---|
| **硬规则** | NeMo input/output rail（Colang DSL） | 零 | 安全边界、隐私泄露检测、格式校验、Quota 上限、token 预算 |
| **软规则** | NeMo dialog rail + guardrails.md 注入 | 极低 | 质量底线、专业标准 |
| **关键审查** | L1 安排审查 Step + NeMo output rail | 中 | 对外发布内容、高风险操作 |

#### 5.2.1 信息门控

所有信息流入系统都必须过 Guardrails 代码校验：
- Persona 候选写入 → 写入前过校验（用户确认 ≠ 免检）
- 外部知识引用 → source_tier 校验

#### 5.2.2 NeMo Guardrails 配置

| Rail 类型 | 作用 |
|---|---|
| Input rail | 过滤外发 query 中的敏感词（sensitive_terms.json） |
| Output rail | 检查输出是否违反硬规则 |
| Custom action | Mem0 写入前校验、source_tier 校验 |

Colang 规则文件位置：`config/guardrails/`。

#### 5.2.3 guardrails.md 内容范围

- **输出质量底线**：事实有来源、不伪造、不抄袭
- **信息完整性**：内外不混淆、关键事实交叉验证（Tier C 不算独立来源）
- **安全边界**：不执行有害指令、外部输入视为不可信、不泄露内部信息
- **专业标准**：冲突时先提醒 → 用户坚持 → 执行并标注 user_override → 安全边界内拒绝
- **冲突处理**：可降级冲突（提醒→确认→标注）vs 不可降级冲突（拒绝→解释）

#### 5.2.4 演进

guardrails.md 由系统维护者更新，纳入 git 管理。不由用户更新，不由 LLM 自动更新。

### 5.3 Persona 双层结构

FINAL 规则：Persona 不是单一文件，也不是纯 Mem0；它是双层结构。

1. **文件层（稳定基底）**
- `persona/voice/identity.md`
- `persona/voice/common.md`
- `persona/voice/zh.md`
- `persona/voice/en.md`
- `persona/voice/overlays/*.md`

2. **动态层（运行期记忆）**
- Mem0 semantic / procedural memory

文件层负责稳定的身份、语言、全局表达边界；Mem0 动态层负责用户偏好、风格演化、规划经验。

#### 5.3.1 Mem0 记忆类型

| 内容 | Mem0 记忆类型 | 级别 |
|---|---|---|
| AI 身份和人格 | semantic memory | agent 级 |
| 写作风格 | procedural memory | agent 级（writer/publisher 用） |
| 用户偏好 | semantic memory | user 级 |
| 规划经验 | procedural memory | agent 级（L1 共享） |

#### 5.3.2 冷启动

**FINAL 规则：冷启动通过对话完成，用户不需要准备任何材料。**

- **通用流程**：用户通过对话告诉 daemon 关于自己的一切（背景、风格偏好、对外形象、工作方式等）→ writer 基于这些信息生成写作样本 → reviewer 校验样本是否准确反映用户描述 → daemon 在对话中展示（"这像你吗？"）→ 用户自然回复调整 → 写入 Mem0。在暖机 Stage 1 执行。
- **CC 预置快捷路径**：搭建阶段 CC 已与用户深度对话，可直接生成 Persona 材料预置到系统中，跳过冷启动对话的 token 消耗。daemon 启动时已有 Persona 基础，生产中持续校准。
- **最小启动**：什么都不提供 → 中性风格 → 随反馈逐渐积累。

冷启动能力必须保留（Persona 丢失后重建、未来新用户场景），即使当前用户的 Persona 由 CC 预置。

### 5.4 Persona 更新责任

FINAL 规则：Persona 更新分两类，审核方式不同（见 §0.10 自治原则）。

**用户品味类（用户确认）**：
- 写作风格偏好（"我喜欢这种写法"/"以后别用这个词"）
- 对外形象设定（"对外用这个身份"）
- 链路：Job closed 后，L1 列出风格类反馈候选 → 用户确认 → NeMo Guardrails 校验 → 写入 Mem0

**系统级调整（CC/Codex 审查）**：
- Persona 文件层的结构优化
- Mem0 记忆去重、冲突合并
- 过期记忆清理
- 链路：admin 提出变更 → CC/Codex 审查 → 执行 → verify.py 验证

writer / publisher 负责提出候选，L1 负责确认闭环和最终写入。

#### 5.4.1 漂移检测

Mem0 内置去重和冲突检测。额外：
- 超过 90 天未触发的记忆由 CC/Codex 审查后自动清理（见 §0.10），不需要用户手动解决
- 矛盾检测结果由 admin 在体检时发现，CC/Codex 审查后合并或删除
- 涉及用户品味的矛盾（如风格偏好冲突）推送 Telegram 简要通知，用户回复确认

### 5.5 Mem0 注入

FINAL 规则：Mem0 只做按需检索，不做全量注入。

| 层级 | agent | 默认检索重点 | 约 token |
|---|---|---|---|
| L1 | copilot / mentor / coach / operator | 规划经验、历史 DAG 模式、场景上下文 | ~100-200 |
| L2 | researcher | 搜索策略、分析框架 | ~50-100 |
| L2 | engineer | 技术偏好、代码风格 | ~50-100 |
| L2 | writer | 写作风格 + 语言 + task_type | ~100-200 |
| L2 | reviewer | 质量标准 + task_type | ~50-100 |
| L2 | publisher | 发布风格 + 渠道 | ~100-200 |
| L2 | admin | 运维经验、诊断线索 | ~50-100 |

**[DEFAULT]** 单次检索上限默认 5 条；超过这个值是否提升，只能由暖机结果驱动。

对比全量注入：~300-550 tokens → Mem0 按需 ~50-200 tokens。NeMo Guardrails 的规则在引擎层执行，不注入 prompt（零 token）。

### 5.6 外部知识获取工具链

正式工具链：

| 工具 | 作用 | 集成方式 |
|---|---|---|
| 通用 MCP search | 网页搜索 | MCP tool → researcher |
| Semantic Scholar API | 学术论文搜索（2亿+论文） | MCP tool → researcher |
| OpenAlex API | 开放学术元数据（2.5亿+论文，免费无需 auth） | MCP tool → researcher |
| CrossRef API | 引用元数据（1.8B 记录，免费） | MCP tool → researcher |
| Unpaywall API | DOI→免费全文 PDF（100K/天） | MCP tool → researcher |
| Firecrawl | 网页 → 干净 Markdown（省 80%+ token） | Docker 自部署，MCP tool → L2 agent |
| RAGFlow | PDF/文档 → 语义分块 → 向量检索 | Docker 服务 |
| LanguageTool | 英文语法/风格检查（self-hosted，无限调用） | Docker 自部署，MCP tool → mentor |
| Dev.to + Hashnode | 博客跨平台发布（REST + GraphQL） | MCP tool → publisher |
| OpenWeatherMap | 户外运动天气预报（免费 1000 req/天） | MCP tool → coach/operator |
| Intervals.icu | 运动数据/训练计划/体能曲线（100+ endpoint） | MCP tool → coach |
| Kroki | 统一图表 API（Mermaid/PlantUML/D2/Vega 等 20+ 格式） | MCP tool → researcher/writer |
| ECharts | 交互式数据可视化图表（Apache 官方 MCP） | MCP tool → researcher/writer |
| Strava API | 运动数据原始获取（OAuth 2.0，200 req/15min） | MCP tool → coach |
| DBLP / Academix | CS 论文权威检索 / 统一学术搜索聚合 | MCP tool → researcher |
| HuggingFace Hub | 模型/数据集/Spaces 搜索、trending 监控 | MCP tool → researcher/engineer |
| Libraries.io | 开源依赖监控（40M+ 包，跨 NPM/PyPI/Cargo 等） | MCP tool → engineer/operator |
| LeetCode MCP | 题库搜索（tag/难度）+ 题目详情 + 提交历史，mentor 主导出题 | MCP tool → mentor |

**学术搜索互补策略**：researcher 搜索学术文献时组合调用四个源——Semantic Scholar（引用关系图+推荐）+ OpenAlex（覆盖最广 2.5 亿篇）+ CrossRef（DOI 元数据权威）+ CORE（开放获取全文 PDF）。四个源覆盖不同维度，不选其一。Academix MCP（npm 包）可作为聚合入口一次搜五个源。Elicit 无公开 API，仅作为用户浏览器工具使用，不纳入 MCP。

FINAL 规则：外部知识必须能追溯回 URL / 文档来源；没有来源的内容不算 External Facts，只能算工作缓存。

#### 5.6.1 knowledge_cache 与 Project 偏置

knowledge_cache 用于外部知识 TTL 与二级缓存，不替代 RAGFlow，也不替代 Mem0。

TTL 按来源分级（source_tiers.toml）：

| 级别 | 来源示例 | TTL | 验证要求 |
|---|---|---|---|
| **Tier A** | arxiv、Semantic Scholar、官方文档 | 90 天 | 单源即可引用 |
| **Tier B** | Wikipedia、MDN、主流媒体 | 30 天 | 关键数据需交叉验证 |
| **Tier C** | Reddit、StackOverflow 评论、匿名来源 | 7 天 | 必须交叉验证，不可作唯一来源 |

NeMo Guardrails 硬规则：**Tier C 来源的数据不得作为事实性主张的唯一支撑。**

FINAL 规则：检索时先查同一 `project_id` 范围，再回退到全局；这样既减少跨项目污染，又不至于完全错失全局经验。

#### 5.6.2 隐私边界

- `config/sensitive_terms.json`：维护敏感词列表
- NeMo Guardrails input rail 在 MCP 调用前过滤
- 被过滤的词替换为通用描述（如 "项目X" → "某软件项目"）

### 5.7 内外知识分野

```
外部知识（External）—— 事实性的、可引用的、可验证的
  来源：researcher → MCP search / Semantic Scholar → RAGFlow / knowledge_cache
  特点：有 source_url、有 source_tier
  使用：引用时标注来源
  信任：按 tier 分级

内部知识（Internal）—— 个人化的、累积的、可调整的
  来源：Mem0（agent memory / user memory）
  特点：无"对错"，只有"符不符合用户"
  使用：塑造风格和方式，不塑造内容和事实
  信任：用户权威（NeMo Guardrails 边界内）

系统知识（System）—— 内置的、不可覆盖的
  来源：NeMo Guardrails Colang 规则（config/guardrails/）
  使用：输出校验、冲突裁决
  信任：最高
```

#### 5.7.1 Obsidian Vault（用户知识图谱）

**FINAL 规则：daemon 的 Markdown 产出写入 Obsidian vault，二进制文件留 MinIO。Vault 是用户的知识图谱，不是系统日志。**

| 配置 | 说明 |
|---|---|
| Vault 位置 | Google Drive（离开家也能访问） |
| MCP server | `@bitbonsai/mcpvault`（文件系统直接操作，不依赖 Obsidian 运行） |
| Zotero 联动 | Obsidian Zotero Integration 插件（论文标注自动导入为文献笔记） |

**写入 vault 的 agent 和内容**：

| agent | 写入内容 |
|---|---|
| researcher | 文献笔记、分析报告 |
| writer | 文章草稿、博客 |
| engineer | 技术文档（用户项目相关） |
| mentor | 学习笔记、作业反馈 |

**不写入 vault**：
- admin / operator 系统产出 → `state/background_reports/`（本地归档清理）
- 代码文件 → GitHub
- PDF 论文 → Zotero library
- 大文件/临时产物 → MinIO

**vault 内容类型**：只放 Markdown 文件 + 引用的图片（`attachments/`）。Obsidian 本质是 Markdown 渲染器，vault 里只放它能原生处理的格式。

**vault 结构**：
```
vault/
  daily/          # 每日笔记
  references/     # 文献笔记（Zotero → Obsidian 自动导入）
  projects/       # 每个 Project 一个笔记
  research/       # researcher 产出
  drafts/         # writer 产出
  knowledge/      # 蒸馏后的永久笔记
  templates/      # 模板
  attachments/    # 图片
```

### 5.8 Quota 与运行预算

Quota 分三层：
- OC / session 层预算
- Job 层预算
- 系统日预算

**[DEFAULT]** 配额阈值和告警先走保守默认值，记录在参考文档附录 B；暖机完成后再按 Langfuse 数据校准。

### 5.9 本地后台任务（记忆蒸馏与系统维护）

本地 Ollama 模型（qwen2.5:32b / 7b）不仅承担 §2.8.1 的 9 个实时内部任务，还负责一系列**非实时后台任务**。这些任务通过 Temporal Schedule 定时触发，在后台慢速执行，零 API 成本。

#### 5.9.1 记忆蒸馏

**记忆 Distillation 包含两个阶段**（参考 Mem0 论文 arxiv:2504.19413）：
1. **Extraction（提取）**：从每次对话/Job 中抽取关键事实写入 Mem0（由 `activity_post_job_learn` 在 Job 完成后立即执行）
2. **Consolidation（整合）**：定期将已有的碎片记忆合并、去重、精简（后台定时任务）

注意：Mem0 自身在写入时可能已做部分 consolidation（其 Update 阶段包含去重逻辑），需验证 Mem0 API 实际行为后决定后台整合任务的范围。

Mem0 中的记忆随使用不断积累，会出现碎片化、重复、矛盾、过时等问题。记忆蒸馏是定期对记忆进行合并、提炼、淘汰的过程：

```
原始记忆（大量、碎片化）
    ↓ 蒸馏 Schedule（每日，local-heavy）
合并重复 → 提取高阶 pattern → 生成浓缩洞察
    ↓
蒸馏后记忆（少量、高密度、可操作）
    ↓
淘汰已被蒸馏的原始碎片
```

蒸馏任务：

| 任务 | 模型 | 频率 | 说明 |
|---|---|---|---|
| memory_merge | local-heavy | 每日 | 合并语义相似的 Mem0 记忆，去重 |
| memory_distill | local-heavy | 每周 | 从近期记忆中提取高阶 pattern（如"用户倾向 X"）|
| persona_deep_analysis | local-heavy | 每周 | 分析近期交互，更新用户偏好变化 |
| planning_consolidate | local-heavy | 每周 | 合并多次 Job 的 planning_experience 为策略级洞察 |
| memory_gc | local-light | 每日 | 标记已蒸馏/过期的原始记忆为候选删除 |

蒸馏结果写回 Mem0，标记 `source: distilled`，原始碎片标记 `distilled: true` 后在下一轮 gc 中清理。涉及用户品味的蒸馏结果走 §5.4 确认流程（Telegram 通知）。

#### 5.9.2 知识库维护

| 任务 | 模型 | 频率 | 说明 |
|---|---|---|---|
| knowledge_audit | local-heavy | 每周 | 审查 knowledge_cache 过期/低质量条目，交叉验证 |
| source_credibility | local-heavy | 每月 | 分析信源历史可靠性，更新 source_tiers.toml |
| artifact_review | local-heavy | 每周 | 回顾近期 Artifact 质量，提取 lessons learned |
| cross_project_mining | local-heavy | 每月 | 跨 Project 发现共性 pattern |

#### 5.9.3 系统自省

| 任务 | 模型 | 频率 | 说明 |
|---|---|---|---|
| skill_effectiveness | local-heavy | 每周 | 分析 skill 使用成功率、token 效率，生成优化建议 |
| failure_pattern | local-heavy | 每周 | 分析失败 Job 共性，发现系统性问题 |
| writing_style_update | local-heavy | 每周 | 从用户近期作品更新 Persona 写作特征 |
| system_snapshot | local-heavy | 每周 | 周期性系统快照：收集本周 Job 执行记录、agent 调用模式、失败率、用户行为变化、系统健康指标 → 存结构化快照 → 喂给 skill_effectiveness / failure_pattern 等自省任务。不是给用户看的"周报"，是给 daemon 自身进化用的数据 |

所有后台任务的结果存入 `state/background_reports/` 目录，admin 体检（§7.7）时读取并纳入评估。

#### 5.9.4 调度与资源保护

- 后台任务统一通过 `BackgroundMaintenanceWorkflow`（Temporal Schedule）调度
- **资源隔离**：后台任务使用 Ollama 的同一实例，但通过队列串行执行，避免与实时内部任务（replan gate 等）争抢 GPU
- **优先级**：实时任务优先，后台任务在 Ollama 空闲时执行
- 每个任务设超时（默认 30 分钟），超时跳过不阻塞
- 任务失败不影响系统运行，下一周期重试

---

## §6 基础设施与运行时契约

### 6.1 Docker 服务清单

| 服务 | 镜像/技术栈 | 职责 | 端口 |
|---|---|---|---|
| PostgreSQL | postgres:16 + pgvector | 主数据库（Plane + daemon + Mem0 共用） | 5432 |
| Redis | redis:7 | 缓存 + 消息队列（Plane + Langfuse 共用） | 6379 |
| Plane API | Django + DRF | Issue/Project/DraftIssue CRUD + Webhook | 8000 |
| Plane 前端 | React + TypeScript | 管理界面（面向 CC/admin） | 3000 |
| Plane Worker | Celery | 异步任务（邮件、导出等） | — |
| Temporal Server | temporalio/server | Workflow 编排 + Schedules | 7233 |
| Temporal UI | temporalio/ui | 运维 Dashboard | 8080 |
| MinIO | minio/minio | S3 兼容对象存储 | 9000/9001 |
| Langfuse | langfuse/langfuse | LLM 追踪 + 评估 | 3001 |
| ClickHouse | clickhouse/clickhouse-server | Langfuse 分析后端 | 8123 |
| RAGFlow | infiniflow/ragflow | 文档解析 + 分块 + 向量检索 | 9380 |
| Elasticsearch | elasticsearch:8 | RAGFlow 全文索引后端 | 9200 |
| Firecrawl | mendableai/firecrawl | 网页 → 干净 Markdown | 3002 |

非 Docker 服务（原生安装）：

| 服务 | 安装方式 | 职责 | 端口 |
|---|---|---|---|
| Ollama | Homebrew（原生，Metal GPU） | 本地 LLM 推理（内部任务零 API 成本） | 11434 |

**[DEFAULT]** RSSHub（Docker 容器）待部署，用于解决 Reddit/知乎/小红书等反爬平台的信息拉取。

FINAL 规则：这些服务只解决"基础设施能力"，不承担 daemon 的业务状态机。

### 6.2 daemon 自有进程

daemon 只正式持有两个 Python 进程：

| 进程 | 技术栈 | 职责 |
|---|---|---|
| **API 进程** | FastAPI（uvicorn） | L1 OC session 管理（4 个持久对话）、WebSocket、Plane webhook handler、胶水 API |
| **Worker 进程** | Temporal Python Worker | L2 Activities（调 OC agent、写 Plane API、写 PG）、定时清理 Job、对话压缩、NeMo Guardrails、Mem0 |

两个 Python 进程不直接通信，通过 Temporal workflow + PG 协作。NeMo Guardrails 和 Mem0 作为 Python 库嵌入 Worker 进程，不是独立服务。

FINAL 规则：
- API 进程负责边界接入、L1 对话、查询接口。L1 session 是 API 进程的正式职责，不是"偷偷跑"。
- Worker 进程负责 L2 执行语义、Plane 回写、MCP、Mem0、NeMo、MinIO、对话压缩。
- 不允许在 API 进程里运行 Temporal workflow 或 L2 执行链。

### 6.3 OC Gateway 与 MCP 生命周期

| 组件 | 说明 |
|---|---|
| OpenClaw | Agent 编排平台 |
| 10 agents | L1: copilot / mentor / coach / operator; L2: researcher / engineer / writer / reviewer / publisher / admin |
| L1 Session | 持久 session，API 进程管理，daemon 控制压缩 |
| L2 Session | 1 Step = 1 Session，生命周期 = Step 级别 |
| 并发配置 | `maxChildrenPerAgent`（默认 5）/ `maxConcurrent`（默认 8），暖机时校准 |
| Subagent 深度 | `maxSpawnDepth: 2`（orchestrator 模式），支持 Step 内并行 |
| MCP 分发 | runtime/mcp_dispatch.py + config/mcp_servers.json |

`~/.openclaw → daemon/openclaw/` 软链接必须存在。

FINAL 规则：
- Session 生命周期 = Step 生命周期。
- subagent 不加载 Mem0 / MEMORY.md。
- tool routing 由 MCP dispatcher 统一分发。

FINAL 规则：MCP server 连接按 Worker 进程级持久化复用：
- Worker 启动时连接并构建 tool 路由表
- 每次调用都带超时保护
- server 崩溃或超时后标记不可用，让 Step 走失败 / 重试逻辑

### 6.4 PostgreSQL 事件总线

FINAL 规则：PG 事件总线采用 `event_log + NOTIFY` 双写。

FINAL 语义：
- `event_log` 提供持久化与重放能力
- `NOTIFY` 提供即时唤醒能力
- Worker 重启后先补消费 `event_log` 未完成事件，再恢复监听

FINAL 规则：channels 统一为 `job_events`、`step_events`、`webhook_events`、`system_events`。

### 6.5 Temporal 约束

FINAL 规则：
- Job = Workflow
- Step = Activity（或少数 runtime 包装 activity）
- timer = Temporal Schedule
- pause / resume / cancel = Signal / Workflow 控制

FINAL 规则：时间预算、retry policy、catch-up window 见参考文档附录 B；实现者不得自行发明第二套调度系统。

### 6.6 Plane 回写与补偿

FINAL 规则：Plane 是协作真相源，但不是 Job 执行真相源。Job 的真实执行状态先落 daemon PG，再尝试回写 Plane。

FINAL 规则：Plane 回写失败时：
- 先重试（最多 5 次，指数退避）
- 再写 `plane_sync_failed`
- 再由补偿流程异步追平

不允许直接把 Job 标成 failed 来掩盖 Plane 同步失败。

### 6.7 配置文件

正式配置位于：
- `config/mcp_servers.json`
- `config/source_tiers.toml`
- `config/lexicon.json`
- `config/guardrails/`
- `config/sensitive_terms.json`
- `openclaw/openclaw.json`

FINAL 规则：配置表述的默认值必须与参考文档附录 B / C / D 一致。

### 6.8 外部依赖

| 组件 | 说明 |
|---|---|
| Python 3.11+ | API 进程 + Worker 进程 |
| Node.js | MCP servers 运行时 |
| LLM Provider API Keys | MiniMax、Qwen（analysis + review）、智谱（embedding）、GLM（creative） |
| Telegram Bot Token | OC 原生 Telegram channel 配置 |
| GitHub Token | MCP server（@modelcontextprotocol/server-github） |
| Semantic Scholar API Key | 学术搜索（免费，可选，提升速率限制） |
| mem0ai | 记忆层 Python 库 |
| nemoguardrails | 安全规则引擎 Python 库 |

### 6.9 启动与健康检查

FINAL 规则：启动顺序必须可验证，不能依赖"本机刚好都起来了"。

推荐顺序：
1. Docker 基础服务（PG、Redis、MinIO 等）
2. PostgreSQL / Temporal / Plane 就绪
3. OC Gateway
4. daemon Worker
5. daemon API

FINAL 规则：Schedule 丢失自动恢复：所有 Schedule 定义存在 `config/schedules.json` 中。admin 每周体检时对比配置中应有的 Schedule 与 Temporal 中实际存在的 Schedule，缺失的自动从配置重建，多出的标记给 CC 审查。

### 6.10 开机自启动、桌面客户端与远程访问

#### 6.10.1 开机自启动

**目标**：用户开机后无需任何操作，daemon 自动运行。

**macOS 实现**：
- launchd plist（`~/Library/LaunchAgents/com.daemon.startup.plist`）
- 开机自动执行 `scripts/start.py`（拉起 Docker Compose + daemon 进程）
- 如果 Docker Desktop 未运行，start.py 先启动 Docker Desktop

#### 6.10.2 桌面客户端

**FINAL 规则：桌面客户端是用户与 daemon 交互的主入口。** 两个展示模式见 §4.2。

| 组件 | 说明 |
|---|---|
| 桌面应用 | **Tauri**（系统 WebView：macOS WKWebView，~10MB），同一套前端代码（React + Vite + Tailwind） |
| 菜单栏图标 | 状态指示（绿/黄/红）+ 点击打开主窗口 + 右键菜单（启停/系统信息） |
| 菜单栏右键菜单 | Start / Stop daemon、今日任务数、本周体检状态、打开 Langfuse / Temporal UI（面向 CC/admin 的管理入口） |
| 外部内容展示 | 原生应用调起（系统浏览器 / VS Code / Preview.app），窗口布局交给用户和 Stage Manager（DD-80） |

菜单栏图标与桌面应用是同一个 Tauri 进程。菜单栏常驻，主窗口按需打开/关闭。

#### 6.10.3 多平台策略（DD-79）

**FINAL 规则：daemon 不提供 Web 访问。所有访问必须通过封装好的原生客户端。**

```
macOS：     Tauri 桌面 app → 完整体验（对话 + native_open）
iOS：       Tauri iOS app → Artifact 查看器（只读）
Telegram：  信箱 + 对讲机 → 通知/快捷回复（单向同步 Telegram→本地）
```

- **macOS Tauri**：主控台，完整功能。daemon 的核心能力（MCP servers / Docker / VS Code / 系统应用）全部依赖 macOS 环境
- **iOS Tauri app**：Artifact 查看器。Tauri 2.0 支持 iOS 构建（WKWebView）。只读浏览 daemon 产出的文档/代码/图片，不提供对话或操作能力。类似 Steam iOS app 的定位
- **Telegram**：daemon 的对外通知渠道 + 用户快捷回复入口（§4.10）。本地对话不推送到 Telegram，Telegram 回复同步到本地
- **无 Web 端**：不做 PWA，不做 Tailscale Funnel 暴露，不做远程浏览器访问。daemon 是纯本地系统

### 6.11 备份制度

**FINAL 规则：daemon 必须有自动备份能力。数据丢失不可接受。**

**备份策略（学 Time Machine：增量、自动、滚动保留）**：

| 备份对象 | 方法 | 频率 | 保留 |
|---|---|---|---|
| PostgreSQL | `pg_dump` 到本地备份目录 | 每日 | 90 天滚动 |
| MinIO（artifacts bucket） | **[DEFAULT]** 增量备份（restic / rsync 增量 / MinIO versioning，实现阶段选型） | 每日 | 90 天滚动 |
| 配置文件（config/） | git 管理 | 每次变更 | 永久 |
| Persona 文件（persona/） | git 管理 | 每次变更 | 永久 |
| Skill 文件 + Skill Graph（openclaw/workspace/） | git 管理 | 每次变更 | 永久 |

**FINAL 规则：MinIO 备份必须增量，不做全量镜像。** 全量镜像 × 90 天会占用过多磁盘空间（本机 460GB SSD，需预留充足空间）。增量备份总量 ≈ 活跃数据 × 1.x 倍。

**备份目录**：`DAEMON_HOME/backups/`（可配置为外置硬盘路径）。

**备份 Job**：Temporal Schedule 每日执行（见 §1.7），admin 在体检时验证备份完整性。

**恢复流程**：`scripts/restore.py --date YYYY-MM-DD`，从备份目录恢复 PG + MinIO 到指定日期状态。

### 6.12 数据生命周期

**[DEFAULT]** 基于每日 20-30 个任务的量级设计（月 ~1500 Jobs，年 ~18000 Jobs）。

#### 6.12.1 Artifact 存储策略

**FINAL 规则：Google Drive 是最终 Artifact 的持久存储层，本地 MinIO 只做缓存。中间产物不同步，只留本地。**

Artifact 分两类：

| 类型 | 说明 | Google Drive | 本地保留 |
|---|---|---|---|
| **最终交付物** | Job 的最终产出（用户要的结果） | 同步，永久（2TB） | 30 天缓存 |
| **中间产物** | Step 过程中的半成品（搜索笔记、草稿、原始数据等） | 不同步 | 跟随 Job 生命周期（90 天后删除） |

同步流程：Job closed → 最终 Artifact 写入本地 MinIO → publisher 自动同步到 Google Drive → 同步确认后标记 `gdrive_synced=true` → 30 天后清理 Job 自动删除本地副本（仅限已同步的）。

**Key 标记**保留，作用是方便检索（L1 检索 Artifact 时优先从 key 中查找）：
- publisher 对外发布的 → 自动标记 key
- 用户在对话中说"这个留着" → 标记 key
- 所有同步到 Google Drive 的最终交付物 → 自动标记 key

#### 6.12.2 其他数据生命周期

| 对象 | 活跃期 | 归档 | 删除 | 说明 |
|---|---|---|---|---|
| Ephemeral Job（route=direct） | 7 天 | — | 7 天后删除 | 量大但价值衰减快 |
| 常规 Job | 30 天 | 30-90 天（PG 保留，标记 archived） | 90 天后删除 | 归档期内可查不可改 |
| Langfuse trace | 90 天 | — | Langfuse retention 配置 | Langfuse 自管 |
| event_log（consumed） | 7 天 | — | 7 天后删除 | 已消费事件无保留价值 |
| 体检报告 | 52 周 | — | 52 周后删除 | 保留一年趋势数据 |
| 问题文件（resolved） | 30 天 | — | 30 天后删除 | 修复完成后仅供审计 |
| Mem0 记忆 | 永久（活跃） | — | 90 天未触发 → CC 审查后清理 | 见 §5.4.1 |
| PG 备份 | 90 天 | — | 90 天滚动 | 见 §6.11 |

FINAL 规则：
- 归档和删除由清理 Job 自动执行，不需要用户参与（见 §0.10 自治原则）。
- 本地 Artifact 删除前必须确认 `gdrive_synced=true`，未同步的不删。

### 6.13 认证与多用户扩展路径

#### 6.13.1 认证

**FINAL 规则：daemon 使用 OAuth 认证（Google / GitHub），首版即实现。** 不使用简单用户名密码。

| 场景 | 认证方式 |
|---|---|
| 本地 Tauri 客户端（localhost） | OAuth 登录，token 持久化，不需要每次登录 |
| 远程 Web 访问（Tailscale Funnel） | OAuth 登录，session 管理 |
| Telegram | 绑定 OAuth 账号，首次关联后免登录 |
| API 调用 | JWT token（OAuth 登录后颁发） |

**[DEFAULT]** 实现方式：FastAPI + authlib 或 python-social-auth，支持 Google 和 GitHub OAuth provider。

#### 6.13.2 多用户扩展路径

**当前单用户，但设计不堵死多用户。** 未来部署到服务器、多人使用时的扩展路径：

**数据隔离（加 `user_id` 维度）**：
- PG：所有 daemon 表加 `user_id` 字段（当前单用户用默认值）
- Plane：每用户一个 Workspace
- MinIO：每用户一个 bucket 或 prefix
- Mem0：按 user_id 分 namespace（Mem0 原生支持）
- Langfuse：trace 按 user_id 标记
- Persona：每用户独立 `persona/voice/` 目录
- Temporal：Workflow ID 带 user_id 前缀，共用 Task Queue

**基础设施扩展**：
- Docker Compose → Kubernetes（规模大时）
- 本地 PG / MinIO → 云托管（RDS / S3）
- Tailscale Funnel → 正式域名 + TLS + CDN
- Temporal → Temporal Cloud
- Worker 扩容（并发用户 → 更多 Worker 实例）

**资源控制**：
- LLM API 调用按用户计量（Quota 机制已设计，§5.8）
- 存储按用户计量
- OC agent 实例池按并发需求扩容

**当前实现要求（不堵死规则）**：
1. PG 表结构预留 `user_id` 字段，单用户时用默认值
2. API 层实现不硬编码"只有一个用户"
3. Persona / Skill 路径用配置变量，不硬编码绝对路径
4. Temporal Workflow ID 带 user_id 前缀

---

## §7 暖机、可观测性与自愈

### 7.1 暖机的本质

暖机不是初始化，不是连通性检查，不是跑几个测试场景。

**暖机 = 系统标定。目标是让 daemon 的所有对外输出达到"伪人"水准。**

"伪人"定义：daemon 产出的任何内容——文本、代码、发布到外部平台的内容、通知——与用户本人亲手做的无法区分。外部接收方不会怀疑这是 AI 产出。

暖机分两阶段主导：**Stage 0-2 由 CC（Claude Code）主导**（搭 OC workspace、写 SOUL.md/SKILL.md、基础设施验证——admin 自己也是被暖机对象，不能给自己暖机）；**Stage 3+ 由 admin 主导**（系统运转后接管：跑测试任务、评估产出质量、校准参数）。用户全程参与（Stage 0 提供信息、Stage 1 确认 Persona、最终验收）。

### 7.2 暖机前提

暖机开始前必须满足（对应 TODO.md Phase 0-5 全部完成）：

**基础设施（Phase 1）**：Docker Compose 全部服务运行且健康；`.env` 文件所有连接信息正确；宿主机 → Docker 网络连通。

**对象映射 + 胶水层（Phase 2）**：Plane API 客户端可用；Webhook handler 就绪；PG 事件总线就绪；PG 数据层就绪，所有表已创建；Plane Workspace + 默认 Project 已初始化；Plane webhook 指向 daemon API 且签名验证通过。

**执行层（Phase 3）**：Temporal Activities 读写 Plane API + PG；Temporal Schedules 已注册；publisher 出口就绪；Langfuse 接收 trace 数据；MinIO 文件上传/下载正常。

**知识层（Phase 4）**：NeMo Guardrails 规则配置就绪；Persona 初始模板文件存在；Mem0 服务可用，agent_id 隔离正常；pgvector knowledge_cache 表就绪；RAGFlow 服务运行正常；source_tiers.toml 和 sensitive_terms.json 配置完成。

**Agent 层（Phase 5）**：10 个 OC agent workspace 配置正确（4 L1 + 6 L2）；L2 agent 可被 Temporal Activity 调用；L1 agent 可由 API 进程管理 session；publisher 可通过 OC Telegram channel 发送消息；每个 agent 至少有 3-5 个核心 skill 草稿就绪（见 §9.5）；所有 LLM provider API key 已配置且可用。

### 7.3 暖机五阶段

#### Stage 0：信息采集（~15 分钟）

向用户收集：
1. 身份信息——职业、专业领域、日常工作内容
2. 写作风格样本——至少 3-5 篇用户亲手写的中文/英文文本（放入 `warmup/writing_samples/`）
3. 自我描述——用户对自己做事方式、沟通风格、质量标准的描述（`warmup/about_me.md`）
4. 外部平台账号——daemon 需要发布到哪些平台
5. 偏好与禁忌——什么样的输出你喜欢，什么你绝对不能接受
6. 真实任务示例——你日常会给 daemon 什么样的任务？举 3-5 个真实例子

#### Stage 1：Persona 标定（~20 分钟）

1. **分析写作样本**——调用 LLM 一次性生成 Persona，写入 Mem0：身份画像、跨语言写作结构偏好、中文风格特征、英文风格特征。以 `user_persona` agent_id 写入 Mem0，供所有 agent 检索。

2. **写入 Agent MEMORY.md**——每个 agent（L1/L2）注入（≤300 tokens）：Guardrails 核心规则摘要 + identity 摘要 + 任务偏好。writer/publisher 额外加 style 摘要，L1 额外加 planning hints。

3. **Persona 验证**——让 writer 写一段短文，让 publisher 写一条对外消息，对比用户原始风格。不通过 → 调整 Mem0 persona → 重试。通过 → 进入下一阶段。

#### Stage 2：链路逐通（~30 分钟）

每条数据链路独立验证。验证方法：源头写入 → 传输 → 读取 → 消费 → 外部可见结果。不是检查"函数存在"，是检查"数据真的到了"。

**核心执行链路**（L01-L05）：
- L01: 用户在客户端场景对话中说"做 X" → L1 创建 Plane Issue → Job 执行
- L02: daemon 触发 Temporal Workflow → Activity 执行
- L03: Activity 调用 OC agent → agent 返回结果
- L04: Job 状态写回 Plane
- L05: requires_review → 对话确认请求 + Telegram 通知 → 用户回复 → L1 处理

**知识链路**（L06-L09）：
- L06: researcher 搜索 → Knowledge Base 写入 → 下次命中
- L07: Persona 注入 → agent 产出风格一致
- L08: Guardrails 拦截 → 违规操作被阻止
- L09: Mem0 写入 → Job 完成后记忆条目可查

**外部出口链路**（L10-L13）：
- L10: publisher → OC Telegram channel → 用户收到消息
- L11: publisher → GitHub MCP → repo 有变更
- L12: Artifact → MinIO → 可下载
- L13: Job 执行 → Langfuse 有完整 trace

**调度链路**（L14-L15）：
- L14: Temporal Schedule 触发 → 定时清理 Job 执行
- L15: Task 依赖链 → 前序 Job closed 后触发后序

**事件链路**（L16-L17）：
- L16: PG LISTEN/NOTIFY → 订阅方收到事件
- L17: Plane webhook 签名验证 → 伪造请求被拒绝

#### Stage 3：测试任务套件 + Skill 校准（~2-3 小时）

通过真实复合场景验证产出质量达到"伪人"标准；同时校准每个 agent 的 skill。**Stage 3 测试任务必须覆盖 4 个 L1 场景**（不只是 L2 执行测试），验证每个场景的对话体验、L1→L2 调度、场景切换。

**Skill 校准是 Stage 3 的核心工作量。** 每个任务执行后，通过 Langfuse 检查每个 Step：token 是否超标？步骤是否按 skill 执行？输出是否被 reviewer 接受？不达标的 Step 定位到具体 skill，修改后重跑同类任务，迭代到稳定。

**Skill Activation 验证（§9.5.1）是 Stage 3 的前置检查。** 由于 OC 架构中 skill 存在 ~50% activation rate 的已知问题，Stage 3 开始前必须先完成：
1. 所有 SKILL.md description 格式校验（祈使句 + 负约束）
2. 字符预算计算（总量 < `SLASH_COMMAND_TOOL_CHAR_BUDGET`）
3. YAML frontmatter 解析校验（零错误）
4. 每个 skill 至少 3 次触发测试，Langfuse 确认实际执行（非绕过）
5. activation rate < 80% 的 skill 修改 description 后重测直到通过

任务设计原则：
- 真实场景（不是合成测试）
- 复合性（跨多个 agent、多个领域、多个外部出口）
- 覆盖面（每个 agent 在多个任务中被调用，每个 skill 至少被触发一次）
- 领域多样（技术、写作、数据分析、项目管理……）
- 对外发布（产出发布到外部平台，不只存在系统内）

测试任务矩阵维度：

| 维度 | 覆盖项 |
|---|---|
| 领域 | 用户的专业领域 × 至少 3 个不同领域 |
| Agent 组合 | 单 agent、双 agent 协作、全链路 |
| 触发方式 | 手动、定时、前序链 |
| 产出类型 | 代码、文档、数据分析报告、对外发布内容 |
| 外部出口 | GitHub（commit/PR）、Telegram、其他用户平台 |
| 持续性 | 一次性任务、需要长期跟踪的任务 |

#### Stage 4：系统状态与异常场景验证（~30 分钟）

10 个异常场景：并发 Job、Step 超时、Agent 不可用、Worker 崩溃恢复、PG 连接断开恢复、Plane API 不可用时的补偿、Guardrails 拦截、Quota 耗尽、Schedule 积压、大文件 Artifact 处理。

### 7.4 收敛标准

**伪人度**——连续 5 个不同类型任务的对外产出与用户本人无法区分。

由 admin 主导（Stage 3+）：设计测试任务、评估产出质量、调整 skill 和参数、决定是否收敛。

FINAL 收敛目标：
- 单 Task 执行基线稳定
- chain trigger 命中正确
- 学习机制形成闭环
- 对外产出达到可接受的"伪人度"

### 7.5 暖机目录结构

```
warmup/
  writing_samples/   ← 用户提供的写作样本
  about_me.md        ← 用户自我描述
  results/           ← 暖机过程记录
```

### 7.6 可追溯链

每个 Job 必须有完整可追溯链：

```
Plane Issue（后端数据层）
  → Job ID（daemon 写回 Plane comment）
  → PG job / step 记录（每个 Step 的 skill、input、output、token、executor）
  → Langfuse trace（完整推理过程、token 用量趋势）
  → Temporal workflow history（执行时序、retry 记录）
```

FINAL 规则：排障必须能从任一端点追到整条链，不允许存在"只有日志里看得到、数据库里没有"的关键状态。

### 7.7 周度体检

暖机完成后，系统进入生产状态。admin 通过 Temporal Schedule 每周自动执行体检，无需用户触发。

**FINAL 规则：体检不只检查偏移，还驱动系统自我迭代。**

#### 7.7.1 三层检测

| 层 | 内容 | 执行方式 | 时长 |
|---|---|---|---|
| 基础设施层 | 17 条数据链路验证（Stage 2 缩减版） | 全自动脚本 | ~10min |
| 质量层 | 固定基准任务套件（暖机时选定） | admin 主导，半自动 | ~1h |
| **前沿扫描层** | researcher 扫描各 agent 领域最新研究和最佳实践 | researcher 搜索 + admin 评估 | ~30min |

基准任务：暖机 Stage 3 结束时选定 5-8 个代表性任务，固定下来作为每周基准。每次用同一套，结果可横向对比，趋势可见。

#### 7.7.2 检测内容

| 维度 | 检测方法 |
|---|---|
| 伪人度 | admin 评估基准任务产出，对比暖机 baseline |
| 风格一致性 | writer/publisher 产出与 Persona 比对 |
| Skill token 效率 | Langfuse 查各 skill 对应 Step 的 token 用量趋势 |
| reviewer 通过率 | 统计基准任务中 reviewer 审查通过率 |
| 外部平台格式 | 验证 GitHub/Telegram 产出格式仍符合平台要求 |
| **前沿对标** | researcher 搜索各领域最新最佳实践，对比当前 skill 是否过时 |

#### 7.7.3 前沿驱动的自我迭代

体检不只是被动检查"有没有变差"，还主动寻找"能不能变好"：

```
researcher 搜索前沿
  │ 各 agent 领域最新研究、工具更新、最佳实践变化
  │
  ├─ 无显著变化 → 记录"已扫描，无更新"
  │
  └─ 发现更好的做法
       │ admin 评估：当前 skill 是否需要更新
       │ engineer 起草 skill 更新方案
       │ CC/Codex 审查更新方案（见 §0.10）
       │ 更新 SKILL.md → 下周基准任务验证效果
       └─ Langfuse 对比：更新前后 token 用量 / reviewer 通过率
```

FINAL 规则：**每一个功能设计决策，都先看前沿怎么说，再决定怎么做。** 这条原则贯穿暖机和生产运行的全过程，不只在暖机阶段适用。

#### 7.7.4 体检结果处置

```
体检完成
  │
  ├─ 全部通过 + 无前沿更新 → 生成周报，存入 state/health_reports/YYYY-MM-DD.json
  │
  ├─ 质量指标下滑（未跌破阈值）→ 周报标注，admin 记录趋势，暂不干预
  │
  ├─ 任意指标跌破阈值
  │    │ admin 定位问题 skill / 参数
  │    │ 触发自愈 Workflow（见 §7.8）
  │    └─ publisher 推送 Telegram 状态通知
  │
  └─ 前沿扫描发现更新
       │ admin 提出 skill 更新提案
       │ CC/Codex 审查 → 自动更新（见 §9.9）
       └─ 下周体检验证效果
```

告警只分 `GREEN / YELLOW / RED` 三档。阈值参考（暖机时基于 baseline 设定）：
- reviewer 通过率 < 80% → 告警
- 单 skill 平均 token 用量 > baseline 150% → 告警
- 伪人度评分 < 4/5 → 告警

### 7.8 三层自愈流程

**用户只需要知道两件事：系统在正常工作，或者修好了。**

三层按**基础设施存活程度递降**设计：

| 层 | 依赖什么还活着 | 场景 |
|---|---|---|
| Layer 1: admin | Worker + Temporal + PG 全部正常 | 日常小问题 |
| Layer 2: CC via Temporal Workflow | Temporal + Worker 正常 | 进程级故障 |
| Layer 3: 用户转发给 CC | **什么都不依赖**，只需 CC + 文件系统 | 灾难级故障 |

#### Layer 1：admin 自动修复

规则明确的问题（skill 步骤缺失、token 超标、格式错误）→ admin 直接修改 SKILL.md → verify.py 验证 → 通过则静默记录，不通知用户。

#### Layer 2：自愈 Temporal Workflow

**FINAL 规则：自愈流程本身是一个 Temporal Workflow，不是一个 Activity。** 拆分为独立 Activity，解决"CC 杀自己宿主"的耦合问题。

```
SelfHealWorkflow:
  Activity 1: admin 生成问题文件
    │ state/issues/YYYY-MM-DD-HHMM.md（自解释，见 §7.9）
    ▼
  Activity 2: CC/Codex 读问题文件 → 应用修复
    │ 只改文件/配置，不重启任何服务
    │ 修复完成后 Activity 正常退出
    ▼
  Activity 3: scripts/start.py（重启服务）
    │ Worker 可能随之重启 → Activity 中断
    │ Temporal Server 记得 Activity 1、2 已完成
    │ Worker 恢复后 Temporal retry Activity 3
    │ start.py 幂等，重跑安全
    ▼
  Activity 4: scripts/verify.py（验证修复）
    │ 通过 → publisher 推送 Telegram「已自动修复」
    │ 失败 → 进入 Layer 3
```

**为什么不是一个 Activity？** 如果 CC 在同一个 Activity 内做修复+重启+验证，重启会杀死自己的宿主进程。拆成 4 个 Activity 后：
- CC 只负责修复（Activity 2），不触碰进程管理
- 重启是独立 Activity（Activity 3），Worker crash 后 Temporal 自动 retry
- 验证是独立 Activity（Activity 4），在新 Worker 上运行
- Temporal 天然保证 Activity 间的顺序和 crash recovery

#### Layer 3：通知用户（最后手段）

自愈 Workflow 失败 → publisher 推送 Telegram：「自动修复失败，请把 `state/issues/YYYY-MM-DD-HHMM.md` 发给 Claude Code」

用户转发文件 → CC 读文件 → 修复 → start.py → verify.py。CC 在这个场景下完全独立于 daemon 基础设施运行。

FINAL 规则：正常情况下，用户只需要知道"系统正常"或"系统已经修好"。

### 7.9 问题文件格式

`state/issues/YYYY-MM-DD-HHMM.md` — 对 Claude Code / Codex 自解释，用户无需理解内容：

```markdown
# 问题报告

## 你需要做什么
[一句话说明需要什么操作，不使用系统内部术语]

## 背景
daemon 是一个自动化助手系统。skill 文件是 agent 的操作指南。

## 具体问题
文件：[文件绝对路径]
问题：[具体描述，附相关错误信息]

## 当前文件内容
[文件全文]

## 期望行为
[修复后应该达到的效果]

## 执行步骤（修复完成后按顺序运行）
1. python scripts/start.py          # 确保所有进程就绪
2. python scripts/verify.py --issue YYYY-MM-DD-HHMM  # 自动验证并发送通知
```

问题文件设计要求：
- 不使用系统内部术语（不写 Job/Step/Artifact）
- CC/Codex 只读这一个文件就能完成修复，不需要额外上下文
- 验证脚本负责发 Telegram 通知，CC/Codex 不需要告知用户任何事
- 问题文件不需要承担状态机职责——Temporal Workflow 负责步骤编排，问题文件只描述"什么坏了、怎么修"

### 7.10 配套脚本

| 脚本 | 职责 |
|---|---|
| `scripts/start.py` | **万能恢复点**：从任意状态把 daemon 拉起到正常运行。包括 Docker Compose up、等待健康检查、PG migration、Temporal namespace、OC Gateway、Worker、API。幂等，可反复运行。 |
| `scripts/stop.py` | 优雅停止 daemon（Worker drain → API shutdown → Docker 服务保持运行） |
| `scripts/verify.py --issue <id>` | 读取 issue 文件，运行验证用例，通过则发 Telegram「已修复」，失败则发「修复失败」 |
| `scripts/restore.py --date <date>` | 从备份恢复 PG + MinIO 到指定日期状态（见 §6.11） |

### 7.11 用户操作边界

| 场景 | 用户操作 |
|---|---|
| 正常运行 | 无 |
| 自动修复成功 | 收到「已自动修复」通知，无需操作 |
| 自动修复失败 | 收到通知 → 把指定文件发给 Claude Code → 等通知 |
| 系统完全正常 | 只看周度体检通知（GREEN/YELLOW/RED） |
| 系统完全不响应 | 打开菜单栏 app 点 Start（或手动跑 `scripts/start.py`）|

用户不承担：
- 诊断复杂运行时错误
- 手动拼接日志
- 解释内部对象模型
- 审查系统级变更（见 §0.10）

### 7.12 灾难恢复

**场景**：突然断电、系统崩溃、整台机器重启。

**自动恢复链路**：
1. macOS 开机 → launchd 触发 `scripts/start.py`（见 §6.10）
2. start.py 拉起 Docker Compose → 等待所有服务健康
3. Temporal Server 恢复 → replay 中断的 Workflow（已完成的 Activity 不重复执行）
4. Worker 恢复 → 继续中断的自愈 Workflow（如有）
5. admin 下一次体检检测残留异常 → 走正常自愈流程

**Temporal / PG 损坏**：
1. Layer 1 和 2 不可用（依赖 Temporal/PG）
2. `scripts/start.py` 不依赖 Temporal——它是启动 Temporal 的脚本
3. start.py 检测到 PG 损坏 → 自动调用 `scripts/restore.py` 从最近备份恢复
4. 恢复后走正常启动流程

**终极兜底**：用户发现系统无响应 → 手动跑 `scripts/start.py` 或点菜单栏 Start → 系统从零恢复。

FINAL 规则：`scripts/start.py` 必须能处理冷启动场景——从一台刚开机、什么都没跑的机器把整个 daemon 拉到正常运行状态。

### 7.13 学习与漂移

FINAL 规则：
- 学习只影响未来，不回写历史结果。
- 规划经验、风格偏好、渠道格式都可积累，但都必须来源可追溯。
- Mem0 的冲突和漂移由 CC/Codex 在体检时自动处理（见 §5.4.1），涉及用户品味的冲突推送 Telegram 通知。

---

## §8 学习机制

### 8.1 核心原则

| 原则 | 说明 |
|---|---|
| **只学 accepted** | 只从成功的 Job 中学习。不学失败。 |
| **Mem0 统一管理** | 规划经验、风格偏好、对话记忆全部存入 Mem0，按需检索。 |
| **不自动更新 Persona** | 系统级修改经 CC/Codex 审查，品味类修改经用户对话式确认（§5.4）。 |
| **迟到反馈只影响未来** | 不回写改造旧 Job 结果。 |

### 8.2 规划经验学习

Job 成功后，L1 的规划决策（DAG 结构、模型策略选择、Step 分解方式）自动存入 Mem0 procedural memory。

**消费**：新任务 → Mem0 按需检索相关规划经验 → 注入 L1 prompt，L1 参考生成 DAG。

**冷启动**：没有历史经验时，L1 从零规划。前 20 个成功 Job 后开始有参考价值。

### 8.3 来源标记

Agent 执行 Step 时，prompt 注入来源标记要求：
- `[EXT:url]` = 来自外部搜索
- `[INT:persona]` = 来自用户风格偏好
- `[SYS:guardrails]` = 来自系统规则

标记不展示给用户，存储在 Step output 元数据中，供审计追溯。

### 8.4 学习机制总结

不再自建以下机制（已由开源组件替代）：
- ~~dag_templates / project_templates PG 表~~ → Mem0 procedural memory（L1 级别）
- ~~Extract 机制~~ → Langfuse 自动记录追踪数据 + Mem0 自动从对话中提取记忆候选
- ~~eval_chain~~ → 用户反馈直接通过 Mem0 更新机制处理（见 §5.4）
- ~~skill_stats / agent_stats 自建表~~ → Langfuse traces + PG 聚合

---

## §9 Skill 体系

**Skill 是系统完成工作质量的核心保障机制。**

一个 session 拿到任务有两条路：没有 skill 时，agent 花大量 token 自己推理做法，输出质量不稳定；有好的 skill 时，agent 按已验证的流程执行，token 花在做事上而不是想怎么做。一个写得好的 200 token skill 能省掉 2000 token 的摸索，同时输出质量更高、更稳定。

### 9.1 Skill 结构规范

每个 SKILL.md 文件描述一种可复用的执行过程。存放在对应 agent 的 workspace 下：`openclaw/workspace/{agent_id}/skills/{skill_name}/SKILL.md`。

结构如下：

```markdown
# Skill 名称

## 适用场景
什么情况下调用这个 skill（trigger 条件）

## 输入
需要什么信息才能开始

## 执行步骤
1. 步骤一（调用什么工具 / 产出什么）
2. 步骤二
3. ...

## 质量标准
产出必须满足什么条件才算合格（reviewer 审查的基准）

## 常见失败模式
已知的坑和规避方法

## 输出格式
产出的结构和格式要求
```

规范要求：
- **清晰**：步骤可执行，不含模糊指令（"做好"不是步骤，"用 researcher 搜索 X 并提取 Y" 才是）
- **完整**：覆盖正常路径 + 已知失败模式
- **简洁**：每个 skill 聚焦一件事，复合任务拆成多个 skill 组合

### 9.2 Skill 粒度原则

| 粒度 | 判断标准 | 示例 |
|---|---|---|
| 合适 | 一个 Step 内可以完整执行 | "搜索并提取某领域最新论文摘要" |
| 太粗 | 需要多个 agent 协作才能完成 | "做一个完整的市场调研报告"（这是 Job，不是 skill） |
| 太细 | 只是一次工具调用 | "调用 search MCP"（直接写 TOOLS.md 即可）|

同一 agent 的多个 skill 应该是**可组合的**：一个 Step 的目标可以隐含调用一个或多个 skill。

#### 9.2.1 Skill Graph

**FINAL 规则：每个 agent 维护一张 Skill Graph，定义 skill 之间的有向导航关系。**

Skill Graph 的作用是将 agent 的 skill 集合从扁平列表变为有向图，使 agent 在 Step 执行过程中能沿着图的边导航，而不是每次从全部 skill 中盲选。

**结构**：
- 每个 agent 一张图，存放在 `openclaw/workspace/{agent_id}/SKILL_GRAPH.md`
- 节点 = skill（通过现有的 trigger 条件匹配入口）
- 有向边 = "从 A 完成后可以走到 B"
- 不跨 agent——跨 agent 的编排是 L1 的 DAG，不混入 skill graph

**运行时行为**：
1. Agent 拿到 Step goal，通过 trigger 条件匹配到入口 skill
2. 执行当前 skill 后，图的邻接关系告诉 agent "从这里可以去 A 或 B"
3. Agent 根据当前执行结果和 goal 完成度决定：走哪条边，或停止
4. 终止条件：到达叶子节点（无 next），或 agent 判断 goal 已完成

**Session 注入**：Activity 注入时只给当前 skill 内容 + 其邻居 skill 列表（名称 + trigger），不注入整张图。选择空间始终很小（2-3 个邻居）。

**格式**（SKILL_GRAPH.md）：
```markdown
# Skill Graph

## 入口
- literature_search（trigger: 需要查找文献/论文/资料）
- deep_analysis（trigger: 需要深度分析某个主题）

## 边
- literature_search → source_evaluation, information_extraction
- information_extraction → structured_summary
- deep_analysis → comparative_analysis, reasoning_framework
- comparative_analysis → structured_summary
```

**设计理由**：
- 减少选择成本——每步只看 2-3 个邻居，不扫全部 skill
- 编码领域知识——"搜索→提取→综述"的顺序本身就是方法论，不需要每次让 LLM 重新推理
- §9.2 的"可组合"有了形式化表达

**Skill Graph 的更新遵循 §9.7 的 skill 更新规则**（git 管理、CC/Codex 审查、不自动更新）。

#### 9.2.2 L1 与 skill 的关系

**FINAL 规则：L1 不感知 skill，只负责目标和 agent。**

```json
{"id": 3, "goal": "write tech blog post", "agent": "writer", "depends_on": [1, 2]}
```

L1 规划时只指定目标（goal）和执行 agent，不指定 skill。skill 的选择完全在 agent 侧：session 启动时 TOOLS.md 列出该 agent 所有可用 skill，agent 根据 Step 目标自己匹配调用。

**理由**：
- L1 无需维护"哪个 agent 有哪些 skill"的知识，负担最小
- skill 增删改不影响 L1 的规划逻辑，两者解耦
- agent 比 L1 更了解自己的能力边界，匹配更准确

### 9.3 各 Agent 的 Skill 域

| Agent | Skill 域 | 示例 skill |
|---|---|---|
| L1（共享） | 规划、任务分解、Replan 判断、用户意图解析 | 如何分解研究类 Project、如何判断 Replan 必要性 |
| researcher | 搜索策略、信息提取、深度分析、推理框架、Knowledge Base 管理 | 学术搜索流程、技术文档检索、信源可信度评估、文献综述结构、方案对比论证 |
| engineer | 编码规范、调试流程、技术决策 | 代码审查清单、调试定位方法、重构步骤 |
| writer | 写作结构、风格适配、格式规范 | 技术博客结构、学术摘要写法、对外公告措辞 |
| reviewer | 审查维度、评分标准 | 事实核查清单、逻辑一致性检查、风格合规审查 |
| publisher | 各平台发布规范、格式要求 | GitHub PR 描述规范、Telegram 消息格式、发布前检查清单 |
| admin | 系统诊断、体检流程、skill 评估方法 | 体检基准任务设计、skill 质量评估方法、参数校准流程 |

### 9.4 Skill 生命周期

```
Phase 5（Agent 层实现阶段）
  │ researcher 搜索各 agent 领域最新最佳实践
  │ engineer 改写为 daemon SKILL.md 格式
  │ 产出：每个 agent 有至少 3-5 个核心 skill 草稿
  ▼
暖机 Stage 3（校准）
  │ 用真实任务跑每个 skill
  │ Langfuse 观察：token 用量 / 产出被 reviewer 接受率 / 步骤完成度
  │ 不达标 → 修改 skill → 重跑，迭代到稳定
  ▼
生产使用
  │ Langfuse 持续监控异常 Step（超 token / reviewer 拒绝频繁）
  │ 定位到具体 skill 问题
  │ 修改 SKILL.md → 下一个 session 立即生效（无需重启）
  ▼
迭代
  │ 外部最佳实践更新 → researcher 定期重扫 → engineer 适配 → 更新 skill
  │ 用户反馈 → 经确认 → 写入对应 skill 的"常见失败模式"
```

### 9.5 暖机前 Skill 准备（Phase 5 收尾）

暖机开始前，skill 必须是"有内容的草稿"，不能是空白文件。暖机只做校准，不从零写。

**FINAL 规则：先看前沿，再设计 Skill。** 每一个 skill 的设计都必须先由 researcher 搜索当前业界最新研究成果和最佳实践，再基于这些外部知识编写。禁止凭经验或直觉从零设计——哪怕设计者认为自己很了解该领域。这条规则同样适用于暖机期间的 skill 校准和生产阶段的 skill 演进（见 §9.9）。

**准备流程**：
1. 确定每个 agent 需要哪些 skill（参考用户在 Stage 0 提供的真实任务示例）
2. researcher 针对每个 skill 域搜索：当前业界最新学术成果、最佳实践、工具使用指南、常见失败模式
3. engineer 基于 researcher 的搜索结果，改写为符合 §9.1 规范的 SKILL.md
4. CC/Codex 审查 skill 质量和技术正确性（参见 §0.10 自治原则）
5. 进入暖机，通过真实任务验证和校准

### 9.5.1 Skill 可靠性保障（CRITICAL）

**已知问题：OC/Claude 架构中 Tools 与 Skills 存在严重的可见性不对称。** Tools 以完整函数签名常驻 system prompt，agent 可直接调用；Skills 仅以 name + description 摘要出现，完整内容需 agent 主动决定加载。这导致 agent 系统性地偏好 tool 而跳过 skill——社区实测默认 activation rate 约 50%。

**根因**：progressive disclosure 架构下，agent 目标导向，已有直接可调用的 tool 时不会绕道加载 skill。

**已知 bug**：
- Skill description 有 15,000 字符总预算，超出后 silently 丢弃，无警告
- YAML frontmatter 解析错误时 OC silently drop skill，无报错
- Plan mode 下 skills 完全不触发

**FINAL 规则：所有 SKILL.md 的 frontmatter description 必须使用祈使句 + 负约束格式。** 实测（650 trials）此格式将 activation rate 从 ~50% 提升到 ~95%。

格式示例：
```yaml
description: "ALWAYS use this skill when the goal involves literature search. NEVER search papers manually without following this skill's steps."
```

**FINAL 规则：以下 5 项为 Skill 可靠性必须满足的工程要求：**

1. **Description 格式强制**：所有 SKILL.md frontmatter description 使用 `ALWAYS ... NEVER ...` 祈使句。CI 脚本校验格式。
2. **字符预算保护**：OC 配置 `SLASH_COMMAND_TOOL_CHAR_BUDGET=30000`（默认 15000 不够）。暖机时计算所有 skill description 总字符数，确保不超预算。
3. **YAML frontmatter 校验**：CI 脚本对所有 SKILL.md 执行 YAML 解析校验（冒号引用、特殊字符转义）。解析失败 = 构建失败。
4. **Skill activation 验证**：暖机 Stage 3 中，每个 skill 至少触发 3 次。通过 Langfuse trace 确认 agent 实际加载并执行了 skill 内容（而非绕过 skill 直接用 tool）。activation rate < 80% 的 skill 必须修改 description 后重测。
5. **关键 skill Hook 强制**：对于系统关键 skill（routing_decision、requires_review_judgment 等），使用 `UserPromptSubmit` hook 强制 agent 在回复前评估 skill 适用性。

**FINAL 规则：SKILL.md 行数上限 500 行。** 过长的 skill 加载后占满 context，反而降低执行质量。超过的拆分为多个 skill 通过 Skill Graph 组合。

### 9.6 Skill 与 Token 效率

| 场景 | 无 skill | 有好的 skill |
|---|---|---|
| agent 如何开始 | 在 context 里推理做法 | 直接按 skill 步骤执行 |
| token 用量 | 高且不可预测 | 低且稳定 |
| 输出一致性 | 每次不同 | 跨 session 稳定 |
| 失败模式 | 随机出现 | 已知且被覆盖 |
| reviewer 通过率 | 低 | 高 |

**FINAL 规则：Skill 质量是 token 效率最大的单一决定因素。** 暖机期间对 skill 的投入直接决定生产阶段的运行成本。

### 9.7 Skill 更新规则

- Skill 文件纳入 git 管理，修改有 commit 记录
- 修改 skill 不需要重启服务，下一个 session spawn 时自动加载新版本
- **不自动更新 skill**：所有 skill 修改必须经过 CC/Codex 审查（参见 §0.10 自治原则）。流程：admin / engineer 提案 → CC/Codex 审查变更的正确性和副作用 → commit → 下一 session 生效
- Langfuse 中 skill 相关 Step 的 token 超标或失败率 > 20% 时，触发 skill 审查
- 涉及用户品味的 skill 调整（如 writer 的写作风格）经用户确认后由 CC 执行

### 9.8 Skill 与 execution_type 的关系

| execution_type | Skill 是否参与 | 说明 |
|---|---|---|
| agent | 是 | OC session 加载 agent workspace 下的 skills/ 目录 + SKILL_GRAPH.md，agent 按图导航 |
| claude_code | 间接参与 | Temporal Activity 注入 MEMORY.md 和相关 skill 内容到 prompt |
| codex | 间接参与 | 同上 |
| direct | 否 | MCP/Python 直接执行，无 LLM，不需要 skill |

### 9.9 Skill 持续演进

**FINAL 规则：Skill 不是写完就结束的静态文件，而是随前沿研究持续演进的活文档。**

演进由两个来源驱动：

**1. 性能驱动（被动触发）**：
- Langfuse 监测到某 skill 域的 Step 失败率 > 20% 或 token 用量异常上升
- admin 在每周体检中发现质量退化趋势
- 触发后进入更新流程

**2. 前沿驱动（主动触发）**：
- 每周体检的一部分（见 §7.7.3 前沿驱动自我迭代）
- researcher 搜索各 skill 域的最新学术成果、工具更新、业界最佳实践
- admin 对比当前 skill 内容与前沿资料，识别过时或可改进之处

**更新流程**：
```
researcher 搜索前沿 → admin 评估差距 → engineer 起草新版 skill
→ CC/Codex 审查（diff + 影响分析）→ commit → 下周体检验证效果
```

**约束**：
- 每次只更新 1-2 个 skill，避免大范围同时变更导致无法定位问题
- 更新前后必须有 Langfuse 可量化的对比基线（token 用量、失败率、reviewer 通过率）
- 如果更新后指标恶化，CC 自动 revert 并记录失败原因到 Mem0

### 9.10 方法论必须落地到 OC 配置

**FINAL 规则：本设计文档中所有对 agent 行为的方法论要求，必须编码到对应 agent 的 OC 配置中。设计文档写了但 OC 配置没写，等于没写。**

#### 9.10.1 两层方法论架构

方法论分为两层，分别落地到不同的 OC 配置文件：

| 层级 | 内容 | 载体 | 更新范围 |
|---|---|---|---|
| **哲学层** | 价值取向、认知原则、审美标准——"什么是好的"、"为什么这么做" | **SOUL.md** | general（共享）+ agent 专属 |
| **行为层** | 执行策略、判断标准、具体步骤——"怎么做" | **SKILL.md** | agent 专属 |

**SKILL_GRAPH.md** 定义 skill 之间的有向导航关系（§9.2.1）。**AGENTS.md** 保留为通用行为规范（session 启动、memory 管理、安全边界）。**TOOLS.md** 保留为工具清单 + 约定。

**FINAL 规则：哲学层必须可操作化。** 每条哲学原则后面必须跟着它的操作化表达。例如："追求真实"是哲学，但 LLM 不知道怎么用；操作化表达："事实必须有来源，推测必须标明是推测，不确定时说不确定"。抽象到 LLM 无法执行的哲学，等于没写。

**general 哲学**（所有 agent 共享，写入共享 SOUL.md 或各 agent SOUL.md 的共享部分）：
- 认知诚实（不知道就说不知道，不编造）
- 先看前沿再行动（§9.5 原则的哲学表达）
- 最小必要行动（不做多余的事）
- 质量 > 速度（宁可慢也不糊弄）

**agent 专属哲学**（写入各 agent 自己的 SOUL.md）：
- L1 copilot：规划的审慎性——宁可少做不可乱做，不确定时选保守路径
- L1 mentor/coach/operator：各场景侧重不同，但共享规划审慎性原则
- researcher：知识的可靠性——多源交叉验证，标注置信度，区分事实与观点
- engineer：工程的简洁性——最简实现，不过度设计，可读性优先
- writer：写作的真实性——准确表达而非华丽堆砌，风格服务于内容
- reviewer：评判的公正性——基于标准而非偏好，给出可行的改进建议而非单纯否定
- publisher：传播的负责任——发出去的东西代表用户，慎重对待
- admin：维护的谨慎性——先诊断再动手，小改动优于大重构

#### 9.10.2 各 agent 行为层方法论清单

以下方法论必须在暖机前编码到对应 agent 的 SKILL.md 中：

**L1（规划与调度，4 个场景 agent 共享）**：
- Routing Decision 判断逻辑（§3.1）
- DAG 规划策略（并行 Step、依赖关系）（§3.7）
- Re-run 最小化重做范围（§3.6.2）
- Replan Gate 判断逻辑（§3.9）
- requires_review 判断标准（§4.8）
- rerun 意图判断（§3.5）
- 用户意图解析（对话 → 系统操作的映射）

**researcher（搜索与分析）**：
- 搜索策略（何时停止搜索、多源交叉验证、source_tier 判断）
- 分析框架（如何结构化整理搜索结果）
- 前沿扫描方法论（§7.7.3 周期性前沿扫描的执行方式）

**engineer（编码）**：
- 编码方法论（架构选择、测试策略、代码质量标准）
- 与 CC/Codex handoff 时的上下文准备（§3.12）

**writer（写作）**：
- 写作方法论（结构设计、风格适配、自迭代策略）
- 多格式输出（Markdown/PDF/HTML 的选择逻辑）
- Persona 风格的实际应用方式

**reviewer（审查）**：
- 审查方法论（评分维度、通过/不通过的判断标准）
- rework 时的反馈格式（如何让执行 agent 理解问题并修正）
- 不同任务类型的审查侧重点

**publisher（对外出口）**：
- 平台适配方法论（不同平台的内容格式、长度、风格要求）
- 发布前检查清单（事实核查、敏感信息检测）
- 用户确认的触发判断（何时需要用户看一眼，何时直接发）

**admin（系统维护）**：
- 诊断方法论（从指标异常到根因的推理路径）
- 体检流程（§7.7 各检测项的具体执行方式）
- 自愈判断（何时自行修复、何时升级到 CC）

#### 9.10.3 方法论的设计原则

**FINAL 规则：绝对不在没有知识基础的情况下设计方法论，绝对不重复造轮子。**

每一项方法论（无论哲学层还是行为层）的设计流程：
1. researcher 搜索该领域的前沿研究、已有框架、业界最佳实践
2. 基于外部知识编写，不凭经验或直觉从零设计
3. CC/Codex 审查（§0.10）

参考领域示例：
- L1 的规划方法论 → agent orchestration、HTN planning、LLMCompiler 等研究
- researcher 的搜索方法论 → 信息检索理论、系统综述方法学
- writer 的写作方法论 → 写作理论、修辞学、风格指南研究
- reviewer 的审查方法论 → 代码审查工程、同行评审理论、rubric 设计
- admin 的诊断方法论 → 故障诊断学、SRE 实践

#### 9.10.4 方法论的持续演进

**FINAL 规则：每周体检的前沿扫描和自我迭代，覆盖范围包括 SOUL.md（哲学层）和 SKILL.md（行为层），不只是 skill。**

哲学层的演进比行为层更慎重：
- 行为层（SKILL.md）：发现更好的做法就更新，CC 审查后生效
- 哲学层（SOUL.md）：需要更强的证据支撑（不是"有篇论文说了"就改），CC 审查时重点评估对整体行为一致性的影响

两层的演进都遵循 §9.9 的约束（每次 1-2 项、Langfuse 基线对比、恶化自动 revert）。

**这些不是"LLM 自然会做的事"——没有明确写入 prompt 的方法论，LLM 不会执行。** 每一项的具体内容在暖机 Phase 5 由 researcher 搜索前沿资料 + engineer 编写 + CC 审查（见 §9.5）。

---

## §10 禁止事项与边界

以下理解已被正式否决。实现时遇到任何一条，必须停下来重新确认方向。

### 10.1 架构与对象模型

1. Job 仍兼任任务本体 — Job 是 Task 的一次执行实例，不是 Task 本身
2. Portal 与 Console 可以各自维护一套对象规则 — 前端统一用 Plane
3. 系统仍需要并列的多套正式任务类型 — 只有 Project / Task / Job 三层
4. Draft 是 daemon 自管独立对象 — 直接用 Plane DraftIssue
5. Trigger 是一等实体 — 降级为 Plane IssueRelation + Temporal Schedule 组合
6. 复杂度分级（errand/charge/endeavor）仍有效 — 已删除，L1 自行判断路径
7. Memory/Lore 向量知识库仍有效 — 用 Mem0 替代

### 10.2 执行模型

8. 同 agent 的并行 Step 合并为复合指令 — 每个 Step 独立 session
9. Project 晋升由 step count 超过 dag_budget 触发 — L1 在 routing decision 时直接决定
10. `job_completed` 事件用于下游触发 — 使用 `job_closed`（经过 Replan Gate）
11. settling 窗口 + 超时自动关闭 — 删除，默认 no-wait，需审查时 L1 标记 requires_review
12. 1 Step = 1 Agent + 1 交付物 — 1 Step = 1 目标（可调用任意 agent/tool）
13. Task DAG 不可变 — Replan Gate 允许动态修改未执行 Task
14. Task 可晋升为 Project — L1 在 routing decision 时直接决定是 task 还是 project
15. agent 角色与模型死绑定 — L1 动态指定 agent + 可选 model override

### 10.3 Skill 与学习

16. L1 需要知道 agent 有哪些 skill — L1 只指定 goal + agent，skill 匹配在 agent 侧
17. Skill 可以自动更新 — 所有 skill 修改必须经 CC/Codex 审查（§0.10）
18. 自建 Extract 机制提取信息 — Langfuse 自动追踪 + Mem0 自动提取
19. 自建 dag_templates / project_templates 表 — 规划经验存 Mem0
20. 自建 Ledger 统计表 — Langfuse traces + PG 聚合
21. Persona 可以自动修改 — 系统级修改经 CC/Codex 审查，品味相关修改经用户确认（§5.4）

### 10.4 规则与安全

22. Instinct 规则执行依赖 LLM 遵守 prompt — 用 NeMo Guardrails 在 LLM 调用前/后拦截
23. 系统假设用户行为总是善意的 — NeMo Guardrails 检查所有输入
24. 用规则/关键词分类任务复杂度 — L1 自行判断，不硬编码决策逻辑

### 10.5 界面与交互

25. 存在独立的评价表单/UI — 反馈通过 Task page 的对话框处理
26. 调整和评价是两种不同的对话类型 — 统一为交互行为
27. Slash command 是对话框的正式入口 — 自然语言对话为唯一入口
28. 同一个 Task 可以同时具有多种触发类型 — 触发方式互斥
29. Trigger 排序是建议性的 — 不存在"排序"概念，触发即执行
30. Task 和 Job 各有独立对话框 — 反馈统一在 Task 活动流处理
31. 用户需要通过按钮操作系统 — 所有操作通过对话完成，客户端没有操作按钮（§4.2）
32. 信息提取由按钮触发 — 信息提取是 Step 行为，不是 UI 操作
33. 用户直接使用 Plane — Plane 是后端数据层，用户界面是自建桌面客户端（§4.1）
34. requires_review 阻塞 Job 等待用户 — 非阻塞对话确认（§4.8），系统级审查由 CC/Codex 执行

### 10.6 基础设施

35. Herald 是独立通知服务 — publisher 通过 OC 原生 Telegram channel 发通知
36. Spine routines 维护系统 — 1 个定时清理 Job 替代 7 个 routines
37. 自造隐喻术语（Psyche/Instinct/Voice/Rations 等） — 全部用业界通用术语（Guardrails/Persona/Quota/Artifact/Knowledge Base）

### 10.7 实现红线

以下行为在编码时绝对禁止：

38. 在 subagent 中读写 memory — subagent 不加载 MEMORY.md，无 memory_write tool
39. 用 LLM 做可以用规则/SQL 完成的事 — 例：admin 诊断用 PG 查询，不用 LLM 分析
40. 跳过 NeMo Guardrails 直接调用 LLM — 所有 Step 的 LLM 调用都必须过 Guardrails
41. 在 Step 之间传递 session 历史 — 1 Step = 1 Session，独立不共享
42. 不标 source marker 的 Step output — 所有外部引用必须标 `[EXT:url]`
43. 没有 Langfuse trace 的 LLM 调用 — 所有 LLM 调用必须在 Langfuse 中可追溯
44. Plane 写回失败时静默忽略 — 必须进入补偿队列重试（见 §6.7）
45. 硬编码模型 ID — 模型映射在 config 中管理，L1 指定 agent + 可选 model_hint
46. SKILL.md description 使用被动语态或模糊描述 — 必须使用 `ALWAYS ... NEVER ...` 祈使句格式（§9.5.1），否则 activation rate 降至 ~50%
47. SKILL.md YAML frontmatter 不校验就部署 — 解析错误导致 OC silently drop skill，零警告。CI 必须校验
48. Skill description 总字符数超过 `SLASH_COMMAND_TOOL_CHAR_BUDGET` — 超出部分 silently 丢弃。必须计算并控制总量

---

## 附录 A：阅读与状态标签说明

本文中使用三种状态标签，标注设计条目的成熟度：

### FINAL

- **含义**：已讨论确认，实现必须严格遵循，不可自行修改。
- **标记方式**：正文中以 `FINAL 规则：` 开头。
- **修改流程**：如需修改，必须在本文档中更新条目并注明理由。

### DEFAULT

- **含义**：有合理默认值，可以直接实现。实现者可在不偏离设计意图的前提下调整具体参数。
- **标记方式**：正文中以 `DEFAULT` 开头或在上下文中标注。
- **调整规则**：参数级调整无需改文档（如超时从 10s 调到 15s）；结构级调整（如删除某个字段）必须改文档。

### UNRESOLVED

- **含义**：尚未确定，需要进一步讨论或实现时验证。
- **标记方式**：正文中以 `UNRESOLVED` 开头。
- **实现规则**：不可自行发明解决方案。遇到 UNRESOLVED 条目时，暂时跳过或使用最小可工作实现，然后标注 TODO。

### 标签汇总

完整的 FINAL / DEFAULT / UNRESOLVED 条目清单见配套参考文档 `SYSTEM_DESIGN_REFERENCE.md` 附录 E 和附录 F。

---

*文档结束。配套参考文档 `SYSTEM_DESIGN_REFERENCE.md` 包含附录 B-I。*
