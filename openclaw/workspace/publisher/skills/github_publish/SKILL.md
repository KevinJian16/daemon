---
name: github-publish
description: >-
  Publish artifacts to GitHub: create issues, pull requests, releases, or push
  commits via GitHub MCP tools. ALWAYS activate when the goal is to create or
  update GitHub resources (issues, PRs, releases, file commits). Validate
  repository access before any write operation. NEVER push content containing
  secrets or internal file paths. NEVER create a PR without Summary and Test
  Plan sections.
---

# GitHub Publishing Workflow

## 适用场景
将 daemon 产出物发布到 GitHub 仓库：创建 Issue、Pull Request、Release，
或向现有 PR 推送代码变更。适用于 engineer 完成编码后的交付环节。

## 输入
- `action`: `create_issue` | `create_pr` | `create_release` | `push_commit`
- `repo`: 目标仓库（格式：`owner/repo`）
- `title`: Issue/PR/Release 标题
- `body`: 正文内容（Markdown）
- `branch`: 目标分支（PR 时必填）
- `labels`: 标签数组（可选）
- `draft`: 是否草稿（PR 专用，默认 false）
- `tag_name`: Release 版本号（release 专用，如 `v1.2.3`）

## 执行步骤

### create_issue
1. 验证仓库存在且有写权限
2. 格式化 Issue 正文（含复现步骤 / 期望行为 / 实际行为 / 环境信息）
3. 通过 GitHub MCP `github_create_issue` 创建
4. 添加 labels（bugfix / enhancement / documentation 等）
5. 返回 Issue URL

### create_pr
1. 检查源分支是否存在，是否有新 commit（相对于目标分支）
2. 检查目标分支保护规则（是否需要 review / CI 通过）
3. 格式化 PR 正文：
   ```
   ## Summary
   [1-3 bullet points about what changed and why]

   ## Changes
   [Detailed change list]

   ## Test Plan
   - [ ] [test item 1]
   - [ ] [test item 2]

   🤖 Generated with daemon publisher
   ```
4. 通过 GitHub MCP `github_create_pull_request` 创建
5. 添加 labels 和 reviewers（如有配置）
6. 返回 PR URL

### create_release
1. 确认 tag_name 格式符合语义化版本（vX.Y.Z）
2. 从 Artifact 或 job 输出中提取 changelog 内容
3. 创建 Git tag（如不存在）
4. 通过 GitHub MCP `github_create_release` 发布
5. 上传 release assets（如有 MinIO artifact 附件）
6. 返回 Release URL

### push_commit
1. 获取目标文件内容（来自 MinIO artifact 或 job 输出）
2. 检查目标路径是否已存在（create vs update）
3. 通过 GitHub MCP `github_create_or_update_file` 推送
4. 确认 commit SHA 并返回

## 质量标准
- PR 标题不超过 70 字符
- PR 正文必须包含 Summary 和 Test Plan 章节
- Issue 正文必须结构化（避免纯文本描述）
- Release notes 必须说明新增/变更/修复（对应 Added/Changed/Fixed）
- 所有 URL 推送前必须验证仓库存在且可写

## 发布前检查清单
- [ ] 目标仓库和分支存在
- [ ] 内容经过 reviewer 审阅（对 public 仓库）
- [ ] 不包含 secrets 或内部路径
- [ ] 标题/正文格式符合目标仓库规范（检查 CONTRIBUTING.md）

## 常见失败模式
- 分支不存在或 base 分支已更新 → 先同步分支再创建 PR
- 标题超长 → 截断到 70 字符，把详情放 body
- 没有 push 权限 → 检查 GitHub token 权限（需要 repo 或 public_repo scope）
- Release tag 已存在 → 检查是否需要更新现有 release 而非创建新的

## 输出格式
返回创建的资源 URL，例如：
- Issue: `https://github.com/owner/repo/issues/123`
- PR: `https://github.com/owner/repo/pull/456`
- Release: `https://github.com/owner/repo/releases/tag/v1.2.3`
