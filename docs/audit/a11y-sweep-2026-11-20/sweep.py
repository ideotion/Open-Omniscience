"""0.9 row D (S4): the axe accessibility sweep at three widths, report only.

NOTHING HERE GOES ONLINE, and the sweep checks it. Before the first page it engages airplane mode
through the app's own endpoint and reads it back, and the browser aborts every request that is not
to this loopback server.

Three passes against one seeded plaintext state (``scripts/ui_clickthrough_seed.py``, state C):

1. ALL axe rules, in the default theme (Ink), on every surface at 1440x900, 768x1024 and 390x844.
2. The two axe rules that measure colour (``color-contrast`` and ``link-in-text-block``), in every
   other selectable theme, on every surface at 1440x900.
3. The article reader again, all rules at the three widths, with the browser in DARK colour scheme.
   The reader does not take the app theme: it has its own palette, dark by default and light under
   ``prefers-color-scheme: light``. Playwright's default scheme is light, so passes 1 and 2 measured
   the reader's light palette only; this pass measures the dark one.

The surfaces are the 13 sidebar tabs (each on its default subtab), Settings, the task-manager
window (``/tasks``) and the article reader (``/api/articles/{id}/view``).

axe is the vendored ``scripts/vendor/axe-core/axe.min.js``. It is evaluated through the DevTools
protocol, never as an inline script tag, so the app's Content-Security-Policy stays as it ships
(the same choice as ``PlaywrightUiWalkDriver.run_axe``).

Usage (the app already running on the seeded data folder, with --loop asyncio):
    OO_WALK_BASE=http://127.0.0.1:8765 OO_WALK_OUT=docs/audit/a11y-sweep-2026-11-20 python sweep.py
"""
import json
import os
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8765")
OUT = Path(os.environ.get("OO_WALK_OUT", "."))
REPO = Path(os.environ.get("OO_REPO", Path(__file__).resolve().parents[3]))
AXE = (REPO / "scripts" / "vendor" / "axe-core" / "axe.min.js").read_text(encoding="utf-8")

WIDTHS = [(1440, 900), (768, 1024), (390, 844)]
TABS = ["home", "feed", "explore", "insights", "observatory", "timemap", "law", "agenda",
        "climate", "indices", "markets", "living", "library"]
DEFAULT_THEME = "ink"
OTHER_THEMES = ["midnight", "cyber", "forest", "aubergine", "garnet", "solar", "sepia", "terminal",
                "contrast", "light", "dawn", "mint", "paper"]

RUN_AXE = """
async (only) => {
  const opts = {resultTypes: ['violations']};
  if (only) opts.runOnly = {type: 'rule', values: only};
  const r = await axe.run(document, opts);
  return r.violations.map(v => ({
    rule: v.id, impact: v.impact || '', help: v.help, helpUrl: v.helpUrl,
    wcag: v.tags.filter(t => /^wcag\\d|^best-practice$/.test(t)),
    nodes: v.nodes.length,
    targets: v.nodes.slice(0, 25).map(n => n.target.join(' ')),
    sample: (v.nodes[0] && v.nodes[0].failureSummary || '').split('\\n').slice(0, 3).join(' | ').slice(0, 300),
    per_node: v.nodes.slice(0, 25).map(n => (n.failureSummary || '').split('\\n').slice(1, 2).join('').trim().slice(0, 240)),
  }));
}
"""


def api(path, body=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def settle(pg, ms=900):
    pg.wait_for_timeout(ms)
    pg.evaluate("""() => { for (const d of document.querySelectorAll('dialog[open]')) {
        if (d.id !== 'tab-analyze') { try { d.close(); } catch (e) {} } } }""")
    pg.wait_for_timeout(150)


def ensure_axe(pg):
    if not pg.evaluate("() => typeof window.axe !== 'undefined'"):
        pg.evaluate(AXE)


def open_spa(pg, theme):
    pg.goto(BASE + "/", wait_until="domcontentloaded")
    pg.wait_for_function("() => typeof showTab === 'function' && typeof setTheme === 'function'", timeout=30000)
    pg.evaluate("(t) => setTheme(t)", theme)
    settle(pg, 1500)


def surfaces(article_id):
    for t in TABS:
        yield t, ("spa", t)
    yield "settings", ("spa", "settings")
    yield "tasks", ("url", "/tasks")
    yield "reader", ("url", f"/api/articles/{article_id}/view")


def visit(pg, how, theme):
    kind, target = how
    if kind == "spa":
        if "/tasks" in pg.url or "/api/" in pg.url or pg.url in ("about:blank", ""):
            open_spa(pg, theme)
        pg.evaluate("(t) => showTab(t)", target)
        settle(pg)
    else:
        pg.goto(BASE + target, wait_until="domcontentloaded")
        # /tasks reads the app theme from the stored ui settings (taskmanager.js); the reader does not (pass 3)
        settle(pg, 1200)
    ensure_axe(pg)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    api("/api/system/network", {"online": False})
    report = {"base": "loopback", "axe": AXE.split("\n", 1)[0].strip("/*! "),
              "airplane_before": api("/api/system/network").get("online") is False,
              "widths": WIDTHS, "tabs": TABS, "themes_contrast": OTHER_THEMES, "runs": [], "blocked": []}
    article_id = api("/api/articles?limit=1")["results"][0]["id"]
    report["reader_article_id"] = article_id
    with sync_playwright() as p:
        exe = os.environ.get("OO_WALK_CHROMIUM")  # a pinned browser build, when the installed Playwright expects another
        br = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        ctx = br.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")

        def guard(route):
            u = route.request.url
            if u.startswith(BASE) or u.startswith("data:") or u.startswith("blob:"):
                return route.continue_()
            report["blocked"].append(u[:200])
            return route.abort()
        ctx.route("**/*", guard)
        pg = ctx.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:200]))
        open_spa(pg, DEFAULT_THEME)

        def one(label, how, theme, width, height, only, scheme="light"):
            pg.set_viewport_size({"width": width, "height": height})
            t0 = time.time()
            try:
                visit(pg, how, theme)
                vio = pg.evaluate(RUN_AXE, only)
                err = None
            except Exception as e:  # recorded, never swallowed: a surface the sweep could not audit is a finding too
                vio, err = [], str(e)[:300]
            report["runs"].append({"surface": label, "theme": theme, "width": width, "height": height,
                                   "rules": ",".join(only) if only else "all", "scheme": scheme, "violations": vio,
                                   "error": err, "seconds": round(time.time() - t0, 1),
                                   "page_errors": errors[:]})
            errors.clear()
            print(f"{label:12s} {theme:10s} {width:5d} {'colour' if only else 'all':8s} "
                  f"{len(vio)} rules, {sum(v['nodes'] for v in vio)} nodes{' ERR ' + err if err else ''}", flush=True)

        for width, height in WIDTHS:
            for label, how in surfaces(article_id):
                one(label, how, DEFAULT_THEME, width, height, None)
        for theme in OTHER_THEMES:
            open_spa(pg, theme)
            for label, how in surfaces(article_id):
                one(label, how, theme, 1440, 900, ["color-contrast", "link-in-text-block"])
            open_spa(pg, DEFAULT_THEME)
        pg.emulate_media(color_scheme="dark")
        for width, height in WIDTHS:
            one("reader", ("url", f"/api/articles/{article_id}/view"), "own-dark", width, height, None, "dark")
        pg.emulate_media(color_scheme="light")
        br.close()
    report["airplane_after"] = api("/api/system/network").get("online") is False
    (OUT / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
