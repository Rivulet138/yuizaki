"""Verify route loading feedback and KeepAlive DOM identity in the real browser."""
import asyncio, json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright
OUT=Path(__file__).resolve().parent
async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True)
        context=await browser.new_context(viewport={'width':1440,'height':900})
        await context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
        page=await context.new_page(); errors=[]; request_paths=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        async def protect(route):
            request=route.request; path=urlsplit(request.url).path
            request_paths.append(path)
            if request.method not in ('GET','HEAD','OPTIONS'):
                await route.fulfill(status=409,json={'error':'performance_read_only'})
            elif '/assets/PromptPanel-' in path and path.endswith('.js'):
                await asyncio.sleep(1.5); await route.continue_()
            else: await route.continue_()
        await page.route('**/*',protect)
        await page.goto('http://127.0.0.1:38945/#/w/default/settings?section=summary',wait_until='domcontentloaded')
        await page.locator('.settings-panel').wait_for(state='visible',timeout=30000)
        await page.evaluate("()=>{window.__cachedSettings=document.querySelector('.settings-panel')}")
        await page.evaluate("location.hash='/w/default/prompt'")
        await page.locator('.navigation-progress').wait_for(state='visible',timeout=3000)
        feedback=await page.locator('.navigation-progress').inner_text()
        await page.locator('.prompt-panel').wait_for(state='visible')
        await page.locator('.navigation-progress').wait_for(state='detached')
        await page.evaluate("location.hash='/w/default/chat'")
        await page.locator('.chat-workspace').wait_for(state='visible')
        await page.evaluate("()=>{window.__cachedStage=document.querySelector('.browser-stage')}")
        await page.evaluate("location.hash='/w/default/settings?section=summary'")
        await page.locator('.settings-panel').wait_for(state='visible')
        assert await page.evaluate("()=>document.querySelector('.settings-panel')===window.__cachedSettings"), 'settings remounted across chat'
        before=request_paths.count('/api/pet/catalog')
        await page.wait_for_timeout(2800)
        assert request_paths.count('/api/pet/catalog')==before, 'hidden stage keeps polling catalog'
        await page.evaluate("location.hash='/w/default/chat'")
        await page.locator('.chat-workspace').wait_for(state='visible')
        assert await page.evaluate("()=>document.querySelector('.browser-stage')===window.__cachedStage"), 'stage remounted'
        await page.evaluate("location.hash='/w/default/settings?section=summary'")
        await page.locator('.settings-panel').wait_for(state='visible')
        await page.set_viewport_size({'width':390,'height':844})
        await page.wait_for_timeout(150)
        overflow=await page.evaluate('document.documentElement.scrollWidth-innerWidth')
        assert overflow==0, overflow
        assert not errors, errors
        result={'settings_retained_across_chat':True,'stage_retained_across_panels':True,'hidden_stage_catalog_polling':False,'loading_feedback':feedback,'compact_overflow':overflow,'pageerrors':errors}
        (OUT/'browser-interactions.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=True))
        await context.close(); await browser.close()
asyncio.run(main())
