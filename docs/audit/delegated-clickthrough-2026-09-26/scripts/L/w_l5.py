import re

from lib import cells, junk_scan, session, set_lang, shot, sub, tab, tip


def map_title(page, iso):
    loc = page.locator(f"#coverage-map path[data-iso='{iso}']").first
    if not loc.count():
        loc = page.locator(f"#coverage-map circle[data-iso='{iso}']").first
    if not loc.count():
        return None
    try:
        loc.hover(timeout=4000, force=True)
    except Exception:
        pass
    return loc.evaluate("e => (e.querySelector('title')||{}).textContent || null")


def cov_cell(page, code):
    return page.locator("#coverage-table tr td strong span", has_text=re.compile(f"^{code}$")).first


with session("L5") as (page, rec):
    tab(page, "library")
    sub(page, "library-views", "coverage")
    page.wait_for_selector("#coverage-table tr td", timeout=60000)
    page.wait_for_timeout(2500)
    # map
    rec.obs["map_paths"] = page.locator("#coverage-map path[data-iso]").count()
    rec.obs["map_points"] = page.locator("#coverage-map circle[data-iso]").count()
    rec.obs["map_titles_en"] = {iso: map_title(page, iso) for iso in ["fr", "de", "us", "cn", "gb"]}
    pts = page.eval_on_selector_all("#coverage-map circle[data-iso]", "els => els.slice(0,8).map(e => [e.dataset.iso, (e.querySelector('title')||{}).textContent])")
    rec.obs["map_point_titles"] = pts
    shot(page, "L5-coverage-map-en")
    # regional balance
    reg = page.locator("#coverage-regions").inner_text()
    m = re.search(r"Top country:[^\n]*", reg)
    rec.obs["top_country_line"] = m.group(0) if m else reg[-300:]
    # table
    rows = page.eval_on_selector_all("#coverage-table tr", "els => els.slice(0,6).map(e => e.innerText.replace(/\\s+/g,' ').trim())")
    rec.obs["table_first_rows"] = rows
    cc = cells(page, "#coverage-table tr td strong > span")
    rec.obs["table_cells_n"] = len(cc)
    rec.obs["table_bad"] = [c for c in cc if not re.fullmatch(r"[A-Z]{3}", c["text"])][:12]
    rec.obs["table_no_title"] = [c for c in cc if not c["title"]][:12]
    first = page.locator("#coverage-table tr td strong > span").first
    rec.obs["first_row_tip"] = [first.inner_text(), tip(page, first)]
    shot(page, "L5-first-row-tip-en")
    rec.obs["DEU_tip_en"] = tip(page, cov_cell(page, "DEU"))
    gaps = cells(page, "#coverage-gaps span.pill")
    rec.obs["gaps_head"] = page.locator("#coverage-gaps").inner_text()[:120]
    rec.obs["gaps_n"] = len(gaps)
    rec.obs["gaps_bad"] = [g for g in gaps if not re.fullmatch(r"[A-Z]{3}", g["text"])][:20]
    rec.obs["gaps_sample"] = gaps[:5]
    gp = page.locator("#coverage-gaps span.pill.oo-tip-target")
    if gp.count():
        rec.obs["gap_tip"] = [gp.first.inner_text(), tip(page, gp.first)]
    junk_scan(page, rec, "#lib-view-coverage", "World coverage")
    # filter by the on-screen code
    page.fill("#cov-filter", "DEU")
    page.wait_for_timeout(800)
    rec.obs["filter_DEU"] = page.eval_on_selector_all("#coverage-table tr", "els => els.map(e => e.innerText.replace(/\\s+/g,' ').trim()).slice(0,4)")
    shot(page, "L5-filter-DEU-en")
    for q in ["de", "germ"]:
        page.fill("#cov-filter", q)
        page.wait_for_timeout(600)
        rec.obs[f"filter_{q}"] = page.eval_on_selector_all("#coverage-table tr td strong > span", "els => els.map(e => e.innerText).slice(0,6)")
    page.fill("#cov-filter", "")
    page.wait_for_timeout(600)
    # ---- L6: bare language switch, re-hover ----
    l6 = {}
    for lang in ["fr", "ar", "zh", "en"]:
        set_lang(page, lang)
        page.wait_for_timeout(1500)
        l6[lang] = {
            "dir": page.evaluate("() => document.documentElement.dir"),
            "DEU_visible": cov_cell(page, "DEU").inner_text() if cov_cell(page, "DEU").count() else None,
            "DEU_tip": tip(page, cov_cell(page, "DEU")),
            "map_de": map_title(page, "de"),
            "map_fr": map_title(page, "fr"),
        }
        if lang in ("ar", "zh", "fr"):
            cov_cell(page, "DEU").hover()
            page.wait_for_timeout(400)
            shot(page, f"L6-DEU-tip-{lang}")
        if lang != "en":
            junk_scan(page, rec, "#lib-view-coverage", f"World coverage [{lang}]")
    rec.obs["L6"] = l6
    # click a code -> Sources
    fra = page.locator("#coverage-table tr td strong", has=page.locator("span", has_text=re.compile("^FRA$"))).first
    fra.click()
    page.wait_for_timeout(3500)
    rec.obs["after_click_hash"] = page.evaluate("() => location.hash")
    try:
        rec.obs["after_click_country_label"] = page.locator("#src-msel-country > summary").inner_text()
        rec.obs["after_click_meta"] = page.locator("#src-meta").inner_text()
        rec.obs["after_click_visible"] = page.locator("#src-table").is_visible()
        rec.obs["after_click_rows"] = sorted(set(page.eval_on_selector_all("#src-table tr td:nth-child(4)", "els => els.map(e => e.innerText.trim())")))
    except Exception as e:  # noqa: BLE001
        rec.obs["after_click_err"] = str(e)[:300]
    shot(page, "L5-click-FRA-sources-en")
    print(rec.obs)
