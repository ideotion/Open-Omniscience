import json, sys
sys.path.insert(0, "/tmp/claude-0/walk/M-recheck")
from harness import *  # noqa
BASE = "http://127.0.0.1:8828"
R = {}
with sync_playwright() as p:
    b, ctx = browser_ctx(p)
    page = ctx.new_page(); attach(page, "main")
    page.on("dialog", lambda d: d.dismiss())
    unlock_if_needed(page, BASE); close_guide(page)
    if page.evaluate("document.documentElement.lang") != "en":
        set_lang(page, "en")
    open_settings_advanced(page)
    page.wait_for_timeout(1000)
    R["closed"] = page.evaluate("""() => { const d=document.querySelector('details.adv-sec[data-adv=bulletin]'); const u=document.querySelector('details.adv-sec[data-adv=uninstall]');
      return {uninstall_open: u.open, bulletin_checkVisibility: d.checkVisibility(), summary_checkVisibility: d.querySelector('summary').checkVisibility(), rect: d.getBoundingClientRect().height,
              adv_summaries_visible: [...document.querySelectorAll('details.adv-sec > summary')].filter(s=>s.checkVisibility()).map(s=>s.innerText.split('\\n')[0].slice(0,40))}; }""")
    page.locator("details.adv-sec[data-adv=uninstall] > summary").scroll_into_view_if_needed()
    shot(page, "Mr-D6-advanced-bottom-closed-en.png")
    page.locator("details.adv-sec[data-adv=uninstall] > summary").click(); page.wait_for_timeout(800)
    R["opened"] = page.evaluate("""() => { const d=document.querySelector('details.adv-sec[data-adv=bulletin]'); return {bulletin_checkVisibility: d.checkVisibility(), y_bulletin: d.getBoundingClientRect().top, y_wipe: [...document.querySelectorAll('#uninstall-panel button.danger')][0].getBoundingClientRect().top}; }""")
    page.locator("details.adv-sec[data-adv=bulletin] > summary").scroll_into_view_if_needed()
    shot(page, "Mr-D6-bulletin-inside-uninstall-en.png")
    b.close()
print(json.dumps(R, indent=1))
