"""Transactional coordination. SQLite is the sole authority for execution state."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import validate_artifact


def now():
    return datetime.now(timezone.utc).isoformat()


def dumps(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


class WorkflowError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class Engine:
    def __init__(self, db_path, project_id='forecast-pilot'):
        self.db_path = Path(db_path).expanduser()
        self.project_id = project_id
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS artifacts(id TEXT,version INTEGER,data TEXT NOT NULL,
                    PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT,task_id TEXT,detail TEXT,created_at TEXT);
                CREATE TABLE IF NOT EXISTS submissions(task_id TEXT,key TEXT,payload_hash TEXT,response TEXT,
                    PRIMARY KEY(task_id,key));
                CREATE TABLE IF NOT EXISTS attempts(task_id TEXT,attempt INTEGER,worker_id TEXT,
                    started_at TEXT,finished_at TEXT,outcome TEXT,PRIMARY KEY(task_id,attempt));
                CREATE TABLE IF NOT EXISTS reviews(task_id TEXT,result_version INTEGER,reviewer TEXT,
                    data TEXT,PRIMARY KEY(task_id,result_version,reviewer));
                CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS metrics(id INTEGER PRIMARY KEY AUTOINCREMENT,participant TEXT,
                    kind TEXT,value REAL,note TEXT,created_at TEXT);
                CREATE TABLE IF NOT EXISTS visits(participant TEXT PRIMARY KEY,seq INTEGER);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,status TEXT,data TEXT,updated_at TEXT);
            ''')
            row = db.execute("SELECT value FROM settings WHERE key='project_id'").fetchone()
            if row and row[0] != project_id:
                raise WorkflowError('Database belongs to a different project', 400)
            db.execute("INSERT OR IGNORE INTO settings VALUES('project_id',?)", (project_id,))

    def connect(self):
        db = sqlite3.connect(str(self.db_path), timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA busy_timeout=30000')
        return db

    @contextmanager
    def _tx(self):
        db = self.connect()
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _event(self, db, kind, task_id=None, detail=''):
        db.execute('INSERT INTO events(kind,task_id,detail,created_at) VALUES(?,?,?,?)',
                   (kind, task_id, detail if isinstance(detail, str) else dumps(detail), now()))

    def _task(self, db, task_id):
        row = db.execute('SELECT data FROM tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise WorkflowError(f'Task {task_id} not found', 404)
        return json.loads(row[0])

    def _save(self, db, task):
        task['updated_at'] = now()
        task['state_version'] = task.get('state_version', 0) + 1
        db.execute('UPDATE tasks SET data=? WHERE id=?', (dumps(task), task['id']))

    def _reap(self, db):
        for row in db.execute('SELECT data FROM tasks').fetchall():
            task = json.loads(row[0])
            if task['status'] == 'running' and task.get('lease_until', 0) <= time.time():
                task.update(status='queued' if task['attempts'] < task['max_attempts'] else 'failed',
                            claim_token=None, lease_until=None, blocker='Worker lease expired; prior attempt cannot submit.')
                db.execute('UPDATE attempts SET finished_at=?,outcome=? WHERE task_id=? AND attempt=?',
                           (now(), 'lease_expired', task['id'], task['attempts']))
                self._save(db, task)
                self._event(db, 'lease_expired', task['id'], task['blocker'])

    def _artifact(self, db, artifact_id, version=None):
        query = 'SELECT data FROM artifacts WHERE id=?'
        params = [artifact_id]
        if version is not None:
            query += ' AND version=?'
            params.append(version)
        query += ' ORDER BY version DESC LIMIT 1'
        row = db.execute(query, params).fetchone()
        if not row:
            raise WorkflowError(f'Artifact {artifact_id}@{version or "latest"} not found', 404)
        return json.loads(row[0])

    def _put_artifact(self, db, metadata, body=''):
        meta = validate_artifact(metadata, body)
        if meta['project_id'] != self.project_id:
            raise WorkflowError('Artifact project does not match this coordination store', 400)
        payload = dumps({'metadata': meta, 'body': body})
        digest = hashlib.sha256(payload.encode()).hexdigest()
        record = dict(id=meta['id'], version=meta['version'], artifact_type=meta['artifact_type'],
                      metadata=meta, body=body, sha256=digest)
        existing = db.execute('SELECT data FROM artifacts WHERE id=? AND version=?',
                              (meta['id'], meta['version'])).fetchone()
        if existing:
            previous = json.loads(existing[0])
            if previous['sha256'] != digest:
                raise WorkflowError(f'Immutable artifact conflict: {meta["id"]}@{meta["version"]}. Submit a new version.')
            return previous
        last = db.execute('SELECT MAX(version) FROM artifacts WHERE id=?', (meta['id'],)).fetchone()[0] or 0
        if meta['version'] != last + 1:
            raise WorkflowError(f'Expected artifact version {last + 1}; received {meta["version"]}')
        for ref in meta.get('input_refs', []):
            self._artifact(db, ref['id'], ref['version'])
        db.execute('INSERT INTO artifacts VALUES(?,?,?)', (meta['id'], meta['version'], dumps(record)))
        self._event(db, 'artifact_recorded', meta.get('task_id'), f'{meta["id"]}@{meta["version"]}')
        return record

    def put_artifact(self, metadata, body=''):
        with self._tx() as db:
            return self._put_artifact(db, metadata, body)

    def get_artifact(self, artifact_id, version=None):
        with self._tx() as db:
            return self._artifact(db, artifact_id, version)

    def list_artifacts(self, all_versions=True):
        with self._tx() as db:
            items = [json.loads(r[0]) for r in db.execute('SELECT data FROM artifacts ORDER BY id,version')]
            if all_versions:
                return items
            latest = {}
            for item in items:
                latest[item['id']] = item
            return list(latest.values())

    def _stale(self, db, task):
        stale = []
        for ref in task['input_refs']:
            current = self._artifact(db, ref['id'])
            if current['version'] != ref['version']:
                stale.append({'id': ref['id'], 'pinned': ref['version'], 'latest': current['version']})
        return stale

    def _decorate(self, db, task):
        task = dict(task)
        dependencies = [self._task(db, dep) for dep in task['dependencies']]
        # Include the exact reviewed outputs a new consumer would inherit before
        # declaring it ready. Direct repository edits can append newer revisions
        # while the upstream task retains its historical completion reference.
        # A human-reconciled explicit pin takes precedence over an upstream
        # task's historical completion reference; do not reintroduce old inputs.
        refs = {ref['id']: dict(ref) for ref in task['input_refs']}
        for dep in dependencies:
            if dep['status'] == 'completed' and dep.get('result_ref'):
                refs.setdefault(dep['result_ref']['id'], dict(dep['result_ref']))
        task['input_refs'] = [refs[artifact_id] for artifact_id in sorted(refs)]
        task['stale_inputs'] = self._stale(db, task)
        task['ready'] = task['status'] == 'queued' and not task['stale_inputs'] and all(
            dep['status'] == 'completed' for dep in dependencies)
        task['waiting_for'] = [dep['id'] for dep in dependencies if dep['status'] != 'completed']
        return task

    def get_task(self, task_id):
        with self._tx() as db:
            self._reap(db)
            return self._decorate(db, self._task(db, task_id))

    def list_tasks(self, owner=None, ready=False):
        with self._tx() as db:
            self._reap(db)
            tasks = [self._decorate(db, json.loads(r[0])) for r in db.execute('SELECT data FROM tasks')]
            return [t for t in tasks if (owner is None or t['owner'] == owner) and (not ready or t['ready'])]

    def _new_task(self, db, proposal):
        task_id = proposal.get('id') or f'task-{uuid.uuid4().hex[:12]}'
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', task_id) or '..' in task_id:
            raise WorkflowError('Task ID must be a safe stable identifier of at most 96 characters, without consecutive dots', 400)
        if db.execute('SELECT 1 FROM tasks WHERE id=?', (task_id,)).fetchone():
            raise WorkflowError(f'Task {task_id} already exists')
        if not isinstance(proposal.get('owner'), str) or not proposal['owner'].strip():
            raise WorkflowError('Approved task requires a responsible owner', 400)
        if proposal['owner'].strip().lower() == 'unassigned':
            raise WorkflowError('Assign a participant to each proposed task before approving scope', 400)
        criteria = proposal.get('acceptance_criteria', [])
        if not criteria:
            raise WorkflowError('Approved task requires acceptance criteria', 400)
        timestamp = now()
        task = dict(id=task_id, project_id=self.project_id, title=proposal.get('title', task_id),
                    owner=proposal['owner'], objective=proposal.get('objective', proposal.get('title', task_id)),
                    dependencies=proposal.get('dependencies', []), input_refs=proposal.get('input_refs', []),
                    expected_outputs=proposal.get('expected_outputs', []), acceptance_criteria=criteria,
                    status='queued', attempts=0, max_attempts=min(10, max(1, int(proposal.get('max_attempts', 5)))),
                    revision_count=0, max_revisions=2, claim_token=None, lease_until=None, progress='',
                    result_ref=None, blocker=None, completion_notes='', repository=[],
                    created_at=timestamp, updated_at=timestamp, state_version=1,
                    provenance=proposal.get('provenance', 'human_approved'))
        for ref in task['input_refs']:
            self._artifact(db, ref['id'], ref['version'])
        artifact = self._put_artifact(db, dict(id=f'task-{task_id}', project_id=self.project_id,
            artifact_type='task', owner=task['owner'], responsible_participant=task['owner'],
            producing_agent='coordination-service', objective=task['objective'], dependencies=task['dependencies'],
            input_refs=task['input_refs'], acceptance_criteria=criteria, expected_outputs=task['expected_outputs']),
            f'# {task["title"]}\n\nApproved scope: {task["objective"]}\n\nOwner: {task["owner"]}\n')
        task['definition_ref'] = {'id': artifact['id'], 'version': artifact['version']}
        db.execute('INSERT INTO tasks VALUES(?,?)', (task_id, dumps(task)))
        self._event(db, 'task_queued', task_id, f'Approved scope assigned to {task["owner"]}')
        return task

    def _check_dag(self, db):
        tasks = {r['id']: json.loads(r['data']) for r in db.execute('SELECT * FROM tasks')}
        visiting, visited = set(), set()
        def visit(task_id):
            if task_id not in tasks:
                raise WorkflowError(f'Unknown dependency: {task_id}', 400)
            if task_id in visiting:
                raise WorkflowError(f'Dependency cycle at {task_id}', 400)
            if task_id in visited:
                return
            visiting.add(task_id)
            for dep in tasks[task_id]['dependencies']:
                visit(dep)
            visiting.remove(task_id)
            visited.add(task_id)
        for task_id in tasks:
            visit(task_id)

    def create_task(self, **proposal):
        with self._tx() as db:
            task = self._new_task(db, proposal)
            self._check_dag(db)
            return task

    def create_meeting(self, notes, participant='human'):
        from .meetings import extract_meeting
        if not notes.strip() or len(notes) > 200_000:
            raise WorkflowError('Meeting notes must contain 1–200,000 characters', 400)
        result = extract_meeting(notes, participant, self.project_id)
        with self._tx() as db:
            try:
                artifact = self._artifact(db, result['metadata']['id'])
            except WorkflowError as error:
                if error.status != 404:
                    raise
                artifact = self._put_artifact(db, result['metadata'], result['body'])
        # Stable note IDs make repeated browser requests idempotent. Preserve the
        # first record's timestamps/attribution instead of conflicting on defaults.
        return {**result, 'metadata': artifact['metadata'], 'body': artifact['body'],
                'id': artifact['id'], 'artifact': artifact}

    def approve_meeting(self, meeting_id, tasks):
        with self._tx() as db:
            meeting = self._artifact(db, meeting_id)
            if meeting['artifact_type'] != 'meeting':
                raise WorkflowError('Expected meeting artifact', 400)
            key = f'approved:{meeting_id}'
            if db.execute('SELECT 1 FROM settings WHERE key=?', (key,)).fetchone():
                raise WorkflowError('Meeting scope already approved; create a follow-up meeting to change scope')
            created = [self._new_task(db, proposal) for proposal in tasks]
            self._check_dag(db)
            db.execute('INSERT INTO settings VALUES(?,?)', (key, dumps([t['id'] for t in created])))
            self._event(db, 'scope_approved', detail=f'{len(created)} tasks from {meeting_id}')
            return created

    def _valid_claim(self, task, token):
        if task['status'] != 'running' or not token or task['claim_token'] != token:
            raise WorkflowError('Task claim is no longer valid; retrieve state and claim a ready task')
        if task['lease_until'] <= time.time():
            raise WorkflowError('Claim expired; prior worker must not submit')

    def claim_task(self, task_id, worker_id, lease_seconds=120):
        if not worker_id:
            raise WorkflowError('worker_id is required', 400)
        with self._tx() as db:
            self._reap(db)
            task = self._task(db, task_id)
            decorated = self._decorate(db, task)
            if not decorated['ready']:
                explanation = f'Task cannot run: status={task["status"]}; waiting={decorated["waiting_for"]}; stale={decorated["stale_inputs"]}'
                if decorated['stale_inputs']:
                    explanation += f'. Ask the human coordinator to review changed inputs and POST /api/tasks/{task_id}/retry with explicitly reconciled input_refs.'
                raise WorkflowError(explanation)
            if task['attempts'] >= task['max_attempts']:
                raise WorkflowError('Attempt budget exhausted')
            task['input_refs'] = decorated['input_refs']
            task.update(status='running', attempts=task['attempts'] + 1,
                        claim_token=uuid.uuid4().hex, worker_id=worker_id,
                        lease_until=time.time() + min(3600, max(1, lease_seconds)),
                        blocker=None, progress='Claimed by worker')
            db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?)',
                       (task_id, task['attempts'], worker_id, now(), None, 'running'))
            self._save(db, task)
            self._event(db, 'task_claimed', task_id, f'{worker_id}; attempt {task["attempts"]}')
            return task

    def heartbeat(self, task_id, claim_token, progress='', lease_seconds=120):
        with self._tx() as db:
            self._reap(db)
            task = self._task(db, task_id)
            self._valid_claim(task, claim_token)
            task.update(lease_until=time.time() + min(3600, max(1, lease_seconds)), progress=progress[:2000])
            self._save(db, task)
            return task

    def submit_result(self, task_id, claim_token, idempotency_key, artifact, completion_notes=''):
        if not idempotency_key or len(idempotency_key) > 200:
            raise WorkflowError('A stable idempotency_key of 1–200 characters is required', 400)
        payload_hash = hashlib.sha256(dumps(dict(artifact=artifact, completion_notes=completion_notes)).encode()).hexdigest()
        with self._tx() as db:
            previous = db.execute('SELECT * FROM submissions WHERE task_id=? AND key=?', (task_id,idempotency_key)).fetchone()
            if previous:
                if previous['payload_hash'] != payload_hash:
                    raise WorkflowError('Idempotency key reused with different content')
                return json.loads(previous['response'])
            self._reap(db)
            task = self._task(db, task_id)
            self._valid_claim(task, claim_token)
            stale = self._stale(db, task)
            if stale:
                raise WorkflowError(f'Inputs changed while work ran: {dumps(stale)}. Block the task and ask a human to rebase its inputs.')
            metadata = dict(artifact.get('metadata', {}))
            if metadata.get('artifact_type') != 'result' or metadata.get('task_id') != task_id:
                raise WorkflowError('Submission must be a result artifact for this task', 400)
            expected_version = task['result_ref']['version'] + 1 if task['result_ref'] else 1
            if metadata.get('version', 1) != expected_version:
                raise WorkflowError(f'Result must use version {expected_version}')
            if task['result_ref'] and metadata.get('id') != task['result_ref']['id']:
                raise WorkflowError('Revisions must retain the original result ID')
            metadata['input_refs'] = task['input_refs']
            metadata['responsible_participant'] = task['owner']
            result = self._put_artifact(db, metadata, artifact.get('body', ''))
            task.update(status='awaiting_review', result_ref={'id': result['id'], 'version': result['version']},
                        completion_notes=completion_notes, progress='Computation complete; agent review pending',
                        claim_token=None, lease_until=None, completed_computation_at=now())
            self._save(db, task)
            db.execute('UPDATE attempts SET finished_at=?,outcome=? WHERE task_id=? AND attempt=?',
                       (now(), 'submitted', task_id, task['attempts']))
            self._event(db, 'result_submitted', task_id, f'{result["id"]}@{result["version"]}: {completion_notes}')
            response = dict(task=task, result=result, result_ref=task['result_ref'], status=task['status'])
            db.execute('INSERT INTO submissions VALUES(?,?,?,?)', (task_id,idempotency_key,payload_hash,dumps(response)))
            return response

    def review_task(self, task_id, reviewer, verdict, rationale, criteria, result_version):
        if verdict not in {'approve', 'revise'} or not rationale.strip() or not criteria:
            raise WorkflowError('Review requires approve/revise, rationale, and acceptance-criteria evidence', 400)
        with self._tx() as db:
            task = self._task(db, task_id)
            if reviewer == task['owner']:
                raise WorkflowError('A different participant must review this result', 400)
            if task['status'] != 'awaiting_review' or not task['result_ref'] or task['result_ref']['version'] != result_version:
                raise WorkflowError('Review is stale or task is not awaiting review')
            if db.execute('SELECT 1 FROM reviews WHERE task_id=? AND result_version=? AND reviewer=?',
                          (task_id,result_version,reviewer)).fetchone():
                raise WorkflowError('Reviewer has already reviewed this result version')
            review_id = f'review-{task_id}-{result_version}-{uuid.uuid4().hex[:8]}'
            record = self._put_artifact(db, dict(id=review_id, project_id=self.project_id, artifact_type='review',
                task_id=task_id, responsible_participant=reviewer, producing_agent=reviewer,
                result_ref=task['result_ref'], verdict=verdict, rationale=rationale,
                input_refs=[task['result_ref']], acceptance_criteria=task['acceptance_criteria'],
                validation_results=criteria, objective='Critique the result against approved acceptance criteria'),
                f'# Review of {task_id}@{result_version}\n\n{rationale}\n\n' + '\n'.join(f'- {c}' for c in criteria))
            db.execute('INSERT INTO reviews VALUES(?,?,?,?)', (task_id,result_version,reviewer,dumps(record)))
            if verdict == 'approve':
                task.update(status='completed', progress='Computation complete; agent review approved', reviewed_at=now(), blocker=None)
            else:
                task['revision_count'] += 1
                exhausted = task['revision_count'] > task['max_revisions'] or task['attempts'] >= task['max_attempts']
                task.update(status='blocked' if exhausted else 'queued', progress='Revision requested',
                            blocker=f'Reviewer {reviewer}: {rationale}', review_feedback=rationale)
                if exhausted:
                    self._request_decision(db, 'Review cycle limit reached. How should this disagreement be resolved?',
                        [rationale, f'Result: {task["result_ref"]}'], ['Revise approved scope', 'Accept with documented limitations', 'Cancel task'],
                        'Dependent tasks remain gated until the disagreement is resolved.', 'human', task_id)
            self._save(db, task)
            self._event(db, 'review_approved' if verdict == 'approve' else 'revision_requested', task_id, rationale)
            return dict(task=task, review=record)

    def block_task(self, task_id, claim_token, reason, question=None, options=None, evidence=None, consequence=None):
        with self._tx() as db:
            task = self._task(db, task_id)
            self._valid_claim(task, claim_token)
            task.update(status='blocked', blocker=reason, progress='Blocked', claim_token=None, lease_until=None)
            self._save(db, task)
            db.execute('UPDATE attempts SET finished_at=?,outcome=? WHERE task_id=? AND attempt=?',
                       (now(),'blocked',task_id,task['attempts']))
            self._event(db, 'task_blocked', task_id, reason)
            if question:
                self._request_decision(db, question, evidence or [reason], options or ['Clarify scope','Cancel task'],
                    consequence or 'This task and dependent work are waiting.', 'human', task_id)
            return task

    def cancel_task(self, task_id):
        with self._tx() as db:
            task = self._task(db, task_id)
            if task['status'] == 'completed':
                raise WorkflowError('Completed tasks remain in the record; create a follow-up task')
            task.update(status='canceled', claim_token=None, lease_until=None, progress='Canceled by coordinator')
            self._save(db, task)
            db.execute("UPDATE attempts SET finished_at=?,outcome='canceled' WHERE task_id=? AND outcome='running'",(now(),task_id))
            self._event(db, 'task_canceled', task_id)
            return task

    def retry_task(self, task_id, input_refs=None):
        with self._tx() as db:
            task = self._task(db, task_id)
            queued_reconciliation = (task['status'] == 'queued' and input_refs is not None
                                     and bool(self._decorate(db, task)['stale_inputs']))
            if task['status'] not in {'blocked', 'failed'} and not queued_reconciliation:
                raise WorkflowError('Only blocked or failed tasks can be retried; queued stale tasks require explicitly reconciled input_refs')
            if task['attempts'] >= task['max_attempts'] or task['revision_count'] > task['max_revisions']:
                raise WorkflowError('Attempt/review budget exhausted; approve a follow-up task with revised scope')
            if input_refs is not None:
                for ref in input_refs:
                    self._artifact(db, ref['id'], ref['version'])
                task['input_refs'] = input_refs
            if self._decorate(db, task)['stale_inputs']:
                raise WorkflowError('Supply explicitly reconciled input_refs to retry stale work')
            task.update(status='queued', blocker=None, progress='Retry authorized')
            self._save(db, task)
            self._event(db, 'task_retried', task_id, 'Human authorized retry/reconciled inputs')
            return task

    def _request_decision(self, db, question, evidence, options, consequence, participant='human', task_id=None):
        decision_id = f'decision-{uuid.uuid4().hex[:12]}'
        decision = dict(id=decision_id,question=question,evidence=evidence,options=options,consequence=consequence,
                        participant=participant,task_id=task_id,status='open',created_at=now())
        artifact = self._put_artifact(db, dict(id=decision_id, project_id=self.project_id, artifact_type='decision',
            responsible_participant=participant, producing_agent='coordination-service', question=question,
            evidence=evidence, options=options, consequence=consequence, status='open'),
            f'# Human scientific decision\n\n{question}\n\nConsequence: {consequence}\n')
        decision['artifact_ref'] = {'id':artifact['id'], 'version':artifact['version']}
        db.execute('INSERT INTO decisions VALUES(?,?)',(decision_id,dumps(decision)))
        self._event(db,'decision_requested',task_id,question)
        return decision

    def request_decision(self, question, evidence, options, consequence, participant='human', task_id=None):
        with self._tx() as db:
            return self._request_decision(db,question,evidence,options,consequence,participant,task_id)

    def resolve_decision(self, decision_id, participant, choice, rationale):
        if not rationale.strip():
            raise WorkflowError('Record the scientific rationale for this decision', 400)
        with self._tx() as db:
            row = db.execute('SELECT data FROM decisions WHERE id=?',(decision_id,)).fetchone()
            if not row:
                raise WorkflowError('Decision not found',404)
            decision = json.loads(row[0])
            if decision['status'] != 'open':
                raise WorkflowError('Decision is already resolved')
            if choice not in decision['options']:
                raise WorkflowError('Choose a recorded option',400)
            decision.update(status='resolved',choice=choice,rationale=rationale,resolved_by=participant,resolved_at=now())
            previous = self._artifact(db,decision_id)
            meta = {**previous['metadata'],'version':previous['version']+1,'updated_at':now(),
                    'status':'resolved','choice':choice,'rationale':rationale,'responsible_participant':participant}
            artifact = self._put_artifact(db,meta,previous['body']+f'\nDecision: {choice}\n\nRationale: {rationale}\n')
            decision['artifact_ref'] = {'id':artifact['id'],'version':artifact['version']}
            db.execute('UPDATE decisions SET data=? WHERE id=?',(dumps(decision),decision_id))
            self._event(db,'decision_resolved',decision.get('task_id'),f'{choice}: {rationale}')
            return decision

    def add_metric(self, participant, kind, value, note=''):
        allowed = {'coordination_minutes','clarification_requests','task_completion_seconds','review_cycles','rework',
                   'unresolved_blockers','understanding','attention_clarity','assessment','assessment_clarity',
                   'human_coordination_minutes','pilot_elapsed_seconds','participant_assessment'}
        if kind not in allowed:
            raise WorkflowError(f'Unknown pilot measure {kind}',400)
        if not isinstance(value,(int,float)) or not 0 <= value < 1e9:
            raise WorkflowError('Measure value must be nonnegative and bounded',400)
        if kind == 'assessment_clarity' and not 1 <= value <= 5:
            raise WorkflowError('Participant clarity assessment must be between 1 and 5',400)
        with self._tx() as db:
            db.execute('INSERT INTO metrics(participant,kind,value,note,created_at) VALUES(?,?,?,?,?)',
                       (participant,kind,value,note,now()))
            return {'participant':participant,'kind':kind,'value':value,'note':note}

    def record_repository(self, task_id, branch, commit, pr=None, detail=''):
        with self._tx() as db:
            if task_id:
                task = self._task(db,task_id)
                link = dict(branch=branch,commit=commit,pull_request=pr,detail=detail)
                if link not in task['repository']:
                    task['repository'].append(link)
                    self._save(db,task)
            self._event(db,'repository_updated',task_id,dict(branch=branch,commit=commit,pull_request=pr,detail=detail))

    def dashboard(self, participant='human', since=0):
        with self._tx() as db:
            self._reap(db)
            tasks = [self._decorate(db,json.loads(r[0])) for r in db.execute('SELECT data FROM tasks')]
            # Never expose active bearer capabilities in dashboard/status snapshots.
            for task in tasks:
                task.pop('claim_token',None)
            events = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY seq DESC LIMIT 150')]
            latest = events[0]['seq'] if events else 0
            previous = db.execute('SELECT seq FROM visits WHERE participant=?',(participant,)).fetchone()
            cursor = int(since) if since else previous[0] if previous else 0
            changes = [event for event in events if event['seq'] > cursor]
            db.execute('INSERT OR REPLACE INTO visits VALUES(?,?)',(participant,latest))
            artifacts = {}
            for row in db.execute('SELECT data FROM artifacts ORDER BY id,version'):
                art = json.loads(row[0])
                artifacts[art['id']] = art
            metrics = [dict(r) for r in db.execute('SELECT * FROM metrics ORDER BY id')]
            return dict(project_id=self.project_id,mode='demo',tasks=tasks,artifacts=list(artifacts.values()),
                        decisions=[json.loads(r[0]) for r in db.execute('SELECT data FROM decisions')],
                        events=events,metrics=metrics,metric_summary={k:sum(m['value'] for m in metrics if m['kind']==k)
                            for k in {m['kind'] for m in metrics}},latest_seq=latest,changes_since_last_visit=changes,
                        jobs=[dict(r) for r in db.execute('SELECT * FROM jobs')])

    def start_job(self, job_id='pilot'):
        with self._tx() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if row and row['status'] in {'running','completed'}:
                return dict(row),False
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?)',(job_id,'running','{}',now()))
            return dict(id=job_id,status='running',data='{}'),True

    def finish_job(self, job_id, status, data):
        with self._tx() as db:
            db.execute('UPDATE jobs SET status=?,data=?,updated_at=? WHERE id=?',(status,dumps(data),now(),job_id))

    def job_status(self, job_id='pilot'):
        with self._tx() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            return dict(row) if row else dict(id=job_id,status='not_started',data='{}')

    def recover_jobs(self):
        with self._tx() as db:
            db.execute("UPDATE jobs SET status='interrupted',data=?,updated_at=? WHERE status='running'",
                       (dumps({'message':'Service restarted. Worker claims recover by lease expiry; rerun pilot to resume.'}),now()))
