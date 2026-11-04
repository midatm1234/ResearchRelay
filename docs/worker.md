# Participant workers and Git integration

The coordinator stores task scope, claims, input versions, events, and reviews. It never runs a participant's arbitrary code. Each scientist starts a worker in their own environment and project clone. Worktrees isolate concurrent task attempts; they are **not an operating-system sandbox**. Supply a container or separate account for stronger execution isolation. Keep large datasets in external storage and record immutable URLs, versions, and hashes in result provenance.

## Initial Claude adapter

Install and authenticate Claude Code yourself. The adapter invokes the documented [`claude -p` interface](https://code.claude.com/docs/en/headless) with JSON output, a turn limit, a timeout, and an explicit tool allowlist. Default tools support file work; allow your own bounded computation command if required:

```powershell
$env:RESEARCHRELAY_TOKEN = '<alice project token from your local configuration>'
researchrelay worker --participant alice --repo D:\research\project-clone --once --allowed-tools 'Read,Write,Edit,Glob,Grep,Bash(python *)'
```

Use a participant's ordinary Claude configuration/credentials. `RESEARCHRELAY_TOKEN` is stripped from the Claude subprocess environment. The adapter does not use permission bypass flags. A heartbeat runs during execution; claim loss or cancellation terminates the CLI. Missing tools, failed authentication, timeout, and invalid outputs become visible blockers rather than fabricated completions. Claude writes `.researchrelay-exchange/result.md` using the provided schema, task context, and pinned inputs. A completed result still requires independent review.

All `RESEARCHRELAY_*` settings are stripped from the Claude subprocess environment. `submission.json` and an idempotency ID remain **untracked** in the task worktree for exact network retry:

```powershell
researchrelay worker --participant alice --repo D:\research\project-clone --resubmit D:\research\project-clone-workspaces\task-id\attempt-1\.researchrelay-exchange\submission.json --task task-id
```

Treat this file as sensitive: it contains the expiring claim token. It is never included in the explicit Git add list. The worker also adds `.researchrelay-exchange/`, `submission.json`, `submission-id.txt`, and `.env` patterns to the repository's local `info/exclude`, shared by its worktrees, to protect ordinary later `git add -A` use. A token is not sent in command-line arguments. Use environment configuration, local credential management, and a project-scoped GitHub token with only contents and pull-request permissions for that repository.

Runtime context, schema, result exchange, and saved submissions stay in that ignored private exchange directory. The worker commits scientific outputs and copies portable records to `task-records/<task-id>/vN.md` and per-attempt context files in that same task-specific directory. Independent branches therefore do not alter a shared root `result.md` or `task-context.json`; existing project files with those names are preserved.

## Provider-independent protocol

`/docs` and `/openapi.json` document the HTTP API. A custom worker can poll `GET /api/tasks?owner=alice&ready=true`, claim a ready task, download each exact `input_refs` version, heartbeat, and submit `{claim_token,idempotency_key,artifact:{metadata,body},completion_notes}`. Agents request review by submitting a result; another participant posts `/api/tasks/{id}/reviews`. `/block` accepts a reason and optional question, options, evidence, and downstream consequence. Humans resolve decision requests through the dashboard/API. Use the same idempotency key and identical payload after a network error.

## Shared project record

SQLite is authoritative. `researchrelay export` writes immutable `artifacts/<type>/<id>/vN.md`, a `record-manifest.json` hash manifest, and `dashboard.json` with its originating event sequence. Dashboard snapshots are generated views and are never imported as task state. Export detects changes to previously exported artifact versions; it does not overwrite them. Commit new versions to propose Git edits, run `researchrelay import`, then reconcile task scope through the API. Changed inputs are detected by the coordinator when dependent tasks claim or submit. Imported task artifacts do not silently reassign or execute work.

For shared workflow-record exports, create a separate clean branch, export there, and publish that branch for review:

```powershell
git -C D:\research\project-clone switch -c records/session-1
researchrelay export --repo D:\research\project-clone
researchrelay publish --repo D:\research\project-clone --github TEAM/PROJECT --branch records/session-1 --base main --title 'Working-session project record' --body-file .\record-description.txt
```

The web export button commits locally to its configured project record repository. It returns the commit for review/publication; it does not push or merge a live GitHub branch. The only automated local merges occur inside the explicitly credential-free pilot. Git imports run in one database transaction: conflicting or missing references roll back the entire artifact batch.

Live publication is an explicit command, separate from coordinator export:

```powershell
git -C D:\research\project-clone remote add origin https://github.com/TEAM/PROJECT.git
gh auth login
researchrelay publish --repo D:\research\project-clone --github TEAM/PROJECT --branch tasks/task-id/attempt-1 --base main --title 'Evaluate experiment A' --body-file .\pr-description.txt
```

The configured origin must match the explicit owner/repository. The command pushes only the named branch and opens or reuses a **draft** pull request. It never merges; repository review rules and branch protections remain in effect. After a reviewed PR merges, `researchrelay fetch --repo D:\research\project-clone --branch main` accepts only a fast-forward, imports new versions, and reports reconciliation issues. Preserve both branches if edits conflict. Local pilot merges are explicitly labeled simulated PRs and are not live GitHub reviews.

## Working-session measures

The demo records real local elapsed/task durations and a scripted review/rework count. Human coordination time and participant assessment remain unmeasured until a real session. Ask participants to record actual coordination minutes, clarification requests, blockers, and a 1–5 assessment: **Do you understand what others completed and what needs attention next?** Add a short explanation. Compare with an agreed baseline only after a real session; the demo establishes no productivity claim.

For another provider or an interactive agent, use `researchrelay worker --participant alice --repo D:\research\project-clone --mode manual --once --timeout 1800`. It prints the isolated workspace and private exchange path, keeps its claim alive, and waits for `.researchrelay-exchange/result.md` written by that agent. The protocol has no model-provider dependency.

Rerun `researchrelay demo` against the same database/repository to resume a stopped pilot. It reuses completed computations, pending result reviews, accepted revisions, and the existing human decision. If a process stopped with a task still running, its old claim must expire before retry; the default lease is 120 seconds. Blocked or canceled work requires an explicit participant action in the dashboard/API.

## What was exercised

Local deterministic workers, real Python forecast metrics and seeded bootstrap, concurrent execution, database transitions, review/revision, isolated Git worktrees, local simulated reviewed merges, and portable Git exports are covered by the pilot. The live Claude subprocess and GitHub draft-PR paths are implemented but require participant credentials and were not invoked by the credential-free pilot.
