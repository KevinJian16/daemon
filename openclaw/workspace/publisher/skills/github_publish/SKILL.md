# GitHub Publish

## 适用场景
在 GitHub 创建格式规范的 Issue 或 Pull Request。

## 输入
类型（issue/pr）+ 标题 + 正文内容 + labels + 目标仓库/分支。

## 执行步骤
1. 验证目标仓库和分支存在
2. 按模板格式化标题和正文（Summary / Changes / Test Plan）
3. 通过 GitHub MCP 创建 issue 或 PR
4. 添加 labels 和 assignees

## 质量标准
- 标题不超过 70 字符
- PR 正文必须包含 Summary 和 Test Plan
- Issue 必须包含复现步骤（如适用）

## 常见失败模式
- 分支不存在或已过期导致 PR 创建失败
- 标题过长或格式不规范

## 输出格式
返回创建的 issue/PR URL。
