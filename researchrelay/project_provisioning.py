"""Checkpointed project initialization using participant-authenticated GitHub APIs.

The caller durably stores every checkpoint. This module never deletes a remote
resource or overwrites an existing project document to recover a failed attempt.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re

from .github_client import GitHubError
from .project_templates import build_project_files, clean_project_input, knowledge_path_for, parse_project_identity, project_id_for


MODES = {"new_repository", "new_branch", "connect"}


def _time():
    return datetime.now(timezone.utc).isoformat()


def _branch(value):
    if (not isinstance(value,str) or not value or len(value)>240 or value.startswith(("/","-"))
            or value.endswith(("/",".")) or ".." in value or "//" in value or "@{" in value
            or any(ord(c)<33 or c in "~^:?*[\\" for c in value)
            or any(part.startswith(".") or part.endswith(".lock") for part in value.split("/"))):
        raise GitHubError("Choose a valid project branch name.",422,kind="validation")
    return value


def _parts(full_name):
    if not isinstance(full_name,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}",full_name):
        raise GitHubError("Choose a repository as owner/name, without URLs or credentials.",422,kind="validation")
    owner,name = full_name.split("/",1)
    if name in {".",".."}:
        raise GitHubError("Choose a valid repository name.",422,kind="validation")
    return owner,name


def read_existing_project(client,owner,repo,branch,knowledge_path):
    """Read one immutable project identity snapshot; no repository writes."""
    prefix = knowledge_path_for(knowledge_path,"unused")
    head = client.get_head(owner,repo,branch)
    raw = client.read_file(owner,repo,prefix+"/PROJECT.md",head)
    if raw is None:
        return None
    try:
        identity = parse_project_identity(raw)
    except (ValueError,UnicodeError,KeyError):
        raise GitHubError("The selected PROJECT.md is not a valid portable project record.",409,kind="invalid_project",
            paths=[prefix+"/PROJECT.md"],next_action="Inspect and reconcile that project file before connecting; no file was overwritten.") from None
    identity.update(commit=head,branch=branch,knowledge_path=prefix)
    return identity


class ProjectProvisioner:
    def __init__(self,client,checkpoint=None):
        self.client = client
        self.checkpoint = checkpoint or (lambda operation:None)

    def _save(self,operation):
        operation["updated_at"] = _time()
        self.checkpoint(deepcopy(operation))

    def _prepare(self,operation):
        if not isinstance(operation,dict) or not isinstance(operation.get("id"),str) or not operation["id"]:
            raise GitHubError("Project initialization needs a stable operation ID.",422,kind="validation")
        try:
            spec = clean_project_input(operation.get("input",{}))
            spec.setdefault("mode","connect")
            spec.setdefault("visibility","private")
            spec.setdefault("initialize",True)
            for optional in ("branch","base_branch","knowledge_path"):
                if spec.get(optional)=="":
                    spec[optional] = None
            if spec["mode"] not in MODES or spec["visibility"] not in {"private","public"} or not isinstance(spec["initialize"],bool):
                raise ValueError("Choose a supported initialization mode and visibility")
            if isinstance(spec.get("repository"),dict):
                spec["repository"] = spec["repository"].get("full_name")
            if spec.get("branch"):
                _branch(spec["branch"])
            if spec.get("base_branch"):
                _branch(spec["base_branch"])
            if spec["mode"]=="new_branch" and not spec.get("branch"):
                raise ValueError("A new-branch operation requires its target branch")
            if spec["mode"]!="new_repository":
                _parts(spec.get("repository"))
            operation.setdefault("project_id",project_id_for(operation["id"],spec["name"]))
            spec["knowledge_path"] = knowledge_path_for(spec.get("knowledge_path"),operation["project_id"])
        except (ValueError,KeyError) as error:
            raise GitHubError(str(error),422,kind="validation") from None
        fingerprint = hashlib.sha256(json.dumps(spec,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if operation.get("input_fingerprint") and operation["input_fingerprint"]!=fingerprint:
            raise GitHubError("An initialization operation cannot be reused with changed configuration.",409,kind="conflict",
                next_action="Start a new operation for the changed project settings; preserve the existing operation and remote resources.")
        operation["input"] = spec
        operation["input_fingerprint"] = fingerprint
        operation.setdefault("created_at",_time())
        operation.setdefault("steps",{})
        # Validate all user text/template metadata before remote creation.
        build_project_files(operation)
        self._save(operation)
        return spec

    def _repository(self,owner,name):
        try:
            return self.client.get_repository(owner,name)
        except GitHubError as error:
            if error.status==404:
                return None
            raise

    def _head(self,owner,name,branch):
        try:
            return self.client.get_head(owner,name,branch)
        except GitHubError as error:
            if error.status==404 or error.kind=="empty":
                return None
            raise

    @staticmethod
    def _require_write(repository):
        permissions = repository.get("permissions") or {}
        if repository.get("archived") or repository.get("disabled") or not (permissions.get("push") or permissions.get("admin")):
            raise GitHubError("Your GitHub authorization does not confirm write access to this repository.",403,kind="permission",
                next_action="Ask the repository administrator for the required write role/authorization, or choose a repository you may initialize. No existing files were changed.")

    def _prepare_repository(self,operation,user):
        spec,steps = operation["input"],operation["steps"]
        full_name = spec.get("repository")
        if not full_name:
            owner = spec.get("owner") or user["login"]
            name = spec.get("repository_name") or re.sub(r"[^A-Za-z0-9_.-]+","-",spec["name"]).strip("-.")[:100]
            full_name = owner+"/"+name
        owner,name = _parts(full_name)
        planned = steps.get("repository_target")
        if planned and planned.lower()!=full_name.lower():
            raise GitHubError("The repository target changed during initialization.",409,kind="conflict")
        steps["repository_target"] = full_name
        current = self._repository(owner,name)
        if spec["mode"]=="new_repository":
            if current and not steps.get("repository_created"):
                if steps.get("repository_create_pending"):
                    raise GitHubError("A repository exists after an interrupted creation, but its operation ownership is unconfirmed.",409,
                        kind="needs_reconciliation",next_action="Inspect the preserved repository. If it is the intended one, connect it with a new explicit operation; do not create duplicate repositories or delete it automatically.")
                raise GitHubError("That repository already exists; it was not replaced.",409,kind="conflict",
                    next_action="Choose a different repository name or explicitly connect the existing repository.")
            if not current:
                if steps.get("repository_created"):
                    raise GitHubError("The previously created repository is no longer accessible.",409,kind="needs_reconciliation",
                        next_action="Restore access or inspect its state before retrying; this operation will not recreate a deleted repository.")
                steps["repository_create_pending"] = True
                self._save(operation)
                current = self.client.create_repository(name,owner=owner,visibility=spec["visibility"],
                    description=spec["description"][:2000],auto_init=True)
                steps["repository_created"] = True
                steps["repository_create_pending"] = False
                steps["repository"] = current
                self._save(operation)
        elif current is None:
            raise GitHubError("The selected repository does not exist or is not accessible.",404,kind="not_found",
                next_action="Check its owner/name and your GitHub permission before retrying.")
        steps["repository"] = current
        self._save(operation)
        return owner,name,current

    def _prepare_branch(self,operation,owner,name,repository):
        spec,steps = operation["input"],operation["steps"]
        branch = spec.get("branch") or repository.get("default_branch")
        if not branch:
            raise GitHubError("The repository has no committed default branch.",409,kind="empty",
                next_action="Create an initial commit/branch in the repository, then retry.")
        _branch(branch)
        if steps.get("branch") and steps["branch"]!=branch:
            raise GitHubError("The target branch changed during initialization.",409,kind="conflict")
        steps["branch"] = branch
        head = self._head(owner,name,branch)
        create = spec["mode"]=="new_branch" or (spec["mode"]=="new_repository" and head is None)
        if create:
            self._require_write(repository)
            if head is not None:
                if steps.get("branch_created"):
                    return branch,head
                if steps.get("branch_create_pending") and head==steps.get("branch_base_sha"):
                    steps["branch_create_pending"] = False
                    steps["branch_creation_reconciled"] = True
                    self._save(operation)
                    return branch,head
                raise GitHubError("The requested new branch already exists; it was preserved.",409,kind="conflict",
                    next_action="Choose another branch or explicitly connect the existing branch.")
            if steps.get("branch_created"):
                raise GitHubError("The previously created branch was removed or became inaccessible.",409,kind="needs_reconciliation")
            base = spec.get("base_branch") or repository.get("default_branch")
            if not base:
                raise GitHubError("Choose an existing committed base branch.",409,kind="empty")
            base_sha = steps.get("branch_base_sha") or self._head(owner,name,base)
            if base_sha is None:
                raise GitHubError("The selected base branch has no accessible commit.",409,kind="empty",
                    next_action="Create/push the base branch or choose an existing committed branch.")
            steps.update(branch_create_pending=True,branch_base_sha=base_sha)
            self._save(operation)
            self.client.create_branch(owner,name,branch,sha=base_sha)
            steps.update(branch_created=True,branch_create_pending=False)
            self._save(operation)
            return branch,base_sha
        if head is None:
            raise GitHubError("The selected branch has no accessible committed history.",409,kind="empty",
                next_action="Create an initial commit and push the selected branch, or choose an existing committed branch.")
        self._save(operation)
        return branch,head

    def _finish(self,operation,repository,branch,commit,*,reconciled=False,identity=None):
        spec,steps = operation["input"],operation["steps"]
        result = dict(status="ready",project_id=(identity or {}).get("project_id",operation["project_id"]),
            name=(identity or {}).get("name") or spec["name"],repository=repository,branch=branch,
            knowledge_path=spec["knowledge_path"],commit=commit,format_status="provisional",
            initialized=spec["initialize"],reconciled=reconciled,
            created_repository=bool(steps.get("repository_created")),created_branch=bool(steps.get("branch_created")),
            branch_creation_reconciled=bool(steps.get("branch_creation_reconciled")),
            initialization_commit=steps.get("initialization_commit"),operation_id=operation["id"])
        if identity:
            result["project"] = identity
        operation.update(state="completed",result=result,error=None)
        self._save(operation)
        return deepcopy(result)

    def run(self,operation):
        if operation.get("state")=="completed" and operation.get("result"):
            return deepcopy(operation["result"])
        try:
            spec = self._prepare(operation)
            operation.update(state="running",error=None)
            self._save(operation)
            user = self.client.get_user()
            operation.setdefault("actor",user["login"])
            operation["authenticated_actor"] = {key:user[key] for key in ("login","id") if key in user}
            self._save(operation)
            owner,name,repository = self._prepare_repository(operation,user)
            if spec["initialize"] or spec["mode"]=="new_branch":
                self._require_write(repository)
            branch,head = self._prepare_branch(operation,owner,name,repository)
            steps = operation["steps"]
            if not spec["initialize"]:
                identity = read_existing_project(self.client,owner,name,branch,spec["knowledge_path"])
                if identity is None:
                    raise GitHubError("No initialized project was found in that knowledge directory.",409,kind="not_initialized",
                        next_action="Choose an existing project directory or explicitly initialize a new project there.")
                operation["project_id"] = identity["project_id"]
                return self._finish(operation,repository,branch,identity["commit"],identity=identity)
            marker_path = spec["knowledge_path"]+"/PROJECT.md"
            existing = self.client.read_file(owner,name,marker_path,head)
            if existing is not None:
                try:
                    identity = parse_project_identity(existing)
                except (ValueError,UnicodeError,KeyError):
                    identity = {}
                if identity.get("operation_id")==operation["id"] and identity.get("project_id")==operation["project_id"]:
                    # The atomic initialization landed; later human edits remain untouched.
                    return self._finish(operation,repository,branch,head,reconciled=True,identity=identity)
            initialization = steps.setdefault("initialization",{"expected_head":head})
            files = build_project_files(operation)
            collisions = [path for path in files if self.client.read_file(owner,name,path,head) is not None]
            if collisions:
                raise GitHubError("Existing project files would be overwritten; they were preserved.",409,kind="conflict",paths=collisions,
                    next_action="Connect the existing project, choose a different knowledge directory, or reconcile the files explicitly.")
            initialization["files"] = {path:hashlib.sha256(content.encode()).hexdigest() for path,content in files.items()}
            initialization["pending"] = True
            self._save(operation)
            committed = self.client.commit_files(owner,name,branch,files,expected_head=initialization["expected_head"],
                expected_files={path:None for path in files},message="Initialize ResearchRelay project: "+spec["name"],max_attempts=3)
            steps["initialization_commit"] = committed["commit"]
            initialization["pending"] = False
            self._save(operation)
            return self._finish(operation,repository,branch,committed["commit"])
        except GitHubError as error:
            operation.update(state="needs_reconciliation" if error.kind=="needs_reconciliation" else "failed",
                error={"message":str(error),"status":error.status,"kind":error.kind,"next_action":error.next_action,"paths":error.paths})
            self._save(operation)
            raise
        except (ValueError,KeyError,TypeError) as error:
            problem = GitHubError("Project initialization configuration or metadata is invalid.",422,kind="validation",
                next_action="Inspect the project configuration and retry with valid portable metadata; existing resources were preserved.")
            operation.update(state="failed",error={"message":str(problem),"status":problem.status,"kind":problem.kind,"next_action":problem.next_action,"paths":[]})
            self._save(operation)
            raise problem from None
