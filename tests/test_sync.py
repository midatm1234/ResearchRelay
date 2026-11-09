"""Two authenticated participants against a real local bare Git remote; no GitHub/model mocks."""
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from researchrelay.api import create_app
from researchrelay.config import Settings
from researchrelay.engine import Engine
from researchrelay.knowledge import render_knowledge
from researchrelay.sync import ProjectSync, SyncError

PROJECT = "agentic-collaboration"
PREFIX = f"projects/{PROJECT}"
BRANCH = "SRTD_DT_test"


def git(path,*arguments):
    return subprocess.check_output(["git","-C",str(path),*arguments],text=True,encoding="utf-8").strip()


def note(identity="alice",version=1,body="Evidence from the verified source.",identifier="finding"):
    metadata = dict(id=identifier,project_id=PROJECT,artifact_type="source_note",type="Source Note",
                    responsible_participant=identity,producing_agent="test-agent/1.0",version=version,
                    sources=[{"id":"source","resource":"https://arxiv.org/abs/2308.08155"}],
                    citations=["https://arxiv.org/abs/2308.08155"])
    return render_knowledge(metadata,"# Finding\n\n"+body)


@pytest.fixture
def shared(tmp_path):
    remote = tmp_path/"remote.git"
    subprocess.run(["git","init","--bare",str(remote)],check=True,capture_output=True)
    seed = tmp_path/"seed"
    subprocess.run(["git","init","-b",BRANCH,str(seed)],check=True,capture_output=True)
    bundle = seed/PREFIX
    bundle.mkdir(parents=True)
    (bundle/"index.md").write_text("# Literature project\n",encoding="utf-8")
    (bundle/"finding.md").write_bytes(note(identity="human").encode())
    git(seed,"add",".")
    git(seed,"-c","user.name=ResearchRelay tests","-c","user.email=tests@localhost.invalid","commit","-m","Seed verified context")
    git(seed,"remote","add","origin",str(remote))
    git(seed,"push","origin",BRANCH)
    settings = Settings(db_path=tmp_path/"state.db",repo_path=tmp_path/"coordinator"/"records",project_id=PROJECT,
                        github_url=str(remote),github_branch=BRANCH,knowledge_path=PREFIX,
                        tokens={"human-secret":"human","alice-secret":"alice","bob-secret":"bob"},mode="demo")
    engine = Engine(settings.db_path,PROJECT)
    app = create_app(settings,engine)
    with TestClient(app) as client:
        yield dict(client=client,engine=engine,sync=app.state.project_sync,remote=remote,seed=seed,settings=settings)


def headers(identity):
    return {"Authorization":f"Bearer {identity}-secret"}


def context(shared,identity="alice"):
    response = shared["client"].get("/api/project/context",headers=headers(identity))
    assert response.status_code==200,response.text
    return response.json()


def payload(ctx,path,content,key):
    previous = next((d for d in ctx["documents"] if d["path"]==path),None)
    return dict(expected_repository=ctx["repository"],base_commit=ctx["sync"]["latest_commit"],changes=[dict(path=path,content=content,
                expected_sha256=previous["sha256"] if previous else None)],
                agent="test-agent/1.0",request_id=key,message="Publish attributed research contribution")


def publish(shared,identity,data):
    return shared["client"].post("/api/project/publish",headers=headers(identity),json=data)


@pytest.mark.parametrize("repo_path", [".runtime/literature/project-record", ".runtime/session with spaces/연구 records"])
def test_relative_repository_paths_support_retrieval_and_publication(shared, tmp_path, monkeypatch, repo_path):
    monkeypatch.chdir(tmp_path)
    settings = Settings(db_path=shared["engine"].db_path, repo_path=Path(repo_path), project_id=PROJECT,
                        github_url=str(shared["remote"]), github_branch=BRANCH, knowledge_path=PREFIX,
                        mode="demo", tokens={})
    sync = ProjectSync(settings, shared["engine"])
    first = sync.context("alice")
    assert first["sync"]["status"] == "synced"
    assert any(document["path"] == f"{PREFIX}/finding.md" for document in first["documents"])

    path = f"{PREFIX}/relative-path-note.md"
    content = note(identifier="relative-path-note")
    result = sync.publish("alice", **payload(first, path, content, "relative-path-publication"))
    assert result["status"] == "published"
    assert git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}") == result["commit"]

    restarted = ProjectSync(settings, shared["engine"])
    retrieved = restarted.context("bob")
    assert retrieved["sync"]["latest_commit"] == result["commit"]
    assert next(document for document in retrieved["documents"] if document["path"] == path)["content"] == content


def test_two_users_exchange_real_git_knowledge_and_review(shared):
    first = context(shared)
    alice = publish(shared,"alice",payload(first,f"{PREFIX}/alice-note.md",note(identifier="alice-note"),"alice-first"))
    assert alice.status_code==200,alice.text
    second = context(shared,"bob")
    finding = next(d for d in second["documents"] if d["path"].endswith("/alice-note.md"))
    assert finding["metadata"]["responsible_participant"]=="alice"
    assert second["sync"]["latest_commit"]==alice.json()["commit"]
    review = note("bob",body="The finding is relevant, but source benchmarks do not establish scientific validity.",identifier="bob-review")
    bob = publish(shared,"bob",payload(second,f"{PREFIX}/bob-review.md",review,"bob-review"))
    assert bob.status_code==200,bob.text
    latest = context(shared)
    assert {Path(d["path"]).name for d in latest["documents"]}>={"alice-note.md","bob-review.md"}
    history = git(shared["sync"]._cache(),"log","-2","--format=%B",latest["sync"]["latest_commit"])
    assert "ResearchRelay-Participant: alice" in history and "ResearchRelay-Participant: bob" in history
    assert "ResearchRelay-Agent: test-agent/1.0" in history
    assert not shared["engine"].list_tasks()


def test_disjoint_changes_preserved_but_same_file_stale_edit_conflicts(shared):
    old = context(shared)
    a = publish(shared,"alice",payload(old,f"{PREFIX}/alice-independent.md",note(identifier="independent"),"independent-a"))
    b = publish(shared,"bob",payload(old,f"{PREFIX}/bob-independent.md",note("bob",identifier="independent-b"),"independent-b"))
    assert a.status_code==b.status_code==200
    edited = publish(shared,"alice",payload(old,f"{PREFIX}/finding.md",note(version=2,body="Updated publication-status evidence."),"edit-a"))
    assert edited.status_code==200,edited.text
    stale_payload = payload(old,f"{PREFIX}/finding.md",note("bob",version=2,body="Stale competing interpretation."),"edit-b")
    stale = publish(shared,"bob",stale_payload)
    assert stale.status_code==409,stale.text
    assert stale.json()["paths"]==[f"{PREFIX}/finding.md"]
    assert "Refresh" in stale.json()["next_action"]
    latest = context(shared,"bob")
    assert next(d for d in latest["documents"] if d["path"].endswith("/finding.md"))["body"].rstrip().endswith("Updated publication-status evidence.")
    # The draft remains durable for deliberate reconciliation; no completion was duplicated.
    with shared["engine"].connect() as db:
        row = db.execute("SELECT payload,response FROM publications WHERE request_id='edit-b'").fetchone()
        assert "Stale competing interpretation" in row["payload"] and row["response"] is None


def test_publication_replay_survives_restart_and_rejects_changed_payload(shared):
    original = payload(context(shared),f"{PREFIX}/idempotent.md",note(identifier="idempotent"),"same-request")
    first = publish(shared,"alice",original)
    assert first.status_code==200,first.text
    restarted = ProjectSync(shared["settings"],Engine(shared["engine"].db_path,PROJECT))
    assert restarted.publish("alice",**original)==first.json()
    changed = {**original,"message":"different content"}
    with pytest.raises(SyncError,match="reused"):
        restarted.publish("alice",**changed)
    assert git(shared["sync"]._cache(),"rev-parse",f"refs/remotes/origin/{BRANCH}") != ""


def test_push_race_retries_without_overwriting_an_external_contribution(shared,monkeypatch):
    sync = shared["sync"]
    original = subprocess.run
    raced = []
    def run(command,*args,**kwargs):
        if command[:3]==["git","-C",str(sync._cache())] and "push" in command and not raced:
            raced.append(True)
            path = shared["seed"]/PREFIX/"external.md"
            path.write_bytes(note("bob",identifier="external").encode())
            original(["git","-C",str(shared["seed"]),"add","."],check=True,capture_output=True)
            original(["git","-C",str(shared["seed"]),"-c","user.name=Other participant","-c","user.email=bob@localhost.invalid",
                      "commit","-m","Concurrent independent finding"],check=True,capture_output=True)
            original(["git","-C",str(shared["seed"]),"push","origin",BRANCH],check=True,capture_output=True)
        return original(command,*args,**kwargs)
    old = context(shared)
    monkeypatch.setattr("researchrelay.sync.subprocess.run",run)
    result = publish(shared,"alice",payload(old,f"{PREFIX}/racing.md",note(identifier="racing"),"race"))
    assert result.status_code==200,result.text
    assert raced
    assert {Path(d["path"]).name for d in context(shared)["documents"]}>={"external.md","racing.md"}


def test_authentication_failure_prevents_claim_and_keeps_cached_context_visible(shared,monkeypatch):
    context(shared)
    shared["engine"].create_task(id="read-evidence",title="Read evidence",owner="alice",acceptance_criteria=["Cite verified evidence"])
    def unavailable():
        raise SyncError("Repository authentication or access failed.",503,kind="authentication_error",next_action="Authenticate Git on the coordinator host.")
    monkeypatch.setattr(shared["sync"],"_fetch",unavailable)
    response = shared["client"].post("/api/tasks/read-evidence/claim",headers=headers("alice"),json={"worker_id":"alice"})
    assert response.status_code==503
    assert shared["engine"].get_task("read-evidence")["attempts"]==0
    dashboard = shared["client"].get("/api/dashboard",headers=headers("alice")).json()
    assert dashboard["project"]["sync"]["status"]=="authentication_error"
    assert dashboard["project"]["sync"]["latest_commit"]
    assert shared["client"].get("/api/project/context",headers=headers("alice")).status_code==503


def test_profiles_and_publications_are_scoped_and_do_not_accept_secrets(shared):
    client = shared["client"]
    assert client.get("/api/project").status_code==401
    assert client.put("/api/project/repository",headers=headers("alice"),json={
        "url":str(shared["remote"]),"branch":BRANCH,"knowledge_path":PREFIX}).status_code==403
    profile = {"provider":"openai-responses","model":"test-model","api_key_env":"OPENAI_API_KEY"}
    assert client.put("/api/participants/me/agent",headers=headers("alice"),json=profile).status_code==200
    assert client.get("/api/participants/me/agent",headers=headers("bob")).json()["profile"]["provider"]=="claude-cli"
    assert client.put("/api/participants/me/agent",headers=headers("alice"),json={**profile,"api_key":"private"}).status_code==422
    forged = payload(context(shared),f"{PREFIX}/forged.md",note("bob",identifier="forged"),"forged")
    assert publish(shared,"alice",forged).status_code==403
    escaped = payload(context(shared),"README.md",note(identifier="escaped"),"escaped")
    assert publish(shared,"alice",escaped).status_code==422


def test_shared_result_rejects_changed_input_document(shared):
    first = context(shared)
    original = next(d for d in first["documents"] if d["path"].endswith("/finding.md"))
    metadata = {"project_context":{"repository":shared["sync"].binding,"commit":first["sync"]["latest_commit"],
                                  "documents":[{"path":original["path"],"sha256":original["sha256"]}]}}
    shared["sync"].check_inputs(metadata)
    response = publish(shared,"alice",payload(first,original["path"],note(version=2,body="New evidence"),"new-evidence"))
    assert response.status_code==200,response.text
    with pytest.raises(SyncError,match="inputs changed"):
        shared["sync"].check_inputs(metadata)



@pytest.mark.parametrize(("existing", "proposed"), [
    ("finding.md", "FINDING.md"),
    ("sources/entry.md", "Sources/another.md"),
    ("caf\u00e9.md", "cafe\u0301.md"),
])
def test_case_and_unicode_aliases_cannot_overwrite_shared_files(shared, existing, proposed):
    # Git names are case-sensitive; default macOS/Windows filesystems are not.
    original = shared["seed"] / PREFIX / existing
    original.parent.mkdir(parents=True, exist_ok=True)
    if not original.exists():
        original.write_bytes(note("human", identifier="existing").encode())
        git(shared["seed"], "add", ".")
        git(shared["seed"], "-c", "user.name=Test seed", "-c", "user.email=tests@localhost.invalid",
            "commit", "-m", "Existing shared record")
        git(shared["seed"], "push", "origin", BRANCH)
    first = context(shared)
    before = git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}")
    result = publish(shared, "alice", payload(first, f"{PREFIX}/{proposed}",
                                             note(identifier="alias-draft"), "alias-draft"))
    assert result.status_code in {409, 422}, result.text
    assert "collid" in result.text.lower() or "collision" in result.text.lower()
    assert git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}") == before
    assert next(d for d in context(shared)["documents"] if d["path"] == f"{PREFIX}/{existing}")


@pytest.mark.parametrize("second_path", ["duplicate.md", "DUPLICATE.md"])
def test_duplicate_document_changes_are_rejected_before_publication(shared, second_path):
    first = context(shared)
    request = payload(first, f"{PREFIX}/duplicate.md", note(identifier="duplicate"), "duplicates")
    request["changes"].append({"path": f"{PREFIX}/{second_path}",
                              "content": note(identifier="second-copy"), "expected_sha256": None})
    before = git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}")
    result = publish(shared, "alice", request)
    assert result.status_code == 422, result.text
    assert git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}") == before


def test_result_context_cannot_invent_a_commit_with_current_document_hashes(shared):
    first = context(shared)
    original = next(d for d in first["documents"] if d["path"].endswith("/finding.md"))
    metadata = {"project_context": {"repository":shared["sync"].binding,"commit": "0" * 40,
                "documents": [{"path": original["path"], "sha256": original["sha256"]}]}}
    with pytest.raises(SyncError, match="commit") as failure:
        shared["sync"].check_inputs(metadata)
    assert failure.value.status == 422


def test_result_hash_must_belong_to_its_declared_commit(shared):
    first = context(shared)
    changed = publish(shared, "alice", payload(first, f"{PREFIX}/finding.md",
                      note(version=2, body="Revised evidence"), "revision-for-provenance"))
    assert changed.status_code == 200, changed.text
    current = next(d for d in context(shared)["documents"] if d["path"].endswith("/finding.md"))
    # Matching latest content does not establish that an older declared snapshot contained it.
    metadata = {"project_context": {"repository":shared["sync"].binding,"commit": first["sync"]["latest_commit"],
                "documents": [{"path": current["path"], "sha256": current["sha256"]}]}}
    with pytest.raises(SyncError, match="declared project commit") as failure:
        shared["sync"].check_inputs(metadata)
    assert failure.value.status == 422


def test_oversized_generated_artifact_cannot_poison_the_shared_branch(shared):
    first = context(shared)
    shared["engine"].put_artifact(dict(id="large-meeting", project_id=PROJECT, artifact_type="meeting",
        summary="Large local working record", decisions=[], proposed_tasks=[], questions=[]), "x" * 1_000_001)
    before = git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}")
    result = publish(shared, "alice", payload(first, f"{PREFIX}/small-note.md",
                      note(identifier="small-note"), "large-generated-record"))
    assert result.status_code == 422, result.text
    assert "limit" in result.text.lower() or "1 mb" in result.text.lower()
    assert git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}") == before
    assert context(shared)["sync"]["status"] == "synced"
    assert shared["engine"].get_artifact("large-meeting")["body"] == "x" * 1_000_001


def test_prospective_document_count_is_checked_before_writing(shared):
    first = context(shared)
    sync = shared["sync"]
    # The existing document map can include 1,000 records; a new generated record
    # must be rejected before any commit/push rather than only by the next refresh.
    documents = {f"{PREFIX}/record-{index}.md": {} for index in range(1000)}
    proposed = [{"path": f"{PREFIX}/new.md", "content": note(identifier="new"), "expected_sha256": None}]
    before = git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}")
    with pytest.raises(SyncError, match="1,000-document"):
        sync._validate_prospective(sync._cache(), first["sync"]["latest_commit"], documents, proposed)
    assert git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}") == before


def test_agent_identity_cannot_inject_commit_trailers(shared):
    first = context(shared)
    request = payload(first, f"{PREFIX}/index.md", "# Updated project index\n", "identity-injection")
    request["agent"] = "test-agent/1.0\rResearchRelay-Participant: forged"
    before = git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}")
    result = publish(shared, "alice", request)
    assert result.status_code == 422, result.text
    assert git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}") == before


def test_push_timeout_is_actionable_and_preserves_the_draft(shared, monkeypatch):
    first = context(shared)
    original = subprocess.run
    before = git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}")
    def timed_out(command, *args, **kwargs):
        if command[:3] == ["git", "-C", str(shared["sync"]._cache())] and "push" in command:
            raise subprocess.TimeoutExpired(command, 60, stderr=b"sensitive-private-server-detail")
        return original(command, *args, **kwargs)
    monkeypatch.setattr("researchrelay.sync.subprocess.run", timed_out)
    request = payload(first, f"{PREFIX}/timeout.md", note(identifier="timeout"), "push-timeout")
    result = publish(shared, "alice", request)
    assert result.status_code in {409, 503}, result.text
    assert result.json()["next_action"]
    assert "sensitive-private-server-detail" not in result.text
    assert shared["sync"].status()["status"] != "synced"
    assert git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}") == before
    with shared["engine"].connect() as db:
        row = db.execute("SELECT payload,response FROM publications WHERE request_id='push-timeout'").fetchone()
        assert "timeout.md" in row["payload"] and row["response"] is None


def test_misconfigured_repository_credentials_are_not_returned_to_participants(shared):
    shared["settings"].github_url = "https://alice:private-config-secret@github.com/example/project.git"
    response = shared["client"].get("/api/project", headers=headers("alice"))
    assert response.status_code in {200, 422, 503}, response.text
    assert "private-config-secret" not in response.text
    assert "alice:" not in response.text



def test_generated_artifact_credential_guard_matches_direct_publication(shared):
    first = context(shared)
    credential = "sk-" + "sensitivefakekey" * 3
    shared["engine"].put_artifact(dict(id="unsafe-working-notes", project_id=PROJECT, artifact_type="meeting",
        summary="Local scratch notes", decisions=[], proposed_tasks=[], questions=[]),
        "A worker accidentally printed a credential: " + credential)
    before = git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}")
    result = publish(shared, "alice", payload(first, f"{PREFIX}/safe-note.md",
                      note(identifier="safe-note"), "unsafe-generated-record"))
    assert result.status_code == 422, result.text
    assert "credential" in result.text.lower()
    assert credential not in result.text
    assert git(shared["remote"], "rev-parse", f"refs/heads/{BRANCH}") == before



def test_generated_decisions_separate_workflow_state_from_okf_lifecycle(shared):
    first = context(shared)
    decision = shared["engine"].request_decision(
        "Should this evidence alter the pilot design?", ["A source note is available"],
        ["Audit methods first", "Proceed to a pilot"], "Determines the next approved task", participant="human")
    opened = publish(shared, "alice", payload(first, f"{PREFIX}/decision-evidence.md",
                       note(identifier="decision-evidence"), "decision-open"))
    assert opened.status_code == 200, opened.text
    current = context(shared)
    artifact_path = f"{PREFIX}/_workflow/decision/{decision['id']}/v1.md"
    record = next(d for d in current["documents"] if d["path"] == artifact_path)
    assert record["metadata"]["decision_status"] == "open"
    assert record["metadata"]["status"] in {"draft", "stable", "deprecated"}
    shared["engine"].resolve_decision(decision["id"], "human", "Audit methods first", "Abstract-level evidence needs deeper appraisal.")
    resolved = publish(shared, "alice", payload(current, f"{PREFIX}/decision-follow-up.md",
                         note(identifier="decision-follow-up"), "decision-resolved"))
    assert resolved.status_code == 200, resolved.text
    latest = context(shared)
    updated = next(d for d in latest["documents"] if d["path"] == artifact_path.replace("v1.md", "v2.md"))
    assert updated["metadata"]["decision_status"] == "resolved"
    assert updated["metadata"]["status"] in {"draft", "stable", "deprecated"}
    assert shared["engine"].get_artifact(decision["id"])["metadata"]["status"] == "resolved"


@pytest.mark.parametrize("changes", [
    [("new.md","parent"),("new.md/child.md","child")],
    [("new.md/child.md","child"),("new.md","parent")],
])
def test_publication_rejects_file_directory_collisions(shared,changes):
    first=context(shared)
    draft=payload(first,f"{PREFIX}/placeholder.md",note(identifier="placeholder"),"file-directory")
    draft["changes"]=[{"path":f"{PREFIX}/{name}","content":note(identifier=identifier),"expected_sha256":None}
                      for name,identifier in changes]
    response=publish(shared,"alice",draft)
    assert response.status_code==422,response.text
    assert context(shared)["sync"]["latest_commit"]==first["sync"]["latest_commit"]


def test_prospective_total_size_limit_is_checked_before_push(shared):
    sync=shared["sync"]
    first=context(shared)
    fake={f"{PREFIX}/already-present.md":{"size_bytes":50_000_000,"content":""}}
    change=payload(first,f"{PREFIX}/overflow.md",note(identifier="overflow"),"total-limit")["changes"]
    with pytest.raises(SyncError,match="50 MB"):
        sync._validate_prospective(sync._cache(),first["sync"]["latest_commit"],fake,change)


def test_nontext_context_commit_is_a_validation_error(shared):
    first=context(shared)
    document=first["documents"][0]
    with pytest.raises(SyncError,match="exact commit"):
        shared["sync"].check_inputs({"project_context":{"repository":shared["sync"].binding,"commit":42,"documents":[{"path":document["path"],"sha256":document["sha256"]}]}})


def test_disabling_fallback_hides_inactive_cache_but_preserves_accepted_acknowledgment(shared,monkeypatch):
    ctx = context(shared)
    draft = payload(ctx,f"{PREFIX}/accepted-before-disable.md",note(identifier="before-disable"),"before-disable")
    accepted = publish(shared,"alice",draft)
    assert accepted.status_code == 200
    shared["settings"].github_url = None
    restarted = ProjectSync(shared["settings"],Engine(shared["engine"].db_path,PROJECT))
    def no_fetch():
        raise AssertionError("An explicitly disabled knowledge source must not fetch Git")
    monkeypatch.setattr(restarted,"_fetch",no_fetch)
    inactive = restarted.context("alice")
    assert inactive["repository"] is None and inactive["documents"] == []
    assert inactive["sync"]["status"] == "disabled" and inactive["sync"]["latest_commit"] is None
    assert restarted.publish("alice",**draft) == accepted.json()
    with pytest.raises(SyncError,match="no configured GitHub"):
        restarted.publish("alice",**{**draft,"request_id":"new-after-disable"})
    assert git(shared["remote"],"rev-parse",f"refs/heads/{BRANCH}") == accepted.json()["commit"]
