---
name: tech-blog
description: >-
  Write a technical blog post targeting developers, with clear structure,
  runnable code examples, and actionable takeaways. ALWAYS activate when the
  goal is to produce a blog post or technical article for a developer audience.
  State reader benefit within the first 3 sentences. NEVER include code examples
  that cannot run standalone. NEVER use undefined technical terms without
  explanation.
---

# Tech Blog

## 适用场景
需要撰写技术博客文章，面向开发者或技术受众。

## 输入
- `topic`: 主题或标题
- `audience`: 目标读者（默认：中级开发者）
- `length`: 目标字数（默认：1500）

## 执行步骤
1. 确定核心论点和读者收益
2. 拟定大纲：引言、正文（2-4 节）、总结
3. 撰写初稿，每节配代码示例或图示说明
4. 检查技术准确性和行文流畅度
5. 写入文件并返回路径

## 质量标准
- 开头 3 句内点明读者能学到什么
- 代码示例可直接运行
- 无未定义术语，首次出现需解释

## 常见失败模式
- 堆砌概念缺乏实例
- 代码片段缺少上下文或依赖说明
- 结尾无行动号召

## 输出格式
Markdown 文件，含 YAML front matter（title, date, tags）。
