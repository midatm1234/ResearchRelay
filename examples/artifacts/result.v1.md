---
id: result-forecast-a
project_id: example-project
artifact_type: result
task_id: forecast-a
responsible_participant: alice
producing_agent: example-stdlib-worker/1.0
objective: Evaluate forecast A
input_refs:
- id: forecast-a
  version: 1
expected_outputs:
- metrics-a.json
acceptance_criteria:
- Report RMSE and bias and paired sample count
data:
- uri: examples/illustrative-observations.csv
  sha256: 491e63dd69f9534a6dec47fc55e444c1ab443b6f1ec81b235363518225ed3361
  paired_days: 4
code:
  implementation: sqrt(sum((prediction-observation)**2)/n); mean(prediction-observation)
  source: This self-contained illustrative fixture; actual pilot records its code
    commit.
configuration:
  forecast: forecast_a
  missing_values: exclude unpaired dates
  units: synthetic degrees
environment:
  python: '3.12'
  dependencies: standard library
evidence:
  n: 4
  rmse: 0.5431390245600108
  bias: 0.25
assumptions:
- Each row represents a paired forecast and observation.
limitations:
- Four synthetic dates provide no evidence of real-world forecast skill.
validation_results:
- Four paired rows checked.
- RMSE and signed mean bias computed.
related_files:
- examples/illustrative-observations.csv
created_at: '2026-11-03T12:00:00Z'
updated_at: '2026-11-03T12:00:00Z'
schema_version: '1.0'
version: 1
dependencies: []
unresolved_questions: []
next_actions: []
repository_commits: []
pull_requests: []
---

# Forecast A example result

RMSE: 0.543139; bias: 0.250000; paired count: 4.

These are illustrative synthetic metrics, not a scientific recommendation.
