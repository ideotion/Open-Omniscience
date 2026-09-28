from lib import cells, junk_scan, session, shot, sub, tab, tip

with session("L8b") as (page, rec):
    tab(page, "insights")
    sub(page, "ins-subtabs", "supergroups")
    page.wait_for_selector("#sg-concept-supers button.lvl-super", timeout=30000)
    page.locator("#sg-concept-supers button.lvl-super").first.click()
    page.wait_for_timeout(1500)
    g = page.locator("#sg-concept-groups button.lvl-group")
    rec.obs["group_chips"] = page.eval_on_selector_all("#sg-concept-groups button.lvl-group", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")[:10]
    import re
    g.filter(has_text=re.compile(r"voting")).first.click()
    page.wait_for_timeout(5000)
    det = page.locator("#sg-ringmap-detail")
    rec.obs["concept_detail_text"] = det.inner_text()[:900]
    rec.obs["ringmap_text"] = page.locator("#sg-ringmap").inner_text()[:300]
    rec.obs["ringmap_paths_with_data"] = page.eval_on_selector_all("#sg-ringmap path[data-iso]", "els => els.filter(e => !(e.getAttribute('fill')||'').includes('nodata')).map(e => (e.querySelector('title')||{}).textContent)")[:8]
    cd = cells(page, "#sg-ringmap-detail table td span")
    rec.obs["concept_country_cells"] = cd[:10]
    if cd:
        rec.obs["concept_country_tip"] = [cd[0]["text"], tip(page, page.locator("#sg-ringmap-detail table td span").first)]
    det.scroll_into_view_if_needed()
    shot(page, "L8-concept-map-en")
    junk_scan(page, rec, "#ins-supergroups", "Insights>Super-groups")
    print(rec.obs)
