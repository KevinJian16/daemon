# 界面分野设计规范 (Interface Separation Design)

> 日期：2026-03-06
> 基准：`daemon_统一方案_v2.md`

---

## 核心原则

**零重叠原则**：任何用户操作归属且仅归属一个界面。Portal 和 Telegram 之间没有功能重叠。

| 界面 | 角色 |
|---|---|
| **Portal** | 用户操作的唯一入口（发起、控制、评价、Circuit 管理） |
| **Telegram** | 纯推送通知频道，不接受任何用户输入 |
| **Console** | 系统治理（Strategy/Norm/Gate）；与用户操作完全分离 |

---

## 一、Portal

### 1.1 整体结构

Portal 采用 Claude.ai 式导航：左侧边栏入口 → 右侧主内容区。

**侧边栏入口（顺序固定）：**
1. **对话** — 发起运行的主入口
2. **运行中** — 当前 `running` 状态的 run 列表
3. **待评价** — 处于评价窗口期内的 run 列表（含倒计时）
4. **历史** — 已过窗口期的所有 run
5. **Circuit** — Circuit 列表与管理

### 1.2 对话页

功能：
- 发起所有类型的 run（Pulse / Thread / Campaign / Circuit）
- 提交后 Router 识别意图，Circuit 意图自动按 Circuit 流程处理，无需用户选类型
- 对话框的意图识别层（在发送给 Router 之前）识别控制命令：

| 用户输入 | 动作 |
|---|---|
| `取消` / `cancel` | 查找 `running` 状态的 run，调 `POST /runs/{id}/cancel` |
| `暂停` / `pause` | 查找 `running` 状态的 run，调 `POST /runs/{id}/pause` |

控制命令匹配后直接返回结果文本，不走 Router。

### 1.3 运行中页

显示所有 `run_status = running` 的 run，每条显示：
- `run_title`（Router 生成，不可变，以提交时语言为准）
- `work_scale` badge（Pulse / Thread / Campaign）
- 已运行时长
- **取消** / **暂停** 按钮（行内操作）

**Campaign 全程常驻运行中页**，直到 completed / cancelled / aborted。根据当前内部状态显示不同信息：

| Campaign 内部状态 | 附加显示 | 可用按钮 |
|---|---|---|
| Milestone N 执行中 | "执行中 · milestone N/总数" | 取消整个 Campaign |
| Milestone N 等待评价（窗口期内） | "等待 milestone N 评价 · 剩余 Xh Xm" | 取消整个 Campaign |
| Milestone N 执行失败 | "milestone N 执行失败" | **重试** / **中止 Campaign** |

**取消**（运行中页）= 强制中断执行；**中止**（待评价页）= 评价后的门控决策，两者语义不同。

### 1.4 待评价页

显示所有处于评价窗口期内的 run（包括 Circuit 实例——其已是 `completed` 但窗口期内显示在此）。

每条显示：
- `run_title`
- 窗口期剩余倒计时（如"剩余 1h 23m"）
- 点击进入详情 → 完整评价界面

**Campaign 里程碑**：每个完成的里程碑各自在待评价页独立出现，行为与 Thread 完全相同，倒计时独立计时。

**进入详情后的评价界面：**
1. 显示里程碑摘要（review agent 生成，含关键发现）
2. Drive 链接（用户点击查看完整产物）
3. 动态选择题（由 `generate_user_feedback_survey` skill 生成，基于 run 内容，3-5道题）
4. 可选文字评语框
5. 提交按钮
6. （Campaign milestone 专属）**继续下一 milestone** / **中止 Campaign** 按钮

**重要约束：**
- 选择题仅部分回答也接受，不报错
- 未评价直接离开，窗口期到期后 run 自动完成（Campaign milestone 自动继续）
- 用户评价对系统是 optional 附加输入，有则写入 Memory，无则静默跳过

### 1.5 历史页

显示所有已过窗口期的 run（无论是否有评价数据）。

- 按时间倒序
- 可追加评语（文字，无选择题）
- 可查看 Drive 链接（按 Outcome GC 规则，6 个月后从 Portal 消失）

### 1.6 Circuit 页

显示所有 Circuit 配置列表，每条显示：
- `run_title`（Circuit 的名称）
- cron 表达式 + 时区
- 状态（active / paused / cancelled）
- 上次触发时间 / 已触发次数
- **暂停** / **立即触发** / **删除** 按钮

创建 Circuit：从**对话页**发起，Router 识别为 Circuit 意图后引导确认（cron 和 prompt），不另开创建表单。

---

## 二、Telegram

### 2.1 角色定位

**纯推送通知频道。** Telegram bot 不接受任何用户输入：
- 删除所有 `_handle_text()` 处理逻辑
- 删除所有 callback_query（inline keyboard）处理逻辑
- 删除所有 `/command` 命令处理器
- 只保留出站 `send_message` 函数

### 2.2 通知格式

**固定规则：**
- 系统文本：始终中文（固定字符串）
- `run_title`：原样嵌入，不翻译（保持提交时的语言）

**格式模板（示例）：**

```
Thread 完成 · "Write a summary of this paper" · 请去 Portal 评价
Campaign 里程碑 2 完成 · "分阶段竞争格局研究" · 请去 Portal 查看
Campaign 里程碑已自动推进（无操作）· "分阶段竞争格局研究"
Circuit 实例完成 · "每日简报" · 请去 Portal 评价
Pulse 完成 · "总结这篇文档" · 请去 Portal 查看
```

### 2.3 通知触发时机

| 事件 | 通知 |
|---|---|
| Pulse / Thread 执行完成（进入窗口期） | ✅ 推送 |
| Campaign milestone 执行完成（进入窗口期） | ✅ 推送 |
| Campaign milestone 窗口期到期自动推进 | ✅ 推送（告知已自动推进） |
| Campaign 整体完成（最后 milestone 通过） | ✅ 推送 |
| Circuit 实例执行完成 | ✅ 推送 |
| 预算耗尽 / Gate 变为 RED | ✅ 推送（系统告警） |
| Skill 演化 proposals 积累 | ✅ 推送摘要 |
| Circuit 触发开始执行 | ❌ 不推送（仅推完成） |

### 2.4 绝对禁止

- Telegram 不接受任何用户操作（cancel / pause / 评价 / Circuit 创建删除）
- Telegram 不显示 run_id（系统内部字段，不对用户暴露）
- Telegram 不发送 inline keyboard 供用户点击

---

## 三、Console

### 3.1 角色定位

**系统治理界面。** Console 面向系统管理员视角，不是用户日常操作界面。

### 3.2 只读区域

| 面板 | 内容 |
|---|---|
| Runs 全局视图 | 所有 run 状态、`run_status`、`work_scale`、时间戳 |
| Circuit 列表 | 只读（用户在 Portal 创建/删除） |
| Gate 状态 | 当前 Gate 颜色（GREEN / YELLOW / RED）与原因 |
| Spine 状态 | 各 routine 最近执行时间与结果 |
| Agent 状态 | 各 agent 健康状态 |

### 3.3 写操作（治理专属）

| 操作 | 说明 |
|---|---|
| Strategy 晋升 / 回滚 | `strategy_stage` 变更 |
| Norm 配置修改 | 质量基准 / 偏好 / 预算边界 |
| Gate 强制覆盖 | 紧急时手动设置 Gate 颜色 |
| 强制终止 run | 运维操作（区别于用户 cancel） |
| **评价窗口期时长配置** | 默认 2 小时，在此修改；Norm 配置项 `eval_window_hours` |

### 3.4 Console 绝对不做

- 发起任何 run
- 对 run 进行用户评价
- 创建 / 删除 Circuit

---

## 四、评价窗口期机制（Eval Window）

### 4.1 规则

**窗口期时长**：由 Console Norm 配置 `eval_window_hours`，默认 2 小时。

执行完成 → 窗口期开始计时：

| 情形 | 结果 |
|---|---|
| 用户在窗口期内完成评价 | 评价数据写入 Memory，run 立即 `completed` |
| 用户在窗口期内部分回答 | 已回答部分写入 Memory，run 立即 `completed` |
| 窗口期到期，无任何评价 | run 自动 `completed`，无评价数据 |
| Campaign milestone 窗口期到期 | milestone 自动 `passed`，Campaign 继续，Telegram 推送告知 |

### 4.2 各类型行为

| 类型 | 是否进入窗口期 | Circuit 特殊说明 |
|---|---|---|
| Pulse | ✅ | — |
| Thread | ✅ | — |
| Campaign milestone | ✅ | milestone 各自独立窗口期 |
| Circuit 实例 | ✅ | 实例已是 `completed`，但窗口期内出现在"待评价"页供可选评价 |

### 4.3 两层 review 的区分

| 层 | 执行者 | 是否必须 | 是否影响 completed 状态 |
|---|---|---|---|
| 系统 review（pipeline 内置） | review agent | **必须，不可省略** | 是（通不过则 run 进入 failed） |
| 用户评价（Portal 外部） | 用户 | 可选 | **否**，永远不影响状态 |

---

## 五、语言层级

三个语言层完全独立，互不绑定：

| 层 | 规则 |
|---|---|
| UI 文本（按钮、标签） | Portal/Console 有 zh/en 切换，随用户设置变化 |
| `run_title` | Router 在提交时生成，与用户提交语言一致，**不可变、不随 UI 语言切换而翻译** |
| 产物（deliverables） | 始终双语（zh + en 各一份完整文件），不受提交语言影响 |

---

## 六、run_title 规范

- **生成时机**：Router 在生成 Weave Plan 时同步生成 `run_title`
- **风格**：简短描述性标题（参考 Claude.ai 对话命名风格），不超过 15 个词
- **语言**：与用户提交语言一致
- **不变性**：写入 run 记录后永久固定，UI 语言切换不影响
- **用途**：替代 `run_id` 出现在所有用户可见界面（Portal、Telegram 通知）
- **run_id**：仅作系统内部字段，不对用户暴露

---

## 七、Campaign 特殊行为补充

### 7.1 初始计划确认

Campaign 提交后，Router 生成 milestone 结构化计划，**通过 Portal 对话框呈现**（不走 Telegram），用户在对话框内确认后 Campaign 正式启动。

### 7.2 Milestone 结构：线性，不引入 DAG

Milestone 严格线性执行（1→2→3→N）。"并行采集多个来源"是单个 milestone 内部的并行 activity，不提升为并行 milestone。条件分支通过继续/中止门控实现，不做 milestone 级别 if/else。

### 7.3 Campaign Context 累积

每个 milestone 成功完成后，review agent 生成的摘要（含关键发现 + Drive 链接）追加到 Campaign manifest 的 `campaign_context` 字段。下一个 milestone 执行时继承此 context 作为额外输入，使后续 milestone 能在前序产出基础上推进。

Memory fabric 负责跨 Campaign 的长期学习；Campaign context 只在当次 Campaign 内有效。

### 7.4 Milestone 执行失败处理

Milestone 执行失败（超出 rework 预算）：
- Telegram 推送告警
- Portal 运行中页显示"milestone N 执行失败"，出现 **重试 / 中止 Campaign** 按钮
- 用户选重试 → milestone 重新执行
- 用户选中止 → Campaign cancelled
- 用户不操作 → Campaign 保持暂停，等待人工介入

### 7.5 里程碑产物查看

里程碑产物写入 Google Drive，Portal 待评价页展示：
- 里程碑摘要（review agent 生成）
- Drive 链接（用户自行打开查看）

Portal 不内嵌渲染产物（代码、PDF、markdown 均由 Drive 处理）。

### 7.6 里程碑评价与门控合并

- Milestone 行为与 Thread 完全相同，独立出现在待评价页
- 评价表单底部额外显示：**继续下一 milestone** / **中止 Campaign**
- 窗口期到期无操作 → 自动继续，Telegram 推送告知

---

## 八、Skill 演化审批

当前 HANDOFF_IMPL.md §1.3 中"Portal 对话控制命令"已废弃（该功能不再需要，因 Telegram 取消了输入功能）。

Skill 演化 proposals 积累 ≥5 条时，Telegram 推送摘要，用户打开 **Portal → 对话页** 回复意见，Router 识别后转 Spine 采纳或忽略。不再使用 Telegram 回复。
