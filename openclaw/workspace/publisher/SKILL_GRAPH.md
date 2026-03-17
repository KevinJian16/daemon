# SKILL_GRAPH.md — publisher

## Entry Points
- "publish to github" | "push" → github_publish
- "release" | "deploy" → release_checklist
- "notify" | "send message" → telegram_notify

## Edges
- release_checklist → github_publish (release includes GitHub publish)
- github_publish → telegram_notify (notify after successful publish)
- release_checklist → telegram_notify (notify release status)
