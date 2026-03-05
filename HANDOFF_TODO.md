# Daemon 实现待办（交接版）

> 文档权威：`.ref/daemon_统一方案_v2.md`（唯一基准）
> 本文件列出所有尚未实现、需要新开发的功能项。
> 已实现的功能（Phase 1-4 主体、cache governance、Weave 命名）不在此列。
> 最后更新：2026-03-05

---

## 一、知识来源区分（§12）

**涉及文件**：`fabric/memory.py`

- [ ] `units` 表新增 `source_type TEXT`（枚举：`empirical` / `synthetic` / `collected` / `human`）和 `source_agent TEXT`
- [ ] `_init_db()` 用 ALTER TABLE 做字段迁移（参考现有模式，加 OperationalError catch）
- [ ] `store()` / `update()` 接口增加 `source_type` 和 `source_agent` 参数
- [ ] `query()` 支持按 `source_type` 过滤和排序（empirical 优先）
- [ ] `spine/routines.py`：`tend()` 对 `collected` 类 unit 的 TTL 设为 `empirical` 的 50%
- [ ] `spine/routines.py`：`distill()` 做 dedup 时 `empirical` 胜 `synthetic`，`human` 胜一切

---

## 二、归档与清理制度（§13）

**涉及文件**：`spine/routines.py`、`spine/nerve.py`、`config/spine_registry.json`

### Memory GC 路径
- [ ] `librarian()` 新增 `_cold_export_memory()` helper：查找 archived 满 7 天且未被引用的 unit，导出为 JSONL 文件（`state/archive/memory/<year>/<month>/units_<ts>.jsonl`），从 SQLite 删除
- [ ] `librarian()` 新增 `_cleanup_local_jsonl()` helper：删除本地 `state/archive/` 下超过 30 天的 JSONL 文件
- [ ] `librarian()` 新增 `_upload_to_drive()` helper：调用 apply agent `google_drive_upload` skill 上传 JSONL（失败降级，记录 `archive_upload_failed` 告警，不阻断主流程）；Drive 上传路径：`daemon/archive/<year>/<month>/`

### memory_pressure 机制
- [ ] `spine/nerve.py`：新增 `memory_pressure` 事件类型
- [ ] `spine/routines.py`：`tend()` 检查 `total_units_cap`（默认 10,000，读自 Compass），超限触发 `memory_pressure` nerve 事件
- [ ] `config/spine_registry.json`：`spine.librarian` 的 `nerve_triggers` 加入 `memory_pressure`

### apply agent Google Drive skill
- [ ] `openclaw/workspace/apply/skills/google_drive_upload/SKILL.md`：新建，定义输入（文件路径、Drive 目标路径）、输出（upload_url）、失败合约
- [ ] `openclaw/workspace/apply/TOOLS.md`：新增 `google_drive_upload` 说明

---

## 三、任务准入 Budget 预检（§14）

**涉及文件**：`services/dispatch.py`（或 `spine/routines.py`）、`spine/contracts.py`

- [ ] Router 生成 Weave Plan 前，查询 Compass 各 provider 当日剩余配额
- [ ] 余量不足时按 fallback_chain 顺序切换 provider（minimax → qwen → zhipu → deepseek）
- [ ] 所有 provider 余量均不足时：任务进入 `queued`，Telegram 告警，不得伪装 running
- [ ] 预检结果写入 `plan.provider_routing` 字段
- [ ] 新增失败码 `provider_budget_insufficient`（与已有 `provider_budget_exceeded` 区分）

---

## 四、Spine 逻辑隔离（§14.2）

**涉及文件**：`spine/routines.py`

- [ ] `distill()` 和 `learn()` 运行开始时对相关数据做 snapshot，写入 `state/tmp/spine_<routine>_<ts>.json`
- [ ] routine 结束后清理 tmp 文件
- [ ] 处理过程中不再反复读最新状态，只读 snapshot

---

## 五、自适应调度（§15.1）

**涉及文件**：`services/scheduler.py`、`config/spine_registry.json`

- [ ] `scheduler.py` 实现 adaptive 间隔计算函数：
  - 队列空 + gate open → 趋向下限（2h）
  - 队列繁忙（>3 running）→ 趋向上限（12h）
  - gate closed → 暂停，恢复后重置为默认间隔
- [ ] `witness` 和 `learn` 的注册改为传入 adaptive 计算函数而非固定 cron

---

## 六、自我升级闭环（§15.2）

**涉及文件**：`spine/routines.py`、`services/delivery.py`（或 telegram adapter）

- [ ] `learn()` 产出的 `skill_evolution_proposals.json` 条数计数
- [ ] 条数 ≥ 5 时，触发 Telegram 推送摘要（列出各条 proposal 标题和影响范围）
- [ ] 用户回复"采纳"后，SKILL.md / config 类改动自动写回（sandbox 测试通过后）；Python 代码类改动仅标记 `pending_human_review`，不自动执行

---

## 七、任务规模分级（§16）

**涉及文件**：`services/dispatch.py`、`temporal/activities.py`、路由相关

- [ ] analyze agent 第一步增加 complexity probe：输出 `estimated_phases`、`estimated_hours`、`requires_campaign`
- [ ] Router 根据 probe 结果写入 `plan.task_scale`（`pulse` / `thread` / `campaign`）
- [ ] `pulse` / `thread` 完成后触发一次性用户评价（问卷推送）

### Checkpoint 持久化
- [ ] 每个 activity 完成后，中间产出写入 `state/runs/<task_id>/steps/<step_id>/output.json`
- [ ] Worker 重启恢复逻辑：已完成步骤从文件系统恢复，不重跑

### Context Window 预检
- [ ] render 步骤开始前，统计上游产出 token 估算
- [ ] 超过目标模型 context window 70% 时：analyze agent 做结构化摘要压缩，附原始产出路径
- [ ] 禁止静默截断

---

## 八、Campaign 模式（§17）

**涉及文件**：新建 `temporal/campaign_workflow.py`（或扩展现有 workflow）、`services/api.py`

### Phase 0 规划
- [ ] `plan.task_scale == 'campaign'` 时触发 Campaign 工作流
- [ ] analyze 生成 milestone 列表（每条：名称 + 预期产出 + 输入依赖），写入 `state/campaigns/<id>/manifest.json`
- [ ] Telegram 推送计划表，等待用户确认（唯一主动门控点）
- [ ] 用户拒绝 → status 写 `cancelled`

### Phase 1..N milestone 执行
- [ ] 每个 milestone 作为独立 Thread 级 workflow 执行
- [ ] 完成后：review rubric 评分（客观，自动）
  - 不通过 → rework（最多 2 次）→ 超出 → campaign 暂停，Telegram 告警
  - 通过 → 触发 `generate_user_feedback_survey`，推送 Telegram/Portal
- [ ] 用户评价回调：
  - 满意 → 写 result.json + playbook.evaluate(pass) → 开始下一 milestone
  - 不满意 → rework（最多 1 次，用户 hint 作为 instruction）→ 超出 → campaign 暂停
- [ ] Telegram 定时播报进度（每完成一个 milestone 推送一次）

### Phase N+1 Synthesis
- [ ] analyze + review 连贯性检查（强制，不可跳过）
- [ ] 推送整体评价问卷给用户
- [ ] 用户最终评价写入 `fabric/memory.py`（source_type=human）
- [ ] render 统一交付物，apply 交付 + 完成通知

### API 支持
- [ ] `GET /campaigns` — 列出所有 campaign 及当前 phase
- [ ] `GET /campaigns/{id}` — campaign 详情（milestone 列表、各 milestone 状态与评分）
- [ ] Console 页面新增 Campaign 面板

---

## 九、用户反馈闭环（§19）

**涉及文件**：review agent skill（已建 SKILL.md）、`temporal/activities.py`、portal

- [ ] Portal 新增反馈问卷 UI：展示问卷问题 + 选项，提交后回调系统
- [ ] `activity_finalize_delivery()` 在 Pulse/Thread 任务完成后调用 `generate_user_feedback_survey` + 推送
- [ ] 用户反馈写入 `playbook.evaluate()`：不满意强制 `outcome=fail`
- [ ] campaign 最终评价写入 Memory unit（source_type=human，摘要格式：任务类型 + 关键策略 + 用户评分 + 主要反馈）

---

## 优先级建议

| 优先级 | 项目 | 原因 |
|---|---|---|
| P0 | 知识来源区分（§12） | 暖机前必须有，否则无法评估系统学到了什么 |
| P0 | 任务规模分级（§16 判定部分） | Campaign 的前提 |
| P1 | Checkpoint 持久化（§16） | 大任务稳定性保障 |
| P1 | Budget 预检（§14） | 防止任务中途因 token 耗尽失败 |
| P1 | Campaign 模式主体（§17） | 核心新功能 |
| P2 | 归档清理制度（§13） | 重要但不影响暖机 |
| P2 | 自适应调度（§15.1） | 已有固定调度可临时替代 |
| P2 | 用户反馈闭环完整实现（§19） | Portal UI 依赖前端工作 |
| P3 | 自我升级闭环（§15.2） | 暖机后才有足够 proposals |
| P3 | Context Window 预检（§16.3） | 先跑起来，遇到问题再补 |
