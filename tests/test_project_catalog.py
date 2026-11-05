"""Catalog concurrency/recovery/privacy with a deterministic API stub; no Git."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import threading

import pytest

from researchrelay.config import Settings
from researchrelay.github_client import GitHubError
from researchrelay.project_hub import HubError, ProjectHub


@dataclass(frozen=True)
class Identity:
    github_user_id: int
    login: str


ALICE = Identity(1,"alice")
BOB = Identity(2,"bob")


class CatalogClient:
    def __init__(self):
        self.denied = {}

    def get_repository(self,owner,repo):
        status = self.denied.get(owner+"/"+repo)
        if status:
            raise GitHubError("Repository access is unavailable.",status,kind="permission")
        return {"full_name":owner+"/"+repo,"default_branch":"main","private":True,
                "clone_url":"https://github.com/"+owner+"/"+repo+".git",
                "permissions":{"pull":True,"push":True,"admin":True}}


@pytest.fixture
def catalog(tmp_path):
    settings = Settings(db_path=tmp_path/"default.db",repo_path=tmp_path/"record",hub_path=tmp_path/"hub",
                        mode="demo",github_url=None)
    hub = ProjectHub(settings)
    client = CatalogClient()
    hub.client_factory = lambda identity:client
    return hub,client


def payload(request_id="create-one",**changes):
    value = dict(request_id=request_id,name="Coordination evidence",description="A private scientific project",objectives="Compare handoffs",
                 collaborators=["bob"],mode="new_repository",repository="alice/shared",branch="main",knowledge_path="")
    value.update(changes)
    return value


def project_data(project_id="shared-project",branch="main",prefix="projects/shared-project",**changes):
    value = dict(id=project_id,name="Sensitive research title",description="Research context",objectives="Retain provenance",collaborators=[],
                 repository="alice/shared",branch=branch,knowledge_path=prefix,clone_url="https://github.com/alice/shared.git",
                 commit="a"*40,created_by="alice",created_at="2026-11-05T00:00:00Z")
    value.update(changes)
    return value


def install_provisioner(monkeypatch,*,blocked_id=None,entered=None,release=None):
    calls = []
    guard = threading.Lock()
    class StubProvisioner:
        def __init__(self,client,checkpoint):
            self.client,self.checkpoint = client,checkpoint
        def run(self,operation):
            if operation.get("state")=="completed" and operation.get("result"):
                return deepcopy(operation["result"])
            with guard:
                calls.append(operation["id"])
            operation["steps"]["remote_intent_saved"] = True
            self.checkpoint(operation)
            if operation["id"]==blocked_id:
                entered.set()
                assert release.wait(5), "Test failed to release the intentionally slow provider"
            spec = operation["input"]
            owner,repo = spec["repository"].split("/")
            result = dict(repository=self.client.get_repository(owner,repo),branch=spec.get("branch") or "main",
                          knowledge_path=spec.get("knowledge_path") or "projects/"+operation["project_id"],
                          project_id=operation["project_id"],commit=hashlib.sha1(operation["id"].encode()).hexdigest())
            operation.update(state="completed",result=result)
            operation["steps"]["remote_commit_acknowledged"] = True
            self.checkpoint(operation)
            return deepcopy(result)
    monkeypatch.setattr("researchrelay.project_provisioning.ProjectProvisioner",StubProvisioner)
    return calls


def test_same_request_is_provisioned_once_and_completed_replay_survives_restart(catalog,monkeypatch):
    hub,client = catalog
    entered,release,second_started = threading.Event(),threading.Event(),threading.Event()
    calls = install_provisioner(monkeypatch,blocked_id="create-one",entered=entered,release=release)
    def second():
        second_started.set()
        return hub.create(ALICE,payload())
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(hub.create,ALICE,payload())
        assert entered.wait(3)
        pending = hub.operation("create-one",ALICE)
        assert pending["steps"]["remote_intent_saved"]
        other = pool.submit(second)
        assert second_started.wait(3)
        try:
            assert calls==["create-one"]
        finally:
            release.set()
        a,b = first.result(timeout=3),other.result(timeout=3)
    assert a["project"]["id"]==b["project"]["id"]
    with hub.tx() as db:
        assert db.execute("SELECT count(*) FROM projects").fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM operations").fetchone()[0]==1
    recreated = ProjectHub(hub.settings)
    recreated.client_factory = lambda identity:client
    replay = recreated.create(ALICE,payload())
    assert replay["project"]["id"]==a["project"]["id"]
    assert replay["operation"]["status"]=="completed"
    assert calls==["create-one"]


def test_slow_operation_does_not_block_cached_project_or_different_creation(catalog,monkeypatch):
    hub,_ = catalog
    existing = hub.register(ALICE,project_data())
    cached = hub.child(existing["id"])
    cached.state.engine.create_task(id="ongoing",owner="alice",acceptance_criteria=["Keep working"])
    entered,release = threading.Event(),threading.Event()
    calls = install_provisioner(monkeypatch,blocked_id="slow",entered=entered,release=release)
    with ThreadPoolExecutor(max_workers=3) as pool:
        slow = pool.submit(hub.create,ALICE,payload("slow",repository="alice/slow"))
        assert entered.wait(3)
        try:
            lookup = pool.submit(hub.child,existing["id"])
            assert lookup.result(timeout=2) is cached
            fast = pool.submit(hub.create,ALICE,payload("fast",repository="alice/fast"))
            result = fast.result(timeout=3)
            assert result["project"]["repository"]=="alice/fast"
            assert not slow.done()
            assert cached.state.engine.get_task("ongoing")["status"]=="queued"
        finally:
            release.set()
        assert slow.result(timeout=3)["project"]["repository"]=="alice/slow"
    assert sorted(calls)==["fast","slow"]


def test_concurrent_same_binding_registration_reuses_one_project_and_engine(catalog):
    hub,_ = catalog
    barrier = threading.Barrier(2)
    def join(identity,identifier):
        barrier.wait(timeout=3)
        return hub.register(identity,project_data(identifier,name="Candidate "+identity.login))
    with ThreadPoolExecutor(max_workers=2) as pool:
        alice = pool.submit(join,ALICE,"alice-candidate")
        bob = pool.submit(join,BOB,"bob-candidate")
        first,second = alice.result(timeout=3),bob.result(timeout=3)
    assert first==second
    assert hub.child(first["id"]) is hub.child(second["id"])
    with hub.tx() as db:
        assert db.execute("SELECT count(*) FROM projects").fetchone()[0]==1
        assert db.execute("SELECT count(*) FROM memberships").fetchone()[0]==2
    assert hub.list_projects(ALICE)[0]["id"]==hub.list_projects(BOB)[0]["id"]


@pytest.mark.parametrize(("branch","prefix"),[("review","projects/shared-project"),("main","projects/other-folder")])
def test_external_id_collision_preserves_separate_coordinators_and_pinned_versions(catalog,branch,prefix):
    hub,_ = catalog
    first = hub.register(ALICE,project_data())
    second = hub.register(BOB,project_data(branch=branch,prefix=prefix,name="Another binding"))
    assert first["id"]!=second["id"]
    assert second["artifact_project_id"]==first["id"]
    assert hub.record(first["id"])["name"]=="Sensitive research title"
    assert hub.record(second["id"])["branch"]==branch
    a,b = hub.child(first["id"]).state.engine,hub.child(second["id"]).state.engine
    assert a.project_id==b.project_id=="shared-project"
    assert a.db_path!=b.db_path
    for engine,body in ((a,"First binding source"),(b,"Other binding source")):
        engine.put_artifact(dict(id="source",project_id=engine.project_id,artifact_type="task",owner="alice"),body)
        engine.create_task(id="dependent",owner="alice",input_refs=[{"id":"source","version":1}],acceptance_criteria=["Read pinned source"])
    metadata = dict(a.get_artifact("source",1)["metadata"],version=2)
    a.put_artifact(metadata,"First binding revised")
    assert a.get_artifact("source",1)["body"]=="First binding source"
    assert b.get_artifact("source",1)["body"]=="Other binding source"
    assert a.get_task("dependent")["stale_inputs"]
    assert not b.get_task("dependent")["stale_inputs"]
    assert b.get_task("dependent")["input_refs"]==[{"id":"source","version":1}]


def test_operation_ownership_hides_other_users_private_request_and_rejects_reuse(catalog,monkeypatch):
    hub,_ = catalog
    calls = install_provisioner(monkeypatch)
    sensitive = payload(name="Confidential unpublished hypothesis")
    created = hub.create(ALICE,sensitive)
    with pytest.raises(HubError) as missing:
        hub.operation("create-one",BOB)
    assert missing.value.status==404 and missing.value.operation is None
    with pytest.raises(HubError) as collision:
        hub.create(BOB,payload(name="Different project"))
    assert collision.value.status==409 and collision.value.operation is None
    assert "Confidential" not in str(collision.value)
    assert hub.list_projects(BOB)==[]
    assert hub.operation("create-one",ALICE)["project"]["id"]==created["project"]["id"]
    assert calls==["create-one"]


@pytest.mark.parametrize("status",[403,404])
def test_revoked_repository_access_hides_private_project_metadata(catalog,status):
    hub,client = catalog
    hub.register(ALICE,project_data())
    assert len(hub.list_projects(ALICE))==1
    client.denied["alice/shared"] = status
    visible = hub.list_projects(ALICE)
    assert visible==[] and "Sensitive research title" not in json.dumps(visible)


def test_fine_grained_pat_is_rejected_before_operation_persistence_or_shared_files(catalog,monkeypatch):
    hub,_ = catalog
    calls = install_provisioner(monkeypatch)
    secret = "github_pat_"+"A1_b"*12
    with pytest.raises(HubError) as caught:
        hub.create(ALICE,payload(description="Accidental token: "+secret))
    assert caught.value.status==422 and secret not in str(caught.value)
    assert calls==[]
    with hub.tx() as db:
        assert db.execute("SELECT count(*) FROM operations").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM projects").fetchone()[0]==0
    assert all(secret.encode() not in path.read_bytes() for path in hub.root.rglob("*") if path.is_file())


def test_remote_success_then_local_registration_failure_recovers_without_reprovisioning(catalog,monkeypatch):
    hub,client = catalog
    calls = install_provisioner(monkeypatch)
    original = hub.register
    def unavailable(*args,**kwargs):
        raise HubError("Local registration was interrupted.",503)
    monkeypatch.setattr(hub,"register",unavailable)
    with pytest.raises(HubError,match="registration was interrupted"):
        hub.create(ALICE,payload())
    saved = hub.operation("create-one",ALICE)
    assert saved["status"]=="failed" and saved["state"]=="completed"
    assert saved["steps"]["remote_commit_acknowledged"]
    recreated = ProjectHub(hub.settings)
    recreated.client_factory = lambda identity:client
    recovered = recreated.create(ALICE,payload())
    assert recovered["operation"]["status"]=="completed"
    assert calls==["create-one"]
    with recreated.tx() as db:
        assert db.execute("SELECT count(*) FROM projects").fetchone()[0]==1
