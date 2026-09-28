import re
from lib import cells, junk_scan, session, shot, sub, tab, tip

with session("L10") as (page, rec):
    tab(page, "indices")
    page.wait_for_timeout(4000)
    board = page.locator("#idx-board")
    rec.obs["idx_cats"] = page.eval_on_selector_all("#indices-cats button", "els => els.map(e => e.innerText.trim())")
    rec.obs["idx_board_all_text"] = board.inner_text()[:1500]
    rec.obs["idx_titled"] = page.eval_on_selector_all("#idx-board [title]", "els => els.slice(0,10).map(e => [e.innerText.trim().slice(0,50), e.getAttribute('title').slice(0,80)])")
    rec.obs["idx_codes_in_text"] = sorted(set(re.findall(r"\b[A-Z]{3}\b", board.inner_text())))[:30]
    shot(page, "L10-indices-all-en")
    eu = page.locator("#indices-cats button", has_text=re.compile("Europe"))
    if eu.count():
        eu.first.click()
        page.wait_for_timeout(2500)
        rec.obs["idx_board_europe_text"] = board.inner_text()[:1200]
        shot(page, "L10-indices-europe-en")
    junk_scan(page, rec, "#tab-indices", "Indices")
    tab(page, "markets")
    page.wait_for_timeout(4000)
    ms = page.locator("#mkt-minerals-supply")
    ms.scroll_into_view_if_needed()
    page.wait_for_timeout(1500)
    rec.obs["minerals_text"] = ms.inner_text()[:1200]
    areas = page.eval_on_selector_all("#mkt-minerals-supply table tbody tr td:first-child", "els => els.map(e => [e.innerText.trim(), !!e.querySelector('[title]') || e.hasAttribute('title')])")
    rec.obs["minerals_area_cells"] = areas
    shot(page, "L10-minerals-supply-en")
    junk_scan(page, rec, "#mkt-minerals-supply", "Minerals supply")
    # optional: Configure data sources -> feed table grey lines
    h = page.locator("text=Configure data sources").first
    if h.count():
        h.click()
        page.wait_for_timeout(3000)
        rec.obs["feed_grey"] = page.eval_on_selector_all("#feed-table tr td:first-child .muted, #feed-table tr td:first-child div.hint", "els => els.slice(0,10).map(e => e.innerText.trim())")
        rec.obs["feed_rows_first"] = page.eval_on_selector_all("#feed-table tr", "els => els.slice(0,6).map(e => e.innerText.replace(/\\s+/g,' ').trim().slice(0,160))")
    print(rec.obs)
