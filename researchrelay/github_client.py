"""Participant-authenticated GitHub.com REST transport with non-forced Git writes."""
from __future__ import annotations

import base64
import hashlib
import re
import unicodedata
from urllib.parse import quote

import httpx

from .providers import guard_output_bytes, ProviderError

API_ROOT = 'https://api.github.com'
API_VERSION = '2026-03-10'
SHA = re.compile(r'(?:[0-9a-f]{40}|[0-9a-f]{64})')


class GitHubError(RuntimeError):
    """Public diagnosis only: provider response bodies and credentials stay private."""
    def __init__(self, message, status=502, *, kind='github', next_action=None, paths=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.next_action = next_action or 'Check GitHub access and refresh the selected repository before retrying.'
        self.paths = paths or []
        self.retry_after = retry_after


def _component(value, owner=False):
    pattern = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})' if owner else r'[A-Za-z0-9_.-]{1,100}'
    if not isinstance(value,str) or not re.fullmatch(pattern,value) or value in {'.','..'}:
        raise GitHubError('Choose a valid GitHub repository owner and name.',422,kind='validation')
    return quote(value,safe='')


def _branch(value):
    if (not isinstance(value,str) or not value or len(value)>240 or value=='@' or value.startswith(('/', '-'))
            or value.endswith(('/', '.')) or '..' in value or '@{' in value or '//' in value
            or any(ord(c)<33 or ord(c)==127 or c in '~^:?*[\\' for c in value)
            or any(part.startswith('.') or part.endswith('.lock') for part in value.split('/'))):
        raise GitHubError('Choose a valid Git branch name.',422,kind='validation')
    return quote(value,safe='')


def _sha(value):
    if not isinstance(value,str) or not SHA.fullmatch(value):
        raise GitHubError('GitHub did not provide a valid immutable commit or blob identifier.',422,kind='validation')
    return value


def _path(value):
    if (not isinstance(value,str) or not value or len(value)>2000 or value.startswith('/') or '\\' in value
            or any(ord(c)<32 or ord(c)==127 for c in value)
            or any(part in {'','.','..','.git'} for part in value.split('/'))):
        raise GitHubError('Use a repository-relative file path without traversal or Git metadata.',422,kind='validation')
    return value


def _portable_paths(paths):
    segments={}
    for path in paths:
        parts=path.split('/')
        folded=[]
        for part in parts:
            normalized=unicodedata.normalize('NFC',part).casefold()
            key=(tuple(folded),normalized)
            previous=segments.get(key)
            if previous is not None and previous!=part:
                raise GitHubError('Repository paths collide after case or Unicode normalization.',409,kind='conflict',paths=[path],
                    next_action='Use one consistent directory and filename spelling across macOS, Windows and Linux before retrying.')
            segments[key]=part
            folded.append(normalized)


class GitHubClient:
    def __init__(self, token, *, transport=None, timeout=30):
        if not isinstance(token,str) or not token.strip() or len(token)>8192 or any(ord(c)<33 or ord(c)==127 for c in token):
            raise GitHubError('Sign in with your own GitHub account before accessing a project.',401,kind='authentication')
        self._token = token
        self.transport = transport
        self.timeout = timeout

    def _request(self, method, path, *, params=None, payload=None, missing=False):
        if not path.startswith('/') or path.startswith('//') or '?' in path or '#' in path:
            raise GitHubError('Invalid internal GitHub request path.',422,kind='validation')
        headers = {'Authorization':'Bearer '+self._token,'Accept':'application/vnd.github+json',
                   'X-GitHub-Api-Version':API_VERSION,'User-Agent':'ResearchRelay'}
        try:
            with httpx.Client(transport=self.transport,timeout=self.timeout,trust_env=False,follow_redirects=False) as client:
                response = client.request(method,API_ROOT+path,params=params,json=payload,headers=headers)
        except httpx.HTTPError:
            raise GitHubError('GitHub could not be reached or the request timed out.',503,kind='unavailable',
                              next_action='Check connectivity. For an interrupted write, inspect the branch before retrying.') from None
        if missing and response.status_code==404:
            return None
        status=response.status_code
        if not 200<=status<300:
            remaining=response.headers.get('x-ratelimit-remaining')
            if status==429 or status==403 and (remaining=='0' or 'retry-after' in response.headers):
                retry=response.headers.get('retry-after','')
                raise GitHubError('GitHub rate limiting temporarily prevents this operation.',429,kind='rate_limit',
                    next_action='Wait for the GitHub rate limit to recover, then refresh and retry.',
                    retry_after=int(retry) if retry.isdigit() and int(retry)<=86400 else None)
            if status==401:
                raise GitHubError('GitHub authentication expired or was revoked.',401,kind='authentication',
                                  next_action='Sign in to GitHub again using your own account.')
            if status==403:
                raise GitHubError('Your GitHub account or authorization cannot perform this repository operation.',403,kind='permission',
                    next_action='Check repository role, organization OAuth/SSO approval, and branch protection; use the configured review policy.')
            if status==404:
                raise GitHubError('The GitHub resource does not exist or is not accessible to your account.',404,kind='not_found',
                                  next_action='Verify the owner/repository/branch and your access; private resources may appear missing.')
            if status in {409,422}:
                raise GitHubError('GitHub rejected a conflicting or invalid repository update.',status,kind='conflict' if status==409 else 'validation',
                    next_action='Refresh the branch, check name collisions and repository rules, and reconcile before retrying.')
            if 300<=status<400:
                raise GitHubError('The GitHub repository resource moved.',409,kind='moved',
                                  next_action='Choose the current owner/repository explicitly; credentials are not forwarded to redirects.')
            raise GitHubError('GitHub rejected the operation; no provider details were copied into project records.',502,kind='github')
        if status==204:
            return None
        if len(response.content)>16_000_000:
            raise GitHubError('The GitHub response is too large for this working-session service.',413,kind='limit')
        try:
            value=response.json()
            if not isinstance(value,(dict,list)):
                raise ValueError()
            return value
        except (ValueError,TypeError):
            raise GitHubError('GitHub returned an invalid response; refresh before continuing.',502,kind='response') from None

    @staticmethod
    def _repository(value):
        if not isinstance(value,dict) or not isinstance(value.get('full_name'),str):
            raise GitHubError('GitHub returned incomplete repository metadata.',502,kind='response')
        fields=('id','name','full_name','private','visibility','description','default_branch','html_url','fork','archived','disabled','permissions')
        result={key:value.get(key) for key in fields if key in value}
        owner=value.get('owner') or {}
        result['owner']={key:owner.get(key) for key in ('id','login','type') if key in owner}
        try:
            account,name=value['full_name'].split('/')
            _component(account,True);_component(name)
        except (ValueError,GitHubError):
            raise GitHubError('GitHub returned an invalid canonical repository name.',502,kind='response') from None
        result['clone_url']='https://github.com/'+value['full_name']+'.git'
        return result

    def get_user(self):
        value=self._request('GET','/user')
        if not isinstance(value,dict) or not isinstance(value.get('id'),int) or isinstance(value.get('id'),bool) or value.get('id',0)<=0 or not isinstance(value.get('login'),str):
            raise GitHubError('GitHub did not return a verified account identity.',502,kind='response')
        return {key:value.get(key) for key in ('id','login','name','avatar_url','html_url','type') if key in value}

    def list_repositories(self, page=1, per_page=100):
        self._pagination(page,per_page)
        values=self._request('GET','/user/repos',params={'page':page,'per_page':per_page,'sort':'updated','affiliation':'owner,collaborator,organization_member'})
        if not isinstance(values,list): raise GitHubError('GitHub returned an invalid repository list.',502,kind='response')
        return [self._repository(value) for value in values]

    @staticmethod
    def _pagination(page,per_page):
        if not isinstance(page,int) or isinstance(page,bool) or not 1<=page<=1000 or not isinstance(per_page,int) or not 1<=per_page<=100:
            raise GitHubError('Choose a repository page and page size between 1 and 100.',422,kind='validation')

    def get_repository(self,owner,repo):
        return self._repository(self._request('GET',f'/repos/{_component(owner,True)}/{_component(repo)}'))

    def list_branches(self,owner,repo,page=1,per_page=100):
        self._pagination(page,per_page)
        values=self._request('GET',f'/repos/{_component(owner,True)}/{_component(repo)}/branches',params={'page':page,'per_page':per_page})
        if not isinstance(values,list):raise GitHubError('GitHub returned an invalid branch list.',502,kind='response')
        try:
            return [{'name':item['name'],'commit':{'sha':_sha(item['commit']['sha'])},'protected':bool(item.get('protected'))} for item in values]
        except (KeyError,TypeError):
            raise GitHubError('GitHub returned incomplete branch metadata.',502,kind='response') from None

    def create_repository(self,name,*,owner=None,visibility='private',description='',auto_init=True):
        _component(name)
        if visibility not in {'private','public'} or not isinstance(description,str) or len(description)>2000:
            raise GitHubError('Choose private/public visibility and a concise repository description.',422,kind='validation')
        user=self.get_user()
        route='/user/repos' if owner is None or owner.lower()==user['login'].lower() else f'/orgs/{_component(owner,True)}/repos'
        value=self._request('POST',route,payload={'name':name,'private':visibility=='private','visibility':visibility,
                            'description':description,'auto_init':bool(auto_init)})
        return self._repository(value)

    def get_head(self,owner,repo,branch):
        value=self._request('GET',f'/repos/{_component(owner,True)}/{_component(repo)}/git/ref/heads/{_branch(branch)}')
        try:return _sha(value['object']['sha'])
        except (KeyError,TypeError):raise GitHubError('GitHub returned an invalid branch reference.',502,kind='response') from None

    def create_branch(self,owner,repo,branch,*,from_branch=None,sha=None):
        _branch(branch)
        if sha is None:
            base=from_branch or self.get_repository(owner,repo).get('default_branch')
            if not base:raise GitHubError('Initialize the empty repository before creating a branch.',409,kind='empty')
            sha=self.get_head(owner,repo,base)
        return self._request('POST',f'/repos/{_component(owner,True)}/{_component(repo)}/git/refs',
                             payload={'ref':'refs/heads/'+branch,'sha':_sha(sha)})

    def read_tree(self,owner,repo,ref,recursive=True):
        if not isinstance(ref,str) or not ref:raise GitHubError('Select a Git tree or commit reference.',422,kind='validation')
        value=self._request('GET',f'/repos/{_component(owner,True)}/{_component(repo)}/git/trees/{quote(ref,safe="")}',
                            params={'recursive':'1'} if recursive else None)
        if not isinstance(value,dict) or not isinstance(value.get('tree'),list):
            raise GitHubError('GitHub returned an invalid repository tree.',502,kind='response')
        if value.get('truncated'):
            raise GitHubError('The repository tree exceeds the safe complete-read limit.',413,kind='limit',
                              next_action='Use a smaller project repository; partial knowledge trees are not accepted.')
        return value

    def _blob(self,owner,repo,sha):
        value=self._request('GET',f'/repos/{_component(owner,True)}/{_component(repo)}/git/blobs/{_sha(sha)}')
        try:
            if value.get('encoding')!='base64' or value.get('size',0)>2_000_000:raise ValueError()
            data=base64.b64decode(''.join(value['content'].split()),validate=True)
            if len(data)>2_000_000:raise ValueError()
            return data
        except (ValueError,TypeError,KeyError):
            raise GitHubError('The selected GitHub file is not a supported small file.',413,kind='limit') from None

    def read_file(self,owner,repo,path,ref):
        path=_path(path)
        value=self._request('GET',f'/repos/{_component(owner,True)}/{_component(repo)}/contents/{quote(path,safe="/")}',params={'ref':ref},missing=True)
        if value is None:return None
        if not isinstance(value,dict) or value.get('type')!='file':
            raise GitHubError('The selected path is not a regular repository file.',422,kind='validation',paths=[path])
        return self._blob(owner,repo,value['sha'])

    def recent_commits(self,owner,repo,branch,per_page=20):
        self._pagination(1,per_page)
        values=self._request('GET',f'/repos/{_component(owner,True)}/{_component(repo)}/commits',params={'sha':branch,'per_page':per_page})
        if not isinstance(values,list):raise GitHubError('GitHub returned an invalid commit list.',502,kind='response')
        return [{'sha':item['sha'],'html_url':item.get('html_url'),'message':item.get('commit',{}).get('message',''),
                 'author':(item.get('author') or {}).get('login'),'committed_at':item.get('commit',{}).get('committer',{}).get('date')} for item in values]

    def invite_collaborator(self,owner,repo,username,permission='push'):
        if permission not in {'pull','triage','push','maintain','admin'}:
            raise GitHubError('Choose an explicit supported GitHub collaborator permission.',422,kind='validation')
        return self._request('PUT',f'/repos/{_component(owner,True)}/{_component(repo)}/collaborators/{_component(username,True)}',payload={'permission':permission})

    def _commit_tree(self,owner,repo,commit):
        value=self._request('GET',f'/repos/{_component(owner,True)}/{_component(repo)}/git/commits/{_sha(commit)}')
        try:tree=_sha(value['tree']['sha'])
        except (KeyError,TypeError):raise GitHubError('GitHub returned an incomplete commit.',502,kind='response') from None
        return tree,{item['path']:item for item in self.read_tree(owner,repo,tree)['tree'] if item.get('type') in {'blob','commit'}}

    def commit_files(self,owner,repo,branch,files,*,expected_head,message,expected_files=None,max_attempts=3):
        expected_head=_sha(expected_head);_branch(branch)
        if not isinstance(files,dict) or not files or len(files)>100 or not isinstance(message,str) or not message.strip() or len(message)>2000:
            raise GitHubError('Provide 1-100 files, a pinned head, and a concise commit message.',422,kind='validation')
        if not isinstance(max_attempts,int) or not 1<=max_attempts<=3:
            raise GitHubError('GitHub update attempts must be bounded between one and three.',422,kind='validation')
        content={}
        for path,value in files.items():
            _path(path)
            if not isinstance(value,(str,bytes)):raise GitHubError('Repository file content must be text or bytes.',422,kind='validation')
            data=value.encode('utf-8') if isinstance(value,str) else value
            if len(data)>2_000_000:raise GitHubError('Store large outputs outside the GitHub knowledge record.',413,kind='limit',paths=[path])
            try:guard_output_bytes(data,[self._token.encode()] if len(self._token)>=8 else [])
            except ProviderError:raise GitHubError('A possible credential was found in a proposed repository file.',422,kind='credential',paths=[path]) from None
            content[path]=data
        if sum(map(len,content.values()))>10_000_000:raise GitHubError('The proposed repository update is too large.',413,kind='limit')
        if len({path.casefold() for path in content})!=len(content) or any(first!=second and second.casefold().startswith(first.casefold()+'/') for first in content for second in content):
            raise GitHubError('Proposed filenames collide on case-insensitive filesystems.',422,kind='validation')
        _portable_paths(content)
        _,baseline=self._commit_tree(owner,repo,expected_head)
        if expected_files is not None:
            if not isinstance(expected_files,dict) or set(expected_files)!=set(content):
                raise GitHubError('Expected file hashes must pin every proposed file.',422,kind='validation')
            for path,expected in expected_files.items():
                if expected is not None and (not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected)):
                    raise GitHubError('Expected file hashes must be SHA256 strings or null for absent paths.',422,kind='validation')
                previous=baseline.get(path)
                actual=hashlib.sha256(self._blob(owner,repo,previous['sha'])).hexdigest() if previous else None
                if actual!=expected:raise GitHubError('A proposed file differs from its pinned input version.',409,kind='conflict',paths=[path])
        blobs={}
        route=f'/repos/{_component(owner,True)}/{_component(repo)}'
        for attempt in range(1,max_attempts+1):
            head=self.get_head(owner,repo,branch)
            tree,current=self._commit_tree(owner,repo,head)
            _portable_paths([*current,*content])
            changed=[path for path in content if current.get(path)!=baseline.get(path)]
            if changed:raise GitHubError('Another participant changed a file in this proposal.',409,kind='conflict',paths=changed,
                                          next_action='Read the latest files, reconcile the proposal, and use a fresh project context.')
            for path in content:
                existing=current.get(path)
                if existing and (existing.get('type')!='blob' or existing.get('mode') not in {'100644','100755'}):
                    raise GitHubError('A proposed path replaces a symlink or submodule.',409,kind='conflict',paths=[path])
                for other in current:
                    if other!=path and (other.casefold()==path.casefold() or path.startswith(other+'/') or other.startswith(path+'/')):
                        raise GitHubError('A proposed path conflicts with an existing file or directory.',409,kind='conflict',paths=[path,other])
                if path not in blobs:
                    blobs[path]=_sha(self._request('POST',route+'/git/blobs',payload={'content':base64.b64encode(content[path]).decode(),'encoding':'base64'})['sha'])
            entries=[{'path':path,'mode':current.get(path,{}).get('mode','100644'),'type':'blob','sha':blobs[path]} for path in content]
            new_tree=_sha(self._request('POST',route+'/git/trees',payload={'base_tree':tree,'tree':entries})['sha'])
            commit=_sha(self._request('POST',route+'/git/commits',payload={'message':message,'tree':new_tree,'parents':[head]})['sha'])
            try:
                self._request('PATCH',route+'/git/refs/heads/'+_branch(branch),payload={'sha':commit,'force':False})
            except GitHubError as error:
                if error.kind=='unavailable':
                    if self.get_head(owner,repo,branch)==commit:
                        return {'commit':commit,'previous_head':head,'branch':branch,'repository':owner+'/'+repo,'attempts':attempt,'reconciled':True}
                    raise
                if error.status in {409,422} and self.get_head(owner,repo,branch)!=head and attempt<max_attempts:
                    continue
                raise
            return {'commit':commit,'previous_head':head,'branch':branch,'repository':owner+'/'+repo,'attempts':attempt,'files':list(content)}
        raise GitHubError('The branch kept changing; no forced update was attempted.',409,kind='conflict')
