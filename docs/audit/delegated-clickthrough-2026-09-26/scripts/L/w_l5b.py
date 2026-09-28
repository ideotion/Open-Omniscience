import re

from lib import session, shot, sub, tab

with session("L5b") as (page, rec):
    tab(page, "library")
    sub(page, "library-views", "coverage")
    page.wait_for_selector("#coverage-table tr td", timeout=60000)
    page.wait_for_timeout(2000)
    fra = page.locator("#coverage-table tr td strong", has=page.locator("span", has_text=re.compile("^FRA$"))).first
    fra.click()
    seq = []
    for i in range(8):
        page.wait_for_timeout(1000)
        seq.append({
            "t": i + 1,
            "hash": page.evaluate("() => location.hash"),
            "label": page.locator("#src-msel-country > summary").inner_text(),
            "checked": page.eval_on_selector_all("#src-msel-country .msel-list input:checked", "els => els.map(e => e.value)"),
            "n_opts": page.locator("#src-msel-country .msel-list input").count(),
            "meta": page.locator("#src-meta").inner_text(),
            "adv_sources_open": page.evaluate("() => !!document.querySelector(\"details[data-adv='sources']\")?.open"),
            "set_advanced_visible": page.locator("#set-advanced").is_visible() if page.locator("#set-advanced").count() else None,
        })
    rec.obs["seq"] = seq
    page.locator("#src-table").scroll_into_view_if_needed()
    shot(page, "L5-click-FRA-sources-state-en")
    # open the filter to see
    page.click("#src-msel-country > summary")
    page.wait_for_timeout(600)
    rec.obs["checked_after_open"] = page.eval_on_selector_all("#src-msel-country .msel-list input:checked", "els => els.map(e => e.value)")
    print(rec.obs)
