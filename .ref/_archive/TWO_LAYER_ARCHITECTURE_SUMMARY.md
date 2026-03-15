# 两层 Agent 架构设计专题

> 本文档汇总 2026-03-15 讨论的完整设计决策。
> 原始对话记录见 `TWO_LAYER_ARCHITECTURE_DISCUSSION.md`。
> 讨论横跨两个 session（compaction 前后），本文档覆盖全部内容。

---

## 1. 起源

讨论起点是用户与他人关于文献获取工具（Elicit/Zotero/Litmaps）的对话。用户意识到一个根本问题：

**用户作为人类，也需要自己的学习-分析-产出流程。daemon 不只是执行器，它和用户的关系是双向的——daemon 也会给用户布置任务、评估产出。**

这一洞察引发了对 daemon 角色定位的根本反思，最终导致了两层 agent 架构的设计。

### 1.1 用户的双重路径

用户原话："一份工作，不仅 agent 这里需要理解，用户作为人类，他也需要一个自己的学习-分析-产出的流程和物理结构。"

同一批材料有两条路径：
- **agent 路径**：Semantic Scholar → RAGFlow → agent 消费 → 产出
- **用户路径**：同样的材料，用户要能浏览、阅读、标注、整理、形成自己的知识结构

现有设计只有 agent 路径，用户路径是空白的。

### 1.2 双向关系

用户原话："daemon 的角色绝不只是一个助手，他其实更像是导师+同事。比如我说，我想学习某个技术/概念，不只是我给他发布任务就完事了，他反过来也会要求我学习/理解 xxx，给我设计好一套学习路线，搭建一套用例，最后根据我做出来的东西给我反馈。"

设计影响：
1. **对话不是单向命令通道** — daemon 需要能主动向用户提要求、布置任务、追踪进度、给出评估
2. **Artifact 不只是交付物** — 还包括学习材料、练习、用例、用户提交的作业、daemon 的反馈
3. **用户的工作也需要物理结构** — 需要有地方存、有结构组织、能被 daemon 读取和评估
4. **进度追踪是双向的** — 不只追踪 daemon 的 Job 进度，也要追踪用户在学习/理解上的进度

### 1.3 用户的工作环境

用户原话："用户做的事，就像是一个学生在系统提交 assignment 一样（可以是推到 github，可以是创建一个 claude project，可以是用 google docs）。"

原则：**用户不在 daemon 里做作业。** 用户在自己习惯的工具里做，daemon 去那些地方读取和评估。daemon 的职责是布置、监测、评估。

用户原话："可以在系统里做一个系统。给这些外部接口（说不定产物预览那里就直接用 google docs？），然后提交的时候，系统才收到通知。"

具体链路：
1. daemon 通过对话布置任务 → 同时在 Google Drive 创建文档（模板/结构预设好）
2. 桌面客户端的浏览器 view 直接打开 Google Doc → 用户在里面工作
3. 用户完成后通知 daemon（对话里说"交了" / 文档状态变化触发）
4. daemon 读取文档内容 → 评估 → 在对话里给反馈

### 1.4 MCP 工具的扩展

用户原话："mcp 需要的比我们想的多得多。"

现有 MCP 主要是 agent 工作工具（搜索、Plane、代码索引等）。新增的是 **daemon 和用户之间的协作界面**：
- Google Docs/Drive API（创建文档、读取内容、监测变化）
- GitHub API（不只是 daemon 自己的代码，还有用户的提交）
- 其他用户工作/生活平台

`config/mcp_servers.json` 会比现在大得多——不只是 agent 工作工具，还包括所有用户生活/工作平台的连接器。

### 1.5 用户任务的执行模型

用户原话："任务把用户的部分也算进去了，这里似乎就不适合阻塞了，而是等待然后开启新任务？"

用户是执行者时，执行时间是小时到天级，daemon 不可能阻塞。最终方案：用户的行为不进对象模型（不是 Task/Step），而是 **外部事件**。daemon 通过 trigger 机制（event/time/inactivity）监测用户的提交，触发下一阶段。

### 1.6 为什么要独立模式

用户原话："可能可以为导师模式专门设计，不和我们当前的执行混淆。入口也用专门的一个 agent 来做交互，也防止角色混淆。"

用户原话："导师模式在用户端另外做一个界面，从对话入口就分开。"

这是两层架构的直接起因——从对话入口就分开，防止角色混淆。

## 2. 核心原则：场景-角色-行为

**§0.11 场景认知原则**（已写入 SYSTEM_DESIGN.md）

核心主张：**人类不是任务导向的，是场景导向的。** 当人类被置于不同场景下，思维模式会切换。

- 坐在教室里 → 学习心态，主动提问，接受评价
- 面对教练 → 执行心态，关注数字，接受批评
- 和同事协作 → 指挥心态，关注效率和结果
- 看运营报表 → 监督心态，退后一步看全局

**场景决定角色，角色决定行为。不是反过来从行为推场景。**

L1 agent 不是功能模块，是**认知触发器**。用户打开 mentor 对话的那一刻，不只是 daemon 切换了行为，用户自己的思维模式也切换了。

同一个活动（比如"做项目"），在不同场景下性质完全不同：
- mentor 场景：daemon 搭好脚手架和材料，用户亲手实现，重点是学会
- copilot 场景：daemon 去实现，用户看技术文档理解结果，重点是产出

区分依据不是"做什么"，而是用户在场景中的**认知模式和行为状态**。

### 前沿调研结论

经过正式调研确认：

- 两层分离（编排层 vs 执行层）是行业成熟模式
- 但**按权力关系/场景分 L1 agent** 在现有文献中没有对应
- 最接近的是 "Levels of Autonomy for AI Agents"（arxiv:2506.12469），但该论文把自主性当作连续轴，而 daemon 用离散场景
- 连续轴改变的是 agent 行为；离散场景改变的是**用户和 agent 双方**的行为

## 3. 架构：4 L1 + 6 L2

### 3.1 L1 场景 agent（面向用户）

| 名称 | 场景 | 关系 | 用户认知模式 |
|---|---|---|---|
| **copilot** | 日常工作 | 用户主导，daemon 执行+建议 | 指挥、决策、关注结果 |
| **mentor** | 学习指导 | daemon 引导，用户学习 | 学习、探索、接受评价 |
| **coach** | 计划表现 | daemon 规划，用户执行 | 执行、突破、关注表现 |
| **operator** | 持续运营 | daemon 自主，用户监督 | 监督、审视、关注策略 |

说明：
- 4 个 L1 agent 并列，没有谁是"主"
- 每个都是 OC agent，有 MCP/skill 访问权限
- 每个单实例，可多 session 并发
- counsel 消失，其能力（DAG 规划、Replan Gate、路由）泛化为所有 L1 的共享基础能力

### 3.2 L2 执行 agent（面向任务）

| 名称 | 能力 |
|---|---|
| **researcher** | 搜索、调研、分析、推理 |
| **engineer** | 编码、技术实现、调试 |
| **writer** | 写作、内容生产 |
| **reviewer** | 质量审查、评估 |
| **publisher** | 对外发布、通信 |
| **admin** | 系统维护、体检、自愈 |

说明：
- L2 维持 6 个，能力缺口（视觉、持续监测、数据分析）用 MCP + skill 补
- L2 机制不变：1 Step = 1 Session，Temporal 管理

### 3.3 两层关系

- L1 定义"怎么和用户协作"，L2 定义"怎么把事情做出来"
- L1 简单任务自己做（route="direct"），复杂任务派给 L2
- L1→L2 不走 OC spawn；L1 输出结构化动作 → daemon 创建 Task/Job/Step → Temporal → L2 OC session
- L2 结果完成后，daemon 主动往 L1 对话推消息，不需要用户先说话

**为什么要拆两层（L1/L2 gap 的设计理由）**

用户原话："L1 agent 的行为，与 L2 agent 的行为的 gap。一个 agent 根据对话自己就能执行任务，我们设计的这么复杂，为什么呢？"

核心原因：**L1 的对话和 L2 的执行，生命周期根本不同。**

| 问题 | L1 自己做 | 拆给 L2 |
|---|---|---|
| 用户关掉 app | 执行中断 | Temporal 继续跑 |
| 执行失败 | 整个对话受影响 | 隔离重试，对话不断 |
| 多任务 | 串行 | Temporal 并行 |
| 长任务（30min+） | 阻塞对话 | 后台执行，完成通知 |
| 追踪和审计 | 翻聊天记录 | Job/Step/Artifact 结构化记录 |
| 专业化 | 一个 agent 带所有工具 | 每个 L2 有精准的工具集 |

**但不是所有事都走 L2。** L1 routing 判断标准：
- 几秒内能完成 → L1 直接做（direct）
- 需要几分钟以上 → L2
- 需要不同专业能力 → L2
- 需要后台持续运行 → L2
- 需要结构化追踪 → L2

L1 是"有手有脚的对话者"，简单的事自己干，复杂的事分配给专人。

**L1→L2 调度的具体流程**

```
L1 agent 输出：{"action": "create_task", "goal": "搜索半马训练计划的最新研究", "agent": "researcher", "context": "..."}
  ↓
daemon 创建 Task → Job → Step
  ↓
Temporal workflow 启动 → 创建 L2 OC session（researcher）
  ↓
daemon 注入：Step 指令 + 从 L1 对话历史提取的相关上下文 + Mem0
  ↓
researcher 执行，结果写回 PG
  ↓
L1 agent 下次被唤醒时，daemon 把结果注入上下文
```

L1 agent 在一次 session 里可能同时做三种事：和用户对话（纯文本回复）、direct 执行（自己调 MCP tool）、输出结构化动作让 daemon 创建 task/project。三种行为自然发生，agent 自己判断。

### 3.4 合并推导过程

最初讨论了 7 个行为模式 agent：counsel / mentor / brainstorm / creative / coach / operator / curator

合并理由：
- counsel 和 brainstorm、creative 重叠——都是"用户和 daemon 对话中自然发生的事"
- coach 和 mentor 需要分开——关系本质不同（教能力 vs 盯承诺）
- curator 合入 operator——"只看不做"是运营的子集

最终收敛为 4 个，每个的**交互循环、持久上下文、用户认知模式**互不相同。

关键合并判断（用户原话）：
- "我觉得是 counsel 和 creative、brainstorm 这几个重叠了。" — counsel 就是日常对话，brainstorm 和 creative 是对话中自然发生的事，不需要独立 agent
- "导师与学生（学习-指导场景），教练与选手（计划-表现场景），同事协作（工作-交流场景），与外部世界交互（获取-发布场景）。" — 用户自己提出的四种角色关系
- copilot 的命名来自用户的要求："总感觉没达到那个意思。你想想现代职场，这种人一般叫什么。" — copilot：你是 pilot，daemon 是 copilot
- "这7个也是如果能用 mcp+skills 解决的，不需要增加一个 agent。" — agent 数量最小化原则

## 4. 十个设计决策

### 4.1 七个初始问题

**Q1: L1 session 模型**

用户原话："我们的对话是由 daemon 维护的。如果要压缩，也是 daemon 这边做提取信息和压缩，而不是 OC 那边撑爆 session context。"

用户原话："每句话都一个新 session？这不对吧。应该是一个 session 快满了，就压缩然后把压缩过的开一个新 session。当然可能还有更好的方法，比如我们就给 4 个 session 的空间连着，满了就压缩第一个，然后再往第一个放。"

持久 OC session。daemon 全权管理上下文：
- 连续对话中：直接 `sessions_send`，零额外开销
- session 接近上限时：daemon 做压缩（不等 OC compaction），开新 session 接上
- 一个 L1 agent 可以有多个 OC session 串联，等效于 context 容量翻倍
- 旧 session 保持不关闭，原文完整保留

daemon 在 OC 触发 compaction 之前主动介入（`contextTokens` 到 70% 时），防止 OC 自带压缩丢失重要信息。

**OC 自带的 compaction 机制**（调研结果）：
- 接近 context 上限时自动触发，把旧对话压缩成摘要
- 压缩前做 memory flush（把重要信息存到文件）
- daemon 当前配置：`"compaction": {"mode": "safeguard"}`
- daemon 已有 `session_status` 接口能查 `contextTokens`，可监控离上限多远
- **问题**：OC 的压缩不知道什么对 daemon 重要，会丢失关键设计决策和用户纠正（本次对话就出现了这个问题）

**多 session 串联方案**：
```
copilot session 1 (满了，保持，原文完整)
copilot session 2 (满了，保持，原文完整)
copilot session 3 (当前活跃)
```
daemon 控制当前消息发到哪个 session、什么时候开新 session、需要引用历史时从 PG 拉。

对话历史 4 层压缩（daemon 侧）：

| 层 | 内容 | 存储 |
|---|---|---|
| 原文层 | 最近 N 轮完整对话 | PG `conversation_messages` |
| 摘要层 | 较早对话的压缩摘要 | PG `conversation_digest` |
| 决策层 | 承诺、决策、行动项单独提取 | PG `conversation_decisions` |
| 记忆层 | 跨会话长期经验 | Mem0 |

**Q2: L1 和对象模型的关系**

用户原话："所有的这些都是 project，这种 project 就和 claude 的那个 project 是一回事了，因为我们有 agent 来做维护了，不用担心没人来管 project 的走向。"

所有持续性主题都是 Project。Project 带 scene 标签，各场景各自管理。

mentor 场景中一个 Project 的结构示例（如"学 transformer"）：

| 步骤 | 后端对应 |
|---|---|
| 准备教学内容 | Task → L2 (researcher/writer) |
| 讲概念（交付） | L1 对话 |
| 搭脚手架、准备作业环境 | Task → L2 (engineer) |
| 布置作业 | L1 对话 |
| 用户做作业 | 外部事件（不在对象模型里） |
| 审阅成果 | Task → L2 (reviewer) 或 direct |
| 给反馈 | L1 对话 |

一个 Project 里，对话和 Task 交替出现。L1 是 Project 的持续维护者。

**Q3: L1 如何调度 L2**

用户原话："spawn 是不行的。所有的 agent 行为都在我们的管理框架下运作。很简单的道理，需要的信息是我们主动设计注入的。"

不用 OC spawn。L1 输出结构化动作，daemon 解析后创建 Task/Job/Step，走 Temporal → L2 OC session。daemon 负责注入所有上下文。

复用原有 routing 机制：

| route | 谁做 | 机制 |
|---|---|---|
| `direct` | L1 自己 | L1 session 内调 MCP tool |
| `task` | L2 | daemon 创建 Task → Job → Step → Temporal |
| `project` | L2（多任务） | daemon 创建 Project → 多 Task |

**Q4: 外部平台监测 / 用户作业提交**

用户原话："不止是这些外部工具，还有好几个。监测我看可以在 daemon 中主动设计一些系统。比如 mentor 那里，就模仿学校的 assignment，有上交有下发。coach 可以定时获得计划的执行情况（比如在 intervals.icu），定期来做讨论和调整。其他的也是，有监测、汇报、查看的系统。就像一个人可能既用着学校的系统，也用着运动管理网站，还用着社媒账号，每天用不同的方式 input 和 output。"

每个场景有自己的外部平台生态，daemon 作为集成中枢管理所有的 input/output：

| 场景 | 外部平台（示例） | input | output |
|---|---|---|---|
| mentor | Google Docs, GitHub | 用户提交作业 | 教材、练习、反馈 |
| coach | intervals.icu, 健身 app | 训练数据、执行记录 | 计划、分析、调整建议 |
| operator | Twitter/X, 小红书, RSS | 平台数据、趋势 | 内容发布、互动 |
| copilot | GitHub, Google Docs | 工作产出 | 执行结果、文档 |

每个场景的监测机制不同：
- mentor：**assignment 系统** — daemon 在 Google Docs 创建作业文档，用户完成后告知或 daemon 监测文档更新（webhook/轮询）
- coach：**定时数据拉取** — Temporal Schedule 定期从 intervals.icu API 拉数据，生成分析
- operator：**持续监测 + 自主行动** — Temporal Schedule 定期检查平台数据，触发内容生产和发布
- copilot：**按需** — 用户在对话里说需要什么，daemon 去取

原则：**webhook first，没有 webhook 的才用轻量轮询兜底。** daemon 侧统一抽象为 event。

**Q5: L2 结果怎么回到用户**

用户原话："主动在对话里推消息。telebot 我在想是不是完全和 daemon 对话同步？这样费 token 吗？"

daemon 主动往 L1 对话推消息，不需要用户先说话。Telegram 完全同步。Telegram 同步本身不费 token（只是消息转发），费 token 的是用户回复（不管从哪个端回复都一样）。

**Q6: L1 的主动行为**

L1 每次对话结束时输出 follow-up 触发条件。daemon 注册并执行。三种类型：

| 类型 | 触发机制 | 例子 |
|---|---|---|
| **event** | 外部数据变化（webhook/轮询） | intervals.icu 有新数据 |
| **time** | 一次性或周期性 | "三天后提醒交作业" |
| **inactivity** | 用户沉默超阈值 | 一周没来 → 主动问 |

agent 决定回来的时机和理由，daemon 负责执行触发。用户感知到的是 agent 在关注自己，不是机械打卡。

**Q7: 跨场景 Project**

Project 跟场景走，不跨场景。同一主题在不同场景下是不同的 Project。跨场景关联由 daemon 注入层处理（从其他 agent 的对话历史拉相关片段），不需要 Project 结构支持。

### 4.2 三个补充问题

**Q8: 注入层怎么决定注入什么**

规则 + 元数据匹配，不用 LLM。

- 连续对话中：不注入，上下文已在 session 里
- session 恢复时（对话中断后）：按 project_id / 标签匹配新信息（哪些 L2 Task 完成了、哪些 trigger 触发了）
- 事件驱动，不是每句话都检查

**Q9: 压缩谁来执行**

daemon 做，LLM 压缩，Temporal 后台任务。`contextTokens` 到 70% 时触发。频率很低，token 开销可接受。

重要信息不因压缩丢失：
- 已确认的设计决策 → 提取到 `conversation_decisions`，永不丢失
- 用户纠正过的理解 → 提取到 Mem0，每次注入
- 具体讨论过程 → 可以压缩，但决策结论保留

**Q10: L1 怎么知道 L2 能做什么**

写在 L1 agent 的 SKILL.md 里。SKILL.md 是 OC agent 定义的一部分，所有 session 共享，不需要每次注入。静态信息，只有每周体检（§9.10.4）时才可能更新。

## 5. 交互设计

### 5.1 四个独立对话

桌面端方案（讨论中确定）：
- 同一个桌面客户端，左侧对话列表切换（类似微信多个聊天）
- 每个对话有自己的上下文和 agent 身份
- 浏览器 view 和阅读器 view 是共享的（导师让你读的论文，和任务产出的文档，在同一个阅读器里看）

Telegram：4 个独立 bot，各自 DM（不放在一个群里——场景之间没有协作关系，混在一起破坏场景感）

用户原话："对话里不发链接，我们要专门的系统设计接口做展示。用户或者 agent 都知道在哪看，比如 google docs。"

对话是纯文本。产物在哪看，用户和 agent 都知道：
- 文档类 → Google Docs（浏览器 view 打开）
- 代码类 → GitHub repo
- 数据类 → intervals.icu 等专门平台
- 阅读类 → 阅读器 view

对话是对话，展示是展示，各有各的系统。

### 5.2 场景迁移

需要用户感知和同意。这和 §0.9（系统内部实现无感）不同——场景切换改变的是权力关系，用户必须明确知道。

agent 之间无控制权。agent 能读彼此历史（daemon 注入），但不能控制彼此对话。用户自己在场景间导航，agent 最多说"你可以去找 mentor 聊这个"。

### 5.3 长期任务

用户原话："这可以替代过去的'长期任务'的意义，长期任务并没有一个 agent 做维护、理解长期任务的含义、定期做反馈。这样才能真的把 agent 的作用发挥出来。"

用户原话："即使在过去那种发布-产出的单一任务模型下，我对长期任务/单一领域任务一直不太清楚。没有 agent 维护的情况下，如何保证若干步之后仍然在正确的轨道上？现在这个问题可以解决了。"

长期任务不是"一直在跑的进程"，而是"随时可重建的对话关系"。L1 agent 不需要一直活着——它的记忆在 PG 和 Mem0 里，下次用户来找时 daemon 把上下文拼回来。

每个 L1 agent 就是原来 counsel 的泛化：持续维护自己场景内的所有 Project，理解上下文，主动反馈。这解决了旧设计中"长期任务没人维护、若干步后偏离轨道"的根本问题。

### 5.4 对话历史的归属

用户原话："这个对话历史，还不是 OC session 的对话历史，是我们 daemon 的对话历史，我们可以自己决定如何利用这个对话历史。在把他们接到 session 前我们就可以决定如何利用。"

两层生命周期：

| 层 | 生命周期 | 存储 | 状态维护 |
|---|---|---|---|
| L1 对话 | 持久，和用户关系一样长 | daemon PG | 对话历史 + Mem0 |
| L2 执行 | 短命，1 Step = 1 Session | OC session（临时） | 执行完就销毁 |

### 5.5 L1 与 counsel 的关系

用户原话："我记得之前是把动态计划管理交给了 counsel 对吗？现在相当于每个 L1 都是 counsel，只不过他们的思考方式、工作模式不同。"

对。原来 counsel 做的所有事（对话、routing 决策、Job DAG 规划、Replan Gate），现在四个 L1 agent 每个都有。区别只在于 SOUL.md 和 SKILL.md 不同。counsel 的名字消失了，但能力泛化为 L1 共享基础。

**注意**：L1 不按"规划什么"区分（那是任务导向思维），而是按场景区分。四个 agent 的底层机制完全一样（OC session + MCP + L2 调度 + Temporal），上层行为由 SOUL.md + SKILL.md 决定。

### 5.6 角色扮演 vs 架构层场景设计

用户原话："现在确实有很多那种 chatbot 做角色扮演，但是好像内部机制没有做相应的设计。"

市面上的角色扮演 chatbot（Character.ai 等）做的是**表演层的角色扮演**——换名字、换语气、换人设，但底下机制一样。daemon 的设计不同：**场景不只改变 agent 怎么说话，而是改变整个系统怎么运作。**

- mentor 场景：布置作业、创建 Google Doc、等待用户提交、评估产出——完全不同的执行流程
- coach 场景：设定量化目标、定期拉取数据、生成表现分析——又是不同的执行流程
- operator 场景：自主行动、定期汇报——执行节奏都不一样

从 prompt 到 session 到 Job 到 Temporal workflow，整条链路都跟着场景变。这是"表演层角色扮演"和"架构层场景设计"的本质区别。

### 5.7 operator 的切换

不是从其他 agent"切换"到 operator，是**派生**。任何 L1 对话到某个点发现需要持续自主管理的事，建议用户开 operator。

运动计划全程由 coach 管（daemon 规划、用户执行、daemon 评估调整），不是 operator。区别在于**谁是执行者**——用户还是 daemon。

### 5.8 客户端 UI 架构

**原则：专业工具外部调起，轻量展示 panel 内嵌，客户端只做调度和聚合。**

桌面客户端（Electron）有三种展示模式：

| 模式 | 技术 | 用途 |
|---|---|---|
| **对话** | 纯文本 | 和 L1 agent 交流 |
| **场景 panel** | 自研 UI（PG 数据驱动） | 状态总览 + 入口聚合 |
| **浏览器 view** | Electron BrowserView / WebView | 打开外部工具网页 |

各场景的 panel 设计：

| 场景 | panel 内容（示例） |
|---|---|
| mentor | 当前学习计划、assignment 列表（待交/已交/已评）、学习进度 |
| coach | 本周计划执行率、最近训练数据摘要、下次评估时间 |
| copilot | 活跃 Project 列表、进行中的 Task 状态、最近产出 |
| operator | 各平台运营数据、待审内容、自动发布日志 |

外部工具的打开方式：

| 工具类型 | 方案 | 理由 |
|---|---|---|
| Web 平台（Google Docs, intervals.icu, 社媒后台） | 浏览器 view 内嵌 | 不离开客户端，保持场景感 |
| VS Code | 系统调起本地 VS Code（`code` CLI / `vscode://` URI） | VS Code 本身是 Electron，嵌入 = 双 Chromium，无意义 |
| 代码查看/轻量编辑 | panel 内嵌 Monaco Editor | VS Code 编辑器内核，足够轻 |
| 移动端 | Telegram DM + 链接跳转 | 无自研 app |

关键设计决策：
- **客户端不替代专业工具**，只做入口和聚合。用户在 Google Docs 里写作业，不在客户端里写。
- **assignment 系统是 panel 功能**，不是独立应用。mentor panel 显示作业列表和状态，提交入口指向外部工具（Google Docs / GitHub），daemon 通过 webhook 或轮询感知提交。
- **对话和展示严格分离**。对话里不出现链接和富内容，该看什么、在哪看，用户和 agent 心里都清楚。

## 6. 三层上下文模型

daemon 有三个平行的上下文来源：

| 来源 | 特点 | 存储 |
|---|---|---|
| 对话历史 | 短期、具体、带时序 | daemon PG |
| Mem0 | 长期、抽象、经验性 | Mem0 |
| knowledge_cache | 外部知识 | RAGFlow |

daemon 按需组合注入到 L1/L2 session 中。

daemon 在组装 session 上下文时决定注入什么。L1 agent 甚至不需要知道另一个 L1 agent 的存在——daemon 自己知道就行。"跨 agent 共享上下文"不需要 agent 之间直接通信。

## 7. Token 效率

- 持久 session + prompt caching → 前缀稳定 → 缓存命中率高 → 大部分 input token 走缓存价
- 多 session 串联 → context 容量翻倍，减少压缩频率
- daemon 在 OC compaction 前主动介入 → 压缩质量可控，重要信息不丢
- 连续对话不额外注入 → 零开销
- 简单回复可轻量处理
- SKILL.md 是 agent 定义，不重复注入

## 8. 补充设计决策（2026-03-15 第二轮）

写入 SYSTEM_DESIGN.md 前的 gap 审查，逐项讨论确认。

### 8.1 L2 agent 最终命名

**废弃古风名，使用现代名。**

| 旧名（废弃） | 新名（最终） |
|---|---|
| scholar | **researcher** |
| artificer | **engineer** |
| scribe | **writer** |
| arbiter | **reviewer** |
| envoy | **publisher** |
| steward | **admin** |

所有 workspace 目录、Mem0 bucket、openclaw.json、SKILL.md 路径跟着改。§1.8 废弃术语表同步更新。

### 8.2 L1 session 的进程归属

**L1 session 由 API 进程管理，不走 Temporal。**

理由：
- L1 是对话伙伴（秒级响应），不是任务执行器（分钟级）
- 走 Temporal signal 转发消息会引入不必要的延迟和复杂度
- API 进程已有 WebSocket 长连接，L1 OC session 是 WebSocket 的后端
- 重活（L2 执行、压缩、Replan Gate）仍走 Worker + Temporal

数据流：
```
用户消息 → WebSocket → API 进程
  → sessions_send(L1 OC session) → 流式响应 → WebSocket → 用户
  → L1 输出 structured action → API 创建 Temporal workflow → Worker 执行 L2
  → 消息存 PG (conversation_messages)
```

§6.2 规则修订："不允许在 API 进程里运行 Temporal workflow 或 L2 执行链"（原来是"不允许跑长执行链"，现在 L1 对话不算"长执行"）。

### 8.3 L1 对话历史 PG 表

4 层压缩模型需要 3 张新表（第 4 层 = Mem0，已有）：

| 表 | 用途 |
|---|---|
| `conversation_messages` | 原文层：每条消息（scene, session_key, role, content, metadata, created_at） |
| `conversation_digests` | 摘要层：一段对话压缩后的摘要（scene, source_range, summary） |
| `conversation_decisions` | 决策层：从对话中提取的关键决策（scene, project_id, decision_type, content, source_message_id） |

**scene 是过滤列，不是硬分区。** 正常操作查本 scene，daemon 注入层可跨 scene 查（按 project_id / tags）。decisions 表尤其需要跨 scene 可查——一个决策和哪个主题相关比它在哪个场景产生更重要。

### 8.4 counsel 消失的级联影响

counsel 名字消失，能力泛化为 4 个 L1 共享基础。具体规则：

| 原来的 counsel 行为 | 新归属 |
|---|---|
| Routing Decision（§3.1） | 每个 L1 自己做。用户已选场景 = 选了 L1，L1 自主判断 direct/task/project |
| Replan Gate（§3.9） | 哪个 L1 创建的 Project，由哪个 L1 做 Replan |
| DAG 规划 | L1 共享能力，写在各 L1 的 SKILL.md 共享部分 |
| 用户意图解析 | L1 在对话中自然完成 |

文档中所有 "counsel" → "L1 agent"（泛指）或具体 L1 名字（特定场景）。

### 8.5 暖机分工

| 阶段 | 主导者 | 说明 |
|---|---|---|
| Stage 0-2 | **CC（Claude Code）** | 搭 OC workspace、写 SOUL.md/SKILL.md、基础设施验证。admin 自己也是被暖机对象，不能给自己暖机 |
| Stage 3+ | **admin** | 系统运转后接管：跑测试任务、评估产出、校准参数 |
| 全程 | **用户** | Stage 0 提供信息、Stage 1 确认 Persona、最终验收 |

Stage 3 测试任务必须覆盖 4 个 L1 场景（不只是 L2 执行测试）。

### 8.6 活动流归属变化

**场景对话流是用户看到的主流，Task 活动流降为后台数据。**

- 用户体验 = "和 mentor 聊天"，不是"查看 Task A 的活动记录"
- 一次对话可能跨多个 Project/Task，甚至纯闲聊
- L2 执行结果由 L1 在对话里自然汇报，用户不直接看 Task 活动流
- Task 活动流保留（L2 执行记录 + 审计追溯），但面向 CC/admin

### 8.7 Plane scene 组织

**[DEFAULT]** Plane 是后端数据层，用户不看。具体怎么按 scene 组织 Plane Project 是实现细节，实现时决定。

### 8.8 4 个 Telegram bot

4 个独立 Bot Token，用户在 Telegram 里看到 4 个联系人，各自 DM。和桌面客户端的 4 个聊天页面完全同步。

## 9. 待写入 SYSTEM_DESIGN.md 的章节

| 章节 | 改动 |
|---|---|
| §0.11 | ✅ 已写入 |
| §1.4 agent 架构 | 7 agent → 4 L1 + 6 L2，两层定义 |
| §2 agent 定义表 | 重写，分 L1/L2 两张表 |
| §3 执行模型 | counsel 的规划/routing 泛化为 L1 共享能力 |
| §4 客户端 | 一个对话 → 四个独立对话 |
| §4.9 API | 四个场景的路由 |
| §4.10 Telegram | 四个独立 bot DM |
| §5.3 Persona | SOUL.md 扩展到 L1 |
| §5.4/5.5 Memory | 对话历史作为新的上下文来源 |
| §7 暖机 | L1 agent 的暖机流程 |
| §9.10 方法论 | L1 也需要 SOUL.md + SKILL.md |
| §10 禁止事项 | 更新 |
| 附录 C/D/E/I | 全部同步 |

## 9. 设计中纠正的错误

记录讨论中出现的错误理解，防止重犯：

1. **L1 不需要 MCP/OC** → 错。L1 是 OC agent，需要 MCP tool。
2. **每句话新建 session** → 错。持久 session，daemon 管压缩。
3. **L1 按"规划什么"区分** → 错。L1 是场景导向的，不是任务导向的。
4. **operator 多实例** → 错。单实例多 session，多实例 = 任务导向。
5. **对话里发链接** → 错。对话纯文本，富内容在专门系统。
6. **"谁主导"区分场景** → 不够。要看用户在场景里的实际行为和认知模式。场景-角色-行为，不是反过来。
7. **4 个 bot 放一个 Telegram 群** → 错。场景之间无协作，独立 DM。
