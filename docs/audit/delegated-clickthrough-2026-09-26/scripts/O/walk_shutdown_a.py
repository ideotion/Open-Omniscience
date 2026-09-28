"""O15a part 1: read A's figures, then shut A down through the top-bar power icon + confirm."""
import json
from playwright.sync_api import sync_playwright
from lib import Rec, close_guide, save, shot, api
rec = Rec(); R = {}
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox","--no-proxy-server","--disable-background-networking"])
    pg = br.new_page(viewport={"width": 1440, "height": 950}); rec.watch(pg, "A-shutdown")
    pg.goto("http://127.0.0.1:8834/", wait_until="networkidle"); pg.wait_for_timeout(1200); close_guide(pg)
    R["storage"] = json.loads(api(pg, "/api/storage/lanes")["body"])
    R["living"] = json.loads(api(pg, "/api/living/overview")["body"])
    R["shutdown_title"] = pg.get_attribute("#app-shutdown", "title")
    dialogs = []
    def on_dialog(d):
        dialogs.append(d.message); d.accept()
    pg.on("dialog", on_dialog)
    pg.click("#app-shutdown")
    pg.wait_for_timeout(4000)
    R["confirm_messages"] = dialogs
    R["page_text_after"] = pg.evaluate("() => document.body.innerText.slice(0, 600)")
    shot(pg, "O-O15-shutdown-en.png")
    save("raw-shutdown-a.json", {"R": R, "page_errors": rec.page_errors, "console_errors": rec.console_errors, "http": rec.http})
    br.close()
print("done")
