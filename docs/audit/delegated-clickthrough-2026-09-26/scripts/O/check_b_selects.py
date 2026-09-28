from playwright.sync_api import sync_playwright
import json
with sync_playwright() as p:
    br = p.chromium.launch(executable_path="/opt/pw-browsers/chromium", args=["--no-sandbox","--no-proxy-server","--disable-background-networking"])
    pg = br.new_page(viewport={"width": 1440, "height": 950})
    pg.goto("http://127.0.0.1:8835/", wait_until="networkidle"); pg.wait_for_timeout(1000)
    print(json.dumps(pg.evaluate("""() => ({collect_selects: [...document.querySelectorAll("details[data-adv='collect'] select")].map(s => s.id),
      collect_labels_mode: [...document.querySelectorAll("details[data-adv='collect'] label")].filter(l => /\\bmode\\b/i.test(l.innerText)).map(l => l.innerText),
      sch_mode: !!document.getElementById('sch-mode')})""")))
    br.close()
