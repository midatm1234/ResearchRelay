---
id: source-shao-2024-storm
project_id: agentic-collaboration
schema_version: '1.0'
artifact_type: source_note
version: 1
type: Literature Source
title: Assisting in Writing Wikipedia-like Articles From Scratch with Large Language
  Models
description: Perspective-driven questioning and source-grounded outlining improved
  evaluated article organization and breadth over an outline-based retrieval baseline.
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
- id: shao-2024-storm
  resource: https://aclanthology.org/2024.naacl-long.347/
  title: Assisting in Writing Wikipedia-like Articles From Scratch with Large Language
    Models
citations:
- source_id: shao-2024-storm
  url: https://aclanthology.org/2024.naacl-long.347/
relations: []
provenance:
  method: primary-source web search and agent-authored synthesis
  search_date: '2026-11-04'
  search_timezone: America/Los_Angeles
  human_reviewed: false
  source_access: publisher abstract, citation metadata and BibTeX
bibliography:
  title: Assisting in Writing Wikipedia-like Articles From Scratch with Large Language
    Models
  authors:
  - Yijia Shao
  - Yucheng Jiang
  - Theodore Kanell
  - Peter Xu
  - Omar Khattab
  - Monica Lam
  year: 2024
  kind: published_paper
  venue: 'NAACL-HLT 2024, Volume 1: Long Papers, 6252–6278'
  doi: 10.18653/v1/2024.naacl-long.347
  url: https://aclanthology.org/2024.naacl-long.347/
  access: publisher abstract, citation metadata and BibTeX
tags:
- literature
- published_paper
---

# Assisting in Writing Wikipedia-like Articles From Scratch with Large Language Models

## Findings

Perspective-driven questioning and source-grounded outlining improved evaluated article organization and breadth over an outline-based retrieval baseline.[^shao-2024-storm]

## Methods

STORM combines retrieval, simulated expert conversations, FreshWiki outline assessments, and feedback from experienced Wikipedia editors.[^shao-2024-storm]

## Limitations

The task is encyclopedic writing; editor feedback identifies transferred source bias and associations between unrelated facts.

## Implications for ResearchRelay — design inference

Separate source collection from synthesis, keep per-claim citations, and ask a second participant to inspect coverage and unsupported associations.

## Related project knowledge

This note informs the [synthesis](../synthesis.md) and [follow-up questions](../open-questions.md).

[^shao-2024-storm]: [Primary source](https://aclanthology.org/2024.naacl-long.347/). Bibliographic status and access scope are recorded in front matter.
