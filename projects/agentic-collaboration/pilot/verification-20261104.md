---
id: verification-live-pilot-20261104
project_id: agentic-collaboration
artifact_type: verification
type: Workflow Verification
responsible_participant: midatm1234
producing_agent: codex-implementation/2026-11-04
title: Live GitHub literature handoff verification
sources:
- id: alice-publication
  resource: https://github.com/midatm1234/ResearchRelay/commit/cf95142ca465251311e7256b788cabbf491fdd7a
- id: bob-publication
  resource: https://github.com/midatm1234/ResearchRelay/commit/b6b378ff170d68a681cd92255b222102ef390520
provenance:
  run_id: df58611a
  github_transport_live: true
  model_inference_live: false
  transport: SSH, normal Git push
  participant_identity: Two application users; one configured service Git principal
  human_reviewed: false
  stale_edit_http_status: 409
relations:
- type: verifies
  target: ./alice-finding-df58611a.md
- type: verifies
  target: ./bob-review-df58611a.md
schema_version: '1.0'
version: 1
created_at: '2026-11-04T23:10:32.247238Z'
updated_at: '2026-11-04T23:10:32.247238Z'
format_status: provisional
citations: []
generated:
  by: codex-implementation/2026-11-04
  at: '2026-11-04T23:10:32.247238Z'
---

# Live literature handoff

This software integration run used two participant-owned **scripted command agents** with verified source context. It exercised real GitHub SSH reads and writes on `SRTD_DT_test`. It did not invoke Claude/GPT or authenticate two different GitHub accounts.

1. Alice retrieved the committed literature bundle, ran her scoped task, submitted its result, and [published a finding](alice-finding-df58611a.md).[^alice-publication]
2. Bob retrieved Alice's Git update, reviewed the exact result version, and ran a dependency-gated extension using the accepted result and W3C provenance evidence.
3. Alice reviewed Bob's result. Bob then [published his review and extension](bob-review-df58611a.md). Alice retrieved it.[^bob-publication]
4. A publication based on the original context tried to reuse Alice's newly occupied path. The API returned HTTP **409**, preserving the committed finding.
5. Both executable test tasks reached `completed`. Their results, reviews, task definitions, and derived coordinator snapshot are in `../_workflow/`. The original literature task proposals remain unapproved.

| Evidence | Value |
| --- | --- |
| Run | `df58611a` |
| Input commit | `7b89d78c92b34a9424a347d366fb2eb696435bf5` |
| Alice publication | `cf95142ca465251311e7256b788cabbf491fdd7a` |
| Bob publication | `b6b378ff170d68a681cd92255b222102ef390520` |
| Tasks | `lit-finding-df58611a`, `lit-review-df58611a` |
| GitHub transport live | true |
| Commercial model inference live | false |
| Stale-edit response | 409 |

The first retrieval after this run exposed a historical relative link in Bob's generated result that resolved differently from its `pilot/` copy. An [additive Reference](../_workflow/result/result-lit-review-df58611a/alice-finding-df58611a.md) repairs navigation while preserving the accepted v1 bytes. Future pilot reports use committed GitHub permalinks (plain versioned paths for local remotes), and the pilot now checks the entire published bundle for unresolved links.

Authentication, provider refusal/failure, remote race, and interrupted/repeated submissions also have automated checks; simulated failures are distinguished from this live transport run in the [test report](https://github.com/midatm1234/ResearchRelay/blob/SRTD_DT_test/docs/shared-workflow-verification.md). Review rationales and scope approval here are scripted test inputs. No human coordination-time, comprehension, scientific validation, or productivity gain was measured.

[^alice-publication]: [Alice's publishing commit](https://github.com/midatm1234/ResearchRelay/commit/cf95142ca465251311e7256b788cabbf491fdd7a).
[^bob-publication]: [Bob's publishing commit](https://github.com/midatm1234/ResearchRelay/commit/b6b378ff170d68a681cd92255b222102ef390520).
