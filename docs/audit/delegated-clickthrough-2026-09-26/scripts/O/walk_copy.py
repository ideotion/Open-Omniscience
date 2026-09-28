"""O15a: the app-stopped folder copy of the encrypted throwaway, started on 8835."""
import json
import traceback
from playwright.sync_api import sync_playwright
import lib
from lib import Rec, close_guide, save, shot, api, txt, unlock, living_open
rec = Rec(); R = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox","--no-proxy-server","--disable-background-networking"])
    pg = br.new_page(viewport={"width": 1440, "height": 950}); rec.watch(pg, "copy")
    try:
        R["unlock"] = unlock(pg, "http://127.0.0.1:8835", "walk-pass-2026", wrong="not-the-passphrase")
        R["guide_open"] = pg.evaluate("() => { const d = document.getElementById('guide-wizard'); return !!(d && d.open); }")
        close_guide(pg)
        R["plane_fill"] = pg.evaluate("() => document.getElementById('net-plane').getAttribute('fill')")
        R["network"] = api(pg, "/api/system/network")["body"]
        R["storage"] = json.loads(api(pg, "/api/storage/lanes")["body"])
        R["living"] = json.loads(api(pg, "/api/living/overview")["body"])
        lib.settings_sub(pg, "data"); lib.storage_ready(pg)
        R["storage_rows"] = pg.evaluate("() => [...document.querySelectorAll('#storage-lanes tbody tr')].map(r => [...r.children].map(c => c.innerText.trim()))")
        shot(pg, "O-O15-copy-storage-en.png")
        living_open(pg)
        R["living_facts"] = txt(pg, "#living-wiki-facts")
        R["living_stream_cap"] = txt(pg, "#living-stream-cap")
        shot(pg, "O-O15-copy-living-en.png", full=True)
        pg.goto("http://127.0.0.1:8835/api/system/doctor"); R["doctor"] = pg.evaluate("() => document.body.innerText")
        pg.goto("http://127.0.0.1:8835/", wait_until="networkidle"); pg.wait_for_timeout(1000); close_guide(pg)
        msgs = []
        pg.on("dialog", lambda d: (msgs.append(d.message), d.accept()))
        pg.click("#app-shutdown"); pg.wait_for_timeout(3500)
        R["shutdown_confirm"] = msgs
    except Exception:
        R["_exception"] = traceback.format_exc()[-2500:]; print(R["_exception"])
    save("raw-copy.json", {"R": R, "page_errors": rec.page_errors, "console_errors": rec.console_errors, "http": rec.http})
    br.close()
print("done")
