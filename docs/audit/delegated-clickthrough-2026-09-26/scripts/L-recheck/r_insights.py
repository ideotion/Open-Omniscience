import re
from lib import cells, session, shot, sub, tab, tip

with session("R-insights") as (page, rec):
    tab(page, "insights")
    sub(page, "ins-subtabs", "map")
    page.fill("#map-days", "3650")
    page.click("#ins-map button[onclick='loadMap()']")
    page.wait_for_function("() => document.querySelectorAll('#map-countries tr').length > 1", timeout=30000)
    page.wait_for_timeout(1000)
    rec.obs["by_country_first_col"] = page.eval_on_selector_all("#map-countries tr td:first-child", "els => els.map(e => [e.innerText.trim(), !!e.querySelector('[title]')])")
    rec.obs["api_countries"] = page.evaluate("() => fetch('/api/insights/map?days=3650&kind=all').then(r=>r.json()).then(d => d.countries.map(c => Object.keys(c).join('/') + ':' + c.code).slice(0,4))")
    c1 = page.locator("#map-countries tr td:first-child strong").first
    rec.obs["hover_first"] = tip(page, c1, tries=2)
    page.locator("#map-countries").scroll_into_view_if_needed()
    shot(page, "R2-insights-by-country-en")
    sub(page, "ins-subtabs", "supergroups")
    page.wait_for_selector("#sg-concept-supers button.lvl-super", timeout=30000)
    page.locator("#sg-concept-supers button.lvl-super").first.click()
    page.wait_for_timeout(1500)
    rec.obs["group_chips"] = page.eval_on_selector_all("#sg-concept-groups button.lvl-group", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")[:6]
    g = page.locator("#sg-concept-groups button.lvl-group").filter(has_text=re.compile(r"voting"))
    if g.count():
        g.first.click()
    else:
        page.locator("#sg-concept-groups button.lvl-group").first.click()
    page.wait_for_timeout(5000)
    det = page.locator("#sg-ringmap-detail").inner_text()
    rec.obs["lang_lines"] = re.findall(r"(?:Languages|By language)[^\n]*", det)
    rec.obs["lang_titles"] = page.eval_on_selector_all("#sg-ringmap-detail [title]", "els => els.map(e => [e.innerText.trim().slice(0,30), e.getAttribute('title').slice(0,60)])")[:8]
    page.locator("#sg-ringmap-detail").scroll_into_view_if_needed()
    shot(page, "R10-concept-map-langs-en")
    print(rec.obs)
