from fastapi.testclient import TestClient

from coclaude.api import create_app
from coclaude.config import Settings
from coclaude.engine import Engine


def client_for(tmp_path,tokens=None):
    settings = Settings(db_path=tmp_path/'state.db',repo_path=tmp_path/'record',tokens=tokens or {})
    return TestClient(create_app(settings,Engine(settings.db_path)))


def test_meeting_scope_and_task_protocol(tmp_path):
    with client_for(tmp_path) as client:
        meeting = client.post('/api/meetings',json={'notes':
            'Agreed: Compare errors because accuracy matters.\n'
            'Task score | owner=alice | Score forecast | criteria=Report RMSE | outputs=score.json'}).json()
        assert meeting['decisions'][0]['provenance']=='explicit'
        approved = client.post(f'/api/meetings/{meeting["id"]}/approve',json={'tasks':meeting['proposed_tasks']})
        assert approved.status_code == 200,approved.text
        assert client.get('/api/tasks',params={'owner':'alice','ready':True}).json()[0]['id']=='score'
        claim = client.post('/api/tasks/score/claim',json={'worker_id':'alice'}).json()
        assert claim['claim_token']
        assert 'claim_token' not in client.get('/api/tasks/score').json()
        assert 'claim_token' not in client.get('/api/dashboard').json()['tasks'][0]
        assert client.post('/api/tasks/score/heartbeat',json={'claim_token':claim['claim_token'],'progress':'Computing'}).status_code==200
        canceled=client.post('/api/tasks/score/cancel')
        assert canceled.status_code==200
        assert client.post('/api/tasks/score/heartbeat',json={'claim_token':claim['claim_token']}).status_code==409


def test_tokens_scope_execution_and_human_decisions(tmp_path):
    with client_for(tmp_path,{'secret-human':'human','secret-alice':'alice','secret-bob':'bob'}) as client:
        assert client.get('/api/dashboard').status_code==401
        human={'Authorization':'Bearer secret-human'}
        alice={'Authorization':'Bearer secret-alice'}
        bob={'Authorization':'Bearer secret-bob'}
        assert client.post('/api/tasks',headers=human,json={'id':'score','title':'Score','owner':'alice','acceptance_criteria':['Evidence']}).status_code==201
        assert client.post('/api/tasks/score/claim',headers=bob,json={'worker_id':'bob'}).status_code==403
        assert client.post('/api/tasks/score/claim',headers=alice,json={'worker_id':'alice'}).status_code==200
        assert client.post('/api/tasks/score/cancel',headers=alice).status_code==403
        assert client.post('/api/tasks/score/cancel',headers=human).status_code==200


def test_upload_and_schema(tmp_path):
    with client_for(tmp_path) as client:
        response=client.post('/api/meetings/upload',files={'file':('meeting.txt',b'Alice will report error metrics')})
        assert response.status_code==201,response.text
        record=response.json()['artifact']
        exported=client.get(f'/api/artifacts/{record["id"]}/markdown',params={'version':1})
        assert exported.status_code==200
        assert exported.text.startswith('---\n')
        assert client.get('/api/schemas/result').status_code==200
        assert client.get('/').status_code==200
        assert client.get('/static/app.js').status_code==200


def test_result_revision_and_independent_review_roundtrip(tmp_path):
    with client_for(tmp_path,{'secret-human':'human','secret-alice':'alice','secret-bob':'bob'}) as client:
        human = {'Authorization':'Bearer secret-human'}
        alice = {'Authorization':'Bearer secret-alice'}
        bob = {'Authorization':'Bearer secret-bob'}
        created = client.post('/api/tasks',headers=human,json={
            'id':'score','title':'Score paired forecasts','owner':'alice',
            'acceptance_criteria':['Report RMSE, paired count, and pairing evidence']})
        assert created.status_code == 201, created.text
        claim = client.post('/api/tasks/score/claim',headers=alice,json={'worker_id':'alice-claude'}).json()
        artifact = {'metadata':{'id':'result-score','project_id':'forecast-pilot',
            'artifact_type':'result','task_id':'score','producing_agent':'claude-local-adapter',
            'data':[{'uri':'synthetic://forecast','n':4}], 'code':{'commit':'0123456789abcdef'},
            'configuration':{'metric':'RMSE'}, 'environment':{'python':'3.12'},
            'evidence':{'rmse':0.5,'n':4}},'body':'RMSE 0.5, n=4; pairing evidence to follow.'}
        payload = {'claim_token':claim['claim_token'],'idempotency_key':'score-attempt-1',
                   'artifact':artifact,'completion_notes':'First pass metrics complete'}
        first = client.post('/api/tasks/score/submit',headers=alice,json=payload)
        assert first.status_code == 200, first.text
        assert first.json()['status'] == 'awaiting_review'
        assert 'claim_token' not in first.json()['task']
        assert client.post('/api/tasks/score/submit',headers=alice,json=payload).json() == first.json()
        revision = client.post('/api/tasks/score/reviews',headers=bob,json={
            'reviewer':'bob','verdict':'revise','rationale':'Provide paired date IDs so the pairing criterion can be checked',
            'criteria':['RMSE and n present; paired date IDs missing'],'result_version':1})
        assert revision.status_code == 200, revision.text
        assert revision.json()['task']['status'] == 'queued'
        assert client.get('/api/tasks',headers=alice,params={'owner':'alice','ready':True}).json()[0]['id'] == 'score'
        claim2 = client.post('/api/tasks/score/claim',headers=alice,json={'worker_id':'alice-claude'}).json()
        artifact['metadata']['version'] = 2
        artifact['metadata']['evidence']['paired_dates'] = ['day1','day2','day3','day4']
        artifact['body'] = 'RMSE 0.5, n=4; paired dates day1, day2, day3, day4.'
        revised = client.post('/api/tasks/score/submit',headers=alice,json={
            'claim_token':claim2['claim_token'],'idempotency_key':'score-attempt-2','artifact':artifact,
            'completion_notes':'Recorded paired date IDs as requested'})
        assert revised.status_code == 200, revised.text
        accepted = client.post('/api/tasks/score/reviews',headers=bob,json={
            'reviewer':'bob','verdict':'approve','rationale':'All three criteria are now evidenced',
            'criteria':['RMSE verified','n=4 verified','Four paired date IDs verified'],'result_version':2})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()['task']['status'] == 'completed'
        original = client.get('/api/artifacts/result-score',headers=alice,params={'version':1}).json()
        assert 'paired_dates' not in original['metadata']['evidence']
        current = client.get('/api/artifacts/result-score',headers=alice,params={'version':2}).json()
        assert len(current['metadata']['evidence']['paired_dates']) == 4
        markdown = client.get('/api/artifacts/result-score/markdown',headers=human,params={'version':2})
        assert markdown.status_code == 200 and 'version: 2' in markdown.text
        dashboard = client.get('/api/dashboard',headers=human).json()
        assert dashboard['tasks'][0]['completion_notes'] == 'Recorded paired date IDs as requested'
        assert dashboard['tasks'][0]['revision_count'] == 1


def test_startup_exposes_interrupted_background_job(tmp_path):
    settings = Settings(db_path=tmp_path/'state.db',repo_path=tmp_path/'record',tokens={})
    coordinator = Engine(settings.db_path)
    coordinator.start_job()
    with TestClient(create_app(settings,coordinator)) as client:
        status = client.get('/api/pilot/status')
        assert status.status_code == 200
        assert status.json()['status'] == 'interrupted'
        assert 'restarted' in status.json()['data'].lower()


def test_authenticated_attribution_cannot_be_spoofed_by_coordinator_or_workers(tmp_path):
    with client_for(tmp_path,{'human-key':'human','alice-key':'alice','bob-key':'bob'}) as client:
        human = {'Authorization':'Bearer human-key'}
        alice = {'Authorization':'Bearer alice-key'}
        bob = {'Authorization':'Bearer bob-key'}
        meeting = client.post('/api/meetings',headers=human,json={
            'notes':'Task score | owner=alice | Score observations | criteria=Report metrics',
            'participant':'pretend-participant'})
        assert meeting.status_code == 201, meeting.text
        assert meeting.json()['metadata']['responsible_participant'] == 'human'
        client.post('/api/tasks',headers=human,json={
            'id':'score','title':'Score','owner':'alice','acceptance_criteria':['Metrics']})
        claimed = client.post('/api/tasks/score/claim',headers=alice,json={'worker_id':'alice-agent'}).json()
        assert client.post('/api/tasks/score/heartbeat',headers=bob,json={
            'claim_token':claimed['claim_token']}).status_code == 403
        artifact = {'metadata':{'id':'result-score','project_id':'forecast-pilot','artifact_type':'result',
            'task_id':'score','data':['synthetic://data'],'code':['0123456789abcdef'],
            'configuration':{'metric':'RMSE'},'environment':{'python':'3.12'},'evidence':['n=4, RMSE=0.5']},
            'body':'Result'}
        assert client.post('/api/tasks/score/submit',headers=alice,json={
            'claim_token':claimed['claim_token'],'idempotency_key':'score','artifact':artifact}).status_code == 200
        for auth, spoofed_reviewer in [(human,'bob'),(alice,'bob'),(bob,'alice')]:
            assert client.post('/api/tasks/score/reviews',headers=auth,json={
                'reviewer':spoofed_reviewer,'verdict':'approve','rationale':'Looks good',
                'criteria':['Metrics evidenced'],'result_version':1}).status_code == 403
        assert client.post('/api/tasks/score/reviews',headers=bob,json={
            'reviewer':'bob','verdict':'approve','rationale':'Metrics checked independently',
            'criteria':['Metrics evidenced'],'result_version':1}).status_code == 200
        requested = client.post('/api/decisions',headers=alice,json={
            'question':'Collect more observations?','evidence':['n=4 only'],
            'options':['Collect more','Limit claims'],'consequence':'Determines follow-up scope'}).json()
        resolved = client.post(f'/api/decisions/{requested["id"]}/resolve',headers=human,json={
            'participant':'pretend-scientist','choice':'Collect more','rationale':'Small sample limits interpretation'})
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()['resolved_by'] == 'human'


def test_generic_artifact_api_enforces_task_ownership_and_existing_responsibility(tmp_path):
    with client_for(tmp_path,{'human-key':'human','alice-key':'alice','bob-key':'bob'}) as client:
        human = {'Authorization':'Bearer human-key'}
        alice = {'Authorization':'Bearer alice-key'}
        bob = {'Authorization':'Bearer bob-key'}
        client.post('/api/tasks',headers=human,json={
            'id':'bob-score','title':'Bob score','owner':'bob','acceptance_criteria':['Metrics']})
        forged_result = {'metadata':{'id':'result-bob-score','project_id':'forecast-pilot',
            'artifact_type':'result','task_id':'bob-score','responsible_participant':'alice',
            'data':['synthetic://data'],'code':['0123456789abcdef'],
            'configuration':{'metric':'RMSE'},'environment':{'python':'3.12'},'evidence':['n=4']}}
        assert client.post('/api/artifacts',headers=alice,json=forged_result).status_code == 403
        for kind in ('task','meeting'):
            assert client.post('/api/artifacts',headers=alice,json={'metadata':{
                'id':'forged-scope','project_id':'forecast-pilot','artifact_type':kind,
                'responsible_participant':'alice'}}).status_code == 403
        own_decision = {'metadata':{'id':'bob-observation','project_id':'forecast-pilot',
            'artifact_type':'decision','responsible_participant':'bob','question':'Investigate coverage?',
            'options':['Investigate','Defer'],'evidence':['Sparse stations'],'consequence':'Scopes analysis'}}
        assert client.post('/api/artifacts',headers=bob,json=own_decision).status_code == 201
        own_decision['metadata'].update(version=2,responsible_participant='alice')
        assert client.post('/api/artifacts',headers=alice,json=own_decision).status_code == 403
        # Human reconciliation is explicit and still cannot misattribute a result task.
        assert client.post('/api/artifacts',headers=human,json=own_decision).status_code == 201
        assert client.post('/api/artifacts',headers=human,json=forged_result).status_code == 403
