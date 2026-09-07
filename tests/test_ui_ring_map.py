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
from tests.js_source_helper import app_js

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = app_js()


def test_ring_map_hosts_exist():
    # GROUPS amendment §D: the flat 540-item <select> was replaced by the two-tier
    # circled browse (super-group chips -> group chips) -- see test_repo_invariants
    # ::test_concept_map_two_tier_browse_and_clickable_countries for the full pin.
    assert 'id="sg-ringmap-pick"' not in _HTML
    for el_id in ("sg-concept-supers", "sg-concept-groups"):
        assert f'id="{el_id}"' in _HTML
    assert 'id="sg-ringmap"' in _HTML and 'id="sg-ringmap-detail"' in _HTML
    assert "showRingMap(ringId)" in _JS  # selectConceptGroup drives it now


def test_showringmap_uses_ring_countries_and_ooMap():
    assert "function showRingMap(" in _JS
    assert "/api/insights/ring-countries?ring_id=" in _JS
    assert "await ooMap(host, {" in _JS  # renders on the shared ooMap component


def test_unlocated_sources_are_never_mapped_but_disclosed():
    # a country-less row goes to the unlocated bucket, not into the choropleth values
    assert "if (!c.country) { unloc = c; return; }" in _JS
    assert 't("Not mapped (source country unknown)")' in _JS
    # §D: the unlocated note is now a CLICKABLE drill (often the largest bucket,
    # never a dead end), not a static caveat div.
    assert "onclick=\"_conceptDrillCountry('${esc(ringId)}', null)\"" in _JS


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


# --------------------------------------------------------------------------- #
# Anti-capping on the concept map (2026-07-18: "a cap may bound which EXAMPLES
# are listed; it may never bound a reported NUMBER"). The polygons are a bounded
# LIST, so the figure announced beside the map must come from the payload's exact
# n_countries, and a short list must say so where a reader can see it.
#
# Every assertion below reads COMMENT-STRIPPED source, because the fix's own
# comments quote the rule they explain. MEASURED, so the claim matches the code:
# stripping changes NO verdict today -- the needles carry enough context
# ("d.n_countries", not a bare "n_countries") that the comment cannot satisfy
# them. It is defence-in-depth against the NEXT comment, not what makes these
# guards discriminate; the mutation that deletes the read while leaving the
# comment in place is what proves they do.
# --------------------------------------------------------------------------- #


def _show_ring_map_body() -> str:
    from tests.js_source_helper import function_body, strip_comments
    return strip_comments(function_body(_JS, "showRingMap"))


def test_the_announced_country_figure_is_the_exact_total_not_the_drawn_count():
    body = _show_ring_map_body()
    assert "d.n_countries" in body, (
        "showRingMap must read the payload's exact located-country total; the number "
        "of polygons it drew is the cap whenever the list is truncated"
    )
    # The aria label is composed from that figure, never from the polygon count --
    # otherwise a screen reader is the one reader still handed the cap.
    assert "const ariaLabel = countLine ?" in body and "aria: ariaLabel," in body
    # And there is no fallback to the drawn count: defaulting to it when the exact
    # total is absent would reinstate the very cap this guard exists to forbid.
    assert "? d.n_countries : null" in body, (
        "an absent exact total must yield NO number, never the polygon count"
    )
    assert "Object.keys(values).length}" not in body, (
        "the announced figure must not be interpolated from the drawn-polygon count"
    )


def test_a_truncated_country_list_discloses_the_ratio_visibly():
    body = _show_ring_map_body()
    assert 'tf("Countries listed: {shown} of {total}"' in body, (
        "the ratio travels as a keyed TEMPLATE with the counts as data, so the frame "
        "translates and the numbers do not"
    )
    # Visible by default, not aria-only: the note is written into the detail block.
    assert "truncNote" in body and "detail.innerHTML = langs + langBd + truncNote" in body
    # ...and ONLY when the list really is short of the total -- a note that always
    # rendered would claim a truncation the data does not exhibit.
    assert "(d.truncated && tf)" in body


def test_the_truncation_template_is_translated_in_every_locale():
    import json
    key = "Countries listed: {shown} of {total}"
    locales = _STATIC / "locales"
    en = json.loads((locales / "en.json").read_text(encoding="utf-8"))
    assert key in en
    for loc in ("fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id"):
        d = json.loads((locales / f"{loc}.json").read_text(encoding="utf-8"))
        val = d.get(key)
        assert val, f"{loc}: missing translation for the country-truncation ratio"
        # Both holes must survive translation, in any order -- a frame that lost one
        # renders a literal "{shown}" to the reader.
        assert "{shown}" in val and "{total}" in val, f"{loc}: template hole dropped"
