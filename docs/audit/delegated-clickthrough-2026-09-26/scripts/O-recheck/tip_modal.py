"""Is the #oo-tip bubble actually VISIBLE over a modal dialog? Hover the Export dialog's Living
sources row (and, for comparison, a non-modal control), then hit-test the bubble's own centre."""
import json
from playwright.sync_api import sync_playwright
from recheck import A, ARGS, PASS, COACH_STATE, unlock, close_guide, switch_lang, shot, open_settings, rec

HIT = """() => { const t = document.getElementById('oo-tip'); const r = t.getBoundingClientRect();
  const pts = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + 10, r.top + 10], [r.right - 10, r.bottom - 10]];
  return {shown: t.classList.contains('show'), text: t.textContent.slice(0, 90), opacity: getComputedStyle(t).opacity,
          rect: [r.left, r.top, r.right, r.bottom].map(Math.round), in_top_layer_dialog: !!t.closest('dialog'),
          hits: pts.map(([x, y]) => { const h = document.elementFromPoint(x, y); return h === t || (h && t.contains(h)) ? 'TIP' : (h ? (h.id || h.tagName + '.' + h.className).slice(0, 40) : null); })}; }"""
R = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=ARGS)
    ctx = br.new_context(viewport={"width": 1440, "height": 950}); pg = ctx.new_page(); rec.watch(pg, "tip")
    unlock(pg, A, PASS); close_guide(pg)
    st = pg.evaluate(COACH_STATE)
    if st and "show" in (st["cls"] or ""):
        pg.click("#net-coach-dismiss")
    open_settings(pg)
    pg.click("#set-subtabs button[data-tab='data']"); pg.wait_for_timeout(1200)
    # control: a non-modal hover in the Storage panel
    lane = pg.locator("#storage-lanes tbody tr td .oo-tip-target").first
    lane.hover(); pg.wait_for_timeout(800)
    R["storage_nonmodal"] = pg.evaluate(HIT)
    pg.mouse.move(2, 2); pg.wait_for_timeout(300)
    pg.locator("#set-data button[onclick='openUnifiedExport()']").click()
    pg.wait_for_function("() => document.getElementById('ux-export').open && document.querySelectorAll('#ux-checklist label').length > 2", timeout=15000)
    pg.wait_for_timeout(1000)
    lab = pg.locator("#ux-checklist label:has(#ux-c-lanes)")
    lab.hover(); pg.wait_for_timeout(900)
    R["export_modal"] = pg.evaluate(HIT)
    R["export_modal"]["dialog_is_modal"] = pg.evaluate("() => document.getElementById('ux-export').matches(':modal')")
    shot(pg, "Orc-export-hover-living-en.png")
    r = R["export_modal"]["rect"]
    pg.screenshot(path="Orc-export-hover-living-crop-en.png",
                  clip={"x": max(0, r[0] - 60), "y": max(0, r[1] - 40), "width": 460, "height": 160})
    pg.mouse.move(2, 2); pg.wait_for_timeout(300)
    pg.locator("#ux-export button[onclick*='close()']").first.click(); pg.wait_for_timeout(400)
    # the consent popup: are ITS lane hovers visible?
    pg.click("#net-toggle")
    pg.wait_for_function("() => document.getElementById('net-consent').open && document.querySelectorAll('#net-consent-lanes div > span:first-child').length > 3", timeout=15000)
    pg.wait_for_timeout(800)
    sp = pg.locator("#net-consent-lanes div > span:first-child").first
    sp.hover(); pg.wait_for_timeout(900)
    R["consent_modal"] = pg.evaluate(HIT)
    R["consent_modal"]["dialog_is_modal"] = pg.evaluate("() => document.getElementById('net-consent').matches(':modal')")
    shot(pg, "Orc-consent-hover-en.png")
    pg.mouse.move(2, 2); pg.wait_for_timeout(300)
    # Stay offline (never Go online)
    btns = pg.evaluate("() => [...document.querySelectorAll('#net-consent button')].map(b => [b.id, b.innerText.trim(), b.value])")
    R["consent_buttons"] = btns
    pg.locator("#net-consent button", has_text="Stay offline").first.click()
    pg.wait_for_timeout(600)
    R["online_after"] = pg.evaluate("() => fetch('/api/system/network').then(r => r.json())")
    ctx.close(); br.close()
R["page_errors"], R["http"] = rec.page_errors, rec.http
json.dump(R, open("raw-tip-modal.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(R, ensure_ascii=False, indent=1))
