"""The analysis window's 2026-09-27 delegated re-walk fixes (batch B24, round 2).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

N-3 (P1) the Trend's Counts mode, and the price x coverage panel beside it, called
MENTION counts "articles" -- about three times the real article count on screen.
U-6 the price x coverage svg drew its tick labels over the first bar in Arabic, and
its aria-label was an English frame. N-2 the Links / Sentiment / Sources caveats were
English server prose in every locale. N-4 a live language switch left those panels,
the Articles list, an open Trend chart and the per-form counts in the old language.
N-5 labels and lists welded an English ": " or ", ". N-6 the ⛶ hover said "Enlarge"
over an enlarged map. N-7 the concept map's labels were 5-7 px at 375 px.

The behaviour is driven in ``rewalk_b24_node_test.js`` against the real renderers and
the real locale files, ONE GROUP PER DEFECT so each fails on its own; this file runs
those groups and holds the facts a node sandbox cannot see (the server's own caveat
sentences, the locale files, the one ``oo:langchange`` listener).
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from tests.js_source_helper import (
    event_listener_bodies,
    function_body,
    read_static,
    strip_comments,
)

_ROOT = Path(__file__).resolve().parents[1]
_LOCALES = _ROOT / "src" / "static" / "locales"
_NODE = Path(__file__).resolve().parent / "rewalk_b24_node_test.js"


def _locales() -> dict[str, dict]:
    out = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in _LOCALES.glob("*.json")}
    assert len(out) == 12, f"expected 12 locale files, found {len(out)}"
    return out


def _served_caveat(rel: str, func: str) -> str:
    """The caveat a server function puts in its payload, read out of its SOURCE.

    Read rather than re-typed, so a reworded server sentence fails here with the new
    wording in the message instead of leaving a stale key that nothing sends.
    """
    tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func:
            for d in ast.walk(node):
                if isinstance(d, ast.Dict):
                    for k, v in zip(d.keys, d.values, strict=True):
                        if (isinstance(k, ast.Constant) and k.value == "caveat"
                                and isinstance(v, ast.Constant) and isinstance(v.value, str)):
                            return v.value
    raise AssertionError(f"no literal caveat in {rel}:{func} -- was it moved?")


def _module_constant(rel: str, name: str) -> str:
    """A module-level string constant, read out of its SOURCE rather than imported:
    ``src/awareness/framing.py`` builds VADER and the keyword extractor at import time."""
    tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
    for node in tree.body:
        if (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            return node.value.value
    raise AssertionError(f"no string constant {name} in {rel} -- was it moved?")


def _caveats() -> dict[str, str]:
    from src.analytics.queries import _COORD_CAVEAT, _COORD_METHOD, _SENTIMENT_CAVEAT

    return {
        "sentiment": _SENTIMENT_CAVEAT,
        "sources": _served_caveat("src/analytics/queries.py", "corpus_sources"),
        "links": _served_caveat("src/api/link_analysis.py", "corpus_links"),
        # Drawn by the same window the same way, found on the way: When / Where / Who,
        # and the Related tab's near-duplicate clusters (its method line and caveat).
        "www": _served_caveat("src/api/insights.py", "insights_corpus_www"),
        "coordination": _COORD_CAVEAT,
        "coordination method": _COORD_METHOD,
        # The Competitive tab draws /api/framing's own sentence beside the sources one; it
        # had no key in any locale, so it read English in all twelve (the round-2 review).
        "framing": _module_constant("src/awareness/framing.py", "_CAVEAT"),
    }


@pytest.mark.parametrize("group", ["n3", "u6", "n2", "n4", "n5", "n6", "n7"])
def test_the_node_group_passes(group: str) -> None:
    env = dict(os.environ, B24_CAVEATS=json.dumps(_caveats()))
    proc = subprocess.run(["node", str(_NODE), group], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"ok {group}" in proc.stdout


# --- N-2: the caveats are keyed where they are sent ----------------------------------- #


def test_every_caveat_the_analysis_window_draws_is_keyed_in_all_twelve_locales() -> None:
    """A caveat that has no key reads English in every locale, and "every caveat ships
    x12" is the informed-consent non-negotiable, not a style rule."""
    loc = _locales()
    for name, sentence in _caveats().items():
        for code, table in loc.items():
            assert sentence in table, f"{code}.json has no entry for the {name} caveat"
            if code != "en":
                assert table[sentence] != sentence, (
                    f"{code}.json 'translates' the {name} caveat as the English sentence")


#: ``esc(d.caveat)``, ``esc(d.caveat || "")``, ``esc((x && x.caveat) || "")``: a server
#: sentence drawn with no ``t()``, the exact shape of N-2.
_VERBATIM = re.compile(
    r'esc\(\s*(?:\(\s*\w+\s*&&\s*\w+\.caveat\s*\)|\w+\.caveat)\s*(?:\|\|\s*""\s*)?\)')


def test_the_panels_draw_their_caveats_through_t() -> None:
    js = read_static("app-analysis.js")
    # The renderers a language switch also calls (N-4): When/Where/Who and Competitive
    # moved out of loadAnalysis / renderAnCompetitive into their own.
    for fn in ("_anLinksHtml", "_anSentimentHtml", "_anSourcesHtml", "_anWwwHtml",
               "_anCompetitiveHtml"):
        body = strip_comments(function_body(js, fn))
        assert not _VERBATIM.findall(body), f"{fn} draws a server caveat without t()"
        assert "t(d.caveat)" in body or "t(cs.caveat)" in body, fn
    for fn in ("loadAnalysis", "renderAnCompetitive", "renderAnRelated"):
        assert not _VERBATIM.findall(strip_comments(function_body(js, fn))), (
            f"{fn} draws a server caveat without t()")
    # ...and beside the sources caveat, /api/framing's own sentence.
    assert "t(fr.caveat)" in strip_comments(function_body(js, "_anCompetitiveHtml"))
    # The Related tab draws the SAME /api/links/corpus sentence the Links tab does, and
    # the near-duplicate clusters' own method line and caveat.
    related = strip_comments(function_body(js, "_anRelatedHtml"))
    assert not _VERBATIM.findall(related), "the Related tab draws a server caveat without t()"
    for call in ("t(ld.caveat)", "t(cd.caveat)", "t(cd.method)"):
        assert call in related, f"the Related tab no longer draws {call}"


def test_the_verbatim_shape_is_what_the_pattern_catches() -> None:
    """The guard above is only as good as its pattern; pinned both ways."""
    for bad in ('esc(d.caveat)', 'esc(d.caveat || "")', 'esc((cd && cd.caveat) || "")'):
        assert _VERBATIM.search(bad), bad
    for good in ('esc(d.caveat ? t(d.caveat) : "")',
                 'esc((ld && ld.caveat) ? t(ld.caveat) : t("x"))'):
        assert not _VERBATIM.search(good), good


# --- N-3: the unit is mentions ------------------------------------------------------- #


def test_the_trend_counts_are_labelled_as_what_the_endpoint_sums() -> None:
    """The node group drives the renderer; this pins the PREMISE it rests on, in the
    server source: every point's ``count`` is a SUM of the mention count."""
    src = (_ROOT / "src" / "analytics" / "queries.py").read_text(encoding="utf-8")
    assert "func.sum(KeywordMentionRead.count)" in src, (
        "the trend no longer sums mention counts -- the Counts label must follow it")
    js = read_static("app-analysis.js")
    body = strip_comments(function_body(js, "renderAnTrend"))
    assert 'unit: t("articles")' not in body
    assert body.count('unitKey: "mentions"') == 2, "both the term and its relatives are mentions"
    # Kept as the KEY and translated where it is drawn: a t() at fetch time froze the unit
    # in the fetch language, under a caption that followed a live switch (N-4, round 2).
    assert "unit: t(" not in body, "the trend's unit is translated when it is fetched"
    assert "t(s.unitKey)" in strip_comments(function_body(js, "drawAnTrend"))


def test_the_new_keys_are_keyed_in_all_twelve_locales() -> None:
    loc = _locales()
    keys = [
        "Mention counts on a shared time axis.",
        "Price × coverage: {prices} price points, {coverage} coverage points",
        "Shrink the mindmap",
        "{list}, {item}",
        "{term} ({count}, Association {pmi})",
        "{term} ({count})",
    ]
    for key in keys:
        want = sorted(re.findall(r"\{(\w+)\}", key))
        for code, table in loc.items():
            assert key in table, f"{code}.json has no entry for {key!r}"
            assert sorted(re.findall(r"\{(\w+)\}", table[key])) == want, (
                f"{code}.json changes the placeholders of {key!r}: {table[key]!r}")
    assert loc["zh"]["{list}, {item}"] == "{list}、{item}"
    assert loc["ja"]["{list}, {item}"] == "{list}、{item}"
    assert loc["ar"]["{list}, {item}"] == "{list}، {item}"


# --- N-5: the locale's own separators ------------------------------------------------ #

#: Both forms a welded colon takes: ``${t("X")}:`` and ``t("X") + ": "``.
_WELDED = (re.compile(r't\("([^"]+)"\)\)?\}:[\s<]'),
           re.compile(r't\("([^"]+)"\)\)?\s*\+\s*["\'`]\s*:'))


@pytest.mark.parametrize("name", ["app-analysis.js", "app-shell.js", "app-boot.js"])
def test_no_label_welds_its_own_colon(name: str) -> None:
    """'Afficher:', 'Analyse: “climat”', 'avec: assembly' in French; '视图:' in Chinese."""
    src = strip_comments(read_static(name))
    found = [m.group(1) for rx in _WELDED for m in rx.finditer(src)]
    assert not found, f"{name}: a label welds an English colon: {found}"


def test_the_keyword_hover_joins_its_items_with_the_readers_punctuation() -> None:
    boot = strip_comments(read_static("app-boot.js"))
    assert 'ooLabelText(t("with"), ooListJoin(co))' in boot
    assert 'ooLabelText(t("trend"), fb)' in boot
    assert 'co.join(", ")' not in boot, "the co-occurrence list is joined with a Latin comma again"
    assert 'tf("{term} ({count}, Association {pmi})"' in boot


# --- N-4: the one listener, and no fetch -------------------------------------------- #


def test_a_language_switch_repaints_the_analysis_window_without_a_request() -> None:
    boot = read_static("app-boot.js")
    bodies = event_listener_bodies(boot, "oo:langchange")
    assert any("_anRepaintOnLangChange()" in b for b in bodies), (
        f"{len(bodies)} oo:langchange listener(s), none repaints the analysis panels")
    js = read_static("app-analysis.js")
    drawers = ("_anWwwHtml", "_anLinksHtml", "_anSentimentHtml", "_anSourcesHtml",
               "_anRelatedHtml", "_anCompetitiveHtml", "_anOverviewHtml")
    for fn in ("_anRepaintOnLangChange", "_anRepaintArticles", "_anDrawArticles",
               "_anRefillFormSlots", "_anApplyDupBadges", "anRelUpdateSel", *drawers):
        assert "api(" not in strip_comments(function_body(js, fn)), (
            f"{fn} runs on a language switch and must never fetch")
    # Every panel the window composes at render time is in the repaint (round 2 added
    # When/Where/Who, Related, Competitive and the Overview tiles).
    repaint = strip_comments(function_body(js, "_anRepaintOnLangChange"))
    for fn in drawers:
        assert fn in repaint, f"a language switch does not redraw {fn}"
    load = strip_comments(function_body(js, "loadAnalysis"))
    assert "_anPanelsLast = {};" in load and "_anFormCountsLast = {};" in load, (
        "a new run must drop the previous corpus's payloads, or a switch paints them back")
