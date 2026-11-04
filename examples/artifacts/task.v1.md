---
id: forecast-a
project_id: example-project
artifact_type: task
responsible_participant: alice
producing_agent: local-rules-extractor/1.0
created_at: '2026-11-03T12:00:00Z'
updated_at: '2026-11-03T12:00:00Z'
title: Evaluate forecast A
owner: alice
objective: Evaluate forecast A
dependencies: []
input_refs:
- id: meeting-14a43ac3ec32
  version: 1
expected_outputs:
- metrics-a.json
acceptance_criteria:
- Report RMSE and bias and paired sample count
provenance: explicit_assignment_inferred_details
inferred_fields:
- dependencies
source_quote: Task forecast-a | owner=alice | Evaluate forecast A | criteria=Report
  RMSE and bias and paired sample count | outputs=metrics-a.json
scope_status: approved
schema_version: '1.0'
version: 1
validation_results: []
unresolved_questions: []
next_actions: []
related_files: []
repository_commits: []
pull_requests: []
---

# Approved scope example

Compute RMSE, mean bias, and paired sample count for forecast A.

This file illustrates a task artifact. Execution state comes from SQLite.
