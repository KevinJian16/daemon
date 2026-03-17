---
name: platform-adaptation
description: >-
  Adapt a finished artifact to the formatting, length, and style constraints of
  a target publishing platform (GitHub, Telegram, social media, etc.). ALWAYS
  activate before publishing when the source artifact format does not match the
  target platform's requirements. Respect platform character limits and
  supported markup. NEVER publish content that exceeds the target platform's
  message size limit without splitting.
---

# Skill: platform_adaptation

## Purpose
Adapt a finished artifact to the formatting, length, and style requirements of a target publishing platform (GitHub, Telegram, social media, Google Drive, etc.) before publishing.

## Steps
1. Receive the source artifact and target platform specification
2. Load platform constraints: character limits, supported formatting (Markdown, HTML, plain text), media requirements
3. Analyze source artifact structure and identify adaptation needs
4. Transform content: adjust formatting, split into parts if exceeding limits, convert media references
5. For social media: generate platform-appropriate summary / thread structure
6. For GitHub: ensure README conventions, license headers, proper Markdown
7. For Telegram: respect 4096-char message limit, use supported HTML tags
8. Validate adapted output against platform constraints
9. Return adapted content ready for publishing

## Input
- Source artifact (via MinIO reference)
- Target platform identifier (github | telegram | gdrive | twitter | xiaohongshu | wechat)
- Publishing parameters (repo name, channel ID, etc.)

## Output
- Adapted content (one or more parts if split required)
- Platform-specific metadata (tags, title, description)
- Validation result (pass / warnings)

## Token Budget
~3500 tokens (content analysis + transformation)
