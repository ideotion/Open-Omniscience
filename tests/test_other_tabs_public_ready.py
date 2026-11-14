"""The other tabs, made ready for ordinary people (Lane O, 2026-11-13).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each pin below is a defect measured in a Chromium walk of Markets, Indices,
Insights, the Observatory and the Agenda at 1440, 390 and 320 px, and fixed in the
same change. The falling-rate arrow and the wrapped sky labels are pinned as
running code in growth_sentinel_node_test.js and oosky_node_test.js; these are the
layout and wording pins that only a source read can hold.
"""

from __future__ import annotations

import re

from tests.js_source_helper import read_static


def _css() -> str:
    return read_static("app.css")


def test_card_grids_never_ask_for_more_than_the_screen() -> None:
    """A grid column floor wider than a phone overflowed the card at 320 px."""
    html = read_static("index.html")
    assert "minmax(min(300px,100%),1fr)" in html, "the Commodities board grid"
    css = _css()
    assert "minmax(min(280px,100%),1fr)" in css, "the Indices board grid"
    assert "minmax(min(220px,100%),1fr)" in css, "the Agenda month grid"


def test_small_controls_are_at_least_a_24px_target() -> None:
    """WCAG 2.5.8: these measured 15 to 21 px tall before."""
    css = _css()
    for selector in (".fam-mbtn", ".fam-enlarge", ".fig-leg", ".sky-tbl td button.ghost",
                     ".mkt-tagrow .chip"):
        # The rule body up to its closing brace at line end (a comment inside a rule
        # may quote a template literal's braces, so "[^}]*" would stop too early).
        rule = re.search(re.escape(selector) + r"\s*\{(.*?)\}\s*$", css, re.S | re.M)
        assert rule, selector
        assert re.search(r"min-height:\s*(2[4-9]|[3-9]\d)px", rule.group(1)), selector


def test_the_super_group_sparkline_keeps_its_drawn_size() -> None:
    """A 300 x 120 drawing at full card width scaled 3.6x (journalist walk 4e)."""
    assert 'class="sg-spark"' in read_static("app-insights.js")
    assert re.search(r"\.sg-spark\s*\{[^}]*max-width:\s*420px", _css())


def test_the_agenda_states_its_caveat_once() -> None:
    """The intro and the month bar printed the same four sentences on one screen."""
    html = read_static("index.html")
    tab = html.split('id="tab-agenda"', 1)[1].split('id="tab-climate"', 1)[0]
    assert "<label>View</label>" not in tab, "the orphan label the relocated tabs left behind"
    assert 'id="agenda-views" aria-label="View"' in tab, "the view switch keeps its name"
    agenda = read_static("app-agenda.js")
    assert 'textContent = AG.caveat || ""' not in agenda
    assert "A forward-looking agenda of major recurring events." in agenda


def test_the_agenda_duplicate_check_matches_the_servers_caveat() -> None:
    """The month bar hides the caveat by its first sentence; if the server's sentence
    is reworded, this fails rather than letting the caveat be printed twice again."""
    from src.api.events import _CAVEAT

    assert _CAVEAT.startswith("A forward-looking agenda of major recurring events.")


def test_the_sky_lays_out_with_one_inner_radius() -> None:
    """A fixed rInner of 46 px beside the paint path's 0.19 x outer squeezed a phone
    sky's value band to 24 px after one measure switch."""
    js = read_static("app-observatory.js")
    assert "rInner: 46" not in js
    assert js.count("Math.round((_obs.rOuter || 240) * 0.19)") == 1
