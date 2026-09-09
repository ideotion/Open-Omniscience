"""The keyword explorer can now CORRECT a tag, not only read one.

The docket's Item AC left this as its REMAINING half: "the per-keyword TAG add/remove
UI (the S3a write endpoints exist; the explorer currently does explore + hide + backfill
only)". Both write endpoints have existed and been tested since the tags shipped, so an
operator could see the baseline pass's labels and had no way to fix a wrong one -- on a
surface whose entire purpose is curation.

Two things are guarded here. The WIRING, because a frontend-only feature has no other
mechanical witness. And the ROUTES, because the endpoints were covered only by
direct-call unit tests: nothing proved they were actually reachable over HTTP under the
prefix the frontend types into a fetch, which is exactly the seam a new caller hits.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.js_source_helper import app_js, assert_absent, assert_present, function_source


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_the_write_endpoints_are_reachable_over_http_not_only_by_direct_call(client):
    """A 404 here means the frontend's fetch would fail while the unit tests stayed
    green -- the gap this feature had to cross."""
    # Reachability is asserted by CALLING, never by reading app.routes: the recorded
    # lesson is that a positive assertion against the shared mutable app singleton is
    # how the additive-restore guard went flaky in CI. A 404 below is the failure.
    r = client.get("/api/insights/keyword-tags", params={"normalized": "no-such-keyword-zz"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["tags"] == {} and body["sources"] == {}, "an unknown keyword reads empty, not 404"

    # The validation the editor relies on to keep a typo out of the store.
    bad_axis = client.post(
        "/api/insights/keyword-tags", json={"normalized": "x", "axis": "vibe", "tag": "t"}
    )
    assert bad_axis.status_code == 400 and "axis" in bad_axis.json()["detail"]
    empty_tag = client.post(
        "/api/insights/keyword-tags", json={"normalized": "x", "axis": "type", "tag": "   "}
    )
    assert empty_tag.status_code == 400


def test_the_row_offers_a_tag_editor_that_loads_lazily():
    """Lazily on purpose: the tag list is a PER-KEYWORD read and the explorer renders up
    to 200 rows, so eager loading would be a self-inflicted stampede."""
    js = app_js()
    show = function_source(js, "kxShowTag")
    assert_present(show, "kxToggleTags(", why="each row needs a way into its tags")
    assert_present(show, "kx-tagbox", why="the editor gets its own container per row")
    assert_present(show, "hidden", why="closed until asked for")
    assert_absent(show, "/api/insights/keyword-tags?normalized=",
                  why="the per-keyword read must NOT fire while rendering the list")

    toggle = function_source(js, "kxToggleTags")
    assert_present(toggle, "kxRenderTags(", why="fetch on open")


def test_the_editor_shows_who_asserted_each_tag():
    """Provenance is the point of a curation surface: an operator has to know which
    labels are the baseline's and which are theirs before changing one."""
    render = function_source(app_js(), "kxRenderTags")
    assert_present(render, "/api/insights/keyword-tags?normalized=")
    assert_present(render, "d.sources", why="the endpoint returns axis:tag -> baseline|user")
    assert_present(render, 't("you")')
    assert_present(render, 't("baseline")')
    assert_present(render, "No tags yet.", why="an honest empty state, never a blank box")


def test_add_and_remove_post_to_the_real_endpoints_and_re_read_after_writing():
    """Re-reading rather than patching the DOM optimistically: add is idempotent and
    remove drops EVERY source of a tag, so the server's answer can differ from what a
    local edit would have assumed."""
    js = app_js()
    add = function_source(js, "kxAddTag")
    assert_present(add, '"/api/insights/keyword-tags"')
    assert_present(add, '"POST"')
    assert_present(add, "kxRenderTags(", why="re-read after writing")
    assert_present(add, ".trim()", why="an empty tag is a 400; do not send it")

    rm = function_source(js, "kxRemoveTag")
    assert_present(rm, '"/api/insights/keyword-tags/remove"')
    assert_present(rm, "kxRenderTags(", why="re-read after writing")


def test_the_editor_only_offers_the_axes_the_backend_accepts():
    """`_norm_tag` rejects anything outside ("type", "topic") with a 400. A free-text
    axis field would make that refusal the operator's problem instead of preventing it."""
    from src.api.insights import _TAG_AXES

    render = function_source(app_js(), "kxRenderTags")
    assert_present(render, '["type", "topic"]')
    assert tuple(_TAG_AXES) == ("type", "topic"), (
        "the backend's axis vocabulary moved; the editor's <select> must move with it"
    )
