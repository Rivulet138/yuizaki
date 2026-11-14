"""Read-only panel/subtab sweep against the isolated real Python backend.
The Electron host is unavailable; its endpoints deliberately remain 404 and are
recorded as validation gaps. All non-read requests are blocked except isolated
workspace/session bookkeeping. No fixture data is presented as host integration.
"""
import json, time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
OUT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:5173/?api_origin=http%3A%2F%2Flocalhost%3A48001&control_origin=http%3A%2F%2Flocalhost%3A48001'
PANELS = ['chat','memory','settings','prompt','pet','svc','tool','plugins','infrastructure','agent-governance','agent-trace','persona-memory','i18n','deploy']
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width':1440,'height':900})
    context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true'); window.__YUIZAKI_CONTROL_TOKEN__='panel-audit-local-fixture';")
    page = context.new_page()
    errors, responses, blocked, results = [], [], [], []
    current = ['bootstrap']
    page.on('pageerror', lambda error: errors.append({'panel':current[0], 'error':str(error)}))
    def record(response):
        parts = urlsplit(response.url)
        if parts.port == 48001:
            responses.append({'panel':current[0], 'path':parts.path, 'status':response.status, 'method':response.request.method})
    page.on('response', record)
    def protect(route):
        req = route.request
        parts = urlsplit(req.url)
        if parts.port != 48001:
            route.continue_(); return
        if req.method in ('GET','HEAD','OPTIONS') or (req.method in ('PATCH','PUT','POST') and (parts.path.startswith('/api/workspaces') or parts.path.startswith('/api/sessions'))):
            route.continue_(); return
        blocked.append({'panel':current[0], 'path':parts.path, 'method':req.method})
        route.fulfill(status=409, json={'code':'audit_read_only', 'message':'Audit blocked host or provider mutation'})
    context.route('**/*', protect)
    def snapshot(label):
        return page.evaluate('''label => ({label, hash:location.hash, headings:[...document.querySelectorAll('h1,h2,h3')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()), tabs:[...document.querySelectorAll('[role=tab]')].filter(e=>e.getClientRects().length).map(e=>({text:e.textContent.trim(),selected:e.getAttribute('aria-selected')})), loading:[...document.querySelectorAll('.el-loading-mask,.async-state--loading,[aria-busy=true]')].filter(e=>e.getClientRects().length).length, messages:[...document.querySelectorAll('.el-alert--error,.el-message--error,[role=alert]')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()), overflow:document.documentElement.scrollWidth-innerWidth, bodyText:document.body.innerText.slice(0,18000)})''', label)
    for panel in PANELS:
        page.evaluate("localStorage.removeItem('deskpet-workspaces');localStorage.removeItem('deskpet-active-workspace')") if page.url != 'about:blank' else None
        current[0] = panel
        before = time.monotonic()
        page.goto(BASE+'#/w/default/'+panel, wait_until='domcontentloaded')
        try: page.wait_for_load_state('networkidle',timeout=12000)
        except PlaywrightTimeout: pass
        page.locator('main').first.wait_for(timeout=20000)
        page.wait_for_function("document.documentElement.dataset.yuizakiAppReady === 'true'",timeout=25000)
        page.evaluate("panel => { location.hash = '/w/default/' + panel }", panel)
        page.wait_for_timeout(300)
        page.wait_for_timeout(300)
        entry = snapshot(panel)
        entry['entry_ms'] = round((time.monotonic()-before)*1000)
        entry['subtabs'] = []
        seen = set()
        page.set_default_timeout(4000)
        for _ in range(45):
            tabs = page.get_by_role('tab').all()
            next_tab = None
            for tab in tabs:
                if not tab.is_visible() or tab.get_attribute('aria-disabled') == 'true': continue
                try: key = (tab.get_attribute('id'), tab.inner_text())
                except Exception: continue
                if key not in seen:
                    seen.add(key); next_tab = tab; break
            if next_tab is None: break
            try:
                text = next_tab.inner_text()
                next_tab.click(timeout=5000)
                try: page.wait_for_load_state('networkidle',timeout=5000)
                except PlaywrightTimeout: pass
                page.wait_for_timeout(150)
                entry['subtabs'].append(snapshot(text))
            except Exception as error:
                entry['subtabs'].append({'label':str(key),'interaction_error':str(error)})
        for width in (768,390):
            page.set_viewport_size({'width':width,'height':900})
            page.wait_for_timeout(100)
            entry.setdefault('responsive',[]).append(snapshot(str(width)))
        page.set_viewport_size({'width':1440,'height':900})
        page.screenshot(path=str(OUT/(panel+'.png')),full_page=True)
        results.append(entry)
        report={'scope':'real isolated Python backend; Electron host not running','results':results,'page_errors':errors,'responses':responses,'blocked_mutations':blocked}
        (OUT/'browser-panels.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'panel':panel,'actual':entry['hash'],'subtabs':len(entry['subtabs']),'loading':entry['loading'],'overflow':entry['overflow'],'page_errors':len(errors)},ensure_ascii=False),flush=True)
    context.close(); browser.close()
