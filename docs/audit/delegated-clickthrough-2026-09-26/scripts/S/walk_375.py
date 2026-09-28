"""Row S: the 375px-wide pass in en (horizontal scroll + clipped text) on the surfaces walked."""
import json
import sys
from pathlib import Path
sys.path.insert(0, "/tmp/claude-0/walk/S")
import walk_a as W  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

OUTF = Path("/tmp/claude-0/walk/S/raw_375.json")
res = {"console_errors": [], "page_errors": [], "http_errors": []}
CLIP_JS = """(root) => {
  const out = [];
  const host = document.querySelector(root); if (!host) return ['no host'];
  host.querySelectorAll('*').forEach(e => {
    if (!e.offsetParent) return;
    const cs = getComputedStyle(e);
    if ((cs.overflowX === 'hidden' || cs.overflow === 'hidden' || cs.textOverflow === 'ellipsis') && e.scrollWidth > e.clientWidth + 1)
      out.push({clip: true, tag: e.tagName, id: e.id, text: e.innerText.slice(0, 80)});
    const r = e.getBoundingClientRect();
    if ((r.right > window.innerWidth + 1 || r.left < -1) && e.innerText && e.innerText.trim() && e.children.length === 0)
      out.push({offscreen: true, tag: e.tagName, id: e.id, left: r.left, right: r.right, text: e.innerText.slice(0, 80)});
  });
  return out.slice(0, 30);
}"""
OVER = "() => document.documentElement.scrollWidth - document.documentElement.clientWidth"

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=W.CHROME, args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 375, "height": 800})
    ctx.add_init_script(W.INIT)
    pg = ctx.new_page()
    pg.on("console", lambda m: res["console_errors"].append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: res["page_errors"].append(str(e)))
    pg.on("response", lambda r: res["http_errors"].append([r.url, r.status]) if r.status >= 400 else None)
    W.unlock_if_needed(pg)
    W.settle_chrome(pg)
    pg.wait_for_timeout(1500)
    res["lang"] = pg.evaluate("() => document.documentElement.lang")
    res["home_overflow"] = pg.evaluate(OVER)
    res["home_clip"] = pg.evaluate(CLIP_JS, "#home-stats")
    pg.screenshot(path=str(W.SHOTS / "S-375-home-en.png"))
    # Settings: the top-bar gear button (the sidebar is off-canvas below 600px)
    res["settings_btn_visible"] = pg.locator("button[onclick=\"showTab('settings')\"]").is_visible()
    res["hamburger_visible"] = pg.locator("#hamburger").is_visible()
    if not pg.evaluate("() => document.body.classList.contains('nav-open')"):
        pg.click("#hamburger")
        pg.wait_for_timeout(600)
    pg.screenshot(path=str(W.SHOTS / "S-375-nav-open-en.png"))
    pg.click("button[onclick=\"showTab('settings')\"]")
    pg.wait_for_timeout(2500)
    res["coach_visible_on_settings"] = pg.locator("#net-coach-dismiss").is_visible()
    if res["coach_visible_on_settings"]:
        pg.screenshot(path=str(W.SHOTS / "S-375-coachmark-en.png"))
        pg.click("#net-coach-dismiss")
        pg.wait_for_timeout(500)
    pg.click("#set-subtabs button[data-tab='advanced']")
    pg.wait_for_selector("details[data-adv='qualification'] > summary", state="visible", timeout=15000)
    W.expand_quality(pg)
    pg.wait_for_timeout(800)
    res["quality_overflow"] = pg.evaluate(OVER)
    res["quality_clip"] = pg.evaluate(CLIP_JS, "#qualification-panel")
    res["panel_width"] = pg.evaluate("() => document.getElementById('qualification-panel').getBoundingClientRect().width")
    pg.locator("#qual-state").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(W.SHOTS / "S-375-quality-gates-en.png"))
    pg.locator("#qual-admission").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(W.SHOTS / "S-375-admission-en.png"))
    res["admission_rows"] = pg.evaluate("""() => Array.from(document.querySelectorAll('#qual-admission .row')).map(r => {
       const a = r.children[0].getBoundingClientRect(), c = r.children[1].getBoundingClientRect();
       return {info: [Math.round(a.left), Math.round(a.right)], action: [Math.round(c.left), Math.round(c.right)], text: r.innerText.replace(/\\s+/g,' ').slice(0,60)}; })""")
    pg.locator("#qual-overlay").scroll_into_view_if_needed()
    pg.wait_for_timeout(300)
    pg.screenshot(path=str(W.SHOTS / "S-375-overlay-en.png"))
    # Library -> Database & storage
    if not pg.evaluate("() => document.body.classList.contains('nav-open')"):
        pg.click("#hamburger")
        pg.wait_for_timeout(500)
    pg.click("#navGroups button.nav-item[data-tab='library']")
    pg.wait_for_timeout(800)
    pg.click("#library-views button[data-tab='storage']")
    pg.wait_for_timeout(3000)
    res["library_overflow"] = pg.evaluate(OVER)
    res["library_clip"] = pg.evaluate(CLIP_JS, "#db-stats")
    pg.locator("#db-stats").scroll_into_view_if_needed()
    pg.screenshot(path=str(W.SHOTS / "S-375-library-db-en.png"))
    b.close()
OUTF.write_text(json.dumps(res, indent=2, ensure_ascii=False))
print(json.dumps(res, indent=1, ensure_ascii=False))
