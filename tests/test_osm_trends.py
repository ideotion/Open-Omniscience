"""Trend surfaces 2 and 3: metadata adoption over time, and openings and closures (v0.6.0 B3a, S06-01 S3).

Expected values are written out by hand from the fixture extract's stored tags and from each change file below, never computed by the code
under test. Every refusal has a test that fails when the refusal is removed.
"""

from __future__ import annotations

import ast
import json
import pathlib
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from src.osm import apply as A
from src.osm import ingest
from src.osm import trends as TR
from src.osm.lane_models import OsmHistoryChange, OsmHistoryCut, OsmTagChange
from src.versioned import store
from tests import _osm_lane_helpers
from tests.test_osm_apply import DAY1, SEQ0, T0, Mirror, _extract, _osc

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = pathlib.Path(__file__).resolve().parents[1]
D1 = "2025-01-11"  # the date of change file 101 (the fixture's own state time), never the day it is applied


@pytest.fixture
def cut(osm_lane_dir):
    path = _extract(osm_lane_dir)
    assert ingest.ingest_country(path, "ZZ", reader="python").status == "complete"
    return path


def _apply(osm_lane_dir, seq_to_body: dict[int, bytes | str]):
    diffs = {s: (b if isinstance(b, bytes) else _osc(b)) for s, b in seq_to_body.items()}
    rep = A.update_country("ZZ", Mirror(max(diffs), diffs), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    assert rep.outcome == "applied", rep.reason
    return rep


def _tags(d: dict) -> str:
    return "".join(f'<tag k="{k}" v="{v}"/>' for k, v in d.items())


def _day(block: dict, bucket: str) -> dict:
    (row,) = [r for r in block["series"] if r["bucket"] == bucket]
    return row


CAFE = {
    "name": "Fixture Cafe", "opening_hours": "Mo-Fr 08:00-18:00", "website": "https://cafe.invalid", "phone": "+000 0000 0001",
    "email": "cafe@example.invalid", "cuisine": "coffee_shop", "wheelchair": "yes", "amenity": "cafe", "outdoor_seating": "yes",
    "name:fr": "Cafe du Test", "payment:cash": "yes",
}


def test_a_lane_that_never_ran_is_named_and_not_created(osm_lane_dir):
    assert TR.trends("ZZZ") == {"status": "lane-never-run", "country": "ZZZ"}
    assert not store.lane_exists("osm"), "reading the trends must not create the lane file"


def test_a_country_that_was_not_cut_and_a_cut_with_no_file_applied_are_named(cut):
    assert TR.trends("QQQ") == {"status": "not-cut", "country": "QQQ"}
    got = TR.trends("ZZZ")
    assert got["status"] == "no-daily-files" and "adoption" not in got and "openings" not in got, "no figure at all, not zeros"
    assert got["prior"] == {"available": False, "reason": "no-history-cut", "detail": "the full-history planet has not been read for this country"}


def test_the_fixture_day_counts_exactly_these_changes_on_the_files_own_date(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: DAY1})
    got = TR.trends("ZZZ")
    assert got["status"] == "ok" and got["tag_rows"] == 20
    assert got["tracked"]["days"] == [D1] and got["tracked"]["files"] == 1
    assert (got["tracked"]["since"], got["tracked"]["through"]) == (f"{D1}T00:00:00+00:00",) * 2
    # node 5 (the cafe) kept opening_hours (modified, neither gained nor lost) and lost website, email and phone; nothing was gained
    assert _day(got["adoption"], D1) == {
        "bucket": D1,
        "gained": {"opening_hours": 0, "website": 0, "email": 0, "phone": 0},
        "lost": {"opening_hours": 0, "website": 1, "email": 1, "phone": 1},
    }
    # appeared: node 30, way 40, relation 110; disappeared: node 7; nobody stopped qualifying; no signals
    assert _day(got["openings"], D1) == {"bucket": D1, "created": 3, "deleted": 1, "left_class": 0, "disused": 0, "vacant": 0, "closed": 0}
    assert (got["adoption"]["n"], got["openings"]["n"]) == (3, 4)
    for block in (got["adoption"], got["openings"]):
        assert block["method"] and block["caveat"]


def test_the_three_closure_signals_and_a_gain_are_read_from_places_the_lane_already_held(cut, osm_lane_dir):
    body = (
        # the cafe keeps every tag and gains a disused:* key
        f'<modify><node id="5" version="4" timestamp="2025-01-11T01:00:00Z" lat="0.15" lon="0.15">{_tags({**CAFE, "disused:shop": "x"})}</node>'
        # the bakery's shop tag becomes vacant (still a kept class)
        '<node id="6" version="4" timestamp="2025-01-11T01:00:00Z" lat="0.15" lon="0.15"><tag k="shop" v="vacant"/><tag k="name" v="Fixture Bakery"/>'
        '<tag k="phone" v="+000 0000 0002"/><tag k="contact:email" v="bakery@example.invalid"/></node>'
        # the pharmacy's empty opening_hours becomes closed: a signal, and (a non-empty value) a gain of opening hours
        '<node id="7" version="4" timestamp="2025-01-11T01:00:00Z" lat="0.18" lon="0.12"><tag k="amenity" v="pharmacy"/>'
        '<tag k="name" v="Fixture Pharmacy"/><tag k="opening_hours" v="closed"/><tag k="website" v="https://p.invalid"/>'
        '<tag k="contact:website" v="https://p.invalid"/></node></modify>'
        # a NEW place that is vacant from the start appeared; it is not a change to a place the lane held, so it is no vacant signal
        '<create><node id="90" version="1" timestamp="2025-01-11T01:00:00Z" lat="0.16" lon="0.16"><tag k="shop" v="vacant"/>'
        '<tag k="website" v="https://v.invalid"/></node></create>'
    )
    _apply(osm_lane_dir, {101: body})
    got = TR.trends("ZZZ")
    assert _day(got["openings"], D1) == {"bucket": D1, "created": 1, "deleted": 0, "left_class": 0, "disused": 1, "vacant": 1, "closed": 1}
    # the pharmacy gained website AND contact:website: one place, one gain of the type (counted once per place per tag type);
    # the new vacant place's website is not a gain either
    assert _day(got["adoption"], D1)["gained"] == {"opening_hours": 1, "website": 1, "email": 0, "phone": 0}
    assert _day(got["adoption"], D1)["lost"] == {"opening_hours": 0, "website": 0, "email": 0, "phone": 0}


def test_a_tag_moved_to_its_contact_twin_is_neither_a_gain_nor_a_loss(cut, osm_lane_dir):
    moved = {k: v for k, v in CAFE.items() if k != "website"} | {"contact:website": "https://cafe.invalid"}
    _apply(osm_lane_dir, {101: f'<modify><node id="5" version="4" timestamp="2025-01-11T01:00:00Z" lat="0.15" lon="0.15">{_tags(moved)}</node></modify>'})
    got = TR.trends("ZZZ")
    zero = dict.fromkeys(("opening_hours", "website", "email", "phone"), 0)
    assert _day(got["adoption"], D1) == {"bucket": D1, "gained": zero, "lost": zero}, "a move was counted as a loss and a gain"
    assert "counts as neither" in TR.METHOD_ADOPTION, "the method does not say what the code does"


def test_a_row_without_a_timestamp_does_not_make_the_country_unreadable(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: DAY1})
    with store.lane_session("osm") as s:
        s.add(OsmTagChange(osm_type="n", osm_id=77, key="website", change="added", new_value="x", diff_timestamp=None, object_version=1, country_alpha3="ZZZ"))
        s.add(OsmTagChange(osm_type="n", osm_id=78, key="website", change="removed", old_value="x", diff_timestamp=None, object_version=1, country_alpha3="ZZZ", object_event="deleted"))
        s.add(OsmTagChange(osm_type="n", osm_id=79, key="shop", change="modified", old_value="a", new_value="vacant", diff_timestamp=None, object_version=1, country_alpha3="ZZZ"))
    got = TR.trends("ZZZ")
    assert got["status"] == "ok" and [r["bucket"] for r in got["adoption"]["series"]] == [D1], "a row that cannot be placed in a day is not a day"


def test_the_key_rows_of_a_version_that_created_deleted_or_restored_an_object_are_not_adoption_or_signals(cut, osm_lane_dir):
    """history.py writes a per-key row for every key of such a version beside the object-level row; those keys are the event's, not changes."""
    _apply(osm_lane_dir, {101: DAY1})
    t = lambda y, m, d: datetime(y, m, d, tzinfo=UTC)  # noqa: E731
    _history([
        # object 20 is deleted in March 2020: the object-level row, then a removed row per key it held
        ("n", 20, 3, t(2020, 3, 5), "deleted", None, None, None),
        ("n", 20, 3, t(2020, 3, 5), "removed", "website", "w", None),
        ("n", 20, 3, t(2020, 3, 5), "removed", "shop", "vacant", None),
        # restored in April 2020: the object-level row, then an added row per key
        ("n", 20, 4, t(2020, 4, 5), "restored", None, None, None),
        ("n", 20, 4, t(2020, 4, 5), "added", "website", None, "w"),
        ("n", 20, 4, t(2020, 4, 5), "added", "shop", None, "vacant"),
        # a chain that STARTS after version 1: created at version 3, every key added
        ("n", 21, 3, t(2020, 4, 9), "created", None, None, None),
        ("n", 21, 3, t(2020, 4, 9), "added", "phone", None, "p"),
        # an ordinary edit, which is adoption
        ("n", 22, 5, t(2020, 4, 20), "added", "email", None, "e"),
    ])
    p = TR.trends("ZZZ")["prior"]
    assert [r["bucket"] for r in p["adoption"]["series"]] == ["2020-03", "2020-04"]
    assert _day(p["adoption"], "2020-03")["lost"]["website"] == 0, "a deleted place's keys were counted as lost"
    a = _day(p["adoption"], "2020-04")
    assert (a["gained"]["website"], a["gained"]["phone"], a["gained"]["email"]) == (0, 0, 1)
    assert _day(p["openings"], "2020-04")["vacant"] == 0 and _day(p["openings"], "2020-03")["deleted"] == 1
    assert _day(p["openings"], "2020-04")["created"] == 1


def test_an_object_that_stops_qualifying_is_left_class_and_its_lost_tags_are_not_adoption(cut, osm_lane_dir):
    # node 6 loses its shop tag: it leaves the kept classes. Its phone and e-mail did not change, and its shop key is not a metadata type.
    body = (
        '<modify><node id="6" version="4" timestamp="2025-01-11T01:00:00Z" lat="0.15" lon="0.15"><tag k="name" v="Fixture Bakery"/>'
        '<tag k="phone" v="+000 0000 0002"/></node></modify>'
    )
    _apply(osm_lane_dir, {101: body})
    got = TR.trends("ZZZ")
    assert _day(got["openings"], D1)["left_class"] == 1
    # the lost contact:email would read as a lost e-mail if left_class rows were counted as adoption
    assert _day(got["adoption"], D1)["lost"]["email"] == 0 and got["adoption"]["n"] == 0


def test_a_day_with_a_file_and_no_change_is_a_zero_and_a_day_without_a_file_is_absent(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: DAY1, 102: ""})
    got = TR.trends("ZZZ")
    days = got["tracked"]["days"]
    assert days == [D1, "2025-01-12"], "no file was applied for 2025-01-13, so it is neither a zero nor a day"
    assert _day(got["adoption"], "2025-01-12") == {
        "bucket": "2025-01-12", "gained": dict.fromkeys(("opening_hours", "website", "email", "phone"), 0),
        "lost": dict.fromkeys(("opening_hours", "website", "email", "phone"), 0),
    }
    assert [r["bucket"] for r in got["openings"]["series"]] == days


def test_a_rebaseline_is_a_named_unobserved_stretch_and_the_earlier_rows_stay(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: DAY1})
    (osm_lane_dir / "fresh").mkdir()
    A.rebaseline("ZZ", _extract(osm_lane_dir / "fresh", seq=SEQ0 + 200, when=T0 + timedelta(days=200)), reason="past retention", reader="python")
    got = TR.trends("ZZZ")
    assert got["tracked"]["days"] == [D1], "the file applied before the re-baseline is still a day; nothing after it yet"
    (gap,) = got["tracked"]["unobserved"]
    assert gap["kind"] == "rebaseline" and gap["to_time"] == (T0 + timedelta(days=200)).isoformat()
    assert got["tag_rows"] == 20, "a re-baseline does not erase what was observed"


def _history(rows, *, status="complete"):
    with store.lane_session("osm") as s:
        s.add(OsmHistoryCut(alpha3="ZZZ", status=status, history_vintage=datetime(2025, 1, 1, tzinfo=UTC), span_json=json.dumps({"oldest": "2019-01-01T00:00:00+00:00"})))
        for osm_type, osm_id, version, when, change, key, old, new in rows:
            s.add(OsmHistoryChange(country_alpha3="ZZZ", osm_type=osm_type, osm_id=osm_id, object_version=version, version_timestamp=when, change=change, key=key, old_value=old, new_value=new))


def test_the_planets_prior_is_read_separately_by_month_and_never_added_to_the_window(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: DAY1})
    before = TR.trends("ZZZ")
    assert before["prior"]["available"] is False and before["prior"]["reason"] == "no-history-cut"
    t = lambda y, m, d: datetime(y, m, d, tzinfo=UTC)  # noqa: E731
    _history([
        ("n", 5, 1, t(2019, 1, 5), "added", "website", None, "x"),          # an object's FIRST version adds every key: not adoption
        ("n", 5, 2, t(2020, 3, 10), "added", "website", None, "x"),         # gained website, 2020-03
        ("n", 6, 3, t(2020, 3, 20), "removed", "phone", "p", None),         # lost phone, 2020-03
        ("n", 7, 1, t(2020, 5, 1), "created", None, None, None),            # appeared, 2020-05
        ("n", 8, 4, t(2020, 5, 2), "deleted", None, None, None),            # disappeared, 2020-05
        ("n", 5, 4, t(2021, 1, 9), "modified", "shop", "bakery", "vacant"),  # vacant signal, 2021-01
        ("n", 9, 2, None, "added", "email", None, "e"),                     # no timestamp: cannot be placed in a month, not invented
    ])
    got = TR.trends("ZZZ")
    p = got["prior"]
    assert p["available"] is True and p["bucket"] == "month" and p["span"] == {"oldest": "2019-01-01T00:00:00+00:00"}
    assert [r["bucket"] for r in p["adoption"]["series"]] == ["2020-03", "2020-05", "2021-01"]
    assert _day(p["adoption"], "2020-03") == {
        "bucket": "2020-03", "gained": {"opening_hours": 0, "website": 1, "email": 0, "phone": 0},
        "lost": {"opening_hours": 0, "website": 0, "email": 0, "phone": 1},
    }
    # no "left_class": the history has no such fact, so no column of zeros stands in for it
    assert _day(p["openings"], "2020-05") == {"bucket": "2020-05", "created": 1, "deleted": 1, "disused": 0, "vacant": 0, "closed": 0}
    assert "left_class" not in p["openings"]["fields"]
    assert _day(p["openings"], "2021-01")["vacant"] == 1
    # the planet's block shows its own caveat (a month, not a day), never the window's sentence about days without a file
    assert p["adoption"]["caveat"] == TR.CAVEAT_PRIOR and p["openings"]["caveat"] == TR.CAVEAT_PRIOR
    assert "day without a change file" not in TR.CAVEAT_PRIOR
    # the window is unchanged by the prior's existence: same series, same totals
    assert got["adoption"] == before["adoption"] and got["openings"] == before["openings"] and got["tracked"] == before["tracked"]


def test_a_history_cut_that_did_not_finish_is_not_used(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: DAY1})
    _history([("n", 5, 2, datetime(2020, 3, 10, tzinfo=UTC), "added", "website", None, "x")], status="failed")
    assert TR.trends("ZZZ")["prior"]["reason"] == "history-cut-unfinished"


def test_a_lane_cut_before_the_tag_table_says_why_and_never_reads_zero(cut):
    with store.lane_session("osm") as s:
        s.execute(sa.text("DROP TABLE osm_tag_changes"))
    got = TR.trends("ZZZ")
    assert got["status"] == "old-lane" and got["missing"] == ["osm_tag_changes"] and "adoption" not in got


def test_an_unreadable_lane_is_named_without_the_errors_words(cut, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret path /home/someone/x")

    monkeypatch.setattr(store, "lane_session", boom)
    got = TR.trends("ZZZ")
    assert got["status"] == "unreadable" and "secret" not in repr(got) and "/home" not in repr(got)


def test_the_route_answers_for_a_cut_country_and_refuses_a_bad_code(cut, osm_lane_dir):
    from fastapi.testclient import TestClient

    from src.api.main import app

    _apply(osm_lane_dir, {101: DAY1})
    with TestClient(app) as c:
        r = c.get("/api/osm/countries/ZZ/trends")
        assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["tracked"]["days"] == [D1]
        assert c.get("/api/osm/countries/not-a-country/trends").status_code == 400


def test_the_module_makes_no_request_and_imports_no_socket_library():
    tree = ast.parse((ROOT / "src/osm/trends.py").read_text("utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & {"requests", "httpx", "urllib", "socket", "http"}


def test_an_empty_value_is_not_a_gain_and_a_contact_twin_is_the_same_type_and_off_is_a_closed_signal(cut, osm_lane_dir):
    body = (
        # the bakery gains website="": a key with nothing in it says nothing
        '<modify><node id="6" version="4" timestamp="2025-01-11T01:00:00Z" lat="0.15" lon="0.15"><tag k="shop" v="bakery"/><tag k="name" v="Fixture Bakery"/>'
        '<tag k="phone" v="+000 0000 0002"/><tag k="contact:email" v="bakery@example.invalid"/><tag k="website" v=""/></node>'
        # the pharmacy gains only contact:website (the twin), and sets its opening hours to off
        '<node id="7" version="4" timestamp="2025-01-11T01:00:00Z" lat="0.18" lon="0.12"><tag k="amenity" v="pharmacy"/><tag k="name" v="Fixture Pharmacy"/>'
        '<tag k="opening_hours" v="off"/><tag k="contact:website" v="https://p.invalid"/></node></modify>'
    )
    _apply(osm_lane_dir, {101: body})
    got = TR.trends("ZZZ")
    assert _day(got["adoption"], D1)["gained"]["website"] == 1, "the twin counts as the type, the empty value does not"
    assert _day(got["openings"], D1)["closed"] == 1


def test_another_countrys_rows_are_not_this_countrys(cut, osm_lane_dir):
    from src.osm.lane_models import OsmTagChange

    _apply(osm_lane_dir, {101: DAY1})
    before = TR.trends("ZZZ")
    with store.lane_session("osm") as s:
        s.add(OsmTagChange(osm_type="n", osm_id=999, key="website", change="added", new_value="x", diff_timestamp=datetime(2025, 1, 11, tzinfo=UTC), object_version=1, country_alpha3="YYY"))
    after = TR.trends("ZZZ")
    assert after["adoption"] == before["adoption"] and after["tag_rows"] == before["tag_rows"] == 20
