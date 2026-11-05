"""Actual coordinator/Git editor-file workflow; no extension/model inference is mocked as live."""
import json
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from researchrelay.api import create_app
from researchrelay.config import Settings
from researchrelay.engine import Engine
from researchrelay.providers import ProviderError, REPORT_SCHEMA, validate_profile
from researchrelay.repository import Repository, _git
from researchrelay.vscode import prepare_handoff, read_report, wait_for_report, main
from researchrelay.worker import Worker


def report():
    return {'body':'# Coordination finding\n\nThe supplied source describes programmable multi-agent conversations. '
                   'This suggests explicit persisted handoffs for ResearchRelay, which is a design inference. '
                   '[AutoGen](https://openreview.net/pdf?id=BAakY1hNKS)',
            'findings':['AutoGen describes configurable agents and programmable conversation patterns.'],
            'citations':['https://openreview.net/pdf?id=BAakY1hNKS'],'assumptions':[],
            'limitations':['A source-note review does not establish scientific productivity gains.'],
            'validation_results':['Compared the claim to the supplied source note; no experiment was run.'],
            'unresolved_questions':['How should persisted handoffs be evaluated?'],
            'next_actions':['Request independent review and human methodological judgment.']}


def write_report(workspace):
    exchange=Path(workspace)/'.researchrelay-exchange'
    (exchange/'report.json').write_text(json.dumps(report()),encoding='utf-8')
    main(['ready','--workspace',str(workspace)])


def make_worker(tmp_path, configured=False):
    engine=Engine(tmp_path/'state.db',project_id='agentic-collaboration')
    engine.create_task(id='source-review',title='Review AutoGen source',owner='alice',
                       objective='Summarize the supplied AutoGen coordination mechanism and one limitation.',
                       acceptance_criteria=['Cite the supplied source and distinguish inference.'])
    settings=Settings(db_path=engine.db_path,repo_path=tmp_path/'record',project_id=engine.project_id,
                      tokens={'human-project-token':'human','alice-project-token':'alice','bob-project-token':'bob'})
    app=create_app(settings,engine)
    worker=Worker('http://testserver','alice',tmp_path/'alice-clone',provider='vscode',timeout=15)
    remote=None
    if configured:
        seed=Repository(tmp_path/'seed');seed.initialize()
        source=Path(__file__).resolve().parents[1]/'projects/agentic-collaboration/sources/wu-2024-autogen.md'
        target=seed.path/'projects/agentic-collaboration/source.md';target.parent.mkdir(parents=True)
        target.write_bytes(source.read_bytes())
        _git(seed.path,'add','projects');seed._commit(seed.path,'Add supplied verified source note')
        remote=tmp_path/'remote.git';remote.mkdir();_git(remote,'init','--bare')
        _git(seed.path,'remote','add','origin',str(remote));_git(seed.path,'push','origin','HEAD:refs/heads/SRTD_DT_test')
        with TestClient(app,headers={'Authorization':'Bearer human-project-token'}) as human:
            response=human.put('/api/project/repository',json={'url':str(remote),'branch':'SRTD_DT_test',
                                                  'knowledge_path':'projects/agentic-collaboration'})
            assert response.status_code==200,response.text
    return engine,app,worker,remote


def wait_workspace(worker):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        candidates=list(worker.repository.workspaces.glob('*/*/.researchrelay-exchange/ResearchRelay.code-workspace'))
        if candidates:
            return candidates[0].parent.parent
        time.sleep(.05)
    raise AssertionError('Editor handoff did not appear')


def test_vscode_profile_and_portable_handoff(tmp_path):
    assert validate_profile({'provider':'vscode'})['api_key_env'] is None
    bundle=prepare_handoff(tmp_path,{'input_artifacts':[{'id':'source','version':1}]})
    definition=json.loads(Path(bundle['workspace_file']).read_text())
    assert definition['folders'][0]['path']=='..'
    assert definition['tasks']['tasks'][0]['type']=='process'
    assert not (tmp_path/'.researchrelay-exchange/report.json').exists()
    assert json.loads((tmp_path/'.researchrelay-exchange/report-schema.json').read_text())==REPORT_SCHEMA
    assert (tmp_path/'.researchrelay-exchange/inputs/001.json').exists()
    write_report(tmp_path)
    assert read_report(tmp_path)==report()


def test_editor_handoff_shared_source_result_review_and_publication(tmp_path,monkeypatch):
    engine,app,worker,remote=make_worker(tmp_path,configured=True)
    monkeypatch.setenv('RESEARCHRELAY_TOKEN','alice-project-token')
    with TestClient(app,base_url='http://testserver/api/',headers={'Authorization':'Bearer alice-project-token'}) as client:
        worker.client=client
        with ThreadPoolExecutor(max_workers=1) as pool:
            execution=pool.submit(worker.run_once)
            workspace=wait_workspace(worker)
            context=json.loads((workspace/'.researchrelay-exchange/task-context.json').read_text())
            assert context['project']['sync']['latest_commit']
            assert any('AutoGen' in document['body'] for document in context['project']['documents'])
            assert 'claim_token' not in context['task']
            write_report(workspace)
            outcome=execution.result(timeout=30)
        assert outcome['status']=='submitted'
        artifact=engine.get_artifact('result-source-review')
        assert artifact['metadata']['provenance']['execution_kind']=='editor_handoff'
        assert artifact['metadata']['project_context']['repository']==context['project']['repository']
        assert artifact['metadata']['producing_agent']=='vscode/editor-selected'
        assert artifact['metadata']['configuration']['model_selection_verified'] is False
        assert engine.get_task('source-review')['status']=='awaiting_review'
        assert not (workspace/'.researchrelay-exchange/submission.json').exists()
        assert Path(outcome['submission_path']).is_relative_to(worker.repository.path/'.git')
        private=json.loads(next((worker.repository.path/'.git/researchrelay-worker').glob('*.handoff.json')).read_text())
        for path in (workspace/'.researchrelay-exchange').rglob('*'):
            if path.is_file():
                text=path.read_text(encoding='utf-8')
                assert 'alice-project-token' not in text and private['claim_token'] not in text
        with TestClient(app,base_url='http://testserver/api/',headers={'Authorization':'Bearer bob-project-token'}) as bob:
            review=bob.post('tasks/source-review/reviews',json={'reviewer':'bob','verdict':'approve',
                'rationale':'The coordination finding and explicit design inference match the supplied source note; productivity remains unproven.',
                'criteria':['Cite the supplied source and distinguish inference.'],'result_version':1})
            assert review.status_code==200,review.text
        fresh=client.get('project/context').json()
        from researchrelay.knowledge import render_knowledge
        result=render_knowledge(artifact['metadata'],artifact['body'])
        publication=client.post('project/publish',json={'base_commit':fresh['sync']['latest_commit'],'expected_repository':fresh['repository'],
            'request_id':'editor-finding-publication','agent':'vscode/editor-selected',
            'message':'Record editor handoff source finding','changes':[{'path':'projects/agentic-collaboration/editor-finding.md',
              'content':result,'expected_sha256':None}]})
        assert publication.status_code==200,publication.text
        assert 'editor-finding.md' in _git(remote,'ls-tree','-r','--name-only','refs/heads/SRTD_DT_test')


def test_editor_handoff_resume_uses_same_claim_and_workspace(tmp_path,monkeypatch):
    engine,app,worker,_=make_worker(tmp_path)
    def interrupted(*args,**kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr('researchrelay.vscode.wait_for_report',interrupted)
    with TestClient(app,base_url='http://testserver/api/',headers={'Authorization':'Bearer alice-project-token'}) as client:
        worker.client=client
        with pytest.raises(KeyboardInterrupt):
            worker.run_once()
        state=next((worker.repository.path/'.git/researchrelay-worker').glob('*.handoff.json'))
        workspace=Path(json.loads(state.read_text())['isolation']['workspace'])
        write_report(workspace)
        monkeypatch.setattr('researchrelay.vscode.wait_for_report',wait_for_report)
        recovered=Worker('http://testserver','alice',worker.repository.path,provider='vscode')
        recovered.client=client
        outcome=recovered.run_once(resume_handoff=state)
    assert outcome['status']=='submitted'
    assert outcome['workspace']==str(workspace)
    assert engine.get_task('source-review')['attempts']==1


def test_editor_handoff_rejects_expired_or_replaced_attempt(tmp_path,monkeypatch):
    engine,app,worker,_=make_worker(tmp_path)
    def interrupted(*args,**kwargs): raise KeyboardInterrupt()
    monkeypatch.setattr('researchrelay.vscode.wait_for_report',interrupted)
    with TestClient(app,base_url='http://testserver/api/',headers={'Authorization':'Bearer alice-project-token'}) as client:
        worker.client=client
        with pytest.raises(KeyboardInterrupt): worker.run_once()
        state=next((worker.repository.path/'.git/researchrelay-worker').glob('*.handoff.json'))
        engine.cancel_task('source-review')
        with pytest.raises(ProviderError,match='no longer running'):
            worker.run_once(resume_handoff=state)
    assert not list(worker.repository.workspaces.rglob('submission.json'))


@pytest.mark.parametrize('failure',['invalid','timeout','canceled'])
def test_editor_report_errors_are_clear_and_do_not_submit(tmp_path,failure):
    prepare_handoff(tmp_path,{})
    lost=threading.Event()
    if failure=='invalid':
        (tmp_path/'.researchrelay-exchange/report.json').write_text('{bad json')
        (tmp_path/'.researchrelay-exchange/REPORT_READY').touch()
    elif failure=='canceled': lost.set()
    with pytest.raises(ProviderError): wait_for_report(tmp_path,timeout=.01,lost=lost)


def test_editor_launch_is_explicit_and_excludes_project_tokens(tmp_path,monkeypatch):
    from researchrelay.vscode import open_editor
    monkeypatch.setenv('RESEARCHRELAY_TOKEN','private-token')
    captured={}
    monkeypatch.setattr('researchrelay.vscode.shutil.which',lambda command:'/installed/code')
    monkeypatch.setattr('researchrelay.vscode.subprocess.Popen',lambda command,**kwargs:captured.update(command=command,**kwargs))
    open_editor(tmp_path/'task.code-workspace')
    assert captured['command']==['/installed/code','--new-window',str(tmp_path/'task.code-workspace')]
    assert not any(key.startswith('RESEARCHRELAY_') for key in captured['env'])
    monkeypatch.setattr('researchrelay.vscode.shutil.which',lambda command:None)
    with pytest.raises(ProviderError,match='open the printed'): open_editor(tmp_path/'task.code-workspace')


def test_editor_report_rejects_path_escape(tmp_path):
    exchange=tmp_path/'.researchrelay-exchange';exchange.mkdir()
    target=tmp_path/'external.json';target.write_text(json.dumps(report()))
    try: (exchange/'report.json').symlink_to(target)
    except OSError: pytest.skip('Symlinks unavailable to this Windows account')
    with pytest.raises(ProviderError,match='outside'): read_report(tmp_path)


def test_editor_resume_rejects_changed_input_version(tmp_path,monkeypatch):
    engine,app,worker,_=make_worker(tmp_path)
    source=engine.put_artifact({'id':'input-note','project_id':engine.project_id,'artifact_type':'decision',
        'question':'Use the supplied source?','options':['yes'],'evidence':['Approved source note'],
        'consequence':'Constrains source review'},'Original approved source')
    engine.create_task(id='pinned-review',title='Pinned source review',owner='alice',objective='Review the exact source note',
        acceptance_criteria=['Use the approved version'],input_refs=[{'id':'input-note','version':1}])
    engine.cancel_task('source-review')
    def interrupted(*args,**kwargs): raise KeyboardInterrupt()
    monkeypatch.setattr('researchrelay.vscode.wait_for_report',interrupted)
    with TestClient(app,base_url='http://testserver/api/',headers={'Authorization':'Bearer alice-project-token'}) as client:
        worker.client=client
        with pytest.raises(KeyboardInterrupt): worker.run_once()
        state=next((worker.repository.path/'.git/researchrelay-worker').glob('*.handoff.json'))
        metadata=dict(source['metadata']);metadata['version']=2
        engine.put_artifact(metadata,'Corrected source evidence')
        with pytest.raises(ProviderError,match='Shared inputs changed'):
            worker.run_once(resume_handoff=state)
    assert engine.get_task('pinned-review')['status']=='blocked'


def test_cli_demo_refuses_a_bound_shared_repository(monkeypatch,capsys):
    from researchrelay.cli import main as cli
    monkeypatch.setenv('RESEARCHRELAY_MODE','demo')
    monkeypatch.setenv('RESEARCHRELAY_GITHUB_URL','git@github.com:team/research.git')
    with pytest.raises(SystemExit) as error: cli(['demo'])
    assert error.value.code==2 and 'unbound repository' in capsys.readouterr().err


def test_vscode_tasks_debugger_and_actual_module_entrypoint():
    import subprocess
    import sys
    root=Path(__file__).resolve().parents[1]
    tasks=json.loads((root/'.vscode/tasks.json').read_text())
    for task in tasks['tasks']:
        assert task['type']=='process' and task['command']=='${command:python.interpreterPath}'
        if task['args'][1]=='researchrelay':
            module_help=subprocess.run([sys.executable,*task['args'][:3],'--help'],cwd=root,
                                       capture_output=True,text=True,timeout=30)
            assert module_help.returncode==0,module_help.stderr
    demo=next(task for task in tasks['tasks'] if task['label']=='ResearchRelay: run offline literature demo')
    assert demo['args']==['-m','researchrelay','demo','--offline']
    launch=json.loads((root/'.vscode/launch.json').read_text())['configurations'][0]
    assert launch['type']=='debugpy' and launch['module']=='researchrelay'
    assert launch['envFile']=='${workspaceFolder}/.env'
    module_help=subprocess.run([sys.executable,'-m','researchrelay','--help'],cwd=root,
                               capture_output=True,text=True,timeout=30)
    assert module_help.returncode==0 and 'worker' in module_help.stdout


def test_missing_editor_launcher_keeps_manual_handoff_available(tmp_path,monkeypatch,capsys):
    engine,app,worker,_=make_worker(tmp_path)
    worker.open_editor=True
    def unavailable(*args): raise ProviderError('VS Code command is unavailable; open the printed workspace manually','configuration')
    monkeypatch.setattr('researchrelay.vscode.open_editor',unavailable)
    with TestClient(app,base_url='http://testserver/api/',headers={'Authorization':'Bearer alice-project-token'}) as client:
        worker.client=client
        with ThreadPoolExecutor(max_workers=1) as pool:
            future=pool.submit(worker.run_once)
            workspace=wait_workspace(worker)
            write_report(workspace)
            outcome=future.result(timeout=30)
    assert outcome['status']=='submitted'
    assert engine.get_task('source-review')['status']=='awaiting_review'
    assert 'editor_launch_unavailable' in capsys.readouterr().out


def test_cli_demo_refuses_a_persisted_binding_without_environment_url(tmp_path,monkeypatch,capsys):
    from researchrelay.cli import main as cli
    from researchrelay.sync import ProjectSync
    engine=Engine(tmp_path/'team.db',project_id='agentic-collaboration')
    settings=Settings(db_path=engine.db_path,repo_path=tmp_path/'team-record',github_url=None)
    ProjectSync(settings,engine)._set('shared_repository',{'url':'git@github.com:team/research.git',
                    'branch':'SRTD_DT_test','knowledge_path':'projects/agentic-collaboration'})
    before=engine.list_tasks()
    monkeypatch.setenv('RESEARCHRELAY_MODE','demo')
    monkeypatch.setenv('RESEARCHRELAY_GITHUB_URL','')
    def forbidden(*args,**kwargs): raise AssertionError('Bound team database must never reach the local demo')
    monkeypatch.setattr('researchrelay.pilot.run_pilot',forbidden)
    with pytest.raises(SystemExit) as error:
        cli(['demo','--db',str(engine.db_path),'--repo',str(tmp_path/'unused-record')])
    assert error.value.code==2 and 'fresh unbound database' in capsys.readouterr().err
    assert engine.list_tasks()==before
    assert not (tmp_path/'unused-record').exists()


@pytest.mark.parametrize('repository',[
    {'url':'git@github.com:midatm1234/ResearchRelay.git','branch':'SRTD_DT_test','knowledge_path':'projects/agentic-collaboration'},
    {'url':'git@github.com:other-team/research.git','branch':'group-knowledge','knowledge_path':'knowledge/group-a'},
    None,
])
def test_editor_handoff_identifies_actual_authoritative_knowledge_source(tmp_path,repository):
    project={'repository':repository,'sync':{'status':'synced' if repository else 'disabled',
                                            'latest_commit':'a'*40 if repository else None}}
    handoff=prepare_handoff(tmp_path,{'project':project})
    source=json.loads((tmp_path/'.researchrelay-exchange/knowledge-source.json').read_text())
    assert handoff['knowledge_source']==source
    instructions=Path(handoff['instructions']).read_text()
    if repository:
        assert source['repository']==repository['url']
        assert source['branch']==repository['branch'] and source['knowledge_path']==repository['knowledge_path']
        assert source['retrieved_commit']=='a'*40
        assert all(value in instructions for value in repository.values())
        assert 'does not select the knowledge branch' in instructions
        assert 'falling back to bundled example notes' in instructions
    else:
        assert source['repository'] is None and source['retrieved_commit'] is None
        assert 'explicitly unbound local/offline handoff' in instructions
        assert 'git@github.com:midatm1234' not in instructions


def test_editor_resume_rejects_repository_branch_change_with_identical_documents(tmp_path,monkeypatch):
    engine,app,worker,remote=make_worker(tmp_path,configured=True)
    def interrupted(*args,**kwargs): raise KeyboardInterrupt()
    monkeypatch.setattr('researchrelay.vscode.wait_for_report',interrupted)
    with TestClient(app,base_url='http://testserver/api/',headers={'Authorization':'Bearer alice-project-token'}) as client:
        worker.client=client
        with pytest.raises(KeyboardInterrupt): worker.run_once()
        state=next((worker.repository.path/'.git/researchrelay-worker').glob('*.handoff.json'))
        before=json.loads(state.read_text())['context']['project']
        _git(remote,'update-ref','refs/heads/group-knowledge',before['sync']['latest_commit'])
        with TestClient(app,headers={'Authorization':'Bearer human-project-token'}) as human:
            changed=human.put('/api/project/repository',json={'url':str(remote),'branch':'group-knowledge',
                             'knowledge_path':'projects/agentic-collaboration'})
            assert changed.status_code==200,changed.text
        after=worker.project_context()
        assert Worker._context_pins(after)['documents']==Worker._context_pins(before)['documents']
        assert after['repository']!=before['repository']
        with pytest.raises(ProviderError,match='knowledge repository/branch/path was reconfigured'):
            worker.run_once(resume_handoff=state)
    assert engine.get_task('source-review')['status']=='blocked'


@pytest.mark.parametrize('custom_paths',[False,True])
def test_offline_service_selects_separate_unbound_project_and_clears_live_tokens(tmp_path,monkeypatch,custom_paths):
    from researchrelay.cli import main as cli
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('RESEARCHRELAY_MODE','live')
    monkeypatch.setenv('RESEARCHRELAY_GITHUB_URL','git@github.com:group/live.git')
    monkeypatch.setenv('RESEARCHRELAY_PROJECT','another-group')
    monkeypatch.setenv('RESEARCHRELAY_TOKENS','{"private-team-token":"human"}')
    monkeypatch.setenv('RESEARCHRELAY_DB',str(tmp_path/'live.db'))
    monkeypatch.setenv('RESEARCHRELAY_REPO',str(tmp_path/'live-record'))
    captured={}
    def start(*args,**kwargs):
        settings=Settings()
        captured.update(mode=settings.mode,url=settings.github_url,project=settings.project_id,
                        tokens=settings.tokens,db=settings.db_path,repo=settings.repo_path,kwargs=kwargs)
    monkeypatch.setattr('uvicorn.run',start)
    arguments=['serve','--offline-demo']
    if custom_paths: arguments+=['--db',str(tmp_path/'custom/demo.db'),'--repo',str(tmp_path/'custom/record')]
    cli(arguments)
    assert captured['mode']=='demo' and captured['url'] is None
    assert captured['project']=='agentic-collaboration' and captured['tokens']=={}
    expected_db=tmp_path/'custom/demo.db' if custom_paths else Path('.runtime/offline-demo/state.db')
    expected_repo=tmp_path/'custom/record' if custom_paths else Path('.runtime/offline-demo/project-record')
    assert captured['db']==expected_db and captured['repo']==expected_repo
    assert captured['db'].exists() and not (tmp_path/'live.db').exists()


def test_offline_demo_flag_uses_same_dedicated_state_as_offline_service(tmp_path,monkeypatch,capsys):
    from researchrelay.cli import main as cli
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('RESEARCHRELAY_MODE','live')
    monkeypatch.setenv('RESEARCHRELAY_GITHUB_URL','git@github.com:group/live.git')
    monkeypatch.setenv('RESEARCHRELAY_PROJECT','another-group')
    monkeypatch.setenv('RESEARCHRELAY_TOKENS','{"private-team-token":"human"}')
    captured={}
    def demo(engine,repo):
        captured.update(project=engine.project_id,db=engine.db_path,repo=repo,settings=Settings())
        return {'status':'test-stub'}
    monkeypatch.setattr('researchrelay.pilot.run_pilot',demo)
    cli(['demo','--offline'])
    assert captured['project']=='agentic-collaboration'
    assert captured['db']==Path('.runtime/offline-demo/state.db')
    assert captured['repo']==Path('.runtime/offline-demo/project-record').resolve()
    assert captured['settings'].tokens=={} and captured['settings'].github_url is None


def test_offline_service_preserves_and_rejects_a_saved_shared_binding(tmp_path,monkeypatch,capsys):
    from researchrelay.cli import main as cli
    from researchrelay.sync import ProjectSync
    engine=Engine(tmp_path/'bound.db',project_id='agentic-collaboration')
    settings=Settings(db_path=engine.db_path,repo_path=tmp_path/'bound-record',github_url=None)
    saved={'url':'git@github.com:group/research.git','branch':'knowledge','knowledge_path':'projects/team'}
    synchronizer=ProjectSync(settings,engine);synchronizer._set('shared_repository',saved)
    before=engine.list_tasks()
    monkeypatch.setattr('uvicorn.run',lambda *a,**k:pytest.fail('Bound database must not start offline'))
    with pytest.raises(SystemExit) as error:
        cli(['serve','--offline-demo','--db',str(engine.db_path),'--repo',str(tmp_path/'bound-record')])
    assert error.value.code==2 and 'saved binding was preserved' in capsys.readouterr().err
    assert synchronizer.binding==saved and engine.list_tasks()==before


def test_service_db_override_requires_explicit_offline_mode(tmp_path,capsys):
    from researchrelay.cli import main as cli
    with pytest.raises(SystemExit) as error: cli(['serve','--db',str(tmp_path/'do-not-create.db')])
    assert error.value.code==2 and 'require --offline-demo' in capsys.readouterr().err
    assert not (tmp_path/'do-not-create.db').exists()


def test_offline_service_refuses_non_loopback_even_with_inherited_tokens(tmp_path,monkeypatch,capsys):
    from researchrelay.cli import main as cli
    monkeypatch.setenv('RESEARCHRELAY_TOKENS','{"private-team-token":"human"}')
    with pytest.raises(SystemExit) as error:
        cli(['serve','--offline-demo','--db',str(tmp_path/'offline.db'),'--repo',str(tmp_path/'record'),'--host','0.0.0.0'])
    assert error.value.code==2 and 'before binding to a non-loopback' in capsys.readouterr().err
