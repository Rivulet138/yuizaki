from pathlib import Path
import json
from playwright.sync_api import sync_playwright
OUT=Path(__file__).resolve().parent
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    context=browser.new_context(viewport={"width":390,"height":844})
    context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
    page=context.new_page()
    errors=[]
    page.on("pageerror",lambda error:errors.append(str(error)))
    page.route("**/*",lambda route:route.continue_() if route.request.method in ("GET","HEAD","OPTIONS") else route.fulfill(status=409,json={"error":"acceptance_read_only","message":"验收禁止修改用户数据"}))
    page.goto("http://127.0.0.1:38945/#/w/default/chat",wait_until="domcontentloaded")
    page.get_by_placeholder("输入消息",exact=True).fill("临时验收草稿，不会发送")
    button=page.locator(".send-button")
    button.focus()
    result=button.evaluate("e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,uncovered:e.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2)),focused:document.activeElement===e}}")
    result.update({"width":390,"height":844,"pageerrors":errors,"currentScriptAssets":page.locator("script[src]").evaluate_all("es=>es.map(e=>e.getAttribute('src'))")})
    assert result["left"]>=0 and result["right"]<=390 and result["top"]>=0 and result["bottom"]<=844,result
    assert result["uncovered"] and result["focused"] and not errors,result
    assert page.locator(".workspace-save-floating").count()==0
    page.screenshot(path=str(OUT/"chat-390.png"))
    (OUT/"browser-chat-final.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=True))
    context.close();browser.close()
