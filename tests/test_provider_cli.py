import json

import httpx
import pytest

from researchrelay.cli import main
from researchrelay.knowledge import render_knowledge


def client_factory(monkeypatch, handler):
    original=httpx.Client
    monkeypatch.setattr('researchrelay.cli.httpx.Client',lambda **kwargs: original(transport=httpx.MockTransport(handler),**kwargs))


def test_cli_profile_stores_key_name_and_uses_local_project_token(monkeypatch,capsys):
    monkeypatch.setenv('RESEARCHRELAY_TOKEN','local-project-token')
    def server(request):
        assert request.url.path=='/api/participants/me/agent'
        assert request.headers['Authorization']=='Bearer local-project-token'
        profile=json.loads(request.content)
        assert profile['api_key_env']=='OPENAI_API_KEY'
        assert 'local-project-token' not in request.content.decode()
        return httpx.Response(200,json={'participant':'alice','profile':profile})
    client_factory(monkeypatch,server)
    main(['agent','configure','--provider','openai-responses','--model','chosen-model'])
    assert json.loads(capsys.readouterr().out)['profile']['model']=='chosen-model'


def test_cli_publication_uses_saved_context_hash_and_stable_retry_id(tmp_path,monkeypatch,capsys):
    path='projects/agentic-collaboration/finding.md'
    context={'project_id':'agentic-collaboration','participant':'alice','sync':{'latest_commit':'a'*40},
             'documents':[{'path':path,'sha256':'b'*64}]}
    saved=tmp_path/'context.json';saved.write_text(json.dumps(context),encoding='utf-8')
    draft=tmp_path/'finding.md';draft.write_text(render_knowledge({'id':'finding','project_id':'agentic-collaboration',
        'artifact_type':'source_note','responsible_participant':'alice','producing_agent':'configured-agent/1'},'# Finding'),encoding='utf-8')
    payloads=[]
    def server(request):
        assert request.url.path=='/api/project/publish'
        payload=json.loads(request.content);payloads.append(payload)
        assert payload['base_commit']=='a'*40
        assert payload['changes'][0]['expected_sha256']=='b'*64
        assert payload['agent']=='configured-agent/1'
        return httpx.Response(200,json={'status':'published','commit':'c'*40})
    client_factory(monkeypatch,server)
    arguments=['project','publish','--context',str(saved),'--file',str(draft),'--path',path]
    main(arguments);main(arguments)
    assert payloads[0]==payloads[1]
    assert payloads[0]['request_id'].startswith('cli-')


def test_cli_conflict_explains_changed_path_and_next_action(tmp_path,monkeypatch,capsys):
    def server(request):
        return httpx.Response(409,json={'detail':'The finding changed.','paths':['projects/project/finding.md'],
                                        'next_action':'Read the new revision before editing.'})
    client_factory(monkeypatch,server)
    with pytest.raises(SystemExit) as error:
        main(['project','sync'])
    assert error.value.code==2
    message=capsys.readouterr().err
    assert 'HTTP 409' in message and 'projects/project/finding.md' in message and 'Read the new revision' in message


def test_cli_vscode_profile_does_not_request_api_credentials(monkeypatch,capsys):
    def server(request):
        profile=json.loads(request.content)
        assert profile['provider']=='vscode'
        assert profile['api_key_env'] is None and profile['base_url'] is None
        return httpx.Response(200,json={'participant':'alice','profile':profile})
    client_factory(monkeypatch,server)
    main(['agent','configure','--provider','vscode'])
    assert json.loads(capsys.readouterr().out)['profile']['provider']=='vscode'
