"""The monthly summary of the planet's prior (v0.6.0 R435): a cache of one function of the history rows, never a second source of truth.

Expected values are not computed by the code under test: the parity test compares the stored path with the computed path on the SAME rows, and
every fallback state has a test that fails when the fallback is removed (a stale summary that is served would show the poisoned rows).
"""

from __future__ import annotations

import ast
import pathlib
import time
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa

from src.osm import ingest
from src.osm import prior_summary as PS
from src.osm import profile as PF
from src.osm import trends as TR
from src.osm.lane_models import (
    OsmHistoryChange,
    OsmHistoryCut,
    OsmHistoryMonthly,
    OsmHistorySummary,
)
from src.versioned import store
from tests import _osm_lane_helpers
from tests.test_osm_apply import DAY1, _extract
from tests.test_osm_trends import _apply, _history

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = pathlib.Path(__file__).resolve().parents[1]
FINISHED = datetime(2025, 1, 2, tzinfo=UTC)


@pytest.fixture
def cut(osm_lane_dir):
    path = _extract(osm_lane_dir)
    assert ingest.ingest_country(path, "ZZ", reader="python").status == "complete"
    return path


def _t(y, m, d):
    return datetime(y, m, d, tzinfo=UTC)


#: A prior with every kind of row the readers count: gains and losses of the default and the brand and the social groups, a net-zero move,
#: the three signals, created / deleted / restored objects whose key rows are the event's own, an object's first version, a row with no
#: timestamp, a history with no version numbers, check_date, and another country's rows.
ROWS = [
    ("n", 5, 1, _t(2019, 1, 5), "added", "website", None, "x"),
    ("n", 5, 2, _t(2020, 3, 10), "added", "website", None, "x"),
    ("n", 6, 3, _t(2020, 3, 20), "removed", "phone", "p", None),
    ("n", 6, 4, _t(2020, 3, 21), "added", "brand", None, "Acme"),
    ("n", 6, 4, _t(2020, 3, 21), "added", "contact:facebook", None, "f"),
    ("n", 7, 1, _t(2020, 5, 1), "created", None, None, None),
    ("n", 7, 1, _t(2020, 5, 1), "added", "brand", None, "Z"),
    ("n", 8, 4, _t(2020, 5, 2), "deleted", None, None, None),
    ("n", 8, 4, _t(2020, 5, 2), "removed", "email", "e", None),
    ("n", 9, 3, _t(2020, 6, 2), "restored", None, None, None),
    ("n", 5, 4, _t(2021, 1, 9), "modified", "shop", "bakery", "vacant"),
    ("n", 10, 3, _t(2021, 1, 9), "added", "disused:shop", None, "bakery"),
    ("n", 11, 2, _t(2021, 1, 10), "modified", "opening_hours", "Mo-Fr", "closed"),
    ("n", 12, 2, _t(2021, 2, 1), "added", "check_date", None, "2021-02-01"),
    ("n", 12, 2, _t(2021, 2, 1), "added", "operator", None, "Op"),
    ("n", 13, 2, _t(2021, 2, 2), "added", "website", None, "w"),  # a tag moved to its contact twin: neither
    ("n", 13, 2, _t(2021, 2, 2), "removed", "contact:website", "old", None),
    ("n", 9, 2, None, "added", "email", None, "e"),
    ("n", 30, None, _t(2020, 3, 6), "deleted", None, None, None),
    ("n", 30, None, _t(2020, 3, 6), "removed", "email", "e", None),
    ("n", 30, None, _t(2020, 4, 6), "added", "email", None, "e"),
]


def _prior_of(alpha3="ZZZ"):
    """Every surface's prior block, the summary's own fields set aside."""
    out = {"trends": TR.trends(alpha3)["prior"]}
    for s_ in PF.SURFACES:
        out[s_] = PF.profile(alpha3, s_)["prior"]
    return out


def _bare(block):
    return {k: v for k, v in block.items() if k not in ("source", "summary")}


def _seed(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: DAY1})
    _history(ROWS)
    with store.lane_session("osm") as s:
        s.query(OsmHistoryCut).filter_by(alpha3="ZZZ").one().finished_at = FINISHED
        s.add(OsmHistoryChange(country_alpha3="YYY", osm_type="n", osm_id=999, object_version=3, version_timestamp=_t(2020, 3, 1), change="added", key="website", new_value="y"))


def test_the_stored_summary_gives_the_same_answer_as_the_history_rows_on_every_surface(cut, osm_lane_dir):
    _seed(cut, osm_lane_dir)
    before = _prior_of()
    assert {b["source"] for b in before.values()} == {"computed"} and {b["summary"]["state"] for b in before.values()} == {"not-built"}
    assert before["trends"]["available"] is True and before["trends"]["adoption"]["n"] > 0
    res = PS.build_summary("ZZZ")
    assert res["status"] == "built" and res["rows"] > 0
    after = _prior_of()
    assert {b["source"] for b in after.values()} == {"summary"} and {b["summary"]["state"] for b in after.values()} == {"current"}
    for surface in before:
        assert _bare(after[surface]) == _bare(before[surface]), f"the {surface} surface reads differently from its summary"
    # method and caveat are the unchanged strings
    assert after["trends"]["method"] == TR.METHOD_PRIOR and after["trends"]["adoption"]["caveat"] == TR.CAVEAT_PRIOR
    assert after["brands"]["method"] == PF.METHOD_PRIOR and after["brands"]["caveat"] == PF.CAVEAT_PRIOR


def test_another_countrys_rows_are_not_in_this_countrys_summary(cut, osm_lane_dir):
    _seed(cut, osm_lane_dir)
    PS.build_summary("ZZZ")
    with store.lane_session("osm") as s:
        assert s.query(OsmHistoryMonthly).filter_by(alpha3="YYY").count() == 0
        assert s.query(OsmHistorySummary).filter_by(alpha3="ZZZ").count() == len(PS.SURFACES)


def test_a_reader_never_writes_a_summary(cut, osm_lane_dir):
    _seed(cut, osm_lane_dir)
    _prior_of()
    with store.lane_session("osm") as s:
        assert s.query(OsmHistoryMonthly).count() == 0 and s.query(OsmHistorySummary).count() == 0, "a GET built the summary"


def _poison():
    """Rows that no history produces: a summary served when it should not be would show them."""
    with store.lane_session("osm") as s:
        s.query(OsmHistoryMonthly).filter_by(surface="trends", kind="event").delete()
        s.add(OsmHistoryMonthly(alpha3="ZZZ", surface="trends", kind="event", bucket="1999-09", name="created", direction=None, n=777))


def test_a_summary_of_an_older_cut_is_not_served_and_the_answer_says_computed(cut, osm_lane_dir):
    _seed(cut, osm_lane_dir)
    expected = _bare(TR.trends("ZZZ")["prior"])
    PS.build_summary("ZZZ")
    _poison()
    with store.lane_session("osm") as s:
        s.query(OsmHistoryCut).filter_by(alpha3="ZZZ").one().finished_at = datetime(2025, 3, 1, tzinfo=UTC)  # the cut was run again
    got = TR.trends("ZZZ")["prior"]
    assert got["source"] == "computed" and got["summary"]["state"] == "stale-cut"
    assert _bare(got) == expected and "1999-09" not in repr(got)


def test_a_summary_written_by_another_rule_is_not_served(cut, osm_lane_dir):
    _seed(cut, osm_lane_dir)
    expected = _bare(PF.profile("ZZZ", "brands")["prior"])
    PS.build_summary("ZZZ")
    with store.lane_session("osm") as s:
        s.query(OsmHistorySummary).update({"rule_version": "0old00000000"})
        s.add(OsmHistoryMonthly(alpha3="ZZZ", surface="brands", kind="adoption", bucket="1999-09", name="brand", direction="gained", n=777))
    got = PF.profile("ZZZ", "brands")["prior"]
    assert got["source"] == "computed" and got["summary"]["state"] == "stale-rule"
    assert _bare(got) == expected and "1999-09" not in repr(got)


def test_the_rule_version_follows_the_key_sets(monkeypatch):
    base = PS.rule_version()
    assert PS.rule_version() == base
    monkeypatch.setattr(PF, "BRAND_GROUPS", (*PF.BRAND_GROUPS, ("brand:wikipedia", ("brand:wikipedia",))))
    assert PS.rule_version() != base, "a new key group must make every stored summary stale"
    monkeypatch.undo()
    monkeypatch.setattr(PS, "RULE_REVISION", PS.RULE_REVISION + 1)
    assert PS.rule_version() != base


def test_a_lane_without_the_summary_tables_computes_says_so_and_a_build_adds_them(cut, osm_lane_dir):
    """A lane cut by an older build has no table for the summary: the readers compute and say so, and the build (a writer) adds the tables."""
    _seed(cut, osm_lane_dir)
    expected = _bare(TR.trends("ZZZ")["prior"])
    with store.lane_session("osm") as s:
        s.execute(sa.text("DROP TABLE osm_history_monthly"))
        s.execute(sa.text("DROP TABLE osm_history_summaries"))
    got = TR.trends("ZZZ")["prior"]
    assert got["source"] == "computed" and got["summary"]["state"] == "no-summary-table" and _bare(got) == expected
    assert PS.summary_state("ZZZ")["state"] == "no-summary-table"
    assert PS.build_summary("ZZZ")["status"] == "built"
    after = TR.trends("ZZZ")["prior"]
    assert after["source"] == "summary" and _bare(after) == expected
    assert PS.summary_state("ZZZ")["state"] == "current"


def test_no_finished_cut_has_no_summary_and_no_prior(cut, osm_lane_dir):
    _apply(osm_lane_dir, {101: DAY1})
    assert PS.build_summary("ZZZ") == {"status": "no-cut", "reason": "no-history-cut"}
    _history(ROWS, status="failed")
    assert PS.build_summary("ZZZ") == {"status": "no-cut", "reason": "history-cut-unfinished"}
    assert TR.trends("ZZZ")["prior"]["available"] is False


def test_a_rebuild_replaces_the_rows_and_a_current_summary_is_skipped(cut, osm_lane_dir):
    _seed(cut, osm_lane_dir)
    assert PS.build_summary("ZZZ", only_if_missing=True)["status"] == "built"
    assert PS.build_summary("ZZZ", only_if_missing=True) == {"status": "current"}
    with store.lane_session("osm") as s:
        n = s.query(OsmHistoryMonthly).count()
    assert PS.build_summary("ZZZ")["status"] == "built"
    with store.lane_session("osm") as s:
        assert s.query(OsmHistoryMonthly).count() == n, "a rebuild must replace the rows, not add to them"
        assert s.query(OsmHistorySummary).count() == len(PS.SURFACES)


def test_a_cut_re_run_during_the_pass_leaves_nothing_that_could_pass_for_current(cut, osm_lane_dir, monkeypatch):
    _seed(cut, osm_lane_dir)
    real = PS.surface_rows

    def rerun(*a, **k):
        with store.lane_session("osm") as s:
            s.query(OsmHistoryCut).filter_by(alpha3="ZZZ").one().finished_at = datetime(2025, 6, 1, tzinfo=UTC)
        return real(*a, **k)

    monkeypatch.setattr(PS, "surface_rows", rerun)
    assert PS.build_summary("ZZZ") == {"status": "superseded"}
    with store.lane_session("osm") as s:
        assert s.query(OsmHistoryMonthly).count() == 0 and s.query(OsmHistorySummary).count() == 0


def test_a_failed_summary_never_fails_the_cut_and_the_readers_compute(cut, osm_lane_dir, monkeypatch, caplog):
    _seed(cut, osm_lane_dir)

    def boom(*a, **k):
        raise RuntimeError("disk full /home/someone/secret")

    monkeypatch.setattr(PS, "build_summary", boom)
    PS.build_quietly("ZZZ")  # does not raise
    assert not PS.is_building("ZZZ"), "a failed build left the country marked as building"
    assert TR.trends("ZZZ")["prior"]["source"] == "computed"
    assert "planet-prior summary could not be built" in caplog.text, "the failure is logged, not swallowed"


def test_the_history_cut_builds_the_summary_when_it_finishes(osm_lane_dir):
    from src.osm import history, ingest
    from tests.test_osm_history import FIXTURE, HISTORY

    ingest.ingest_country(FIXTURE, "ZZ", reader="python")
    assert history.ingest_history(HISTORY, FIXTURE, "ZZ", reader="python").status == "complete"
    prior = TR.trends("ZZZ")
    # the fixture lane has no daily files, so the trends answer is the window-less one; the prior is still the summary
    assert prior["prior"]["source"] == "summary" and prior["prior"]["summary"]["state"] == "current"
    for s_ in PF.SURFACES:
        assert PF.profile("ZZZ", s_)["prior"]["source"] == "summary"


def test_the_route_builds_for_an_existing_cut_on_a_thread_and_a_get_does_not(cut, osm_lane_dir):
    from fastapi.testclient import TestClient

    from src.api.main import app

    _seed(cut, osm_lane_dir)
    with TestClient(app) as c:
        assert c.get("/api/osm/countries/ZZ/trends").json()["prior"]["source"] == "computed"
        assert c.post("/api/osm/countries/not-a-country/prior-summary").status_code == 400
        first = c.post("/api/osm/countries/ZZ/prior-summary").json()
        assert first["status"] == "building" and first["started"] in (True, False)
        for _ in range(100):
            if not PS.is_building("ZZZ"):
                break
            time.sleep(0.1)
        assert not PS.is_building("ZZZ")
        got = c.get("/api/osm/countries/ZZ/trends").json()["prior"]
        assert got["source"] == "summary" and got["summary"]["state"] == "current"
        again = c.post("/api/osm/countries/ZZ/prior-summary").json()
        assert again["status"] in ("building",)


def test_the_module_makes_no_request_and_imports_no_socket_library():
    tree = ast.parse((ROOT / "src" / "osm" / "prior_summary.py").read_text())
    names = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)} | {
        (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    }
    assert not names & {"requests", "httpx", "socket", "urllib", "http", "aiohttp"}


def test_the_page_states_the_source_and_asks_for_a_build_once_in_node():
    import subprocess

    proc = subprocess.run(["node", str(ROOT / "tests" / "osm_prior_summary_node_test.js")], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_page_wiring_reads_the_source_in_both_prior_blocks_and_never_asks_for_the_network():
    from tests.js_source_helper import function_source

    js = (ROOT / "src" / "static" / "app-map.js").read_text(encoding="utf-8")
    assert "_osmPriorSource(p)" in function_source(js, "_osmTrendPrior")
    assert "_osmPriorSource(p)" in function_source(js, "_osmProfileBody")
    assert "_osmPriorEnsure(" in function_source(js, "_renderOsmTrends") and "_osmPriorEnsure(" in function_source(js, "_osmProfileFetch")
    assert "ensureOnline" not in function_source(js, "_osmPriorEnsure"), "building a local summary asked for the network consent"
