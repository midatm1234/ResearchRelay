---
id: source-fourney-2024-magentic-one
project_id: agentic-collaboration
schema_version: '1.0'
artifact_type: source_note
version: 1
type: Literature Source
title: 'Magentic-One: A Generalist Multi-Agent System for Solving Complex Tasks'
description: An orchestrator delegates to specialized agents, monitors progress, and
  replans after problems across several computer-use benchmarks.
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
- id: fourney-2024-magentic-one
  resource: https://arxiv.org/abs/2411.04468
  title: 'Magentic-One: A Generalist Multi-Agent System for Solving Complex Tasks'
citations:
- source_id: fourney-2024-magentic-one
  url: https://arxiv.org/abs/2411.04468
relations: []
provenance:
  method: primary-source web search and agent-authored synthesis
  search_date: '2026-11-04'
  search_timezone: America/Los_Angeles
  human_reviewed: false
  source_access: arXiv abstract and Microsoft technical-report metadata; no peer-reviewed
    venue established
bibliography:
  title: 'Magentic-One: A Generalist Multi-Agent System for Solving Complex Tasks'
  authors:
  - Adam Fourney
  - Gagan Bansal
  - Hussein Mozannar
  - Cheng Tan
  - Eduardo Salinas
  - Erkang Zhu
  - Friederike Niedtner
  - Grace Proebsting
  - Griffin Bassman
  - Jack Gerrits
  - Jacob Alber
  - Peter Chang
  - Ricky Loynd
  - Robert West
  - Victor Dibia
  - Ahmed Awadallah
  - Ece Kamar
  - Rafah Hosn
  - Saleema Amershi
  year: 2024
  kind: preprint
  venue: Microsoft technical report MSR-TR-2024-47 / arXiv:2411.04468
  doi: 10.48550/arXiv.2411.04468
  url: https://arxiv.org/abs/2411.04468
  access: arXiv abstract and Microsoft technical-report metadata; no peer-reviewed
    venue established
tags:
- literature
- preprint
---

# Magentic-One: A Generalist Multi-Agent System for Solving Complex Tasks

## Findings

An orchestrator delegates to specialized agents, monitors progress, and replans after problems across several computer-use benchmarks.[^fourney-2024-magentic-one]

## Methods

GAIA, AssistantBench, and WebArena evaluation with ablations and an isolation/repetition-oriented evaluation harness.[^fourney-2024-magentic-one]

## Limitations

General computer-use benchmarks differ from long-running scientific teamwork; benchmark results do not validate scientific conclusions or multi-user governance.

## Implications for ResearchRelay — design inference

Persist plan/progress separately, bound retries, retain blockers, and isolate repeated executions before attributing gains to coordination.

## Related project knowledge

This note informs the [synthesis](../synthesis.md) and [follow-up questions](../open-questions.md).

[^fourney-2024-magentic-one]: [Primary source](https://arxiv.org/abs/2411.04468). Bibliographic status and access scope are recorded in front matter.
