# Set up GitHub sign-in locally

GitHub browser sign-in connects the Projects page to a participant's GitHub identity. Sign in to see registered projects and discover shared `PROJECT.md` records from accessible GitHub repositories. A signed-out browser shows an empty project list.

## 1. Register an OAuth App

Open [GitHub's OAuth App registration page](https://github.com/settings/applications/new). For a ResearchRelay service running on port 8000, enter:

| Field | Value |
| --- | --- |
| Application name | `ResearchRelay Local` |
| Homepage URL | `http://127.0.0.1:8000` |
| Authorization callback URL / Redirect URL | `http://127.0.0.1:8000/api/hub/auth/callback` |

The redirect URL is the callback address GitHub uses to return the browser to ResearchRelay after authorization. Keep the host and port consistent: use `127.0.0.1` in the registration, server configuration, and browser address.

Register the application, copy its client ID, and generate a client secret. ResearchRelay's browser integration uses an **OAuth App**. See [GitHub's registration instructions](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app).

## 2. Configure the service

Create or edit `.env` in the ResearchRelay checkout. Replace the two credential placeholders locally:

```dotenv
RESEARCHRELAY_PUBLIC_URL=http://127.0.0.1:8000
RESEARCHRELAY_GITHUB_CLIENT_ID=YOUR_OAUTH_APP_CLIENT_ID
RESEARCHRELAY_GITHUB_CLIENT_SECRET=YOUR_OAUTH_APP_CLIENT_SECRET
RESEARCHRELAY_HUB_PATH=.runtime/literature/project-hub
```

Keep `.env` private and Git-ignored. Enter credentials directly into that file or a server secret manager.

Preserve the existing `RESEARCHRELAY_HUB_PATH`: it selects the project catalog, memberships, encrypted authorizations, and project stores. The application's default literature workspace uses `.runtime/literature/project-hub`; `.env.example` suggests `.runtime/project-hub` for an explicitly configured hub. Use the directory that already holds your projects. Changing directories can make an existing project appear to be missing.

## 3. Restart and verify configuration

Stop the existing service with Ctrl+C in its terminal. Start it again from the checkout:

```bash
mamba run -n researchrelay researchrelay serve --host 127.0.0.1 --port 8000 --reload
```

OAuth settings in `.env` need a full service restart. Automatic Python reload and browser refresh handle application code and frontend changes.

Check the configuration:

```bash
curl --silent --show-error http://127.0.0.1:8000/api/hub/status
```

The response should contain `"configured": true`. Before browser sign-in, `"identity": null` and `"projects": []` are expected. This check confirms that OAuth settings are loaded; complete the browser authorization to verify the credentials with GitHub.

## 4. Sign in and find your project

Open [Projects](http://127.0.0.1:8000/projects), select **Connect GitHub**, and authorize ResearchRelay using an account with access to the project repository. After GitHub redirects back, the Projects page retrieves registered projects and searches the default branches of accessible repositories for ResearchRelay `PROJECT.md` files. It follows repository pagination and registers discovered projects locally without writing to GitHub. **Refresh list** repeats this search. Scan failures are displayed beside the list; already retrieved projects remain available.

For a project on a different branch, choose **New Project → Existing branch**, select its repository and branch, uncheck **Initialize a new project record**, and enter the existing folder containing `PROJECT.md`.

Each computer's `127.0.0.1` addresses its own local service. Separate local services can discover and exchange committed project records through GitHub. Their live task queues and execution databases remain independent; use one coordinator service when sharing task claims and execution state.

Browser access uses GitHub sign-in. Workers and CLI commands reuse the participant’s own `gh auth login` authorization; set `RESEARCHRELAY_SERVER` to the managed project URL. SSH access for the worker’s clone is configured separately. Each collaborator signs in with their own GitHub account and joins the existing project folder after receiving repository access.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| GitHub sign-in is not configured | Fill both credential fields, save `.env`, and fully restart the service. |
| Callback or redirect URL mismatch | Match `RESEARCHRELAY_PUBLIC_URL` and the registered callback exactly, including scheme, host, port, and `/api/hub/auth/callback`. |
| Sign-in fails or its state expires | Start again through **Connect GitHub** in the same browser. |
| Project list remains empty | Select **Refresh list**, check discovery errors and GitHub repository access, and explicitly join projects on other branches. Preserve the existing `RESEARCHRELAY_HUB_PATH` for local execution state. |
| Repository access is rejected | Check GitHub repository permissions and any organization OAuth/SSO restrictions. |

See [GitHub authentication and repository permissions](github-auth.md) for requested scopes, credential storage, session behavior, worker authentication, and HTTPS deployment requirements.
