"""Durable project catalog. Execution remains in one isolated Engine per project."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

from .config import Settings
from .knowledge import parse_knowledge, render_knowledge

class HubError(ValueError):
    def __init__(self,message,status=409,*,next_action=None,operation=None):
        super().__init__(message)
        self.status = status
        self.next_action = next_action or "Refresh the project and retry after reviewing the repository."
        self.operation = operation

class ProjectHub:
    """A single-process catalog with durable, idempotent provisioning checkpoints."""
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.hub_path.resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.db_path = self.root/"catalog.db"
        self.lock = threading.RLock()
        self.apps = {}
        self.operation_locks = {}
        self.lock_guard = threading.Lock()
        self.auth = None
        self.client_factory = None
        with self.tx() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, binding TEXT UNIQUE NOT NULL,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memberships(project_id TEXT,user_id TEXT,login TEXT,
              PRIMARY KEY(project_id,user_id));
            CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY,actor_id TEXT,payload_hash TEXT,
              data TEXT NOT NULL);
            """)

    @contextmanager
    def tx(self):
        db = sqlite3.connect(self.db_path,timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def operation_lock(self,key):
        with self.lock_guard:
            return self.operation_locks.setdefault(key,threading.RLock())

    def operation(self, request_id, identity):
        with self.tx() as db:
            row = db.execute("SELECT * FROM operations WHERE id=?",(request_id,)).fetchone()
        if not row or row["actor_id"]!=str(identity.github_user_id):
            raise HubError("Project creation request was not found.",404)
        return json.loads(row["data"])

    def checkpoint(self,operation):
        state = operation.get("state")
        if isinstance(state,str) and state in {"running","failed","needs_reconciliation"}:
            operation["status"] = state
        steps = operation.get("steps") or {}
        if operation.get("status")=="completed":
            operation["phase"] = "ready"
        elif steps.get("initialization_commit") or state=="completed":
            operation["phase"] = "register_project"
        elif (steps.get("initialization") or {}).get("pending"):
            operation["phase"] = "initialize_files"
        elif steps.get("branch_create_pending"):
            operation["phase"] = "create_branch"
        elif steps.get("repository_create_pending"):
            operation["phase"] = "create_repository"
        else:
            operation["phase"] = "check_repository"
        with self.tx() as db:
            db.execute("UPDATE operations SET data=? WHERE id=?",(json.dumps(operation),operation["id"]))

    @staticmethod
    def binding(repository,branch,prefix):
        return json.dumps([repository.casefold(),branch,prefix],separators=(",",":"))

    def record(self,project_id):
        with self.tx() as db:
            row = db.execute("SELECT data FROM projects WHERE id=?",(project_id,)).fetchone()
        if not row:
            raise HubError("Project not found. Open Projects to create or join one.",404)
        return json.loads(row[0])

    def permission(self,identity,project):
        repository = self.client_factory(identity).get_repository(*project["repository"].split("/"))
        perms = repository.get("permissions") or {}
        if not (perms.get("pull") or perms.get("push") or perms.get("admin") or not repository.get("private",True)):
            raise HubError("Your GitHub account does not have access to this repository.",403)
        return "admin" if perms.get("admin") else ("write" if perms.get("push") else "read")

    def public(self, project, role=None):
        public = {key:value for key,value in project.items() if key not in {"clone_url"}}
        public.update(url=f"/projects/{project['id']}",role=role or "read")
        app = self.apps.get(project["id"])
        public["sync"] = app.state.project_sync.status() if app else {"status":"pending","latest_commit":project.get("commit")}
        return public

    def list_projects(self,identity):
        with self.tx() as db:
            rows = db.execute("""SELECT p.data FROM projects p JOIN memberships m ON p.id=m.project_id
                                  WHERE m.user_id=? ORDER BY p.rowid DESC""",(str(identity.github_user_id),)).fetchall()
        result = []
        for row in rows:
            project = json.loads(row[0])
            try:
                role = self.permission(identity,project)
            except Exception as error:
                # Revoked GitHub access hides private metadata, including titles.
                from .github_client import GitHubError
                if isinstance(error,HubError) and error.status==403 or isinstance(error,GitHubError) and error.status in {401,403,404}:
                    continue
                raise
            result.append(self.public(project,role))
        return result

    def register(self, identity, data):
        binding = self.binding(data["repository"],data["branch"],data["knowledge_path"])
        with self.tx() as db:
            row = db.execute("SELECT data FROM projects WHERE binding=?",(binding,)).fetchone()
            if row:
                project = json.loads(row[0])
            else:
                project = dict(data)
                collision = db.execute("SELECT binding FROM projects WHERE id=?",(project["id"],)).fetchone()
                if collision and collision[0]!=binding:
                    project["artifact_project_id"] = project.get("artifact_project_id",project["id"])
                    project["id"] = project["id"][:90]+"-"+hashlib.sha256(binding.encode()).hexdigest()[:16]
                db.execute("INSERT INTO projects VALUES(?,?,?)",(project["id"],binding,json.dumps(project)))
            db.execute("INSERT OR REPLACE INTO memberships VALUES(?,?,?)",
                       (project["id"],str(identity.github_user_id),identity.login))
        return project

    def create(self,identity,payload):
        from .project_provisioning import ProjectProvisioner
        from .project_templates import clean_project_input
        try:
            clean_project_input(payload)
        except ValueError as error:
            raise HubError(str(error),422) from error
        request_id = payload.get("request_id","")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",request_id):
            raise HubError("A stable request_id is required for safe retries.",422)
        digest = hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        with self.operation_lock("create:"+request_id):
            with self.tx() as db:
                row = db.execute("SELECT * FROM operations WHERE id=?",(request_id,)).fetchone()
                if row:
                    if row["actor_id"]!=str(identity.github_user_id) or row["payload_hash"]!=digest:
                        raise HubError("This request ID already belongs to a different request. Start a new project request.",409)
                    operation = json.loads(row["data"])
                else:
                    slug = re.sub(r"[^a-z0-9]+","-",payload.get("name","").lower()).strip("-")[:60] or "research"
                    project_id = slug+"-"+uuid.uuid4().hex[:12]
                    operation = dict(id=request_id,project_id=project_id,actor=identity.login,
                                     input=payload,original_input=dict(payload),state="pending",steps={},status="pending",created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()))
                    db.execute("INSERT INTO operations VALUES(?,?,?,?)",(request_id,str(identity.github_user_id),digest,json.dumps(operation)))
            if operation.get("status")=="completed" and operation.get("project"):
                project = self.record(operation["project"]["id"])
                return dict(project=self.public(project,self.permission(identity,project)),operation=operation)
            try:
                if payload.get("initialize",True) is False:
                    project = self.join(identity,payload)
                    operation.update(status="completed",project=project)
                    self.checkpoint(operation)
                    return dict(project=self.public(project,self.permission(identity,project)),operation=operation)
                result = ProjectProvisioner(self.client_factory(identity),self.checkpoint).run(operation)
                repository = result["repository"]
                full_name = repository["full_name"] if isinstance(repository,dict) else repository
                repo = self.client_factory(identity).get_repository(*full_name.split("/"))
                project = self.register(identity,dict(id=result.get("project_id",operation["project_id"]),
                    name=payload["name"],description=payload.get("description",""),objectives=payload.get("objectives",""),
                    collaborators=payload.get("collaborators",[]),repository=full_name,branch=result["branch"],
                    knowledge_path=result["knowledge_path"],clone_url=repo.get("clone_url") or f"https://github.com/{full_name}.git",
                    commit=result["commit"],created_by=identity.login,created_at=operation["created_at"]))
                operation.update(status="completed",project=project)
                self.checkpoint(operation)
                return dict(project=self.public(project,self.permission(identity,project)),operation=operation)
            except Exception as error:
                operation["status"] = "failed"
                operation["error"] = dict(message=str(error),kind=getattr(error,"kind","error"))
                operation["next_action"] = getattr(error,"next_action","Inspect any resources listed in this operation; retry the exact request to resume safely. No resources were deleted.")
                self.checkpoint(operation)
                if hasattr(error,"operation"):
                    error.operation = operation
                    raise
                raise HubError(str(error),getattr(error,"status",503),next_action=operation["next_action"],operation=operation) from error

    def join(self,identity,payload):
        repository = payload["repository"]
        branch = payload.get("branch") or self.client_factory(identity).get_repository(*repository.split("/"))["default_branch"]
        prefix = payload.get("knowledge_path","").rstrip("/")
        if not prefix:
            raise HubError("Enter the existing project's knowledge folder to join it.",422)
        from .project_templates import knowledge_path_for
        try:
            prefix = knowledge_path_for(prefix,"existing")
        except ValueError as error:
            raise HubError(str(error),422) from error
        # Read-only discovery: no commits or remote changes.
        client = self.client_factory(identity)
        repo = client.get_repository(*repository.split("/"))
        head = client.get_head(*repository.split("/"),branch)
        raw = client.read_file(*repository.split("/"),prefix+"/PROJECT.md",head)
        if raw is None:
            raise HubError("No ResearchRelay PROJECT.md was found in this folder.",404,
                           next_action="Check the repository, branch and knowledge folder, or initialize a new project.")
        metadata,body = parse_knowledge(raw.decode("utf-8-sig"),path=prefix+"/PROJECT.md")
        project_id = metadata["project_id"]
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",project_id):
            raise HubError("The shared project ID is not a safe identifier.",422)
        project = dict(id=project_id,name=metadata.get("title") or payload.get("name") or project_id,
                       description=metadata.get("description",payload.get("description","")),objectives=metadata.get("research_objectives",payload.get("objectives","")),
                       collaborators=metadata.get("collaborators",payload.get("collaborators",[])),repository=repository,branch=branch,
                       knowledge_path=prefix,clone_url=repo.get("clone_url") or f"https://github.com/{repository}.git",commit=head,
                       created_by=metadata.get("responsible_participant","unknown"),created_at=metadata["created_at"])
        self.permission(identity,project)
        # Different bindings may share external IDs. Keep coordinator directory IDs unique.
        with self.tx() as db:
            collision = db.execute("SELECT binding FROM projects WHERE id=?",(project_id,)).fetchone()
        binding = self.binding(repository,branch,prefix)
        if collision and collision[0]!=binding:
            project["id"] = project_id+"-"+hashlib.sha256(binding.encode()).hexdigest()[:8]
        project["artifact_project_id"] = project_id
        return self.register(identity,project)

    def refresh_metadata(self,identity,project):
        client = self.client_factory(identity)
        owner,repo = project["repository"].split("/")
        head = client.get_head(owner,repo,project["branch"])
        name = project["knowledge_path"]+"/PROJECT.md"
        raw = client.read_file(owner,repo,name,head)
        if raw is not None:
            metadata,_ = parse_knowledge(raw.decode("utf-8-sig"),path=name)
            expected = project.get("artifact_project_id",project["id"])
            if metadata["project_id"]!=expected:
                raise HubError("The repository's PROJECT.md now belongs to another project. Reconcile the file before continuing.",409)
            for key,field in (("name","title"),("description","description"),("objectives","research_objectives"),("collaborators","collaborators")):
                if field in metadata:
                    project[key] = metadata[field]
        project["commit"] = head
        with self.tx() as db:
            db.execute("UPDATE projects SET data=? WHERE id=?",(json.dumps(project),project["id"]))
        return project

    def update(self,identity,project_id,changes):
        with self.operation_lock("settings:"+project_id):
            project = self.record(project_id)
            if self.permission(identity,project) not in {"write","admin"}:
                raise HubError("Write access is required to edit project settings.",403)
            client = self.client_factory(identity)
            owner,repo = project["repository"].split("/")
            head = client.get_head(owner,repo,project["branch"])
            name = project["knowledge_path"]+"/PROJECT.md"
            raw = client.read_file(owner,repo,name,head)
            if raw is None:
                raise HubError("PROJECT.md is missing; project settings were not changed.",409)
            metadata,body = parse_knowledge(raw.decode("utf-8-sig"),project_id=project.get("artifact_project_id",project_id),path=name)
            for key in ("name","description","objectives","collaborators"):
                if key in changes:
                    project[key] = changes[key]
            metadata.update(title=project["name"],description=project["description"],
                research_objectives=project["objectives"],collaborators=project["collaborators"],
                responsible_participant=identity.login,producing_agent="researchrelay/project-settings",
                version=metadata["version"]+1,updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ",time.gmtime()))
            metadata["generated"] = dict(by="researchrelay/project-settings",at=metadata["updated_at"])
            content = render_knowledge(metadata,body+"\\n\\n## Project settings update\\n\\n"+
                project["name"]+"\\n\\n"+project["description"]+"\\n\\nResearch objectives:\\n"+project["objectives"]+"\\n")
            result = client.commit_files(owner,repo,project["branch"],{name:content},expected_head=head,
                expected_files={name:hashlib.sha256(raw).hexdigest()},
                message=f"Update ResearchRelay project settings\\n\\nResearchRelay-Participant: {identity.login}\\nResearchRelay-Agent: researchrelay/project-settings")
            project["commit"] = result["commit"]
            with self.tx() as db:
                db.execute("UPDATE projects SET data=? WHERE id=?",(json.dumps(project),project_id))
            return self.public(project,self.permission(identity,project))

    def child(self,project_id):
        cached = self.apps.get(project_id)
        if cached is not None:
            return cached
        with self.lock:
            if project_id not in self.apps:
                from .api import create_app
                from .managed_context import ManagedProjectSync
                from .engine import Engine
                project = self.record(project_id)
                path = self.root/"projects"/hashlib.sha256(project_id.encode()).hexdigest()[:16]
                settings = replace(self.settings,db_path=path/"state.db",repo_path=path/"record",
                    project_id=project.get("artifact_project_id",project_id),tokens={},github_url=project["clone_url"],
                    github_branch=project["branch"],knowledge_path=project["knowledge_path"])
                engine = Engine(settings.db_path,settings.project_id)
                sync = ManagedProjectSync(settings,engine)
                engine.recover_jobs()
                self.apps[project_id] = create_app(settings,engine,include_hub=False,synchronizer=sync)
                self.apps[project_id].servers = [{"url":f"/projects/{project_id}"}]
            return self.apps[project_id]
