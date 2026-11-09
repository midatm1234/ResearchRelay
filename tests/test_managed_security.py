"""Request identity and deployment boundary regressions; no network calls."""
import os
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from researchrelay.api import create_app
from researchrelay.config import Settings
from researchrelay.engine import Engine
from researchrelay.github_auth import GitHubIdentity
from researchrelay.managed_context import ManagedProjectSync,managed_identity
from researchrelay.sync import ProjectSync,SyncError

def test_oauth_deployment_does_not_expose_legacy_loopback_api(tmp_path):
    settings = Settings(db_path=tmp_path/"state.db",repo_path=tmp_path/"record",github_url=None,
        oauth_client_id="test-client",oauth_client_secret="private-client-secret",hub_path=tmp_path/"hub")
    app = create_app(settings)
    client = TestClient(app)
    assert client.get("/",follow_redirects=False).headers["location"]=="/projects"
    assert client.get("/api/tasks").status_code==401
    assert client.get("/api/hub/status").status_code==200
    assert client.get("/api/tasks",headers={"Authorization":"Bearer legacy-operator-secret"}).status_code==401

def test_git_credentials_are_request_local_and_never_saved_in_configuration(tmp_path,monkeypatch):
    settings = Settings(db_path=tmp_path/"state.db",repo_path=tmp_path/"record",github_url=None)
    sync = ManagedProjectSync(settings,Engine(settings.db_path,settings.project_id))
    monkeypatch.setenv("RESEARCHRELAY_GITHUB_CLIENT_SECRET","server-secret")
    monkeypatch.setenv("GIT_TRACE","1")
    monkeypatch.setenv("GIT_CONFIG_COUNT","1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0","http.extraHeader")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0","ambient-credential")
    identity = GitHubIdentity(123,"alice","own-secret-not-a-recognizable-pattern")
    token = managed_identity.set(dict(identity=identity,role="write",demo=False))
    try:
        environment = sync._environment()
        assert "RESEARCHRELAY_GITHUB_CLIENT_SECRET" not in environment
        assert "GIT_TRACE" not in environment
        assert "ambient-credential" not in str(environment)
        config = {environment[f"GIT_CONFIG_KEY_{i}"]:environment[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(environment["GIT_CONFIG_COUNT"]))}
        assert config["credential.helper"]==""
        assert config["http.followRedirects"]=="false"
        assert config["core.longpaths"]=="true"
        assert config["protocol.file.allow"]=="never"
        assert config["http.https://github.com/.extraHeader"].startswith("Authorization: Basic ")
        assert "own-secret-not-a-recognizable-pattern" not in repr(identity)
        assert not (tmp_path/"record").exists()
    finally:
        managed_identity.reset(token)
    with pytest.raises(SyncError):
        sync._environment()

@pytest.mark.parametrize("credential",["own-current-token-without-provider-prefix","github_pat_"+"a"*30])
def test_managed_generated_documents_refuse_current_and_fine_grained_tokens(tmp_path,credential):
    settings = Settings(db_path=tmp_path/"state.db",repo_path=tmp_path/"record",github_url=None)
    sync = ManagedProjectSync(settings,Engine(settings.db_path,settings.project_id))
    identity = GitHubIdentity(1,"alice","own-current-token-without-provider-prefix")
    token = managed_identity.set(dict(identity=identity,role="write",demo=False))
    try:
        with pytest.raises(SyncError) as caught:
            sync._validate_prospective(None,None,{},[dict(path="projects/test/leak.md",content=credential)])
        assert caught.value.status==422
        assert credential not in str(caught.value)
    finally:
        managed_identity.reset(token)

def test_managed_git_auth_failure_requests_own_github_reconnection(tmp_path,monkeypatch):
    settings = Settings(db_path=tmp_path/"state.db",repo_path=tmp_path/"record",github_url=None)
    sync = ManagedProjectSync(settings,Engine(settings.db_path,settings.project_id))
    def rejected(*args,**kwargs):
        raise SyncError("Repository authentication or access failed.",503,kind="authentication_error")
    monkeypatch.setattr(ProjectSync,"_git",rejected)
    with pytest.raises(SyncError) as caught:
        sync._git(tmp_path,"fetch")
    assert caught.value.status==401
    assert "Reconnect your GitHub account" in caught.value.next_action
    assert "coordinator host" not in caught.value.next_action

def test_project_demo_ipv6_origin_is_valid(monkeypatch):
    from researchrelay.cli import main
    import uvicorn
    monkeypatch.setattr(uvicorn,"run",lambda *args,**kwargs:None)
    main(["serve","--project-demo","--host","::1","--port","8123"])
    assert os.environ["RESEARCHRELAY_PUBLIC_URL"]=="http://[::1]:8123"
