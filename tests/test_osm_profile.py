"""Trend surfaces 4 to 6: brand footprint, contact channels, data freshness (v0.6.0 B3b, S06-01 S3).

Expected values are written out by hand from the rows seeded below and from each change file, never computed by the code under test.
Every refusal has a test that fails when the refusal is removed.
"""

from __future__ import annotations

import ast
import json
import pathlib
from datetime import UTC, date, datetime

import pytest
import sqlalchemy as sa

from src.osm import ingest
from src.osm import profile as PF
from src.osm.lane_models import OsmCountry, OsmTagChange, osm_objects_table
from src.versioned import store
from tests import _osm_lane_helpers
from tests.test_osm_apply import DAY1, _extract
from tests.test_osm_trends import CAFE, D1, _apply, _history, _tags

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = pathlib.Path(__file__).resolve().parents[1]
T = osm_objects_table


@pytest.fixture
def cut(osm_lane_dir):
    path = _extract(osm_lane_dir)
    assert ingest.ingest_country(path, "ZZ", reader="python").status == "complete"
    return path


def _dt(y, m, d):
    return datetime(y, m, d, tzinfo=UTC)


def _seed():
    """Five places with metadata (nodes 5, 6, 7, relation 101 and an inserted node 900), and a brand on a PLACE (node 8) that must not count.

    The extract's vintage is 2025-01-10, so with no change file applied the ages are measured from it: one year back is 2024-01-10, two
    years 2023-01-10 and five years 2020-01-10.
    """
    with store.lane_session("osm") as s:
        def upd(osm_type, osm_id, **vals):
            s.execute(T.update().where(T.c.osm_type == osm_type, T.c.osm_id == osm_id).values(**vals))

        upd("n", 5, t_brand="Acme", t_brand_wikidata="Q1", t_operator="Op1", t_check_date="2024-12-30", timestamp=_dt(2024, 12, 1),
            contact=json.dumps({"facebook": "f", "instagram": "i"}))
        upd("n", 6, t_brand="Acme", t_brand_wikidata="Q1", t_check_date="2023", timestamp=_dt(2023, 6, 1),
            contact=json.dumps({"email": "bakery@example.invalid", "twitter": "t"}))
        upd("n", 7, t_brand="acme", t_check_date="soon", timestamp=_dt(2019, 1, 1), contact=json.dumps({"facebook": ""}))
        upd("r", 101, t_check_date="2025-06", timestamp=None)
        upd("n", 8, t_brand="Acme", t_brand_wikidata="Q1")   # a place, not a place with metadata: never counted
        s.execute(T.insert().values(osm_type="n", osm_id=900, country_alpha3="ZZZ", kind="poi", notable=False, t_check_date="", timestamp=None))


def _snap(surface, **kw):
    got = PF.profile("ZZZ", surface, **kw)
    assert got["status"] == "ok", got
    return got


# --------------------------------------------------------------------------- #
#  Refusals and shape                                                          #
# --------------------------------------------------------------------------- #


def test_a_lane_that_never_ran_is_named_and_not_created(osm_lane_dir):
    assert PF.profile("ZZZ", "brands") == {"status": "lane-never-run", "country": "ZZZ", "surface": "brands"}
    assert not store.lane_exists("osm"), "reading a surface must not create the lane file"


def test_a_country_that_was_not_cut_and_an_unknown_surface_are_named(cut):
    assert PF.profile("QQQ", "channels") == {"status": "not-cut", "country": "QQQ", "surface": "channels"}
    assert PF.profile("ZZZ", "nonsense")["status"] == "unknown-surface"


def test_an_unreadable_lane_is_named_without_the_errors_words(cut, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret path /home/someone/x")

    monkeypatch.setattr(store, "lane_session", boom)
    got = PF.profile("ZZZ", "freshness")
    assert got["status"] == "unreadable" and "secret" not in repr(got) and "/home" not in repr(got)


def test_a_cut_with_no_file_applied_has_a_snapshot_and_says_the_window_is_empty(cut):
    _seed()
    got = _snap("brands")
    assert got["changes"] == {"status": "no-daily-files"}, "no figure at all for the window, not zeros"
    assert got["prior"]["available"] is False and got["prior"]["reason"] == "no-history-cut"
    assert got["snapshot"]["n"] == 5, "the snapshot does not need a change file"
    assert got["vintage"] == {"extract": "2025-01-10T00:00:00+00:00", "last_diff": None, "reference": "2025-01-10T00:00:00+00:00"}


def test_a_lane_cut_before_the_tag_table_keeps_its_snapshot_and_says_why_the_window_is_missing(cut):
    _seed()
    with store.lane_session("osm") as s:
        s.execute(sa.text("DROP TABLE osm_tag_changes"))
    got = _snap("channels")
    assert got["changes"]["status"] == "old-lane" and got["changes"]["missing"] == ["osm_tag_changes"] and "series" not in got["changes"]
    assert got["snapshot"]["n"] == 5


# --------------------------------------------------------------------------- #
#  Surface 4: brands                                                           #
# --------------------------------------------------------------------------- #


def test_the_brand_counts_and_ranking_are_exactly_these_and_an_operator_is_never_a_brand(cut):
    _seed()
    snap = _snap("brands")["snapshot"]
    assert snap["n"] == 5, "the place (node 8) and everything not a place with metadata are not counted"
    present = {t["key"]: (t["present"], t["group"]) for t in snap["tags"]}
    assert present == {"brand": (3, "brand"), "brand:wikidata": (2, "brand"), "operator": (1, "operator"), "operator:wikidata": (0, "operator")}
    assert [t["share"] for t in snap["tags"]] == [3 / 5, 2 / 5, 1 / 5, 0.0]
    by_name, by_id = snap["rankings"]
    # the spelling is the mapper's: Acme and acme are two rows, the larger first
    assert by_name == {"key": "brand", "total": 2, "shown": 2, "rows": [{"value": "Acme", "places": 2}, {"value": "acme", "places": 1}]}
    assert by_id == {"key": "brand:wikidata", "total": 1, "shown": 1, "rows": [{"value": "Q1", "places": 2}]}
    assert "never merged into a brand" in PF.METHOD_BRANDS, "the method does not say what the code does"


def test_the_ranking_limit_is_stated_and_clamped_and_the_total_is_always_the_real_one(cut):
    _seed()
    one = _snap("brands", limit=1)["snapshot"]
    assert one["limit"] == 1 and one["rankings"][0]["shown"] == 1 and one["rankings"][0]["total"] == 2
    assert one["rankings"][0]["rows"] == [{"value": "Acme", "places": 2}]
    assert _snap("brands", limit=0)["snapshot"]["limit"] == 1
    assert _snap("brands", limit=10**9)["snapshot"]["limit"] == PF.MAX_LIMIT


def test_ties_in_the_ranking_break_by_the_text_so_the_order_is_the_same_every_time(cut):
    _seed()
    with store.lane_session("osm") as s:
        s.execute(T.update().where(T.c.osm_type == "n", T.c.osm_id == 7).values(t_brand="Zed"))
        s.execute(T.update().where(T.c.osm_type == "n", T.c.osm_id == 6).values(t_brand="Beta"))
        s.execute(T.update().where(T.c.osm_type == "n", T.c.osm_id == 5).values(t_brand="Alpha"))
    assert [r["value"] for r in _snap("brands")["snapshot"]["rankings"][0]["rows"]] == ["Alpha", "Beta", "Zed"]


# --------------------------------------------------------------------------- #
#  Surface 5: channels                                                         #
# --------------------------------------------------------------------------- #


def test_the_channel_counts_the_social_services_and_the_mix_are_exactly_these(cut):
    _seed()
    snap = _snap("channels")["snapshot"]
    assert snap["n"] == 5
    # website: node 5 only; phone: 5 and 6; e-mail: 5 (the tag) and 6 (its contact: twin); social: 5 (two services) and 6 (one)
    assert [(c["key"], c["present"]) for c in snap["channels"]] == [("website", 1), ("phone", 2), ("email", 2), ("social", 2)]
    assert {s_["key"]: s_["present"] for s_ in snap["social"]} == {
        "facebook": 1, "instagram": 1, "twitter": 1, "youtube": 0, "tiktok": 0, "linkedin": 0, "telegram": 0, "whatsapp": 0,
    }, "node 7's empty contact:facebook was counted as a channel"
    # places by how many of the four channels they carry: node 5 carries four, node 6 three, nodes 7, 101 and 900 none
    assert [(m["channels"], m["places"]) for m in snap["mix"]] == [(0, 3), (1, 0), (2, 0), (3, 1), (4, 1)]
    assert sum(m["places"] for m in snap["mix"]) == snap["n"], "every place is in exactly one bucket of the mix"


def test_site_phone_and_email_are_analytic_ones_figures_exactly(cut):
    from src.osm.completeness import tag_completeness

    _seed()
    comp = {k["key"]: k["present"] for k in tag_completeness("ZZZ")["keys"]}
    snap = {c["key"]: c["present"] for c in _snap("channels")["snapshot"]["channels"]}
    assert (snap["website"], snap["phone"], snap["email"]) == (comp["website"], comp["phone"], comp["email"]), "two tables disagree about one fact"
    assert "opening_hours" not in snap, "opening hours is not a contact channel"


# --------------------------------------------------------------------------- #
#  Surface 6: freshness                                                        #
# --------------------------------------------------------------------------- #


def test_the_edit_ages_and_the_check_dates_are_exactly_these_from_the_extracts_vintage(cut):
    _seed()
    snap = _snap("freshness")["snapshot"]
    assert snap["n"] == 5 and snap["age_years"] == [1, 2, 5]
    le = snap["last_edit"]
    # node 5 edited 2024-12-01 (inside a year of 2025-01-10); node 6 on 2023-06-01 (one to two years); node 7 on 2019-01-01 (over five);
    # relation 101 and node 900 have no timestamp, which is counted, not dropped
    assert {b["bucket"]: b["places"] for b in le["buckets"]} == {"within_1y": 1, "y1_2": 1, "y2_5": 0, "over_5y": 1, "after": 0}
    assert le["no_timestamp"] == 2 and sum(b["places"] for b in le["buckets"]) + le["no_timestamp"] == snap["n"]
    cd = snap["check_date"]
    # carrying: 5, 6, 7 and 101; node 900's EMPTY check_date is absent
    assert cd["present"] == 4 and cd["share"] == 4 / 5
    # 2024-12-30 (inside a year); "2023" read as 2023-01-01 (two to five years: older, never fresher); "2025-06" is after the vintage; "soon" is no date
    assert {b["bucket"]: b["places"] for b in cd["buckets"]} == {"within_1y": 1, "y1_2": 0, "y2_5": 1, "over_5y": 0, "after": 1}
    assert cd["unreadable"] == 1


def test_ages_are_measured_from_the_newest_change_file_not_from_the_extract_and_not_from_the_clock(cut, osm_lane_dir):
    _seed()
    with store.lane_session("osm") as s:   # edited exactly one year before the NEWEST change file's date, one year and a day before the extract's
        s.execute(T.update().where(T.c.osm_type == "n", T.c.osm_id == 5).values(timestamp=_dt(2024, 1, 11)))
    before = _snap("freshness")
    assert {b["bucket"]: b["places"] for b in before["snapshot"]["last_edit"]["buckets"]}["within_1y"] == 1   # 2024-01-11 is after 2024-01-10
    _apply(osm_lane_dir, {101: ""})
    after = _snap("freshness")
    assert after["vintage"]["reference"] == after["vintage"]["last_diff"] == f"{D1}T00:00:00+00:00"
    assert {b["bucket"]: b["places"] for b in after["snapshot"]["last_edit"]["buckets"]}["within_1y"] == 0   # the cut moved to 2024-01-11: not after it
    assert {b["bucket"]: b["places"] for b in after["snapshot"]["last_edit"]["buckets"]}["y1_2"] == 2


def test_an_edit_dated_after_the_vintage_is_named_and_never_counted_as_recent(cut):
    _seed()
    with store.lane_session("osm") as s:   # the extract's vintage is 2025-01-10
        s.execute(T.update().where(T.c.osm_type == "n", T.c.osm_id == 5).values(timestamp=_dt(2025, 3, 1)))
    le = _snap("freshness")["snapshot"]["last_edit"]
    got = {b["bucket"]: b["places"] for b in le["buckets"]}
    assert got["after"] == 1 and got["within_1y"] == 0, "an edit after the vintage was counted as inside the last year"
    assert sum(got.values()) + le["no_timestamp"] == 5


def test_a_lane_with_no_date_to_measure_from_says_so_and_invents_none(cut):
    _seed()
    with store.lane_session("osm") as s:
        s.query(OsmCountry).update({OsmCountry.extract_vintage: None, OsmCountry.diff_timestamp: None})
    snap = _snap("freshness")["snapshot"]
    assert snap["last_edit"] == {"available": False, "reason": "no-reference", "detail": snap["last_edit"]["detail"]}
    assert snap["check_date"]["available"] is False and snap["check_date"]["present"] == 4, "the count needs no date; the ages do"
    assert "buckets" not in snap["check_date"]


def test_check_dates_parse_as_the_start_of_their_period_and_anything_else_is_none():
    p = PF.parse_check_date
    assert p("2024-05-17") == date(2024, 5, 17) and p("2024-05") == date(2024, 5, 1) and p("2024") == date(2024, 1, 1) and p(" 2024-05 ") == date(2024, 5, 1)
    for bad in ("", "soon", "24", "2024-5", "2024-13", "2024-02-30", "2024-05-05T10:00", "2024/05/05", "05-05-2024"):
        assert p(bad) is None, bad


def test_the_age_edges_are_half_open_and_a_leap_day_reference_has_a_cutoff():
    ref = date(2025, 1, 10)
    cuts = [PF._years_before(ref, y) for y in PF.AGE_YEARS]
    assert cuts == [date(2024, 1, 10), date(2023, 1, 10), date(2020, 1, 10)]
    b = PF._age_bucket
    assert b(date(2024, 1, 11), ref, cuts) == "within_1y" and b(date(2024, 1, 10), ref, cuts) == "y1_2", "a year to the day is a year, not under one"
    assert b(date(2023, 1, 10), ref, cuts) == "y2_5" and b(date(2020, 1, 10), ref, cuts) == "over_5y" and b(date(2025, 1, 11), ref, cuts) == "after"
    assert b(date(2025, 1, 10), ref, cuts) == "within_1y", "the reference day itself is not after it"
    assert PF._years_before(date(2024, 2, 29), 1) == date(2023, 2, 28)


# --------------------------------------------------------------------------- #
#  The window and the planet's past                                            #
# --------------------------------------------------------------------------- #

_BODY = (
    # the cafe keeps its tags and gains brand, brand:wikidata, contact:facebook and a check_date
    f'<modify><node id="5" version="4" timestamp="2025-01-11T01:00:00Z" lat="0.15" lon="0.15">{_tags({**CAFE, "brand": "Acme", "brand:wikidata": "Q1", "contact:facebook": "f", "check_date": "2025-01-10"})}</node>'
    # the bakery gains an operator and contact:twitter
    '<node id="6" version="4" timestamp="2025-01-11T01:00:00Z" lat="0.15" lon="0.15"><tag k="shop" v="bakery"/><tag k="name" v="Fixture Bakery"/>'
    '<tag k="phone" v="+000 0000 0002"/><tag k="contact:email" v="bakery@example.invalid"/><tag k="operator" v="Op"/><tag k="contact:twitter" v="t"/></node>'
    # the pharmacy gains a brand and an EMPTY check_date: edited, but not checked
    '<node id="7" version="4" timestamp="2025-01-11T01:00:00Z" lat="0.18" lon="0.12"><tag k="amenity" v="pharmacy"/><tag k="name" v="Fixture Pharmacy"/>'
    '<tag k="opening_hours" v=""/><tag k="brand" v="Pharma"/><tag k="check_date" v=""/></node></modify>'
    # a NEW place that arrives with a brand, a facebook page and a check_date was not changed: it is an appearance, not a gain
    '<create><node id="91" version="1" timestamp="2025-01-11T01:00:00Z" lat="0.16" lon="0.16"><tag k="amenity" v="cafe"/><tag k="brand" v="New"/>'
    '<tag k="contact:facebook" v="n"/><tag k="check_date" v="2025-01-10"/></node></create>'
)


def test_the_window_counts_exactly_these_changes_on_the_files_own_date_for_each_surface(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: _BODY})
    brands = _snap("brands")["changes"]
    assert brands["status"] == "ok" and brands["tracked"]["days"] == [D1]
    (day,) = brands["series"]
    assert day == {
        "bucket": D1,
        "gained": {"brand": 2, "brand:wikidata": 1, "operator": 1, "operator:wikidata": 0},
        "lost": {"brand": 0, "brand:wikidata": 0, "operator": 0, "operator:wikidata": 0},
    }, "the new place's brand was counted, or the operator was merged into the brand"
    assert brands["n"] == 4 and [k["key"] for k in brands["keys"]] == ["brand", "brand:wikidata", "operator", "operator:wikidata"]
    social = _snap("channels")["changes"]["series"][0]
    assert social["gained"] == {"facebook": 1, "instagram": 0, "twitter": 1, "youtube": 0, "tiktok": 0, "linkedin": 0, "telegram": 0, "whatsapp": 0}
    assert sum(social["lost"].values()) == 0
    fresh = _snap("freshness")["changes"]
    assert fresh["fields"] == ["edited", "checked"]
    assert fresh["series"] == [{"bucket": D1, "edited": 3, "checked": 1}], "the empty check_date was counted as checked, or the new place as edited"
    channels = _snap("channels")["changes"]
    for block in (brands, channels, fresh):
        assert block["method"] and block["caveat"]
    assert channels["n"] == 2


def test_a_day_with_a_file_and_no_brand_row_is_a_measured_zero(cut, osm_lane_dir):
    # the fixture day changes websites, e-mails and phones and appears/disappears places, but touches no brand or operator tag
    _apply(osm_lane_dir, {101: DAY1})
    got = _snap("brands")["changes"]
    assert got["series"][0]["lost"] == dict.fromkeys(("brand", "brand:wikidata", "operator", "operator:wikidata"), 0), "a day with a file and no brand row is a measured zero"
    assert got["n"] == 0


def test_the_planets_prior_is_read_separately_by_month_with_the_same_rules_and_never_added(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: _BODY})
    before = {s_: _snap(s_)["changes"] for s_ in PF.SURFACES}
    _history([
        ("n", 6, 1, _dt(2019, 1, 5), "added", "brand", None, "Acme"),               # an object's FIRST version: not a change
        ("n", 6, 3, _dt(2020, 3, 10), "added", "brand", None, "Acme"),              # gained brand, 2020-03
        ("n", 6, 3, _dt(2020, 3, 10), "added", "contact:facebook", None, "f"),      # gained facebook, 2020-03 (same place: edited once)
        ("n", 5, 2, _dt(2021, 2, 1), "added", "check_date", None, "2021-02-01"),    # edited and checked, 2021-02
        ("n", 21, 3, _dt(2020, 4, 9), "created", None, None, None),                 # a created object's keys are the event's own
        ("n", 21, 3, _dt(2020, 4, 9), "added", "brand", None, "X"),
        ("n", 22, 2, None, "added", "brand", None, "Y"),                            # no timestamp: not placed in a month, not invented
    ])
    b, c, f = (_snap(s_)["prior"] for s_ in PF.SURFACES)
    assert b["available"] is True and b["bucket"] == "month" and [r["bucket"] for r in b["series"]] == ["2020-03"]
    assert b["series"][0]["gained"]["brand"] == 1 and b["n"] == 1
    assert c["series"][0]["gained"]["facebook"] == 1 and [r["bucket"] for r in c["series"]] == ["2020-03"]
    assert f["series"] == [{"bucket": "2020-03", "edited": 1, "checked": 0}, {"bucket": "2021-02", "edited": 1, "checked": 1}]
    assert b["caveat"] == f["caveat"] == PF.CAVEAT_PRIOR and "day without a change file" not in PF.CAVEAT_PRIOR
    after = {s_: _snap(s_)["changes"] for s_ in PF.SURFACES}
    assert after == before, "the prior's existence changed the window"


def test_another_countrys_rows_are_not_this_countrys(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: _BODY})
    before = _snap("freshness")["changes"]
    with store.lane_session("osm") as s:
        s.add(OsmTagChange(osm_type="n", osm_id=999, key="check_date", change="added", new_value="2025-01-01",
                           diff_timestamp=_dt(2025, 1, 11), object_version=1, country_alpha3="YYY"))
    assert _snap("freshness")["changes"] == before


def test_a_row_without_a_timestamp_does_not_make_the_country_unreadable(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: _BODY})
    with store.lane_session("osm") as s:
        s.add(OsmTagChange(osm_type="n", osm_id=77, key="brand", change="added", new_value="x", diff_timestamp=None, object_version=1, country_alpha3="ZZZ"))
    assert [r["bucket"] for r in _snap("brands")["changes"]["series"]] == [D1]


# --------------------------------------------------------------------------- #
#  Route and module hygiene                                                    #
# --------------------------------------------------------------------------- #


def test_the_route_answers_for_each_surface_and_refuses_a_bad_code_or_surface(cut, osm_lane_dir):
    from fastapi.testclient import TestClient

    from src.api.main import app

    _seed()
    with TestClient(app) as c:
        for surface in PF.SURFACES:
            r = c.get(f"/api/osm/countries/ZZ/profile/{surface}")
            assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["surface"] == surface
        assert c.get("/api/osm/countries/ZZ/profile/brands?limit=1").json()["snapshot"]["limit"] == 1
        assert c.get("/api/osm/countries/not-a-country/profile/brands").status_code == 400
        assert c.get("/api/osm/countries/ZZ/profile/nonsense").status_code == 400


def test_the_module_makes_no_request_and_imports_no_socket_library():
    tree = ast.parse((ROOT / "src/osm/profile.py").read_text("utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & {"requests", "httpx", "urllib", "socket", "http"}


def test_the_key_sets_are_the_ones_the_module_records():
    assert [n for n, _ in PF.BRAND_GROUPS] == ["brand", "brand:wikidata", "operator", "operator:wikidata"]
    assert PF.SOCIAL_SERVICES == ("facebook", "instagram", "twitter", "youtube", "tiktok", "linkedin", "telegram", "whatsapp")
    from src.osm.tags import SCALAR_KEYS

    assert {"brand", "brand:wikidata", "operator", "operator:wikidata", "check_date"} <= set(SCALAR_KEYS), "a key the profile reads is not an ingested column"
