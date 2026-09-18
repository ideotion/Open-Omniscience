#!/usr/bin/env python3
"""Chromium click-through of the law reader -- en / fr / de / ar.

Drives the pinned Chromium build over the DevTools Protocol (see cdp.py for why not
playwright here). Visits the reader's current-text page and its `?version=` page for a
document seeded through the REAL tracker, in four locales, capturing a full-page
screenshot and the rendered text of every surface this slice added.

The locale is set the way the app's own engine reads it -- `localStorage["oo.lang"]`,
which `i18n.js:119 current()` reads with NO navigator fallback -- on the same origin,
before navigating to the reader, because the reader page loads i18n.js and translates
on load.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdp import open_page  # noqa: E402

OUT = Path(sys.argv[1])
PORT = int(sys.argv[2])
DEBUG_PORT = int(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)

BASE = f"http://127.0.0.1:{PORT}"
DOC_ID = int(os.environ["OO_DOC_ID"])
BASELINE_REV = int(os.environ["OO_BASELINE_REV"])

# Every phrase this slice added, as the locale files key them. Checked per locale so a
# string that silently stayed English is a NAMED failure rather than a general "looks ok".
OWED = [
    "Versions",
    "Current text (as last captured)",
    "first captured snapshot",
    "an amendment",
    "Enacted",
    "This text is in force from",
    "Captured by this instance",
    "Showing",
    "measured against the previous version",
    "the first captured snapshot — there is nothing earlier to measure it against",
]
LOCALES = ["en", "fr", "de", "ar"]
report: dict = {"base": BASE, "document": DOC_ID, "baseline_revision": BASELINE_REV, "locales": {}}

page = open_page(DEBUG_PORT)
page.call("Page.enable")
page.call("Runtime.enable")
page.call(
    "Emulation.setDeviceMetricsOverride",
    width=1280, height=900, deviceScaleFactor=1, mobile=False,
)

for loc in LOCALES:
    # Same origin, so the localStorage write lands where the reader will read it.
    page.call("Page.navigate", url=f"{BASE}/")
    page.pump("Page.loadEventFired")
    page.evaluate(f"localStorage.setItem('oo.lang', {json.dumps(loc)})")

    entry: dict = {}
    for name, url in (
        ("current", f"{BASE}/api/law/documents/{DOC_ID}/view"),
        ("baseline", f"{BASE}/api/law/documents/{DOC_ID}/view?version={BASELINE_REV}"),
    ):
        before = len(page.events)
        page.call("Page.navigate", url=url)
        page.pump("Page.loadEventFired")
        # Let the i18n walker's debounced MutationObserver pass finish.
        page.evaluate("new Promise(r => setTimeout(r, 900))")
        body = page.evaluate("document.body.innerText")
        shot = OUT / f"law-reader-{loc}-{name}.png"
        data = page.call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
        shot.write_bytes(base64.b64decode(data["data"]))
        errors = [
            e["params"]["exceptionDetails"].get("text", "")
            + " "
            + str(e["params"]["exceptionDetails"].get("exception", {}).get("description", ""))
            for e in page.events[before:]
            if e["method"] == "Runtime.exceptionThrown"
        ]
        entry[name] = {
            "screenshot": shot.name,
            "dir": page.evaluate(
                "document.documentElement.getAttribute('dir') || getComputedStyle(document.body).direction"
            ),
            "html_lang": page.evaluate("document.documentElement.lang || ''"),
            "versions_listed": page.evaluate("document.querySelectorAll('.versions li').length"),
            "version_links": page.evaluate(
                "Array.from(document.querySelectorAll('.versions a,.versions li')).map(e => e.innerText.trim()).slice(0,8)"
            ),
            "article_chars": page.evaluate(
                "(document.querySelector('article')||{innerText:''}).innerText.length"
            ),
            "meta_block": page.evaluate(
                "(document.querySelector('.meta')||{innerText:''}).innerText.trim()"
            ),
            "body_chars": len(body or ""),
            # Which owed phrases are STILL IN ENGLISH on this page. For `en` that is
            # all the ones the page shows (the control); for fr/de/ar any hit is an
            # untranslated string.
            "still_english": [p for p in OWED if p in (body or "")],
            "page_errors": errors,
        }
    # The tracked-document panel (Governments -> Law) is the OTHER surface this slice
    # changes: `last_status` renders there, and this slice made one of its values longer
    # ("changed (+96 bytes vs the previous version)"). Walked in the same four locales so
    # a layout break or an untranslated neighbour is seen rather than assumed away.
    page.call("Page.navigate", url=f"{BASE}/")
    page.pump("Page.loadEventFired")
    page.evaluate("new Promise(r => setTimeout(r, 1200))")
    before = len(page.events)
    # The SIDEBAR button opens the main tab; the gov subtab nav then opens the Law facet.
    # Both are `[data-tab="law"]`, so the sidebar one has to be named specifically --
    # a bare `[data-tab="law"]` matches the subtab button inside the still-hidden page.
    page.evaluate(
        "(() => { const b = document.querySelector('.sidebar .nav-item[data-tab=\"law\"]');"
        " if (!b) return 'no sidebar button'; b.click(); return 'clicked'; })()"
    )
    page.evaluate("new Promise(r => setTimeout(r, 1200))")
    page.evaluate(
        "(() => { const n = document.querySelector('#gov-subtabs [data-tab=\"law\"]');"
        " if (!n) return 'no subtab'; n.click(); return 'clicked'; })()"
    )
    page.evaluate("new Promise(r => setTimeout(r, 2500))")
    shot = OUT / f"law-panel-{loc}.png"
    data = page.call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
    shot.write_bytes(base64.b64decode(data["data"]))
    panel = page.evaluate(
        "(document.querySelector('#gov-law')||{innerText:''}).innerText.trim().slice(0, 1400)"
    )
    entry["law_panel"] = {
        "screenshot": shot.name,
        "dir": page.evaluate(
            "document.documentElement.getAttribute('dir') || getComputedStyle(document.body).direction"
        ),
        "visible": page.evaluate(
            "(() => { const e = document.querySelector('#gov-law'); "
            "return !!e && getComputedStyle(e).display !== 'none'; })()"
        ),
        "rows": page.evaluate("document.querySelectorAll('#law-docs tbody tr').length"),
        "status_titles": page.evaluate(
            "Array.from(document.querySelectorAll('#law-docs [title]')).map(e => e.getAttribute('title')).slice(0, 6)"
        ),
        "text": panel,
        "page_errors": [
            e["params"]["exceptionDetails"].get("text", "")
            for e in page.events[before:]
            if e["method"] == "Runtime.exceptionThrown"
        ],
    }
    report["locales"][loc] = entry

(OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(report, indent=2, ensure_ascii=False))
