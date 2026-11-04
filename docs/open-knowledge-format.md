# Selected Open Knowledge Format reference

No existing ResearchRelay documentation, template, or artifact bound the phrase **Open Knowledge Format** to an intended specification. A live search on **2026-11-04** found Google Cloud's [canonical OKF repository](https://github.com/GoogleCloudPlatform/open-knowledge-format), including the migration notice from `GoogleCloudPlatform/knowledge-catalog/okf`.

We **select** [OKF 0.2 at commit `ad30107c31c06aec8a7d5636e0d1058118604e6f`](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/ad30107c31c06aec8a7d5636e0d1058118604e6f/SPEC.md) as an explicit assumption; a matching name does not establish the user's intended adoption. The fetched SPEC.md SHA-256 is `26aa5da029278939f914e578107242d9607d4f2dc5fe153272b82f9ed1030101`. ResearchRelay's publishing profile and initial review remain **provisional**, pending team confirmation and broader interoperability review.

## Conventions used

Concepts are UTF-8 Markdown with YAML front matter and nonempty `type`. The canonical format always requires only that key; ResearchRelay adds workflow metadata. Concept identity in OKF is its bundle-relative filename without `.md`; ResearchRelay's `id` is an additional stable identifier. Unknown type names and extension keys are preserved.

Provenance uses `sources`, whose entries name a `resource`; per-claim footnotes match stable source IDs. `generated` distinguishes authorship from optional `verified` events. Actor names identify agents as producer/version, people as human:id, and automated processes as process:id. No human verification is inferred. Lifecycle values are draft/stable/deprecated. The literature body uses relative Markdown links so GitHub readers can navigate it.

`index.md` and `log.md` are reserved listings/history rather than concepts. Indexes have no front matter except optional `okf_version` on the bundle-root index. Logs use newest-first ISO date headings and no front matter. These files derive contribution attribution from Git history.

## ResearchRelay publishing profile

The JSON Schema is [knowledge.v1.schema.json](../researchrelay/schemas/knowledge.v1.schema.json); helpers are in [knowledge.py](../researchrelay/knowledge.py). `parse_knowledge(text, project_id=None, path=None)` validates stored concepts and recognizes reserved files when `path` is supplied. `validate_knowledge(metadata, body)` and `render_knowledge(metadata, body)` explicitly normalize workflow metadata for newly produced or converted records. Raw concept parsing requires an actual `type` field; it does not silently declare an untyped file valid OKF.

The profile adds project/schema/content versions, responsible participant, producing agent, timestamps, provisional status, citations/relations extensions, and execution provenance. Ordinary scientific result metadata is preserved. The `sources` and `generated` fields remain distinct from those extensions. This is a stricter publishing contract, not a validator for all possible OKF bundles or optional attested-computation features.

Workflow exports keep operational state separate from OKF lifecycle: decision `open`/`resolved` values become `decision_status`, and other non-lifecycle states become `workflow_status`. Their exported lifecycle starts as `draft`. SQLite retains the original execution fields; Git snapshots do not update task claims or resolve decisions.

`validate_bundle(root, project_id)` checks these documents and reports unresolved internal links. Broken links are tolerated by the selected format and therefore reported rather than treated as universal conformance errors. Local tests require this initial seed bundle to have no unintended unresolved links. Bibliographic checks and format validation do not establish scientific validity.

## Initial project and update responsibility

The [literature bundle](../projects/agentic-collaboration/index.md) contains the actual search record, source notes, synthesis, and proposed follow-up work. It has not received human scientific review. Task proposals do not authorize execution; participant approval remains a separate coordination action. Agent results must name the project commit and document hashes they consumed. Consumers must still handle stale inputs, permissions, and review policy outside the format.
