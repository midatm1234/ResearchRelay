# GitHub authentication and repository permissions

The multi-project browser connects each person to GitHub through a server-side OAuth web flow. ResearchRelay stores an encrypted per-user GitHub authorization and sends the browser an opaque session identifier. It does not ask browser users to paste tokens, store OAuth tokens in localStorage, borrow a shared account, or treat an agent chat subscription as GitHub/API access. The original single-project token interface remains separate from managed project sessions.

## Configure browser sign-in

Register a GitHub OAuth app for the ResearchRelay service. Use the service's public URL as its homepage and exactly `PUBLIC_URL/api/hub/auth/callback` as its authorization callback. For loopback development, the default callback is `http://127.0.0.1:8000/api/hub/auth/callback`. Use a separate OAuth app registration for a deployed service when callback origins differ.

Set these server-only values in its private `.env` or secret manager, then start the normal service:

```dotenv
RESEARCHRELAY_PUBLIC_URL=https://researchrelay.example.org
RESEARCHRELAY_GITHUB_CLIENT_ID=YOUR_OAUTH_APP_CLIENT_ID
RESEARCHRELAY_GITHUB_CLIENT_SECRET=YOUR_SERVER_ONLY_OAUTH_APP_SECRET
RESEARCHRELAY_HUB_PATH=.runtime/project-hub
```

```bash
researchrelay serve
```

These are placeholders. Keep the actual client secret out of Git, project Markdown, prompts, frontend JavaScript, and screenshots. `RESEARCHRELAY_PUBLIC_URL` must match the browser-visible origin and OAuth registration. HTTPS is required away from loopback. Configure a reverse proxy to preserve the intended origin and redact callback query strings from its own access logs; the application strips OAuth callback code/state queries from its Uvicorn request scope. Proxy configuration and TLS termination must be checked separately for deployment.

Open `/projects` and choose **Connect GitHub**. Missing OAuth configuration is reported explicitly; ResearchRelay does not silently substitute the machine's GitHub CLI account or a connector token. The local project demonstration described below is a separate mode, not a successful live login.

## What the sign-in stores

Sign-in uses an unpredictable one-use OAuth state value, an independent browser nonce in an HTTPOnly pending cookie, and an S256 PKCE challenge. The server stores hashes of the state/browser nonce and an encrypted PKCE verifier for ten minutes. It consumes the state before exchanging the temporary code, so a callback cannot be replayed or transferred to another browser.

After the code exchange, GitHub's `/user` endpoint verifies the account's numeric ID and login. Membership is associated with the stable numeric ID. The server encrypts access tokens and any refresh tokens using Fernet authenticated encryption in `auth.db` below `RESEARCHRELAY_HUB_PATH`. The private `auth.key` in that directory is created atomically, kept outside Git, and must be backed up separately and protected by the server's filesystem permissions. Unix files are restricted with private modes; Windows deployments should verify account ACLs on that directory. Encryption protects a database copy without the key; a machine account that can read both can decrypt the credentials.

The session cookie contains a random opaque value. Only its SHA256 hash is stored in SQLite. Cookies are HTTPOnly, SameSite=Lax, and Secure when the configured public URL is HTTPS; insecure HTTP is allowed only for explicit loopback development. Sessions last eight hours by default. Mutations also pass the application's same-origin checks. Browser code receives public identity metadata, never the OAuth token or encryption key.

The server revalidates the GitHub identity when using a session. Expiring authorizations refresh with GitHub when a valid refresh token is available; rotated tokens remain encrypted and must identify the same numeric account. Revoked authorization invalidates local sessions when GitHub returns an authentication failure. Session expiry or an unrefreshable authorization requires sign-in again. Signing out removes that session; signing out the last local session removes its stored encrypted credentials. It does not revoke the OAuth app on GitHub. Use GitHub's authorized-app settings to revoke that grant.

Restore the original key if it is lost. If encrypted credentials exist, ResearchRelay refuses to generate a replacement key silently. Corrupt ciphertext or a wrong key produces an actionable failure with no plaintext fallback. A fresh authorization requires a deliberately reconciled server store; do not overwrite a live key to resolve an error. Key rotation, external key-management integration, and high-availability deployment remain future work; the MVP uses a single coordination process and local SQLite storage.

## Requested access and actual repository permissions

The OAuth app requests `repo`, `read:user`, and `read:org`. `repo` is broad: GitHub OAuth apps do not offer a per-repository fine-grained equivalent of GitHub App installations. The consent screen and organizational approval policy still apply. ResearchRelay checks the signed-in user's current repository metadata/permissions for each managed project. OAuth scope never grants more access than the GitHub account itself possesses. Organization OAuth restrictions, SSO authorization, repository roles, rate limits, and branch protections can prevent an operation and are shown as errors to resolve.

Read access permits opening and reading an authorized project. Write/admin capability is determined by GitHub's reported permissions and required by corresponding mutations. Joining an existing ResearchRelay record does not invite a user to its repository or escalate a role. A collaborator invitation, when exposed, is a separate explicit action requiring GitHub permission; no invitation is sent during a normal join. A personal or organization repository is created only from the confirmed wizard action, using the user's GitHub authorization and selected private/public visibility.

The HTTP client uses GitHub.com's fixed API origin, an explicit API version, no environment proxy routing, and no redirects that could forward credentials. It returns sanitized auth/permission/rate/conflict errors without copying raw GitHub response bodies. Repository creation, branch creation, file writes, and collaborator invitations remain distinct calls so their durable provisioning checkpoints can identify partial failure.

Repository initialization uses Git blobs, a tree based on the current existing tree, a commit with the retrieved parent, and a non-forced reference update. A changed touched file is rejected. Unrelated concurrent additions are preserved by rebuilding against the latest tree, with at most three update attempts. A lost reference-update acknowledgement is accepted only when the branch is observed at the exact commit just created. Normal GitHub branch rules still apply; protected branches are not force-updated or bypassed. Provisioning records operation markers and idempotency separately so a retry does not adopt an unrelated repository merely because its name matches.

## Agent workers and CLI access

A browser session is not exported to an agent. A managed worker can authenticate with its participant's own permitted GitHub personal access token in `RESEARCHRELAY_TOKEN`, sent as an HTTP Authorization Bearer header. The server verifies the token's GitHub identity without persisting the PAT. Fine-grained PATs need access to the selected repository, metadata read permission, and the contents permissions needed by the requested work; repository creation/organization operations may need additional GitHub entitlements. Classic PATs need the appropriate repository scope. GitHub remains the authority and insufficient permissions are reported.

Use the managed project URL as the worker server and the actual GitHub login as its participant identity:

```bash
researchrelay worker --server http://127.0.0.1:8000/projects/PROJECT_ID --participant YOUR_GITHUB_LOGIN --repo /path/to/your/project-clone --provider vscode --once
```

Set the PAT privately in the participant's terminal or credential tooling, never in that command, its Git remote URL, agent profile, prompt, or Markdown. On macOS/Linux set `RESEARCHRELAY_TOKEN` in the terminal; on PowerShell use `$env:RESEARCHRELAY_TOKEN`. For the worker's local clone/fetch, configure that participant's own Git credential manager or SSH authentication separately. The HTTP PAT is not automatically a Git credential. An existing SSH clone can be used; the worker verifies its origin matches the selected repository and fetches the exact project branch before making an isolated task worktree.

An agent's Claude/GPT/editor sign-in is still independent of GitHub authorization. The service coordinates tasks; the participant's own agent executes them. See [agent connections](agents.md) and [VS Code handoff](vscode.md).

## Explicit credential-free project demonstration

```bash
researchrelay serve --project-demo
```

This loopback-only mode uses simulated GitHub identities and real temporary/local Git records to exercise the project wizard and collaboration. It does not perform a GitHub OAuth exchange, create account repositories, invite collaborators, or prove live permissions. The older cached scientific workflow remains available through its separate `--offline-demo` / `demo --offline` commands. Keep all simulated and live verification claims distinct.

## Verification and references

`python -m pytest tests/test_github_auth.py tests/test_github_client.py -q` exercises mocked OAuth/REST responses with real SQLite/Fernet storage, state and nonce failures, PKCE, concurrent callback replay, session expiry/revocation, refresh/account binding, no plaintext token persistence, explicit resource calls, permission/rate errors, touched-file conflicts, non-forced racing updates, and lost acknowledgements. These are protocol/security checks, not live OAuth consent or live repository creation. No live account resource creation is authorized by these tests.

Implementation follows primary documentation for [GitHub OAuth web flow and PKCE](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps), [OAuth scope semantics](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps), [Git trees and preserving the base tree](https://docs.github.com/en/rest/git/trees), [non-forced reference updates](https://docs.github.com/en/rest/git/refs), and [Fernet encryption/key handling](https://cryptography.io/en/latest/fernet/). A GitHub App with finer repository grants is the most useful next authentication refinement after this OAuth MVP is evaluated.
