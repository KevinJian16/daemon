# SKILL_GRAPH.md — publisher

## Entry Points
- "publish to github" | "push" → github_publish
- "release" | "deploy" → release_checklist
- "notify" | "send message" → telegram_notify
- "adapt format" | "cross-platform" | "reformat for" → platform_adaptation

## Edges
- release_checklist → github_publish (release includes GitHub publish)
- github_publish → telegram_notify (notify after successful publish)
- release_checklist → telegram_notify (notify release status)
- platform_adaptation → github_publish (adapted content ready for GitHub)
- platform_adaptation → telegram_notify (adapted content ready for Telegram)
- release_checklist → platform_adaptation (release needs cross-platform formatting)
