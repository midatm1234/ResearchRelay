"""Mocked GitHub OAuth protocol and real encrypted SQLite/session storage."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
from urllib.parse import parse_qs,urlparse

from cryptography.fernet import Fernet
import httpx
import pytest

from researchrelay.github_auth import GitHubAuth
from researchrelay.github_client import GitHubError


class GitHubOAuth:
    def __init__(self):
        self.requests=[]
        self.access='gho_private-access-value-for-test-only'
        self.refresh='ghr_private-refresh-value-for-test-only'
        self.user_id=123
        self.status=200
        self.token_error=False
        self.expires=3600
        self.scopes='repo,read:user,read:org'
        self.refresh_calls=0
    def __call__(self,request):
        self.requests.append(request)
        if request.url.host=='github.com':
            data=parse_qs(request.content.decode())
            assert data['client_secret']==['server-private-client-secret']
            if self.token_error:return httpx.Response(200,json={'error':'bad_verification_code','error_description':self.access})
            if data.get('grant_type')==['refresh_token']:
                self.refresh_calls+=1
                self.access='gho_rotated-access-value-for-test-only'
                self.refresh='ghr_rotated-refresh-value-for-test-only'
            return httpx.Response(200,json={'access_token':self.access,'refresh_token':self.refresh,
                'token_type':'bearer','scope':self.scopes,'expires_in':self.expires,'refresh_token_expires_in':10000})
        assert request.url.host=='api.github.com' and request.url.path=='/user'
        if self.status!=200:return httpx.Response(self.status,json={'message':self.access})
        return httpx.Response(200,json={'id':self.user_id,'login':'alice','avatar_url':'https://avatars.githubusercontent.com/u/123'})


def auth(tmp_path,server,clock=None,**kwargs):
    return GitHubAuth(tmp_path/'auth.db',client_id='public-client-id',client_secret='server-private-client-secret',
        redirect_uri='http://127.0.0.1:8000/api/auth/github/callback',key_path=tmp_path/'private/auth.key',
        transport=httpx.MockTransport(server),clock=clock,**kwargs)


def login(instance):
    start=instance.begin_login()
    query=parse_qs(urlparse(start['authorization_url']).query)
    finished=instance.finish_login('temporary-code',query['state'][0],start['pending_cookie'])
    return start,query,finished


def test_oauth_state_pkce_encrypted_tokens_and_opaque_session(tmp_path):
    server=GitHubOAuth();instance=auth(tmp_path,server)
    start,query,finished=login(instance)
    exchange=parse_qs(server.requests[0].content.decode())
    verifier=exchange['code_verifier'][0]
    expected=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    assert query['code_challenge']==[expected] and query['code_challenge_method']==['S256']
    assert exchange['redirect_uri']==['http://127.0.0.1:8000/api/auth/github/callback']
    assert 'server-private-client-secret' not in start['authorization_url']
    assert finished['identity']['github_user_id']==123 and 'token' not in finished['identity']
    assert finished['session_cookie']!=server.access
    data=(tmp_path/'auth.db').read_bytes()
    for secret in (server.access,server.refresh,finished['session_cookie'],verifier,'temporary-code','server-private-client-secret'):
        assert secret.encode() not in data
    with sqlite3.connect(tmp_path/'auth.db') as db:
        encrypted=db.execute('SELECT encrypted FROM github_credentials').fetchone()[0]
        session_hash=db.execute('SELECT session_hash FROM github_sessions').fetchone()[0]
    assert Fernet((tmp_path/'private/auth.key').read_bytes()).decrypt(encrypted)
    assert session_hash==hashlib.sha256(finished['session_cookie'].encode()).hexdigest()
    identity=instance.identity(finished['session_cookie'])
    assert identity.github_user_id==123 and identity.token==server.access
    assert server.access not in repr(identity) and 'token' not in identity.public()


@pytest.mark.parametrize('failure',['wrong_state','wrong_browser','expired','replay'])
def test_oauth_rejects_state_browser_expiration_and_replay(tmp_path,failure):
    now=[1000.0];server=GitHubOAuth();instance=auth(tmp_path,server,clock=lambda:now[0])
    start=instance.begin_login();state=parse_qs(urlparse(start['authorization_url']).query)['state'][0]
    nonce=start['pending_cookie']
    if failure=='wrong_state':state='x'*43
    elif failure=='wrong_browser':nonce='x'*43
    elif failure=='expired':now[0]+=601
    else:instance.finish_login('temporary-code',state,nonce)
    before=len(server.requests)
    with pytest.raises(GitHubError) as error:instance.finish_login('temporary-code',state,nonce)
    assert error.value.kind=='oauth_state' and len(server.requests)==before


def test_missing_oauth_configuration_is_actionable_and_no_pat_is_shared(tmp_path):
    instance=GitHubAuth(tmp_path/'auth.db')
    assert not instance.configured
    with pytest.raises(GitHubError) as error:instance.begin_login()
    assert error.value.kind=='configuration' and error.value.status==503
    assert 'administrator' in error.value.next_action


@pytest.mark.parametrize('configuration',['http://external.example/callback','https://user:password@example.org/callback','https://example.org/callback?token=bad'])
def test_oauth_callback_configuration_rejects_insecure_urls(tmp_path,configuration):
    with pytest.raises(GitHubError):GitHubAuth(tmp_path/'auth.db',client_id='client-id',client_secret='secret',redirect_uri=configuration)


def test_oauth_failure_does_not_expose_provider_details_or_create_session(tmp_path):
    server=GitHubOAuth();server.token_error=True;instance=auth(tmp_path,server)
    with pytest.raises(GitHubError) as error:login(instance)
    assert server.access not in str(error.value)
    with sqlite3.connect(tmp_path/'auth.db') as db:
        assert db.execute('SELECT COUNT(*) FROM github_credentials').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM github_sessions').fetchone()[0]==0


def test_oauth_insufficient_scope_is_not_silently_accepted(tmp_path):
    server=GitHubOAuth();server.scopes='public_repo';instance=auth(tmp_path,server)
    with pytest.raises(GitHubError) as error:login(instance)
    assert error.value.status==403 and error.value.kind=='permission'


def test_session_survives_restart_and_last_logout_removes_encrypted_credentials(tmp_path):
    server=GitHubOAuth();instance=auth(tmp_path,server)
    first=login(instance)[2]['session_cookie'];second=login(instance)[2]['session_cookie']
    restarted=auth(tmp_path,server)
    assert restarted.identity(first).github_user_id==123
    instance.logout(first)
    assert restarted.identity(second).login=='alice'
    with pytest.raises(GitHubError):instance.identity(first)
    restarted.logout(second)
    with sqlite3.connect(tmp_path/'auth.db') as db:
        assert db.execute('SELECT COUNT(*) FROM github_credentials').fetchone()[0]==0


def test_expiring_oauth_token_refresh_is_rotated_and_identity_checked(tmp_path):
    now=[1000.0];server=GitHubOAuth();server.expires=60;instance=auth(tmp_path,server,clock=lambda:now[0])
    cookie=login(instance)[2]['session_cookie'];now[0]+=31;server.expires=3600
    identity=instance.identity(cookie)
    assert server.refresh_calls==1 and identity.token==server.access
    instance.identity(cookie)
    assert server.refresh_calls==1
    data=(tmp_path/'auth.db').read_bytes()
    assert server.access.encode() not in data and server.refresh.encode() not in data


def test_refresh_cannot_switch_the_github_numeric_identity(tmp_path):
    now=[1000.0];server=GitHubOAuth();server.expires=60;instance=auth(tmp_path,server,clock=lambda:now[0])
    cookie=login(instance)[2]['session_cookie'];now[0]+=31;server.user_id=999
    with pytest.raises(GitHubError) as error:instance.identity(cookie)
    assert error.value.status==401


def test_revoked_oauth_token_invalidates_local_sessions(tmp_path):
    server=GitHubOAuth();instance=auth(tmp_path,server);cookie=login(instance)[2]['session_cookie']
    server.status=401
    with pytest.raises(GitHubError):instance.identity(cookie)
    with sqlite3.connect(tmp_path/'auth.db') as db:
        assert db.execute('SELECT COUNT(*) FROM github_sessions').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM github_credentials').fetchone()[0]==0


def test_expired_session_never_reuses_a_stored_token(tmp_path):
    now=[1000.0];server=GitHubOAuth();instance=auth(tmp_path,server,clock=lambda:now[0],session_seconds=60)
    cookie=login(instance)[2]['session_cookie'];now[0]+=61;before=len(server.requests)
    with pytest.raises(GitHubError) as error:instance.identity(cookie)
    assert error.value.status==401 and len(server.requests)==before


def test_cli_pat_is_verified_but_never_persisted(tmp_path):
    server=GitHubOAuth();instance=auth(tmp_path,server)
    identity=instance.identity(bearer='private-cli-pat-for-test-only')
    assert identity.source=='pat' and identity.github_user_id==123
    assert 'private-cli-pat-for-test-only' not in repr(identity)
    assert b'private-cli-pat-for-test-only' not in (tmp_path/'auth.db').read_bytes()
    with pytest.raises(GitHubError):instance.identity('x'*64,bearer='private-cli-pat-for-test-only')


def test_corrupt_ciphertext_or_wrong_key_does_not_fall_back_to_plaintext(tmp_path):
    server=GitHubOAuth();instance=auth(tmp_path,server);cookie=login(instance)[2]['session_cookie']
    key=tmp_path/'private/auth.key';key.write_bytes(Fernet.generate_key())
    restarted=auth(tmp_path,server)
    with pytest.raises(GitHubError) as error:restarted.identity(cookie)
    assert error.value.status==503 and server.access not in str(error.value)
    assert (tmp_path/'auth.db').exists()


def test_missing_key_with_existing_credentials_is_not_silently_replaced(tmp_path):
    server=GitHubOAuth();instance=auth(tmp_path,server);login(instance)
    key=tmp_path/'private/auth.key';key.unlink()
    with pytest.raises(GitHubError) as error:auth(tmp_path,server)
    assert error.value.kind=='configuration' and not key.exists()
    with sqlite3.connect(tmp_path/'auth.db') as db:
        assert db.execute('SELECT COUNT(*) FROM github_credentials').fetchone()[0]==1


def test_one_oauth_callback_state_cannot_be_exchanged_twice_concurrently(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    server=GitHubOAuth();instance=auth(tmp_path,server)
    start=instance.begin_login();state=parse_qs(urlparse(start['authorization_url']).query)['state'][0]
    def finish():
        try:return instance.finish_login('temporary-code',state,start['pending_cookie'])
        except GitHubError as error:return error
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:finish(),range(2)))
    assert sum(isinstance(result,dict) for result in results)==1
    assert sum(isinstance(result,GitHubError) for result in results)==1
    assert sum(request.url.host=='github.com' for request in server.requests)==1


def test_unconfigured_oauth_remains_inspectable_without_a_usable_public_callback(tmp_path):
    instance=GitHubAuth(tmp_path/'auth.db',redirect_uri='http://not-yet-configured.example/api/hub/auth/callback')
    assert instance.configured is False
    with pytest.raises(GitHubError) as error:instance.begin_login()
    assert error.value.status==503 and error.value.kind=='configuration'
