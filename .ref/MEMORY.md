# Daemon 项目记忆

## 项目基础

- **位置**：`/Users/kevinjian/daemon/`
- **方案文档**：`/Users/kevinjian/mas/.cursor/plans/daemon_系统设计方案_ddbc4981.plan.md`
- **构建指南**：`/Users/kevinjian/mas/.cursor/plans/CLAUDE.md`
- **旧代码参考**：`/Users/kevinjian/mas/src/`（仅参考，不可直接复制）
- **openclaw.json 位置**：`/Users/kevinjian/daemon/openclaw/openclaw.json`

## 关键架构约定

- `DAEMON_HOME` 默认 = `Path(__file__).parent`（即 daemon/ 目录），无需设置
- `OPENCLAW_HOME` 不需要设置；Python 代码默认 `daemon_home / "openclaw"`
- openclaw 进程本身查找 `~/.openclaw/`，因此 `~/.openclaw → daemon/openclaw/` 软链接是必须的（不是多余的）
- 两个 Python 进程：**API 进程**（FastAPI+Scheduler+Spine）和 **Worker 进程**（Temporal+Activities）
- 两进程不直接通信，通过 Temporal 和共享文件系统协作

## 代码规范

- `except Exception: pass` 禁止；异常至少 `logger.warning(...)` 或 `activity.logger.warning(...)`
- Temporal activity 内部方法用 `activity.logger`，普通 service 用模块级 `logger = logging.getLogger(__name__)`
- 不写多余注释，不硬编码路径

## .env 配置

- 已创建 `/Users/kevinjian/daemon/.env`，包含真实的 API keys
- MINIMAX_GROUP_ID = 2021048365067805608（native MiniMax API 需要，Anthropic-compatible 端点不需要）
- Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID 均已配置

## 已完成的工作

### Phase 1-4 全部实现（代码层面）
- fabric/ (memory.py, playbook.py, compass.py)
- spine/ (routines.py, nerve.py, contracts.py, registry.py, trace.py)
- runtime/ (cortex.py, openclaw.py, temporal.py)
- temporal/ (workflows.py, activities.py, worker.py)
- services/ (api.py, scheduler.py, dispatch.py, delivery.py, dialog.py)
- interfaces/ (portal/index.html, console/index.html, telegram/adapter.py, cli/main.py)
- bootstrap.py

### 已修复的 try/except 问题
- activities.py: _update_outcome_index、_update_task_status（加了 activity.logger.warning）
- api.py: list_tasks、get_task、list_outcomes、console_overview（加了 logger.warning）
- dialog.py: _extract_plan（加了 logger.debug）

### Console 已添加
- Agent Manager 面板（调用 GET /console/agents）
- Schedule Manager 面板（调用 GET /console/schedules，有 Run 按钮）
- 对应的 /console/agents 端点已在 api.py 实现

## 功能差距（详见 gap_analysis.md）

完整分析见：`memory/gap_analysis.md`

### 最关键问题（P0）
1. **Nerve 跨进程断裂**：Worker 进程的 delivery_completed 无法触发 API 进程的 spine.record，整个学习闭环失效
2. **replay handler 缺失**：tend 发出 task_replay 但没有 handler 接收
3. **delivery.py._update_index 仍有静默 except**（activities.py 版本已修复，delivery.py 版本漏掉了）
4. **Contracts 未调用**：check_contract() 定义了但 routines.py 里没有调用

### 重要缺失（P1）
- witness/learn 没有读 OpenClaw 会话日志（透明内化是空壳）
- Scheduler Nerve handler 未注册（所有 nerve_triggers 无效）
- relay 缺少 runtime_hints.txt 回写
- Skill Evolution 面板缺失（Console）

### Console API 缺失端点（约14个）
- /console/fabric/memory*、/console/fabric/playbook*
- /console/fabric/compass/budgets、/console/fabric/compass/signals
- /console/policy/*（CRUD + versions + rollback）
- /console/agents/{agent}/skills*
- /console/traces/{trace_id}
- /console/spine/nerve/events
- /console/cortex/usage

### Portal 缺失
- Timeline 视图
- 字段名错误：读 archived_utc 但 index.json 存 delivered_utc
- HTML 报告预览失败（找 report.md 但存的是 report.html）

## 工作量估算

约 13-17 工程天，主要在跨进程机制（3-4天）、透明内化（2-3天）、Console（5-7天）。
