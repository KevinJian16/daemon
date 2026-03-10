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

### Q1.1 Memory 的容量策略

Memory 采用“热度衰减 + 相似合并 + 最后淘汰”的策略。

先合并相似低价值记忆，仍超限时再淘汰最低分项。

### Q1.2 Memory 的冲突处理

新的显式事实覆盖旧的矛盾事实，不保留冲突并存。

### Q1.3 Memory 的隔离策略

Memory 不做硬主题隔离，不做预定义 cluster。

查询时以 embedding 为主，并引入 `folio_id` 作为主题偏置：

- 同卷内容优先
- 若无合适命中，再看全局

### Q1.4 Lore 的职责

Lore 记录的是：

- 这次是如何做的
- 质量如何
- 花了多少
- 反馈如何

Lore 的主锚点是 `deed_id`，并同时记录 `slip_id`、`folio_id`、`writ_id`。

### Q1.5 Instinct 的职责

Instinct 只负责全局偏好、默认值和配额倾向。

它不承担主题级规划习惯，不承担单次执行经验。

### Q1.6 规划学习的归属

规划学习不挂在 `Folio` 上。

分工如下：

- `Folio`：提供主题级长期背景
- `Slip`：学习这张签札通常该如何规划
- `Writ`：学习这类事件通常如何生发和接续
- `Deed`：沉淀这一次执行的成败与反馈

### Q1.7 Writ 可学习，但不可无声改写

`Writ` 是可学习对象。

系统可以积累：

- 命中率
- 误触发率
- 合适的触发时机
- 合适的目标 `Slip`
- 合适的 suppress 条件

但 canonical `Writ` 不应被无声改写；正式变更必须版本化。

---

## 2. Spine（脊柱与事件）

### Q2.1 Routine 列表

当前正式 routine 为：

- `pulse`
- `record`
- `witness`
- `learn`
- `distill`
- `focus`
- `relay`
- `tend`
- `curate`

旧 `intake / judge / librarian` 不再是正式 routine 名。

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
- 相关 `Lore`

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

### Q7.3 反馈的对象

反馈首先绑定一次 `Deed`，并可回流影响：

- 对该 `Slip` 的规划习惯
- 对该 `Writ` 的效果判断
- 对相关 `Lore` 的质量权重

### Q7.4 反馈窗口

反馈窗口保留正式的延迟评价能力，允许在结果到达后一段时间内补评和改评。

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

### Q8.5 任务链

多阶段推进由：

- `Folio`
- 多张 `Slip`
- `Writ`

共同承担。

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

### Q10.2 审计文档地位

`MECHANISM_AUDIT.md` 不再承担机制定义职责，只承担 gap 审查职责。

### Q10.3 当前审查入口

后续 auditor 应根据以下五份文档重写 audit：

- `README.md`
- `TERMINOLOGY.md`
- `INTERACTION_DESIGN.md`
- `DESIGN_QA.md`
- `daemon_实施方案.md`

### Q10.4 当前禁止事项

以下理解已被正式否决：

1. `Deed` 仍兼任任务本体
2. Portal 与 Console 可以各自维护一套对象规则
3. 系统仍需要并列的多套正式任务类型
