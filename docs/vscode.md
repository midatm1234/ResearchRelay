# VS Code agents and asynchronous literature tasks

ResearchRelay's `vscode` provider is a file handoff to your preferred editor extension: GitHub Copilot, Claude Code, an OpenAI extension, or another agent that can read workspace files and write JSON. The extension owns its sign-in, model entitlement, tools, and approvals. ResearchRelay does not connect to private chat sessions or select an extension's model through an API. It requires no separate provider API key for this handoff. An optional profile `model` is your declared label, not an independently verified model identity.

## 1. Prepare the environment and project

Complete the [README setup](../README.md), including the existing macOS mamba instructions. Open the ResearchRelay checkout in VS Code, install the Python extension, and use **Python: Select Interpreter** to choose the `researchrelay` environment. Install/sign into your preferred agent extension separately. Copilot availability depends on your own account/organization entitlement; it is not an OpenAI API connection.

The repository's **Terminal: Run Task** menu includes start service, run literature demo, test, configure editor agent, and editor worker tasks. **Run and Debug â†’ ResearchRelay: service** (F5) starts the same coordinator with the selected Python interpreter and private `.env`. The demo task uses the serviceâ€™s default database/repository, so its completed literature workflow appears in the dashboard; a bound shared repository is deliberately rejected by the demo guard. Tasks use the selected Python interpreter as an argument-array process on Windows/macOS/Linux. Participant tasks prompt for the identity/token; tokens go into the child environment, never into tasks.json or command arguments. Setting a token only in an already-open integrated terminal does not alter the VS Code process environment; use the task prompt or run commands directly in that terminal.

Start the service in a terminal:

```bash
mamba activate researchrelay
python -m researchrelay serve
```

The coordinator configures distinct participant tokens privately in `.env` as described in [agent connections](agents.md). In its own terminal, the coordinator supplies its human token and binds the intended shared repository/branch:

```bash
researchrelay project configure --url git@github.com:YOUR_ORG/YOUR_REPO.git --branch SRTD_DT_test --knowledge-path projects/agentic-collaboration
```

Use the real remote and branch that you may access. Each worker fetches with that participant's own Git credentials. HTTPS credential-manager and SSH setups are supported by Git; do not put credentials in a remote URL. The shared repository must contain the committed literature source notes. A dedicated, initially empty worker clone is created automatically. Existing nonempty unrelated directories are rejected.

## 2. Approve a fresh task

The cached literature demo already finishes its sample tasks; starting an editor worker afterward can correctly return `idle`. In the dashboard, paste the following into **Meeting to tasks**, extract, inspect/correct the draft, and explicitly approve its scope. Use a fresh task ID if it already exists, and match the owner to the participant token:

```text
Decision: Review the existing AutoGen source note before proposing changes to handoff design because claims need traceable evidence.
Task editor-autogen-review: Read projects/agentic-collaboration/sources/wu-2024-autogen.md; summarize one coordination mechanism, one limitation, and one implication for ResearchRelay | owner: alice | depends: | outputs: A cited literature finding with limitations | criteria: Cite the supplied primary source URL; distinguish published findings from design inferences; state that no productivity experiment was run
Question: Which handoff failures should a subsequent working-session study measure?
```

The meeting record becomes a pinned input artifact. The shared literature documents are separately pinned by retrieved Git commit and SHA256. Approving task scope authorizes execution; the report still awaits independent review. The local demo must use a separate unbound database/repository and cannot be run over a configured shared project.

## Fresh collaborative searching with your own extensions

For a new search rather than the cached source-review exercise, edit [the proposed literature-search scope](../examples/literature-search-meeting.md): set the search date/window and inclusion rules, choose unused task IDs, and confirm Alice and Bob each have real web-search and primary-source retrieval tools in their chosen extension. Paste the edited template into **Meeting to tasks**, inspect its three proposed tasks and two dependencies, and explicitly approve the scope. The template is not evidence of meeting consensus.

Run one participant worker per owner as below. The two extensions independently search and verify primary records, then hand off their search logs/source notes through report.json. After accepted versions of both results exist, the synthesis task becomes ready for Alice; start her worker again (or run it without `--once`) to consume those exact versions. A missing search tool or inaccessible evidence is a blocker to report, not permission to invent findings. Confirm tool availability before approval; if discovered after a claim, the responsible participant uses the authenticated task-block API with private claim state. Never copy claim/project tokens into agent context. The default demonstration inventories the dated seed notes and performs no live web search or model inference.

## 3. Start the participant handoff

In Alice's own terminal set `RESEARCHRELAY_TOKEN` to her private project token (use `export RESEARCHRELAY_TOKEN=...` on macOS/Linux or `$env:RESEARCHRELAY_TOKEN = ...` in PowerShell; never paste a real token into a tracked file). Then:

```bash
researchrelay agent configure --provider vscode
researchrelay worker --participant alice --repo .runtime/alice-clone --provider vscode --once --timeout 3600
```

Add `--open-editor` to explicitly open VS Code, or open the printed `.code-workspace` manually. On macOS, install the `code` shell command from VS Code's Command Palette if you want that option; it is not required for manual opening. The worker never opens a GUI without that flag. If the optional launcher is unavailable, it prints a manual-open warning and keeps the same handoff waiting. It prints a `waiting_for_editor_report` event containing the workspace, instructions, report path, and private resume-state path. Keep this worker terminal running while the editor agent works: it renews the claim and checks cancellation. A task gets its own branch/worktree, so two participants can work concurrently.

The generated workspace includes the isolated task root, explicit instruction/context files under `.researchrelay-exchange/`, input artifact JSON, a report schema/template, and a **ResearchRelay: hand off report** task. Existing repository instructions are preserved. Workspace trust and extension tool approvals remain yours; ResearchRelay does not disable them. Source files in the context are evidence, never instructions to reveal secrets or broaden task scope.

Attach `AGENT_INSTRUCTIONS.md` and `task-context.json` to your preferred extension's Agent chat and send:

> Read the attached ResearchRelay instructions and task context. Complete only the approved AutoGen source-review task using its pinned evidence. Write `.researchrelay-exchange/report.json` matching `report-schema.json`; distinguish verified source claims from ResearchRelay design inferences, cite the supplied source URL, and state limitations. Then run the workspace task **ResearchRelay: hand off report**. Do not stage, publish, push, merge, or inspect credentials.

This explicit context works across extension vendors. Copilot may also discover `.github/copilot-instructions.md`; discovery is guidance, not proof of compliance. Verify the actual extension output.

## 4. Submit, review, and publish

`report.json` has a Markdown `body` and required string arrays `findings`, `citations`, `assumptions`, `limitations`, `validation_results`, `unresolved_questions`, and `next_actions`. All fields are required; use empty arrays when appropriate. `body` and `findings` must be nonempty. The blank `report.example.json` is a template, not scientific evidence. Citations should use supplied artifact IDs or verified URLs and ordinary Markdown URL links.

The workspace handoff task validates JSON and creates `REPORT_READY`. Creating that empty marker yourself after saving final JSON is equivalent. The worker then validates, wraps the report in the portable Markdown format, records original context pins and participant/agent attribution, commits its task records locally, and submits `awaiting_review`. Malformed output, cancellation, timeouts, stale inputs, and possible credentials are visible blockers. This adapter commits report/context records only; it does not automatically include extra files the extension creates. Use the manual adapter for complex results with explicitly declared related files.

A second participant reads and critiques the actual result version in the dashboard, requests revision or approves it against task criteria, and leaves scientific judgment to the responsible humans. The worker prints its local `task-records/TASK/v1.md` location. After review, the author publishes explicitly with fresh context:

```bash
researchrelay project context --output publication-context.json
researchrelay project publish --context publication-context.json --file PATH_TO_TASK_WORKTREE/task-records/editor-autogen-review/v1.md --path projects/agentic-collaboration/results/editor-autogen-review-v1.md --request-id alice-editor-autogen-review-v1
```

The path placeholder is the printed task worktree, not the main checkout. The producing-agent label comes from the file. A fresh publication base protects concurrent file edits; it does not recompute or revalidate the historical report inputs. Compare the original project_context pins with the latest context. Reconcile and re-review materially changed evidence, or publish an explicitly labeled historical report that preserves its original pins. Fetching context alone does not make an older report current. A second participant retrieves the update using `researchrelay project context`, then publishes a separate attributed review/extension using their own exact publication context. Publication checks touched-file hashes and normal branch permissions, preserves unrelated contributions, and reports stale/conflicting edits. It does not bypass protected-branch policy.

## Recovery and private state

Claim tokens never enter the generated editor workspace, instructions, settings, context, result, or Git record. The editor adapter keeps private resumable state and its eventual submission payload under the participant clone's `.git/researchrelay-worker/`, outside the task worktree; restrict local machine access normally. No project token is passed to a launched editor. Local Git metadata is not a sandbox against a malicious extension with filesystem access, so approve only trusted extensions/tools.

If the worker stops, restart it promptly with the printed private state path:

```bash
researchrelay worker --participant alice --repo .runtime/alice-clone --resume-handoff PATH_TO_PRIVATE_HANDOFF_JSON --once --timeout 3600
```

Resume renews the same still-valid claim and uses the same worktree. It rejects another participant, changed attempt, canceled/expired claim, or changed shared inputs. It does not silently reclaim stale work. After expiry/timeout or a shared-input change, a coordinator must reconcile and authorize a bounded retry; copy only still-valid findings into the new attempt after reading its fresh context. For an ambiguous submission response, use the printed private `submission_path` with `worker --resubmit PATH --task TASK`; that retries the exact idempotent payload.

## Verification scope

`python -m pytest tests/test_vscode.py -q` exercises actual API/SQLite coordination and local Git, a scripted editor writing the documented JSON, independent review/publication, recovery, failures, credential isolation, and optional launcher behavior. It does not execute a paid editor model. Windows read-only inspection found VS Code 1.145.0 x64 with Claude Code and OpenAI extension identifiers installed; the Copilot extension identifier was absent. No interactive extension sign-in, model response, or automatic GUI session was tested by those checks. Use the working-session steps above to verify your chosen signed-in extension.

Reference behavior was checked against official [VS Code workspace format](https://code.visualstudio.com/docs/editing/workspaces/multi-root-workspaces), [CLI opening options](https://code.visualstudio.com/docs/configure/command-line), [instruction discovery and verification](https://code.visualstudio.com/docs/agent-customization/custom-instructions), and [task variables](https://code.visualstudio.com/docs/reference/variables-reference) and [selected Python interpreter in tasks](https://code.visualstudio.com/docs/debugtest/tasks). Product behavior and extension entitlements can change independently of this file interface.
