'use strict';

const $ = (id) => document.getElementById(id);
const state = { dashboard: null, filter: 'all', search: '', meeting: null, pollBusy: false,
  seen: Number(localStorage.getItem('researchrelay:last-seen') || 0), pilotBusy: false };
let toastTimer;

function node(tag, attrs = {}, children = []) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null) continue;
    if (key === 'text') element.textContent = String(value);
    else if (key === 'class') element.className = value;
    else if (key.startsWith('on')) element.addEventListener(key.slice(2), value);
    else if (key === 'checked') element.checked = Boolean(value);
    else if (key === 'value') element.value = value;
    else element.setAttribute(key, String(value));
  }
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child != null) element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}
function clear(element, children = []) { element.replaceChildren(...children); }
function asText(value) {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}
function lines(value) { return Array.isArray(value) ? value.map(asText).join('\n') : asText(value); }
function lineArray(value) { return String(value).split('\n').map(x => x.trim()).filter(Boolean); }
function cap(value) { return String(value || '').replaceAll('_', ' ').replace(/\b\w/g, c => c.toUpperCase()); }
function timeAgo(value) {
  if (!value) return 'Just now';
  let text = String(value);
  if (!/[zZ]$|[+-]\d\d:\d\d$/.test(text)) text += 'Z';
  const date = new Date(text);
  const elapsed = Math.max(0, (Date.now() - date.getTime()) / 1000);
  if (!Number.isFinite(elapsed)) return String(value);
  if (elapsed < 60) return 'Just now';
  if (elapsed < 3600) return `${Math.floor(elapsed / 60)} min ago`;
  if (elapsed < 86400) return `${Math.floor(elapsed / 3600)} hr ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').className = `toast${error ? ' error' : ''}`;
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, error ? 8000 : 4500);
}
function notice(message, error = false) {
  $('notice').hidden = !message;
  $('notice').textContent = message;
  $('notice').className = `notice${error ? ' error' : ''}`;
}
async function api(path, method = 'GET', data) {
  const headers = { Accept: 'application/json' };
  const token = sessionStorage.getItem('researchrelay:token');
  if (token) headers.Authorization = `Bearer ${token}`;
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(`/api${path}`, { method, headers, body: data === undefined ? undefined : JSON.stringify(data) });
  if (!response.ok) {
    let detail;
    try { const body = await response.json(); detail = asText(body.detail || body.message || body); }
    catch { detail = response.statusText; }
    if (response.status === 401) throw new Error('A project access token is required. Select Access in the top bar.');
    throw new Error(detail || `Request failed (${response.status})`);
  }
  const type = response.headers.get('content-type') || '';
  return type.includes('application/json') ? response.json() : response.text();
}
async function action(button, callback) {
  if (button.disabled) return;
  button.disabled = true;
  try { await callback(); }
  catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}
function avatar(name) { return node('span', { class: `avatar ${name === 'bob' ? 'bob' : name === 'carol' ? 'carol' : ''}`, text: (name || '?').slice(0, 2).toUpperCase() }); }
function badge(status) { return node('span', { class: `status-badge ${status}`, text: cap(status) }); }
function empty(title, detail) { return node('div', { class: 'empty-state' }, [node('strong', { text: title }), detail]); }
function latestSequence(data) { return Number(data.latest_seq || Math.max(0, ...(data.events || []).map(event => Number(event.seq) || 0))); }
function metricTotal(kind) {
  const metrics = state.dashboard?.metrics || [];
  if (!Array.isArray(metrics)) return Number(metrics[kind] || 0);
  return metrics.filter(metric => metric.kind === kind).reduce((total, metric) => total + (Number(metric.value) || 0), 0);
}

async function refresh(silent = false) {
  if (state.pollBusy) return;
  state.pollBusy = true;
  try {
    const data = await api(`/dashboard?participant=human&since=${state.seen}`);
    state.dashboard = data;
    render(data);
    $('connection-status').textContent = 'All changes saved';
    if (!silent) notice('');
  } catch (error) {
    $('connection-status').textContent = 'Connection interrupted';
    if (!silent || !state.dashboard) notice(error.message, true);
  } finally { state.pollBusy = false; }
}
function render(data) {
  const tasks = data.tasks || [];
  const completed = tasks.filter(task => task.status === 'completed').length;
  const awaiting = tasks.filter(task => task.status === 'awaiting_review').length;
  const openDecisions = (data.decisions || []).filter(decision => !['resolved', 'completed', 'canceled'].includes(decision.status));
  const blocked = tasks.filter(task => ['blocked', 'failed'].includes(task.status)).length;
  clear($('stat-completed'), [document.createTextNode(`${completed} `), node('small', { text: `/ ${tasks.length}` })]);
  $('stat-review').textContent = awaiting;
  $('stat-attention').textContent = openDecisions.length + blocked;
  const minutes = metricTotal('coordination_minutes');
  clear($('stat-time'), [document.createTextNode(`${minutes ? minutes.toFixed(1).replace('.0', '') : '—'} `), node('small', { text: 'min' })]);
  $('work-count').textContent = tasks.length;
  $('nav-task-count').textContent = tasks.length;
  renderDecisions(openDecisions);
  renderTasks();
  renderArtifacts(data.artifacts || []);
  renderActivity(data.events || []);
  // Keep the catch-up stable across polls until the participant acknowledges it.
  const newEvents = (data.events || []).filter(event => Number(event.seq) > state.seen);
  const newResults = newEvents.filter(event => /submit|result|complet/.test(event.kind || '')).length;
  const newReviews = newEvents.filter(event => /review/.test(event.kind || '')).length;
  $('catchup-text').textContent = newEvents.length
    ? `${newEvents.length} recorded updates${newResults ? `, including ${newResults} result or completion update${newResults === 1 ? '' : 's'}` : ''}${newReviews ? ` and ${newReviews} review update${newReviews === 1 ? '' : 's'}` : ''}. ${openDecisions.length ? `${openDecisions.length} scientific decision${openDecisions.length === 1 ? '' : 's'} need your judgment.` : 'No unresolved scientific decisions.'}`
    : 'You’re up to date. New results, reviews, and decisions will appear here.';
  const jobs = Array.isArray(data.jobs) ? data.jobs : [];
  state.pilotBusy = jobs.some(job => ['running', 'queued'].includes(job.status));
  $('pilot-button').disabled = state.pilotBusy;
  const completeJob = jobs.find(job => job.id === 'pilot' && job.status === 'completed');
  $('pilot-button').replaceChildren(node('span', { text: state.pilotBusy ? '◷' : completeJob ? '✓' : '▷' }), document.createTextNode(state.pilotBusy ? 'Pilot in progress…' : completeJob ? 'View pilot summary' : 'Run local pilot'));
  const failedJob = jobs.find(job => job.status === 'failed');
  if (completeJob && $('notice').textContent.startsWith('Local demonstration running:')) {
    notice('Local pilot complete: the reviewed evidence and a scientific decision are ready. Live Claude and GitHub were not used.');
  }
  if (failedJob) {
    let detail = failedJob.data;
    try { detail = typeof detail === 'string' ? JSON.parse(detail) : detail; } catch { /* Show the original detail. */ }
    notice(`Pilot needs attention: ${asText(failedJob.error || detail?.error || failedJob.detail || 'Inspect the server log and retry.')}`, true);
  }
  const localMode = data.mode || 'local demo';
  $('footer-state').textContent = `${cap(localMode)} · SQLite is the authoritative workflow record.`;
  const isDemo = ['demo', 'local demo', 'local_demo'].includes(localMode);
  $('pilot-button').hidden = !isDemo;
  clear(document.querySelector('.local-badge'), [node('span', { class: 'live-dot' }), isDemo ? 'LOCAL DEMO' : 'PROJECT SERVICE']);
}

function renderDecisions(decisions) {
  if (!decisions.length) {
    const complete = state.dashboard?.tasks?.some(task => task.status === 'completed');
    clear($('decision-section'), [node('div', { class: 'decision-empty' }, [node('span', { class: 'empty-icon', text: '◇' }), node('div', {}, [node('h2', { text: complete ? 'The next move belongs to the science.' : 'A shared record. A clearer next step.' }), node('p', { text: complete ? 'No open human decisions. Review the evidence and record what the team should do next.' : 'Run the forecast pilot or turn your meeting notes into an agreed scope of work.' })])])]);
    return;
  }
  clear($('decision-section'), decisions.map((decision, index) => {
    const options = Array.isArray(decision.options) ? decision.options : [];
    const choice = node('select', { 'aria-label': 'Scientific decision choice' }, options.map(option => {
      const label = typeof option === 'string' ? option : (option.label || option.title || option.value || asText(option));
      return node('option', { value: label, text: label });
    }));
    if (!options.length) choice.append(node('option', { value: 'Proceed after team discussion', text: 'Proceed after team discussion' }));
    const rationale = node('input', { placeholder: 'Your scientific rationale…', 'aria-label': 'Scientific rationale', required: 'required' });
    const button = node('button', { class: 'button', type: 'submit', text: 'Record scientific decision →' });
    const evidence = Array.isArray(decision.evidence) ? decision.evidence : [decision.evidence].filter(Boolean);
    const evidenceNodes = evidence.slice(0, 4).map(item => {
      const text = typeof item === 'string' ? item : (item.summary || item.id || asText(item));
      return node('span', { class: 'evidence-chip', text: text.replace(/-?\d+\.\d{5,}/g, value => Number(value).toFixed(4)) });
    });
    const optionsForm = node('form', { class: 'decision-options', onsubmit: event => {
      event.preventDefault();
      action(button, async () => {
        await api(`/decisions/${encodeURIComponent(decision.id)}/resolve`, 'POST', { participant: 'human', choice: choice.value, rationale: rationale.value.trim() });
        toast('Scientific judgment recorded in the project record.');
        await refresh();
      });
    } }, [node('label', { text: 'RECORD YOUR JUDGMENT' }), choice, rationale, button, node('p', { class: 'consequence', text: `Next: ${asText(decision.consequence || 'Your choice directs subsequent work.')}` })]);
    return node('article', { class: 'decision-card' }, [node('div', {}, [node('div', { class: 'eyebrow' }, [node('span', { class: 'live-dot' }), `HUMAN SCIENTIFIC JUDGMENT · ${String(index + 1).padStart(2, '0')}`]), node('h2', { text: decision.question || decision.title || 'A scientific decision is needed' }), node('p', { text: asText(decision.context || decision.summary || 'Review the evidence and consequences before directing the next step.') }), node('div', { class: 'evidence-tags' }, evidenceNodes)]), optionsForm]);
  }));
}

function renderTasks() {
  let tasks = state.dashboard?.tasks || [];
  if (state.filter === 'attention') tasks = tasks.filter(task => ['blocked', 'failed', 'awaiting_review'].includes(task.status) || task.stale_inputs?.length);
  if (state.filter === 'completed') tasks = tasks.filter(task => task.status === 'completed');
  if (state.search) tasks = tasks.filter(task => `${task.title} ${task.owner} ${task.id} ${task.objective}`.toLowerCase().includes(state.search));
  if (!tasks.length) {
    clear($('task-list'), [empty(state.dashboard?.tasks?.length ? 'No tasks match this view.' : 'The first handoff starts here.', state.dashboard?.tasks?.length ? 'Try another filter or search.' : 'Add meeting notes, review the proposed scope, and let your agents take it from there.')]);
    return;
  }
  const symbols = { queued: '◷', running: '↗', blocked: '!', awaiting_review: '◎', completed: '✓', failed: '!', canceled: '−' };
  clear($('task-list'), tasks.map(task => {
    const computingDone = ['awaiting_review', 'completed'].includes(task.status);
    const reviewed = task.status === 'completed';
    const meta = [node('span', { class: 'owner-chip' }, [avatar(task.owner), cap(task.owner || 'Unassigned')]), node('span', { class: 'meta-divider', text: '·' }), node('span', { text: `${task.attempts || 0} attempt${Number(task.attempts) === 1 ? '' : 's'}` })];
    (task.dependencies || []).forEach(dependency => meta.push(node('span', { class: 'dependency-chip', text: `↳ ${dependency}` })));
    if (task.stale_inputs?.length) meta.push(node('span', { class: 'status-badge blocked', text: 'Input changed' }));
    if (task.status === 'queued' && task.ready === false) meta.push(node('span', { class: 'dependency-chip', text: 'Waiting on dependencies' }));
    if (task.revision_count) meta.push(node('span', { class: 'dependency-chip', text: `${task.revision_count} revision${task.revision_count === 1 ? '' : 's'}` }));
    const body = node('div', { class: 'task-body' }, [node('div', { class: 'task-title-line' }, [node('span', { class: 'task-title', text: task.title || task.id }), badge(task.status)]), node('p', { class: 'task-objective', text: task.blocker || task.objective || 'Defined in the agreed meeting scope.' }), node('div', { class: 'task-meta' }, meta), node('div', { class: 'review-stage' }, [node('span', { class: computingDone ? 'done' : '', text: `${computingDone ? '✓' : '○'} Computation` }), node('span', { class: reviewed ? 'done' : '', text: `${reviewed ? '✓' : '○'} Agent review` }), node('span', { text: '◇ Human judgment remains separate' })])]);
    if (task.status === 'running') {
      const progress = typeof task.progress === 'number' ? task.progress : 20;
      body.append(node('div', { class: 'progress-track', 'aria-label': `Progress ${progress}%` }, [node('div', { style: `width:${Math.max(0, Math.min(100, progress))}%` })]));
    }
    return node('article', { class: 'task', tabindex: '0', role: 'button', 'aria-label': `Open ${task.title || task.id}`, onclick: () => showTask(task), onkeydown: event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); showTask(task); } } }, [node('div', { class: 'task-head' }, [node('span', { class: `task-state-icon ${task.status}`, text: symbols[task.status] || '○' }), body])]);
  }));
}
function renderArtifacts(artifacts) {
  const sorted = [...artifacts].sort((a, b) => (b.metadata?.updated_at || b.created_at || '').localeCompare(a.metadata?.updated_at || a.created_at || ''));
  if (!sorted.length) { clear($('artifact-list'), [empty('Evidence will live here.', 'Every handoff becomes a readable, versioned artifact.')]); return; }
  clear($('artifact-list'), sorted.slice(0, 14).map(artifact => {
    const metadata = artifact.metadata || artifact;
    const id = artifact.id || metadata.id;
    const version = artifact.version || metadata.version || 1;
    return node('div', { class: 'artifact-row' }, [node('span', { class: 'artifact-icon', text: { meeting: '▤', task: '☷', result: '⌁', review: '◎', decision: '◇' }[metadata.artifact_type || artifact.artifact_type] || '▤' }), node('div', { class: 'artifact-main' }, [node('button', { text: metadata.title || metadata.objective || id, onclick: () => showArtifact(id, version) }), node('div', { class: 'artifact-meta', text: `${cap(metadata.artifact_type || artifact.artifact_type)} · ${cap(metadata.producing_agent || metadata.responsible_participant || 'Shared record')} · ${timeAgo(metadata.updated_at || metadata.created_at)}` })]), node('span', { class: 'artifact-version', text: `v${version}` }), node('button', { class: 'text-button download-link', text: '↓', title: 'Download Markdown', 'aria-label': `Download ${id} Markdown`, onclick: () => downloadArtifact(id, version) })]);
  }));
}
function eventDescription(event) {
  let detail = event.detail;
  if (typeof detail === 'string' && detail.startsWith('{')) {
    try { detail = JSON.parse(detail); } catch { /* Ordinary event text. */ }
  }
  if (typeof detail === 'string' && detail.length < 170) return detail;
  if (detail && typeof detail === 'object') return detail.message || detail.rationale || detail.reason || detail.title || `${cap(event.kind)}${event.task_id ? ` · ${event.task_id}` : ''}`;
  return `${cap(event.kind)}${event.task_id ? ` · ${event.task_id}` : ''}`;
}
function renderActivity(events) {
  if (!events.length) { clear($('activity-list'), [empty('Ready for the first update.', 'Claims, results, reviews, and decisions are recorded as they happen.')]); return; }
  clear($('activity-list'), [...events].sort((a, b) => Number(b.seq) - Number(a.seq)).slice(0, 9).map(event => node('article', { class: 'activity-item' }, [node('span', { class: 'avatar', text: /review/.test(event.kind || '') ? '◎' : /decision/.test(event.kind || '') ? '◇' : /complet|submit/.test(event.kind || '') ? '✓' : '↗' }), node('div', { class: 'activity-item-content' }, [node('p', { text: eventDescription(event) }), node('time', { text: timeAgo(event.created_at), title: event.created_at || '' })])])));
}

function detailField(title, value) {
  if (value == null || value === '' || (Array.isArray(value) && !value.length)) return null;
  const content = Array.isArray(value) ? node('ul', {}, value.map(item => node('li', { text: asText(item) }))) : node('p', { text: asText(value) });
  return node('section', { class: 'detail-field' }, [node('h4', { text: title }), content]);
}
function openDetail(title, eyebrow, content) {
  $('detail-title').textContent = title;
  $('detail-eyebrow').textContent = eyebrow;
  clear($('detail-content'), content.filter(Boolean));
  if (!$('detail-dialog').open) $('detail-dialog').showModal();
}
function showTask(task) {
  const content = [node('div', { class: 'detail-meta' }, [badge(task.status), node('span', { class: 'status-badge', text: `Owner: ${cap(task.owner)}` }), node('span', { class: 'status-badge', text: `${task.attempts || 0}/${task.max_attempts || 3} attempts` })]), detailField('Objective', task.objective), detailField('Acceptance criteria', task.acceptance_criteria), detailField('Expected outputs', task.expected_outputs), detailField('Dependencies', task.dependencies), detailField('Blocker', task.blocker), detailField('Completion notes', task.completion_notes)];
  if (task.stale_inputs?.length) content.push(reconciliationForm(task));
  if (task.input_refs?.length) content.push(node('section', { class: 'detail-field' }, [node('h4', { text: 'Pinned input artifacts' }), node('div', { class: 'detail-buttons' }, task.input_refs.map(ref => node('button', { class: 'button secondary', text: `${ref.id} · v${ref.version}`, onclick: () => showArtifact(ref.id, ref.version) })))]));
  const buttons = [];
  if (task.result_ref?.id) buttons.push(node('button', { class: 'button secondary', text: `View result · v${task.result_ref.version}`, onclick: () => showArtifact(task.result_ref.id, task.result_ref.version) }));
  if (!['completed', 'canceled'].includes(task.status)) buttons.push(node('button', { class: 'button danger', text: 'Cancel task', onclick: event => action(event.currentTarget, async () => { await api(`/tasks/${encodeURIComponent(task.id)}/cancel`, 'POST', {}); $('detail-dialog').close(); toast('Task canceled. Outstanding claims can no longer submit.'); await refresh(); }) }));
  if (['blocked', 'failed'].includes(task.status) && !task.stale_inputs?.length) buttons.push(node('button', { class: 'button secondary', text: 'Retry task', onclick: event => action(event.currentTarget, async () => { await api(`/tasks/${encodeURIComponent(task.id)}/retry`, 'POST', {}); $('detail-dialog').close(); toast('Task queued for another bounded attempt.'); await refresh(); }) }));
  if (buttons.length) content.push(node('div', { class: 'detail-buttons' }, buttons));
  if (task.status === 'awaiting_review' && task.result_ref) content.push(reviewForm(task));
  openDetail(task.title || task.id, `TASK · ${task.id}`, content);
}
function reconciliationForm(task) {
  const stale = task.stale_inputs || [];
  const canReconcile = ['queued', 'blocked', 'failed'].includes(task.status);
  const entries = stale.map(ref => node('div', { class: 'reconciliation-input' }, [
    node('strong', { text: ref.id }),
    node('p', { text: `Pinned version ${ref.pinned} → latest version ${ref.latest}` }),
    node('div', { class: 'detail-buttons' }, [
      node('button', { type: 'button', class: 'button secondary', text: `View pinned · v${ref.pinned}`, onclick: () => showArtifact(ref.id, ref.pinned, ref.latest) }),
      node('button', { type: 'button', class: 'button secondary', text: `View latest · v${ref.latest}`, onclick: () => showArtifact(ref.id, ref.latest, ref.latest) }),
    ]),
  ]));
  const section = node('section', { class: 'reconciliation-section' }, [
    node('h3', { text: 'Changed inputs need your review' }),
    node('p', { class: 'section-intro', text: 'Accepting these versions changes the evidence used for this task and its subsequent results. Check whether the approved method and acceptance criteria still apply.' }),
    ...entries,
  ]);
  if (!canReconcile) {
    section.append(node('p', { class: 'meeting-item', text: 'Review the changed evidence before deciding whether this work needs a follow-up task.' }));
    return section;
  }
  const checkbox = node('input', { type: 'checkbox', required: 'required', 'aria-label': 'I reviewed the changed input versions' });
  const button = node('button', { type: 'submit', class: 'button primary', text: 'Use reviewed versions and queue task' });
  button.disabled = true;
  checkbox.addEventListener('change', () => { button.disabled = !checkbox.checked; });
  const form = node('form', { class: 'reconciliation-form', onsubmit: event => {
    event.preventDefault();
    if (!checkbox.checked) return;
    action(button, async () => {
      const versions = new Map(stale.map(ref => [ref.id, ref.latest]));
      const refs = (task.input_refs || []).map(ref => ({ ...ref, version: versions.get(ref.id) || ref.version }));
      await api(`/tasks/${encodeURIComponent(task.id)}/retry`, 'POST', { input_refs: refs });
      $('detail-dialog').close();
      toast('Reviewed input versions recorded. The task will run when its dependencies are complete.');
      await refresh();
    });
  } }, [node('label', { class: 'reconciliation-confirm' }, [checkbox, node('span', { text: 'I reviewed the changed input versions' })]), button]);
  section.append(form);
  return section;
}
function reviewForm(task) {
  const reviewer = node('input', { value: 'carol', required: 'required', 'aria-label': 'Reviewing participant' });
  const verdict = node('select', { 'aria-label': 'Review verdict' }, [node('option', { value: 'approve', text: 'Approve computational result' }), node('option', { value: 'revise', text: 'Request a justified revision' })]);
  const rationale = node('textarea', { rows: 3, placeholder: 'Explain the evidence and methodological reason for this review…', required: 'required', 'aria-label': 'Review evidence and rationale' });
  const criteria = node('textarea', { rows: 3, value: lines(task.acceptance_criteria), 'aria-label': 'Acceptance criteria reviewed, one per line' });
  const button = node('button', { type: 'submit', class: 'button primary', text: 'Record review' });
  return node('form', { class: 'review-form', onsubmit: event => {
    event.preventDefault();
    action(button, async () => {
      await api(`/tasks/${encodeURIComponent(task.id)}/reviews`, 'POST', { reviewer: reviewer.value.trim(), verdict: verdict.value, rationale: rationale.value.trim(), criteria: lineArray(criteria.value), result_version: task.result_ref.version });
      $('detail-dialog').close(); toast('Review recorded against the specific result version.'); await refresh();
    });
  } }, [node('h3', { text: 'Review against the task scope' }), node('p', { class: 'section-intro', text: 'Agent review evaluates the computational result. Human scientific judgment is recorded separately.' }), node('div', { class: 'field-row' }, [node('div', {}, [node('label', { text: 'Reviewing participant' }), reviewer]), node('div', {}, [node('label', { text: 'Verdict' }), verdict])]), node('label', { text: 'Acceptance criteria considered' }), criteria, node('label', { text: 'Evidence and rationale' }), rationale, button]);
}
async function showArtifact(id, version, latestVersion = version) {
  try {
    const artifact = await api(`/artifacts/${encodeURIComponent(id)}?version=${Number(version)}`);
    const metadata = artifact.metadata || artifact;
    const source = await api(`/artifacts/${encodeURIComponent(id)}/markdown?version=${Number(version)}`);
    const history = node('select', { 'aria-label': 'Artifact version', onchange: event => showArtifact(id, Number(event.target.value), latestVersion) }, Array.from({ length: Math.max(1, Number(latestVersion) || 1) }, (_, index) => node('option', { value: index + 1, text: `Version ${index + 1}` })));
    history.value = String(version);
    history.style.width = '140px';
    openDetail(metadata.objective || id, `${cap(metadata.artifact_type || artifact.artifact_type).toUpperCase()} · ${id}`, [node('div', { class: 'detail-meta' }, [history, node('button', { class: 'button secondary', text: 'Download Markdown ↓', onclick: () => downloadArtifact(id, version) })]), node('p', { class: 'section-intro', text: `Artifact ${id} · Version ${version} · Readable outside the web interface` }), node('pre', { class: 'artifact-source', text: typeof source === 'string' ? source : asText(source) })]);
  } catch (error) { toast(error.message, true); }
}
async function downloadArtifact(id, version) {
  try {
    const text = await api(`/artifacts/${encodeURIComponent(id)}/markdown?version=${Number(version)}`);
    const url = URL.createObjectURL(new Blob([typeof text === 'string' ? text : asText(text)], { type: 'text/markdown;charset=utf-8' }));
    const link = node('a', { href: url, download: `${id}.v${version}.md` });
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { toast(error.message, true); }
}

function openMeeting() { $('meeting-dialog').showModal(); }
function provenance(value) {
  const text = typeof value === 'string' ? value : value?.kind || value?.type || value?.status || 'inferred';
  const hasInference = /inferred/.test(text);
  const explicit = /explicit|recorded/.test(text) && !hasInference;
  return node('span', { class: `provenance ${explicit ? 'explicit' : ''}`, text: explicit ? 'EXPLICITLY RECORDED' : /explicit|recorded/.test(text) ? 'RECORDED ASSIGNMENT · INFERRED DETAILS' : 'AGENT INFERENCE · REVIEW' });
}
function meetingItem(item) {
  if (typeof item === 'string') return node('div', { class: 'meeting-item', text: item });
  return node('div', { class: 'meeting-item' }, [provenance(item.provenance || item.origin), node('strong', { text: item.statement || item.decision || item.text || item.question || item.title || item.summary || asText(item) }), item.rationale ? node('div', { text: `Rationale: ${item.rationale}` }) : null]);
}
function proposalField(label, value, type = 'input', field) {
  const input = node(type, { value, ...(type === 'textarea' ? { rows: 2 } : {}), 'data-field': field, 'aria-label': label });
  return node('div', {}, [node('label', { text: label }), input]);
}
function renderMeeting(data) {
  const extracted = data.extraction || data;
  state.meeting = extracted;
  state.meeting.id = extracted.id || extracted.metadata?.id || data.id;
  $('meeting-preview').hidden = false;
  clear($('meeting-summary'), [node('div', { class: 'summary-box', text: asText(extracted.summary || extracted.metadata?.summary || 'Meeting outcomes extracted. Review all inferred assignments before approving.') })]);
  const decisions = extracted.decisions || extracted.metadata?.decisions || [];
  clear($('meeting-decisions'), decisions.length ? decisions.map(meetingItem) : [node('p', { class: 'meeting-item', text: 'No explicit decisions were identified.' })]);
  const proposals = extracted.proposed_tasks || extracted.metadata?.proposed_tasks || [];
  clear($('proposal-list'), proposals.map((proposal, index) => {
    const include = node('input', { type: 'checkbox', checked: true, 'data-include': 'true', 'aria-label': `Include task ${proposal.id}`, style: 'width:auto;margin-right:8px' });
    const card = node('article', { class: 'proposal-card', 'data-index': index }, [node('div', {}, [include, provenance(proposal.provenance || proposal.origin)]), proposal.inferred_fields?.length ? node('p', { class: 'meeting-item', text: `Confirm inferred fields: ${proposal.inferred_fields.map(cap).join(', ')}.` }) : null, node('div', { class: 'field-row wide' }, [proposalField('Stable task ID', proposal.id, 'input', 'id'), proposalField('Owner', proposal.owner || '', 'input', 'owner')]), proposalField('Task title', proposal.title || proposal.id, 'input', 'title'), node('div', { style: 'margin-top:12px' }, [proposalField('Objective', proposal.objective || '', 'textarea', 'objective')]), node('div', { class: 'field-row wide', style: 'margin-top:12px' }, [proposalField('Dependencies (one task ID per line)', lines(proposal.dependencies), 'textarea', 'dependencies'), proposalField('Expected outputs (one per line)', lines(proposal.expected_outputs), 'textarea', 'expected_outputs')]), proposalField('Acceptance criteria (one per line)', lines(proposal.acceptance_criteria), 'textarea', 'acceptance_criteria'), proposal.source_quote ? node('p', { class: 'meeting-item', text: `Source: “${proposal.source_quote}”` }) : null]);
    return card;
  }));
  const questions = extracted.questions || extracted.metadata?.questions || [];
  clear($('meeting-questions'), questions.length ? questions.map(meetingItem) : [node('p', { class: 'meeting-item', text: 'No open questions identified. Add methodological questions to the notes if anything remains unresolved.' })]);
  $('approve-scope-button').disabled = !proposals.length;
  $('meeting-preview').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

$('meeting-button').addEventListener('click', openMeeting);
$('nav-meeting').addEventListener('click', openMeeting);
document.querySelectorAll('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } }));
document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => { state.filter = button.dataset.filter; document.querySelectorAll('.tab').forEach(tab => tab.classList.toggle('active', tab === button)); renderTasks(); }));
document.querySelectorAll('.sidebar a.nav-link').forEach(link => link.addEventListener('click', () => { document.querySelectorAll('.nav-link').forEach(item => item.classList.toggle('selected', item === link)); }));
$('task-search').addEventListener('input', event => { state.search = event.target.value.trim().toLowerCase(); renderTasks(); });
$('refresh-button').addEventListener('click', () => refresh());
$('mark-seen-button').addEventListener('click', () => { state.seen = latestSequence(state.dashboard || {}); localStorage.setItem('researchrelay:last-seen', String(state.seen)); render(state.dashboard || {}); toast('Project updates marked as read.'); });
$('meeting-upload').addEventListener('change', async event => {
  const file = event.target.files?.[0];
  if (!file) return;
  if (file.size > 200_000) { toast('Please use a text or Markdown file smaller than 200 KB.', true); return; }
  $('meeting-notes').value = await file.text();
  toast(`${file.name} loaded. Review the notes, then extract.`);
});
$('meeting-form').addEventListener('submit', event => {
  event.preventDefault();
  const button = event.submitter;
  action(button, async () => { const data = await api('/meetings', 'POST', { notes: $('meeting-notes').value, participant: 'human' }); renderMeeting(data); toast('Draft scope ready for your review.'); await refresh(true); });
});
$('approve-scope-button').addEventListener('click', event => action(event.currentTarget, async () => {
  const proposals = state.meeting.proposed_tasks || state.meeting.metadata?.proposed_tasks || [];
  const tasks = [...$('proposal-list').querySelectorAll('.proposal-card')].filter(card => card.querySelector('[data-include]').checked).map(card => {
    const proposal = { ...proposals[Number(card.dataset.index)] };
    card.querySelectorAll('[data-field]').forEach(field => { proposal[field.dataset.field] = ['dependencies', 'expected_outputs', 'acceptance_criteria'].includes(field.dataset.field) ? lineArray(field.value) : field.value.trim(); });
    return proposal;
  });
  if (!tasks.length) throw new Error('Select at least one task to approve.');
  if (tasks.some(task => !task.owner || !task.title || !task.objective)) throw new Error('Each approved task needs a title, owner, and objective.');
  await api(`/meetings/${encodeURIComponent(state.meeting.id)}/approve`, 'POST', { tasks });
  $('meeting-dialog').close(); $('meeting-preview').hidden = true; $('meeting-notes').value = ''; state.meeting = null;
  toast(`${tasks.length} task${tasks.length === 1 ? '' : 's'} queued within the approved scope.`); await refresh();
}));
$('pilot-button').addEventListener('click', event => action(event.currentTarget, async () => {
  const completedJob = state.dashboard?.jobs?.find(job => job.id === 'pilot' && job.status === 'completed');
  if (completedJob) {
    let data = completedJob.data;
    try { data = typeof data === 'string' ? JSON.parse(data) : data; } catch { /* Retain original data. */ }
    openDetail('Working-session pilot', 'LOCAL DEMONSTRATION · RECORDED MEASURES', [node('p', { class: 'section-intro', text: 'Synthetic computations, local Git commits, and reviews ran without external credentials. Coordination time and the assessment must be supplied by a participant.' }), detailField('Pilot measures', state.dashboard.metric_summary || {}), node('pre', { class: 'artifact-source', text: asText(data) })]);
    return;
  }
  const result = await api('/pilot/run', 'POST', {});
  state.pilotBusy = true;
  notice('Local demonstration running: two independent agents, synthesis, a justified revision, and a human scientific decision. No external credentials are used.');
  toast(result.message || 'Pilot started. You can close the browser while agents work.');
  await refresh(true);
}));
$('export-button').addEventListener('click', event => action(event.currentTarget, async () => { const result = await api('/repository/export', 'POST', {}); toast(result.message || 'Versioned artifacts and a generated state snapshot exported to the local Git project record.'); await refresh(true); }));
$('import-button').addEventListener('click', event => action(event.currentTarget, async () => { const result = await api('/repository/import', 'POST', {}); const conflicts = result.conflicts || []; if (conflicts.length) { openDetail('Repository reconciliation', 'CONFLICTS REQUIRE ATTENTION', [node('p', { class: 'section-intro', text: 'These repository updates need reconciliation before they can be imported.' }), node('pre', { class: 'artifact-source', text: asText(conflicts) })]); } else toast(result.message || 'Repository artifacts reconciled with the authoritative workflow state.'); await refresh(true); }));
$('assessment-form').addEventListener('submit', event => {
  event.preventDefault();
  action(event.submitter, async () => {
    const note = $('assessment-note').value.trim();
    await api('/metrics', 'POST', { participant: 'human', kind: 'assessment_clarity', value: Number($('assessment-rating').value), note });
    const minutes = $('coordination-time').value;
    if (minutes !== '') await api('/metrics', 'POST', { participant: 'human', kind: 'coordination_minutes', value: Number(minutes), note: 'Participant-reported coordination time for this working session.' });
    $('coordination-time').value = ''; $('assessment-note').value = ''; toast('Pilot assessment recorded.'); await refresh(true);
  });
});
const accessButton = node('button', { class: 'text-button', text: 'Access', title: 'Configure a project-scoped access token for this browser session', onclick: () => {
  const input = node('input', { type: 'password', autocomplete: 'off', placeholder: 'Project access token', value: sessionStorage.getItem('researchrelay:token') || '', 'aria-label': 'Project access token' });
  const button = node('button', { type: 'submit', class: 'button primary', text: 'Use for this browser session' });
  openDetail('Project access', 'OPTIONAL AUTHENTICATED SERVICE', [node('p', { class: 'section-intro', text: 'The local demonstration does not need a token. For a configured service, use your project-scoped token. It is held only in this browser session and sent to this service.' }), node('form', { onsubmit: event => { event.preventDefault(); const token = input.value.trim(); if (token) sessionStorage.setItem('researchrelay:token', token); else sessionStorage.removeItem('researchrelay:token'); $('detail-dialog').close(); refresh(); } }, [input, node('div', { class: 'detail-buttons' }, [button])])]);
} });
document.querySelector('.topbar-right').append(accessButton);
refresh();
setInterval(() => refresh(true), 4000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(true); });
