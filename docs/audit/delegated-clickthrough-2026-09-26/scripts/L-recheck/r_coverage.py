import re
from lib import cells, session, set_lang, shot, sub, tab, tip

def cov_cell(page, code):
    return page.locator("#coverage-table tr td strong span", has_text=re.compile(f"^{re.escape(code)}$")).first

with session("R-coverage") as (page, rec):
    tab(page, "library")
    sub(page, "library-views", "coverage")
    page.wait_for_selector("#coverage-table tr td", timeout=60000)
    page.wait_for_timeout(2500)
    first = page.locator("#coverage-table tr td strong > span").first
    rec.obs["first_row"] = [first.inner_text(), first.get_attribute("title"), tip(page, first)]
    shot(page, "R11-none-row-tip-en")
    rec.obs["none_payload"] = page.evaluate("() => fetch('/api/database/sources-by-country').then(r=>r.json()).then(d => (d.countries||[]).filter(c => c.code==='(none)' || ['va','ai','ck'].includes(c.code)).map(c => [c.code, c.name, c.sources]))")
    for code in ["va", "ai", "ck", "VAT"]:
        c = cov_cell(page, code)
        rec.obs[f"cell_{code}"] = [c.inner_text(), c.get_attribute("title")] if c.count() else None
    gaps = cells(page, "#coverage-gaps span.pill")
    rec.obs["gaps_head"] = page.locator("#coverage-gaps strong").first.inner_text()
    rec.obs["gaps_not_alpha3"] = [(g["text"], g["title"]) for g in gaps if not re.fullmatch(r"[A-Z]{3}", g["text"])]
    rec.obs["gaps_alpha3_sample"] = [(g["text"], g["title"]) for g in gaps if re.fullmatch(r"[A-Z]{3}", g["text"])][:4]
    reg = page.locator("#coverage-regions").inner_text()
    m = re.search(r"Top country:[^\n]*", reg)
    rec.obs["top_country_line_en"] = m.group(0) if m else None
    rec.obs["top_country_strong_title"] = page.evaluate("() => { const d=document.getElementById('coverage-regions'); const s=[...d.querySelectorAll('strong')].pop(); return s ? [s.textContent, s.getAttribute('title')] : null; }")
    # filter by on-screen code
    for q in ["DEU", "deu", "Germ", "de"]:
        page.fill("#cov-filter", q)
        page.wait_for_timeout(700)
        rec.obs[f"filter_{q}"] = page.eval_on_selector_all("#coverage-table tr td:first-child", "els => els.map(e => e.innerText.trim()).slice(0,5)")
        if q == "DEU":
            shot(page, "R11-filter-DEU-en")
    page.fill("#cov-filter", "")
    page.wait_for_timeout(700)
    for lang in ["fr", "ar"]:
        set_lang(page, lang)
        page.wait_for_timeout(1500)
        reg = page.locator("#coverage-regions").inner_text()
        rec.obs[f"regions_tail_{lang}"] = reg[-260:]
        rec.obs[f"gaps_head_{lang}"] = page.locator("#coverage-gaps strong").first.inner_text()
        rec.obs[f"DEU_tip_{lang}"] = tip(page, cov_cell(page, "DEU"))
        if lang == "fr":
            page.locator("#coverage-regions").scroll_into_view_if_needed()
            shot(page, "R11-top-country-fr")
    set_lang(page, "en")
    print(rec.obs)
