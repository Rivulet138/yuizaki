import json,tempfile,os
from playwright.sync_api import sync_playwright,TimeoutError
with sync_playwright() as p:
 b=p.chromium.launch(headless=True)
 page=b.new_page(viewport={'width':1440,'height':900})
 errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.route('**/*',lambda r:r.continue_() if r.request.url.startswith('http://127.0.0.1:48957/') and r.request.method in ('GET','HEAD','OPTIONS') else r.abort())
 page.goto('http://127.0.0.1:48957/',wait_until='networkidle')
 page.locator('.el-dialog:visible textarea').first.fill('UNSAVED DIALOG DRAFT')
 def snapshot():
  return page.evaluate('''()=>({route:reviewRouter.currentRoute.value.name,memoryInBody:!!document.querySelector('.memory-panel'),visibleDialogs:[...document.querySelectorAll('.el-dialog')].filter(x=>x.getBoundingClientRect().width>0).length,visibleDrawers:[...document.querySelectorAll('.el-drawer')].filter(x=>x.getBoundingClientRect().width>0).length,bodyClass:document.body.className,bodyOverflow:getComputedStyle(document.body).overflow,activeTag:document.activeElement?.tagName,activeText:document.activeElement?.textContent?.slice(0,80),atOtherButton:(()=>{const e=document.querySelector('#other-action');if(!e)return null;const r=e.getBoundingClientRect();const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return {hit:hit?.className,covered:hit!==e}})()})''')
 result={'edit_open':snapshot()}
 page.evaluate("reviewRouter.push('/w/fixture/other')")
 page.locator('#other-action').wait_for(state='attached');page.wait_for_timeout(350)
 result['edit_deactivated']=snapshot()
 try:page.locator('#other-action').click(timeout=1200);result['edit_other_click']='success'
 except TimeoutError as e:result['edit_other_click']='intercepted: '+str(e)[-500:]
 page.evaluate("reviewRouter.push('/w/fixture/memory')")
 page.locator('.memory-panel').wait_for(state='visible');page.wait_for_timeout(350)
 result['edit_return_draft']=page.locator('.el-dialog:visible textarea').first.input_value()
 page.locator('.el-dialog:visible').get_by_role('button',name='memoryPanel.cancel',exact=True).click()
 page.wait_for_timeout(350)
 page.locator('[data-testid="memory-advanced-tools-toggle"]').click()
 page.get_by_role('menuitem',name='memoryPanel.advancedIndexTools',exact=True).click()
 page.locator('.el-drawer:visible').wait_for();page.wait_for_timeout(350)
 result['advanced_open']=snapshot()
 page.evaluate("reviewRouter.push('/w/fixture/other')")
 page.locator('#other-action').wait_for(state='attached');page.wait_for_timeout(350)
 result['advanced_deactivated']=snapshot()
 try:page.locator('#other-action').click(timeout=1200);result['advanced_other_click']='success'
 except TimeoutError as e:result['advanced_other_click']='intercepted: '+str(e)[-500:]
 screenshot=os.path.join(os.path.dirname(__file__),'before-memory-deactivated-drawer.png')
 page.screenshot(path=screenshot)
 result['screenshot']=screenshot;result['pageerrors']=errors
 print(json.dumps(result,ensure_ascii=True,indent=2));b.close()
