import re
import sys

from lib import close_guide, enter, junk_scan, session, set_lang, shot, sub, tab, tip

LANG = sys.argv[1]
LAWCODES = ["GBR", "DEU", "EUU", "INT", "CAN", "FRA"]


def law_tips(page):
    tab(page, "law")
    sub(page, "gov-subtabs", "law")
    page.wait_for_selector("#law-docs tbody tr", timeout=30000)
    page.wait_for_timeout(1000)
    out = {}
    for code in LAWCODES:
        loc = page.locator("#law-docs tbody tr td:first-child span", has_text=re.compile(f"^{code}$")).first
        out[code] = [loc.inner_text() if loc.count() else None, tip(page, loc) if loc.count() else "ABSENT"]
    return out


with session(f"L13-{LANG}") as (page, rec):
    # optional pre-reload glance: en law hover, then a BARE switch
    rec.obs["pre_en"] = law_tips(page)
    set_lang(page, LANG)
    page.wait_for_timeout(1500)
    rec.obs["bare_switch_law"] = {c: tip(page, page.locator("#law-docs tbody tr td:first-child span", has_text=re.compile(f"^{c}$")).first) for c in ["GBR", "DEU", "EUU"]}
    # bare-switch agenda + sources state (for the frozen-locale note)
    # RELOAD
    page.reload(wait_until="domcontentloaded")
    enter.__wrapped__(page, rec) if hasattr(enter, "__wrapped__") else None
    page.wait_for_selector("#navGroups .nav-item", timeout=60000)
    page.wait_for_timeout(2500)
    close_guide(page)
    rec.obs["html_lang_dir"] = page.evaluate("() => [document.documentElement.lang, document.documentElement.dir]")
    rec.obs["law"] = law_tips(page)
    shot(page, f"L13-law-{LANG}")
    loc = page.locator("#law-docs tbody tr td:first-child span", has_text=re.compile("^EUU$")).first
    loc.hover()
    page.wait_for_timeout(400)
    shot(page, f"L13-law-EUU-tip-{LANG}")
    rec.obs["law_headers"] = page.eval_on_selector_all("#law-docs thead th", "els => els.map(e => e.innerText.trim())")
    junk_scan(page, rec, "#gov-law", f"Law [{LANG}]")
    # Agenda
    tab(page, "agenda")
    page.wait_for_function("() => document.querySelectorAll('#agenda-country option').length > 1", timeout=30000)
    ao = page.eval_on_selector_all("#agenda-country option", "els => els.map(e => e.textContent.trim())")
    rec.obs["agenda_opts_first8"] = ao[:8]
    rec.obs["agenda_opts_all"] = ao
    names = [re.sub(r"^\S+\s+", "", x) for x in ao[1:]]
    names = [re.sub(r"\s*\([A-Z]{3}\)$", "", x) for x in names]
    rec.obs["agenda_order_mismatch"] = page.evaluate("""([names, lc]) => { const c = new Intl.Collator(lc);
        const s = names.slice().sort(c.compare); const bad=[]; for (let i=0;i<names.length;i++) if (names[i]!==s[i]) bad.push([i,names[i],s[i]]); return bad.slice(0,5); }""", [names, LANG])
    rec.obs["agenda_codes_ok"] = all(re.search(r"\([A-Z]{3}\)$", x) for x in ao[1:])
    page.locator("#agenda-country").scroll_into_view_if_needed()
    shot(page, f"L13-agenda-{LANG}")
    junk_scan(page, rec, "#tab-agenda", f"Agenda [{LANG}]")
    # Sources filters
    tab(page, "settings")
    sub(page, "set-subtabs", "advanced")
    page.click("details[data-adv='sources'] > summary")
    page.wait_for_selector("#src-table tr td", timeout=30000)
    page.wait_for_timeout(1500)
    tc = page.locator("#src-table tr td:nth-child(4) span").first
    rec.obs["src_table_country_tip"] = [tc.inner_text(), tip(page, tc)]
    tl = page.locator("#src-table tr td:nth-child(5) span").first
    rec.obs["src_table_lang_tip"] = [tl.inner_text(), tip(page, tl)]
    page.click("#src-msel-country > summary")
    page.wait_for_timeout(800)
    co = page.eval_on_selector_all("#src-msel-country .msel-opt", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")
    rec.obs["src_country_first8"] = co[:8]
    rec.obs["src_country_ARM"] = [x for x in co if "ARM" in x]
    cn = [re.sub(r"\s*\((?:[A-Z]{3}|[a-z]{2})\).*$", "", x) for x in co]
    rec.obs["src_country_order_mismatch"] = page.evaluate("""([names, lc]) => { const c = new Intl.Collator(lc);
        const s = names.slice().sort(c.compare); const bad=[]; for (let i=0;i<names.length;i++) if (names[i]!==s[i]) bad.push([i,names[i],s[i]]); return bad.slice(0,5); }""", [cn, LANG])
    shot(page, f"L13-src-country-filter-{LANG}")
    page.click("#src-msel-country > summary")
    page.click("#src-msel-language > summary")
    page.wait_for_timeout(800)
    lo = page.eval_on_selector_all("#src-msel-language .msel-opt", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")
    rec.obs["src_lang_first8"] = lo[:8]
    shot(page, f"L13-src-lang-filter-{LANG}")
    page.click("#src-msel-language > summary")
    junk_scan(page, rec, "details[data-adv='sources']", f"Sources [{LANG}]")
    # Governments map in this locale
    tab(page, "law")
    sub(page, "gov-subtabs", "map")
    page.wait_for_timeout(2500)
    try:
        page.select_option("#gov-map-ind", "SP.POP.TOTL")
        page.wait_for_timeout(3000)
    except Exception:
        pass
    gm = {}
    for iso in ["fr", "de"]:
        l = page.locator(f"#gov-map-host path[data-iso='{iso}']").first
        if l.count():
            gm[iso] = l.evaluate("e => (e.querySelector('title')||{}).textContent")
    rec.obs["gov_map_titles"] = gm
    # Home law card
    tab(page, "home")
    page.wait_for_timeout(3000)
    rec.obs["home_law_card"] = page.eval_on_selector_all("#tab-home *", "els => els.filter(e => e.children.length===0 && /\\(fr\\)|\\(FRA\\)|Law changed|Loi modifiée/.test(e.textContent)).map(e => e.textContent.trim().slice(0,120)).slice(0,5)")
    if LANG == "en":
        pass
    print(rec.obs)
