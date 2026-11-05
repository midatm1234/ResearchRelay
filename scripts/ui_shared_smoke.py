"""Browser interaction checks with an explicitly mocked collaboration backend.

No Git/model calls are made. Run after installing .[browser] and Chromium.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import time

import httpx
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, expect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local-git',action='store_true',help='Exercise the real service with a temporary bare Git remote.')
    args=parser.parse_args()
    if args.local_git:
        local_git_main()
        return
    root = Path(__file__).resolve().parent.parent
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root/'researchrelay'), **kwargs)
        def do_GET(self):
            if self.path == '/':
                self.path = '/static/index.html'
            super().do_GET()
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    state = {'commit':'a'*40,'profile':{'provider':'manual'},'publications':[],'syncs':0,'conflict':True}
    original = "---\nid: shared-note\nproject_id: agentic-collaboration\nschema_version: '1.0'\nartifact_type: synthesis\ntype: 'Research Synthesis'\nversion: 1\nresponsible_participant: alice\nproducing_agent: alice-agent\ncreated_at: '2026-11-04T12:00:00Z'\nupdated_at: '2026-11-04T12:00:00Z'\nformat_status: provisional\ncitations: []\nrelations: []\nprovenance:\n  method: browser-qa-fixture\n---\n\n# Shared evidence\n\nInitial finding.\n"
    document = {'path':'projects/agentic-collaboration/shared-note.md','content':original,
                'sha256':hashlib.sha256(original.encode()).hexdigest(),
                'metadata':{'id':'shared-note','artifact_type':'synthesis','title':'Shared evidence','version':1,
                            'responsible_participant':'alice','producing_agent':'alice-agent','format_status':'provisional'},
                'body':'# Shared evidence','commit':state['commit']}
    def project(participant='human'):
        return {'project_id':'agentic-collaboration','participant':participant,
                'repository':{'url':'git@github.com:example/research.git','branch':'SRTD_DT_test','knowledge_path':'projects/agentic-collaboration'},
                'sync':{'status':'synced','latest_commit':state['commit'],'last_checked_at':'2026-11-04T12:00:00Z','error':None,'next_action':None},
                'format_status':'provisional'}
    def intercept(route):
        request=route.request
        path=urlparse(request.url).path
        participant='bob' if request.headers.get('authorization')=='Bearer bob-project-token' else 'human'
        payload=request.post_data_json if request.post_data else None
        status=200
        if path=='/api/dashboard':
            result={'project_id':'agentic-collaboration','mode':'live','tasks':[],'artifacts':[],'decisions':[],
                    'events':[],'metrics':[],'jobs':[],'latest_seq':0,'project':project(participant)}
        elif path=='/api/project':
            result=project(participant)
        elif path=='/api/project/context':
            result={**project(participant),'documents':[document],'tasks':[],'artifacts':[]}
        elif path=='/api/project/sync':
            state['syncs']+=1
            result=project(participant)['sync']
        elif path=='/api/participants/me/agent':
            if request.method=='PUT':
                state['profile']=payload
            result={'participant':participant,'profile':state['profile']}
        elif path=='/api/project/publish':
            state['publications'].append(payload)
            if state['conflict']:
                state['conflict']=False
                state['commit']='b'*40
                document['content']=original+'\nTeammate concurrent extension.\n'
                document['sha256']=hashlib.sha256(document['content'].encode()).hexdigest()
                document['commit']=state['commit']
                status=409
                result={'detail':'The target file changed after your retrieved context.','conflicts':[document['path']],
                        'next_action':'Compare the latest version and reconcile your draft.'}
            else:
                assert payload['base_commit']=='b'*40
                assert payload['changes'][0]['expected_sha256']==document['sha256']
                assert 'My preserved draft.' in payload['changes'][0]['content']
                document['content']=payload['changes'][0]['content']
                document['sha256']=hashlib.sha256(document['content'].encode()).hexdigest()
                state['commit']='c'*40
                document['commit']=state['commit']
                result={'status':'published','commit':state['commit'],'branch':'SRTD_DT_test','paths':[document['path']]}
        else:
            status=404
            result={'detail':f'Unexpected mocked API route: {path}'}
        route.fulfill(status=status,content_type='application/json',body=json.dumps(result))
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            page=browser.new_page(viewport={'width':1512,'height':1100})
            errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.route('**/api/**',intercept)
            page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
            expect(page.locator('#project-title')).to_have_text('Collaborative science with agentic AI')
            expect(page.locator('#sync-details')).to_contain_text('aaaaaaaaaaaa')
            expect(page.locator('#knowledge-list')).to_contain_text('alice / alice-agent')
            expect(page.locator('#knowledge-format')).to_contain_text('Selected OKF 0.2')
            expect(page.locator('#pilot-button')).not_to_be_visible()
            page.locator('#sync-project-button').click()
            expect(page.locator('#sync-project-button')).to_be_enabled()
            assert state['syncs']==1
            # A connection profile stores only metadata and never pretends to run a model.
            page.locator('#agent-profile-button').click()
            assert page.get_by_role('textbox',name='Provider credential environment variable name').input_value()==''
            page.get_by_role('combobox',name='Preferred agent connection').select_option('openai-compatible')
            page.get_by_role('textbox',name='Agent model ID').fill('local-model')
            page.get_by_role('textbox',name='Agent API base URL').fill('http://127.0.0.1:11434/v1')
            page.get_by_role('button',name='Save my agent connection').click()
            expect(page.locator('#detail-dialog')).not_to_be_visible()
            assert 'api_key_env' not in state['profile']
            page.locator('#agent-profile-button').click()
            assert page.get_by_role('textbox',name='Provider credential environment variable name').input_value()==''
            page.get_by_role('combobox',name='Preferred agent connection').select_option('openai-responses')
            page.get_by_role('textbox',name='Agent model ID').fill('configured-test-model')
            page.get_by_role('textbox',name='Provider credential environment variable name').fill('OPENAI_API_KEY')
            page.get_by_role('button',name='Save my agent connection').click()
            expect(page.locator('#detail-dialog')).not_to_be_visible()
            assert state['profile']['provider']=='openai-responses'
            assert state['profile']['api_key_env']=='OPENAI_API_KEY'
            assert 'api_key' not in state['profile']
            # Switching to an editor handoff must not retain API credential metadata.
            page.locator('#agent-profile-button').click()
            page.get_by_role('combobox',name='Preferred agent connection').select_option('vscode')
            expect(page.locator('.editor-handoff-help')).to_be_visible()
            expect(page.locator('.editor-handoff-help')).to_contain_text('REPORT_READY')
            page.get_by_role('textbox',name='Agent model ID').fill('my-editor-model')
            page.get_by_role('button',name='Save my agent connection').click()
            expect(page.locator('#detail-dialog')).not_to_be_visible()
            assert state['profile']=={'provider':'vscode','model':'my-editor-model'}
            # A stale edit must retain the exact draft until the person reviews a new base.
            page.locator('.knowledge-title').first.click()
            page.get_by_role('button',name='Edit and publish a revision').click()
            draft=page.get_by_role('textbox',name='Shared Markdown draft')
            draft.fill(draft.input_value()+'\nMy preserved draft.\n')
            page.get_by_role('button',name='Publish contribution to GitHub').click()
            expect(page.locator('.publish-problem')).to_contain_text('Concurrent change detected')
            assert 'My preserved draft.' in draft.input_value()
            original_request=state['publications'][0]['request_id']
            page.get_by_role('button',name='Retrieve latest for comparison').click()
            expect(page.locator('.publish-comparison')).to_contain_text('Teammate concurrent extension.')
            rebase=page.get_by_role('button',name='Use this reviewed base for my draft')
            expect(rebase).to_be_disabled()
            draft.fill(draft.input_value()+'\nTeammate concurrent extension.\n')
            page.get_by_role('checkbox',name='I reconciled my draft with the latest committed file').check()
            rebase.click()
            assert 'My preserved draft.' in draft.input_value()
            page.get_by_role('button',name='Publish contribution to GitHub').click()
            expect(page.locator('#detail-dialog')).not_to_be_visible()
            assert len(state['publications'])==2
            assert state['publications'][1]['request_id']!=original_request
            # Change browser participant via its own session token.
            page.get_by_role('button',name='Access',exact=True).click()
            page.get_by_label('Project access token').fill('bob-project-token')
            page.get_by_role('button',name='Use for this browser session').click()
            expect(page.locator('#participant-label')).to_have_text('Bob')
            expect(page.locator('#configure-project-button')).not_to_be_visible()
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors,errors
            browser.close()
        print(json.dumps({'status':'passed','mode':'mocked-backend browser UI','checks':[
            'repository commit and attribution','forced update retrieval','own profile metadata','unauthenticated local-provider profile','VS Code handoff metadata and instructions','stale publication draft preservation',
            'explicit reconciliation and normal retry','participant token switch','mobile layout'],'page_errors':errors}))
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def local_git_main():
    """Actual Git transport and service, with no external host or model calls."""
    from researchrelay.knowledge import render_knowledge
    from researchrelay.repository import _git
    root=Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix='ResearchRelay shared UI ') as directory:
        temporary=Path(directory)
        seed=temporary/'seed';seed.mkdir()
        _git(seed,'init','-b','SRTD_DT_test')
        relative='projects/agentic-collaboration/shared-note.md'
        target=seed/relative;target.parent.mkdir(parents=True)
        metadata={'id':'ui-shared-evidence','project_id':'agentic-collaboration','artifact_type':'synthesis',
                  'type':'Research Synthesis','title':'Shared evidence','responsible_participant':'alice',
                  'producing_agent':'ui-fixture','version':1,'provenance':{'method':'synthetic UI fixture, not literature evidence'}}
        target.write_bytes(render_knowledge(metadata,'# Shared evidence\n\nInitial synthetic finding.').encode('utf-8'))
        _git(seed,'add','--',relative)
        _git(seed,'-c','user.name=UI fixture','-c','user.email=fixture@localhost.invalid','commit','-m','Seed synthetic shared UI fixture')
        remote=temporary/'remote.git'
        subprocess.run(['git','init','--bare',str(remote)],capture_output=True,check=True)
        _git(seed,'remote','add','origin',str(remote))
        _git(seed,'push','-u','origin','SRTD_DT_test')
        other=temporary/'other participant'
        subprocess.run(['git','clone','--branch','SRTD_DT_test',str(remote),str(other)],capture_output=True,check=True)
        environment=dict(os.environ,RESEARCHRELAY_MODE='demo',RESEARCHRELAY_PROJECT='agentic-collaboration',
                         RESEARCHRELAY_DB=str(temporary/'service/state.db'),RESEARCHRELAY_REPO=str(temporary/'service/record'),
                         RESEARCHRELAY_GITHUB_URL=str(remote),RESEARCHRELAY_GITHUB_BRANCH='SRTD_DT_test',
                         RESEARCHRELAY_KNOWLEDGE_PATH='projects/agentic-collaboration',RESEARCHRELAY_SYNC_INTERVAL='1',
                         RESEARCHRELAY_TOKENS=json.dumps({'ui-human-token':'human','ui-alice-token':'alice','ui-bob-token':'bob'}))
        import socket
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        url=f'http://127.0.0.1:{port}'
        with (temporary/'server.log').open('w+',encoding='utf-8') as log:
            server=subprocess.Popen([sys.executable,'-m','researchrelay.cli','serve','--port',str(port)],cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT)
            try:
                for _ in range(300):
                    try:
                        if httpx.get(url+'/api/health',timeout=1,trust_env=False).is_success:break
                    except httpx.HTTPError:pass
                    if server.poll() is not None:raise RuntimeError('Shared UI fixture service exited')
                    time.sleep(.1)
                else:raise RuntimeError('Shared UI fixture service did not become healthy')
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(headless=True)
                    page=browser.new_page(viewport={'width':1512,'height':1100})
                    page.add_init_script("sessionStorage.setItem('researchrelay:token','ui-human-token')")
                    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(url,wait_until='networkidle')
                    expect(page.locator('#pilot-button')).not_to_be_visible()
                    expect(page.locator('#sync-status')).to_contain_text('Synced',timeout=30_000)
                    expect(page.locator('#knowledge-list')).to_contain_text('Shared evidence')
                    expect(page.locator('#knowledge-list')).to_contain_text('alice / ui-fixture')
                    page.locator('#agent-profile-button').click()
                    page.get_by_role('combobox',name='Preferred agent connection').select_option('openai-responses')
                    page.get_by_role('textbox',name='Agent model ID').fill('configured-ui-test-model')
                    page.get_by_role('button',name='Save my agent connection').click()
                    expect(page.locator('#detail-dialog')).not_to_be_visible()
                    page.locator('.knowledge-title').filter(has_text='Shared evidence').click()
                    page.get_by_role('button',name='Edit and publish a revision').click()
                    draft=page.get_by_role('textbox',name='Shared Markdown draft')
                    draft.fill(draft.input_value()+'\nMy preserved UI draft.\n')
                    # A second clone commits after the first participant opened its editor.
                    changed=dict(metadata,version=2,responsible_participant='bob',producing_agent='ui-fixture-bob')
                    remote_body='# Shared evidence\n\nInitial synthetic finding.\n\nConcurrent Bob extension.\n'
                    (other/relative).write_bytes(render_knowledge(changed,remote_body).encode('utf-8'))
                    _git(other,'add','--',relative)
                    _git(other,'-c','user.name=UI Bob','-c','user.email=fixture@localhost.invalid','commit','-m','Bob concurrent extension')
                    _git(other,'push','origin','SRTD_DT_test')
                    page.get_by_role('button',name='Publish contribution to GitHub').click()
                    expect(page.locator('.publish-problem')).to_contain_text('Concurrent change detected',timeout=30_000)
                    assert 'My preserved UI draft.' in draft.input_value()
                    page.get_by_role('button',name='Retrieve latest for comparison').click()
                    expect(page.locator('.publish-comparison')).to_contain_text('Concurrent Bob extension.',timeout=30_000)
                    draft.fill(draft.input_value().replace('version: 2','version: 3')+'\nConcurrent Bob extension.\n')
                    page.get_by_role('checkbox',name='I reconciled my draft with the latest committed file').check()
                    page.get_by_role('button',name='Use this reviewed base for my draft').click()
                    page.get_by_role('button',name='Publish contribution to GitHub').click()
                    expect(page.locator('#detail-dialog')).not_to_be_visible(timeout=30_000)
                    _git(other,'fetch','origin','SRTD_DT_test')
                    committed=_git(other,'show',f'origin/SRTD_DT_test:{relative}')
                    assert 'My preserved UI draft.' in committed and 'Concurrent Bob extension.' in committed
                    assert 'human:human' in committed
                    # Another token sees the new committed artifact and its own profile.
                    page.get_by_role('button',name='Access',exact=True).click()
                    page.get_by_label('Project access token').fill('ui-bob-token')
                    page.get_by_role('button',name='Use for this browser session').click()
                    expect(page.locator('#participant-label')).to_have_text('Bob')
                    page.locator('#sync-project-button').click()
                    expect(page.locator('#sync-project-button')).to_be_enabled(timeout=30_000)
                    expect(page.locator('#sync-status')).to_contain_text('Synced',timeout=30_000)
                    page.locator('.knowledge-title').filter(has_text='Shared evidence').click()
                    expect(page.locator('.knowledge-source')).to_contain_text('My preserved UI draft.')
                    page.locator('#detail-dialog .close-dialog').click()
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    assert not errors,errors
                    browser.close()
                time.sleep(1)  # Drain any already-started local Git retrieval before Windows shutdown.
                print(json.dumps({'status':'passed','mode':'real service and local bare Git remote; no external model calls',
                                  'checks':['project retrieval','own profile metadata','concurrent clone update','stale draft retained',
                                            'explicit merged reconciliation','normal Git publication','second participant retrieval','mobile layout'],
                                  'page_errors':errors}))
            except BaseException:
                log.flush();log.seek(0);print(log.read(),file=sys.stderr)
                raise
            finally:
                server.terminate()
                try:server.wait(timeout=10)
                except subprocess.TimeoutExpired:server.kill();server.wait(timeout=10)


if __name__=='__main__':
    main()
