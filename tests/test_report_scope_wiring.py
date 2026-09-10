"""Methods + signed Evidence reach the endpoint with the corpus they are looking at.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

`/api/reports/methods` and `/api/reports/evidence` have always accepted
``article_ids | query`` -- one ``_select_articles`` serves both, and
``tests/test_reporting_api.py`` already proves the id path end to end. The CLIENT sent
only ``{query: q}``, and the two #an buttons passed ``anQuery()``, which is empty for
an id-seeded corpus (``_anApplySeed`` sets ``an-adv-query`` to ``tb.query || ""`` and a
Lead/facet/card corpus has no query). So both buttons refused on exactly the corpora
the analysis window exists to hold, and refused with advice that was false there --
"Run a search first", to a reader already looking at a Lead's articles.

The behaviour lives in ``tests/report_scope_node_test.js``, executed rather than
grepped for the reason recorded the same day: a source assertion that ``article_ids``
is MENTIONED survives a resolver that reads the field and drops it. What is pinned
HERE is the wiring the node suite cannot see -- which argument each call site passes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.js_source_helper import assert_absent, assert_present, function_source, read_static

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_AI_TOOLS = read_static("app-ai-tools.js")


def test_the_resolver_behaviour_is_executed():
    proc = subprocess.run(
        ["node", str(Path(__file__).resolve().parent / "report_scope_node_test.js")],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout


def test_the_analysis_window_passes_the_corpus_not_just_its_query():
    """``anQuery()`` cannot carry an id set; ``anParams()`` is the one that can."""
    assert 'onclick="exportMethods(anParams())"' in _HTML
    assert 'onclick="exportEvidence(anParams())"' in _HTML
    assert 'onclick="exportMethods(anQuery())"' not in _HTML, (
        "anQuery() is empty for a Lead / facet / card corpus, which is precisely when "
        "a Methods appendix is worth exporting"
    )
    assert 'onclick="exportEvidence(anQuery())"' not in _HTML


def test_the_search_tab_call_shape_is_untouched():
    """The Search tab passes nothing and still reads its own input."""
    assert 'onclick="exportMethods()"' in _HTML
    assert 'onclick="exportEvidence()"' in _HTML


def test_neither_exporter_builds_its_own_body_any_more():
    """One resolver, so the two buttons cannot drift apart on what scopes a report."""
    for name in ("exportMethods", "exportEvidence"):
        src = function_source(_AI_TOOLS, name)
        assert_present(src, "_reportScope(scope)", why=f"{name} must resolve its scope once")
        assert_absent(
            src, 'JSON.stringify({query:',
            why=f"{name} hand-building a query-only body is the bug this replaced",
        )


def test_the_resolver_never_toasts_so_each_button_keeps_its_own_message():
    src = function_source(_AI_TOOLS, "_reportScope")
    assert_absent(
        src, "toast(",
        why="the two refusals say different things (an appendix records the query, a "
            "bundle is scoped by it) and that difference belongs to the callers",
    )


def test_an_id_set_never_travels_as_a_fabricated_case_name():
    src = function_source(_AI_TOOLS, "_reportScope")
    assert_present(src, "case_name: lab || null")
    assert_absent(
        src, "ids.join",
        why="a bundle named after its id list is a name no reader asked for; with no "
            "label the honest answer is no case name at all",
    )
