# .ref/ 文档导航

## 当前工作文档（按优先级）

| 文档 | 用途 | 状态 |
|---|---|---|
| **`daemon_统一方案_v2.md`** | 唯一设计权威。所有实现决策以此为准，冲突时以本文件胜出 | 持续更新 |
| **`NEXT_PHASE_PLAN.md`** | 当前阶段工作计划（v2 收尾 → UX → 暖机 → Skills）| 持续更新 |
| **`UX_SPEC.md`** | UX 偏好规范：设计语言、界面分野、评价体系、Telegram/Portal 职责 | 持续更新 |
| **`CLAUDE.md`** | Claude Code 构建指南，技术栈约束与代码规范 | 稳定 |

## 归档文档（`_archive/`）

历史参考，**不作为实施依据**：

- `HANDOFF_TODO.md` — 上轮开发交接清单，已完成，归档
- `daemon_系统设计方案_ddbc4981.plan.md` — 原始骨架设计，已被 v2 继承
- `action_plan.md` — 旧行动计划，已废弃
- `gap_analysis.md` — 旧 gap 分析，已废弃
- `delivery_note.md` — 历史交接记录
- `MEMORY.md` — 旧记忆文件，已由自动记忆系统接管

## 权威顺序

```
daemon_统一方案_v2.md  >  CLAUDE.md  >  其他
```

如有冲突，v2 文档说了算。
