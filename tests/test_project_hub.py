"""Real local Git + HTTP-ASGI checks; no live GitHub/OAuth/model calls."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from researchrelay.api import create_app
from researchrelay.config import Settings
from researchrelay.knowledge import render_knowledge,parse_knowledge
from researchrelay.project_demo import DemoIdentity,LocalGitHubClient

@pytest.fixture
def app(tmp_path):
    return create_app(Settings(db_path=tmp_path/"default.db",repo_path=tmp_path/"record",
        project_demo=True,hub_path=tmp_path/"hub",mode="demo",github_url=None))

def login(app,name="alice"):
    client = TestClient(app)
    response = client.post("/api/hub/auth/demo",json=dict(login=name))
    assert response.status_code==200,response.text
    return client

def create(client,**overrides):
    payload = dict(request_id="new-repository",name="Agent literature",description="A shared evidence review",
        objectives="Compare human-agent coordination methods",collaborators=["bob"],mode="new_repository",
        repository="alice/literature",visibility="private",branch="",base_branch="",knowledge_path="")
    payload.update(overrides)
    response = client.post("/api/hub/projects",json=payload)
    assert response.status_code==201,response.text
    return response.json()

def publish(client,project,context,path,content,request_id,agent="manual/alice",expected=None):
    return client.post(project["url"]+"/api/project/publish",json=dict(
        expected_repository=context["repository"],base_commit=context["sync"]["latest_commit"],
        changes=[dict(path=path,content=content,expected_sha256=expected)],
        agent=agent,request_id=request_id,message="Record attributed literature contribution"))

def note(project,participant,id,body):
    return render_knowledge(dict(id=id,project_id=project["id"],artifact_type="source_note",
        responsible_participant=participant,producing_agent="manual/"+participant),body)

def test_three_workflows_preserve_repository_content(app):
    alice = login(app)
    first = create(alice)
    project = first["project"]
    context = alice.get(project["url"]+"/api/project/context")
    assert context.status_code==200,context.text
    docs = context.json()["documents"]
    assert len(docs)==8
    assert {Path(d["path"]).name for d in docs} >= {"README.md","AGENTS.md","PROJECT.md","TASKS.md","MEETINGS.md","KNOWLEDGE.md","DECISIONS.md"}
    root_readme = app.state.project_hub.client_factory(DemoIdentity(1,"alice")).read_file("alice","literature","README.md",first["project"]["commit"])
    assert root_readme==b"# literature\n"
    second = create(alice,request_id="new-branch",name="Branch review",mode="new_branch",
                    repository="alice/literature",branch="team-review",base_branch="main")
    assert second["project"]["branch"]=="team-review"
    third = create(alice,request_id="connect",name="Connected review",mode="connect",
                   repository="alice/literature",branch="main")
    assert third["project"]["knowledge_path"]!=project["knowledge_path"]
    assert len(alice.get("/api/hub/projects").json()["projects"])==3
    assert alice.get(project["url"]+"/api/tasks").json()==[]
    assert app.state.engine.list_tasks()==[]

def test_two_users_publish_review_and_reject_stale_updates(app):
    alice,bob = login(app),login(app,"bob")
    project = create(alice)["project"]
    joined = create(bob,request_id="join-bob",name="Join existing",mode="connect",repository=project["repository"],
                    branch=project["branch"],knowledge_path=project["knowledge_path"],initialize=False)["project"]
    assert joined["id"]==project["id"]
    alice_context = alice.get(project["url"]+"/api/project/context").json()
    path = project["knowledge_path"]+"/sources/finding.md"
    content = note(project,"alice","finding-one","# Literature finding\n\nA provenance-bearing initial finding.")
    result = publish(alice,project,alice_context,path,content,"finding-one")
    assert result.status_code==200,result.text
    repeated = publish(alice,project,alice_context,path,content,"finding-one")
    assert repeated.json()["commit"]==result.json()["commit"]
    bob_context = bob.get(project["url"]+"/api/project/context").json()
    original = next(d for d in bob_context["documents"] if d["path"]==path)
    assert original["metadata"]["responsible_participant"]=="alice"
    review = note(project,"bob","review-one","# Review\n\nAdd the study setting and limitations before interpreting this finding.")
    reviewed = publish(bob,project,bob_context,project["knowledge_path"]+"/reviews/review.md",review,"review-one",agent="manual/bob")
    assert reviewed.status_code==200,reviewed.text
    # Another participant changed the same file after Alice's pinned context.
    revision = note(project,"bob","finding-one","# Extended evidence\n\nStudy limitations documented.")
    extended = publish(bob,project,bob_context,path,revision,"extend-one",agent="manual/bob",expected=original["sha256"])
    assert extended.status_code==200,extended.text
    stale = publish(alice,project,bob_context,path,note(project,"alice","finding-one","# Stale draft"),"stale-one",expected=original["sha256"])
    assert stale.status_code==409,stale.text
    assert path in stale.json()["paths"]
    final = alice.get(project["url"]+"/api/project/context").json()
    assert next(d["content"] for d in final["documents"] if d["path"]==path)==revision
    assert any(d["path"].endswith("/reviews/review.md") for d in final["documents"])
    replay = create(alice)
    assert replay["project"]["id"]==project["id"]
    history = alice.post("/api/hub/projects/"+project["id"]+"/refresh").json()
    assert len(history["commits"])>=4

def test_permission_auth_and_cross_origin_failures(app):
    anonymous = TestClient(app)
    assert anonymous.post("/api/hub/projects",json={}).status_code in {401,422}
    assert anonymous.get("/api/hub/repositories").status_code==401
    alice = login(app)
    project = create(alice)["project"]
    reader = login(app,"reader")
    assert reader.get(project["url"]+"/api/project/context").status_code==200
    assert reader.post(project["url"]+"/api/tasks",json=dict(title="No",owner="reader",acceptance_criteria=["No"])).status_code==403
    assert reader.post("/api/hub/projects",json=dict(request_id="forbidden",name="No",mode="new_repository",repository="reader/no")).status_code==403
    assert alice.post("/api/hub/auth/logout",headers={"Origin":"https://untrusted.example"}).status_code==403
    assert alice.post("/api/hub/auth/logout").status_code==200
    assert alice.get(project["url"]+"/api/project/context").status_code==401

def test_branch_collision_and_exact_request_recovery(app):
    alice = login(app)
    project = create(alice)["project"]
    payload = dict(request_id="branch-collision",name="Collision",mode="new_branch",
                   repository=project["repository"],branch="main",base_branch="main")
    response = alice.post("/api/hub/projects",json=payload)
    assert response.status_code in {409,422}
    assert response.json()["operation"]["id"]=="branch-collision"
    operation = alice.get("/api/hub/operations/branch-collision").json()["operation"]
    assert operation["status"] in {"failed","needs_reconciliation"}
    # Reusing a successful request ID for another payload never creates another repository.
    response = alice.post("/api/hub/projects",json=dict(request_id="new-repository",name="Wrong",mode="new_repository",repository="alice/wrong"))
    assert response.status_code==409
    assert len(alice.get("/api/hub/repositories").json()["repositories"])==1

def test_settings_recorded_in_git_and_project_state_survives_restart(app):
    alice = login(app)
    project = create(alice)["project"]
    edited = alice.patch("/api/hub/projects/"+project["id"],json=dict(name="Updated review",objectives="Track coordination evidence"))
    assert edited.status_code==200,edited.text
    current = alice.get(project["url"]+"/api/project/context").json()
    doc = next(d for d in current["documents"] if d["path"].endswith("/PROJECT.md"))
    assert doc["metadata"]["title"]=="Updated review"
    assert doc["metadata"]["responsible_participant"]=="alice"
    alice.put(project["url"]+"/api/participants/me/agent",json={"provider":"vscode"}).raise_for_status()
    recreated = create_app(app.state.settings)
    second = TestClient(recreated)
    second.cookies.update(alice.cookies)
    assert second.get("/api/hub/projects").json()["projects"][0]["name"]=="Updated review"
    assert second.get(project["url"]+"/api/participants/me/agent").json()["profile"]["provider"]=="vscode"

def test_unconfigured_oauth_is_actionable_and_legacy_remains_available(tmp_path):
    app = create_app(Settings(db_path=tmp_path/"state.db",repo_path=tmp_path/"record",github_url=None,hub_path=tmp_path/"hub"))
    client = TestClient(app)
    assert client.get("/api/hub/status").json()["configured"] is False
    response = client.get("/api/hub/auth/login",follow_redirects=False)
    assert response.status_code==503
    assert "administrator" in response.json()["next_action"]
    assert client.get("/api/tasks").status_code==200
    assert client.post("/api/hub/auth/demo",json={"login":"alice"}).status_code==404

def test_managed_task_identity_and_isolation(app):
    alice,bob = login(app),login(app,"bob")
    project = create(alice)["project"]
    response = alice.post(project["url"]+"/api/tasks",json=dict(title="Review coordination methods",owner="alice",objective="Review evidence",acceptance_criteria=["Cite verified sources"]))
    assert response.status_code==201,response.text
    task = response.json()
    assert bob.post(project["url"]+"/api/tasks/"+task["id"]+"/claim",json=dict(worker_id="bob")).status_code==403
    assert alice.post(project["url"]+"/api/tasks/"+task["id"]+"/claim",json=dict(worker_id="alice")).status_code==200
    second = create(alice,request_id="second-project",name="Other",repository="alice/other")["project"]
    assert alice.get(second["url"]+"/api/tasks").json()==[]
    assert alice.get("/api/tasks").json()==[]
