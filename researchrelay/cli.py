"""Command line entry points for the coordinator and participant workers."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="researchrelay", description="Experimental artifact-first scientific coordination")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Start the local coordinator and dashboard")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    demo = commands.add_parser("demo", help="Run the credential-free local scientific pilot")
    demo.add_argument("--db", help="New SQLite file for an independent pilot")
    demo.add_argument("--repo", help="Local project record repository")
    worker = commands.add_parser("worker", help="Run a participant-owned worker against the HTTP API")
    worker.add_argument("--server", default="http://127.0.0.1:8000")
    worker.add_argument("--participant", required=True)
    worker.add_argument("--repo", required=True, help="Participant's local project clone or empty directory")
    worker.add_argument("--mode", choices=["claude", "manual"], default="claude")
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--timeout", type=int, default=600)
    worker.add_argument("--allowed-tools", default="Read,Write,Edit,Glob,Grep")
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
    args = parser.parse_args(argv)
    from .config import Settings
    settings = Settings()
    if args.command == "demo" and settings.mode != "demo":
        parser.error("The synthetic pilot is only available with RESEARCHRELAY_MODE=demo; select a separate demo database/repository")
    if args.command == "serve":
        if args.host not in {"127.0.0.1", "localhost", "::1"} and not settings.tokens:
            parser.error("Configure project-scoped RESEARCHRELAY_TOKENS before binding to a non-loopback interface")
        import uvicorn
        uvicorn.run("researchrelay.api:app", host=args.host, port=args.port)
        return
    if args.command == "worker":
        from .worker import Worker
        adapter = Worker(args.server, args.participant, args.repo, token=os.getenv("RESEARCHRELAY_TOKEN"),
                         mode=args.mode, timeout=args.timeout, allowed_tools=args.allowed_tools)
        if args.resubmit:
            if not args.task:
                parser.error("--resubmit requires --task")
            print(json.dumps(adapter.resubmit(args.resubmit, args.task), indent=2, default=str))
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
            from .pilot import run_pilot
            outcome = run_pilot(engine, repo.path)
        elif args.command == "export":
            outcome = repo.export(engine)
        elif args.command == "fetch":
            outcome = {"fetch": repo.fetch_reviewed(args.branch), "import": repo.import_artifacts(engine)}
        else:
            outcome = repo.import_artifacts(engine)
    print(json.dumps(outcome, indent=2, default=str))


if __name__ == "__main__":
    main()
