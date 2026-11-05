"""Provisioning state-machine tests; in-memory API model, no live GitHub writes."""
from copy import deepcopy
import hashlib
import json

import pytest

from researchrelay.github_client import GitHubError
from researchrelay.knowledge import parse_knowledge, validate_bundle
from researchrelay.project_provisioning import ProjectProvisioner, read_existing_project
from researchrelay.project_templates import PROJECT_FILES, build_project_files


class MemoryGitHub:
    def __init__(self):
        self.repositories = {}
        self.calls = []
        self.sequence = 0
        self.push = True
        self.authenticated = True
        self.fail_create_ack = False
        self.fail_branch_ack = False
        self.fail_commit_ack = False
        self.before_commit = None

    def get_user(self):
        if not self.authenticated:
            raise GitHubError("Sign in again.",401,kind="authentication",next_action="Sign in using your own GitHub account.")
        return {"login":"alice","id":1}

    def _commit(self,entry,branch,files):
        self.sequence += 1
        sha = hashlib.sha1((str(self.sequence)+json.dumps({name:value.decode() for name,value in files.items()},sort_keys=True)).encode()).hexdigest()
        entry["commits"][sha] = deepcopy(files)
        entry["branches"][branch] = sha
        return sha

    def create_repository(self,name,*,owner=None,visibility="private",description="",auto_init=True):
        full_name = (owner or "alice")+"/"+name
        self.calls.append(("create_repository",full_name))
        if full_name in self.repositories:
            raise GitHubError("Repository exists.",409,kind="conflict")
        meta = {"full_name":full_name,"name":name,"owner":{"login":owner or "alice"},"default_branch":"main",
                "visibility":visibility,"private":visibility=="private","description":description,
                "clone_url":"https://github.com/"+full_name+".git","permissions":{"push":True,"admin":True,"pull":True}}
        entry = {"meta":meta,"branches":{},"commits":{}}
        self.repositories[full_name] = entry
        if auto_init:
            self._commit(entry,"main",{"README.md":("# "+name+"\n").encode()})
        if self.fail_create_ack:
            self.fail_create_ack = False
            raise GitHubError("Creation response was interrupted.",503,kind="unavailable")
        return self.get_repository(*(full_name.split("/")))

    def get_repository(self,owner,repo):
        full_name = owner+"/"+repo
        if full_name not in self.repositories:
            raise GitHubError("Repository not found.",404,kind="not_found")
        meta = deepcopy(self.repositories[full_name]["meta"])
        meta["permissions"] = {"pull":True,"push":self.push,"admin":self.push}
        return meta

    def get_head(self,owner,repo,branch):
        try:
            return self.repositories[owner+"/"+repo]["branches"][branch]
        except KeyError:
            raise GitHubError("Branch not found.",404,kind="not_found") from None

    def create_branch(self,owner,repo,branch,*,from_branch=None,sha=None):
        self.calls.append(("create_branch",owner+"/"+repo,branch))
        entry = self.repositories[owner+"/"+repo]
        if branch in entry["branches"]:
            raise GitHubError("Branch exists.",409,kind="conflict")
        sha = sha or entry["branches"][from_branch or "main"]
        entry["branches"][branch] = sha
        if self.fail_branch_ack:
            self.fail_branch_ack = False
            raise GitHubError("Branch response was interrupted.",503,kind="unavailable")
        return {"ref":"refs/heads/"+branch,"object":{"sha":sha}}

    def read_file(self,owner,repo,path,ref):
        entry = self.repositories[owner+"/"+repo]
        sha = entry["branches"].get(ref,ref)
        return entry["commits"][sha].get(path)

    def commit_files(self,owner,repo,branch,files,*,expected_head,message,expected_files=None,max_attempts=3):
        self.calls.append(("commit_files",owner+"/"+repo,branch))
        assert expected_files is not None and set(expected_files)==set(files)
        assert max_attempts==3
        entry = self.repositories[owner+"/"+repo]
        if self.before_commit:
            callback,self.before_commit = self.before_commit,None
            callback(entry,branch)
        head = entry["branches"][branch]
        current = deepcopy(entry["commits"][head])
        conflicting = [path for path,wanted in expected_files.items()
                       if (hashlib.sha256(current[path]).hexdigest() if path in current else None)!=wanted]
        if conflicting:
            raise GitHubError("Touched files changed.",409,kind="conflict",paths=conflicting,
                              next_action="Compare the files and explicitly reconcile the draft.")
        current.update({path:value.encode() if isinstance(value,str) else value for path,value in files.items()})
        commit = self._commit(entry,branch,current)
        if self.fail_commit_ack:
            self.fail_commit_ack = False
            raise GitHubError("Commit acknowledgment was interrupted.",503,kind="unavailable")
        return {"commit":commit,"previous_head":head,"branch":branch,"repository":owner+"/"+repo}


def operation(mode="new_repository",**changes):
    spec = dict(mode=mode,name="Coordination evidence",description="Study collaborative scientific work",objectives=["Review evidence"],
                collaborators=["bob"],repository="alice/evidence",branch="",base_branch="",knowledge_path="",visibility="private")
    spec.update(changes)
    return {"id":"operation-1","actor":"alice","created_at":"2026-11-05T00:00:00Z","input":spec,"steps":{},"state":{}}


def runner(client):
    saved = []
    return ProjectProvisioner(client,lambda item:saved.append(deepcopy(item))),saved


def files_at(client,result):
    entry = client.repositories[result["repository"]["full_name"]]
    return entry["commits"][result["commit"]]


def test_seven_portable_templates_and_index_are_deterministic_and_honest(tmp_path):
    op = operation()
    op["project_id"] = "evidence-project"
    first = build_project_files(op)
    assert first==build_project_files(op)
    assert {path.rsplit("/",1)[-1] for path in first}==set(PROJECT_FILES)|{"index.md"}
    for name,content in first.items():
        target = tmp_path/name
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(content,encoding="utf-8")
        metadata,_ = parse_knowledge(content,path=name)
        if not metadata.get("reserved"):
            assert metadata["format_status"]=="provisional" and metadata["status"]=="draft"
            assert metadata["provenance"]["scientific_approval_recorded"] is False
            assert metadata["sources"]==[] and "verified" not in metadata
    report = validate_bundle(tmp_path/"projects/evidence-project","evidence-project")
    assert report["count"]==8 and not report["broken_links"]
    project,_ = parse_knowledge(first["projects/evidence-project/PROJECT.md"])
    assert project["research_objectives"]=="Review evidence"
    assert project["title"]=="Coordination evidence"


@pytest.mark.parametrize("mode",["new_repository","new_branch","connect"])
def test_three_modes_use_one_atomic_initialization_and_preserve_existing_files(mode):
    client = MemoryGitHub()
    if mode!="new_repository":
        client.create_repository("evidence")
    op = operation(mode,branch="review" if mode=="new_branch" else "",base_branch="main")
    provisioner,saved = runner(client)
    result = provisioner.run(op)
    assert op["state"]=="completed" and result["status"]=="ready"
    assert result["branch"]==("review" if mode=="new_branch" else "main")
    assert result["knowledge_path"].startswith("projects/")
    current = files_at(client,result)
    assert current["README.md"]==b"# evidence\n"
    assert len([path for path in current if path.startswith(result["knowledge_path"]+"/")])==8
    assert len([call for call in client.calls if call[0]=="commit_files"])==1
    pending = next(item for item in saved if item["steps"].get("initialization",{}).get("pending"))
    assert pending["steps"]["initialization"]["expected_head"]
    before = list(client.calls)
    assert provisioner.run(deepcopy(op))==result
    assert client.calls==before


def test_read_only_connect_discovers_identity_without_requiring_write_or_mutating():
    client = MemoryGitHub()
    initial,_ = runner(client)
    original = initial.run(operation())
    client.push = False
    calls = list(client.calls)
    op = operation("connect",initialize=False,knowledge_path=original["knowledge_path"],name="Join existing")
    op["id"] = "join-operation"
    result = ProjectProvisioner(client).run(op)
    assert result["project_id"]==original["project_id"]
    assert result["name"]=="Coordination evidence"
    assert not result["initialized"] and client.calls==calls
    identity = read_existing_project(client,"alice","evidence","main",original["knowledge_path"])
    assert identity["metadata"]["collaborators"]==["bob"]


@pytest.mark.parametrize("failure",["authentication","permission"])
def test_authentication_and_write_permission_failures_are_durable_and_make_no_remote_writes(failure):
    client = MemoryGitHub()
    client.create_repository("evidence")
    client.calls.clear()
    client.authenticated = failure!="authentication"
    client.push = failure!="permission"
    provisioner,saved = runner(client)
    op = operation("connect")
    with pytest.raises(GitHubError) as caught:
        provisioner.run(op)
    assert caught.value.status in {401,403}
    assert op["state"]=="failed" and saved[-1]["error"]["kind"]==failure
    assert client.calls==[]


def test_existing_project_files_are_never_overwritten_or_partially_replaced():
    client = MemoryGitHub()
    client.create_repository("evidence")
    entry = client.repositories["alice/evidence"]
    head = client.get_head("alice","evidence","main")
    current = deepcopy(entry["commits"][head]);current["projects/chosen/TASKS.md"] = b"Existing human work"
    client._commit(entry,"main",current)
    before = client.get_head("alice","evidence","main")
    op = operation("connect",knowledge_path="projects/chosen")
    with pytest.raises(GitHubError) as caught:
        ProjectProvisioner(client).run(op)
    assert caught.value.kind=="conflict" and caught.value.paths==["projects/chosen/TASKS.md"]
    assert client.get_head("alice","evidence","main")==before
    assert entry["commits"][before]["projects/chosen/TASKS.md"]==b"Existing human work"
    assert not any(call[0]=="commit_files" for call in client.calls)


def test_commit_ack_loss_reconciles_by_operation_marker_without_another_commit():
    client = MemoryGitHub();client.fail_commit_ack = True
    provisioner,saved = runner(client)
    op = operation()
    with pytest.raises(GitHubError,match="acknowledgment"):
        provisioner.run(op)
    accepted_head = client.get_head("alice","evidence","main")
    recovered = provisioner.run(deepcopy(saved[-1]))
    assert recovered["reconciled"] and recovered["commit"]==accepted_head
    assert recovered["initialization_commit"] is None
    assert len([call for call in client.calls if call[0]=="commit_files"])==1


def test_lost_repository_creation_ack_preserves_resource_and_requires_explicit_reconciliation():
    client = MemoryGitHub();client.fail_create_ack = True
    provisioner,saved = runner(client)
    with pytest.raises(GitHubError):
        provisioner.run(operation())
    with pytest.raises(GitHubError) as caught:
        provisioner.run(deepcopy(saved[-1]))
    assert caught.value.kind=="needs_reconciliation"
    assert len(client.repositories)==1
    assert len([call for call in client.calls if call[0]=="create_repository"])==1
    assert not any(call[0]=="commit_files" for call in client.calls)


def test_lost_branch_creation_ack_reuses_the_exact_intended_base_without_duplicate_ref():
    client = MemoryGitHub();client.create_repository("evidence");client.fail_branch_ack = True
    provisioner,saved = runner(client)
    with pytest.raises(GitHubError):
        provisioner.run(operation("new_branch",branch="review",base_branch="main"))
    result = provisioner.run(deepcopy(saved[-1]))
    assert result["branch_creation_reconciled"] and not result["created_branch"]
    assert len([call for call in client.calls if call[0]=="create_branch"])==1


@pytest.mark.parametrize("touched",[False,True])
def test_concurrent_changes_preserve_unrelated_work_and_conflict_on_template_paths(touched):
    client = MemoryGitHub()
    op = operation(knowledge_path="projects/chosen")
    def race(entry,branch):
        files = deepcopy(entry["commits"][entry["branches"][branch]])
        files["projects/chosen/PROJECT.md" if touched else "other-participant.md"] = b"Concurrent contribution"
        client._commit(entry,branch,files)
    client.before_commit = race
    if touched:
        with pytest.raises(GitHubError) as caught:
            ProjectProvisioner(client).run(op)
        assert caught.value.kind=="conflict"
        files = client.repositories["alice/evidence"]["commits"][client.get_head("alice","evidence","main")]
        assert files["projects/chosen/PROJECT.md"]==b"Concurrent contribution"
        assert "projects/chosen/TASKS.md" not in files
    else:
        result = ProjectProvisioner(client).run(op)
        assert files_at(client,result)["other-participant.md"]==b"Concurrent contribution"


def test_changed_operation_input_cannot_retarget_an_interrupted_attempt():
    client = MemoryGitHub();client.fail_commit_ack = True
    provisioner,saved = runner(client)
    with pytest.raises(GitHubError):
        provisioner.run(operation())
    retry = deepcopy(saved[-1]);retry["input"]["repository"] = "alice/another"
    with pytest.raises(GitHubError,match="changed configuration"):
        provisioner.run(retry)
    assert "alice/another" not in client.repositories


@pytest.mark.parametrize("path",[".","../outside","/absolute","projects/.git","projects\\windows"])
def test_invalid_knowledge_paths_fail_before_remote_creation(path):
    client = MemoryGitHub()
    with pytest.raises(GitHubError) as caught:
        ProjectProvisioner(client).run(operation(knowledge_path=path))
    assert caught.value.status==422
    assert client.repositories=={}
