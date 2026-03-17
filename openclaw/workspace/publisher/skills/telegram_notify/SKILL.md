---
name: telegram-notify
description: >-
  Send formatted notifications through the Telegram channel using MarkdownV2
  formatting. ALWAYS activate when a notification must be delivered to the user
  via Telegram. Escape all MarkdownV2 special characters. NEVER send messages
  exceeding 4096 characters without splitting. NEVER send unescaped special
  characters that would cause API rejection.
---

# Telegram Notify

## When to Activate
When sending formatted notifications through the OC native Telegram channel.

## Input
Notification type (info/warning/error) + message content + optional attachments.

## Execution Steps
1. Select template and prefix marker based on notification type
2. Format message as Telegram MarkdownV2
3. Escape special characters (`.` `_` `(` `)` etc.)
4. Send to designated channel via Telegram MCP

## Quality Standards
- Message length must not exceed 4096 characters; split if longer
- Special characters must be properly escaped

## Common Failure Modes
- Missing MarkdownV2 escaping causes send failure
- Message too long without splitting, rejected by API

## Output Format
On success, return message_id. On failure, return error reason.
