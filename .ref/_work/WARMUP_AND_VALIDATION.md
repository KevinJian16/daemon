# Daemon 暖机与系统标定方案

> 日期：2026-03-13
> 状态：设计完成，待执行
> 前置：TODO.md Phase 0-5 全部完成
> 执行者：Opus（作为用户分身）

---

## §0 暖机的本质

暖机不是初始化，不是连通性检查，不是跑几个测试场景。

**暖机 = 系统标定。目标是让 daemon 的所有对外输出达到"伪人"水准。**

"伪人"定义：daemon 产出的任何内容——文本、代码、发布到外部平台的内容、通知——与用户本人亲手做的无法区分。外部接收方不会怀疑这是 AI 产出。

暖机由 AI（Opus，作为用户分身）全程主导：设计测试任务、提交执行、评估产出、调整系统参数、迭代直到收敛。用户只在暖机完成后检查对外接口。

---

## §1 前置条件

暖机开始前，以下必须全部就绪：

### 1.1 基础设施（Phase 1 产出）
- [ ] Docker Compose 全部服务运行且健康
  - PostgreSQL（+ pgvector 扩展已安装）
  - Redis
  - MinIO（offerings bucket 已创建）
  - Temporal Server + UI
  - Plane（API + Frontend + Worker + Beat）
  - Langfuse（+ ClickHouse）
- [ ] `.env` 文件所有连接信息正确
- [ ] 宿主机 → Docker 网络连通（Python 进程能访问所有容器服务）

### 1.2 对象映射 + 胶水层（Phase 2 产出）
- [ ] `services/plane_client.py` — Plane API 客户端可用
- [ ] `services/plane_webhook.py` — Webhook handler 就绪
- [ ] `services/event_bus.py` — PG LISTEN/NOTIFY 就绪
- [ ] `services/store.py` — PG 数据层就绪，所有表已创建
- [ ] Plane Workspace + 默认 Project 已初始化
- [ ] Plane webhook 指向 daemon API 且签名验证通过

### 1.3 执行层（Phase 3 产出）
- [ ] Temporal Activities 读写 Plane API + PG（不再读写 JSON 文件）
- [ ] Temporal Schedules 已注册（所有 Spine routines）
- [ ] Herald 已删除，envoy 出口就绪
- [ ] Langfuse 接收 trace 数据
- [ ] MinIO 文件上传/下载正常

### 1.4 知识层（Phase 4 产出）
- [ ] NeMo Guardrails 规则配置就绪（config/guardrails/ Colang 规则）
- [ ] Persona 初始模板文件存在（warmup/about_me.md），内容待暖机填充
- [ ] Mem0 服务可用，agent_id 隔离正常
- [ ] pgvector knowledge_cache 表就绪
- [ ] RAGFlow 服务运行正常
- [ ] source_tiers.toml 配置完成
- [ ] sensitive_terms.json 配置完成（NeMo input rail 依赖）

### 1.5 Agent 层（Phase 5 产出）
- [ ] 7 个 OC agent workspace 配置正确
- [ ] 每个 agent 可被 Temporal Activity 调用
- [ ] envoy 可通过 OC Telegram channel 发送消息
- [ ] envoy 可通过 GitHub MCP server 执行操作
- [ ] scholar 可通过搜索 MCP server 获取外部知识
- [ ] 每个 agent 的 MEMORY.md 模板就绪（内容待暖机填充）
- [ ] 每个 agent 至少有 3-5 个核心 skill 草稿就绪（见 §9.5 准备流程）
  - scholar 已搜索各 agent 领域最新最佳实践
  - artificer 已将外部资料改写为 SKILL.md 格式
  - 用户已审阅 skill 草稿方向正确

### 1.6 Python 环境
- [ ] API 进程可启动（FastAPI）
- [ ] Worker 进程可启动（Temporal Worker）
- [ ] OC gateway 运行中
- [ ] `~/.openclaw → daemon/openclaw/` 软链接存在
- [ ] 所有 LLM provider API key 已配置且可用

---

## §2 暖机阶段

### Stage 0：信息采集（~15 分钟）

**目的**：获取用户的完整画像，建立"分身"能力。

向用户收集：
1. **身份信息**——职业、专业领域、日常工作内容
2. **写作风格样本**——至少 3-5 篇用户亲手写的中文/英文文本（放入 `warmup/writing_samples/`）
3. **自我描述**——用户对自己做事方式、沟通风格、质量标准的描述（`warmup/about_me.md`）
4. **外部平台账号**——daemon 需要发布到哪些平台（GitHub, intervals.icu, 等）
5. **偏好与禁忌**——什么样的输出你喜欢，什么你绝对不能接受
6. **真实任务示例**——你日常会给 daemon 什么样的任务？举 3-5 个真实例子

### Stage 1：Persona 标定（~20 分钟）

**目的**：让 daemon 的 Persona 与用户一致。

1. **分析写作样本**——调用 LLM 一次性生成 Persona，写入 Mem0：
   - 身份画像（identity：职业、专业领域、做事方式）
   - 跨语言写作结构偏好
   - 中文风格特征
   - 英文风格特征
   - 以 `user_persona` agent_id 写入 Mem0，供所有 agent 检索

2. **写入 Agent MEMORY.md**——每个 agent 注入（≤300 tokens）：
   - Guardrails 核心规则摘要
   - identity 摘要
   - 任务偏好
   - scribe/envoy 额外加 style 摘要
   - counsel 额外加 planning hints

3. **Persona 验证**——让 scribe 写一段短文，让 envoy 写一条对外消息，对比用户原始风格
   - 不通过 → 调整 Mem0 persona → 重试
   - 通过 → 进入下一阶段

### Stage 2：链路逐通（~30 分钟）

**目的**：每条数据链路独立验证，确保信号从源头到终点完整传递。

每条链路的验证方法：**源头写入 → 传输 → 读取 → 消费 → 外部可见结果**。不是检查"函数存在"，是检查"数据真的到了"。

#### 2.1 核心执行链路
| # | 链路 | 验证方法 |
|---|---|---|
| L01 | 用户在 Plane 创建 Issue → webhook → daemon 收到 | 创建 Issue，检查 daemon 日志有 webhook 记录 |
| L02 | daemon 触发 Temporal Workflow → Activity 执行 | 提交一个最简单的 Job，检查 Temporal UI 有 workflow |
| L03 | Activity 调用 OC agent → agent 返回结果 | 用 scholar 做一次简单搜索，检查返回内容 |
| L04 | Job 状态写回 Plane | 检查 Plane Issue 的 comment/activity 有 Job 记录 |
| L05 | Job paused（requires_review）→ 用户 Temporal Signal → job_closed 事件 | 模拟 requires_review Signal，检查 PG 事件和下游 Task 触发 |

#### 2.2 知识链路
| # | 链路 | 验证方法 |
|---|---|---|
| L06 | scholar 搜索 → Knowledge Base 写入 → 下次命中 | 搜索一个 query，检查 PG knowledge_cache 有缓存记录，再搜同一 query 确认命中 |
| L07 | Persona 注入 → agent 产出风格一致 | 给 scribe 同一指令跑两次，检查风格一致性 |
| L08 | Guardrails 拦截 → 违规操作被阻止 | 尝试触发一条 Guardrails 规则，确认被拒绝 |
| L09 | Mem0 写入 → Job 完成后记忆条目可查 | 完成一个 Job，检查 Mem0 有对应记忆条目 |

#### 2.3 外部出口链路
| # | 链路 | 验证方法 |
|---|---|---|
| L10 | envoy → OC Telegram channel → 用户收到消息 | 发一条测试消息，确认 Telegram 收到 |
| L11 | envoy → GitHub MCP → repo 有变更 | 创建一个测试 issue 或 commit |
| L12 | Offering → MinIO → 可下载 | 上传一个测试文件，通过 URL 下载验证 |
| L13 | Job 执行 → Langfuse 有完整 trace | 检查 Langfuse Dashboard 有 trace 且层级完整 |

#### 2.4 调度链路
| # | 链路 | 验证方法 |
|---|---|---|
| L14 | Temporal Schedule 触发 → Spine routine 执行 | 创建一个短间隔 Schedule，等一个周期，检查执行记录 |
| L15 | Task 依赖链 → 前序 Job closed 后触发后序 | 创建两个 Task（blocked_by 关系），完成前序 Job，检查后序自动触发 |

#### 2.5 事件链路
| # | 链路 | 验证方法 |
|---|---|---|
| L16 | PG LISTEN/NOTIFY → 订阅方收到事件 | 在一个进程 NOTIFY，另一个进程确认收到 |
| L17 | Plane webhook 签名验证 → 伪造请求被拒绝 | 发一个错误签名的 webhook，确认 403 |

### Stage 3：测试任务套件 + Skill 校准（~2-3 小时）

**目的**：通过真实复合场景验证产出质量达到"伪人"标准；同时校准每个 agent 的 skill，直到 token 用量稳定、arbiter 通过率达标。

**Skill 校准是 Stage 3 的核心工作量。** 每个任务执行后，通过 Langfuse 检查每个 Step：token 是否超标？步骤是否按 skill 执行？输出是否被 arbiter 接受？不达标的 Step 定位到具体 skill，修改后重跑同类任务，迭代到稳定。

#### 3.1 任务设计原则

- **真实场景**：不是合成测试，是用户实际会提交的任务
- **复合性**：一个任务通常跨多个 agent、多个领域、多个外部出口
- **覆盖面**：确保每个 agent 在多个任务中被调用，每个 skill 至少被触发一次
- **领域多样**：技术、健康、写作、数据分析、项目管理……
- **对外发布**：任务产出不是存在系统内，而是发布到外部平台

#### 3.2 测试任务矩阵

任务在 Stage 0 信息采集后根据用户的实际领域和平台设计。以下是框架：

| 维度 | 覆盖项 |
|---|---|
| **领域** | 用户的专业领域 × 至少 3 个不同领域 |
| **Agent 组合** | 单 agent、双 agent 协作、全链路（counsel→scholar→artificer→scribe→envoy） |
| **触发方式** | 手动、定时、前序链 |
| **产出类型** | 代码、文档、数据分析报告、对外发布内容、通知/邮件 |
| **外部出口** | GitHub（commit/PR）、Telegram、其他用户平台 |
| **持续性** | 一次性任务、需要长期跟踪的任务（定时 + 状态积累） |

#### 3.3 任务示例框架（真实任务在 Stage 0 后设计）

**示例 A：跨域研究 + 发布**
- 用户意图：「调研 X 领域最新进展，写一份报告，发布到 Y 平台」
- 涉及 agent：counsel(规划) → scholar(搜索) → scholar(分析) → scribe(撰写) → envoy(发布)
- 验证点：搜索质量、分析深度、文风一致性、发布格式正确

**示例 B：代码任务 + review + 提交**
- 用户意图：「给 Z 项目实现 W 功能，提交 PR」
- 涉及 agent：counsel(规划) → artificer(编码) → arbiter(review) → envoy(提交 PR)
- 验证点：代码质量、review 准确性、PR 描述的"伪人"程度

**示例 C：长期跟踪任务**
- 用户意图：「制定 X 计划，发布到 Y 平台，每周更新」
- 涉及 agent：counsel(规划) → scholar(数据) → scribe(撰写) → envoy(发布)
- 触发：首次手动，后续定时（Temporal Schedule）
- 验证点：定时触发准确、每次更新内容连贯、外部平台内容格式一致

**示例 D：并发 + 依赖链**
- 在一个 Project 中创建多个 Task（blocked_by 依赖）
- 同时触发多个不阻塞的 Task
- 验证：排队行为正确、依赖顺序严格、并发不互相干扰

#### 3.4 评估方法

每个任务的产出从以下维度评估：

| 维度 | 标准 | 方法 |
|---|---|---|
| **伪人度** | 外部接收方无法区分是 AI 还是人 | 逐条审查对外输出的措辞、格式、细节 |
| **风格一致性** | 与用户写作风格匹配 | 对比 Mem0 Persona 和实际产出 |
| **内容准确性** | 事实正确、逻辑通顺、无幻觉 | 交叉验证关键事实（用 scholar 二次搜索） |
| **格式正确性** | 发布到目标平台的内容格式无误 | 检查实际发布结果 |
| **完整性** | 任务要求的所有部分都完成了 | 对照原始 Brief 逐项检查 |
| **及时性** | 执行耗时在合理范围内 | 记录 Job 启动到完成的时间 |

评估不合格时的处理：
1. 定位问题源头（Persona？agent prompt？DAG 设计？模型能力？搜索质量？）
2. 调整对应参数
3. 重新执行相同或类似任务
4. 再次评估

### Stage 4：系统状态测试（~30 分钟）

**目的**：验证非正常状态下系统行为正确，不会产出垃圾或卡死。

| # | 状态 | 模拟方法 | 预期行为 |
|---|---|---|---|
| S01 | **并发参数校准** | 逐步提高并发 Job 数，观察 LLM rate limit / 机器负载边界 | 确定 `maxChildrenPerAgent` / `maxConcurrent` 最佳值并固化到 `openclaw.json`；排队有序、不丢任务、不死锁 |
| S02 | **Agent 超时** | 给 agent 一个需要很长时间的任务 | runTimeoutSeconds 触发，Job 转 failed，envoy 通知用户 |
| S03 | **Agent 产出不合格** | 故意给一个模糊指令，arbiter 应该拒绝 | arbiter 评分低 → 触发 rework 而非直接交付 |
| S04 | **rework 循环** | 连续 rework 同一 Job | rework 次数有上限（Guardrails），超限转 failed |
| S05 | **外部 API 不可用** | 临时关闭 Telegram bot / GitHub token 失效 | envoy 报错但不崩溃，Job 记录失败原因，系统继续运行 |
| S06 | **数据库压力** | 大量并发读写 PG | 无死锁、无数据丢失、响应时间可接受 |
| S07 | **Temporal Worker 重启** | 杀掉 Worker 进程再启动 | 进行中的 workflow 恢复执行，不丢失进度 |
| S08 | **Plane webhook 延迟** | 模拟 webhook 延迟到达 | 系统幂等处理，不重复创建 Job |
| S09 | **定时任务积压** | 暂停 Worker 一段时间再恢复 | Temporal Schedule catchup 补执行，不漏 |
| S10 | **Knowledge Base 缓存过期** | 手动标记缓存过期 | 下次搜索重新 fetch，不返回旧数据 |

### Stage 5：收敛判定

**目的**：确认系统进入稳态，可以接受真实工作。

#### 5.1 收敛标准

| 维度 | 标准 |
|---|---|
| **伪人度** | 连续 5 个不同类型任务的对外产出全部通过伪人评估 |
| **风格一致性** | scribe/envoy 在不同任务中的文风无明显漂移 |
| **系统稳定性** | Stage 4 所有状态测试通过，无未处理异常 |
| **链路完整** | Stage 2 所有链路验证通过 |
| **外部出口** | 每个配置的外部平台至少成功发布一次 |

#### 5.2 就绪判定

| 级别 | 条件 | 系统状态 |
|---|---|---|
| **Ready** | Stage 2-5 全部通过 | GREEN — 可接受真实任务 |
| **Degraded** | Stage 3/4 有 ≤2 项不通过但非关键 | YELLOW — 可接受简单任务，限制并发 |
| **Not Ready** | Stage 2 有链路不通 或 Stage 3 伪人度不达标 | RED — 不可投入使用 |

#### 5.3 暖机报告

暖机完成后生成报告存入 `state/warmup_report.json`：

```json
{
  "warmup_utc": "2026-03-14T...",
  "duration_minutes": 240,
  "status": "ready",
  "voice_iterations": 2,
  "tasks_executed": 12,
  "tasks_passed": 12,
  "system_state_tests": 10,
  "system_state_passed": 10,
  "link_tests": 17,
  "link_tests_passed": 17,
  "issues_found": [...],
  "adjustments_made": [...]
}
```

---

## §3 暖机执行流程

```
Stage 0: 信息采集
  │ 向用户收集：身份、写作样本、偏好、平台、真实任务示例
  │ 存入 warmup/ 目录
  ▼
Stage 1: Persona 标定
  │ LLM 分析样本 → 写入 Mem0 persona
  │ 写入 agent MEMORY.md
  │ scribe/envoy 试写 → 对比 → 不通过则调整重试
  ▼
Stage 2: 链路逐通（17 条链路）
  │ 每条链路：源头→传输→终点→外部可见
  │ 不通过 → 修复 → 重验
  ▼
Stage 3: 测试任务套件
  │ 根据 Stage 0 信息设计 8-15 个真实复合任务
  │ 逐个执行 → 评估 → 不通过则调整 → 重试
  │ 迭代直到连续 5 个通过
  ▼
Stage 4: 系统状态测试（10 个场景）
  │ 并发/超时/rework/故障恢复/积压...
  │ 不通过 → 修复 → 重验
  ▼
Stage 5: 收敛判定
  │ 全部通过 → Ready（GREEN）
  │ 部分通过 → Degraded（YELLOW）
  │ 关键链路不通或伪人度不达标 → Not Ready（RED）
  ▼
生成暖机报告 → state/warmup_report.json
```

---

## §4 暖机基础设施

### 4.1 目录结构

```
warmup/
  writing_samples/       ← 用户写作样本（Stage 0 收集）
    sample_01.md
    sample_02.md
    ...
  about_me.md            ← 用户自我描述（Stage 0 收集）
  task_designs/           ← 暖机测试任务设计（Stage 3 生成）
    task_01.json
    task_02.json
    ...
  results/                ← 任务执行结果和评估（Stage 3 产出）
    task_01_result.json
    task_02_result.json
    ...
```

### 4.2 暖机脚本

`scripts/warmup.py` 不是"一键跑完"的脚本。它是暖机过程的工具集：

```python
# 前置检查
python scripts/warmup.py preflight        # 验证 §1 前置条件

# Stage 1
python scripts/warmup.py persona-init     # 分析样本，写入 Mem0 persona
python scripts/warmup.py persona-verify   # scribe/envoy 试写，评估风格

# Stage 2
python scripts/warmup.py link-test        # 逐条链路验证
python scripts/warmup.py link-test L06    # 单条链路重验

# Stage 3（由 Opus 手动驱动，不是脚本自动跑）
# Opus 设计任务 → 提交到 Plane → daemon 执行 → Opus 评估

# Stage 4
python scripts/warmup.py stress-test      # 系统状态测试

# Stage 5
python scripts/warmup.py report           # 生成暖机报告
```

Stage 3 不能自动化——因为 Opus 需要根据每个任务的结果决定下一步做什么（调整 Persona？改 agent 配置？重新设计任务？）。这是暖机中最核心、最耗时的部分。

---

## §5 废弃术语确认

暖机文档中不再使用以下旧术语：

| 旧术语 | 状态 | 替代 |
|---|---|---|
| errand / charge / endeavor | **废弃** | 不再按复杂度分级任务 |
| glance / study / scrutiny | **废弃** | 不再按深度分级知识检索 |
| Folio / Slip / Deed / Move | **废弃** | Project / Task / Job / Step |
| Writ | **废弃** | Task blocked_by 依赖（Plane IssueRelation） |
| Psyche / Instinct / Voice / Preferences | **废弃** | Guardrails / Persona（Mem0）|
| Ledger / Lore / SourceCache | **废弃** | Langfuse / Knowledge Base（RAGFlow + pgvector） |
| Ether | **废弃** | PG LISTEN/NOTIFY |
| Herald | **废弃** | envoy + OC channel |
| Cadence | **废弃** | Temporal Schedules |
| Trail | **废弃** | Langfuse |
| Portal | **废弃** | Plane 前端 |
| Console | **废弃** | Plane 管理界面 |
| Vault | **废弃** | MinIO |

---

## §6 关键约束

1. **暖机期间不接受真实任务**——暖机产出可能发布到外部平台（测试账号或专门的测试环境）
2. **暖机产出可以删除**——Stage 3 的测试任务发布到外部后，如果不合格可以删除/撤回
3. **LLM 成本**——Stage 1 Persona 初始化约 1 次 LLM 调用。Stage 3 每个测试任务消耗正常 Job 的 token。预计总暖机成本 ≈ 10-15 个正常 Job 的 token 量
4. **暖机可中断恢复**——每个 Stage 的结果持久化，中断后可从断点继续
5. **暖机结果是系统状态的一部分**——Mem0 persona、agent MEMORY.md 都是暖机的产出，暖机后它们成为系统的永久配置
