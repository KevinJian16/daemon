# Daemon 下一阶段计划 v2

> 更新日期：2026-03-06
> 基准：`daemon_统一方案_v2.md`、`UX_SPEC.md`、`REFACTOR_PLAN.md`

---

## 当前完成状态

| 模块 | 状态 |
|---|---|
| V2 §12-19 全部功能 | ✅ DONE |
| Portal UI + 模块化重构 | ✅ DONE |
| Console UI + 模块化重构 | ✅ DONE |
| Telegram Bot（inline keyboard、/notify、/pause）| ✅ DONE |
| API / Dispatch / Spine / Activities 结构重构 | ✅ DONE |
| StateStore 统一状态层 | ✅ DONE |
| Drive outcome 路径对齐（→ My Drive/daemon/outcomes/）| ✅ DONE |
| Tailscale | ❌ DISABLED |

---

## 新方向共识

### A. Build Agent 治理模型（GitHub PR 流）

产出代码不直接修改本地。流程：

```
build agent → GitHub feature branch → PR
Claude Code → review PR（逻辑、V2 一致性、安全边界）
用户 → 确认 merge
本地 → git pull
```

**前置条件**：在 GitHub 建 repo，`git remote add origin <url>`。
`gh auth` 已就绪（KevinJian16，repo + workflow scope），build agent 直接继承。

### B. 周报机制（每周前沿扫描）

- **每周**：collect agent 轻量扫描目标领域新动态，产出简报推 Telegram
- **按需**：简报中发现值得引入的机制时，触发完整升级 Campaign（Milestone 1-4）
- 不是每周跑完整 Campaign，是每周扫描、按需升级

### C. 机制升级 Campaign 模板

```
Milestone 1  调研      collect agent → 抓取代表性工作（paper、repo、工程实现）
Milestone 2  Gap 分析  analyze agent → 对照 daemon 现状逐项评估差距与引入成本
Milestone 3  设计方案  review agent  → 输出具体改动方案（文件级别）
Milestone 4  实施      build agent   → GitHub PR（人工 review 后 merge）
```

产出必须写入 Portal 可查看的文件，不只是 Telegram 摘要。
build agent 不直接修改本地代码，走 GitHub PR 流。

---

## 推进顺序

### 阶段一：基础设施（立即）

1. **GitHub remote**：建 repo，`git remote add`，push 当前代码
2. **CRUD Memory 升级**：由 Claude Code 直接实施（不走 Campaign）

   **改动范围**：
   - `fabric/memory.py`：写入时检测矛盾/冗余，支持 Update/Delete 操作
   - `fabric/playbook.py`：method entry 原子化，支持单条覆写
   - `spine/routines_ops_learn.py`：learn 写入前做矛盾检测，矛盾时 Update 旧条目而非 append

   **核心缺口**：目前只有 C（create）和 R（read），缺 Update（矛盾覆写）和 Delete（智能清除）

### 阶段二：Skills Campaign（第一个正式 Campaign）

```
Milestone 1  collect → 抓取 ClawHub skills 清单（描述、star、更新时间）
Milestone 2  analyze → 对比现有 31 个 skills，识别缺口与可替代项
Milestone 3  review + render → 输出"skill 引入优先级报告"（双语）
Milestone 4  用户确认 → build agent 执行安装 + V2 包装（GitHub PR 流）
```

同时是：系统第一次真实 Campaign 压力测试。

### 阶段三：冒烟测试（Skills 就绪后）

验证端到端链路全部跑通：

| 任务 | 类型 | 验收点 |
|---|---|---|
| 总结一个 URL | Pulse | events.jsonl 有 task_completed |
| 技术主题小报告 | Thread / research_report | playbook.db total_runs +1 |
| 写一个小工具脚本 | Thread / dev_project | runtime_hints best_methods runs > 0 |
| 整合几条笔记 | Thread / knowledge_synthesis | 用户评价写入 memory（human 来源）|

每个任务完成后填写快速评价。

### 阶段四：正式暖机 + 周报启动

- 每种 cluster 各跑 3-5 个任务，大小混搭
- 约 10 个任务后检查 `weave_patterns/` 是否有新 pattern
- 启动每周前沿扫描定时任务
- 检查 hot/warm/cold tier 分化、P95 延迟基线

### 阶段五：Tailscale 接入（低优先级，按需）

- 修改 `openclaw.json` gateway.tailscale.mode
- Portal/Console 外网访问鉴权

---

## 关键约束

1. **机制升级 Campaign 的 build 产物必须走 GitHub PR**，不允许直接写本地
2. **周报简报**推 Telegram，Portal 可查看全文
3. **CRUD memory** 在 Skills Campaign 之前落地，确保暖机数据质量
4. **Tailscale** 不阻塞主线，随时可插入
