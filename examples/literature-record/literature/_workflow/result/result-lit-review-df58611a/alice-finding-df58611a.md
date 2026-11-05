---
id: reference-alice-finding-df58611a
project_id: agentic-collaboration
schema_version: '1.0'
version: 1
artifact_type: reference
type: Reference
title: Historical reference to Alice's published finding
description: Resolve the original relative link without modifying Bob's accepted result
  version.
responsible_participant: midatm1234
producing_agent: codex-link-repair/2026-11-04
created_at: '2026-11-04T23:09:08.849189+00:00'
updated_at: '2026-11-04T23:09:08.849189+00:00'
status: draft
format_status: provisional
generated:
  by: codex-link-repair/2026-11-04
  at: '2026-11-04T23:09:08.849189+00:00'
sources:
- id: alice-finding
  resource: https://github.com/midatm1234/ResearchRelay/blob/cf95142ca465251311e7256b788cabbf491fdd7a/projects/agentic-collaboration/pilot/alice-finding-df58611a.md
- id: historical-result
  resource: https://github.com/midatm1234/ResearchRelay/blob/b6b378ff170d68a681cd92255b222102ef390520/projects/agentic-collaboration/_workflow/result/result-lit-review-df58611a/v1.md
citations:
- source_id: alice-finding
  url: https://github.com/midatm1234/ResearchRelay/blob/cf95142ca465251311e7256b788cabbf491fdd7a/projects/agentic-collaboration/pilot/alice-finding-df58611a.md
- source_id: historical-result
  url: https://github.com/midatm1234/ResearchRelay/blob/b6b378ff170d68a681cd92255b222102ef390520/projects/agentic-collaboration/_workflow/result/result-lit-review-df58611a/v1.md
relations:
- type: redirects_to
  target: /pilot/alice-finding-df58611a.md
  commit: cf95142ca465251311e7256b788cabbf491fdd7a
- type: repairs_reference_from
  target: /_workflow/result/result-lit-review-df58611a/v1.md
  commit: b6b378ff170d68a681cd92255b222102ef390520
provenance:
  method: Added a Reference at the historical relative-link target
  reason: The same accepted body was projected into two directories; its relative
    link resolved differently.
  original_reference: ./alice-finding-df58611a.md
  original_result_commit: b6b378ff170d68a681cd92255b222102ef390520
  target_commit: cf95142ca465251311e7256b788cabbf491fdd7a
  target_sha256: e299782d09e3d41cd814e4b2da5803419d88b9b882ce9aed775c2fca86a6b24e
  human_reviewed: false
objective: Keep the historical reference navigable while preserving accepted result
  bytes and Git history.
---

# Historical reference to Alice's finding

Continue to [Alice's published finding](../../../pilot/alice-finding-df58611a.md), or read its [exact committed version](https://github.com/midatm1234/ResearchRelay/blob/cf95142ca465251311e7256b788cabbf491fdd7a/projects/agentic-collaboration/pilot/alice-finding-df58611a.md).[^alice-finding]

This Reference was added because [Bob's accepted result v1](./v1.md) used `./alice-finding-df58611a.md`. That link worked in the `pilot/` copy, but its identical body resolved to this different directory in the generated workflow record.[^historical-result]

The accepted result and its history are preserved. This file repairs navigation; it does not revise the result, add scientific evidence, or claim an independent review. The original result's version-pinned input metadata remains authoritative for what Bob consumed.

[^alice-finding]: [Alice's finding at its publishing commit](https://github.com/midatm1234/ResearchRelay/blob/cf95142ca465251311e7256b788cabbf491fdd7a/projects/agentic-collaboration/pilot/alice-finding-df58611a.md).
[^historical-result]: [Bob's original workflow result at its publishing commit](https://github.com/midatm1234/ResearchRelay/blob/b6b378ff170d68a681cd92255b222102ef390520/projects/agentic-collaboration/_workflow/result/result-lit-review-df58611a/v1.md).
