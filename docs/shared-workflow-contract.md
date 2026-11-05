# Shared-project implementation contract

One FastAPI process/database coordinates one project. SQLite owns execution state; committed GitHub Markdown preserves project knowledge. Distinct project tokens identify trusted participants and their non-secret connection profiles. This is not per-user GitHub OAuth.

## Repository and context API

- `GET /api/project`: project identity, participant, repository binding, format status, and sync status including latest retrieved commit, check time, sanitized error, and next action.
- `PUT /api/project/repository`: coordinator-only binding `{url,branch,knowledge_path}`. Live mode uses GitHub SSH/HTTPS; demo mode also permits temporary local Git remotes.
- `POST /api/project/sync`: explicit retrieval.
- `GET /api/project/context`: current project fields plus documents `{path,content,sha256,metadata,body,commit}`, tasks, and artifacts. Context retrieval and task claim retrieve latest committed context. Unconfigured sync remains valid for the local literature demo.
- `POST /api/project/publish`: `{expected_repository:{url,branch,knowledge_path},base_commit,changes:[{path,content,expected_sha256}],agent,request_id,message}`. Null expected hash means the target path was absent. The authenticated participant is authoritative attribution. The expected tuple comes from the context the author read, not later service settings. Exact accepted repeats return their original publication even after a binding change; new requests with a changed target or stale edits return HTTP 409 with a next action, while unrelated contributions are preserved. Publication uses a normal push and respects branch policy.

The dashboard polls workflow state every four seconds; Git retrieval is bounded by the configured sync interval (default 15 seconds). A saved commit is last-known context until retrieval succeeds. Browser drafts survive publication failures; adopting a newer base requires explicit comparison and acknowledgement.

## Agent connections

`GET/PUT /api/participants/me/agent` uses `provider` (`vscode`, `claude-cli`, `openai-responses`, `openai-compatible`, `command`, or `manual`), optional `model`, `base_url`, `api_key_env`, command argument array, and Claude `allowed_tools` where appropriate. API providers require a configured model. The server stores metadata, never credential values, and does not execute participant commands.

Workers fetch current context before work and pin context commit/document hashes in result provenance. Task submission still enters `awaiting_review`; reviewed completion unlocks dependencies. VS Code is a local editor file handoff, not an API to invoke extension chat: the participant starts Agent chat, the agent writes the validated report and readiness marker, and the worker submits. See [connections](agents.md) and [editor handoff](vscode.md).

## Portable knowledge

The selected canonical reference is Google Open Knowledge Format 0.2, pinned in [format status](open-knowledge-format.md). Selection is a documented assumption; the ResearchRelay workflow profile is provisional, not a full conformance certification. Markdown retains core metadata, generated attribution, citations, provenance, and relationships. Knowledge includes source notes, index, search log, synthesis, questions, proposed tasks, decisions, reviews, and results. Imports preserve evidence; only explicit scope approval creates executable tasks.

The source search is dated 2026-11-04. The explicit offline literature demo reads that verified note snapshot, labels publication/access limits, and performs no new search or live inference. The separate shared-Git pilot uses two command connections and reports live transport separately from model calls.

OpenAPI at the running service's `/docs` is the detailed HTTP contract. Keep the project within 1,000 documents, 1,000,000 bytes per document, and 50,000,000 bytes total. A publication is limited to 30 documents and 2,000,000 content bytes. Store large outputs externally with versioned references.
