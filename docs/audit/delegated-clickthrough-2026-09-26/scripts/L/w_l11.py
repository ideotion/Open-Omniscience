import re

from lib import cells, junk_scan, session, shot, sub, tab, tip


def opts(page, sel):
    return page.eval_on_selector_all(f"{sel} option", "els => els.map(e => [e.value, e.textContent.trim()])")


def check_picker(page, sel):
    o = opts(page, sel)
    labs = [x[1] for x in o]
    bad = [l for l in labs if not re.search(r"\([A-Z]{3}\)$", l)]
    names = [re.sub(r"\s*\([A-Z]{3}\)$", "", l) for l in labs]
    order_bad = page.evaluate("""(names) => { const c = new Intl.Collator(document.documentElement.lang||'en');
        const s = names.slice().sort(c.compare); const bad=[]; for (let i=0;i<names.length;i++) if (names[i]!==s[i]) bad.push([i,names[i],s[i]]); return bad.slice(0,5); }""", names)
    return {"n": len(o), "first": labs[:6], "not_name_code": bad[:10], "order_mismatch": order_bad}


with session("L11") as (page, rec):
    tab(page, "law")
    sub(page, "gov-subtabs", "countries")
    page.wait_for_timeout(4000)
    rec.obs["countries_picker"] = check_picker(page, "#gov-country")
    rec.obs["countries_data_head"] = page.locator("#gov-country-data").inner_text()[:500]
    junk_scan(page, rec, "#gov-countries", "Gov>Countries")
    shot(page, "L11-countries-en")
    # consent popup for 'Load standard country data' -> Stay offline
    from lib import close_guide
    close_guide(page)
    page.locator("#gov-load-btn").scroll_into_view_if_needed()
    page.click("#gov-load-btn")
    try:
        page.wait_for_selector("#net-consent-ok", state="visible", timeout=10000)
        rec.obs["consent_reason"] = page.locator("#net-consent-reason").inner_text()
        rec.obs["consent_body"] = page.locator("#net-consent-body").inner_text()[:700]
        shot(page, "L11-consent-load-standard-en")
        page.click("#net-consent-cancel")
        page.wait_for_timeout(1500)
        rec.obs["after_cancel_btn"] = page.locator("#gov-load-btn").inner_text()
        rec.obs["online_after_cancel"] = page.evaluate("() => fetch('/api/system/network').then(r => r.json()).catch(e => String(e))")
    except Exception as e:  # noqa: BLE001
        rec.obs["consent_err"] = str(e)[:300]
    # Compare
    sub(page, "gov-subtabs", "compare")
    page.wait_for_timeout(3000)
    rec.obs["cmp_a"] = check_picker(page, "#gov-cmp-a")
    rec.obs["cmp_b"] = check_picker(page, "#gov-cmp-b")
    rec.obs["compare_text"] = page.locator("#gov-compare").inner_text()[:500]
    junk_scan(page, rec, "#gov-compare", "Gov>Compare")
    # Map
    sub(page, "gov-subtabs", "map")
    page.wait_for_timeout(3000)
    rec.obs["map_ind_opts"] = [x[1] for x in opts(page, "#gov-map-ind")][:8]
    ind = [x[0] for x in opts(page, "#gov-map-ind") if x[0] == "SP.POP.TOTL"]
    if ind:
        page.select_option("#gov-map-ind", "SP.POP.TOTL")
        page.wait_for_timeout(3500)
    host = "#gov-map-host"
    t = {}
    for iso in ["fr", "de", "us", "xk", "gb"]:
        loc = page.locator(f"{host} path[data-iso='{iso}'], {host} circle[data-iso='{iso}']").first
        if loc.count():
            try:
                loc.hover(timeout=3000, force=True)
            except Exception:
                pass
            t[iso] = loc.evaluate("e => (e.querySelector('title')||{}).textContent")
    rec.obs["map_titles"] = t
    rec.obs["map_host_text"] = page.locator(host).inner_text()[:300]
    shot(page, "L11-gov-map-en")
    de = page.locator(f"{host} path[data-iso='de']").first
    if de.count():
        bb = de.bounding_box()
        page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
        page.wait_for_timeout(3000)
        rec.obs["after_map_click_view_visible"] = page.locator("#gov-countries").is_visible()
        rec.obs["after_map_click_country"] = page.evaluate("() => { const s = document.getElementById('gov-country'); return s ? [s.value, s.options[s.selectedIndex] && s.options[s.selectedIndex].textContent] : null; }")
    junk_scan(page, rec, "#gov-map", "Gov>Map")
    # Groups -> published aggregates + computed
    sub(page, "gov-subtabs", "groups")
    page.wait_for_timeout(3000)
    rec.obs["agg_opts"] = [x[1] for x in opts(page, "#gov-agg-pick")][:12]
    rec.obs["agg_body"] = page.locator("#gov-agg-body").inner_text()[:500]
    shot(page, "L11-groups-published-en")
    page.click("#gov-lens button[data-lens='computed']")
    page.wait_for_timeout(2500)
    go = opts(page, "#gov-grp-pick")
    rec.obs["grp_opts"] = [x[1] for x in go][:15]
    pick = next((v for v, l in go if re.search(r"\bG7\b|G20|European Union|OECD", l)), None)
    if pick:
        page.select_option("#gov-grp-pick", pick)
        page.wait_for_timeout(1000)
    gi = opts(page, "#gov-grp-ind")
    if any(v == "SP.POP.TOTL" for v, _ in gi):
        page.select_option("#gov-grp-ind", "SP.POP.TOTL")
    page.wait_for_timeout(3500)
    body = page.locator("#gov-grp-body").inner_text()
    rec.obs["grp_pick"] = pick
    rec.obs["grp_body"] = body[:1500]
    rec.obs["grp_code_spans_with_title"] = page.eval_on_selector_all("#gov-grp-body [title]", "els => els.slice(0,10).map(e => [e.innerText.trim().slice(0,40), e.getAttribute('title').slice(0,60)])")
    m = re.findall(r"Range across reporting members[^\n]*", body)
    rec.obs["grp_range_line"] = m[:2]
    rec.obs["grp_two_letter_tokens"] = sorted(set(re.findall(r"\b[a-z]{2}\b", body)))[:20]
    page.locator("#gov-grp-body").scroll_into_view_if_needed()
    shot(page, "L11-groups-computed-en")
    junk_scan(page, rec, "#gov-groups", "Gov>Groups")
    # Statistics
    sub(page, "gov-subtabs", "statistics")
    page.wait_for_timeout(2000)
    rec.obs["stat_placeholders"] = page.evaluate("() => [document.getElementById('statfig-country').placeholder, document.getElementById('statfig-view-area').placeholder]")
    page.fill("#statfig-view-series", "NY.GDP.MKTP.CD")
    page.check("#statfig-map-level")
    page.click("#gov-statistics button[onclick='renderStatMap()']")
    page.wait_for_timeout(5000)
    rec.obs["stat_map_meta"] = page.locator("#statfig-map-meta").inner_text()[:400]
    rec.obs["stat_map_text"] = page.locator("#statfig-map").inner_text()[:900]
    rows = page.eval_on_selector_all("#statfig-map table tr", "els => els.map(e => Array.from(e.children).map(c => c.innerText.trim()))")
    rec.obs["stat_table_rows"] = rows[:14]
    area = cells(page, "#statfig-map table tr td span.oo-tip-target")
    rec.obs["stat_area_cells"] = area[:12]
    aggs = {}
    for code in ["WLD", "HIC", "EUU", "EAS", "FRA", "XKX"]:
        loc = page.locator("#statfig-map table tr td span", has_text=re.compile(f"^{code}$")).first
        if loc.count():
            aggs[code] = tip(page, loc)
    rec.obs["stat_area_tips"] = aggs
    page.locator("#statfig-map").scroll_into_view_if_needed()
    shot(page, "L11-statistics-level-table-en")
    junk_scan(page, rec, "#gov-statistics", "Gov>Statistics")
    print(rec.obs)
