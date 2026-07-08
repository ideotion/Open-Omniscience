"""Home "Latest in your corpus" panel (wave 4 I, task 1).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A recency LENS with transparent substance FILTERS: newest first by COLLECTION time
(un-spoofable, never the publisher's claimed date), gated by min-words AND
min-cited-sources thresholds the user sets AND sees, with near-identical wire reprints
collapsed. Each row shows its REAL word count + cited-source count + channel — counts,
NEVER a score. It reuses GET /api/insights/latest (facets included), hides until the
corpus has recent articles (Home is never blank-and-silent), and shows an honest
"loosen the gates" message when articles exist but none pass. Pure string-assertion
wiring guard (browser-unverified per fork-3).
"""

from __future__ import annotations

from pathlib import Path

from tests.test_repo_invariants import _ui_source

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = (_STATIC / "app.js").read_text(encoding="utf-8")
_UI = _ui_source()


def test_panel_exists_and_starts_hidden():
    import re

    m = re.search(r'<section[^>]*id="home-latest-panel"[^>]*>', _HTML)
    assert m, "the Latest panel must exist"
    assert "hidden" in m.group(0), "it starts hidden (Home is never blank-and-silent)"
    assert 'id="home-latest"' in _HTML


def test_user_settable_and_visible_gate_controls():
    # the substance gates the user sets AND sees, each re-running the fetch on change
    for cid in ("latest-minwords", "latest-minsources", "latest-channel",
                "latest-tag", "latest-collapse"):
        assert f'id="{cid}"' in _HTML, f"missing control {cid}"
    assert _HTML.count("onchange=\"loadHomeLatest()\"") >= 5, "each control re-runs the fetch"


def test_wired_into_loadHome_and_functions_defined():
    assert "loadHomeLatest();" in _JS
    assert "async function loadHomeLatest(" in _JS
    assert "function _fillLatestFacet(" in _JS


def test_reuses_the_latest_endpoint_with_facets():
    assert '"/api/insights/latest?"' in _JS
    assert 'p.set("content_type"' in _JS and 'p.set("tag"' in _JS
    assert 'facets: "1"' in _JS
    # facet <select>s populated from the endpoint's window-wide options
    assert "d.available_content_types" in _JS and "d.available_tags" in _JS


def test_rows_show_real_word_and_cited_source_counts_never_a_score():
    # REAL substance figures, counts only
    assert "a.word_count" in _JS
    assert "a.cited_sources" in _JS
    assert 't("words")' in _JS and 't("cited sources")' in _JS
    # the endpoint caveat ("counts only, never a score") is rendered visibly
    assert "d.caveat" in _JS
    # unsegmented-language flag respected (word_count meaningless there)
    assert "a.unsegmented" in _JS


def test_recency_by_collection_time_and_reader_link_invariant6():
    # honest: ordering is collection time (created_at), never the publisher's date
    assert "collection time (never the publisher's claimed date)" in _HTML
    assert "a.created_at" in _JS
    # every title opens the offline stored copy (invariant #6)
    assert '/api/articles/" + a.id + "/view' in _JS
    assert 't("offline stored copy")' in _JS


def test_failsafe_hides_when_no_recent_articles_but_honest_when_gates_too_tight():
    # no recent articles at all -> hide (Home never blank-and-silent)
    assert "if (!arts.length && !Object.keys(types).length && !tags.length)" in _JS
    assert "panel.hidden = true; return;" in _JS
    # articles exist but none pass -> honest message, controls stay reachable
    assert 't("No recent articles pass these gates yet — loosen the gates or collect more.")' in _JS
    # any error -> hide, never a broken div
    assert "catch (e) { panel.hidden = true; box.innerHTML = \"\"; }" in _JS


def test_strings_translated_x12():
    import json

    for loc in ("en", "fr", "de", "ar", "zh"):
        data = json.loads((_STATIC / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        for key in ("Latest in your corpus", "Min words", "cited sources",
                    "No recent articles pass these gates yet — loosen the gates or collect more."):
            assert key in data, f"{loc}.json missing {key!r}"
