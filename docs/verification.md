# Literature-first workflow verification

This report covers the default literature demo and VS Code editor handoff. Earlier shared-Git and native macOS results are preserved in [the archived shared-workflow report](shared-workflow-verification.md), with exact commit/run references. Those earlier passes do not verify later changes.

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
| Default demo/API smoke | Real startup and HTTP assets; Alice/Bob concurrent source-note processing; reviewed dependencies; synthesis v1 → justified revision → v2; local Git records; exactly 12 source notes and correct publication classifications; a human next-search decision; idempotent replay. |
| Default browser smoke | The real demo, source coverage/status/access table, result history, Markdown download, decision resolution, participant assessment, editable meeting proposals, scope approval, justified review, task search, changed-input reconciliation, and mobile layout. QA ratings/time are synthetic inputs. |
| Shared browser/local Git | Real FastAPI plus a temporary bare Git remote, second-clone concurrent edit, retained stale draft, explicit reconciliation, normal publication, second-participant retrieval, and mobile layout. Mocked mode separately tests browser failure/interaction contracts. |
| Shared literature pilot | Two authenticated participant command connections, current context/pinned inputs, finding publication, peer review/extension, dependency handoff, normal local Git publication, and stale edit HTTP 409. Its summary distinguishes GitHub transport and model inference. |
| Editor/provider tests | File/report validation, handoff isolation and restart/fencing, credential handling, provider errors, and supported HTTP/subprocess contracts. Automated editor reports do not establish that an actual Copilot chat session generated them. |
| Native macOS CI | The macOS workflow runs native arm64 and Intel tests/build/API/browser checks. Only a named successful run for the final implementation establishes those platforms were exercised. Interactive Miniforge installation and Safari remain separate. |

The deterministic demo inventories the verified 2026-11-04 source notes and executes reproducible local scripts. It performs no fresh literature search or live model inference. Publication status, access limits, and review outcomes remain distinct from human scientific verification. The example records are in [examples/literature-record](../examples/literature-record).

## Results for this change

Available Windows/AMD64 checks passed for these changes:

- Real isolated API smoke: startup/assets/schemas, parallel literature tasks, reviewed synthesis v2 with one revision, publication/access evidence, local Git record, human next-search decision, and idempotent replay.
- Real managed-Chromium default browser smoke: **12 workflow checks passed**, zero JavaScript errors, including the 12-source table and 390px layout. Desktop/mobile screenshots were retained and visually inspected; the script now waits for refreshed task state before opening a newly submitted review.
- Shared browser with mocked backend: **9 checks passed**, zero JavaScript errors, including the VS Code handoff guide and clearing API-only metadata when switching to editor handoff.
- Shared browser with real FastAPI/local bare Git: **8 checks passed**, zero JavaScript errors, including concurrent clone changes, stale draft retention, reconciliation, normal publication, second-participant retrieval, and hiding the local demo button for a bound project.
- `node --check researchrelay/static/app.js` passed.

The available local host is Windows. The full suite passed **159 tests, 1 skipped** in **397.54 seconds**. The skipped symlink escape check requires symlink privileges unavailable to this account. After collection, one final CLI persisted-binding guard was added and passed in a four-test focused run. The current inventory is **161 tests**. The wheel build, dependency consistency, Python compilation, and whitespace checks passed. Native macOS results for this implementation are pending CI; earlier runs are not evidence for this commit. Actual VS Code extension sign-in/Agent chat and paid model inference require participant access and must be reported separately from automated file-handoff tests.

- Actual editor CLI/HTTP smoke passed: `python -m researchrelay` starts the coordinator and participant worker; approved scope and pinned source context create an isolated editor workspace; a scripted JSON report is validated and submitted; Bob reviews it; Alice explicitly publishes; Bob retrieves it; a stale edit returns HTTP 409. Claim/submission capabilities stay below the participant clone's private `.git` directory. No GUI, GitHub write, or extension inference is claimed.
- A real module-service check returned HTTP 200 for health and dashboard. VS Code 1.145.0 is installed on the Windows host; generated workspace/tasks and F5 configuration were validated. An actual interactive F5/debugger session and signed-in Copilot/other extension Agent chat were not automated. Copilot is not installed in this environment; use your own extension entitlement/sign-in.
- The example's twelve source files and every declared source/code SHA256 match the executed archive. Its linked knowledge context has 37 Markdown documents with zero unresolved links.
- Existing project state is preserved: new defaults use `.runtime/literature/`; the demo refuses unrelated tasks/dirty record repositories and configured shared bindings. Background exports do not acknowledge a human's unread updates.
- The fresh-search [meeting template](../examples/literature-search-meeting.md) parses into three proposed tasks with two dependencies and no recorded decisions. It requires actual web tools for fresh searching, source-verification/access notes, and an explicit blocker when tools or evidence are unavailable.

The shared command-agent literature pilot also passed after the editor changes: 37 input context documents, 46 published documents, zero unresolved links, both tasks completed, and stale publication HTTP 409. This used a local bare remote; it made no GitHub write or model call.
