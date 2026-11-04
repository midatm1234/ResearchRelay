# Shared project operation

ResearchRelay runs one project per service/database. Multiple participants use individual project tokens; they can choose different agents and environments. Committed Markdown is the shared knowledge record. SQLite owns execution state, claims, attempts, results, and reviews. Source code/large datasets stay in their appropriate repositories/storage, with immutable references in the records.

## Set up a shared working branch

Use an existing repository and branch that participants may read and publish to. This pilot uses `git@github.com:midatm1234/ResearchRelay.git`, branch `SRTD_DT_test`, and knowledge directory `projects/agentic-collaboration`. Set `RESEARCHRELAY_PROJECT=agentic-collaboration` and use an independent database so the literature project does not reuse forecast-pilot state. The full configuration example is in the README.

The coordinator can set repository metadata using **Configure repository** or `researchrelay project configure --server URL --url REPOSITORY --branch SRTD_DT_test --knowledge-path projects/agentic-collaboration`. The configured branch must exist. In live mode the binding targets GitHub SSH/HTTPS; demo mode additionally permits local bare repositories for reproducible tests.

The service host authenticates Git through its configured SSH/credential helper. Each participant authenticates to this project with their own token. These are separate permissions: participant tokens authorize trusted project writers through the service principal; they are not GitHub OAuth or provider API credentials. For direct participant Git publication, each local worker uses the participant's own Git credentials. Repository rules remain in effect; a protected-branch rejection needs an approved PR/review path, not a forced update.

## Retrieve and continue another participant's work

1. Enter your project token using **Access**, or export `RESEARCHRELAY_TOKEN` in the worker terminal.
2. Open or refresh the project. The dashboard retrieves recent committed information and reports status, branch, commit, and last check. It polls local workflow state every four seconds and checks Git on the configured interval (default 15 seconds).
3. **Retrieve updates** or `researchrelay project sync --server URL` forces retrieval. `researchrelay project context --server URL --output context.json` saves exact context for an agent.
4. Read the literature index, relevant source notes, synthesis, and open tasks. Each knowledge row names its responsible participant and producing agent. Workers retrieve current context again before claiming an assigned task and consume pinned versions.
5. Configure your own profile with **My agent** or `researchrelay agent configure`; start a participant-owned worker. A profile selection alone does not run an agent. See `docs/agents.md` for the connection types and required credentials.
6. Submit the task result for independent review, or publish a separate source note/review/extension. The record identifies the actual producer, input commit, citations, and provenance.

A knowledge artifact is not automatically a human-approved task. Scientific choices and task scope remain explicit coordination operations. An AI computational result, another agent's review, and a human scientific decision are separate records.

## Publish a literature finding

Use a new path for an independent finding or a review of someone else's result. Preserve source citations and relationships. New browser drafts default to `manual` attribution; enter an AI agent name only if it actually produced that contribution.

```bash
researchrelay project context --server http://127.0.0.1:8000 --output context.json
researchrelay project publish --server http://127.0.0.1:8000 --context context.json --file finding.md --path projects/agentic-collaboration/alice-finding.md --agent alice-agent --request-id alice-finding-001 --message 'Record verified coordination evidence'
```

Bob retrieves a **new** context, reads that committed finding, and publishes `projects/agentic-collaboration/bob-review.md` with a relationship to Alice's artifact and his own attribution. API/CLI credentials stay in each participant's environment. Real provider model calls require supported API/CLI access; a chat subscription is not assumed to include it.

## Concurrent changes

A publication names its observed `base_commit` and each changed file's `expected_sha256` (null means that path did not exist). The server checks the latest branch first and preserves unrelated changes. A changed target file or non-fast-forward race yields an actionable conflict; the service never force-pushes or silently overwrites a teammate.

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
