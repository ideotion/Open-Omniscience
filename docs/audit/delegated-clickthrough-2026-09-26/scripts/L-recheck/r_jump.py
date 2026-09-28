import re
from lib import session, shot, sub, tab

with session("R-jump") as (page, rec):
    reqs = []
    page.on("request", lambda r: reqs.append((round(page.evaluate("() => performance.now()") if False else 0), r.url.split('8824')[-1])) if ("/api/sources/facets" in r.url or "/api/catalog/sources" in r.url) else None)
    runs = []
    for attempt in range(3):
        tab(page, "library")
        sub(page, "library-views", "coverage")
        page.wait_for_selector("#coverage-table tr td", timeout=60000)
        page.wait_for_timeout(1500)
        reqs.clear()
        fra = page.locator("#coverage-table tr td strong", has=page.locator("span", has_text=re.compile("^FRA$"))).first
        fra.click()
        page.wait_for_timeout(5000)
        run = {
            "label": page.locator("#src-msel-country > summary").inner_text(),
            "checked": page.eval_on_selector_all("#src-msel-country .msel-list input:checked", "els => els.map(e => e.value)"),
            "meta": page.locator("#src-meta").inner_text(),
            "rows": sorted(set(page.eval_on_selector_all("#src-table tr td:nth-child(4)", "els => els.map(e => e.innerText.trim())"))),
            "reqs": [u for _, u in reqs],
        }
        runs.append(run)
        if attempt == 0:
            page.locator("#src-msel-country").scroll_into_view_if_needed()
            shot(page, "R3-jump-FRA-filter-Any-en")
        # now tick Germany to show the consequence
        if attempt == 2:
            page.click("#src-msel-country > summary")
            page.wait_for_timeout(600)
            de = page.locator("#src-msel-country .msel-opt", has_text=re.compile(r"^\s*Germany \(DEU\)"))
            de.first.locator("input").check()
            page.wait_for_timeout(2000)
            run["after_tick_DEU"] = {
                "label": page.locator("#src-msel-country > summary").inner_text(),
                "meta": page.locator("#src-meta").inner_text(),
                "rows": sorted(set(page.eval_on_selector_all("#src-table tr td:nth-child(4)", "els => els.map(e => e.innerText.trim())"))),
            }
        page.evaluate("() => { clearSrcFilters && 0; }")
    rec.obs["runs"] = runs
    print(rec.obs)
