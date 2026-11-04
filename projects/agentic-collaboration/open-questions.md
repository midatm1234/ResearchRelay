---
id: open-questions
project_id: agentic-collaboration
schema_version: '1.0'
artifact_type: question
version: 1
type: Research Questions
title: Open scientific and design questions
description: Decisions requiring judgment and proposed follow-up work.
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

# Questions requiring participants

1. **Evaluation:** Which quality rubric and human-only/agent-only baselines should be compared? Consequence: determines whether a time saving is meaningful.
2. **Review intensity:** Which claims need full-text appraisal or independent review? Consequence: trades effort against error propagation.
3. **Delegation:** Which choices may an agent make inside approved scope? Consequence: determines human-decision blockers.
4. **Memory:** Does progressive disclosure preserve open questions better than a complete history? Consequence: defines a comprehension experiment.
5. **Publication:** Should the shared branch accept direct proposals or require PR review? Consequence: changes latency and necessary repository permissions.
6. **Format:** Does the team confirm the selected Google OKF 0.2 reference? Consequence: the ResearchRelay profile remains provisional pending that decision and interoperability checks.

## Proposed follow-up work

- [Audit publication status and full-text evidence](tasks/audit-sources.md).
- [Evaluate handoff comprehension](tasks/evaluate-handoff.md).
- [Design bounded review](tasks/design-review.md).

A participant must assign owners, confirm scope/criteria/dependencies, and approve execution. No human answer or scientific sign-off has been invented.
