# Daemon 外部集成清单

> **日期**：2026-03-17
> **依据**：SYSTEM_DESIGN.md 七稿 §2.6, §2.7 + 用户确认
> **原则**：能用现成 MCP server 就用，没有的自写。信息获取和行动输出同等重要。
> **不纳入 MCP 的工具**：Elicit（无公开 API，仅浏览器使用，2026-03 确认）。

---

## 1. 已有 MCP servers（9 个）

| MCP server | 用途 | 配置文件 |
|---|---|---|
| brave-search | 通用网页搜索 | config/mcp_servers.json ✅ |
| semantic-scholar | 学术论文搜索 | config/mcp_servers.json ✅ |
| firecrawl | 网页→干净 Markdown | config/mcp_servers.json ✅ |
| github | GitHub 仓库操作 | config/mcp_servers.json ✅ |
| filesystem | daemon 本地文件读写 | config/mcp_servers.json ✅ |
| code-functions | 代码分析工具 | config/mcp_servers.json ✅ |
| paper-tools | 论文处理工具 | config/mcp_servers.json ✅ |
| playwright | 浏览器自动化 | config/mcp_servers.json ✅ |
| code-exec | Step 内代码执行 | config/mcp_servers.json ✅ |

---

## 2. 需要新增的 MCP servers

### 2.1 浏览器自动化（无 API 平台的兜底）

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **playwright** | `@anthropic-ai/mcp-server-playwright` | P0 | 小红书、微信公众号、任何无 API 平台的兜底 |

### 2.2 Google 生态

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **google-calendar** | Google Calendar API MCP | P0 | coach 场景时间轴、日程管理、训练安排 |
| **google-docs** | Google Docs API MCP | P0 | 文档读写，mentor 场景 assignment 核心 |
| **google-drive** | Google Drive API MCP | P0 | 文件管理、Artifact 同步（§6.12 MinIO→Drive） |
| **gmail** | Gmail API MCP | P1 | 邮件处理、通知 |

> Google 四件套共享同一个 OAuth credential（同一个 GCP project），MCP server 可能合并为一个或分开。

### 2.3 文献管理

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **zotero** | 社区包 mcp-server-zotero（npm） | P1 | 文献收藏/标注/分组/引用导出。REST API 完善，有官方文档 |

Zotero 工作流：
- researcher 搜到论文 → Zotero API 添加到 collection
- 用户浏览器插件一键收藏 → daemon 通过 Zotero API 感知新增
- 写作时 → Zotero API 拉引用 → BibTeX/CSL 格式 → 插入文档
- RAGFlow 解析 PDF 全文 → 向量检索 → Zotero 做元数据管理

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **openalex** | 自写 MCP（REST API，免费无 auth） | P1 | 2.5亿+论文元数据，替代 Microsoft Academic Graph |
| **unpaywall** | 自写 MCP（REST API，免费 100K/天） | P1 | DOI→免费全文 PDF 下载链接 |
| **crossref** | 自写 MCP（REST API，免费无 auth） | P1 | 1.8B 引用元数据，DOI 解析 |
| **dblp** | 社区包 mcp-dblp（npm，AAAI-26 配套） | P1 | CS 论文权威检索，按作者/会议/年份，免费无需 key |
| **academix** | 社区包 Academix（npm） | P1 | 统一学术搜索：聚合 OpenAlex+DBLP+S2+arXiv+CrossRef |
| **core** | 自写 MCP（REST API，免费需注册 key） | P2 | 4.3 亿 OA 论文元数据 + 全文托管，与 Unpaywall 互补 |

### 2.4 运动 / 健康

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **intervals-icu** | intervals.icu REST API MCP（自写） | P1 | 训练计划、执行数据、TSS/CTL/ATL 分析、日历同步 |

intervals.icu API 能力：activities, wellness, events, athlete settings, workout library, fitness/fatigue/form curves, structured workouts, webhooks。社区 MCP：`mrgeorgegray/intervals-icu-mcp`。

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **openweathermap** | 社区包 mcp-openweathermap（npm） | P1 | 户外运动天气预报，免费 1000 req/天 |

| **strava** | 自写 MCP（REST API，OAuth 2.0） | P1 | 运动数据原始获取（200 req/15min），intervals.icu 数据源 |

OpenWeatherMap 用途：coach 根据天气决定室内/户外训练计划。与 intervals.icu 和 Google Calendar 联动。
Strava 用途：intervals.icu 数据来源就是 Strava，直接接 Strava API 获取更原始的运动数据。

### 2.5 英文写作辅助

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **languagetool** | self-hosted Docker + 自写 MCP wrapper | P1 | 英文语法/风格/学术用词检查，无限调用 |

LanguageTool 工作流：
- 用户每次英文输出（论文/博客/GitHub commit message）→ LanguageTool 检查
- mentor 解释错误模式（为什么这样写不对，学术英文怎么表达）
- Mem0 记录用户常犯错误 → 逐步减少同类问题
- 配合 Stage 0 确认的"渐进式英文浸泡"策略

LanguageTool 部署：官方 Docker 镜像 `erikvl87/languagetool`，约 2GB 内存（含 n-gram 数据）。

### 2.6 博客发布平台

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **devto** | 自写 MCP（Forem REST API v1） | P1 | 技术社区博客发布，Dev.to |
| **hashnode** | 自写 MCP（GraphQL API） | P1 | 开发者社区博客发布 |

博客三渠道发布架构：
1. **Hugo + GitHub Pages**（canonical）：完全所有权，SEO 友好，通过 GitHub MCP 推送 Markdown
2. **Dev.to**（Forem API v1）：技术社区触达，REST API 支持 CRUD，API key 认证
3. **Hashnode**（GraphQL API）：开发者社区触达，Personal Access Token 认证，支持自定义域名

publisher 写一次 Markdown → 自动适配各平台 front matter 和格式 → 跨平台同步发布。

### 2.7 社媒 / 社区（输入+输出）

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **twitter-x** | Twitter/X API v2 MCP（自写或社区） | P1 | 发推/读 timeline/监控关键词 |
| **reddit** | Reddit API MCP（自写或社区） | P1 | 发帖/评论/监控 subreddit |
| **xiaohongshu** | Playwright MCP（无官方 API） | P2 | 浏览器自动化发布+监控 |
| **wechat-mp** | Playwright MCP 或微信公众号 API | P2 | 公众号发布 |

### 2.8 信息源 / 监控（输入）

这一块是 daemon 的"眼睛"——持续获取外部世界的信息，喂给 researcher 和 L1 agent。

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **rss-reader** | 自写 MCP（feedparser + OPML 管理） | P1 | RSS/Atom 订阅聚合 |
| **hackernews** | HN API MCP（自写，API 简单） | P1 | 技术社区热点 |
| **newsdata** | 自写 MCP（NewsData.io REST API） | P2 | 新闻聚合 API（免费 200 req/天），按关键词/国家/语言过滤 |
| **arxiv** | arXiv API MCP（自写） | P1 | 预印本监控，按关键词/作者/分类追踪 |

**RSSHub**：自部署 Docker 容器，用于解决反爬平台（Reddit/知乎/小红书）的信息拉取（见 SYSTEM_DESIGN.md §2.7.1）。RSSHub 不是 MCP server，而是基础设施层组件——它生成标准 RSS feed，由 rss-reader MCP 消费。

**信息源分类**：

| 类别 | 具体来源 | 获取方式 |
|---|---|---|
| **学术** | arXiv, Semantic Scholar, OpenAlex, CrossRef, Unpaywall, DBLP | arXiv MCP + Semantic Scholar MCP + OpenAlex MCP + CrossRef MCP + Unpaywall MCP + Firecrawl |
| **业界** | 公司技术博客（Google AI, Meta AI, OpenAI, Anthropic, DeepMind...） | RSS + Firecrawl |
| **开源社区** | GitHub Trending, GitHub Releases（关注的 repo）, HN | GitHub MCP + HN MCP + RSS |
| **技术博客** | 个人博客、Medium、Substack、知乎专栏 | RSS + Firecrawl |
| **Reddit** | r/MachineLearning, r/LocalLLaMA, r/programming 等 | Reddit MCP |
| **Twitter/X** | AI/ML 领域 KOL、技术圈 | Twitter MCP |
| **权威机构** | NIST, IEEE, ACM, Nature, Science | RSS + Firecrawl |
| **新闻** | TechCrunch, The Verge, Ars Technica | RSS + Firecrawl |
| **反爬平台** | Reddit, 知乎, 小红书 | RSSHub → rss-reader MCP（每 2 小时，见 §2.7.1） |

> RSS 是信息监控的骨干——大部分权威源都有 RSS feed。RSS MCP 负责订阅管理和定时拉取，Firecrawl 负责全文抓取，RAGFlow 负责存储和检索。

### 2.9 开发工具

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **docker** | Docker Engine API MCP（自写） | P2 | 容器管理、开发环境 |
| **libraries-io** | 自写 MCP（Libraries.io REST API） | P1 | 开源依赖监控（40M+ 包，跨 NPM/PyPI/Cargo 等），版本/依赖/安全，免费需 API key |

Libraries.io 用途：engineer 检查依赖安全性和最新版本，operator 监控关注项目的依赖变更。

### 2.10 可视化 / 生成

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **matplotlib** | 自写 MCP（Python 调用，输出 PNG/SVG → MinIO） | P1 | 数据图表 |
| **mermaid** | 自写 MCP（mermaid-cli，输出 SVG → MinIO） | P1 | 流程图/架构图/甘特图 |
| **echarts** | `apache/echarts-mcp`（npm 官方包） | P1 | 交互式图表（bar/line/pie/scatter/tree/sunburst 等），Apache 官方 |
| **kroki** | 自写 MCP（Kroki API） | P1 | 统一 20+ 图表格式 API（Mermaid/PlantUML/GraphViz/D2/Vega/Vega-Lite/Ditaa 等），可自部署 |
| **latex** | 自写 MCP（tectonic/pdflatex，输出 PDF → MinIO） | P2 | 论文排版 |
| **excalidraw** | 社区包（excalidraw-mcp，npm） | P2 | 白板/手绘风格图表，适合头脑风暴和概念草图 |
| **typst** | 自写 MCP（typst CLI，输出 PDF → MinIO） | P2 | 现代排版系统（Rust，编译极快），LaTeX 轻量替代 |

Kroki 部署选择：
- 公共 API（`https://kroki.io`，免费）或自部署 Docker（`yuzutech/kroki`）
- 一个 POST endpoint 统一处理所有图表格式 → SVG/PNG

### 2.11 ML 研究

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **huggingface** | 自写 MCP（HuggingFace Hub API，免费无 auth） | P1 | 模型/数据集/Spaces 搜索，模型卡片获取，trending 监控 |
| **kaggle** | 自写 MCP（Kaggle REST API，免费需 key） | P2 | 数据集搜索/下载、竞赛信息、Notebook 获取 |

HuggingFace 用途：researcher 追踪最新开源模型、搜索数据集、获取 model card 评测信息。engineer 查找可用预训练模型。
Kaggle 用途：researcher 获取公开数据集、竞赛信息、社区 Notebook 作为参考实现。

### 2.12 LeetCode 刷题

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **leetcode** | 社区包 `@jinzcdev/leetcode-mcp-server`（npm） | P1 | 题库搜索（tag/难度）、题目详情、用户提交历史，支持 leetcode.com + leetcode.cn |

**LeetCode 刷题链路**（mentor 主导出题）：
1. mentor 根据用户薄弱点（Mem0 记录）通过 LeetCode MCP 搜索合适题目（tag/难度筛选）
2. mentor 出题："去做 LeetCode 第 X 题"，给出背景提示但不给答案
3. daemon 自动打开 VS Code（LeetCode 插件），用户在 Stage Manager 中安排窗口
4. 用户在 VS Code 中做题，代码存本地 `~/.leetcode/`
5. 做完后 mentor 通过 filesystem MCP 读用户代码 → 点评思路、时间/空间复杂度、代码风格
6. 如果卡住 → mentor 渐进式引导（先 hint → 再给思路框架 → 最后讲解）
7. Mem0 记录：已刷题目、薄弱知识点（DP/图/树/贪心等 tag）、常犯错误、进步曲线
8. mentor 基于 Mem0 调整出题策略，渐进式难度提升

**依赖**：
- `@jinzcdev/leetcode-mcp-server`（npm 直装，~180 star）：题库搜索、题目详情、提交历史
- 认证：公开数据无需 auth；提交历史需 `LEETCODE_SESSION` cookie
- VS Code LeetCode 插件（用户端）：解题界面，本地存储代码
- filesystem MCP（已有）：读取本地解题文件

**mentor SKILL.md 需新增**：`leetcode_coaching` skill — 搜索题库出题、引导式教学（先 hint 再深入）、读取本地解题文件点评、Mem0 记录刷题进度与弱项。

### 2.13 系统控制

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **macos-control** | 自写 MCP（AppleScript / osascript） | P1 | 打开 app、调窗口、Finder 操作、系统通知 |

### 2.14 知识图谱

| MCP server | 方案 | 优先级 | 说明 |
|---|---|---|---|
| **obsidian-vault** | `@bitbonsai/mcpvault`（npm） | P0 | Obsidian vault 文件系统直接操作（不依赖 Obsidian 运行），用户知识图谱读写（DD-81，§5.7.1） |

Obsidian vault 是用户的知识图谱（Markdown + 双向链接），存放在 Google Drive。daemon 的 Markdown 产出（报告/文章/笔记）写入 vault，二进制文件留 MinIO。写入 vault 的 agent：researcher（研究报告/文献笔记）、writer（文章草稿）、engineer（技术笔记/ADR）、mentor（学习笔记模板）。

---

## 3. 信息监控架构

daemon 不只是被动响应用户请求，还需要**主动获取信息**。这是 operator 和 researcher 的核心能力。

```
定时触发（Temporal Schedule）
    │
    ├── RSS MCP → 拉取所有订阅源 → 新条目
    ├── arXiv MCP → 按关键词/作者查询 → 新论文
    ├── GitHub MCP → 关注 repo 的 releases/issues → 新动态
    ├── HN MCP → 热门帖子 → 新讨论
    ├── Reddit MCP → 关注 subreddit → 新帖子
    ├── Twitter MCP → 关注列表 timeline → 新推文
    │
    ▼
researcher 筛选 + 摘要
    │
    ├── 重要的 → Firecrawl 全文抓取 → RAGFlow 存储
    ├── 相关的 → knowledge_cache 缓存
    └── 值得用户知道的 → L1 在对话中自然提及
```

**触发频率**（[DEFAULT]，可调）：
| 源类型 | 频率 | 理由 |
|---|---|---|
| RSS / arXiv | 每 4 小时 | 学术和博客更新频率低 |
| GitHub Releases | 每 6 小时 | release 不频繁 |
| HN / Reddit / Twitter | 每 2 小时 | 社区讨论时效性较高 |
| OpenWeatherMap | 每 3 小时 | 户外运动天气决策 |
| intervals.icu | 每日 1 次 | 运动数据按天聚合 |

---

## 4. 外部 API Key 清单

| API | Key 环境变量 | 免费/付费 | 说明 |
|---|---|---|---|
| Brave Search | `BRAVE_API_KEY` | 免费 2000 次/月 | ✅ 已有 |
| Semantic Scholar | `S2_API_KEY` | 免费（有 rate limit） | ✅ 已有 |
| GitHub | `GITHUB_TOKEN` | 免费 PAT | ✅ 已有 |
| Firecrawl | 自部署，无 key | 免费（Docker） | ✅ 已有 |
| Google OAuth | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | 免费 | Calendar/Docs/Drive/Gmail 共用 |
| Zotero | `ZOTERO_API_KEY` | 免费 | Zotero Settings → API Keys |
| intervals.icu | `INTERVALS_API_KEY` | 免费（个人） | Settings → Developer |
| Twitter/X | `TWITTER_BEARER_TOKEN` | 免费 Basic tier（10k reads/月） | Developer Portal |
| Reddit | `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | 免费 | Apps → script type |
| arXiv | 无需 key | 免费 | OAI-PMH 或 arXiv API |
| HN | 无需 key | 免费 | Firebase API |
| OpenAlex | 无需 key（推荐加 email） | 免费 100K/天 | Polite pool with email |
| Unpaywall | `UNPAYWALL_EMAIL` | 免费 100K/天 | 只需邮箱 |
| CrossRef | 无需 key | 免费 | REST API |
| OpenWeatherMap | `OPENWEATHERMAP_API_KEY` | 免费 1000/天 | Developer portal 注册 |
| LanguageTool | 自部署，无 key | 免费（Docker） | `erikvl87/languagetool` |
| Dev.to | `DEVTO_API_KEY` | 免费 | Settings → Extensions |
| Hashnode | `HASHNODE_TOKEN` | 免费 | Personal Access Token |
| DBLP | 无需 key | 免费 | REST API |
| CORE | `CORE_API_KEY` | 免费（需注册） | CORE Dashboard |
| Strava | `STRAVA_CLIENT_ID` / `STRAVA_CLIENT_SECRET` | 免费 | Developer Portal, OAuth 2.0 |
| HuggingFace | 无需 key（推荐加 token） | 免费 | HF Hub Settings |
| Libraries.io | `LIBRARIES_IO_API_KEY` | 免费 | API key via account |
| NewsData.io | `NEWSDATA_API_KEY` | 免费 200 req/天 | Developer portal 注册 |
| Kaggle | `KAGGLE_USERNAME` / `KAGGLE_KEY` | 免费 | Account → API → Create New Token |

---

## 5. 自写 MCP server 工作量估算

| MCP server | 工作量 | 依赖 | 说明 |
|---|---|---|---|
| rss-reader | 小 | feedparser, OPML | 订阅管理 + 拉取 + 缓存 |
| zotero | 小 | pyzotero | REST API 封装 |
| intervals-icu | 小 | requests | REST API 封装 |
| twitter-x | 中 | tweepy | API v2 封装 |
| reddit | 小 | praw | API 封装 |
| arxiv | 小 | arxiv (PyPI) | API 封装 |
| hackernews | 小 | requests | Firebase API 封装 |
| matplotlib | 小 | matplotlib | 生成图表 → 保存文件 |
| mermaid | 小 | mermaid-cli (npm) | 生成 SVG |
| latex | 中 | tectonic / pdflatex | 编译 + 错误处理 |
| macos-control | 中 | osascript | AppleScript 封装 |
| google-suite | 中 | google-api-python-client | Calendar/Docs/Drive/Gmail |
| docker | 小 | docker SDK | Engine API 封装 |
| openalex | 小 | requests | REST API 封装，免费无 auth |
| unpaywall | 小 | requests | DOI→PDF URL，单 endpoint |
| crossref | 小 | requests | REST API 封装，免费无 auth |
| languagetool | 小 | requests + Docker | REST API wrapper，需部署 Docker |
| devto | 小 | requests | Forem API v1 封装 |
| hashnode | 小 | gql (GraphQL) | GraphQL API 封装 |
| echarts | 现成 | apache/echarts-mcp (npm) | 直接装 |
| kroki | 小 | requests | 单 POST endpoint |
| openweathermap | 现成 | mcp-openweathermap (npm) | 直接装 |
| playwright | 现成 | @anthropic-ai/mcp-server-playwright | 直接装 |
| dblp | 现成 | mcp-dblp (npm) | 直接装 |
| academix | 现成 | Academix (npm) | 直接装 |
| core | 小 | requests | REST API 封装，需注册 key |
| strava | 小 | requests | REST API + OAuth 2.0 封装 |
| huggingface | 小 | huggingface_hub (PyPI) | Hub API 封装 |
| libraries-io | 小 | requests | REST API 封装 |
| excalidraw | 现成 | excalidraw-mcp (npm) | 直接装 |
| newsdata | 小 | requests | REST API 封装 |
| typst | 小 | typst CLI (cargo) | 编译 + 输出 PDF → MinIO |
| kaggle | 小 | kaggle (PyPI) | REST API 封装 |
| leetcode | 现成 | @jinzcdev/leetcode-mcp-server (npm) | 直接装 |

---

## 6. 优先级汇总

### P0（系统核心）— 总计 12 个（SYSTEM_DESIGN §2.6.1 的 11 个 + DD-81 obsidian-vault）

已注册（9 个）：brave-search, semantic-scholar, firecrawl, playwright, github, filesystem, code-functions, paper-tools, code-exec

需新增（3 个 + DD-81）：
1. google-calendar — coach 场景时间轴
2. google-docs — 文档读写
3. google-drive — 文件管理
4. obsidian-vault — 用户知识图谱读写（DD-81，`@bitbonsai/mcpvault`，§5.7.1）

### P1（核心场景，尽快装）— 31 个
**信息获取**：
5. rss-reader — 信息监控骨干
6. hackernews — 技术热点
7. arxiv — 学术监控
8. openalex — 开放学术元数据（2.5亿+论文）
9. crossref — 引用元数据（1.8B 记录）
10. unpaywall — DOI→免费全文 PDF
11. dblp — CS 论文权威检索（npm 社区包）
12. academix — 统一学术搜索聚合（npm 社区包）

**文献管理**：
13. zotero — 文献收藏/标注/引用

**运动/健康**：
14. intervals-icu — 运动数据/训练计划
15. openweathermap — 户外运动天气
16. strava — 运动数据原始获取

**英文写作**：
17. languagetool — 语法/风格/学术用词检查

**博客发布**：
18. devto — Dev.to 博客发布
19. hashnode — Hashnode 博客发布

**社媒**：
20. twitter-x — 社媒监控+发布
21. reddit — 社区监控+参与

**可视化**：
22. matplotlib — 数据图表
23. mermaid — 流程图/架构图
24. echarts — 交互式图表（Apache 官方）
25. kroki — 统一 20+ 图表格式 API

**ML 研究**：
26. huggingface — 模型/数据集搜索（Hub API）

**刷题**：
27. leetcode — mentor 主导出题 + 引导刷题（npm 社区包）

**开发工具**：
28. libraries-io — 开源依赖监控（40M+ 包）

**系统**：
29. gmail — 邮件
30. macos-control — 系统控制

**已注册但需补充**：
31. code-exec — Step 内代码执行（§3.13）

### P2（按需）— 10 个
32. xiaohongshu（via playwright）
33. wechat-mp（via playwright 或 API）
34. latex — 论文排版
35. docker — 容器管理
36. core — OA 论文元数据+全文（4.3 亿）
37. excalidraw — 白板/手绘风格图表
38. typst — 现代排版系统（LaTeX 轻量替代）
39. newsdata — 新闻聚合 API
40. kaggle — 数据集/竞赛/Notebook
