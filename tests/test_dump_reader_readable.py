"""The dump reader offers a READABLE rendition, and never calls it a render.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The docket's remaining dump-reader work names "wikitext rendering". What this codebase
can honestly offer is ``plain_from_wikitext`` -- the corpus pipeline's own reducer,
whose docstring states its target as "keyword/WWW-quality text, not rendering fidelity".
It PEELS templates and DROPS refs, comments, tables and file links. So an infobox does
not become a table in this view: it disappears. A reader told "rendered" would conclude
the page never had one, which is the failure this whole session has been about -- a
surface claiming something it does not deliver.

So the readable view is named a STRIP, carries what it removed, keeps Raw one click
away as the complete thing, and true rendering stays open in the docket. These pin that
naming, the reuse (never a second stripper), and the one case the UI must not get wrong:
a page that reduces to nothing.
"""

from __future__ import annotations

from pathlib import Path

from src.wiki.corpus import plain_from_wikitext
from tests.js_source_helper import assert_absent, assert_present, function_source, read_static

_ROOT = Path(__file__).resolve().parents[1]
_MAP = read_static("app-map.js")
_RENDER = function_source(_MAP, "_renderDumpPage")

_SAMPLE = """{{Infobox country
| name = Examplia
| pop = 1000
}}
'''Examplia''' is a [[country|nation]] in the sea.<ref>Smith 2020</ref>

{| class="wikitable"
! Year !! Population
|-
| 2020 || 1000
|}

== History ==
It was founded in 1900.<!-- check this -->
[[File:Flag.svg|thumb|The flag]]
"""


# --- the strip itself, so the endpoint's claim is anchored to real behaviour ---- #


def test_the_strip_removes_exactly_what_the_caveat_says_it_removes():
    out = plain_from_wikitext(_SAMPLE)
    assert "Examplia" in out and "nation" in out, "link labels and prose are kept"
    assert "It was founded in 1900." in out
    assert "Infobox" not in out and "pop = 1000" not in out, "templates are peeled"
    assert "Smith 2020" not in out, "references are dropped"
    assert "check this" not in out, "comments are dropped"
    assert "wikitable" not in out, "tables are dropped"
    assert "Flag.svg" not in out, "file links are dropped"


def test_the_infobox_disappears_rather_than_becoming_a_table():
    """The exact reason the view may not be called a render.

    The population figure lived ONLY in the infobox. After the strip it is gone --
    not laid out differently, gone -- so a reader who believed this was a rendering
    would conclude the page never carried it.
    """
    out = plain_from_wikitext(_SAMPLE)
    assert "1000" not in out


# --- the endpoint reuses the reducer, and states the caveat on the payload ------ #


def test_the_endpoint_actually_returns_stripped_text(monkeypatch):
    """The assertion the source-level ones cannot make, found by a surviving mutant.

    Checking that the endpoint IMPORTS the reducer, and that the UI labels the pane
    honestly, both pass against ``res["plain"] = raw`` -- an endpoint that offers the
    raw wikitext under the word "Readable". Only calling it catches that, so it is
    called: ``find_page`` is stubbed with a canned page so no dump file is needed and
    the assertion is about the transform rather than about the reader.
    """
    from fastapi.testclient import TestClient

    import src.wiki.dumpread as dumpread
    from src.api.main import app

    monkeypatch.setattr(
        dumpread, "find_page",
        lambda wiki, title: {
            "found": True, "wiki": wiki, "title": title, "wikitext": _SAMPLE,
            "match": "exact", "index_lines_scanned": 1, "scan_seconds": 0.0,
        },
    )
    with TestClient(app) as c:
        d = c.get("/api/wiki/dumps/page?wiki=en&title=Examplia").json()

    assert d["wikitext"] == _SAMPLE, "the raw text is still returned in full"
    assert d["plain"] != d["wikitext"], "a 'readable' view identical to the raw text is a lie"
    assert "Examplia" in d["plain"] and "It was founded in 1900." in d["plain"]
    for dropped in ("Infobox", "Smith 2020", "wikitable", "Flag.svg", "check this"):
        assert dropped not in d["plain"], f"{dropped!r} must not survive the strip"
    assert "not a render" in d["plain_method"]


def test_a_page_with_no_wikitext_gets_no_readable_view(monkeypatch):
    """A miss carries no text, so it must not carry an empty ``plain`` either."""
    from fastapi.testclient import TestClient

    import src.wiki.dumpread as dumpread
    from src.api.main import app

    monkeypatch.setattr(
        dumpread, "find_page",
        lambda wiki, title: {"found": False, "reason": "title-not-in-index",
                             "index_lines_scanned": 12, "scan_seconds": 0.1},
    )
    with TestClient(app) as c:
        d = c.get("/api/wiki/dumps/page?wiki=en&title=Nope").json()
    assert d["found"] is False
    assert "plain" not in d and "plain_method" not in d, (
        "an absent page must not sprout an empty readable view"
    )


def test_the_endpoint_reuses_the_corpus_reducer_rather_than_stripping_again():
    api = (_ROOT / "src" / "api" / "wiki.py").read_text(encoding="utf-8")
    assert "from src.wiki.corpus import plain_from_wikitext" in api, (
        "a second stripper here would drift from the one the corpus pipeline uses"
    )
    assert 'res["plain_method"]' in api, (
        "the caveat travels on the payload, not only in whichever UI draws it"
    )
    assert "not a render" in api


# --- the UI names it a strip, and keeps Raw reachable -------------------------- #


def test_the_readable_view_is_never_labelled_a_render():
    assert_absent(
        _RENDER, "Rendered",
        why="the strip is not a render; naming it one is the claim this view refuses",
    )
    assert_present(_RENDER, 'Readable text')
    assert_present(_RENDER, 'Raw wikitext')


def test_the_caveat_says_a_template_s_output_is_absent_rather_than_rendered():
    assert_present(_RENDER, "absent rather than rendered")


def test_a_page_that_strips_to_nothing_falls_back_to_raw_instead_of_an_empty_pane():
    """An empty pane labelled "Readable text" reads as an empty PAGE.

    Pinned because it is the one case where offering the view is worse than not
    offering it, and it is invisible on any page with prose.
    """
    assert_present(_RENDER, "const canPlain = plain.length > 0")
    assert_present(_RENDER, 'const view = canPlain ? _dumpPageView : "raw"')
    assert_present(_RENDER, "Nothing readable survives the strip")


def test_the_toggle_does_not_re_scan_the_dump_index():
    """A scan is seconds of local I/O; re-paying it to change a VIEW is a tax on looking."""
    assert_present(_MAP, "let _dumpPage = null")
    read = function_source(_MAP, "dumpReadPage")
    assert_present(read, "_dumpPage = d;")
    toggle = function_source(_MAP, "dumpReadView")
    assert_absent(
        toggle, "api(",
        why="the toggle re-renders from the stashed payload; a fetch here would rescan",
    )
