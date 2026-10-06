"""H3's gate: ``#ins-term`` + ``exploreTerm`` go only once the omnibar's analysis window has ABSORBED them.

Register ruling H3 (0.5 gate row I, assumption RC08.5 = a, brief S05-09) removes the Insights
"Keyword or entity" box and ``exploreTerm`` BEHIND the omnibar-absorption test -- the recorded
"never lose a tool" discipline (and the 2026-07-12 refusal of a blind hide). The older guard
``test_omnibar_analysis_window_absorbs_the_insights_bar_capabilities`` pins FOUR capabilities
(trend, associations, mindmap, context). This file measures the rest of ``exploreTerm``, on
2026-10-06, against the analysis window's own source, and the measurement says the test does NOT
pass yet:

  * the layered mind-map zoom (Keywords -> Families -> Super-groups, and its Period / text-size /
    enlarge controls) exists only in the shared ``#mm-kit`` that Insights' Explore view hosts; the
    analysis window's self-contained mind-map has Map / Cloud / Concept and no levels;
  * ``exploreTerm``'s "Resolved to <keyword> <kind> · N mentions in M articles" header (what the
    box turned "inflation" INTO, with the tier and the counts) has no counterpart in the analysis
    window;
  * five call sites send a clicked keyword to the Insights box through ``pickTerm`` (keyword stats,
    the mind-map's own nodes, the families list, the map tab, the trending lists), so removing the
    box without rerouting them would turn each into a dead link.

So the box STAYS, and this file makes that a measured state rather than a mood: it pins the gaps as
they are, and pins the box as present while any gap is open. Closing a gap (absorbing the capability
or rerouting the callers) fails the gap test until its entry is deleted, and only an EMPTY gap list
lets the box test accept a removal -- the order the ruling asked for, enforced.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "static"


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _gaps() -> list[str]:
    """Every capability of ``exploreTerm`` the analysis window does not yet carry, measured."""
    analysis = _read("app-analysis.js")
    gaps = []
    if "mmLevel(" not in analysis and "data-level=" not in analysis:
        gaps.append("layered mind-map zoom (keywords, families, super-groups) is only in #mm-kit")
    if "Resolved to" not in analysis:
        gaps.append("the resolved-term header (keyword, tier, mentions in articles) is absent")
    sites = 0
    for f in sorted(STATIC.glob("app-*.js")):
        text = _read(f.name)
        sites += len(re.findall(r"(?<![\w.])pickTerm\(", text)) - len(re.findall(r"function pickTerm\(", text))
    if sites:
        gaps.append(f"{sites} call sites still send a clicked keyword to the Insights box through pickTerm")
    return gaps


# The gaps as measured on 2026-10-06. Delete an entry in the same change that closes it.
EXPECTED_GAPS = [
    "layered mind-map zoom (keywords, families, super-groups) is only in #mm-kit",
    "the resolved-term header (keyword, tier, mentions in articles) is absent",
    "5 call sites still send a clicked keyword to the Insights box through pickTerm",
]


def test_the_four_capabilities_the_older_guard_pins_are_still_absorbed():
    """The part that DOES hold, read from the analysis window's own functions, not the union of all modules."""
    from tests.js_source_helper import function_source

    analysis = _read("app-analysis.js")
    corpus = _read("app-corpus.js")
    trend = function_source(analysis, "renderAnTrend")
    assert "/api/insights/trend" in trend and "/api/insights/associations" in trend
    # the context concordance loader lives in app-corpus.js, as the older guard reads it
    ctx = function_source(corpus, "loadAnContext")
    assert "/api/insights/context" in ctx and "anQuery()" in ctx
    assert "/api/framing?query=" in analysis, "outlet framing is the Competitive tab's, keyed on the query"
    assert "anMMset({cloud:true" in analysis, "the cloud is the mind-map's second view in the analysis window too"


def test_the_gaps_between_exploreterm_and_the_analysis_window_are_exactly_the_recorded_ones():
    assert _gaps() == EXPECTED_GAPS, (
        "the absorption state moved: if a gap CLOSED, delete its entry from EXPECTED_GAPS (and "
        "the gate row's text says so); if a new one OPENED, exploreTerm gained a capability the "
        "analysis window does not carry"
    )


def test_the_insights_box_is_not_removed_while_any_gap_is_open():
    """The removal H3 asks for is conditional on the absorption test; it is not passing."""
    html = _read("index.html")
    corpus = _read("app-corpus.js")
    removed = 'id="ins-term"' not in html and "async function exploreTerm(" not in corpus
    if removed:
        assert not _gaps(), (
            "#ins-term / exploreTerm are gone while the analysis window still lacks: " + "; ".join(_gaps())
        )
    else:
        assert 'id="ins-term"' in html and "async function exploreTerm(" in corpus
