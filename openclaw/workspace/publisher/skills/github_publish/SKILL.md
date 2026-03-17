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

## When to Activate
When publishing daemon artifacts to a GitHub repository: creating Issues, Pull Requests, Releases, or pushing code changes to an existing PR. Used in the delivery step after engineer completes coding.

## Input
- `action`: `create_issue` | `create_pr` | `create_release` | `push_commit`
- `repo`: Target repository (format: `owner/repo`)
- `title`: Issue/PR/Release title
- `body`: Body content (Markdown)
- `branch`: Target branch (required for PR)
- `labels`: Label array (optional)
- `draft`: Whether draft (PR only, default false)
- `tag_name`: Release version (release only, e.g., `v1.2.3`)

## Execution Steps

### create_issue
1. Verify repository exists and has write access
2. Format Issue body (include reproduction steps / expected behavior / actual behavior / environment info)
3. Create via GitHub MCP `github_create_issue`
4. Add labels (bugfix / enhancement / documentation etc.)
5. Return Issue URL

### create_pr
1. Check source branch exists and has new commits (relative to target branch)
2. Check target branch protection rules (whether review / CI pass required)
3. Format PR body:
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
4. Create via GitHub MCP `github_create_pull_request`
5. Add labels and reviewers (if configured)
6. Return PR URL

### create_release
1. Confirm tag_name follows semantic versioning (vX.Y.Z)
2. Extract changelog content from Artifact or job output
3. Create Git tag (if not exists)
4. Publish via GitHub MCP `github_create_release`
5. Upload release assets (if MinIO artifact attachments exist)
6. Return Release URL

### push_commit
1. Get target file content (from MinIO artifact or job output)
2. Check whether target path already exists (create vs update)
3. Push via GitHub MCP `github_create_or_update_file`
4. Confirm commit SHA and return

## Quality Standards
- PR title under 70 characters
- PR body must include Summary and Test Plan sections
- Issue body must be structured (avoid plain text descriptions)
- Release notes must describe Added/Changed/Fixed
- All URLs must be verified writable before push

## Pre-Publish Checklist
- [ ] Target repository and branch exist
- [ ] Content reviewed by reviewer (for public repositories)
- [ ] Contains no secrets or internal paths
- [ ] Title/body format matches target repository conventions (check CONTRIBUTING.md)

## Common Failure Modes
- Branch does not exist or base branch has been updated → sync branch before creating PR
- Title too long → truncate to 70 characters, put details in body
- No push permission → check GitHub token permissions (needs repo or public_repo scope)
- Release tag already exists → check whether to update existing release instead of creating new one

## Output Format
Return the created resource URL, for example:
- Issue: `https://github.com/owner/repo/issues/123`
- PR: `https://github.com/owner/repo/pull/456`
- Release: `https://github.com/owner/repo/releases/tag/v1.2.3`
