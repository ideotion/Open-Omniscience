"""Explore > Links: download the whole corpus's citation graph (R684, Lane M).

``GET /api/links/export.graphml`` and ``/export.json`` had no button. The Links panel
now ends with two same-origin downloads and a visible caveat saying the file is the
WHOLE corpus, not the analysis on screen, with the caps the server applies.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.js_source_helper import function_body

_ROOT = Path(__file__).resolve().parents[1]
_AN = (_ROOT / "src" / "static" / "app-analysis.js").read_text(encoding="utf-8")
_LINKS = (_ROOT / "src" / "api" / "link_analysis.py").read_text(encoding="utf-8")


def test_the_two_downloads_are_same_origin_files():
    body = function_body(_AN, "_anLinksHtml")
    hrefs = re.findall(r'href="([^"]+)"', body)
    assert hrefs == ["/api/links/export.graphml", "/api/links/export.json"], hrefs
    assert body.count(" download=") == 2
    assert "target=" not in body and "http" not in body


def test_the_caveat_is_visible_and_says_whole_corpus():
    body = function_body(_AN, "_anLinksHtml")
    assert 'class="card-caveat"' in body
    assert "your whole corpus, not only this analysis" in body


def test_the_caps_the_caveat_names_are_the_servers():
    # "the 2,000 most-cited sites and at most 2,000 of their articles" must stay true.
    sig = re.search(r"def _citation_graph_compute\(db, \*, min_citations: int = 1, max_nodes: int = (\d+)\)", _LINKS)
    assert sig and sig.group(1) == "2000", "the default cap moved: update the caveat"
    assert _LINKS.count("[:max_nodes]") >= 2
