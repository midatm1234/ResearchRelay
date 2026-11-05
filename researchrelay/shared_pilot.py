"""Two participant-owned command agents, real HTTP API, and real Git handoffs.

Default: isolated local bare repository. --live explicitly permits SSH publication
to the requested SRTD_DT_test branch. No commercial model inference is simulated
as live inference; the executable report adapter is deliberately scripted.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from fastapi.testclient import TestClient

from .api import create_app
from .config import Settings
from .engine import Engine
from .knowledge import render_knowledge, validate_bundle
from .worker import Worker

PROJECT = "agentic-collaboration"
PREFIX = f"projects/{PROJECT}"

PRODUCER = r"""
import json,sys
context=json.load(sys.stdin)
documents=context['project']['documents']
task=context['task']
def source(suffix):
    return next(document for document in documents if document['path'].endswith(suffix))
autogen=source('/sources/wu-2024-autogen.md')
url=autogen['metadata']['sources'][0]['resource']
if task['owner']=='alice':
    body=('# Verified literature finding\n\n'
          'AutoGen describes configurable multi-agent conversations involving models, people, and tools. '
          'This supports explicit coordination interfaces in ResearchRelay; it does not establish that '
          'unattended agents produce scientifically valid conclusions. Source: ['+autogen['metadata']['title']+']('+url+').\n\n'
          'Connection test: this report was emitted by a participant-local scripted command adapter, not a paid model API.')
    findings=['Programmable conversation patterns are an architectural precedent, not proof of scientific validity.']
    citations=[url]
else:
    finding=next(document for document in documents if document['path']==sys.argv[1])
    assert 'AutoGen' in finding['body']
    assert context['input_artifacts'], 'The dependent task must consume the first accepted result.'
    remote=context['project']['repository']['url']
    repository=('https://github.com/'+remote.split(':',1)[1]) if remote.startswith('git@github.com:') else remote
    commit=context['project']['sync']['latest_commit']
    finding_ref=('['+'the preceding finding'+']('+repository.removesuffix('.git')+'/blob/'+commit+'/'+sys.argv[1]+')'
                 if repository.startswith('https://github.com/') else '`'+sys.argv[1]+'` at commit `'+commit+'`')
    prov=source('/sources/w3c-2013-prov.md')
    prov_url=prov['metadata']['sources'][0]['resource']
    body=('# Independent review and extension\n\n'
          'The first finding was retrieved from Git at '+context['project']['sync']['latest_commit']+'. '
          'Its architecture claim is appropriately limited. The subsequent task also consumed its exact result artifact version.\n\n'
          'Extension: preserve explicit provenance between evidence, agent activity, and responsible participant. '
          'The [W3C PROV source]('+prov_url+') provides a vocabulary for this relationship, not a guarantee of correctness. '
          'ResearchRelay should retain input versions and keep methodological judgment human.\n\n'
          'The finding reviewed is '+finding_ref+'. '
          'This scripted review is a connection test, not independent human scientific validation.')
    findings=['The preceding finding limits its claim to architecture.',
              'Add explicit derivation and participant provenance to every handoff.']
    citations=[url,prov_url]
print(json.dumps({'body':body,'findings':findings,'citations':citations,
    'assumptions':['The verified source notes are the supplied evidence.'],
    'limitations':['Scripted report generation; no live Claude, GPT, or other model inference.',
                   'The literature search is focused and non-exhaustive.'],
    'validation_results':['Referenced source notes and input versions were present in the retrieved context.'],
    'unresolved_questions':['How much coordination effort does a real team save?'],
    'next_actions':['Ask participants to assess evidence quality and coordination effort.']}))
"""


def _git(path,*args):
    result = subprocess.run(["git","-C",str(path),*args],capture_output=True,text=True,encoding="utf-8",timeout=90)
    if result.returncode:
        raise RuntimeError(f"Pilot Git {args[0]} failed; check local Git setup/repository access.")
    return result.stdout.strip()


class _Session:
    def __init__(self,client,participant,token):
        self.client = client
        self.headers = {"Authorization":f"Bearer {token}"}
    def get(self,path,**kwargs):
        return self.client.get(path,headers=self.headers,**kwargs)
    def post(self,path,**kwargs):
        return self.client.post(path,headers=self.headers,**kwargs)
    def put(self,path,**kwargs):
        return self.client.put(path,headers=self.headers,**kwargs)


def run_shared_pilot(remote=None,branch="SRTD_DT_test",workspace=None,live=False):
    if live and (not remote or branch!="SRTD_DT_test"):
        raise ValueError("Live pilot publication requires an explicit GitHub remote and the authorized SRTD_DT_test branch")
    if remote and not live and not Path(remote).expanduser().is_dir():
        raise ValueError("Use --live for a GitHub remote; default pilot mode accepts only a local bare repository")
    run_id = uuid.uuid4().hex[:8]
    root = Path(workspace or Path(".runtime")/f"literature-pilot-{run_id}").expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a new empty pilot workspace; existing work is preserved")
    root.mkdir(parents=True,exist_ok=True)
    bundle = Path(__file__).resolve().parent.parent/PREFIX
    validation = validate_bundle(bundle,PROJECT)
    if remote is None:
        bare = root/"shared.git"
        subprocess.run(["git","init","--bare",str(bare)],check=True,capture_output=True)
        seed = root/"seed"
        subprocess.run(["git","init","-b",branch,str(seed)],check=True,capture_output=True)
        shutil.copytree(bundle,seed/PREFIX)
        _git(seed,"add","--",PREFIX)
        _git(seed,"-c","user.name=ResearchRelay pilot","-c","user.email=pilot@localhost.invalid","commit","-m","Seed verified literature project")
        _git(seed,"remote","add","origin",str(bare))
        _git(seed,"push","origin",branch)
        remote = str(bare)
    else:
        remote = str(remote)
    credentials = {name:secrets.token_urlsafe(32) for name in ("human","alice","bob")}
    settings = Settings(db_path=root/"state.db",repo_path=root/"coordinator"/"records",project_id=PROJECT,
        mode="live" if live else "demo",github_url=remote,github_branch=branch,knowledge_path=PREFIX,
        tokens={token:name for name,token in credentials.items()})
    engine = Engine(settings.db_path,PROJECT)
    producer = root/"participant-agent.py"
    producer.write_text(PRODUCER,encoding="utf-8")
    alice_path = f"{PREFIX}/pilot/alice-finding-{run_id}.md"
    bob_path = f"{PREFIX}/pilot/bob-review-{run_id}.md"
    first_task,second_task = f"lit-finding-{run_id}",f"lit-review-{run_id}"
    app = create_app(settings,engine)
    with TestClient(app,base_url="http://testserver/api/") as client:
        sessions = {name:_Session(client,name,credentials[name]) for name in credentials}
        human,alice,bob = (sessions[name] for name in ("human","alice","bob"))
        initial_response = alice.get("project/context")
        initial_response.raise_for_status()
        initial = initial_response.json()
        assert any(document["path"].endswith("/sources/wu-2024-autogen.md") for document in initial["documents"])
        for proposal in (
            dict(id=first_task,title="Extract a bounded AutoGen architecture finding",owner="alice",
                 objective="Use the verified AutoGen source note to identify a coordination design implication without claiming scientific validity.",
                 acceptance_criteria=["Cite the supplied primary source.","State a limitation and a ResearchRelay implication."],
                 expected_outputs=["An attributed literature finding"]),
            dict(id=second_task,title="Review and extend the preceding finding",owner="bob",dependencies=[first_task],
                 objective="Read the first user's published finding and accepted result, critique its scope, and extend its provenance implication.",
                 acceptance_criteria=["Retrieve the preceding Git update.","Consume the accepted result version.","Add a sourced provenance implication."],
                 expected_outputs=["An attributed review and extension"])):
            response = human.post("tasks",json=proposal)
            response.raise_for_status()
        for name in ("alice","bob"):
            response = sessions[name].put("participants/me/agent",json={"provider":"command",
                "command":[sys.executable,str(producer),alice_path]})
            response.raise_for_status()
        def execute(name):
            worker = Worker("http://testserver",name,root/f"{name}-clone",token=credentials[name])
            worker.client.close()
            worker.client = sessions[name]
            outcome = worker.run_once()
            assert outcome["status"]=="submitted",outcome
            return outcome
        alice_outcome = execute("alice")
        alice_result = engine.get_artifact(f"result-{first_task}")
        def prepared(record,identifier,kind):
            metadata = {**record["metadata"],"id":identifier,"artifact_type":kind,"type":"Research Finding" if kind=="source_note" else "Research Review"}
            metadata["relations"] = [{"type":"derived_from","target":f"artifact:{record['id']}@{record['version']}"}]
            metadata["provenance"]["pilot_run"] = run_id
            metadata["provenance"]["live_model_inference"] = False
            return render_knowledge(metadata,record["body"])
        alice_content = prepared(alice_result,f"pilot-alice-{run_id}","source_note")
        def publish(session,ctx,path,content,key,agent):
            old = next((document for document in ctx["documents"] if document["path"]==path),None)
            return session.post("project/publish",json={"expected_repository":ctx["repository"],"base_commit":ctx["sync"]["latest_commit"],
                "changes":[{"path":path,"content":content,"expected_sha256":old["sha256"] if old else None}],
                "agent":agent,"request_id":key,"message":"Literature pilot: attributed participant handoff"})
        first_publication = publish(alice,initial,alice_path,alice_content,f"alice-{run_id}",alice_result["metadata"]["producing_agent"])
        first_publication.raise_for_status()
        retrieved = bob.get("project/context")
        retrieved.raise_for_status()
        bob_context = retrieved.json()
        assert any(document["path"]==alice_path for document in bob_context["documents"])
        response = bob.post(f"tasks/{first_task}/reviews",json={"reviewer":"bob","verdict":"approve","result_version":1,
            "rationale":"The finding cites the verified note and limits its claim to coordination architecture.",
            "criteria":["Source citation retained","Scientific-validity limitation is explicit"]})
        response.raise_for_status()
        bob_outcome = execute("bob")
        bob_result = engine.get_artifact(f"result-{second_task}")
        response = alice.post(f"tasks/{second_task}/reviews",json={"reviewer":"alice","verdict":"approve","result_version":1,
            "rationale":"The extension links to the preceding finding and W3C provenance evidence.",
            "criteria":["Prior Git update consumed","Provenance implication and limitations recorded"]})
        response.raise_for_status()
        bob_content = prepared(bob_result,f"pilot-bob-{run_id}","review")
        before_second = bob.get("project/context").json()
        second_publication = publish(bob,before_second,bob_path,bob_content,f"bob-{run_id}",bob_result["metadata"]["producing_agent"])
        second_publication.raise_for_status()
        stale = publish(alice,initial,alice_path,alice_content,f"stale-{run_id}",alice_result["metadata"]["producing_agent"])
        assert stale.status_code==409,stale.text
        final = alice.get("project/context")
        final.raise_for_status()
        final_context = final.json()
        assert any(document["path"]==bob_path for document in final_context["documents"])
        assert all(task["status"]=="completed" for task in engine.list_tasks())
        # A result is copied into both pilot notes and generated workflow records.
        # Validate links after publication so relative references cannot silently
        # break when the same accepted evidence is projected at another path.
        published_bundle = root/"published-bundle"
        for document in final_context["documents"]:
            target = published_bundle/document["path"].removeprefix(PREFIX+"/")
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(document["content"],encoding="utf-8")
        published_validation = validate_bundle(published_bundle,PROJECT)
        if published_validation["broken_links"]:
            raise ValueError("Published pilot has unresolved knowledge links; inspect published-bundle before continuing")
    summary = dict(status="completed",run_id=run_id,workspace=str(root),branch=branch,
        github_transport_live=bool(live),model_inference_live=False,
        agent_connections=["alice: participant-local command","bob: participant-local command"],
        initial_commit=initial["sync"]["latest_commit"],first_commit=first_publication.json()["commit"],
        second_commit=second_publication.json()["commit"],paths=[alice_path,bob_path],
        task_ids=[first_task,second_task],stale_edit_status=stale.status_code,
        verified_source_count=sum(1 for document in validation["documents"] if document["path"].startswith("sources/") and not document["metadata"].get("reserved")),
        source_bundle_validation={key:validation[key] for key in ("count","broken_links","format_status","selected_spec")},
        published_bundle_validation={key:published_validation[key] for key in ("count","broken_links","format_status")},
        note="Two application participant identities share the configured Git principal. Distinct GitHub accounts and paid model APIs were not exercised.")
    (root/"summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    return summary
