"""Participant-owned HTTP worker. No execution happens inside the coordinator."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse, quote

from .providers import ProviderError, validate_profile, generate_report, guard_output_bytes
from .knowledge import validate_knowledge

import httpx

from .artifacts import get_schema, parse_markdown, render_markdown
from .repository import Repository, _git


class Worker:
    def __init__(self, server: str, participant: str, repository: str | Path,
                 token: str | None = None, mode: str | None = None, lease_seconds: int = 120,
                 timeout: int = 600, allowed_tools: str | None = None, provider: str | None = None,
                 model: str | None = None, base_url: str | None = None,
                 api_key_env: str | None = None, command: list[str] | None = None):
        self.client = httpx.Client(base_url=server.rstrip("/") + "/api/", timeout=30,
                                   headers={"Authorization": f"Bearer {token}"} if token else {})
        self.participant = participant
        self.repository = Repository(repository)
        self.mode = mode
        self.lease_seconds = lease_seconds
        self.timeout = timeout
        self.allowed_tools = allowed_tools or "Read,Write,Edit,Glob,Grep"
        self.profile_overrides = {key:value for key,value in {
            'provider':provider, 'model':model, 'base_url':base_url,
            'api_key_env':api_key_env, 'command':command, 'allowed_tools':allowed_tools,
        }.items() if value is not None}
        if mode is not None:
            legacy = {'claude':'claude-cli','manual':'manual'}.get(mode)
            if not legacy or (provider is not None and provider != legacy):
                raise ValueError('Use a supported provider, or the compatible legacy --mode claude/manual option')
            self.profile_overrides['provider'] = legacy
        self.active_profile = validate_profile(self.profile_overrides)

    def _post(self, route: str, payload: dict) -> dict:
        response = self.client.post(route, json=payload)
        response.raise_for_status()
        return response.json()

    def _get(self, route: str) -> dict:
        response = self.client.get(route)
        response.raise_for_status()
        return response.json()

    def project_context(self) -> dict:
        context = self._get('project/context')
        state = context.get('sync',{}).get('status','disabled')
        if context.get('repository') and state not in {'synced','current','up_to_date','ready'}:
            raise RuntimeError('Project synchronization needs attention before this worker can start a task')
        return context

    def run_once(self) -> dict:
        self.project_context()
        connection = self._get('participants/me/agent')
        stored = connection.get('profile',connection)
        stored = {key:value for key,value in stored.items() if key in {'provider','model','base_url','api_key_env','command','allowed_tools'}}
        self.active_profile = validate_profile({**stored,**self.profile_overrides})
        self.allowed_tools = self.active_profile['allowed_tools'] or self.allowed_tools
        response = self.client.get("tasks", params={"owner": self.participant, "ready": "true"})
        response.raise_for_status()
        tasks = response.json()
        if isinstance(tasks, dict):
            tasks = tasks.get("tasks", [])
        if not tasks:
            return {"status": "idle", "participant": self.participant}
        task = tasks[0]
        try:
            claim = self._post(f"tasks/{task['id']}/claim", {"worker_id": self.participant,
                                                          "lease_seconds": self.lease_seconds})
        except httpx.HTTPStatusError as error:
            if error.response.status_code == 409:
                return {"status": "claim_lost", "task_id": task["id"]}
            raise
        task = claim.get("task", claim)
        token = claim.get("claim_token") or task["claim_token"]
        stopped, lost = threading.Event(), threading.Event()

        def heartbeat() -> None:
            while not stopped.wait(max(1, self.lease_seconds / 3)):
                try:
                    self._post(f"tasks/{task['id']}/heartbeat", {"claim_token": token,
                              "progress": "Participant agent executing in isolated worktree",
                              "lease_seconds": self.lease_seconds})
                except Exception:
                    lost.set()
                    return

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            project = self.project_context()
            base_ref = self._prepare_project_repository(project)
            isolation = self.repository.isolated_branch(task["id"], task["attempts"], base_ref=base_ref)
            workspace = Path(isolation["workspace"])
            exchange = workspace / ".researchrelay-exchange"
            if _git(workspace, "ls-files", "--", ".researchrelay-exchange"):
                raise RuntimeError("Reserved .researchrelay-exchange path is already tracked; reconcile the repository before running this worker")
            if not exchange.resolve().is_relative_to(workspace.resolve()):
                raise RuntimeError("Worker exchange directory resolves outside its isolated worktree")
            exchange.mkdir(exist_ok=True)
            inputs = []
            for ref in task.get("input_refs", []):
                response = self.client.get(f"artifacts/{ref['id']}", params={"version": ref["version"]})
                response.raise_for_status()
                inputs.append(response.json())
            context = {"task": {k: v for k, v in task.items() if k != "claim_token"},
                       "input_artifacts": inputs, "project": project}
            context_text = json.dumps(context, indent=2)
            (exchange / "task-context.json").write_text(context_text, encoding="utf-8")
            request_id_path = exchange / "submission-id.txt"
            if request_id_path.exists():
                submission_id = request_id_path.read_text(encoding="utf-8").strip()
            else:
                submission_id = str(uuid.uuid4())
                request_id_path.write_text(submission_id, encoding="utf-8")
            result_path = exchange / "result.md"
            provider = self.active_profile['provider']
            if provider == 'claude-cli':
                self._claude(workspace, lost)
            elif provider == 'manual':
                self._wait_for_manual(workspace, lost)
            else:
                self._report(workspace, lost, context)
            if lost.is_set():
                raise RuntimeError("Claim lost or task canceled; result retained locally, not submitted")
            metadata, body = parse_markdown(result_path.read_text(encoding="utf-8"))
            if metadata["task_id"] != task["id"] or metadata["project_id"] != task.get("project_id", metadata["project_id"]):
                raise ValueError("Result does not belong to the claimed task/project")
            metadata["input_refs"] = task.get("input_refs", [])
            metadata["responsible_participant"] = task["owner"]
            metadata['project_context'] = self._context_pins(project)
            metadata.setdefault('format_status','provisional')
            metadata.setdefault('type','Research Result')
            metadata.setdefault('sources',self._sources(context))
            metadata.setdefault('citations',[])
            metadata.setdefault('relations',[])
            metadata.setdefault('provenance',{})
            if not isinstance(metadata['provenance'],dict):
                raise ValueError('Result provenance must be an object for shared publication')
            metadata['provenance']['context_commit'] = metadata['project_context']['commit']
            metadata['provenance']['participant_owned_worker'] = True
            if self.active_profile['provider'] != 'manual' or metadata.get('producing_agent') in {'human','unassigned',None}:
                metadata['producing_agent'] = self._agent_id()
            actor = metadata['producing_agent']
            if '/' not in actor and not actor.startswith(('human:','process:')):
                actor += '/unspecified'
            metadata['generated'] = {'by':actor,'at':metadata['updated_at']}
            for field in ("objective", "acceptance_criteria", "expected_outputs", "dependencies"):
                if not metadata.get(field):
                    metadata[field] = task.get(field, [] if field != "objective" else "")
            metadata = validate_knowledge(metadata,body)
            record_directory = workspace / "task-records" / task["id"]
            if not record_directory.resolve().is_relative_to(workspace.resolve()):
                raise ValueError("Task record directory escapes the isolated worktree")
            record_directory.mkdir(parents=True, exist_ok=True)
            context_name = f"task-records/{task['id']}/attempt-{task['attempts']}-context.json"
            (workspace / context_name).write_text(context_text, encoding="utf-8")
            files = [context_name]
            for name in metadata.get("related_files", []):
                if not isinstance(name, str):
                    continue
                candidate = (workspace / name).resolve()
                if not candidate.is_relative_to(workspace.resolve()):
                    raise ValueError("Result file reference escapes the isolated worktree")
                if any(part.startswith(".env") or part in {".git", ".researchrelay-exchange", "submission.json", "submission-id.txt"}
                       or "credential" in part.lower() or "secret" in part.lower() for part in Path(name).parts):
                    raise ValueError("Credential or runtime submission files cannot be committed as outputs")
                if candidate.is_file() and name not in files:
                    files.append(name)
            self._guard_commit_outputs(workspace, files, render_markdown(metadata,body))
            code_commit = self.repository.commit_workspace(workspace, task["id"], files,
                                                           "Participant scientific outputs and pinned context")
            metadata["repository_commits"] = [code_commit]
            record_name = f"task-records/{task['id']}/v{metadata['version']}.md"
            (workspace / record_name).write_text(render_markdown(metadata, body), encoding="utf-8")
            self._guard_commit_outputs(workspace, [record_name])
            commit = self.repository.commit_workspace(workspace, task["id"], [record_name],
                                                      "Validated result artifact")
            # Persist exact payload before network submission; --resubmit retries it safely.
            payload = {"claim_token": token, "idempotency_key": submission_id,
                       "artifact": {"metadata": metadata, "body": body},
                       "completion_notes": f"Computed in isolated branch {isolation['branch']}; commit {commit}. Scientific interpretation awaits review."}
            (exchange / "submission.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
            result = self._post(f"tasks/{task['id']}/submit", payload)
            self._post(f"tasks/{task['id']}/repository", {"branch": isolation["branch"], "commit": commit,
                       "detail": "Participant-owned isolated worktree; ready for configured repository review policy"})
            return {"status": "submitted", "task_id": task["id"], "branch": isolation["branch"],
                    "commit": commit, "result": result, "workspace": str(workspace), "exchange": str(exchange)}
        except Exception as error:
            if not lost.is_set():
                try:
                    self._post(f"tasks/{task['id']}/block", {"claim_token": token, "reason": str(error),
                               "question": "How should this worker execution blocker be resolved?",
                               "options": ["Correct the environment and retry", "Revise the authorized task scope"],
                               "evidence": ["Participant worker could not produce a validated submission"],
                               "consequence": "Task remains blocked until a participant reconciles the issue."})
                except Exception:
                    pass
            raise
        finally:
            stopped.set()
            thread.join(timeout=2)

    def _guard_commit_outputs(self, workspace, files, result_text=''):
        # Inspect exactly the outputs we will add; never inspect private submission
        # files containing the legitimate expiring claim token.
        expected = {Path(name).as_posix() for name in files}
        staged = set(filter(None,_git(workspace,'diff','--cached','--name-only','-z').split('\0')))
        if staged-expected:
            raise ProviderError('Unexpected staged files are outside the declared task outputs; inspect them locally and list intended safe outputs before retrying', 'credential_output')
        candidates = []
        for key,value in os.environ.items():
            if (key.endswith(('_API_KEY','_TOKEN','_SECRET_ACCESS_KEY')) or key==self.active_profile.get('api_key_env')) and 8<=len(value)<=4096:
                candidates.append(value.encode('utf-8'))
        authorization = self.client.headers.get('Authorization','')
        if authorization.startswith('Bearer ') and 8<=len(authorization[7:])<=4096:
            candidates.append(authorization[7:].encode('utf-8'))
        try:
            tokens = json.loads(os.getenv('RESEARCHRELAY_TOKENS','{}'))
            if isinstance(tokens,dict):
                candidates.extend(value.encode('utf-8') for value in tokens if isinstance(value,str) and 8<=len(value)<=4096)
        except ValueError:
            pass
        candidates = tuple(set(candidates))
        guard_output_bytes(result_text.encode('utf-8'),candidates)
        for name in files:
            # This directory and runtime filenames are never eligible outputs.
            relative = Path(name)
            target = (workspace/relative).resolve()
            if not target.is_relative_to(workspace.resolve()) or '.researchrelay-exchange' in relative.parts or relative.name in {'submission.json','submission-id.txt'}:
                raise ProviderError('A private runtime file cannot be committed as task output', 'credential_output')
            overlap = b''
            with target.open('rb') as stream:
                while chunk := stream.read(65536):
                    data = overlap+chunk
                    guard_output_bytes(data,candidates)
                    overlap = data[-8192:]

    @staticmethod
    def _context_pins(project):
        return {'commit':project.get('sync',{}).get('latest_commit'),
                'documents':[{'path':document['path'],'sha256':document['sha256']}
                             for document in project.get('documents',[])]}

    def _agent_id(self):
        profile = self.active_profile
        return profile['provider']+'/'+(profile.get('model') or ('configured-agent' if profile['provider']=='command' else 'default'))

    @staticmethod
    def _sources(context):
        result = []
        seen = set()
        project = context.get('project',{})
        remote = (project.get('repository') or {}).get('url','')
        commit = project.get('sync',{}).get('latest_commit')
        web = None
        if remote.startswith('git@github.com:'):
            web = 'https://github.com/'+remote[len('git@github.com:'):].removesuffix('.git')
        elif remote.startswith('https://github.com/'):
            web = remote.removesuffix('.git')
        for document in project.get('documents',[]):
            source_id = document.get('metadata',{}).get('id') or 'document-'+hashlib.sha256(document['path'].encode()).hexdigest()[:12]
            if source_id in seen:
                source_id += '-'+hashlib.sha256(document['path'].encode()).hexdigest()[:8]
            seen.add(source_id)
            resource = web+'/blob/'+commit+'/'+quote(document['path'],safe='/') if web and commit else document['path']
            result.append({'resource':resource,'id':source_id})
        for item in context.get('input_artifacts',[]):
            source_id = item['id']
            if source_id in seen:
                source_id += '-artifact-v'+str(item['version'])
            seen.add(source_id)
            result.append({'resource':f"artifact:{item['id']}@{item['version']}",'id':source_id})
        return result

    def _prepare_project_repository(self, project):
        configuration = project.get('repository')
        if not configuration:
            return 'HEAD'
        remote = configuration['url']
        branch = configuration['branch']
        expected = project.get('sync',{}).get('latest_commit')
        if not expected:
            raise RuntimeError('Project context has no synchronized commit; refresh synchronization before starting')
        path = self.repository.path
        environment = dict(os.environ,GIT_TERMINAL_PROMPT='0')
        environment.setdefault('GIT_SSH_COMMAND','ssh -o BatchMode=yes')
        def git(*arguments):
            result = subprocess.run(['git',*arguments],capture_output=True,text=True,encoding='utf-8',
                                    timeout=90,env=environment)
            if result.returncode:
                raise RuntimeError('Participant Git access failed; check your own SSH/HTTPS repository permission and refresh project context')
            return result.stdout.strip()
        if not (path/'.git').exists():
            if path.exists() and any(path.iterdir()):
                raise RuntimeError('Worker clone directory is nonempty; use an existing project clone or a new empty directory')
            path.parent.mkdir(parents=True,exist_ok=True)
            git('clone','--single-branch','--branch',branch,'--',remote,str(path))
        origin = git('-C',str(path),'remote','get-url','origin')
        def canonical(value):
            if value.startswith('git@github.com:'):
                return value[len('git@github.com:'):].removesuffix('.git').lower()
            if value.startswith('https://github.com/'):
                return value[len('https://github.com/'):].removesuffix('.git').lower()
            return str(Path(value).expanduser().resolve())
        if canonical(origin) != canonical(remote):
            raise RuntimeError('Participant clone origin differs from the configured shared project repository')
        git('-C',str(path),'fetch','--no-tags','origin',f'refs/heads/{branch}:refs/remotes/origin/{branch}')
        actual = git('-C',str(path),'rev-parse',f'refs/remotes/origin/{branch}')
        if actual != expected:
            raise RuntimeError('Shared repository advanced while task context was prepared; refresh and retry with its latest commit')
        return expected

    def _report(self, workspace, lost, context):
        import sys
        report = generate_report(self.active_profile,context,self.timeout,lost,workspace)
        task = context['task']
        project = context.get('project',{})
        timestamp = datetime.now(timezone.utc).isoformat()
        version = (task.get('result_ref') or {}).get('version',0)+1
        metadata = {'id':f"result-{task['id']}",'project_id':task['project_id'],
                    'artifact_type':'result','schema_version':'1.0','version':version,'task_id':task['id'],
                    'responsible_participant':task['owner'],'producing_agent':self._agent_id(),
                    'created_at':timestamp,'updated_at':timestamp,'objective':task['objective'],
                    'input_refs':task.get('input_refs',[]),'acceptance_criteria':task.get('acceptance_criteria',[]),
                    'data':self._context_pins(project)['documents'] or [{'description':'Task-supplied input artifacts and authorized objective'}],
                    'code':[{'component':'researchrelay.providers','execution':'Participant-local report synthesis; no scientific code execution claimed'}],
                    'configuration':{'provider':self.active_profile['provider'],'model':self.active_profile.get('model')},
                    'environment':{'python':sys.version.split()[0],'execution':'participant-owned provider adapter'},
                    'evidence':report['findings'],'assumptions':report['assumptions'],
                    'limitations':report['limitations']+['A provider report is not an independently verified scientific conclusion.'],
                    'validation_results':report['validation_results']+['JSON research report schema validated; independent review pending'],
                    'unresolved_questions':report['unresolved_questions'],'next_actions':report['next_actions'],
                    'citations':report['citations'],'relations':[], 'format_status':'provisional','type':'Research Result',
                    'sources':self._sources(context),'generated':{'by':self._agent_id(),'at':timestamp},
                    'provenance':{'execution_kind':'provider_report','context_commit':project.get('sync',{}).get('latest_commit')},
                    'project_context':self._context_pins(project)}
        (workspace/'.researchrelay-exchange/result.md').write_text(render_markdown(metadata,report['body']),encoding='utf-8')

    def _wait_for_manual(self, workspace: Path, lost: threading.Event) -> None:
        exchange = workspace / ".researchrelay-exchange"
        print(json.dumps({"status": "waiting_for_manual_result", "workspace": str(workspace), "exchange": str(exchange),
                          "instructions": "Use your own agent/tools to write .researchrelay-exchange/result.md; heartbeat remains active."}), flush=True)
        deadline = time.monotonic() + self.timeout
        while not (exchange / "result.md").exists():
            if lost.is_set():
                raise RuntimeError("Claim lost or task canceled while waiting for the participant result")
            if time.monotonic() >= deadline:
                raise RuntimeError("Timed out waiting for result.md; worktree retained for inspection")
            lost.wait(.25)

    def _claude(self, workspace: Path, lost: threading.Event) -> None:
        prompt = (
            "Execute the authorized scientific task in .researchrelay-exchange/task-context.json using the pinned input artifact versions. "
            "Work only in this worktree and within acceptance criteria. Do not change scope or publish/merge. "
            "Write .researchrelay-exchange/result.md as Markdown with YAML front matter matching .researchrelay-exchange/context-schema.json. "
            "Use artifact ID result-{task.id}, project_id from task, version task.revision_count+1. "
            "Include data and code paths with SHA256 checksums, configuration, environment, evidence, assumptions, "
            "limitations, validation_results, unresolved_questions, next_actions, input_refs and task_id. "
            "Do not invent successful computations or credentials. Record blockers in the result."
        )
        exchange = workspace / ".researchrelay-exchange"
        exchange.mkdir(exist_ok=True)
        (exchange / "context-schema.json").write_text(json.dumps(get_schema("result"), indent=2), encoding="utf-8")
        command = ["claude", "-p", prompt, "--output-format", "json", "--max-turns", "20",
                   "--permission-mode", "dontAsk", "--tools", self.allowed_tools,
                   "--allowedTools", self.allowed_tools]
        if self.active_profile.get('model'):
            command.extend(['--model',self.active_profile['model']])
        child_env = {k: v for k, v in os.environ.items() if not k.upper().startswith("RESEARCHRELAY_")}
        process = subprocess.Popen(command, cwd=workspace, env=child_env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                if lost.is_set() or time.monotonic() > deadline:
                    process.kill()
                    process.communicate(timeout=10)
                    raise RuntimeError("Claude stopped after cancellation/claim loss or execution timeout")
                try:
                    stdout, stderr = process.communicate(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode:
                raise RuntimeError(f"Claude CLI exited {process.returncode}; inspect participant CLI authentication and allowed tools")
            envelope = json.loads(stdout)
            if envelope.get("is_error"):
                raise RuntimeError("Claude reported an execution error; inspect participant environment")
            if not (exchange / "result.md").exists():
                raise RuntimeError("Claude did not write .researchrelay-exchange/result.md; inspect task scope and tool permissions")
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

    def resubmit(self, payload_path: str | Path, task_id: str) -> dict:
        return self._post(f"tasks/{task_id}/submit", json.loads(Path(payload_path).expanduser().read_text(encoding="utf-8")))

    def review(self, task_id: str, verdict: str, rationale: str,
               criteria: list[str], result_version: int) -> dict:
        return self._post(f"tasks/{task_id}/reviews", {"reviewer": self.participant, "verdict": verdict,
                          "rationale": rationale, "criteria": criteria, "result_version": result_version})

    def run(self, poll_seconds: float = 3, once: bool = False) -> None:
        while True:
            outcome = self.run_once()
            print(json.dumps(outcome, default=str), flush=True)
            if once:
                return
            time.sleep(poll_seconds)
