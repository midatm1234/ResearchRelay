"""Explicit credential-free GitHub simulator, backed by real local bare Git."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
import time

from .github_client import GitHubError

@dataclass
class DemoIdentity:
    github_user_id: int
    login: str
    token: str = field(default="local-demo-no-credential",repr=False)
    def public(self):
        return dict(github_user_id=self.github_user_id,login=self.login,name=self.login.title())

class DemoAuth:
    configured = True
    def __init__(self,hub):
        self.hub = hub
        with hub.tx() as db:
            db.execute("CREATE TABLE IF NOT EXISTS demo_sessions(hash TEXT PRIMARY KEY,login TEXT,expires REAL)")
    def sign_in(self,login):
        if login not in {"alice","bob","reader"}:
            raise GitHubError("Choose alice, bob or reader in the local demonstration.",422)
        token = secrets.token_urlsafe(32)
        with self.hub.tx() as db:
            db.execute("INSERT INTO demo_sessions VALUES(?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),login,time.time()+28800))
        return token
    def identity(self,session_cookie=None,bearer=None):
        if bearer:
            if bearer in {"local-demo-alice","local-demo-bob","local-demo-reader"}:
                login = bearer.removeprefix("local-demo-")
                return DemoIdentity({"alice":1,"bob":2,"reader":3}[login],login)
            raise GitHubError("Use a documented local-demo participant token; real GitHub credentials are not accepted in demonstration mode.",401)
        with self.hub.tx() as db:
            row = db.execute("SELECT login FROM demo_sessions WHERE hash=? AND expires>?",
                (hashlib.sha256((session_cookie or "").encode()).hexdigest(),time.time())).fetchone()
        if not row:
            raise GitHubError("Sign in as a local demo participant.",401)
        login = row[0]
        return DemoIdentity({"alice":1,"bob":2,"reader":3}[login],login)
    def logout(self,session_cookie):
        with self.hub.tx() as db:
            db.execute("DELETE FROM demo_sessions WHERE hash=?",(hashlib.sha256((session_cookie or "").encode()).hexdigest(),))

class LocalGitHubClient:
    """No network or real account mutations; same interface as GitHubClient."""
    def __init__(self,root,identity):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.identity = identity
    def _path(self,owner,repo):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+",owner) or not re.fullmatch(r"[A-Za-z0-9_.-]+",repo) or owner in {".",".."} or repo in {".",".."}:
            raise GitHubError("Invalid demo repository name.",422)
        return self.root/owner/(repo+".git")
    def _git(self,path,*args,input=None,check=True,env=None):
        result = subprocess.run(["git","-C",str(path),*args],input=input,capture_output=True,timeout=30,env=env)
        if check and result.returncode:
            raise GitHubError("Local demonstration Git operation failed; inspect the selected branch.",409)
        return result
    def _write(self):
        if self.identity.login=="reader":
            raise GitHubError("The reader demonstration account has read-only repository permissions.",403)
    def get_user(self):
        return dict(self.identity.public(),id=self.identity.github_user_id)
    def get_repository(self,owner,repo):
        path = self._path(owner,repo)
        if not (path/"HEAD").exists():
            raise GitHubError("Repository was not found in the local demonstration.",404)
        meta = json.loads((path/"researchrelay-demo.json").read_text())
        return dict(id=hashlib.sha256(str(path).encode()).hexdigest()[:12],name=repo,full_name=owner+"/"+repo,
            private=meta["visibility"]=="private",default_branch="main",clone_url=str(path),ssh_url=str(path),
            html_url="",permissions=dict(pull=True,push=self.identity.login!="reader",admin=self.identity.login==owner))
    def list_repositories(self,page=1,per_page=100):
        found = [self.get_repository(p.parent.name,p.name[:-4]) for p in sorted(self.root.glob("*/*.git"))]
        return found[(page-1)*per_page:page*per_page]
    def create_repository(self,name,*,owner=None,visibility="private",description="",auto_init=True):
        self._write()
        owner = owner or self.identity.login
        if owner!=self.identity.login:
            raise GitHubError("Demo repositories must be created in your own account.",403)
        path = self._path(owner,name)
        if path.exists():
            raise GitHubError("A repository with this name already exists; connect it instead.",422)
        path.parent.mkdir(parents=True,exist_ok=True)
        subprocess.run(["git","init","--bare","--initial-branch=main",str(path)],capture_output=True,check=True,timeout=20)
        (path/"researchrelay-demo.json").write_text(json.dumps(dict(visibility=visibility,description=description)))
        if auto_init:
            with tempfile.TemporaryDirectory(dir=self.root) as temporary:
                work = Path(temporary)
                self._git(work,"init","--initial-branch=main")
                (work/"README.md").write_bytes(("# "+name+"\n").encode("utf-8"))
                self._git(work,"add","README.md")
                self._git(work,"-c","user.name=Local Demo","-c","user.email=demo@localhost.invalid","commit","-m","Initialize local demonstration repository")
                self._git(work,"push",str(path),"HEAD:refs/heads/main")
        return self.get_repository(owner,name)
    def get_head(self,owner,repo,branch):
        result = self._git(self._path(owner,repo),"rev-parse","--verify","refs/heads/"+branch,check=False)
        if result.returncode:
            raise GitHubError("Branch not found.",404)
        return result.stdout.decode().strip()
    def list_branches(self,owner,repo,page=1,per_page=100):
        rows = self._git(self._path(owner,repo),"for-each-ref","--format=%(refname:short) %(objectname)","refs/heads").stdout.decode().splitlines()
        return [dict(name=row.split()[0],commit=dict(sha=row.split()[1])) for row in rows][(page-1)*per_page:page*per_page]
    def create_branch(self,owner,repo,branch,*,from_branch=None,sha=None):
        self._write()
        path = self._path(owner,repo)
        if self._git(path,"check-ref-format","refs/heads/"+branch,check=False).returncode:
            raise GitHubError("Invalid branch name.",422)
        source = sha or self.get_head(owner,repo,from_branch or "main")
        result = self._git(path,"update-ref","refs/heads/"+branch,source,"0"*40,check=False)
        if result.returncode:
            raise GitHubError("That branch already exists; choose another name or connect it.",409)
        return dict(ref="refs/heads/"+branch,object=dict(sha=source))
    def read_file(self,owner,repo,path,ref):
        result = self._git(self._path(owner,repo),"cat-file","blob",ref+":"+path,check=False)
        return result.stdout if result.returncode==0 else None
    def read_tree(self,owner,repo,ref,recursive=True):
        args = ["ls-tree","-z"]+(["-r"] if recursive else [])+[ref]
        rows = self._git(self._path(owner,repo),*args).stdout.split(b"\0")
        return dict(truncated=False,tree=[dict(path=row.split(b"\t",1)[1].decode(),mode=row.split()[0].decode(),
             type=row.split()[1].decode(),sha=row.split()[2].decode()) for row in rows if row])
    def commit_files(self,owner,repo,branch,files,*,expected_head,message,expected_files=None,max_attempts=3):
        self._write()
        path = self._path(owner,repo)
        if self.get_head(owner,repo,branch)!=expected_head:
            raise GitHubError("The branch changed. Refresh and reconcile before retrying.",409)
        with tempfile.TemporaryDirectory(dir=self.root) as temporary:
            index = str(Path(temporary)/"index")
            environment = dict(os.environ,GIT_INDEX_FILE=index,GIT_AUTHOR_NAME=self.identity.login,
                GIT_AUTHOR_EMAIL=self.identity.login+"@localhost.invalid",GIT_COMMITTER_NAME="ResearchRelay local demonstration",
                GIT_COMMITTER_EMAIL="demo@localhost.invalid")
            self._git(path,"read-tree",expected_head,env=environment)
            for name,content in files.items():
                if expected_files is not None:
                    expected = expected_files.get(name)
                    actual = self.read_file(owner,repo,name,expected_head)
                    # Client contract uses exact bytes for expected file contents.
                    if expected != (hashlib.sha256(actual).hexdigest() if actual is not None else None):
                        raise GitHubError("An initialization file changed; existing content was preserved.",409)
                blob = self._git(path,"hash-object","-w","--stdin",input=content.encode() if isinstance(content,str) else content).stdout.decode().strip()
                self._git(path,"update-index","--add","--cacheinfo","100644",blob,name,env=environment)
            tree = self._git(path,"write-tree",env=environment).stdout.decode().strip()
            commit = self._git(path,"commit-tree",tree,"-p",expected_head,input=message.encode(),env=environment).stdout.decode().strip()
            result = self._git(path,"update-ref","refs/heads/"+branch,commit,expected_head,check=False)
            if result.returncode:
                raise GitHubError("Concurrent update detected. Existing contributions were preserved.",409)
        return dict(sha=commit,commit=commit)
    def recent_commits(self,owner,repo,branch,per_page=20):
        data = self._git(self._path(owner,repo),"log",str(self.get_head(owner,repo,branch)),"-"+str(per_page),
            "--format=%H%x00%s%x00%an%x00%aI").stdout.decode().splitlines()
        return [dict(sha=parts[0],commit=dict(message=parts[1],author=dict(name=parts[2],date=parts[3])),html_url="")
                for parts in (row.split("\0") for row in data)]
    def invite_collaborator(self,*args,**kwargs):
        raise GitHubError("Demo collaborators already have local access; no invitations were sent.",409)
