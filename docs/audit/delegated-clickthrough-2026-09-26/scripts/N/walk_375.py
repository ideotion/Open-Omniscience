"""Row N at phone width (375 px, en): horizontal scroll and clipped text on the row's surfaces."""
import json, re, sys, traceback
sys.path.insert(0, "/tmp/claude-0/walk/N")
from lib import *
from playwright.sync_api import sync_playwright

R: dict = {}
rec = Recorder("375")

OVER = "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"
CLIP = """(sel) => { const out=[]; const vw=document.documentElement.clientWidth;
  for (const root of document.querySelectorAll(sel)) for (const e of root.querySelectorAll('*')) {
    if (!e.offsetParent && getComputedStyle(e).position!=='fixed') continue;
    const r=e.getBoundingClientRect(); if (!r.width) continue;
    const cs=getComputedStyle(e);
    const hid = /(hidden|clip)/.test(cs.overflowX) || cs.textOverflow==='ellipsis';
    if (hid && e.scrollWidth > e.clientWidth + 1 && e.children.length===0) out.push({kind:'clipped', tag:e.tagName, text:e.textContent.trim().slice(0,60)});
    if (r.right > vw + 1 && e.children.length===0 && e.textContent.trim()) {
      // offscreen unless an ancestor scrolls horizontally
      let a=e.parentElement, scroller=false; while (a) { const s=getComputedStyle(a); if (/(auto|scroll)/.test(s.overflowX) && a.scrollWidth>a.clientWidth) { scroller=true; break;} a=a.parentElement; }
      if (!scroller) out.push({kind:'offscreen', tag:e.tagName, right:Math.round(r.right), text:e.textContent.trim().slice(0,60)});
    }
  } return out.slice(0,25); }"""


def palette(page, term):
    if page.is_visible(".omni"):
        page.click(".omni")
    else:
        page.keyboard.press("Control+k")
    page.wait_for_selector("#pal-input", state="visible", timeout=5000)
    page.fill("#pal-input", "")
    page.type("#pal-input", term, delay=30)
    page.wait_for_timeout(900)
    cov = page.evaluate("""() => { const c=document.getElementById('net-coach'); const it=document.querySelector('.pal-item');
      if (!c || !it) return null; const a=c.getBoundingClientRect(), b=it.getBoundingClientRect();
      const vis = c.classList.contains('show');
      const hit = document.elementFromPoint(b.left + b.width/2, b.top + b.height/2);
      return {coach_shown: vis, coach_rect:[Math.round(a.left),Math.round(a.top),Math.round(a.right),Math.round(a.bottom)],
              row_rect:[Math.round(b.left),Math.round(b.top),Math.round(b.right),Math.round(b.bottom)],
              element_at_row_centre: hit ? (hit.id || hit.className || hit.tagName) : null,
              coach_z: getComputedStyle(c).zIndex, palette_z: getComputedStyle(document.getElementById('palette')).zIndex}; }""")
    R.setdefault("palette_coach_overlap", []).append({"term": term, **(cov or {})})
    if cov and cov.get("coach_shown"):
        shot(page, f"N-375-palette-coach-{term}")
        # the coach sits over the result rows; press its own 'Not now' (POSTs nothing)
        page.click("#net-coach-dismiss", force=True)
        page.wait_for_timeout(400)


with sync_playwright() as p:
    b = launch(p)
    ctx = b.new_context(viewport={"width": 375, "height": 800}, is_mobile=False)
    rec.attach_context(ctx, "375")
    page = ctx.new_page()
    rec.attach(page, "main")
    try:
        page.goto(URL + "/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        close_dialogs(page); dismiss_coach(page)
        try:
            set_lang(page, "en")
        except Exception as e:
            R["set_lang_note"] = str(e)[:200]
        R["home_overflow"] = page.evaluate(OVER)
        R["omni_visible"] = page.is_visible(".omni")
        shot(page, "N-375-home-en")
        palette(page, "climate")
        with ctx.expect_page(timeout=20000) as pinfo:
            click_palette_row(page, ["Analysis: “climate”"])
        ap = pinfo.value
        ap.wait_for_load_state("domcontentloaded"); ap.wait_for_timeout(3000); dismiss_coach(ap)
        ap.click("#an-subtabs [data-tab=articles]")
        R["total"] = wait_art_total(ap)
        ap.wait_for_timeout(2500)
        R["xlang_head"] = (text(ap, "#an-xlang") or "")[:80]
        R["articles_overflow"] = ap.evaluate(OVER)
        R["articles_clip"] = ap.evaluate(CLIP, "#an-articles")
        shot(ap, "N-375-articles-en")
        ap.click("#an-xlang button[onclick^='_anFormCounts']")
        ap.wait_for_function("() => { const e=document.querySelector(\"[id^='an-xforms-']\"); return e && e.querySelector('b'); }", timeout=60000)
        R["forms_overflow"] = ap.evaluate(OVER)
        ap.click("#an-articles button[onclick='_anSetGroupByLang(true)']"); ap.wait_for_timeout(1200)
        R["grouped_overflow"] = ap.evaluate(OVER)
        ap.click("#an-articles button[onclick='_anSetGroupByLang(false)']"); ap.wait_for_timeout(800)
        ap.click("#an-subtabs [data-tab=trend]"); ap.wait_for_timeout(2500)
        bl = ap.locator("#an-trend button[onclick=\"anTrendSetMode('bylang')\"]")
        if bl.count():
            bl.first.click(); ap.wait_for_selector("#an-trend-chart canvas", timeout=30000); ap.wait_for_timeout(800)
        R["trend_overflow"] = ap.evaluate(OVER)
        R["trend_clip"] = ap.evaluate(CLIP, "#an-trend")
        shot(ap, "N-375-trend-en")
        ap.click("#an-subtabs [data-tab=mindmap]"); ap.wait_for_timeout(2500)
        cb = ap.locator("#an-mindmap button[onclick*='concept:true']")
        if cb.count():
            cb.first.click(); ap.wait_for_timeout(2000)
        R["mindmap_overflow"] = ap.evaluate(OVER)
        R["mindmap_svg_text_clipped"] = ap.evaluate("""() => { const out=[]; for (const svg of document.querySelectorAll('#an-mindmap svg')) { const sr=svg.getBoundingClientRect();
            for (const t of svg.querySelectorAll('text')) { const q=t.getBoundingClientRect(); if (!q.width) continue;
              if (q.left < sr.left-1 || q.right > sr.right+1) out.push(t.textContent.trim()); } } return out; }""")
        R["mindmap_label_px"] = ap.evaluate("() => { const t=[...document.querySelectorAll('#an-mindmap svg text')].find(x=>x.textContent.trim()==='climate'); return t ? Math.round(t.getBoundingClientRect().height) : null; }")
        shot(ap, "N-375-concept-en")
        ap.close()
        page.bring_to_front()
        palette(page, "election")
        with ctx.expect_page(timeout=20000) as pinfo:
            click_palette_row(page, ["Analysis: “election”"])
        ep = pinfo.value
        ep.wait_for_load_state("domcontentloaded"); ep.wait_for_timeout(3000); dismiss_coach(ep)
        ep.click("#an-subtabs [data-tab=articles]"); wait_art_total(ep); ep.wait_for_timeout(2500)
        R["election_xlang_head"] = (text(ep, "#an-xlang") or "")[:100]
        pick = ep.locator("#an-xlang button[onclick*='_anPickSense']").filter(has_text="public election")
        if pick.count():
            pick.first.click(); ep.wait_for_timeout(4000)
        R["election_overflow"] = ep.evaluate(OVER)
        R["election_clip"] = ep.evaluate(CLIP, "#an-articles")
        shot(ep, "N-375-election-en")
        ep.close()
        page.bring_to_front()
        # Insights trends at 375
        dismiss_coach(page)
        page.click("#hamburger")
        page.wait_for_timeout(700)
        R["drawer_open"] = page.evaluate("() => document.body.classList.contains('nav-open')")
        page.click("#navGroups button[data-tab=insights]")
        page.wait_for_selector("#ins-subtabs button[data-tab=trends]", state="visible", timeout=30000)
        page.click("#ins-subtabs button[data-tab=trends]"); page.wait_for_timeout(3000)
        R["insights_overflow"] = page.evaluate(OVER)
        shot(page, "N-375-insights-en")
    except Exception as e:  # noqa: BLE001
        R["exception"] = f"{type(e).__name__}: {str(e)[:500]}"
        R["trace"] = traceback.format_exc()[-1200:]
    b.close()

rec.data = R
rec.save()
(OUT / "R-375.json").write_text(json.dumps(R, ensure_ascii=False, indent=1))
print(json.dumps(R, ensure_ascii=False, indent=1))
print("PAGE ERRORS", rec.page_errors, "CONSOLE", rec.console_errors, "HTTP", rec.http_errors)
