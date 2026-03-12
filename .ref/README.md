# .ref 文档总则

## 0. 这份 README 的作用

这是 `.ref/` 的入口文档。

它只负责四件事：

1. 说明当前**六份权威文档**各自做什么
2. 规定文档之间的权威顺序
3. 记录当前重构工作的推进顺序
4. 说明审计文档和历史归档文档的角色

无论是实现者还是审计者，都应先读本文件。

---

## 1. 当前六份权威文档

当前正式权威文档为六份：

1. `TERMINOLOGY.md`
2. `INTERACTION_DESIGN.md`
3. `DESIGN_QA.md`
4. `EXECUTION_MODEL.md`
5. `daemon_实施方案.md`
6. `README.md`

`config/lexicon.json` 是术语词典的**机器可读数据源**，受 `TERMINOLOGY.md` 约束，服务于 Console 词典和术语显示。

### 1.1 各文档职责

| 文档 | 职责 | 主要使用者 |
|---|---|---|
| `README.md` | 文档治理入口。说明权威关系、推进顺序、审计定位、归档规则 | 实现者 / 审计者 |
| `TERMINOLOGY.md` | 术语权威。规定正式对象、中文显示名、英文 canonical name、旧新机制映射 | 实现者 / 审计者 |
| `INTERACTION_DESIGN.md` | 交互权威。规定 Portal / Console / Telegram 的对象语义、行为语法、风格与边界 | 实现者 / 审计者 |
| `DESIGN_QA.md` | 细节确认文档。记录已确认的机制细节、边界和例外；与实施方案冲突时以 QA 为准 | 实现者 / 审计者 |
| `EXECUTION_MODEL.md` | 执行模型权威。Move/Session/Deed/Folio 的运行机制与状态模型；与实施方案冲突时以本文档为准 | 实现者 / 审计者 |
| `daemon_实施方案.md` | 全机制说明书与实施规范。给出对象模型、事件流、存储、执行、学习与界面映射的正式落地方案 | 实现者 / 审计者 |

---

## 2. 当前机制的正式对象

当前正式事项机制已经切换为：

- `Draft`
- `Slip`
- `Folio`
- `Writ`
- `Deed`

这意味着：

1. `Slip` 是任务载体，`Deed` 是执行实例
2. `Folio` 是正式主题容器
3. 所有事项先成一张 `Slip`，超限再开 `Folio`
4. Portal 与 Console 都要服从同一套对象机制与同一套交互语法

在这一轮重构里，任何过时残余都应被消除，不与当前机制并存。

---

## 3. 权威顺序

六份权威文档的职责不同，但它们共同构成当前的正式依据。

冲突处理顺序如下：

1. 术语冲突：以 `TERMINOLOGY.md` 为准
2. 交互冲突：以 `INTERACTION_DESIGN.md` 为准
3. 机制细节冲突：以 `DESIGN_QA.md` 为准
4. 执行模型冲突：以 `EXECUTION_MODEL.md` 为准
5. 实施细节冲突：以 `daemon_实施方案.md` 为准
6. `README.md` 只负责解释这种权威关系，不单独定义机制细节

`config/lexicon.json` 只承担术语数据源角色，不单独推翻或新增术语定义。

---

## 4. 当前工作顺序与进度

### 已完成

1. **权威文档重写**：六份权威文档已反映当前机制现实
2. **术语全量重命名**：代码、API、存储全部切换到新术语
3. **后台对象模型**：Draft / Slip / Folio / Writ / Deed 已落地
4. **执行模型重构**：Move/Session/Deed 执行机制、状态两层模型、Direct Move
5. **知识层重构（Part 1）**：Psyche 六组件（Instinct / Voice / Preferences / Rations / Ledger / SourceCache），删除旧 Memory / Lore / learn / distill

### 进行中

6. **Portal 前端**：前端开发中，基于六份权威文档实现
7. **Console 前端**：待 Portal 稳定后启动

### 待做

8. **全系统验收脚本**（`.ref/_work/REFACTOR_KNOWLEDGE_AND_WARMUP.md` §17-§19）：前后端都完成后编写
9. **暖机流程**（§20-§23）：校准参数，验收后实施
10. **删旧与回归验证**：最终清理

---

## 5. 工作文档

`.ref/_work/` 存放进行中的工作文档，不是权威文档：

| 文件 | 用途 |
|------|------|
| `REFACTOR_KNOWLEDGE_AND_WARMUP.md` | 知识层重构实施方案（Part 1 已完成，Part 2/3 待做） |
| `OC_DOCS_REFERENCE.md` | OpenClaw 官方文档本地缓存 |

工作文档与权威文档冲突时，一律以六份权威文档为准。

> 旧归档文档（`DESIGN_QA_v1_archive.md`、`daemon_统一方案_v2_archive.md`、`MECHANISM_AUDIT.md`）已删除。

---

## 7. 当前提醒

当前最容易出错的地方有四个：

1. 把 `Deed` 重新混回“任务本体 + 执行实例”的双重角色
2. 把 `Folio` 做成普通列表容器，而不是正式主题对象
3. 重新引入多套并列任务类型作为主机制
4. 把 Portal / Console 各自做成一套不同的对象世界

另一个高风险误区是把前端风格理解成“可选偏好”。

当前正式约束是：

- Portal = Claude 静态 + Apple app 层级动态 + 文件系统式对象组织
- Console = Claude 静态 + Apple app 层级动态

这条约束属于正式交互机制的一部分，不是视觉润色建议。

如果发现机制定义冲突，优先修正文档权威的一致性，再修代码。
