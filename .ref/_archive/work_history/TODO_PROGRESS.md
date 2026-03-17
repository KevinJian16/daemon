# TODO 更新进度

## Phase 1: 提取需求
- [x] §0-§1（概述 + 术语）
- [x] §2（对象模型 + 数据层）
- [x] §3（Agent 角色 + 执行模型）
- [x] §4（场景 + 交互 + Telegram + Portal）→ `TODO_DRAFT_4_6.md`
- [x] §5（知识 + Persona + Guardrails + Quota）→ `TODO_DRAFT_4_6.md`
- [x] §6（基础设施 + 运行时契约）→ `TODO_DRAFT_4_6.md`
- [x] §7（暖机 + 可观测性 + 自愈）→ `TODO_DRAFT_7_10.md`
- [x] §8（学习机制）→ `TODO_DRAFT_7_10.md`
- [x] §9（Skill 体系）→ `TODO_DRAFT_7_10.md`
- [x] §10（禁止事项 checklist）→ `TODO_DRAFT_7_10.md`
- [x] REFERENCE 附录 B-I → `TODO_DRAFT_7_10.md`

## Phase 2: 代码对比
- [x] Python 层（services/ temporal/ runtime/）→ `TODO_AUDIT_PYTHON.md`（88 ✅ / 32 🔨 / 52 ❌ / 14 🔧）
- [x] OpenClaw 层（workspace/ skills/ openclaw.json）→ `TODO_AUDIT_OPENCLAW.md`
- [x] 配置层（config/ .env docker-compose）— 合并入 Python + OC audit

## Phase 3: 写入 TODO.md
- [x] 最终合并 + 排序 — 2026-03-16 完成
  - 12 CRITICAL items, ~25 HIGH, ~50 MEDIUM, ~15 LOW, 5 CLEANUP groups
  - 45 禁止事项 checklist (§10)
  - Deduped Python + OC audit into single items where applicable
