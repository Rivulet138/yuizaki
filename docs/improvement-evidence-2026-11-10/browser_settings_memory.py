from pathlib import Path
from urllib.parse import urlsplit
import json
from playwright.sync_api import sync_playwright

OUT=Path(__file__).resolve().parent
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={'width':1440,'height':900})
    context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
    page=context.new_page(); errors=[]; blocked=[]; tabs=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def protect(route):
        if route.request.method not in ('GET','HEAD','OPTIONS'):
            blocked.append(urlsplit(route.request.url).path)
            route.fulfill(status=409,json={'error':'acceptance_read_only'})
        else:route.continue_()
    page.route('**/*',protect)
    page.goto('http://127.0.0.1:38945/#/w/default/settings',wait_until='domcontentloaded')
    page.wait_for_selector('.settings-section-button',timeout=45000)
    labels=page.locator('.settings-section-button').all_text_contents()
    for label in labels:
        page.locator('.settings-section-button').filter(has_text=label.strip()).first.click()
        page.wait_for_timeout(200)
        tabs.append(label.strip())
    assert len(tabs)==10,tabs
    system_tab=page.locator('.settings-section-button').filter(has_text='系统').first
    system_tab.click()
    page.locator('.settings-admin-card .el-collapse-item__header').click()
    page.locator('input[placeholder="system.theme"]').fill('system.theme')
    page.locator('.settings-admin-card textarea').fill('{broken')
    before=list(blocked)
    page.locator('.settings-admin-card').get_by_role('button',name='写入',exact=True).click()
    page.wait_for_timeout(300)
    validation=page.locator('.settings-admin-card .el-alert--error').inner_text()
    assert 'JSON' in validation,validation
    assert not any('/settings/key' in path for path in blocked[len(before):]),blocked[len(before):]

    meta={'scope':'workspace','workspace_id':'default','layer':'semantic','type':'fact','review_status':'approved','importance':0.8}
    doc={'id':'acceptance-doc','text':'Synthetic acceptance memory','metadata':meta,'storage_status':'saved','index_status':'failed'}
    index={'status':'error','backend':'sqlite','healthy':True,'document_count':1,'metadata':{'authority':'sqlite','index_ready':False,'pending_index_count':1,'last_index_error':'synthetic_index_failure'}}
    overview={'total':1,'recallable':1,'by_state':{'active':1},'by_layer':{'semantic':1},'by_source':{'manual':1},'by_review_status':{'approved':1},'latest_activity':[],
              'by_index_status':{'failed':1},'recall_policy':{'scope':'workspace','inherited_scopes':[]},'integrity':{'orphan_session_ids':['synthetic-orphan'],'orphan_resolution':'explicit_assignment_required'},
              'deletion_scope':{'authority':'body_and_sensitive_metadata_removed','chat_history':'unchanged','summaries':'unchanged','backups':'unchanged'},'index_health':index}
    page.route('**/memory/overview**',lambda r:r.fulfill(json=overview))
    page.route('**/memory/index/status**',lambda r:r.fulfill(json=index))
    page.route('**/memory/docs**',lambda r:r.fulfill(json={'docs':[doc]}))
    page.route('**/memory/operations**',lambda r:r.fulfill(json={'operations':[]}))
    page.route('**/memory/candidates**',lambda r:r.fulfill(json={'candidates':[]}))
    page.route('**/memory/docs/delete-preview**',lambda r:r.fulfill(status=500,json={'detail':'synthetic_preflight_failure'}))
    page.evaluate('()=>{location.hash="/w/default/memory"}')
    page.wait_for_selector('[data-memory-id="acceptance-doc"]',timeout=15000)
    status=page.locator('.storage-status').inner_text()
    assert 'synthetic_index_failure' in status,status
    assert 'explicit_assignment_required' in page.locator('.storage-status').text_content()
    page.locator('[data-memory-id="acceptance-doc"]').click()
    editor=page.locator('textarea[data-testid="memory-inspector-text"], [data-testid="memory-inspector-text"] textarea')
    editor.fill('Unsaved synthetic draft')
    doc['text']='New remote synthetic version'
    page.get_by_test_id('memory-refresh').click()
    page.wait_for_timeout(500)
    assert editor.input_value()=='Unsaved synthetic draft'
    page.locator('[data-testid="memory-inspector"] details.danger-zone > summary').click()
    page.get_by_test_id('memory-inspector-delete').click()
    page.wait_for_timeout(500)
    assert page.locator('.memory-panel > p[role="alert"]').count()>0
    assert page.locator('.memory-panel > p[role="alert"]').first.inner_text().strip()
    assert page.locator('.el-message-box').count()==0
    result={'settingsTabs':tabs,'invalidJson':{'blockedBeforeWrite':True,'error':validation},'memory':{'indexFailureVisible':True,'orphanDiagnosticVisible':True,'dirtyDraftPreserved':True,'preflightFailureVisible':True,'deletionNotSubmitted':True},'pageerrors':errors,'fixture':'synthetic memory responses; user writes intercepted'}
    assert not errors,errors
    (OUT/'browser-settings-memory.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True),flush=True)
    context.close();browser.close()
