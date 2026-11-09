"""Shared defaults and durable custom bindings; all Git transport stays local."""
import subprocess

import pytest
from fastapi.testclient import TestClient

from researchrelay.api import create_app
from github_fixture import authenticated_app
from researchrelay.config import Settings
from researchrelay.engine import Engine
from researchrelay.knowledge import render_knowledge
from researchrelay.sync import ProjectSync, SyncError

CANONICAL_URL = "git@github.com:midatm1234/ResearchRelay.git"
DEFAULT_BRANCH = "SRTD_DT_test"
PROJECT = "agentic-collaboration"


@pytest.fixture(autouse=True)
def forbid_external_git(monkeypatch):
    original = subprocess.run
    def local_only(command, *args, **kwargs):
        if isinstance(command, (list, tuple)) and command and command[0] == "git":
            assert not any(isinstance(argument, str) and argument.startswith(
                ("git@github.com:", "https://github.com/", "ssh://git@github.com"))
                for argument in command[1:]), "These tests must never contact GitHub"
        return original(command, *args, **kwargs)
    monkeypatch.setattr(subprocess, "run", local_only)


def settings_at(tmp_path, **changes):
    return Settings(db_path=tmp_path / "state.db", repo_path=tmp_path / "coordinator" / "record", **changes)


def clear_default_overrides(monkeypatch):
    for name in ("RESEARCHRELAY_MODE", "RESEARCHRELAY_GITHUB_URL", "RESEARCHRELAY_GITHUB_BRANCH",
                 "RESEARCHRELAY_KNOWLEDGE_PATH", "RESEARCHRELAY_PROJECT"):
        monkeypatch.delenv(name, raising=False)


def git(path, *arguments):
    return subprocess.check_output(["git", "-C", str(path), "-c", "core.longpaths=true", *arguments],
                                   text=True, encoding="utf-8").strip()


def seed_remote(tmp_path, name, branch, prefix="team/knowledge", include_note=False):
    remote = tmp_path / (name + ".git")
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    seed = tmp_path / (name + "-seed")
    subprocess.run(["git", "init", "-b", branch, str(seed)], check=True, capture_output=True)
    (seed / "README.md").write_text("# " + name + "\n", encoding="utf-8")
    if include_note:
        target = seed / prefix / "source.md"
        target.parent.mkdir(parents=True)
        target.write_text(note("human", "existing-source"), encoding="utf-8")
    git(seed, "add", ".")
    git(seed, "-c", "user.name=Shared default tests", "-c", "user.email=tests@localhost.invalid",
        "commit", "-m", "Seed committed repository")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "origin", branch)
    return remote, git(seed, "rev-parse", "HEAD")


def note(participant="alice", identifier="initial-finding"):
    return render_knowledge(dict(id=identifier, project_id=PROJECT, artifact_type="source_note", type="Reference",
        responsible_participant=participant, producing_agent="shared-default-test/1.0",
        sources=[{"id": "prov", "resource": "https://www.w3.org/TR/2013/REC-prov-dm-20130430/"}]),
        "# Shared finding\n\nA portable attributed record used for local transport verification.\n")


def headers(participant="human"):
    return {"Authorization": "Bearer " + ("github-human-test-token" if participant == "human" else "github-alice-test-token")}


def test_fresh_install_defaults_to_the_shared_researchrelay_project(tmp_path, monkeypatch):
    clear_default_overrides(monkeypatch)
    settings = settings_at(tmp_path)
    sync = ProjectSync(settings, Engine(settings.db_path, settings.project_id))
    assert settings.mode == "live"
    assert settings.github_url == CANONICAL_URL
    assert settings.github_branch == DEFAULT_BRANCH
    assert settings.project_id == PROJECT
    assert sync.binding == {"url": CANONICAL_URL, "branch": DEFAULT_BRANCH,
                            "knowledge_path": "projects/agentic-collaboration"}
    assert sync.public()["sync"]["status"] == "pending"
    assert sync.public()["sync"]["latest_commit"] is None


def test_explicit_blank_disables_the_environment_fallback(tmp_path, monkeypatch):
    clear_default_overrides(monkeypatch)
    monkeypatch.setenv("RESEARCHRELAY_GITHUB_URL", "")
    settings = settings_at(tmp_path)
    sync = ProjectSync(settings, Engine(settings.db_path, settings.project_id))
    assert settings.mode == "live"
    assert settings.github_url is None
    assert sync.binding is None
    assert sync.context()["sync"]["status"] == "disabled"
    assert sync.context()["documents"] == []


def test_custom_environment_repository_branch_and_prefix_are_respected(tmp_path, monkeypatch):
    clear_default_overrides(monkeypatch)
    monkeypatch.setenv("RESEARCHRELAY_GITHUB_URL", "https://github.com/research-team/shared-science.git")
    monkeypatch.setenv("RESEARCHRELAY_GITHUB_BRANCH", "reviews/current")
    monkeypatch.setenv("RESEARCHRELAY_KNOWLEDGE_PATH", "knowledge/team-project")
    monkeypatch.setenv("RESEARCHRELAY_PROJECT", "team-project")
    settings = settings_at(tmp_path)
    sync = ProjectSync(settings, Engine(settings.db_path, settings.project_id))
    assert sync.public()["repository"] == {"url": "https://github.com/research-team/shared-science.git",
        "branch": "reviews/current", "knowledge_path": "knowledge/team-project"}


def test_omitted_knowledge_prefix_uses_the_actual_project_id(tmp_path, monkeypatch):
    clear_default_overrides(monkeypatch)
    monkeypatch.setenv("RESEARCHRELAY_PROJECT", "different-team-project")
    settings = settings_at(tmp_path)
    sync = ProjectSync(settings, Engine(settings.db_path, settings.project_id))
    assert sync.binding["knowledge_path"] == "projects/different-team-project"
    assert sync.binding["url"] == CANONICAL_URL


@pytest.mark.parametrize("fallback", ["default", "blank"])
def test_saved_custom_binding_survives_restart_and_environment_fallback(tmp_path, monkeypatch, fallback):
    custom = {"url": "git@github.com:research-team/custom-project.git", "branch": "team-review",
              "knowledge_path": "knowledge/custom-project"}
    settings = settings_at(tmp_path, mode="live", github_url=None)
    engine = Engine(settings.db_path, PROJECT)
    engine.create_task(id="preserve-existing-work", owner="alice", acceptance_criteria=["Retain task state"])
    sync = ProjectSync(settings, engine)
    def inaccessible():
        raise SyncError("Repository authentication is not configured in this isolated test.", 503,
                        kind="authentication_error", next_action="Configure the coordinator Git credentials.")
    monkeypatch.setattr(sync, "_fetch", inaccessible)
    assert sync.configure(**custom)["status"] == "authentication_error"
    clear_default_overrides(monkeypatch)
    if fallback == "blank":
        monkeypatch.setenv("RESEARCHRELAY_GITHUB_URL", "")
    restarted_settings = settings_at(tmp_path)
    restarted = ProjectSync(restarted_settings, Engine(settings.db_path, PROJECT))
    assert restarted_settings.github_url == (None if fallback == "blank" else CANONICAL_URL)
    assert restarted.binding == custom
    assert restarted.public()["repository"] == custom
    assert restarted.engine.get_task("preserve-existing-work")["status"] == "queued"


def test_coordinator_rebinds_one_project_without_leaking_old_cached_documents(tmp_path):
    prefix = "team/knowledge"
    first_remote, first_commit = seed_remote(tmp_path, "first-team", "team-main", prefix, include_note=True)
    second_remote, second_commit = seed_remote(tmp_path, "second-team", "other-main", prefix)
    settings = settings_at(tmp_path, mode="demo", github_url=None)
    engine = Engine(settings.db_path, PROJECT)
    engine.create_task(id="keep-task", owner="alice", acceptance_criteria=["Preserve approved scope"])
    app = authenticated_app(settings, engine)
    with TestClient(app) as client:
        first_binding = {"url": str(first_remote), "branch": "team-main", "knowledge_path": prefix}
        denied = client.put("/api/project/repository", headers=headers("alice"), json=first_binding)
        assert denied.status_code == 403
        assert app.state.project_sync.binding is None
        configured = client.put("/api/project/repository", headers=headers(), json=first_binding)
        assert configured.status_code == 200, configured.text
        first = client.get("/api/project/context", headers=headers()).json()
        assert first["sync"]["latest_commit"] == first_commit
        assert [document["path"] for document in first["documents"]] == [prefix + "/source.md"]
        second_binding = {"url": str(second_remote), "branch": "other-main", "knowledge_path": prefix}
        changed = client.put("/api/project/repository", headers=headers(), json=second_binding)
        assert changed.status_code == 200, changed.text
        current = client.get("/api/project/context", headers=headers()).json()
        assert current["repository"] == second_binding
        assert current["sync"]["latest_commit"] == second_commit != first_commit
        assert current["documents"] == []
        assert engine.get_task("keep-task")["status"] == "queued"
        rejected = client.put("/api/project/repository", headers=headers(), json={**second_binding,
            "url": "https://alice:private-url-secret@github.com/team/other.git"})
        assert rejected.status_code == 422, rejected.text
        assert "private-url-secret" not in rejected.text
        assert app.state.project_sync.binding == second_binding
        assert client.get("/api/project", headers=headers()).json()["repository"] == second_binding


def test_committed_custom_repository_with_no_bundle_accepts_first_publication(tmp_path):
    prefix = "science/knowledge"
    remote, original_commit = seed_remote(tmp_path, "empty-knowledge", "research/initial", prefix)
    settings = settings_at(tmp_path, mode="demo", github_url=str(remote), github_branch="research/initial",
                           knowledge_path=prefix)
    app = authenticated_app(settings, Engine(settings.db_path, PROJECT))
    with TestClient(app) as client:
        first = client.get("/api/project/context", headers=headers("alice"))
        assert first.status_code == 200, first.text
        assert first.json()["documents"] == []
        assert first.json()["sync"]["latest_commit"] == original_commit
        path = prefix + "/first-finding.md"
        response = client.post("/api/project/publish", headers=headers("alice"), json={
            "base_commit": original_commit, "expected_repository": first.json()["repository"],
            "agent": "shared-default-test/1.0", "request_id": "first-team-finding",
            "message": "Create the initial shared knowledge artifact", "changes": [
                {"path": path, "content": note(), "expected_sha256": None}]})
        assert response.status_code == 200, response.text
        latest = client.get("/api/project/context", headers=headers("alice")).json()
        assert latest["sync"]["latest_commit"] == response.json()["commit"] != original_commit
        assert [document["path"] for document in latest["documents"]] == [path]
        assert latest["documents"][0]["metadata"]["responsible_participant"] == "alice"
        tree = git(remote, "ls-tree", "-r", "--name-only", "refs/heads/research/initial")
        assert "README.md" in tree and path in tree


def test_unborn_custom_repository_has_actionable_initial_commit_error(tmp_path):
    remote = tmp_path / "unborn.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    settings = settings_at(tmp_path, mode="demo", github_url=str(remote), github_branch="team-main")
    app = authenticated_app(settings, Engine(settings.db_path, PROJECT))
    with TestClient(app) as client:
        response = client.get("/api/project/context", headers=headers())
        assert response.status_code in {409, 422, 503}, response.text
        problem = response.json()
        assert problem["kind"] == "configuration", response.text
        explanation = (problem["detail"] + " " + problem["next_action"]).lower()
        assert "commit" in explanation and "branch" in explanation
        assert app.state.project_sync.status()["latest_commit"] is None



@pytest.mark.parametrize("rebind", ["repository", "branch", "knowledge_path"])
def test_identical_commit_cannot_redirect_a_publication_to_another_binding(tmp_path, rebind):
    prefix = "team/knowledge"
    branch = "team-main"
    remote, _ = seed_remote(tmp_path, "original-team", branch, prefix)
    settings = settings_at(tmp_path, mode="demo", github_url=str(remote), github_branch=branch,
                           knowledge_path=prefix)
    app = authenticated_app(settings, Engine(settings.db_path, PROJECT))

    def publication(context, name, key):
        return {"base_commit": context["sync"]["latest_commit"], "expected_repository": context["repository"],
                "agent": "shared-default-test/1.0", "request_id": key, "message": "Publish to the reviewed project binding",
                "changes": [{"path": context["repository"]["knowledge_path"] + "/" + name + ".md",
                             "content": note(identifier=name), "expected_sha256": None}]}

    with TestClient(app) as client:
        first = client.get("/api/project/context", headers=headers("alice")).json()
        accepted_payload = publication(first, "accepted-before-rebind", "accepted-before-rebind")
        accepted = client.post("/api/project/publish", headers=headers("alice"), json=accepted_payload)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["repository"] == first["repository"]
        old_context = client.get("/api/project/context", headers=headers("alice")).json()
        old_draft = publication(old_context, "pending-draft", "stale-binding-draft")
        old_result_inputs = {"project_context": {"repository": old_context["repository"],
            "commit": old_context["sync"]["latest_commit"],
            "documents": [{"path": document["path"], "sha256": document["sha256"]}
                          for document in old_context["documents"]]}}
        app.state.project_sync.check_inputs(old_result_inputs)
        unchanged = old_context["sync"]["latest_commit"]
        assert unchanged == accepted.json()["commit"]

        if rebind == "repository":
            destination = tmp_path / "other-team.git"
            subprocess.run(["git", "clone", "--bare", str(remote), str(destination)], check=True, capture_output=True)
            destination_branch = branch
        elif rebind == "branch":
            destination = remote
            destination_branch = "another-team-branch"
            git(remote, "branch", destination_branch, unchanged)
        else:
            destination = remote
            destination_branch = branch
        new_prefix = "another/knowledge" if rebind == "knowledge_path" else prefix
        assert git(destination, "rev-parse", "refs/heads/" + destination_branch) == unchanged
        new_binding = {"url": str(destination), "branch": destination_branch, "knowledge_path": new_prefix}
        rebound = client.put("/api/project/repository", headers=headers(), json=new_binding)
        assert rebound.status_code == 200, rebound.text
        assert rebound.json()["sync"]["latest_commit"] == unchanged

        # A running result also belongs to its original repository/branch,
        # even when both destinations currently expose identical documents.
        with pytest.raises(SyncError) as changed_inputs:
            app.state.project_sync.check_inputs(old_result_inputs)
        assert changed_inputs.value.status == 409
        assert any(action in changed_inputs.value.next_action.lower() for action in ("refresh", "reconcile"))

        # Identical Git object IDs do not authorize publishing to a different
        # destination than the one the participant inspected.
        rejected = client.post("/api/project/publish", headers=headers("alice"), json=old_draft)
        assert rejected.status_code == 409, rejected.text
        assert any(action in rejected.json()["next_action"].lower() for action in ("refresh", "retrieve", "reconcile"))
        assert git(destination, "rev-parse", "refs/heads/" + destination_branch) == unchanged
        assert git(remote, "rev-parse", "refs/heads/" + branch) == unchanged

        # An already accepted request remains an historical acknowledgment;
        # replaying it does not send the old contribution to the new binding.
        replay = client.post("/api/project/publish", headers=headers("alice"), json=accepted_payload)
        assert replay.status_code == 200, replay.text
        assert replay.json() == accepted.json()
        assert git(destination, "rev-parse", "refs/heads/" + destination_branch) == unchanged
        assert git(remote, "rev-parse", "refs/heads/" + branch) == unchanged

        current = client.get("/api/project/context", headers=headers("alice")).json()
        assert current["repository"] == new_binding
        assert current["sync"]["latest_commit"] == old_context["sync"]["latest_commit"]
        app.state.project_sync.check_inputs({"project_context": {"repository": current["repository"],
            "commit": current["sync"]["latest_commit"],
            "documents": [{"path": document["path"], "sha256": document["sha256"]}
                          for document in current["documents"]]}})
        fresh_payload = {**old_draft, "request_id": "fresh-binding-draft", "expected_repository": current["repository"],
                         "base_commit": current["sync"]["latest_commit"], "changes": [
                             {**change, "path": new_prefix + "/pending-draft.md"} for change in old_draft["changes"]]}
        published = client.post("/api/project/publish", headers=headers("alice"), json=fresh_payload)
        assert published.status_code == 200, published.text
        assert published.json()["repository"] == current["repository"]
        assert published.json()["commit"] != unchanged
        assert git(destination, "rev-parse", "refs/heads/" + destination_branch) == published.json()["commit"]
        if rebind != "knowledge_path":
            assert git(remote, "rev-parse", "refs/heads/" + branch) == unchanged
        content = git(destination, "show", "refs/heads/" + destination_branch + ":" + new_prefix + "/pending-draft.md")
        assert "pending-draft" in content and "responsible_participant: alice" in content
