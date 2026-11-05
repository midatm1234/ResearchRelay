---
project_id: agentic-collaboration
created_at: '2026-11-04T23:00:00Z'
updated_at: '2026-11-04T23:00:00Z'
producing_agent: literature-example/1.0
responsible_participant: alice
format_status: provisional
generated:
  by: literature-example/1.0
  at: '2026-11-04T23:00:00Z'
sources:
- id: vaccaro-2024-human-ai
  resource: https://www.nature.com/articles/s41562-024-02024-1
citations:
- source_id: vaccaro-2024-human-ai
  url: https://www.nature.com/articles/s41562-024-02024-1
provenance:
  method: Illustrative template grounded in the verified source note
  human_reviewed: false
id: result-literature-example
artifact_type: result
task_id: literature-example
input_refs:
- id: meeting-literature-example
  version: 1
- id: task-literature-example
  version: 1
data:
- resource: https://www.nature.com/articles/s41562-024-02024-1
  source_note: projects/agentic-collaboration/sources/vaccaro-2024-human-ai.md
  sha256: af5d4865da10eff7155fdfa794781aa23297ca103994c1bb8e2bc7630bb0769e
code:
  component: researchrelay.pilot
  method: Deterministic inventory of supplied source notes
configuration:
  search_date: '2026-11-04'
  live_search: false
  model_inference_live: false
environment:
  execution: Illustrative Markdown template; not an executed analysis
evidence:
  publication_status: published_paper
  access: publisher full-text HTML and bibliographic record
  finding: Human-AI combinations are task-dependent; synergy must be evaluated rather
    than assumed.
limitations:
- A source note does not establish ResearchRelay productivity gains.
schema_version: '1.0'
version: 1
objective: ''
dependencies: []
expected_outputs: []
acceptance_criteria: []
validation_results: []
unresolved_questions: []
next_actions: []
related_files: []
repository_commits: []
pull_requests: []
assumptions: []
type: Literature Result
---

# Literature result example

Illustrative portable template for the collaborative literature-search workflow.

Human-AI collaboration benefits depend on the task and comparator.[^vaccaro-2024-human-ai]

[^vaccaro-2024-human-ai]: [Published primary source](https://www.nature.com/articles/s41562-024-02024-1).
