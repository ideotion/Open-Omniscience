import re

from lib import cells, junk_scan, session, shot, sub, tab, tip

with session("L8") as (page, rec):
    tab(page, "insights")
    sub(page, "ins-subtabs", "map")
    page.fill("#map-days", "3650")
    page.click("#ins-map button[onclick='loadMap()']")
    page.wait_for_timeout(4000)
    rows = page.eval_on_selector_all("#map-countries tr", "els => els.map(e => Array.from(e.children).map(c => c.innerText.trim()))")
    rec.obs["by_country_rows"] = rows[:12]
    first_col = [r[0] for r in rows[1:]]
    rec.obs["by_country_first_col"] = first_col
    rec.obs["by_country_first_col_titles"] = page.eval_on_selector_all("#map-countries tr td:first-child", "els => els.map(e => [e.innerText.trim(), !!e.querySelector('[title]'), (e.querySelector('[title]')||{getAttribute:()=>null}).getAttribute('title')])")[:10]
    c1 = page.locator("#map-countries tr td:first-child strong").first
    rec.obs["by_country_hover_first"] = tip(page, c1, tries=2) if c1.count() else None
    page.locator("#map-countries").scroll_into_view_if_needed()
    shot(page, "L8-insights-by-country-en")
    rec.obs["by_city_rows"] = page.eval_on_selector_all("#map-cities tr", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")[:8]
    cc = page.locator("#map-cities tr td:first-child span.muted span.oo-tip-target")
    rec.obs["by_city_code_n"] = cc.count()
    if cc.count():
        rec.obs["by_city_code_tip"] = [cc.first.inner_text(), tip(page, cc.first)]
    junk_scan(page, rec, "#ins-map", "Insights>Map")
    # Super-groups: cross-country map of a concept
    sub(page, "ins-subtabs", "supergroups")
    page.wait_for_timeout(4000)
    chips = page.locator("#sg-concept-groups button, #sg-concept-supers button, #sg-concept-groups [onclick], #sg-concept-supers [onclick]")
    rec.obs["concept_chips"] = chips.count()
    rec.obs["concept_area_text"] = page.locator("#sg-concept-supers").inner_text()[:200] + " | " + page.locator("#sg-concept-groups").inner_text()[:300]
    rec.obs["sg_list_text"] = page.locator("#sg-list").inner_text()[:300]
    if chips.count():
        chips.first.click()
        page.wait_for_timeout(3500)
        # may be a super -> click a group chip
        g = page.locator("#sg-concept-groups button, #sg-concept-groups [onclick]")
        if not page.locator("#sg-ringmap-detail").inner_text().strip() and g.count():
            g.first.click()
            page.wait_for_timeout(3500)
        det = page.locator("#sg-ringmap-detail")
        rec.obs["concept_detail_text"] = det.inner_text()[:800]
        cd = cells(page, "#sg-ringmap-detail table td span")
        rec.obs["concept_country_cells"] = cd[:10]
        if cd:
            rec.obs["concept_country_tip"] = [cd[0]["text"], tip(page, page.locator("#sg-ringmap-detail table td span").first)]
        shot(page, "L8-concept-map-en")
        junk_scan(page, rec, "#ins-supergroups", "Insights>Super-groups")
    print(rec.obs)
