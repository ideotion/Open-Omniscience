import re
from lib import close_guide, session, shot, sub, tab, tip

def hs(page):
    return page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth, document.body.scrollWidth]")

def clipped(page, sel):
    return page.evaluate("""(sel) => { const out=[]; document.querySelectorAll(sel).forEach(e => {
        const r=e.getBoundingClientRect(); if (r.width===0) return;
        if (e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX==='visible') out.push([e.tagName, e.id||e.className, (e.innerText||'').slice(0,40)]);
        if (r.right > window.innerWidth + 1) out.push(['OFFSCREEN', e.tagName, e.id||e.className, (e.innerText||'').slice(0,40), Math.round(r.right)]);
    }); return out.slice(0,10); }""", sel)

with session("L375", width=375, height=800) as (page, rec):
    res = {}
    def nav(t):
        close_guide(page)
        # at 375 the sidebar may be a rail or hidden: use showTab through the same button if visible
        btn = page.locator(f"#navGroups .nav-item[data-tab='{t}']")
        if page.locator("#hamburger").is_visible():
            page.click("#hamburger"); page.wait_for_timeout(500)
        btn.click()
        page.wait_for_timeout(300)
        page.evaluate("() => document.body.classList.remove('nav-open')")
        page.wait_for_timeout(1500)
    rec.obs["sidebar_item_visible"] = page.locator("#navGroups .nav-item[data-tab='law']").is_visible()
    nav("law"); sub(page, "gov-subtabs", "law"); page.wait_for_timeout(1500)
    res["law"] = {"hs": hs(page), "clip": clipped(page, "#gov-law td, #gov-law th, #law-changes b")}
    loc = page.locator("#law-docs tbody tr td:first-child span", has_text=re.compile("^EUU$")).first
    res["law"]["EUU_tip"] = tip(page, loc)
    shot(page, "L375-law-en")
    nav("agenda"); sub(page, "agenda-views", "list"); page.wait_for_timeout(1500)
    res["agenda"] = {"hs": hs(page), "clip": clipped(page, "#agenda-list h3, #agenda-country")}
    shot(page, "L375-agenda-en")
    nav("library"); sub(page, "library-views", "coverage"); page.wait_for_selector("#coverage-table tr td", timeout=60000); page.wait_for_timeout(1500)
    res["coverage"] = {"hs": hs(page), "clip": clipped(page, "#coverage-table td, #coverage-gaps")}
    shot(page, "L375-coverage-en")
    nav("law"); sub(page, "gov-subtabs", "map"); page.wait_for_timeout(2500)
    res["govmap"] = {"hs": hs(page)}
    sub(page, "gov-subtabs", "countries"); page.wait_for_timeout(2000)
    res["govcountries"] = {"hs": hs(page), "clip": clipped(page, "#gov-country")}
    close_guide(page)
    page.click("#hamburger"); page.wait_for_timeout(500)
    page.click("button[onclick=\"showTab('settings')\"]")
    page.evaluate("() => document.body.classList.remove('nav-open')")
    page.wait_for_timeout(1500)
    sub(page, "set-subtabs", "advanced")
    page.click("details[data-adv='sources'] > summary"); page.wait_for_selector("#src-table tr td", timeout=30000); page.wait_for_timeout(1500)
    res["sources"] = {"hs": hs(page), "clip": clipped(page, "#src-msel-country, #src-msel-language")}
    page.locator("#src-msel-country").scroll_into_view_if_needed()
    res["sources"]["boxes"] = page.evaluate("""() => ['src-search','src-msel-language','src-msel-country','src-msel-source_type','src-msel-tag','src-enabled'].map(id => { const e=document.getElementById(id); const r=e.getBoundingClientRect(); return [id, Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })""")
    shot(page, "L375-sources-filters-closed-en")
    try:
        page.click("#src-msel-country > summary", timeout=5000); page.wait_for_timeout(600)
        res["sources"]["filter_open_hs"] = hs(page)
    except Exception as e:
        res["sources"]["filter_click_err"] = str(e).split("Call log")[0][:200]
        b = page.locator("#src-msel-country > summary").bounding_box()
        res["sources"]["elementFromPoint"] = page.evaluate("([x,y]) => { const e = document.elementFromPoint(x,y); return e ? [e.tagName, e.parentElement && e.parentElement.id, e.textContent.slice(0,30)] : null; }", [b["x"]+b["width"]/2, b["y"]+b["height"]/2])
    shot(page, "L375-sources-filter-en")
    rec.obs["res"] = res
    print(rec.obs)
