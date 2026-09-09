"""The omnibar's last two REMAINING groups: events, and the CONTENT of the Help docs.

The palette already offered the Help documents by NAME. A reader who remembers a phrase
and not which document holds it had nowhere to type it, and the world-events agenda was
not searchable from the omnibar at all.

WHY THESE TWO ARE ALLOWED HERE AT ALL, which is the whole design question on this
surface. `search_omni.py` opens with "Never scan-on-type: every group is served by an
index or a small bounded table". Both new groups are bounded BY CONSTRUCTION and, more
to the point, neither grows with the user's corpus: the events catalogue is a 154-entry
file that ships with the app, and the Help documents are the ten the API's own allow-list
serves. That is exactly the property the keyword table lacks -- 406,723 rows on a real
corpus -- which is why typo tolerance is parked on an index decision instead of built.

So the tests below are mostly about BOUNDEDNESS and about not fabricating: an event with
no fixed date stays unconfirmed, and a doc hit carries the heading it actually sits under.
"""

from __future__ import annotations

import pytest

from src.api import search_omni as so


@pytest.fixture(autouse=True)
def _warm():
    so._docs_index.cache_clear()
    yield
    so._docs_index.cache_clear()


# ---- the events group ------------------------------------------------------------- #


def test_events_match_on_what_the_catalogue_asserts():
    out = so._events_group(None, "press")
    assert out["kind"] == "events"
    assert out["total"] >= 1
    assert len(out["items"]) <= so._PER_GROUP, "the per-group display bound must hold"
    assert "catalogue" in out["note"] and "never deduced" in out["note"]


def test_an_event_without_a_fixed_date_is_carried_as_unconfirmed_never_filled_in():
    """A movable summit has no exact date and the catalogue declines to invent one. The
    omnibar must carry that through rather than quietly presenting a guess as a date."""
    from src.events.catalog import agenda

    movable = [e for e in agenda() if not e.get("confirmed")]
    if not movable:
        pytest.skip("this catalogue has no movable events to exercise")
    target = movable[0]
    out = so._events_group(None, str(target["title"])[:12].casefold())
    hit = next((i for i in out["items"] if i["title"] == target["title"]), None)
    assert hit is not None, "the movable event should be findable by its own title"
    assert hit["confirmed"] is False
    assert hit["next_occurrence"] == target.get("next_occurrence")


def test_the_events_total_is_the_real_match_count_not_the_display_bound():
    """UNCONDITIONAL, and chosen so the two numbers must DIFFER.

    The first draft asserted `total >= len(items)` and guarded the interesting half behind
    `if total > _PER_GROUP` -- both satisfied when the endpoint reports the display bound
    AS the total, which is precisely the failure the module's "totals are disclosed so the
    display bound never silently hides how much matched" doctrine exists to prevent. The
    mutant that returned len(items) passed. It does not now."""
    out = so._events_group(None, "day")
    assert out["total"] > so._PER_GROUP, "pick a query that genuinely overflows the bound"
    assert len(out["items"]) == so._PER_GROUP
    assert out["total"] > len(out["items"]), (
        "the total must be the REAL match count, never the number displayed"
    )


def test_a_query_matching_nothing_is_an_honest_empty_group():
    out = so._events_group(None, "zzzz-no-such-event")
    assert out["items"] == [] and out["total"] == 0 and out["note"]


# ---- the Help-document content group ---------------------------------------------- #


def test_the_docs_index_covers_only_the_documents_the_app_actually_serves():
    """Read from the API's own allow-list, so a new Help document becomes searchable on
    the commit that publishes it -- and an unserved repo document never leaks into a
    result the reader cannot open."""
    from src.api.main import _DOCS

    slugs = {row[0] for row in so._docs_index()}
    assert slugs, "the index must not be empty"
    assert slugs <= set(_DOCS), f"indexed documents outside the allow-list: {slugs - set(_DOCS)}"


def test_a_hit_carries_the_heading_it_sits_under_and_that_heading_s_real_anchor():
    """The point of the group: open at the passage, not at the top of a 3,000-line
    manual. The anchor must be one the renderer actually produces."""
    out = so._docs_group(None, "passphrase")
    assert out["total"] >= 1
    hit = out["items"][0]
    assert hit["heading"], "a prose hit should know its section"
    assert hit["anchor"] and " " not in hit["anchor"]
    assert "passphrase" in hit["snippet"].casefold()


def test_the_anchor_convention_matches_the_one_the_help_renderer_uses():
    """Pinned against the shipped slugifier's own documented examples -- the same cases
    tests/test_help_doc_anchors_resolve.py uses -- so this port cannot drift into
    producing anchors that land nowhere."""
    assert so._slugify_heading("1. Install & first run") == "1-install--first-run"
    assert so._slugify_heading("3.1a Analysis — the corpora window") == (
        "31a-analysis--the-corpora-window"
    )
    assert so._slugify_heading("`code` and **bold**") == "code-and-bold"


def test_code_blocks_tables_and_quotes_are_not_prose():
    """A hit inside a fenced command or a table row is noise in a prose search, and the
    note says they are excluded -- so the index must actually exclude them."""
    for _slug, _title, _heading, _anchor, line in so._docs_index():
        assert not line.startswith(("```", "|", ">")), f"non-prose line indexed: {line[:60]}"


def test_the_snippet_is_bounded_and_never_silently_truncated():
    out = so._docs_group(None, "the")
    for item in out["items"]:
        assert len(item["snippet"]) <= so._DOC_SNIPPET
        if len(item["snippet"]) == so._DOC_SNIPPET:
            assert item["snippet"].endswith("…"), "a cut snippet must say it was cut"


def test_the_docs_total_is_the_real_match_count():
    """Same shape as the events one, and weak for the same reason until it was mutated:
    a total equal to the display bound must fail here."""
    out = so._docs_group(None, "corpus")
    assert out["total"] > so._PER_GROUP, "pick a query that genuinely overflows the bound"
    assert len(out["items"]) == so._PER_GROUP
    assert out["total"] > len(out["items"]), (
        "the total must be the REAL match count, never the number displayed"
    )


def test_the_index_is_built_once_not_per_keystroke():
    """The boundedness claim in the module comment rests on this. A per-keystroke rebuild
    would be the scan-on-type the surface promises never to do."""
    so._docs_index.cache_clear()
    assert so._docs_index.cache_info().misses == 0
    for _ in range(5):
        so._docs_group(None, "corpus")
    info = so._docs_index.cache_info()
    assert info.misses == 1, f"index rebuilt {info.misses} times"
    assert info.hits >= 4


def test_neither_new_group_touches_the_keyword_table():
    """The distinction the module comment draws: these are bounded populations that ship
    with the app. If either ever reached Keyword (406,723 rows on a real corpus) it would
    become the very scan-on-type this surface forbids."""
    import inspect

    for fn in (so._events_group, so._docs_group, so._docs_index):
        src = inspect.getsource(fn)
        assert "Keyword" not in src, f"{fn.__name__} reaches the keyword table"


# ---- the fan-out ------------------------------------------------------------------ #


def test_both_groups_are_registered_in_the_omni_fan_out():
    import inspect

    src = inspect.getsource(so.omni)
    assert "_events_group" in src and "_docs_group" in src


def test_a_failing_group_can_never_blank_the_omnibar():
    """Pre-existing contract, re-pinned because two more groups now ride it: each group
    is called inside its own try/except, so one raising leaves the others rendered."""
    import inspect

    src = inspect.getsource(so.omni)
    assert "one group must never blank the omnibar" in src


# ---- the renderer: a group nobody draws is a group that does not exist ------------- #


def test_both_kinds_are_rendered_by_the_palette():
    """The omnibar renderer (_omniItems) is an if/else-if chain on `g.kind` and SILENTLY DROPS an
    unknown one. A backend group with no branch is exactly the built-and-unreachable
    shape this same PR fixed in the Conjunction Lens, so it is pinned here."""
    from tests.js_source_helper import app_js, assert_present, function_source

    fn = function_source(app_js(), "_omniItems")
    assert_present(fn, 'g.kind === "events"', why="the events group needs a branch")
    assert_present(fn, 'g.kind === "docs"', why="the Help-content group needs a branch")


def test_a_movable_event_does_not_borrow_a_date_in_the_palette():
    """The catalogue refuses to fabricate a date for a movable summit. The row must say
    so rather than fall back to a neighbouring field that happens to hold one."""
    from tests.js_source_helper import app_js, assert_present, function_source

    fn = function_source(app_js(), "_omniItems")
    assert_present(fn, "it.confirmed && it.next_occurrence",
                   why="a date is shown only when the catalogue confirms it")
    assert_present(fn, "date moves each year", why="the honest alternative to a date")


def test_a_help_hit_opens_at_its_passage():
    from tests.js_source_helper import app_js, assert_present, function_source

    fn = function_source(app_js(), "_omniItems")
    assert_present(fn, "openDoc(it.slug, it.anchor)", why="the anchor must be passed through")

    open_doc = function_source(app_js(), "openDoc")
    assert_present(open_doc, "anchor", why="openDoc must accept one")
    assert_present(open_doc, "scrollIntoView", why="and actually scroll to it")


def test_an_unknown_anchor_never_swallows_the_document():
    """Additive by construction: a stale anchor simply does not scroll. If a missing
    element could blank the prose, a renamed heading would break Help itself."""
    from tests.js_source_helper import app_js, assert_present, function_source

    open_doc = function_source(app_js(), "openDoc")
    assert_present(open_doc, "(at || prose).scrollIntoView",
                   why="fall back to the document, never to nothing")


def test_the_two_new_strings_are_keyed_in_all_twelve_locales():
    import json
    import pathlib

    for p in sorted(pathlib.Path("src/static/locales").glob("*.json")):
        d = json.loads(p.read_text("utf-8"))
        for key in ("Help", "date moves each year — see the official source"):
            assert key in d, f"{p.stem} is missing {key!r}"
