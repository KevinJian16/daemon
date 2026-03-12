# 诊断测试套件设计文档

> **状态**：草案
> **日期**：2026-03-12
> **文件**：`tests/test_diagnostics.py`
> **定位**：验证机制是否正常工作（管道通不通），不验证效果好不好（输出质量）
> **前置依赖**：后端缺口已补完（wash.py, deed_closed events, running TTL, rework context）

---

## §1 设计原则

### 1.1 核心方法论

来自审计教训（MEMORY.md）：

1. **画完整数据/控制流**：从源头到终点，包括跨系统边界
2. **逐环节验证**：写入端确实写了 → 传输路径通 → 读取端确实读了 → 数据被实际使用
3. **跨系统边界必查**：Python ↔ OpenClaw、Python ↔ Temporal、API process ↔ Worker process
4. **反问**：什么条件下这会失效？

### 1.2 不做什么

- 不测 LLM 输出质量（不可确定性的东西不测）
- 不测外部服务的业务逻辑（Temporal server 内部、OC gateway 内部）
- 不做 load testing 或 performance benchmarks
- 不重复现有 test_services.py / test_spine.py / test_temporal.py 已覆盖的逻辑

### 1.3 与现有测试的关系

| 文件 | 定位 | 关系 |
|------|------|------|
| `test_services.py` | Will/Herald/Cadence 单元逻辑 | 诊断套件不重复，但会补充 end-to-end 链路 |
| `test_spine.py` | Nerve/Trail/Canon/Routines 单元 | 诊断套件增加 Routine→产出→消费 的完整链路 |
| `test_temporal.py` | Workflow DAG 辅助函数 | 诊断套件增加 Activity→外部系统 的连接验证 |
| `test_psyche.py` | PsycheConfig/LedgerStats/InstinctEngine 单元 | 诊断套件增加配置一致性和 token 预算检查 |
| **test_diagnostics.py** | **机制链路验证 + 配置一致性 + 数据完整性** | 本文档 |

### 1.4 运行模式

```bash
# 全量（含跨系统链路，需 Temporal + OC 运行）
pytest tests/test_diagnostics.py -v

# 仅本地检查（不需要外部服务）
pytest tests/test_diagnostics.py -v -k "not CrossSystem"

# 单个类别
pytest tests/test_diagnostics.py -v -k "TestDataModel"

# 单项检查
pytest tests/test_diagnostics.py -v -k "test_deed_status_transitions"
```

### 1.5 标记策略

```python
import pytest

# 需要外部服务的测试
cross_system = pytest.mark.skipif(
    not _service_available(), reason="External services not running"
)

# 需要 OpenClaw 的测试
needs_openclaw = pytest.mark.skipif(
    not _openclaw_available(), reason="OpenClaw not available"
)

# 需要 Temporal 的测试
needs_temporal = pytest.mark.skipif(
    not _temporal_available(), reason="Temporal not available"
)
```

---

## §2 测试类别总览

| # | 类别 | 类名 | 测试项 | 依赖外部 |
|---|------|------|--------|---------|
| 1 | 数据模型一致性 | `TestDataModel` | 58 | 否 |
| 2 | 状态机与生命周期 | `TestLifecycle` | 56 | 否 |
| 3 | 事件链路完整性 | `TestEventChains` | 41 | 否 |
| 4 | Psyche 配置验证 | `TestPsycheConfig` | 25 | 否 |
| 5 | Spine Routines 链路 | `TestSpineChains` | 20 | 否 |
| 6 | API 端点合约 | `TestAPIContracts` | 62 | 否 |
| 7 | 洗信息机制 | `TestWashMechanism` | 20 | 否 |
| 8 | 学习与统计 | `TestLearningStats` | 23 | 否 |
| 9 | 并发与原子性 | `TestConcurrency` | 18 | 否 |
| 10 | 跨系统链路 | `TestCrossSystem` | 30 | **是** |
| 11 | 安全与防御 | `TestSecurity` | 26 | 否 |
| 12 | 配置文件一致性 | `TestConfigConsistency` | 23 | 否 |
| 13 | FolioWrit 注册表 | `TestFolioWritRegistry` | 56 | 否 |
| 14 | Will 提交管线 | `TestWillPipeline` | 33 | 否 |
| 15 | Cron 与调度 | `TestCronScheduling` | 25 | 否 |
| 16 | Herald 归档管线 | `TestHeraldPipeline` | 15 | 否 |
| 17 | Runtime 组件 | `TestRuntimeComponents` | 36 | 否 |
| 18 | Ledger 状态存储 | `TestLedgerStore` | 32 | 否 |
| 19 | Voice 对话管线 | `TestVoiceService` | 37 | 否 |
| 20 | Cadence 调度引擎 | `TestCadenceEngine` | 34 | 否 |
| 21 | Temporal Workflow | `TestTemporalWorkflow` | 30 | 否 |
| 22 | Temporal Activities | `TestTemporalActivities` | 27 | 否 |
| 23 | Pact 契约验证 | `TestPactValidation` | 14 | 否 |
| 24 | 启动与初始化 | `TestBootstrapStartup` | 21 | 否 |
| 25 | Telegram 通知 | `TestTelegramAdapter` | 13 | 否 |
| 26 | 设计验证器 | `TestDesignValidator` | 15 | 否 |
| | **合计** | | **790** | |

> 每个检查项对应 1 个 test function。部分检查项在实现时会衍生边界 case，
> 预计最终 test function 数量 850-950。

---

## §3 TestDataModel — 数据模型一致性

验证所有数据结构的 schema 约束、必填字段、字段类型。

### 3.1 Deed 数据模型

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| DM-01 | Deed 必填字段完整 | 创建 deed → 检查 deed_id, deed_status, created_utc, slip_id 存在且非空 |
| DM-02 | deed_id 格式正确 | `deed_{YYYYMMDDHHMMSS}_{hex6}` 正则匹配 |
| DM-03 | deed_status 只能是合法值 | 创建后只能是 `running`/`settling`/`closed` 之一 |
| DM-04 | deed_sub_status 只能是合法值 | 只允许 `succeeded`/`failed`/`timed_out`/`cancelled`/`""` |
| DM-05 | 时间戳格式 ISO 8601 | created_utc, updated_utc 匹配 `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$` |
| DM-06 | deed 引用的 slip_id 存在 | 遍历所有 deed，检查 slip_id 在 slips.json 中 |
| DM-07 | deed plan 结构合法 | plan 必须包含 moves（list）且每个 move 有 id 字段 |

### 3.2 Slip 数据模型

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| DM-10 | Slip 必填字段完整 | slip_id, title, status, created_utc 存在且非空 |
| DM-11 | slip_id 格式正确 | `slip_{hex12}` 正则匹配 |
| DM-12 | Slip status 只能是合法值 | `active`/`archived`/`deleted` 之一 |
| DM-13 | Slip.deed_ids 引用存在 | deed_ids 中每个 ID 都在 deeds.json 中 |
| DM-14 | Slip.folio_id 如非空则引用存在 | folio_id 在 folios.json 中 |
| DM-15 | standing Slip 有合法触发类型 | standing=true → trigger_type 为 manual/timed/event 之一 |
| DM-16 | Slip slug 唯一性 | 所有 active Slip 的 slug 不重复 |

### 3.3 Folio 数据模型

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| DM-20 | Folio 必填字段完整 | folio_id, title, status, created_utc 存在 |
| DM-21 | Folio.slip_ids 引用存在 | 每个 slip_id 在 slips.json 中 |
| DM-22 | Folio.writ_ids 引用存在 | 每个 writ_id 在 writs.json 中 |
| DM-23 | Folio slug 唯一性 | 所有 active Folio 的 slug 不重复 |

### 3.4 Writ 数据模型

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| DM-30 | Writ 必填字段完整 | writ_id, folio_id, action 存在 |
| DM-31 | Writ.folio_id 引用存在 | folio_id 在 folios.json 中 |
| DM-32 | Writ.action.type 合法 | 只允许 `spawn_deed` |
| DM-33 | Writ.action.slip_id 引用存在 | slip_id 在 slips.json 中 |
| DM-34 | Writ trigger 类型排他 | match 中 schedule/event/manual 只有一种 |

### 3.5 Draft 数据模型

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| DM-40 | Draft 必填字段完整 | draft_id, status, source, created_utc, updated_utc 存在 |
| DM-41 | Draft status 合法 | `drafting`/`gone` 之一 |
| DM-42 | Draft sub_status 合法 | open/refining/crystallized/superseded/abandoned 之一 |
| DM-43 | Draft.folio_id 如非空则引用存在 | folio_id 在 folios.json 中 |
| DM-44 | Draft candidate_brief 是 dict | isinstance(candidate_brief, dict) |
| DM-45 | Draft candidate_design 是 dict | isinstance(candidate_design, dict) |

### 3.6 Slug 系统

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| DM-46 | Slip slug 由标题生成 | create_slip(title="测试") → slug 包含 "测试" |
| DM-47 | 同名 slug 自动去重 | 创建两个同标题 Slip → slug 不同 |
| DM-48 | slug_history 记录旧 slug | 改标题 → 旧 slug 在 slug_history 中 |
| DM-49 | 通过旧 slug 仍可查找 | 改标题后 → get_slip_by_slug(旧slug) 仍返回该 Slip |
| DM-49b | Folio slug 同理 | 同上逻辑适用于 Folio |

### 3.7 双向引用一致性

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| DM-50 | Slip↔Folio 双向 | Slip.folio_id 指向 Folio → 该 Folio.slip_ids 包含该 Slip |
| DM-51 | Slip↔Deed 双向 | Slip.deed_ids 中的每个 deed → 该 deed.slip_id 指回该 Slip |
| DM-52 | Writ↔Folio 双向 | Writ.folio_id 指向 Folio → 该 Folio.writ_ids 包含该 Writ |
| DM-53 | Writ→Slip 一致 | Writ.action.slip_id 指向的 Slip 属于同一个 Folio |
| DM-54 | latest_deed_id 与 deed_ids 一致 | Slip.latest_deed_id 在 Slip.deed_ids 中 |
| DM-55 | Draft crystallize 后 gone | crystallize_draft → draft status=gone, sub_status=crystallized |
| DM-56 | Writ version 递增 | 更新 canonical 字段 → version +1 |
| DM-57 | Writ.deed_history 引用存在 | deed_history 中每个 deed_id 在 deeds.json 中 |

### 3.8 Move 数据模型

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| DM-60 | Move 必填字段 | id, agent 存在且非空 |
| DM-61 | Move.id 唯一 | plan.moves 中 id 不重复 |
| DM-62 | Move.agent 合法 | 在 VALID_AGENTS 中 |
| DM-63 | Move.depends_on 引用存在 | 每个依赖 id 在 moves 中 |
| DM-64 | Move checkpoint 结构 | status (ok/degraded/pending), output_path, token_usage |
| DM-65 | Move output 目录结构 | moves/{move_id}/output/ 存在 |

### 3.9 Plan 结构

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| DM-70 | Plan 必填字段 | deed_id, moves, brief 存在 |
| DM-71 | Plan.brief 是 dict | isinstance(brief, dict) |
| DM-72 | Plan.metadata 可选 | metadata 缺失不报错 |
| DM-73 | Plan.concurrency 正整数 | concurrency > 0 |
| DM-74 | Plan.agent_model_map 合法 | 每个 agent 在 VALID_AGENTS 中 |
| DM-75 | Plan.eval_window_hours 正数 | > 0 |

### 3.10 Deed Root 目录结构

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| DM-80 | deed_root 存在 | 提交后 state/deeds/{deed_id}/ 存在 |
| DM-81 | deed_root/plan.json 存在 | 包含完整 plan |
| DM-82 | deed_root/moves/ 存在 | 目录已创建 |
| DM-83 | deed_root/messages.jsonl 可追加 | append 后可 load |

---

## §4 TestLifecycle — 状态机与生命周期

验证所有实体的状态转换路径是否正确。

### 4.1 Deed 生命周期

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LC-01 | running → settling 合法 | 创建 running deed → mutate 到 settling → 成功 |
| LC-02 | running → closed 合法 | 创建 running deed → mutate 到 closed → 成功 |
| LC-03 | settling → closed 合法 | 创建 settling deed → mutate 到 closed → 成功 |
| LC-04 | closed → running 非法 | closed deed 不能回到 running（验证拒绝或无效） |
| LC-05 | closed → settling 非法 | closed deed 不能回到 settling |
| LC-06 | 执行创建原子性 | 提交 plan → deed 出现在 deeds.json 且 status=running |
| LC-07 | 收束写入完整 | settle → deed_status=closed, deed_sub_status=succeeded, settled_utc 存在 |
| LC-08 | 超时关闭写入完整 | TTL 过期 → deed_status=closed, deed_sub_status=timed_out |
| LC-09 | phase 字段同步 | running deed → phase="active", closed deed → phase="history" |

### 4.2 Deed Running TTL

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LC-10 | 默认 TTL 4 小时 | 创建 4h+1s 前的 running deed → tick_running_ttl → deed closed |
| LC-11 | 未过期不关闭 | 创建 1h 前的 running deed → tick_running_ttl → deed 仍 running |
| LC-12 | TTL 可配置 | preferences 设置 deed_running_ttl_s=7200 → 用 2h 判定 |
| LC-13 | 关闭后发 deed_closed event | TTL 过期 → nerve 收到 deed_closed + sub_status=timed_out |

### 4.3 Deed Eval Window

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LC-20 | 默认 eval window 48h | settling deed 48h 过期 → tick_eval_windows → deed closed |
| LC-21 | 未过期不关闭 | settling deed 24h → tick_eval_windows → deed 仍 settling |
| LC-22 | 关闭后发 deed_closed event | eval 过期 → nerve 收到 deed_closed + sub_status=timed_out |

### 4.4 Slip 生命周期

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LC-30 | 创建 → active | create_slip → status=active, sub_status=normal |
| LC-31 | active → archived | update_slip_status("archived") → 成功 |
| LC-32 | active → deleted | update_slip_status("deleted") → 成功 |
| LC-33 | trigger_type 合法枚举 | 只允许 manual/timer/writ_chain |
| LC-34 | Writ 创建同步 trigger_type | create_writ(schedule) → Slip trigger_type 变为 timer |
| LC-35 | Writ 创建同步 trigger_type (event) | create_writ(event=deed_closed) → Slip trigger_type 变为 writ_chain |
| LC-36 | 无效 status 更新被拒绝 | update_slip(status="bogus") → status 不变 |
| LC-37 | 无效 sub_status 更新被拒绝 | update_slip(sub_status="bogus") → sub_status 不变 |

### 4.5 Folio 生命周期

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LC-40 | 创建 → active | create_folio → status=active, sub_status=normal |
| LC-41 | active → archived | update_folio(status="archived") → 成功 |
| LC-42 | delete_folio 级联效果 | delete → 关联 Slip.folio_id 清空, 关联 Writ disabled |
| LC-43 | 无效 status 更新被拒绝 | update_folio(status="bogus") → status 不变 |

### 4.6 Draft 生命周期

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LC-50 | 创建 → drafting + open | create_draft → status=drafting, sub_status=open |
| LC-51 | crystallize → gone + crystallized | crystallize_draft → status=gone, sub_status=crystallized |
| LC-52 | crystallize 生成 Slip | crystallize → 返回值含 slip_id，Slip 存在 |
| LC-53 | crystallize 不存在的 draft → ValueError | draft_id="nonexistent" → raise ValueError |
| LC-54 | 更新 draft 字段 | update_draft(intent_snapshot=...) → 保存成功 |
| LC-55 | 无效 draft status 更新被拒绝 | update_draft(status="bogus") → status 不变 |

### 4.7 Writ 生命周期

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LC-60 | 创建 → active | create_writ → status=active |
| LC-61 | active → paused | update_writ(status="paused") → 成功 |
| LC-62 | active → disabled | update_writ(status="disabled") → 成功 |
| LC-63 | 删除 Writ 解除 Folio 关联 | delete_writ → Folio.writ_ids 不再包含该 writ_id |
| LC-64 | canonical 字段更新 version 递增 | update_writ(title="新") → version +1 |
| LC-65 | 非 canonical 字段不递增 version | update_writ(deed_history=[...]) → version 不变 |
| LC-66 | record_writ_triggered 更新历史 | record → deed_history 增加, last_triggered_utc 更新 |

### 4.8 系统状态生命周期

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LC-70 | 默认系统状态 = running | 无 status 文件 → "running" |
| LC-71 | running → paused 合法 | 写入 paused → 读回 paused |
| LC-72 | paused → running 合法 | 恢复运行 |
| LC-73 | system shutdown 状态 | shutdown → Will.submit 拒绝 |

### 4.9 Ward 状态转换

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LC-80 | GREEN → YELLOW 合法 | pulse 检测降级 → ward 变 YELLOW |
| LC-81 | YELLOW → RED 合法 | 进一步降级 → RED |
| LC-82 | RED → GREEN 合法 | 恢复 → GREEN |
| LC-83 | 连续 3 次失败 → 自动诊断 | pulse 记录 3+ 失败 → auto_diagnosis=True |

### 4.10 Deed Sub-Status 转换

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LC-90 | queued → executing | dequeue 后 sub_status 变化 |
| LC-91 | executing → succeeded | 正常完成 |
| LC-92 | executing → failed | 执行异常 |
| LC-93 | executing → cancelled | 取消信号 |
| LC-94 | executing → timed_out | TTL 过期 |
| LC-95 | reviewing → succeeded | arbiter accept |
| LC-96 | reviewing → retrying | arbiter reject + rework |

---

## §5 TestEventChains — 事件链路完整性

验证 Nerve 事件从发射到消费的完整路径。

### 5.1 deed_closed 事件链

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| EC-01 | 收束触发 deed_closed | portal settle → nerve.emit("deed_closed") 被调用 |
| EC-02 | 反馈关闭触发 deed_closed | feedback → _close_eval → nerve.emit("deed_closed") |
| EC-03 | eval 超时触发 deed_closed | cadence tick → deed closed → nerve.emit("deed_closed") |
| EC-04 | running TTL 触发 deed_closed | cadence tick → TTL expired → nerve.emit("deed_closed") |
| EC-05 | deed_closed → spine.record 触发 | emit deed_closed → canon.by_trigger("deed_closed") 包含 spine.record |
| EC-06 | deed_closed → Writ chain 触发 | emit deed_closed → folio_writ handlers 被调用 |
| EC-07 | deed_closed payload 完整 | payload 包含 deed_id, sub_status, source |

### 5.2 Writ trigger chain

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| EC-10 | deed_closed → writ_trigger_ready | deed_closed → folio_writ._on_trigger_fired → 匹配的 Writ emit writ_trigger_ready |
| EC-11 | 前序未满足不触发 | Writ 依赖 A 和 B，只完成 A → 不 emit writ_trigger_ready |
| EC-12 | 前序全满足才触发 | Writ 依赖 A 和 B，A 和 B 都 closed → emit writ_trigger_ready |
| EC-13 | writ_trigger_ready → deed 创建 | emit writ_trigger_ready → _consume_writ_trigger 被调用 |

### 5.3 herald_completed 事件

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| EC-20 | Herald deliver 成功 → herald_completed | deliver 返回 ok=True → nerve 有 herald_completed |
| EC-21 | herald_completed → spine.record 触发 | canon.by_trigger("herald_completed") 包含 spine.record |

### 5.4 ward_changed 事件

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| EC-30 | pulse 检测变化 → ward_changed | ward GREEN→YELLOW → nerve 有 ward_changed |
| EC-31 | ward_changed → spine.tend 触发 | canon.by_trigger("ward_changed") 包含 spine.tend |

### 5.5 FolioWrit 注册事件

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| EC-50 | create_folio → folio_created | nerve 收到 folio_created + folio_id |
| EC-51 | create_slip → slip_created | nerve 收到 slip_created + slip_id + folio_id |
| EC-52 | create_writ → writ_created | nerve 收到 writ_created + writ_id + folio_id |
| EC-53 | create_draft → draft_created | nerve 收到 draft_created + draft_id |
| EC-54 | crystallize → draft_crystallized | nerve 收到 draft_crystallized + draft_id + slip_id |
| EC-55 | duplicate_slip → slip_duplicated | nerve 收到 slip_duplicated + source + target |
| EC-56 | delete_folio → folio_deleted | nerve 收到 folio_deleted + folio_id |
| EC-57 | delete_writ → writ_deleted | nerve 收到 writ_deleted + writ_id |
| EC-58 | deed_submitted → deed_submitted | Will submit 成功 → nerve 有 deed_submitted |

### 5.6 Nerve 基础设施

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| EC-60 | handler 异常不阻塞 emit | 注册 throwing handler → emit 不抛异常，handler_errors 记录 |
| EC-61 | 事件持久化到 events.jsonl | emit → events.jsonl 多一行，内容可 JSON parse |
| EC-62 | replay_unconsumed 正确重播 | 写入 unconsumed event → replay → handler 被调用 |
| EC-63 | history size 限制生效 | history_size=5 → emit 10 次 → recent(100) 只返回 5 条 |
| EC-64 | emit 返回 event_id | event_id 以 "ev_" 开头 |
| EC-65 | event record 结构完整 | 包含 event_id, event, payload, timestamp, consumed_utc, handler_errors |
| EC-66 | 多个 handler 都被调用 | 同一事件注册 3 个 handler → 全部被调用 |
| EC-67 | event_count 按类型统计 | emit a×2, b×3 → event_count == {a:2, b:3} |

### 5.7 Ether 跨进程事件

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| EC-70 | deed_progress event | Worker emit deed_progress → ether events.jsonl 有记录 |
| EC-71 | deed_settling event | finalize → ether 有 deed_settling |
| EC-72 | deed_failed event | 执行失败 → ether 有 deed_failed |
| EC-73 | routine_completed event | spine routine 完成 → nerve 有 routine_completed |
| EC-74 | ward_changed payload 完整 | 包含 old_status, new_status, checked_utc |

### 5.8 事件顺序与因果

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| EC-80 | deed_submitted 先于 deed_settling | 同 deed → submitted.timestamp < settling.timestamp |
| EC-81 | deed_settling 先于 deed_closed | settling.timestamp < closed.timestamp |
| EC-82 | herald_completed 在 deed_settling 之后 | herald.timestamp ≥ settling.timestamp |
| EC-83 | writ_trigger_ready 在 deed_closed 之后 | trigger.timestamp > closed.timestamp |

---

## §6 TestPsycheConfig — Psyche 配置验证

### 6.1 文件存在性与格式

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| PC-01 | instinct.md 存在且非空 | Path.exists() + len > 100 |
| PC-02 | voice/identity.md 存在 | Path.exists() |
| PC-03 | voice/common.md 存在 | Path.exists() |
| PC-04 | preferences.toml 可解析 | tomllib.loads() 不报错 |
| PC-05 | rations.toml 可解析 | tomllib.loads() 不报错 |
| PC-06 | PsycheConfig 可实例化 | PsycheConfig(path) 不抛异常 |
| PC-07 | InstinctEngine 可实例化 | InstinctEngine(path) 不抛异常 |

### 6.2 Token 预算

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| PC-10 | Instinct prompt ≤ 400 tokens | len(fragment) / 4 ≤ 400 |
| PC-11 | Identity ≤ 150 tokens | 读 identity.md, len / 4 ≤ 150 |
| PC-12 | Style (common+zh) ≤ 250 tokens | 读文件, 合计 len / 4 ≤ 250 |
| PC-13 | Style (common+en) ≤ 250 tokens | 同上 |
| PC-14 | Overlay ≤ 50 tokens each | 遍历 overlays/*.md |
| PC-15 | 总注入 ≤ 600 tokens (scribe) | instinct + identity + style + overlay |

### 6.3 PsycheConfig 读写

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| PC-20 | get_pref 返回正确值 | set_pref("k", "v") → get_pref("k") == "v" |
| PC-21 | all_prefs 返回所有键 | 设置多个 → all_prefs() 全包含 |
| PC-22 | consume_ration 扣减正确 | 设置限额 → consume → 剩余正确 |
| PC-23 | consume_ration 超额拒绝 | 消耗超过限额 → 返回 False |
| PC-24 | reset_rations 清零 | consume → reset → current_usage 归零 |
| PC-25 | snapshot 格式正确 | snapshot() 返回 dict，包含 preferences 和 rations |

### 6.4 InstinctEngine 硬规则

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| PC-30 | 敏感词过滤生效 | check_outbound_query(含敏感词) → 被替换 |
| PC-31 | 空输出被拦截 | check_output("", "research") → ["empty_output"] |
| PC-32 | 敏感词泄漏被检测 | check_output(含敏感词) → 返回 violation |
| PC-33 | Voice token 超限被拒绝 | check_voice_update("identity", 巨长内容) → violation |
| PC-34 | 正常内容通过 | check_output(正常文本, "code") → [] |
| PC-35 | wash output 过长 candidate 被过滤 | check_wash_output({voice_candidates: [{content: 超600字}]}) → 被过滤 |

---

## §7 TestSpineChains — Spine Routines 链路

不只测"能跑"，测"产出被消费"。

### 7.1 spine.pulse 链路

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SC-01 | pulse 写入 ward.json | 执行 pulse → ward.json 存在且可解析 |
| SC-02 | ward.json 包含必填字段 | status (GREEN/YELLOW/RED), checked_utc, checks |
| SC-03 | ward 状态变化 → ward_changed event | 连续两次 pulse 且状态变化 → nerve 有 ward_changed |

### 7.2 spine.record 链路

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SC-10 | record 合并 dag_templates | 传入 accepted deed → dag_templates 表 times_validated ≥ 1 |
| SC-11 | record 更新 skill_stats | 传入含 skill 的 plan → skill_stats 表有记录 |
| SC-12 | record 更新 agent_stats | 传入 move_results → agent_stats 表有记录 |
| SC-13 | record 不记录 rejected deed | accepted=False → dag_templates 不变 |
| SC-14 | record 滚动平均正确 | 合并两次 → avg_tokens 是两次平均值 |

### 7.3 spine.witness 链路

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SC-20 | witness 写入 system_health | 执行 → system_health.json 存在 |
| SC-21 | witness 读 ledger 统计 | witness 返回结果包含 deed 统计信息 |

### 7.4 spine.relay 链路

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SC-30 | relay 导出快照 | 执行 → state/snapshots/ 有文件 |
| SC-31 | 快照包含 planning hints | 快照文件包含 dag_template_count 等字段 |

### 7.5 spine.tend 链路

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SC-40 | tend 清理 traces | 创建旧 trace 文件 → tend → 文件被清理 |
| SC-41 | tend 检查 rations | tend 返回 rations_checked=True |

### 7.6 spine.curate 链路

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SC-50 | curate 清理旧 deed | 创建 90 天前 closed deed → curate → 被清理 |
| SC-51 | curate 不清理 active deed | 创建 active deed → curate → 仍在 |

### 7.7 Registry 一致性

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SC-60 | registry 所有 routine 有实现 | spine_registry.json 每个 name → SpineRoutines 有对应方法 |
| SC-61 | registry 无多余 routine | SpineRoutines 方法名都在 registry 中 |
| SC-62 | trigger 映射正确 | by_trigger("deed_closed") 返回 spine.record |
| SC-63 | 所有 routine 模式为 deterministic | 没有 hybrid 模式 |

---

## §8 TestAPIContracts — API 端点合约

验证 API 端点的输入输出合约（不启动 HTTP server，直接调用 FastAPI TestClient）。

### 8.1 Portal Shell 端点

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-01 | GET /portal-api/desk 返回结构正确 | 有 folios, slips, deeds, drafts 字段 |
| AC-02 | GET /portal-api/slips/{slug} 返回正确 | 有 slip_id, title, status, dag, deeds, cadence |
| AC-03 | dag 结构正确 | dag 包含 nodes(list) + edges(list) |
| AC-04 | dag.nodes 每项有 id, label, agent, status | 字段类型检查 |
| AC-05 | cadence 包含 next_trigger_utc | 定时 Slip 的 cadence 有 next_trigger_utc |
| AC-06 | POST /portal-api/slips/{slug}/message 成功 | 返回 {ok: true, slip_id} |
| AC-07 | POST /portal-api/slips/{slug}/message 空文本拒绝 | 返回 400 |
| AC-08 | GET /portal-api/slips/{slug}/messages 返回列表 | 每条有 role, content, created_utc |
| AC-09 | messages 跨 deed 合并 | 多个 deed 的消息按时间排序返回 |
| AC-10 | POST /portal-api/slips/{slug}/stance settle 成功 | 返回 {ok: true, settled: true} |
| AC-11 | POST /portal-api/slips/{slug}/stance settle 无 deed 报 409 | 无 active deed → 409 |
| AC-12 | POST /portal-api/slips/{slug}/stance settle closed deed 报 409 | deed 已 closed → 409 |
| AC-13 | POST /portal-api/slips/{slug}/stance park 成功 | 返回 {ok: true, parked: true} |
| AC-14 | POST /portal-api/slips/{slug}/execute 触发执行 | 返回含 deed_id |
| AC-15 | 不存在的 slug → 404 | 所有端点对不存在 slug 返回 404 |

### 8.2 Folio-Writ 端点

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-20 | GET /portal-api/folios 返回列表 | 每项有 id, title, slips |
| AC-21 | GET /portal-api/folios/{slug} 返回正确 | 有 folio_id, title, slips, writs |
| AC-22 | GET /portal-api/slips/{slug}/writ-neighbors 返回正确 | 有 writs 列表，每条有 source_slip_id, target_slip_id, latest_deed_status |
| AC-23 | POST /drafts/{draft_id}/crystallize 缺 title 报 400 | 400 |
| AC-24 | POST /drafts/{draft_id}/crystallize 缺 objective 报 400 | 400 |
| AC-25 | POST /drafts/{draft_id}/crystallize 成功 | 返回含 slip_id |

### 8.3 Basic 端点

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-30 | GET /health 返回 200 | status_code == 200 |
| AC-31 | POST /deeds/{deed_id}/message 记录消息 | 消息出现在 deed messages 中 |
| AC-32 | POST /deeds/{deed_id}/message 不暂停执行 | running deed 收到消息后仍然 running |
| AC-33 | POST /deeds/{deed_id}/append 记录操作 | 调用 _record_operation |
| AC-34 | GET /offerings/{deed_id} 返回文件 | 有 offering → 返回文件 |
| AC-35 | GET /offerings/{deed_id}/files 返回列表 | 列表每项有 name, size |

### 8.4 Console 端点

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-40 | GET /console/runtime/status 返回结构 | 有 temporal_connected, deeds_active 等 |
| AC-41 | POST /console/spine/{routine_name}/trigger 可触发 | 返回 routine 执行结果 |
| AC-42 | GET /console/psyche/preferences 返回 dict | 可解析的偏好对象 |
| AC-43 | PUT /console/psyche/preferences 可更新 | 更新后 GET 返回新值 |

### 8.5 静态路由

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-50 | GET /portal/ 返回 HTML | content-type 包含 text/html |
| AC-51 | GET /portal/slips/{slug} 返回 HTML (SPA) | 同上 |
| AC-52 | GET /portal/slips/{slug}/deeds/{deed_id} 返回 HTML | Deed deep link 路由存在 |
| AC-53 | GET /portal/folios/{slug} 返回 HTML | 同上 |

### 8.6 操作→自然语言记录

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-60 | settle 生成 NL 记录 | settle → messages 中有 event=operation 的条目 |
| AC-61 | execute 生成 NL 记录 | execute → messages 中有 event=operation |
| AC-62 | append 生成 NL 记录 | append → messages 中有 event=operation |
| AC-63 | 操作记录内容可读 | operation 的 content 是人类可读的中文描述 |

### 8.7 Chat 端点

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-70 | POST /chat/voice 新会话 | 返回 session_id + assistant reply |
| AC-71 | POST /chat/voice/{session_id} 继续 | 同 session_id → 消息追加 |
| AC-72 | POST /chat/voice/{session_id} 过期 → 404 | session TTL 过期 → 404 |
| AC-73 | POST /chat/voice 空消息 → 400 | message="" → 400 |

### 8.8 Submit 端点

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-80 | POST /submit 合法 plan → deed_id | 返回 deed_id, slip_id |
| AC-81 | POST /submit 无 moves → 400 | 缺 moves → 400 |
| AC-82 | POST /submit 循环依赖 → 400 | A→B→A → 400 |
| AC-83 | POST /submit 空 body → 422 | {} → 422 |

### 8.9 Feedback 端点

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-90 | POST /feedback/evaluate settle | deed settling → ok |
| AC-91 | POST /feedback/evaluate rework | → 触发 rework |
| AC-92 | POST /feedback/evaluate 无 active deed → 409 | → 409 |
| AC-93 | POST /feedback/message 记录用户反馈 | → messages 增加 |

### 8.10 Console Spine 端点

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-100 | GET /console/spine/status 返回列表 | 7 项，每项有 name, schedule, next_run_utc |
| AC-101 | GET /console/spine/{name}/history 返回列表 | 每项有 started_utc, status, duration_ms |
| AC-102 | PUT /console/spine/{name}/schedule 更新 | 更新后 status 反映新 schedule |
| AC-103 | POST /console/spine/{name}/trigger 手动触发 | 返回执行结果 |

### 8.11 Console Psyche 端点

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-110 | GET /console/psyche/rations 返回配额 | 有 daily_limits, current_usage |
| AC-111 | POST /console/psyche/rations/reset 清零 | reset 后 current_usage 全 0 |
| AC-112 | GET /console/psyche/instinct 返回规则 | 有 sensitive_terms_count, token_limits |

### 8.12 Console Observe 端点

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| AC-120 | GET /console/observe/deeds 返回列表 | 每项有 deed_id, status, slip_id |
| AC-121 | GET /console/observe/deeds?status=running 过滤 | 只返回 running |
| AC-122 | GET /console/observe/deeds/{deed_id} 详情 | 有 plan, moves, messages |
| AC-123 | GET /console/observe/activity 最近活动 | 返回时间排序的活动列表 |

---

## §9 TestWashMechanism — 洗信息机制

### 9.1 基本功能

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| WM-01 | 无前序 deed → 不洗 | previous_deed_ids=[] → washed=False, reason=no_previous_deeds |
| WM-02 | 有前序但无消息 → 不洗 | load_messages_fn 返回 [] → washed=False, reason=no_messages |
| WM-03 | 正常洗 → 返回完整结果 | 有消息 → washed=True + brief_supplement + stats + voice_candidates |
| WM-04 | brief_supplement 非空 | 有 user_messages → brief_supplement 包含内容 |
| WM-05 | brief_supplement 限制长度 | 巨长消息 → brief_supplement ≤ 1200+20 字符 |

### 9.2 统计提取

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| WM-10 | message_count 正确 | 传入 5 条 → stats.message_count == 5 |
| WM-11 | user_message_count 正确 | 3 条 user + 2 条 system → user_message_count == 3 |
| WM-12 | operation_count 正确 | 2 条 event=operation → operation_count == 2 |
| WM-13 | 时间范围正确 | first_message_utc ≤ last_message_utc |

### 9.3 Voice 候选提取

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| WM-20 | 风格关键词匹配 | 消息含"简洁" → voice_candidates 有 formality_preference |
| WM-21 | 否定偏好匹配 | 消息含"不要太正式" → voice_candidates 有 negative_preference |
| WM-22 | 每条消息最多一个候选 | 一条消息同时匹配多个 → 只取第一个 |
| WM-23 | 最多 5 个候选 | 10 条匹配消息 → voice_candidates 长度 ≤ 5 |
| WM-24 | 候选 confirmed=False | 所有候选初始 confirmed=False |

### 9.4 持久化与加载

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| WM-30 | wash 结果写入文件 | wash → state/wash/{deed_id}.json 存在 |
| WM-31 | 文件内容可解析 | JSON.loads 不报错 |
| WM-32 | load_wash_supplement 读取正确 | wash → load_wash_supplement(deed_id) 返回 brief_supplement 内容 |
| WM-33 | 不存在的 deed → 空字符串 | load_wash_supplement("nonexistent") == "" |

### 9.5 Will 集成

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| WM-40 | 新 deed 提交时触发洗 | submit plan for slip with previous deed → wash 被调用 |
| WM-41 | wash supplement 注入 brief | wash 产出 → brief.context_supplement 包含内容 |

---

## §10 TestLearningStats — 学习与统计

### 10.1 DAG 模板

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LS-01 | 首次合并创建模板 | merge_dag_template → template_id 非空 |
| LS-02 | 相似目标合并而非新建 | 两个相似 embedding → 同一个 template_id |
| LS-03 | 不相似目标新建 | 两个不同 embedding → 不同 template_id |
| LS-04 | times_validated 递增 | 合并两次 → times_validated == 2 |
| LS-05 | 滚动平均正确 | 第一次 1000 tokens, 第二次 2000 → avg = 1500 |
| LS-06 | eval_summary 追加 | 第一次 "good", 第二次 "great" → 包含两段 |
| LS-07 | eval_summary 不超 2000 字符 | 累积超长 → 截断 |
| LS-08 | similar_dag_templates 返回 top_k | 3 个模板 → top_k=2 → 返回 2 个 |
| LS-09 | similar_dag_templates 相似度排序 | 最相似的在前 |

### 10.2 Folio 模板

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LS-10 | 首次合并创建模板 | merge_folio_template → template_id 非空 |
| LS-11 | 相似目标合并 | 两个相似 → 同一个 template_id, times_validated=2 |
| LS-12 | similar_folio_templates 查询正确 | 有模板 → 查询返回非空 |

### 10.3 Skill 统计

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LS-20 | accepted 递增 | update_skill_stats(accepted=True) → accepted 增 1 |
| LS-21 | rejected 递增 | update_skill_stats(accepted=False) → rejected 增 1 |
| LS-22 | skill_health 返回正确 | 查询已有 skill → invocations, accept_rate 正确 |
| LS-23 | needs_review 触发条件 | invocations≥5, reject>20% → needs_review=True |
| LS-24 | skills_needing_review 聚合 | 有需审查 skill → 列表非空 |

### 10.4 Agent 统计

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LS-30 | agent_stats 写入正确 | update_agent_stats → 查询返回记录 |
| LS-31 | agent_performance 聚合 | 多次更新 → success_rate 正确 |
| LS-32 | agent_summary 返回所有角色 | 多角色更新 → summary 包含所有 |

### 10.5 Planning 查询

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LS-40 | planning_hints 冷启动 | 无历史 → est_tokens=0, confidence=0 |
| LS-41 | planning_hints 有历史 | 有相似 DAG → est_tokens>0, confidence>0 |
| LS-42 | global_planning_hints 统计 | 有模板 → dag_template_count > 0 |

---

## §11 TestConcurrency — 并发与原子性

### 11.1 Ledger 原子性

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CC-01 | 并发 mutate_deeds 不丢数据 | 10 线程同时 mutate → 所有修改都生效 |
| CC-02 | 并发 upsert_deed 不丢数据 | 10 线程同时 upsert 不同 deed → 全部存在 |
| CC-03 | 并发读写不报错 | 读线程 + 写线程同时运行 → 无异常 |
| CC-04 | .tmp 文件不残留 | 并发写入后 → 无 *.tmp* 文件 |

### 11.2 LedgerStats 并发

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CC-10 | 并发 merge_dag_template | 多线程合并 → 数据一致（WAL mode） |
| CC-11 | 并发 update_skill_stats | 多线程更新 → invocations 计数正确 |

### 11.3 Nerve 并发

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CC-20 | 并发 emit 不丢事件 | 10 线程各 emit 10 次 → event_count 总和 100 |
| CC-21 | 并发 emit + handler 不死锁 | handler 内部再 emit → 不死锁（30s 超时） |

### 11.4 Retinue 原子性

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CC-30 | 并发 allocate 不重复分配 | 多线程请求同一角色 → 不同实例 |
| CC-31 | release 后可重新分配 | allocate → release → allocate → 成功 |

### 11.5 FolioWrit 并发

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CC-40 | 并发 create_slip 不丢 | 10 线程各创建 1 → 10 个 Slip 存在 |
| CC-41 | 并发 update_slip 不冲突 | 同 Slip 10 线程更新不同字段 → 全生效 |
| CC-42 | 并发 crystallize 不重复 | 同 draft 并发 crystallize → 只创建 1 个 Slip |

### 11.6 Ether 并发

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CC-50 | 并发 emit 不丢事件 | 10 线程各 emit → events.jsonl 行数正确 |
| CC-51 | 并发 consume 不重复 | 2 consumer 同时 consume → 各自 cursor 独立 |
| CC-52 | emit + consume 并发安全 | writer + reader 并发 → 无异常 |

### 11.7 PsycheConfig 并发

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CC-60 | 并发 set_pref 不丢 | 10 线程设不同 key → 全存在 |
| CC-61 | 并发 consume_ration 不超额 | 限额 100, 10 线程各消耗 10 → 恰好 100 |

---

## §12 TestCrossSystem — 跨系统链路

**需要 Temporal server 和/或 OpenClaw gateway 运行。** 全部标记 `@cross_system`。

### 12.1 Python → Temporal

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| XS-01 | TemporalClient 可连接 | connect() 不抛异常 |
| XS-02 | Workflow 可提交 | start_workflow 返回 workflow_id |
| XS-03 | Workflow 可查询状态 | describe_workflow 返回 status |
| XS-04 | Signal 可发送 | signal_workflow 不抛异常 |
| XS-05 | 所有 activity 已注册 | Worker 启动后 activity 列表包含所有 DaemonActivities 方法 |

### 12.2 Python → OpenClaw

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| XS-10 | OC gateway 可达 | HTTP GET /health 返回 200 |
| XS-11 | Session 可创建 | sessions_new 返回 session_id |
| XS-12 | Session 可发送消息 | sessions_send 返回 response |
| XS-13 | Session 可销毁 | sessions_destroy 不抛异常 |
| XS-14 | Agent workspace 存在 | 7 个角色的 workspace 目录都存在 |

### 12.3 Python → MCP

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| XS-20 | MCP config 可解析 | mcp_servers.json loads 成功 |
| XS-21 | MCPDispatcher 可实例化 | 构造不抛异常 |
| XS-22 | MCP server 可连接 (如有配置) | discover_all → 至少 0 个 server |
| XS-23 | MCP tool 可调用 (如有配置) | call_tool 返回结果 |

### 12.4 Ether 跨进程通信

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| XS-30 | Ether emit → consume 链路 | API 进程 emit → Worker 进程 consume → handler 被调用 |
| XS-31 | cursor 正确追踪 | consume 后 cursor 前进 |
| XS-32 | ack 正确标记 | ack 后 pending 减少 |
| XS-33 | 重启后 cursor 恢复 | 重建 Ether → cursor 从持久化恢复 |

### 12.5 端到端链路

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| XS-40 | 提交→执行→完成→归档 | submit plan → workflow complete → Herald deliver → offering 存在 |
| XS-41 | rework 链路 | submit → arbiter reject → rework → complete |
| XS-42 | 定时触发链路 | cron Writ → cadence tick → deed created |

### 12.6 Writ Chain 端到端

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| XS-50 | 前序 deed closed → 后序触发 | A closed → B 的 Writ 触发 → B deed 创建 |
| XS-51 | 前序 deed failed → 后序不触发 | A failed → B 不创建 |
| XS-52 | 多前序全完成 → 后序触发 | A+B closed → C 触发 |

### 12.7 Voice → Submit 端到端

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| XS-60 | 对话 → 提取计划 → 提交 → deed | chat → plan → submit → deed 存在 |
| XS-61 | 对话 → 定时 Writ 创建 | "每天9点" → Writ schedule 正确 |
| XS-62 | 对话 → Folio 亲和绑定 | 已有 Folio → plan.folio_id 指向它 |

### 12.8 Rework 端到端

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| XS-70 | arbiter reject → rework → 再执行 | feedback → rework → 新 deed_settling |
| XS-71 | rework session append | rework → session_seq 递增 |
| XS-72 | rework 不创建新 move_id | 同 move_id 复用 |

---

## §13 TestSecurity — 安全与防御

### 13.1 输入验证

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SE-01 | SQL 注入在 slug 中被拒 | slug 含 `'; DROP TABLE` → 404 或 400 |
| SE-02 | XSS 在 title 中被清理 | title 含 `<script>` → 存储时无 script 标签 |
| SE-03 | 路径遍历被拒 | slug 含 `../../etc/passwd` → 404 |
| SE-04 | 超长输入被截断 | 100KB 的 message → 不 OOM，被截断或拒绝 |
| SE-05 | JSON 畸形输入不崩溃 | POST 非法 JSON → 400/422，不 500 |

### 13.2 Instinct 安全边界

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SE-10 | 敏感词不外泄 | outbound query 中敏感词被替换 |
| SE-11 | 输出中敏感词被检测 | check_output → violation 列表非空 |
| SE-12 | Voice 更新不超 token 限制 | 超限 → violation |

### 13.3 权限与隔离

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SE-20 | Console 端点有认证 | 未认证请求 → 401/403 |
| SE-21 | Deed 隔离 | 不同 deed 的 messages 不混合（deed_id 过滤） |
| SE-22 | Session key 格式正确 | {agent_id}:{deed_id}:{session_seq} |

### 13.4 资源防御

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SE-30 | 并发 deed 限制 | 超过 concurrent_deeds 限制 → 排队 |
| SE-31 | 单 deed token 限制 | 超过 deed_ration_ratio → 拒绝 |
| SE-32 | 日配额限制 | 超过 daily_limits → consume_ration 返回 False |

### 13.5 文件系统安全

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SE-40 | deed_root 路径不逃逸 | deed_id 含 "../" → 被规范化或拒绝 |
| SE-41 | offering 路径不逃逸 | 归档路径在 offerings/ 下 |
| SE-42 | 状态文件损坏恢复 | deeds.json 损坏 → load_deeds 返回默认值 |
| SE-43 | JSONL 损坏行跳过 | events.jsonl 有非法行 → 跳过该行继续 |

### 13.6 Unicode 与编码

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SE-50 | 中文标题正确存储 | title="测试标题" → 存取一致 |
| SE-51 | emoji 标题正确存储 | title="🚀 部署" → 存取一致 |
| SE-52 | 混合语言 slug 生成 | "测试 Test" → slug 合法 |
| SE-53 | UTF-8 BOM 不影响解析 | 带 BOM 的 JSON → 正确解析 |
| SE-54 | 超长 Unicode 截断 | 10000 字中文 → 不 OOM |

### 13.7 敏感词边界

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| SE-60 | 敏感词大小写不敏感 | "SECRET" 和 "secret" 都被检测 |
| SE-61 | 敏感词在词中间 | "my_SECRET_key" → 被检测 |
| SE-62 | 空 sensitive_terms.json → 不崩溃 | [] → check_outbound_query 原样返回 |

---

## §14 TestConfigConsistency — 配置文件一致性

### 14.1 spine_registry.json

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CF-01 | JSON 格式正确 | json.loads 不报错 |
| CF-02 | 7 个 routine 完整 | pulse, record, witness, focus, relay, tend, curate |
| CF-03 | 所有 mode 为 deterministic | 无 hybrid |
| CF-04 | nerve_triggers 事件名合法 | 每个 trigger 是已知的 event name |
| CF-05 | depends_on 引用存在 | 依赖的 routine name 在 registry 中 |
| CF-06 | schedule 格式合法 | cron 表达式可解析 |

### 14.2 model_policy.json

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CF-10 | 所有 agent 有映射 | counsel, scout, sage, artificer, arbiter, scribe, envoy |
| CF-11 | 所有 alias 在 model_registry 中 | fast, analysis, review, glm 等 |

### 14.3 model_registry.json

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CF-20 | 所有 alias 有 provider + model_id | 字段非空 |
| CF-21 | provider 是合法值 | minimax, qwen, zhipu, deepseek, openai, anthropic 之一 |

### 14.4 mcp_servers.json

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CF-30 | JSON 格式正确 | json.loads 不报错 |
| CF-31 | servers 是 dict | isinstance(servers, dict) |
| CF-32 | 每个 server 有 transport 字段 | transport 为 stdio 或 http |

### 14.5 跨文件一致性

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CF-40 | registry routines = SpineRoutines 方法 | 一一对应 |
| CF-41 | model_policy agents = POOL_ROLES + counsel | 完整覆盖 |
| CF-42 | preferences.toml 默认值合理 | default_depth 在 errand/charge/endeavor 中 |

### 14.6 rations.toml 一致性

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CF-50 | daily_limits 所有 provider 有值 | minimax, qwen, zhipu, deepseek 都有 |
| CF-51 | concurrent_deeds 有值且 > 0 | 正整数 |
| CF-52 | current_usage 结构对齐 | 与 daily_limits 同 key |

### 14.7 Psyche 文件一致性

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CF-60 | instinct.md 与 InstinctEngine 一致 | prompt_fragment() 返回内容 == 文件内容 |
| CF-61 | voice/identity.md ≤ IDENTITY_TOKEN_LIMIT | 长度检查 |
| CF-62 | voice overlays 每个 ≤ OVERLAY_TOKEN_LIMIT | 遍历 overlays/*.md |
| CF-63 | sensitive_terms.json 是 list | isinstance(terms, list) |

---

## §15 TestFolioWritRegistry — FolioWrit 注册表

全面测试 FolioWritManager 的 CRUD、关联、查询、触发逻辑。

### 15.1 Folio CRUD

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| FW-01 | create_folio 返回完整结构 | 所有必填字段存在 |
| FW-02 | get_folio 返回正确 | 创建后 get → 相同 folio_id |
| FW-03 | get_folio_by_slug 查找正确 | 按 slug 查 → 同一个 folio |
| FW-04 | list_folios 按 updated_utc 倒排 | 最新的在前 |
| FW-05 | update_folio 更新标题 | 更新 → 标题变、slug 同步变 |
| FW-06 | delete_folio 移除记录 | delete → get 返回 None |
| FW-07 | delete_folio 级联 Slip 脱离 | delete → 关联 Slip.folio_id = None |
| FW-08 | delete_folio 级联 Writ disabled | delete → 关联 Writ.status = disabled |

### 15.2 Slip CRUD

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| FW-10 | create_slip 返回完整结构 | 所有必填字段存在 |
| FW-11 | create_slip 自动附加到 Folio | folio_id 非空 → Folio.slip_ids 包含新 Slip |
| FW-12 | get_slip_by_slug 查找正确 | 按 slug 查 → 同一个 slip |
| FW-13 | list_slips 按 folio_id 过滤 | 只返回指定 Folio 的 Slip |
| FW-14 | update_slip 更新标题 | 更新 → 标题变、slug 同步变 |
| FW-15 | update_slip 迁移 Folio | 从 A 迁到 B → A.slip_ids 减少, B.slip_ids 增加 |
| FW-16 | duplicate_slip 复制结构 | 标题加 "副本"，objective/design 相同，deed_ids 空 |
| FW-17 | duplicate_slip standing=False | 复制品 standing=False, brief.standing=False |
| FW-18 | reorder_folio_slips 持久化 | 重排 [C, A, B] → folio.slip_ids == [C, A, B] |
| FW-19 | reorder_folio_slips 忽略无效 ID | 传入不存在的 slip_id → 被忽略 |
| FW-20 | record_deed_created 更新 Slip | 记录 → deed_ids 增加, latest_deed_id 更新 |
| FW-21 | deed_ids 上限 200 | 插入 250 个 → 只保留最近 200 |

### 15.3 Writ CRUD

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| FW-30 | create_writ 返回完整结构 | 所有必填字段存在 |
| FW-31 | create_writ 自动附加到 Folio | Folio.writ_ids 包含新 Writ |
| FW-32 | create_writ 注册触发器 | _registered_triggers 包含该 writ_id |
| FW-33 | create_writ 同步 Slip trigger_type | schedule → timer, event → writ_chain |
| FW-34 | update_writ canonical 字段 version++ | 更新 title → version 递增 |
| FW-35 | delete_writ 移除记录 | delete → get 返回 None |
| FW-36 | delete_writ 从 Folio 脱离 | delete → Folio.writ_ids 不含该 writ_id |

### 15.4 Draft CRUD

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| FW-40 | create_draft 返回完整结构 | 必填字段存在 |
| FW-41 | list_drafts 按 updated_utc 倒排 | 最新在前 |
| FW-42 | update_draft 修改字段 | 更新 intent_snapshot → 保存成功 |
| FW-43 | crystallize_draft 创建 Slip | draft→gone，slip 创建在同 folio |
| FW-44 | crystallize 不存在 → ValueError | draft_id 不存在 → raise |

### 15.5 Trigger 机制

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| FW-50 | register_all_triggers 注册所有 active | 3 active + 1 disabled → 注册 3 个 |
| FW-51 | event 触发匹配 | writ match event=deed_closed → emit deed_closed → handler 调用 |
| FW-52 | event filter 匹配 | match filter {slip_id: "X"} → 只有 slip_id=X 的 payload 触发 |
| FW-53 | event filter 不匹配跳过 | match filter {slip_id: "X"} → slip_id=Y 的 payload 不触发 |
| FW-54 | schedule 触发 cadence.tick | writ schedule + cadence.tick payload → 匹配则 emit writ_trigger_ready |
| FW-55 | schedule 不匹配跳过 | schedule "0 9 * * *" + tick 10:00 → 不触发 |
| FW-56 | 重复触发抑制 | 同分钟连续 tick → 只触发一次（last_triggered_utc 去重） |

### 15.6 Submission Limits

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| FW-60 | can_trigger_writ 无 active deed → true | 允许触发 |
| FW-61 | can_trigger_writ 超 max_active_deeds → false | 3 active deed for same writ → false |
| FW-62 | can_trigger_writ 超 max_active_folio → false | 6 active deed in folio → false |
| FW-63 | check_submission_limits global | running_total ≥ limit → false |
| FW-64 | infer_dag_budget_from_history | 历史 [4, 6, 8] → 平均 6 |
| FW-65 | infer_dag_budget 无历史 → default | 返回传入的 default |

### 15.7 Standing Slip

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| FW-70 | ensure_standing_writ 创建 Folio | Slip 无 Folio → 自动创建 Folio |
| FW-71 | ensure_standing_writ 创建 Writ | → Writ match.schedule 正确, action.slip_id 正确 |
| FW-72 | ensure_standing_writ 幂等 | 调两次 → 同一个 writ_id |
| FW-73 | ensure_standing_writ 不存在 → None | slip_id 不存在 → None |

### 15.8 Writ Neighbors / DAG Navigation

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| FW-80 | writ_neighbors 前序正确 | Writ: A.deed_closed → spawn B → B.prev 含 A |
| FW-81 | writ_neighbors 后序正确 | 同上 → A.next 含 B |
| FW-82 | writ_neighbors 无关联 → 空 | 独立 Slip → prev=[], next=[] |
| FW-83 | predecessors_all_closed 全关闭 | A latest deed closed → (True, []) |
| FW-84 | predecessors_all_closed 有阻塞 | A latest deed running → (False, [A.slip_id]) |
| FW-85 | predecessors_all_closed 无 deed → 阻塞 | A 无 deed → 视为阻塞 |
| FW-86 | active_folio_matches 关键词匹配 | Folio title 含关键词 → 返回该 Folio |

---

## §16 TestWillPipeline — Will 提交管线

### 16.1 验证

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| WP-01 | validate 合法 plan → (True, "") | 有 moves 且 id 不重复 |
| WP-02 | validate 空 moves → (False, ...) | 报错含 "moves" |
| WP-03 | validate 重复 id → (False, ...) | 报错含 "duplicate" |
| WP-04 | validate 未知依赖 → (False, ...) | 报错含 "unknown" |
| WP-05 | validate 循环依赖 → (False, ...) | A→B→A → 检测到 |

### 16.2 Enrichment

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| WP-10 | enrich 分配 deed_id | deed_id 以 "deed_" 开头 |
| WP-11 | enrich 保留用户指定 deed_id | plan 已有 deed_id → 不覆盖 |
| WP-12 | enrich 设置 brief 默认值 | dag_budget, depth 有值 |
| WP-13 | enrich 设置 concurrency 默认值 | concurrency > 0 |
| WP-14 | enrich 设置 rework_limit | rework_limit > 0 |
| WP-15 | enrich 设置 eval_window_hours | 默认 48 |
| WP-16 | enrich 从 preferences 读 require_bilingual | 值正确 |
| WP-17 | enrich 设置 quality_profile | 有值 |
| WP-18 | enrich 应用 model routing | agent_model_map 存在 |

### 16.3 Ward 检查

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| WP-20 | ward RED → queued | plan.queued == True, queue_reason 含 "red" |
| WP-21 | ward YELLOW + 大 dag → queued | dag_budget ≥ 6 → queued |
| WP-22 | ward YELLOW + 小 dag → 不 queued | dag_budget < 6 → 不 queued |
| WP-23 | ward GREEN → 不 queued | 不设 queued |
| WP-24 | system_status 非 running → queued | system paused → queued |

### 16.4 Submit 流程

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| WP-30 | submit 合法 plan → ok=True (有 Temporal) | 返回 deed_id, slip_id |
| WP-31 | submit 合法 plan → ok=False (无 Temporal) | error_code=temporal_unavailable |
| WP-32 | submit 非法 plan → ok=False | error_code=invalid_plan |
| WP-33 | submit queued plan → ok=True + queued reason | deed_status=running, sub_status=queued |
| WP-34 | submit DAG 超预算 → 拒绝 | moves > dag_budget → error_code=ward_dag_budget_exceeded |
| WP-35 | submit 触发 _materialize_objects | Slip/Folio/Writ 创建 |
| WP-36 | submit 触发 _record_deed | deed 出现在 deeds.json |
| WP-37 | submit 触发 _record_registry_links | Slip.deed_ids 更新 |
| WP-38 | submit 触发 deed_submitted event | nerve 有 deed_submitted |

### 16.5 Materialization

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| WP-40 | 无 folio_id → 从 metadata 创建 | create_folio_title → 新 Folio |
| WP-41 | 无 draft_id → 自动创建 Draft | Draft 出现在 drafts.json |
| WP-42 | 无 slip_id → 自动 crystallize | Slip 出现在 slips.json |
| WP-43 | standing + schedule → ensure_standing_writ | Writ 创建在 Folio 中 |
| WP-44 | metadata.slip_id 已有 → 不重复创建 | 直接使用已有 Slip |

---

## §17 TestCronScheduling — Cron 与调度

### 17.1 Cron 表达式解析

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CR-01 | `*/10 * * * *` → 每 10 分钟 | _cron_values minute → {0,10,20,30,40,50} |
| CR-02 | `0 3 * * *` → 每天 3:00 | hour={3}, minute={0} |
| CR-03 | `0 9 * * 1` → 每周一 9:00 | dow={1} |
| CR-04 | `0 2 * * 0` → 每周日 2:00 | dow={0} (7 映射到 0) |
| CR-05 | `0 6 1,15 * *` → 每月 1/15 日 | dom={1,15} |
| CR-06 | `30 8 * * 1-5` → 工作日 8:30 | dow={1,2,3,4,5} |
| CR-07 | 无效表达式 → 不匹配 | _cron_matches("invalid", now) → False |
| CR-08 | 4 字段表达式 → 不匹配 | "* * * *" → False |

### 17.2 Cron 匹配

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CR-10 | 精确时间匹配 | "0 9 * * *" + 09:00 → True |
| CR-11 | 分钟不匹配 | "0 9 * * *" + 09:01 → False |
| CR-12 | DOM 匹配 | "0 0 15 * *" + 15 日 → True |
| CR-13 | DOM 不匹配 | "0 0 15 * *" + 16 日 → False |
| CR-14 | DOW 匹配周一 | "* * * * 1" + 周一 → True |
| CR-15 | DOW 不匹配 | "* * * * 1" + 周二 → False |
| CR-16 | Month 匹配 | "* * * 3 *" + 3 月 → True |
| CR-17 | DOM+DOW 都指定 → OR 逻辑 | "0 0 1 * 1" → 1 号 OR 周一 |

### 17.3 Cadence 调度辅助

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CR-20 | _parse_cron_simple 正确 | "*/10 * * * *" → 600 |
| CR-21 | _parse_duration hours | "4h" → 14400 |
| CR-22 | _parse_duration minutes | "30m" → 1800 |
| CR-23 | _parse_duration mixed | "2h30m" → 9000 |
| CR-24 | _parse_duration invalid → None | "abc" → None |
| CR-25 | _next_cron_occurrence 返回 UTC | 下一次触发时间格式正确 |

### 17.4 Cadence Schedule 覆盖

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CR-30 | update_schedule 更新成功 | 新 schedule → 持久化到 schedules.json |
| CR-31 | update_schedule 禁用 | enabled=False → 跳过执行 |
| CR-32 | schedule_history 记录变更 | 更新 → history 增加一条 |

---

## §18 TestHeraldPipeline — Herald 归档管线

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| HP-01 | deliver 无 scribe 输出 → 失败 | error_code=scribe_output_missing |
| HP-02 | deliver 有 scribe 输出 → 成功 | ok=True, offering_path 存在 |
| HP-03 | _vault 复制文件 | offering 目录有 .md 文件 |
| HP-04 | _generate_pdf_best_effort 不崩溃 | 无论成功失败都不抛异常 |
| HP-05 | _update_index 写入 herald_log | herald_log.jsonl 多一条 |
| HP-06 | herald_log 结构完整 | 有 deed_id, slip_id, folio_id, offering_path |
| HP-07 | deliver 触发 herald_completed | nerve 有 herald_completed 事件 |
| HP-08 | deliver 短内容仍成功 | 10 字的 scribe output → ok=True |
| HP-09 | HTML scribe 输出 | .html 文件 → PDF 转换尝试 |
| HP-10 | _html_to_text 基本转换 | `<p>text</p>` → "text" |
| HP-11 | _route_telegram 配置关闭不崩溃 | telegram_enabled=false → 不调用 |
| HP-12 | 连续 deliver 不覆盖 | 两次不同 deed → 两个 offering 目录 |
| HP-13 | offering 目录结构 YYYY-MM | offering_path 包含日期目录 |
| HP-14 | load_herald_log 返回正确 | 写入后 load → 条目一致 |
| HP-15 | word count 基本统计 | deliver 返回含 word_count 或 offering 有统计 |

---

## §19 TestRuntimeComponents — Runtime 组件

### 19.1 Cortex

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| RT-01 | Cortex 可实例化 | 无 API key → is_available()==False，不崩溃 |
| RT-02 | try_or_degrade 主路径 | 主函数成功 → 返回主结果 |
| RT-03 | try_or_degrade 降级路径 | 主函数异常 → 返回降级结果 |
| RT-04 | _ration_admit 有配额 → True | 配额充足 → 允许 |
| RT-05 | _ration_admit 无配额 → False | 配额耗尽 → 拒绝 |

### 19.2 Retinue

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| RT-10 | 池加载空文件 → 空列表 | pool_status.json 不存在 → [] |
| RT-11 | allocate 返回实例 | allocate("scout") → 返回实例 dict |
| RT-12 | allocate 同角色不同实例 | 连续 allocate → 不同 instance_id |
| RT-13 | allocate 池耗尽 → PoolExhausted | 分配完所有 → 异常 |
| RT-14 | release 归还实例 | release → 实例变 idle |
| RT-15 | release 后可重新分配 | release → allocate → 成功 |
| RT-16 | pool_status.json 持久化 | allocate → 文件更新 |
| RT-17 | POOL_ROLES 包含 6 个角色 | scout, sage, artificer, arbiter, scribe, envoy |

### 19.3 Ether

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| RT-20 | Ether 可实例化 | 创建不崩溃，目录存在 |
| RT-21 | emit 写入 events.jsonl | emit → 文件多一行 |
| RT-22 | consume 返回新事件 | emit → consume → 返回该事件 |
| RT-23 | consume 后 cursor 前进 | 二次 consume → 不重复 |
| RT-24 | ack 标记已处理 | ack → pending 减少 |
| RT-25 | cursor 持久化 | 重建 Ether → cursor 从文件恢复 |
| RT-26 | 老格式 cursor 兼容 | 纯数字 cursor 文件 → 正确读取 offset |

### 19.4 Trail

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| RT-30 | span 记录正常完成 | with trail.span → status=ok |
| RT-31 | span 记录异常 | raise → status=error, error 含异常类型 |
| RT-32 | span degraded | mark_degraded → degraded=True |
| RT-33 | step 记录 | ctx.step → trace 包含 step 数据 |
| RT-34 | 持久化到 JSONL | span 完成 → traces/*.jsonl 有行 |
| RT-35 | query 按 routine 过滤 | 多个 span → query(routine=X) 只返回 X |
| RT-36 | recent 返回最近 N 条 | recent(2) → 最多 2 条 |

### 19.5 MCPDispatcher

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| RT-40 | 空配置可实例化 | mcp_servers.json servers={} → available==False |
| RT-41 | call_tool 未知工具 → ValueError | tool 不在 routes → raise |
| RT-42 | list_tools 空配置 → 空列表 | [] |

### 19.6 Brief / Design Validator

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| RT-50 | Brief.from_dict 默认值 | 空 dict → 有 dag_budget, depth 默认值 |
| RT-51 | Brief.execution_defaults 合理 | timeout_per_move_s > 0, concurrency > 0 |
| RT-52 | SINGLE_SLIP_DEFAULTS 完整 | 包含 dag_budget, depth, timeout_per_move_s |
| RT-53 | validate_design 合法 → True | 有 moves + id → True |
| RT-54 | validate_design 空 moves → False | [] → False |
| RT-55 | validate_design 循环依赖 → False | A→B→A → False |

---

## §20 TestLedgerStore — Ledger 状态存储

### 20.1 基本读写

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LD-01 | 初始化创建目录 | Ledger(new_path) → 目录存在 |
| LD-02 | load_deeds 空文件 → 空列表 | deeds.json 不存在 → [] |
| LD-03 | upsert_deed 新增 | upsert → load_deeds 包含该 deed |
| LD-04 | upsert_deed 更新 | 同 deed_id 再 upsert → 覆盖 |
| LD-05 | get_deed 存在 | upsert → get → 相同 deed_id |
| LD-06 | get_deed 不存在 → None | get("nonexistent") → None |
| LD-07 | mutate_deeds 修改生效 | mutate → 修改被持久化 |
| LD-08 | mutate_deeds 原子性 | mutate 中异常 → 数据不变 |

### 20.2 Ward

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LD-10 | load_ward 空 → 默认 | ward.json 不存在 → {} 或默认 |
| LD-11 | save_ward 持久化 | save → load → 相同内容 |
| LD-12 | ward status 合法值 | GREEN/YELLOW/RED |

### 20.3 文件操作

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LD-20 | load_json 不存在 → 默认 | path 不存在 → 返回 default |
| LD-21 | load_json 损坏文件 → 默认 | 非法 JSON → 返回 default, 不崩溃 |
| LD-22 | save_json 原子写入 | save → 无 .tmp 残留 |
| LD-23 | append_jsonl 追加 | 连续 append → 行数递增 |
| LD-24 | load_herald_log 返回列表 | append 后 load → 条目存在 |
| LD-25 | load_system_status 默认 | 无文件 → "" 或 "running" |

### 20.4 线程锁

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LD-30 | _lock_for 同路径同锁 | 两次 _lock_for(same_path) → 同一个 Lock 对象 |
| LD-31 | _lock_for 不同路径不同锁 | _lock_for(A) != _lock_for(B) |
| LD-32 | 并发 save_json 不丢数据 | 10 线程同时写不同 key → 全保存 |

### 20.5 Daily Stats

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LD-40 | load_daily_stats 空 → 默认 | 无文件 → {} |
| LD-41 | mutate_daily_stats 更新 | 设置 deeds_completed=5 → 持久化 |
| LD-42 | 按日期分区 | 不同日期 → 不同 key |
| LD-43 | 自动清理旧 stats | 90 天前 → 被清理 |

### 20.6 Notification Queue

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LD-50 | enqueue_failed_notification 写入 | enqueue → load_notify_queue 非空 |
| LD-51 | enqueue 结构完整 | 有 deed_id, message, created_utc, retry_count |
| LD-52 | rewrite_notify_queue 替换 | rewrite([]) → load 为空 |
| LD-53 | 多次 enqueue 累积 | enqueue 3 次 → load 长度 3 |

### 20.7 Schedule History

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| LD-60 | load_schedule_history 空 → 默认 | 无文件 → {} |
| LD-61 | save_schedule_history 持久化 | save → load → 一致 |
| LD-62 | 按 routine 分组 | 不同 routine → 不同 key |
| LD-63 | history 条目结构 | 有 started_utc, status, duration_ms, trigger |

---

## §21 TestVoiceService — 对话与计划管线

全面测试 VoiceService 的会话管理、Counsel 交互、计划提取与充实。

### 21.1 Session 管理

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| VS-01 | new_session 返回 session_id | session_id 非空字符串 |
| VS-02 | new_session 初始化 messages 为空 | session["messages"] == [] |
| VS-03 | get_session 返回正确 session | new → get → 相同 session_id |
| VS-04 | get_session 不存在 → None | get("nonexistent") → None |
| VS-05 | session 结构完整 | 包含 session_id, user_id, messages, created_utc, last_active_utc |
| VS-06 | session TTL 默认 24h | SESSION_TTL_S == 86400 |
| VS-07 | 过期 session 被清理 | 创建 25h 前的 session → cleanup → get 返回 None |
| VS-08 | 未过期 session 不被清理 | 创建 1h 前的 session → cleanup → 仍存在 |
| VS-09 | chat 更新 last_active_utc | chat 后 last_active_utc 变化 |
| VS-10 | 多 session 互不干扰 | session_A chat → session_B 无消息 |

### 21.2 消息文本提取

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| VS-15 | 字符串消息直接返回 | _extract_text("hello") == "hello" |
| VS-16 | list 消息提取 text blocks | _extract_text([{"type":"text","text":"hi"}]) == "hi" |
| VS-17 | errorMessage 提取 | _extract_text({"errorMessage":"err"}) → 包含 "err" |
| VS-18 | 空消息 → 空字符串 | _extract_text(None) == "" |
| VS-19 | 混合 content blocks | list 含 text + non-text → 只提取 text |

### 21.3 计划提取

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| VS-20 | 标准 JSON block 提取 | ```json\n{...}\n``` → 正确解析 |
| VS-21 | 无 JSON block → None | 纯文本回复 → plan=None |
| VS-22 | 畸形 JSON → None | ```json\n{invalid}\n``` → plan=None，不崩溃 |
| VS-23 | 嵌套 JSON 正确 | moves 内嵌对象 → 完整提取 |
| VS-24 | 多个 JSON block → 取第一个 | 两个 ```json block → 只取第一个 |

### 21.4 计划充实

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| VS-30 | enrich 添加 slip_title | plan 无 title → enrich 后有 slip_title |
| VS-31 | enrich Folio 亲和匹配 | active_folio_matches 返回高分 → folio_id 被设置 |
| VS-32 | enrich 无匹配 Folio → 新建 | 无匹配 → create_folio_title 非空 |
| VS-33 | enrich 检测定时关键词 "每天" | plan 含 "每天" → standing=True + schedule 被设置 |
| VS-34 | enrich 检测 "weekly" | 含 "weekly" → schedule 包含 cron 表达式 |
| VS-35 | enrich 检测 "每月" | 含 "每月" → schedule 包含 cron |
| VS-36 | enrich 创建 Draft | plan → draft 出现在 drafts 中 |
| VS-37 | enrich 更新已有 Draft | draft_id 已有 → 更新而非新建 |

### 21.5 直接命令（无 LLM）

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| VS-40 | "不用看了" → 禁用 Writ | 发送 → 匹配 Folio 的 Writ status=disabled |
| VS-41 | "stop tracking" → 禁用 Writ | 同上（英文版） |
| VS-42 | "改成每周" → 更新 schedule | Writ schedule 包含 weekly cron |
| VS-43 | "switch to daily" → 更新 schedule | Writ schedule 更新为 daily |
| VS-44 | 不匹配任何命令 → 走 LLM | 普通对话 → 不触发直接命令 |
| VS-45 | 直接命令返回确认消息 | 返回消息包含操作确认文本 |

### 21.6 显示元数据

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| VS-50 | move_count ≤ dag_budget → slip mode | display_mode == "slip" |
| VS-51 | move_count > dag_budget → folio mode | display_mode == "folio" + slip_count hint |
| VS-52 | slip mode 有 timeline | 返回含 timeline 字段 |

---

## §22 TestCadenceEngine — Cadence 调度引擎

### 22.1 启动与停止

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CA-01 | start 注册 nerve handlers | nerve._handlers 包含 cadence 相关事件 |
| CA-02 | start 加载 schedule_overrides | schedules.json 中覆盖生效 |
| CA-03 | stop 取消 asyncio task | start → stop → task.cancelled() |
| CA-04 | status 返回所有 routine | len(status()) == 7 |
| CA-05 | status 含 next_run_utc | 每项有 next_run_utc 字段 |
| CA-06 | history 返回执行记录 | 执行后 history(routine) 非空 |

### 22.2 Routine 执行

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CA-10 | _run_routine 调用正确方法 | trigger("pulse") → SpineRoutines.pulse 被调用 |
| CA-11 | _run_routine 检查 pact pre | pre condition 失败 → PactError |
| CA-12 | _run_routine 检查 pact post | post condition 失败 → PactError |
| CA-13 | _run_routine 超时处理 | routine 执行超时 → timeout error 记录 |
| CA-14 | _run_routine 记录执行历史 | 执行后 schedule_history 增加一条 |
| CA-15 | _run_routine 发 routine_completed event | 成功 → nerve 有 routine_completed |
| CA-16 | _run_routine degraded mode=skip | routine 报错 + degraded_mode=skip → 跳过 |
| CA-17 | _run_routine degraded mode=degrade | routine 报错 + degraded_mode=degrade → 标 degraded |

### 22.3 Upstream 依赖检查

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CA-20 | 无依赖 → 允许执行 | depends_on=[] → True |
| CA-21 | 上游成功 → 允许执行 | depends_on=["pulse"] + pulse 上次成功 → True |
| CA-22 | 上游失败 → 阻塞 | depends_on=["pulse"] + pulse 上次失败 → False |
| CA-23 | 上游无记录 → 阻塞 | depends_on=["pulse"] + 无 pulse 历史 → False |

### 22.4 Adaptive Interval

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CA-30 | 基础间隔 = registry schedule | learning_rhythm 无覆盖 → 用 registry 间隔 |
| CA-31 | queue_depth 影响 | 高 queue depth → 缩短间隔 |
| CA-32 | portal_activity 影响 | 高 portal activity → 缩短间隔 |
| CA-33 | error_rate 影响 | 高 error_rate → 延长间隔 |
| CA-34 | 间隔最小值保护 | 不低于 60s |
| CA-35 | 间隔最大值保护 | 不超过 86400s |

### 22.5 Tick 机制

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CA-40 | _tick_eval_windows 关闭过期 deed | settling 48h → deed closed |
| CA-41 | _tick_eval_windows 不关闭未过期 | settling 24h → 仍 settling |
| CA-42 | _tick_running_ttl 关闭过期 deed | running 4h+ → deed closed + timed_out |
| CA-43 | _tick_running_ttl 不关闭未过期 | running 1h → 仍 running |
| CA-44 | _tick_eval_windows emit deed_closed | 关闭时 nerve 有 deed_closed 事件 |
| CA-45 | _tick_running_ttl emit deed_closed | 关闭时 nerve 有 deed_closed 事件 |
| CA-46 | tick 匹配 Writ schedule | cadence.tick payload + writ schedule → _on_trigger_fired 调用 |

### 22.6 手动触发

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| CA-50 | trigger 合法 routine → 成功 | trigger("pulse") → 返回结果 |
| CA-51 | trigger 不存在 routine → 错误 | trigger("nonexistent") → error |
| CA-52 | trigger disabled routine → 跳过 | enabled=False → 不执行 |

---

## §23 TestTemporalWorkflow — Workflow 执行逻辑

测试 GraphWillWorkflow 的 DAG 执行、信号处理、错误路径（mock Temporal runtime）。

### 23.1 DAG 构建与验证

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TW-01 | 线性 DAG 排序正确 | A→B→C → 执行顺序 [A, B, C] |
| TW-02 | 并行 DAG 识别并发 | A→[B,C]→D → B,C 可同时执行 |
| TW-03 | 钻石 DAG 正确 | A→[B,C]→D → D 在 B,C 之后 |
| TW-04 | 空 moves → ApplicationError | plan.moves=[] → 报错 |
| TW-05 | 重复 move_id → ApplicationError | 两个 id="m1" → 报错 |
| TW-06 | 循环依赖 → ApplicationError | A→B→A → 报错 |
| TW-07 | 未知依赖 → ApplicationError | depends_on=["nonexistent"] → 报错 |
| TW-08 | 单 move DAG 正常执行 | 1 个 move → 正常完成 |

### 23.2 Move 执行与调度

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TW-10 | move 按拓扑序执行 | A(deps=[]) → B(deps=[A]) → B 在 A 后执行 |
| TW-11 | 并行 move 尊重 concurrency 限制 | concurrency=1 → 串行执行 |
| TW-12 | 并行 move concurrency=2 | 3 个独立 move → 最多 2 个同时 |
| TW-13 | move 失败 → workflow 继续 (degraded) | move_A 失败 → 后续 move 仍执行 |
| TW-14 | direct move 调用 activity_direct_move | execution_type="direct" → 调用 direct activity |
| TW-15 | spine move 调用 activity_spine_routine | agent="spine" → 调用 spine activity |
| TW-16 | 普通 move 调用 activity_openclaw_move | agent="scout" → 调用 openclaw activity |

### 23.3 Retinue 分配

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TW-20 | 执行前分配 retinue | workflow start → allocate 被调用 |
| TW-21 | 同 agent 同 deed 共享实例 | 两个 scout move → 同一 instance_id |
| TW-22 | 不同 agent 不同实例 | scout + sage → 不同 instance_id |
| TW-23 | 执行完释放 retinue | workflow complete → release 被调用 |
| TW-24 | PoolExhausted → 重试 | 首次失败 → 重试 → 成功 |
| TW-25 | PoolExhausted 重试上限 | 2 次失败 → workflow 失败 |

### 23.4 Signal 处理

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TW-30 | append_requirement 累积消息 | signal 3 次 → requirements 长度 3 |
| TW-31 | append_requirement 上限 20 | signal 25 次 → requirements 长度 20 |
| TW-32 | pause_execution 暂停 | signal pause → 下一个 move 不执行 |
| TW-33 | resume_execution 恢复 | pause → resume → 继续执行 |
| TW-34 | rework 复用 move_id | rework 同 move → session append 而非新建 |

### 23.5 Finalization

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TW-40 | workflow 完成 → finalize_herald 调用 | 正常结束 → activity_finalize_herald 被调用 |
| TW-41 | workflow 完成 → update_deed_status 调用 | → deed_status=settling |
| TW-42 | workflow 失败 → deed_status=closed + failed | 异常 → deed_status=closed, sub=failed |
| TW-43 | workflow 取消 → deed_status=closed + cancelled | cancel signal → closed, sub=cancelled |

---

## §24 TestTemporalActivities — Activity 实现

### 24.1 OpenClaw Move Activity

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TA-01 | session key 格式正确 | {agent_id}:{deed_id}:{session_seq} |
| TA-02 | 首次执行 session_seq=0 | 新 deed + 新 agent → seq=0 |
| TA-03 | rework session_seq 递增 | 同 move rework → seq=1 |
| TA-04 | 上下文包含前序输出 | move_B depends A → context 含 A 的 output |
| TA-05 | checkpoint 写入成功 | 执行完 → moves/{move_id}/checkpoint.json 存在 |
| TA-06 | checkpoint 跳过已完成 | checkpoint status=ok → 不重新执行 |
| TA-07 | checkpoint status=degraded → 跳过 | degraded → 不重新执行 |
| TA-08 | output 写入 moves/{move_id}/output/ | 执行成功 → output 目录有文件 |
| TA-09 | heartbeat 每 30s 发送 | 长任务 → heartbeat_details 被调用 |
| TA-10 | cancellation 优雅处理 | 取消信号 → 写 degraded checkpoint |

### 24.2 Direct Move Activity

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TA-15 | MCP tool 调用正确 | tool_name + tool_args → MCPDispatcher.call_tool 被调用 |
| TA-16 | tool 不存在 → degraded | 未知 tool → checkpoint status=degraded |
| TA-17 | tool 超时 → degraded | timeout → degraded |
| TA-18 | tool 结果写入 output | 成功 → output 包含 tool 返回值 |
| TA-19 | zero token 消耗 | direct move → token_usage=0 |

### 24.3 Herald Finalize Activity

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TA-20 | 成功 deed → offering 存档 | offering 目录创建 |
| TA-21 | 失败 deed → Telegram 通知 | deed_failed → notification enqueued |
| TA-22 | deed_settling event 发出 | → ether 有 deed_settling |
| TA-23 | accepted deed → dag_template 合并 | deed_closed + accepted → merge 调用 |
| TA-24 | cancelled deed → deed_closed event | → ether 有 deed_closed + cancelled |

### 24.4 Deed Status Activity

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TA-30 | status 更新持久化 | running→settling → deeds.json 反映 |
| TA-31 | sub_status 同步更新 | settling + succeeded → sub_status=succeeded |
| TA-32 | updated_utc 更新 | 状态变更 → updated_utc 刷新 |

### 24.5 Retinue Activities

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TA-35 | allocate 返回 instance_id | → 非空字符串 |
| TA-36 | allocate 设置 deed_id | → 实例 deed_id == 请求的 deed_id |
| TA-37 | release 归还实例 | → 实例变 idle |
| TA-38 | release 不存在的实例 → 不崩溃 | → 无异常 |

---

## §25 TestPactValidation — Pact 契约验证

### 25.1 Pre-condition 检查

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| PT-01 | infra:gateway → 检查 OC gateway | gateway 不可达 → PactError |
| PT-02 | infra:temporal → 检查 Temporal | temporal 不可达 → PactError |
| PT-03 | infra:disk → 检查磁盘空间 | 磁盘满 → PactError |
| PT-04 | state:ward → ward.json 存在 | 不存在 → PactError |
| PT-05 | state:traces → traces/ 存在 | 不存在 → PactError |
| PT-06 | psyche:config → PsycheConfig 可用 | 不可用 → PactError |
| PT-07 | deeds:active → deeds.json 可读 | 不可读 → PactError |
| PT-08 | 未知 resource spec → 跳过 | unknown:spec → 不报错 |

### 25.2 Post-condition 检查

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| PT-10 | state:ward post → ward.json 写入 | pulse 后 ward.json 存在 → pass |
| PT-11 | state:ward post → ward.json 缺失 | pulse 后 ward.json 不存在 → PactError |
| PT-12 | post check 在异常后不执行 | routine 抛异常 → 不检查 post |

### 25.3 Pact 配置

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| PT-15 | registry reads 字段正确 | pulse reads=["infra:*"] → pre check 包含 infra |
| PT-16 | registry writes 字段正确 | pulse writes=["state:ward"] → post check 包含 ward |
| PT-17 | 空 reads/writes → 无 pact 检查 | reads=[] → pre check 跳过 |

---

## §26 TestBootstrapStartup — 启动与初始化

### 26.1 API 进程启动

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| BS-01 | create_app 不崩溃 | create_app() 返回 FastAPI 实例 |
| BS-02 | 必要目录自动创建 | state/, psyche/ 不存在 → 自动创建 |
| BS-03 | PsycheConfig 从文件加载 | preferences.toml 存在 → 正确加载 |
| BS-04 | PsycheConfig 缺文件 → 默认值 | 无 preferences.toml → 使用 _DEFAULT_PREFS |
| BS-05 | Nerve 实例化并注册 handler | nerve._handlers 非空（cadence 注册的） |
| BS-06 | Trail 目录创建 | state/traces/ 存在 |
| BS-07 | Canon 加载 7 个 routine | len(canon.all()) == 7 |
| BS-08 | Ledger 可操作 | ledger.load_deeds() 不抛异常 |
| BS-09 | FolioWritManager 加载状态 | 已有 folios.json → 正确加载 |
| BS-10 | Retinue 池初始化 | pool_status.json 创建或加载 |

### 26.2 Worker 进程启动

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| BS-15 | DaemonActivities 可实例化 | 构造不崩溃 |
| BS-16 | 所有 activity 注册 | @activity.defn 装饰的方法都在注册列表 |
| BS-17 | Ether 初始化 | state/nerve_bridge/ 目录创建 |
| BS-18 | MCPDispatcher 从 config 加载 | 空 config → available=False |

### 26.3 Nerve 启动恢复

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| BS-20 | replay_unconsumed 读取持久化事件 | events.jsonl 有未消费 → handler 调用 |
| BS-21 | replay_unconsumed 跳过已消费 | consumed_utc 非空 → 跳过 |
| BS-22 | replay_unconsumed 跳过损坏行 | 非法 JSON 行 → 跳过，不崩溃 |
| BS-23 | replay_unconsumed 返回重播计数 | 3 个未消费 → return 3 |

### 26.4 配置热重载

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| BS-30 | preferences.toml 修改后重载 | set_pref → 文件变更 → 下次读取正确 |
| BS-31 | rations.toml 修改后重载 | 同上 |
| BS-32 | spine_registry.json 不支持热重载 | 修改后需要重启 → 行为正确 |

---

## §27 TestTelegramAdapter — Telegram 通知

### 27.1 基本通知

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TG-01 | telegram_enabled=false → 不发送 | 配置关闭 → _route_telegram 不调用 HTTP |
| TG-02 | telegram_enabled=true → 发送 | 配置开启 → HTTP POST 到 adapter URL |
| TG-03 | 通知包含 deed 信息 | payload 含 deed_id, slip_title, status |
| TG-04 | 通知包含 offering 链接 | succeeded deed → 链接存在 |
| TG-05 | 失败通知包含错误 | failed deed → error_summary 存在 |

### 27.2 重试队列

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TG-10 | 发送失败 → enqueue | HTTP 失败 → enqueue_failed_notification |
| TG-11 | 重试读取队列 | enqueue → load_notify_queue → 非空 |
| TG-12 | 重试成功 → 移出队列 | 重试成功 → rewrite 不含该条 |
| TG-13 | 重试仍失败 → 保留 | 重试失败 → 仍在队列 |
| TG-14 | 队列条目过期清理 | 72h 前的条目 → 清理 |

### 27.3 Adapter 端点

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| TG-20 | POST /notify 接受通知 | 返回 200 |
| TG-21 | POST /notify 畸形 body → 400 | 非法 JSON → 400 |
| TG-22 | 消息格式化正确 | Markdown 格式包含标题+状态+链接 |

---

## §28 TestDesignValidator — 设计验证器（扩展）

补充 runtime/design_validator.py 的边界 case（基本检查已在 RT-53~55）。

| ID | 检查项 | 验证方式 |
|----|--------|---------|
| DV-01 | 合法 agent 全覆盖 | counsel/scout/sage/artificer/arbiter/scribe/envoy/spine 全 pass |
| DV-02 | 非法 agent → False | agent="unknown" → (False, "invalid agent") |
| DV-03 | move 无 id 字段 → False | {"agent":"scout"} → (False, ...) |
| DV-04 | move 缺 agent → False | {"id":"m1"} → (False, ...) |
| DV-05 | dag_budget=0 → False | 任何 move 都超预算 |
| DV-06 | dag_budget=1 单 move → True | 1 move, budget=1 → True |
| DV-07 | dag_budget=3 四 move → False | 4 move, budget=3 → False |
| DV-08 | 无终端 move → False | A→B, B→A（如有非循环但全有后续的情况）→ False |
| DV-09 | 多终端 move → True | A→B, A→C，B 和 C 都是终端 → True |
| DV-10 | 自依赖 → False | A depends_on=[A] → 循环 → False |
| DV-11 | 深层依赖链 → True | A→B→C→D→E (5 层) → True |
| DV-12 | 孤立 move (无依赖无被依赖) → True | 独立 move → 是终端 → True |
| DV-13 | 空 depends_on → 合法 | depends_on=[] → ok |
| DV-14 | depends_on=None → 合法 | 缺字段视为无依赖 |
| DV-15 | spine agent move → True | agent="spine" → 合法 |

---

## §29 实现架构

### 29.1 文件结构

```
tests/
  test_diagnostics.py          ← 主诊断文件（所有 25 个本地类别）
  test_diagnostics_cross.py    ← 跨系统链路（需要服务运行）
  conftest.py                  ← 共享 fixtures（现有 + 新增）
```

### 29.2 Fixture 设计

```python
# conftest.py 新增

@pytest.fixture
def daemon_home(tmp_path):
    """完整的 daemon 目录结构，用于集成测试。"""
    home = tmp_path / "daemon"
    (home / "state").mkdir(parents=True)
    (home / "psyche").mkdir(parents=True)
    (home / "psyche" / "voice").mkdir()
    (home / "psyche" / "overlays").mkdir()
    (home / "config").mkdir(parents=True)
    # 写入最小配置
    _write_minimal_config(home)
    return home

@pytest.fixture
def full_ctx(daemon_home):
    """完整的 API context，包含所有 service。"""
    # 初始化 PsycheConfig, Nerve, Trail, Ledger, LedgerStats,
    # InstinctEngine, SpineRoutines, FolioWritManager, Will, Herald, Cadence
    ...

@pytest.fixture
def test_client(full_ctx):
    """FastAPI TestClient。"""
    from fastapi.testclient import TestClient
    app = _create_test_app(full_ctx)
    return TestClient(app)
```

### 29.3 辅助函数

```python
def _create_deed(ledger, *, status="running", slip_id=None, age_hours=0):
    """创建测试用 deed，可指定状态和年龄。"""

def _create_slip(folio_writ, *, title="Test", standing=False, folio_id=None):
    """创建测试用 slip。"""

def _create_folio(folio_writ, *, title="Test Folio"):
    """创建测试用 folio。"""

def _mock_messages(n=5, user_count=3, operation_count=1):
    """生成 mock 消息列表。"""

def _mock_embedding(dim=256, seed=42):
    """生成确定性 mock embedding。"""

def _similar_embedding(base, noise=0.01):
    """生成与 base 相似的 embedding（cosine > 0.99）。"""

def _different_embedding(base):
    """生成与 base 不相似的 embedding（cosine < 0.5）。"""
```

### 29.4 运行约定

- 所有本地测试必须能在 5 秒内完成（无网络、无外部进程）
- 跨系统测试超时 30 秒
- 每个测试独立，不依赖执行顺序
- 使用 `tmp_path` 而非真实 state 目录
- 测试文件不写入项目目录

---

## §30 优先级与实施顺序

| 阶段 | 类别 | 测试项 | 理由 |
|------|------|--------|------|
| **P0** | TestDataModel + TestLifecycle + TestLedgerStore | 146 | 数据正确性是一切的基础 |
| **P1** | TestEventChains + TestFolioWritRegistry + TestWashMechanism | 117 | 事件链和注册表是系统核心机制 |
| **P2** | TestAPIContracts + TestWillPipeline + TestVoiceService | 132 | 前端依赖的接口合约 + 提交管线 + 对话入口 |
| **P3** | TestSpineChains + TestLearningStats + TestCronScheduling + TestCadenceEngine | 102 | 治理、学习、调度机制 |
| **P4** | TestTemporalWorkflow + TestTemporalActivities + TestPactValidation | 71 | Workflow 执行、Activity、Pact 契约 |
| **P5** | TestHeraldPipeline + TestRuntimeComponents + TestPsycheConfig + TestDesignValidator | 91 | 归档、运行时、Psyche、设计验证 |
| **P6** | TestConcurrency + TestSecurity + TestBootstrapStartup | 65 | 健壮性 + 启动验证 |
| **P7** | TestConfigConsistency + TestCrossSystem + TestTelegramAdapter | 66 | 配置一致性、集成验证、通知 |

---

## §31 Console 诊断入口

```python
# API 端点
@app.post("/console/diagnostics/run")
def run_diagnostics(payload: dict):
    """运行诊断套件，返回结果。"""
    categories = payload.get("categories") or ["all"]
    # 调用 pytest 以 subprocess 运行，收集 JSON 结果
    # 返回 {passed: N, failed: N, skipped: N, details: [...]}
```

此端点在诊断测试实现完成后添加。

---

## §32 与知识层重构的关系

本诊断套件基于**当前代码状态**设计。知识层重构（Phase A→E）完成后需要更新的部分：

| 重构项 | 影响的测试类别 |
|--------|--------------|
| Psyche 三分 → 新架构 | TestPsycheConfig（文件路径变更）、TestBootstrapStartup |
| Voice 双层 | TestPsycheConfig（token 预算检查）、TestConfigConsistency |
| Spine 9→7 | TestSpineChains（routine 列表）、TestCadenceEngine |
| 删除 learn/distill | TestConfigConsistency（registry 检查） |
| SourceCache | 新增 TestSourceCache 类别 |
| Session 模型变更 | TestTemporalActivities（session key）、TestVoiceService |

这些更新在重构代码提交时同步进行，不需要提前做。
