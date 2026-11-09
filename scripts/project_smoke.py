"""Real HTTP/CLI/local Git project workflow; scripted agents, no GitHub/model calls."""
from __future__ import annotations
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import httpx
from researchrelay.knowledge import parse_knowledge,render_knowledge

def main():
    checkout = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="ResearchRelay project smoke ") as directory:
        root = Path(directory).resolve()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1",0))
            port = reservation.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        environment = {k:v for k,v in os.environ.items() if not k.upper().startswith("RESEARCHRELAY_")}
        server = None
        with (root/"server.log").open("w",encoding="utf-8") as log:
            try:
                server = subprocess.Popen([sys.executable,"-m","researchrelay","serve","--project-demo","--port",str(port)],
                    cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT)
                with httpx.Client(base_url=url,timeout=120,trust_env=False) as client:
                    deadline = time.monotonic()+40
                    while True:
                        try:
                            client.get("/api/health").raise_for_status()
                            break
                        except httpx.HTTPError:
                            if server.poll() is not None or time.monotonic()>deadline:
                                raise AssertionError("Disposable project service did not start.")
                            time.sleep(.1)
                    def call(actor,method,path,payload=None):
                        response = client.request(method,path,json=payload,
                            headers={"Authorization":"Bearer local-demo-"+actor})
                        response.raise_for_status()
                        return response.json()
                    project = call("alice","POST","/api/hub/projects",dict(request_id="smoke-create",
                        name="Collaborative literature",description="A transport evaluation using a supplied verified source note.",
                        objectives="Trace evidence and handoffs. No productivity claim or fresh literature search.",
                        collaborators=["bob"],mode="new_repository",repository="alice/literature"))["project"]
                    project_url = url+project["url"]
                    prefix = project["knowledge_path"]
                    joined = call("bob","POST","/api/hub/projects/join",dict(repository=project["repository"],
                        branch=project["branch"],knowledge_path=prefix))["project"]
                    assert joined["id"]==project["id"]
                    # Publish one supplied source note through the real CLI.
                    source = checkout/"projects/agentic-collaboration/sources/wu-2024-autogen.md"
                    meta,body = parse_knowledge(source.read_text(encoding="utf-8"),path=source.name)
                    meta.update(project_id=project["id"],responsible_participant="alice",
                        producing_agent="manual/alice",generated=dict(by="manual/alice",at=meta["updated_at"]))
                    prepared = root/"source.md"
                    prepared.write_bytes(render_knowledge(meta,body).encode())
                    def cli(actor,*args):
                        completed = subprocess.run([sys.executable,"-m","researchrelay",*args],
                            cwd=root,env=dict(environment,GH_TOKEN="local-demo-"+actor),
                            capture_output=True,text=True,encoding="utf-8",timeout=180)
                        assert completed.returncode==0,completed.stderr[-1200:]
                        records = []
                        for line in completed.stdout.splitlines():
                            try:records.append(json.loads(line))
                            except ValueError:pass
                        return completed.stdout,records
                    context_file = root/"context.json"
                    cli("alice","project","context","--server",project_url,"--output",str(context_file))
                    cli("alice","project","publish","--server",project_url,"--context",str(context_file),
                        "--file",str(prepared),"--path",prefix+"/sources/autogen.md","--request-id","smoke-source")
                    context = call("bob","GET",project["url"]+"/api/project/context")
                    assert any(d["path"].endswith("/sources/autogen.md") for d in context["documents"])
                    # Two participant-owned scripted agents use the existing provider-neutral command adapter.
                    command = root/"agent.py"
                    command.write_text("""import json,sys
context=json.load(sys.stdin)
assert context['project']['documents']
print(json.dumps({'body':'# Scripted literature handoff\\n\\nThe supplied AutoGen note describes configurable multi-agent conversations. This checks transport only; no fresh search, model inference, productivity gain or human scientific judgment.',
'findings':['A shared version-pinned source note was retrieved.'],
'citations':['https://arxiv.org/abs/2308.08155'],
'assumptions':['Supplied verified source note is the evidence.'],
'limitations':['Scripted transport demonstration, not an independent literature finding.'],
'validation_results':['Read shared project context and task inputs.'],
'unresolved_questions':['Which coordination failures should a working session measure?'],
'next_actions':['Review the evidence and decide the next search scope.']}))
""",encoding="utf-8",newline="\n")
                    command_file = root/"command.json"
                    command_file.write_text(json.dumps([sys.executable,str(command)]),encoding="utf-8")
                    result_paths = {}
                    for actor,task_id,dependency in [("alice","source-review",None),("bob","review-synthesis","source-review")]:
                        inputs = [{"id":"result-source-review","version":1}] if dependency else []
                        call(actor,"POST",project["url"]+"/api/tasks",dict(id=task_id,title=task_id,
                            owner=actor,objective="Review the supplied evidence and limitations",
                            dependencies=[dependency] if dependency else [],input_refs=inputs,
                            acceptance_criteria=["Identify the supplied source and state demonstration limitations"]))
                        _,records = cli(actor,"worker","--server",project_url,"--participant",actor,
                            "--repo",str(root/(actor+" clone")),"--provider","command",
                            "--command-file",str(command_file),"--once","--timeout","60")
                        submitted = next(item for item in records if item.get("status")=="submitted")
                        result_paths[actor] = submitted["result_path"]
                        reviewer = "bob" if actor=="alice" else "alice"
                        call(reviewer,"POST",project["url"]+"/api/tasks/"+task_id+"/reviews",dict(
                            reviewer=reviewer,verdict="approve",rationale="Transport and source provenance demonstrated; scientific interpretation remains open.",
                            criteria=["Source citation present","Scripted transport limitation explicit"],result_version=1))
                        cli(actor,"project","context","--server",project_url,"--output",str(context_file))
                        cli(actor,"project","publish","--server",project_url,"--context",str(context_file),
                            "--file",result_paths[actor],"--path",prefix+"/results/"+actor+".md",
                            "--request-id","smoke-result-"+actor)
                    final = call("alice","GET",project["url"]+"/api/project/context")
                    assert all(task["status"]=="completed" for task in final["tasks"])
                    assert any(d["path"].endswith("/results/bob.md") for d in final["documents"])
                    # A stale edit cannot overwrite Bob's newer revision.
                    path = prefix+"/results/bob.md"
                    original = next(d for d in final["documents"] if d["path"]==path)
                    modified_meta,modified_body = parse_knowledge(original["content"],path=path)
                    modified_meta.update(responsible_participant="bob",producing_agent="manual/bob")
                    updated = render_knowledge(modified_meta,modified_body+"\n\n## Follow-up\nRecord study limitations.")
                    proposal = dict(expected_repository=final["repository"],base_commit=final["sync"]["latest_commit"],
                        changes=[dict(path=path,content=updated,expected_sha256=original["sha256"])],agent="manual/bob",
                        request_id="smoke-extend",message="Record a subsequent contribution")
                    call("bob","POST",project["url"]+"/api/project/publish",proposal)
                    modified_meta.update(responsible_participant="alice",producing_agent="manual/alice")
                    proposal.update(request_id="smoke-stale",agent="manual/alice",
                        changes=[dict(path=path,content=render_knowledge(modified_meta,modified_body),expected_sha256=original["sha256"])])
                    rejected = client.post(project["url"]+"/api/project/publish",json=proposal,
                        headers={"Authorization":"Bearer local-demo-alice"})
                    assert rejected.status_code==409
                    print(json.dumps(dict(status="passed",transport="real HTTP, CLI, SQLite and local Git",
                        integrations="simulated GitHub identities, scripted command agents; no GitHub writes or model inference",
                        checks=["project initialization","Bob joins same coordinator","CLI context and publication",
                            "two participant-owned workers","dependency and pinned input handoff","independent reviews",
                            "auditable result publication","latest update retrieval","stale edit rejected"],
                        project=project["id"])))
            finally:
                if server is not None and server.poll() is None:
                    server.terminate()
                    try:server.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        server.kill();server.wait(timeout=10)

if __name__=="__main__":
    main()
