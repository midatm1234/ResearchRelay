"""GitHub-authenticated project management and existing coordinator routing."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from fastapi import Request, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, ConfigDict

from .project_hub import ProjectHub, HubError
from .managed_context import managed_identity

SESSION = "researchrelay_github"
PENDING = "researchrelay_oauth_pending"

class CreateProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1,max_length=128)
    name: str = Field(min_length=1,max_length=160)
    description: str = Field(default="",max_length=10000)
    objectives: str = Field(default="",max_length=20000)
    collaborators: list[str] = Field(default_factory=list,max_length=50)
    mode: str = Field(pattern="^(new_repository|new_branch|connect)$")
    repository: str = Field(min_length=1,max_length=200)
    branch: str = Field(default="",max_length=200)
    base_branch: str = Field(default="",max_length=200)
    visibility: str = Field(default="private",pattern="^(private|public)$")
    knowledge_path: str = Field(default="",max_length=300)
    initialize: bool = True

class JoinProject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str = Field(min_length=1,max_length=200)
    branch: str = Field(min_length=1,max_length=200)
    knowledge_path: str = Field(min_length=1,max_length=300)

class ProjectEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None,min_length=1,max_length=160)
    description: str | None = Field(default=None,max_length=10000)
    objectives: str | None = Field(default=None,max_length=20000)
    collaborators: list[str] | None = Field(default=None,max_length=50)

def install_hub(app,settings,hub=None):
    from .github_auth import GitHubAuth
    from .github_client import GitHubClient, GitHubError
    hub = hub or ProjectHub(settings)
    app.state.project_hub = hub
    if not hub.auth:
        if settings.project_demo:
            from .project_demo import DemoAuth, LocalGitHubClient
            hub.auth = DemoAuth(hub)
            hub.client_factory = lambda identity: LocalGitHubClient(hub.root/"demo-remotes",identity)
        else:
            hub.auth = GitHubAuth(hub.root/"auth.db",client_id=settings.oauth_client_id,
                client_secret=settings.oauth_client_secret,redirect_uri=settings.public_url+"/api/hub/auth/callback",
                key_path=hub.root/"auth.key")
            hub.client_factory = lambda identity: GitHubClient(identity.token)

    def error_response(error):
        return JSONResponse(dict(detail=str(error),next_action=getattr(error,"next_action",None),
            operation=getattr(error,"operation",None)),status_code=getattr(error,"status",503))

    @app.exception_handler(HubError)
    async def hub_error(request,error):
        return error_response(error)

    @app.exception_handler(GitHubError)
    async def github_error(request,error):
        return error_response(error)

    def origin_check(request):
        if request.method not in {"GET","HEAD","OPTIONS"}:
            origin = request.headers.get("origin")
            allowed = {settings.public_url}
            if origin and origin not in allowed:
                raise HTTPException(403,"Request origin does not match the ResearchRelay service.")
            if request.headers.get("sec-fetch-site")=="cross-site":
                raise HTTPException(403,"Cross-site project changes are not allowed.")

    def identity(request,optional=False):
        if settings.project_demo and request.client and request.client.host not in {"127.0.0.1","::1","localhost","testclient"}:
            raise HTTPException(403,"The credential-free project demonstration is loopback only.")
        origin_check(request)
        bearer = request.headers.get("authorization","")
        bearer = bearer[7:] if bearer.startswith("Bearer ") else None
        try:
            return hub.auth.identity(session_cookie=request.cookies.get(SESSION),bearer=bearer)
        except GitHubError as error:
            if optional and error.status==401:
                return None
            raise

    def cookie(response,name,value,max_age):
        response.set_cookie(name,value,max_age=max_age,httponly=True,
            secure=settings.public_url.startswith("https://"),samesite="lax",path="/")

    @app.get("/api/hub/status")
    def status(request: Request):
        who = identity(request,optional=True)
        return dict(configured=hub.auth.configured,demo=settings.project_demo,
            identity=who.public() if who else None,projects=hub.list_projects(who) if who else [],
            github_auth_url="/api/hub/auth/login")

    @app.get("/api/hub/auth/login")
    def login(request: Request):
        if settings.project_demo:
            raise HubError("Choose a local demonstration participant from Projects.",409)
        begin = hub.auth.begin_login()
        response = RedirectResponse(begin["authorization_url"],status_code=303)
        cookie(response,PENDING,begin["pending_cookie"],begin["expires_in"])
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/hub/auth/callback")
    def callback(request: Request,code: str="",state: str="",error: str=""):
        # Strip OAuth codes from Uvicorn's completion/access-log scope.
        request.scope["query_string"] = b""
        request.scope["raw_path"] = b"/api/hub/auth/callback"
        if error or not code or not state:
            response = RedirectResponse("/projects?auth_error=GitHub+sign-in+was+not+completed",status_code=303)
            response.delete_cookie(PENDING,path="/")
            return response
        try:
            result = hub.auth.finish_login(code,state,request.cookies.get(PENDING,""))
        except GitHubError:
            response = RedirectResponse("/projects?auth_error=GitHub+sign-in+failed.+Retry+Connect+GitHub.",status_code=303)
            response.delete_cookie(PENDING,path="/")
            return response
        response = RedirectResponse("/projects",status_code=303)
        cookie(response,SESSION,result["session_cookie"],result["expires_in"])
        response.delete_cookie(PENDING,path="/")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/hub/auth/demo")
    async def demo_login(request: Request):
        origin_check(request)
        if not settings.project_demo:
            raise HubError("Local demonstration sign-in is disabled.",404)
        if request.client and request.client.host not in {"127.0.0.1","::1","localhost","testclient"}:
            raise HubError("Local project demonstration is loopback only.",403)
        data = await request.json()
        token = hub.auth.sign_in(data.get("login","alice"))
        response = JSONResponse(dict(identity=hub.auth.identity(session_cookie=token).public(),demo=True))
        cookie(response,SESSION,token,28800)
        return response

    @app.post("/api/hub/auth/logout")
    def logout(request: Request):
        origin_check(request)
        hub.auth.logout(request.cookies.get(SESSION))
        response = JSONResponse(dict(status="signed_out"))
        response.delete_cookie(SESSION,path="/")
        return response

    @app.get("/api/hub/repositories")
    def repositories(request: Request,page: int=1):
        who = identity(request)
        if not 1<=page<=10000:
            raise HubError("Invalid repository page.",422)
        return dict(repositories=hub.client_factory(who).list_repositories(page=page,per_page=100),page=page)

    @app.get("/api/hub/repositories/{owner}/{repo}/branches")
    def branches(owner: str,repo: str,request: Request,page: int=1):
        who = identity(request)
        if not 1<=page<=10000:
            raise HubError("Invalid branch page.",422)
        return dict(branches=hub.client_factory(who).list_branches(owner,repo,page=page,per_page=100),page=page)

    @app.get("/api/hub/projects")
    def projects(request: Request):
        who = identity(request)
        return dict(projects=hub.list_projects(who))

    @app.post("/api/hub/projects",status_code=201)
    def new_project(data: CreateProject,request: Request):
        who = identity(request)
        return hub.create(who,data.model_dump())

    @app.post("/api/hub/projects/join")
    def join_project(data: JoinProject,request: Request):
        who = identity(request)
        project = hub.join(who,data.model_dump())
        return dict(project=hub.public(project,hub.permission(who,project)))

    @app.get("/api/hub/operations/{request_id}")
    def operation(request_id: str,request: Request):
        return dict(operation=hub.operation(request_id,identity(request)))

    @app.post("/api/hub/operations/{request_id}/resume")
    def resume_operation(request_id: str,request: Request):
        who = identity(request)
        saved = hub.operation(request_id,who)
        if not saved.get("original_input"):
            raise HubError("This older setup request requires a new explicit connection request.",409)
        return hub.create(who,saved["original_input"])

    @app.get("/api/hub/projects/{project_id}")
    def project(project_id: str,request: Request):
        who = identity(request)
        data = hub.record(project_id)
        role = hub.permission(who,data)
        data = hub.refresh_metadata(who,data)
        data = hub.register(who,data)
        return dict(project=hub.public(data,role))

    @app.patch("/api/hub/projects/{project_id}")
    def edit_project(project_id: str,data: ProjectEdit,request: Request):
        return dict(project=hub.update(identity(request),project_id,data.model_dump(exclude_none=True)))

    @app.post("/api/hub/projects/{project_id}/refresh")
    def refresh_project(project_id: str,request: Request):
        who = identity(request)
        project = hub.record(project_id)
        role = hub.permission(who,project)
        token = managed_identity.set(dict(identity=who,role=role,demo=settings.project_demo))
        try:
            project = hub.refresh_metadata(who,project)
            sync = hub.child(project_id).state.project_sync.refresh(force=True,require=True)
            commits = hub.client_factory(who).recent_commits(*project["repository"].split("/"),project["branch"])
            return dict(project=hub.public(project,role),sync=sync,commits=commits)
        finally:
            managed_identity.reset(token)

    static = Path(__file__).parent/"static"

    @app.get("/projects",include_in_schema=False)
    def projects_page():
        return FileResponse(static/"projects.html")

    @app.get("/projects/{project_id}",include_in_schema=False)
    def project_page(project_id: str,request: Request):
        # HTML contains no private project data; all API access is authenticated.
        return FileResponse(static/"index.html")

    @app.api_route("/projects/{project_id}/{route:path}",methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS","HEAD"],include_in_schema=False)
    async def project_api(project_id: str,route: str,request: Request):
        if not (route=="api" or route.startswith("api/") or route in {"docs","openapi.json","redoc"}):
            raise HTTPException(404,"Project route not found")
        # GitHub and SQLite calls are blocking; keep other users' requests responsive.
        from starlette.concurrency import run_in_threadpool
        who = await run_in_threadpool(identity,request)
        project = await run_in_threadpool(hub.record,project_id)
        role = await run_in_threadpool(hub.permission,who,project)
        child = await run_in_threadpool(hub.child,project_id)
        token = managed_identity.set(dict(identity=who,role=role,demo=settings.project_demo))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=child),base_url="http://managed.internal") as client:
                headers = {k:v for k,v in request.headers.items() if k.lower() not in {"host","authorization","cookie","content-length"}}
                response = await client.request(request.method,"/"+route,
                    params=list(request.query_params.multi_items()),headers=headers,content=await request.body())
                content = response.content
                if route in {"docs","redoc"}:
                    content = content.replace(b"/openapi.json",f"/projects/{project_id}/openapi.json".encode())
                return Response(content,status_code=response.status_code,
                    headers={k:v for k,v in response.headers.items() if k.lower() not in {"content-length","transfer-encoding","content-encoding","set-cookie"}})
        finally:
            managed_identity.reset(token)
