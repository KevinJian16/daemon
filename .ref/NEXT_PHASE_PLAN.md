# Daemon 下一阶段计划

## Context

V2 方案（§12-19）代码层面基本全部落地。剩余工作分三个方向：
1. V2 最后一个 gap 的收尾
2. 用户体验全面优化（UI、Telegram、外网访问）
3. 系统暖机与 Skills 生态建设

本计划将以文档形式保存到 `.ref/NEXT_PHASE_PLAN.md`。

---

## 当前状态确认

| 模块 | 状态 | 备注 |
|---|---|---|
| §12 知识来源区分 | ✅ DONE | source_type/source_agent 字段、优先级排序、TTL 策略全部实现 |
| §13 归档清理 + Drive | ✅ DONE | _cold_export_memory / _upload_to_drive / _cleanup_local_jsonl 均实现 |
| §14 Budget 预检 | ✅ DONE | _preflight_provider_budget 含 fallback chain |
| §14.2 Spine 逻辑隔离 | ✅ DONE | distill/learn 均用 snapshot 模式 |
| §15.1 自适应调度 | ✅ DONE | queue-depth + gate 状态动态调整间隔 |
| §15.2 自我升级闭环 | ⚠️ PARTIAL | proposals 生成有，≥5 条推 Telegram 的通知逻辑缺失 |
| §16 Pulse/Thread/Campaign 分级 | ✅ DONE | complexity probe + task_scale 字段 |
| §16.2 Checkpoint 持久化 | ✅ DONE | 逐步写 state/runs/ |
| §16.3 Context Window 预检 | ✅ DONE | 70% 阈值 + 压缩触发 |
| §17 Campaign 模式 | ✅ DONE | Phase0-Synthesis 完整，API endpoints 齐全 |
| §19 用户反馈闭环 | ✅ DONE | 动态问卷 + 双写 playbook + Memory |
| Portal UI | ✅ DONE | 6 面板含 Campaign、Feedback modal |
| Console UI | ✅ DONE | 15 面板 |
| Telegram Bot | ✅ DONE | 命令集含 campaign_confirm / milestone feedback |
| Tailscale | ❌ DISABLED | openclaw.json mode="off" |
| Skills（现有） | 31 个（7 agent）| 可用但未从 ClawhHub 扩充 |

---

## 阶段一：V2 收尾（1 个 gap）

**目标文件**：`spine/routines.py`、`services/delivery.py` 或 Telegram adapter

**内容**：`learn()` 产出的 `skill_evolution_proposals.json` 条目计数，积累 ≥5 条时向用户推 Telegram 摘要（列出各 proposal 标题 + 影响范围）。用户回复后标记采纳/忽略。这是 §15.2 唯一缺失的部分。

---

## 阶段二：用户体验优化

### 2.1 偏好对齐（先做，再动手）

在修改任何 UI 之前，通过场景描述方式对齐以下偏好：

**UI 风格**
- Portal 和 Console 的视觉调性：极简/信息密度高/卡片式/表格式
- 配色方向：深色/浅色/混合
- 最重要的操作：提交任务、查看进度、反馈评价——哪个要最顺手
- 手机端 vs 桌面端优先？（影响布局策略）

**Telegram Bot 交互**
- 任务完成时收到的通知详细程度：一句话摘要 / 完整结果 / 带链接到 Portal 查看
- 进度播报的频率：每个 milestone / 只在完成和异常 / 完全静默只收完成
- 是否希望在 Telegram 里直接做所有操作，还是只做确认，详情去 Portal

**外网访问**
- 主要使用场景：Telegram 已经够用 / 需要在外网直接访问 Portal 和 Console
- Tailscale 账号是否已有 / 是否愿意开 Funnel（公网）还是只 VPN（设备间）

### 2.2 UI 实施（偏好对齐后）

根据 2.1 的输出实施改动。改动前每个方向给用户看 ASCII mockup 确认。

### 2.3 Tailscale 接入

- 修改 `openclaw.json` gateway.tailscale.mode
- 配置 daemon 服务在 tailscale 网络上的端口暴露
- 可选：Portal/Console 的访问鉴权（当前仅 localhost）

---

## 阶段三：Skills 生态建设

### 3.1 Skills Campaign（第一个正式 Campaign）

**任务设计**：用 daemon 系统自己跑一个 Campaign，专门用来评估和引入 ClawhHub skills。

```
Milestone 1  ClawhHub skills 清单采集
  collect agent → 抓取 ClawhHub 上的 skill 列表、描述、star 数、更新时间

Milestone 2  Gap 分析
  analyze agent → 对比现有 31 个 skills，识别：
    - 有价值但缺失的能力（如日历、笔记、RSS、代码执行、图像处理等）
    - 与现有重复可替代的
    - 质量明显更好的同类 skill

Milestone 3  优先级排序报告
  review + render → 输出结构化"skill 引入优先级报告"

Milestone 4  用户确认 + 批量引入
  用户确认后，build agent 执行安装 + V2 包装
```

这个 Campaign 同时是：系统第一次真实 Campaign 任务的压力测试 + skills 生态建设本身。

### 3.2 Skills 持续运营

- 每季度跑一次 skills audit（Pulse 级任务，自动触发）
- `spine.learn` 产出的 `skill_evolution_proposals.json` 形成闭环：skills 表现差 → proposals → 用户确认 → 升级或替换

---

## 阶段四：暖机

### 4.0 冷启动特性（重要前提）

学习机制已全部落地，但有明确的冷启动特性：

| 指标类型 | 生效时机 | 说明 |
|---|---|---|
| **Quantitative**（success_rate、value_score、tier）| 第 1 个任务完成后立即 | spine.record 直接写入 playbook，机械更新 |
| **Qualitative**（新 method candidate、weave_patterns）| 约 5-10 个任务后 | spine.learn 需要足够的 trace 数据才能提炼有效模式 |
| **Router 行为变化**（读取 runtime_hints 后调整规划）| spine.relay 每 4h 写一次 | 学到的模式最多延迟 4h 反映到下一次任务规划 |

因此暖机任务要**覆盖不同 cluster**，否则系统只在一个方向上优化。

### 4.1 冒烟测试（阶段三 Skills Campaign 之前）

目标：验证端到端链路全部跑通，确认 spine 学习循环、review 评分、Telegram 通知、Portal 产出查看均正常。

最少任务集（每个 cluster 至少 1 个）：
- **Pulse**：总结一个 URL（collect → render，最短路径）
- **Thread / research_report**：某个技术主题小报告
- **Thread / dev_project**：写一个小工具脚本
- **Thread / knowledge_synthesis**：整合几条已有笔记或材料

每个任务完成后：填写用户评价（这是写入 Memory 的第一批 `human` 来源知识）。

验收标准：
- `state/nerve_bridge/events.jsonl` 有 task_completed 事件
- `playbook.db` 里对应 method 的 `total_runs` 增加、`success_rate` 有值
- `openclaw/workspace/router/memory/runtime_hints.json` 的 `best_methods` 里 `runs > 0`

### 4.2 正式暖机（Skills 就绪后）

覆盖 4 个 cluster + 个人产出辅助：
- 每种 cluster 各跑 3-5 个代表性任务，大小混搭
- 约 10 个任务后检查 `weave_patterns/` 目录，确认有新 pattern 产生
- 约 15-20 个任务后，`spine.judge` 应开始看到 hot/warm/cold tier 分化

### 4.3 暖机质量评估指标

- `playbook.db` method 的 value_score 分布：hot/warm/cold 比例是否健康
- `weave_patterns/` 数量和 index.json 里的 hit_count
- 用户评价平均分（建立基线，目标 ≥ 3.5/5）
- 各 agent 的 P95 延迟（是否需要调整并发配额）

---

## 推进顺序

```
现在    → 阶段一：§15.2 补全（小改动）
         → 阶段二 2.1：偏好对齐访谈（非代码，需要用户配合）
Week 1  → 阶段二 2.2-2.3：UI 实施 + Tailscale 接入
         → 阶段三 + 阶段四 4.1：Skills Campaign + 冒烟测试
Week 2+ → 阶段四 4.2-4.3：正式暖机，持续迭代
```
