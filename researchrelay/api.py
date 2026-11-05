"""Web interface and provider-neutral worker protocol; see /docs for OpenAPI."""
from __future__ import annotations

import logging
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .artifacts import render_markdown, get_schema
from .config import Settings
from .engine import Engine, WorkflowError
from .sync import ProjectSync, SyncError


class Payload(BaseModel):
    model_config = {'extra': 'forbid'}


class TaskProposal(Payload):
    id: str | None = None
    title: str
    owner: str
    objective: str = ''
    dependencies: list[str] = Field(default_factory=list)
    input_refs: list[dict] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(min_length=1)
    provenance: str | dict = 'human_approved'
    source_quote: str = ''
    max_attempts: int = Field(default=5, ge=1, le=10)
    # Extraction includes uncertainty for the human scope editor.
    inferred_fields: list[str] = Field(default_factory=list)
    confirmed: bool | None = None
    scope_status: str = 'proposed'


class Claim(Payload):
    worker_id: str = Field(min_length=1,max_length=200)
    lease_seconds: int = Field(default=120,ge=1,le=3600)


class Heartbeat(Payload):
    claim_token: str
    progress: str = ''
    lease_seconds: int = Field(default=120,ge=1,le=3600)


class Artifact(Payload):
    metadata: dict[str, Any]
    body: str = Field(default='',max_length=2_000_000)


class Submission(Payload):
    claim_token: str
    idempotency_key: str
    artifact: Artifact
    completion_notes: str = ''


class Block(Payload):
    claim_token: str
    reason: str = Field(min_length=1)
    question: str | None = None
    options: list[str] | None = None
    evidence: list[str] | None = None
    consequence: str | None = None


class Review(Payload):
    reviewer: str
    verdict: str
    rationale: str
    criteria: list[str]
    result_version: int = Field(ge=1)


class Meeting(Payload):
    notes: str = Field(min_length=1,max_length=200_000)
    participant: str = 'human'


class Scope(Payload):
    tasks: list[TaskProposal] = Field(min_length=1,max_length=100)


class Resolution(Payload):
    participant: str = 'human'
    choice: str
    rationale: str


class DecisionRequest(Payload):
    question: str
    evidence: list[str]
    options: list[str]
    consequence: str
    participant: str = 'human'
    task_id: str | None = None


class Metric(Payload):
    participant: str = 'human'
    kind: str
    value: float
    note: str = ''


class Retry(Payload):
    input_refs: list[dict] | None = None


class RepositoryLink(Payload):
    branch: str
    commit: str
    pr: str | None = None
    detail: str = ''


class SharedRepository(Payload):
    url: str = Field(min_length=1,max_length=500)
    branch: str = Field(min_length=1,max_length=200)
    knowledge_path: str = Field(min_length=1,max_length=300)


class KnowledgeChange(Payload):
    path: str
    content: str = Field(max_length=1_000_000)
    expected_sha256: str | None = Field(default=None,pattern=r"^[0-9a-f]{64}$")


class KnowledgePublication(Payload):
    expected_repository: SharedRepository
    base_commit: str
    changes: list[KnowledgeChange] = Field(min_length=1,max_length=30)
    agent: str = Field(min_length=1,max_length=200)
    request_id: str = Field(min_length=1,max_length=128)
    message: str = Field(min_length=1,max_length=300)


def create_app(settings: Settings | None = None, engine: Engine | None = None):
    settings = settings or Settings()
    coordinator = engine or Engine(settings.db_path,settings.project_id)
    synchronizer = ProjectSync(settings,coordinator)
    pool = ThreadPoolExecutor(max_workers=1,thread_name_prefix='pilot')

    @asynccontextmanager
    async def lifespan(app):
        coordinator.recover_jobs()
        yield
        pool.shutdown(wait=False,cancel_futures=True)

    app = FastAPI(title='ResearchRelay · Scientific Agent Coordination',version='0.1.0',lifespan=lifespan,
                  description='One project per service. SQLite owns state; immutable Markdown artifacts travel between agents.')
    app.state.engine = coordinator
    app.state.settings = settings
    app.state.project_sync = synchronizer

    @app.middleware('http')
    async def project_auth(request: Request, call_next):
        request.state.participant = 'human'
        if request.url.path.startswith('/api') and request.url.path != '/api/health':
            if settings.tokens:
                bearer = request.headers.get('Authorization','')
                token = bearer[7:] if bearer.startswith('Bearer ') else ''
                participant = next((owner for secret,owner in settings.tokens.items()
                                    if token and secrets.compare_digest(secret,token)),None)
                if not participant:
                    return JSONResponse({'detail':'Project bearer token required. Configure the session token in the dashboard.'},status_code=401)
                request.state.participant = participant
            elif request.client and request.client.host not in {'127.0.0.1','::1','localhost','testclient'}:
                return JSONResponse({'detail':'Unauthenticated demonstration is loopback only. Configure project tokens for team access.'},status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @app.exception_handler(SyncError)
    async def sync_error(request,error):
        return JSONResponse({'detail':str(error),'kind':error.kind,'paths':error.paths,
                             'next_action':error.next_action,'sync':synchronizer.status()},status_code=error.status)

    @app.exception_handler(WorkflowError)
    async def workflow_error(request, error):
        return JSONResponse({'detail':str(error)},status_code=error.status)

    @app.exception_handler(ValueError)
    async def validation_error(request,error):
        return JSONResponse({'detail':str(error)},status_code=422)

    from .repository import RepositoryConflict

    @app.exception_handler(RepositoryConflict)
    async def repository_error(request,error):
        return JSONResponse({'detail':str(error),'next_action':'Reconcile the retained Git branch or immutable artifact versions before retrying.'},status_code=409)

    def human(request):
        if settings.tokens and request.state.participant != 'human':
            raise HTTPException(403,'Human coordinator token required to change approved scope or resolve scientific decisions')

    def owner(request,task_id):
        task = coordinator.get_task(task_id)
        if settings.tokens and request.state.participant not in {'human',task['owner']}:
            raise HTTPException(403,'This task belongs to a different participant')
        return task

    def public_task(task):
        return {k:v for k,v in task.items() if k != 'claim_token'}

    @app.get('/api/health')
    def health():
        return {'status':'ok','project_id':settings.project_id,'mode':settings.mode}

    @app.get('/api/dashboard')
    def dashboard(request: Request,participant: str='human',since: int=0):
        identity = request.state.participant if settings.tokens else participant
        synchronizer.refresh()
        return {**coordinator.dashboard(identity,since),'mode':settings.mode,'project':synchronizer.public(identity)}

    @app.get('/api/project')
    def project(request: Request):
        synchronizer.refresh()
        return synchronizer.public(request.state.participant)

    @app.put('/api/project/repository')
    def configure_shared_project(data: SharedRepository,request: Request):
        human(request)
        synchronizer.configure(**data.model_dump())
        return synchronizer.public(request.state.participant)

    @app.post('/api/project/sync')
    def refresh_shared_project():
        return synchronizer.refresh(force=True,require=bool(synchronizer.binding))

    @app.get('/api/project/context')
    def shared_context(request: Request):
        return synchronizer.context(request.state.participant,force=True)

    @app.post('/api/project/publish')
    def publish_shared_knowledge(data: KnowledgePublication,request: Request):
        if sum(len(change.content.encode("utf-8")) for change in data.changes)>2_000_000:
            raise HTTPException(413,"Publish at most 2 MB of Markdown per request")
        return synchronizer.publish(request.state.participant,**data.model_dump())

    @app.get('/api/participants/me/agent')
    def own_agent(request: Request):
        return synchronizer.agent_profile(request.state.participant)

    @app.put('/api/participants/me/agent')
    def configure_own_agent(data: dict,request: Request):
        return synchronizer.agent_profile(request.state.participant,data)

    @app.get('/api/tasks')
    def tasks(owner: str | None=None,ready: bool=False):
        return [public_task(t) for t in coordinator.list_tasks(owner,ready)]

    @app.get('/api/tasks/{task_id}')
    def task(task_id: str):
        return public_task(coordinator.get_task(task_id))

    @app.post('/api/tasks',status_code=201)
    def new_task(data: TaskProposal,request: Request):
        human(request)
        return coordinator.create_task(**data.model_dump(exclude_none=True))

    @app.post('/api/tasks/{task_id}/claim')
    def claim(task_id: str,data: Claim,request: Request):
        owner(request,task_id)
        synchronizer.refresh(force=True,require=bool(synchronizer.binding))
        task = coordinator.claim_task(task_id,**data.model_dump())
        task['project_commit'] = synchronizer.status().get('latest_commit')
        return task

    @app.post('/api/tasks/{task_id}/heartbeat')
    def heartbeat(task_id: str,data: Heartbeat,request: Request):
        owner(request,task_id)
        return coordinator.heartbeat(task_id,**data.model_dump())

    @app.post('/api/tasks/{task_id}/submit')
    def submit(task_id: str,data: Submission,request: Request):
        owner(request,task_id)
        def previously_accepted():
            with coordinator._tx() as db:
                return db.execute("SELECT 1 FROM submissions WHERE task_id=? AND key=?",
                                  (task_id,data.idempotency_key)).fetchone() is not None
        # Configuration and new submissions share a single source snapshot.
        # A rebind cannot slip between input validation and durable completion.
        with synchronizer._lock:
            try:
                if not previously_accepted():
                    synchronizer.check_inputs(data.artifact.metadata)
            except SyncError:
                if not previously_accepted():
                    raise
            response = coordinator.submit_result(task_id,**data.model_dump())
        response['task'] = public_task(response['task'])
        return response

    @app.post('/api/tasks/{task_id}/block')
    def block(task_id: str,data: Block,request: Request):
        owner(request,task_id)
        return public_task(coordinator.block_task(task_id,**data.model_dump()))

    @app.post('/api/tasks/{task_id}/cancel')
    def cancel(task_id: str,request: Request):
        human(request)
        return public_task(coordinator.cancel_task(task_id))

    @app.post('/api/tasks/{task_id}/retry')
    def retry(task_id: str,request: Request,data: Retry | None=None):
        human(request)
        return public_task(coordinator.retry_task(task_id,**(data.model_dump() if data else {})))

    @app.post('/api/tasks/{task_id}/reviews')
    def review(task_id: str,data: Review,request: Request):
        if settings.tokens and request.state.participant != data.reviewer:
            raise HTTPException(403,'Reviewer must match authenticated participant')
        return coordinator.review_task(task_id,**data.model_dump())

    @app.post('/api/tasks/{task_id}/repository')
    def repository_link(task_id: str,data: RepositoryLink,request: Request):
        owner(request,task_id)
        coordinator.record_repository(task_id,**data.model_dump())
        return public_task(coordinator.get_task(task_id))

    @app.get('/api/artifacts')
    def artifacts(all_versions: bool=True):
        return coordinator.list_artifacts(all_versions)

    @app.get('/api/artifacts/{artifact_id}/markdown',response_class=PlainTextResponse)
    def markdown(artifact_id: str,version: int | None=None):
        record = coordinator.get_artifact(artifact_id,version)
        return PlainTextResponse(render_markdown(record['metadata'],record['body']),headers={
            'Content-Disposition':f'attachment; filename="{record["id"]}.v{record["version"]}.md"'})

    @app.get('/api/artifacts/{artifact_id}')
    def artifact(artifact_id: str,version: int | None=None):
        return coordinator.get_artifact(artifact_id,version)

    @app.post('/api/artifacts',status_code=201)
    def put_artifact(data: Artifact,request: Request):
        if settings.tokens:
            identity = request.state.participant
            metadata = data.metadata
            if identity != 'human':
                if identity != metadata.get('responsible_participant'):
                    raise HTTPException(403,'Artifact responsibility must match participant')
                if metadata.get('artifact_type') in {'task','meeting'}:
                    raise HTTPException(403,'Human coordinator token required to publish scope records')
                try:
                    previous = coordinator.get_artifact(metadata.get('id'))
                except WorkflowError as error:
                    if error.status != 404:
                        raise
                else:
                    if previous['metadata']['responsible_participant'] != identity:
                        raise HTTPException(403,'Existing artifact responsibility belongs to another participant; request human reconciliation')
            if metadata.get('artifact_type') == 'result':
                task = coordinator.get_task(metadata.get('task_id'))
                if identity not in {'human',task['owner']}:
                    raise HTTPException(403,'Result task belongs to another participant')
                if metadata.get('responsible_participant',task['owner']) != task['owner']:
                    raise HTTPException(403,'Result responsibility must match its approved task owner')
                metadata['responsible_participant'] = task['owner']
        return coordinator.put_artifact(**data.model_dump())

    @app.get('/api/schemas/{artifact_type}')
    def schema(artifact_type: str):
        return get_schema(artifact_type)

    @app.post('/api/meetings',status_code=201)
    def meeting(data: Meeting,request: Request):
        human(request)
        if settings.tokens:
            data.participant = request.state.participant
        return coordinator.create_meeting(**data.model_dump())

    @app.post('/api/meetings/upload',status_code=201)
    async def upload(request: Request,file: UploadFile=File(...),participant: str=Form('human')):
        human(request)
        if settings.tokens:
            participant = request.state.participant
        content = await file.read(200_001)
        if len(content)>200_000:
            raise HTTPException(413,'Use UTF-8 text meeting notes under 200 KB')
        try:
            notes = content.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise HTTPException(415,'Upload UTF-8 .txt or .md notes')
        return coordinator.create_meeting(notes,participant)

    @app.post('/api/meetings/{meeting_id}/approve')
    def approve(meeting_id: str,data: Scope,request: Request):
        human(request)
        return coordinator.approve_meeting(meeting_id,[p.model_dump(exclude_none=True) for p in data.tasks])

    @app.post('/api/decisions')
    def decision(data: DecisionRequest):
        return coordinator.request_decision(**data.model_dump())

    @app.post('/api/decisions/{decision_id}/resolve')
    def resolve(decision_id: str,data: Resolution,request: Request):
        human(request)
        if settings.tokens:
            data.participant = request.state.participant
        return coordinator.resolve_decision(decision_id,**data.model_dump())

    @app.post('/api/metrics',status_code=201)
    def metric(data: Metric,request: Request):
        participant = request.state.participant if settings.tokens else data.participant
        return coordinator.add_metric(participant,data.kind,data.value,data.note)

    def run_background_pilot():
        from .pilot import run_pilot
        try:
            summary = run_pilot(coordinator,settings.repo_path)
            coordinator.finish_job('pilot','completed',summary)
        except Exception as error:
            logging.exception('Pilot failed')
            coordinator.finish_job('pilot','failed',{'error':str(error),'next_action':'Inspect task blockers and service logs; retry the pilot.'})

    @app.post('/api/pilot/run',status_code=202)
    def pilot(request: Request):
        human(request)
        if settings.mode != 'demo':
            raise HTTPException(409,'The cached-literature demonstration is only available in explicitly labeled demo mode')
        if synchronizer.binding:
            raise HTTPException(409,'Use a dedicated demo database without a configured shared repository; approve real literature tasks separately for participant agents.')
        job,created = coordinator.start_job()
        if created:
            pool.submit(run_background_pilot)
        return job

    @app.get('/api/pilot/status')
    def pilot_status():
        return coordinator.job_status()

    @app.post('/api/repository/export')
    def export(request: Request):
        human(request)
        from .repository import Repository
        return Repository(settings.repo_path).export_state(coordinator)

    @app.post('/api/repository/import')
    def import_records(request: Request):
        human(request)
        from .repository import Repository
        return Repository(settings.repo_path).import_state(coordinator)

    static = Path(__file__).parent/'static'
    app.mount('/static',StaticFiles(directory=static,check_dir=False),name='static')

    @app.get('/',include_in_schema=False)
    def index():
        return FileResponse(static/'index.html')

    return app


def __getattr__(name):
    # Keep uvicorn's existing api:app entry point while making imports safe for
    # tools/tests: opening a module must not initialize a user's live database.
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
