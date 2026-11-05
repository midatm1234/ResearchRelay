"""Committed Git knowledge with per-file optimistic concurrency and durable attribution."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile
import threading
import time
import unicodedata
from datetime import datetime, timezone

from .engine import WorkflowError, dumps
from .knowledge import parse_knowledge, render_knowledge

RECOGNIZABLE_CREDENTIAL = re.compile(r"(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{24,}|github_pat_[A-Za-z0-9_]{24,}|-----BEGIN[^\r\n]*PRIVATE KEY-----)")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class SyncError(WorkflowError):
    def __init__(self, message, status=409, *, kind="conflict", paths=None, next_action=None):
        super().__init__(message, status)
        self.kind = kind
        self.paths = paths or []
        self.next_action = next_action or "Refresh project context, compare the changed files, and explicitly reconcile your draft."


class ProjectSync:
    """One coordinator's disposable Git cache; committed knowledge is never execution state."""
    _lock = threading.RLock()

    def __init__(self, settings, engine):
        self.settings = settings
        self.engine = engine
        self._last_check = 0.0
        self.root = settings.repo_path.parent / "shared-git"
        with engine._tx() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS knowledge_documents(
                    path TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_profiles(
                    participant TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS publications(
                    participant TEXT,request_id TEXT,payload_hash TEXT,payload TEXT,response TEXT,
                    PRIMARY KEY(participant,request_id));
            """)

    def _setting(self, key, default=None):
        with self.engine._tx() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else default

    def _set(self, key, value):
        with self.engine._tx() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key,dumps(value)))

    @property
    def binding(self):
        stored = self._setting("shared_repository")
        if stored:
            return stored
        if self.settings.github_url:
            return dict(url=self.settings.github_url,branch=self.settings.github_branch,
                        knowledge_path=self.settings.knowledge_path or f"projects/{self.engine.project_id}")
        return None

    def status(self):
        return self._setting("shared_sync", dict(status="disabled" if not self.binding else "pending",
            latest_commit=None,last_checked_at=None,error=None,next_action=None))

    def public(self, participant="human"):
        binding = self.binding
        try:
            binding = self._validate_binding(binding) if binding else None
        except SyncError:
            binding = None
        return dict(project_id=self.engine.project_id,participant=participant,repository=binding,
                    sync=self.status(),format_status="provisional")

    def _state(self, **changes):
        state = {**self.status(),**changes}
        self._set("shared_sync",state)
        return state

    def _validate_binding(self, binding):
        url, branch, prefix = (binding.get(k,"") for k in ("url","branch","knowledge_path"))
        github = re.fullmatch(r"(?:git@github\.com:|https://github\.com/)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?",url)
        local = Path(url).expanduser()
        if not github and not (self.settings.mode=="demo" and local.is_absolute() and local.is_dir()):
            raise SyncError("Use a credential-free GitHub SSH/HTTPS URL. Absolute local remotes are restricted to demonstration mode.",
                            422,kind="configuration",next_action="Configure the project repository URL; credentials belong in the local Git credential manager.")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,199}",branch) or any(v in branch for v in ("..","//","@{")) or branch.endswith("/"):
            raise SyncError("Invalid repository branch",422,kind="configuration")
        self._safe_path(prefix+"/index.md",prefix)
        return dict(url=url,branch=branch,knowledge_path=prefix.rstrip("/"))

    def configure(self, url, branch, knowledge_path):
        binding = self._validate_binding(dict(url=url,branch=branch,knowledge_path=knowledge_path))
        with self._lock:
            self._set("shared_repository",binding)
            with self.engine._tx() as db:
                db.execute("DELETE FROM knowledge_documents")
            self._last_check = 0
            self._state(status="pending",latest_commit=None,error=None,next_action=None,last_checked_at=None)
            return self.refresh(force=True)

    def _cache(self):
        binding = self._validate_binding(self.binding)
        digest = hashlib.sha256(dumps(binding).encode()).hexdigest()[:16]
        return self.root / (self.engine.project_id.replace(":","-")+"-"+digest)

    def _environment(self, base=None):
        environment = dict(os.environ if base is None else base, GIT_TERMINAL_PROMPT="0",GCM_INTERACTIVE="Never")
        environment.setdefault("GIT_SSH_COMMAND","ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes")
        return environment

    def _git(self, path, *arguments, data=None, check=True):
        environment = self._environment()
        try:
            completed = subprocess.run(["git","-C",str(path),"-c","core.longpaths=true",*arguments],input=data,
                capture_output=True,env=environment,timeout=60)
        except (OSError,subprocess.TimeoutExpired) as error:
            raise SyncError("Git is unavailable or the repository operation timed out.",503,kind="error",
                            next_action="Verify Git is installed, network access works, and the configured repository is reachable.") from error
        if check and completed.returncode:
            failure = completed.stderr.decode("utf-8",errors="replace").lower()
            if any(term in failure for term in ("permission denied","authentication","could not read username","repository not found","publickey","host key verification")):
                raise SyncError("Repository authentication or access failed.",503,kind="authentication_error",
                    next_action="Authenticate Git on the coordinator host and verify access to this repository. For SSH, verify its host key and run ssh -T git@github.com.")
            if "couldn't find remote ref" in failure or "does not appear to be a git repository" in failure:
                raise SyncError("The knowledge repository or selected branch has no accessible committed history.",422,kind="configuration",
                    next_action="Create an initial commit and push the selected branch, or configure an existing repository and committed branch before retrieving knowledge.")
            raise SyncError("Git could not complete the repository operation.",409,kind="error",
                    next_action="Check the configured branch and Git access. A protected branch may require a reviewed pull request; no policy was bypassed.")
        return completed.stdout

    def _fetch(self):
        binding = self._validate_binding(self.binding)
        cache = self._cache()
        cache.parent.mkdir(parents=True,exist_ok=True)
        if not (cache/".git").is_dir():
            if cache.exists() and any(cache.iterdir()):
                raise SyncError("Managed Git cache is incomplete; existing files were preserved.",503,kind="error")
            self._git(cache.parent,"clone","--no-checkout","--origin","origin",binding["url"],str(cache))
        remote = self._git(cache,"remote","get-url","origin").decode().strip()
        if remote != binding["url"]:
            raise SyncError("Managed cache origin differs from the project binding.",409,kind="configuration")
        self._git(cache,"fetch","--no-tags","origin",f"refs/heads/{binding['branch']}")
        latest = self._git(cache,"rev-parse","FETCH_HEAD").decode().strip()
        return cache, latest

    def _safe_path(self, name, prefix=None):
        if not isinstance(name,str) or "\\" in name or ":" in name:
            raise SyncError("Use a bundle-relative Markdown path.",422,kind="validation")
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in {"..",".git",".env"} or part.startswith(".") for part in path.parts):
            raise SyncError("Knowledge path must remain inside the configured project bundle.",422,kind="validation")
        if path.as_posix()!=name or path.suffix.lower()!=".md":
            raise SyncError("Only normalized Markdown paths may be published.",422,kind="validation")
        if prefix is not None and (not prefix or prefix.startswith("/") or not name.startswith(prefix.rstrip("/")+"/")):
            raise SyncError("Path is outside this project's knowledge bundle.",422,kind="validation")
        return path

    def _run_local(self, arguments, **options):
        try:
            return subprocess.run(arguments,capture_output=True,timeout=options.pop("timeout",30),env=self._environment(options.pop("env",None)),**options)
        except (OSError,subprocess.TimeoutExpired) as error:
            raise SyncError("A Git operation could not finish; the publication draft was retained.",503,kind="error",
                            next_action="Check Git/network access and retry the same request. A possibly accepted push is reconciled before retrying.") from error

    def _blob(self, cache, commit, name):
        # cat-file is explicit object lookup. Unlike show REV:PATH, it never
        # stats an ambiguous worktree filename (important for deep Windows paths).
        result = self._run_local(["git","-C",str(cache),"cat-file","blob",f"{commit}:{name}"])
        return result.stdout if result.returncode==0 else None

    @staticmethod
    def _path_key(name):
        return unicodedata.normalize("NFC",name).casefold()

    def _guard_paths(self, cache, commit, changes):
        tree = self._git(cache,"ls-tree","-r","-z",commit).split(b"\0")
        spellings, files, directories = {}, set(), set()
        prefix = self.binding["knowledge_path"]
        for entry in tree:
            if not entry:
                continue
            name = entry.split(b"\t",1)[1].decode("utf-8")
            files.add(name)
            parts = PurePosixPath(name).parts
            for length in range(1,len(parts)+1):
                segment = "/".join(parts[:length])
                key = self._path_key(segment)
                previous = spellings.get(key)
                if previous and previous!=segment and (
                    segment.startswith(prefix+"/") or previous.startswith(prefix+"/")):
                    raise SyncError("The repository has filenames that collide on macOS/Windows.",paths=[previous,segment],
                                    next_action="Rename the conflicting files on a case-sensitive checkout before synchronizing.")
                spellings.setdefault(key,segment)
                if length<len(parts):
                    directories.add(key)
        proposed = set()
        for change in changes:
            name = change["path"]
            key = self._path_key(name)
            if key in proposed:
                raise SyncError("The request contains duplicate or case-colliding document paths.",422,kind="validation",paths=[name])
            proposed.add(key)
            if key in directories:
                raise SyncError("A proposed document replaces an existing or proposed directory.",422,kind="validation",paths=[name])
            parts = PurePosixPath(name).parts
            for length in range(1,len(parts)+1):
                segment = "/".join(parts[:length])
                key = self._path_key(segment)
                previous = spellings.get(key)
                if previous and previous!=segment:
                    raise SyncError("The proposed path collides with an existing filename on macOS/Windows.",paths=[previous,segment])
                if length<len(parts) and segment in files:
                    raise SyncError("A document path descends through a tracked file or symlink.",422,kind="validation",paths=[segment])
                spellings[key]=segment
                if length<len(parts):
                    directories.add(key)
            files.add(name)

    def _ancestor(self, cache, base, latest):
        result = self._run_local(["git","-C",str(cache),"merge-base","--is-ancestor",base,latest])
        return result.returncode==0

    def _validate_prospective(self, cache, latest, documents, changes):
        self._guard_paths(cache,latest,changes)
        prospective = set(documents)
        sizes = {name:document.get("size_bytes",len(document.get("content","").encode("utf-8"))) for name,document in documents.items()}
        for change in changes:
            name,content = change["path"],change["content"]
            if RECOGNIZABLE_CREDENTIAL.search(content):
                raise SyncError("A possible credential was found in a proposed or generated document.",422,kind="validation",paths=[name],
                                next_action="Remove the credential from the artifact and keep it in the participant's credential environment.")
            if len(content.encode("utf-8"))>1_000_000:
                raise SyncError("A generated or proposed document exceeds the 1 MB publication limit.",422,kind="validation",paths=[name])
            try:
                parse_knowledge(content,project_id=self.engine.project_id,path=name)
            except ValueError as error:
                raise SyncError(f"A proposed document is invalid: {error}",422,kind="validation",paths=[name]) from error
            prospective.add(name)
            sizes[name] = len(content.encode("utf-8"))
        if sum(sizes.values())>50_000_000:
            raise SyncError("This publication would exceed the 50 MB project context limit.",422,kind="validation")
        if len(prospective)>1000:
            raise SyncError("This publication would exceed the 1,000-document pilot limit.",422,kind="validation")

    def _documents(self, cache, commit):
        prefix = self.binding["knowledge_path"]
        self._guard_paths(cache,commit,[])
        entries = self._git(cache,"ls-tree","-r","-z",commit,"--",prefix).split(b"\0")
        selected = []
        for entry in entries:
            if not entry:
                continue
            header,raw_name = entry.split(b"\t",1)
            name = raw_name.decode("utf-8")
            if not name.lower().endswith(".md"):
                continue
            self._safe_path(name,prefix)
            mode,kind,object_id = header.split()
            if mode not in {b"100644",b"100755"} or kind!=b"blob":
                raise SyncError("Knowledge Markdown must be a regular file, not a symlink.",422,paths=[name])
            selected.append((name,object_id))
        if len(selected)>1000:
            raise SyncError("Project bundle exceeds the 1,000-document pilot limit.",422,kind="validation")
        if not selected:
            return []
        requests = b"\n".join(oid for name,oid in selected)+b"\n"
        sizes = self._git(cache,"cat-file","--batch-check",data=requests).splitlines()
        if len(sizes)!=len(selected):
            raise SyncError("Git could not read all knowledge objects.",503,kind="error")
        total = 0
        for (name,oid),entry in zip(selected,sizes):
            fields = entry.split()
            if len(fields)!=3 or fields[1]!=b"blob":
                raise SyncError("A knowledge object is missing.",422,paths=[name])
            size = int(fields[2])
            if size>1_000_000:
                raise SyncError("Knowledge document exceeds 1 MB.",422,paths=[name])
            total += size
        if total>50_000_000:
            raise SyncError("The project bundle exceeds the 50 MB pilot context limit.",422,kind="validation",
                            next_action="Keep large data in external storage and publish concise provenance/reference records.")
        stream = io.BytesIO(self._git(cache,"cat-file","--batch",data=requests))
        documents = []
        for name,oid in selected:
            header = stream.readline().split()
            if len(header)!=3 or header[0]!=oid or header[1]!=b"blob":
                raise SyncError("Git returned an inconsistent knowledge object.",503,kind="error")
            raw = stream.read(int(header[2]))
            if stream.read(1)!=b"\n":
                raise SyncError("Git returned an incomplete knowledge object.",503,kind="error")
            try:
                content = raw.decode("utf-8-sig")
                metadata,body = parse_knowledge(content,project_id=self.engine.project_id,path=name)
            except (ValueError,UnicodeError) as error:
                raise SyncError(f"Invalid knowledge document {name}: {error}",422,kind="validation",paths=[name]) from error
            documents.append(dict(path=name,content=content,sha256=hashlib.sha256(raw).hexdigest(),
                                  metadata=metadata,body=body,commit=commit,size_bytes=len(raw)))
        return documents

    def refresh(self, force=False, require=False):
        with self._lock:
            if not self.binding:
                return self._state(status="disabled",latest_commit=None,last_checked_at=None,error=None,next_action=None)
            if not force and time.monotonic()-self._last_check<self.settings.sync_interval:
                state = self.status()
                if require and state["status"]!="synced":
                    raise SyncError(state.get("error") or "Project synchronization has not completed.",503,
                                    kind=state["status"],next_action=state.get("next_action"))
                return state
            try:
                cache,latest = self._fetch()
                documents = self._documents(cache,latest)
                state = dict(status="synced",latest_commit=latest,last_checked_at=timestamp(),error=None,next_action=None)
                with self.engine._tx() as db:
                    db.execute("DELETE FROM knowledge_documents")
                    for document in documents:
                        db.execute("INSERT INTO knowledge_documents VALUES(?,?)",(document["path"],dumps(document)))
                    db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)",("shared_sync",dumps(state)))
            except SyncError as error:
                state = self._state(status=error.kind,error=str(error),next_action=error.next_action,last_checked_at=timestamp())
                if require:
                    raise
            finally:
                self._last_check = time.monotonic()
            return state

    def context(self, participant="human", force=True):
        with self._lock:
            return self._context(participant,force)

    def _context(self, participant, force):
        bound = bool(self.binding)
        self.refresh(force=force,require=bound)
        with self.engine._tx() as db:
            documents = ([json.loads(row[0]) for row in db.execute("SELECT data FROM knowledge_documents ORDER BY path")]
                         if bound else [])
        tasks = self.engine.list_tasks()
        for task in tasks:
            task.pop("claim_token",None)
        return {**self.public(participant),"documents":documents,"tasks":tasks,
                "artifacts":self.engine.list_artifacts(all_versions=False)}

    def check_inputs(self, metadata):
        with self._lock:
            return self._check_inputs(metadata)

    def _check_inputs(self, metadata):
        if not self.binding:
            return
        pins = metadata.get("project_context")
        if not isinstance(pins,dict) or not pins.get("commit"):
            raise SyncError("A shared-project result must identify its retrieved project commit and input document hashes.",422,
                            kind="validation",next_action="Retrieve current project context before running this task and record its exact inputs.")
        if not isinstance(pins["commit"],str) or not re.fullmatch(r"[0-9a-f]{40,64}",pins["commit"]) or not isinstance(pins.get("documents"),list) or any(
            not isinstance(ref,dict) or not isinstance(ref.get("path"),str) or not re.fullmatch(r"[0-9a-f]{64}",str(ref.get("sha256","")))
            for ref in pins["documents"]):
            raise SyncError("Result project context must contain an exact commit and version-pinned document references.",422,kind="validation")
        if not isinstance(pins.get("repository"),dict):
            raise SyncError("Shared-result context must identify its knowledge repository, branch, and directory.",422,kind="validation",
                            next_action="Retrieve project context before executing and include its repository binding in project_context.")
        if self._validate_binding(pins["repository"]) != self._validate_binding(self.binding):
            raise SyncError("The result's knowledge repository, branch, or directory changed while the task ran.",
                            next_action="Inspect the new source and explicitly reconcile/retry the task; an identical commit does not authorize a different repository.")
        state = self.refresh(force=True,require=True)
        cache = self._cache()
        if not self._ancestor(cache,pins["commit"],state["latest_commit"]):
            raise SyncError("The result's project commit is not a retrieved ancestor of the shared branch.",422,kind="validation")
        historical = {document["path"]:document for document in self._documents(cache,pins["commit"])}
        for ref in pins["documents"]:
            self._safe_path(ref["path"],self.binding["knowledge_path"])
            if ref["path"] not in historical or historical[ref["path"]]["sha256"]!=ref["sha256"]:
                raise SyncError("An input hash does not belong to the result's declared project commit.",422,kind="validation",paths=[ref["path"]])
        current = {doc["path"]:doc for doc in self.context(force=False)["documents"]}
        changed = [ref.get("path") for ref in pins.get("documents",[])
                   if ref.get("path") not in current or current[ref["path"]]["sha256"]!=ref.get("sha256")]
        if changed:
            raise SyncError("Shared knowledge inputs changed while the task ran.",409,paths=changed,
                            next_action="Block this task, inspect the changed evidence, and explicitly retry with refreshed project context.")

    def _workflow_changes(self, latest_documents):
        prefix = self.binding["knowledge_path"]
        changes = []
        for artifact in self.engine.list_artifacts(all_versions=True):
            metadata = dict(artifact["metadata"])
            if metadata.get("status") and metadata["status"] not in {"draft","stable","deprecated"}:
                state_key = "decision_status" if metadata["artifact_type"]=="decision" else "workflow_status"
                metadata[state_key] = metadata["status"]
                metadata["status"] = "draft"
            if "provenance" in metadata and not isinstance(metadata["provenance"],dict):
                metadata["provenance"] = {"legacy_provenance":metadata["provenance"]}
            metadata.setdefault("type",metadata["artifact_type"].replace("_"," ").title())
            metadata.setdefault("format_status","provisional")
            metadata.setdefault("sources",[])
            content = render_knowledge(metadata,artifact["body"])
            name = f"{prefix}/_workflow/{metadata['artifact_type']}/{metadata['id']}/v{metadata['version']}.md"
            previous = latest_documents.get(name)
            if previous and previous["content"]!=content:
                raise SyncError("An immutable workflow artifact differs from the authoritative record.",409,paths=[name],
                                next_action="Preserve the Git revision and create an explicitly reconciled artifact version.")
            if not previous:
                changes.append(dict(path=name,content=content,expected_sha256=None))
        with self.engine._tx() as db:
            decisions = [json.loads(row[0]) for row in db.execute("SELECT data FROM decisions")]
        dashboard = {"tasks":self.engine.list_tasks(),"decisions":decisions}
        if not dashboard["tasks"] and not dashboard["decisions"]:
            return changes
        lines = ["# Generated workflow view","",
                 "SQLite is authoritative for claims and execution. This is a generated project-record snapshot.","",
                 "| Task | Owner | State | Result | Completion notes |","| --- | --- | --- | --- | --- |"]
        for task in dashboard["tasks"]:
            cells = [task["id"],task["owner"],task["status"],str(task.get("result_ref") or ""),task.get("completion_notes","")]
            lines.append("| "+" | ".join(str(cell).replace("|","/").replace("\n"," ") for cell in cells)+" |")
        lines += ["","## Decisions",""]
        lines += [f"- {decision['question']} ({decision['status']})" for decision in dashboard["decisions"]]
        content = "\n".join(lines)+"\n"
        store_id = self._setting("coordinator_store_id")
        if not store_id:
            import uuid
            store_id = uuid.uuid4().hex
            self._set("coordinator_store_id",store_id)
        name = f"{prefix}/_workflow/coordinators/{store_id}/index.md"
        previous = latest_documents.get(name)
        if not previous or previous["content"]!=content:
            changes.append(dict(path=name,content=content,expected_sha256=previous["sha256"] if previous else None))
        return changes

    def _prior_request(self, cache, latest, participant, request_id, digest):
        candidate = self._setting(f"publication_candidate:{participant}:{request_id}")
        if candidate and self._ancestor(cache,candidate,latest):
            body = self._git(cache,"show","-s","--format=%B",candidate).decode("utf-8")
            if f"Payload-SHA256: {digest}" in body.splitlines():
                return candidate
        log = self._git(cache,"log","-100","--format=%H%x00%B%x00",latest).decode("utf-8").split("\0")
        marker = f"ResearchRelay-Request: {participant}:{request_id}"
        for index in range(0,len(log)-1,2):
            if marker in log[index+1].splitlines():
                if f"Payload-SHA256: {digest}" not in log[index+1].splitlines():
                    raise SyncError("Publication request ID was already used for different content.")
                return log[index].strip()
        return None

    def _commit(self, cache, latest, changes, participant, agent, request_id, digest, message):
        parent = cache.parent / "publication-worktrees"
        parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="publication-",dir=parent) as directory:
            workspace = Path(directory)
            self._git(cache,"worktree","add","--detach",str(workspace),latest)
            try:
                for change in changes:
                    target = workspace / PurePosixPath(change["path"])
                    if not target.resolve().is_relative_to(workspace.resolve()):
                        raise SyncError("Knowledge output resolves outside its isolated workspace.",422,kind="validation")
                    target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(change["content"].encode("utf-8"))
                self._git(workspace,"add","--",*[change["path"] for change in changes])
                staged = self._git(workspace,"diff","--cached","--name-only").strip()
                if not staged:
                    return latest
                body = (message[:300].replace("\n"," ").replace("\r"," ")+"\n\n"+
                        f"ResearchRelay-Participant: {participant}\nResearchRelay-Agent: {agent}\n"+
                        f"ResearchRelay-Request: {participant}:{request_id}\nPayload-SHA256: {digest}\n")
                self._git(workspace,"-c",f"user.name=ResearchRelay {participant}","-c","user.email=record@localhost.invalid",
                          "commit","-m",body)
                return self._git(workspace,"rev-parse","HEAD").decode().strip()
            finally:
                self._git(cache,"worktree","remove","--force",str(workspace),check=False)

    def publish(self, participant, *, base_commit, changes, agent, request_id, message, expected_repository=None):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}",participant) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",request_id):
            raise SyncError("Participant and request ID must be safe stable identifiers.",422,kind="validation")
        if not re.fullmatch(r"[0-9a-f]{40,64}",base_commit or "") or not agent or any(ord(character)<32 for character in agent) or len(agent)>200:
            raise SyncError("Publication requires an exact base commit and a producing agent.",422,kind="validation")
        if not changes or len(changes)>30:
            raise SyncError("Publish 1–30 prepared Markdown documents per request.",422,kind="validation")
        payload = dict(base_commit=base_commit,changes=changes,agent=agent,request_id=request_id,message=message,
                       expected_repository=expected_repository)
        digest = hashlib.sha256(dumps(payload).encode()).hexdigest()
        with self._lock:
            # An acknowledged exact replay belongs to its original source, even
            # after the project's selected repository/branch/prefix has changed.
            with self.engine._tx() as db:
                row = db.execute("SELECT * FROM publications WHERE participant=? AND request_id=?",(participant,request_id)).fetchone()
                if row and row["payload_hash"]!=digest:
                    raise SyncError("Publication request ID was reused with different content.")
                if row and row["response"]:
                    return json.loads(row["response"])
            if not self.binding:
                raise SyncError("This project has no configured GitHub repository.",422,kind="configuration")
            if not isinstance(expected_repository,dict):
                raise SyncError("Publication requires the repository binding from its retrieved context.",422,kind="validation",
                                next_action="Retrieve fresh project context and include its repository as expected_repository.")
            binding = self._validate_binding(self.binding)
            observed = self._validate_binding(expected_repository)
            if observed != binding:
                raise SyncError("The knowledge repository, branch, or directory changed since this contribution's context was retrieved.",
                                next_action="Retrieve current context, confirm the intended source, and explicitly reconcile or recreate the contribution before publishing.")
            for change in changes:
                name,content = change["path"],change["content"]
                self._safe_path(name,self.binding["knowledge_path"])
                if "/_workflow/" in name:
                    raise SyncError("Workflow records are generated from authoritative state.",422,kind="validation")
                if not isinstance(content,str) or len(content.encode("utf-8"))>1_000_000:
                    raise SyncError("Knowledge documents must be UTF-8 text under 1 MB.",422,kind="validation")
                if RECOGNIZABLE_CREDENTIAL.search(content):
                    raise SyncError("A possible credential was found in the proposed document.",422,kind="validation")
                try:
                    metadata,_ = parse_knowledge(content,project_id=self.engine.project_id,path=name)
                except ValueError as error:
                    raise SyncError(f"Invalid proposed knowledge: {error}",422,kind="validation",paths=[name]) from error
                if not metadata.get("reserved"):
                    if metadata.get("responsible_participant")!=participant or metadata.get("producing_agent")!=agent:
                        raise SyncError("Document participant and producing agent must match this authenticated contribution.",403,kind="authorization",paths=[name])
            with self.engine._tx() as db:
                db.execute("INSERT OR REPLACE INTO publications VALUES(?,?,?,?,NULL)",(participant,request_id,digest,dumps(payload)))
            try:
                for attempt in range(2):
                    cache, latest = self._fetch()
                    prior = self._prior_request(cache,latest,participant,request_id,digest)
                    if prior:
                        commit = prior
                        break
                    if not self._ancestor(cache,base_commit,latest):
                        raise SyncError("The supplied base commit is not an ancestor of this project branch.")
                    # macOS Git may precompose a lookup path before cat-file resolves
                    # it. Diagnose filesystem aliases before checking blob hashes.
                    self._guard_paths(cache,latest,changes)
                    conflicts = []
                    for change in changes:
                        old = self._blob(cache,base_commit,change["path"])
                        current = self._blob(cache,latest,change["path"])
                        old_hash = hashlib.sha256(old).hexdigest() if old is not None else None
                        current_hash = hashlib.sha256(current).hexdigest() if current is not None else None
                        if change.get("expected_sha256")!=old_hash or current_hash!=old_hash:
                            conflicts.append(change["path"])
                    if conflicts:
                        raise SyncError("The edited knowledge files changed since this context was retrieved.",paths=conflicts)
                    documents = {doc["path"]:doc for doc in self._documents(cache,latest)}
                    try:
                        combined = changes+self._workflow_changes(documents)
                    except ValueError as error:
                        raise SyncError(f"A workflow artifact is not valid portable knowledge: {error}",422,kind="validation") from error
                    self._validate_prospective(cache,latest,documents,combined)
                    commit = self._commit(cache,latest,combined,participant,agent,request_id,digest,message)
                    self._set(f"publication_candidate:{participant}:{request_id}",commit)
                    pushed = self._run_local(["git","-C",str(cache),"push","origin",f"{commit}:refs/heads/{self.binding['branch']}"],
                                            timeout=60,env=dict(os.environ,GIT_TERMINAL_PROMPT="0",GCM_INTERACTIVE="Never",
                                            GIT_SSH_COMMAND=os.getenv("GIT_SSH_COMMAND","ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=yes")))
                    if not pushed.returncode:
                        break
                    if attempt:
                        raise SyncError("Publication could not be pushed; the draft and local commit were retained.",kind="error",
                            next_action="Check write access and branch protection, refresh, then retry this request. Use a reviewed PR if required.")
                state = self.refresh(force=True,require=True)
                response = dict(status="published",commit=commit,branch=binding["branch"],repository=binding,
                                paths=[change["path"] for change in changes],sync=state)
                with self.engine._tx() as db:
                    db.execute("UPDATE publications SET response=? WHERE participant=? AND request_id=?",
                               (dumps(response),participant,request_id))
                    self.engine._event(db,"knowledge_published",detail=dict(participant=participant,agent=agent,commit=commit,repository=binding,paths=response["paths"]))
                return response
            except SyncError as error:
                self._state(status=error.kind,error=str(error),next_action=error.next_action,last_checked_at=timestamp())
                raise

    def agent_profile(self, participant, profile=None):
        from .providers import validate_profile
        with self.engine._tx() as db:
            if profile is not None:
                normalized = validate_profile(profile)
                db.execute("INSERT OR REPLACE INTO agent_profiles VALUES(?,?)",(participant,dumps(normalized)))
            row = db.execute("SELECT data FROM agent_profiles WHERE participant=?",(participant,)).fetchone()
        return dict(participant=participant,profile=json.loads(row[0]) if row else validate_profile({"provider":"claude-cli"}))
