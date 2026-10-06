"""The place gazetteer's build (0.5 row C, S05-03 S4): OSM place=* + Wikidata -> places_gazetteer.yml.

Everything here is fixture-only. Row D's synthetic extract is ingested for real; a few more
``place`` rows are written into its ``osm.db`` (the extract has one village and no QID), and the
Wikidata side is a recorded-shape ``wbgetentities`` answer. No test opens a socket.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
import yaml

from scripts import build_place_gazetteer as CLI
from src.catalog import cities
from src.entities import gazetteer_build as G
from src.osm import ingest
from tests import _osm_lane_helpers
from tests._osm_lane_helpers import FIXTURE

osm_lane_dir = _osm_lane_helpers.osm_lane_dir

ROOT = Path(__file__).resolve().parents[1]
WD_FIXTURE = ROOT / "tests" / "fixtures" / "wikidata" / "place_items.json"
BUILT = "2026-10-06"


def _seed(extra: bool = True) -> None:
    """Row D's synthetic country plus the place rows the join clauses need."""
    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    if not extra:
        return
    from src.osm.lane_models import OsmObject
    from src.versioned.store import lane_session

    rows = [
        # (id, place, name, names, lat, lon, wikidata, population)
        (9001, "city", "Testburg", {"fr": "Testbourg"}, 0.11, 0.12, "Q1000001", "12 345"),
        (9002, "town", "Dubville", {}, 0.12, 0.13, "Q1000002;Q1000003", "~5k"),
        (9003, "village", None, {}, 0.13, 0.14, "Q1000003", None),
        (9004, "hamlet", "Missingham", {}, 0.14, 0.15, "Q1000004", "80"),
        (9005, "town", "Redirectown", {}, 0.16, 0.16, "Q1000005", None),
        (9006, "suburb", "Farpoint", {}, 0.15, 0.11, "Q1000007", "4,000"),
        (9007, "city", "Paris", {}, 0.17, 0.17, None, None),
        (9008, "locality", None, {}, 0.18, 0.18, None, None),
    ]
    with lane_session("osm") as s:
        for oid, place, name, names, lat, lon, wd, pop in rows:
            s.add(
                OsmObject(
                    osm_type="n", osm_id=oid, country_alpha3="ZZZ", kind="place", notable=True,
                    primary_key="place", primary_value=place, lat=lat, lon=lon, t_place=place, t_name=name,
                    names=json.dumps(names) if names else None, t_wikidata=wd, t_population=pop,
                )
            )
        # A relation tagged place=*: no point of its own, a gap and never a (0, 0).
        s.add(OsmObject(osm_type="r", osm_id=9100, country_alpha3="ZZZ", kind="place", notable=True,
                        primary_key="place", primary_value="island", t_place="island", t_name="Gapland"))


def _run(tmp_path: Path, *extra: str) -> tuple[int, dict, Path]:
    out = tmp_path / "places.yml"
    argv = ["--country", "ZZ", "--out", str(out), "--built-date", BUILT, *extra]
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = CLI.main(argv)
    text = buf.getvalue()
    try:
        data = json.loads(text)
    except ValueError:
        data = {"stdout": text}
    return rc, data, out


def _by_osm(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text("utf-8"))
    return {c["osm"]: c for c in doc["cities"]}


# --------------------------------------------------------------------------- #
#  reading osm.db
# --------------------------------------------------------------------------- #


def test_the_read_counts_what_it_cannot_place_and_refuses_what_is_not_complete(osm_lane_dir):
    _seed()
    country, places, counts = G.read_places("ZZZ")
    assert country["alpha2"] == "ZZ" and counts["no_point"] == 1
    assert counts["with_wikidata_tag"] == 6 and counts["bad_wikidata_tag"] == 1
    assert all(p.osm != "relation/9100" for p in places), "a relation with no point is counted, never a (0, 0)"
    with pytest.raises(G.GazetteerBuildError, match="has not been ingested"):
        G.read_places("FRA")
    from sqlalchemy import text

    from src.versioned.store import lane_session

    with lane_session("osm") as s:
        s.execute(text("UPDATE osm_countries SET status = 'failed'"))
    with pytest.raises(G.GazetteerBuildError, match="not complete"):
        G.read_places("ZZZ")


def test_no_lane_is_a_named_refusal_not_a_crash(osm_lane_dir):
    with pytest.raises(G.GazetteerBuildError, match="no osm.db"):
        G.read_places("ZZZ")
    rc, data, _ = _run(osm_lane_dir, "--no-wikidata")
    assert rc == 2 and "no osm.db" in data["stdout"]


@pytest.mark.parametrize(
    ("raw", "want"),
    [("12 345", 12345), ("12,345", 12345), ("1.234.567", 1234567), ("812", 812), ("~5k", None),
     ("", None), (None, None), ("0", None), ("12 34", None), ("1e6", None)],
)
def test_osm_population_reads_only_what_is_plainly_a_number(raw, want):
    assert G.parse_osm_population(raw) == want


@pytest.mark.parametrize(("raw", "want"), [("Q42", "Q42"), (" Q42 ", "Q42"), ("Q1;Q2", None), ("q42", None),
                                           ("Q0", None), ("42", None), (None, None)])
def test_a_wikidata_tag_is_a_single_qid_exactly_or_nothing(raw, want):
    assert G.clean_wikidata_tag(raw) == want


# --------------------------------------------------------------------------- #
#  population: preferred rank, else the latest point in time
# --------------------------------------------------------------------------- #


def _claim(n, rank="normal", when=None, prec=11):
    c = {"mainsnak": {"datavalue": {"value": {"amount": f"+{n}"}}}, "rank": rank}
    if when:
        c["qualifiers"] = {"P585": [{"datavalue": {"value": {"time": when, "precision": prec}}}]}
    return c


def test_population_takes_the_preferred_claim_even_when_a_normal_one_is_newer():
    got = G.pick_population([_claim(1, when="+2011-00-00T00:00:00Z", prec=9),
                             _claim(2, "preferred", "+2015-00-00T00:00:00Z", 9),
                             _claim(3, when="+2021-01-01T00:00:00Z")])
    assert got == {"value": 2, "date": "2015", "rank": "preferred"}


def test_without_a_preferred_claim_the_latest_point_in_time_wins_and_deprecated_never_does():
    got = G.pick_population([_claim(500, when="+2010-00-00T00:00:00Z", prec=9), _claim(900, when="+2020-06-30T00:00:00Z"),
                             _claim(9999, "deprecated", "+2024-00-00T00:00:00Z", 9)])
    assert got == {"value": 900, "date": "2020-06-30", "rank": "normal"}


def test_an_undated_claim_loses_to_a_dated_one_and_a_tie_keeps_the_first():
    assert G.pick_population([_claim(7), _claim(8, when="+1999-01-01T00:00:00Z")])["value"] == 8
    assert G.pick_population([_claim(7), _claim(8)])["value"] == 7


@pytest.mark.parametrize("claims", [None, [], [{"rank": "deprecated"}], [_claim(0)], [_claim("x")], "no"])
def test_no_usable_population_is_none(claims):
    assert G.pick_population(claims) is None


# --------------------------------------------------------------------------- #
#  the join, end to end through the CLI
# --------------------------------------------------------------------------- #


def test_the_join_end_to_end_through_the_loader(osm_lane_dir):
    _seed()
    rc, data, out = _run(osm_lane_dir, "--wikidata-fixture", str(WD_FIXTURE))
    assert rc == 0, data
    by = _by_osm(out)

    t = by["node/9001"]
    assert t["qid"] == "Q1000001" and t["source"] == "osm+wikidata"
    # Preferred-rank P1082 is the value; OSM's own number stays beside it, both named.
    assert (t["population"], t["population_source"], t["population_date"], t["population_rank"]) == (
        12000, "wikidata:P1082", "2015", "preferred")
    assert t["population_osm"] == 12345
    # OSM's name:fr beats Wikidata's label; a language only Wikidata has is taken, its source named.
    assert t["names"]["fr"] == "Testbourg" and t["names_source"]["fr"] == "osm"
    assert t["names"]["de"] == "Testburg" and t["names_source"]["de"] == "wikidata"
    assert t["names"]["ar"] == "تستبورغ"

    # The loader reads it as THE shape it already understands, source and vintage on the entry.
    loaded = {c.osm: c for c in cities.load_cities(out)}
    c = loaded["node/9001"]
    assert (c.qid, c.kind, c.country, c.population, c.source) == ("Q1000001", "city", "zz", 12000, "osm+wikidata")
    assert c.names["fr"] == "Testbourg"


def test_a_place_with_no_single_qid_never_gets_one(osm_lane_dir):
    _seed()
    _rc, _d, out = _run(osm_lane_dir, "--wikidata-fixture", str(WD_FIXTURE))
    by = _by_osm(out)
    bad = by["node/9002"]  # "Q1000002;Q1000003": two ids, so no id
    assert "qid" not in bad and bad["source"] == "osm"
    assert "population" not in bad, "OSM's '~5k' is not a number and Wikidata was not asked"
    assert "qid" not in by["node/9007"] and by["node/9007"]["name"] == "Paris"


def test_a_qid_wikidata_does_not_have_is_kept_as_osm_wrote_it_and_flagged(osm_lane_dir):
    _seed()
    _rc, data, out = _run(osm_lane_dir, "--wikidata-fixture", str(WD_FIXTURE))
    e = _by_osm(out)["node/9004"]
    assert e["qid"] == "Q1000004" and e["qid_status"] == "missing-on-wikidata"
    assert e["source"] == "osm" and e["population"] == 80 and e["population_source"] == "osm"
    assert data["build"][0]["qid_missing_on_wikidata"] == 1


def test_a_redirected_qid_keeps_the_asked_id_and_names_where_it_went(osm_lane_dir):
    _seed()
    _rc, _d, out = _run(osm_lane_dir, "--wikidata-fixture", str(WD_FIXTURE))
    e = _by_osm(out)["node/9005"]
    assert e["qid"] == "Q1000005" and e["qid_resolved"] == "Q1000006"
    assert e["names"]["fr"] == "Redirectville" and e["names_source"]["fr"] == "wikidata"


def test_an_unnamed_place_takes_wikidatas_english_label_and_says_so_else_is_skipped(osm_lane_dir):
    _seed()
    _rc, data, out = _run(osm_lane_dir, "--wikidata-fixture", str(WD_FIXTURE))
    by = _by_osm(out)
    e = by["node/9003"]
    assert e["name"] == "Anonymville" and e["name_source"] == "wikidata"
    assert e["population"] == 900 and e["population_date"] == "2020-06-30", "no preferred claim: the latest P585"
    assert "node/9008" not in by, "no name from anywhere: not an entry, and counted"
    assert data["build"][0]["unnamed_skipped"] == 1


def test_a_wikidata_coordinate_far_from_osms_is_recorded_not_corrected(osm_lane_dir):
    _seed()
    _rc, data, out = _run(osm_lane_dir, "--wikidata-fixture", str(WD_FIXTURE))
    e = _by_osm(out)["node/9006"]
    assert (e["lat"], e["lon"]) == (0.15, 0.11), "OSM's point stays"
    assert e["coord_check"]["wikidata_differs_km"] > G.COORD_CHECK_KM
    assert "coord_check" not in _by_osm(out)["node/9001"]
    assert data["build"][0]["coord_differs"] == 1
    assert km_close(G.km_between((0.0, 0.0), (0.0, 1.0)), 111.2, 0.3)


def km_close(a, b, tol):
    return abs(a - b) <= tol


def test_osm_name_xx_wins_and_a_language_neither_has_is_left_out(osm_lane_dir):
    _seed()
    _rc, _d, out = _run(osm_lane_dir, "--wikidata-fixture", str(WD_FIXTURE))
    names = _by_osm(out)["node/9001"]["names"]
    assert set(names) <= set(G.LANGS) and "ja" not in names and "zh" not in names


def test_the_osm_only_build_carries_no_wikidata_derived_value(osm_lane_dir):
    _seed()
    rc, _d, out = _run(osm_lane_dir, "--no-wikidata")
    assert rc == 0
    doc = yaml.safe_load(out.read_text("utf-8"))
    assert doc["source"] == "osm" and doc["wikidata"] == {"joined": False}
    for e in doc["cities"]:
        assert e["source"] == "osm" and "qid_status" not in e and "coord_check" not in e
        assert e.get("population_source", "osm") == "osm"
        assert all(v == "osm" for v in e.get("names_source", {}).values())
    assert {c["osm"] for c in doc["cities"]} >= {"node/8", "node/9001"}


def test_the_artifact_is_byte_identical_for_the_same_input_and_says_its_vintage(osm_lane_dir):
    _seed()
    _rc, data1, out = _run(osm_lane_dir, "--wikidata-fixture", str(WD_FIXTURE))
    first = out.read_bytes()
    _rc, data2, out2 = _run(osm_lane_dir, "--wikidata-fixture", str(WD_FIXTURE))
    assert out2.read_bytes() == first and data1["artifact"]["sha256"] == data2["artifact"]["sha256"]
    assert data1["artifact"]["sha256"] == G.sha256_hex(first)
    # The synthetic extract states no vintage, so the artifact claims none (never a borrowed date).
    doc = yaml.safe_load(first.decode("utf-8"))
    assert "as_of" not in doc and doc["built"] == BUILT
    from sqlalchemy import text

    from src.versioned.store import lane_session

    with lane_session("osm") as s:
        s.execute(text("UPDATE osm_countries SET extract_vintage = '2026-10-01 00:00:00'"))
    _rc, _d, out3 = _run(osm_lane_dir, "--wikidata-fixture", str(WD_FIXTURE))
    assert yaml.safe_load(out3.read_text("utf-8"))["as_of"] == "2026-10-01"
    assert "OpenStreetMap contributors" in doc["license"] and "ODbL" in doc["license"]


def test_the_registry_entry_is_printed_with_the_real_hash_never_written(osm_lane_dir):
    _seed()
    _rc, data, out = _run(osm_lane_dir, "--no-wikidata")
    entry = yaml.safe_load("items:\n" + data["registry_entry"])["items"][0]
    assert entry["id"] == "place-gazetteer" and entry["pin"]["sha256"] == data["artifact"]["sha256"]
    assert "ODbL" in entry["license"] and entry["last_verified"] == BUILT
    assert "place-gazetteer" not in (ROOT / "configs" / "external_artifacts.yml").read_text("utf-8"), (
        "the registry entry lands with the artifact, in its own PR"
    )


def test_the_default_output_is_the_places_file_and_the_world_file_is_never_written():
    assert CLI.DEFAULT_OUT.name == "places_gazetteer.yml"
    assert CLI.DEFAULT_OUT != cities.GAZETTEER_PATH
    assert "cities.yml" not in (ROOT / "scripts" / "build_place_gazetteer.py").read_text("utf-8").replace(
        "configs/cities.yml", "")


def test_the_script_deletes_nothing_it_did_not_write(osm_lane_dir):
    _seed()
    before = {p.name for p in osm_lane_dir.rglob("*") if p.is_file()}
    _rc, _d, out = _run(osm_lane_dir, "--no-wikidata")
    after = {p.name for p in osm_lane_dir.rglob("*") if p.is_file()}
    assert before - after == set(), "no file of the data directory went away"
    assert out.exists() and not (osm_lane_dir / "places.yml.tmp").exists()


def test_a_how_to_join_must_be_chosen_and_plan_writes_nothing(osm_lane_dir, capsys):
    _seed()
    with pytest.raises(SystemExit):
        CLI.main(["--country", "ZZ"])
    capsys.readouterr()
    rc, _data, out = _run(osm_lane_dir, "--plan")
    assert rc == 0 and not out.exists()


# --------------------------------------------------------------------------- #
#  the plan, the pace and the fetch loop
# --------------------------------------------------------------------------- #


def test_the_plan_is_arithmetic_and_prints_the_run_time():
    p = G.plan(36_000)
    assert p["requests"] == 720 and p["min_seconds"] == 7190 and p["min_hours"] == 2.0
    assert "ceil(qids / 50)" in p["formula"] and "wbgetentities" in p["endpoint"]
    assert G.plan(0)["requests"] == 0 and G.plan(0)["min_seconds"] == 0
    assert G.plan(50)["requests"] == 1 and G.plan(51)["requests"] == 2 and G.plan(51)["min_seconds"] == 10


class _Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s


def _gate(clock):
    from src.analytics.ring_loader import RateGate

    return RateGate(clock=clock.now, sleep=clock.sleep)


def _answer(url: str) -> G.GetResult:
    from urllib.parse import parse_qs, urlparse

    ids = parse_qs(urlparse(url).query)["ids"][0].split("|")
    return G.GetResult(200, {"entities": {q: {"type": "item", "id": q, "labels": {"en": {"language": "en", "value": q}}}
                                          for q in ids}})


def test_requests_go_one_at_a_time_ten_seconds_apart_fifty_ids_each_with_maxlag():
    from urllib.parse import parse_qs, urlparse

    clock, urls = _Clock(), []

    def getter(url):
        urls.append((clock.now(), url))
        clock.t += 3.0  # the request takes time: the next one still starts a full pace after THIS one began
        return _answer(url)

    qids = [f"Q{n}" for n in range(1, 121)]
    items, rep = G.fetch_wikidata(qids, getter=getter, gate=_gate(clock), sleep=clock.sleep, kill_switch=lambda: False)
    assert rep["asked"] == 120 and rep["ok"] == 120 and rep["requests_made"] == 3 and len(items) == 120
    gaps = [b[0] - a[0] for a, b in zip(urls, urls[1:], strict=False)]
    assert all(g >= 10.0 for g in gaps), gaps
    assert [len(parse_qs(urlparse(u).query)["ids"][0].split("|")) for _t, u in urls] == [50, 50, 20]
    assert all(f"&maxlag={G.MAXLAG_S}" in u and "action=wbgetentities" in u for _t, u in urls)
    assert "OpenOmniscience-place-gazetteer" in G.USER_AGENT and "contact" in G.USER_AGENT


def test_retry_after_is_honoured_and_a_batch_that_keeps_failing_is_counted_refused():
    clock, calls = _Clock(), []

    def getter(url):
        calls.append(clock.now())
        if len(calls) == 1:
            return G.GetResult(429, None, 45.0)
        if len(calls) == 2:
            return G.GetResult(200, {"error": {"code": "maxlag", "info": "waiting"}}, 3.0)
        return _answer(url)

    items, rep = G.fetch_wikidata(["Q1", "Q2"], getter=getter, gate=_gate(clock), sleep=clock.sleep, kill_switch=lambda: False)
    assert rep["ok"] == 2 and rep["waited_for_server"] == 2
    assert 45.0 in clock.slept, "the server's Retry-After was waited out"
    assert max(clock.slept) <= G.RETRY_CAP_S
    assert any(s >= 10.0 for s in clock.slept[1:]), "a short Retry-After is never shorter than the pace"

    clock2 = _Clock()
    items, rep = G.fetch_wikidata(["Q1"], getter=lambda u: G.GetResult(503, None, 1.0), gate=_gate(clock2),
                                  sleep=clock2.sleep, kill_switch=lambda: False)
    assert rep["refused"] == 1 and rep["ok"] == 0 and rep["requests_made"] == G.RETRY_MAX + 1 and items == {}


def test_a_huge_retry_after_is_capped():
    clock = _Clock()
    n = []

    def getter(url):
        n.append(1)
        return G.GetResult(429, None, 99999.0) if len(n) == 1 else _answer(url)

    G.fetch_wikidata(["Q1"], getter=getter, gate=_gate(clock), sleep=clock.sleep, kill_switch=lambda: False)
    assert max(clock.slept) == G.RETRY_CAP_S


def test_a_failing_batch_does_not_stop_the_next_one_and_the_counts_add_up():
    clock = _Clock()

    def getter(url):
        if "ids=Q1%7C" in url:
            raise OSError("boom")
        return _answer(url)

    qids = [f"Q{n}" for n in range(1, 61)]
    items, rep = G.fetch_wikidata(qids, getter=getter, gate=_gate(clock), sleep=clock.sleep, kill_switch=lambda: False)
    assert rep["refused"] == 50 and rep["ok"] == 10
    assert rep["asked"] == rep["ok"] + rep["refused"] + rep["missing_on_wikidata"] + rep["not_asked"]


def test_the_kill_switch_refuses_by_name_before_any_request_and_stops_a_run_in_progress():
    called = []
    with pytest.raises(G.AirplaneRefusal, match="airplane mode"):
        G.fetch_wikidata(["Q1"], getter=lambda u: called.append(u), kill_switch=lambda: True)
    assert called == []

    clock, state = _Clock(), {"n": 0}

    def switch():
        state["n"] += 1
        return state["n"] > 3  # checks: start, batch 1, batch 2; on from the 4th (batch 3's request)

    def getter(url):
        called.append(url)
        return _answer(url)

    qids = [f"Q{n}" for n in range(1, 111)]
    items, rep = G.fetch_wikidata(qids, getter=getter, gate=_gate(clock), sleep=clock.sleep, kill_switch=switch)
    assert rep["stopped_by_airplane_mode"] is True and rep["not_asked"] > 0 and len(called) < 3


def test_a_kill_switch_engaged_during_the_pace_wait_stops_the_next_request():
    """The check comes AFTER the gate's wait: a switch thrown while the run waits is not missed."""
    clock, called = _Clock(), []

    def getter(url):
        called.append(url)
        return _answer(url)

    qids = [f"Q{n}" for n in range(1, 111)]
    _items, rep = G.fetch_wikidata(qids, getter=getter, gate=_gate(clock), sleep=clock.sleep,
                                   kill_switch=lambda: bool(clock.slept))  # true once the gate has slept
    assert len(called) == 1 and rep["stopped_by_airplane_mode"] is True and rep["not_asked"] == 60


def test_a_retry_goes_through_the_gate_so_the_next_batch_is_never_back_to_back():
    clock, times, state = _Clock(), [], {"n": 0}

    def getter(url):
        times.append(clock.now())
        state["n"] += 1
        return G.GetResult(429, None, 10.0) if state["n"] == 1 else _answer(url)

    qids = [f"Q{n}" for n in range(1, 61)]
    _items, rep = G.fetch_wikidata(qids, getter=getter, gate=_gate(clock), sleep=clock.sleep, kill_switch=lambda: False)
    assert rep["ok"] == 60 and len(times) == 3
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    assert all(g >= 10.0 for g in gaps), f"two requests left too close together: {gaps}"


def test_a_refusal_by_the_transport_or_the_kill_switch_is_named_not_counted_as_a_failed_batch():
    from src.safety.fetcher import NetworkBlocked, TransportUnavailable

    for exc, expected in ((TransportUnavailable("no proxy configured"), G.TransportRefusal),
                          (NetworkBlocked("kill switch"), G.AirplaneRefusal)):
        clock = _Clock()

        def getter(url, exc=exc):
            raise exc

        with pytest.raises(expected):
            G.fetch_wikidata(["Q1"], getter=getter, gate=_gate(clock), sleep=clock.sleep, kill_switch=lambda: False)


def test_retry_after_in_http_date_form_is_read():
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    soon = format_datetime(datetime.now(UTC) + timedelta(seconds=120), usegmt=True)
    assert 100 <= G._retry_after_seconds(soon) <= 120
    assert G._retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0
    assert G._retry_after_seconds("7") == 7.0 and G._retry_after_seconds("soon") is None
    assert G._retry_after_seconds(None) is None


def test_a_refused_batch_means_nothing_is_written_and_the_request_count_stays_out_of_the_artifact(osm_lane_dir, monkeypatch):
    import contextlib
    import io

    _seed()
    refused = {"asked": 5, "ok": 0, "missing_on_wikidata": 0, "refused": 5, "not_asked": 0, "requests_made": 6,
               "waited_for_server": 5, "stopped": False, "stopped_by_airplane_mode": False}
    monkeypatch.setattr(G, "fetch_wikidata", lambda qids, **kw: ({}, refused))
    out = osm_lane_dir / "x.yml"
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = CLI.main(["--country", "ZZ", "--out", str(out), "--online", "--clearnet", "--built-date", BUILT])
    assert rc == 2 and not out.exists(), "an artifact claiming a join over a refused one would mislead"

    items = G.items_from_fixture(WD_FIXTURE)
    first = b""
    for requests_made in (1, 3):  # a transient 429 changes the count, never the bytes
        ok = dict(refused, refused=0, ok=len(items), requests_made=requests_made)
        monkeypatch.setattr(G, "fetch_wikidata", lambda qids, ok=ok, **kw: (items, ok))
        with contextlib.redirect_stdout(io.StringIO()):
            assert CLI.main(["--country", "ZZ", "--out", str(out), "--online", "--clearnet", "--built-date", BUILT]) == 0
        if requests_made == 1:
            first = out.read_bytes()
    assert out.read_bytes() == first and b"requests" not in first


def test_online_under_airplane_mode_is_refused_by_name_and_the_getter_is_never_built(osm_lane_dir, monkeypatch):
    _seed()
    monkeypatch.setattr(G, "_kill_switch_active", lambda: True)
    monkeypatch.setattr(G, "guarded_getter", lambda url: pytest.fail("a request was attempted"))
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = CLI.main(["--country", "ZZ", "--out", str(osm_lane_dir / "x.yml"), "--online", "--clearnet"])
    assert rc == 2 and "airplane mode is engaged" in buf.getvalue()
    assert not (osm_lane_dir / "x.yml").exists()


def _no_transport_env(monkeypatch):
    for k in ("OO_FETCH_MODE", "OO_HTTP_PROXY", "OO_HTTP_PROXIES"):
        monkeypatch.delenv(k, raising=False)


def test_online_refuses_when_no_transport_is_named_unless_clearnet_is_said(osm_lane_dir, monkeypatch):
    """A fresh or throwaway store holds none of the operator's Tor settings: clearnet must be a choice."""
    _seed()
    _no_transport_env(monkeypatch)
    monkeypatch.setattr(G, "guarded_getter", lambda url: pytest.fail("a request was attempted"))
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = CLI.main(["--country", "ZZ", "--out", str(osm_lane_dir / "x.yml"), "--online"])
    assert rc == 2 and "name no transport" in buf.getvalue() and "--clearnet" in buf.getvalue()
    assert not (osm_lane_dir / "x.yml").exists()
    assert G.transport_state()["explicit"] is False


def test_online_end_to_end_through_an_injected_getter_records_its_transport(osm_lane_dir, monkeypatch):
    _seed()
    _no_transport_env(monkeypatch)
    payload = json.loads(WD_FIXTURE.read_text("utf-8"))
    seen = []

    def getter(url):
        seen.append(url)
        return G.GetResult(200, payload)

    monkeypatch.setattr(G, "guarded_getter", getter)
    monkeypatch.setattr(G, "_kill_switch_active", lambda: False)
    rc, data, out = _run(osm_lane_dir, "--online", "--clearnet")
    assert rc == 0, data
    assert data["transport"]["chosen_by"] == "--clearnet" and data["transport"]["protected"] is False
    assert data["fetch"]["requests_made"] == 1 and data["fetch"]["asked"] == 5 and len(seen) == 1
    assert "maxlag=5" in seen[0]
    assert _by_osm(out)["node/9001"]["population"] == 12000
    # An environment that names the transport is the operator's choice, and needs no flag.
    monkeypatch.setenv("OO_FETCH_MODE", "open")
    assert G.transport_state()["explicit"] is True
    rc, data, _o = _run(osm_lane_dir, "--online")
    assert rc == 0 and data["transport"]["chosen_by"] == "settings or environment"


def test_the_offline_modes_open_no_socket(osm_lane_dir, monkeypatch):
    _seed()

    def refuse(*a, **k):
        raise AssertionError("the gazetteer build opened a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    for mode in (["--no-wikidata"], ["--wikidata-fixture", str(WD_FIXTURE)], ["--plan"]):
        rc, _d, _o = _run(osm_lane_dir, *mode)
        assert rc == 0, mode


def test_a_plan_of_the_fixture_counts_the_qids_it_would_ask_for(osm_lane_dir):
    _seed()
    rc, data, _out = _run(osm_lane_dir, "--plan")
    assert rc == 0
    # Q1000001, Q1000003, Q1000004, Q1000005, Q1000007: the ambiguous "Q1000002;Q1000003" is not asked.
    assert data["plan"]["qids_expected"] == 5 and data["plan"]["requests"] == 1
    assert data["read"]["ZZZ"]["bad_wikidata_tag"] == 1


# --------------------------------------------------------------------------- #
#  the loader reads both files and merges by QID
# --------------------------------------------------------------------------- #


def _write(path: Path, doc: dict) -> Path:
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=True), "utf-8")
    return path


@pytest.fixture
def two_files(tmp_path, monkeypatch):
    world = _write(tmp_path / "cities.yml", {"as_of": "2026-06-01", "cities": [
        {"name": "Testburg", "lat": 0.0, "lon": 0.0, "country": "zz", "population": 1, "qid": "Q1000001"},
        {"name": "Elsewhere", "lat": 5.0, "lon": 5.0, "country": "zz", "population": 9, "qid": "Q555"},
        {"name": "Paris", "lat": 48.85, "lon": 2.35, "country": "fr", "population": 2_100_000},
    ]})
    places = _write(tmp_path / "places_gazetteer.yml", {"as_of": "2026-10-01", "source": "osm+wikidata", "cities": [
        {"name": "Testburg (OSM)", "lat": 0.11, "lon": 0.12, "country": "zz", "population": 12000, "qid": "Q1000001",
         "osm": "node/9001", "kind": "city"},
        {"name": "Paris", "lat": 0.17, "lon": 0.17, "country": "zz", "population": 40, "osm": "node/9007", "kind": "city",
         "source": "osm"},
    ]})
    monkeypatch.setattr(cities, "GAZETTEER_PATH", world)
    monkeypatch.setattr(cities, "PLACES_GAZETTEER_PATH", places)
    cities.gazetteer_meta.cache_clear()
    cities.cached_index.cache_clear()
    yield tmp_path
    monkeypatch.undo()
    cities.gazetteer_meta.cache_clear()
    cities.cached_index.cache_clear()


def test_an_overlapping_qid_takes_the_place_artifacts_entry_and_drops_the_worlds(two_files):
    got = {(c.name, c.qid): c for c in cities.load_cities()}
    assert ("Testburg (OSM)", "Q1000001") in got and ("Testburg", "Q1000001") not in got
    assert got[("Testburg (OSM)", "Q1000001")].population == 12000
    assert ("Elsewhere", "Q555") in got, "a world entry no place entry shares a QID with stays"


def test_two_entries_with_one_name_and_no_qid_are_never_merged(two_files):
    parises = [c for c in cities.load_cities() if c.name == "Paris"]
    assert len(parises) == 2 and {c.country for c in parises} == {"fr", "zz"}
    idx = cities.build_index(cities.load_cities())
    assert cities.lookup(idx, "Paris", "fr").population == 2_100_000
    assert cities.lookup(idx, "Paris", "zz").population == 40


def test_every_entry_keeps_its_source_and_the_vintage_of_its_own_file(two_files):
    by = {(c.name, c.osm): c for c in cities.load_cities()}
    assert by[("Elsewhere", None)].source == "wikidata-wdqs" and by[("Elsewhere", None)].vintage == "2026-06-01"
    assert by[("Testburg (OSM)", "node/9001")].source == "osm+wikidata"
    assert by[("Testburg (OSM)", "node/9001")].vintage == "2026-10-01"
    assert by[("Paris", "node/9007")].source == "osm", "an entry's own source wins over its file's"
    meta = cities.gazetteer_meta()
    assert meta["vintage"] == "2026-06-01" and meta["places"] == {
        "path": "places_gazetteer.yml", "artifact": True, "vintage": "2026-10-01"}


def test_a_place_resolved_from_the_artifact_is_stamped_with_the_artifacts_vintage(two_files):
    from src.entities import places as P

    class _Row:
        pass

    seen = {}

    class _Session:
        def get(self, model, key):
            return None

        def add(self, row):
            seen["row"] = row

    c = {x.osm: x for x in cities.load_cities()}["node/9001"]
    P.materialise(_Session(), c, vintage="2026-06-01")
    assert seen["row"].gazetteer_vintage == "2026-10-01"


def test_without_a_place_artifact_the_loader_reads_exactly_what_it_read_before(tmp_path, monkeypatch):
    world = _write(tmp_path / "cities.yml", {"as_of": "2026-06-01", "cities": [
        {"name": "A", "lat": 1.0, "lon": 1.0, "country": "zz"}]})
    monkeypatch.setattr(cities, "GAZETTEER_PATH", world)
    monkeypatch.setattr(cities, "PLACES_GAZETTEER_PATH", tmp_path / "absent.yml")
    cities.gazetteer_meta.cache_clear()
    got = cities.load_cities()
    assert [c.name for c in got] == ["A"] and cities.gazetteer_meta()["places"]["artifact"] is False
    cities.gazetteer_meta.cache_clear()
    assert got == cities._load_file(world), "the default path is the one-file path, entry for entry"


def test_an_osm_locality_sharing_a_world_citys_name_does_not_take_the_lookup_over(tmp_path, monkeypatch):
    world = _write(tmp_path / "cities.yml", {"as_of": "2026-06-01", "cities": [
        {"name": "Saint-Denis", "lat": 48.9, "lon": 2.36, "country": "fr", "population": 110_000, "qid": "Q1"}]})
    places = _write(tmp_path / "places_gazetteer.yml", {"cities": [
        {"name": "Saint-Denis", "lat": 45.0, "lon": 5.0, "country": "fr", "osm": "node/1", "kind": "hamlet"},
        {"name": "Saint-Denis", "lat": 46.0, "lon": 4.0, "country": "fr", "osm": "node/2", "kind": "locality",
         "qid": "Q9", "population": 80},
        {"name": "Saint-Denis", "lat": 47.0, "lon": 3.0, "country": "fr", "osm": "node/3", "kind": "town"}]})
    monkeypatch.setattr(cities, "GAZETTEER_PATH", world)
    monkeypatch.setattr(cities, "PLACES_GAZETTEER_PATH", places)
    got = cities.load_cities()
    assert len(got) == 4, "no entry was dropped for sharing a name"
    idx = cities.build_index(got)
    assert cities.lookup(idx, "Saint-Denis", "fr").qid == "Q1"
    assert cities.lookup(idx, "Saint-Denis").qid == "Q1"


def test_a_place_artifact_without_a_vintage_never_borrows_the_world_files(tmp_path, monkeypatch):
    from src.entities import places as P

    world = _write(tmp_path / "cities.yml", {"as_of": "2026-06-01", "cities": []})
    places = _write(tmp_path / "places_gazetteer.yml", {"cities": [
        {"name": "Fixtureville", "lat": 0.1, "lon": 0.1, "country": "zz", "osm": "node/9", "kind": "village"}]})
    monkeypatch.setattr(cities, "GAZETTEER_PATH", world)
    monkeypatch.setattr(cities, "PLACES_GAZETTEER_PATH", places)
    seen = {}

    class _Session:
        def get(self, model, key):
            return None

        def add(self, row):
            seen["row"] = row

    c = cities.load_cities()[0]
    P.materialise(_Session(), c, vintage="2026-06-01")
    assert seen["row"].gazetteer_vintage is None


def test_the_run_stops_asking_after_consecutive_refused_batches():
    clock, calls = _Clock(), []

    def getter(url):
        calls.append(url)
        return G.GetResult(404, None)  # not a request to wait out: the batch is refused at once

    qids = [f"Q{n}" for n in range(1, 501)]
    _items, rep = G.fetch_wikidata(qids, getter=getter, gate=_gate(clock), sleep=clock.sleep, kill_switch=lambda: False)
    assert len(calls) == G.CONSECUTIVE_REFUSED_MAX and rep["gave_up_after_refusals"] is True
    assert rep["refused"] == 50 * G.CONSECUTIVE_REFUSED_MAX and rep["not_asked"] == 500 - rep["refused"]
    assert rep["asked"] == rep["ok"] + rep["refused"] + rep["missing_on_wikidata"] + rep["not_asked"]


def test_a_200_with_an_error_body_counts_as_a_refused_batch_and_ends_the_run():
    """A 200 carrying ``{"error": ...}`` (or ``{}``) mentions none of the asked ids: it is a refusal that looks
    like a success, and it must neither reset the streak nor be reported as a joined batch."""
    clock, calls = _Clock(), []

    def getter(url):
        calls.append(url)
        return G.GetResult(200, {"error": {"code": "internal_api_error", "info": "try later"}} if len(calls) % 2 else {})

    qids = [f"Q{n}" for n in range(1, 501)]
    items, rep = G.fetch_wikidata(qids, getter=getter, gate=_gate(clock), sleep=clock.sleep, kill_switch=lambda: False)
    assert items == {} and rep["ok"] == 0
    assert len(calls) == G.CONSECUTIVE_REFUSED_MAX and rep["gave_up_after_refusals"] is True
    assert rep["refused"] == 50 * G.CONSECUTIVE_REFUSED_MAX


def test_a_stop_during_the_pace_wait_sends_no_request():
    clock, called = _Clock(), []
    stop = {"v": False}

    def sleeper(s):
        clock.sleep(s)
        stop["v"] = True  # the operator cancels while the gate waits

    from src.analytics.ring_loader import RateGate

    gate = RateGate(clock=clock.now, sleep=sleeper)
    qids = [f"Q{n}" for n in range(1, 111)]
    _items, rep = G.fetch_wikidata(qids, getter=lambda u: (called.append(u), _answer(u))[1], gate=gate,
                                   sleep=clock.sleep, kill_switch=lambda: False, should_stop=lambda: stop["v"])
    assert len(called) == 1 and rep["stopped"] is True and rep["not_asked"] > 0


def test_a_corrupt_place_artifact_never_takes_the_world_files_coverage_with_it(tmp_path, monkeypatch):
    world = _write(tmp_path / "cities.yml", {"as_of": "2026-06-01", "cities": [
        {"name": "A", "lat": 1.0, "lon": 1.0, "country": "zz"}]})
    places = tmp_path / "places_gazetteer.yml"
    places.write_text("cities: [unclosed\n  - : :\n", encoding="utf-8")
    monkeypatch.setattr(cities, "GAZETTEER_PATH", world)
    monkeypatch.setattr(cities, "PLACES_GAZETTEER_PATH", places)
    assert [c.name for c in cities.load_cities()] == ["A"]


@pytest.mark.parametrize("body", ["cities:\n", "cities: {a: 1}\n", "cities: just-a-string\n"])
def test_a_place_artifact_with_no_list_of_places_never_takes_the_world_files_coverage_with_it(tmp_path, monkeypatch, body):
    world = _write(tmp_path / "cities.yml", {"as_of": "2026-06-01", "cities": [
        {"name": "A", "lat": 1.0, "lon": 1.0, "country": "zz"}]})
    places = tmp_path / "places_gazetteer.yml"
    places.write_text(body, encoding="utf-8")
    monkeypatch.setattr(cities, "GAZETTEER_PATH", world)
    monkeypatch.setattr(cities, "PLACES_GAZETTEER_PATH", places)
    assert [c.name for c in cities.load_cities()] == ["A"]
