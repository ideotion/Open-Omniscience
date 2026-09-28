import re

from lib import junk_scan, session, shot, sub, tab, tip

with session("L7") as (page, rec):
    tab(page, "timemap")
    sub(page, "oomap-lenses", "coverage")
    page.wait_for_selector("#oo-coverage-map path[data-iso]", timeout=60000)
    page.wait_for_timeout(2500)
    host = "#oo-coverage-map"
    rec.obs["paths"] = page.locator(f"{host} path[data-iso]").count()
    titles = {}
    for iso in ["fr", "de", "us", "cn", "gb"]:
        loc = page.locator(f"{host} path[data-iso='{iso}']").first
        if loc.count():
            try:
                loc.hover(timeout=3000, force=True)
            except Exception:
                pass
            titles[iso] = loc.evaluate("e => (e.querySelector('title')||{}).textContent")
    rec.obs["shape_titles"] = titles
    pts = page.eval_on_selector_all(f"{host} circle[data-iso]", "els => els.map(e => [e.dataset.iso, (e.querySelector('title')||{}).textContent])")
    rec.obs["point_titles"] = pts[:10]
    rec.obs["map_controls_text"] = page.locator(host).inner_text()[:400]
    shot(page, "L7-coverage-en")
    # click France
    de = page.locator(f"{host} path[data-iso='de']").first
    de.scroll_into_view_if_needed()
    bb = de.bounding_box()
    rec.obs["de_bbox"] = bb
    page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
    page.wait_for_timeout(1500)
    det = page.locator("#oo-coverage-detail")
    rec.obs["detail_text"] = det.inner_text()[:400]
    strong = det.locator("strong").first
    rec.obs["detail_heading"] = strong.inner_text() if strong.count() else None
    rec.obs["detail_heading_title"] = strong.evaluate("e => e.getAttribute('title') || (e.querySelector('[title]')||{getAttribute:()=>null}).getAttribute('title')") if strong.count() else None
    rec.obs["detail_heading_tip"] = tip(page, strong, tries=1) if strong.count() else None
    shot(page, "L7-coverage-detail-DEU-en")
    junk_scan(page, rec, "#tab-timemap", "World map coverage")
    # Stories
    sub(page, "oomap-lenses", "stories")
    page.wait_for_timeout(3000)
    sig = page.locator(f"{host} [data-oomap-sig]")
    rec.obs["story_dots"] = sig.count()
    lines = []
    got = None
    for i in range(min(sig.count(), 25)):
        try:
            sig.nth(i).click(force=True, timeout=3000)
        except Exception as e:  # noqa: BLE001
            continue
        page.wait_for_timeout(500)
        g = page.locator("#oo-coverage-detail div.muted").first
        if not g.count():
            continue
        txt = g.inner_text().replace("\n", " ")
        lines.append(txt[:160])
        cc = g.locator("span.oo-tip-target").first
        if cc.count() and re.fullmatch(r"[A-Z]{3}", cc.inner_text().strip()) and got is None:
            got = [txt, cc.inner_text().strip(), tip(page, cc)]
            shot(page, "L7-stories-detail-tip-en")
    rec.obs["story_lines"] = lines[:10]
    rec.obs["story_code_tip"] = got
    junk_scan(page, rec, "#tab-timemap", "World map stories")
    print(rec.obs)
