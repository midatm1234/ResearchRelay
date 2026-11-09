"""Command line entry points for the coordinator and participant workers."""
from __future__ import annotations

import argparse
import json
import os
import hashlib
import httpx
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="researchrelay", description="Experimental artifact-first scientific coordination")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the local coordinator and dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action=argparse.BooleanOptionalAction, default=None,
                       help="Reload Python changes automatically (default on loopback; --no-reload disables)")
    serve.add_argument("--project-demo",action="store_true",help="Serve credential-free multi-project creation with simulated GitHub accounts and real local Git")
    serve.add_argument("--offline-demo",action="store_true",help="Serve an explicitly offline cached literature demo in isolated local state")
    serve.add_argument("--db",help="Offline-demo SQLite path; requires --offline-demo")
    serve.add_argument("--repo",help="Offline-demo local record path; requires --offline-demo")
    demo = commands.add_parser("demo", help="Run the credential-free local scientific pilot")
    demo.add_argument("--offline",action="store_true",help="Use isolated local demo state without a GitHub binding")
    demo.add_argument("--db", help="New SQLite file for an independent pilot")
    demo.add_argument("--repo", help="Local project record repository")
    literature = commands.add_parser("literature-pilot",help="Run two participant agents against verified literature and a real Git remote")
    literature.add_argument("--remote",help="Local bare remote, or explicit GitHub SSH/HTTPS URL with --live")
    literature.add_argument("--branch",default="SRTD_DT_test")
    literature.add_argument("--workspace",help="New empty workspace; defaults to .runtime/literature-pilot-<run>")
    literature.add_argument("--live",action="store_true",help="Explicitly publish to the GitHub SRTD_DT_test branch")
    worker = commands.add_parser("worker", help="Run a participant-owned worker against the HTTP API")
    worker.add_argument("--server", default="http://127.0.0.1:8000")
    worker.add_argument("--participant", required=True)
    worker.add_argument("--repo", required=True, help="Participant's local project clone or empty directory")
    worker.add_argument("--mode", choices=["claude", "manual"], help="Legacy explicit Claude/manual selection")
    worker.add_argument("--provider", choices=['claude-cli','openai-responses','openai-compatible','command','manual','vscode'])
    worker.add_argument("--model")
    worker.add_argument("--base-url")
    worker.add_argument("--api-key-env", help="Provider credential environment variable name; never its value")
    worker.add_argument("--command-file", help="JSON array of argv strings for a participant-local agent")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--open-editor", action="store_true", help="Explicitly launch VS Code for a vscode handoff")
    worker.add_argument("--resume-handoff", help="Resume the same unexpired editor claim using its private state path")
    worker.add_argument("--timeout", type=int, default=600)
    worker.add_argument("--allowed-tools", help="Override own profile Claude tools")
    worker.add_argument("--resubmit", help="Retry exact saved submission.json after a network interruption")
    worker.add_argument("--task", help="Task ID for --resubmit")
    for action in ("export", "import"):
        command = commands.add_parser(action, help=f"{action.title()} portable repository artifacts")
        command.add_argument("--db")
        command.add_argument("--repo")
    publish = commands.add_parser("publish", help="Explicitly push a task branch and open/reuse a draft GitHub PR")
    publish.add_argument("--repo", required=True)
    publish.add_argument("--github", required=True, help="owner/repository (must match origin)")
    publish.add_argument("--branch", required=True)
    publish.add_argument("--base", default=None, help="Defaults to RESEARCHRELAY_GITHUB_BASE (main)")
    publish.add_argument("--title", required=True)
    publish.add_argument("--body-file", required=True)
    sync = commands.add_parser("fetch", help="Fast-forward reviewed Git changes, then import artifacts")
    sync.add_argument("--repo")
    sync.add_argument("--db")
    sync.add_argument("--branch", default="main")
    project = commands.add_parser('project',help='Retrieve synchronized project context and publish prepared Markdown')
    project_commands = project.add_subparsers(dest='project_action',required=True)
    for action in ('configure','context','sync','publish'):
        action_parser = project_commands.add_parser(action)
        action_parser.add_argument('--server',default='http://127.0.0.1:8000')
        if action=='configure':
            action_parser.add_argument('--url',required=True)
            action_parser.add_argument('--branch',required=True)
            action_parser.add_argument('--knowledge-path',required=True)
        elif action=='context':
            action_parser.add_argument('--output')
        elif action=='publish':
            action_parser.add_argument('--context',required=True,help='Saved exact project context JSON')
            action_parser.add_argument('--file',required=True,help='Prepared structured Markdown')
            action_parser.add_argument('--path',required=True,help='Repository-relative target below knowledge_path')
            action_parser.add_argument('--agent',help='Producing agent; defaults to prepared artifact metadata')
            action_parser.add_argument('--request-id',help='Stable idempotency key; otherwise derived from the exact draft/context')
            action_parser.add_argument('--message',default='Record participant agent contribution')
    agent = commands.add_parser("agent",help="Configure this authenticated participant's non-secret agent profile")
    agent_commands = agent.add_subparsers(dest='agent_action',required=True)
    for action in ('show','configure'):
        action_parser = agent_commands.add_parser(action)
        action_parser.add_argument('--server',default='http://127.0.0.1:8000')
        if action=='configure':
            action_parser.add_argument('--provider',required=True,choices=['claude-cli','openai-responses','openai-compatible','command','manual','vscode'])
            action_parser.add_argument('--model')
            action_parser.add_argument('--base-url')
            action_parser.add_argument('--api-key-env')
            action_parser.add_argument('--command-file')
            action_parser.add_argument('--allowed-tools')
    args = parser.parse_args(argv)
    if args.command in {'project','agent'}:
        try:
            outcome = _shared_command(args)
        except (RuntimeError,ValueError,httpx.HTTPError) as error:
            parser.exit(2,str(error)+'\n')
        print(json.dumps(outcome,indent=2,default=str))
        return
    if args.command=="literature-pilot":
        from .shared_pilot import run_shared_pilot
        print(json.dumps(run_shared_pilot(args.remote,args.branch,args.workspace,args.live),indent=2))
        return
    if args.command=='serve' and args.project_demo:
        if args.offline_demo or args.host not in {'127.0.0.1','localhost','::1'}:
            parser.error('--project-demo requires loopback and cannot be combined with --offline-demo')
        origin_host = f'[{args.host}]' if ':' in args.host else args.host
        os.environ.update(RESEARCHRELAY_PROJECT_DEMO='1',RESEARCHRELAY_MODE='demo',
            RESEARCHRELAY_GITHUB_URL='',RESEARCHRELAY_TOKENS='{}',
            RESEARCHRELAY_DB='.runtime/project-demo/default/state.db',
            RESEARCHRELAY_REPO='.runtime/project-demo/default/record',
            RESEARCHRELAY_HUB_PATH='.runtime/project-demo/hub',
            RESEARCHRELAY_PUBLIC_URL=f'http://{origin_host}:{args.port}')
    offline = ((args.command=='serve' and args.offline_demo)
               or (args.command=='demo' and args.offline))
    if args.command=='serve' and (args.db or args.repo) and not args.offline_demo:
        parser.error('serve --db/--repo require --offline-demo; configure the normal project through its environment or project API')
    if offline:
        os.environ.update(RESEARCHRELAY_MODE='demo',RESEARCHRELAY_GITHUB_URL='',
                          RESEARCHRELAY_PROJECT='agentic-collaboration',RESEARCHRELAY_TOKENS='{}',
                          RESEARCHRELAY_DB=args.db or '.runtime/offline-demo/state.db',
                          RESEARCHRELAY_REPO=args.repo or '.runtime/offline-demo/project-record')
    from .config import Settings
    settings = Settings()
    if args.command == "demo" and (settings.mode != "demo" or settings.github_url):
        parser.error("The cached literature demo requires RESEARCHRELAY_MODE=demo and an unbound repository; run researchrelay demo --offline with a separate demo database/repository")
    if args.command == "serve":
        if args.offline_demo:
            from .engine import Engine
            from .sync import ProjectSync
            if ProjectSync(settings,Engine(settings.db_path,project_id=settings.project_id)).binding:
                parser.error('Offline service requires an unbound database; this database has a saved shared repository. Choose a separate --db/--repo; its saved binding was preserved')
        if args.host not in {"127.0.0.1", "localhost", "::1"} and not (settings.tokens or (settings.oauth_client_id and settings.oauth_client_secret and settings.public_url.startswith("https://"))):
            parser.error("Configure project-scoped tokens or GitHub OAuth with an HTTPS PUBLIC_URL before binding to a non-loopback interface")
        import uvicorn
        reload = args.reload if args.reload is not None else args.host in {"127.0.0.1", "localhost", "::1"}
        uvicorn.run("researchrelay.api:app", host=args.host, port=args.port, reload=reload,
                    reload_dirs=[str(Path(__file__).resolve().parent)] if reload else None)
        return
    if args.command == "worker":
        from .worker import Worker
        adapter = Worker(args.server, args.participant, args.repo, token=os.getenv("RESEARCHRELAY_TOKEN"),
                         mode=args.mode, timeout=args.timeout, allowed_tools=args.allowed_tools,
                         provider=args.provider,model=args.model,base_url=args.base_url,api_key_env=args.api_key_env,
                         command=_read_command(args.command_file),open_editor=args.open_editor)
        if args.resubmit:
            if not args.task:
                parser.error("--resubmit requires --task")
            print(json.dumps(adapter.resubmit(args.resubmit, args.task), indent=2, default=str))
        elif args.resume_handoff:
            print(json.dumps(adapter.run_once(resume_handoff=args.resume_handoff),indent=2,default=str))
        else:
            adapter.run(once=args.once)
        return
    from .repository import Repository
    if args.command == "publish":
        outcome = Repository(args.repo).publish_github(args.branch, args.title,
                    Path(args.body_file).expanduser().read_text(encoding="utf-8"), args.base or settings.github_base, args.github)
    else:
        from .engine import Engine
        engine = Engine(args.db or settings.db_path, project_id=settings.project_id)
        repo = Repository(args.repo or settings.repo_path)
        if args.command == "demo":
            from .sync import ProjectSync
            if ProjectSync(settings,engine).binding:
                parser.error("The cached literature demo requires a fresh unbound database/repository; this database is configured for a shared project")
            from .pilot import run_pilot
            outcome = run_pilot(engine, repo.path)
        elif args.command == "export":
            outcome = repo.export(engine)
        elif args.command == "fetch":
            outcome = {"fetch": repo.fetch_reviewed(args.branch), "import": repo.import_artifacts(engine)}
        else:
            outcome = repo.import_artifacts(engine)
    print(json.dumps(outcome, indent=2, default=str))


def _read_command(path):
    if not path:
        return None
    command = json.loads(Path(path).expanduser().read_text(encoding='utf-8'))
    if not isinstance(command,list) or any(not isinstance(part,str) for part in command):
        raise ValueError('Command file must contain a JSON array of argument strings')
    return command


def _shared_command(args):
    from .providers import validate_profile
    headers = {'Authorization':'Bearer '+os.environ['RESEARCHRELAY_TOKEN']} if os.getenv('RESEARCHRELAY_TOKEN') else {}
    with httpx.Client(base_url=args.server.rstrip('/')+'/api/',headers=headers,timeout=120,trust_env=False) as client:
        def request(method,route,payload=None):
            response = client.request(method,route,json=payload) if payload is not None else client.request(method,route)
            if response.is_error:
                try:
                    detail = response.json()
                except ValueError:
                    detail = {}
                message = f"ResearchRelay request failed (HTTP {response.status_code}): "+str(detail.get('detail','Check the project connection and participant permission.'))
                if detail.get('paths'):
                    message += ' Paths: '+', '.join(detail['paths'])+'.'
                if detail.get('next_action'):
                    message += ' Next: '+str(detail['next_action'])
                raise RuntimeError(message)
            return response.json()
        if args.command=='agent':
            if args.agent_action=='show':
                return request('GET','participants/me/agent')
            profile = {key:value for key,value in {'provider':args.provider,'model':args.model,'base_url':args.base_url,
                       'api_key_env':args.api_key_env,'command':_read_command(args.command_file),
                       'allowed_tools':args.allowed_tools}.items() if value is not None}
            return request('PUT','participants/me/agent',validate_profile(profile))
        if args.project_action=='configure':
            return request('PUT','project/repository',{'url':args.url,'branch':args.branch,'knowledge_path':args.knowledge_path})
        if args.project_action=='sync':
            return request('POST','project/sync',{})
        if args.project_action=='context':
            context = request('GET','project/context')
            if args.output:
                Path(args.output).expanduser().write_text(json.dumps(context,indent=2),encoding='utf-8')
            return context
        context = json.loads(Path(args.context).expanduser().read_text(encoding='utf-8'))
        repository = context.get('repository')
        if not isinstance(repository,dict) or not all(isinstance(repository.get(key),str) and repository[key] for key in ('url','branch','knowledge_path')):
            raise ValueError('Saved context has no valid repository binding; retrieve fresh project context and review the intended repository, branch, and knowledge directory before publishing')
        base_commit = context.get('sync',{}).get('latest_commit')
        if not base_commit:
            raise ValueError('Saved context has no synchronized commit; configure a repository and retrieve context first')
        content = Path(args.file).expanduser().read_text(encoding='utf-8')
        from .knowledge import parse_knowledge, render_knowledge
        metadata,body = parse_knowledge(content,project_id=context['project_id'],path=args.path)
        if not metadata.get('reserved'):
            content = render_knowledge(metadata,body)
        agent = args.agent or metadata.get('producing_agent') or 'manual/'+str(context.get('participant','participant'))
        previous = next((document for document in context.get('documents',[]) if document['path']==args.path),None)
        changes = [{'path':args.path,'content':content,'expected_sha256':previous['sha256'] if previous else None}]
        identity = [context.get('participant'),repository,base_commit,changes,agent]
        request_id = args.request_id or 'cli-'+hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:32]
        return request('POST','project/publish',{'base_commit':base_commit,'expected_repository':repository,'changes':changes,'agent':agent,
                       'request_id':request_id,'message':args.message})


if __name__ == "__main__":
    main()
