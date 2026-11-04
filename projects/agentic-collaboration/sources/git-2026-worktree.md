---
id: source-git-2026-worktree
project_id: agentic-collaboration
schema_version: '1.0'
artifact_type: source_note
version: 1
type: Literature Source
title: 'git-worktree: Manage multiple working trees'
description: Linked working trees provide separate working directories and per-worktree
  state while sharing a repository object store.
status: draft
responsible_participant: midatm1234
producing_agent: codex-literature-review/2026-11-04
created_at: '2026-11-04T22:23:37.394641Z'
updated_at: '2026-11-04T22:23:37.394641Z'
format_status: provisional
generated:
  by: codex-literature-review/2026-11-04
  at: '2026-11-04T22:23:37.394641Z'
sources:
- id: git-2026-worktree
  resource: https://git-scm.com/docs/git-worktree/2.56.0
  title: 'git-worktree: Manage multiple working trees'
citations:
- source_id: git-2026-worktree
  url: https://git-scm.com/docs/git-worktree/2.56.0
relations: []
provenance:
  method: primary-source web search and agent-authored synthesis
  search_date: '2026-11-04'
  search_timezone: America/Los_Angeles
  human_reviewed: false
  source_access: official command documentation and worktree semantics
bibliography:
  title: 'git-worktree: Manage multiple working trees'
  authors:
  - Git project
  year: 2026
  kind: software_documentation
  venue: Git reference manual, documentation version 2.56.0
  doi: null
  url: https://git-scm.com/docs/git-worktree/2.56.0
  access: official command documentation and worktree semantics
tags:
- literature
- software_documentation
---

# git-worktree: Manage multiple working trees

## Findings

Linked working trees provide separate working directories and per-worktree state while sharing a repository object store.[^git-2026-worktree]

## Methods

Operational documentation for branching, worktree lifecycle, repair, and repository metadata.[^git-2026-worktree]

## Limitations

Worktrees are not security sandboxes and do not resolve competing edits or enforce a team review policy by themselves.

## Implications for ResearchRelay — design inference

Use isolated workspaces for execution and normal non-force pushes, while detecting stale touched files and presenting reconciliation choices.

## Related project knowledge

This note informs the [synthesis](../synthesis.md) and [follow-up questions](../open-questions.md).

[^git-2026-worktree]: [Primary source](https://git-scm.com/docs/git-worktree/2.56.0). Bibliographic status and access scope are recorded in front matter.
