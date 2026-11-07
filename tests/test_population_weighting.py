"""The weighting stated on a population-weighted figure, and the operator's dated population table (S06-04 S6).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1153 = a. The claims pinned here: a weighted figure names its weights' source, date and the members it
covers; a member with a value and no population is a STATED gap (the figure refuses, naming it, and no
unweighted mean is offered under the weighted label); the operator's table fills only what the stored
series lacks, never overrides a stored figure, and is refused whole when it is undated or has a bad row.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.database.models import Base, StatFigure
from src.database.session import get_db
from src.stats import aggregate, population


def _table(tmp_path, doc):
    p = tmp_path / "population_table.json"
    p.write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")
    return p


GOOD = {"source": "Test publisher 2024", "as_of": "2024-07-01", "rows": {"FR": 60.0, "LU": 0.5}}


# --------------------------------------------------------------------------- loader
def test_no_file_is_absent_not_an_error(tmp_path):
    t = population.load_population_table(tmp_path / "nope.json")
    assert t["status"] == "absent" and t["weights"] == {} and t["reason"]


def test_the_repo_ships_no_table():
    """The operator's drop-in: this repository must not make up a population vintage. Asked of git (is it
    TRACKED), not of the working tree, so an operator who placed the file locally still passes; the path is
    also ignored so a `git add .` cannot ship it by accident."""
    import subprocess

    root = population.DEFAULT_PATH.parents[1]
    try:
        tracked = subprocess.run(["git", "ls-files", "configs/population_table.json"], cwd=root,
                                 capture_output=True, text=True, check=True).stdout
        ignored = subprocess.run(["git", "check-ignore", "-q", "configs/population_table.json"], cwd=root).returncode
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    assert tracked.strip() == "" and ignored == 0


def test_a_good_table_loads_with_lowercase_codes_and_its_account(tmp_path):
    t = population.load_population_table(_table(tmp_path, GOOD))
    assert t["status"] == "ok" and t["weights"] == {"fr": 60.0, "lu": 0.5}
    assert t["source"] == "Test publisher 2024" and t["as_of"] == "2024-07-01"


@pytest.mark.parametrize(
    ("doc", "status"),
    [
        ("{not json", "malformed"),
        ("[1, 2]", "malformed"),
        ({"as_of": "2024-07-01", "rows": {"FR": 1}}, "undated"),
        ({"source": "  ", "as_of": "2024-07-01", "rows": {"FR": 1}}, "undated"),
        ({"source": "s", "rows": {"FR": 1}}, "undated"),
        ({"source": "s", "as_of": "last year", "rows": {"FR": 1}}, "undated"),
        ({"source": "s", "as_of": "2024-99-99", "rows": {"FR": 1}}, "undated"),
        ({"source": "s", "as_of": "2024-13", "rows": {"FR": 1}}, "undated"),
        ('{"source": "s", "as_of": "2024-07", "rows": {"FR": 1' + "0" * 400 + '}}', "malformed"),
        ({"source": "s", "as_of": "2024-07-01"}, "malformed"),
        ({"source": "s", "as_of": "2024-07-01", "rows": {}}, "malformed"),
        ({"source": "s", "as_of": "2024-07-01", "rows": {"FRA": 1}}, "malformed"),
        ({"source": "s", "as_of": "2024-07-01", "rows": {"FR": 0}}, "malformed"),
        ({"source": "s", "as_of": "2024-07-01", "rows": {"FR": -3}}, "malformed"),
        ({"source": "s", "as_of": "2024-07-01", "rows": {"FR": True}}, "malformed"),
        ({"source": "s", "as_of": "2024-07-01", "rows": {"FR": "68000000"}}, "malformed"),
        ('{"source": "s", "as_of": "2024-07", "rows": {"FR": NaN}}', "malformed"),
        ({"source": "s", "as_of": "2024-07-01", "rows": {"FR": 1, "fr": 2}}, "malformed"),
    ],
)
def test_a_table_that_cannot_state_itself_or_has_a_bad_row_is_refused_whole(tmp_path, doc, status):
    t = population.load_population_table(_table(tmp_path, doc))
    assert t["status"] == status and t["weights"] == {} and t["source"] is None


def test_an_unreadable_path_is_reported_by_class_only(tmp_path):
    t = population.load_population_table(tmp_path)  # a directory
    assert t["status"] == "unreadable" and "IsADirectoryError" in t["reason"]


# --------------------------------------------------------------------------- fill_gaps
def test_the_table_fills_only_holes_and_a_stored_figure_wins(tmp_path):
    table = population.load_population_table(_table(tmp_path, GOOD))
    out, taken = population.fill_gaps({"fr": 70.0, "lu": None, "de": None}, ["fr", "lu", "de"], table)
    assert out == {"fr": 70.0, "lu": 0.5, "de": None}  # FR stays the stored 70, not the table's 60
    assert taken == ["lu"]  # DE is in neither: a stated gap, never a guess


def test_a_table_that_did_not_load_fills_nothing(tmp_path):
    table = population.load_population_table(tmp_path / "nope.json")
    out, taken = population.fill_gaps({"fr": None}, ["fr"], table)
    assert out == {"fr": None} and taken == []


# --------------------------------------------------------------------------- the engine
_IND = {"id": "X", "label": "X per capita", "unit": "%"}
_AGG = {"extensive": False, "denominator": "population"}


def _members():
    return [aggregate.Member("fr", 10.0), aggregate.Member("de", 20.0), aggregate.Member("lu", 30.0)]


def test_a_weighted_figure_states_its_weighting():
    src = {"population": {"source": "stored series SP.POP.TOTL", "as_of": "2023", "from_table": ["lu"],
                          "table": {"source": "T", "as_of": "2024-07-01"}}}
    out = aggregate.aggregate_indicator(
        indicator=_IND, aggregation=_AGG, members=_members(),
        weights={"population": {"fr": 60.0, "de": 80.0, "lu": 0.5}}, weight_source=src)
    r = out["strategies"]["population_weighted"]
    assert r["value"] == pytest.approx((10 * 60 + 20 * 80 + 30 * 0.5) / 140.5)
    assert r["weighting"] == {
        "weight": "population", "stated": True, "source": "stored series SP.POP.TOTL", "as_of": "2023",
        "members_total": 3, "members_covered": 3, "members_without_weight": [], "from_table": ["lu"],
        "table": {"source": "T", "as_of": "2024-07-01"},
    }
    assert "weighting" not in out["strategies"]["mean"]  # only weighted figures carry one


def test_a_weighting_nobody_described_says_so_rather_than_inventing_a_source():
    out = aggregate.aggregate_indicator(
        indicator=_IND, aggregation=_AGG, members=_members(),
        weights={"population": {"fr": 60.0, "de": 80.0, "lu": 0.5}})
    w = out["strategies"]["population_weighted"]["weighting"]
    assert w["stated"] is False and w["source"] is None and w["as_of"] is None and w["table"] is None


def test_a_weight_from_the_operators_table_makes_the_figure_approximate_never_exact():
    """A table figure is dated on its own, not at the indicator's period: it cannot rebuild the real numerator."""
    src = {"population": {"source": "stored series SP.POP.TOTL", "as_of": "2023", "from_table": ["lu"],
                          "table": {"source": "T", "as_of": "2015-01"}}}
    out = aggregate.aggregate_indicator(
        indicator=_IND, aggregation=_AGG, members=_members(),
        weights={"population": {"fr": 60.0, "de": 80.0, "lu": 0.5}}, weight_source=src)  # a COMPLETE group
    assert out["coverage"]["complete"] is True
    r = out["strategies"]["population_weighted"]
    assert r["basis"] == "approximate" and r["method_code"] == "weighted_table" and "true figure" not in r["method"]
    assert out["default_strategy"] != "population_weighted"
    # ...and with no table weight in play the same group IS exact (the control that makes the assertion mean something).
    exact = aggregate.aggregate_indicator(
        indicator=_IND, aggregation=_AGG, members=_members(),
        weights={"population": {"fr": 60.0, "de": 80.0, "lu": 0.5}},
        weight_source={"population": {"source": "stored series SP.POP.TOTL", "as_of": "2023", "from_table": []}})
    assert exact["strategies"]["population_weighted"]["basis"] == "exact"


def test_from_table_names_only_members_whose_weight_entered_the_figure():
    members = [aggregate.Member("fr", 10.0), aggregate.Member("de", None), aggregate.Member("lu", 30.0)]
    src = {"population": {"source": "s", "as_of": "2023", "from_table": ["de", "lu"],
                          "table": {"source": "T", "as_of": "2015-01"}}}
    out = aggregate.aggregate_indicator(
        indicator=_IND, aggregation=_AGG, members=members, allow_incomplete=True,
        weights={"population": {"fr": 60.0, "de": 80.0, "lu": 0.5}}, weight_source=src)
    w = out["strategies"]["population_weighted"]["weighting"]
    assert w["from_table"] == ["lu"]  # DE did not report, so its table weight touched nothing


def test_NEGATIVE_a_member_with_no_population_is_a_named_gap_and_no_unweighted_mean_stands_in():
    src = {"population": {"source": "stored series SP.POP.TOTL", "as_of": "2023", "from_table": []}}
    out = aggregate.aggregate_indicator(
        indicator=_IND, aggregation=_AGG, members=_members(),
        weights={"population": {"fr": 60.0, "de": 80.0, "lu": None}}, weight_source=src)
    r = out["strategies"]["population_weighted"]
    assert "value" not in r and r["refused_code"] == "missing_weight" and r["missing_weight"] == ["lu"]
    assert r["weighting"]["members_without_weight"] == ["lu"] and r["weighting"]["members_covered"] == 2
    assert out["strategies"]["mean"]["value"] == pytest.approx(20.0)  # the plain mean stays labelled as the plain mean
    assert out["default_strategy"] != "population_weighted"


# --------------------------------------------------------------------------- the route
def _fig(area, series, value):
    return StatFigure(agency="worldbank", series_id=series, ref_area=area, time_period="2023",
                      value=value, unit="", extracted_at="2026-08-01")


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, future=True)()
    # LUX has a GDP-per-capita figure and NO stored population.
    s.add_all([
        _fig("FRA", "SP.POP.TOTL", 68.0), _fig("DEU", "SP.POP.TOTL", 84.0),
        _fig("FRA", "NY.GDP.PCAP.CD", 44_000.0), _fig("DEU", "NY.GDP.PCAP.CD", 52_000.0),
        _fig("LUX", "NY.GDP.PCAP.CD", 128_000.0),
    ])
    s.commit()
    app.dependency_overrides[get_db] = lambda: s
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)
        s.close()


def _pop_weighted(client):
    r = client.get("/api/governments/group-aggregate",
                   params={"group": "europe", "indicator": "NY.GDP.PCAP.CD", "year": "2023", "allow_incomplete": True})
    assert r.status_code == 200, r.text
    return r.json()["aggregate"]["strategies"]["population_weighted"]


def test_route_without_a_table_names_the_member_the_stored_series_lacks(client, tmp_path, monkeypatch):
    monkeypatch.setattr(population, "DEFAULT_PATH", tmp_path / "absent.json")
    r = _pop_weighted(client)
    assert "value" not in r and r["refused_code"] == "missing_weight" and r["missing_weight"] == ["lu"]
    assert r["weighting"]["source"] == "stored series SP.POP.TOTL" and r["weighting"]["from_table"] == []


def test_route_with_a_table_fills_the_gap_and_says_where_it_came_from(client, tmp_path, monkeypatch):
    # FR's table figure (1.0) must NOT beat the stored 68.0; LU is filled from the table.
    monkeypatch.setattr(population, "DEFAULT_PATH", _table(tmp_path, {**GOOD, "rows": {"FR": 1.0, "LU": 0.66}}))
    r = _pop_weighted(client)
    assert r["value"] == pytest.approx((44_000 * 68.0 + 52_000 * 84.0 + 128_000 * 0.66) / (68.0 + 84.0 + 0.66))
    w = r["weighting"]
    assert w["from_table"] == ["lu"] and w["table"] == {"source": "Test publisher 2024", "as_of": "2024-07-01"}
    assert w["as_of"] == "2023" and w["members_covered"] == 3 and w["members_without_weight"] == []
    assert r["basis"] == "approximate"  # the group is incomplete (most of Europe did not report), and says so


def test_route_with_an_undated_table_ignores_it_and_refuses(client, tmp_path, monkeypatch):
    monkeypatch.setattr(population, "DEFAULT_PATH", _table(tmp_path, {"source": "s", "rows": {"LU": 0.66}}))
    r = _pop_weighted(client)
    assert "value" not in r and r["missing_weight"] == ["lu"]


def test_route_with_nothing_stored_names_the_table_as_the_only_source(client, tmp_path, monkeypatch):
    # No stored population for ANY member of this group: the line must not claim the stored series.
    monkeypatch.setattr(population, "DEFAULT_PATH", _table(tmp_path, {**GOOD, "rows": {"FR": 60.0, "DE": 80.0, "LU": 0.5}}))
    from src.stats import indicators as ind
    monkeypatch.setitem(ind.WEIGHT_SERIES, "population", "SP.POP.NOPE")  # a series nothing is stored under
    r = _pop_weighted(client)
    w = r["weighting"]
    assert w["source"] == "operator table: Test publisher 2024" and w["as_of"] == "2024-07-01"
    assert "stored series" not in w["source"] and r["basis"] == "approximate"
    # DE, FR and LU reported; only they appear, none of Europe's non-reporting members.
    assert w["from_table"] == ["de", "fr", "lu"]


def test_route_says_so_when_it_ignores_a_table_and_why(client, tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(population, "DEFAULT_PATH", _table(tmp_path, {**GOOD, "rows": {"XXX": 1}}))
    with caplog.at_level("WARNING"):
        r = client.get("/api/governments/group-aggregate",
                       params={"group": "europe", "indicator": "NY.GDP.PCAP.CD", "year": "2023", "allow_incomplete": True})
    note = r.json()["aggregate"]["population_table"]
    assert note["status"] == "malformed" and "XXX" in note["reason"]
    assert any("population table ignored" in m for m in caplog.messages)


def test_route_survives_an_oversized_number_in_the_table(client, tmp_path, monkeypatch):
    p = tmp_path / "population_table.json"
    p.write_text('{"source": "s", "as_of": "2024-07", "rows": {"LU": 1' + "0" * 400 + "}}", encoding="utf-8")
    monkeypatch.setattr(population, "DEFAULT_PATH", p)
    r = client.get("/api/governments/group-aggregate",
                   params={"group": "europe", "indicator": "NY.GDP.PCAP.CD", "year": "2023", "allow_incomplete": True})
    assert r.status_code == 200 and r.json()["aggregate"]["population_table"]["status"] == "malformed"
