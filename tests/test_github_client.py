"""GitHub protocol checks with mocked HTTP; no live account resources are created."""
import base64
import hashlib
import json

import httpx
import pytest

from researchrelay.github_client import GitHubClient,GitHubError

A='a'*40;B='b'*40;C='c'*40;D='d'*40
T1='1'*40;T2='2'*40;T3='3'*40
OLD='4'*40;OTHER1='5'*40;OTHER2='6'*40;NEW='7'*40


class GitStore:
    def __init__(self,*,race=False,touched=False):
        self.head=A
        self.race=race;self.touched=touched;self.patch_calls=0;self.posts=[];self.requests=[]
    def __call__(self,request):
        self.requests.append(request)
        assert request.url.host=='api.github.com'
        assert request.headers['Authorization']=='Bearer participant-private-token'
        route=request.url.path
        if request.method=='GET' and '/git/ref/heads/' in route:return httpx.Response(200,json={'object':{'sha':self.head}})
        if request.method=='GET' and '/git/commits/' in route:
            sha=route.rsplit('/',1)[1]
            return httpx.Response(200,json={'tree':{'sha':T1 if sha==A else T2}})
        if request.method=='GET' and '/git/trees/' in route:
            tree=route.rsplit('/',1)[1]
            entries=[{'path':'finding.md','mode':'100644','type':'blob','sha':NEW if self.touched and tree==T2 else OLD},
                     {'path':'unrelated.md','mode':'100644','type':'blob','sha':OTHER1 if tree==T1 else OTHER2}]
            return httpx.Response(200,json={'sha':tree,'tree':entries,'truncated':False})
        if request.method=='GET' and '/git/blobs/' in route:
            return httpx.Response(200,json={'encoding':'base64','content':base64.b64encode(b'old finding').decode(),'size':11})
        payload=json.loads(request.content)
        if request.method=='POST':
            self.posts.append((route,payload))
            sha=NEW if route.endswith('/blobs') else T3 if route.endswith('/trees') else C
            return httpx.Response(201,json={'sha':sha})
        if request.method=='PATCH':
            self.patch_calls+=1
            assert payload['force'] is False
            if self.race and self.patch_calls==1:
                self.head=B
                return httpx.Response(422,json={'message':'Update is not a fast forward participant-private-token'})
            self.head=C
            return httpx.Response(200,json={'object':{'sha':C}})
        raise AssertionError(str(request.url))


def client(store):return GitHubClient('participant-private-token',transport=httpx.MockTransport(store))


def test_atomic_commit_preserves_unrelated_concurrent_files_and_never_force_updates():
    store=GitStore();store.head=B
    result=client(store).commit_files('alice','research','work',{'finding.md':'revised finding'},expected_head=A,message='Record finding',
              expected_files={'finding.md':hashlib.sha256(b'old finding').hexdigest()})
    tree=next(payload for route,payload in store.posts if route.endswith('/trees'))
    commit=next(payload for route,payload in store.posts if route.endswith('/commits'))
    assert tree['base_tree']==T2 and len(tree['tree'])==1
    assert commit['parents']==[B] and result['commit']==C
    assert store.patch_calls==1


def test_ref_race_retries_against_latest_tree_with_bounded_nonforce_update():
    store=GitStore(race=True)
    result=client(store).commit_files('alice','research','work',{'finding.md':'revised'},expected_head=A,message='Record finding')
    assert store.patch_calls==2 and result['attempts']==2
    assert [payload['base_tree'] for route,payload in store.posts if route.endswith('/trees')]==[T1,T2]
    assert sum(route.endswith('/blobs') for route,payload in store.posts)==1


def test_conflicting_file_change_is_reported_before_any_mutating_api_call():
    store=GitStore(touched=True);store.head=B
    with pytest.raises(GitHubError) as error:
        client(store).commit_files('alice','research','work',{'finding.md':'revised'},expected_head=A,message='Record finding')
    assert error.value.status==409 and error.value.paths==['finding.md']
    assert store.posts==[] and store.patch_calls==0


def test_wrong_expected_file_hash_is_not_silently_adopted():
    store=GitStore()
    with pytest.raises(GitHubError) as error:
        client(store).commit_files('alice','research','work',{'finding.md':'revised'},expected_head=A,message='Record finding',expected_files={'finding.md':None})
    assert error.value.status==409 and store.posts==[]


@pytest.mark.parametrize('status,headers,kind',[(401,{},'authentication'),(403,{},'permission'),(403,{'x-ratelimit-remaining':'0'},'rate_limit'),
                                              (429,{'retry-after':'20'},'rate_limit'),(404,{},'not_found'),(301,{'location':'https://untrusted.example/token'},'moved')])
def test_github_failures_are_actionable_and_do_not_echo_credentials_or_follow_redirects(status,headers,kind):
    calls=[]
    def failure(request):
        calls.append(request)
        return httpx.Response(status,headers=headers,json={'message':'participant-private-token private provider failure details'})
    with pytest.raises(GitHubError) as error:client(failure).get_user()
    assert error.value.kind==kind and error.value.next_action
    assert 'participant-private-token' not in str(error.value) and len(calls)==1


def test_repository_metadata_and_permissions_use_the_signed_in_user_without_token_fields():
    def github(request):
        assert request.url.path=='/user/repos'
        assert request.url.params['page']=='2' and request.url.params['per_page']=='50'
        return httpx.Response(200,json=[{'id':1,'full_name':'org/research','name':'research','private':True,'visibility':'private',
            'default_branch':'main','owner':{'login':'org','type':'Organization'},'permissions':{'pull':True,'push':False,'admin':False},
            'untrusted_token':'participant-private-token'}])
    repo=client(github).list_repositories(page=2,per_page=50)[0]
    assert repo['permissions']['push'] is False and repo['owner']['login']=='org'
    assert 'untrusted_token' not in repo


@pytest.mark.parametrize('owner,route',[(None,'/user/repos'),('alice','/user/repos'),('organization','/orgs/organization/repos')])
def test_repository_creation_is_explicit_private_and_uses_correct_owner_endpoint(owner,route):
    calls=[]
    def github(request):
        calls.append(request)
        if request.url.path=='/user':return httpx.Response(200,json={'id':1,'login':'alice'})
        assert request.url.path==route and request.method=='POST'
        data=json.loads(request.content);assert data['private'] is True and data['auto_init'] is True
        return httpx.Response(201,json={'full_name':(owner or 'alice')+'/research','name':'research','owner':{'login':owner or 'alice'},'default_branch':'main'})
    assert client(github).create_repository('research',owner=owner)['default_branch']=='main'
    assert len(calls)==2


def test_branch_creation_and_explicit_collaborator_invitation():
    calls=[]
    def github(request):
        calls.append(request)
        if request.method=='POST':
            assert request.url.path.endswith('/git/refs')
            assert json.loads(request.content)=={'ref':'refs/heads/project/review','sha':A}
            return httpx.Response(201,json={'ref':'refs/heads/project/review','object':{'sha':A}})
        assert request.method=='PUT' and request.url.path.endswith('/collaborators/bob')
        assert json.loads(request.content)=={'permission':'pull'}
        return httpx.Response(201,json={'id':123})
    c=client(github)
    c.create_branch('alice','research','project/review',sha=A)
    assert c.invite_collaborator('alice','research','bob',permission='pull')['id']==123


def test_incomplete_tree_is_never_treated_as_complete_project_context():
    with pytest.raises(GitHubError) as error:
        client(lambda request:httpx.Response(200,json={'tree':[],'truncated':True})).read_tree('alice','research',A)
    assert error.value.status==413


@pytest.mark.parametrize('files',[{'../escape.md':'x'},{'a':'x','a/b.md':'y'},{'same.md':'x','SAME.md':'y'},{'finding.md':'participant-private-token'}])
def test_unsafe_or_secret_output_never_reaches_github(files):
    calls=[]
    def forbidden(request):calls.append(request);raise AssertionError('Unsafe output must fail before network')
    with pytest.raises(GitHubError):client(forbidden).commit_files('alice','research','work',files,expected_head=A,message='Record finding')
    assert calls==[]


def test_file_read_uses_git_blob_bytes_not_untrusted_download_url():
    calls=[]
    def github(request):
        calls.append(request)
        if '/contents/' in request.url.path:
            assert request.url.params['ref']==A
            return httpx.Response(200,json={'type':'file','sha':OLD,'download_url':'https://untrusted.example/private-token'})
        return httpx.Response(200,json={'encoding':'base64','content':base64.b64encode(b'verified note').decode(),'size':13})
    assert client(github).read_file('alice','research','notes/source.md',A)==b'verified note'
    assert len(calls)==2 and all(request.url.host=='api.github.com' for request in calls)


def test_lost_ref_update_ack_is_reconciled_without_a_duplicate_commit():
    store=GitStore()
    def github(request):
        response=store(request)
        if request.method=='PATCH':raise httpx.ReadTimeout('Private transport detail',request=request)
        return response
    result=client(github).commit_files('alice','research','work',{'finding.md':'revised'},expected_head=A,message='Record finding')
    assert result['commit']==C and result['reconciled'] is True
    assert store.patch_calls==1
    assert sum(route.endswith('/commits') for route,payload in store.posts)==1


def test_ref_races_are_bounded_and_never_force_updated():
    store=GitStore();heads=[B,D,'e'*40]
    def github(request):
        if request.method=='PATCH':
            assert json.loads(request.content)['force'] is False
            store.patch_calls+=1;store.head=heads[store.patch_calls-1]
            return httpx.Response(422,json={'message':'Reference moved'})
        return store(request)
    with pytest.raises(GitHubError):
        client(github).commit_files('alice','research','work',{'finding.md':'revised'},expected_head=A,message='Record finding')
    assert store.patch_calls==3


def test_repository_clone_url_is_canonical_and_never_uses_provider_credentials():
    def github(request):
        return httpx.Response(200,json={'full_name':'alice/research','owner':{'login':'alice'},
            'clone_url':'https://private-token@untrusted.example/research.git','permissions':{'pull':True,'push':True}})
    repository=client(github).get_repository('alice','research')
    assert repository['clone_url']=='https://github.com/alice/research.git'
    assert 'private-token' not in json.dumps(repository)


@pytest.mark.parametrize('files',[
    {'FOO/x.md':'x','foo/y.md':'y'},
    {'caf\u00e9/x.md':'x','cafe\u0301/y.md':'y'},
])
def test_case_or_unicode_colliding_directories_fail_before_network(files):
    def forbidden(request):pytest.fail('Portable directory collision must fail before any GitHub API call')
    with pytest.raises(GitHubError) as error:
        client(forbidden).commit_files('alice','research','work',files,expected_head=A,message='Initialize project')
    assert error.value.status==409 and error.value.kind=='conflict'


def test_proposed_directory_spelling_cannot_collide_with_existing_repository():
    store=GitStore()
    def github(request):
        if request.method=='GET' and '/git/trees/' in request.url.path:
            return httpx.Response(200,json={'tree':[{'path':'Existing/file.md','sha':OLD,'type':'blob','mode':'100644'}],'truncated':False})
        return store(request)
    with pytest.raises(GitHubError):
        client(github).commit_files('alice','research','work',{'existing/new.md':'note'},expected_head=A,message='Add note')
    assert store.posts==[]
