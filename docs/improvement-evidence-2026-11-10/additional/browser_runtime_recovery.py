"""Exercise new runtime recovery and backup provenance on the built browser UI."""
import json
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    context.add_init_script("localStorage.setItem('yuizaki.onboarding.completed.v1','true')")
    page = context.new_page()
    errors, blocked, retries, reads = [], [], [], []
    network = []
    page.on("request", lambda request: network.append({"request": urlsplit(request.url).path}) if "/api/" in request.url else None)
    page.on("response", lambda response: network.append({"response": urlsplit(response.url).path, "status": response.status}) if "/api/" in response.url else None)
    state = {"retried": False}
    page.on("pageerror", lambda error: errors.append(str(error)))

    def protect(route):
        request = route.request
        pathname = urlsplit(request.url).path
        if pathname == "/api/settings/runtime/status":
            reads.append(pathname)
            route.fulfill(json={"sections": {"svc": {
                "state": "applied" if state["retried"] else "failed", "target_revision": 7,
                "applied_revision": 7 if state["retried"] else None,
                "error": None if state["retried"] else "runtime_reload_failed",
            }}})
        elif pathname == "/api/settings/runtime/retry":
            retries.append(request.post_data_json)
            assert retries[-1] == {"targets": {"svc": 7}}, retries
            state["retried"] = True
            route.fulfill(json={"sections": {"svc": {
                "state": "applying", "target_revision": 7, "applied_revision": None, "error": None,
            }}})
        elif pathname == "/api/system/backup/targets":
            route.fulfill(json={"source": "configured_offline", "targets": []})
        elif request.method not in ("GET", "HEAD", "OPTIONS"):
            blocked.append({"method": request.method, "path": pathname})
            route.fulfill(status=409, json={"error": "acceptance_read_only"})
        else:
            route.continue_()

    page.route("**/*", protect)
    page.goto("http://127.0.0.1:38945/#/w/default/settings", wait_until="domcontentloaded")
    panel = page.locator(".el-alert").filter(has_text="\u670d\u52a1\u5e94\u7528\u72b6\u6001").first
    try:
        panel.wait_for(state="visible", timeout=20000)
    except Exception:
        print(json.dumps({"phase":"initial_panel", "url":page.url, "reads":reads, "network":network, "alerts":page.locator(".el-alert").all_inner_texts(), "headings":page.locator("h1,h2").all_inner_texts(), "errors":errors},ensure_ascii=True),flush=True)
        raise
    try:
        panel.get_by_role("button", name="\u91cd\u8bd5\u5f53\u524d\u914d\u7f6e", exact=True).wait_for(state="visible", timeout=12000)
    except Exception:
        print(json.dumps({"phase":"failed_wait", "status_reads":reads, "alerts":page.locator(".el-alert").all_inner_texts(), "errors":errors}, ensure_ascii=True))
        raise
    before = panel.inner_text()
    panel.get_by_role("button", name="\u91cd\u8bd5\u5f53\u524d\u914d\u7f6e", exact=True).click()
    try:
        page.wait_for_function("() => [...document.querySelectorAll('.el-alert')].some(e => e.textContent.includes('\\u670d\\u52a1\\u5df2\\u5e94\\u7528'))", timeout=10000)
    except Exception:
        print(json.dumps({"phase":"after_retry", "reads":reads, "retries":retries,"panel":panel.inner_text(),"network":network,"errors":errors},ensure_ascii=True),flush=True)
        raise
    after = panel.inner_text()
    assert len(retries) == 1, retries
    assert len(reads) >= 2, reads
    assert panel.get_by_role("button", name="\u91cd\u8bd5\u5f53\u524d\u914d\u7f6e", exact=True).count() == 0
    page.screenshot(path=str(OUT / "settings-runtime-recovery.png"))
    page.evaluate("location.hash='/w/default/infrastructure'")
    warning = page.get_by_text("\u5f53\u524d\u6309\u672c\u5730\u914d\u7f6e\u89e3\u6790\u5907\u4efd\u8def\u5f84", exact=False)
    warning.first.wait_for(state="visible", timeout=30000)
    result = {"retry_payloads": retries, "status_reads": len(reads), "before": before, "after": after,
              "backup_provenance": warning.first.inner_text(), "pageerrors": errors, "blocked_real_mutations": blocked,
              "assets": page.locator("script[src]").evaluate_all("es=>es.map(e=>e.getAttribute('src'))")}
    assert not errors, errors
    (OUT / "browser-runtime-recovery.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    browser.close()
