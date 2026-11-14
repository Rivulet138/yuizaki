from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from pathlib import Path
import json, time
from urllib.parse import urlsplit
OUT=Path(r'E:\yuizaki\docs\audit-evidence-2026-11-09')
ROUTES=['chat','memory','settings','prompt','pet','svc','tool','plugins','infrastructure','agent-governance','agent-trace','persona-memory','i18n','deploy']
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':900})
    page=context.new_page()
    active=['bootstrap']; errors=[]; failed=[]; requests=[]; results=[]
    page.on('pageerror', lambda e:errors.append({'route':active[0],'message':str(e)}))
    def record(r):
        u=urlsplit(r.url)
        if u.hostname in ('localhost','127.0.0.1') and not '/assets/' in u.path:
            row={'route':active[0],'status':r.status,'method':r.request.method,'path':u.path}
            requests.append(row)
            if r.status>=400: failed.append(row)
    page.on('response',record)
    page.on('requestfailed',lambda r:errors.append({'route':active[0],'request_path':urlsplit(r.url).path,'message':r.failure}))
    page.goto('http://127.0.0.1:38945/',wait_until='networkidle')
    (OUT/'onboarding-observation.json').write_text(json.dumps({'text':page.locator('body').inner_text(),'networkErrors':failed},ensure_ascii=False,indent=2),encoding='utf-8')
    if page.get_by_role('button',name='跳过并进入应用',exact=True).count():
        page.get_by_role('button',name='跳过并进入应用',exact=True).first.click()
        page.wait_for_selector('nav',timeout=15000)
        page.wait_for_timeout(16000)
    for route in ROUTES:
        active[0]=route
        page.goto('http://127.0.0.1:38945/#/w/default/'+route,wait_until='domcontentloaded')
        try: page.wait_for_load_state('networkidle',timeout=7000)
        except PWTimeout: pass
        page.wait_for_timeout(1200)
        try: page.locator('.async-state--loading').first.wait_for(state='hidden',timeout=16000)
        except PWTimeout: pass
        row=page.evaluate('''(route)=>({route,actual:location.hash,headings:[...document.querySelectorAll('h1,h2,h3,[role="heading"]')].filter(e=>e.getClientRects().length).map(e=>e.textContent?.trim()),tabs:[...document.querySelectorAll('[role="tab"]')].filter(e=>e.getClientRects().length).map(e=>({text:e.textContent?.trim(),selected:e.getAttribute('aria-selected')})),actions:[...document.querySelectorAll('button')].filter(e=>e.getClientRects().length).map(e=>({text:e.innerText?.trim(),aria:e.getAttribute('aria-label'),disabled:e.disabled})),canvas:document.querySelectorAll('canvas').length,overflow:document.documentElement.scrollWidth-innerWidth,routeHost:document.querySelector('[data-route-name]')?.getAttribute('data-route-name'),loading:document.querySelectorAll('.el-loading-mask').length,errors:[...document.querySelectorAll('.el-message--error,.el-alert--error')].map(e=>e.textContent?.trim())})''',route)
        results.append(row)
        if route in ('chat','settings','infrastructure','i18n','pet'):
            page.screenshot(path=str(OUT/(route+'-desktop.png')),full_page=True)
        print(json.dumps({'route':route,'actual':row['actual'],'tabs':len(row['tabs']),'buttons':len(row['actions']),'overflow':row['overflow'],'errors':row['errors']},ensure_ascii=False),flush=True)
    report={'browser':'Playwright bundled Chromium headless','viewport':{'width':1440,'height':900},'results':results,'pageerrors':errors,'failedResponses':failed,'requests':requests}
    (OUT/'browser-panels.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'pageerrors':errors,'failedResponses':failed},ensure_ascii=False),flush=True)
    context.close();browser.close()
