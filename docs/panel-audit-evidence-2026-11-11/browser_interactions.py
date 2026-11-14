"""User interactions with explicit failure injection, isolated Python, and no provider calls."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
OUT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:5173/?api_origin=http%3A%2F%2Flocalhost%3A48001&control_origin=http%3A%2F%2Flocalhost%3A48001'
results = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width':1440,'height':900})
    context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true');window.__YUIZAKI_CONTROL_TOKEN__='panel-audit-local-fixture'")
    patches = []
    def protect(route):
        req = route.request
        path = urlsplit(req.url).path
        if urlsplit(req.url).port != 48001 or req.method in ('GET','HEAD','OPTIONS'):
            route.continue_(); return
        if req.method == 'PATCH' and path.rstrip('/') == '/api/settings':
            patches.append(req.post_data_json)
            route.fulfill(status=503,json={'code':'audit_save_failed','message':'Synthetic save failure','retryable':True}); return
        if path.startswith('/api/workspaces') or path.startswith('/api/sessions'):
            route.continue_(); return
        route.fulfill(status=409,json={'code':'audit_read_only','message':'Audit blocked mutation'})
    context.route('**/*',protect)
    page = context.new_page()
    page.set_default_timeout(10000)
    errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(BASE+'#/w/default/settings',wait_until='networkidle')
    page.wait_for_function("document.documentElement.dataset.yuizakiAppReady==='true'")
    field=page.locator('input[name="llm-base-url"]')
    original=field.input_value()
    draft='http://127.0.0.1:49999/v1'
    field.fill(draft); field.press('Tab')
    retry=page.get_by_role('button',name='重试保存',exact=True)
    expect(retry).to_be_visible(timeout=10000)
    expect(retry).to_be_enabled()
    expect(field).to_have_value(draft)
    first_count=len(patches)
    retry.click()
    page.wait_for_timeout(1500)
    assert len(patches)>first_count, 'Retry did not resend the failed settings patch'
    expect(retry).to_be_enabled()
    expect(field).to_have_value(draft)
    results.append({'scenario':'settings save failure and retry','passed':True,'patch_count':len(patches),'draft_preserved':True,'response':'synthetic 503; no settings persisted'})
    page.evaluate("location.hash='/w/default/memory'")
    page.get_by_test_id('memory-advanced-tools-toggle').click()
    page.get_by_role('menuitem').first.click()
    dialog=page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    results.append({'scenario':'memory advanced drawer opens','passed':True,'buttons':dialog.get_by_role('button').all_text_contents()})
    page.keyboard.press('Escape'); expect(dialog).to_be_hidden()
    page.get_by_role('button',name='当前工作区',exact=True).click()
    workspace=page.get_by_role('dialog'); expect(workspace).to_be_visible()
    expect(page.get_by_test_id('proactive-enabled')).to_be_visible()
    page.wait_for_timeout(1000)
    expect(page.get_by_test_id('proactive-enabled')).to_be_enabled()
    results.append({'scenario':'workspace drawer proactive controls finish loading','passed':True})
    page.keyboard.press('Escape'); expect(workspace).to_be_hidden()
    context.close()
    onboarding=browser.new_context(viewport={'width':1280,'height':900})
    onboarding.add_init_script("window.__YUIZAKI_CONTROL_TOKEN__='panel-audit-local-fixture'")
    onboarding.route('**/*',protect)
    gate=onboarding.new_page()
    gate.goto(BASE,wait_until='networkidle')
    skip=gate.get_by_role('button',name='跳过并进入应用',exact=True)
    expect(skip.first).to_be_visible()
    skip.first.click()
    expect(gate.locator('main').first).to_be_visible()
    results.append({'scenario':'onboarding skip remains usable when Electron host unavailable','passed':True})
    onboarding.close(); browser.close()
(OUT/'browser-interactions.json').write_text(json.dumps({'results':results,'page_errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':len(results),'page_errors':errors},ensure_ascii=False))
