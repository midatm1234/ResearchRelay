# Participant-owned agent connections

Each participant uses a project-scoped ResearchRelay token and their own execution environment. The service stores only the participant's provider selection, model identifier, endpoint, credential **environment variable name**, and optional executable argument array. Provider credential values stay on the worker machine. Commands and model calls never execute on the coordination server.

A consumer ChatGPT or Claude chat subscription is not evidence of API access. Confirm the provider's account entitlements separately. OpenAI Responses requires a usable API credential and access to the chosen model; any account-specific credits do not create a key automatically. The Claude CLI uses that participant's own supported CLI authentication. No provider keys are necessary for VS Code editor handoffs, manual adapters or a local compatible server that permits unauthenticated loopback requests.

## Authenticate the participant

The coordinator configures `RESEARCHRELAY_TOKENS` in its private `.env` as a mapping of random tokens to participant identities. For example, Alice and Bob receive different tokens; neither token belongs in repository files, command arguments, chat prompts, or agent profiles. The token determines whose profile is read or written and whose tasks can be claimed. Run commands from a trusted project checkout and keep this terminal's environment private.

macOS/Linux:

```bash
export RESEARCHRELAY_TOKEN='ALICE_PROJECT_TOKEN'
```

Windows PowerShell:

```powershell
$env:RESEARCHRELAY_TOKEN = 'ALICE_PROJECT_TOKEN'
```

A participant worker's `--participant alice` must match their configured token identity. A separate local demo coordinator can use `--mode manual` without tokens; shared multi-user use should configure distinct tokens.

## Configure your connection

All commands below accept `--server http://127.0.0.1:8000` (the default). Connection profiles belong to the authenticated user. `researchrelay agent show` retrieves your current profile.

### Claude CLI

Install and authenticate [Claude Code](https://code.claude.com/docs/en/headless) in your own environment, and confirm `claude --version` works in the terminal that starts the worker.

```bash
researchrelay agent configure --provider claude-cli
researchrelay worker --participant alice --repo "$HOME/Projects/team-worker" --once
```

The worker invokes `claude -p` with JSON output, a bounded turn count, an execution timeout, and an explicit tool allowlist. Default tools allow file work. Scientific computation requires your own approved tool permissions; `--allowed-tools` can override the profile. `--model` can pin your permitted Claude model. The legacy `--mode claude` spelling is retained.

### GPT through the OpenAI Responses API

Set the API key in the participant terminal and configure an explicit model identifier that your account can use and that supports Structured Outputs:

```bash
export OPENAI_API_KEY='YOUR_PROVIDER_KEY'
researchrelay agent configure --provider openai-responses --model YOUR_MODEL_ID --api-key-env OPENAI_API_KEY
researchrelay worker --participant alice --repo "$HOME/Projects/team-worker" --once
```

On PowerShell the key assignment is `$env:OPENAI_API_KEY = 'YOUR_PROVIDER_KEY'`; the other commands are unchanged. `YOUR_MODEL_ID` is a placeholder, not a model selected or silently upgraded by ResearchRelay. The adapter uses the documented [Responses structured output interface](https://developers.openai.com/api/docs/guides/structured-outputs), disables provider response storage with `store=false`, and validates the returned report locally. Account or provider retention policies still apply.

### OpenAI-compatible or local models

An explicitly configured compatible endpoint must implement `/chat/completions` and JSON-object response mode. A local example is:

```bash
researchrelay agent configure --provider openai-compatible --model YOUR_LOCAL_MODEL --base-url http://127.0.0.1:11434/v1
researchrelay worker --participant bob --repo "$HOME/Projects/team-worker-bob" --once
```

Use Bob's token in Bob's terminal. A remote endpoint requires HTTPS; credentials, when needed, are read from the `--api-key-env` variable on that worker. Loopback HTTP can be used for a local server. Compatibility is an implemented protocol adapter, not a claim that every third-party model or server has been tested. Unsupported JSON modes, missing models, invalid JSON, quota errors, and provider refusal are visible execution blockers.

### Other executable agents

Use a local adapter command for a different model or tool suite. Create a private JSON file containing its executable and arguments, for example `["python", "/absolute/path/to/my_agent_adapter.py"]`, then configure:

```bash
researchrelay agent configure --provider command --command-file agent-command.json
researchrelay worker --participant alice --repo "$HOME/Projects/team-worker" --once
```

The process receives the task, exact input artifacts, and synchronized project context as one JSON object on stdin. It must emit only a JSON report on stdout with these fields:

```json
{
  "body": "# Finding\n\nA concise evidence-led report.",
  "findings": ["A finding supported by the supplied evidence"],
  "citations": ["https://example.org/a-supplied-source"],
  "assumptions": [],
  "limitations": ["No independent experiment was run"],
  "validation_results": [],
  "unresolved_questions": [],
  "next_actions": ["Independent review"]
}
```

The command is an argument array, not a shell string. ResearchRelay strips coordination-token settings from its environment. Provider-specific credentials may remain because the participant's own tool needs them. Do not put secrets in the argument array; use environment variables or the provider's normal credential manager. An agent command can run its own authorized tools, but a report by itself does not establish that any computation was performed.

### VS Code with Copilot or another extension

Choose `researchrelay agent configure --provider vscode`, then run `researchrelay worker --participant alice --repo /path/to/alice-clone --provider vscode --once --timeout 3600`. Add `--open-editor` only when you want ResearchRelay to open the generated `.code-workspace`. Use your own extension sign-in and attach its printed instructions/context files to Agent chat. The extension writes a simple JSON report and marks it ready; the worker wraps, validates, and submits the result for review. No extension-specific API key or chat-session access is required by ResearchRelay. See [the complete VS Code setup, fresh task, first prompt, and recovery walkthrough](vscode.md).

### Manual handoffs and external chat agents

```bash
researchrelay worker --participant alice --repo "$HOME/Projects/team-worker" --mode manual --once --timeout 1800
```

The worker prints its isolated workspace and private `.researchrelay-exchange/` directory, keeps its lease alive, and waits for `result.md`. An external agent reads the context there and writes validated Markdown/YAML according to `researchrelay/schemas/result.v1.schema.json`. This supports a participant's preferred agent without assuming access to a consumer chat application's private sessions or an API included in its subscription. The worker validates and submits the file after it appears. A manual report remains subject to peer review.

## Complete task and shared-artifact workflow

1. Retrieve fresh context before proposing work: `researchrelay project context --output alice-context.json`. The server fetches the selected repository branch, validates its committed Markdown, and returns document hashes plus the latest retrieved commit.
2. A coordinator approves executable task scope in the UI/API. Participants poll their assigned ready tasks with `researchrelay worker --participant alice --repo /path/to/alice-clone --once`.
3. Before work starts, the worker synchronizes again. Its own clone must have an origin matching the configured shared project, and its own Git credentials must permit reading that branch. An empty dedicated worker directory is cloned automatically; a nonempty unrelated directory is preserved and rejected. A fetched exact commit is the base for an isolated task worktree; the worker does not switch an existing user's checked-out branch.
4. The agent consumes the task's exact artifact versions and committed knowledge documents. Its context commit and document SHA256 values enter result provenance. API report providers perform grounded text synthesis; they have no code-execution tools. Claude/command/manual/editor agents may use their separately authorized local tools. Scientific outputs and task-specific records are committed in the participant's local task branch.
5. Submission enters `awaiting_review`. A second participant reviews the particular result version through the dashboard or `Worker.review(...)`/the review API. Computational completion, agent review, and human judgment remain separate.
6. Prepare the result or follow-up finding as Markdown under the configured project knowledge directory. The worker's `task-records/TASK/vN.md` already carries selected OKF core fields and the provisional ResearchRelay metadata. Get a publication context, inspect the evidence and intended file, and publish explicitly:

```bash
researchrelay project context --output publication-context.json
researchrelay project publish --context publication-context.json --file /path/to/task-records/TASK/v1.md --path projects/agentic-collaboration/results/TASK-v1.md --agent PRODUCING_AGENT --request-id alice-TASK-v1 --message "Record reviewed task finding"
```

`PRODUCING_AGENT` must match the artifact's `producing_agent`; omitting `--agent` uses that metadata value. The authenticated participant must match its responsible user. The CLI derives a stable request ID from the exact context and draft when none is supplied. Publish the independent review as its own related concept; publication does not invent a human or agent approval. No worker publishes automatically merely because an inference completed.

Bob retrieves the next committed state with `researchrelay project context --output bob-context.json`, reads Alice's finding, and writes a review or extension with his own attribution and a relationship to that finding. Bob's subsequent `project publish` uses his exact base commit and expected file SHA. A stale touched file is rejected with an actionable conflict. Unrelated new contributions are preserved. A normal Git push enforces branch permissions/policies; ResearchRelay does not force-push around them.

## Recovery and limits

- A stopped worker's lease expires; another attempt may claim the task within its retry budget. `.researchrelay-exchange/submission.json` contains a sensitive expiring claim token and stays locally Git-excluded for non-editor adapters. The VS Code adapter instead keeps both resumable claim state and submission payload below the participant clone’s `.git/researchrelay-worker/`, outside the editor worktree. Retry its exact payload with `worker --resubmit PATH --task TASK` after an ambiguous network response; do not generate a new completion to recover a successful submission.
- Before committing declared task outputs, the worker checks rendered results, context, and output files for recognizable key/private-key patterns and configured local credential values. Unexpected staged files are blocked rather than silently included. Private submission files are excluded from this scan and from Git. This is a focused guard, not a complete detector for arbitrary secrets; repository secret controls and participant review remain necessary.
- Provider errors share a sanitized diagnosis and create a blocker; raw provider response bodies and command output are not copied into the shared project. Correct missing credentials/model access locally, then have a coordinator authorize a bounded retry. In-flight API requests are bounded by the worker timeout; a lost lease prevents their output from being submitted.
- Agent profiles are application identities, not automatic GitHub OAuth permission delegation. Own Git access and the project's configured publication identity must be provisioned deliberately. Never share an SSH key, provider key, or a coordinator token to make a test pass.
- The portable Markdown publishing profile is provisional on an explicitly selected OKF specification. See [format status](open-knowledge-format.md). A provider's schema-valid output is not evidence that its citations, calculations, or scientific interpretation are correct; independent review is still required.

Credential-free tests exercise mocked OpenAI/compatible HTTP contracts, real local command execution, provider errors, and the task/artifact protocol. Live provider inference requires that participant's configured credentials/model access and must be reported separately from these tests. The literature search itself uses verified primary sources, not a provider-generated bibliography presented as verified evidence.
