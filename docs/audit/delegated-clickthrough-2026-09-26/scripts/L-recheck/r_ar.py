from lib import session, shot, sub, tab
with session("R-ar", lang="ar") as (page, rec):
    rec.obs["lang"] = page.evaluate("() => [document.documentElement.lang, document.documentElement.dir]")
    tab(page, "settings")
    sub(page, "set-subtabs", "advanced")
    page.click("details[data-adv='sources'] > summary")
    page.wait_for_selector("#src-table tr td", timeout=30000)
    page.wait_for_timeout(2500)
    rec.obs["headers"] = page.eval_on_selector_all("#src-table tr:first-child th", "els => els.map(e => e.innerText.trim())")
    rec.obs["meta"] = page.locator("#src-meta").inner_text()
    rec.obs["unmanaged"] = page.locator("#unmanaged-lang-panel").inner_text()[:200] if page.locator("#unmanaged-lang-panel").count() else None
    page.locator("#src-table").scroll_into_view_if_needed()
    shot(page, "R17-sources-ar")
    print(rec.obs)
