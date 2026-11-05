# Participant workers and Git integration

The coordinator stores approved task scope, claims, pinned inputs, events, and reviews. Each participant starts a worker in their own environment and Git clone. Worktrees isolate concurrent task attempts; they do not provide an operating-system sandbox. Large data and model outputs stay in external storage with immutable versions and hashes in result provenance.

## Choose your connection

See [agent connections](agents.md) for Claude CLI, GPT/OpenAI Responses, compatible API endpoints, command adapters, and manual Markdown handoff. See [VS Code/Copilot handoff](vscode.md) for using a participant's signed-in editor extension without a separate provider API key.

In macOS/Linux, with a project token and your own writable clone:

```bash
export RESEARCHRELAY_TOKEN='your-alice-project-token'
researchrelay agent configure --server http://127.0.0.1:8000 --provider vscode
researchrelay worker --server http://127.0.0.1:8000 --participant alice --repo "$HOME/Projects/alice-project-clone" --provider vscode --once --timeout 3600 --open-editor
```

On PowerShell, set `$env:RESEARCHRELAY_TOKEN = 'your-alice-project-token'` and pass your Windows clone path. A coordinator must approve ready work assigned to that participant. The worker retrieves committed project knowledge before claiming a task, reads pinned input versions, and keeps its claim alive while the selected connection works.

For `vscode`, the worker prints an isolated `.code-workspace`, instructions, and private restart state. Open the workspace, start your extension's Agent chat yourself, and have it write `.researchrelay-exchange/report.json`, then `.researchrelay-exchange/REPORT_READY`. The worker validates the structured report, records provenance, and submits it for independent review. Extension authentication stays in VS Code; ResearchRelay does not remotely invoke a consumer chat session.

For Claude CLI, authenticate the installed CLI in the worker's environment and select `--provider claude-cli`. Its default allowlist supports file work. Authorize additional execution tools explicitly using `--allowed-tools` and your local Claude permission rules. The managed CLI has bounded turns/time and is stopped after claim loss or cancellation. API adapters generate grounded structured reports without local code-execution tools; a provider-produced report does not prove that code was executed. Consumer chat access does not establish API access.

## Private exchanges and recovery

Runtime context, schema, result exchange, and saved submissions are kept in ignored private exchange/state files. Their exact location and restart instructions depend on the connection; the editor handoff prints its private `resume_handoff` path. Never commit those files. Tokens and provider credentials stay outside portable records and editor workspace files.

For a byte-identical network retry of an already prepared submission:

```bash
researchrelay worker --participant alice --repo "$HOME/Projects/alice-project-clone" --resubmit /path/printed/by/worker/submission.json --task TASK_ID
```

The saved submission contains an expiring claim token. Retry only while that claim remains valid. Do not put its contents in a shared artifact or a command argument. An expired claim fences the old attempt; a coordinator must authorize recovery within the task's attempt/revision bounds. For an interrupted editor handoff, use the exact `--resume-handoff` command printed by the worker before lease expiry; see [editor recovery](vscode.md).

The worker commits approved task outputs and portable result records under task-specific paths such as `task-records/<task-id>/vN.md`. It rejects tracked exchange/configuration credentials and staged unrelated files rather than including them in a task commit. Independent branches preserve pre-existing root project files.

## Provider-independent API

The running service's `/docs` and `/openapi.json` document the API. A custom worker can:

1. Retrieve `GET /api/project/context` and `GET /api/tasks?owner=alice&ready=true`.
2. Claim a ready task, download every exact `input_refs` version, and heartbeat its lease.
3. Submit `{claim_token,idempotency_key,artifact:{metadata,body},completion_notes}`. Use the same key and identical payload after an uncertain network outcome.
4. Report a blocker through `/api/tasks/{id}/block`, optionally including a question, options, evidence, and downstream consequence.
5. Have another participant review the exact result version through `/api/tasks/{id}/reviews`.

Submission enters `awaiting_review`. Reviewed completion unlocks downstream tasks. Human scientific decisions and changes to approved scope remain explicit participant operations.

## Shared project record and review policy

SQLite is authoritative for execution state. `researchrelay export` writes immutable versioned Markdown, `record-manifest.json`, and a derived `dashboard.json` tagged with its event sequence. Snapshots never become an alternative scheduler. Git import validates new evidence in one transaction; task definitions, reviews, and decisions imported as artifacts do not silently change execution state.

The browser's **Export to Git** commits to the configured local project-record repository. Shared knowledge publication through `/api/project/publish` uses the observed base commit and hashes, preserves unrelated contributions, checks stale edits, and normally pushes to the configured shared branch. Generated `_workflow/` records derive from SQLite. See [shared-project operations](shared-projects.md).

For repositories requiring pull requests, publish a worker branch through the existing draft-PR CLI:

```bash
researchrelay publish --repo "$HOME/Projects/alice-project-clone" --github TEAM/PROJECT --branch tasks/human-ai-evidence/attempt-1 --base main --title 'Review human-agent collaboration evidence' --body-file proposal.md
```

The configured origin must match `TEAM/PROJECT`. This path needs the participant's Git permissions and authenticated `gh`; it opens/reuses a draft PR and never merges. Branch protections remain in force. Coordinator fetch accepts only fast-forwards, imports validated evidence, and reports reconciliation issues. No path force-pushes over another participant's contributions.

## Local literature workflow and evaluation

`researchrelay demo` runs the deterministic literature-note pilot with real SQLite and Git. Alice and Bob process separate source groups concurrently; their reviewed inputs feed a synthesis. Carol requests explicit publication/access limitations, Alice revises, and a human receives the next-search question. The 12-source seed, meeting notes, and example records are in [the project bundle](../projects/agentic-collaboration), [meeting notes](../examples/meeting-notes.txt), and [literature records](../examples/literature-record). This run performs no fresh search or live model inference.

Rerunning the demo against the same database/repository resumes supported stages and avoids duplicate submissions/reviews/decisions. A still-running claim must expire before a new attempt; the default lease is 120 seconds. Blocked or canceled work requires explicit participant action.

Task elapsed time and scripted review/rework counts are recorded. Human coordination minutes, clarification requests, and the 1–5 handoff-comprehension assessment require a real participant. Compare them with an agreed baseline before claiming a productivity gain. The separate `researchrelay literature-pilot` exercises two participant command connections and shared Git handoffs; its summary states whether GitHub transport or model inference actually ran.
