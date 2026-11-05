"""Deterministic literature collaboration demo over verified, dated source notes.

This executes local Python scripts, not a live literature search or model call.
SQLite owns task state; isolated Git branches preserve intermediate work.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

import yaml

from .artifacts import render_markdown, validate_artifact
from .engine import WorkflowError
from .knowledge import parse_knowledge
from .meetings import extract_meeting
from .repository import Repository, _git

TASK_IDS = ("human-ai-evidence", "agent-coordination", "literature-synthesis")
SOURCE_GROUPS = {
    "human-ai-evidence": ["vaccaro-2024-human-ai", "amershi-2019-guidelines", "schmidgall-2025-agent-laboratory",
                          "shao-2024-storm", "liu-2024-lost-middle", "w3c-2013-prov"],
    "agent-coordination": ["wu-2024-autogen", "hong-2024-metagpt", "fourney-2024-magentic-one",
                           "yang-2024-swe-agent", "git-2026-worktree", "google-2026-okf"],
}
NEXT_SEARCH_OPTIONS = ["Update the search for recent human-agent collaboration studies",
                       "Audit full-text methods and outcome measures", "Design a small-team handoff evaluation"]

INVENTORY_SCRIPT = r'''"""Reproduce the local source inventory and evidence synthesis; no network or LLM."""
from collections import Counter
import hashlib,json,re,sys
from pathlib import Path
import yaml

def section(body, heading):
    pattern = r"^## " + re.escape(heading) + r"[^\n]*\n+(.*?)(?=^## |\Z)"
    found = re.search(pattern, body, re.M | re.S)
    return found.group(1).strip() if found else "Not recorded in the source note."

def inventory(task_id):
    groups = json.loads(Path("literature/groups.json").read_text(encoding="utf-8"))
    notes = []
    for slug in groups[task_id]:
        path = Path("literature/sources") / (slug + ".md")
        raw = path.read_bytes()
        _, front, body = raw.decode("utf-8").split("---", 2)
        meta = yaml.safe_load(front)
        bib = meta["bibliography"]
        notes.append(dict(id=slug,artifact_id=meta["id"],title=bib["title"],publication_status=bib["kind"],
            authors=bib["authors"],year=bib["year"],venue=bib["venue"],doi=bib.get("doi"),url=bib["url"],access=bib["access"],
            source_path=path.as_posix(),sha256=hashlib.sha256(raw).hexdigest(),
            findings=section(body,"Findings"),methods=section(body,"Methods"),limitations=section(body,"Limitations"),
            implication=section(body,"Implications for ResearchRelay")))
    return dict(task_id=task_id,source_count=len(notes),source_notes=notes,search_date="2026-11-04",
                live_search=False,model_inference_live=False,method="Read and inventory the verified seed notes")

def synthesize(input_path, version):
    groups = json.loads(Path(input_path).read_text(encoding="utf-8"))
    notes = [note for group in groups for note in group["source_notes"]]
    if len({note["id"] for note in notes}) != len(notes):
        raise ValueError("The source groups overlap; reconcile the pinned results.")
    result = dict(source_count=len(notes),search_date="2026-11-04",live_search=False,model_inference_live=False,
        source_titles=[note["title"] for note in notes],
        claim="Structured, attributed handoffs are a promising coordination design; this corpus does not measure ResearchRelay productivity.")
    if version == 1:
        result.update(access_limits_explicit=False,
            unresolved=["Classify publication status and distinguish abstract access from full methodological appraisal."])
    else:
        result.update(source_notes=notes,publication_counts=dict(Counter(note["publication_status"] for note in notes)),
            access_limits_explicit=True,
            limitations=["Focused seed search, not a systematic or exhaustive review.",
                         "Most summaries rely on abstracts and metadata; full-text methodological audit is follow-up work.",
                         "Preprints, standards, and software manuals are not interchangeable empirical evidence.",
                         "Scripted local execution does not establish human coordination savings or scientific validity."],
            next_search_options=["Update the search for recent human-agent collaboration studies",
                                 "Audit full-text methods and outcome measures","Design a small-team handoff evaluation"])
    return result

if __name__ == "__main__":
    result = inventory(sys.argv[2]) if sys.argv[1] == "inventory" else synthesize(sys.argv[2], int(sys.argv[3]))
    print(json.dumps(result, indent=2, ensure_ascii=False))
'''


def _checkout() -> Path:
    path = Path(__file__).resolve().parent.parent
    if not (path / "examples/meeting-notes.txt").exists() or not (path / "projects/agentic-collaboration/sources").is_dir():
        raise FileNotFoundError("Run the literature demo from the source checkout; its meeting and verified source notes must be present")
    return path


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed(repo: Repository, checkout: Path) -> None:
    # These namespaces belong to the demo record. Commit byte-preserving
    # attributes before creating worker worktrees: provenance hashes must not
    # depend on a participant's core.autocrlf or root-level text policy.
    # Existing policies are handled by the same preserve-or-refuse seed check.
    files = {directory+"/.gitattributes": b"* -text\n"
             for directory in ("literature", "analysis", "task-records", "artifacts")}
    files.update({"analysis/source_inventory.py": INVENTORY_SCRIPT.encode("utf-8"),
                  "literature/groups.json": (json.dumps(SOURCE_GROUPS, indent=2)+"\n").encode("utf-8")})
    bundle = checkout / "projects/agentic-collaboration"
    for source in sorted(bundle.rglob("*.md")):
        relative = source.relative_to(bundle)
        raw = source.read_bytes()
        parse_knowledge(raw.decode("utf-8"), "agentic-collaboration", path=relative)
        files["literature/"+relative.as_posix()] = raw
    for name, content in files.items():
        target = repo.path / name
        if target.exists() and target.read_bytes() != content:
            raise WorkflowError(f"The demo seed differs from existing {name}. Preserve that record and choose a fresh literature database/repository.")
    for name, content in files.items():
        target = repo.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _git(repo.path, "add", "--", *files)
    if _git(repo.path, "diff", "--cached", "--name-only"):
        repo._commit(repo.path, "Add dated literature source notes and reproducible inventory script")


def _metadata(engine, task: dict, version: int, code_commit: str, workspace: Path,
              evidence: dict, notes: list[dict]) -> dict:
    return validate_artifact(dict(id=f"result-{task['id']}", project_id=engine.project_id,
        artifact_type="result", version=version, task_id=task["id"], type="Literature Result", format_status="provisional",
        responsible_participant=task["owner"], producing_agent=f"literature-script/{task['owner']}",
        objective=task["objective"], input_refs=task.get("input_refs",[]), dependencies=task.get("dependencies",[]),
        acceptance_criteria=task["acceptance_criteria"], expected_outputs=task["expected_outputs"],
        data=[dict(path=note["source_path"],sha256=note["sha256"],source=note["url"],access=note["access"]) for note in notes],
        code=[dict(path="analysis/source_inventory.py",sha256=_hash(workspace/"analysis/source_inventory.py"),commit=code_commit)],
        configuration=dict(search_date="2026-11-04",execution="deterministic source-note inventory",
                           groups_sha256=_hash(workspace/"literature/groups.json"),live_search=False,model_inference_live=False),
        environment=dict(python=sys.version.split()[0],io_encoding="utf-8",dependencies={"PyYAML":yaml.__version__}),
        evidence=evidence, assumptions=["The dated source notes are the supplied evidence, not a freshly executed search."],
        limitations=evidence.get("limitations",["Scripted demo; no live search, model inference, independent scientific validation, or productivity claim."]),
        validation_results=[dict(check="Source note paths and SHA-256 hashes recorded",passed=True)],
        next_actions=["Review evidence scope and access limits", "Human chooses the next search question"],
        sources=[dict(id=note["id"],resource=note["url"],title=note["title"]) for note in notes],
        citations=[dict(source_id=note["id"],url=note["url"]) for note in notes],
        repository_commits=[code_commit],related_files=[note["source_path"] for note in notes]+["analysis/source_inventory.py"]))


def _run(workspace: Path, *arguments: str) -> dict:
    completed = subprocess.run([sys.executable,"-X","utf8","analysis/source_inventory.py",*arguments],cwd=workspace,
        capture_output=True,text=True,encoding="utf-8",timeout=30,check=True)
    return json.loads(completed.stdout)


def run_pilot(engine, repo_path: str | Path) -> dict:
    """Run/resume the default literature demo without mixing unrelated user tasks."""
    started = time.monotonic()
    checkout = _checkout()
    notes_text = (checkout/"examples/meeting-notes.txt").read_text(encoding="utf-8")
    proposed = extract_meeting(notes_text,"human",engine.project_id)
    meeting_id = proposed["metadata"]["id"]
    existing = {task["id"] for task in engine.list_tasks()}
    with engine.connect() as db:
        approved = db.execute("SELECT value FROM settings WHERE key=?",(f"approved:{meeting_id}",)).fetchone()
    if existing and (existing != set(TASK_IDS) or not approved or set(json.loads(approved[0])) != set(TASK_IDS)):
        raise WorkflowError("This database contains unrelated or legacy work. Choose a fresh literature demo database and project repository; existing records were preserved.")
    resuming = bool(existing)
    repo = Repository(repo_path)
    repo.initialize()
    if not resuming:
        if _git(repo.path,"status","--porcelain"):
            raise WorkflowError("The project record has uncommitted work. Preserve it and choose a fresh demo repository, or reconcile those changes first.")
        _seed(repo, checkout)
        meeting = engine.create_meeting(notes_text,"human")
        # This approval is a labeled script fixture, not a claim of human consensus.
        engine.approve_meeting(meeting["id"],meeting["proposed_tasks"])

    def reviewed_merge(task_id):
        current = engine.get_task(task_id)
        if current.get("repository"):
            repo.reconcile_local(current["repository"][-1]["branch"],task_id)

    def review_inventory(task_id):
        result = engine.get_artifact(f"result-{task_id}",1)
        evidence = result["metadata"]["evidence"]
        if evidence["source_count"] != 6 or {note["id"] for note in evidence["source_notes"]} != set(SOURCE_GROUPS[task_id]):
            raise RuntimeError("The inventory does not match its approved source group; reconcile before review.")
        engine.review_task(task_id,"carol","approve",
            "Scripted check: all six assigned notes are inventoried with source URLs, access labels and exact file hashes. Interpretation still needs scientific review.",
            ["Read the assigned source notes", "Preserve citations and provenance", "Avoid unsupported productivity claims"],1)

    def inventory(task_id):
        task_started = time.monotonic()
        current = engine.get_task(task_id)
        if current["status"] in {"completed","awaiting_review"}:
            if current["status"] == "awaiting_review":
                review_inventory(task_id)
            reviewed_merge(task_id)
            return engine.get_artifact(f"result-{task_id}",1)["metadata"]["evidence"]
        claim = engine.claim_task(task_id,current["owner"],120)
        task = claim.get("task",claim)
        token = claim.get("claim_token") or task["claim_token"]
        isolation = repo.isolated_branch(task_id,task["attempts"])
        workspace = Path(isolation["workspace"])
        engine.heartbeat(task_id,token,"Reading assigned literature notes and recording citation/access provenance",120)
        evidence = _run(workspace,"inventory",task_id)
        output = f"analysis/{task_id}/inventory.json"
        (workspace/output).parent.mkdir(parents=True,exist_ok=True)
        (workspace/output).write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        code_commit = repo.commit_workspace(workspace,task_id,[output],"Inventory verified literature source notes")
        metadata = _metadata(engine,task,1,code_commit,workspace,evidence,evidence["source_notes"])
        lines = [f"# {task['title']}","","Local deterministic script; no live search or model inference.",""]
        lines += [f"- [{note['title']}]({note['url']}) — {note['publication_status']}; access: {note['access']}." for note in evidence["source_notes"]]
        body = "\n".join(lines)+"\n\nThe inventory records supplied findings; it is not an independent scientific validation.\n"
        name = f"task-records/{task_id}/v1.md"
        (workspace/name).parent.mkdir(parents=True,exist_ok=True)
        (workspace/name).write_text(render_markdown(metadata,body),encoding="utf-8")
        commit = repo.commit_workspace(workspace,task_id,[name],"Result and completion notes")
        engine.record_repository(task_id,isolation["branch"],commit,detail="Local literature demo branch; simulated PR, no external service")
        engine.submit_result(task_id,token,f"pilot-{task_id}-v1",{"metadata":metadata,"body":body},
            "Read six source notes; publication/access labels and pinned provenance recorded; scripted peer review requested.")
        review_inventory(task_id)
        repo.reconcile_local(isolation["branch"],task_id)
        engine.add_metric(task["owner"],"task_completion_seconds",time.monotonic()-task_started,task_id)
        return evidence

    with ThreadPoolExecutor(max_workers=2,thread_name_prefix="literature-participant") as pool:
        first = pool.submit(inventory,TASK_IDS[0])
        second = pool.submit(inventory,TASK_IDS[1])
        group_a,group_b = first.result(),second.result()

    def synthesize(version):
        task_id = TASK_IDS[2]
        synthesis_started = time.monotonic()
        current = engine.get_task(task_id)

        def finish_review():
            if version == 1:
                engine.review_task(task_id,"carol","revise",
                    "The synthesis pools published papers, unreviewed reports and documentation without classifying their evidential roles. Most source access is abstract-level. Add publication counts, per-source access limits and a bounded claim before proposing the next search.",
                    ["Distinguish publication status", "Make access limits explicit", "Separate design implications from productivity evidence"],1)
            else:
                engine.review_task(task_id,"carol","approve",
                    "The revision distinguishes seven published papers, two preprints, two specifications and one manual; access limits are explicit. The next search and methodological appraisal remain human choices. This is a scripted check, not independent scientific verification.",
                    ["Publication classes and citations recorded", "Abstract/full-text access distinguished", "Human search direction retained"],2)

        if current["status"] == "completed":
            reviewed_merge(task_id)
            return engine.get_artifact(f"result-{task_id}")["metadata"]["evidence"]
        if version == 1 and current["revision_count"] >= 1:
            return engine.get_artifact(f"result-{task_id}",1)["metadata"]["evidence"]
        if current["status"] == "awaiting_review" and current.get("result_ref",{}).get("version") == version:
            finish_review()
            if version == 2:
                reviewed_merge(task_id)
            return engine.get_artifact(f"result-{task_id}",version)["metadata"]["evidence"]
        claim = engine.claim_task(task_id,"alice",120)
        task = claim.get("task",claim)
        token = claim.get("claim_token") or task["claim_token"]
        isolation = repo.isolated_branch(task_id,task["attempts"])
        workspace = Path(isolation["workspace"])
        engine.heartbeat(task_id,token,"Synthesizing exact accepted source inventories and evidence limits",120)
        expected = {f"result-{identifier}" for identifier in TASK_IDS[:2]}
        pinned = {ref["id"]:engine.get_artifact(ref["id"],ref["version"])
                  for ref in task["input_refs"] if ref["id"] in expected}
        if set(pinned) != expected:
            raise RuntimeError("Literature synthesis requires exact accepted versions of both source inventories")
        for record in pinned.values():
            for item in record["metadata"]["data"]:
                if _hash(workspace/item["path"]) != item["sha256"]:
                    raise RuntimeError("The literature notes differ from the accepted input inventory. Reconcile the changed evidence before retrying.")
        inputs = [pinned[f"result-{identifier}"]["metadata"]["evidence"] for identifier in TASK_IDS[:2]]
        source_notes = [note for inventory_result in inputs for note in inventory_result["source_notes"]]
        input_name = f"analysis/literature-synthesis/inputs-v{version}.json"
        (workspace/input_name).parent.mkdir(parents=True,exist_ok=True)
        (workspace/input_name).write_text(json.dumps(inputs,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        evidence = _run(workspace,"synthesize",input_name,str(version))
        if version == 1:
            body = ("# Initial literature synthesis\n\n"+evidence["claim"]+"\n\n"
                    f"The two accepted inventories cover {evidence['source_count']} sources. "
                    "Publication classes and evidence-access limitations still need an explicit synthesis-level appraisal.\n\n"
                    "This is a deterministic demonstration over the dated seed search, not a new literature search or live model review.\n")
        else:
            counts = evidence["publication_counts"]
            body = ("# Revised literature synthesis\n\n"+evidence["claim"]+"\n\n"
                    f"The {evidence['source_count']} sources comprise {counts['published_paper']} published papers, "
                    f"{counts['preprint']} preprints/technical reports, {counts['specification']} specifications, "
                    f"and {counts['software_documentation']} official software manual.\n\n"
                    "## Evidence and access limits\n\n")
            body += "\n".join(f"- [{note['title']}]({note['url']}) — {note['publication_status']}; access: {note['access']}." for note in source_notes)
            body += ("\n\n## Interpretation and next search\n\nThe published studies and system descriptions inform coordination design. "
                     "They do not demonstrate ResearchRelay productivity gains or validate a scientific conclusion. "
                     "Most notes summarize abstracts and metadata; preprints are not treated as peer-reviewed findings, and documentation is not empirical evidence. "
                     "A human should choose between updating the search, auditing full-text methods, and designing a small-team evaluation. "
                     "The scripted peer review checks workflow behavior; independent scientific review remains open.\n")
        output_name = f"analysis/literature-synthesis/v{version}.json"
        (workspace/output_name).write_text(json.dumps(evidence,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
        code_commit = repo.commit_workspace(workspace,task_id,[input_name,output_name],f"Literature synthesis version {version}")
        metadata = _metadata(engine,task,version,code_commit,workspace,evidence,source_notes)
        if version == 2:
            metadata["validation_results"].extend([dict(check="Publication classes distinguished",passed=True),
                                                  dict(check="Per-source access limitations explicit",passed=True)])
        name = f"task-records/{task_id}/v{version}.md"
        (workspace/name).parent.mkdir(parents=True,exist_ok=True)
        (workspace/name).write_text(render_markdown(metadata,body),encoding="utf-8")
        commit = repo.commit_workspace(workspace,task_id,[name],f"Reviewed literature result version {version}")
        engine.record_repository(task_id,isolation["branch"],commit,detail="Local literature demo; simulated review proposal")
        engine.submit_result(task_id,token,f"pilot-{task_id}-v{version}",{"metadata":metadata,"body":body},
            "Revised synthesis distinguishes publication status and access limits; human chooses next search." if version==2 else
            "Initial synthesis of the accepted source inventories submitted for critique.")
        finish_review()
        if version == 2:
            repo.reconcile_local(isolation["branch"],task_id)
            engine.add_metric("alice","task_completion_seconds",time.monotonic()-synthesis_started,
                              "Revised literature synthesis and scripted review")
        return evidence

    synthesize(1)
    review = synthesize(2)
    question = "Which evidence gap should the team investigate next?"
    existing_decision = next((decision for decision in engine.dashboard(mark_visit=False)["decisions"] if decision["question"]==question),None)
    counts = review["publication_counts"]
    decision = existing_decision or engine.request_decision(question,
        [f"The dated seed review covers {review['source_count']} sources: {counts['published_paper']} published papers, "
         f"{counts['preprint']} preprints, {counts['specification']} specifications and {counts['software_documentation']} manual.",
         "Most notes use abstracts/metadata; source access and publication status are explicit in result-literature-synthesis@2.",
         "The search is focused and non-exhaustive; no ResearchRelay productivity gain has been measured.",
         "Evidence: both pinned inventories, the revised synthesis, and the recorded review rationale."],
        NEXT_SEARCH_OPTIONS,
        "The selected option defines the next search or evaluation scope. No follow-up task is launched automatically.",
        participant="human",task_id=TASK_IDS[2])
    if not existing_decision:
        engine.add_metric("carol","review_cycles",2,"Literature synthesis reviewed twice (scripted demonstration)")
        engine.add_metric("alice","rework",1,"One justified revision: publication classification and access limitations")
    exported = repo.export(engine)
    return dict(status="completed",mode="local literature demonstration — deterministic scripts and simulated pull requests",
        literature_review=review,source_groups={TASK_IDS[0]:group_a,TASK_IDS[1]:group_b},human_decision=decision,
        repository=exported,task_ids=list(TASK_IDS),
        exercised=["SQLite persisted coordination","parallel source-note inventories","dependency-pinned accepted results",
                   "justified peer review and revision","isolated Git worktrees and local reviewed merges","portable artifact export"],
        github_exercised=False,claude_exercised=False,live_search=False,model_inference_live=False,
        elapsed_seconds=time.monotonic()-started,resumed=resuming,
        note="Uses the verified 2026-11-04 seed search. Human coordination time and participant understanding require actual working-session input; no productivity gain is claimed.")
