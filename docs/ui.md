# Relay browser interface

The dashboard is served by FastAPI at `/`. Its plain HTML/CSS/JavaScript interface needs no build tool. External Google Fonts are optional; operating-system fallbacks keep the interface usable offline.

The dashboard polls persistent workflow state every four seconds. Closing a browser does not stop agents. The browser stores only the last acknowledged event sequence in local storage and an optional project token in session storage. Workflow state, measurements, and artifacts belong to the backend.

Use **Meeting to tasks** to paste or upload text/Markdown notes, inspect explicitly recorded outcomes versus agent inferences, edit task IDs/owners/objectives/dependencies/outputs/acceptance criteria, exclude proposals, and approve the resulting scope. File contents are read locally and submitted as notes; uploads are limited to 200 KB in the interface.

Task details expose criteria, pinned artifact inputs, completion notes, blockers, cancellation/retry, and version-specific result reviews. Computational completion, agent review, and human scientific judgment are labeled separately. Artifact details show validated portable Markdown including YAML front matter, provide a version selector, and allow Markdown downloads. All supplied content is rendered using text nodes, including artifact source.

When an input changes, task details show its pinned and latest versions with artifact inspection controls. For queued, blocked, or failed work, a participant must explicitly acknowledge reviewing the changed versions before accepting the updated inputs and queueing the task. Unchanged input references are retained. The interface explains that this changes the scientific evidence used for subsequent results.

Human decisions include the evidence, options, a rationale field, and consequences. Decisions and pilot assessments are submitted to the backend. Coordination time is participant-reported, with no prefilled productivity claims.

**Export to Git** and **Import Git** invoke the configured local repository integration. Import conflicts are shown in a reconciliation dialog. The local demonstration does not claim to have opened or merged a live GitHub pull request.

The interface includes keyboard-operable task rows, native dialogs, labels, visible focus styles, reduced-motion support, a skip link, responsive layouts, connection errors, and action feedback. API documentation is available from the sidebar.

`scripts/ui_smoke.py` performs an optional real-browser workflow smoke with Playwright and an installed Chrome/Edge. Point it at a **fresh, isolated demo database and repository**; it writes synthetic QA tasks, a review, a decision resolution, and measurements. In the initial verification it passed 11 workflow checks with no browser JavaScript errors, and the 390px mobile layout had no horizontal overflow. Screenshots were captured under `.runtime/` and visually inspected.

Use `python scripts/ui_smoke.py --url http://127.0.0.1:8768 --reconciliation-only` against a fresh isolated service to check changed-input inspection, the required acknowledgement, acceptance of the complete updated input set, and the resulting task readiness without repeating the forecast pilot.
