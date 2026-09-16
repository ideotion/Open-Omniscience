"""Drive the #net-consent per-lane disclosure in Chromium (Q1128 = a).

AIRPLANE MODE IS ENGAGED EXPLICITLY. The recorded lesson: an instance booted with
OO_NO_SCHEDULER=1 starts ONLINE (the boot kill-switch activation lives inside the
OO_NO_SCHEDULER != 1 block), so ensureOnline returns true immediately and the popup
never appears -- a silence that reads as either a defect or a pass. Every observation
below states which state it was made in.
"""
import json, sys, time, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8010"
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)

def call(path, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json",
                                        "Origin": BASE, "Host": "127.0.0.1:8010"})
    with urllib.request.urlopen(r, timeout=20) as resp:
        return json.loads(resp.read().decode())

record = []
def note(k, v):
    record.append((k, v)); print(f"  {k}: {v}")

print("== state before ==")
note("kill switch engaged (offline)", call("/api/system/network")["online"] is False)
if call("/api/system/network")["online"]:
    call("/api/scheduler/stop", "POST")          # the Stop button trips the kill switch
note("airplane engaged after stop", call("/api/system/network")["online"] is False)
cfg = call("/api/scheduler/config")
note("auto_track_signals", cfg.get("auto_track_signals"))
note("world_discovery_per_pass", cfg.get("world_discovery_per_pass"))
note("auto_track_law present in payload", "auto_track_law" in cfg)

def open_dialog(page):
    page.click("#net-toggle")                    # a REAL click, not eval_on_selector
    page.wait_for_selector("#net-consent[open]", timeout=8000)
    page.wait_for_function(
        "() => { const e = document.getElementById('net-consent-lanes');"
        " return e && e.textContent.trim() && e.textContent.trim() !== '…'; }", timeout=8000)

def close_dialog(page):
    page.click("#net-consent-cancel")
    page.wait_for_selector("#net-consent[open]", state="detached", timeout=4000)

with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
    page = b.new_page(viewport={"width": 900, "height": 1000})
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector("#net-toggle", timeout=15000)
    # The first-launch guide is modal and covers the top bar. Dismissing it is a
    # real click on its own close control -- not a JS close() -- so the app takes
    # the same path a person would.
    if page.locator("#guide-wizard[open]").count():
        page.click("#gw-close")
        page.wait_for_selector("#guide-wizard[open]", state="detached", timeout=5000)
        note("first-launch guide dismissed by clicking #gw-close", True)
    note("airplane still engaged after dismissing the guide",
         call("/api/system/network")["online"] is False)

    for loc in ("en", "ar", "zh"):
        page.evaluate("l => window.OOI18N && OOI18N.setLang(l)", loc)
        page.wait_for_timeout(500)
        open_dialog(page)
        box = page.locator("#net-consent-lanes")
        txt = box.inner_text()
        note(f"[{loc}] lane block characters", len(txt))
        note(f"[{loc}] dir attribute", page.evaluate("document.documentElement.getAttribute('dir')"))
        titled = page.eval_on_selector_all(
            "#net-consent-lanes [title], #net-consent-lanes .oo-tip-target",
            "els => els.map(e => e.getAttribute('title') || e.dataset.ooTip || '')")
        note(f"[{loc}] lanes carrying a host hover", len([t for t in titled if t]))
        if loc == "en":
            note("en lane block text", repr(txt))
            for lane_name in ("Law", "Calendars", "Hazard feeds", "Newsletter mailbox",
                              "Chain of custody", "Wikipedia / Wikimedia"):
                h = page.eval_on_selector_all(
                    "#net-consent-lanes .oo-tip-target",
                    "(els, n) => { const e = els.find(x => x.textContent.trim() === n);"
                    " return e ? (e.getAttribute('title') || e.dataset.ooTip) : null; }", lane_name)
                note(f"hover[{lane_name}]", repr(h))
            note("en first hover", repr(titled[0] if titled else None))
            # hover a real lane and read the ONE shared bubble
            page.hover("#net-consent-lanes .oo-tip-target")
            page.wait_for_timeout(450)
            tip = page.locator("#oo-tip")
            note("#oo-tip visible on hover", tip.is_visible())
            note("#oo-tip text", repr(tip.inner_text()[:200]))
        # the two standing caveats must still be visible IN the dialog
        hints = page.eval_on_selector_all("#net-consent .hint", "els => els.map(e => e.innerText)")
        note(f"[{loc}] visible hints in the dialog", len(hints))
        page.screenshot(path=str(OUT / f"net-consent-{loc}.png"), full_page=False)
        close_dialog(page)

    # --- a lane toggled OFF must move buckets -------------------------------
    page.evaluate("l => window.OOI18N && OOI18N.setLang(l)", "en")
    page.wait_for_timeout(300)
    call("/api/scheduler/config", "PUT", {"auto_track_signals": False,
                                          "world_discovery_per_pass": 0})
    note("after PUT: auto_track_signals", call("/api/scheduler/config")["auto_track_signals"])
    open_dialog(page)
    txt_off = page.locator("#net-consent-lanes").inner_text()
    note("source discovery moved to 'Switched off right now'",
         txt_off.index("Switched off right now:") < txt_off.index("Source discovery"))
    # FINDING, not a harness failure: auto_track_signals=false is accepted with a
    # 200 and discarded, because SchedulerConfigUpdate does not declare the field.
    # The lane therefore stays ON, which is the TRUTH about the running app -- and
    # its hover says why.
    note("hazards STAYS on despite the PUT (the unreachable opt-out)",
         txt_off.index("Runs on every collection pass:") < txt_off.index("Hazard feeds")
         and txt_off.index("Hazard feeds") < txt_off.index("Switched off right now:"))
    note("off-state lane block text", repr(txt_off))
    page.screenshot(path=str(OUT / "net-consent-en-lane-off.png"))
    close_dialog(page)

    call("/api/scheduler/config", "PUT", {"auto_track_signals": True,
                                          "world_discovery_per_pass": 2})
    note("restored world_discovery_per_pass", call("/api/scheduler/config")["world_discovery_per_pass"])

    # --- phone width: a taller dialog is the obvious regression risk ---------
    page.set_viewport_size({"width": 375, "height": 667})
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#net-toggle", timeout=15000)
    if page.locator("#guide-wizard[open]").count():
        page.click("#gw-close")
        page.wait_for_selector("#guide-wizard[open]", state="detached", timeout=5000)
    open_dialog(page)
    m = page.evaluate("""() => {
      const d = document.getElementById('net-consent');
      const ok = document.getElementById('net-consent-ok').getBoundingClientRect();
      const body = document.getElementById('net-consent-body');
      const hints = [...document.querySelectorAll('#net-consent .hint')];
      const dr = d.getBoundingClientRect();
      return {h: d.scrollHeight, vh: window.innerHeight,
              dialogClipped: d.scrollHeight > d.clientHeight + 1,
              bodyScrolls: body.scrollHeight > body.clientHeight,
              okInViewport: ok.bottom <= window.innerHeight && ok.top >= 0 && ok.width > 0,
              okInsideDialog: ok.bottom <= dr.bottom + 1,
              hintCount: hints.length,
              standingCaveatsInFlow: ['does not check it', 'hardware switch'].every(
                needle => hints.some(h => h.innerText.includes(needle) &&
                  h.offsetParent !== null && getComputedStyle(h).display !== 'none')),
              dialogWidth: Math.round(dr.width),
              scrollableX: document.documentElement.scrollWidth > window.innerWidth};
    }""")
    note("375px: dialog height vs viewport", f"{m['h']}px in {m['vh']}px")
    note("375px: dialog itself clipped", m["dialogClipped"])
    note("375px: the BODY scrolls (by design)", m["bodyScrolls"])
    note("375px: 'Go online' is inside the viewport without scrolling", m["okInViewport"])
    note("375px: .hint blocks in the dialog", m["hintCount"])
    note("375px: both STANDING caveats in normal flow, not display:none", m["standingCaveatsInFlow"])
    note("375px: dialog width", f"{m['dialogWidth']}px")
    note("375px: page scrolls horizontally WITH the dialog open", m["scrollableX"])
    # Prove the caveats are REACHABLE, not merely present: scroll the body to the end.
    page.evaluate("() => { const b = document.getElementById('net-consent-body');"
                  " b.scrollTop = b.scrollHeight; }")
    page.wait_for_timeout(250)
    reach = page.evaluate("""() => {
      const h = [...document.querySelectorAll('#net-consent .hint')].pop().getBoundingClientRect();
      return h.top >= 0 && h.bottom <= window.innerHeight;
    }""")
    note("375px: the last caveat is on screen once the body is scrolled", reach)
    page.screenshot(path=str(OUT / "net-consent-en-375-scrolled.png"))
    page.evaluate("() => { document.getElementById('net-consent-body').scrollTop = 0; }")
    close_dialog(page)
    # Is the horizontal scroll ours, or the page's own? Measure with the dialog shut.
    note("375px: page scrolls horizontally with the dialog CLOSED (pre-existing?)",
         page.evaluate("() => document.documentElement.scrollWidth > window.innerWidth"))
    open_dialog(page)
    page.screenshot(path=str(OUT / "net-consent-en-375.png"), full_page=False)
    close_dialog(page)
    b.close()

(OUT / "observations.json").write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
print("\nwrote", OUT)
