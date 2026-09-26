"""Recheck: defects 1 (calendar directory + sources filter), 7 (closed filter label), 14 (hint)."""
import re
from lib import cells, session, shot, sub, tab, tip

with session("R-settings") as (page, rec):
    tab(page, "settings")
    sub(page, "set-subtabs", "advanced")
    page.click("details[data-adv='calendars'] > summary")
    page.wait_for_selector("#agenda-feeds .cs-row", timeout=30000)
    page.wait_for_timeout(2000)
    allc = page.eval_on_selector_all("#agenda-feeds .cs-row summary span.muted span", "els => els.map(e => [e.innerText.trim(), e.getAttribute('title')])")
    rec.obs["dir_codes_n"] = len(allc)
    rec.obs["dir_codes_not_alpha3"] = sorted({tuple(c) for c in allc if not re.fullmatch(r"[A-Z]{3}", c[0])})
    for code in ["AX", "AI", "VA"]:
        loc = page.locator("#agenda-feeds .cs-row summary span.muted span", has_text=re.compile(f"^{code}$")).first
        if loc.count():
            rec.obs[f"dir_{code}_tip"] = tip(page, loc)
            if code == "AX":
                shot(page, "R1-directory-AX-tip-en")
    # what the API holds for AX feeds
    rec.obs["feed_api_sample"] = page.evaluate("""() => fetch('/api/events/feeds').then(r => r.json()).then(d => {
        const rows = (d.feeds || d || []); const arr = Array.isArray(rows) ? rows : (rows.feeds||[]);
        return arr.filter(f => ['AX','ax','AI','ai','VA','va'].includes(f.country)).slice(0,4).map(f => [f.name, f.country]); }).catch(e => String(e))""")
    page.click("details[data-adv='calendars'] > summary")
    page.wait_for_timeout(500)
    page.click("details[data-adv='sources'] > summary")
    page.wait_for_selector("#src-table tr td", timeout=30000)
    page.wait_for_timeout(1500)
    page.click("#src-msel-country > summary")
    page.wait_for_timeout(800)
    opts = page.eval_on_selector_all("#src-msel-country .msel-opt", "els => els.map(e => [e.querySelector('input').value, e.innerText.replace(/\\s+/g,' ').trim()])")
    rec.obs["country_filter_n"] = len(opts)
    rec.obs["country_filter_not_alpha3"] = [o for o in opts if not re.search(r"\([A-Z]{3}\)", o[1])]
    va = page.locator("#src-msel-country .msel-opt", has_text=re.compile(r"Vatican"))
    if va.count():
        va.first.scroll_into_view_if_needed()
        shot(page, "R1-src-filter-vatican-en")
    # tick France, close, read label
    fr = page.locator("#src-msel-country .msel-opt", has_text=re.compile(r"^\s*France \(FRA\)"))
    fr.first.locator("input").check()
    page.wait_for_timeout(1500)
    page.click("#src-msel-country > summary")
    page.wait_for_timeout(800)
    rec.obs["country_closed_label_FRA"] = page.locator("#src-msel-country > summary").inner_text().strip()
    rec.obs["meta_after_FRA"] = page.locator("#src-meta").inner_text()
    rec.obs["rows_after_FRA"] = sorted(set(page.eval_on_selector_all("#src-table tr td:nth-child(4)", "els => els.map(e => e.innerText.trim())")))
    page.click("#src-msel-language > summary")
    page.wait_for_timeout(800)
    en = page.locator("#src-msel-language .msel-opt", has_text=re.compile(r"^\s*English \(eng\)"))
    en.first.locator("input").check()
    page.wait_for_timeout(1200)
    page.click("#src-msel-language > summary")
    page.wait_for_timeout(600)
    rec.obs["lang_closed_label_eng"] = page.locator("#src-msel-language > summary").inner_text().strip()
    page.locator("#src-msel-country").scroll_into_view_if_needed()
    shot(page, "R7-closed-filter-labels-en")
    page.click("button[onclick='clearSrcFilters()']")
    page.wait_for_timeout(1500)
    rec.obs["csv_hint"] = page.locator("#src-csv-hint").inner_text()
    # the CSV export as served (read the response the button opens)
    rec.obs["csv_rows_va_ck_ai"] = page.evaluate("""() => fetch('/api/catalog/export.csv').then(r => r.text()).then(t => {
        const lines = t.split(/\\r?\\n/); const head = lines[0].split(',');
        const out = lines.filter(l => /,(va|ck|ai|ax),/.test(l)).slice(0,5).map(l => l.slice(-60));
        return {head: head, sample: out}; })""")
    print(rec.obs)
