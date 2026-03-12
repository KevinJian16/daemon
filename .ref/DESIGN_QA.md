# Daemon 设计决策录

> 日期：2026-03-10  
> 本文档记录当前已确认的正式设计决策。  
> 术语以 `TERMINOLOGY.md` 为准；交互以 `INTERACTION_DESIGN.md` 为准；实施以 `daemon_实施方案.md` 为准。  
> 若实施方案与本文档冲突，以本文档为准。

---

## 0. 当前确认范围

当前已确认的正式对象为：

- `Draft`
- `Slip`
- `Folio`
- `Writ`
- `Deed`

### Q0.1 前端表现语言

前端表现语言已经正式确认：

- **Portal** = Claude 静态 + Apple app 层级动态 + 文件系统式对象组织
- **Console** = Claude 静态 + Apple app 层级动态

补充约束：

- 所有会动的东西都应使用 Apple 的动态语言
- Portal 的 `Slip / Folio` 组织行为使用文件系统式对象操作感
- Console 不引入文件管理器味，不以拖拽整理对象为主语法

这不是风格建议，而是正式交互约束。

---

## 1. Psyche（心智层）

Psyche 由六个组件构成：Instinct（本能）、Voice（画像）、Preferences（偏好）、Rations（配给）、Ledger（账簿）、SourceCache（源缓存）。

> 旧 Memory（记忆）和 Lore（阅历）已废除。外部知识由 SourceCache 承担，经验学习改为 Ledger 机械统计。

### Q1.1 Instinct 的职责

Instinct 是系统不可被用户覆盖的原则。

它不承担主题级规划习惯，不承担单次执行经验。

### Q1.1.1 Instinct 的执行模型（InstinctEngine）

Instinct 的规则执行必须是**代码层确定性执行**（`InstinctEngine`），不依赖 LLM 遵守指令。

三层执行：

| 层级 | 执行方式 | 例子 |
|------|---------|------|
| 硬规则（pre/post check） | Python if/else | Ration 上限、token 预算、并发数、格式校验 |
| 软规则（prompt injection） | instinct.md ~200 tokens | 给 agent 解释规则的原因，让行为更合理 |
| 关键审查 | arbiter 专审 | 重要交付物的质量门控 |

### Q1.1.2 Instinct 是信息门控

所有信息流入系统（对话洗出物、Voice 写入、Brief 补充）都必须过 Instinct 代码校验。

用户可能无意中侵蚀系统质量（反复跳过反馈、矛盾偏好、注入外部内容）。系统不假设用户善意——这不是道德问题，是认知差问题。Instinct 必须比用户更强，为用户的长期利益服务。

### Q1.2 Voice（画像）的职责

Voice 是系统的身份与写作风格描述，以 markdown 文件存储于 `psyche/voice/`。

双层结构：

| 层 | 文件 | 注入对象 | token 上限 |
|----|------|---------|-----------|
| Identity（身份画像） | `identity.md` | 所有 agent | ≤150 |
| Style（写作风格） | `common.md` / `zh.md` / `en.md` | scribe / envoy | ≤250 |
| Overlay（任务覆盖） | `overlays/*.md` | 按 task_type 匹配 | ≤50 |

> 注意：此处 Voice（画像）是 Psyche 的组件，与执行层的 Voice（对话服务，`services/voice.py`）是不同概念。

### Q1.3 Preferences 与 Rations

由 `PsycheConfig`（TOML）统一管理：

- **Preferences**：用户可调整的系统偏好（语言、输出格式、深度默认值等）
- **Rations**：资源额度与配额配置（token 预算、并发上限等）

`PsycheConfig.snapshot()` 提供只读快照，供 API 和 Console 使用。

### Q1.4 Ledger（机械统计）

Ledger 是 Psyche 的统计层（`LedgerStats`，SQLite），只做机械统计，不做 LLM 语义学习。

四张表：

| 表 | 内容 | 学习来源 |
|----|------|---------|
| `dag_templates` | DAG 执行模式模板 | accepted Deed，embedding 相似度合并（cosine > 0.85） |
| `folio_templates` | Folio 结构模板 | 归档 Folio（accepted_ratio > 0.5） |
| `skill_stats` | 技能使用统计 | Deed 执行元数据 |
| `agent_stats` | Agent 表现统计 | Deed 执行元数据 |

学习原则：**只学 accepted，不学失败**。学模式不学实例。

### Q1.5 SourceCache

SourceCache 是外部知识的 TTL 缓存层，支持 embedding 检索。

查询时以 embedding 为主，`folio_id` 作为主题偏置（同卷优先，无命中看全局）。

### Q1.6 规划学习的归属

规划学习不挂在 `Folio` 上。

分工如下：

- `Folio`：提供主题级长期背景
- `Slip`：通过 `dag_templates` 学习类似任务该如何规划
- `Writ`：学习这类事件通常如何生发和接续
- `Deed`：执行元数据写入 `Ledger` 统计

### Q1.7 Writ 可学习，但不可无声改写

`Writ` 是可学习对象。

系统可以积累：

- 命中率
- 误触发率
- 合适的触发时机
- 合适的目标 `Slip`
- 合适的 suppress 条件

但 canonical `Writ` 不应被无声改写；正式变更必须版本化。

### Q1.8 选择性 Psyche 注入

Move 执行时，`_build_move_context` 按 agent 角色选择性注入 Psyche 内容：

| Agent 角色 | 注入内容 | 约 token |
|-----------|---------|---------|
| 所有 agent | instinct.md（软规则）+ identity.md | ~300 |
| scribe / envoy | + style（语言相关）+ overlay（任务覆盖） | ~550 |
| counsel | + planning_hints（Ledger 统计摘要） | ~400 |

---

## 2. Spine（脊柱与事件）

### Q2.1 Routine 列表

当前正式 routine 为 7 个：

- `pulse` — 基础健康巡检
- `record` — 行事结果写回 Ledger 统计
- `witness` — 观察趋势、提取信号
- `focus` — 调整系统关注重点
- `relay` — 快照与上下文转递
- `tend` — 清理、轮转与维护
- `curate` — 归档与藏库整理

> 已废除：`learn`（学习）和 `distill`（提炼）。学习机制改为 Ledger 机械统计，由 `record` 和 `witness` 承担。旧 `intake / judge / librarian` 也不再是正式 routine 名。

### Q2.2 Nerve 的可靠性

Nerve 采用 at-least-once 语义。

关键事件必须写入持久化事件日志，重启后可重放未消费事件。

### Q2.3 看门狗的定位

看门狗必须独立于主系统运行。

它只负责发现异常和发出通知，不承担修复职责。

### Q2.4 系统生命周期

系统级状态保留：

- `running`
- `paused`
- `restarting`
- `resetting`
- `shutdown`

这些状态是全局状态，不与单个 `Slip` / `Deed` 状态混淆。

---

## 3. 事项机制对象与生命周期

### Q3.1 Draft 是真实对象

`Draft` 不是临时聊天缓存，而是正式对象。

任何一件事，在成札前都先以 `Draft` 形式存在。

### Q3.2 Draft 的来源

`Draft` 可以来自：

- 用户对话
- 规则触发
- 外部事件
- 系统内部推进

自动任务也必须先经过 `Draft`，再决定是否成札。

### Q3.3 Slip 的地位

`Slip` 是最小可持久化任务对象。

所有正式成立的任务都先落成 `Slip`。

### Q3.4 Deed 的地位

`Deed` 是某张 `Slip` 的一次具体执行实例。

它不是任务本体。

### Q3.5 Slip 与 Deed 的关系

一张 `Slip` 可以没有 `Deed`，也可以对应多个 `Deed`。

一个 `Deed` 必定源于一张 `Slip`。

### Q3.6 Deed 完成后，Slip 不结束

`Deed` 完成后，本次执行结束；`Slip` 仍可继续存在。

它可以：

- 再次执行
- 被归入某卷
- 被搁置
- 被归档

### Q3.7 定时任务的正式组织

周期性任务采用：

- 一张 standing `Slip`
- 一条 `Writ`
- 多次 `Deed`

而不是让一个 `Deed` 永远活着。

### Q3.8 单 Slip 承载上限

单 `Slip` 的承载上限采用当前正式单札基线。

具体阈值由暖机校准，但机制结论已定：

- 能装入一张 `Slip` 就保持为单札
- 超出上限就提升为 `Folio`

### Q3.9 对象类型规则

前台正式对象只有：

- `Draft`
- `Slip`
- `Folio`
- `Writ`
- `Deed`

系统不再引入新的并列任务类型作为正式前台主物种。

---

## 4. Voice（对话与计划）

### Q4.1 Voice 的职责

Voice 负责：

- 理解意图
- 收敛为 `Draft`
- 形成 `Brief`
- 生成 `Design`

Voice 不直接等于执行。

### Q4.2 未完成对话的存续

未完成的任务收敛过程保留为 `Draft`，不丢失。

### Q4.3 所有 Slip 都有 plan card

plan card 是统一原件。

轻任务和重任务只在信息密度上不同，不在对象类型上不同。

### Q4.4 不满意 plan 的处理

对 plan 不满意时，优先通过对话修改，而不是暴露结构化 DAG 编辑。

### Q4.5 不收敛任务的处理

系统不直接拒绝任务。

处理路径固定为：

1. 继续收敛 `Draft`
2. 尝试成 `Slip`
3. 若超出单札上限，则提升为 `Folio`

### Q4.6 规划学习的输入

计划生成可以读取：

- 相似 `Slip`
- 相似 `Writ`
- `Ledger` 中的 `dag_templates`（相似成功 DAG 模板）

但不以旧复杂度分类做主导。

---

## 5. Will（决策与执行前判断）

### Q5.1 Will 的职责

Will 负责：

- `Brief` 正规化
- 单 `Slip` 默认基线填充
- 模型路由
- `Ration` 预检
- `Ward` 检查

### Q5.2 Will 不负责的事

Will 不负责：

- 重新理解用户意图
- 重写 `Draft`
- 重新生成 `Design`

这些属于 Voice。

### Q5.3 默认执行基线

单 `Slip` 的默认执行参数采用当前正式单札基线。

### Q5.4 Ward 的定位

`Ward` 只关心系统健康与可用性，不承担资源配额和对象组织职责。

### Q5.5 Ration 的定位

`Ration` 负责资源份额与额度，不负责系统健康判断。

---

## 6. Deed 执行

### Q6.1 Retinue 是正式执行池

系统使用预创建 `Retinue`，不在运行时动态造 agent。

### Q6.2 单次执行对象

真正提交到 Temporal / 执行层的对象是 `Deed`，不是 `Slip` 本体。

### Q6.3 review / rework 的职责

质量判断由 `Arbiter` 负责，物流由 `Herald` 负责。

`Herald` 不做质量判断。

### Q6.4 rework 的边界

rework 作用于本次 `Deed`，不是重写 `Slip` 的存在性。

### Q6.5 多次执行

“再执行一次”意味着：

- 基于同一张 `Slip`
- 生成新的 `Deed`

不是克隆新的 `Slip`。

---

## 7. 交付、反馈与学习

### Q7.1 Offering 的定位

`Offering` 是交给主人看的正式交付物。

它不携带系统痕迹。

### Q7.2 Vault 的定位

`Vault` 是内部留存、审计与归档空间，不等于给主人看的交付。

### Q7.3 反馈 = 对话 + 按钮

不存在独立的评价表单。用户在 Slip 对话中的发言（"太正式了""算了就这样吧"）即反馈内容。用户按下的按钮（执行 / 收束）即反馈动作。

反馈绑定一次 `Deed`，通过洗信息机制回流影响 Ledger 统计和 Voice 候选。

### Q7.4 迟到的反馈

用户回到 Slip 页面发起新 Deed = 对上次结果的隐式否定信号。不设专门的回溯评价机制。

### Q7.5 评价链机制

评价不是 settling 阶段的对话，而是以**运行周期**为单位的完整对话链。

**评价段**：一段评价 = 一次运行开始到下一次运行开始之间的所有对话内容（包含 running 和 settling 两个阶段的对话）。

**评价链**：
- 链头 = Slip 的「执行」按钮（创建 Deed，开始第一个运行周期）
- 链尾 = 「收束」按钮（结束最后一个运行周期）
- 链头和链尾完全可能重合（只有一次运行的 Deed）

**洗信息触发**：在每个运行周期边界（进入下一个运行周期的那一刻），对当前评价段做机械压缩。洗信息只做**机械提取**，不用 LLM：

- 压缩对话段 → 喂给下次运行的 Brief 补充（同时保留一份压缩结果）
- 客观数字 → Ledger 统计（rework 次数、消息数、时长）
- 关键词匹配提取 → Voice 候选（写入前必须用户确认）

**收束时汇总**：串联所有运行周期的压缩结果，作为该 Deed 的完整评价，送给系统（Ledger + Voice 候选 + dag_templates）。

所有洗出物流入系统前必须过 Instinct 代码门控。

### Q7.6 操作-自然语言对应

所有用户所做的非对话框操作（按钮、拖拽、姿态变更等），都在对话流中生成对应的自然语言记录。对话流是完整的行为日志。

因此 **Slash command 已取消**——所有 slash command 的功能已由按钮或直接操作承担，对话框只承载自然语言对话。

---

## 8. Folio 与 Writ

### Q8.1 Folio 的定义

`Folio` 是正式容器对象。

它可以：

- 自动生成
- 手动创建
- 重命名
- 合并
- 解散
- 收纳或放出 `Slip`

### Q8.2 Writ 的定义

`Writ` 是写在 `Folio` 中的规则。

它统一处理所有事件触发，不再分出本体上不同种类的 `Writ`。

### Q8.3 所有触发本质上都是事件

以下在机制上统一视为事件：

- 时间到达
- 某次 `Deed` 完成
- 外部对象到达
- 用户动作
- 反馈提交

差别只是事件源不同，不是规则本体不同。

### Q8.4 Writ 的工作公式

`Writ = Event -> action(on Draft / Slip / Deed / Folio)`

### Q8.5 触发类型排他性

对于给定的一张 `Slip`，触发类型是排他的，只能是以下之一：

- **手动触发**：用户按「执行」按钮
- **定时触发**：时间到达自动触发
- **前序事件触发**：Writ chain 中前序 `Deed` closed 后触发

三种触发类型互斥——一张 `Slip` 有且只有一种触发类型。

### Q8.6 Writ 是强约束

Writ 的排序是**强制执行**的，不是建议性的。

- 如果 Writ 规定"Slip B 在 Slip A closed 后执行"，那么 Slip B 的执行按钮在条件未满足时**禁用或隐藏**
- 前序条件未满足时，不允许用户绕过 Writ 顺序手动执行
- Writ chain 形成的 DAG 关系是硬约束

### Q8.7 任务链

多阶段推进由：

- `Folio`
- 多张 `Slip`
- `Writ`

共同承担。

### Q8.8 Slip 链 DAG 导航

Folio 内 Slip 通过 Writ 连接形成 DAG。Slip 页面支持链内前后导航：

- **线性链**：单个"上一张"/"下一张"标签
- **分支点**：多个"下一张"标签（每个标注目标 Slip 名称）
- **合并点**：多个"上一张"标签（每个标注来源 Slip 名称）

导航标签动态反映 Writ DAG 结构。

---

## 9. 交互与界面

### Q9.1 Portal 与 Console 共用对象机制

Portal 与 Console 必须共用：

- 同一批对象
- 同一批状态意义
- 同一批动作含义

不能形成两套对象现实。

### Q9.2 统一手势语法

全系统保持：

- 点开 = 进入下一层
- 下拉 = 刷新当前层现实
- 返回 = 回上一层
- 长按 / 拖起 = 进入操作态
- 拖放 = 改变关系或姿态

### Q9.3 Apple 动态语言是正式要求

所有会动的东西都按 Apple 动态语言设计。

这里指的是：

- 层级进入 / 返回
- 展开 / 收束
- 下拉刷新
- sheet / detail / side detail
- 对象被抓起、拖动、吸附、归位

不允许退化成普通 web 动效。

### Q9.4 Portal 的正式对象

Portal 中高频正式对象为：

- `Draft`
- `Slip`
- `Folio`

### Q9.5 Portal 的动态分工

Portal 同时承担两种动态语法：

1. Apple 原生 app 式层级动态
2. 文件系统式对象组织动态

前者用于页面层级、打开、返回、展开、收束。  
后者用于：

- `Slip -> Slip` 开卷
- `Slip -> Folio` 入卷
- `Slip` 在卷内重排
- 对象姿态变更

### Q9.6 Console 的正式对象视图

Console 至少需要清楚观察：

- `Folio`
- `Slip`
- `Deed`
- `Writ`

### Q9.7 Console 的动态分工

Console 使用：

- Claude 式静态秩序
- Apple 原生 app 式层级动态

但不使用文件系统式对象组织动态，不以拖拽整理对象为主要治理手段。

### Q9.8 Console 的编辑原则

Console 默认只做结构化编辑。

唯一明确例外是技能正文编辑器。

### Q9.9 术语显示

Portal 与 Console 都使用正式中文术语显示。

英文 canonical name 保留给代码、字段、词典和调试辅助。

---

## 10. 治理与边界

### Q10.1 词典地位

`config/lexicon.json` 是机器可读词典来源；`TERMINOLOGY.md` 是解释和规范来源。

两者必须一致。

### Q10.2 审计文档

`MECHANISM_AUDIT.md` 已删除。后续审计直接基于六份权威文档进行，不再维护独立审计文档。

### Q10.3 当前审查入口

auditor 应根据以下六份文档审查实现：

- `README.md`
- `TERMINOLOGY.md`
- `INTERACTION_DESIGN.md`
- `DESIGN_QA.md`
- `EXECUTION_MODEL.md`
- `daemon_实施方案.md`

### Q10.4 当前禁止事项

见 §13.1。

---

## 11. 执行模型（详见 EXECUTION_MODEL.md）

### Q11.1 Move 颗粒度

1 Move = 1 Agent + 1 交付物。不合并、不拆分。

### Q11.2 Session 模型

1 role = 1 OC instance。并行通过多 session，不通过多 instance。

Session 生命周期 = Deed 级别。串行共享、并行独立、Rework append。

### Q11.3 状态模型

两层模型：主状态（用户可见，2-3 个）+ 子状态（metadata）。

详见 `EXECUTION_MODEL.md` §5。

### Q11.4 下游触发

Writ chain 触发基于 `deed_closed`，不是 `deed_completed`。

### Q11.5 dag_budget

dag_budget 是 Ward 层面的成本护栏，不是 Folio 晋升的结构性触发条件。

---

## 12. Slip-Deed 解耦

### Q12.1 Slip 和 Deed 是两层独立实体

Slip 的状态、按钮、对话框和 Deed 的状态、按钮、对话框完全独立。两者物理分离，不共享 UI 元素。

### Q12.2 Slip 的按钮

Slip 只有一个动作按钮：「执行」。作用是创建一次新 Deed。

Deed 也可由其他事件产生（定时、Writ 联动），不一定由用户按钮触发。

### Q12.3 Deed 的按钮

Deed 只有两组按钮：

- 开始/停止（toggle）
- 收束

Deed 内多次开始/停止是同一个 Deed，不是新 Deed。

### Q12.4 Slip 对话框 = 调整 DAG

Slip 的对话框只做一件事：调整 Slip 的 DAG。不洗给系统学习。

DAG 修改的结果已经体现在 DAG 本身，不需要洗自然语言对话。

### Q12.5 Deed 对话框 = 调整/评价执行

Deed 的对话框承载执行期间的调整和评价。按钮触发洗信息（见 Q7.5）。

### Q12.6 DAG 快照

Deed 创建时冻结当前 DAG 版本。Slip 端的 DAG 修改不影响正在运行的 Deed。

首次执行：counsel 从 Slip 对话生成 DAG。后续修改：用户通过 Slip 对话增量调整。新 DAG 只在下一个 Deed 执行时生效。

### Q12.7 Deed 收束后冻结

Deed 收束后只保留产物标签和对话历史，只读，无操作。

过去的 Deed 页面保留但有保质期，过期从页面淡去。

### Q12.8 按钮-对话分离原则

按钮 = 状态边界（结构控制），对话 = 边界间的语义内容。

任何用户行为都有唯一归属，不重叠。按钮按下之前，对话段的性质未定。按下哪个按钮，决定洗出物的路由。

Slash command 已取消。所有结构控制由按钮或直接操作承担。所有非对话操作在对话流中生成自然语言记录（见 Q7.6）。

---

## 13. 当前禁止事项（更新）

### Q13.1 以下理解已被正式否决

1. `Deed` 仍兼任任务本体
2. Portal 与 Console 可以各自维护一套对象规则
3. 系统仍需要并列的多套正式任务类型
4. 同 agent 的并行 Move 合并为复合指令
5. Folio 晋升由 step count 超过 dag_budget 触发
6. `deed_completed` 事件用于下游 Writ 触发
7. Instinct 规则执行依赖 LLM 遵守 prompt
8. 存在独立的评价表单/UI
9. 调整和评价是两种不同的对话类型
10. 系统假设用户行为总是善意的
11. 评价只发生在 settling 阶段（评价段 = 运行周期，跨 running + settling）
12. Slash command 是对话框的正式入口（已取消，所有操作由按钮/直接操作承担）
13. 同一张 Slip 可以同时具有多种触发类型（手动/定时/前序事件互斥）
14. Writ 排序是建议性的（Writ 是强约束，前序未满足时按钮禁用）
