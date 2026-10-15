"""Real-data walk: row D's surfaces over a REAL OSM extract (Liechtenstein, osm2pgsql test data, 2013-08-03).

Loopback only: the browser aborts every request that is not to this server, and airplane mode is read back first.
Records per surface x language x width: text, console errors, page errors, horizontal overflow, junk tokens.
"""
import json
import os
import re
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = os.environ.get("OO_WALK_BASE", "http://127.0.0.1:8771")
OUT = os.environ.get("OO_WALK_OUT", "/tmp/claude-0/walk/out")
os.makedirs(OUT, exist_ok=True)
JUNK = re.compile(r"\b(undefined|NaN|null)\b|\[object Object\]|\{[a-z_]+\}")
report = {"observations": [], "errors": [], "offline_requests_blocked": []}


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.load(r)


def main():
    req = urllib.request.Request(BASE + "/api/system/network", data=b'{"online":false}', headers={"content-type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=30).read()
    net = get("/api/system/network")
    assert net.get("online") is False, net
    report["network_before"] = net
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome", args=["--no-sandbox"])
        for lang in ("en", "ar"):
            for width in (1440, 390):
                ctx = b.new_context(viewport={"width": width, "height": 900}, locale=lang)
                page = ctx.new_page()
                tag = f"{lang}-{width}"

                def route(r, _tag=tag):
                    if r.request.url.startswith(BASE) or r.request.url.startswith("data:") or r.request.url.startswith("blob:"):
                        r.continue_()
                    else:
                        report["offline_requests_blocked"].append(r.request.url)
                        r.abort()

                page.route("**/*", route)
                page.on("pageerror", lambda e, _t=tag: report["errors"].append([_t, "pageerror", str(e)[:300]]))
                page.on("console", lambda m, _t=tag: report["errors"].append([_t, "console." + m.type, m.text[:300]]) if m.type in ("error",) else None)
                page.on("response", lambda r, _t=tag: report["errors"].append([_t, "http" + str(r.status), r.url[-120:]]) if r.status >= 400 else None)
                page.goto(BASE + "/", wait_until="domcontentloaded")
                page.wait_for_timeout(1500)
                page.evaluate("""(l) => { try { localStorage.setItem('oo.lang', l); } catch (e) {} if (window.OOI18N && OOI18N.setLang) OOI18N.setLang(l); }""", lang)
                page.wait_for_timeout(500)

                def observe(name, sel, extra=None):
                    txt = page.evaluate("(s) => { const e = document.querySelector(s); return e ? e.innerText : null; }", sel)
                    ov = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
                    rec = {"surface": name, "tag": tag, "text": (txt or "")[:1500], "present": txt is not None, "overflow_px": ov,
                           "junk": JUNK.findall(txt or "")}
                    if extra:
                        rec.update(extra)
                    report["observations"].append(rec)
                    try:
                        loc = page.locator(sel).first
                        loc.scroll_into_view_if_needed(timeout=3000)
                        loc.screenshot(path=f"{OUT}/{name}-{tag}.png", timeout=5000)
                    except Exception:   # a hidden or zero-size element: the viewport is the record
                        page.screenshot(path=f"{OUT}/{name}-{tag}.png", full_page=False)

                # 1 World map (sidebar tab): the vintage line, analytic 1, the local geocoder
                page.evaluate("() => { showTab('timemap'); }")
                page.wait_for_timeout(2500)
                observe("world-vintage", "#oomap-osm-vintage")
                observe("completeness", "#osm-completeness")
                if lang == "en":
                    page.fill("#osm-geo-q", "Bahnhofstrasse")
                    page.click("#osm-geo-form button[type=submit]")
                    page.wait_for_timeout(1500)
                    observe("geocoder-bahnhofstrasse", "#osm-geocoder")
                    page.fill("#osm-geo-q", "Nowhere street 99")
                    page.click("#osm-geo-form button[type=submit]")
                    page.wait_for_timeout(1000)
                    observe("geocoder-not-located", "#osm-geo-out")
                # 2 Settings -> Maps: the picker
                page.evaluate("() => { showTab('settings'); const b = [...document.querySelectorAll('#set-subtabs button')].find(x => /^\\s*(OpenStreetMap|Maps)\\s*$/i.test(x.textContent)); if (b) b.click(); }")
                page.wait_for_timeout(2500)
                observe("settings-picker", "#osm-lane-picker")
                # 3 Living sources -> OpenStreetMap
                page.evaluate("() => { showTab('living'); }")
                page.wait_for_timeout(2000)
                observe("living", "#tab-living")
                ctx.close()
        b.close()
    json.dump(report, open(f"{OUT}/walk.json", "w"), indent=1, ensure_ascii=False)
    print("observations", len(report["observations"]), "errors", len(report["errors"]), "blocked", len(report["offline_requests_blocked"]))
    for o in report["observations"]:
        print(o["tag"], o["surface"], "present" if o["present"] else "ABSENT", "overflow", o["overflow_px"], "junk", o["junk"])
    for e in report["errors"][:15]:
        print("ERR", e)


if __name__ == "__main__":
    main()
