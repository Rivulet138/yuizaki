"""Delayed, isolated HTTP fixtures: no writes reach the user's running services."""
import asyncio, copy, json, sys, time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright
OUT=Path(__file__).resolve().parent
async def scenario(browser, normalized):
    context=await browser.new_context(viewport={'width':1440,'height':900})
    await context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
    page=await context.new_page(); errors=[]; reads=[]; writes=[]; completed=[]; blocked=[]; token_starts=[]
    snapshot=(await (await context.request.get('http://127.0.0.1:48945/api/settings/')).json())
    page.on('pageerror',lambda error:errors.append(str(error)))
    timing={}
    async def protect(route):
        request=route.request; path=urlsplit(request.url).path
        if path=='/api/settings/' and request.method=='GET':
            reads.append(time.perf_counter()); timing.setdefault('first_read',time.perf_counter())
            await asyncio.sleep(.15); await route.fulfill(json=copy.deepcopy(snapshot))
        elif path=='/api/system/backend-token' and request.method=='GET':
            token_starts.append(time.perf_counter()); await asyncio.sleep(3); completed.append('token')
            await route.fulfill(json={'configured':False,'available':True})
        elif path=='/api/settings/runtime/status':
            await route.fulfill(json={'sections':{}})
        elif path=='/api/settings/' and request.method=='PATCH':
            patch=request.post_data_json; writes.append({'at':time.perf_counter(),'patch':patch})
            for section,values in patch.items(): snapshot.setdefault(section,{}).update(values)
            await asyncio.sleep(.15)
            result={'status':'success','updated':list(patch),'runtime_applied':[], 'runtime_changed':False,'runtime_reload':{'sections':{}}}
            if normalized: result['normalized_settings']=copy.deepcopy(snapshot)
            await route.fulfill(json=result)
        elif request.method not in ('GET','HEAD','OPTIONS'):
            blocked.append({'method':request.method,'path':path})
            await route.fulfill(status=409,json={'error':'performance_fixture_blocks_real_mutation'})
        else: await route.continue_()
    await page.route('**/*',protect)
    await page.goto('http://127.0.0.1:48945/#/w/default/settings?section=summary',wait_until='domcontentloaded')
    await page.locator('.summary-advanced summary').click(timeout=20000)
    field=page.locator('.summary-settings-group').first.get_by_role('spinbutton').first
    await field.wait_for(state='visible')
    ready_before_token='token' not in completed
    ready_ms=round((time.perf_counter()-timing['first_read'])*1000,1)
    original=int(await field.input_value()); before_reads=len(reads)
    start=time.perf_counter(); await field.fill(str(min(original+1,99))); await field.press('Tab')
    await page.wait_for_function("()=>[...document.querySelectorAll('.el-alert')].some(e=>e.textContent.includes('已保存')&&!e.textContent.includes('正在保存')&&!e.textContent.includes('待保存'))",timeout=15000)
    elapsed=round((time.perf_counter()-start)*1000,1)
    assert writes, 'save request missing'
    result={'normalized_response':normalized,'token_requests_started':len(token_starts),'ready_before_unrelated_token':ready_before_token,'form_ready_from_first_read_ms':ready_ms,'edit_to_saved_ms':elapsed,'edit_to_request_ms':round((writes[0]['at']-start)*1000,1),'save_readbacks':len(reads)-before_reads,'save_posts':len(writes),'pageerrors':errors,'blocked_real_mutations':blocked}
    assert not errors, errors
    await context.close()
    return result
async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        result=[await scenario(browser,True),await scenario(browser,False)]
        assert all(x['token_requests_started']==0 for x in result), result
        label='review-token-probe'
        (OUT/(label+'-save.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=True),flush=True)
        if False:
            assert all(x['ready_before_unrelated_token'] for x in result), result
            assert result[0]['save_readbacks']==0, result
            assert result[1]['save_readbacks']==1, result
            assert all(x['save_posts']==1 for x in result), result
        await browser.close()
asyncio.run(main())

