"""Synthetic runtime failures/retries; all real mutations are blocked."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
OUT = Path(__file__).resolve().parent
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width': 1440, 'height': 900})
    context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
    page = context.new_page()
    errors, retries, writes, reads = [], [], [], []
    phase = {'value': 'failed', 'retry_count': 0}
    page.on('pageerror', lambda e: errors.append(str(e)))
    def status(state):
        return {'sections': {'svc': {'state': state, 'target_revision': 7, 'applied_revision': 7 if state == 'applied' else None, 'error': 'runtime_reload_failed' if state == 'failed' else None}, 'llm': {'state': 'applied', 'target_revision': 9, 'applied_revision': 9}}}
    def protect(route):
        r = route.request
        path = urlsplit(r.url).path
        if path == '/api/settings/runtime/retry' and r.method == 'POST':
            retries.append(r.post_data_json)
            phase['retry_count'] += 1
            if phase['retry_count'] == 1:
                route.fulfill(status=503, json={'error': 'synthetic_runtime_temporarily_unavailable'})
            else:
                phase['value'] = 'applied'
                route.fulfill(json=status('applying'))
        elif path == '/api/settings/runtime/status' and r.method == 'GET':
            reads.append(phase['value'])
            if phase['value'] == 'read_error':
                route.fulfill(status=503, json={'error': 'synthetic_status_unavailable'})
            else:
                route.fulfill(json=status(phase['value']))
        elif r.method not in ('GET', 'HEAD', 'OPTIONS'):
            writes.append({'method': r.method, 'path': path})
            route.fulfill(status=409, json={'error': 'acceptance_blocks_real_mutation'})
        elif '/assets/pet-renderer-' in path and path.endswith('.js'):
            route.abort()
        else:
            route.continue_()
    page.route('**/*', protect)
    try:
        page.goto('http://127.0.0.1:48945/#/w/default/settings?section=summary', wait_until='domcontentloaded')
        feedback = page.get_by_test_id('settings-runtime-feedback')
        feedback.wait_for(state='visible', timeout=30000)
        page.locator('[data-section="svc"][data-target-revision="7"]').wait_for()
        initial_visible = feedback.is_visible()
        page.screenshot(path=str(OUT / 'runtime-failure.png'))
        page.set_viewport_size({'width':390,'height':844})
        feedback.scroll_into_view_if_needed()
        bounds = feedback.bounding_box()
        assert bounds and bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 391, bounds
        feedback.locator('button').nth(1).focus()
        assert feedback.locator('button').nth(1).evaluate('(e)=>e===document.activeElement')
        page.screenshot(path=str(OUT / 'runtime-failure-390.png'))
        page.set_viewport_size({'width':1440,'height':900})
        feedback.locator('button').nth(1).click()
        feedback.get_by_role('alert').wait_for()
        retry_error_visible = feedback.get_by_role('alert').is_visible()
        feedback.locator('button').nth(1).click()
        feedback.wait_for(state='hidden', timeout=10000)
        phase['value'] = 'read_error'
        page.evaluate("location.hash='/w/default/chat'")
        page.locator('.chat-workspace').wait_for(state='visible')
        page.evaluate("location.hash='/w/default/settings?section=summary'")
        feedback.get_by_role('alert').wait_for(timeout=10000)
        read_error_visible = feedback.is_visible()
        phase['value'] = 'applied'
        feedback.locator('button').first.click()
        feedback.wait_for(state='hidden', timeout=10000)
        page.wait_for_timeout(350)
        assert not feedback.is_visible(), 'runtime recovery remained stale after refresh completed'
        result = {'runtime_feedback_fits_390px_and_retry_focusable': True, 'initial_failure_visible_on_summary': initial_visible, 'retry_error_visible': retry_error_visible, 'read_error_visible': read_error_visible, 'retry_payloads': retries, 'recovered_to_applied': True, 'blocked_mutations': writes, 'status_reads': reads, 'pageerrors': errors}
        assert retries == [{'targets': {'svc': 7}}, {'targets': {'svc': 7}}], result
        assert not any(x['path'] == '/api/settings/' for x in writes), result
        assert not errors, result
        (OUT / 'runtime-feedback.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=True), flush=True)
    finally:
        context.close()
        browser.close()
