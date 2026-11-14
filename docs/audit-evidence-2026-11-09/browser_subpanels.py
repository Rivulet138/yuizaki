from playwright.sync_api import sync_playwright,TimeoutError as PWTimeout
from pathlib import Path
from urllib.parse import urlsplit
import json
OUT=Path(r'E:\yuizaki\docs\audit-evidence-2026-11-09')
with sync_playwright() as p:
 b=p.chromium.launch(headless=True);c=b.new_context(viewport={'width':1440,'height':900});c.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')");page=c.new_page();fail=[];exceptions=[];tabs=[];responsive=[];active=['bootstrap']
 page.on('response',lambda r:fail.append({'route':active[0],'path':urlsplit(r.url).path,'status':r.status,'method':r.request.method}) if r.status>=400 else None)
 page.on('pageerror',lambda e:exceptions.append({'route':active[0],'message':str(e)}))
 page.goto('http://127.0.0.1:38945/#/w/default/settings',wait_until='domcontentloaded');page.wait_for_selector('.settings-section-button',timeout=45000)
 for route in ['settings','memory','tool','agent-governance','agent-trace']:
  active[0]=route;page.goto('http://127.0.0.1:38945/#/w/default/'+route,wait_until='domcontentloaded');page.wait_for_timeout(1400)
  loc=page.locator('.settings-section-button') if route=='settings' else page.get_by_role('tab')
  names=loc.evaluate_all('(es)=>es.filter(e=>e.getClientRects().length).map(e=>({id:e.id,label:e.textContent.trim()}))')
  for item in names:
   if route=='settings':target=page.locator('.settings-section-button').filter(has_text=item['label']).first
   elif item['id']:target=page.locator('[id="'+item['id']+'"]')
   else:target=page.get_by_role('tab',name=item['label'],exact=True).first
   if not target.is_visible():continue
   target.click();page.wait_for_timeout(650)
   info=page.evaluate('''()=>({headings:[...document.querySelectorAll('h2,h3')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()),errors:[...document.querySelectorAll('.async-error,.el-alert--error,.el-message--error')].filter(e=>e.getClientRects().length).map(e=>e.textContent.trim()),overflow:document.documentElement.scrollWidth-innerWidth,loading:document.querySelectorAll('.async-state--loading').length})''')
   tabs.append({'route':route,'tab':item['label'],**info})
  print(json.dumps({'route':route,'testedTabs':[x['tab'] for x in tabs if x['route']==route]},ensure_ascii=True),flush=True)
 for width in [768,390]:
  page.set_viewport_size({'width':width,'height':844})
  for route in ['chat','memory','settings']:
   active[0]=route;page.goto('http://127.0.0.1:38945/#/w/default/'+route,wait_until='domcontentloaded');page.wait_for_timeout(800)
   info=page.evaluate('''()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,overflow:document.documentElement.scrollWidth-innerWidth,offscreen:[...document.querySelectorAll('main,nav,aside,section,textarea,[role="tablist"],.el-select,.settings-content-tabs')].filter(e=>e.getClientRects().length).map(e=>({tag:e.tagName,class:e.className,x:Math.round(e.getBoundingClientRect().x),right:Math.round(e.getBoundingClientRect().right),width:Math.round(e.getBoundingClientRect().width)})).filter(e=>e.x<0||e.right>innerWidth+2)})''')
   responsive.append({'route':route,**info})
 report={'tabs':tabs,'responsive':responsive,'failedResponses':fail,'pageerrors':exceptions};(OUT/'browser-subpanels.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'responsive':responsive,'failures':fail,'exceptions':exceptions},ensure_ascii=True),flush=True);c.close();b.close()
