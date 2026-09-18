#!/usr/bin/env python3
"""Chromium click-through of the law METADATA MODEL in the reader — en / fr / de / ar.

Drives the pinned Chromium build over the DevTools Protocol (see cdp.py for why not
playwright here) against a TWO-LANGUAGE document seeded through the real tracker: the
original and its official translation, on one identity.

What it measures, per locale: the licence row, the redistribution row, the provenance
row (phrase AND body, as separate elements), the identity row, the other-language-versions
section in BOTH directions, and that every phrase this slice added is not English outside
`en`.
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
DOC = int(os.environ["OO_DOC_ID"])
TRANSLATION = int(os.environ["OO_TRANSLATION_ID"])

OWED = [
    "Licence", "Redistribution", "Provenance", "Identity",
    "This licence permits redistribution",
    "Other language versions",
    "The original text as issued",
    "An official translation",
    "Each language version is tracked as its own document",
]
LOCALES = ["en", "fr", "de", "ar"]
report: dict = {"base": BASE, "document": DOC, "translation": TRANSLATION, "locales": {}}

page = open_page(DEBUG_PORT)
page.call("Page.enable")
page.call("Runtime.enable")
page.call("Emulation.setDeviceMetricsOverride", width=1280, height=1000,
          deviceScaleFactor=1, mobile=False)

for loc in LOCALES:
    page.call("Page.navigate", url=f"{BASE}/")
    page.pump("Page.loadEventFired")
    page.evaluate(f"localStorage.setItem('oo.lang', {json.dumps(loc)})")
    entry: dict = {}
    for name, doc_id in (("original", DOC), ("translation", TRANSLATION)):
        before = len(page.events)
        page.call("Page.navigate", url=f"{BASE}/api/law/documents/{doc_id}/view")
        page.pump("Page.loadEventFired")
        page.evaluate("new Promise(r => setTimeout(r, 900))")
        body = page.evaluate("document.body.innerText") or ""
        shot = OUT / f"law-model-{loc}-{name}.png"
        data = page.call("Page.captureScreenshot", format="png", captureBeyondViewport=True)
        shot.write_bytes(base64.b64decode(data["data"]))
        entry[name] = {
            "screenshot": shot.name,
            "dir": page.evaluate(
                "document.documentElement.getAttribute('dir') || getComputedStyle(document.body).direction"
            ),
            "meta_block": page.evaluate(
                "(document.querySelector('.meta')||{innerText:''}).innerText.trim()"
            ),
            "other_versions": page.evaluate(
                "Array.from(document.querySelectorAll('.langs li')).map(e => e.innerText.trim())"
            ),
            "other_versions_heading": page.evaluate(
                "(document.querySelector('.langs h2')||{innerText:''}).innerText.trim()"
            ),
            # The provenance phrase and its body must be SEPARATE elements, or the phrase
            # can never be translated.
            "provenance_spans": page.evaluate(
                "Array.from(document.querySelectorAll('.mrow b span')).map(e => e.innerText.trim())"
            ),
            "still_english": [p for p in OWED if p in body],
            "page_errors": [
                e["params"]["exceptionDetails"].get("text", "")
                for e in page.events[before:]
                if e["method"] == "Runtime.exceptionThrown"
            ],
        }
    report["locales"][loc] = entry

(OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(report, indent=2, ensure_ascii=False))
