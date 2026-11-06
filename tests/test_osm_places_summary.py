"""The stored summary of a country's current places (v0.6.0 R439): a cache of one function of ``osm_objects``, never a second source of truth.

The parity test compares the stored path with the computed path on the SAME places, on every reader (the three profile surfaces and the geography
view); every fallback state has a test that fails when the fallback is removed (a stored summary served when it should not be would show the poisoned counts).
"""

from __future__ import annotations

import ast
import json
import pathlib
import time
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from src.osm import geography as GE
from src.osm import ingest
from src.osm import places_summary as PS
from src.osm import profile as PF
from src.osm.lane_models import (
    OsmCountry,
    OsmPlacesCount,
    OsmPlacesDay,
    OsmPlacesSummary,
    OsmPlacesValue,
)
from src.versioned import store
from tests import _osm_lane_helpers
from tests.test_osm_apply import DAY1, _extract
from tests.test_osm_profile import T, _dt, _seed
from tests.test_osm_trends import _apply

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def cut(osm_lane_dir):
    path = _extract(osm_lane_dir)
    assert ingest.ingest_country(path, "ZZ", reader="python").status == "complete"
    return path


def _more_places(n_brands: int = 12) -> None:
    """Places that make every reader's answer richer than the fixture's five: many distinct brands (more than a small limit), every social service,
    a spread of edit days and check dates, a place with no timestamp, a brand carried only as a wikidata id, and another country's place."""
    with store.lane_session("osm") as s:
        rows = []
        for i in range(n_brands):
            rows.append({
                "osm_type": "n", "osm_id": 2000 + i, "country_alpha3": "ZZZ", "kind": "poi", "notable": False,
                "t_brand": f"Brand{i % (7 if n_brands <= 12 else n_brands)}", "t_brand_wikidata": f"Q{i}",
                "t_check_date": f"20{10 + i}-0{1 + i % 9}", "timestamp": _dt(2015 + i % 10, 1 + i % 12, 1 + i % 27),
                "contact": json.dumps(dict.fromkeys(PF.SOCIAL_SERVICES[: i % 9], "x")), "t_website": "https://x.invalid" if i % 2 else None,
                "t_phone": "+0" if i % 3 == 0 else None,
            })
        blank = {"contact": None, "t_brand": None, "t_brand_wikidata": None, "t_website": None, "t_phone": None, "t_check_date": None, "timestamp": None}
        rows.append({**blank, "osm_type": "n", "osm_id": 3000, "country_alpha3": "ZZZ", "kind": "poi", "notable": False, "t_brand_wikidata": "Q99"})
        rows.append({**blank, "osm_type": "n", "osm_id": 3001, "country_alpha3": "YYY", "kind": "poi", "notable": False, "t_brand": "Elsewhere", "timestamp": _dt(2024, 6, 1)})
        s.execute(T.insert(), rows)
    _osm_lane_helpers.forget_places_summary()


def _surfaces(**kw):
    """Every reader's snapshot answer for ZZZ, and the geography area, the summary's own fields set aside."""
    out = {}
    for name in PF.SURFACES:
        got = PF.profile("ZZZ", name, **kw)
        assert got["status"] == "ok", got
        out[name] = {k: v for k, v in got["snapshot"].items() if k not in ("source", "summary")}
        out[name + "_source"] = got["snapshot"]["source"]
    (area,) = [a for a in GE.countries_view()["areas"] if a["alpha3"] == "ZZZ"]
    out["geography"] = {k: v for k, v in area.items() if k != "places_summary"}
    out["geography_source"] = area["places_summary"]["source"]
    return out


def _bare(d):
    return {k: v for k, v in d.items() if not k.endswith("_source")}


def test_the_stored_summary_gives_the_same_answer_as_the_places_on_every_reader_and_every_limit(cut, osm_lane_dir):
    _seed()
    _more_places()
    for limit in (PF.DEFAULT_LIMIT, 1, 3, 5):
        before = _surfaces(limit=limit)
        assert {v for k, v in before.items() if k.endswith("_source")} == {"computed"}
        assert before["brands"]["rankings"][0]["total"] >= 7 and before["brands"]["n"] > 5, "the fixture is too poor to prove anything"
        res = PS.build_summary("ZZZ")
        assert res["status"] == "built" and res["rows"] > 0
        after = _surfaces(limit=limit)
        assert {v for k, v in after.items() if k.endswith("_source")} == {"summary"}, "the stored path was not taken"
        for key in _bare(before):
            assert _bare(after)[key] == _bare(before)[key], f"limit {limit}: {key} reads differently from its summary"
        _osm_lane_helpers.forget_places_summary()
    # the geography view's other measures are unchanged by the summary's existence
    assert before["geography"]["values"]["places"] == before["brands"]["n"]


def test_every_distinct_value_is_stored_and_the_reader_applies_the_limit(cut, osm_lane_dir):
    _seed()
    _more_places(n_brands=30)
    full = PF.profile("ZZZ", "brands", limit=PF.MAX_LIMIT)["snapshot"]["rankings"][0]
    assert full["total"] > 20 and full["shown"] == full["total"]
    PS.build_summary("ZZZ")
    with store.lane_session("osm") as s:
        stored = s.query(OsmPlacesValue).filter_by(alpha3="ZZZ", part="brands", key="brand").count()
    assert stored == full["total"], "the summary kept fewer values than exist"
    small = PF.profile("ZZZ", "brands", limit=2)["snapshot"]
    assert small["source"] == "summary" and small["rankings"][0]["shown"] == 2 and small["rankings"][0]["total"] == full["total"], "the limit is the reader's, the total is real"


def test_the_last_edit_is_stored_by_day_so_the_ages_follow_the_reference_date(cut, osm_lane_dir):
    _seed()
    _more_places()
    PS.build_summary("ZZZ")
    with store.lane_session("osm") as s:
        days = s.query(OsmPlacesDay).filter_by(alpha3="ZZZ", part="freshness").count()
        none = s.query(OsmPlacesCount).filter_by(alpha3="ZZZ", part="freshness", name="n").one().n
    assert days > 3 and none == PF.profile("ZZZ", "freshness")["snapshot"]["n"]
    # a daily apply moves the reference date: the summary is stale and rebuilt, and the ages differ only by what the reference date decides
    ref = datetime(2025, 1, 10, tzinfo=UTC)
    stored = PF._age_counts([[d, n] for d, n in _days_of("freshness")], ref.date())
    assert sum(stored[0].values()) == stored[1]


def _days_of(part):
    with store.lane_session("osm") as s:
        return [(d, n) for d, n in s.execute(sa.select(OsmPlacesDay.day, OsmPlacesDay.n).where(OsmPlacesDay.alpha3 == "ZZZ", OsmPlacesDay.part == part))]


def test_another_countrys_places_are_not_in_this_countrys_summary(cut, osm_lane_dir):
    _seed()
    _more_places()
    PS.build_summary("ZZZ")
    with store.lane_session("osm") as s:
        assert s.query(OsmPlacesSummary).filter_by(alpha3="YYY").count() == 0
        assert s.query(OsmPlacesValue).filter_by(alpha3="ZZZ", key="brand", value="Elsewhere").count() == 0
        assert s.query(OsmPlacesSummary).filter_by(alpha3="ZZZ").count() == 1


def _poison():
    """Counts that no places produce: a summary served when it should not be would show them."""
    with store.lane_session("osm") as s:
        s.query(OsmPlacesCount).filter_by(alpha3="ZZZ", part="brands", name="n").update({"n": 777})


def test_a_reader_never_writes_a_summary(cut, osm_lane_dir):
    _seed()
    _surfaces()
    with store.lane_session("osm") as s:
        assert s.query(OsmPlacesSummary).count() == 0 and s.query(OsmPlacesCount).count() == 0, "a GET built the summary"


def test_a_summary_of_an_older_position_is_not_served_and_the_answer_says_computed(cut, osm_lane_dir):
    _seed()
    expected = PF.profile("ZZZ", "brands")["snapshot"]["n"]
    PS.build_summary("ZZZ")
    _poison()
    assert PF.profile("ZZZ", "brands")["snapshot"]["n"] == 777, "the poison is not visible: the stored path is not what is read"
    for field, value in (("diff_sequence", 12345), ("finished_at", datetime(2030, 1, 1, tzinfo=UTC))):
        with store.lane_session("osm") as s:
            setattr(s.query(OsmCountry).filter_by(alpha3="ZZZ").one(), field, value)
        got = PF.profile("ZZZ", "brands")["snapshot"]
        assert got["source"] == "computed" and got["summary"]["state"] == "stale-cut" and got["n"] == expected, f"{field} moved and the old summary was served"
        assert PS.summary_state("ZZZ")["state"] == "stale-cut"
        with store.lane_session("osm") as s:   # put the position back for the next field
            row = s.query(OsmCountry).filter_by(alpha3="ZZZ").one()
            row.diff_sequence = None
            row.finished_at = s.query(OsmPlacesSummary).one().cut_finished_at


def test_a_summary_written_by_another_rule_is_not_served(cut, osm_lane_dir):
    _seed()
    expected = PF.profile("ZZZ", "brands")["snapshot"]["n"]
    PS.build_summary("ZZZ")
    _poison()
    with store.lane_session("osm") as s:
        s.query(OsmPlacesSummary).one().rule_version = "0123456789ab"
    got = PF.profile("ZZZ", "brands")["snapshot"]
    assert got["source"] == "computed" and got["summary"]["state"] == "stale-rule" and got["n"] == expected


def test_the_rule_version_follows_the_key_sets(monkeypatch):
    base = PS.rule_version()
    assert PS.rule_version() == base
    monkeypatch.setattr(PF, "BRAND_GROUPS", (*PF.BRAND_GROUPS, ("brand:wikipedia", ("brand:wikipedia",))))
    assert PS.rule_version() != base, "a new key group must make every stored summary stale"
    monkeypatch.undo()
    monkeypatch.setattr(PS, "RULE_REVISION", PS.RULE_REVISION + 1)
    assert PS.rule_version() != base


def test_a_lane_without_the_summary_tables_computes_says_so_and_a_build_adds_them(cut, osm_lane_dir):
    """A lane cut by an older build has no tables for the summary: the readers compute and say so, and the build (a writer) adds the tables."""
    _seed()
    expected = _bare(_surfaces())
    with store.lane_session("osm") as s:
        for table in ("osm_places_counts", "osm_places_values", "osm_places_days", "osm_places_summaries"):
            s.execute(sa.text(f"DROP TABLE {table}"))
    got = PF.profile("ZZZ", "channels")["snapshot"]
    assert got["source"] == "computed" and got["summary"]["state"] == "no-summary-table"
    assert PS.summary_state("ZZZ")["state"] == "no-summary-table"
    assert _bare(_surfaces()) == expected
    assert PS.build_summary("ZZZ")["status"] == "built"
    assert _bare(_surfaces()) == expected and PF.profile("ZZZ", "channels")["snapshot"]["source"] == "summary"
    assert PS.summary_state("ZZZ")["state"] == "current"


def test_a_country_that_was_not_cut_has_no_summary(cut, osm_lane_dir):
    assert PS.build_summary("QQQ") == {"status": "not-cut"}
    assert PS.summary_state("QQQ")["state"] == "not-cut"
    assert PS.build_summary("ZZZ")["status"] == "built"


def test_a_rebuild_replaces_the_rows_and_a_current_summary_is_skipped(cut, osm_lane_dir):
    _seed()
    assert PS.build_summary("ZZZ", only_if_missing=True)["status"] == "built"
    assert PS.build_summary("ZZZ", only_if_missing=True) == {"status": "current"}

    def rows():
        with store.lane_session("osm") as s:
            return [s.query(m).count() for m in (OsmPlacesCount, OsmPlacesValue, OsmPlacesDay, OsmPlacesSummary)]

    before = rows()
    assert PS.build_summary("ZZZ")["status"] == "built"
    assert rows() == before, "a rebuild must replace the rows, not add to them"
    assert before[3] == 1, "one header per country"


def test_an_apply_during_the_pass_leaves_nothing_that_could_pass_for_current(cut, osm_lane_dir, monkeypatch):
    _seed()
    real = PS.compute_part

    def apply_meanwhile(*a, **k):
        with store.lane_session("osm") as s:
            s.query(OsmCountry).filter_by(alpha3="ZZZ").one().diff_sequence = 4242
        return real(*a, **k)

    monkeypatch.setattr(PS, "compute_part", apply_meanwhile)
    assert PS.build_summary("ZZZ") == {"status": "superseded"}
    with store.lane_session("osm") as s:
        assert s.query(OsmPlacesSummary).count() == 0 and s.query(OsmPlacesCount).count() == 0


def test_a_daily_apply_rebuilds_the_summary_and_a_failed_rebuild_never_fails_the_apply(cut, osm_lane_dir, monkeypatch, caplog):
    PS.build_summary("ZZZ")
    with store.lane_session("osm") as s:
        before = s.query(OsmPlacesSummary).one().diff_sequence
    _apply(osm_lane_dir, {101: DAY1})
    assert PS.summary_state("ZZZ")["state"] == "current", "the apply left the stored counts stale"
    with store.lane_session("osm") as s:
        assert s.query(OsmPlacesSummary).one().diff_sequence != before
    # the stored answer is the computed one on the applied places
    stored = _bare(_surfaces())
    _osm_lane_helpers.forget_places_summary()
    assert _bare(_surfaces()) == stored

    def boom(*a, **k):
        raise RuntimeError("disk full /home/someone/secret")

    monkeypatch.setattr(PS, "build_summary", boom)
    with caplog.at_level("WARNING"):
        rep = _apply(osm_lane_dir, {102: DAY1})   # applies: a failed summary does not make the run fail
    assert rep.outcome == "applied"
    assert "places summary could not be built" in caplog.text, "the failure is logged, not swallowed"
    assert not PS.is_building("ZZZ")


def test_the_cut_builds_the_summary_when_it_finishes(cut, osm_lane_dir):
    assert PS.summary_state("ZZZ")["state"] == "current"
    assert PF.profile("ZZZ", "brands")["snapshot"]["source"] == "summary"
    with store.lane_session("osm") as s:
        assert s.query(OsmPlacesSummary).one().cut_finished_at is not None


def test_a_cut_again_makes_the_old_summary_stale_and_builds_a_new_one(cut, osm_lane_dir):
    with store.lane_session("osm") as s:
        first = s.query(OsmPlacesSummary).one().cut_finished_at
    assert ingest.ingest_country(cut, "ZZ", reader="python").status == "complete"
    with store.lane_session("osm") as s:
        second = s.query(OsmPlacesSummary).one().cut_finished_at
        assert s.query(OsmPlacesSummary).count() == 1
    assert second != first and PS.summary_state("ZZZ")["state"] == "current"


def test_the_route_builds_for_an_existing_country_on_a_thread_and_a_get_does_not(cut, osm_lane_dir):
    from fastapi.testclient import TestClient

    from src.api.main import app

    _seed()
    with TestClient(app) as c:
        got = c.get("/api/osm/countries/ZZ/profile/brands").json()["snapshot"]
        assert got["source"] == "computed" and got["summary"]["state"] == "not-built"
        assert c.get("/api/osm/countries/ZZ/places-summary").json()["state"] == "not-built"
        assert c.post("/api/osm/countries/not-a-country/places-summary").status_code == 400
        first = c.post("/api/osm/countries/ZZ/places-summary").json()
        assert first["status"] == "building" and first["started"] in (True, False)
        for _ in range(100):
            if not PS.is_building("ZZZ"):
                break
            time.sleep(0.1)
        assert not PS.is_building("ZZZ")
        got = c.get("/api/osm/countries/ZZ/profile/brands").json()["snapshot"]
        assert got["source"] == "summary" and got["summary"]["state"] == "current"
        assert c.get("/api/osm/countries/ZZ/places-summary").json()["state"] == "current"


def test_the_module_makes_no_request_and_imports_no_socket_library():
    tree = ast.parse((ROOT / "src" / "osm" / "places_summary.py").read_text(encoding="utf-8"))
    names = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)} | {
        (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    }
    assert not names & {"requests", "httpx", "socket", "urllib", "http", "aiohttp"}


def test_only_the_cut_and_the_apply_write_osm_objects():
    """The summary's key (the country row's ``finished_at`` and ``diff_sequence``) is sound only while nothing else writes the places."""
    import re

    # a write is an insert/update/delete of the table object, spelled directly (the cut) or through the apply's context (``ctx.t`` / ``self.t``), or raw SQL
    write = re.compile(r"\b(insert|update|delete)\((osm_objects_table|ctx\.t|self\.t)\b|osm_objects_table\.(insert|update|delete)\(|\b(UPDATE|INSERT INTO|DELETE FROM) osm_objects\b")
    writers = sorted(p.name for p in (ROOT / "src").rglob("*.py") if p.name != "lane_models.py" and write.search(p.read_text(encoding="utf-8")))
    assert writers == ["apply.py", "ingest.py"], f"another module writes osm_objects, so a stored summary can go stale unseen: {writers}"


def test_the_page_asks_for_a_build_once_for_each_part_in_node():
    import subprocess

    proc = subprocess.run(["node", str(ROOT / "tests" / "osm_prior_summary_node_test.js")], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout
