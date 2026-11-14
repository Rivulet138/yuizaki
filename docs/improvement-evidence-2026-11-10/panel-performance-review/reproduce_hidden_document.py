import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
OUT=Path(__file__).resolve().parent
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':900})
    context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true');window.__reviewHidden=false;Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.__reviewHidden})")
    page=context.new_page(); reads=[]
    def protect(route):
        r=route.request; path=urlsplit(r.url).path
        if r.method not in ('GET','HEAD','OPTIONS'): route.fulfill(status=409,json={'error':'review_read_only'})
        elif path=='/api/pet/catalog': reads.append(path);route.fulfill(json={'models':[]})
        elif '/assets/pet-renderer-' in path and path.endswith('.js'): route.abort()
        else: route.continue_()
    page.route('**/*',protect)
    page.goto('http://127.0.0.1:38945/#/w/default/chat',wait_until='domcontentloaded')
    page.locator('.chat-workspace').wait_for(state='visible',timeout=30000)
    page.wait_for_timeout(500)
    page.evaluate("()=>{window.__reviewHidden=true;document.dispatchEvent(new Event('visibilitychange'))}")
    before=len(reads);page.wait_for_timeout(3100)
    result={'document_hidden':page.evaluate('document.hidden'),'catalog_reads_while_document_hidden_3100ms':len(reads)-before,'simulation':'document.hidden getter plus visibilitychange; verifies handler behavior, not OS minimization'}
    print(json.dumps(result,ensure_ascii=True),flush=True)
    (OUT/'hidden-document.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    context.close();browser.close()
