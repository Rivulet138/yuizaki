"""Isolated live-backend/browser regression checks; no production/user data writes."""
from __future__ import annotations
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUN = ROOT / 'artifacts' / ('panel-fix-runtime-' + str(time.time_ns()))
RUN.mkdir(parents=True)
API = 'http://127.0.0.1:48011'
BASE = 'http://127.0.0.1:5178/?api_origin=http%3A%2F%2Flocalhost%3A48011&control_origin=http%3A%2F%2Flocalhost%3A48011'
processes = []
logs = []
results = []
page_errors = []
proactive_responses = []
expect.set_options(timeout=15000)

def start(args, cwd, env, log_name):
    output = (OUT / log_name).open('w', encoding='utf-8')
    logs.append(output)
    proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    processes.append(proc)
    return proc

def ready(url, proc):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        assert proc.poll() is None, f'Server exited: {url}'
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.2)
    raise AssertionError('Server readiness timed out: ' + url)

try:
    for port in (48011, 5178):
        with socket.socket() as sock:
            assert sock.connect_ex(('127.0.0.1', port)) != 0, f'Reserved test port occupied: {port}'
    env = {**os.environ, 'SERVER_PORT': '48011', 'SERVER_HOST': '127.0.0.1',
           'YUIZAKI_DATA_DIR': str(RUN), 'YUIZAKI_SETTINGS_PATH': str(RUN/'settings.json'),
           'DATABASE_URL': 'sqlite:///' + (RUN/'chat.db').as_posix(),
           'AUDIO_CACHE_DIR': str(RUN/'audio'), 'MEMORY_SQLITE_PATH': str(RUN/'memory.db'),
           'MEMORY_BACKEND': 'sqlite', 'QDRANT_AUTO_START': '0', 'MEMORY_RERANKER_ENABLED': '0',
           'YUIZAKI_ALLOWED_ORIGINS': 'http://127.0.0.1:5178,http://localhost:5178',
           'YUIZAKI_BACKEND_API_TOKEN': 'panel-fix-local-fixture'}
    backend = start([str(ROOT/'python/.venv/Scripts/python.exe'), 'app.py'], ROOT/'python', env, 'backend.log')
    frontend = start(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '5178'],
                     ROOT/'electron', os.environ.copy(), 'frontend.log')
    ready(API+'/health', backend)
    ready('http://127.0.0.1:5178', frontend)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 900})
        context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true'); window.__YUIZAKI_CONTROL_TOKEN__='panel-fix-local-fixture'")
        api = context.request
        for workspace_id in ('audit-a', 'audit-b'):
            response = api.post(API+'/api/workspaces', data={'id': workspace_id, 'name': workspace_id})
            assert response.ok, response.text()
        page = context.new_page()
        page.set_default_timeout(15000)
        page.on('pageerror', lambda exc: page_errors.append(str(exc)))
        def record_response(response):
            path = urlsplit(response.url).path
            if '/proactive/' in path or '/activity-frames' in path:
                proactive_responses.append({'method': response.request.method, 'url': response.url, 'status': response.status})
        page.on('response', record_response)
        def protect(route):
            request = route.request
            path = urlsplit(request.url).path
            if urlsplit(request.url).port != 48011 or request.method in ('GET', 'HEAD', 'OPTIONS'):
                route.continue_(); return
            if path.startswith(('/api/workspaces', '/api/sessions', '/api/system/proactive/settings')) or path == '/api/system/active-workspace':
                route.continue_(); return
            route.fulfill(status=409, json={'code': 'isolated_test_no_provider_operation'})
        context.route('**/*', protect)
        held_summaries = []
        def hold_summary(route):
            held_summaries.append(route)
        page.route('**/api/system/proactive/feedback-summary?*', hold_summary)
        page.goto(BASE+'#/w/audit-a/settings', wait_until='domcontentloaded')
        page.wait_for_function("() => document.documentElement.dataset.yuizakiAppReady === 'true'")
        page.evaluate("location.hash='/w/audit-a/settings'")
        page.get_by_role('button', name='当前工作区', exact=True).click()
        dnd = page.get_by_test_id('proactive-dnd')
        expect(dnd).to_be_visible()
        try:
            expect(dnd).to_be_enabled(timeout=15000)
        except Exception:
            print(json.dumps({'pageErrors': page_errors, 'hash': page.evaluate('location.hash'), 'body': page.locator('body').inner_text()[-12000:], 'responses': proactive_responses}, ensure_ascii=True), flush=True)
            page.screenshot(path=str(OUT/'failure.png'), full_page=True)
            raise
        expect(dnd).not_to_be_checked()
        initial = api.get(API+'/api/system/proactive/settings', params={'workspace_id': 'audit-a'}).json()
        assert initial['revision'] == 0 and initial['updatedAt'] is None, initial
        assert held_summaries, 'Summary request was not held'
        results.append({'scenario': 'new workspace with null updatedAt loads while optional summary is still pending', 'passed': True})

        held_patches = []
        def hold_patch(route):
            if route.request.method == 'PATCH': held_patches.append(route)
            else: route.continue_()
        page.route('**/api/system/proactive/settings?*', hold_patch)
        with page.expect_request(lambda req: req.method == 'PATCH' and '/api/system/proactive/settings?' in req.url):
            dnd.check()
        expect(dnd).to_be_disabled()
        patch_deadline = time.monotonic() + 3
        while not held_patches and time.monotonic() < patch_deadline:
            page.wait_for_timeout(10)
        assert len(held_patches) == 1
        outgoing = held_patches[0].request
        assert parse_qs(urlsplit(outgoing.url).query)['workspace_id'] == ['audit-a']
        changed = api.post(API+'/api/system/active-workspace', data={'workspace_id': 'audit-b'})
        assert changed.ok, changed.text()
        held_patches[0].continue_()
        expect(dnd).to_be_enabled(); expect(dnd).to_be_checked()
        saved_a = api.get(API+'/api/system/proactive/settings', params={'workspace_id': 'audit-a'}).json()
        saved_b = api.get(API+'/api/system/proactive/settings', params={'workspace_id': 'audit-b'}).json()
        assert (saved_a['dnd'], saved_a['revision']) == (True, 1), saved_a
        assert (saved_b['dnd'], saved_b['revision']) == (False, 0), saved_b
        results.append({'scenario': 'real browser A PATCH held until global active switches to B, write and readback remain A', 'passed': True,
                        'A': {'dnd': saved_a['dnd'], 'revision': saved_a['revision']}, 'B': {'dnd': saved_b['dnd'], 'revision': saved_b['revision']}})
        page.unroute('**/api/system/proactive/feedback-summary?*', hold_summary)
        for route in held_summaries:
            workspace_id = parse_qs(urlsplit(route.request.url).query)['workspace_id'][0]
            route.fulfill(response=api.get(API+'/api/system/proactive/feedback-summary', params={'workspace_id': workspace_id}))
        page.unroute('**/api/system/proactive/settings?*', hold_patch)

        page.reload(wait_until='domcontentloaded')
        page.wait_for_function("() => document.documentElement.dataset.yuizakiAppReady === 'true'")
        page.evaluate("location.hash='/w/audit-a/settings'")
        page.get_by_role('button', name='当前工作区', exact=True).click()
        expect(dnd).to_be_enabled(); expect(dnd).to_be_checked()
        results.append({'scenario': 'successful save survives full page reload', 'passed': True})
        page.evaluate("location.hash='/w/audit-b/settings'")
        expect(dnd).to_be_enabled(); expect(dnd).not_to_be_checked()
        page.evaluate("location.hash='/w/audit-a/settings'")
        expect(dnd).to_be_enabled(); expect(dnd).to_be_checked()
        results.append({'scenario': 'A to B to A without page reload restores workspace settings', 'passed': True})
        page.screenshot(path=str(OUT/'proactive-save-readback.png'), full_page=True)
        page.keyboard.press('Escape')
        expect(page.get_by_role('dialog')).to_be_hidden()

        panels = ['pet','chat','prompt','svc','tool','plugins','infrastructure','agent-governance','agent-trace','persona-memory','settings','i18n','memory','deploy']
        for panel in panels:
            page.evaluate('(panel) => {location.hash="/w/audit-a/"+panel}', panel)
            expected = 'infrastructure' if panel == 'deploy' else panel
            page.wait_for_function('(name) => document.querySelector(`[data-route-name="${name}"]`) !== null', arg=expected)
            main = page.locator('main').first
            expect(main).to_be_visible()
            assert main.inner_text().strip(), f'Empty panel: {panel}'
            results.append({'scenario': 'SPA navigation '+panel, 'passed': True, 'actual_hash': page.evaluate('location.hash'),
                            'scope': 'entry render assertion; host/provider functions covered by controlled regression tests, not live here'})
        missing = api.patch(API+'/api/system/proactive/settings', data={'expectedRevision': 0, 'dnd': True})
        assert missing.status == 422
        assert not page_errors, page_errors
        assert proactive_responses and all(item['status'] == 200 for item in proactive_responses), proactive_responses
        results.append({'scenario': 'unscoped PATCH rejected and no page JavaScript exceptions', 'passed': True})
        browser.close()
    report = {'passed': True, 'runtimeData': str(RUN), 'scope': 'Real isolated Python + Vite + headless Chromium. Electron host and real providers not running.',
              'results': results, 'pageErrors': page_errors, 'proactiveResponses': proactive_responses}
    (OUT/'browser-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'scenarios': len(results), 'pageErrors': page_errors, 'report': str(OUT/'browser-verification.json')}, ensure_ascii=False), flush=True)
finally:
    for proc in reversed(processes):
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait(timeout=5)
    for log in logs: log.close()
