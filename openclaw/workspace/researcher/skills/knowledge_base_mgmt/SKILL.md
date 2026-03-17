---
name: knowledge-base-mgmt
description: >-
  Manage the RAGFlow knowledge base: ingest, update, remove, or audit documents
  in the corpus. ALWAYS activate when documents need to be added to, removed
  from, or verified in the knowledge base. Confirm indexing status after ingest;
  run sample retrieval queries during audit. NEVER delete a document without
  checking for active references first.
---

# Skill: knowledge_base_mgmt

## Purpose
Manage the RAGFlow knowledge base: ingest new documents, update stale entries, remove outdated sources, and verify retrieval quality for project-specific and global corpora.

## Steps
1. Receive a knowledge operation request (ingest / update / remove / audit)
2. For ingest: validate source format, call RAGFlow upload API, confirm indexing status
3. For update: locate existing document by ID, re-upload with updated content, verify version bump
4. For remove: mark document as expired in knowledge_cache, call RAGFlow delete API
5. For audit: run sample queries against the corpus, compare retrieval relevance scores against baseline
6. Write operation result to Step output with source markers (`[EXT:url]` or `[INT:persona]`)

## Input
- Operation type: ingest | update | remove | audit
- Document URL or content (for ingest/update)
- Document ID (for update/remove)
- Project ID (optional, scopes to project corpus)

## Output
- Operation status (success / partial / failed)
- Document ID and RAGFlow index status
- For audit: retrieval quality score and sample results

## Token Budget
~2000 tokens (mostly API calls, minimal LLM reasoning)
