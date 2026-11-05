---
id: search-record-2026-11-04
project_id: agentic-collaboration
schema_version: '1.0'
artifact_type: search_log
version: 1
type: Search Record
title: 'Search record: 2026-11-04'
description: Actual queries, screening decisions, access limitations, and update protocol.
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
- id: vaccaro-2024-human-ai
  resource: /sources/vaccaro-2024-human-ai.md
  title: 'When combinations of humans and AI are useful: A systematic review and meta-analysis'
- id: amershi-2019-guidelines
  resource: /sources/amershi-2019-guidelines.md
  title: Guidelines for Human-AI Interaction
- id: wu-2024-autogen
  resource: /sources/wu-2024-autogen.md
  title: 'AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversations'
- id: hong-2024-metagpt
  resource: /sources/hong-2024-metagpt.md
  title: 'MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework'
- id: shao-2024-storm
  resource: /sources/shao-2024-storm.md
  title: Assisting in Writing Wikipedia-like Articles From Scratch with Large Language
    Models
- id: schmidgall-2025-agent-laboratory
  resource: /sources/schmidgall-2025-agent-laboratory.md
  title: 'Agent Laboratory: Using LLM Agents as Research Assistants'
- id: fourney-2024-magentic-one
  resource: /sources/fourney-2024-magentic-one.md
  title: 'Magentic-One: A Generalist Multi-Agent System for Solving Complex Tasks'
- id: liu-2024-lost-middle
  resource: /sources/liu-2024-lost-middle.md
  title: 'Lost in the Middle: How Language Models Use Long Contexts'
- id: yang-2024-swe-agent
  resource: /sources/yang-2024-swe-agent.md
  title: 'SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering'
- id: w3c-2013-prov
  resource: /sources/w3c-2013-prov.md
  title: 'PROV-DM: The PROV Data Model'
- id: git-2026-worktree
  resource: /sources/git-2026-worktree.md
  title: 'git-worktree: Manage multiple working trees'
- id: google-2026-okf
  resource: /sources/google-2026-okf.md
  title: Open Knowledge Format (OKF), Version 0.2
citations: []
relations: []
provenance:
  method: primary-source web search and agent-authored synthesis
  search_date: '2026-11-04'
  search_timezone: America/Los_Angeles
  human_reviewed: false
---

# Search record

## Date and method

Search performed **2026-11-04**, America/Los_Angeles, using web search followed by primary-source retrieval. This is a focused scoping search, not a database-complete or preregistered systematic review. No database hit-count or PRISMA count is asserted: the search interface mixes duplicates, previews, and unrelated news.

## Queries actually used

1. `"Open Knowledge Format" specification Markdown agents`
2. `AutoGen Enabling Next-Gen LLM Applications Multi-Agent Conversation COLM 2024 OpenReview`
3. `When combinations of humans and AI are useful systematic review meta-analysis Nature Human Behaviour 2024`
4. `site.aclanthology.org 2024 STORM Assisting in Writing Wikipedia-like Articles From Scratch`
5. `site.openreview.net MetaGPT Meta Programming Multi-Agent Collaborative Framework ICLR 2024`
6. `site.microsoft.com research Guidelines Human AI Interaction 2019 Amershi`
7. `site.arxiv.org Agent Laboratory Using LLM Agents as Research Assistants 2501`
8. `site.arxiv.org Magentic-One Generalist Multi-Agent System Solving Complex Tasks 2024`
9. `site.proceedings.neurips.cc SWE-agent Agent-Computer Interfaces Enable Automated Software Engineering 2024`
10. `site.aclanthology.org Lost in the Middle How Language Models Use Long Contexts 2024`
11. `SWE-agent Agent-Computer Interfaces Enable Automated Software Engineering 2024 [restricted to proceedings.neurips.cc]`
12. `Agent Laboratory 2501.04227 [restricted to openreview.net and arxiv.org]`
13. `Magentic-One A Generalist Multi-Agent System 2411.04468 [restricted to arxiv.org and microsoft.com]`
14. `"Magentic-One" conference published COLM 2025 2026 [restricted to arxiv.org, openreview.net, microsoft.com]`
15. `"Agent Laboratory" "Schmidgall" published conference 2025 2026 [restricted to arxiv.org, openreview.net, proceedings.mlr.press, neurips.cc]`

## Primary record verification

Opened each included source's publisher/proceedings, author, arXiv, or official documentation record. ACL BibTeX exports confirmed STORM and Lost in the Middle metadata/DOIs. COLM's accepted-paper list and search-indexed conference PDF metadata established AutoGen's 2024 publication; direct OpenReview retrieval encountered a browser verification challenge. NeurIPS proceedings confirmed SWE-agent's venue and DOI. Agent Laboratory and Magentic-One remain labeled preprints/technical reports: no peer-reviewed venue was established in the inspected records. Access is recorded per note rather than assumed to be full-text review.

The OKF search found Google's prior knowledge-catalog location and its migration notice. Canonical SPEC.md was pinned with `git ls-remote` and raw-file retrieval to commit `ad30107c31c06aec8a7d5636e0d1058118604e6f`, SHA-256 `26aa5da029278939f914e578107242d9607d4f2dc5fe153272b82f9ed1030101`, version 0.2. Existing ResearchRelay documentation did not bind an intended specification. See [format choice](format-choice.md).

## Inclusion and exclusion

Include primary empirical/framework papers relevant to human/agent collaboration, scientific pipelines, multi-agent coordination, memory, or repository execution; include official standards/documentation for provenance and exchange. Prefer established published versions to duplicate preprints. Exclude duplicate records, unverifiable claims, unrelated news, social posts, and productivity conclusions without stated comparators. Search/social results were discovery leads only.

## Access and coverage limitations

Most paper notes summarize abstracts and bibliographic pages; the Amershi camera-ready abstract/evaluation description and search-indexed AutoGen conference PDF abstract/author metadata were also inspected. Direct OpenReview access was challenged. This is not full methodological appraisal. Ranking changes across dates; emerging 2026 work may be missed, and selected records favor accessible English-language material. The scientific-agent literature is underrepresented by this initial seed set. Publication status was checked for the cited records and targeted later-venue queries, not through an exhaustive search of every venue. Search hits headed with later conference names sometimes only cite these preprints; those headings were not treated as evidence that the cited preprint was accepted there.

## Update protocol

1. Repeat these queries with a new date; inspect newly relevant primary records and publication/version changes.
2. Preserve source IDs and record changed versions, access scope, and primary identifiers.
3. Revise notes with new content versions and explicit attribution; use stable source-keyed citations.
4. Ask another participant to review status classification, contrary evidence, and synthesis.
5. Refresh the [index](literature-index.md), [questions](open-questions.md), log, and Git record.
