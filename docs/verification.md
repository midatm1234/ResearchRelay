# Literature-first workflow verification

This report preserves the literature-demo and VS Code editor-handoff baseline through implementation `e8d1511452a7b4be07aed7725e66fc2a3f360c60`. It predates the shared-GitHub-by-default change; those results do not verify the newer defaults. The reproducible checks below use explicit isolated/offline state. Earlier shared-Git and native macOS results are preserved in [the archived shared-workflow report](shared-workflow-verification.md), with exact commit/run references. Those earlier passes do not verify later changes.

## Reproduce current checks

From the source checkout with the `researchrelay` environment installed:

```bash
mamba run -n researchrelay python -m pytest -q
mamba run -n researchrelay python -m pip check
mamba run -n researchrelay python -m pip wheel --no-deps --wheel-dir .runtime/dist .
mamba run -n researchrelay python scripts/smoke.py
mamba run -n researchrelay python scripts/smoke.py --browser
mamba run -n researchrelay python scripts/ui_shared_smoke.py
mamba run -n researchrelay python scripts/ui_shared_smoke.py --local-git
mamba run -n researchrelay python scripts/editor_smoke.py
mamba run -n researchrelay researchrelay literature-pilot
```

Install `.[browser]` and `python -m playwright install chromium` for browser checks. These commands work without external provider/GitHub credentials and use isolated state. The service smoke explicitly disables inherited repository/token configuration. The optional direct browser script requires a fresh isolated service as documented in the README.

## Expected evidence and boundaries

| Check | What it verifies |
| --- | --- |
| Isolated offline demo/API smoke | Real startup and HTTP assets; Alice/Bob concurrent source-note processing; reviewed dependencies; synthesis v1 → justified revision → v2; local Git records; exactly 12 source notes and correct publication classifications; a human next-search decision; idempotent replay. |
| Isolated offline browser smoke | The real demo, source coverage/status/access table, result history, Markdown download, decision resolution, participant assessment, editable meeting proposals, scope approval, justified review, task search, changed-input reconciliation, and mobile layout. QA ratings/time are synthetic inputs. |
| Shared browser/local Git | Real FastAPI plus a temporary bare Git remote, second-clone concurrent edit, retained stale draft, explicit reconciliation, normal publication, second-participant retrieval, and mobile layout. Mocked mode separately tests browser failure/interaction contracts. |
| Shared literature pilot | Two authenticated participant command connections, current context/pinned inputs, finding publication, peer review/extension, dependency handoff, normal local Git publication, and stale edit HTTP 409. Its summary distinguishes GitHub transport and model inference. |
| Editor/provider tests | File/report validation, handoff isolation and restart/fencing, credential handling, provider errors, and supported HTTP/subprocess contracts. Automated editor reports do not establish that an actual Copilot chat session generated them. |
| Native macOS CI | The macOS workflow runs native arm64 and Intel tests/build/API/browser checks. Only a named successful run for the final implementation establishes those platforms were exercised. Interactive Miniforge installation and Safari remain separate. |

The deterministic demo inventories the verified 2026-11-04 source notes and executes reproducible local scripts. It performs no fresh literature search or live model inference. Publication status, access limits, and review outcomes remain distinct from human scientific verification. The example records are in [examples/literature-record](../examples/literature-record).

## Verified baseline before the default knowledge change

The following Windows/AMD64 checks passed for that baseline:

- Real isolated API smoke: startup/assets/schemas, parallel literature tasks, reviewed synthesis v2 with one revision, publication/access evidence, local Git record, human next-search decision, and idempotent replay.
- Real managed-Chromium default browser smoke: **12 workflow checks passed**, zero JavaScript errors, including the 12-source table and 390px layout. Desktop/mobile screenshots were retained and visually inspected; the script now waits for refreshed task state before opening a newly submitted review.
- Shared browser with mocked backend: **9 checks passed**, zero JavaScript errors, including the VS Code handoff guide and clearing API-only metadata when switching to editor handoff.
- Shared browser with real FastAPI/local bare Git: **8 checks passed**, zero JavaScript errors, including concurrent clone changes, stale draft retention, reconciliation, normal publication, second-participant retrieval, and hiding the local demo button for a bound project.
- `node --check researchrelay/static/app.js` passed.

The available local host is Windows. The full suite passed **159 tests, 1 skipped** in **397.54 seconds**. The skipped symlink escape check requires symlink privileges unavailable to this account. After collection, one final CLI persisted-binding guard was added and passed in a four-test focused run. That baseline collected **161 tests**. The wheel build, dependency consistency, Python compilation, and whitespace checks passed. Native macOS [run 41938882066](https://github.com/midatm1234/ResearchRelay/actions/runs/41938882066) passed for implementation `e8d1511452a7b4be07aed7725e66fc2a3f360c60`: **161 tests on each architecture**, macOS 15.8.2 arm64 (34.72 seconds) and macOS 15.7.9 x86_64 (72.10 seconds), Python 3.12. All dependency/build, default literature API, shared literature, real CLI/HTTP editor, and both browser workflow steps passed. Shared browser runs reported zero JavaScript errors. This verifies the service/worker and editor file protocol on native Macs, not an interactive VS Code/Copilot GUI session. Actual VS Code extension sign-in/Agent chat and paid model inference require participant access and must be reported separately from automated file-handoff tests.

- Actual editor CLI/HTTP smoke passed: `python -m researchrelay` starts the coordinator and participant worker; approved scope and pinned source context create an isolated editor workspace; a scripted JSON report is validated and submitted; Bob reviews it; Alice explicitly publishes; Bob retrieves it; a stale edit returns HTTP 409. Claim/submission capabilities stay below the participant clone's private `.git` directory. No GUI, GitHub write, or extension inference is claimed.
- A real module-service check returned HTTP 200 for health and dashboard. VS Code 1.145.0 is installed on the Windows host; generated workspace/tasks and F5 configuration were validated. An actual interactive F5/debugger session and signed-in Copilot/other extension Agent chat were not automated. Copilot is not installed in this environment; use your own extension entitlement/sign-in.
- The example's twelve source files and every declared source/code SHA256 match the executed archive. Its linked knowledge context has 37 Markdown documents with zero unresolved links.
- Existing project state is preserved: new defaults use `.runtime/literature/`; the demo refuses unrelated tasks/dirty record repositories and configured shared bindings. Background exports do not acknowledge a human's unread updates.
- The fresh-search [meeting template](../examples/literature-search-meeting.md) parses into three proposed tasks with two dependencies and no recorded decisions. It requires actual web tools for fresh searching, source-verification/access notes, and an explicit blocker when tools or evidence are unavailable.

The shared command-agent literature pilot also passed after the editor changes: 37 input context documents, 46 published documents, zero unresolved links, both tasks completed, and stale publication HTTP 409. This used a local bare remote; it made no GitHub write or model call.

The first native editor smoke exposed a test-only lexical path comparison between macOS `/var` and its `/private/var` target. The smoke now resolves temporary, workspace, and private-state paths before containment checks. It passed again on Windows and both native Mac architectures; the production worker already used resolved paths and kept its claim/submission files private.

## Shared knowledge default change

A new service now selects the ResearchRelay GitHub `SRTD_DT_test` knowledge branch; an existing saved project binding wins. The offline workflow is explicit: `researchrelay serve --offline-demo` and `researchrelay demo --offline` select separate local state. Merely opening the shared service retrieves context and does not push. Current-change checks and any matching native macOS run must be recorded separately from the baseline above.

## Default GitHub knowledge base

The current implementation makes `git@github.com:midatm1234/ResearchRelay.git`, branch `SRTD_DT_test`, the default shared source. The initial project uses `projects/agentic-collaboration`. A saved project binding takes precedence over defaults and environment fallbacks. Owners of personal projects and group coordinators can configure another GitHub repository/branch/directory; one active binding is authoritative for a project.

Verified locally for these changes:

- **Live read-only SSH/API retrieval:** the actual defaults retrieved commit `fdca5c482da36bb06d3762e65ff6da17115a8658`, 37 Markdown documents, and 12 source notes in a temporary coordinator. No tasks or GitHub publications were created.
- **Live read-only browser:** the same default source and commit appeared with SHARED PROJECT status, 12 Git-derived sources, a working source view, no offline pilot button, zero tasks/jobs, and zero JavaScript errors. The service/cache were temporary and cleaned up.
- **Custom sources:** 12 local/mocked tests cover default/blank/custom fallbacks, saved choices across restarts, coordinator-only changes and cache isolation, first publication into a committed empty bundle, unborn-branch guidance, and repository/branch/directory switches at identical commits. Old drafts/results are rejected, accepted acknowledgments retain their original target, and fresh contexts publish to the selected source.
- **Editor/CLI:** 42 focused checks passed with one expected Windows symlink skip. Reports pin the observed repository, publications carry `expected_repository`, automatic request IDs distinguish forks, and editor resume rejects a changed source even when commit/document hashes match. A missing binding in a saved publication context is rejected with retrieval guidance.
- **Browser/file protocol:** mocked browser 15 checks, real service/local-Git browser 8 checks, offline browser 12 checks, and actual CLI/HTTP editor report/review/publication/retrieval/stale409 all passed. Scripted output is not extension inference.
- **Offline mode:** `serve --offline-demo` and `demo --offline` share dedicated local state, clear inherited live project/token configuration in that process, require loopback access, and refuse an existing saved binding instead of erasing it. Their documented commands passed together despite inherited live settings.
- **Import/consistency:** API imports do not initialize a user's database. New task completion and its source validation are serialized against repository changes. Explicitly disabling an unsaved source hides inactive cached knowledge while preserving exact accepted publication acknowledgments.

The complete current Windows suite passed **189 tests, 1 skipped** in **514.97 seconds**. The skip is the existing Windows symlink-privilege limitation. The wheel build, pip dependency check, Python compilation, JavaScript syntax, and whitespace checks passed. Native macOS verification for this implementation is pending CI; earlier runs identify their own commits and are not verification of these defaults. Interactive editor inference/sign-in and institutional SSO remain outside these checks.
