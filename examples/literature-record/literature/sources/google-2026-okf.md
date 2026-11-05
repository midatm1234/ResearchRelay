---
id: source-google-2026-okf
project_id: agentic-collaboration
schema_version: '1.0'
artifact_type: source_note
version: 1
type: Literature Source
title: Open Knowledge Format (OKF), Version 0.2
description: The specification organizes linked Markdown concepts with YAML metadata,
  source-keyed attribution, authorship/trust signals, and lifecycle information.
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
- id: google-2026-okf
  resource: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/SPEC.md
  title: Open Knowledge Format (OKF), Version 0.2
citations:
- source_id: google-2026-okf
  url: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/SPEC.md
relations: []
provenance:
  method: primary-source web search and agent-authored synthesis
  search_date: '2026-11-04'
  search_timezone: America/Los_Angeles
  human_reviewed: false
  source_access: canonical SPEC.md and repository README; selected reference, intended
    user adoption unconfirmed
bibliography:
  title: Open Knowledge Format (OKF), Version 0.2
  authors:
  - Google Cloud / GoogleCloudPlatform contributors
  year: 2026
  kind: specification
  venue: Canonical repository specification, snapshot ad30107c31c06aec8a7d5636e0d1058118604e6f
  doi: null
  url: https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/SPEC.md
  access: canonical SPEC.md and repository README; selected reference, intended user
    adoption unconfirmed
tags:
- literature
- specification
---

# Open Knowledge Format (OKF), Version 0.2

## Findings

The specification organizes linked Markdown concepts with YAML metadata, source-keyed attribution, authorship/trust signals, and lifecycle information.[^google-2026-okf]

## Methods

A portable format specification with reserved directory indexes and update logs; it does not prescribe execution or a provider.[^google-2026-okf]

## Limitations

Format structure does not authenticate an actor or verify claims. The repository did not previously identify this as its intended specification.

## Implications for ResearchRelay — design inference

Adopt its conventions explicitly as a selected reference, mark the ResearchRelay extension profile provisional, and retain readable sources and links.

## Related project knowledge

This note informs the [synthesis](../synthesis.md) and [follow-up questions](../open-questions.md).

[^google-2026-okf]: [Primary source](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/SPEC.md). Bibliographic status and access scope are recorded in front matter.
