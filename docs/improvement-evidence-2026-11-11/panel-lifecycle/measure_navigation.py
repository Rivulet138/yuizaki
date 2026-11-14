from pathlib import Path
from urllib.parse import urlsplit
import json, sys, time
from playwright.sync_api import sync_playwright
out=Path(__file__).resolve().parent
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':900})
    context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
    page=context.new_page(); errors=[]; requests=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.on('request',lambda r: requests.append({'path':urlsplit(r.url).path,'method':r.method}))
    def protect(route):
        if route.request.method not in ('GET','HEAD','OPTIONS'):
            route.fulfill(status=409,json={'error':'performance_read_only'})
        else: route.continue_()
    page.route('**/*',protect)
    page.goto('http://127.0.0.1:48945/#/w/default/settings',wait_until='domcontentloaded')
    page.locator('.settings-section-button').first.wait_for(timeout=30000)
    page.wait_for_timeout(1200)
    page.evaluate("()=>{window.__settingsNode=document.querySelector('.settings-panel');}")
    samples=[]
    for name,selector in [('memory','.memory-panel'),('settings','.settings-panel'),('chat','.chat-workspace'),('settings','.settings-panel'),('prompt','.prompt-panel'),('settings','.settings-panel')]*5:
        start=time.perf_counter(); before=len(requests)
        page.evaluate('(name)=>{location.hash="/w/default/"+name}',name)
        page.locator(selector).first.wait_for(state='visible',timeout=30000)
        page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        elapsed=round((time.perf_counter()-start)*1000,1)
        samples.append({'route':name,'visible_ms':elapsed,'same_settings_instance':page.evaluate("()=>document.querySelector('.settings-panel')===window.__settingsNode") if name=='settings' else None,'requests':requests[before:]})
    warm = sorted(x['visible_ms'] for x in samples[6:])
    result={'warm_sample_count':len(warm),'warm_p95_ms':warm[max(0, __import__('math').ceil(len(warm)*.95)-1)],'samples':samples,'pageerrors':errors,'settings_gets':sum(r['path']=='/api/settings/' for r in requests)}
    label=sys.argv[1] if len(sys.argv)>1 else 'baseline'
    (out/(label+'.json')).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True))
    if label!='baseline':
        assert all(item['same_settings_instance'] for item in samples if item['route']=='settings'), result
        assert not errors, errors
    context.close(); browser.close()
