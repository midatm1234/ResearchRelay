"""Browser freshness and real local reloads with durable workflow state."""
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time

import httpx
from fastapi.testclient import TestClient

from researchrelay.api import create_app
from researchrelay.config import Settings


def test_pages_assets_and_project_state_are_not_cached(tmp_path):
    settings = Settings(db_path=tmp_path/'state.db', repo_path=tmp_path/'record', github_url=None, tokens={})
    with TestClient(create_app(settings)) as client:
        for path in ('/', '/workspace', '/projects', '/projects/example', '/static/app.js',
                     '/static/projects.js', '/static/styles.css', '/api/health', '/api/dashboard'):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.headers['cache-control'] == 'no-store', path


def test_local_serve_loads_changed_python_and_preserves_tasks(tmp_path):
    source = tmp_path/'source'
    package = source/'researchrelay'
    shutil.copytree(Path(__file__).resolve().parents[1]/'researchrelay', package,
                    ignore=shutil.ignore_patterns('__pycache__'))
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    environment = {key:value for key,value in os.environ.items() if not key.upper().startswith('RESEARCHRELAY_')}
    environment['PYTHONPATH'] = str(source)
    log_path = tmp_path/'server.log'
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-m', 'researchrelay', 'serve', '--offline-demo', '--port', str(port)],
            cwd=tmp_path, env=environment, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=os.name != 'nt',
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False, timeout=1) as client:
                def wait_for_status(expected):
                    deadline = time.monotonic()+30
                    while time.monotonic() < deadline and process.poll() is None:
                        try:
                            response = client.get('/api/health')
                            if response.status_code == 200 and response.json()['status'] == expected:
                                return
                        except httpx.HTTPError:
                            pass
                        time.sleep(.1)
                    raise AssertionError(log_path.read_text(encoding='utf-8'))

                wait_for_status('ok')
                response = client.post('/api/tasks', json=dict(id='keep-after-reload', title='Retain saved task',
                    owner='alice', acceptance_criteria=['Task survives a code reload']))
                assert response.status_code == 201, response.text
                api_path = package/'api.py'
                original = api_path.read_text(encoding='utf-8')
                changed = original.replace("return {'status':'ok'", "return {'status':'reloaded'", 1)
                assert changed != original
                api_path.write_text(changed, encoding='utf-8')
                wait_for_status('reloaded')
                tasks = client.get('/api/tasks').json()
                assert [task['id'] for task in tasks] == ['keep-after-reload']
                assert client.get('/workspace').headers['cache-control'] == 'no-store'
        finally:
            if process.poll() is None:
                process.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=10)
