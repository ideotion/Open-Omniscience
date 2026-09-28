"""Row S, S10: the memory-floor refusal, read through the real UI after a restart (encrypted, unlocked via #pw)."""
import json
import sys
from pathlib import Path
sys.path.insert(0, "/tmp/claude-0/walk/S")
import walk_a as W  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

tag = sys.argv[1]
OUTF = Path(f"/tmp/claude-0/walk/S/raw_s10_{tag}.json")
res = {"console_errors": [], "page_errors": [], "http_errors": [], "toasts": []}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=W.CHROME, args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1440, "height": 950})
    ctx.add_init_script(W.INIT)
    pg = ctx.new_page()
    pg.on("console", lambda m: res["console_errors"].append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: res["page_errors"].append(str(e)))
    pg.on("response", lambda r: res["http_errors"].append([r.url, r.status]) if r.status >= 400 else None)
    res["unlocked_via_ui"] = W.unlock_if_needed(pg)
    W.settle_chrome(pg)
    res["net_before"] = W.api_json(pg, "/api/system/network")
    if res["net_before"].get("online"):
        pg.wait_for_function("() => document.getElementById('net-plane').getAttribute('fill') === 'none'", timeout=20000)
        t0 = W.now_ms(pg)
        pg.click("#net-toggle")
        pg.wait_for_function("() => (window.__toasts||[]).some(x => /Offline —/.test(x.text))", timeout=15000)
        res["net_toasts"] = [x["text"] for x in W.toasts_since(pg, t0)]
    res["net_after"] = W.api_json(pg, "/api/system/network")
    res["plane_fill"] = pg.get_attribute("#net-plane", "fill")
    pg.click("button[onclick=\"showTab('settings')\"]")
    pg.wait_for_timeout(1500)
    if pg.locator("#net-coach-dismiss").is_visible():
        pg.click("#net-coach-dismiss")
    pg.click("#set-subtabs button[data-tab='advanced']")
    W.expand_quality(pg)
    pr = W.panel_read(pg)
    res["bulk"] = pr["bulk"]
    res["overlay"] = pr["overlay"]
    res["state"] = pr["state"]
    res["bulk_api"] = W.api_json(pg, "/api/sources/qualify-bulk/status")
    res["done_zero_anywhere"] = pg.evaluate("() => /done \\[0\\//.test(document.body.innerText)")
    shot = pg.locator("#qualify-bulk-status")
    shot.scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.locator("#qualification-panel").screenshot(path=str(W.SHOTS / f"S-S10-{tag}-panel-en.png"))
    pg.screenshot(path=str(W.SHOTS / f"S-S10-{tag}-bulk-en.png"))
    b.close()
OUTF.write_text(json.dumps(res, indent=2, ensure_ascii=False))
print(json.dumps({k: v for k, v in res.items() if k != "bulk_api"}, indent=1, ensure_ascii=False))
print("floor:", json.dumps(res["bulk_api"].get("floor"), ensure_ascii=False), "backlog:", res["bulk_api"].get("backlog"))
