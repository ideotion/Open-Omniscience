"""Retire the #corpus-win keyword modal — absorption-gated (wave 4 I, task 5).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The app converged on ONE in-SPA analysis window (#an). The legacy #corpus-win keyword
modal is DEAD: openCorpus() routes to openAnalysisFor() (which spawns an #an tab), and
NOTHING opens the dialog (no live .showModal()/.show()). This is the ABSORPTION gate
(the Desk lesson — nothing is lost): the #an window is a strict SUPERSET of every subtab
the modal had, so retiring the modal removes no capability. Row 357 then DELETED the
unreachable markup, its corpus-subtabs nav and the corpusTab/renderCorpus* JS; the
negative checks below keep every piece of it from coming back. Pure string-assertion
guard; the facet-by-facet content audit is tests/test_corpus_win_absorption_content.py.
"""

from __future__ import annotations

from pathlib import Path

from tests.js_source_helper import app_js, assert_absent
from tests.test_repo_invariants import _ui_source

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")
_JS = app_js()
_UI = _ui_source()

# The subtabs the retired #corpus-win modal exposed — every one must survive in #an.
_MODAL_SUBTABS = (
    "trend", "articles", "keywords", "mindmap", "links", "sentiment", "sources", "competitive",
)


def test_open_corpus_routes_to_the_an_window():
    assert "function openCorpus(term) { openAnalysisFor(term); }" in _JS


def test_modal_is_never_opened():
    # no live opener of the dialog anywhere in the UI source
    assert "corpus-win').showModal" not in _UI
    assert 'corpus-win").showModal' not in _UI
    assert "corpus-win').show(" not in _UI
    assert 'corpus-win").show(' not in _UI


def test_modal_is_marked_dead():
    assert "RETIRED (wave 4 I" in _HTML, "the #corpus-win dialog must carry the retirement marker"


def test_the_deleted_modal_and_its_code_stay_deleted():
    """Row 357: the dead markup and the JS reachable only through it are gone."""
    for markup in ('id="corpus-win"', 'id="corpus-subtabs"', 'id="corpus-body"'):
        assert markup not in _HTML, f"the deleted #corpus-win markup came back: {markup}"
    for decl in (
        "function corpusTab(",
        "function renderCorpusSources(",
        "function renderCorpusKeywords(",
        "function renderCorpusCompetitive(",
        "function _mmKitHome(",
        "_corpusSubtabs",
        "_corpusTerm",
    ):
        assert_absent(_JS, decl, why="row 357 deleted the retired modal's code")


def test_an_window_absorbs_every_modal_subtab():
    # locate the #an subtab nav and assert every modal facet exists as an #an data-tab
    import re

    nav = re.search(r'id="an-subtabs".*?</nav>', _HTML, re.S)
    assert nav, "the #an subtab nav must exist"
    an_nav = nav.group(0)
    for sub in _MODAL_SUBTABS:
        assert f'data-tab="{sub}"' in an_nav, f"#an is missing the {sub!r} subtab the modal had"
