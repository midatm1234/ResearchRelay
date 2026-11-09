# Shared project operation

The Projects hub coordinates isolated projects backed by shared GitHub records. Each participant signs in with their own GitHub account and repository permissions. SQLite owns execution state; committed Markdown preserves shared knowledge.

## Default knowledge base and other projects

A new service defaults to `git@github.com:midatm1234/ResearchRelay.git`, branch `SRTD_DT_test`, knowledge directory `projects/agentic-collaboration`, with project ID `agentic-collaboration`. The code checkout can be on `main`; committed knowledge is retrieved from the configured branch. Opening the project retrieves context and does not publish changes. The full configuration example is in the README.

A binding already saved in the project database takes precedence over these startup defaults, including when the URL environment variable is blank. An explicit empty `RESEARCHRELAY_GITHUB_URL` disables the fallback only for a new unbound project. New defaults do not erase task state, cached records, or a group's chosen repository.

Create or join a personal or team project from **Projects**. Each managed project has one repository/branch/directory binding shared by its participants and an isolated execution database. Its dashboard and API live under `/projects/PROJECT_ID`.

The project coordinator can change that binding using **Configure repository** or:

```bash
researchrelay project configure --server http://127.0.0.1:8000 --url git@github.com:YOUR_ORG/YOUR_REPO.git --branch YOUR_BRANCH --knowledge-path projects/YOUR_PROJECT
```

The configuration command above applies to a local operator workspace without browser OAuth. Teams create or connect managed projects through **Projects**; managed bindings are fixed. Repository permissions and branch policies still apply.

For a local cached literature demonstration, use `researchrelay serve --offline-demo --port 8001` and `researchrelay demo --offline`. They use isolated local state, disable browser OAuth, require loopback, and reject a database with an existing shared binding.

Each team member signs in with GitHub and keeps their own agent/provider credentials. Workers and CLI commands reuse that participant’s GitHub CLI login. GitHub remains authoritative for repository permissions and branch policies.

## Retrieve and continue another participant's work

1. Sign in through **Projects → Connect GitHub** and open the managed project.
2. Open or refresh the project. The dashboard retrieves recent committed information and reports status, branch, commit, and last check. It polls local workflow state every four seconds and checks Git on the configured interval (default 15 seconds).
3. **Retrieve updates** or `researchrelay project sync --server URL` forces retrieval. `researchrelay project context --server URL --output context.json` saves exact context for an agent.
4. Read the literature index, relevant source notes, synthesis, and open tasks. Each knowledge row names its responsible participant and producing agent. Workers retrieve current context again before claiming an assigned task and consume pinned versions.
5. Configure your own profile with **My agent** or `researchrelay agent configure`; start a participant-owned worker. A profile selection alone does not run an agent. See [agent connections](agents.md) for the connection types and required credentials, or [VS Code/Copilot](vscode.md) to hand off to a signed-in editor extension without a provider API key.
6. Submit the task result for independent review, or publish a separate source note/review/extension. The record identifies the actual producer, input commit, citations, and provenance.

A knowledge artifact is not automatically a human-approved task. Scientific choices and task scope remain explicit coordination operations. An AI computational result, another agent's review, and a human scientific decision are separate records.

## Use your editor agent

After `gh auth login --hostname github.com`, set `RESEARCHRELAY_SERVER` to the full managed project URL. Select **My agent → VS Code / Copilot**, then run the worker in your own terminal:

```bash
researchrelay worker --server http://127.0.0.1:8000/projects/PROJECT_ID --participant alice --repo "$HOME/Projects/alice-project-clone" --provider vscode --once --timeout 3600 --open-editor
```

A coordinator must first approve a task assigned to Alice. The worker retrieves current context, claims the ready task, and prints an isolated editor workspace and instructions. Start your own extension's Agent chat there; it writes `report.json` and `REPORT_READY` under `.researchrelay-exchange/`. The worker validates and submits the result for review. This uses the participant's existing extension session rather than invoking a remote chat API. See [editor handoff](vscode.md) for exact report/restart requirements. On PowerShell, use your own Windows clone path in `--repo`.

## Publish a literature finding

Use a new path for an independent finding or a review of someone else's result. Preserve source citations and relationships. New browser drafts default to `manual` attribution; enter an AI agent name only if it actually produced that contribution.

```bash
researchrelay project context --server http://127.0.0.1:8000/projects/PROJECT_ID --output context.json
researchrelay project publish --server http://127.0.0.1:8000/projects/PROJECT_ID --context context.json --file finding.md --path projects/agentic-collaboration/alice-finding.md --agent alice-agent --request-id alice-finding-001 --message 'Record verified coordination evidence'
```

Bob retrieves a **new** context, reads that committed finding, and publishes `projects/agentic-collaboration/bob-review.md` with a relationship to Alice's artifact and his own attribution. API/CLI credentials stay in each participant's environment. Real provider model calls require supported API/CLI access; a chat subscription is not assumed to include it.

## Concurrent changes

A publication names its observed `expected_repository` tuple (`url`, `branch`, `knowledge_path`), `base_commit`, and each changed file's `expected_sha256` (null means that path did not exist). The server checks the latest branch first and preserves unrelated changes. A changed target file or non-fast-forward race yields an actionable conflict; the service never force-pushes or silently overwrites a teammate.

A changed repository binding is a conflict even if the new target contains the same commit and files. The browser clears old knowledge immediately, preserves and disables the draft, and requires a new contribution after reviewing the current source; it never silently redirects a report to another repository. Exact accepted network retries still identify their original publication.

The browser retains your textarea draft on failure. **Retrieve latest for comparison** shows committed text without replacing your draft. Reconcile the content, explicitly acknowledge the comparison, then select **Use this reviewed base for my draft** before retrying. CLI users retrieve a new context and reconcile their saved Markdown themselves. Keep the publication request ID stable for a byte-identical network retry; use a new ID for a materially revised/reconciled request.

Authentication and sync errors show next actions rather than pretending an update succeeded. Until retrieval succeeds, an earlier commit is only the last known state. No provider key belongs in a Markdown file, browser profile form, shared Git history, or error report.

## Format and source quality

The selected OKF 0.2 specification is a documented assumption because this repository did not previously identify one. The ResearchRelay profile is provisional. See `docs/open-knowledge-format.md` for canonical metadata, supported relationships, source-keyed citations, extension fields, and validation limits. The review's search log records queries, date, selection, and source access; source notes distinguish publication status and scientific claims from software documentation.

## Run the literature pilot

```bash
mamba run -n researchrelay researchrelay literature-pilot
# Optional: choose a new/empty workspace instead of the generated default.
mamba run -n researchrelay researchrelay literature-pilot --workspace .runtime/literature-session-1
```

The default run needs no external credentials. It creates an isolated local bare remote and coordination database, runs two participant-owned command agents, publishes Alice's finding, has Bob retrieve/review/extend it, and tests a stale publication conflict. Each run's `summary.json` records artifact paths, retrieved/published commits, task IDs, and which transport/model paths actually ran. The initial bundle's three task documents remain proposals. The pilot creates and approves its own isolated test tasks; no import silently turns a proposed literature task into executable scope.

For explicitly requested publication to the GitHub test branch:

```bash
mamba run -n researchrelay researchrelay literature-pilot --remote git@github.com:midatm1234/ResearchRelay.git --branch SRTD_DT_test --live
```

Live publication is permitted only on the authorized `SRTD_DT_test` branch and requires the invoking Git principal's permissions. It adds unique run-suffixed Markdown under `projects/agentic-collaboration/pilot/` and generated workflow records. Two application participants share that service Git principal; neither distinct GitHub account access nor paid model inference is implied. The agents are command adapters using verified source context. Use the summary's `github_transport_live` and `model_inference_live` flags and the verification report to determine what was actually exercised.

## Context and publication bounds

The selected project may contain at most 1,000 Markdown documents, each at most 1,000,000 UTF-8 bytes, with at most 50,000,000 bytes of total context. Each publication request accepts at most 30 documents and 2,000,000 UTF-8 content bytes. Oversized or invalid content produces an actionable validation error. Store large datasets/model outputs externally and retain immutable URLs/versions/checksums in the project record.

A direct push that conflicts with repository protection is rejected. Use your approved review process or the existing `researchrelay publish` task-branch/draft-PR path; ResearchRelay does not force-push or bypass branch policy.

## Verification boundaries

The repeatable two-participant pilot uses independent sessions with a local bare remote; it can test fetching, publication, stale/concurrent edits, and failure handling without credentials. A live SSH publication to the shared GitHub branch demonstrates actual remote transport separately. Provider API tests use explicit mock transports unless the verification report names a live call. Do not infer model execution from a saved provider profile or from a successful Git push. Consult the final test report for which live/model/macOS paths actually ran.
