"""Start a disposable coordinator and exercise its real HTTP workflow on any OS.

Run from the source checkout after installing it. --browser additionally requires
the browser extra and `python -m playwright install chromium`.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import socket
import subprocess
import sys
import tempfile
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', action='store_true', help='Run the full browser workflow instead of the API pilot.')
    args = parser.parse_args()
    checkout = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix='ResearchRelay smoke ') as directory:
        workspace = Path(directory)
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        server_url = f'http://127.0.0.1:{port}'
        environment = dict(os.environ, RESEARCHRELAY_MODE='demo', RESEARCHRELAY_PROJECT='forecast-pilot',
                           RESEARCHRELAY_TOKENS='{}', RESEARCHRELAY_DB=str(workspace/'state.db'),
                           RESEARCHRELAY_REPO=str(workspace/'project record'))
        with (workspace/'server.log').open('w+', encoding='utf-8') as log:
            server = subprocess.Popen([sys.executable, '-m', 'researchrelay.cli', 'serve', '--port', str(port)],
                                      cwd=workspace, env=environment, stdout=log, stderr=subprocess.STDOUT)
            try:
                with httpx.Client(base_url=server_url, timeout=10, trust_env=False) as client:
                    deadline = time.monotonic()+30
                    while True:
                        try:
                            client.get('/api/health').raise_for_status()
                            break
                        except httpx.HTTPError:
                            if server.poll() is not None or time.monotonic()>deadline:
                                raise RuntimeError('Coordinator did not become healthy')
                            time.sleep(.1)
                    for route in ('/', '/static/app.js', '/api/schemas/result', '/openapi.json'):
                        client.get(route).raise_for_status()
                    if args.browser:
                        subprocess.run([sys.executable, str(checkout/'scripts/ui_smoke.py'), '--url', server_url,
                                        '--screenshot', str(workspace/'dashboard.png')],
                                       cwd=workspace, env=environment, check=True, timeout=180)
                    else:
                        client.post('/api/pilot/run').raise_for_status()
                        deadline = time.monotonic()+120
                        while True:
                            response = client.get('/api/pilot/status')
                            response.raise_for_status()
                            job = response.json()
                            if job['status'] == 'completed':
                                break
                            if job['status'] in {'failed','interrupted'} or time.monotonic()>deadline:
                                raise RuntimeError(f'Pilot did not complete: {job}')
                            time.sleep(.25)
                        dashboard = client.get('/api/dashboard').json()
                        assert len(dashboard['tasks']) == 3
                        assert all(task['status']=='completed' for task in dashboard['tasks'])
                        synthesis = next(task for task in dashboard['tasks'] if task['id']=='synthesis')
                        assert synthesis['result_ref']['version'] == 2 and synthesis['revision_count'] == 1
                        assert len(dashboard['decisions']) == 1 and dashboard['decisions'][0]['status'] == 'open'
                        result = client.get('/api/artifacts/result-synthesis/markdown', params={'version':2})
                        result.raise_for_status()
                        assert 'schema_version:' in result.text
                        replay = client.post('/api/pilot/run')
                        replay.raise_for_status()
                        assert replay.json()['status'] == 'completed'
                print(json.dumps({'status':'passed','system':platform.system(),'machine':platform.machine(),
                                  'workflow':'browser' if args.browser else 'API pilot',
                                  'checks':['CLI startup','HTTP assets and schemas','parallel tasks','review/revision',
                                            'Git record','human decision']}))
            except BaseException:
                log.flush()
                log.seek(0)
                print(log.read(), file=sys.stderr)
                raise
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)


if __name__ == '__main__':
    main()
