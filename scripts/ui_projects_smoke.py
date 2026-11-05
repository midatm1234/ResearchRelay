"""Project hub browser workflow: mocked contracts by default; --demo uses real HTTP/local Git.

Neither mode authenticates to GitHub, creates remote repositories, or calls a model.
Install .[browser] and Playwright Chromium first.
"""
from __future__ import annotations
import argparse
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlparse
import httpx
from playwright.sync_api import sync_playwright,expect


def create_project(page,name,mode='new_repository',repository=None,path=None,fail_once=False):
    page.get_by_role('button',name='＋ New Project',exact=True).click()
    page.get_by_label('Project name',exact=True).fill(name)
    page.get_by_label('Description',exact=True).fill('A browser evaluation of collaborative literature work.')
    page.get_by_label('Research objectives',exact=True).fill('Trace sources and review handoffs against explicit criteria.')
    page.get_by_label('Collaborators’ GitHub usernames').fill('bob')
    page.locator(f'input[name=mode][value={mode}]').check()
    if mode=='new_repository':
        expect(page.get_by_label('Visibility',exact=True)).to_have_value('private')
    else:
        page.get_by_label('Accessible GitHub repository').select_option(repository)
        branch=page.get_by_label('Start from branch' if mode=='new_branch' else 'Existing branch',exact=True)
        expect(branch).to_have_value('main',timeout=30_000)
        if mode=='new_branch':page.get_by_label('Project branch',exact=True).fill('researchrelay/cohort-b')
    if path:
        page.locator('#advanced-settings').evaluate('(item)=>item.open=true')
        page.get_by_label('Knowledge folder inside the repository').fill(path)
    page.get_by_role('button',name='Create project →',exact=True).click()
    if fail_once:
        expect(page.locator('#project-form-error')).to_contain_text('interrupted')
        page.get_by_role('button',name='Create project →',exact=True).click()
    expect(page.locator('#project-form-operation').get_by_role('link',name='Open project →')).to_be_visible(timeout=90_000)
    page.get_by_role('button',name='Close project form').click()
    expect(page.locator('.hub-project-card').filter(has_text=name)).to_have_count(1)


def exercise(page,url,fixture=None):
    errors=[];requests=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:requests.append((urlparse(request.url).path,request.headers.get('authorization'))))
    page.add_init_script("sessionStorage.setItem('researchrelay:token','legacy-do-not-leak');localStorage.setItem('researchrelay:last-seen','999')")
    page.goto(url+'/projects',wait_until='networkidle')
    if fixture is not None:
        expect(page.locator('#github-connect')).to_be_visible()
        expect(page.locator('#github-connect')).to_have_attribute('href','/api/hub/auth/login')
        fixture['demo']=True
        page.get_by_role('button',name='Refresh list ↻').click()
    expect(page.locator('#hub-demo')).to_contain_text('Local project demonstration')
    page.get_by_role('button',name='Continue as Alice').click()
    expect(page.locator('#hub-identity')).to_have_text('@alice')
    create_project(page,'Cohort A',fail_once=fixture is not None)
    projects=fixture['projects'] if fixture is not None else page.request.get(url+'/api/hub/status').json()['projects']
    first=next(project for project in projects if project['name']=='Cohort A')
    if fixture is not None:
        assert fixture['creates'][0]['request_id']==fixture['creates'][1]['request_id']
        assert fixture['creates'][0]==fixture['creates'][1]
        assert fixture['creates'][0]['visibility']=='private'
    create_project(page,'Cohort B','new_branch',repository=first['repository'])
    create_project(page,'Cohort C','connect',repository=first['repository'],path='projects/cohort-c')
    expect(page.locator('.hub-project-card')).to_have_count(3)
    if fixture is not None:
        fixture['fail_repositories']=True
        page.get_by_role('button',name='＋ New Project',exact=True).click()
        page.locator('input[name=mode][value=new_branch]').check()
        page.get_by_role('button',name='Reload',exact=True).click()
        expect(page.locator('#project-form-error')).to_contain_text('Repository access denied')
        expect(page.locator('#project-form-error')).to_contain_text('Reconnect GitHub')
        page.get_by_role('button',name='Close project form').click()
        fixture['fail_repositories']=False
    card=page.locator(f'[data-project-id="{first["id"]}"]')
    card.get_by_role('button',name='Edit details').click()
    page.get_by_label('Project name',exact=True).fill('Cohort A revised')
    page.get_by_label('Research objectives',exact=True).fill('Audit source access and assess review clarity.')
    page.get_by_role('button',name='Save project details →').click()
    expect(page.locator('#project-dialog')).not_to_be_visible()
    expect(card).to_contain_text('Cohort A revised')
    card.get_by_role('button',name='Refresh ↻',exact=True).click()
    expect(card.locator('.hub-card-sync')).to_contain_text('Latest retrieved commit:',timeout=60_000)
    card.get_by_role('button',name='Repository activity').click()
    expect(page.locator('#hub-detail-dialog')).to_be_visible(timeout=30_000)
    expect(page.locator('.hub-activity-item')).not_to_have_count(0)
    page.get_by_role('button',name='Close project details').click()
    page.get_by_role('button',name='Check setup status →').click()
    expect(page.locator('#hub-detail-content')).to_contain_text('Completed')
    page.get_by_role('button',name='Close project details').click()
    if fixture is not None:
        saved=fixture['operations'][fixture['creates'][-1]['request_id']]
        saved.update(original_input=fixture['creates'][-1].copy(),state='needs_reconciliation',status='needs_reconciliation')
        page.get_by_role('button',name='Check setup status →').click()
        expect(page.get_by_role('button',name='Resume setup',exact=True)).to_have_count(0)
        page.get_by_role('button',name='Close project details').click()
        saved.update(state='failed',status='failed')
        page.get_by_role('button',name='Check setup status →').click()
        page.get_by_role('button',name='Resume setup',exact=True).click()
        expect(page.locator('#hub-detail-content')).to_contain_text('Completed')
        expect(page.locator('#hub-detail-content').get_by_role('link',name='Open project →')).to_be_visible()
        assert fixture['resume_count']==1
        assert saved['original_input']==fixture['creates'][-1]
        page.get_by_role('button',name='Close project details').click()
    desktop=Path(__file__).resolve().parents[1]/'.runtime/projects-hub-desktop.png';desktop.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(desktop),full_page=True)
    page.get_by_role('button',name='Sign out',exact=True).click()
    expect(page.locator('#hub-identity')).to_have_text('Choose a demo account')
    page.get_by_role('button',name='Continue as Bob').click()
    expect(page.locator('#hub-identity')).to_have_text('@bob')
    page.get_by_role('button',name='＋ New Project',exact=True).click()
    page.locator('input[name=mode][value=connect]').check()
    page.get_by_label('Accessible GitHub repository').select_option(first['repository'])
    expect(page.get_by_label('Existing branch',exact=True)).to_have_value('main',timeout=30_000)
    page.get_by_label('Initialize a new project record in this branch').uncheck()
    page.get_by_label('Knowledge folder inside the repository').fill(first['knowledge_path'])
    page.get_by_role('button',name='Join project →',exact=True).click()
    expect(page.locator('#project-dialog')).not_to_be_visible(timeout=30_000)
    expect(page.locator('#hub-detail-dialog')).to_be_visible(timeout=30_000)
    page.get_by_role('button',name='Close project details').click()
    card=page.locator(f'[data-project-id="{first["id"]}"]')
    expect(card).to_contain_text('Cohort A revised')
    card.get_by_role('link',name='Open project →').click()
    expect(page.locator('#connection-status')).to_have_text('All changes saved',timeout=60_000)
    expect(page.locator('#project-title')).to_have_text('Cohort A revised')
    expect(page.locator('#configure-project-button')).not_to_be_visible()
    expect(page.locator('#knowledge-list')).to_contain_text('PROJECT.md')
    page.get_by_role('button',name='Project account',exact=True).click()
    expect(page.locator('#detail-content')).to_contain_text('server-managed GitHub sign-in')
    expect(page.locator('#detail-content input[type=password]')).to_have_count(0)
    page.get_by_role('button',name='Close details').click()
    page.locator('#mark-seen-button').click()
    assert page.evaluate("localStorage.getItem('researchrelay:last-seen')")=='999'
    assert page.evaluate(f"localStorage.getItem('researchrelay:project:{first['id']}:last-seen')") is not None
    assert all(not bearer for path,bearer in requests if path.startswith('/projects/') and '/api/' in path)
    page.goto(url+'/projects',wait_until='networkidle')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'Project hub overflows the mobile viewport'
    screenshot=Path(__file__).resolve().parents[1]/'.runtime/projects-hub.png';screenshot.parent.mkdir(exist_ok=True)
    page.screenshot(path=str(screenshot),full_page=True)
    if fixture is not None:
        fixture.update(configured=False,demo=False,login=None)
        page.get_by_role('button',name='Refresh list ↻').click()
        expect(page.locator('#hub-auth')).to_contain_text('GitHub sign-in is not configured')
        expect(page.locator('#github-connect')).not_to_be_visible()
        expect(page.locator('#project-list')).not_to_contain_text('Cohort A revised')
    assert not errors,errors
    return dict(status='passed',mode='real HTTP/local Git demo' if fixture is None else 'mocked hub API/browser contracts',
        checks=['three creation modes','private default','setup recovery','metadata edits','repository activity',
                'second user joins existing project','project-scoped dashboard','legacy bearer isolation','project-scoped catch-up','390px layout']+(['interrupted setup retries exact payload','resume uses saved input and excludes reconciliation','repository access error stays in form','unconfigured OAuth clears private project list'] if fixture is not None else []),
        same_request_retry=fixture is not None,browser_errors=errors,github_transport_live=False,model_inference_live=False)


def mock_main():
    root=Path(__file__).resolve().parents[1]
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(root/'researchrelay'),**kwargs)
        def do_GET(self):
            if self.path.startswith('/projects'):self.path='/static/projects.html' if self.path=='/projects' else '/static/index.html'
            super().do_GET()
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    fixture={'demo':False,'login':None,'projects':[],'creates':[],'operations':{},'joined':False}
    def repos():return [{'full_name':name,'private':True,'default_branch':'main','permissions':{'push':True,'pull':True}} for name in sorted({p['repository'] for p in fixture['projects']})]
    def visible():return fixture['projects'] if fixture['login']=='alice' else fixture['projects'][:1] if fixture['login'] and fixture['joined'] else []
    def intercept(route):
        request=route.request;path=urlparse(request.url).path;method=request.method;payload=request.post_data_json if request.post_data else None;status=200
        if path=='/api/hub/status':result={'configured':fixture.get('configured',True),'demo':fixture['demo'],'identity':{'login':fixture['login']} if fixture['login'] else None,'projects':visible(),'github_auth_url':'/api/hub/auth/login'}
        elif path=='/api/hub/auth/demo':fixture['login']=payload['login'];result={'demo':True,'identity':{'login':fixture['login']}}
        elif path=='/api/hub/auth/logout':fixture['login']=None;result={'status':'signed_out'}
        elif path=='/api/hub/repositories':
            if fixture.get('fail_repositories'):status=403;result={'detail':'Repository access denied.','next_action':'Reconnect GitHub and verify repository permissions.'}
            else:result={'repositories':repos()}
        elif path.startswith('/api/hub/repositories/') and path.endswith('/branches'):result={'branches':[{'name':'main','commit':{'sha':'a'*40}}]}
        elif path=='/api/hub/projects/join':fixture['joined']=True;result={'project':fixture['projects'][0]}
        elif path=='/api/hub/projects' and method=='POST':
            fixture['creates'].append(payload)
            operation={'id':payload['request_id'],'status':'completed','phase':'project_record_written'}
            if len(fixture['creates'])==1:
                status=503;operation.update(status='failed',phase='repository_created');result={'detail':'Project setup interrupted after repository creation.','next_action':'Retry the same request to resume.','operation':operation}
            else:
                project={'id':f'project-{len(fixture["projects"])+1}','name':payload['name'],'description':payload['description'],'objectives':payload['objectives'],'collaborators':payload['collaborators'],'repository':payload['repository'],'branch':payload['branch'],'knowledge_path':payload.get('knowledge_path') or f'projects/project-{len(fixture["projects"])+1}','role':'admin','sync':{'status':'synced','latest_commit':'b'*40}}
                fixture['projects'].append(project);operation['project']=project;fixture['operations'][operation['id']]=operation;result={'project':project,'operation':operation}
        elif path.startswith('/api/hub/operations/'):
            if path.endswith('/resume'):
                operation=fixture['operations'][path.split('/')[-2]];operation.update(status='completed',state='completed');fixture['resume_count']=fixture.get('resume_count',0)+1;result={'operation':operation,'project':operation['project']}
            else:result={'operation':fixture['operations'][path.rsplit('/',1)[-1]]}
        elif path.startswith('/api/hub/projects/'):
            project=next(p for p in fixture['projects'] if p['id']==path.split('/')[4])
            if method=='PATCH':project.update(payload)
            result={'project':project}
            if path.endswith('/refresh'):result.update(sync={'latest_commit':'b'*40,'status':'synced'},commits=[{'sha':'b'*40,'commit':{'message':'Update project objectives','author':{'name':'Alice','date':'2026-11-05'}}}])
        elif path.startswith('/projects/') and '/api/' in path:
            project=next(p for p in fixture['projects'] if p['id']==path.split('/')[2]);binding={'url':'https://github.com/'+project['repository']+'.git','branch':project['branch'],'knowledge_path':project['knowledge_path']}
            info={'project_id':project['id'],'participant':'bob','repository':binding,'sync':{'status':'synced','latest_commit':'b'*40},'format_status':'provisional'}
            if path.endswith('/dashboard'):result={'project_id':project['id'],'project':info,'mode':'live','tasks':[],'artifacts':[],'decisions':[],'events':[],'jobs':[],'metrics':[],'latest_seq':2}
            elif path.endswith('/project/context'):result={**info,'documents':[{'path':project['knowledge_path']+'/PROJECT.md','content':'# Shared project record','body':'# Shared project record','sha256':'d'*64,'commit':'b'*40,'metadata':{'id':project['id'],'title':project['name'],'artifact_type':'project','responsible_participant':'alice','producing_agent':'mock-fixture'}}]}
            else:result=info
        else:status=404;result={'detail':'Unexpected mocked route: '+path}
        route.fulfill(status=status,content_type='application/json',body=json.dumps(result))
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1000});page.route('**/api/**',intercept)
            result=exercise(page,f'http://127.0.0.1:{server.server_port}',fixture);browser.close();print(json.dumps(result))
    finally:server.shutdown();server.server_close();thread.join(timeout=5)


def demo_main():
    with tempfile.TemporaryDirectory(prefix='ResearchRelay project hub UI ') as directory:
        root=Path(directory)
        with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
        environment={key:value for key,value in os.environ.items() if not key.upper().startswith('RESEARCHRELAY_')}
        with (root/'private-server.log').open('w',encoding='utf-8') as log:
            service=subprocess.Popen([sys.executable,'-m','researchrelay','serve','--project-demo','--port',str(port)],cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT)
            try:
                for _ in range(300):
                    try:
                        if httpx.get(f'http://127.0.0.1:{port}/api/health',timeout=1,trust_env=False).is_success:break
                    except httpx.HTTPError:pass
                    assert service.poll() is None,'Project demo service exited before startup'
                    time.sleep(.1)
                else:raise AssertionError('Project demo did not start')
                with sync_playwright() as pw:
                    browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1000})
                    result=exercise(page,f'http://127.0.0.1:{port}');browser.close();print(json.dumps(result))
                time.sleep(.5)
            finally:
                service.terminate()
                try:service.wait(timeout=15)
                except subprocess.TimeoutExpired:service.kill();service.wait(timeout=10)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--demo',action='store_true',help='Use the real local project-demo service/Git instead of mocked HTTP contracts.')
    args=parser.parse_args();demo_main() if args.demo else mock_main()
