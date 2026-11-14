"""Real Vue/KeepAlive/Element Plus regression against the copied, isolated review harness."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

OUTPUT = Path(__file__).resolve().parent
ORIGIN = "http://127.0.0.1:48957/"

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors, blocked = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def isolate(route):
        request = route.request
        if request.url.startswith(ORIGIN) and request.method in ("GET", "HEAD", "OPTIONS"):
            route.continue_()
        else:
            blocked.append({"url": request.url, "method": request.method})
            route.abort()

    page.route("**/*", isolate)
    result = {"origin": ORIGIN, "browser": browser.version}

    def snapshot():
        return page.evaluate("""() => ({
            route: reviewRouter.currentRoute.value.name,
            memoryInBody: !!document.querySelector('.memory-panel'),
            visibleDialogs: document.querySelectorAll('.el-dialog').length && [...document.querySelectorAll('.el-dialog')].filter(el => el.getBoundingClientRect().width > 0).length,
            visibleDrawers: [...document.querySelectorAll('.el-drawer')].filter(el => el.getBoundingClientRect().width > 0).length,
            visibleOverlays: [...document.querySelectorAll('.el-overlay')].filter(el => el.getBoundingClientRect().width > 0 && getComputedStyle(el).visibility !== 'hidden').length,
            bodyClass: document.body.className,
            bodyOverflow: getComputedStyle(document.body).overflow,
            bodyWidth: document.body.style.width,
            activeTag: document.activeElement?.tagName,
            activeId: document.activeElement?.id,
            focusInMemoryOverlay: !!document.activeElement?.closest('.el-dialog, .el-drawer'),
            otherClicks,
            atOtherButton: (() => {
                const el = document.querySelector('#other-action');
                if (!el) return null;
                const rect = el.getBoundingClientRect();
                const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
                return {hit: hit?.className, covered: hit !== el};
            })(),
        })""")

    def deactivate(label):
        page.evaluate("reviewRouter.push('/w/fixture/other')")
        page.locator('#other-action').wait_for(state='visible')
        page.wait_for_function("""() => !document.body.classList.contains('el-popup-parent--hidden')
            && ![...document.querySelectorAll('.el-overlay')].some(el => el.getBoundingClientRect().width > 0)""")
        current = snapshot()
        result[label + '_deactivated'] = current
        assert current['route'] == 'other' and not current['memoryInBody'], current
        assert current['visibleDialogs'] == current['visibleDrawers'] == current['visibleOverlays'] == 0, current
        assert current['bodyOverflow'] != 'hidden' and current['bodyWidth'] == '', current
        assert not current['focusInMemoryOverlay'] and not current['atOtherButton']['covered'], current
        before = page.evaluate('otherClicks')
        page.locator('#other-action').click(timeout=1500)
        expect(page.locator('#other-action')).to_be_focused()
        page.keyboard.press('Space')
        assert page.evaluate('otherClicks') == before + 2
        result[label + '_other_pointer_and_keyboard'] = snapshot()
        page.screenshot(path=str(OUTPUT / (label + '-deactivated.png')))

    def return_to_memory():
        page.evaluate("reviewRouter.push('/w/fixture/memory')")
        page.locator('.memory-panel').wait_for(state='visible')
        expect(page.locator('.el-dialog:visible')).to_have_count(0)
        expect(page.locator('.el-drawer:visible')).to_have_count(0)

    def open_drawer():
        page.locator('[data-testid="memory-advanced-tools-toggle"]').click()
        page.get_by_role('menuitem', name='memoryPanel.advancedIndexTools', exact=True).click()
        page.locator('.el-drawer:visible').wait_for()

    page.goto(ORIGIN, wait_until='networkidle')
    dialog_text = page.locator('.el-dialog:visible textarea').first
    dialog_text.fill('UNSAVED DIALOG DRAFT')
    result['edit_open'] = snapshot()
    assert result['edit_open']['focusInMemoryOverlay']
    deactivate('edit')
    return_to_memory()
    page.locator('[data-testid="memory-inspector"]').get_by_text('memoryView.inspectorMore', exact=True).click()
    page.get_by_role('button', name='memoryView.editAllFields', exact=True).click()
    dialog_text = page.locator('.el-dialog:visible textarea').first
    expect(dialog_text).to_have_value('UNSAVED DIALOG DRAFT')
    result['edit_return_draft'] = dialog_text.input_value()
    page.locator('.el-dialog:visible').get_by_role('button', name='memoryPanel.cancel', exact=True).click()
    page.wait_for_function("() => !document.body.classList.contains('el-popup-parent--hidden')")

    open_drawer()
    query = page.locator('.el-drawer:visible [data-testid="memory-query-input"]')
    query.fill('UNSAVED RECALL QUERY')
    result['advanced_open'] = snapshot()
    assert result['advanced_open']['focusInMemoryOverlay']
    deactivate('advanced')
    return_to_memory()
    open_drawer()
    expect(query).to_have_value('UNSAVED RECALL QUERY')
    result['advanced_return_draft'] = query.input_value()
    # A second cache/deactivate cycle catches stale lock/focus ownership on reopen.
    deactivate('advanced_second_cycle')
    result['pageerrors'] = errors
    result['blocked_requests'] = blocked
    assert not errors and not blocked, (errors, blocked)
    result['passed'] = True
    (OUTPUT / 'browser-after.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2, ensure_ascii=True))
    browser.close()
