from lib import close_guide, session, shot, sub

with session("R-375", width=375, height=800) as (page, rec):
    close_guide(page)
    if page.locator("#hamburger").is_visible():
        page.click("#hamburger"); page.wait_for_timeout(500)
    page.click("button[onclick=\"showTab('settings')\"]")
    page.evaluate("() => document.body.classList.remove('nav-open')")
    page.wait_for_timeout(1500)
    sub(page, "set-subtabs", "advanced")
    page.click("details[data-adv='sources'] > summary")
    page.wait_for_selector("#src-table tr td", timeout=30000)
    page.wait_for_timeout(1500)
    page.locator("#src-msel-country").scroll_into_view_if_needed()
    page.wait_for_timeout(400)
    rec.obs["hs"] = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    rec.obs["boxes"] = page.evaluate("""() => ['src-search','src-msel-language','src-msel-country','src-msel-source_type','src-msel-tag','src-enabled'].map(id => { const e=document.getElementById(id); const w=e.parentElement.getBoundingClientRect(); const r=e.getBoundingClientRect(); return [id, 'wrap', Math.round(w.x), Math.round(w.width), 'ctrl', Math.round(r.x), Math.round(r.width), Math.round(r.y)]; })""")
    rec.obs["labels"] = page.evaluate("() => [...document.querySelectorAll('#src-search')][0].closest('.row').innerText.slice(0,80)")
    shot(page, "R4-375-sources-filter-row-en")
    try:
        page.click("#src-msel-country > summary", timeout=5000)
        page.wait_for_timeout(600)
        rec.obs["country_open"] = page.evaluate("() => document.getElementById('src-msel-country').open")
    except Exception as e:
        rec.obs["click_err"] = str(e).split("Call log")[0][:200]
        b = page.locator("#src-msel-country > summary").bounding_box()
        rec.obs["elementFromPoint_center"] = page.evaluate("([x,y]) => { const e = document.elementFromPoint(x,y); return e ? [e.tagName, (e.closest('details')||{}).id, e.textContent.slice(0,20)] : null; }", [b["x"]+b["width"]/2, b["y"]+b["height"]/2])
        # is ANY visible point of the country summary clickable?
        rec.obs["clickable_points"] = page.evaluate("""() => { const s = document.querySelector('#src-msel-country > summary'); const r = s.getBoundingClientRect(); const hits=[];
            for (let x = Math.ceil(r.left)+1; x < r.right; x += 4) { const e = document.elementFromPoint(x, r.top + r.height/2); if (e && s.contains(e)) hits.push(Math.round(x)); } return hits; }""")
    # real tap at the leftmost visible point, if any
    pts = rec.obs.get("clickable_points")
    if pts:
        b = page.locator("#src-msel-country > summary").bounding_box()
        page.mouse.click(pts[0], b["y"] + b["height"] / 2)
        page.wait_for_timeout(600)
        rec.obs["country_open_after_edge_tap"] = page.evaluate("() => document.getElementById('src-msel-country').open")
        shot(page, "R4-375-country-edge-tap-en")
    print(rec.obs)
