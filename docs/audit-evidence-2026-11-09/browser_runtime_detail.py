from playwright.sync_api import sync_playwright,TimeoutError as PWTimeout
from pathlib import Path
import json,time
from urllib.parse import urlsplit
OUT=Path(r'E:\yuizaki\docs\audit-evidence-2026-11-09')
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True)
 context=browser.new_context(viewport={'width':1440,'height':900})
 context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
 page=context.new_page(); logs=[]; failed=[];responses=[]
 page.on('requestfailed',lambda r:failed.append({'host':urlsplit(r.url).netloc,'path':urlsplit(r.url).path,'error':r.failure}))
 page.on('pageerror',lambda e:logs.append(str(e)))
 def res(r):
  u=urlsplit(r.url)
  if '/api/' in u.path or '/system/' in u.path or '/memory/' in u.path:
   responses.append({'host':u.netloc,'path':u.path,'status':r.status})
 page.on('response',res)
 page.goto('http://127.0.0.1:38945/#/w/default/settings',wait_until='domcontentloaded')
 page.wait_for_timeout(20000)
 settings=page.evaluate("() => ({text:document.body.innerText, tabs:[...document.querySelectorAll('[role=tab]')].map(e=>e.textContent),async:[...document.querySelectorAll('.async-state,.async-error')].map(e=>e.textContent?.trim()),host:document.querySelector('[data-route-name]')?.getAttribute('data-route-name')})")
 safe=page.evaluate('''async()=>{const token=document.querySelector('meta[name="yuizaki-control-token"]')?.content;return await Promise.all(['/api/ping','/api/health','/api/onboarding/snapshot','/api/ui-capabilities','/api/route-manifest'].map(async(path)=>{try {const r=await fetch(path,{headers:token?{Authorization:'Bearer '+token}:{},signal:AbortSignal.timeout(8000)});const d=await r.json();return {path,status:r.status,keys:Object.keys(d),...(path==='/api/onboarding/snapshot'?{snapshot:{operation:d.operation,readyForText:d.readyForText,probes:d.probes?.map(x=>({id:x.id,status:x.status,message:x.message,messageCode:x.messageCode}))}}:{}),...(path==='/api/ping'?{ping:d}:{})};}catch(e){return {path,error:e.name}}}))}''')
 page.screenshot(path=str(OUT/'settings-after-20s.png'),full_page=True)
 report={'settings':settings,'runtime':safe,'responses':responses,'requestFailed':failed,'pageerrors':logs}
 (OUT/'browser-runtime-detail.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(report,ensure_ascii=True),flush=True)
 context.close();browser.close()
