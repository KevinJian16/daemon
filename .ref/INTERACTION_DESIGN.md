# Daemon 交互设计

> 日期：2026-03-08
> 状态：**已确认**
> 依赖：TERMINOLOGY.md（术语）、DESIGN_QA.md（已确认决策）、daemon_实施方案.md（机制）
> 本文档使用新术语体系。旧名→新名映射见 TERMINOLOGY.md。

---

## 0. 设计准则

**静态学 Claude，动态学 Apple。**

- **静态设计与审美**：对齐 Claude 网页端。温暖克制的配色、干净的间距、圆角卡片、微阴影。无冗余装饰。
- **动态过程与转场**：对齐 Apple 动效哲学。所有状态转换有流畅的过渡动画（spring/fade/morph），无瞬切。动效服务于信息传达，不为炫技。

---

## 1. Portal 核心范式：Deed = Chat Session

**每个 Deed 就是一个 chat session。** 对话和任务是同一个界面，不分离。

用户点进侧边栏的一个 Deed = 打开一个对话。对话从任务提交开始，贯穿执行、完成、反馈的全过程。daemon 的进度更新、完成通知、反馈请求都是对话中的消息。用户随时可以在对话中打字——调整方向、追问进度、给反馈。

这比 Claude 的 chat 多一层：Claude 只有对话，daemon 的 chat = **对话 + 任务状态 + 产出展示**，三合一。

```
[新建对话] → Voice 对话 → Design 展示 → 确认执行
  → daemon 进度消息 → 完成消息 + Offering → 反馈选择 → （继续对话）
```

### 1.1 提交（Voice 对话）

| 项目 | 规格 |
|------|------|
| 入口 | Portal 唯一提交入口 |
| 驱动 | Counsel agent（MiniMax M2.5），system prompt 模拟 Claude Opus 语气 |
| 完成标志 | Design 通过收敛性验证 + 用户确认执行 |
| 草稿 | 未完成的 Voice session 内存保留，重启清除 |

**对话行为规范：**

- daemon 是耐心的一方，适应意图漂移，不被用户急躁带偏
- 追问不超过必要程度：能从上下文推断的不问
- 每轮回复附带当前对 Brief 的理解摘要（让用户知道 daemon 听懂了什么）
- 不收敛时引导补充 > 自动缩窄 > 建议分步推进。永远不拒绝、不单方面终止

### 1.2 Design 展示与计划组件

用户确认前展示 daemon 的执行方案。

**展示原则：**
- 用自然语言描述，不暴露 DAG 结构、Move 编号、agent 类型
- 用户可以修改、补充、否决 → 回到 Voice 对话调整

**计划组件（Plan Component）：**

嵌入 chat 消息中的**富 UI 卡片**（圆角、微阴影），不是 markdown 文本。按 Deed 复杂度分三种形态：

**Errand（简单）：** 无计划组件。daemon 用一句话描述即可（"好的，我来看看"）。

**Charge（中等）：** 纵向时间线卡片。
- 左侧一条细连接线串联圆点节点
- 已完成节点 = 实心绿点（checkmark stroke animation 画入），步骤文字变浅
- 进行中节点 = accent 色圆点 + 微弱脉冲动画，步骤文字加粗
- 待开始节点 = 空心灰点
- 顶部一条极细进度条（accent → 灰色渐变），实时更新

**Endeavor（复杂）：** 分段式阶段卡片。
- 顶部 = 分段进度条，每段代表一个 Passage。已完成段填充 accent 色，当前段有进度动画
- 当前 Passage 展开 = 内部包含 Charge 式纵向时间线（步骤详情）
- 已完成 Passage 折叠成一行 + checkmark，点击可展开查看回顾
- 未来 Passage 仅显示标题 + 灰色待开始

**计划组件更新方式：** 组件在 chat 中**原地刷新**（状态变化时节点颜色 morphing 过渡），不重发消息。daemon 的文字进度消息（"正在收集资料…"）是独立的 chat 消息，与计划组件共存。

### 1.3 执行中进度

用户确认执行后，daemon 的进度更新以 **chat 消息** 的形式出现在对话中：

| 情况 | Portal（chat 消息） | Telegram |
|------|---------------------|----------|
| 正常推进 | daemon 发消息："正在收集资料…" | 不推送 |
| 关键节点 | daemon 发消息更新进展 | 不推送（除非 Endeavor Passage 完成） |
| Endeavor Passage 完成 | daemon 发消息：阶段摘要 + 下一阶段计划 + 轻量反馈（👍/👎） | 推送摘要 |
| rework | daemon 发消息："我重新看了一下…" | 不推送 |
| rework 预算耗尽 | daemon 发消息：诊断 + 选项 | 推送警告 |
| 异常/失败 | daemon 发消息：问题 + 备选方案 | 推送警告 |
| Ward 变化 | daemon 发消息：维护提示 | 推送系统状态 |

daemon 的进度消息语气与 Voice 对话阶段一致，用自然语言：
- "正在分析你提供的材料。"
- "第一阶段做完了。[摘要]。接下来打算 [下一阶段概述]。"
- "遇到了一个问题——[描述]。我可以 [方案A] 或 [方案B]，你觉得呢？"

**用户随时可以在 chat 中打字**：追问进度、调整方向、补充信息。daemon 会回应并在必要时调整执行计划。

**Endeavor Passage 轻量反馈：**

Passage 完成消息末尾附加 👍 / 👎 按钮（inline，不占额外空间）：
- 👍 或不点 = 继续当前方向
- 👎 = daemon 主动追问具体问题，必要时调整后续 Passage 计划

此信号记入 Lore 供 Arbiter 参考，但不计为 user_feedback。

### 1.4 完成通知（Q6.3）

**Portal（chat 消息）：**
- daemon 在对话中发送完成消息：摘要（1-3 句话）+ Offering 预览
- Offering 预览嵌入在消息中：文本类显示开头摘要，PDF 类显示缩略图，代码类显示 diff 摘要
- bilingual 产出两份并列展示
- 消息附带"查看完整结果"链接（展开 Offering 详情 / 下载文件）

**Telegram：**
- 推送完成通知。格式：

```
做好了。

[1-2句摘要]

完整结果：[Portal 链接]
```

- 简短、信息密集、一条消息说清
- 不附带文件（文件在 Portal / Google Drive 获取）

**Offering 文件获取：**
- Portal API 端点：`GET /offerings/{deed_id}/files/` 列出文件，`GET /offerings/{deed_id}/files/{filename}` 下载文件
- 底层读取 Google Drive 本地路径（`~/My Drive/daemon/outcomes/...`）
- Telegram 通知中的 Portal 链接格式：`http://{host}:{port}/offerings/{deed_id}`
- 通过 Tailscale 从任何设备访问 Portal 的 hostname:port 即可查看和下载
- 文件不通过 Telegram 发送（Telegram 文件体验差，且 Offering 可能含多个文件）

**通知时机：**
- Herald 完成交付后立即推送
- Portal 推送 = WebSocket 实时事件
- Telegram 推送 = Herald activity 内同步调用 Telegram API

### 1.5 执行控制

**按钮控制**（chat 顶栏，根据 Deed 状态动态显示）：

| 按钮 | 前提条件 | 行为 |
|------|---------|------|
| **暂停** | running | 当前 Move 完毕后挂起 |
| **继续** | paused | 从暂停点恢复执行 |
| **取消** | running / paused | 终止执行，已完成产出保留 |
| **重新执行** | failed | 基于原 Design 重新执行（新 Deed ID） |

**对话控制**（直接在 chat 中打字）：

用户随时可以在执行中的 Deed chat 里打字，不需要点任何按钮：
- "方向对了，但重点放在 X 上" → daemon 理解意图，调整剩余步骤
- "先暂停" → 等同于点暂停按钮
- "这个不要了" → daemon 确认后取消

调整方向不是独立操作——就是在 chat 里继续对话。daemon 收到用户消息后自动暂停当前执行、理解调整意图、重新规划、展示新计划、用户确认后继续。体验和最初提交任务时的对话一致。

**异常处理：**

*局部异常*（不影响整体）：daemon 自行绕过，在 chat 中告知（"有一个来源暂时没取到，用了其他来源补充"）。不中断执行。

*致命异常*（无法继续）：
- rework 预算耗尽 → Deed 状态转 failed
- daemon 在 chat 中发消息：问题诊断 + "要不要重新来？还是你想调整一下再试？"
- 用户可以直接在 chat 中回应（重新执行 / 调整后重新提交 / 不处理）
- Telegram 推送失败通知 + Portal 链接

### 1.6 反馈收集（Q7.2a）

**触发：** Deed 完成 → 状态转 `awaiting_eval` → daemon 在 chat 中发送反馈请求。

**重要：awaiting_eval 只在整个 Deed 完成后触发。** Endeavor 的 Passage 完成时只发进度通知，不触发 awaiting_eval，不阻塞后续 Passage 执行。

**交互流程（全部在 chat 内）：**

1. daemon 发完成消息 + Offering 预览
2. daemon 紧接着发一条带 **inline 选择组件** 的消息（类似 Claude Code / Codex plan mode 的选择 UI）：

```
做好了，想听听你的想法。

  ○ 符合预期，质量满意
  ○ 基本达标，尚可接受
  ○ 未达预期，存在明显问题
  ○ 方向偏离，需要重新审视
```

3. 用户点选。如果选了"未达预期"或"方向偏离"，展开问题多选：

```
  □ 关键信息缺失
  □ 分析深度不足
  □ 存在事实性错误
  □ 格式或排版不当
  □ 偏离了原始需求方向
```

4. 选择完成后，daemon 跟进："还有什么想说的吗？"
5. 用户可以在 chat 中写一段文字评语，也可以直接离开
6. 离开 = 反馈已提交（选择部分），文字评语为空

**数据映射：**

| 用户行为 | → 系统值 |
|---------|---------|
| 符合预期，质量满意 | `satisfactory` |
| 基本达标，尚可接受 | `acceptable` |
| 未达预期，存在明显问题 | `unsatisfactory` |
| 方向偏离，需要重新审视 | `wrong` |
| 关键信息缺失 | `missing_info` |
| 分析深度不足 | `depth_insufficient` |
| 存在事实性错误 | `factual_error` |
| 格式或排版不当 | `format_issue` |
| 偏离了原始需求方向 | `wrong_direction` |
| 文字评语 | `comment` + 自由文本 |
| 不做选择就离开 | `user_feedback=null`，`quality_bonus=0`（中性） |

**Telegram 不提供反馈入口。** 反馈统一在 Portal chat 中完成。

### 1.7 修改反馈（Q7.2e）

**入口：** 用户回到已完成 Deed 的 chat，在 awaiting_eval 期间可以继续对话修改反馈。

**规则：**
- awaiting_eval 期间：用户可以重新进入这个 chat，重新选择或补充文字。新反馈覆盖旧反馈
- awaiting_eval 过期（48 小时后自动转 completed + feedback_expired=true）：chat 只读，不可再修改反馈
- 过期前 12 小时 Telegram 提醒一次

### 1.8 转场动效

遵循"动态学 Apple"准则。所有状态转换有流畅的过渡动画，无瞬切。

**T1 · 空白 → 第一条消息**
- 起始：居中占位文字（"需要做什么？"）+ 底部输入框
- 用户发送 → 占位文字 dissolve out，消息气泡从输入框位置上浮到对话区
- daemon 回复从底部淡入（fade in + slight slide up）

**T2 · Voice 对话 → Design 计划组件**
- daemon 收敛完意图，发出 Design 方案
- 计划组件从消息底部展开（spring animation，有回弹感），不是瞬间出现
- 确认按钮淡入

**T3 · 确认 → 执行开始（启动动效）**
- 用户点确认 → 计划组件节点从全灰依次点亮第一个（类似 Apple Watch 充电环亮起）
- 侧边栏新增 Deed 条目（iOS list insertion：从右侧滑入 + 淡入）
- 侧边栏条目获得 running 呼吸灯
- 输入框 placeholder 交叉淡出淡入："描述你的目标…" → "随时说点什么…"

**T4 · 步骤推进**
- 计划组件节点状态变化：颜色 morphing 过渡（不跳变）
- 完成节点 checkmark = stroke animation 画入（类似 Apple Pay 成功的勾）
- Endeavor Passage 切换：当前 Passage 折叠收缩（scale down），下一个展开（spring）

**T5 · 完成 → Offering + 反馈**
- 计划组件最后节点亮绿 → 整个组件微缩折叠（scale down + fade to compact 状态）
- Offering 预览卡片从下方升起（slide up + fade in）
- 反馈选择组件紧随滑入
- 侧边栏呼吸灯停止 → 静态完成标记（morphing 过渡）

---

## 2. 通道行为规范

### 2.1 Portal

**使用者：** daemon 的主人（owner）。通过自然语言表达意图和目标，不接触系统内部概念。

**角色：** 唯一任务提交入口 + 全生命周期交互界面。100% 复刻 Claude 网页端对话行为。

**侧边栏（自动聚类）：**

daemon 自动将相关 Deed 归组，用自然语言标签呈现（不暴露 Dominion 术语）。无 Dominion 的独立 Deed 平铺在顶层。

```
+ 新建对话

进行中
  "帮我看看竞品动态"

历史
  ▸ 市场分析 (3)          ← 自动归组，daemon 命名
  ▸ 技术调研 (5)
  "帮我润色那篇文章"      ← 独立 Deed
  "写个项目计划"
```

- 搜索框：过滤 Deed 标题
- Deed 标题 = daemon 根据对话内容自动生成
- 进行中的 Deed 带呼吸灯状态指示器

**Chat 页面结构：**

| 区域 | 内容 |
|------|------|
| 顶栏（固定） | Deed 标题 + 状态徽标（running/paused/completed/failed/awaiting_eval）+ 控制按钮（按状态动态显示）。Endeavor 额外显示 Passage 进度（如 "2/5"） |
| 对话流（滚动） | 完整对话历史：用户消息、daemon 回复、Design 计划组件、进度消息、Offering 预览、反馈选择组件——全部是连续的消息流 |
| 输入区（固定底部） | 文本框 + 附件按钮 + 发送按钮。awaiting_eval 过期后变为只读 |

**不存在的页面：** 没有独立的"任务详情页"、"结果页"、"反馈页"。一切都在 chat 中。

**实时更新：** WebSocket 推送，daemon 的进度消息实时出现在 chat 中，计划组件原地刷新。

### 2.2 Telegram

**角色：** 通知推送 + 最小命令交互。不提供反馈入口。

**白名单命令：**

| 命令 | 功能 |
|------|------|
| `/status` | 当前进行中的 Deed 列表 |
| `/cancel` | 取消指定 Deed（弹出编号选择） |

**交互模式：**
- 命令 + 编号列表 + 数字选择
- 非命令消息一律忽略
- adapter 内存状态机，超时 60 秒清除

**推送事件：**

| 事件 | 推送 | 内容 |
|------|------|------|
| Deed 完成 | 是 | 摘要 + Portal 链接 |
| Endeavor Passage 完成 | 是 | 阶段摘要 + 下一阶段概述 |
| rework 预算耗尽 | 是 | 问题描述 |
| Deed 失败 | 是 | 问题描述 + 建议 |
| Ward YELLOW | 是 | 系统状态警告 |
| Ward RED | 是 | 系统需要维护 |
| awaiting_eval 即将过期 | 是 | 提醒用户给反馈 |
| 正常进度 | 否 | — |
| rework | 否 | — |

**不推送的原则：** 除了上述明确列出的事件，其他一律不推送。避免打扰。

### 2.3 Console

**使用者：** 系统维护者（maintainer），与 Portal 的主人不是同一个人。对系统内部不一定有很好的理解。维护者的职责是保障系统正常运转，不是替主人做决策。

**角色：** 系统治理观测，不面向普通用户。

- 使用系统术语（Deed, Writ, Dominion, Move 等）
- **隐私边界**：主人的私人内容对维护者不可见。维护者只能看到运维所需的系统数据，不能看到主人的目标、任务内容、偏好、知识、经验
- **可观测（运维数据）**：系统健康（Ward/uptime/组件连通性）、Routine 状态、Deed 运行状态（数量/状态分布，不含任务内容）、Retinue 占用率、Provider 调用统计、系统日志、资源使用
- **不可观测（主人隐私）**：Psyche 内容（Memory/Lore/Instinct）、Dominion objective、Deed Brief/内容、Writ brief_template、Move 产出内容、Offering 内容
- **可操作（运维控制）**：Routine 开关/触发、系统生命周期（pause/restart/reset/shutdown）、Ward 手动覆盖、Provider 模型分配、Provider 配额调整、Retinue size 调整、Dominion/Writ 运维（暂停/恢复/删除）
- **不可操作**：Dominion/Writ 创建和内容编辑、Psyche 任何编辑、Instinct 偏好修改、Norm 质量配置、任务提交
- 禁止原始文件编辑（JSON/Markdown/文档），所有配置编辑使用结构化控件（选项、按钮、下拉栏、滑块），简洁美观

### 2.4 CLI

- 不独立提交任务
- 用于开发调试和系统管理
- 命令参数交互，纯文本输出

---

## 3. 通知与汇报机制

### 3.1 通知路由

daemon 内部事件到用户通知的路由规则：

| Nerve 事件 | Portal（chat 消息） | Telegram |
|-----------|---------------------|----------|
| `deed_completed` | 完成消息 + Offering 预览 + 反馈选择 | 完成通知 |
| `deed_failed` | 问题诊断 + 选项 | 失败通知 |
| `passage_completed` | 阶段总结 + 下阶段计划 + 👍/👎 | 阶段完成通知 |
| `deed_rework` | 进度消息 | — |
| `deed_rework_exhausted` | 诊断消息 + 选项 | 警告通知 |
| `ward_changed` | 维护提示消息 | 状态通知 |
| `eval_expiring` | 提醒消息 | 提醒通知 |

### 3.2 通知失败兜底

Telegram 推送失败时的降级链（已在方案中定义）：
1. Telegram Bot API 重试（3 次，指数退避）
2. macOS 桌面通知
3. `~/daemon/alerts/` 日志文件
4. 失败通知入队（暖机前实现通知失败队列）

### 3.3 Dominion 相关的主动沟通

daemon 通过 witness routine 观察 Dominion 进展，主动与用户沟通：

- **进展汇报：** "你之前关注的 X，最近有些新进展。要不要我深入看看？"
- **周期任务完成：** "这周的 [任务描述] 做完了。[简要发现]。详细内容已经整理好了。"
- **建议新方向：** "关于 X，我注意到 [发现]，可能值得关注。"

**通道选择：**
- Dominion 相关的主动沟通通过 Telegram 推送（轻量、异步）
- 用户回应后引导到 Portal 继续深入对话

**触发机制：**
- witness routine 发现值得沟通的进展 → 发出 Nerve 事件 → Voice 生成自然语言 → Herald 推送

---

## 4. 周期任务的用户感知（Q8.4）

**核心原则：** 用户不接触"周期任务"概念。

**用户体验：**
1. 用户在 Portal 对话中自然表达持续关注意图："每周帮我看看 X 的动态"
2. daemon 理解意图，内部创建 cron Writ
3. 每次 Writ 触发生成 Deed，完成后通过 Telegram 用自然语言汇报
4. 用户想停止 → 在 Portal 对话中说"X 不用看了" → daemon 内部 disable Writ
5. 用户想调整频率 → 在 Portal 对话中说"X 改成每月看一次" → daemon 调整 Writ

**不需要的：** 周期任务创建/编辑/暂停的专用 UI。一切通过自然语言对话。

---

## 5. Dominion 推进的用户交互（Q8.5）

**核心原则：** Dominion 推进对用户不可见。

**机制：**
1. witness 观察 Dominion 内 Writ/Deed 的进展
2. 发现值得沟通的事 → 通过 Voice 生成自然语言
3. Telegram 推送（如"X 方面有新进展，要不要深入看看？"）
4. 用户回应 → daemon 内部调整 Writ 结构或触发新 Deed
5. 不回应 → daemon 按既有 Writ 继续运转

**不需要的：** Dominion/Writ 的用户面管理界面。用户只通过自然语言与 daemon 交流意图。

---

## 7. 已确认项

| # | 决策 |
|---|------|
| 7.1 | awaiting_eval 过期时间 = **48 小时**，过期前 12 小时 Telegram 提醒 |
| 7.2 | Portal 范式 = **Deed = Chat Session**，100% 复刻 Claude 网页端对话行为 + 任务状态层 + 产出展示层 + inline 反馈/计划组件 |
| 7.3 | 设计准则 = **静态学 Claude，动态学 Apple** |
| 7.4 | 侧边栏 = **自动聚类**，daemon 按 Dominion 归组并用自然语言标签，独立 Deed 平铺 |
| 7.5 | 计划组件 = **富 UI 卡片**（非 markdown），三种形态对应 Errand / Charge / Endeavor |
| 7.6 | 计划组件**原地刷新**，进度文字消息独立 |
| 7.7 | 转场动效 = 5 个关键节点（T1-T5），全部有流畅过渡 |
| 7.8 | Telegram = **纯通知**，不提供反馈入口 |
| 7.9 | 反馈 = chat 内 **inline 选择组件**（plan mode 风格），选完后 daemon 问"还有什么想说的吗？" |
