"""Exercise home expansion and non-ASCII paths without requiring a particular OS."""
import json
from pathlib import Path

from researchrelay.config import Settings
from researchrelay.engine import Engine
from researchrelay.repository import Repository, _git
from researchrelay.worker import Worker


def home_directory(tmp_path, monkeypatch):
    home = tmp_path/'Research Team home'
    home.mkdir()
    monkeypatch.setenv('HOME',str(home))
    monkeypatch.setenv('USERPROFILE',str(home))
    return home


def test_config_expands_home_in_environment_paths(tmp_path, monkeypatch):
    home = home_directory(tmp_path,monkeypatch)
    monkeypatch.setenv('RESEARCHRELAY_DB','~/Library/Application Support/ResearchRelay/state.db')
    monkeypatch.setenv('RESEARCHRELAY_REPO','~/Library/Application Support/ResearchRelay/project record')
    settings = Settings()
    assert settings.db_path == home/'Library/Application Support/ResearchRelay/state.db'
    assert settings.repo_path == home/'Library/Application Support/ResearchRelay/project record'


def test_database_and_git_support_home_spaces_and_unicode(tmp_path, monkeypatch):
    home = home_directory(tmp_path,monkeypatch)
    engine = Engine('~/Research équipe/state.db')
    repo = Repository('~/Research équipe/project record')
    assert engine.db_path.is_file()
    assert repo.path == (home/'Research équipe/project record').resolve()
    engine.put_artifact({'id':'decision-method','project_id':engine.project_id,'artifact_type':'decision',
                        'question':'Comparer les résultats?','options':['Réviser la méthode'],
                        'evidence':['Sources bibliographiques'],'consequence':'Nouvelle analyse'},
                        '# Résultats\n\nDonnées et limites.')
    repo.export(engine)
    assert not repo.import_artifacts(engine)['conflicts']
    # git log emits the actual non-ASCII commit message; decode it consistently.
    _git(repo.path,'-c','user.name=ResearchRelay test','-c','user.email=test@localhost.invalid',
         'commit','--allow-empty','-m','Méthodologie vérifiée')
    assert _git(repo.path,'log','-1','--format=%B') == 'Méthodologie vérifiée'
    assert _git(repo.path,'status','--porcelain') == ''


def test_worker_can_resubmit_a_home_relative_payload(tmp_path, monkeypatch):
    home = home_directory(tmp_path,monkeypatch)
    payload = {'idempotency_key':'stable-attempt','completion_notes':'Résultat conservé'}
    (home/'submission.json').write_text(json.dumps(payload),encoding='utf-8')
    worker = Worker('http://localhost','alice',tmp_path/'project')
    requests = []
    monkeypatch.setattr(worker,'_post',lambda route,data: requests.append((route,data)) or {'status':'accepted'})
    assert worker.resubmit('~/submission.json','analysis') == {'status':'accepted'}
    assert requests == [('tasks/analysis/submit',payload)]
    worker.client.close()


def test_literature_defaults_leave_an_existing_project_database_untouched(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    for name in ('RESEARCHRELAY_PROJECT','RESEARCHRELAY_DB','RESEARCHRELAY_REPO'):
        monkeypatch.delenv(name,raising=False)
    old = Engine('.runtime/state.db',project_id='previous-project')
    old.create_task(id='prior-work',title='Existing team work',owner='alice',
                    acceptance_criteria=['Preserve the existing result record'])
    settings = Settings()
    current = Engine(settings.db_path,settings.project_id)
    assert current.project_id == 'agentic-collaboration'
    assert current.db_path != old.db_path
    assert settings.repo_path == Path('.runtime/literature/project-record')
    assert current.list_tasks() == []
    assert Engine(old.db_path,'previous-project').get_task('prior-work')['status'] == 'queued'
