from pathlib import Path
from urllib.parse import urlsplit
import json
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

OUT = Path(__file__).resolve().parent
ROUTES = ['chat','memory','settings','prompt','pet','svc','tool','plugins','infrastructure','agent-governance','agent-trace','persona-memory','i18n','deploy']
PANELS = {'chat':'.chat-workspace','memory':'.memory-panel','settings':'.settings-section-button','prompt':'.prompt-panel','pet':'.pet-console','svc':'.voice-panel','tool':'.tool-panel','plugins':'.plugin-console','infrastructure':'.infra-console','agent-governance':'.governance-console','agent-trace':'.trace-console','persona-memory':'.persona-panel','i18n':'.i18n-panel','deploy':'.infra-console'}
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(viewport={'width':1440,'height':900})
    context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
    page = context.new_page()
    active = ['bootstrap']; errors = []; failed = []; mutations = []; routes = []; tabs = []; responsive = []
    page.on('pageerror', lambda e: errors.append({'route':active[0], 'message':str(e)}))
    page.on('response', lambda r: failed.append({'route':active[0], 'path':urlsplit(r.url).path, 'status':r.status}) if r.status >= 400 else None)
    def read_only(route):
        request = route.request
        if request.method not in ('GET','HEAD','OPTIONS'):
            mutations.append({'route':active[0], 'method':request.method, 'path':urlsplit(request.url).path})
            route.fulfill(status=409, json={'error':'acceptance_read_only','message':'Acceptance blocks changes to existing user data'})
        else:
            route.continue_()
    page.route('**/*', read_only)
    page.goto('http://127.0.0.1:38945/', wait_until='domcontentloaded')
    page.wait_for_selector('nav', timeout=30000)
    for name in ROUTES:
        active[0] = name
        page.evaluate('(name)=>{location.hash="/w/default/"+name}',name)
        target = 'infrastructure' if name == 'deploy' else name
        page.wait_for_function('(name)=>location.hash.includes("/"+name)',arg=target,timeout=12000)
        page.locator(PANELS[name]).first.wait_for(state='visible',timeout=30000)
        page.wait_for_timeout(200)
        item = page.evaluate("()=>({hash:location.hash, headings:[...document.querySelectorAll('h1,h2,h3')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()),overflow:document.documentElement.scrollWidth-innerWidth,loading:document.querySelectorAll('.async-state--loading').length})")
        routes.append({'route':name, **item})
        if name in ('settings','memory','tool','agent-governance','agent-trace'):
            locator = page.locator('.settings-section-button') if name == 'settings' else page.get_by_role('tab')
            choices = locator.evaluate_all("es=>es.filter(e=>e.getClientRects().length).map(e=>({id:e.id,label:e.textContent.trim()}))")
            for choice in choices:
                if name == 'settings':
                    button = page.locator('.settings-section-button').filter(has_text=choice['label']).first
                elif choice['id']:
                    button = page.locator('[id="'+choice['id']+'"]')
                else:
                    button = page.get_by_role('tab',name=choice['label'],exact=True).first
                if button.is_visible():
                    button.click();page.wait_for_timeout(250)
                    tabs.append({'route':name,'tab':choice['label']})
        print(json.dumps({'route':name,'actual':item['hash'],'overflow':item['overflow']},ensure_ascii=True),flush=True)
    for width in (768,390):
        page.set_viewport_size({'width':width,'height':844})
        for name in ('chat','memory','settings'):
            active[0] = name
            page.evaluate('(name)=>{location.hash="/w/default/"+name}',name)
            page.locator(PANELS[name]).first.wait_for(state='visible',timeout=30000)
            page.wait_for_timeout(200)
            bounds = page.evaluate("()=>({width:innerWidth,overflow:document.documentElement.scrollWidth-innerWidth,controls:[...document.querySelectorAll('.runtime-model-select,.runtime-response-select,.send-button')].filter(e=>e.getClientRects().length).map(e=>{const r=e.getBoundingClientRect();return {class:e.className,left:Math.round(r.left),right:Math.round(r.right),top:Math.round(r.top),bottom:Math.round(r.bottom),uncovered:e.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2))}})})")
            responsive.append({'route':name,**bounds})
            if name == 'chat':
                assert bounds['controls'], 'chat controls missing'
                for control in bounds['controls']:
                    assert control['left'] >= 0 and control['right'] <= width, control
                    assert control['top'] >= 0 and control['bottom'] <= 844, control
                    assert control['uncovered'], control
            if width == 390 and name == 'chat':page.screenshot(path=str(OUT/'chat-390.png'))
    result={'source':'current dist/renderer served by existing control host','routes':routes,'tabs':tabs,'responsive':responsive,'pageerrors':errors,'httpFailures':failed,'blockedMutations':mutations}
    (OUT/'browser-acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'routes':len(routes),'tabs':len(tabs),'pageerrors':errors,'responsive':responsive,'blockedMutations':len(mutations)},ensure_ascii=True),flush=True)
    assert len(routes)==14 and len(tabs)==26,(len(routes),len(tabs))
    assert not errors,errors
    assert all(item['overflow']==0 for item in routes+responsive)
    context.close();browser.close()
