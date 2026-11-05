import json
from pathlib import Path
import threading
import pytest

from fastapi.testclient import TestClient

from researchrelay.api import create_app
from researchrelay.artifacts import render_markdown
from researchrelay.config import Settings
from researchrelay.engine import Engine
from researchrelay.worker import Worker


def test_provider_independent_worker_retrieves_inputs_and_submits(tmp_path, monkeypatch):
    engine = Engine(tmp_path / "state.db")
    source = engine.put_artifact({"id": "reference", "project_id": engine.project_id,
        "artifact_type": "decision", "question": "Use the source note?", "options": ["yes"],
        "evidence": ["Protocol fixture"], "consequence": "Defines review evidence"}, "Reference agreed")
    engine.create_task(id="analysis", title="Review source provenance", owner="alice", objective="Summarize source evidence",
        input_refs=[{"id": "reference", "version": 1}], acceptance_criteria=["Report reproducible evidence"])
    settings = Settings(db_path=tmp_path / "state.db", repo_path=tmp_path / "record")
    adapter = Worker("http://testserver", "alice", tmp_path / "worker-record", mode="manual")
    def write_result(workspace, lost):
        context = json.loads((workspace / ".researchrelay-exchange/task-context.json").read_text(encoding="utf-8"))
        assert context["input_artifacts"][0]["id"] == "reference"
        assert "claim_token" not in context["task"]
        (workspace / "source-summary.txt").write_text("Source evidence checked\n", encoding="utf-8")
        metadata = {"id": "result-analysis", "project_id": engine.project_id, "artifact_type": "result",
                    "version": 1, "task_id": "analysis", "data": ["Supplied source note"],
                    "code": ["source-summary.txt"], "configuration": {"method": "source review"},
                    "environment": {"python": "3.12"}, "evidence": {"source_reviewed": True},
                    "related_files": ["source-summary.txt"]}
        (workspace / ".researchrelay-exchange/result.md").write_text(render_markdown(metadata, "# Source review\n\nSource evidence checked"), encoding="utf-8")
    monkeypatch.setattr(adapter, "_wait_for_manual", write_result)
    with TestClient(create_app(settings, engine), base_url="http://testserver/api/") as client:
        adapter.client = client
        outcome = adapter.run_once()
    assert outcome["status"] == "submitted"
    assert engine.get_task("analysis")["status"] == "awaiting_review"
    assert engine.get_task("analysis")["repository"][0]["commit"] == outcome["commit"]
    assert engine.get_artifact("result-analysis")["metadata"]["input_refs"] == [{"id": "reference", "version": 1}]
    from researchrelay.repository import _git
    files = _git(Path(outcome["workspace"]), "ls-tree", "-r", "--name-only", "HEAD").splitlines()
    assert "source-summary.txt" in files
    assert "task-records/analysis/v1.md" in files and "task-records/analysis/attempt-1-context.json" in files
    assert "result.md" not in files and "task-context.json" not in files
    assert not any(name.startswith(".researchrelay-exchange/") for name in files)
    assert "submission.json" not in files and "submission-id.txt" not in files
    assert _git(Path(outcome["workspace"]), "check-ignore", "submission.json") == "submission.json"
    assert _git(Path(outcome["workspace"]), "check-ignore", ".researchrelay-exchange/submission.json") == ".researchrelay-exchange/submission.json"


def test_claude_child_environment_excludes_coordinator_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("RESEARCHRELAY_TOKEN", "private-worker-token")
    monkeypatch.setenv("RESEARCHRELAY_TOKENS", '{"private-admin-token":"human"}')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "participant-provider-key")
    captured = {}
    class Process:
        returncode = 0
        def __init__(self, command, **kwargs):
            captured.update(command=command, **kwargs)
        def communicate(self, timeout=None):
            return '{"is_error":false}', ""
        def poll(self):
            return 0
    monkeypatch.setattr("researchrelay.worker.subprocess.Popen", Process)
    (tmp_path / ".researchrelay-exchange").mkdir()
    (tmp_path / ".researchrelay-exchange/result.md").write_text("Agent output", encoding="utf-8")
    Worker("http://localhost", "alice", tmp_path / "record")._claude(tmp_path, threading.Event())
    assert not any(key.startswith("RESEARCHRELAY_") for key in captured["env"])
    assert captured["env"]["ANTHROPIC_API_KEY"] == "participant-provider-key"
    assert "--dangerously-skip-permissions" not in captured["command"]


def test_cli_demo_refuses_live_mode(monkeypatch, capsys):
    import pytest
    from researchrelay.cli import main
    monkeypatch.setenv("RESEARCHRELAY_MODE", "live")
    with pytest.raises(SystemExit) as error:
        main(["demo"])
    assert error.value.code == 2
    assert "requires RESEARCHRELAY_MODE=demo" in capsys.readouterr().err


def test_independent_worker_branches_merge_without_exchange_conflicts(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from researchrelay.repository import Repository, _git
    engine = Engine(tmp_path / "state.db")
    for task_id, owner in (("analysis-a", "alice"), ("analysis-b", "bob")):
        engine.create_task(id=task_id, title=task_id, owner=owner, objective="Compute independent evidence",
                           acceptance_criteria=["Output a reproducible score"])
    repo = Repository(tmp_path / "worker-record")
    repo.initialize()
    (repo.path / "result.md").write_text("Existing scientific result\n", encoding="utf-8")
    (repo.path / "task-context.json").write_text('{"existing":"project context"}\n', encoding="utf-8")
    _git(repo.path, "add", "result.md", "task-context.json")
    repo._commit(repo.path, "Preserve existing project exchange filenames")
    adapters = [Worker("http://testserver", owner, repo.path, mode="manual") for owner in ("alice", "bob")]
    def produce(workspace, lost):
        exchange = workspace / ".researchrelay-exchange"
        task = json.loads((exchange / "task-context.json").read_text(encoding="utf-8"))["task"]
        output = f"outputs/{task['id']}.txt"
        (workspace / "outputs").mkdir(exist_ok=True)
        (workspace / output).write_text("Score = 1.0\n", encoding="utf-8")
        meta = {"id": f"result-{task['id']}", "project_id": engine.project_id, "artifact_type": "result",
                "task_id": task["id"], "data": ["Synthetic"], "code": [output],
                "configuration": {"metric": "score"}, "environment": {"python": "3.12"},
                "evidence": {"score": 1}, "related_files": [output]}
        (exchange / "result.md").write_text(render_markdown(meta, "# Independent evidence"), encoding="utf-8")
    for adapter in adapters:
        monkeypatch.setattr(adapter, "_wait_for_manual", produce)
    settings = Settings(db_path=engine.db_path, repo_path=tmp_path / "coordinator-record")
    with TestClient(create_app(settings, engine), base_url="http://testserver/api/") as client:
        for adapter in adapters:
            adapter.client = client
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda adapter: adapter.run_once(), adapters))
    for outcome in outcomes:
        engine.review_task(outcome["task_id"], "carol", "approve", "Independent score and provenance inspected", ["Reproducible output"], 1)
        repo.reconcile_local(outcome["branch"], outcome["task_id"])
    assert (repo.path / "result.md").read_text(encoding="utf-8") == "Existing scientific result\n"
    assert (repo.path / "task-context.json").read_text(encoding="utf-8") == '{"existing":"project context"}\n'
    for task_id in ("analysis-a", "analysis-b"):
        assert (repo.path / f"task-records/{task_id}/v1.md").exists()
        assert (repo.path / f"task-records/{task_id}/attempt-1-context.json").exists()
        assert (repo.path / f"outputs/{task_id}.txt").exists()
    assert not (repo.path / ".researchrelay-exchange").exists()


def test_gpt_worker_complete_context_result_review_and_shared_publication(tmp_path,monkeypatch):
    """Real application/Git exchange with mocked model inference, not a live GPT call."""
    import httpx
    from researchrelay.providers import APIReportProvider
    from researchrelay.knowledge import render_knowledge, parse_knowledge
    from researchrelay.repository import Repository, _git
    project_id='agentic-collaboration'
    seed=Repository(tmp_path/'seed');seed.initialize()
    directory=seed.path/'projects/agentic-collaboration';directory.mkdir(parents=True)
    source=render_knowledge({'id':'test-source','project_id':project_id,'artifact_type':'source_note',
        'responsible_participant':'alice','producing_agent':'fixture/1',
        'citations':['https://example.org/source'],'provenance':{'verification':'Synthetic test evidence only'}},
        '# Source\n\nA synthetic fixture for protocol verification, not a verified paper.')
    (directory/'source.md').write_bytes(source.encode())
    _git(seed.path,'add','projects');seed._commit(seed.path,'Add synthetic shared source')
    remote=tmp_path/'remote.git';remote.mkdir();_git(remote,'init','--bare')
    _git(seed.path,'remote','add','origin',str(remote))
    _git(seed.path,'push','origin','HEAD:refs/heads/SRTD_DT_test')
    engine=Engine(tmp_path/'state.db',project_id)
    engine.create_task(id='analysis',title='Review source collaboration mechanism',owner='alice',
        objective='Synthesize only the supplied source evidence.',acceptance_criteria=['Cite supplied evidence and limitations'])
    settings=Settings(db_path=engine.db_path,repo_path=tmp_path/'record',project_id=project_id,
                      tokens={'human-secret':'human','alice-secret':'alice','bob-secret':'bob'})
    monkeypatch.setenv('OPENAI_API_KEY','local-provider-secret')
    report={'body':'# Finding\n\nThis synthetic example shows an evidence-linked handoff.',
            'findings':['An explicit handoff links a task to a source.'],'citations':['https://example.org/source'],
            'assumptions':[],'limitations':['Protocol fixture; no scientific generalization.'],
            'validation_results':['Supplied source retained.'],'unresolved_questions':[], 'next_actions':['Independent review.']}
    observed=[]
    def model(request):
        payload=json.loads(request.content);observed.append(payload)
        assert 'test-source' in request.content.decode()
        assert 'local-provider-secret' not in request.content.decode()
        return httpx.Response(200,json={'status':'completed','output':[{'type':'message','content':[
            {'type':'output_text','text':json.dumps(report)}]}]})
    def generate(profile,context,timeout,lost,workspace):
        return APIReportProvider(profile,timeout,httpx.MockTransport(model)).generate(context,lost)
    monkeypatch.setattr('researchrelay.worker.generate_report',generate)
    human={'Authorization':'Bearer human-secret'};bob={'Authorization':'Bearer bob-secret'}
    with TestClient(create_app(settings,engine),base_url='http://testserver/api/',headers={'Authorization':'Bearer alice-secret'}) as client:
        configured=client.put('project/repository',headers=human,json={'url':str(remote),'branch':'SRTD_DT_test',
                              'knowledge_path':'projects/agentic-collaboration'})
        assert configured.status_code==200,configured.text
        configured=client.put('participants/me/agent',json={'provider':'openai-responses','model':'configured-model'})
        assert configured.status_code==200,configured.text
        worker=Worker('http://testserver','alice',tmp_path/'alice clone',token='alice-secret')
        worker.client.close();worker.client=client
        outcome=worker.run_once()
        assert outcome['status']=='submitted'
        task=engine.get_task('analysis');assert task['status']=='awaiting_review'
        record=engine.get_artifact('result-analysis')
        assert record['metadata']['project_context']['commit']
        assert record['metadata']['project_context']['documents'][0]['path']=='projects/agentic-collaboration/source.md'
        content=(Path(outcome['workspace'])/'task-records/analysis/v1.md').read_text(encoding='utf-8')
        metadata,_=parse_knowledge(content,project_id=project_id)
        assert metadata['generated']['by']=='openai-responses/configured-model'
        reviewed=client.post('tasks/analysis/reviews',headers=bob,json={'reviewer':'bob','verdict':'approve',
             'rationale':'The result cites only the synthetic supplied source and makes its limitation explicit.',
             'criteria':['Evidence and limitation are present.'],'result_version':1})
        assert reviewed.status_code==200,reviewed.text
        context=client.get('project/context').json()
        target='projects/agentic-collaboration/results/analysis-v1.md'
        published=client.post('project/publish',json={'base_commit':context['sync']['latest_commit'],'expected_repository':context['repository'],
             'changes':[{'path':target,'content':content,'expected_sha256':None}],
             'agent':metadata['producing_agent'],'request_id':'alice-result-1','message':'Record independently reviewed finding'})
        assert published.status_code==200,published.text
        bob_context=client.get('project/context',headers=bob).json()
        assert any(document['path']==target for document in bob_context['documents'])
        review=render_knowledge({'id':'review-analysis','project_id':project_id,'artifact_type':'review',
             'responsible_participant':'bob','producing_agent':'review-fixture/1','relations':[{'type':'reviews','target':'result-analysis'}],
             'provenance':{'input_commit':bob_context['sync']['latest_commit']},'task_id':'analysis','result_ref':{'id':'result-analysis','version':1},
             'verdict':'approve','rationale':'Source linkage and limitations verified.'},'# Independent review\n\nNo productivity or generalization claim follows from the synthetic fixture.')
        subsequent=client.post('project/publish',headers=bob,json={'base_commit':bob_context['sync']['latest_commit'],'expected_repository':bob_context['repository'],
             'changes':[{'path':'projects/agentic-collaboration/reviews/analysis.md','content':review,'expected_sha256':None}],
             'agent':'review-fixture/1','request_id':'bob-review-1','message':'Record independent extension/review'})
        assert subsequent.status_code==200,subsequent.text
        latest=client.get('project/context').json()
        assert latest['sync']['latest_commit']!=context['sync']['latest_commit']
        paths={document['path'] for document in latest['documents']}
        assert {target,'projects/agentic-collaboration/source.md','projects/agentic-collaboration/reviews/analysis.md'}<=paths
        # An exact saved successful submission remains replayable after inputs change.
        source_document=next(document for document in latest['documents'] if document['path']=='projects/agentic-collaboration/source.md')
        updated_source=render_knowledge({**source_document['metadata'],'version':2},'# Updated source\n\nNew synthetic calibration evidence.')
        correction=client.post('project/publish',json={'base_commit':latest['sync']['latest_commit'],'expected_repository':latest['repository'],
             'changes':[{'path':source_document['path'],'content':updated_source,'expected_sha256':source_document['sha256']}],
             'agent':source_document['metadata']['producing_agent'],'request_id':'alice-source-correction','message':'Correct source evidence'})
        assert correction.status_code==200,correction.text
        payload=json.loads((Path(outcome['exchange'])/'submission.json').read_text(encoding='utf-8'))
        replay=client.post('tasks/analysis/submit',json=payload)
        assert replay.status_code==200,replay.text
        assert replay.json()['result']['version']==1
    assert len(observed)==1
    assert engine.get_task('analysis')['status']=='completed'


def test_provider_authentication_failure_becomes_a_safe_task_blocker(tmp_path,monkeypatch):
    from researchrelay.providers import ProviderError
    engine=Engine(tmp_path/'state.db')
    engine.create_task(id='analysis',title='Review evidence',owner='alice',objective='Compare evidence',
                       acceptance_criteria=['Provide source evidence'])
    settings=Settings(db_path=engine.db_path,repo_path=tmp_path/'record',tokens={'alice-secret':'alice'})
    with TestClient(create_app(settings,engine),base_url='http://testserver/api/',headers={'Authorization':'Bearer alice-secret'}) as client:
        assert client.put('participants/me/agent',json={'provider':'openai-responses','model':'configured-model'}).status_code==200
        adapter=Worker('http://testserver','alice',tmp_path/'worker clone',token='alice-secret')
        adapter.client.close();adapter.client=client
        def missing(*args,**kwargs):
            raise ProviderError('Provider credential is missing from this participant worker environment','authentication')
        monkeypatch.setattr('researchrelay.worker.generate_report',missing)
        import pytest
        with pytest.raises(ProviderError,match='credential is missing'):
            adapter.run_once()
    task=engine.get_task('analysis')
    assert task['status']=='blocked' and 'credential is missing' in task['blocker']
    assert not task['result_ref']


def test_worker_rejects_unjoined_source_footnote_before_commit_or_submission(tmp_path,monkeypatch):
    engine=Engine(tmp_path/'state.db')
    engine.create_task(id='analysis',title='Review sources',owner='alice',objective='Explain the source',
                       acceptance_criteria=['Cite actual evidence'])
    adapter=Worker('http://testserver','alice',tmp_path/'worker clone',mode='manual')
    def invalid(workspace,lost):
        metadata={'id':'result-analysis','project_id':engine.project_id,'artifact_type':'result','task_id':'analysis',
                  'data':['Supplied task'],'code':['manual agent'],'configuration':{'mode':'manual'},
                  'environment':{'provider':'external'},'evidence':['An unjoined citation is not valid provenance.']}
        (workspace/'.researchrelay-exchange/result.md').write_text(render_markdown(metadata,'# Result\n\nUnsupported footnote[^missing-source].'),encoding='utf-8')
    monkeypatch.setattr(adapter,'_wait_for_manual',invalid)
    settings=Settings(db_path=engine.db_path,repo_path=tmp_path/'record')
    import pytest
    with TestClient(create_app(settings,engine),base_url='http://testserver/api/') as client:
        adapter.client.close();adapter.client=client
        with pytest.raises(ValueError,match='Footnote labels'):
            adapter.run_once()
    task=engine.get_task('analysis')
    assert task['status']=='blocked' and task['result_ref'] is None


def test_shared_sources_use_exact_git_commit_and_unique_reference_ids():
    commit='a'*40
    context={'project':{'repository':{'url':'git@github.com:team/research.git'},'sync':{'latest_commit':commit},
              'documents':[{'path':'projects/lab/index.md','metadata':{'id':'index'}},
                           {'path':'projects/lab/notes/index.md','metadata':{'id':'index'}},
                           {'path':'projects/lab/source note.md','metadata':{'id':'source-note'}}]},
             'input_artifacts':[{'id':'index','version':1}]}
    sources=Worker._sources(context)
    assert len({source['id'] for source in sources})==len(sources)
    assert sources[2]['resource']==f'https://github.com/team/research/blob/{commit}/projects/lab/source%20note.md'



@pytest.mark.parametrize('location',['result','related_file','unexpected_index'])
def test_worker_blocks_credentials_before_any_output_commit(tmp_path,monkeypatch,location):
    from researchrelay.providers import ProviderError
    from researchrelay.repository import _git
    secret='opaque-local-provider-value'
    monkeypatch.setenv('OPENAI_API_KEY',secret)
    engine=Engine(tmp_path/'state.db')
    engine.create_task(id='analysis',title='Review evidence',owner='alice',objective='Explain supplied evidence',
                       acceptance_criteria=['No credentials in outputs'])
    adapter=Worker('http://testserver','alice',tmp_path/'worker clone',mode='manual')
    captured={}
    def produce(workspace,lost):
        captured['workspace']=workspace
        captured['before']=_git(workspace,'rev-parse','HEAD')
        body='# Result\n\nA provisional finding.'
        metadata={'id':'result-analysis','project_id':engine.project_id,'artifact_type':'result','task_id':'analysis',
                  'data':['Supplied evidence'],'code':['manual adapter'],'configuration':{'mode':'manual'},
                  'environment':{'provider':'external'},'evidence':['A provisional finding.']}
        if location=='result':
            body+='\n'+('sk-'+'x'*32)
        elif location=='related_file':
            # Deliberately straddle a scan chunk boundary with a non-pattern key.
            (workspace/'analysis.txt').write_text('x'*65530+secret,encoding='utf-8')
            metadata['related_files']=['analysis.txt']
        else:
            (workspace/'unlisted.txt').write_text(secret,encoding='utf-8')
            _git(workspace,'add','unlisted.txt')
        (workspace/'.researchrelay-exchange/result.md').write_text(render_markdown(metadata,body),encoding='utf-8')
    monkeypatch.setattr(adapter,'_wait_for_manual',produce)
    settings=Settings(db_path=engine.db_path,repo_path=tmp_path/'record')
    with TestClient(create_app(settings,engine),base_url='http://testserver/api/') as client:
        adapter.client.close();adapter.client=client
        with pytest.raises(ProviderError) as error:
            adapter.run_once()
        assert secret not in str(error.value)
    assert _git(captured['workspace'],'rev-parse','HEAD')==captured['before']
    task=engine.get_task('analysis')
    assert task['status']=='blocked' and task['result_ref'] is None
    assert secret not in task['blocker']
