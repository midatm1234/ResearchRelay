"""GitHub OAuth web login with PKCE, browser binding, opaque sessions and encrypted tokens."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
from urllib.parse import urlencode, urlparse

from cryptography.fernet import Fernet, InvalidToken
import httpx

from .github_client import GitHubClient, GitHubError

OAUTH_AUTHORIZE = 'https://github.com/login/oauth/authorize'
OAUTH_TOKEN = 'https://github.com/login/oauth/access_token'


def _digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class GitHubIdentity:
    github_user_id: int
    login: str
    token: str = field(repr=False,compare=False)
    avatar_url: str | None = None
    scopes: tuple[str,...] = ()
    source: str = 'oauth'

    def public(self):
        return {'github_user_id':self.github_user_id,'login':self.login,'avatar_url':self.avatar_url,
                'scopes':list(self.scopes),'source':self.source}


class GitHubAuth:
    def __init__(self,db_path,*,client_id=None,client_secret=None,redirect_uri=None,key_path=None,
                 scopes=('repo','read:user','read:org'),session_seconds=28800,transport=None,clock=None):
        self.db_path=Path(db_path).expanduser().resolve()
        self.key_path=Path(key_path).expanduser().absolute() if key_path else self.db_path.with_suffix('.key')
        self.client_id=client_id or ''
        self._client_secret=client_secret or ''
        self.redirect_uri=redirect_uri or ''
        self.scopes=tuple(scopes)
        self.session_seconds=int(session_seconds)
        self.transport=transport
        self.clock=clock or time.time
        if not 60<=self.session_seconds<=604800:
            raise GitHubError('Session lifetime must be between one minute and seven days.',422,kind='configuration')
        if self.configured:
            target=urlparse(self.redirect_uri)
            if (target.username or target.password or target.query or target.fragment or not target.hostname
                    or target.scheme!='https' and not (target.scheme=='http' and target.hostname in {'localhost','127.0.0.1','::1'})):
                raise GitHubError('Configure an HTTPS OAuth callback, or HTTP only on a loopback development host.',422,kind='configuration')
        self.db_path.parent.mkdir(parents=True,exist_ok=True)
        self._fernet=Fernet(self._key())
        with self._transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS github_oauth_pending(
                    state_hash TEXT PRIMARY KEY,nonce_hash TEXT NOT NULL,verifier BLOB NOT NULL,expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS github_credentials(
                    user_id INTEGER PRIMARY KEY,public_json TEXT NOT NULL,encrypted BLOB NOT NULL,updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS github_sessions(
                    session_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires REAL NOT NULL,created REAL NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES github_credentials(user_id) ON DELETE CASCADE);
            """)
        self.db_path.chmod(0o600)

    @property
    def configured(self):
        return bool(self.client_id and self._client_secret and self.redirect_uri)

    def _require_configuration(self):
        if not self.configured:
            raise GitHubError('GitHub browser sign-in is not configured on this ResearchRelay server.',503,kind='configuration',
                next_action='Ask the server administrator to configure its GitHub OAuth client ID, secret and callback URL. No shared login is substituted.')

    def _key(self):
        self.key_path.parent.mkdir(parents=True,exist_ok=True)
        if self.key_path.is_symlink():
            raise GitHubError('The OAuth encryption key must be a private regular file.',503,kind='configuration')
        if not self.key_path.exists():
            if self.db_path.exists():
                try:
                    with sqlite3.connect(self.db_path,timeout=5) as db:
                        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='github_credentials'").fetchone()
                        if exists and db.execute('SELECT 1 FROM github_credentials LIMIT 1').fetchone():
                            raise GitHubError('The OAuth encryption key is missing while encrypted credentials still exist.',503,kind='configuration',
                                next_action='Restore the original private key from backup; no replacement key was generated.')
                except sqlite3.Error:
                    raise GitHubError('OAuth credential storage could not be inspected safely.',503,kind='configuration') from None
            descriptor,temporary=tempfile.mkstemp(prefix='.github-key-',dir=self.key_path.parent)
            try:
                with os.fdopen(descriptor,'wb') as stream:
                    stream.write(Fernet.generate_key())
                    stream.flush()
                    os.fsync(stream.fileno())
                try:
                    os.link(temporary,self.key_path)
                except FileExistsError:
                    pass
                except OSError:
                    raise GitHubError('A private OAuth encryption key could not be initialized atomically.',503,kind='configuration',
                        next_action='Configure a private key file on a filesystem that supports atomic file creation.') from None
            finally:
                Path(temporary).unlink(missing_ok=True)
        if self.key_path.is_symlink():
            raise GitHubError('The OAuth encryption key must be a private regular file.',503,kind='configuration')
        try:
            self.key_path.chmod(0o600)
            key=self.key_path.read_bytes().strip()
            Fernet(key)
            return key
        except (OSError,ValueError,TypeError):
            raise GitHubError('The OAuth encryption key is unavailable or invalid; existing credentials were preserved.',503,kind='configuration',
                next_action='Restore the private server encryption key from backup; do not replace it while stored credentials are needed.') from None

    @contextmanager
    def _transaction(self):
        db=sqlite3.connect(self.db_path,timeout=30,isolation_level=None)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _encrypt(self,value):
        return self._fernet.encrypt(json.dumps(value,separators=(',',':')).encode('utf-8'))

    def _decrypt(self,value):
        try:
            return json.loads(self._fernet.decrypt(value).decode('utf-8'))
        except (InvalidToken,ValueError,UnicodeError,TypeError):
            raise GitHubError('Stored GitHub authorization could not be decrypted.',503,kind='configuration',
                next_action='Restore the original server key or disconnect and sign in again; no plaintext fallback is used.') from None

    def begin_login(self,browser_nonce=None):
        self._require_configuration()
        nonce=browser_nonce or secrets.token_urlsafe(32)
        if not isinstance(nonce,str) or not 32<=len(nonce)<=256 or any(ord(c)<33 or ord(c)>126 for c in nonce):
            raise GitHubError('Start sign-in again to establish a valid browser nonce.',400,kind='oauth_state')
        state=secrets.token_urlsafe(32)
        verifier=secrets.token_urlsafe(64)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        now=self.clock()
        with self._transaction() as db:
            db.execute('DELETE FROM github_oauth_pending WHERE expires<=?',(now,))
            db.execute('INSERT INTO github_oauth_pending VALUES(?,?,?,?)',
                       (_digest(state),_digest(nonce),self._encrypt({'verifier':verifier}),now+600))
        url=OAUTH_AUTHORIZE+'?'+urlencode({'client_id':self.client_id,'redirect_uri':self.redirect_uri,
            'scope':' '.join(self.scopes),'state':state,'code_challenge':challenge,'code_challenge_method':'S256'})
        return {'authorization_url':url,'pending_cookie':nonce,'expires_in':600}

    def _token_request(self,payload):
        try:
            with httpx.Client(transport=self.transport,timeout=30,trust_env=False,follow_redirects=False) as client:
                response=client.post(OAUTH_TOKEN,data=payload,headers={'Accept':'application/json','User-Agent':'ResearchRelay'})
        except httpx.HTTPError:
            raise GitHubError('GitHub sign-in could not complete because the token exchange was unavailable.',503,kind='unavailable',
                              next_action='Check connectivity and start sign-in again; no credential response was exposed.') from None
        if not 200<=response.status_code<300:
            raise GitHubError('GitHub rejected the server token exchange.',401 if response.status_code in {400,401,403} else 503,
                              kind='authentication',next_action='Start sign-in again; the administrator should verify the OAuth registration if this repeats.')
        try:
            value=response.json()
            if not isinstance(value,dict) or value.get('error') or not isinstance(value.get('access_token'),str) or not value['access_token']:
                raise ValueError()
            if value.get('token_type','bearer').lower()!='bearer':raise ValueError()
            return value
        except (ValueError,TypeError,AttributeError):
            raise GitHubError('GitHub did not issue a usable authorization token.',401,kind='authentication',
                              next_action='Start sign-in again and approve the requested repository access.') from None

    def _token_record(self,value,old=None):
        now=self.clock()
        scopes=value.get('scope',','.join((old or {}).get('scopes',[])))
        if not isinstance(scopes,str):raise GitHubError('GitHub returned invalid authorization scopes.',502,kind='response')
        granted=set(scopes.replace(',',' ').split())
        implied=set(granted)
        if 'user' in granted:implied.add('read:user')
        if granted & {'admin:org','write:org'}:implied.add('read:org')
        if not set(self.scopes)<=implied:
            raise GitHubError('GitHub authorization did not grant the required repository and account scopes.',403,kind='permission',
                              next_action='Sign in again and approve the requested scopes, including organization authorization where needed.')
        record={'access_token':value['access_token'],'scopes':sorted(granted),'obtained_at':now}
        for source,destination in (('expires_in','expires_at'),('refresh_token_expires_in','refresh_expires_at')):
            if source in value:
                duration=value[source]
                if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not 0<duration<=366*86400:
                    raise GitHubError('GitHub returned invalid token expiration metadata.',502,kind='response')
                record[destination]=now+duration
        if value.get('refresh_token'):
            if not isinstance(value['refresh_token'],str):raise GitHubError('GitHub returned an invalid refresh token.',502,kind='response')
            record['refresh_token']=value['refresh_token']
        elif old and old.get('refresh_token'):
            record['refresh_token']=old['refresh_token']
            record['refresh_expires_at']=old.get('refresh_expires_at')
        return record

    @staticmethod
    def _identity(user,token,scopes=(),source='oauth'):
        if (not isinstance(user,dict) or not isinstance(user.get('id'),int) or isinstance(user['id'],bool) or user['id']<=0
                or not isinstance(user.get('login'),str) or not user['login'] or len(user['login'])>100):
            raise GitHubError('GitHub account identity could not be verified.',502,kind='response')
        return GitHubIdentity(user['id'],user['login'],token,user.get('avatar_url'),tuple(scopes),source)

    def finish_login(self,code,state,browser_nonce):
        self._require_configuration()
        if (not isinstance(code,str) or not code or len(code)>2048 or not isinstance(state,str) or not 20<=len(state)<=256
                or not isinstance(browser_nonce,str) or not 32<=len(browser_nonce)<=256):
            raise GitHubError('The GitHub callback is missing its original browser sign-in state.',400,kind='oauth_state',
                              next_action='Start sign-in again from this browser; do not reuse a callback URL.')
        with self._transaction() as db:
            pending=db.execute('SELECT * FROM github_oauth_pending WHERE state_hash=?',(_digest(state),)).fetchone()
            if not pending or pending['expires']<=self.clock() or not hmac.compare_digest(pending['nonce_hash'],_digest(browser_nonce)):
                raise GitHubError('GitHub sign-in state expired, was already used, or does not belong to this browser.',400,kind='oauth_state',
                                  next_action='Start sign-in again from this browser.')
            verifier=self._decrypt(pending['verifier'])['verifier']
            db.execute('DELETE FROM github_oauth_pending WHERE state_hash=?',(_digest(state),))
        value=self._token_request({'client_id':self.client_id,'client_secret':self._client_secret,'code':code,
                                  'redirect_uri':self.redirect_uri,'code_verifier':verifier})
        record=self._token_record(value)
        user=GitHubClient(record['access_token'],transport=self.transport).get_user()
        identity=self._identity(user,record['access_token'],record['scopes'])
        session=secrets.token_urlsafe(48)
        now=self.clock()
        with self._transaction() as db:
            db.execute('DELETE FROM github_sessions WHERE expires<=?',(now,))
            db.execute('INSERT INTO github_credentials VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET '
                       'public_json=excluded.public_json,encrypted=excluded.encrypted,updated=excluded.updated',
                       (identity.github_user_id,json.dumps(user),self._encrypt(record),now))
            db.execute('INSERT INTO github_sessions VALUES(?,?,?,?)',(_digest(session),identity.github_user_id,now+self.session_seconds,now))
        return {'session_cookie':session,'identity':identity.public(),'expires_in':self.session_seconds}

    def identity(self,session_cookie=None,bearer=None):
        if bearer:
            if session_cookie:raise GitHubError('Use one GitHub authentication method for a request.',400,kind='authentication')
            token=bearer[7:] if bearer.startswith('Bearer ') else bearer
            user=GitHubClient(token,transport=self.transport).get_user()
            return self._identity(user,token,source='pat')
        if not isinstance(session_cookie,str) or not 32<=len(session_cookie)<=256:
            raise GitHubError('Sign in to GitHub before opening a collaborative project.',401,kind='authentication')
        now=self.clock()
        with self._transaction() as db:
            row=db.execute('SELECT s.user_id,s.expires,c.encrypted,c.public_json FROM github_sessions s JOIN github_credentials c '
                           'ON s.user_id=c.user_id WHERE s.session_hash=?',(_digest(session_cookie),)).fetchone()
            if not row or row['expires']<=now:
                if row:db.execute('DELETE FROM github_sessions WHERE session_hash=?',(_digest(session_cookie),))
                raise GitHubError('Your ResearchRelay GitHub session expired or was signed out.',401,kind='authentication',
                                  next_action='Sign in again; project membership is checked with your current GitHub permissions.')
            record=self._decrypt(row['encrypted'])
            if record.get('expires_at',float('inf'))<=now+30:
                if not self.configured or not record.get('refresh_token') or record.get('refresh_expires_at',float('inf')) is not None and record.get('refresh_expires_at',float('inf'))<=now:
                    raise GitHubError('Your GitHub authorization expired.',401,kind='authentication',next_action='Sign in to GitHub again.')
                value=self._token_request({'client_id':self.client_id,'client_secret':self._client_secret,
                    'grant_type':'refresh_token','refresh_token':record['refresh_token']})
                refreshed=self._token_record(value,record)
                user=GitHubClient(refreshed['access_token'],transport=self.transport).get_user()
                if user['id']!=row['user_id']:
                    raise GitHubError('GitHub refreshed a different account identity; sign in again.',401,kind='authentication')
                record=refreshed
                db.execute('UPDATE github_credentials SET encrypted=?,public_json=?,updated=? WHERE user_id=?',
                           (self._encrypt(record),json.dumps(user),now,row['user_id']))
            user_id=row['user_id']
        try:
            user=GitHubClient(record['access_token'],transport=self.transport).get_user()
        except GitHubError as error:
            if error.status==401:
                with self._transaction() as db:db.execute('DELETE FROM github_credentials WHERE user_id=?',(user_id,))
            raise
        if user['id']!=user_id:
            raise GitHubError('GitHub authorization no longer identifies the signed-in account.',401,kind='authentication')
        return self._identity(user,record['access_token'],record['scopes'])

    def logout(self,session_cookie):
        if not isinstance(session_cookie,str) or len(session_cookie)>256:return
        with self._transaction() as db:
            row=db.execute('SELECT user_id FROM github_sessions WHERE session_hash=?',(_digest(session_cookie),)).fetchone()
            db.execute('DELETE FROM github_sessions WHERE session_hash=?',(_digest(session_cookie),))
            if row and not db.execute('SELECT 1 FROM github_sessions WHERE user_id=?',(row['user_id'],)).fetchone():
                db.execute('DELETE FROM github_credentials WHERE user_id=?',(row['user_id'],))
