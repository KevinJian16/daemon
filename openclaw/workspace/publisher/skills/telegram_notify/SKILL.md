# Telegram Notify

## 适用场景
通过 OC 原生 Telegram channel 发送格式化通知。

## 输入
通知类型（info/warning/error）+ 消息内容 + 可选附件。

## 执行步骤
1. 根据通知类型选择模板和标记前缀
2. 格式化消息为 Telegram MarkdownV2
3. 转义特殊字符（`.` `_` `(` `)` 等）
4. 通过 Telegram MCP 发送到指定 channel

## 质量标准
- 消息长度不超过 4096 字符，超长需拆分
- 特殊字符必须正确转义

## 常见失败模式
- MarkdownV2 转义遗漏导致发送失败
- 消息过长未拆分被 API 拒绝

## 输出格式
发送成功返回 message_id，失败返回错误原因。
