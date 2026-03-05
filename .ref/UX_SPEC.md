# UX 偏好规范

本文件记录用户 UX 偏好，作为所有 UI/UX 改动的设计依据。

---

## 设计语言

**参照**：Claude.ai + Apple 设计语言
- 极简，内容为王，大量有意义的留白
- Typography 驱动，无装饰性元素，无渐变，无图标堆砌
- 按钮/操作上下文出现，不预先堆满屏幕
- 跟随系统深/浅色（`prefers-color-scheme`）
- Console 与 Portal 同一设计语言，Console 是 Portal 的"运维入口"，从 Portal 右上角进入

**不要出现**：
- openclaw 默认主题风格（颜色杂乱、间距不一致）
- 大量色块填充、阴影堆叠
- 找不到的操作入口（按钮藏在角落里）

---

## Portal 布局

**桌面**：双栏响应式
```
+---sidebar---+----------main-content----------+
| [+ New Task]| Task Title   Pulse · Running    |
|-------------|  Progress:  ████░░░░  Phase 2/4  |
| ⚡ Pending  |                                  |
|   Milestone | Pending Review                   |
|   Confirm   |  Milestone 2: Analysis done      |
|             |  [★★★★☆]  [Comment]  [Approve]  |
| ● Running   |                                  |
|   Report    | Output                           |
|   Review    |  ...                             |
|             |                                  |
| ✓ Done (5) |                    [⚙ Console]  |
+-------------+----------------------------------+
```

**手机**：单栏，sidebar 折叠为底部 Tab（待处理 / 进行中 / 已完成）

---

## Portal 首屏优先级

1. **待处理（需要我操作的）** — 最突出显示：待评分 milestone、待确认 Campaign plan、待处理中途变更
2. **进行中任务** — 次级展示：正在运行的任务 + 进度
3. **快速提交入口** — 始终可见的输入框/按钮

---

## Telegram vs Portal 分野

两端都支持手机使用。分野是**触发模式**，不是设备。

### Telegram = 系统找你（push-initiated）

系统有事通知你，你快速响应后放下手机。

| 事件 | Telegram 行为 |
|---|---|
| 任务启动 | 确认收到，预计规模（Pulse/Thread/Campaign） |
| Milestone 完成 | 完整摘要 + inline keyboard 评分（1-5）+ 可选一句话 |
| Campaign plan 就绪 | 计划摘要 + [确认开始] [取消] |
| 需要用户决策 | 推 inline keyboard，30 秒内可决策的 |
| 异常/失败 | 说清楚出了什么事 + [重试] [取消] |
| 任务完成 | 完整摘要（主要结论直接推，不用开 Portal） |
| 系统内部 rework | 不推，用户不感知 |

### Portal = 你找系统（pull-initiated）

你主动打开，想看或想做一件事。

| 场景 | Portal 能力 |
|---|---|
| 提交任务 | 输入 + 文件上传（拖拽或点击） |
| 深度回顾 | 看完整输出内容 + 评价（有上下文） |
| Campaign 全貌 | milestone 时间线 + 各阶段状态 |
| 中途调整 | 修改方向 / 暂停 / 取消（有 diff 对比） |
| 历史浏览 | 已完成任务、产出物、评分记录 |
| 系统管理 | 进入 Console（Agent 状态、调度、健康） |

### 去重规则（不重复触发）

- Telegram 里完成的操作（评分/确认/取消），Portal 里显示"已在 Telegram 处理"，不再弹提示
- Portal 里完成的操作，不再推 Telegram 提醒
- 同一事件只触发一次通知；Portal 是状态展示，不是通知源

---

## 中途改主意

任务进行中，用户可以介入，三种模式：

| 模式 | 触发 | 系统行为 |
|---|---|---|
| **取消** | Telegram 按钮 / Portal 按钮 | 立刻停止，标记 `cancelled`，不计入 playbook 学习 |
| **调整方向** | Telegram 发文字 / Portal 输入框 | 注入 correction note，下一个 phase 从修正后的 intent 继续 |
| **暂停** | Telegram `/pause` / Portal 按钮 | 等当前 step 完成后暂停，推通知等用户确认继续 |

Campaign 特殊处理：
- milestone 边界是天然暂停点，可在下一个 milestone 开始前调整方向
- 进行中的 milestone 不强行打断，等当前 step 完成后暂停

---

## 评价体系

```
系统评价（自动，用户不感知）
  └─ review rubric → 不通过 → 自动 rework → 最多 N 次
  └─ review rubric → 通过 → 触发用户评价

用户评价（触发一次，谁先完成算谁）
  ├─ Telegram：inline keyboard 1-5 + 可选一句话（快速）
  └─ Portal：同一评价，但附带完整输出内容（有上下文）

结果写入 milestones/<n>/result.json + playbook.evaluate()
```

---

## 文件上传

- 任务提交时即可附带文件（不强制用固定文件夹）
- Portal：拖拽或点击上传，与任务描述在同一区域
- Telegram：直接发文件后跟上任务描述，Bot 自动关联

---

## 语言策略

| 内容类型 | 处理方式 |
|---|---|
| 系统定义性术语（Campaign, Thread, Pulse, Trace, Milestone, Weave…） | 不翻译，保留英文 |
| 产品名（Temporal, OpenClaw, Google Drive…） | 不翻译 |
| UI 文本（按钮、标签、提示） | 支持中/英一键切换，默认中文 |
| 任务内容、错误信息、反馈文本 | 跟随界面语言设置 |

语言切换入口：界面右上角，持久化到 localStorage。

---

## Tailscale 外网访问

- 状态：有账号，尚未配置
- 计划：近期配置，Portal + Console 对外暴露（VPN 模式，设备间访问）
- 当前 openclaw.json gateway.tailscale.mode = "off"，待配置后改 "tailscale"

---

## 评价体系

### 两档评价，可升级

- **快速评价**：1-5 分 + 可选一句话。Telegram inline keyboard 或 Portal 一键评分，30 秒完成
- **深度评价**：多维度 + 长文字，仅 Portal（需要完整输出上下文）。可在快速评价之后任意时间补充
- 规则：有 deep_rating → playbook 用 deep_rating；只有 quick_rating → 用 quick_rating；允许反悔（deep 可覆盖 quick）

### 任务保留与评价时效

用户视角：**Portal 能看到的任务 = 可以操作的任务**。

| 阶段 | 时间 | Portal 状态 | 输出可访问性 |
|---|---|---|---|
| 本地完整 | 0–7 天 | 可见，完整操作 | 本地直接读取 |
| Drive 归档 | 7–30 天 | 可见，完整操作 | 按需从 Drive 拉取 |
| Drive 保留 | 30 天–6 个月 | 可见，可补充评价 | 按需从 Drive 拉取 |
| 完全清理 | 6 个月后 | 不再显示 | 已删除 |

- 6 个月后任务从 Portal 消失，index 条目随之清理，Drive 同步清理
- 学习效果（playbook value_score）在任务完成时即写入，清理不影响已学到的内容
- 评价入口在 Portal History 页，任务存在期间始终可操作

---

## 约束摘要

| 维度 | 决策 |
|---|---|
| 视觉调性 | Claude.ai + Apple，极简留白 |
| 深浅色 | 跟随系统 |
| 主要操作界面 | Telegram（通知+快速操作）+ Portal（深度工作面） |
| Console | Portal 内入口，同设计语言 |
| 文件上传 | 两端均支持，随提交时附带 |
| 通知去重 | 同一事件只触发一次，跨端操作互相感知 |
| 中途变更 | 支持取消/调整方向/暂停，两端均可触发 |
| 通知详细度 | 完整摘要直推 |
| 评价入口 | 两端均可，谁先完成算谁，不重复弹 |
| 设备 | 手机 + 电脑均需兼容 |
| UI 语言 | 一键切换，默认中文，术语保留英文 |
