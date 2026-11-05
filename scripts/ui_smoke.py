"""Optional real-browser smoke. Start an isolated service first; see --help.

Requires `python -m pip install playwright` and `python -m playwright install chromium`.
Uses Playwright's Chromium on any supported OS; --browser accepts an existing browser.
This script intentionally writes synthetic QA tasks/decisions to its target.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import sync_playwright, expect


def check_reconciliation(page, url):
    """Seed only portable inputs, then reconcile their versions through the UI."""
    suffix = str(int(time.time()))
    artifact_id = f'ui-reconciliation-input-{suffix}'
    task_id = f'ui-reconciliation-task-{suffix}'
    metadata = {'id': artifact_id, 'project_id': 'agentic-collaboration', 'artifact_type': 'decision',
                'question': 'Which source classification should be used?', 'options': ['Reviewed source classification'],
                'evidence': ['Browser QA source-status note'], 'consequence': 'Changes the evidence used by the synthesis.',
                'objective': 'Source-status input for reconciliation QA'}
    first = page.request.post(url + '/api/artifacts', data={'metadata': metadata, 'body': '# Source classification v1'})
    assert first.ok, first.text()
    created = page.request.post(url + '/api/tasks', data={
        'id': task_id, 'title': 'Reconcile changed source classification', 'owner': 'alice',
        'objective': 'Use the latest reviewed publication-status classification.',
        'input_refs': [{'id': artifact_id, 'version': 1}],
        'acceptance_criteria': ['Use the human-reviewed source classification.'],
    })
    assert created.ok, created.text()
    second = page.request.post(url + '/api/artifacts', data={'metadata': {**metadata, 'version': 2}, 'body': '# Source classification v2\n\nUpdated publication-status evidence.'})
    assert second.ok, second.text()
    page.locator('#refresh-button').click()
    row = page.locator('.task').filter(has_text='Reconcile changed source classification')
    expect(row).to_contain_text('Input changed')
    row.click()
    expect(page.locator('.reconciliation-section')).to_contain_text('Pinned version 1 → latest version 2')
    button = page.get_by_role('button', name='Use reviewed versions and queue task')
    expect(button).to_be_disabled()
    page.get_by_role('button', name='View latest · v2').click()
    expect(page.locator('.artifact-source')).to_contain_text('Updated publication-status evidence')
    page.locator('#detail-dialog .close-dialog').click()
    row.click()
    page.get_by_role('checkbox', name='I reviewed the changed input versions').check()
    page.get_by_role('button', name='Use reviewed versions and queue task').click()
    expect(page.locator('#detail-dialog')).not_to_be_visible()
    updated = page.request.get(url + f'/api/tasks/{task_id}').json()
    assert updated['ready'] and not updated['stale_inputs'], updated
    assert updated['input_refs'] == [{'id': artifact_id, 'version': 2}], updated
    expect(row).not_to_contain_text('Input changed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8767')
    parser.add_argument('--browser', help='Optional Chrome/Edge executable; defaults to Playwright-managed Chromium.')
    parser.add_argument('--screenshot', default='.runtime/dashboard.png')
    parser.add_argument('--reconciliation-only', action='store_true', help='Run only the changed-input reconciliation regression.')
    args = parser.parse_args()
    errors = []
    with sync_playwright() as playwright:
        launch_options = {'headless': True}
        if args.browser:
            launch_options['executable_path'] = str(Path(args.browser).expanduser())
        browser = playwright.chromium.launch(**launch_options)
        page = browser.new_page(viewport={'width': 1512, 'height': 1100}, device_scale_factor=1)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.url, wait_until='networkidle')
        expect(page.locator('#connection-status')).to_have_text('All changes saved')
        initial = page.request.get(args.url + '/api/dashboard').json()
        assert not initial['tasks'], 'Use a fresh isolated demo database for this mutating browser smoke.'
        if args.reconciliation_only:
            check_reconciliation(page, args.url)
            assert not errors, errors
            print(json.dumps({'status': 'passed', 'checks': ['changed input version inspection', 'explicit review acknowledgement', 'complete input reconciliation', 'task ready after reconciliation'], 'browser_errors': errors}, indent=2))
            browser.close()
            return
        page.locator('#pilot-button').click()
        expect(page.locator('#stat-completed')).to_contain_text('3', timeout=120_000)
        expect(page.locator('.decision-card')).to_have_count(1, timeout=30_000)
        expect(page.locator('#pilot-button')).to_contain_text('View literature summary', timeout=30_000)
        screenshot = Path(args.screenshot)
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot), full_page=True)
        expect(page.locator('#source-count')).to_have_text('12 source notes')
        expect(page.locator('#source-status-counts')).to_contain_text('Published papers: 7')
        expect(page.locator('#source-status-counts')).to_contain_text('Preprints: 2')
        expect(page.locator('.coverage-table tbody tr')).to_have_count(12)
        # Inspect the revised synthesis and both immutable result versions.
        synthesis = page.locator('.task').filter(has_text='literature synthesis').first
        if not synthesis.count():
            synthesis = page.locator('.task').last
        synthesis.click()
        page.get_by_role('button', name='View result · v2').click()
        expect(page.locator('.artifact-source')).to_contain_text('schema_version:')
        page.get_by_role('combobox', name='Artifact version').select_option('1')
        expect(page.locator('#detail-content')).to_contain_text('Version 1')
        page.locator('#detail-dialog .close-dialog').click()
        # Test artifact download via the authenticated request path.
        with page.expect_download() as download:
            page.locator('.artifact-row').first.locator('.download-link').click()
        assert download.value.suggested_filename.endswith('.md')
        # Resolve a synthetic human decision in this isolated QA workspace.
        decision = page.locator('.decision-card').first
        decision.locator('input').fill('Browser QA: audit full-text methods before drawing conclusions from the literature snapshot.')
        decision.get_by_role('button', name='Record scientific decision').click()
        expect(page.locator('.decision-card')).to_have_count(0, timeout=15_000)
        page.locator('#coordination-time').fill('2.5')
        page.locator('#assessment-note').fill('Synthetic browser QA: the evidence and next action are visible.')
        page.get_by_role('button', name='Record assessment').click()
        expect(page.locator('#stat-time')).to_contain_text('2.5', timeout=15_000)
        # Meeting intake, inferred-field correction, and explicit scope approval.
        page.locator('#meeting-button').click()
        page.locator('#meeting-notes').fill('Decision: Audit source access because abstract-only evidence limits interpretation.\nAlice will audit the literature search exclusions.\nQuestion: Which studies need full-text review?')
        page.get_by_role('button', name='Extract meeting artifacts').click()
        expect(page.locator('#proposal-list .proposal-card')).to_have_count(1)
        expect(page.locator('#proposal-list')).to_contain_text('INFERRED DETAILS')
        card = page.locator('#proposal-list .proposal-card')
        card.locator('[data-field=id]').fill(f'ui-source-audit-{int(time.time())}')
        card.locator('[data-field=owner]').fill('bob')
        card.locator('[data-field=acceptance_criteria]').fill('Document search exclusions, inspected access, and limitations.')
        page.locator('#approve-scope-button').click()
        expect(page.locator('#meeting-dialog')).not_to_be_visible()
        expect(page.locator('.task')).to_have_count(4, timeout=15_000)
        # Review form against a task result that we submit through the worker API.
        context = page.request
        task_data = context.get(args.url + '/api/tasks').json()
        qa_task = next(task for task in task_data if str(task['id']).startswith('ui-source-audit'))
        claim = context.post(args.url + f'/api/tasks/{qa_task["id"]}/claim', data={'worker_id': 'ui-qa-bob', 'lease_seconds': 120}).json()
        token = claim.get('claim_token') or claim.get('task', {}).get('claim_token')
        metadata = {
            'id': f'{qa_task["id"]}-result', 'project_id': 'agentic-collaboration', 'artifact_type': 'result',
            'responsible_participant': 'bob', 'producing_agent': 'browser-qa-worker', 'task_id': qa_task['id'],
            'data': [{'path': 'qa/search-log.md', 'mode': 'synthetic browser fixture'}],
            'code': [{'path': 'scripts/ui_smoke.py', 'mode': 'synthetic browser fixture'}],
            'configuration': {'mode': 'synthetic browser QA'}, 'environment': {'python': '3.12', 'mode': 'synthetic'},
            'evidence': ['Synthetic QA result only'], 'input_refs': claim.get('input_refs', []),
        }
        response = context.post(args.url + f'/api/tasks/{qa_task["id"]}/submit', data={
            'claim_token': token, 'idempotency_key': qa_task['id'],
            'artifact': {'metadata': metadata, 'body': '# Browser QA source audit\n\nThe exclusion and access evidence is incomplete.'},
            'completion_notes': 'Browser QA only.',
        })
        assert response.ok, response.text()
        page.locator('#refresh-button').click()
        task_row = page.locator('.task').filter(has_text='literature search exclusions').last
        expect(task_row).to_contain_text('Awaiting Review')
        task_row.click()
        expect(page.locator('.review-form')).to_be_visible()
        page.locator('.review-form select').select_option('revise')
        page.locator('.review-form textarea').last.fill('The approved criterion requires an explicit exclusion log and source access classifications. Record them before interpreting coverage.')
        page.get_by_role('button', name='Record review', exact=True).click()
        expect(page.locator('#detail-dialog')).not_to_be_visible()
        page.locator('#task-search').fill('search exclusions')
        expect(page.locator('.task')).to_have_count(1)
        expect(page.locator('.task')).to_contain_text('1 revision')
        page.locator('#task-search').fill('')
        check_reconciliation(page, args.url)
        # Mobile page must fit the viewport, without horizontal scrolling.
        page.set_viewport_size({'width': 390, 'height': 844})
        page.wait_for_timeout(300)
        overflow = page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
        assert not overflow, 'Mobile layout has horizontal overflow'
        page.screenshot(path=str(screenshot.with_name('dashboard-mobile.png')), full_page=True)
        assert not errors, errors
        print(json.dumps({'status': 'passed', 'browser_errors': errors, 'checks': [
            'pilot background execution', 'literature coverage and next-search decision', 'result version history',
            'Markdown download', 'scientific decision resolution', 'participant assessment',
            'meeting extraction and inferred-field correction', 'scope approval', 'justified revision review',
            'task search', '390px responsive layout',
            'changed-input reconciliation with explicit human acknowledgement',
        ], 'screenshot': str(screenshot.resolve())}, indent=2))
        browser.close()


if __name__ == '__main__':
    main()
