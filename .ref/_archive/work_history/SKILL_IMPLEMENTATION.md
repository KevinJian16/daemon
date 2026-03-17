# Skill: daemon 实现工作

## 目标
从 TODO.md 出发，按优先级实现 daemon 系统的所有功能。

## 文档关系图

```
.ref/SYSTEM_DESIGN.md          ← 唯一权威设计文档（七稿）
    │                              §0 治理规则
    │                              §1 术语+对象模型
    │                              §2 数据层+外部出口+知识获取+信息监控(§2.7.1)
    │                              §3 执行模型+Session+DAG
    │                              §4 交互+客户端+API+消息协议+Telegram
    │                              §5 知识+Persona+Guardrails+Quota
    │                              §6 基础设施+运行时
    │                              §7 暖机+体检+自愈
    │                              §8 学习机制
    │                              §9 Skill 体系
    │                              §10 禁止事项(43条)
    │
    ├── .ref/SYSTEM_DESIGN_REFERENCE.md  ← 配套查表文档
    │       附录 B: 运行时参数默认值 (B.1-B.8)
    │           B.7: MCP Server 完整配置表(24个)
    │           B.8: 信息监控参数
    │       附录 C: PG 表结构 (C.1-C.10)
    │           C.10: info_subscriptions
    │       附录 D: 接口契约 (D.1-D.7)
    │           D.1: API 端点(11个)
    │           D.7: 对话流消息协议(8种类型)
    │       附录 E: DEFAULT 条目
    │       附录 F: UNRESOLVED 条目（当前为空）
    │       附录 G: Gap 吸收情况
    │       附录 I: 设计决策日志 (DD-01 ~ DD-73)
    │
    └── .ref/_work/  ← 工作文档（设计讨论产出）
            TODO.md                 ← 主任务清单（🔴12 🟠25 🟡50 🟢15 + Design Specs）
            TODO_PROGRESS.md        ← TODO 审计进度（已完成）
            TODO_DRAFT.md           ← §0-§3 需求提取
            TODO_DRAFT_4_6.md       ← §4-§6 需求提取
            TODO_DRAFT_7_10.md      ← §7-§10+附录 需求提取
            TODO_AUDIT_PYTHON.md    ← Python 层审计结果
            TODO_AUDIT_OPENCLAW.md  ← OC 层审计结果
            CLIENT_SPEC.md          ← 桌面客户端规格（已审批）
            EXTERNAL_INTEGRATIONS.md ← 外部集成清单（已审批）
            INFO_ARCHITECTURE.md    ← 信息监控架构（已审批）
            SKILL_TODO_UPDATE.md    ← TODO 审计 skill（已完成）
            SKILL_IMPLEMENTATION.md ← 本文件（实现 skill）
```

## 代码目录结构

```
daemon/
├── services/           ← Python 层：API + 胶水服务
│   ├── api.py              API 主入口（FastAPI + OC gateway 生命周期）
│   ├── api_routes/         路由（scenes, admin 等）
│   ├── store.py            PG 数据层
│   ├── plane_client.py     Plane API 客户端
│   ├── event_bus.py        PG LISTEN/NOTIFY
│   └── session_manager.py  L1 OC session 管理
├── temporal/           ← Worker 进程：Temporal workflows + activities
│   ├── workflows.py
│   ├── activities.py
│   ├── activities_exec.py
│   ├── activities_herald.py
│   └── activities_health.py
├── runtime/            ← 运行时辅助
│   └── mcp_dispatch.py     MCP server 分发
├── config/             ← 配置
│   ├── mcp_servers.json    MCP server 配置（当前7个，目标24个）
│   ├── spine_registry.json
│   └── ...
├── mcp_servers/        ← 自写 MCP server 实现
│   ├── semantic_scholar.py
│   ├── firecrawl_scrape.py
│   ├── code_functions.py
│   └── paper_tools.py
├── openclaw/           ← OC agent 层（双层系统的第二层）
│   ├── openclaw.json       OC 主配置
│   ├── package.json        OC 本地安装
│   └── workspace/          10 个 agent 配置
│       ├── copilot/        L1: SOUL.md, TOOLS.md, AGENTS.md, USER.md, SKILL_GRAPH.md
│       ├── mentor/         L1
│       ├── coach/          L1
│       ├── operator/       L1
│       ├── researcher/     L2
│       ├── engineer/       L2
│       ├── writer/         L2
│       ├── reviewer/       L2
│       ├── publisher/      L2
│       └── admin/          L2
├── scripts/            ← 启停脚本
│   ├── start.py
│   └── (需要: restore.py, verify.py)
├── tests/              ← 测试（68个）
├── persona/            ← Persona 文件
│   └── stage0_interview.md
└── client/             ← 桌面客户端（待创建）
    └── (Electron app)
```

## 工作优先级

### 第一批：🔴 CRITICAL（系统不能运行）
详见 TODO.md 🔴 section，12 项。核心是：
1. MinIO client + Artifact API
2. requires_review + pending_confirmation flow
3. Plane writeback compensation
4. Chain trigger dispatch
5. OAuth authentication
6. NeMo Guardrails 正确接入
7. SOUL.md 全部重写
8. Routing Decision schema
9. Electron 客户端骨架
10. Job → Plane Issue state mapping
11. restore.py
12. Structured routing output

### 第二批：🟠 HIGH（核心功能缺失）
详见 TODO.md 🟠 section，~25 项。

### 第三批：🟡 MEDIUM + 🟢 LOW + Design Specs
详见 TODO.md 对应 section。

### 第四批：Warmup（Stage 1-4）
所有 🔴 解决后启动。

## 关键约束
- **双层系统**：每次改 Python → 检查 OC 层联动
- **文档先行**：改代码前确认设计文档一致
- **链路验证**：函数存在 ≠ 链路成立，必须端到端验证
- **不猜不试**：不确定的先查文档/web search

## 恢复指南（compact 后读这里）
1. 读本文件了解全局
2. 读 `.ref/_work/TODO.md` 看当前任务清单
3. 读 MEMORY.md 看用户偏好和反馈
4. 从 TODO.md 中最高优先级未完成项继续
5. 用 subagent 做大范围搜索/审计，避免主窗口溢出
