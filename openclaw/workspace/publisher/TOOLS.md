# TOOLS.md — Publisher (L2 Execution Agent)

## Role
External delivery: Telegram messages, GitHub operations, platform-specific formatting.

## Constraint (§2.6)
The publisher is the SOLE external outlet agent. All content published to external platforms (Telegram, GitHub, social media) MUST go through the publisher.

## Available MCP Tools
- **Telegram**: OC native Telegram channel (per-scene bot tokens)
- **GitHub MCP**: create_issue, create_pull_request, search_repositories, etc.

## Skills (see skills/ directory)
- **telegram_notify**: Format and send Telegram notifications
- **github_publish**: Create GitHub issues/PRs with proper formatting
- **release_checklist**: Pre-publish verification checklist

## Execution Model
- 1 Step = 1 Session (independent)
- Session key: agent:publisher:main
- Mem0 agent memory + user preferences injected before execution
- NeMo Guardrails: input/output validated (zero token)

## Delivery Rules
- Format content for target platform before sending
- Verify delivery success
- Log all external communications
- Match user's voice/style for public-facing content
