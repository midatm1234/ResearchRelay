# Portable artifact contract

Artifacts are ordinary UTF-8 Markdown files with YAML front matter. Five bundled
JSON Schemas describe schema version `1.0`: meeting, task, result, review, decision.
Use `researchrelay.artifacts.validate_artifact`, `render_markdown`, and `parse_markdown`
to validate and exchange records. JSON Schemas ship in `researchrelay/schemas`.

`schema_version` versions the format. `version` versions the content of one stable
`id`. An input reference always has `{id, version}` and may additionally include a
SHA-256 digest. References never mean “whatever is latest.” The database stores
immutable artifact revisions. Content changes under an existing artifact ID must
increment its version. Scope approval freezes the participant's edited proposals
in task definitions; the original meeting record retains its original proposals.
SQLite owns execution state. Committed task status is a generated snapshot.

Common fields identify the project, responsible participant, producing agent,
timezone-aware creation/update timestamps (generated in UTC), objective, dependencies, inputs, expected outputs,
acceptance criteria, validation, open questions, next actions, files, commits, and
pull requests. Result records additionally require data, code, configuration,
environment, and evidence. Record external data URI, content hash, access notes,
code commit, relevant settings, and environment versions here; keep large files
in external storage. Record assumptions and limitations even when inconclusive.

Review records identify the exact result version and justify approval/revision
against acceptance criteria. Human decision records retain the question,
evidence, available options, downstream consequences, and eventual rationale.
Agent approval and computational completion do not establish scientific validity.

The local meeting extractor supports explicit markers:

```text
Decision: Use paired observations because missing samples can bias comparison.
Task forecast-a | owner=alice | Compare forecast A | criteria=Report RMSE and bias | outputs=metrics-a.json
Task forecast-b | owner=bob | Compare forecast B | criteria=Report RMSE and bias | outputs=metrics-b.json
Task synthesis | owner=alice | Compare both forecasts | depends=forecast-a,forecast-b | criteria=Quantify uncertainty | outputs=comparison.md
Question: Is the improvement scientifically useful?
```

Natural assignments such as “Alice will inspect station coverage” are recognized,
but unstated criteria, IDs, outputs, or dependencies remain labeled inferred.
Unrecognized text remains in the summary/original notes. No executable tasks are
created until a participant edits and approves the proposed scope. If the parser
cannot find tasks it proposes a clearly inferred scope clarification task.

Parsing rejects duplicate YAML keys, aliases, invalid timestamps, unsupported
schema versions, unsafe IDs, and unpinned input references. Named secret fields
are rejected recursively in metadata; this is a guardrail, not content redaction.
Participants must avoid pasting credentials into prose or meeting notes.

Artifact IDs contain at most 128 letters, digits, dots, underscores, or hyphens;
they begin with a letter/digit and cannot contain consecutive dots. Task IDs use
the same character set with a 96-character bound, leaving room for generated
result/review prefixes. References use the exact artifact ID, which may differ
from the execution task ID (the service's task definition ID is `task-<task-id>`).

`examples/artifacts/` contains five small schema illustrations with four-row
synthetic data. `examples/pilot-record/` contains actual records from an executed
local pilot, including both synthesis result versions and their reviews. These
are separate examples; running `researchrelay demo` generates a fresh project record.
Direct Git imports add evidence artifacts; they never execute imported task
definitions, apply imported review state, or resolve scientific decisions. Use
the coordination API for those authoritative transitions.

When an imported result revision supersedes an upstream task's historical
completion version, dependent queued work becomes stale. A human reviews that
change and calls `POST /api/tasks/<id>/retry` with the complete reconciled
`input_refs` list, naming the intended replacement version. This is also allowed
for queued stale tasks that have never run. An explicit pin overrides the
inherited reference for the same artifact ID; the upstream task keeps its
historical completion record. A worker claim then persists and consumes exactly
those reconciled versions. The service never selects the newest version silently.

Regenerate schemas after changing `_generate.py` with:
`python researchrelay/schemas/_generate.py`. Intentional extension metadata is allowed
so external analysis tools can preserve domain-specific details.
