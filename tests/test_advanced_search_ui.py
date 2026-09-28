"""The advanced search's UI half (S05-01): the builder, the time component, the views,
the first-launch history opt-in.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The behaviour (chips two-way with the box, the permalink round-trip, the saved-search
stored form, the timescale snapping) is DRIVEN in node by ``advanced_search_node_test.js``;
this file pins the wiring a node run cannot see, mostly as negative space: no inline
handler in anything added, no second filter definition, no suggestion that runs itself.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.js_source_helper import app_js, function_source, page_source, read_static

_ROOT = Path(__file__).resolve().parents[1]
_HTML = read_static("index.html")
_APP = app_js()


def _block(html: str, start_marker: str, end_marker: str) -> str:
    return html.split(start_marker, 1)[1].split(end_marker, 1)[0]


_ADVANCED = _block(_HTML, 'id="an-advanced"', '<div class="an-export"')
# The page and its own script (unlock.js since 0.5 row I, Q1127 = a).
_UNLOCK = page_source("unlock.html")
_HISTORY_VIEW = _block(_UNLOCK, 'id="view-history"', "</div>\n\n")


def test_node_suite() -> None:
    proc = subprocess.run(["node", str(_ROOT / "tests" / "advanced_search_node_test.js")],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout


def test_the_builder_adds_no_inline_handler() -> None:
    """S05-09's ratchet: nothing new is wired through an on*= attribute."""
    assert not re.search(r"\son[a-z]+=", _ADVANCED), "the Advanced subtab must carry no inline handler"
    assert not re.search(r"\son[a-z]+=", _HISTORY_VIEW), "the first-launch history view must carry none"
    builder = read_static("app-analysis.js").split("THE ADVANCED SEARCH BUILDER (S05-01", 1)[1]
    assert not re.search(r"""\son(?:click|change|input|keydown)=""", builder), (
        "HTML drawn by the builder must be answered by delegated listeners, not inline handlers"
    )


def test_every_ruled_filter_is_a_control() -> None:
    """Q601: every field of the confirmed list is reachable from the builder."""
    for cid in ("an-adv-query", "adv-chips", "an-adv-exact", "adv-near-default", "an-adv-lang",
                "adv-lang-basis", "adv-sources", "adv-countries", "adv-regions", "adv-published",
                "adv-collected", "adv-words-min", "adv-words-max", "adv-mentions-from",
                "adv-mentions-to", "adv-quarantined", "adv-save", "adv-link", "adv-hist-on",
                "adv-hist-clear"):
        assert f'id="{cid}"' in _ADVANCED, cid
    for s in ("positive", "neutral", "negative"):
        assert f'class="adv-sent" value="{s}"' in _ADVANCED
    for op in ("AND", "OR", "NOT"):
        assert f'data-op="{op}"' in _ADVANCED, "the localised buttons compile to canonical tokens (Q604)"
    # The five bare controls this replaced (brief §2) are gone, not hidden.
    for old in ("an-adv-source", "an-adv-from", "an-adv-to"):
        assert f'id="{old}"' not in _HTML, old


def test_the_caveats_are_visible_and_filled_from_the_server() -> None:
    """Informed consent: each caveat sits beside its filter, not behind a toggle, and its
    text is the server's one sentence (FILTER_CAVEATS) through t()."""
    for k in ("words", "sentiment", "mentions", "quarantine"):
        assert f'id="adv-cav-{k}"' in _ADVANCED
    fill = function_source(_APP, "_advFillFacets")
    assert 'd.caveats' in fill and "t(cav[k])" in fill
    assert "<details" not in _ADVANCED.split('<details id="adv-hist"', 1)[0], (
        "no filter or caveat is folded away; only the history list is a disclosure"
    )


def test_one_filter_definition_feeds_view_and_export() -> None:
    """Q607: the export reproduces the view because both are built from anParams, which
    reads the active tab's ONE filter dict."""
    params = function_source(_APP, "anParams")
    assert "_advToParams(_advActive(), p)" in params
    assert "exportResults('csv', anParams())" in _HTML and "exportResults('json', anParams())" in _HTML


def test_did_you_mean_is_offered_never_run() -> None:
    """Q605 = b: rendering the block issues nothing; only the reader's press runs it."""
    dym = function_source(_APP, "_advDymHtml")
    assert "data-adv-dym=" in dym
    assert "api(" not in dym and "doSearch" not in dym and "openAnalysisFor" not in dym
    assert "d.caveat" in dym, "the table's freshness caveat is shown beside the suggestion"


def test_the_order_is_stated_on_both_lists() -> None:
    """Q618: relevance by default, and the order said on every results header."""
    assert "_anOrderingHtml(d.ordering)" in function_source(_APP, "_anDrawArticles")
    assert "_anOrderingHtml(data.ordering)" in function_source(_APP, "doSearch")


def test_the_table_view_sorts_on_every_ruled_column() -> None:
    """Q615: date, source, language, words, sentiment -- each a header sort."""
    draw = function_source(_APP, "_anDrawArticles")
    for field in ("date", "source", "language", "words", "sentiment"):
        assert f'_anTh("{field}"' in draw, field
    assert '_anArtView === "list"' in draw, "the list (cards) view exists beside the table"


def test_quarantine_reason_travels_on_the_row() -> None:
    """Q617: include-quarantined is advanced-only, and each such row says why."""
    assert "_anQuarantineNote(a)" in function_source(_APP, "_anDrawArticles")
    assert 'id="adv-quarantined"' in _ADVANCED
    search_tab = _block(_HTML, 'id="tab-search"', 'id="tab-analyze"')
    assert "quarantin" not in search_tab.lower(), "Q617: the control lives in Advanced only"


def test_one_time_component_with_a_timescale_three_consumers() -> None:
    """Q609: ooTimeScope gains the scale and stays the one component (Markets, Insights,
    Advanced), and its data window is never thinned (invariant #16)."""
    ts = function_source(_APP, "ooTimeScope")
    assert 'class="ts-scale"' in ts
    assert "opts.onChange({from: _tsIso(from), to: _tsIso(to), scale})" in ts
    assert "get: () => ({from: _tsIso(from), to: _tsIso(to), scale})" in ts
    assert "_mktTimeScope = ooTimeScope(" in _APP and "_idxTimeScope = ooTimeScope(" in _APP
    assert "ooTimeScope(box, {" in function_source(_APP, "_buildTrendScope")
    assert 'mk("adv-published", spans.published)' in _APP and 'mk("adv-collected", spans.collected)' in _APP


def test_history_opt_in_follows_the_legal_step_and_is_off_by_default() -> None:
    """Q614's note: offered after the legal screen; off unless chosen; the caveat visible."""
    assert 'id="hs-off" checked' in _HISTORY_VIEW
    assert "Stored only on this machine" in _HISTORY_VIEW
    step = function_source(_UNLOCK, "historyToDataLocation")
    assert "oo.search.history.firstrun" in step and "legalToDataLocation();" in step
    assert "fetch(" not in step, "the page writes nothing but a browser key; the app applies it"
    apply = function_source(_APP, "_advApplyFirstRunHistoryChoice")
    assert '"search_history_enabled: true"' not in apply and "search_history_enabled: true" in apply
    assert 'removeItem(ADV_HIST_FIRSTRUN_KEY)' in apply


def test_history_is_recorded_only_when_on() -> None:
    rec = function_source(_APP, "_advHistRecord")
    assert "!_advHist.enabled" in rec
