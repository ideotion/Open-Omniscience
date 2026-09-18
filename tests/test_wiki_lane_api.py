"""The lane's read-only surfaces: Q714's counts, Q712's analytics, Q711 and Q819 step 1.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A lane that has never run is the ordinary state of a fresh install, so the ABSENCE is
what most of these check. "This lane has not run" and "this lane ran and found nothing"
are different facts about an operator's machine, and a route that answered ``0`` to
both would make the Home strip claim a measurement nobody took.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from src.api import wiki_lane
from src.versioned.models import VersionedChange, VersionedEntityFact
from src.versioned.pipeline import ensure_entity
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki.pagefacts import encode


@pytest.fixture
def no_lane(tmp_path, monkeypatch):
    """A machine where the lane has never run: no file at all."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    try:
        yield
    finally:
        dispose_all()


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    create_lane("wiki")
    try:
        yield
    finally:
        dispose_all()


#: Called with their arguments SPELLED OUT rather than relying on the defaults. A
#: route function invoked directly receives FastAPI's ``Query(...)`` object where HTTP
#: would have put an int, and a test that let that through would be exercising a code
#: path no request can reach.
_ROUTES = (
    ("lane_status", lambda: wiki_lane.lane_status()),
    ("lane_analytics", lambda: wiki_lane.lane_analytics(window_days=7)),
    ("lane_counters", lambda: wiki_lane.lane_counters_route(window_days=7)),
    ("lane_places", lambda: wiki_lane.lane_places(limit=2000)),
)


@pytest.mark.parametrize("name,route", _ROUTES, ids=[n for n, _ in _ROUTES])
def test_every_route_answers_a_NAMED_absence_when_the_lane_has_never_run(no_lane, name, route):
    out = route()
    assert out["measured"] is False
    assert out["reason"] == "lane-never-run"
    assert "never run" in out["detail"]


@pytest.mark.parametrize("name,route", _ROUTES, ids=[n for n, _ in _ROUTES])
def test_no_route_returns_a_ZERO_for_an_absent_lane(no_lane, name, route):
    """A zero is a measurement. A lane that has never run took none.

    ``bool`` is excluded deliberately and not by accident: ``measured: False`` is the
    absence itself, and in Python ``False == 0``, so a naive scan would flag the one
    field that is doing this test's job.
    """
    out = route()
    for key, value in out.items():
        if isinstance(value, bool):
            continue
        assert value != 0, f"{name} answered {key}=0 for a lane with no file"


def test_all_four_routes_share_ONE_absence_shape(no_lane):
    """Two surfaces that word "not run yet" differently eventually disagree about it."""
    shapes = [tuple(sorted(route().keys())) for _n, route in _ROUTES]
    assert len(set(shapes)) == 1, shapes


# --------------------------------------------------------------------------- #
# Q714: the lane's own counts, separate from the corpus's.
# --------------------------------------------------------------------------- #
def test_the_status_counts_pages_and_TODAYS_changes_separately(lane):
    now = datetime.now(UTC)
    with lane_session("wiki") as db:
        ensure_entity(db, "en:p1", title="Rome")
        ensure_entity(db, "en:p2", title="Paris")
        db.add(VersionedChange(change_ref="a", feed="stream:en", change_kind="edit", recorded_at=now))
        db.add(
            VersionedChange(
                change_ref="old",
                feed="stream:en",
                change_kind="edit",
                recorded_at=now - timedelta(days=3),
            )
        )
        db.flush()
    out = wiki_lane.lane_status()
    assert out["pages"] == 2
    assert out["changes_today"] == 1
    assert out["changes_total"] == 2


def test_the_status_says_the_count_is_SEPARATE_from_the_article_count(lane):
    """Q714 = a: the "articles" headline stays press unless a lane filter is chosen."""
    out = wiki_lane.lane_status()
    assert "separate from the corpus" in out["caveat"]
    assert "not an article in your press corpus" in out["caveat"]


def test_the_status_names_WHICH_day_it_counted_and_from_when(lane):
    out = wiki_lane.lane_status()
    assert out["day"] == "local"
    assert "T00:00:00" in out["counted_since"], "local midnight, stated"


def test_the_local_midnight_boundary_is_TIMEZONE_AWARE(lane):
    """The lane's timestamp type refuses a naive datetime by name, and it is right to:
    a naive boundary compared against stored UTC shifts the count by the operator's
    offset. This reproduced as a StatementError before the fix."""
    from datetime import datetime as _dt

    out = wiki_lane.lane_status()
    parsed = _dt.fromisoformat(out["counted_since"])
    assert parsed.tzinfo is not None


# --------------------------------------------------------------------------- #
# Q711: the section diff.
# --------------------------------------------------------------------------- #
def test_a_page_the_lane_does_not_follow_is_a_404_not_an_empty_answer(lane):
    with pytest.raises(HTTPException) as exc:
        wiki_lane.lane_sections(external_id="en:p999")
    assert exc.value.status_code == 404


def test_a_followed_page_with_NO_stored_text_says_why_rather_than_showing_nothing(lane):
    with lane_session("wiki") as db:
        ensure_entity(db, "en:p1", title="Rome")
        db.flush()
    out = wiki_lane.lane_sections(external_id="en:p1")
    assert out["measured"] is False
    assert out["reason"] == "no-stored-text"
    assert "HOT tier" in out["detail"] and "budget" in out["detail"]


# --------------------------------------------------------------------------- #
# Q819 step 1: places.
# --------------------------------------------------------------------------- #
def _place(db, external_id, *, lat, lon, qid=None):
    entity = ensure_entity(db, external_id, title=external_id, qid=qid)
    db.flush()
    db.add(
        VersionedEntityFact(
            entity_id=entity.id, name="coordinates", value_json=encode({"lat": lat, "lon": lon})
        )
    )
    db.flush()


def test_a_page_with_no_coordinate_is_ABSENT_and_never_placed_at_null_island(lane):
    with lane_session("wiki") as db:
        ensure_entity(db, "en:p1", title="An idea")
        _place(db, "en:p2", lat=41.9, lon=12.5)
    out = wiki_lane.lane_places(limit=2000)
    assert [p["external_id"] for p in out["points"]] == ["en:p2"]
    assert not any(p["lat"] == 0 and p["lon"] == 0 for p in out["points"])


def test_an_OUT_OF_RANGE_coordinate_is_DROPPED_not_clamped(lane):
    """A clamped coordinate is a point drawn at the edge of the world as though it had
    been measured there."""
    with lane_session("wiki") as db:
        _place(db, "en:p1", lat=999.0, lon=12.5)
        _place(db, "en:p2", lat=41.9, lon=-999.0)
        _place(db, "en:p3", lat=41.9, lon=12.5)
    out = wiki_lane.lane_places(limit=2000)
    assert [p["external_id"] for p in out["points"]] == ["en:p3"]


def test_the_QID_travels_with_each_point_and_a_point_without_one_is_still_drawn(lane):
    """Step 2 (0.5) joins OSM objects on the QID. A point with none is a real place
    with a real coordinate and is marked unjoinable rather than dropped."""
    with lane_session("wiki") as db:
        _place(db, "en:p1", lat=41.9, lon=12.5, qid="Q220")
        _place(db, "en:p2", lat=48.9, lon=2.3)
    out = wiki_lane.lane_places(limit=2000)
    by_id = {p["external_id"]: p for p in out["points"]}
    assert by_id["en:p1"]["qid"] == "Q220" and by_id["en:p1"]["joinable"] is True
    assert by_id["en:p2"]["qid"] is None and by_id["en:p2"]["joinable"] is False
    assert out["with_qid"] == 1


def test_a_BOUNDED_answer_says_it_was_bounded(lane):
    """A truncated set that did not say so would be a silent downsample by another
    name -- the detailed-curves rule applies to points on a map too."""
    with lane_session("wiki") as db:
        for i in range(5):
            _place(db, f"en:p{i}", lat=10.0 + i, lon=20.0 + i)
    out = wiki_lane.lane_places(limit=2)
    assert out["n"] == 2
    assert out["total_with_coordinates"] == 5
    assert out["truncated"] is True


def test_the_places_caveat_distinguishes_an_UNREAD_page_from_a_placeless_one(lane):
    out = wiki_lane.lane_places(limit=2000)
    assert "gap in what has been read, not in the world" in out["caveat"]


def test_the_places_METHOD_names_the_source_of_the_coordinate(lane):
    out = wiki_lane.lane_places(limit=2000)
    assert "prop=coordinates" in out["method"]
    assert "never placed at 0,0" in out["method"]


# --------------------------------------------------------------------------- #
# The map layer's behavioural half, registered so the every-node-suite-has-a-driver
# guard can see it -- a node suite nothing runs is a file, not a test.
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(
    __import__("subprocess").run(["which", "node"], capture_output=True).returncode != 0,
    reason="node is not installed",
)
def test_the_node_driver_runs_the_real_map_layer():
    import pathlib
    import subprocess
    import sys

    root = pathlib.Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        ["node", str(root / "tests" / "wiki_map_layer_node_test.js")],
        capture_output=True,
        text=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    assert proc.returncode == 0, proc.stderr or proc.stdout


# --------------------------------------------------------------------------- #
# An exception's own words must not travel in a response body.
#
# CodeQL flagged `POST /api/wiki/pages`'s pin result for exactly this, and it was
# right: `LaneAbsentError` names the database FILE, and a generic failure carries
# whatever the driver put in its message. Loopback-only is not a reason to hand
# internals to a surface -- the response carries the TOKEN the UI translates plus a
# fixed explanation, and the exception goes to the log.
# --------------------------------------------------------------------------- #
def test_a_pin_that_fails_returns_a_TOKEN_and_never_the_exceptions_own_words(
    tmp_path, monkeypatch, caplog
):
    import logging

    from src.api import wiki as wiki_api

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")

    secret = "/a/path/that/should/never/reach/a/response.db"

    def explode(*_a, **_kw):
        raise RuntimeError(secret)

    monkeypatch.setattr("src.versioned.store.lane_session", explode)
    with caplog.at_level(logging.WARNING, logger="api.wiki"):
        out = wiki_api._pin_to_hot("en", "Rome", 101)

    assert out["ok"] is False
    assert out["reason"] == "pin_failed", "a token the UI can translate"
    blob = " ".join(str(v) for v in out.values())
    assert secret not in blob, "the exception's message reached the response body"
    assert "RuntimeError" not in blob, "so did its type"
    assert any(secret in r.getMessage() or secret in str(r.exc_info) for r in caplog.records), (
        "and it must still be in the LOG -- an operator debugging needs it"
    )


def test_an_ABSENT_lane_says_so_without_naming_the_database_file(tmp_path, monkeypatch):
    from src.api import wiki as wiki_api

    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")

    from src.versioned.store import LaneAbsentError

    def absent(*_a, **_kw):
        raise LaneAbsentError("the wiki lane has no database file at wiki.db")

    monkeypatch.setattr("src.versioned.store.lane_session", absent)
    out = wiki_api._pin_to_hot("en", "Rome", 101)
    assert out["reason"] == "lane_absent"
    assert "wiki.db" not in " ".join(str(v) for v in out.values())
    assert "has not been started" in out["detail"], "and still says what happened"
