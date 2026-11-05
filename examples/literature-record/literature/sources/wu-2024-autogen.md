---
id: source-wu-2024-autogen
project_id: agentic-collaboration
schema_version: '1.0'
artifact_type: source_note
version: 1
type: Literature Source
title: 'AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversations'
description: Configurable agents combine models, people, and tools through programmable
  conversation patterns across varied applications.
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
- id: wu-2024-autogen
  resource: https://openreview.net/pdf?id=BAakY1hNKS
  title: 'AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversations'
citations:
- source_id: wu-2024-autogen
  url: https://openreview.net/pdf?id=BAakY1hNKS
relations: []
provenance:
  method: primary-source web search and agent-authored synthesis
  search_date: '2026-11-04'
  search_timezone: America/Los_Angeles
  human_reviewed: false
  source_access: Search-indexed conference PDF abstract and author metadata; acceptance
    cross-checked against COLM accepted-paper list. Direct OpenReview retrieval
    encountered browser verification.
bibliography:
  title: 'AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversations'
  authors:
  - Qingyun Wu
  - Gagan Bansal
  - Jieyu Zhang
  - Yiran Wu
  - Beibin Li
  - Erkang Zhu
  - Li Jiang
  - Xiaoyun Zhang
  - Shaokun Zhang
  - Jiale Liu
  - Ahmed Hassan Awadallah
  - Ryen W. White
  - Doug Burger
  - Chi Wang
  year: 2024
  kind: published_paper
  venue: Conference on Language Modeling (COLM 2024)
  doi: null
  url: https://openreview.net/pdf?id=BAakY1hNKS
  access: Search-indexed conference PDF abstract and author metadata; acceptance
    cross-checked against COLM accepted-paper list. Direct OpenReview retrieval
    encountered browser verification.
  status_verification_url: https://colmweb.org/2024/AcceptedPapers.html
tags:
- literature
- published_paper
---

# AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversations

## Findings

Configurable agents combine models, people, and tools through programmable conversation patterns across varied applications.[^wu-2024-autogen]

## Methods

Framework implementation and application-specific evaluations using multiple agent interaction arrangements.[^wu-2024-autogen]

## Limitations

Framework case studies do not establish that multi-agent conversation always outperforms simpler execution or reduces scientific coordination costs.

## Implications for ResearchRelay — design inference

Separate provider adapters from coordination policy; persist explicit handoff state instead of treating chat history as the execution ledger.

## Related project knowledge

This note informs the [synthesis](../synthesis.md) and [follow-up questions](../open-questions.md).

[^wu-2024-autogen]: [Primary source](https://openreview.net/pdf?id=BAakY1hNKS). Bibliographic status and access scope are recorded in front matter.
