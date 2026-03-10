# Daemon 术语权威

> 日期：2026-03-10  
> 本文档规定 Daemon 的正式术语、中文显示名、英文 canonical name、旧新机制映射与显示规则。  
> `config/lexicon.json` 必须与本文档保持一致。

---

## 0. 总原则

### 0.1 只有一套正式术语

当前正式事项机制只有这一组对象：

- `Draft`
- `Slip`
- `Folio`
- `Writ`
- `Deed`

Portal 和 Console 都使用同一套正式术语，不再把“用户面术语”和“系统面术语”人为拆成两套世界。

### 0.2 代码与界面分层

- 代码、日志、存储、字段、API 使用 **英文 canonical names**
- Portal 与 Console 使用 **固定中文显示名**
- 英文 canonical names 仍然是唯一的代码层和存储层命名

### 0.3 词义必须稳定

所有正式术语必须满足：

1. 一词一义
2. 不与其它正式对象重叠
3. 前台、后台、文档三处含义一致
4. 不允许今天换一种普通说法、明天再换另一种

---

## 1. 正式事项机制术语

| 英文 canonical name | 中文显示名 | 定义 |
|---|---|---|
| `Draft` | 草稿 | 尚未成札、但已经被系统识别并可继续收敛的候选事项 |
| `Slip` | 签札 | 持续存在的最小可持久化任务对象 |
| `Folio` | 卷 | 收纳并组织若干 `Slip` 的主题容器 |
| `Writ` | 成文 | 写在 `Folio` 中、对事件作出响应的规则 |
| `Deed` | 行事 | 据某张 `Slip` 发生的一次具体执行 |

### 1.1 五个对象的严格边界

- `Draft` 不是一段临时聊天，而是真实系统对象
- `Slip` 不是一次执行，而是任务载体
- `Folio` 不是大号 `Slip`，而是容器
- `Writ` 不是任务，也不是容器，而是规则
- `Deed` 不是任务本体，而是一次执行实例

### 1.2 五个对象的职责边界

| 对象 | 职责边界 |
|---|---|
| `Draft` | 只承载成札前的候选事项与收敛过程 |
| `Slip` | 只承载任务本体、计划和长期身份 |
| `Folio` | 只承载主题容器与组织关系 |
| `Writ` | 只承载事件到对象动作的规则 |
| `Deed` | 只承载一次具体执行实例 |

---

## 2. 其它核心系统术语

### 2.1 心智层

| 英文 canonical name | 中文显示名 | 定义 |
|---|---|---|
| `Psyche` | 心智 | 系统总心智层 |
| `Memory` | 记忆 | 事实与知识记忆 |
| `Lore` | 阅历 | 经验与过往做法 |
| `Instinct` | 本能 | 偏好、倾向与默认值 |

### 2.2 治理层

| 英文 canonical name | 中文显示名 | 定义 |
|---|---|---|
| `Spine` | 脊柱 | 自主神经系统 |
| `Nerve` | 神经 | 事件总线 |
| `Cortex` | 皮层 | 推理与 embedding 能力层 |
| `Trail` | 踪迹 | 可追溯执行痕迹 |
| `Canon` | 典籍 | routine 定义与注册表 |
| `Pact` | 契约 | 结构化输入输出契约 |

### 2.3 执行与编排层

| 英文 canonical name | 中文显示名 | 定义 |
|---|---|---|
| `Voice` | 对话 | 意图收敛与计划形成 |
| `Will` | 意志 | 决策、富化与执行前判断 |
| `Cadence` | 节律 | 调度与周期推进 |
| `Herald` | 传告 | 物流与交付搬运 |
| `Brief` | 简报 | 任务说明与约束 |
| `Design` | 设计 | 执行方案与 DAG |
| `Move` | 步 | `Design` 中的一个执行节点 |
| `Retinue` | 随从 | 预创建执行实例池 |
| `Ward` | 结界 | 系统级健康门控 |
| `Ration` | 配给 | 资源额度与配额 |
| `Ether` | 以太 | API 进程与 Worker 之间的桥接层 |

### 2.4 产出与存储层

| 英文 canonical name | 中文显示名 | 定义 |
|---|---|---|
| `Offering` | 献作 | 面向主人的正式交付物 |
| `Vault` | 宝库 | 审计、留存与归档存储 |
| `Ledger` | 账簿 | 结构化状态记录 |

### 2.5 角色层

| 英文 canonical name | 中文显示名 |
|---|---|
| `Counsel` | 参谋 |
| `Scout` | 斥候 |
| `Sage` | 贤者 |
| `Artificer` | 工匠 |
| `Arbiter` | 仲裁 |
| `Scribe` | 书记 |
| `Envoy` | 使节 |

### 2.6 例行与界面

| 英文 canonical name | 中文显示名 |
|---|---|
| `Routine` | 例行 |
| `Portal` | 门户 |
| `Console` | 控制台 |
| `Telegram` | Telegram |
| `CLI` | CLI |
| `Skill` | 技能 |
| `Lexicon` | 词典 |

### 2.7 正式 routine 名

| 英文 canonical name | 中文显示名 | 定义 |
|---|---|---|
| `pulse` | 脉察 | 基础健康巡检例行 |
| `record` | 记录 | 把行事结果写回阅历的例行 |
| `witness` | 见证 | 观察趋势、提取信号、形成偏好的例行 |
| `learn` | 学习 | 把可复用知识抽入记忆的例行 |
| `distill` | 提炼 | 压缩、衰减与清整记忆的例行 |
| `focus` | 聚焦 | 调整系统关注重点的例行 |
| `relay` | 转递 | 负责快照与上下文转递的例行 |
| `tend` | 照料 | 负责清理、提交、轮转与维护的例行 |
| `curate` | 策藏 | 负责归档与藏库整理的例行 |

---

## 3. 命名与显示规则

### 3.1 Portal 与 Console 的显示规则

- Portal 与 Console 都显示**中文正式术语**
- 如需精确对照，可在次级说明或词典里展示英文 canonical name

### 3.2 代码与存储规则

以下场景统一使用英文 canonical name：

- Python / TypeScript 标识符
- JSON 字段
- SQLite 字段
- 文件名与目录名
- REST path / WebSocket payload
- 日志与审计记录

### 3.3 不强行翻译的内容

以下内容不纳入正式中文术语翻译：

1. 外部专有名词  
   例如：`Temporal`、`Telegram`、`OpenClaw`、模型名、Provider 名

2. 实现级标识  
   例如：`id`、文件路径、环境变量、HTTP / WebSocket、workflow id、session key

3. 原始用户内容  
   用户自己的文本、标题、附件名、文件名不做术语层强翻译

---

## 4. 对象命名规范

### 4.1 ID

所有正式对象都使用全局唯一 ID：

- `draft_id`
- `slip_id`
- `folio_id`
- `writ_id`
- `deed_id`

ID 只承担身份意义，不承担顺序或数值语义。

### 4.2 Slug

Portal 的可公开路由使用 `slug`，不使用内部 ID。

规则：

1. 标题允许重复
2. `slug` 必须唯一
3. 标题重命名时保留 `slug_history`
4. 旧 `slug` 不复用

### 4.3 复合命名

| 类型 | 规范 | 示例 |
|---|---|---|
| 状态字段 | `_status` | `slip_status` |
| 输入对象 | `Input` | `DeedInput` |
| 输出对象 | `Output` | `DeedOutput` |
| 完成事件 | `_completed` | `deed_completed` |
| 失败事件 | `_failed` | `deed_failed` |
| 根目录 | `_root` | `deed_root` |
| 配置对象 | `Config` | `WritConfig` |

---

## 5. 当前术语治理要求

从现在起，任何实现、设计、审计都不得再做以下事情：

1. 把 `Slip` 和 `Deed` 再次混成一个对象
2. 把 `Folio` 降成普通列表容器
3. 在 Portal / Console / 文档里混用多套同义词
4. 给同一正式对象发明多个普通替代词

若新增系统概念，必须先更新：

1. `TERMINOLOGY.md`
2. `config/lexicon.json`

再更新代码与界面显示。
