import re
from lib import cells, close_guide, session, shot, sub, tab, tip

with session("R-gov") as (page, rec):
    # Minerals supply
    tab(page, "markets")
    page.wait_for_timeout(3000)
    ms = page.locator("#mkt-minerals-supply")
    ms.scroll_into_view_if_needed()
    page.wait_for_timeout(1500)
    rec.obs["minerals_area_cells"] = page.eval_on_selector_all("#mkt-minerals-supply table tbody tr td:first-child", "els => els.map(e => [e.innerText.trim(), !!e.querySelector('[title]') || e.hasAttribute('title')])")
    rec.obs["minerals_caveat"] = page.locator("#mkt-minerals-supply .hint").first.inner_text()[:300]
    shot(page, "R9-minerals-supply-en")
    # Gov consent popup reason
    tab(page, "law")
    sub(page, "gov-subtabs", "countries")
    page.wait_for_timeout(3000)
    close_guide(page)
    page.locator("#gov-load-btn").scroll_into_view_if_needed()
    page.click("#gov-load-btn")
    page.wait_for_selector("#net-consent-ok", state="visible", timeout=10000)
    rec.obs["consent_reason_html"] = page.locator("#net-consent-reason").inner_html()
    rec.obs["consent_reason_text"] = page.locator("#net-consent-reason").inner_text()
    shot(page, "R5-consent-no-action-en")
    page.click("#net-consent-cancel")
    page.wait_for_timeout(1200)
    rec.obs["online_after_cancel"] = page.evaluate("() => fetch('/api/system/network').then(r => r.json()).then(d => d.online)")
    # for comparison: another gated button's reason (markets fetch) -- open and cancel
    # Gov map XKX
    sub(page, "gov-subtabs", "map")
    page.wait_for_timeout(2500)
    page.select_option("#gov-map-ind", "SP.POP.TOTL")
    page.wait_for_timeout(3500)
    t = {}
    for iso in ["xk", "fr"]:
        loc = page.locator(f"#gov-map-host path[data-iso='{iso}'], #gov-map-host circle[data-iso='{iso}']").first
        if loc.count():
            try: loc.hover(timeout=3000, force=True)
            except Exception: pass
            t[iso] = loc.evaluate("e => (e.querySelector('title')||{}).textContent")
    rec.obs["gov_map_titles"] = t
    # worldview picker on this ooMap
    rec.obs["worldview_opts"] = page.eval_on_selector_all("#gov-map-host select[data-oomap-worldview] option", "els => els.map(e => [e.value, e.textContent.trim()])")
    # Groups computed Europe population
    sub(page, "gov-subtabs", "groups")
    page.wait_for_timeout(2500)
    page.click("#gov-lens button[data-lens='computed']")
    page.wait_for_timeout(2500)
    go = page.eval_on_selector_all("#gov-grp-pick option", "els => els.map(e => [e.value, e.textContent.trim()])")
    pick = next((v for v, l in go if l == "Europe"), None)
    page.select_option("#gov-grp-pick", pick)
    page.wait_for_timeout(1000)
    page.select_option("#gov-grp-ind", "SP.POP.TOTL")
    page.wait_for_timeout(4000)
    body = page.locator("#gov-grp-body").inner_text()
    rec.obs["grp_refusal"] = re.findall(r"\d+ of \d+ members did not report[^\n]*", body)[:1]
    rec.obs["grp_missing"] = re.findall(r"[Mm]issing[^\n]*", body)[:2]
    rec.obs["grp_range"] = re.findall(r"Range across[^\n]*", body)[:1]
    page.locator("#gov-grp-body").scroll_into_view_if_needed()
    shot(page, "R8-groups-computed-refusal-en")
    # Statistics level map
    sub(page, "gov-subtabs", "statistics")
    page.wait_for_timeout(2000)
    rec.obs["stat_placeholders"] = page.evaluate("() => [document.getElementById('statfig-country').placeholder, document.getElementById('statfig-view-area').placeholder]")
    page.fill("#statfig-view-series", "NY.GDP.MKTP.CD")
    page.check("#statfig-map-level")
    page.click("#gov-statistics button[onclick='renderStatMap()']")
    page.wait_for_timeout(5000)
    aggs = {}
    for code in ["WLD", "HIC", "EAS", "EUU", "XKX", "FRA"]:
        loc = page.locator("#statfig-map table tr td span", has_text=re.compile(f"^{code}$")).first
        if loc.count():
            aggs[code] = [loc.get_attribute("title"), tip(page, loc)]
    rec.obs["stat_area_tips"] = aggs
    page.locator("#statfig-map").scroll_into_view_if_needed()
    shot(page, "R13-statistics-aggregate-tips-en")
    print(rec.obs)
