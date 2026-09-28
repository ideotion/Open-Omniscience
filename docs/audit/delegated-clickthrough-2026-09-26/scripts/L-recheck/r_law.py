import re
from lib import close_guide, session, set_lang, shot, sub, tab, tip

def law_tips(page, codes):
    out = {}
    for code in codes:
        loc = page.locator("#law-docs tbody tr td:first-child span", has_text=re.compile(f"^{code}$")).first
        out[code] = [loc.get_attribute("title") if loc.count() else None, tip(page, loc) if loc.count() else "ABSENT"]
    return out

with session("R-law") as (page, rec):
    tab(page, "law")
    sub(page, "gov-subtabs", "law")
    page.wait_for_selector("#law-docs tbody tr", timeout=30000)
    page.wait_for_timeout(1000)
    rec.obs["en"] = law_tips(page, ["GBR", "DEU", "EUU"])
    rec.obs["changes_feed_en"] = page.eval_on_selector_all("#law-changes b span, #law-changes span[title]", "els => els.slice(0,4).map(e => [e.innerText.trim(), e.getAttribute('title')])")
    for lang in ["fr", "zh"]:
        set_lang(page, lang)
        page.wait_for_timeout(2000)
        rec.obs[f"bare_{lang}"] = law_tips(page, ["GBR", "DEU", "EUU"])
        rec.obs[f"bare_{lang}_changes"] = page.eval_on_selector_all("#law-changes span[title]", "els => els.slice(0,4).map(e => [e.innerText.trim(), e.getAttribute('title')])")
        if lang == "fr":
            loc = page.locator("#law-docs tbody tr td:first-child span", has_text=re.compile("^DEU$")).first
            loc.hover(); page.wait_for_timeout(400)
            shot(page, "R15-law-bare-switch-fr")
    # re-open the subtab (tab away and back) without reload
    tab(page, "home")
    tab(page, "law")
    sub(page, "gov-subtabs", "law")
    page.wait_for_timeout(2000)
    rec.obs["zh_after_tab_away_back"] = law_tips(page, ["DEU"])
    # Home law card in zh (bare switch) then after reload
    tab(page, "home")
    page.wait_for_timeout(3000)
    rec.obs["home_law_card_zh"] = page.eval_on_selector_all("#tab-home *", "els => els.filter(e => e.children.length===0 && /\\((fr|FRA)\\)/.test(e.textContent)).map(e => e.textContent.trim().slice(0,120)).slice(0,5)")
    set_lang(page, "fr")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("#navGroups .nav-item", timeout=60000)
    page.wait_for_timeout(3500)
    close_guide(page)
    rec.obs["html_lang_after_reload"] = page.evaluate("() => document.documentElement.lang")
    tab(page, "home")
    page.wait_for_timeout(3000)
    rec.obs["home_law_card_fr"] = page.eval_on_selector_all("#tab-home *", "els => els.filter(e => e.children.length===0 && /\\((fr|FRA)\\)/.test(e.textContent)).map(e => e.textContent.trim().slice(0,120)).slice(0,5)")
    lc = page.locator("#tab-home :text-matches('Law changed|Loi modifi', 'i')").first
    if lc.count():
        lc.scroll_into_view_if_needed(); page.wait_for_timeout(300)
        shot(page, "R6-home-law-card-fr")
    rec.obs["briefing_api"] = page.evaluate("() => fetch('/api/briefing').then(r=>r.json()).then(d => JSON.stringify(d).match(/Law changed[^\"]{0,80}/g)).catch(e=>String(e))")
    set_lang(page, "en")
    print(rec.obs)
