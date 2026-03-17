# 信息监控架构

> **日期**：2026-03-16
> **依据**：SYSTEM_DESIGN.md 七稿 §0.11, §1.4, §2.6, §2.7
> **定位**：补充设计——信息如何进入 daemon、如何流转、如何呈现给用户

---

## 核心原则

**信息监控是系统级基础设施，不属于任何一个场景。**

场景定义关系和氛围，不定义"做什么"（§0.11）。信息拉取、存储、检索是基础设施层的事，和 Temporal、PG、Mem0 一样。4 个 L1 平等地从全局存储中获取信息，在各自对话中根据关系动态自然使用。

---

## 1. 信息流

```
系统基础设施层
├── Temporal Schedule（定时触发 InfoPullWorkflow）
│   → Activity: pull_sources（direct 类型，零 token）
│     调 MCP tools 拉取各信息源原始数据
│        ├── RSS feeds（含 RSSHub 生成的反爬平台 feed）
│        ├── arXiv 新论文
│        ├── GitHub releases / trending
│        ├── HN 热帖
│        ├── Reddit 关注的 subreddit
│        ├── Twitter/X 关注列表
│        ├── intervals.icu 运动数据
│        └── Zotero 新增文献
│
│   → Activity: triage_results（agent 类型，调 researcher）
│     分析内容与用户上下文的关联性，打标分级
│        ├── 🔴 紧急 → Telegram 通知（4 个 bot 都可能推，看相关性）
│        ├── 🟡 相关 → 全文抓取 → 存 RAGFlow
│        ├── 🔵 有价值 → 摘要存 knowledge_cache
│        └── ⚪ 低价值 → 丢弃
│
└── 全局存储（所有 L1 平等检索）
    ├── RAGFlow（全文向量检索）
    ├── knowledge_cache（PG，摘要 + TTL）
    └── Mem0（和用户偏好/决策相关的提炼）
```

**4 个 L1 怎么用这些信息，取决于各自的关系动态，不取决于信息分类：**

| L1 | 同一条信息（比如"用户依赖的库出了 breaking change"）怎么说 |
|---|---|
| copilot | "你项目里用到了这个库，我先帮你看看影响范围" （协作者，主动帮忙） |
| instructor | "正好，我们来看看这次 breaking change 的设计思路，你觉得为什么要这样改？" （老师，借机教学） |
| navigator | "你这周的目标里有用到这个库的部分，需要调整计划吗？" （教练，关注执行计划） |
| autopilot | 已经自动检查了兼容性，如果没问题就不打扰用户 （自治，只在需要时汇报） |

---

## 2. 呈现方式

### 被动呈现（L1 对话中自然提及）

每个 L1 在对话过程中，通过 Mem0/RAGFlow 检索到相关信息时，根据自己的关系动态自然嵌入对话。不需要额外机制——这是 L1 作为 LLM agent 的基本能力。

### 主动推送（Telegram 通知）

紧急信息通过 Telegram 通知推送。推给哪个 bot 取决于信息和用户当前活跃对话的相关性，不固定绑定某个场景。

### Panel 展示

各场景 panel 可以展示与该场景当前上下文相关的信息摘要，数据来源是全局存储。

---

## 3. 信息源配置

### 3.1 订阅管理

用户在任何场景对话中都可以管理订阅：
- 跟 copilot 说"帮我关注这个库的 release" → 系统级订阅
- 跟 instructor 说"我想跟踪 NLP 领域最新论文" → 系统级订阅
- 跟 autopilot 说"每周给我一个技术周报" → 系统级定时任务

存储：PG 表 `info_subscriptions`（全局，不按场景分区）

### 3.2 订阅分类

| 类别 | 来源示例 | 拉取频率 |
|---|---|---|
| **学术** | arXiv（cs.AI, cs.CL, cs.LG...）, Semantic Scholar alerts | 每 4 小时 |
| **业界** | Google AI Blog, Meta AI, Anthropic, OpenAI, DeepMind | 每 4 小时 |
| **开源** | GitHub releases（关注的 repo）, GitHub trending | 每 6 小时 |
| **技术社区** | HN, Reddit（r/MachineLearning, r/LocalLLaMA...）| 每 2 小时 |
| **技术博客** | 个人博客, Substack, 知乎专栏 | 每 4 小时 |
| **社媒** | Twitter/X 关注列表 | 每 2 小时 |
| **反爬平台** | Reddit, 知乎, 小红书（via RSSHub） | 每 2 小时 |
| **权威机构** | NIST, IEEE, ACM, Nature, Science | 每日 |
| **运动** | intervals.icu | 每日 |
| **新闻** | TechCrunch, Ars Technica | 每 4 小时 |

### 3.3 筛选策略（系统级规则）

系统对 researcher 返回的原始结果做筛选分级：

**🔴 紧急**（立刻通知）：
- 用户正在使用的依赖有 breaking change 或安全漏洞
- 用户关注的领域有重大突破（新 SOTA、重要发布）

**🟡 相关**（全文存储）：
- 和活跃 Project/Task 直接相关的内容
- 用户明确要求关注的主题
- 学术论文被引用数快速上升的

**🔵 有价值**（摘要存储）：
- 用户可能感兴趣但不紧急的趋势
- 领域综述、教程、最佳实践
- 社区热门讨论

**⚪ 低价值**（丢弃）：
- 和用户无关的领域
- 重复/旧闻
- 低质量内容（clickbait、广告）

---

## 4. 文献管理

Zotero 是全局基础设施，任何场景都可以使用：

- Zotero：元数据管理（收藏、标注、分组、引用格式）
- RAGFlow：全文检索引擎（PDF 解析、语义搜索、跨文献检索）

两者互补，不按场景分区。

---

## 5. 与现有架构的关系

不需要新增架构组件。只需要：

| 需要做的 | 在哪做 |
|---|---|
| 配置 Temporal Schedule（定时拉取） | `temporal/workflows.py` 新增 info_pull schedule |
| 新增 info_subscriptions PG 表 | `services/store.py` |
| 新增 MCP servers | `config/mcp_servers.json` |
| 筛选分级规则 | `config/info_triage_rules.toml`（系统级配置） |
