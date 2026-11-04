---
id: initial-synthesis
project_id: agentic-collaboration
schema_version: '1.0'
artifact_type: synthesis
version: 1
type: Research Synthesis
title: 'Collaborative scientific work with agentic AI: initial synthesis'
description: Evidence themes, design inferences, uncertainty, and pilot measures.
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
relations:
- type: synthesizes
  target: literature-index
provenance:
  method: primary-source web search and agent-authored synthesis
  search_date: '2026-11-04'
  search_timezone: America/Los_Angeles
  human_reviewed: false
---

# Initial synthesis — evidence and design inferences

## Evidence boundaries

This review contains seven published papers, two preprints/technical reports, two specifications, and one software manual. Most findings were extracted from abstracts and primary metadata rather than full-paper appraisal. Valid Markdown and source verification do not establish scientific correctness. See [search limitations](search-record.md).

## Findings supported by the selected sources

- Human–AI combinations need comparison with both components, because synergy varies with tasks and component ability.[^vaccaro-2024-human-ai]
- Understandable behavior and correction paths are established human–AI design concerns.[^amershi-2019-guidelines]
- Frameworks demonstrate configurable conversation, role outputs, and replanning. Architectural feasibility is not a universal multi-agent advantage.[^wu-2024-autogen][^hong-2024-metagpt][^fourney-2024-magentic-one]
- Source-grounded outlining can improve article structure; source bias and unsupported associations remain review targets.[^shao-2024-storm]
- A scientific-assistant pipeline reports benefits from researcher feedback. Its task/model/cost comparisons do not substitute for a ResearchRelay evaluation.[^schmidgall-2025-agent-laboratory]
- Context position and interface design affect evaluated model behavior, motivating focused retrieval and explicit task/result interfaces.[^liu-2024-lost-middle][^yang-2024-swe-agent]

## Design implications — inferred, not validated here

1. Persist bounded task state and versioned inputs for asynchronous handoffs. Conversation history alone should not determine ownership or completion.
2. Distinguish computational completion, independent critique, and human scientific judgment. Humans select questions and methodological direction.
3. Keep an index and focused notes. Record consumed commits and document hashes; reconcile changed inputs explicitly.
4. Isolate workspaces, preserve history, detect touched-file conflicts, and respect repository review rules. Git worktrees are operational isolation, not a security sandbox.[^git-2026-worktree]
5. Record entities, activities, responsible people/agents, and derivation links; provenance is not a truth certificate.[^w3c-2013-prov]
6. Use selected OKF conventions while marking additional ResearchRelay workflow metadata provisional. A knowledge format does not provide identity, permissions, or a scheduler.[^google-2026-okf]

## Unresolved questions

These sources do not establish a real team's time savings, optimal agent topology, sufficient review intensity, or error propagation across long asynchronous chains. See [pilot questions](open-questions.md).

## Pilot measures

Record observed coordination minutes, clarification requests, completion latency, review cycles, rework, blockers, and a short assessment: “Do you understand what others completed and what needs attention next?” Use an agreed comparator and quality rubric. Scripted demonstration timings are not productivity evidence.

[^vaccaro-2024-human-ai]: [When combinations of humans and AI are useful: A systematic review and meta-analysis](sources/vaccaro-2024-human-ai.md).
[^amershi-2019-guidelines]: [Guidelines for Human-AI Interaction](sources/amershi-2019-guidelines.md).
[^wu-2024-autogen]: [AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversations](sources/wu-2024-autogen.md).
[^hong-2024-metagpt]: [MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework](sources/hong-2024-metagpt.md).
[^shao-2024-storm]: [Assisting in Writing Wikipedia-like Articles From Scratch with Large Language Models](sources/shao-2024-storm.md).
[^schmidgall-2025-agent-laboratory]: [Agent Laboratory: Using LLM Agents as Research Assistants](sources/schmidgall-2025-agent-laboratory.md).
[^fourney-2024-magentic-one]: [Magentic-One: A Generalist Multi-Agent System for Solving Complex Tasks](sources/fourney-2024-magentic-one.md).
[^liu-2024-lost-middle]: [Lost in the Middle: How Language Models Use Long Contexts](sources/liu-2024-lost-middle.md).
[^yang-2024-swe-agent]: [SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering](sources/yang-2024-swe-agent.md).
[^w3c-2013-prov]: [PROV-DM: The PROV Data Model](sources/w3c-2013-prov.md).
[^git-2026-worktree]: [git-worktree: Manage multiple working trees](sources/git-2026-worktree.md).
[^google-2026-okf]: [Open Knowledge Format (OKF), Version 0.2](sources/google-2026-okf.md).
