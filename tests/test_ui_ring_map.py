"""Cross-country ring map + per-language breakdown in the Groups subtab (item #4).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Insights -> Groups gains a "Cross-country map of a concept": pick a cross-language
ring and see where its coverage comes from on the ooMap component (via
GET /api/insights/ring-countries), plus the per-language mention split that
GET /api/insights/top?group=true already returns (language_breakdown). Counts only,
caveats visible, unlocated sources shown honestly and never mapped. Pure
string-assertion wiring guard over the static assets (browser-unverified per fork-3).
"""

from __future__ import annotations

from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")


def test_ring_map_hosts_exist():
    assert 'id="sg-ringmap-pick"' in _HTML
    assert 'id="sg-ringmap"' in _HTML and 'id="sg-ringmap-detail"' in _HTML
    assert 'onchange="showRingMap(this.value)"' in _HTML


def test_showringmap_uses_ring_countries_and_ooMap():
    assert "function showRingMap(" in _JS
    assert "/api/insights/ring-countries?ring_id=" in _JS
    assert "await ooMap(host, {" in _JS  # renders on the shared ooMap component


def test_unlocated_sources_are_never_mapped_but_disclosed():
    # a country-less row goes to the unlocated bucket, not into the choropleth values
    assert "if (!c.country) { unloc = c; return; }" in _JS
    assert 't("Not mapped (source country unknown)")' in _JS
    assert "card-caveat" in _JS  # the unlocated note is a visible caveat


def test_language_breakdown_surfaced_from_grouped_top():
    # the per-language split comes from /top?group=true rows (language_breakdown), indexed by ring
    assert "_ringLangIndex" in _JS
    assert "f.ring_id && f.language_breakdown" in _JS
    assert 't("By language")' in _JS and 't("mentions per language")' in _JS


def test_counts_only_no_score():
    # the map colours by distinct-article spread + shows mentions; never a composite score
    assert "values[c.country] = c.articles" in _JS
    assert "ringScore" not in _JS and "c.score" not in _JS
    # method + caveat from the endpoint ride the ooMap render (honesty visible)
    assert "method: d.method" in _JS and "caveat: d.caveat" in _JS


def test_ring_map_strings_are_translated():
    en = (_STATIC / "locales" / "en.json").read_text(encoding="utf-8")
    de = (_STATIC / "locales" / "de.json").read_text(encoding="utf-8")
    assert "Cross-country map of a concept" in en and "Cross-country map of a concept" in de
