"""Workers reuse GitHub authorization instead of a ResearchRelay project secret."""
from types import SimpleNamespace

import pytest

from researchrelay.client_auth import authorization_headers


def test_local_demo_does_not_read_a_github_credential(monkeypatch):
    monkeypatch.setattr('researchrelay.client_auth.subprocess.run', lambda *a, **k: pytest.fail('Local demos need no account'))
    assert authorization_headers('http://127.0.0.1:8000') == {}


def test_managed_cli_reuses_the_github_cli_login(monkeypatch):
    monkeypatch.delenv('GH_TOKEN', raising=False)
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    commands = []
    def credential(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout='own-github-authorization\n')
    monkeypatch.setattr('researchrelay.client_auth.subprocess.run', credential)
    assert authorization_headers('http://127.0.0.1:8000/projects/earth-system') == {'Authorization': 'Bearer own-github-authorization'}
    assert commands == [['gh', 'auth', 'token', '--hostname', 'github.com']]


def test_automation_uses_its_own_github_environment(monkeypatch):
    monkeypatch.setenv('GH_TOKEN', 'automation-github-authorization')
    assert authorization_headers('https://relay.example/projects/earth-system') == {'Authorization': 'Bearer automation-github-authorization'}


def test_missing_github_login_gives_a_sign_in_action(monkeypatch):
    monkeypatch.delenv('GH_TOKEN', raising=False)
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    monkeypatch.setattr('researchrelay.client_auth.subprocess.run', lambda *a, **k: SimpleNamespace(returncode=1, stdout=''))
    with pytest.raises(RuntimeError, match='gh auth login'):
        authorization_headers('https://relay.example/projects/earth-system')


def test_remote_http_cannot_receive_github_authorization(monkeypatch):
    monkeypatch.setenv('GH_TOKEN', 'private-github-authorization')
    with pytest.raises(RuntimeError, match='HTTPS'):
        authorization_headers('http://relay.example/projects/earth-system')
