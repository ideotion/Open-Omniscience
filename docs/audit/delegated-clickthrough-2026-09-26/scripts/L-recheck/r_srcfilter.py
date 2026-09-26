import re
from lib import session, shot, sub, tab, tip

with session("R-srcfilter") as (page, rec):
    tab(page, "settings")
    sub(page, "set-subtabs", "advanced")
    page.click("details[data-adv='sources'] > summary")
    page.wait_for_selector("#src-table tr td", timeout=30000)
    page.wait_for_function("() => document.querySelectorAll('#src-msel-country .msel-opt').length > 10", timeout=30000)
    page.click("#src-msel-country > summary")
    page.wait_for_timeout(800)
    opts = page.eval_on_selector_all("#src-msel-country .msel-opt", "els => els.map(e => [e.querySelector('input').value, e.innerText.replace(/\\s+/g,' ').trim()])")
    rec.obs["country_filter_n"] = len(opts)
    rec.obs["country_filter_not_alpha3"] = [o for o in opts if not re.search(r"\([A-Z]{3}\)", o[1])]
    va = page.locator("#src-msel-country .msel-opt", has_text=re.compile(r"Vatican"))
    if va.count():
        va.first.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shot(page, "R1-src-filter-vatican-en")
    # table row for a va source: hover
    if va.count():
        va.first.locator("input").check()
    page.wait_for_timeout(1500)
    page.click("#src-msel-country > summary")
    page.wait_for_timeout(500)
    rec.obs["closed_label_va"] = page.locator("#src-msel-country > summary").inner_text().strip()
    c = page.locator("#src-table tr td:nth-child(4) span").first
    if c.count():
        rec.obs["va_table_cell"] = [c.inner_text(), c.get_attribute("title"), tip(page, c)]
        shot(page, "R1-src-table-va-tip-en")
    print(rec.obs)
