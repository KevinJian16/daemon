# Skill: TODO 全面更新

## 目标
把 SYSTEM_DESIGN.md（七稿）§0-§10 + REFERENCE 附录的每条功能需求映射到 TODO 项，重点关注 openclaw 层。

## 输入
- `.ref/SYSTEM_DESIGN.md` — 唯一权威文档
- `.ref/SYSTEM_DESIGN_REFERENCE.md` — 附录 B-I
- `.ref/_work/TODO.md` — 当前 TODO（需要更新）
- 代码目录：`services/`, `temporal/`, `runtime/`, `config/`, `openclaw/`

## 步骤

### Phase 1: 读设计文档，按 section 提取需求
用 subagent 逐段读 SYSTEM_DESIGN.md，每段产出：
- 功能需求列表（每条一行，标明 section 编号）
- 写入 `.ref/_work/TODO_DRAFT.md`

分段：
1. §0-§1（概述 + 术语）
2. §2（对象模型 + 数据层）
3. §3（Agent 角色 + 执行模型）
4. §4（场景 + 交互 + Telegram + Portal）
5. §5（基础设施：Temporal/PG/MCP/Mem0/Langfuse 等）
6. §6（安全 + Guardrails）
7. §7（暖机）
8. §8（运维 + 监控）
9. §9（Skill 体系）
10. §10（禁止事项 — 不产生 TODO，仅作 checklist）
11. REFERENCE 附录 B-I

### Phase 2: 对比现有代码，标注状态
用 subagent 检查每条需求在代码中的实现状态：
- ✅ 已实现（函数存在 + 逻辑正确）
- 🔨 部分实现（框架在但逻辑 stub/不完整）
- ❌ 未实现（代码不存在）
- 🔧 需修改（实现存在但与七稿不一致）

特别关注 openclaw 层：
- `openclaw/workspace/*/SOUL.md` — agent 人格是否与 §3 一致
- `openclaw/workspace/*/TOOLS.md` — 工具列表是否完整
- `openclaw/skills/*/SKILL.md` — skill 定义是否与 §9 一致
- `openclaw/openclaw.json` — 配置是否与设计一致

### Phase 3: 写入最终 TODO.md
按优先级排列：
- 🔴 CRITICAL — 系统不能运行
- 🟠 HIGH — 核心功能缺失
- 🟡 MEDIUM — 功能不完整
- 🟢 LOW — 优化/打磨

格式：`- [ ] [优先级] [Section] 描述 — 影响范围`

## 进度追踪
每完成一个 phase/section，更新 `.ref/_work/TODO_PROGRESS.md`：
```
Phase 1 §0-§1: ✅ done
Phase 1 §2: ⏳ in progress
...
```

## 恢复指南（compact 后读这里）
1. 读 `.ref/_work/TODO_PROGRESS.md` 查看进度
2. 读 `.ref/_work/TODO_DRAFT.md` 查看已完成的分析
3. 从上次中断的 section 继续
4. 用 subagent 避免主窗口溢出
