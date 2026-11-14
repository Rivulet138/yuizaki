import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
OUT=Path(__file__).resolve().parent
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':900})
    context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
    page=context.new_page(); reads=[]; errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def protect(route):
        r=route.request; path=urlsplit(r.url).path
        if r.method not in ('GET','HEAD','OPTIONS'): route.fulfill(status=409,json={'error':'review_read_only'})
        elif path=='/api/settings/runtime/status':
            reads.append(path); route.fulfill(json={'sections':{'svc':{'state':'failed','target_revision':7,'applied_revision':None,'error':'runtime_reload_failed'}}})
        else: route.continue_()
    page.route('**/*',protect)
    page.goto('http://127.0.0.1:38945/#/w/default/settings?section=svc',wait_until='domcontentloaded')
    page.locator('.settings-panel').wait_for(state='visible',timeout=30000)
    page.wait_for_timeout(1500)
    text=page.locator('.settings-panel').inner_text()
    result={'runtime_status_read':len(reads)>0,'runtime_failure_visible':any(t in text for t in ['\u5f53\u524d\u914d\u7f6e\u5e94\u7528\u5931\u8d25','\u670d\u52a1\u5e94\u7528\u5931\u8d25','runtime_reload_failed']),'retry_current_configuration_buttons':page.get_by_role('button',name='\u91cd\u8bd5\u5f53\u524d\u914d\u7f6e',exact=True).count(),'visible_alerts':page.locator('.el-alert:visible').all_inner_texts(),'pageerrors':errors}
    print(json.dumps(result,ensure_ascii=True),flush=True)
    (OUT/'runtime-feedback.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    context.close();browser.close()
