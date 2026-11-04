# MVP verification — November 3, 2026

Verification ran on Windows with Git, the new `researchrelay` mamba environment, Python 3.12.16, and the package versions in `requirements.lock.txt`. Browser QA used installed Microsoft Edge with Playwright. Source is on `dev/agent-collaboration-mvp`; `main` preserves the initial empty-repository baseline.

## What was actually exercised

| Path | Evidence |
| --- | --- |
| Web service | The exact `mamba run -n researchrelay researchrelay serve --port 8000` command started successfully; health, dashboard, interface, and OpenAPI returned HTTP 200. |
| Full CLI pilot | `researchrelay demo --db .runtime/delivery.db --repo .runtime/delivery-record` completed with real calculations and local Git history. |
| Full browser pilot | Started the pilot from the dashboard against an isolated database/repository; observed completion and a human decision request. |
| Portable artifacts | Five JSON Schemas, all illustrative and actual pilot example records, and pinned example references validate. Markdown download and version history were exercised. |
| Participant worker protocol | Actual HTTP integration through the test application retrieved a task and pinned input, claimed it, wrote scientific output through the provider-independent adapter, submitted it, and recorded its branch/commit. |
| Claude adapter | Installed Claude Code version and documented CLI interface were checked; subprocess configuration and credential-environment handling have targeted verification. No live model execution was performed. |
| Local Git integration | Isolated branches/worktrees, scientific outputs, review/revision commits, portable record export/import, immutable-edit rejection, stale heads, and conflicting merges were exercised. |
| GitHub integration | Explicit destination verification and draft-PR/fetch paths are implemented. No remote was supplied; no repository push, PR creation, remote merge, or external credentials were exercised. |
| Hosting | Local runnable service only; no cloud deployment was performed. |

## Scientific smoke result

The independent initial samples contain 12 days for A and 11 for B. The reviewer requests comparable dates and uncertainty. The revised result uses 11 paired days:

| Measure | Result |
| --- | --- |
| Paired RMSE A | 1.2030264865 |
| Paired RMSE B | 0.9821127504 |
| B minus A | -0.2209137361 |
| Seeded paired-bootstrap 95% interval | [-0.9633047673, 0.4547741007] |
| Bootstrap draws / seed | 2,000 / 1729 |
| Synthesis review cycles / revisions | 2 / 1 |

The interval crosses zero. The dashboard asks whether to expand validation, investigate the high-error event, or revise metric weighting. It does not select an experiment automatically. The small synthetic sample and IID resampling limitation are in the result record. Actual examples are in `examples/pilot-record/`; commit IDs there identify the generated local record repository.

## Reliability and API verification

The automated suite checks lease expiry after restart, old-worker fencing, bounded attempts, simultaneous competing claims, concurrent duplicate submissions and payload conflicts, persistence across restart, review-gated DAG dependencies, input-version pinning, stale inputs before/during execution, explicit human reconciliation without changing upstream history, cancellation, bounded review loops, unresolved disagreements, cyclic-scope rollback, versioned decision resolution, background-job interruption, project token ownership, reviewer/actor identity, artifact responsibility, named secret-field rejection, example validation, and conflicting Git updates.

**Final result: 50 passed in 71.03 seconds.** Python compilation, JavaScript syntax, dependency consistency (`pip check`), and Git whitespace checks also passed.

Concurrent provider-independent Alice/Bob workers also submitted separate branches that merged cleanly, preserving pre-existing project files. A repeated delivery CLI run completed with exactly four submissions, four reviews, and one decision still present.

The pilot tests run the complete calculation/review/Git workflow, resume after an injected interruption before review, and repeat a completed pilot without duplicate submissions, reviews, decisions, or Git commits. The worker tests exercise HTTP exchange without external credentials. Run:

```powershell
mamba run -n researchrelay python -m pytest -q
```

The test client emits one upstream Starlette/httpx deprecation warning; it does not affect service or test behavior. Python compilation and JavaScript syntax checks pass.

## Browser verification

The real-browser smoke passed the pilot, synthesis v2/v1 inspection, Markdown download, scientific decision resolution, assessment/time entry, meeting extraction, inferred-field correction, explicit scope approval, result review/revision, task search, and a 390px mobile overflow check. It reported no JavaScript page errors. Screenshots were captured at `.runtime/dashboard.png` and `.runtime/dashboard-mobile.png` and visually inspected.

A separate browser regression passed four checks for stale-input recovery: inspect versions, require acknowledgement, explicitly adopt reviewed pins, and confirm the task is ready. The full script also includes this regression; `--reconciliation-only` runs it independently.

Browser QA intentionally writes synthetic participant ratings and coordination time into its isolated QA database. These are test inputs, not actual participant assessments or productivity evidence. Human coordination time and comprehension remain to be measured in a working session.

For reproduction, install `.[browser]`, launch a fresh isolated demo service as described in the README, and run `python scripts/ui_smoke.py`. The script accepts `--url` and `--browser`. Temporary test/QA services are stopped at handoff.

## Remaining practical limits

Use one coordinator process and one project database. Agent worktrees isolate Git changes but do not sandbox system access. The meeting extractor is conservative and rule-based. Imported Git artifacts are validated evidence; task-scope changes require explicit coordination actions. Live Claude/GitHub interoperability needs a participant-authenticated session with a designated remote repository. Productivity gains remain an evaluation question.

## ResearchRelay rename verification

After moving the project to `D:\ResearchRelay`, the renamed `researchrelay` mamba environment, Python package, CLI, configuration variables, schema branding, documentation, and browser interface were verified again. All **50 tests passed in 67.74 seconds**. The renamed CLI service started successfully, and real Edge checks passed at 1512, 1200, 1000, 768, 760, and 390 pixels without horizontal overflow or JavaScript errors. Dependency checks and JavaScript syntax checks passed. Sixteen existing local Git worktrees were repaired after the directory move; archived scientific data/code bytes and recorded hashes remain unchanged.

The application source repository uses the user-selected SSH remote `git@github.com:midatm1234/new.git`. Source publication is separate from the scientific worker pilot: live Claude execution and scientific GitHub PR orchestration remain unexercised.

## macOS compatibility work — November 4, 2026

The local execution host is Windows 11 / AMD64 with Python 3.12.16. These local results are not macOS runtime results:

- **53 automated tests passed in 73.43 seconds**, including home-relative configuration and constructor paths, repositories with spaces/non-ASCII names, UTF-8 Git output, and saved worker submissions under the home directory.
- `python -m pip wheel --no-deps --wheel-dir .runtime/dist .` produced the platform-independent application wheel; its static interface and JSON Schemas were verified in the archive. `pip check`, Python compilation, JavaScript syntax, and whitespace checks passed.
- `python scripts/smoke.py` passed real CLI startup, HTTP resources, parallel scoring, dependent synthesis, justified revision, Git recording, a human decision, and idempotent pilot replay. Its service runs from a temporary directory containing spaces and cleans itself up.
- `python scripts/smoke.py --browser` passed the complete UI workflow with Playwright-managed Chromium and no page errors. It includes meeting corrections, reviews, decision resolution, assessment, mobile layout, and stale-input reconciliation. This no longer depends on a Windows Edge path.
- Binary-only dependency downloads for CPython 3.12 succeeded for both `macosx_11_0_arm64` and `macosx_11_0_x86_64`. This checks wheel availability, not Mac installation or execution. The Windows-only Colorama pin now uses an environment marker.

The new [native macOS workflow](../.github/workflows/macos.yml) verifies Python architecture and runs installation, the complete test suite, dependency checks, a wheel build, API/pilot smoke, and browser smoke on `macos-15` (arm64) and `macos-15-intel` (x86_64). Consult the [Actions runs](https://github.com/midatm1234/ResearchRelay/actions/workflows/macos.yml) for the matching commit; configuration of that matrix alone does not establish that either native run passed.

The Miniforge installer itself is not exercised by this pip-based CI. Interactive native Miniforge installation, macOS 11–14, Safari automation, live Claude execution/credentials, and GitHub scientific PR orchestration remain outside these checks. No changes to archived scientific data/code bytes or their recorded hashes were made.
