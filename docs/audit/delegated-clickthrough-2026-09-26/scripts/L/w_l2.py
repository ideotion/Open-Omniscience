import re

from lib import cells, junk_scan, session, shot, sub, tab, tip

GLOBE = "\U0001F310"


def flag_of(label):
    ch = label.strip().split(" ")[0]
    return ch


with session("L2") as (page, rec):
    tab(page, "agenda")
    page.wait_for_function("() => document.querySelectorAll('#agenda-country option').length > 1", timeout=30000)
    opts = page.eval_on_selector_all("#agenda-country option", "els => els.map(e => [e.value, e.textContent.trim()])")
    rec.obs["country_options_n"] = len(opts)
    rec.obs["country_options_first12"] = opts[:12]
    bad = []
    names = []
    for v, lbl in opts[1:]:
        m = re.match(r"^(\S+)\s+(.*)\s\(([A-Z]{3})\)$", lbl)
        if not m:
            bad.append(lbl)
            continue
        flag, name, code = m.groups()
        names.append(name)
        is_globe = flag == GLOBE
        if code == "INT" and not is_globe:
            bad.append("INT without globe: " + lbl)
        if code != "INT" and is_globe:
            bad.append("globe on non-INT: " + lbl)
    rec.obs["country_options_bad"] = bad
    rec.obs["country_options_sorted_by_name"] = names == sorted(names, key=lambda s: s)  # approx; en locale
    rec.obs["country_options_all"] = [o[1] for o in opts]
    rec.obs["eu_option"] = [o for o in opts if "(EUU)" in o[1]]
    rec.obs["int_option"] = [o for o in opts if "(INT)" in o[1]]
    # List view
    sub(page, "agenda-views", "list")
    page.wait_for_timeout(1500)
    def showing():
        try:
            return page.locator("#agenda-list p.hint").first.inner_text()
        except Exception:
            return None
    rec.obs["list_before"] = showing()
    fr_val = next((v for v, l in opts if "(FRA)" in l), None)
    rec.obs["picked"] = fr_val
    page.select_option("#agenda-country", fr_val)
    page.wait_for_timeout(1200)
    rec.obs["list_after_pick_FRA"] = showing()
    pills_fra = page.eval_on_selector_all("#agenda-list .ag-row span.pill[title]", "els => els.map(e => e.textContent.trim())")
    rec.obs["pills_after_pick"] = sorted(set(pills_fra))
    page.select_option("#agenda-country", "")
    page.wait_for_timeout(1000)
    rec.obs["list_after_reset"] = showing()
    # group by country
    page.select_option("#agenda-group", "country")
    page.wait_for_timeout(1500)
    heads = page.eval_on_selector_all("#agenda-list h3", "els => els.map(e => ({t: e.innerText.trim(), span: e.querySelector('span[title], span.oo-tip-target') ? (e.querySelector('span[title]')||{}).getAttribute && e.querySelector('span[title]').getAttribute('title') : null}))")
    rec.obs["group_heads"] = heads
    hs = page.locator("#agenda-list h3 > span.oo-tip-target")
    rec.obs["group_head_tip_first"] = tip(page, hs.first) if hs.count() else None
    inth = page.locator("#agenda-list h3 > span", has_text=re.compile("^INT$"))
    rec.obs["group_head_tip_INT"] = tip(page, inth.first) if inth.count() else "no INT group"
    if inth.count():
        shot(page, "L2-group-INT-tip-en")
    # event pill
    pills = page.locator("#agenda-list .ag-row span.pill.oo-tip-target")
    rec.obs["event_pill_n"] = pills.count()
    pl = cells(page, "#agenda-list .ag-row span.pill.oo-tip-target")
    rec.obs["event_pill_codes"] = sorted(set(p["text"] for p in pl))
    rec.obs["event_pill_bad"] = [p for p in pl if not re.fullmatch(r"[A-Z]{3}", p["text"]) and p["text"] not in ()][:5]
    rec.obs["event_pill_deco"] = pl[0]["deco"] if pl else None
    # hover one pill that is a country code
    for i in range(min(pills.count(), 40)):
        t = pills.nth(i).inner_text().strip()
        if re.fullmatch(r"[A-Z]{3}", t):
            rec.obs["event_pill_tip"] = [t, tip(page, pills.nth(i))]
            shot(page, "L2-pill-tip-en")
            break
    # INT events carry no pill? count INT group rows with pills
    rec.obs["INT_pill_present"] = page.locator("#agenda-list .ag-row span.pill", has_text=re.compile("^INT$")).count()
    # corner dot for pill: pseudo-element check
    rec.obs["pill_after_css"] = page.evaluate("""() => { const p = document.querySelector('#agenda-list .ag-row span.pill.oo-tip-target');
        if (!p) return null; const s = getComputedStyle(p, '::after'); return {content: s.content, w: s.width, bg: s.backgroundColor, deco: getComputedStyle(p).textDecorationLine}; }""")
    junk_scan(page, rec, "#tab-agenda", "Agenda")
    shot(page, "L2-list-country-en")
    # reset group-by to month (view choice is the only persisted thing)
    page.select_option("#agenda-group", "month")
    # Settings -> Advanced -> Calendar directory
    page.click("button[onclick=\"showTab('settings')\"]") if page.locator("button[onclick=\"showTab('settings')\"]").count() else tab(page, "settings")
    page.wait_for_timeout(1200)
    sub(page, "set-subtabs", "advanced")
    page.click("details[data-adv='calendars'] > summary")
    page.wait_for_timeout(2500)
    try:
        page.wait_for_selector("#agenda-feeds .cs-row", timeout=20000)
    except Exception as e:  # noqa: BLE001
        rec.notes.append(f"calendar directory rows not seen: {e}")
    grey = page.eval_on_selector_all("#agenda-feeds .cs-row summary span.muted", "els => els.slice(0,12).map(e => e.innerText.trim())")
    rec.obs["dir_grey_lines"] = grey
    dc = page.locator("#agenda-feeds .cs-row summary span.muted span.oo-tip-target")
    rec.obs["dir_code_n"] = dc.count()
    if dc.count():
        rec.obs["dir_code_tip"] = [dc.first.inner_text(), tip(page, dc.first)]
        shot(page, "L2-directory-tip-en")
    allc = page.eval_on_selector_all("#agenda-feeds .cs-row summary span.muted span", "els => els.map(e => e.innerText.trim())")
    rec.obs["dir_codes_bad"] = [c for c in allc if not re.fullmatch(r"[A-Z]{3}", c)][:10]
    junk_scan(page, rec, "#agenda-feeds", "Calendar directory")
    print({k: v for k, v in rec.obs.items() if k != "country_options_all"})
