# Daemon SOP 设计（Standard Operating Procedures）

> **日期**：2026-03-17
> **依据**：Stage 0 Interview + SYSTEM_DESIGN.md 七稿 + 行业/学术标准工作流调研
> **目标**：定义 daemon 应该主动驱动的用户工作流程，不只是被动响应指令

---

## 0. 核心原则

daemon 不只是工具集合——它是用户的**工作流引擎**。用户在 interview 中明确说：

> "不要入门水平的解释——给正确的工作流和 SOP，上手就能干"

SOP 分三条主线，对应用户的三个目标：
1. **Research SOP** — 从零到博士生级研究能力
2. **Engineering SOP** — 3 年+工程师级开源能力
3. **Life SOP** — 运动/健康/信息管理

三条主线共享一个**知识基础设施**：Obsidian vault + Zotero + Mem0。

---

## 1. Research SOP（学术研究流程）

### 1.1 Build-First 研究周期

用户的研究路径：**Build → Literature Mapping → Write（如果值得写）**

```
┌─────────────────────────────────────────────────────────┐
│                    BUILD 周期（4-16 周）                   │
│                                                         │
│  Phase 1: Build（engineer 主导）                          │
│    构建系统/工具 → 发现有趣的问题/现象                        │
│         ↓                                               │
│  Phase 2: Literature Mapping（researcher 主导）            │
│    定位工作在学术图谱中的位置 → 确认 novelty                   │
│         ↓                                               │
│  Phase 3: Formalize（researcher + writer）                │
│    假设 → 实验设计 → 对照实验 → 消融实验                      │
│         ↓                                               │
│  Phase 4: Write（writer 主导 + reviewer 审查）              │
│    论文撰写 → 自审 → 外部反馈 → arXiv → 会议投稿             │
│         ↓                                               │
│  Phase 5: Publish（publisher）                            │
│    GitHub 开源代码 + arXiv 论文 + 技术博客                   │
└─────────────────────────────────────────────────────────┘
```

**daemon 职责**：
- **Phase 1 → Phase 2 自动触发**：copilot 检测到 engineer 完成一个 build 周期后，自动提醒"该做 literature mapping 了"
- Phase 2 由 researcher 组合调用四个学术源（Semantic Scholar + OpenAlex + CrossRef + CORE）
- Phase 4 的 reviewer 模拟审稿（按 ICML/NeurIPS 四维标准：Soundness/Presentation/Significance/Originality）

### 1.2 Literature Review 流程

```
发现论文（Semantic Scholar / arXiv alerts / Google Scholar）
    ↓
存入 Zotero（浏览器 connector 一键保存）
    ↓
在 Zotero 内置阅读器中读 + 标注（高亮 + 批注）
    ↓
Obsidian Zotero Integration 插件自动导入为文献笔记
    ↓
用户在文献笔记下方写自己的理解（Literature Note）
    ↓
提取原子洞察为 Permanent Note（Zettelkasten）
    ↓
双向链接建立知识图谱
```

**Obsidian 笔记层级**：

| 类型 | 位置 | 生命周期 | 内容 |
|---|---|---|---|
| Fleeting Note | `vault/daily/` | 24 小时内处理 | 碎片想法 |
| Literature Note | `vault/references/` | 永久 | 每篇论文一个笔记：元数据 + 标注 + 自己的理解 |
| Permanent Note | `vault/knowledge/` | 永久 | 一个原子想法，用自己的话写，密集链接 |
| MOC (Map of Content) | `vault/knowledge/` | 持续更新 | 主题索引，连接相关 Permanent Notes |

### 1.3 论文写作流程

**标准 ML/AI 论文结构**：

| 章节 | 页数（8页论文） | 内容 |
|---|---|---|
| Abstract | ~0.25 | 问题 → 方法 → 关键结果（一个数字）|
| Introduction | 1-1.5 | CARS 模型：建立领域 → 指出空白 → 占据空白 |
| Related Work | 1-1.5 | 按主题组织（不按时间），说明与每类工作的区别 |
| Method | 2-2.5 | 完整技术描述，足以复现 |
| Experiments | 2-2.5 | 数据集 + 基线 + 指标 + 主实验 + 消融 |
| Conclusion | 0.5 | 贡献总结 + 明确说明局限 |

**LaTeX 工作流**：本地 TeX Live + VS Code（LaTeX Workshop 扩展）。BibTeX 从 Zotero 自动导出。

**发表路径**：arXiv preprint → Workshop（4-6 页，轻审查）→ Main venue（ICML/NeurIPS/ICLR，8-9 页）

### 1.4 CFP Tracking

daemon 的 researcher 应该监控会议截稿日期：
- 数据源：mldeadlines.com（可导出 .ics）
- 自动在 T-8 周、T-4 周、T-1 周提醒
- 倒推计划：T-8 周实验完成 → T-4 周论文初稿 → T-2 周内审完成

**主要会议年历**：

| 月份 | 截稿 | 会议时间 |
|---|---|---|
| 1 月 | ICML | 7 月 |
| 5 月 | NeurIPS | 12 月 |
| 9 月 | ICLR | 4 月（次年） |
| 2/6 月 | ACL/EMNLP（ARR 滚动） | 7-8/11 月 |

### 1.5 Peer Review 自审清单

投稿前，reviewer agent 按以下维度模拟审稿：

| 维度 | 检查点 |
|---|---|
| **Soundness** | 每个 claim 有 evidence？实验有 error bar？基线公平？消融完整？ |
| **Presentation** | 非子领域专家能看懂 intro？图表可读？符号一致？ |
| **Significance** | 问题重要吗？结果超过 SOTA？局限明确？ |
| **Originality** | 新在哪？和最近的工作区别清楚？ |

### 1.6 Independent Researcher 特殊 SOP

没有导师/实验室，以下需要 daemon 替代：

| 实验室成员有的 | daemon 替代方案 |
|---|---|
| 导师反馈 | reviewer agent 模拟审稿 + mentor 引导 |
| 论文阅读组 | researcher 每周推送 2-3 篇推荐论文 + 要点摘要 |
| 内审 | reviewer agent + 外部征求反馈（ML Collective） |
| arXiv 背书 | researcher 帮找 endorser（查 arXiv 论文页面） |
| 学术社交 | publisher 帮管 Twitter/X 学术讨论 |

---

## 2. Engineering SOP（工程开发流程）

### 2.1 开源项目生命周期

```
Idea → MVP Build（2-6 周）→ Launch → Community → Maintenance
```

每个项目必须有的文件：
- `README.md`（第一天就写）
- `LICENSE`（MIT 或 Apache 2.0）
- `CONTRIBUTING.md`
- `CHANGELOG.md`（keepachangelog.com 格式）
- `.github/workflows/ci.yml`（CI/CD）
- `.github/ISSUE_TEMPLATE/`
- `.github/PULL_REQUEST_TEMPLATE.md`

10K+ LOC 项目额外需要：
- `ARCHITECTURE.md`（高层代码地图）
- `docs/`（详细文档）
- `ADR/`（架构决策记录）

### 2.2 Code Review 方法论

**三遍法**（daemon mentor 教用户学会 review）：

| 遍数 | 时间 | 看什么 |
|---|---|---|
| Pass 1: 扫读 | 2-5 分钟 | 意图、范围、PR 描述 |
| Pass 2: 深读 | 10-30 分钟 | 正确性、架构、安全、性能、测试、错误处理 |
| Pass 3: 打磨 | 5 分钟 | 命名、可读性、文档 |

评论标记法：`issue:`（必须改）/ `suggestion:`（建议）/ `nit:`（小事）/ `question:`（提问）/ `praise:`（做得好）

### 2.3 技术博客写作

**结构模板**（"I Built X" 类型，最常用）：
1. Hook：问题是什么（1-2 句）
2. Context：现有方案为什么不行
3. Architecture：高层设计 + 图
4. Implementation：关键代码片段 + 决策取舍
5. Results：性能数据、截图、经验教训
6. What's Next：路线图

**发布节奏**：2 篇/月（可持续且能建立动量）
**分发渠道**：个人网站（主）→ Dev.to + Hashnode（cross-post）→ Twitter/X + Reddit

### 2.4 GitHub Profile 建设

- Profile README（bio + 当前项目 + tech stack badges）
- 6 个 pinned repos（展示广度和深度）
- 每日保持绿色贡献图（文档/重构也算）
- 参与其他项目的 review 和 PR

### 2.5 工程能力提升路径

**每周**：读一个优秀项目的源码（Redis/SQLite/PyTorch 等）
**每月**：从零实现一个小系统（KV store / task queue / HTTP server）+ 写博客
**每季度**：实现一篇经典论文（Raft / MapReduce / Attention）+ meetup 分享

**Junior → Senior 关键区别**：

| 维度 | Junior | Senior |
|---|---|---|
| 模糊性 | 需要清晰 spec | 从模糊需求定义 spec |
| 范围 | 单功能 | 跨系统 |
| 影响 | 个人产出 | 团队乘数（mentor + review + 架构） |

---

## 3. Life SOP（生活管理流程）

### 3.1 信息获取策略（三层推送）

来自 interview §3 的设计：

| 层级 | 频率 | 内容 | daemon 职责 |
|---|---|---|---|
| **实时层** | 0-2 条/天 | 紧急/时效性事件（CFP deadline、依赖 breaking change） | Telegram 即时推送 |
| **日报层** | 每天固定时间 | 当日巡检摘要，按领域分类 | InfoPull → researcher triage → Telegram |
| **周报层** | 每周 | 趋势分析，literature mapping 级归纳 | Background Maintenance → system_snapshot |

**信息源配置**：
- 学术：arXiv daily（cs.LG / cs.AI / cs.CL），Semantic Scholar feeds，Google Scholar alerts
- 工程：HackerNews top 10 / Reddit r/programming / RSS feeds（限 25-50 个）
- 领域：各领域关键会议 proceedings RSS

**规则**：
- 收集是免费的，阅读是昂贵的——大量存入 read-later，定时处理
- 每周固定 5 小时阅读预算，用完就停
- 每季度清理 20% 最低价值的信息源

### 3.2 运动/健康整合

来自 interview §3 的设计——每天 1-2h（室内）到 5-6h（户外）运动：

| 工具 | 用途 |
|---|---|
| Strava | 记录运动 |
| intervals.icu | 训练负荷分析（CTL/ATL/TSB）+ 计划制定 |
| Google Calendar | 运动计划和工作安排联动 |

coach agent 职责：
- 读取运动数据（Strava/intervals.icu MCP）
- 生成周计划执行率
- 推送策略与运动计划联动（interview §3："推送策略应与 coach 管理的运动计划联动"）

### 3.3 每日/每周/每月 Review

| 频率 | 时长 | 内容 |
|---|---|---|
| **每日（晨）** | 5 min | 看日历、处理 inbox、定当天 1-3 件必做 |
| **每日（晚）** | 5 min | 记录完成情况、清空碎片想法、关机仪式 |
| **每周** | 60 min | GTD 三步：清空 → 更新 → 创造。处理所有 inbox、更新项目状态、设定下周目标 |
| **每月** | 90 min | 审视季度目标进展、修剪项目列表、清理知识库孤岛笔记、调整信息源 |

### 3.4 英文渐进浸泡

来自 interview §3：

| 规则 | 执行 |
|---|---|
| daemon 技术内容全英文输出 | writer / researcher 的 SOUL.md 强制英文 |
| 用户输入不限语言 | L1 接受中文，输出英文 |
| 不懂就问 | 用中文解释具体概念，不整篇翻译 |
| 所有对外产出从第一天起全英文 | publisher 强制 |
| 英文写作经 LanguageTool 检查 | mentor 场景，每次输出后 LanguageTool MCP 检查 + 解释错误模式 |

---

## 4. 知识基础设施（三条主线共享）

```
                    ┌─────────────┐
                    │  用户大脑    │
                    └──────┬──────┘
                           │ 浏览/编辑/思考
                    ┌──────▼──────┐
                    │  Obsidian   │ ← 用户的知识图谱
                    │   Vault     │   Markdown + 双向链接
                    └──────┬──────┘
                           │ MCP 读写
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌────────┐  ┌─────────┐  ┌─────────┐
         │ Zotero │  │  Mem0   │  │ RAGFlow │
         │ 文献库  │  │ agent   │  │ 文档检索 │
         │        │  │ 记忆    │  │         │
         └────────┘  └─────────┘  └─────────┘
              ↑            ↑            ↑
              └────────────┼────────────┘
                    daemon agents 读写
```

| 存储 | 存什么 | 谁写 | 谁读 |
|---|---|---|---|
| Obsidian vault | Markdown 产出、文献笔记、知识笔记 | researcher/writer/engineer/mentor + 用户 | 用户 + researcher（MCP 搜索）|
| Zotero | 论文 PDF + 元数据 + 标注 | 用户 + researcher | 用户 + Obsidian 插件自动导入 |
| Mem0 | agent 记忆（用户偏好、规划经验） | daemon 自动（distillation） | daemon agents |
| RAGFlow | 长文档语义检索 | researcher/engineer | researcher |
| MinIO | 二进制文件、大文件、临时产物 | 各 agent | 各 agent + native_open |

---

## 5. daemon 应主动触发的工作流

以下不是等用户说才做的——daemon 应该按规则自动触发：

| 触发条件 | 动作 | 场景 |
|---|---|---|
| Engineer build 周期结束 | 提醒做 literature mapping | copilot |
| 接近 CFP deadline（T-8 周） | 提醒启动论文写作 | copilot/mentor |
| 新论文发表后 | 推送到 Telegram + 存入 Zotero | operator/researcher |
| 每天固定时间 | 日报推送 | operator |
| 每周 | 推荐 2-3 篇论文 + 运动周报 + 项目进度 | mentor/coach/copilot |
| 写完英文产出 | LanguageTool 检查 + mentor 解释错误 | mentor |
| 完成一个 build + write | 提醒更新 GitHub profile + 写博客 | copilot |
| 代码 PR 提交 | mentor 引导用户做 code review（教学目的） | mentor |

---

## 6. 缺失工具（需要新增）

| 工具 | 用途 | 优先级 |
|---|---|---|
| **Connected Papers** | 论文引用关系可视化 | P1 |
| **Research Rabbit** | 前向/后向引用链追踪 | P1 |
| **mldeadlines.com .ics** | 会议截稿日期日历 | P1 |
| **Spaced Repetition**（Obsidian 插件） | 读过的论文关键知识点记忆巩固 | P2 |
| **个人网站**（Astro/Hugo） | 作品集展示 | P2 |
| **W&B / MLflow** | 实验追踪（如果做 ML 实验） | P2 |
