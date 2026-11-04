# Shared GitHub collaboration verification — November 4, 2026

This report distinguishes local execution, mocked failures, remote Git transport, and model inference. The current implementation is on `SRTD_DT_test`. The full Windows suite and subsequent focused checks passed. The live GitHub SSH pilot also completed. Native macOS CI exposed a Unicode-path diagnostic issue; after the fix, both Apple Silicon and Intel jobs passed the complete suite and all workflow/build/browser checks.

## Verified local workflow

Execution used the Windows host and the existing `researchrelay` mamba environment with Python 3.12. Local Git checks used real repositories, commits, branches, isolated worktrees, and normal pushes to temporary bare remotes. They did not require GitHub or paid model credentials.

| Check | Result and boundary |
| --- | --- |
| Literature seed | All 25 seed Markdown files validated; zero broken internal links. The 12 verified source records contain 7 published papers, 2 preprints/technical reports, 2 specifications, and 1 official software manual. |
| Portable format | Selected Google OKF 0.2 reference is pinned to a commit. Adoption is an explicit assumption, and the ResearchRelay profile remains provisional. Schema/profile checks include exact source permalinks, source-keyed footnotes, reserved indexes/logs, and lossless metadata/resource round trips. |
| Knowledge checks | 29 tests passed, including bibliography/access classifications and all current bundle documents. Seed counts apply to `sources/` and `tasks/`; subsequently committed pilot artifacts are also validated without changing those seed counts. |
| Two-participant literature pilot | Completed with two participant-local command workers. Alice published a finding; Bob retrieved it, reviewed/extended the work, and published a subsequent artifact. Dependencies and review handoffs ran through the coordinator. An intentionally stale publication returned HTTP 409. |
| Synchronization regressions | All 25 synchronization cases passed in the combined suite. Coverage includes disjoint contributions, same-file conflicts, concurrent push retry, duplicate requests, durable drafts, restarted/repeated publication, forged input commits/hashes, case/Unicode path aliases, limits, and sanitized failures. |
| Real browser/service/Git | Eight checks passed against the real local service and a temporary bare Git remote, with zero JavaScript page errors: retrieval, profile metadata, concurrent clone update, retained stale draft, explicit reconciliation, normal publication, second-participant retrieval, and mobile layout. |
| Browser with mocked backend | Eight interaction/failure checks passed separately, including an unauthenticated local-compatible profile. These checks do not establish GitHub or provider connectivity. |
| Provider/worker paths | Targeted provider checks passed, including mocked Claude CLI/OpenAI HTTP responses and failures plus real local command execution. The final worker suite passed all 11 checks, including three new pre-commit credential/staging regressions; the provider/CLI/credential-focused run passed 31 checks. The literature pilot exercised complete task/context/artifact handoffs through command connections. No successful live provider inference was verified; a separate bounded Claude CLI attempt is described below. |
| Final combined suite/build | Windows: 139 passed in 405.81 seconds. The subsequently added three credential regressions passed in the final 11-test worker run (86.01 seconds), covering all 142 currently collected cases across these runs. Wheel build, pip check, compileall, JavaScript syntax, and whitespace checks passed. One upstream Starlette/httpx deprecation warning remains. |

The underlying source notes, [search record](../projects/agentic-collaboration/search-record.md), [synthesis](../projects/agentic-collaboration/synthesis.md), and [format boundaries](open-knowledge-format.md) record evidence and limitations. Most paper summaries use abstracts and bibliographic records. Vaccaro's publisher full-text HTML and parts of the Amershi camera-ready were inspected; AutoGen's author/abstract metadata came from indexed primary PDF content plus the COLM accepted-paper list, with direct OpenReview access challenged. No human scientific verification is implied.

## External integration and platform boundaries

| Path | Verification status |
| --- | --- |
| Live GitHub SSH publication | Completed: Alice `cf95142ca465251311e7256b788cabbf491fdd7a`, Bob `b6b378ff170d68a681cd92255b222102ef390520`. Both tasks completed; subsequent retrieval succeeded; stale edit returned HTTP 409. Two command agents used one SSH Git principal. See [pilot evidence](../projects/agentic-collaboration/pilot/verification-20261104.md). |
| Separate GitHub users | Not demonstrated by the local pilot. Application participant identities share the coordinator's configured Git principal; attributing Alice and Bob does not establish two distinct GitHub account authentications. |
| Claude/GPT live inference | No successful inference verified. Claude CLI reported a configured API-key helper, but one real worker invocation timed out at its 90-second limit: no valid CLI JSON/result, task blocked, review not started. No retry. OpenAI/compatible HTTP contracts used mocks; no live GPT/compatible request was verified. A consumer chat subscription does not establish API access. |
| Current implementation on macOS | [Run 41931908567](https://github.com/midatm1234/ResearchRelay/actions/runs/41931908567), implementation `82c6ea88e8c117a5680309aa41b8b43c020ea2b7`: **142 tests passed on each architecture**, arm64 macOS 15.8.2 (38.40 s) and x86_64 macOS 15.7.9 (81.19 s), native Python 3.12.10. Dependency checks, wheel builds, API startup/scientific smoke, literature handoffs, and both browser workflows passed on both. Shared-browser runs reported zero JavaScript errors. |
| Previous macOS baseline | Native macOS 15 Apple Silicon and Intel baseline checks were reported passing before these collaboration changes. Matching run/commit evidence must remain separate from current-branch verification; see [Actions](https://github.com/midatm1234/ResearchRelay/actions/workflows/macos.yml). |
| Native Miniforge installation / Safari | Not exercised by these local checks. A pip-based macOS CI run does not establish an interactive Miniforge installation or Safari automation. |

The [earlier verification report](verification.md) records the forecast pilot and prior compatibility work. Current live transport and macOS results should be added below with exact commit/run references when available.

## Reproduce

From an installed source checkout with the `researchrelay` environment active:

```sh
mamba run -n researchrelay python -m pytest -q
mamba run -n researchrelay researchrelay literature-pilot
mamba run -n researchrelay python scripts/ui_shared_smoke.py
mamba run -n researchrelay python scripts/ui_shared_smoke.py --local-git
```

Browser checks require `.[browser]` and Playwright Chromium as documented in the README. Each pilot creates isolated local state and reports artifact paths and commits in its summary. Its task authorization and review rationales are scripted test inputs, not measurements of research productivity or real participant understanding. This literature pilot does not collect an actual participant assessment.

The live transport pilot requires the invoking Git principal's SSH/write access and writes new, uniquely named artifacts on the selected remote branch:

```sh
mamba run -n researchrelay researchrelay literature-pilot --remote git@github.com:midatm1234/ResearchRelay.git --branch SRTD_DT_test --live
```

Inspect the emitted `github_transport_live`, `model_inference_live`, publication commit hashes, artifact paths, and stale-edit response. A successful GitHub transport run still uses local command agents unless a separate live provider run is explicitly configured.

## Final result fields

- Windows full suite: 139 passed in 405.81 seconds; final worker suite: 11 passed, including three added credential regressions. Current inventory: 142 tests. Wheel/dependency/syntax checks and isolated HTTP startup/scientific smoke passed.
- Implementation commit pushed: `7b89d78c92b34a9424a347d366fb2eb696435bf5`; subsequent pilot commits were retrieved by fast-forward.
- Live SSH pilot: Alice `cf95142ca465251311e7256b788cabbf491fdd7a`; Bob `b6b378ff170d68a681cd92255b222102ef390520`; stale HTTP 409; no paid model inference.
- Fixed implementation `82c6ea88e8c117a5680309aa41b8b43c020ea2b7`: native arm64 and x86_64 [CI run 41931908567](https://github.com/midatm1234/ResearchRelay/actions/runs/41931908567) passed all 142 tests and every build/smoke/browser step on each architecture.
- Live provider verification: one configured Claude CLI attempt timed out; no validated result or review. No successful live model inference verified. GPT/compatible provider tests remain mocked.

## Findings resolved during integration

The first native arm64 run had 141 passing tests and one diagnostic assertion failure. Native macOS Git can precompose Unicode path lookups. Publication now checks filename aliases before blob hashes so the conflict explains the actual collision. The first live pilot also exposed a relative link that broke when the same accepted body was projected into a workflow directory. An additive Reference preserves the original accepted record. Future pilot reports use pinned GitHub links (plain versioned paths locally); every pilot now validates links in the entire published bundle. Knowledge checks pass after the repair.

The final credential-free repeat run, `fc1ab56b`, consumed the accumulated 37-document project record and published a 46-document bundle with zero unresolved links. Both tasks completed and the stale edit returned 409. Pilot session tokens are independently randomized for every run; credential guards remain enabled. This repeat used a local bare remote, separate from the earlier live SSH run.

## Bounded live Claude connection attempt

Claude CLI sign-in status reported a configured API-key helper; this did not prove usable model access. A separate one-task probe used a local bare repository containing only the verified AutoGen note, its own temporary coordinator, and the existing Claude worker with Read/Write/Edit tools. The worker stopped the single invocation at its 90-second limit (100.19 seconds including setup), persisted a blocked task, and produced neither valid CLI JSON nor a validated result. Review was not started and nothing was pushed to GitHub. This checks an actual bounded failure path; it is not a passing Claude inference/integration claim. Participant-specific CLI/provider access still needs a working-session check. Private logs, credentials, and application tokens are excluded from the shared record.
