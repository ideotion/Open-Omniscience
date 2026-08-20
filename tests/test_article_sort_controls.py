"""The sort control lives with the list it orders, and there is only one of it.

Rulings 20-22 (field feedback 2026-08-07).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The BEHAVIOUR -- what a second click on the same header does, which column claims the
arrow, whether the two sorts can disagree -- is proven in
``tests/article_sort_node_test.js``, which extracts the real functions from ``app.js``.
Only the facts a node suite cannot see are checked here: where the markup sits, that it
was MOVED rather than copied, and that the request reads the live control instead of the
params snapshot taken when the corpus loaded.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.js_source_helper import function_body, read_static, strip_comments

_ROOT = Path(__file__).resolve().parents[1]


def test_there_is_exactly_one_sort_control_in_the_window() -> None:
    """Ruling 20 says MOVE, never duplicate. Two sort controls in one window is the
    defect this was meant to remove, not relocate -- and a duplicate would look correct
    in a screenshot of either subtab."""
    html = read_static("index.html")
    assert html.count('id="an-adv-sort"') == 1
    assert html.count('id="an-adv-dir"') == 1


def test_the_sort_control_sits_in_the_articles_panel() -> None:
    html = read_static("index.html")
    articles = html.index('id="an-articles"')
    advanced = html.index('id="an-advanced"')
    sort_at = html.index('id="an-adv-sort"')
    assert articles < sort_at < advanced, (
        "the sort control must be inside the Articles panel, with the list it orders"
    )


def test_the_list_renders_below_the_sort_bar_not_over_it() -> None:
    """The bar is static markup and the list re-renders on every sort change -- if the
    renderer targeted the panel it would erase the control that triggered it, and the
    second click would have nothing to click."""
    html = read_static("index.html")
    assert 'id="an-art-list"' in html, "the list needs its own host inside the panel"
    body = function_body(read_static("app.js"), "_anLoadArticles")
    assert '$("an-art-list")' in body, "the renderer must target the list host"


def test_the_request_reads_the_live_control_not_the_captured_params() -> None:
    """`_anArtParams` is snapshotted when the corpus loads. Reading sort from it would
    order by whatever was chosen THEN and silently ignore the header just clicked --
    a control that looks live and is not."""
    body = strip_comments(function_body(read_static("app.js"), "_anLoadArticles"))
    assert '$("an-adv-sort")' in body, "the sort must be read from the control at request time"
    assert 'q.delete("sort_by")' in body, (
        "clearing the control must clear the parameter, or a stale sort survives a reset"
    )


def test_the_sort_fields_offered_match_what_the_backend_accepts() -> None:
    """A <select> that offers an ordering the endpoint rejects is a 400 waiting for a
    click. Read the real field set rather than restating it."""
    import re

    from src.api.main import _KEYWORD_COUNT_SORT, _SORT_FIELDS

    html = read_static("index.html")
    block = html.split('id="an-adv-sort"', 1)[1].split("</select>", 1)[0]
    offered = {v for v in re.findall(r'<option value="([^"]*)"', block) if v}
    assert offered <= (_SORT_FIELDS | {_KEYWORD_COUNT_SORT}), (
        f"the picker offers orderings the endpoint refuses: {offered - _SORT_FIELDS}"
    )
    assert "top_keyword" in offered, "the article's own top keyword must be offerable"


def test_article_sort_node_suite() -> None:
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "article_sort_node_test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "passed" in proc.stdout
