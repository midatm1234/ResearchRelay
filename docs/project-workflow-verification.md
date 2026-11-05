# Project workspace verification

Implementation branch: `feature/github-projects`. Verification date: 2026-11-05.

## Exercised locally on Windows / Python 3.12

- Full automated run before the final focused hardening: 258 passed, 1 skipped in 659.16 seconds. The skip requires Windows symlink privileges.
- Final project/API/authentication/initialization/catalog integration run: 98 passed. Additional final security checks cover legacy API protection under OAuth, request-local Git credentials, exact/fine-grained token guards, Git access errors, and IPv6 loopback origin formatting.
- OAuth and GitHub REST transport: 48 mocked protocol/security tests using real SQLite/Fernet storage. No live OAuth consent or GitHub resource creation is inferred from these results.
- Initializer: 19 targeted tests cover all three modes, permission/auth failures, file/branch collisions, concurrent updates, and lost repository/branch/commit acknowledgements.
- Catalog: 10 event-driven tests cover same-request concurrency, restart replay, project/store isolation, external identity collisions, privacy, and remote-success/local-registration recovery. Slow setup does not block another project or its cached coordinator.
- `python scripts/project_smoke.py`: passed using a real disposable HTTP service, real CLI, SQLite and local Git. Alice creates a project, Bob joins the same coordinator, supplied verified AutoGen evidence is published, two independently configured command workers run dependency-based tasks, other participants review their outputs, completion/result artifacts are published, Bob's follow-up is retrieved, and a stale same-file edit receives HTTP 409. Agents are scripted; no fresh search or model inference is claimed.
- `python scripts/ui_projects_smoke.py`: passed 14 checks against mocked API responses, including unchanged-payload retry, durable resume, inaccessible repositories and missing OAuth configuration.
- `python scripts/ui_projects_smoke.py --demo`: passed 10 checks against real HTTP/local Git. Exercises three creation modes, private visibility default, settings edits committed to Git, synchronization/activity, second participant joining, scoped dashboard and catch-up state, no legacy bearer forwarding, and 390px layout. Zero JavaScript errors.
- Existing shared-workspace mocked browser regression: 15 checks passed.
- Dependency consistency (`python -m pip check`) and wheel build passed; hub Python modules and static assets were checked in the wheel.
- Original synchronization regressions were rerun. An invented-commit validation regression caught during hardening was corrected and its targeted test passed.

No GitHub OAuth client ID or client secret is configured in this development environment. Browser OAuth consent, actual private/public repository creation, branch provisioning through a real user's GitHub API authorization, organization SSO policy, and deployed reverse-proxy/TLS behavior remain live verification items.

## Reproduce

From the installed source checkout:

```bash
python -m pytest -q
python -m pip check
python -m pip wheel --no-deps --wheel-dir .runtime/dist .
python scripts/project_smoke.py
python -m playwright install chromium
python scripts/ui_projects_smoke.py
python scripts/ui_projects_smoke.py --demo
```

The standalone scripts own temporary state and stop only the service they start. `researchrelay serve --project-demo` is the persistent, loopback-only working-session variant; visit `/projects`. Simulated accounts and Git repositories are clearly labeled and kept under `.runtime/project-demo/`.

## Native platform CI

`.github/workflows/macos.yml` runs the full suite/build and original literature/editor/browser workflows plus new project CLI/browser scripts on native macOS 15 Apple Silicon and Intel. `.github/workflows/portable.yml` runs the full suite/build and new project scripts on Ubuntu 24.04 and Windows 2025. Exact pushed-commit results are reported after execution; defining CI is not itself evidence of a passing native run.

## Scope and remaining limits

Use one coordinator process with durable local SQLite storage. Each managed project has an isolated workflow store; joins to the same repository/branch/folder share it. GitHub is the shared committed knowledge record, while SQLite remains authoritative for claims and execution. Normal branch protections are respected; no force push or automatic conflict resolution is used. Worker code contributions retain their existing branch/PR integration.

Research files use ResearchRelay's existing explicitly provisional profile of the selected Open Knowledge Format specification. Initialization adds seven Markdown concepts and an index under a project folder, without asserting scientific approval or inventing findings. Collaborator fields record names; repository access is granted in GitHub.

GitHub OAuth scope is broader than a GitHub App installation. Server operators must configure the OAuth app, HTTPS/reverse-proxy behavior and private credential-store filesystem permissions. Workers use their own GitHub PAT and separate local Git/provider credentials. No consumer chat subscription is assumed to include API access. A live two-user working session is needed to evaluate usability, permissions and coordination effort.
