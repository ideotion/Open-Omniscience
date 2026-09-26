import re
from lib import session, shot, sub, tab, tip

with session("R-map") as (page, rec):
    tab(page, "timemap")
    sub(page, "oomap-lenses", "coverage")
    page.wait_for_selector("#oo-coverage-map path[data-iso]", timeout=60000)
    page.wait_for_timeout(2500)
    host = "#oo-coverage-map"
    de = page.locator(f"{host} path[data-iso='de']").first
    de.scroll_into_view_if_needed()
    bb = de.bounding_box()
    page.mouse.click(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)
    page.wait_for_timeout(1500)
    det = page.locator("#oo-coverage-detail")
    strong = det.locator("strong").first
    rec.obs["detail_heading"] = strong.inner_text() if strong.count() else None
    rec.obs["detail_heading_outer"] = strong.evaluate("e => e.outerHTML") if strong.count() else None
    rec.obs["detail_heading_tip"] = tip(page, strong, tries=2) if strong.count() else None
    shot(page, "R12-coverage-detail-DEU-en")
    rec.obs["worldview_opts"] = page.eval_on_selector_all(f"{host} select[data-oomap-worldview] option", "els => els.map(e => e.textContent.trim())")
    print(rec.obs)
