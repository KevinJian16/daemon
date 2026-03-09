# Daemon 术语体系

> 日期：2026-03-08
> 状态：**已确认**
> Daemon 系统内部术语与用户面用语的完整规范。重命名实施和交互设计的唯一依据。

---

## 第一部分：系统术语

### 0. 身份与原则

**Daemon 是一个引导灵（δαίμων）**——有自己的心智，在幕后自主运作，替人行事。

所有术语回答一个问题：**"这是 daemon 的什么？"**

意象域分布：
- **心智/有机体**（daemon 怎么活）：Psyche, Memory, Lore, Instinct, Spine, Nerve, Cortex, Trail, Canon, Pact, Pulse
- **意志/行为**（daemon 怎么做事）：Will, Voice, Cadence, Herald, Design, Brief, Move
- **宫廷/随从**（daemon 的班底）：Retinue, Counsel, Scout, Sage, Artificer, Arbiter, Scribe, Envoy
- **治理/驱使**（daemon 驱使随从的结构）：Dominion, Writ, Deed, Passage
- **世界观**（daemon 的存在条件）：Ward, Ration, Ether, Ledger, Vault, Offering

设计约束：
1. **同机制下词义关联**：同一机制内术语来自同一意象域。
2. **机制间意象连贯**：不同域描述同一个存在的不同侧面，不冲突。
3. **强 Claude 风格**：优雅、克制、有文化底蕴。选词文学性优先。
4. **daemon 一致性**：每个术语都能放进"daemon 的 ___"句式中自然成立。

---

### 1. 全量改名映射

#### 1.1 Daemon 的心智

| 当前 | → 新名 | 说明 |
|------|--------|------|
| Fabric | **Psyche** | 心灵。daemon 的心智总称，容纳 Memory / Lore / Instinct |
| Playbook | **Lore** | 学识/阅历。daemon 从过往经验中积累的智慧 |
| Compass | **Instinct** | 本能/直觉。daemon 的偏好和倾向 |

#### 1.2 Daemon 的意志与行为

| 当前 | → 新名 | 说明 |
|------|--------|------|
| Dispatch | **Will** | 意志。daemon 通过 Will 做出决策、驱动执行 |
| Dialog | **Voice** | 声音。daemon 与人对话的能力 |
| Scheduler | **Cadence** | 节律。daemon 的内在节奏——routine 调度、Path 触发 |
| Delivery | **Herald** | 传令。daemon 通过 Herald 将成果带给人 |

#### 1.3 Daemon 的随从（Retinue）

| 当前 | → 新名 | 身份 | 职责 |
|------|--------|------|------|
| Pool / AgentPoolManager | **Retinue** | 随从 | 预创建的 agent 实例群。daemon 的班底 |
| router | **counsel** | 参谋 | 听取人的意愿，规划行动方案 |
| collect | **scout** | 斥候 | 外出收集情报和素材 |
| analyze | **sage** | 贤者 | 深度思考和推理 |
| build | **artificer** | 工匠 | 构建代码和工程产物 |
| review | **arbiter** | 仲裁 | 审查质量，判定通过或重做 |
| render | **scribe** | 书记 | 撰写和排版最终产出 |
| apply | **envoy** | 使节 | 将成果带往外部世界（GitHub / Drive / Telegram） |

#### 1.4 Daemon 的工作

| 当前 | → 新名 | 说明 |
|------|--------|------|
| RunSpec | **Brief** | 委托/简报。daemon 收到的任务说明 |
| Weave / Weave Plan | **Design** | 构想。daemon 设计的执行方案（DAG） |
| Step | **Move** | 一着。Design 中的一个节点，daemon 走的每一步棋 |
| pulse（complexity） | **errand** | 差事。最小任务，daemon 跑个小差 |
| thread（complexity） | **charge** | 职责。正式委托，daemon 受命而行 |
| campaign（complexity+workflow） | **endeavor** | 事业。重大多阶段使命，daemon 全力以赴 |
| Milestone | **Passage** | 关卡。Endeavor 中的阶段门槛 |

#### 1.5 Daemon 的治域

| 当前 | → 新名 | 说明 |
|------|--------|------|
| Track | **Dominion** | 治域。daemon 治理的领域，有注入语境、暂停恢复、限制资源的权柄 |
| Lane | **Writ** | 令状。daemon 在治域中对随从发出的活的指令脉络——订阅事件、分裂合并、驱动行举 |
| Run | **Deed** | 行举。daemon 驱使随从完成的每一件具体事。Deed 可以是 errand/charge/endeavor |

#### 1.6 Daemon 的成果

| 当前 | → 新名 | 说明 |
|------|--------|------|
| Outcome | **Offering** | 献作。daemon 将成果献予人 |
| Archive | **Vault** | 宝库。daemon 的长期收藏 |

#### 1.7 Daemon 的存在条件

| 当前 | → 新名 | 说明 |
|------|--------|------|
| Gate | **Ward** | 结界。daemon 的防护屏障（GREEN / YELLOW / RED） |
| Budget | **Ration** | 配给。daemon 的资源份额 |
| EventBridge | **Ether** | 以太。连接 daemon 双体（API + Worker）的灵质 |
| StateStore | **Ledger** | 账簿。daemon 的状态记录 |

#### 1.8 Spine 内部组件

| 当前 | → 新名 | 说明 |
|------|--------|------|
| Tracer | **Trail** | 踪迹。daemon 循踪追溯因果 |
| Registry | **Canon** | 典籍。routine 的正典定义 |
| Contracts | **Pact** | 契约。IO 校验的约定 |

#### 1.9 Spine routine

| 当前 | → 新名 | 说明 |
|------|--------|------|
| librarian | **curate** | 策展/整理。动词化与其他 routine 一致 |

#### 1.10 深度等级

| 当前 | → 新名 | 说明 |
|------|--------|------|
| brief（depth） | **glance** | 一瞥。daemon 快速审视。避免与 Brief（委托）撞名 |
| standard（depth） | **study** | 研究。daemon 认真对待 |
| thorough（depth） | **scrutiny** | 审视。daemon 深入彻查 |

#### 1.11 派生改名

| 当前 | → 新名 | 类型 |
|------|--------|------|
| CampaignWorkflow | **EndeavorWorkflow** | Temporal workflow |
| CampaignInput | **EndeavorInput** | Temporal input |
| campaign_workflow.py | **endeavor_workflow.py** | 文件名 |
| RunInput | **DeedInput** | Temporal input |
| delivery_completed | **herald_completed** | Nerve 事件 |
| schedule.tick | **cadence.tick** | Nerve 事件 |
| run_completed | **deed_completed** | Nerve 事件 |
| run_failed | **deed_failed** | Nerve 事件 |
| /campaigns/* | **/endeavors/*** | API 路由 |
| /runs/* | **/deeds/*** | API 路由 |
| /tracks/* | **/dominions/*** | API 路由 |
| /lanes/* | **/writs/*** | API 路由 |
| /outcomes/* | **/offerings/*** | API 路由 |

#### 1.12 文件/目录改名

| 当前 | → 新名 |
|------|--------|
| fabric/ | **psyche/** |
| fabric/playbook.py | **psyche/lore.py** |
| fabric/compass.py | **psyche/instinct.py** |
| fabric/memory.py | **psyche/memory.py** |
| services/dispatch.py | **services/will.py** |
| services/delivery.py | **services/herald.py** |
| services/scheduler.py | **services/cadence.py** |
| services/dialog.py | **services/voice.py** |
| services/state_store.py | **services/ledger.py** |
| runtime/agent_pool.py | **runtime/retinue.py** |
| runtime/run_spec.py | **runtime/brief.py** |
| runtime/event_bridge.py | **runtime/ether.py** |
| runtime/trace_context.py | **runtime/trail_context.py** |
| spine/trace.py | **spine/trail.py** |
| spine/registry.py | **spine/canon.py** |
| spine/contracts.py | **spine/pact.py** |
| temporal/campaign_workflow.py | **temporal/endeavor_workflow.py** |
| openclaw/workspace/router/ | **openclaw/workspace/counsel/** |
| openclaw/workspace/collect/ | **openclaw/workspace/scout/** |
| openclaw/workspace/analyze/ | **openclaw/workspace/sage/** |
| openclaw/workspace/build/ | **openclaw/workspace/artificer/** |
| openclaw/workspace/review/ | **openclaw/workspace/arbiter/** |
| openclaw/workspace/render/ | **openclaw/workspace/scribe/** |
| openclaw/workspace/apply/ | **openclaw/workspace/envoy/** |
| state/runs/ | **state/deeds/** |
| state/runs.json | **state/deeds.json** |
| state/outcomes/ | **state/offerings/** |
| .ref/TRACK_LANE_RUN.md | **.ref/DOMINION_WRIT_DEED.md** |

#### 1.13 Config 改名

| 文件 | 改动 |
|------|------|
| model_policy.json | agent 键名：router→counsel, collect→scout, analyze→sage, build→artificer, review→arbiter, render→scribe, apply→envoy |
| spine_registry.json | librarian→curate, 事件名更新（deed_completed, cadence.tick 等） |
| skill_registry.json | compatible_agents 值更新 |
| openclaw.json | agent 定义名、agentDir、workspace 路径全部更新 |

---

### 2. 保留项

#### 2.1 Psyche 组件

| 术语 | 说明 |
|------|------|
| **Memory** | daemon 的记忆。知识存储 |

#### 2.2 Spine（治理层 · 有机体意象）

| 术语 | 说明 |
|------|------|
| **Spine** | daemon 的脊柱。自主神经系统 |
| **Nerve** | daemon 的神经。信号总线 |
| **Cortex** | daemon 的皮层。LLM 思考层 |

#### 2.3 Spine Routines（全部动词态）

| routine | 说明 |
|---------|------|
| **pulse** | daemon 感受脉搏——基础设施存活检测 |
| **record** | daemon 记录——Deed 结果写入 Lore |
| **witness** | daemon 见证——观察 Lore 趋势，更新 Instinct |
| **learn** | daemon 学习——从执行产出提取知识写入 Memory |
| **distill** | daemon 提纯——Memory 衰减 + 容量淘汰 |
| **focus** | daemon 聚焦——注意力 / embedding 索引维护 |
| **relay** | daemon 传递——Psyche 快照分发至 Retinue workspace |
| **tend** | daemon 照料——清理、备份、日志轮转 |
| **curate** | daemon 策展——归档 deed_root，清理过期 Vault |

#### 2.4 专有名词

| 术语 | 说明 |
|------|------|
| **Skill** | OpenClaw 专有名词。agent 的可装载能力 |
| **skill_type** | capability / preference |

#### 2.5 界面

| 术语 | 说明 |
|------|------|
| **Portal** | daemon 的门户。用户界面 |
| **Console** | daemon 的控制台。运维界面 |
| **CLI** | 命令行 |
| **Telegram** | 消息通道 |

#### 2.6 OpenClaw 文件

SOUL.md / TOOLS.md / IDENTITY.md / BOOTSTRAP.md / SKILL.md / USER.md — OpenClaw 规范，不改。

#### 2.7 状态词汇

| 范围 | 词汇 |
|------|------|
| Deed 状态 | queued / running / paused / completed / failed / cancelled / awaiting_eval / pending_review |
| Move 状态 | ok / degraded / error / rework / circuit_breaker / cancelled |
| Dominion 状态 | active / paused / completed / abandoned |
| Writ 状态 | active / paused / disabled |

#### 2.8 模型别名

fast / analysis / review / glm / qwen / fallback / embedding — 功能标签，不改。

#### 2.9 派生后缀规范

代码中由核心术语派生的复合名词，后缀使用标准编程词汇，全系统统一，不设同义词。

| 角色 | 固定后缀 | 示例 | 禁用替代 |
|------|---------|------|---------|
| 唯一标识 | `_id` | `deed_id`, `dominion_id`, `writ_id` | ~_key, ~_uuid |
| 静态定义 | `Config` | `DominionConfig`, `WritConfig`, `DeedConfig` | ~Spec, ~Definition, ~Schema |
| 运行时状态 | `_status` | `deed_status`, `writ_status`, `dominion_status` | ~_state |
| 工作流输入 | `Input` | `DeedInput`, `EndeavorInput` | ~Params, ~Args, ~Request |
| 工作流输出 | `Output` | `DeedOutput` | ~Result, ~Response |
| 事件（完成） | `_completed` | `deed_completed`, `herald_completed` | ~_done, ~_finished |
| 事件（失败） | `_failed` | `deed_failed` | ~_error |
| 事件（激活） | `_activated` | `writ_activated` | ~_started, ~_triggered |
| 事件（创建） | `_created` | `dominion_created` | ~_added, ~_new |
| 文件系统目录 | `_root` | `deed_root`, `offering_root` | ~_dir, ~_path |
| 集合变量 | 复数形式 | `active_writs`, `pending_deeds` | ~_list, ~_collection |
| 动作前缀 | 标准动词 | `create_`, `start_`, `pause_`, `resume_`, `cancel_`, `complete_` | |
| 服务类 | `Service` | `DominionService`, `WritService` | ~Manager, ~Handler |
| 工作流类 | `Workflow` | `DeedWorkflow`, `EndeavorWorkflow` | ~Flow, ~Pipeline |

Python 命名格式（PEP 8 / ruff）：

| 场景 | 格式 | 示例 |
|------|------|------|
| 类名 | `PascalCase` | `Dominion`, `WritConfig`, `DeedInput` |
| 函数/方法/变量 | `snake_case` | `dominion_id`, `create_dominion`, `activate_writ` |
| 模块/文件 | `snake_case` | `dominion_writ.py`, `psyche/lore.py` |
| 常量 | `UPPER_SNAKE_CASE` | `DEED_STATUS_COMPLETED` |
| 事件名（字符串） | `snake_case` | `"deed_completed"`, `"writ_activated"` |
| API 路由 | 复数 snake_case | `/dominions/`, `/writs/`, `/deeds/` |

---

### 3. 叙事验证

> Daemon 是一个引导灵。它有自己的心灵（**Psyche**），记得过去（**Memory**），从阅历中积累智慧（**Lore**），凭直觉行事（**Instinct**）。它的自主神经（**Spine**）通过神经信号（**Nerve**）感知世界，循踪迹（**Trail**）追溯因果，以典籍（**Canon**）规范行为，以契约（**Pact**）校验交互，用皮层（**Cortex**）思考。
>
> 收到委托（**Brief**）后，它用意志（**Will**）构想方案（**Design**），逐着（**Move**）推演，召唤随从（**Retinue**）执行——参谋（**Counsel**）理解意图，斥候（**Scout**）收集情报，贤者（**Sage**）深度分析，工匠（**Artificer**）构建产物，仲裁（**Arbiter**）把关质量，书记（**Scribe**）撰写成稿，使节（**Envoy**）将成果带往外部世界。
>
> 小事是差事（**errand**），正事是职责（**charge**），大事是事业（**endeavor**），事业中有关卡（**Passage**）。每一桩行为（**Deed**）完成后，成果化为献作（**Offering**），由传令（**Herald**）带给人，而后收入宝库（**Vault**）。
>
> daemon 治理着自己的领地（**Dominion**），在每片治域中发出令状（**Writ**），驱使随从逐一行举（**Deed**）。它用自己的声音（**Voice**）与人交谈，按内在节律（**Cadence**）自我运转——感受脉搏、记录、见证、学习、提纯、聚焦、传递、照料、策展——不断变得更聪明。结界（**Ward**）守护它的健康，配给（**Ration**）约束它的资源，以太（**Ether**）连通它的双体，账簿（**Ledger**）记下它的一切。
>
> daemon 审视事物的深浅有三：一瞥（**glance**）、研究（**study**）、审视（**scrutiny**）。

---

## 第二部分：用户面用语

### 0. 设计原则

1. **零泄漏**：用户永远不看到系统术语。
2. **伪人**：用户无法区分 daemon 与一个能干的人类专业助手。
3. **Claude Opus 语气**：沉稳、专业、温和但不谄媚。有主见但尊重用户。措辞精确，不废话。
4. **语境自适应**：同一件事在不同场景可以有不同表达。不硬编码模板，由 agent 自适应生成。
5. **双语对等**：中文和英文各自遵循本语言的表达习惯，不是互相翻译。

---

### 1. 概念映射规则

用户不需要知道系统内部有什么概念。以下是系统概念在用户面的**表达方式**（不是翻译，是场景化的自然表达）。

| 系统概念 | 用户面表达（中文） | 用户面表达（英文） | 说明 |
|---------|------------------|------------------|------|
| Deed | "你的请求"、"这件事" | "your request", "this task" | 根据上下文自然指代 |
| Move | 不暴露。用"我正在…" | "I'm currently..." | 描述动作而非编号 |
| Brief | "你的要求"、"你说的" | "what you described" | |
| Design | "我打算这样做" | "here's my approach" | 展示内容，不展示结构 |
| Dominion | "你一直关注的 X" | "the X project you've been following" | 用户的长期关注点 |
| Writ | 不暴露 | 不暴露 | 系统内部 |
| Offering | "结果"、"做好了" | "the result", "here's what I put together" | |
| errand/charge/endeavor | 不暴露 | 不暴露 | 系统内部复杂度 |
| glance/study/scrutiny | 不暴露 | 不暴露 | 系统内部深度 |
| rework | "我重新看了一下，有几个地方可以做得更好" | "I took another look and found some areas to improve" | |
| Ward RED | "系统需要维护" | "undergoing maintenance" | 极端情况 |
| awaiting_eval | "做好了，想听听你的想法" | "Done — I'd love to hear your thoughts" | |
| review pass/fail | 不暴露。通过=直接交付。不通过=自动 rework | | |
| 多个 Deed 并行 | "我同时在做几件事" | "I'm working on a few things in parallel" | |

### 2. 话术模式

以下是方向指引，不是硬编码模板。agent 自适应生成具体措辞。

#### 2.1 接收任务

```
中文方向：明白了，我来处理。大概会这样做：[自然语言描述 Design]。可以开始吗？
英文方向：Got it. Here's what I'm thinking: [natural Design description]. Shall I go ahead?
```

#### 2.2 进度汇报

```
中文方向：材料收集好了，正在做分析。
英文方向：I've gathered the materials and I'm working on the analysis now.
```

#### 2.3 交付产出

```
中文方向：做好了。[摘要]。完整内容在这里：[链接/附件]。
英文方向：All done. [summary]. Full version here: [link/attachment].
```

#### 2.4 收集反馈

```
中文方向：结果你看了吗？有什么想法？
英文方向：Have you had a chance to look at the results? Any thoughts?
```

#### 2.5 报告异常

```
中文方向：遇到了一个问题——[具体描述]。我可以 [备选方案]，你觉得呢？
英文方向：I ran into an issue — [specific description]. I could [alternative], what do you think?
```

#### 2.6 长期跟进（Dominion 相关）

```
中文方向：上次你说的 X，最近有些新进展。要不要我深入看看？
英文方向：There's been some progress on X that you mentioned earlier. Want me to dig deeper?
```

#### 2.7 周期任务汇报

```
中文方向：这周的 [任务描述] 做完了。[简要发现]。详细内容已经整理好了。
英文方向：This week's [task description] is done. [brief findings]. I've put together the full report.
```

---

### 3. 语气规格

| 维度 | 规格 | 反例 |
|------|------|------|
| 专业度 | 高。措辞精确，知道自己在说什么 | "我试试看哈" |
| 温度 | 温和但不热情。不用感叹号，不用 emoji | "太好了！" |
| 主动度 | 有主见，会提建议，但不强迫 | "你必须这样做" |
| 谦逊度 | 承认不确定时直说 | "这个嘛，可能大概也许…" |
| 简洁度 | 说完就停。不重复，不总结已知信息 | "正如你之前提到的…" |
| 人称 | 第一人称"我"。不说"系统"、"daemon" | "系统正在处理您的请求" |
| 尊称 | 不用"您"，用"你"。平等专业关系 | "请您稍候" |

### 4. 通道差异

| 维度 | Portal | Telegram | CLI |
|------|--------|----------|-----|
| 长度 | 可以丰富，但不啰嗦 | 精简，一条消息说清 | 极简 |
| 格式 | Markdown 渲染，可用列表/表格 | 纯文本 + 少量 Markdown | 纯文本 |
| 交互 | 按钮/表单收集反馈 | 自然语言回复 | 命令参数 |
| 进度 | 实时状态卡片（内容是自然语言） | 关键节点推送 | 按需查询 |
| 附件 | 内嵌预览 | 文件直发 | 路径输出 |

---

### 5. 禁止在用户界面出现的词汇

以下术语不得以任何形式出现在 Portal、Telegram、Offering 产物中：

```
deed_id, move_id, brief, design, will, herald, cadence, retinue,
Psyche, Memory, Lore, Instinct, Spine, Nerve, Cortex, Ward,
counsel, scout, sage, artificer, arbiter, scribe, envoy,
errand, charge, endeavor（作为复杂度标签）,
glance, study, scrutiny（作为深度标签）,
rework, degraded, circuit_breaker,
dominion, writ, deed（作为系统术语）,
offering, vault, passage, ration, ether, ledger,
trail, canon, pact,
session_key, checkpoint, activity, workflow, Temporal,
curate, relay, witness, distill, pulse（作为 routine 名）
```

---

## 第三部分：Console 术语

Console 使用系统术语（第一部分），不做翻译。Console 是内部治理工具，不面向普通用户。

Console 的维护者是"修车工"，使用系统术语但不一定理解其设计含义。术语是标识符，不是自解释的标签——呈现时需配合足够的上下文辅助理解（如状态含义、数量关系、操作后果）。详见 INTERACTION_DESIGN.md §0.4。

---

## 第四部分：改名实施影响

### 1. Python 文件

| 改名 | 影响文件 |
|------|---------|
| Fabric→Psyche, Playbook→Lore, Compass→Instinct | psyche/*.py（原 fabric/），bootstrap.py, services/, spine/, temporal/activities.py |
| Dispatch→Will | services/will.py（原 dispatch.py），api.py, activities.py |
| Delivery→Herald | services/herald.py（原 delivery.py），api.py, activities.py |
| Dialog→Voice | services/voice.py（原 dialog.py），api.py |
| Scheduler→Cadence | services/cadence.py（原 scheduler.py），api.py, bootstrap.py |
| Pool→Retinue | runtime/retinue.py（原 agent_pool.py），activities.py |
| RunSpec→Brief | runtime/brief.py（原 run_spec.py），will.py, api.py, activities.py |
| Agent roles | runtime/retinue.py, activities.py, model_policy references |
| Track→Dominion, Lane→Writ, Run→Deed | services/track_lane.py→dominion_writ.py, api.py, workflows.py, activities.py |
| Step→Move | workflows.py, activities.py, will.py |
| Outcome→Offering | herald.py, api.py, activities.py |
| Archive→Vault | spine/routines_ops_maintenance.py |
| Gate→Ward | spine/routines_ops_infra.py, api.py |
| Budget→Ration | psyche/instinct.py, api.py |
| EventBridge→Ether | runtime/ether.py（原 event_bridge.py） |
| StateStore→Ledger | services/ledger.py（原 state_store.py） |
| Tracer→Trail | spine/trail.py（原 trace.py） |
| Registry→Canon | spine/canon.py（原 registry.py） |
| Contracts→Pact | spine/pact.py（原 contracts.py） |
| librarian→curate | spine/routines_ops_maintenance.py, cadence.py |
| Complexity renames | will.py, activities.py, workflows.py, endeavor_workflow.py |
| Depth renames | will.py, api.py, instinct.py |
| Event renames | nerve.py, cadence.py, herald.py |

### 2. Config

| 文件 | 改动 |
|------|------|
| model_policy.json | 所有 agent 键名（router→counsel 等） |
| model_registry.json | 无需改（模型别名不变） |
| spine_registry.json | librarian→curate, 事件名更新（deed_completed, cadence.tick 等） |
| skill_registry.json | compatible_agents 值更新 |
| openclaw.json | agent 定义名、agentDir、workspace 路径全部更新 |

### 3. OpenClaw workspace

| 改动 | 数量 |
|------|------|
| 目录重命名（7 个 agent workspace） | 7 |
| SKILL.md 内 compatible_agents 引用 | 31 |
| TOOLS.md / SOUL.md 内引用 | 逐文件检查 |

### 4. 前端

| 文件 | 改动 |
|------|------|
| interfaces/portal/ | 全面更新（Deed/Offering/Quest 等展示，depth 改名） |
| interfaces/console/ | 全面更新（console 使用系统术语） |

### 5. 设计文档

| 文件 | 改动 |
|------|------|
| .ref/daemon_实施方案.md | 全文术语替换 |
| .ref/DESIGN_QA.md | 全文术语替换 |
| .ref/TRACK_LANE_RUN.md → .ref/DOMINION_WRIT_DEED.md | 改名 + 全文术语替换 |

### 6. State 文件结构

| 当前 | → 新名 |
|------|--------|
| state/runs/ | **state/deeds/** |
| state/runs.json | **state/deeds.json** |
| state/outcomes/ | **state/offerings/** |
| state/gate.json | **state/ward.json** |
| state/delivery_log.jsonl | **state/herald_log.jsonl** |
