# ResearchRelay

A working experiment for a small scientific team whose participant agents collaborate asynchronously. Scientists approve scope and make scientific decisions; workers perform routine work and exchange portable evidence. The application is **ResearchRelay**; the Python package and CLI are `researchrelay`.

## Start here

Use Python 3.12 and Git 2.28 or newer. The web interface has no Node.js build step; SQLite is included with Python. The local pilot needs neither Claude nor GitHub credentials. [macOS setup](#macos-setup-apple-silicon-and-intel) below covers both Mac architectures.

The source is in [midatm1234/ResearchRelay](https://github.com/midatm1234/ResearchRelay). In a new checkout:

```bash
git clone https://github.com/midatm1234/ResearchRelay.git
cd ResearchRelay
mamba env create -f environment.yml
mamba run -n researchrelay researchrelay serve --port 8000
```

Run service, demo, and test commands from the checkout directory. Open **http://127.0.0.1:8000**, then choose **Run local pilot**. The browser can close while the service and workers continue. Stop the service with Ctrl+C. Existing users can skip cloning and environment creation.

To evaluate these changes before they merge into `main`, run `git switch dev/agent-collaboration-mvp` after cloning and before installing the environment.

To run the same demonstration from another terminal against the dashboard's default database:

```bash
mamba run -n researchrelay researchrelay demo
```

Use the button or CLI once; both coordinate through the same SQLite database. To run an independent fresh experiment without deleting existing work:

```bash
mamba run -n researchrelay researchrelay demo --db .runtime/session-2.db --repo .runtime/session-2-record
```

To show that independent experiment in the dashboard, start a separate service. In macOS/Linux zsh or bash:

```bash
export RESEARCHRELAY_DB='.runtime/session-2.db'
export RESEARCHRELAY_REPO='.runtime/session-2-record'
mamba run -n researchrelay researchrelay serve --port 8001
```

In Windows PowerShell:

```powershell
$env:RESEARCHRELAY_DB = '.runtime/session-2.db'
$env:RESEARCHRELAY_REPO = '.runtime/session-2-record'
mamba run -n researchrelay researchrelay serve --port 8001
```

API documentation: **http://127.0.0.1:8000/docs**. Configuration: copy `.env.example` to `.env` and edit. Runtime state and credentials are Git-ignored.

## macOS setup (Apple Silicon and Intel)

### Prerequisites and architecture

- Install Git 2.28+ (`git --version`). Apple's Command Line Tools provide Git; run `xcode-select --install` if they are missing and finish the installer before continuing.
- Install [Miniforge3](https://github.com/conda-forge/miniforge#requirements-and-installers) for your native architecture: **arm64** on Apple Silicon, **x86_64** on Intel. Current Miniforge installers require macOS 11+. Open a new Terminal after the installer initializes your shell so `mamba --version` works. These are upstream installer requirements, not a claim that every macOS version has been tested with this application.
- Use a native Terminal on Apple Silicon, rather than a Terminal opened using Rosetta. `uname -m` should report `arm64` on Apple Silicon and `x86_64` on Intel. Keep Miniforge, Python, and their packages on the same architecture. No GPU, CUDA, Homebrew, Docker, or Rosetta is required for the pilot.
- Keep the checkout and runtime directories in a user-writable location, such as `~/Projects/ResearchRelay`. Do not use `sudo pip`, change system Python, or grant Full Disk Access just to start this service. Git worktrees need a local writable filesystem; avoid read-only or cloud-synchronized project-record directories.

Miniforge's base Python version can differ from the application environment. `environment.yml` creates a separate native **Python 3.12** environment on either Mac architecture. The pinned native dependencies have CPython 3.12 wheels for both architectures; using the pinned interpreter avoids unnecessary local C/Rust builds. An already installed environment can be inspected with:

```bash
uname -m
git --version
mamba --version
mamba run -n researchrelay python -c 'import platform; print(platform.python_version(), platform.machine())'
```

### Install and configure

After installing the prerequisites, use a normal zsh/bash Terminal:

```bash
mkdir -p "$HOME/Projects"
cd "$HOME/Projects"
git clone https://github.com/midatm1234/ResearchRelay.git
cd ResearchRelay
mamba env create -f environment.yml
cp .env.example .env
```

If you already cloned the repository, start with `cd` into that checkout instead. If the `researchrelay` environment already exists, use `mamba run -n researchrelay python -m pip install -r requirements.lock.txt -e ".[dev]"` to update its dependencies. Quote extras such as `".[dev]"` in zsh to prevent filename expansion.

Edit `.env` with your text editor. Its default `RESEARCHRELAY_MODE=demo`, empty token mapping, and `.runtime/` paths are enough for the local pilot. To keep state outside the checkout, paths in this file may use `~` and spaces, for example:

```dotenv
RESEARCHRELAY_DB="~/Library/Application Support/ResearchRelay/state.db"
RESEARCHRELAY_REPO="~/Library/Application Support/ResearchRelay/project-record"
```

Relative paths are resolved from the directory where the command runs; `~` expands to your home directory. Keep using the same `.env` and working directory in both terminals. The application creates the state/worktree directories with your normal account permissions. `.env` is ignored by Git; do not put provider credentials in project artifacts.

### Start, demonstrate, and test

Terminal 1, from the checkout:

```bash
mamba run -n researchrelay researchrelay serve --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. In Terminal 2, `cd` into the same checkout and run the demonstration, or use the dashboard's **Run local pilot** button:

```bash
mamba run -n researchrelay researchrelay demo
mamba run -n researchrelay python -m pytest -q
mamba run -n researchrelay python -m pip check
mamba run -n researchrelay python scripts/smoke.py
```

`scripts/smoke.py` starts and stops its own service on a temporary loopback port, using an isolated database/project repository. It checks HTTP startup, parallel scoring, dependent synthesis, review/revision, Git records, and the human decision. It does not alter your working-session state. The full test suite also exercises paths containing spaces and non-ASCII text, home-relative paths, interruption, and concurrency.

To build the wheel without adding a separate build tool:

```bash
mamba run -n researchrelay python -m pip wheel --no-deps --wheel-dir .runtime/dist .
```

For a Python-only setup, install a native Python 3.12 interpreter first, then run `python3.12 -m venv .venv`, `source .venv/bin/activate`, and `python -m pip install -r requirements.lock.txt -e ".[dev]"` from the checkout. Replace `mamba run -n researchrelay` in subsequent commands with the active environment's command (for example, `python scripts/smoke.py` or `researchrelay serve`). Never reuse a Windows virtual environment on a Mac.

### Optional browser and live-worker checks

The service works in your normal browser without Playwright. Automated browser tests use [Playwright-managed Chromium](https://playwright.dev/python/docs/browsers), on either architecture, rather than a Windows executable path. Current [Playwright requirements](https://playwright.dev/python/docs/intro#system-requirements) specify macOS 14+ for this optional test tool.

```bash
mamba run -n researchrelay python -m pip install -e ".[browser]"
mamba run -n researchrelay python -m playwright install chromium
mamba run -n researchrelay python scripts/smoke.py --browser
```

For an existing Chrome installation, `scripts/ui_smoke.py --browser "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"` selects that executable; the complete isolated-service invocation is documented in [verification](#verification-and-limits). Safari is usable as an ordinary browser, but this Chromium smoke does not automate Safari.

Claude and `gh` are needed only for live execution/publication. Install/authenticate them in each participant's own environment and ensure `claude --version` and `gh --version` work in the same Terminal that starts the worker. macOS example:

```bash
export RESEARCHRELAY_TOKEN='alice-project-secret'
mamba run -n researchrelay researchrelay worker --participant alice --repo "$HOME/Projects/team-project" --server http://127.0.0.1:8000 --once
```

Replace that token and repository path with your actual project configuration. Default worker tools support files; authorize the scientific execution tools separately as described in [worker integration](docs/worker.md). The local demo does not exercise live Claude credentials, GitHub PR policy, or macOS privacy prompts for restricted folders.

The [macOS compatibility workflow](.github/workflows/macos.yml) runs native Python 3.12 on Apple Silicon and Intel macOS 15 runners, including tests, a wheel build, service/pilot smoke, and browser smoke. See [verification results](docs/verification.md) for actual execution results and remaining limitations; a passing dependency download on Windows alone is not macOS execution.

## The pilot

The bundled [meeting notes](examples/meeting-notes.txt) and [synthetic daily data](examples/forecast.csv) drive the following sequence:

1. Meeting notes become an attributable summary, explicit decisions with rationale, editable task proposals, and open questions. Demo scope approval is scripted and labeled; ordinary meeting intake requires the participant to edit and approve the proposals.
2. Alice and Bob's simulated participant agents score separate forecasts concurrently in isolated Git worktrees. They run actual Python calculations and record data/code hashes and environment details.
3. Carol reviews their results; only reviewed dependencies unlock the synthesis task. Synthesis pins exact versions of both result artifacts.
4. Carol requests a justified revision: the initial comparison uses unequal dates and lacks uncertainty. Alice produces a second version using paired dates and a seeded bootstrap, with methodological limitations.
5. Reviewed changes and completion notes enter the local project Git history. Portable meeting, task, result, review, and decision records are exported with a generated dashboard snapshot.
6. The dashboard asks a human which next evaluation to prioritize, presenting evidence, options, and the consequences for subsequent work. The human's answer and rationale become a new decision artifact version.

This is **local demonstration mode**: deterministic agents, real scientific calculations, real SQLite and Git, simulated pull requests. It requires no Claude or GitHub credentials. No model calls, GitHub push, PR creation, or cloud deployment are implied by a successful local run.

The bootstrap uses independent resampling of a very small synthetic daily sample. It illustrates a reviewable workflow; it does not support a scientific generalization or a productivity claim.

## Architecture and assumptions

```mermaid
flowchart LR
    H[Scientist / browser] --> API[FastAPI coordination API]
    W1[Alice's worker + Claude CLI] --> API
    W2[Bob's worker + own tools] --> API
    API --> DB[(SQLite: authoritative workflow state)]
    API --> A[Immutable Markdown / YAML artifacts]
    W1 --> G[Isolated Git task branches]
    W2 --> G
    A --> G
    G --> PR[GitHub draft PR / repository review policy]
    PR --> I[Fetch + validate + import evidence]
    I --> API
```

- **One project per service/database.** Intended for a trusted small team and one service process, with SQLite WAL transactions fencing concurrent claims and submissions. This is not a multi-tenant hosted product.
- **Coordination is separate from execution.** FastAPI serves the dashboard and workflow API. Participant workers poll persistent tasks and run in their own environments. The server's demo runner launches only the bundled synthetic experiment.
- **SQLite owns execution state.** Tasks, attempts, leases, events, immutable artifact versions, submissions, review records, decisions, measures, and demo job status survive browser closure and restarts. No in-memory queue owns task work.
- **Git preserves the project record.** Immutable artifact exports, task code/results, and derived dashboard snapshots are reviewable outside the application. Editing a snapshot does not change task state. Imported artifact changes become evidence; execution or scope changes still use explicit API operations.
- **Conservative meeting extraction.** The initial local parser recognizes explicit decision/question markers, structured task lines, and simple named assignments. Inferred owners, criteria, outputs, and dependencies are visible and editable. It preserves source notes and does not claim comprehensive natural-language understanding.
- **Scientific authority stays human.** A computational submission enters `awaiting_review`; independent agent approval allows downstream work. A scientific decision requires a participant's choice and rationale. Resolving a decision never launches new scientific scope automatically.

See [artifact format and schemas](docs/artifacts.md), [worker and Git integration](docs/worker.md), and the [implementation contract](docs/CONTRACT.md).

## State and reliability

```mermaid
stateDiagram-v2
    [*] --> queued: human approves scope
    queued --> running: atomic claim + expiring token
    running --> queued: expired lease / attempts remain
    running --> failed: expired lease / budget exhausted
    running --> blocked: worker needs clarification
    blocked --> queued: human reconciles and retries
    failed --> queued: human retry within budget
    running --> awaiting_review: validated idempotent submission
    awaiting_review --> queued: review requests revision
    awaiting_review --> blocked: review budget exhausted
    awaiting_review --> completed: independent review approves
    queued --> canceled
    running --> canceled
```

Claims default to 120 seconds. Heartbeats renew them; only the active claim token may submit. Lease expiry fences the previous worker and consumes an attempt. A task has five attempts by default (maximum ten) and at most two requested revisions; further disagreement becomes a visible human decision. Workers stop their Claude subprocess after claim loss or execution timeout.

Submissions require a durable idempotency key. The first submission, artifact, event, and task transition commit atomically; exact replays return the stored response, including after restart. Reusing the key with different content is rejected. Artifact versions are immutable and sequential. Reviews name the exact result version. Task dependencies form a validated DAG and require reviewed completion. Workers use a private, locally ignored exchange directory and commit task-specific records, allowing independent output branches to merge without shared exchange-file conflicts.

Input versions are pinned when work is claimed. A newer input artifact disables readiness or prevents submission and shows the conflicting versions. In task details, a human can inspect both versions and explicitly approve updated pins for queued or blocked work. The API also accepts explicitly reconciled `input_refs`; the service does not silently change the evidence beneath an ongoing task.

The demo job launcher persists its status. Restarted service jobs are labeled `interrupted`; rerunning the pilot resumes supported stages. Arbitrary worker processes resume by polling durable task state after lease expiry. Worktrees and saved submission payloads remain available for recovery.

## Claude and GitHub integration

The installed Claude CLI is the initial execution adapter. Each participant logs in and supplies their own clone, local tools, and project token. The coordinator never needs their Claude credentials.

```powershell
# In Alice's own environment and project clone:
$env:RESEARCHRELAY_TOKEN = 'alice-project-secret'
mamba run -n researchrelay researchrelay worker --participant alice --repo D:/research/project --server http://127.0.0.1:8000 --once
```

The default Claude tools cover reading/writing artifacts. For execution, explicitly configure the worker's `--allowed-tools` to match authorized commands and local Claude permission rules; see [worker documentation](docs/worker.md). API-only/manual adapters can use the same task, claim, heartbeat, submit, block, and review endpoints without any provider dependency.

Live publication is opt-in. Configure `origin` to the explicit GitHub project, authenticate `gh` in the participant's environment, and publish a task branch through a draft PR. The adapter verifies the destination, reuses an existing open PR, and never merges; repository protection and review rules remain in force. Fetch is fast-forward only. New versions edited directly in GitHub can be fetched and imported; conflicting immutable edits and divergent branches require reconciliation.

```powershell
mamba run -n researchrelay researchrelay publish --repo D:/research/project --github TEAM/PROJECT --branch tasks/forecast-a/attempt-1 --title 'Forecast A evaluation' --body-file proposal.md
```

Run fetch/import/export on the **coordinator host** against its authoritative database and configured project-record clone. A remote participant publishes their task branch; they do not maintain a second execution-state database. The coordinator can fetch reviewed changes and export updated records on a separate records branch for another draft PR:

```powershell
# On the coordinator host; use the repository path from RESEARCHRELAY_REPO.
mamba run -n researchrelay researchrelay fetch --repo D:/research/project-record --branch main
git -C D:/research/project-record switch -c records/session-1
mamba run -n researchrelay researchrelay export --repo D:/research/project-record
mamba run -n researchrelay researchrelay publish --repo D:/research/project-record --github TEAM/PROJECT --branch records/session-1 --title 'Session project record' --body-file record-proposal.md
```

The Claude invocation follows its [programmatic CLI interface](https://code.claude.com/docs/en/headless). Live PR operations use the [GitHub CLI](https://cli.github.com/manual/gh_pr_create). Live model execution and remote publication require a configured participant session and were not exercised in the credential-free smoke test.

## Team access and data

The default server binds to loopback and rejects unauthenticated nonlocal API traffic. For team access, configure `RESEARCHRELAY_TOKENS` as a JSON mapping from random project tokens to participant names; `human` is the coordination role. Workers may claim and submit only their owner's tasks; review identity must match the token. All tokens belong to this single project. Use a private network and HTTPS reverse proxy for remote access. The dashboard accepts a session token without adding it to exported artifacts.

Git worktrees isolate filesystem changes and branches; they are **not an OS security sandbox**. Participants should use their own container/VM or restricted account for untrusted agent work. The system trusts participants' project access. Do not expose this pilot directly to the public internet.

Keep datasets, model checkpoints, and large outputs in external storage. Artifact provenance records should include a storage URI, checksum/version, access instructions, code commit, parameters, environment, evidence, assumptions, and limitations. Credentials never belong in notes, result bodies, tracked files, or storage URLs. Validation rejects named secret fields in metadata, but human text and arbitrary file contents still need normal repository secret controls.

Back up the database together with its project repository. Use SQLite's backup facility or stop the service before copying the database; copying a live `.db` alone can miss WAL transactions.

## Working-session evaluation

Use the dashboard assessment to record actual human coordination minutes, a 1–5 rating of handoff clarity, and a short observation. The worker/API can additionally record clarification requests. Derived measures include task execution time, review cycles, rework, and unresolved blockers. Demo-generated measures are labeled as scripted or derived, and missing human measures remain unmeasured.

Suggested session: paste or inspect the supplied notes, correct proposed scope, run the local pilot, inspect the first and revised synthesis, resolve the scientific decision with a rationale, and record whether you understand what others completed and what needs attention next. Compare coordination time and comprehension with your existing process before claiming a productivity gain.

## Verification and limits

```powershell
mamba run -n researchrelay python -m pytest -q
```

Tests cover the scientific pilot and Git history, interrupted execution and claim fencing, competing claims, duplicate and conflicting submissions, dependency gating and stale versions, review/revision bounds, artifact validation, cancellation, repository update conflicts, direct Git imports, and API project-token scope. See [verification report](docs/verification.md) for the actual run and browser-check results.

The environment file installs the verified versions in `requirements.lock.txt`. Optional real-browser verification uses a fresh isolated service because it writes synthetic QA records:

```bash
mamba run -n researchrelay python -m pip install -e ".[browser]"
mamba run -n researchrelay python -m playwright install chromium
mamba run -n researchrelay python scripts/smoke.py --browser
```

For manual inspection with a separate browser smoke script, keep an isolated service running. On macOS/Linux:

```bash
export RESEARCHRELAY_DB='.runtime/browser-check.db'
export RESEARCHRELAY_REPO='.runtime/browser-check-record'
mamba run -n researchrelay researchrelay serve --port 8767
```

On Windows PowerShell, use these environment assignments instead:

```powershell
$env:RESEARCHRELAY_DB = '.runtime/browser-check.db'
$env:RESEARCHRELAY_REPO = '.runtime/browser-check-record'
mamba run -n researchrelay researchrelay serve --port 8767
```

In another terminal, with that fresh service running:

```bash
mamba run -n researchrelay python scripts/ui_smoke.py --url http://127.0.0.1:8767
```

The browser script defaults to Playwright-managed Chromium on all supported platforms. To use an existing browser, add `--browser` with its executable path, such as `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"` on macOS or `"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"` on Windows. Use a new database/repository name for each full browser-smoke run.

Known limits: one project and one coordinator process; rule-based meeting extraction; local worker worktrees rather than security sandboxes; manual reconciliation for imported task scope changes; small-team static tokens rather than institutional SSO; no remote GitHub or Claude execution validated without a chosen project/session. Package installation supports the service and worker, while the bundled pilot expects the source checkout's `examples/` directory.

The most useful next step is a real two-participant session using Claude workers against a designated GitHub repository. Use the resulting clarification/review data to improve meeting extraction and task-scope editing before adding providers or orchestration complexity.
