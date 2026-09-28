import re
from lib import cells, junk_scan, session, shot, sub, tab, tip

with session("L9") as (page, rec):
    tab(page, "settings")
    sub(page, "set-subtabs", "wikipedia")
    page.wait_for_function("() => document.querySelectorAll('#wiki-lang option').length > 5", timeout=30000)
    info = page.evaluate("""() => { const s = document.getElementById('wiki-lang');
        return {tag: s.tagName, n: s.options.length, optgroups: s.querySelectorAll('optgroup').length,
                first: Array.from(s.options).slice(0,8).map(o => o.textContent.trim()),
                fr: Array.from(s.options).filter(o => o.value==='fr').map(o => o.textContent.trim()),
                de: Array.from(s.options).filter(o => o.value==='de').map(o => o.textContent.trim())}; }""")
    rec.obs["wiki_lang"] = info
    page.locator("#wiki-lang").scroll_into_view_if_needed()
    shot(page, "L9-wiki-edition-en")
    tab(page, "living")
    sub(page, "living-subtabs", "wiki")
    page.wait_for_timeout(3000)
    rows = page.eval_on_selector_all("#tab-living .living-row .living-row-head", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")
    rec.obs["wiki_rows"] = rows[:8]
    lp = cells(page, "#tab-living .living-row-head span.pill.oo-tip-target")
    rec.obs["wiki_pills"] = lp[:6]
    loc = page.locator("#tab-living .living-row-head span.pill.oo-tip-target")
    if loc.count():
        rec.obs["wiki_pill_tip"] = [loc.first.inner_text(), tip(page, loc.first)]
        shot(page, "L9-living-wiki-pill-en")
    junk_scan(page, rec, "#tab-living", "Living>Wikipedia")
    sub(page, "living-subtabs", "law")
    page.wait_for_timeout(3000)
    rows = page.eval_on_selector_all("#tab-living .living-row .living-row-head", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim())")
    rec.obs["law_rows"] = [r for r in rows][:8]
    lp = cells(page, "#tab-living .living-row-head span.pill.oo-tip-target")
    rec.obs["law_pills"] = [p for p in lp if re.fullmatch(r"[A-Z]{3}", p["text"])][:6]
    tips = {}
    for code in ["GBR", "EUU", "FRA"]:
        l = page.locator("#tab-living .living-row-head span.pill", has_text=re.compile(f"^{code}$")).first
        if l.count():
            tips[code] = tip(page, l)
            if code == "EUU":
                shot(page, "L9-living-law-EUU-en")
    rec.obs["law_tips"] = tips
    rec.obs["pill_after"] = page.evaluate("""() => { const p = document.querySelector('#tab-living .living-row-head span.pill.oo-tip-target');
        if (!p) return null; const s = getComputedStyle(p, '::after'); return {content: s.content, w: s.width, deco: getComputedStyle(p).textDecorationLine}; }""")
    junk_scan(page, rec, "#tab-living", "Living>Law")
    print(rec.obs)
