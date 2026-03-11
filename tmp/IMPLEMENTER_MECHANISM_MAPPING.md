# Implementer Mechanism Mapping

> 仅供实现者迁移与删旧使用。  
> 不是权威文档，不给 auditor 当依据，不进入 `.ref` 权威链。

## 1. 核心对象映射

| 旧对象/旧语义 | 新对象/新语义 | 迁移动作 |
|---|---|---|
| 旧 `Deed`（任务本体层） | `Slip` | 所有“任务载体”“长期存在对象”“对话页对象”改到 `Slip` |
| 旧 `Deed`（执行实例层） | `Deed` | 所有“单次运行”“一次执行结果”“Temporal run 实例”保留到 `Deed` |
| `Dominion` | `Folio` | 所有主题容器、组织容器、归组容器全部改到 `Folio` |
| `Lane` / 旧 chain | `Writ` | 所有事件到动作规则统一收口到 `Writ` |
| 未完成对话 / voice session 草稿 | `Draft` | 所有未成札前的候选对象都显式化成 `Draft` |

## 2. 复杂度映射

| 旧概念 | 新机制位置 | 迁移动作 |
|---|---|---|
| `errand` | 删除为正式对象 | 不再决定前台对象形态 |
| `charge` | 单 `Slip` 上限与默认基线 | 只在实现迁移时借用旧数值，不保留概念本体 |
| `endeavor` | `Folio + 多 Slip + Writ` | 删除为正式对象；旧 workflow 只作为临时代码迁移目标 |

## 3. 交互层映射

| 旧前台理解 | 新前台理解 |
|---|---|
| `Deed = Chat Session` | `Slip = 对话页` |
| 大任务 = `Endeavor` 页面 | 大任务 = `Folio` 卷页 |
| task 类型分三种前台物种 | 只有 `Slip` 和 `Folio` 两种前台对象 |
| 按钮控制优先 | 对话 + 直接操作优先 |

## 4. 数据与字段扫描重点

遇到这些字段或概念时，优先检查是否还在用旧语义：

- `deed_id`
- `dominion_id`
- `endeavor`
- `complexity`
- `work_scale`
- `campaign`
- `lane`
- `track`
- `run`

### 新字段主集

- `draft_id`
- `slip_id`
- `folio_id`
- `writ_id`
- `deed_id`

## 5. 文件和模块扫描重点

重点检查这些类型的旧残留：

1. 旧容器语义  
   `dominion_*`, `track_*`

2. 旧任务本体语义  
   把 `deed` 当长期对象、对话对象、前台对象

3. 旧复杂度三分  
   `errand / charge / endeavor`

4. 旧前台范式  
   `Deed = Chat Session`

## 6. 删除原则

1. 不保留双轨命名
2. 不保留“以后再删”的旧壳
3. 新代码不再引入旧词
4. 旧词只允许存在于：
   - 一次性迁移逻辑
   - Git 历史

## 7. 实施时自检问题

每次改代码时先问：

1. 这里的对象到底是 `Draft`、`Slip`、`Folio`、`Writ` 还是 `Deed`？
2. 这里是不是还把 `Deed` 当任务本体？
3. 这里是不是还把 `Folio` 当旧 `Dominion` 的别名，而不是新正式对象？
4. 这里是不是还让 `errand / charge / endeavor` 决定正式机制？
5. 这里改完后，旧壳是不是已经可以删掉？
