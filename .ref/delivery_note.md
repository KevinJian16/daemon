> ⚠️ 警告：此文档已作废，禁止查看。请仅以 `/.ref/daemon_统一方案_v2.md` 为唯一权威来源。

# Daemon 交付说明（2026-03-04）

## 1. 结论

- 代码侧关键缺口已继续补齐：事件桥一致性、调度自适应语义、CLI 可用性、Worker 启动阻塞点（Temporal sandbox 导入链）已修复。
- 我已做过一轮真实启动验收（Daemon OpenClaw Gateway / API / Worker / Telegram Adapter / 关键 Console API / submit 真实失败语义）。
- 验收临时日志与结果文件全部放在 `/tmp`，并已删除；`daemon/` 内未新增测试脚本与测试结果文档。

## 2. 本轮新增修复

1. `runtime/event_bridge.py`
- 修复“consume 即前移游标”导致崩溃时丢事件的问题。
- 游标状态改为 `offset + pending + acked`，实现可恢复消费与幂等 ack。

2. `services/scheduler.py`
- adaptive 间隔改为基于 `learning_rhythm` + routine offset（`witness`/`learn` 保持相对偏移）。
- cron `day-of-month/day-of-week` 语义修正为标准 OR 逻辑（Vixie 语义）。

3. `interfaces/cli/main.py`
- 修复 `health/chat` 命令参数签名导致的 CLI 直接报错。
- `outcomes` 时间字段输出统一优先 `delivered_utc`。

4. `temporal/__init__.py`
- 去除重导入 activities/worker 的副作用，修复 Worker 启动时 workflow sandbox 校验失败。

5. 其他
- `fabric/compass.py` 的 snapshot 连接管理修复。
- `interfaces/telegram/adapter.py` 入口改为 `uvicorn.run(app, ...)`，避免模块路径依赖问题。

## 3. 运行依赖就绪性（实测）

| 依赖 | 结论 | 说明 |
|---|---|---|
| Python/venv | 就绪 | `.venv` 可运行 API/Worker/Adapter |
| Temporal Server | 就绪 | `127.0.0.1:7233` 可连通 |
| OpenClaw Gateway（daemon） | 就绪 | 可用 daemon config 在 `18790` 启动并响应 |
| Daemon API | 就绪 | `uvicorn services.api:create_app --factory` 可启动 |
| Daemon Worker | 就绪 | `temporal/worker.py` 可启动并注册 workflow/activity |
| Telegram Adapter | 就绪 | `interfaces/telegram/adapter.py` 可启动并返回 `/health` |

## 4. 启动命令（最终建议）

1. 先准备环境变量（含 `.env`）：
- `DAEMON_HOME=/Users/kevinjian/daemon`
- `OPENCLAW_HOME=/Users/kevinjian/daemon/openclaw`
- `PYTHONPATH=/Users/kevinjian/daemon`

2. 启动 daemon 专用 OpenClaw Gateway（示例）
```bash
OPENCLAW_CONFIG_PATH=/Users/kevinjian/daemon/openclaw/openclaw.json \
OPENCLAW_HOME=/Users/kevinjian/daemon/openclaw \
/Users/kevinjian/daemon/node_modules/.bin/openclaw gateway run --port 18790 --bind loopback --token <daemon_token>
```

3. 启动 Worker
```bash
/Users/kevinjian/daemon/.venv/bin/python /Users/kevinjian/daemon/temporal/worker.py
```

4. 启动 API
```bash
/Users/kevinjian/daemon/.venv/bin/python -m uvicorn services.api:create_app --factory --host 127.0.0.1 --port 8000
```

5. 可选：启动 Telegram Adapter
```bash
DAEMON_API_URL=http://127.0.0.1:8000 \
/Users/kevinjian/daemon/.venv/bin/python /Users/kevinjian/daemon/interfaces/telegram/adapter.py
```

## 5. 关键验收事实摘录

- `POST /submit`：
  - Temporal 可用时返回 `status=running`（实测）。
  - Temporal 不可用（探针 API 使用 `TEMPORAL_PORT=9999`）返回 `HTTP 503` + `error_code=temporal_unavailable`（实测）。
- `GET /console/schedules`：返回 `next_run_utc`，`witness/learn` 间隔按新 adaptive 语义可解释（实测）。
- `GET /console/traces/{trace_id}`：返回 `cortex_summary`（实测）。
- 事件桥：Worker 侧写入 `task_completed` 后，API 侧可消费并触发 `spine.record`（实测）。
- CLI：`health` 命令可直接执行（实测）。

## 6. 清理确认

- `/tmp` 下本轮验收日志与结果文件已删除。
- daemon 内 probe 任务/trace/telemetry/临时 policy 项已清理回收。
- 当前仅保留系统运行所需文件与 `.ref` 文档。

## 7. 对“是否已就绪”的直接回答

- 是：在上述依赖满足并按启动顺序拉起后，系统可以进入可工作状态。
- 不是“零依赖即开箱”：仍需要你本机的 Temporal、daemon 专用 OpenClaw Gateway、以及至少一个可用 LLM key。
