import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
OUT=Path(__file__).resolve().parent
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':900})
    context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
    page=context.new_page(); errors=[]; polls=[]; doc_reads=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    job={'job_id':'review-job','state':'running','phase':'embedding','processed_count':0,'total_count':5,'started_at':'2026-11-10T10:00:00Z','updated_at':'2026-11-10T10:00:00Z','recoverable':False}
    doc={'id':'review-doc','text':'Synthetic review memory','metadata':{'scope':'workspace','workspace_id':'default','layer':'semantic','type':'fact','review_status':'approved','importance':0.8}}
    overview={'total':1,'recallable':1,'by_state':{'active':1},'by_layer':{'semantic':1},'by_source':{'manual':1},'by_review_status':{'approved':1},'latest_activity':[]}
    def protect(route):
        r=route.request; path=urlsplit(r.url).path
        if r.method not in ('GET','HEAD','OPTIONS'): route.fulfill(status=409,json={'error':'review_read_only'})
        elif path=='/memory/index/status': route.fulfill(json={'status':'rebuilding','count':1,'healthy':True,'job':job})
        elif path=='/memory/index/rebuild/review-job':
            polls.append({'hash':page.url.split('#')[-1]}); route.fulfill(json={'status':'ok','index_status':'rebuilding','job':job})
        elif path=='/memory/docs': doc_reads.append(page.url.split('#')[-1]); route.fulfill(json={'docs':[doc]})
        elif path=='/memory/overview': route.fulfill(json=overview)
        elif path=='/memory/operations': route.fulfill(json={'operations':[]})
        elif path=='/memory/candidates': route.fulfill(json={'candidates':[]})
        else: route.continue_()
    page.route('**/*',protect)
    page.goto('http://127.0.0.1:48945/#/w/default/memory',wait_until='domcontentloaded')
    page.locator('.memory-panel').wait_for(state='visible',timeout=30000)
    page.wait_for_function("()=>document.body.innerText.includes('Synthetic review memory')")
    page.wait_for_timeout(900)
    page.evaluate("location.hash='/w/default/settings?section=summary'")
    page.locator('.settings-panel').wait_for(state='visible',timeout=30000)
    before=len(polls)
    page.wait_for_timeout(1700)
    hidden_polls=len(polls)-before
    reads_before=len(doc_reads)
    page.evaluate("location.hash='/w/default/memory?edit=review-doc'")
    page.locator('.memory-panel').wait_for(state='visible')
    page.wait_for_timeout(600)
    dialogs=page.locator('.el-dialog:visible').count()
    reads_return=len(doc_reads)-reads_before
    result={'hidden_memory_rebuild_reads_in_1700ms':hidden_polls,'reads_while_returning_cached_memory':reads_return,'edit_deep_link_opened_dialog':dialogs>0,'pageerrors':errors,'polls':polls}
    assert hidden_polls == 0, result
    assert reads_return >= 1, result
    assert dialogs > 0, result
    assert not errors, result
    print(json.dumps(result,ensure_ascii=True),flush=True)
    (OUT/'memory-cache.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    context.close(); browser.close()
