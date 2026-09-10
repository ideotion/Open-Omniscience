"""The #corpus-win superset claim, audited FACET BY FACET rather than by name.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS, and it is the whole point of the file. ``index.html``'s retirement
note says the retired ``#corpus-win`` modal's every subtab is "covered by the ONE #an
window (a strict superset)", and that claim is what licenses deleting the modal. The
guard that was supposed to enforce it --
``test_ui_corpus_win_retired.py::test_an_window_absorbs_every_modal_subtab`` -- asserts
only that the #an nav carries a ``data-tab`` with each modal facet's NAME. A name is not
a capability. That test was green the entire time three facets were strict SUBSETS:

  * SOURCES showed name/volume/tone/span and none of the catalogue facts the modal
    showed (found + partly fixed 2026-09-09; ``region`` and ``tags`` were named in the
    fix's own comment and still not shipped until the second pass).
  * LINKS showed a distinct-ARTICLE count under one blanket caveat, where the modal
    showed the distinct-SOURCE count beside it and said, per link, which of the two
    situations it was in. That is the difference between echo and corroboration.
  * KEYWORDS fetched each co-occurrence's shared-article count and PMI through
    ``keyword-stats`` and rendered neither, where the modal ranked a sortable table on
    exactly those numbers.

So this file pins the FACTS, not the tab names. Each test names the fact the modal
displayed and asserts the #an window displays it -- somewhere in the window, since the
claim is made about the window as a whole and a fact absorbed into a neighbouring facet
is still absorbed. Where the #an window is honestly NOT a superset, the gap is recorded
in ``docs/ledger/OPEN_QUEUE.md`` and named here rather than asserted away.

Source-level assertions, sliced with ``js_source_helper`` so no assertion runs over a
wider text than the function it names (the recorded vacuous-slice failure).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.js_source_helper import assert_present, function_source, read_static

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")

_ANALYSIS = read_static("app-analysis.js")
_CORPUS = read_static("app-corpus.js")
_BOOT = read_static("app-boot.js")

_LOAD_ANALYSIS = function_source(_ANALYSIS, "loadAnalysis")


def test_the_name_only_guard_is_not_mistaken_for_a_content_guard():
    """The sibling guard checks tab NAMES; this file exists because that is not enough.

    Pinned so the two are never confused again: if someone strengthens the sibling to
    compare content, this test should be revisited -- but a name check passing must
    never again be read as the superset claim being verified.
    """
    sibling = (Path(__file__).resolve().parent / "test_ui_corpus_win_retired.py").read_text(
        encoding="utf-8"
    )
    assert "data-tab=" in sibling, "the sibling guard is the NAME check this file supplements"
    # It must not be asserting content facts -- if it starts to, this file's premise moved.
    assert "citing_sources" not in sibling


# --- LINKS: the independence pair ---------------------------------------------- #
# The modal showed cited_by_articles AND citing_sources per link, plus a per-row note
# discriminating "one path" from "cited across distinct sources". #an showed the article
# count alone. Both counts, and the per-row verdict, must be rendered.


def test_links_renders_the_distinct_source_count_beside_the_article_count():
    assert_present(
        _LOAD_ANALYSIS, "it.citing_sources",
        why="the modal showed distinct CITING SOURCES beside distinct citing articles; "
            "without it the article count cannot be read as independence",
    )
    assert_present(_LOAD_ANALYSIS, "it.citations")


def test_links_states_independence_per_row_not_as_one_blanket_caveat():
    assert_present(
        _LOAD_ANALYSIS, 'it.independence === "distinct_sources"',
        why="five articles from one outlet and five from five outlets are different "
            "facts; one caveat covering the whole table cannot say which row is which",
    )


# --- SOURCES: the catalogue facts ---------------------------------------------- #
# The modal showed country / region / language / type / tags. All five ride on the
# corpus-sources row already, so any that is missing is a renderer omission.


def test_sources_renders_every_catalogue_fact_the_modal_showed():
    """Source-level only. The BEHAVIOUR lives in ``an_source_catalog_node_test.js``.

    Kept as the cheap first signal, and deliberately not trusted as more than that: the
    substring ``s.tags`` survives a renderer that reads the field and discards it, which
    is the mutant that survived this assertion in its first form. The executable test
    below is what actually holds the fields in place.
    """
    cell = function_source(_ANALYSIS, "_anSourceCatalogHtml")
    for field in ("s.country", "s.region", "s.language", "s.source_type", "s.tags"):
        assert_present(
            _LOAD_ANALYSIS + cell, field,
            why=f"the modal's Sources view showed {field.split('.')[1]!r}; it rides on the "
                "corpus_sources row already, so dropping it is a pure absorption loss",
        )


def test_the_catalogue_cell_is_executed_not_only_grepped():
    """The node suite is the real guard; this pins that it exists and runs the cell."""
    js = (Path(__file__).resolve().parent / "an_source_catalog_node_test.js").read_text(
        encoding="utf-8"
    )
    assert "_anSourceCatalogHtml" in js
    proc = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "an_source_catalog_node_test.js")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_sources_still_marks_the_catalogue_column_as_asserted_not_deduced():
    assert_present(
        _LOAD_ANALYSIS, "asserted, not deduced from text",
        why="two-class honesty: catalogue metadata is stated by the source, never "
            "deduced from the article text, and the column must keep saying so",
    )


# --- KEYWORDS: the measured association ---------------------------------------- #
# The modal ranked a table on cooccur / n_b / PMI. #an renders chips, whose #oo-tip
# hover fetches keyword-stats -- which returns each co-occurrence's cooccur AND pmi.
# Rendering the term alone threw both away.


def test_keyword_hover_renders_the_numbers_it_fetches():
    fmt = function_source(_BOOT, "fmt")
    assert_present(
        fmt, "c.cooccur",
        why="keyword-stats returns a shared-article count per co-occurrence and the "
            "hover fetched it and dropped it",
    )
    assert_present(
        fmt, "c.pmi",
        why="PMI is the only association STRENGTH anywhere in the #an window; it was "
            "fetched and discarded",
    )


def test_keyword_chips_still_carry_the_stats_hover_that_absorbs_the_modals_counts():
    chips = function_source(_CORPUS, "anRenderKwChips")
    assert_present(
        chips, "data-kwstat",
        why="total mentions + distinct-article spread reach the reader through the "
            "kwstat hover rather than the modal's header line; remove the marker and "
            "those counts are gone with it",
    )


# --- MINDMAP: the second view and the in-map controls -------------------------- #
# Mind-map rules (ruled 2026-06-11): the cloud is a SECOND view; the text-size slider
# and the enlarge control stay.


def test_mindmap_keeps_the_cloud_view_and_its_in_map_controls():
    mm = function_source(_ANALYSIS, "renderAnMindmap")
    for needle in ("cloud:true", "cloud:false", "Text size", "anMMset({big:"):
        assert_present(mm, needle, why="an in-map control the modal's mind-map kit had")


# --- COMPETITIVE: volume / tone / timing / emphasis ----------------------------- #


def test_competitive_keeps_all_four_columns_and_the_not_a_ranking_disclosure():
    comp = function_source(_ANALYSIS, "renderAnCompetitive")
    for needle in ("Volume", "Tone", "Timing", "Emphasis"):
        assert_present(comp, needle, why="a column the modal's Competitive view had")
    assert_present(comp, "never a ranking or a credibility judgement")
    assert_present(
        comp, "Only one source in this corpus",
        why="the modal's honest n=1 state -- nothing to compare",
    )


# --- ARTICLES: the in-context snippets ------------------------------------------ #
# The modal's Articles subtab listed /api/insights/context mention SNIPPETS. In #an the
# same endpoint feeds the concordance under Keywords -- absorbed into a neighbouring
# facet, which the window-level claim allows.


def test_the_context_concordance_survives_and_still_shows_snippets():
    ctx = function_source(_CORPUS, "anContextHtml")
    assert_present(ctx, "m.snippet", why="the modal's Articles view showed mention snippets")
    load = function_source(_CORPUS, "loadAnContext")
    assert_present(load, "/api/insights/context", why="the same endpoint the modal used")


# --- The window-level claim ------------------------------------------------------ #


def test_every_modal_facet_still_has_a_tab_in_the_an_window():
    """The name check, kept here too so this file stands alone as the absorption audit."""
    nav = re.search(r'id="an-subtabs".*?</nav>', _HTML, re.S)
    assert nav, "the #an subtab nav must exist"
    for sub in ("trend", "articles", "keywords", "mindmap", "links",
                "sentiment", "sources", "competitive"):
        assert f'data-tab="{sub}"' in nav.group(0)
