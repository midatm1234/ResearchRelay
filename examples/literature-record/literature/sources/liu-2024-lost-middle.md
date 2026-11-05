---
id: source-liu-2024-lost-middle
project_id: agentic-collaboration
schema_version: '1.0'
artifact_type: source_note
version: 1
type: Literature Source
title: 'Lost in the Middle: How Language Models Use Long Contexts'
description: Relevant information can be used less reliably when placed in the middle
  of long contexts, even in long-context-capable models.
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
- id: liu-2024-lost-middle
  resource: https://aclanthology.org/2024.tacl-1.9/
  title: 'Lost in the Middle: How Language Models Use Long Contexts'
citations:
- source_id: liu-2024-lost-middle
  url: https://aclanthology.org/2024.tacl-1.9/
relations: []
provenance:
  method: primary-source web search and agent-authored synthesis
  search_date: '2026-11-04'
  search_timezone: America/Los_Angeles
  human_reviewed: false
  source_access: publisher abstract, citation metadata and BibTeX
bibliography:
  title: 'Lost in the Middle: How Language Models Use Long Contexts'
  authors:
  - Nelson F. Liu
  - Kevin Lin
  - John Hewitt
  - Ashwin Paranjape
  - Michele Bevilacqua
  - Fabio Petroni
  - Percy Liang
  year: 2024
  kind: published_paper
  venue: Transactions of the Association for Computational Linguistics 12, 157–173
  doi: 10.1162/tacl_a_00638
  url: https://aclanthology.org/2024.tacl-1.9/
  access: publisher abstract, citation metadata and BibTeX
tags:
- literature
- published_paper
---

# Lost in the Middle: How Language Models Use Long Contexts

## Findings

Relevant information can be used less reliably when placed in the middle of long contexts, even in long-context-capable models.[^liu-2024-lost-middle]

## Methods

Position-controlled multi-document question answering and key-value retrieval evaluations.[^liu-2024-lost-middle]

## Limitations

The tested models and synthetic/task settings do not determine present-day model performance or an optimal project-memory policy.

## Implications for ResearchRelay — design inference

Offer an index and focused source notes, pin the context actually consumed, and test whether important unresolved questions survive handoffs.

## Related project knowledge

This note informs the [synthesis](../synthesis.md) and [follow-up questions](../open-questions.md).

[^liu-2024-lost-middle]: [Primary source](https://aclanthology.org/2024.tacl-1.9/). Bibliographic status and access scope are recorded in front matter.
