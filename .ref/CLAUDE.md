> ⚠️ 警告：此文档已作废，禁止查看。请仅以 `/.ref/daemon_统一方案_v2.md` 为唯一权威来源。

# Daemon 构建指南 — Claude Code 专用

## 项目概述

从零构建 Daemon（新一代多智能体系统），替代当前目录下的旧 MAS 系统。

- **设计方案**：`.cursor/plans/daemon_系统设计方案_ddbc4981.plan.md` — 唯一的设计权威，所有实现决策以此为准
- **新代码目录**：`daemon/` — 所有 Daemon 代码放在这个新目录下
- **旧代码目录**：`src/`、`mas_api/` — 仅供参考，不可直接复制

---

## 技术栈

- Python 3.11+
- FastAPI（API 框架 + WebSocket）
- `temporalio`（Python Temporal SDK）
- SQLite（标准库 `sqlite3`，三个 Fabric 各一个 DB）
- HTTP 与 OpenClaw Gateway 通信（端口 18789，`Authorization: Bearer {token}`）
- 不需要 Redis、PostgreSQL 或任何外部数据库
- 前端：轻量 HTML + JS（Portal 和 Console），不使用 React/Vue 等框架

---

## 关键约束

### 文件规范

- 单个 Python 文件不超过 800 行
- 不生成内联 HTML/CSS/JS（前端文件独立放在 `interfaces/` 下）
- 环境变量 `DAEMON_HOME` 作为根路径，所有文件路径运行时解析
- **绝对禁止**硬编码 `/Users/kevinjian/mas/` 或任何用户特定路径

### 代码风格

- 不写多余注释（不要 `# Import module`、`# Define function` 这类）
- 注释只解释非显而易见的意图或约束
- 不要 `try/except: pass` — 所有异常至少记入 trace
- 类型标注：所有公开函数和方法都加 type hints

### 旧代码参考规则

参考旧代码前，**必须先阅读设计方案第十四章"参考旧代码时的风险清单"**。以下是高风险项摘要：

| 禁止带入的模式 | 旧代码位置 |
|-------------|-----------|
| 硬编码路径 `/Users/kevinjian/mas/` | server.py, activities.py, runtime.py 等 10+ 文件 |
| `try/except: pass` 静默异常 | workflows.py, activities.py 多处 |
| 字符串子串匹配判断返工路径 | workflows.py L340-360 |
| tasks.json read-modify-write 无锁 | activities.py + server.py |
| 双通道通信（HTTP + CLI 混用） | activities.py + openclaw_gateway.py |
| 超时/重试/并发数硬编码 | workflows.py, activities.py 全局常量 |

### 值得参考的旧代码

| 逻辑 | 位置 | 注意事项 |
|------|------|---------|
| DAG Kahn 排序 + 并发控制 | `src/temporal/workflows.py` L135-270 | 核心算法成熟，但 retry/timeout 参数需从 Playbook 读取 |
| OpenClaw session 调用和轮询 | `src/temporal/activities.py` activity_openclaw_step | 只参考 HTTP 路径，不要带入 CLI 路径 |
| 质量门禁检查 | `src/temporal/activities.py` activity_finalize_outcome | HTML 密度、domain 覆盖检查可参考 |
| Outcome 交付 + PDF | `src/temporal/activities.py` L5907+ | 文件复制和 PDF 生成逻辑可参考 |

---

## OpenClaw Gateway 协议

这是最复杂的集成点。Daemon 统一使用 **HTTP 方式**与 Gateway 通信。

### 配置来源

```python
# 从 openclaw.json 读取
import json
from pathlib import Path

openclaw_home = Path(os.environ.get("OPENCLAW_HOME", "openclaw"))
config = json.loads((openclaw_home / "openclaw.json").read_text())
gateway_url = f"http://127.0.0.1:{config['gateway']['port']}"
gateway_token = config["gateway"]["auth"]["token"]
```

### 核心接口

```python
headers = {"Authorization": f"Bearer {gateway_token}", "Content-Type": "application/json"}

# 调用工具（发送消息给 Agent）
POST {gateway_url}/tools/invoke
Body: {"tool": "sessions_send", "args": {"session_key": "agent:collect:task:xxx", "message": "..."}}

# 读取 Agent 回复
POST {gateway_url}/tools/invoke
Body: {"tool": "sessions_history", "args": {"session_key": "agent:collect:task:xxx", "limit": 1}}

# Agent 异步调用（提交任务后轮询）
openclaw gateway call --agent {agent_id} --session-key {key} --message {msg} --wait-ms {ms}
→ 不要用这个 CLI 方式，改用 HTTP invoke_tool 实现等价逻辑
```

### Session Key 格式

```
agent:{agent_id}:task:{task_id}:{step_id}
```

---

## 构建顺序

**严格按 Phase 顺序执行。每个 Phase 完成后必须可独立测试。**

### Phase 1：地基（Fabric + Spine + Cortex）

完成标志：
- 三个 Fabric（Memory / Playbook / Compass）能 CRUD + Query + Stats
- Playbook 和 Compass 包含 bootstrap 种子数据
- 10 个 Spine Routines 能手动触发（纯确定性的能实际运行，混合的能 mock Cortex）
- Nerve 能 emit/on/recent
- Cortex 能 complete/embed/try_or_degrade

测试：pytest，SQLite in-memory

### Phase 2：引擎（Temporal + OpenClaw）

完成标志：
- 一个完整 DAG 能通过 Temporal 跑通
- Agent 能通过 Gateway HTTP 调用和轮询
- Skills 已按 Agent 归属分发到各自 workspace
- 双向桥接工作：Spine 能读 Agent 产出、relay 能写回 Snapshot

前置：Gateway 和 Temporal Server 已在运行

### Phase 3：服务

完成标志：
- API 进程能接收 /submit 和 /chat 请求
- Worker 进程独立运行 Temporal Worker
- Scheduler 能触发 Spine Routine
- Delivery 能归档产出到 outcome/ + 发送 Telegram
- ~/Outcome 软链接已创建

### Phase 4：界面

完成标志：
- Console 能显示系统总览、Spine Dashboard、Fabric Explorer
- Portal 能 Chat、浏览 Outcome、查看 Timeline
- Telegram 适配器工作

---

## 冷启动 Bootstrap

首次启动时（Fabric DB 不存在）：

1. 创建三个 Fabric SQLite DB
2. 写入 Playbook 种子：从 `config/langgraph_templates/` 读取 4 个 DAG 模板（research_report、knowledge_synthesis、dev_project、personal_plan），注册为 active method
3. 写入 Compass 种子：从旧 `config/` 下的 JSON 文件提取默认值（领域优先级、质量 profile、资源预算、用户偏好）
4. 校验 OpenClaw 环境：
   - `openclaw.json` 的 agents.list 包含全部 7 个 Agent（router, collect, analyze, build, review, render, apply）
   - 各 Agent 的 workspace 目录存在
   - Gateway 可达

---

## 部署模型

```
[Daemon API]          ← FastAPI + Scheduler + Spine + Nerve（Python 进程 1）
    ↕ gRPC
[Temporal Server]     ← 工作流引擎（外部 Go 进程）
    ↕ gRPC
[Daemon Worker]       ← Temporal Worker + Activities（Python 进程 2）
    ↕ HTTP
[OpenClaw Gateway]    ← Agent 管理（外部 Node.js 进程）
```

两个 Python 进程不直接通信，通过 Temporal 和共享文件系统协作。

---

## 目录结构速查

```
daemon/
  fabric/          # Memory / Playbook / Compass
  spine/           # Registry / 10 Routines / Contracts / Nerve / Trace
  runtime/         # temporal.py / openclaw.py / cortex.py
  temporal/        # workflows.py / activities.py / worker.py
  services/        # api.py / scheduler.py / dispatch.py / delivery.py / dialog.py
  interfaces/      # portal/ / console/ / telegram/ / cli/
  outcome/         # 产出物存储（~/Outcome 软链接指向此处）
  config/          # spine_registry.json / system.json
  state/           # gate.json / traces/ / snapshots/
  tests/
```
