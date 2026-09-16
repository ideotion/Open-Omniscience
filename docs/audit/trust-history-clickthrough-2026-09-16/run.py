"""S04-04 click-through: the Q701-note trust toggle on both surfaces, in en / fr / ar."""
import json, pathlib, sys
from playwright.sync_api import sync_playwright

CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
URL = "http://127.0.0.1:8077/"
OUT = pathlib.Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)
BAK_DIR = sys.argv[2]

EXPECT = {
  "en": ("Trust a backup's scraping history by default", "Trust the backup's scraping history"),
  "fr": ("Faire confiance par défaut à l'historique de collecte d'une sauvegarde",
         "Faire confiance à l'historique de collecte de la sauvegarde"),
  "ar": ("الوثوق افتراضيًا بسجلّ الجلب الخاص بالنسخة الاحتياطية",
         "الوثوق بسجلّ الجلب الخاص بالنسخة الاحتياطية"),
}
rec = {"steps": [], "pageerrors": []}

def step(name, **kw):
    rec["steps"].append(dict(step=name, **kw)); print(name, kw)

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
    pg = b.new_page(viewport={"width": 1280, "height": 900})
    pg.on("pageerror", lambda e: rec["pageerrors"].append(str(e)))
    pg.goto(URL, wait_until="networkidle"); pg.wait_for_timeout(2000)

    # ---- 1. the WIZARD half, in three locales -----------------------------------
    for lang, (label_default, _) in EXPECT.items():
        pg.evaluate("l => { try { localStorage.setItem('oo.lang', l); } catch(e){} }", lang)
        pg.reload(wait_until="networkidle"); pg.wait_for_timeout(1800)
        pg.evaluate("() => { if (window.openGuide) openGuide(); }")
        pg.wait_for_timeout(500)
        # walk forward until the toggle is really on screen
        for _ in range(8):
            if pg.locator("#gw-trust-history").is_visible():
                break
            nxt = pg.locator("#gw-next")
            if not nxt.is_visible(): break
            nxt.click(); pg.wait_for_timeout(450)
        vis = pg.locator("#gw-trust-history").is_visible()
        label = pg.evaluate("() => { const b=document.getElementById('gw-trust-history');"
                            " return b ? b.closest('label').innerText.trim() : null; }")
        note = pg.evaluate("() => { const n=document.getElementById('gw-trust-note');"
                           " return n ? n.innerText.trim() : null; }")
        hover = pg.get_attribute("#gw-trust-history", "title")
        rtl = pg.evaluate("() => document.documentElement.getAttribute('dir')")
        checked = pg.is_checked("#gw-trust-history")
        # WHICH STEP it is on, asserted rather than eyeballed: the screenshot is taken
        # scrolled, so "it looked like the language step" is exactly the reading a
        # picture supports and a measurement settles.
        data_step = pg.evaluate("() => document.getElementById('gw-trust-history')"
                                ".closest('.gw-step').getAttribute('data-step')")
        cbw = pg.evaluate("() => document.getElementById('gw-trust-history')"
                          ".getBoundingClientRect().width")
        pg.locator("#gw-trust-history").scroll_into_view_if_needed()
        pg.screenshot(path=str(OUT / f"wizard-trust-{lang}.png"))
        step(f"wizard/{lang}", visible=vis, checked=checked, dir=rtl,
             data_step=data_step, checkbox_px=round(cbw),
             label=label, note_len=len(note or ""), note=note, hover_len=len(hover or ""),
             label_matches=(label == label_default))
        assert vis, f"{lang}: the wizard toggle is not on screen"
        assert data_step == "sources", f"{lang}: the toggle is on the {data_step!r} step"
        # The global `input, select, textarea { width:100% }` rule stretched this box
        # to 337px until it was given the repo's own `width:auto` escape. Measured here so
        # the fix cannot silently come undone.
        assert 8 <= cbw <= 30, f"{lang}: the checkbox renders {cbw}px wide"
        assert label == label_default, f"{lang}: label is {label!r}"
        assert note and len(note) > 30, f"{lang}: the caveat did not render"
        assert hover and len(hover) > 60, f"{lang}: the layered hover is missing"
        if lang == "ar":
            assert rtl == "rtl", "Arabic did not put the document in RTL"
        pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d&&d.open) d.close(); }")

    # ---- 2. the IMPORT half ------------------------------------------------------
    pg.evaluate("l => { try { localStorage.setItem('oo.lang', l); } catch(e){} }", "en")
    pg.reload(wait_until="networkidle"); pg.wait_for_timeout(1800)
    pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d&&d.open) d.close(); }")
    pg.evaluate("() => openUnifiedImport()"); pg.wait_for_timeout(700)
    before = pg.locator("#ux-imp-trust-row").is_visible()
    pg.screenshot(path=str(OUT / "import-before-scan.png"))
    step("import/before-scan", trust_row_visible=before)
    assert not before, "the toggle was offered before any scan found a backup"

    pg.fill("#ux-imp-src", BAK_DIR)
    pg.click("#ux-import button[onclick^=\"_uxImScan\"]")
    pg.wait_for_timeout(4000)
    after = pg.locator("#ux-imp-trust-row").is_visible()
    checked = pg.is_checked("#ux-imp-trust") if after else None
    cbw = pg.evaluate("() => document.getElementById('ux-imp-trust').getBoundingClientRect().width")
    assert 8 <= cbw <= 30, f"the import checkbox renders {cbw}px wide"
    label = pg.evaluate("() => { const b=document.getElementById('ux-imp-trust');"
                        " return b ? b.closest('label').innerText.trim() : null; }")
    note = pg.evaluate("() => { const n=document.getElementById('ux-imp-trust-note');"
                       " return n ? n.innerText.trim() : null; }")
    summary = pg.evaluate("() => (document.getElementById('ux-imp-summary')||{}).innerText || ''")
    pg.screenshot(path=str(OUT / "import-after-scan-en.png"))
    step("import/after-scan", trust_row_visible=after, checked=checked, label=label,
         checkbox_px=round(cbw),
         note=note, found=summary[:300])
    assert after, f"the scan found a backup but no toggle appeared; summary={summary[:200]}"
    assert label == EXPECT["en"][1], f"import label is {label!r}"
    assert note and "not trusting" in note, "the import caveat lost its other half"

    # the three states the server distinguishes, read off the live control
    pg.uncheck("#ux-imp-trust")
    off = pg.evaluate("() => _uxImTrust()")
    pg.check("#ux-imp-trust")
    on = pg.evaluate("() => _uxImTrust()")
    pg.evaluate("() => { document.getElementById('ux-imp-trust-row').style.display='none'; }")
    hidden = pg.evaluate("() => _uxImTrust()")
    step("import/three-states", unchecked=off, checked=on, hidden=hidden)
    assert (off, on, hidden) == (False, True, None), (off, on, hidden)

    # ---- 3. the same toggle in fr + ar on the import dialog ---------------------
    for lang in ("fr", "ar"):
        pg.evaluate("l => { try { localStorage.setItem('oo.lang', l); } catch(e){} }", lang)
        pg.reload(wait_until="networkidle"); pg.wait_for_timeout(1800)
        pg.evaluate("() => { const d=document.getElementById('guide-wizard'); if (d&&d.open) d.close(); }")
        pg.evaluate("() => openUnifiedImport()"); pg.wait_for_timeout(700)
        pg.fill("#ux-imp-src", BAK_DIR)
        pg.click("#ux-import button[onclick^=\"_uxImScan\"]"); pg.wait_for_timeout(4000)
        label = pg.evaluate("() => { const b=document.getElementById('ux-imp-trust');"
                            " return b ? b.closest('label').innerText.trim() : null; }")
        note = pg.evaluate("() => { const n=document.getElementById('ux-imp-trust-note');"
                           " return n ? n.innerText.trim() : null; }")
        pg.screenshot(path=str(OUT / f"import-after-scan-{lang}.png"))
        step(f"import/{lang}", label=label, note=note,
             label_matches=(label == EXPECT[lang][1]))
        assert label == EXPECT[lang][1], f"{lang}: import label is {label!r}"

    rec["ok"] = True
    b.close()

assert not rec["pageerrors"], rec["pageerrors"]
(OUT / "clickthrough.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
print("\nCLICK-THROUGH OK ->", OUT)
