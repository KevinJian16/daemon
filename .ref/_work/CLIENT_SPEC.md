# Daemon 桌面客户端规格说明

> **依据**：SYSTEM_DESIGN.md 七稿 §4, §6.10, §6.13
> **日期**：2026-03-17（v2：Electron → Tauri，原生应用调起策略）
> **目标**：在写代码之前对齐客户端的完整范围

---

## 1. 总览

| 维度 | 规格 |
|---|---|
| 技术栈 | **Tauri**（系统 WebView：macOS WKWebView） |
| 前端框架 | React + Vite + Tailwind（已有 `interfaces/portal/`） |
| 多平台 | macOS Tauri 主控台 + iOS Tauri artifact 查看器 + Telegram 信箱（DD-79） |
| 进程模型 | 菜单栏图标 + 主窗口 = 同一 Tauri 进程 |
| 后端 | daemon API（FastAPI），本地 localhost |
| 认证 | OAuth（Google / GitHub）→ JWT token 持久化 |
| 体积 | ~10MB（vs Electron ~200MB），使用系统 WebView，无捆绑 Chromium |

### 1.1 架构变更说明（DD-78, DD-80）

v1（Electron）→ v2（Tauri）的关键变更：

| v1（Electron） | v2（Tauri） | 理由 |
|---|---|---|
| BrowserView 内嵌网页 | 系统浏览器打开 | 原生体验更好，省去 BrowserView 复杂度 |
| 阅读器 view（Markdown 渲染） | 按 Artifact 类型调原生应用 | Preview.app/浏览器/VS Code 各司其职 |
| Monaco Editor 内嵌 | VS Code 系统调起 | VS Code 体验远优于内嵌 Monaco |
| Chromium 捆绑（~200MB） | 系统 WKWebView（~10MB） | 轻量，macOS 原生 |

**核心策略：daemon 只负责 open 目标应用/文件，窗口布局由用户通过 Stage Manager 自行管理（DD-80：自动分屏与 Stage Manager 冲突，取消）。**

---

## 2. 两种展示模式

### 2.1 对话 View（核心）

- 4 个独立对话（copilot / instructor / navigator / autopilot）
- **纯文本**，无富文本、无链接、无内嵌卡片
- 对话和展示严格分离——对话里不出现链接和富内容
- 所有操作通过对话完成，**零按钮**（无执行/暂停/取消/触发按钮）
- 用户说 → L1 执行，L1 汇报 → 用户看到

**视觉设计**：
- Claude 风格对话：无气泡，所有消息左对齐，用角色标签（"You" / 场景名）区分
- 字体：Bricolage Grotesque（Google Fonts，类 Styrene 的 quirky grotesque）
- 色板：暖白背景 + 柔和玫瑰紫 primary（oklch 0.65 0.1 310）+ shadcn Nova 设计系统
- 加载动画：场景色脉冲条（不是跳动圆点）
- 输入框：左侧回形针（附件上传）+ 右侧发送箭头
- macOS Tauri 默认 webview zoom = 1.25（实现方式：`index.html` 中 `<script>if(window.__TAURI_INTERNALS__)document.documentElement.style.zoom='1.25'</script>`，仅 Tauri 环境生效，浏览器 dev 模式不受影响）

**消息流协议**：
- WebSocket 双向（低开销，每帧 2-14 字节头）
- 消息可携带多种类型：文本、panel 更新指令、原生应用调起指令
- 客户端根据消息类型分发到对应处理器

**API 端点**：
| 端点 | 说明 |
|---|---|
| `POST /scenes/{scene}/chat` | 发送消息 |
| `GET /scenes/{scene}/chat/stream` (WS) | 实时对话流 |

### 2.2 场景 Panel

每个场景有专属 panel，PG 数据驱动，自研 UI。

| 场景 | panel 内容 |
|---|---|
| **copilot** | 活跃 Project 列表、进行中 Task 状态、最近产出 |
| **instructor** | 当前学习计划、assignment 列表（待交/已交/已评）、学习进度 |
| **navigator** | 本周计划执行率、最近训练数据摘要、下次评估时间 |
| **autopilot** | 各平台运营数据、待审内容、自动发布日志 |

**API 端点**：`GET /scenes/{scene}/panel`

assignment 系统是 instructor panel 的功能，不是独立应用。提交入口指向外部工具（Google Docs / GitHub），daemon 通过 webhook 或轮询感知提交。

---

## 3. 原生应用调起策略（替代 BrowserView / 阅读器 / Monaco）

**核心思路：daemon 不内嵌外部工具，通过 `open` 命令调起原生应用。窗口布局由用户通过 Stage Manager 自行管理（DD-80）。**

### 3.1 Artifact 呈现

| Artifact 类型 | 打开方式 | 应用 |
|---|---|---|
| Markdown | API 渲染为 HTML（`/artifacts/{id}/render`）→ `open` URL | 系统浏览器 |
| PDF | MinIO presigned URL 或下载临时文件 → `open` | Zotero（内置阅读器） |
| 图片 | 同上 | Preview.app |
| 代码文件 | `code` CLI 打开 | VS Code |
| 交互式图表 | ECharts HTML → `open` URL | 系统浏览器 |
| 网页链接 | 直接 `open` URL | 系统浏览器 |

对话中自然引出（"写好了，你看看"）→ 自动打开对应应用并定位窗口：左边距 15% 屏幕宽度（Stage Manager 缩略图空间），上/下/右贴边。按比例计算，不绑定分辨率。

**系统默认应用配置**：通过 `duti` 工具设置 macOS 文件类型关联（`scripts/setup.sh` 中自动执行）：
- `.pdf` → Zotero（`org.zotero.zotero`）
- 图片（png/jpg/gif/...） → Preview.app（系统默认）

### 3.2 外部工具打开

| 工具类型 | 方案 |
|---|---|
| Web 平台（Google Docs, intervals.icu, 社媒后台） | 系统浏览器打开 |
| VS Code / LeetCode 插件 | `code` CLI 调起 |
| PDF | Zotero（内置阅读器） |
| 图片 | Preview.app |
| 移动端 | Telegram DM + 链接跳转 |

**API 端点**：
| 端点 | 说明 |
|---|---|
| `GET /artifacts/{id}` | Artifact 元数据 |
| `GET /artifacts/{id}/render` | Artifact 渲染为 HTML（Markdown→HTML） |
| `GET /artifacts/{id}/download` | Artifact 下载 |

---

## 4. 菜单栏图标

| 功能 | 说明 |
|---|---|
| 状态指示 | 绿（正常）/ 黄（部分异常）/ 红（系统故障） |
| 左键点击 | 打开/聚焦主窗口 |
| 右键菜单 | Start / Stop daemon |
| 右键菜单 | 今日任务数 |
| 右键菜单 | 本周体检状态 |
| 右键菜单 | 打开 Langfuse / Temporal UI（CC/admin） |

**API 端点**：`GET /status`（系统整体状态）

菜单栏常驻，主窗口按需打开/关闭。

---

## 5. 认证

**FINAL 规则：正式发布后，用户必须同时绑定 Google 账户和 GitHub 账户才能进入 Daemon。**

| 场景 | 方式 |
|---|---|
| 首次登录 | Google OAuth + GitHub OAuth，两者都必须完成 |
| 后续登录 | JWT token 持久化，不需要每次登录 |
| API 调用 | JWT token（OAuth 颁发），所有数据端点强制验证 |
| 公开端点 | 仅 `/status`、`/health`、`/auth/*`、`/webhooks/plane` 不需要认证 |
| WebSocket | 握手时通过 query parameter 传递 JWT token |

**API 端点**：
| 端点 | 说明 |
|---|---|
| `GET /auth/google` | Google OAuth 登录 |
| `GET /auth/github` | GitHub OAuth 登录 |
| `GET /auth/callback` | OAuth 回调 |

### 5.2 Google API OAuth（Desktop 类型）

daemon 的 MCP servers（Gmail / Calendar / Docs / Drive）需要调用 Google API，使用独立的 **Desktop 类型** OAuth Client（与 §5.1 的 Web 类型分开）：

| 配置 | 说明 |
|---|---|
| Client type | Desktop app（Google Cloud Console 创建） |
| Env vars | `GOOGLE_DESKTOP_CLIENT_ID` / `GOOGLE_DESKTOP_CLIENT_SECRET` |
| Token 缓存 | `~/.daemon/google_token.json`（首次浏览器授权后自动缓存，过期自动刷新） |
| Scopes | gmail.readonly, gmail.send, calendar, documents, drive |
| 共享模块 | `mcp_servers/google_auth_helper.py`（4 个 MCP server 共用） |
| 授权完成页 | Daemon 品牌页面（Bricolage Grotesque + icon，非默认纯文本） |

Web 类型 Client（`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`）仅用于 FastAPI 用户登录，两者互不干扰。

---

## 6. 多平台策略（DD-79）

**daemon 不提供 Web 访问。所有访问必须通过封装好的原生客户端。**

```
macOS：     Tauri 桌面 app → 完整体验（对话 + native_open）
iOS：       Tauri iOS app → Artifact 查看器（只读）
Telegram：  信箱 + 对讲机 → 通知/快捷回复（单向同步 Telegram→本地）
```

### 6.1 macOS Tauri（主控台）

完整功能。daemon 的核心能力（MCP servers / Docker / VS Code / 系统应用）全部依赖 macOS 环境。默认 webview zoom = 1.25。

### 6.2 iOS Tauri（Artifact 查看器）

Tauri 2.0 支持 iOS 构建（WKWebView）。只读浏览 daemon 产出的文档/代码/图片。不提供对话或操作能力。类似 Steam iOS app。

iOS 上 artifact 按类型 inline 渲染：Markdown→HTML / PDF→内嵌 / 图片→原生 / 代码→语法高亮。

### 6.3 Telegram（信箱 + 对讲机）

daemon → 用户：通知、确认请求。用户 → daemon：简短回复。

**单向同步：Telegram → 本地**。用户在 Telegram 的回复同步到本地客户端。本地桌面对话不推送到 Telegram。

---

## 7. 消息协议设计

对话流消息需要支持多种类型，客户端根据类型分发：

| 消息类型 | 处理方式 | 示例 |
|---|---|---|
| `text` | 对话 view 显示 | 普通对话消息 |
| `panel_update` | 场景 panel 刷新 | Task 状态变更、数据刷新 |
| `native_open` | 调起原生应用 | 打开 Google Docs URL / VS Code / Preview |
| `artifact_show` | 调起渲染 | 展示 Markdown Artifact（浏览器打开 /render） |
| `status_update` | 菜单栏图标更新 | 系统状态变化 |
| `notification` | 系统通知 | macOS 原生通知（Tauri notification 插件） |

注：v1 的 `browser_navigate`、`editor_open`、`vscode_launch` 统一为 `native_open`（由 macos-control MCP 执行）。

---

## 8. 客户端不做什么

- **无操作按钮**：无执行、暂停、恢复、取消按钮
- **无 Plane 页面**：用户不直接看 Plane 风格的 Task/Project 页面
- **无评分/评价 UI**：反馈通过对话自然发生
- **无 agent/模型选择**：L1 自行判断
- **无富文本对话**：对话 = 纯文本
- **不替代专业工具**：用户在 Google Docs 里写作业，不在客户端里写
- **不内嵌外部网页**：外部内容通过系统浏览器打开，窗口布局交给 Stage Manager
- **不内嵌代码编辑器**：代码编辑通过 VS Code 系统调起

---

## 9. 完整 API 端点清单

| 类别 | 端点 | 方法 | 说明 |
|---|---|---|---|
| 对话 | `/scenes/{scene}/chat` | POST | 场景对话输入 |
| 对话 | `/scenes/{scene}/chat/stream` | WS | 实时对话流 |
| 场景 | `/scenes/{scene}/panel` | GET | 场景 panel 数据 |
| 活动流 | `/tasks/{id}/activity` | GET | Task 活动流（CC/admin） |
| 产物 | `/artifacts/{id}` | GET | Artifact 元数据 |
| 产物 | `/artifacts/{id}/render` | GET | Artifact 渲染为 HTML |
| 产物 | `/artifacts/{id}/download` | GET | Artifact 下载 |
| 状态 | `/status` | GET | 系统整体状态 |
| 认证 | `/auth/google` | GET | Google OAuth |
| 认证 | `/auth/github` | GET | GitHub OAuth |
| 认证 | `/auth/callback` | GET | OAuth 回调 |

---

## 10. 已确定项

| # | 问题 | 决定 | 理由 |
|---|---|---|---|
| 1 | 前端框架 | React + Vite + Tailwind | 已有 `interfaces/portal/` |
| 2 | 对话传输 | WebSocket | 双向实时 |
| 3 | 状态管理 | zustand | 轻量，4 个场景各自状态 |
| 4 | 桌面壳 | Tauri（v2） | 轻量（~10MB），系统 WebView，原生 tray/快捷键 |
| 5 | 外部内容展示 | 原生应用调起（open 命令）| 替代 BrowserView/阅读器/Monaco（DD-80：不分屏） |
| 6 | Artifact 渲染 | FastAPI `/artifacts/{id}/render` → 系统浏览器 | 服务端渲染 Markdown→HTML |
| 7 | iOS | Tauri iOS app | Artifact 只读查看器（DD-79） |
| 8 | Telegram | 信箱 + 对讲机 | 通知/快捷回复，单向同步 Telegram→本地（DD-79） |

---

## 11. 开发阶段

| 阶段 | 范围 |
|---|---|
| **P0** | Tauri 骨架 + 菜单栏图标（绿/黄/红）+ OAuth 登录 + 4 个对话 view + WebSocket |
| **P1** | 4 个场景 panel（PG 数据驱动）+ 菜单栏右键菜单 + 全局快捷键 |
| **P2** | iOS Tauri artifact 查看器（只读） |
| **P3** | macOS 开机自启动（launchd plist）|

注：v1 的 P2（BrowserView/阅读器/Monaco）已取消（DD-78）。v2 的 P2（远程访问+PWA）也已取消（DD-79：不做 Web 端），改为 iOS Tauri artifact 查看器。

---

## 12. 命名规范

- **Daemon**（首字母大写）：UI 展示、品牌名、面向用户的文字（sidebar 标题、OAuth 页面、文档标题）
- **daemon**（全小写）：代码标识符、变量名、目录名、设计文档正文、技术讨论
