"""The OSM lane's diagnostics member: what the daily change files did and cost, read back from the stored records (v0.6.0 B1, S06-01 S5).

Expected values are written out from the fixtures' own change files (their sizes) and sequence numbers, never computed by the member.
"""

from __future__ import annotations

import json
import types
from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from src.osm import apply as A
from src.osm import diagnostics as D
from src.osm import ingest
from src.osm.lane_models import OsmCountry, OsmDiffRun
from src.versioned import store
from src.versioned.models import VersionedGap
from tests import _osm_lane_helpers
from tests.os_scope import scope_os
from tests.test_osm_apply import (  # the apply tests' own fixture mirror and change files
    DAY1,
    SEQ0,
    T0,
    Mirror,
    _extract,
    _osc,
)

osm_lane_dir = _osm_lane_helpers.osm_lane_dir


@pytest.fixture
def cut(osm_lane_dir):
    """ZZ cut from a stamped extract named like a Geofabrik one; returns its path."""
    path = _extract(osm_lane_dir)
    assert ingest.ingest_country(path, "ZZ", reader="python").status == "complete"
    return path


DAY2 = _osc('<create><node id="40" version="1" timestamp="2025-01-12T00:00:00Z" lat="0.12" lon="0.12"><tag k="amenity" v="bench"/></node></create>')


def _run(osm_lane_dir, newest, diffs, **kw):
    return A.update_country("ZZ", Mirror(newest, diffs), workdir=osm_lane_dir / "w", kill_switch=lambda: False, **kw)


def test_no_lane_is_a_stated_absence_not_an_error_or_an_empty_list_of_zeros():
    got = D.diagnostics_member(20_000)
    assert got["lane"] == "absent" and got["countries"] == [] and "error" not in got and "no OpenStreetMap country" in got["reason"]


def test_a_cut_country_no_file_has_touched_is_listed_by_code_only(cut):
    got = D.diagnostics_member(20_000)
    assert got["countries"] == [] and got["countries_without_updates"] == ["ZZZ"] and got["countries_not_shown"] == 0


def test_a_country_re_cut_before_any_file_applied_has_a_gap_and_no_cost_and_says_why_never_zero(cut, osm_lane_dir):
    (osm_lane_dir / "fresh").mkdir()
    A.rebaseline("ZZ", _extract(osm_lane_dir / "fresh", seq=SEQ0 + 200, when=T0 + timedelta(days=200)), reason="past retention", reader="python")
    (c,) = D.diagnostics_member(20_000)["countries"]
    assert c["cost"] is None and "no cost was measured" in c["cost_reason"]
    assert (c["diffs_recorded"], c["last_applied_at"], c["runs"], c["rebaselines"]) == (0, None, [], 1)
    assert c["position"] == {"from": "extract", "sequence": SEQ0 + 200, "timestamp": (T0 + timedelta(days=200)).isoformat()}


def test_two_applied_files_are_read_back_with_their_measured_cost(cut, osm_lane_dir):
    _run(osm_lane_dir, 102, {101: DAY1, 102: DAY2})
    got = D.diagnostics_member(20_000)
    (c,) = got["countries"]
    assert c["position"]["from"] == "change file" and c["position"]["sequence"] == 102
    assert (c["diffs_recorded"], c["cursor_token"]) == (2, "102")
    assert [r["sequence"] for r in c["runs"]] == [102, 101], "newest first"
    assert c["cost"]["bytes_fetched"] == {"n": 2, "total": len(DAY1) + len(DAY2), "max": max(len(DAY1), len(DAY2))}
    assert all(type(c["cost"]["bytes_fetched"][k]) in (int, float) for k in ("total", "max"))
    assert c["cost"]["fetch_seconds"]["n"] == 2 and c["cost"]["apply_seconds"]["n"] == 2
    assert got["measured_on"]["os"] and got["measured_on"]["full_record"] == "manifest.json run.hardware"
    assert c["last_applied_at"] == c["runs"][0]["applied_at"]


def test_a_rebaseline_is_counted_as_one_and_a_hand_recut_as_the_other(cut, osm_lane_dir):
    _run(osm_lane_dir, 101, {101: DAY1})
    (osm_lane_dir / "fresh").mkdir()
    later = T0 + timedelta(days=200)
    A.rebaseline("ZZ", _extract(osm_lane_dir / "fresh", seq=SEQ0 + 200, when=later), reason="past retention", reader="python")
    (c,) = D.diagnostics_member(20_000)["countries"]
    assert (c["rebaselines"], c["hand_recuts_seen"], c["gaps_total"]) == (1, 0, 1)
    assert c["gaps"][0]["reason"] == "retention" and (c["gaps"][0]["from_token"], c["gaps"][0]["to_token"]) == ("101", "300")
    assert c["position"]["sequence"] == 300 and c["position"]["from"] == "extract"


def _many_runs(n: int) -> None:
    base = datetime(2025, 2, 1, tzinfo=UTC)
    with store.lane_session("osm") as s:
        for i in range(n):
            s.add(OsmDiffRun(alpha3="ZZZ", sequence=1000 + i, diff_timestamp=base + timedelta(days=i), applied_at=base + timedelta(days=i),
                             bytes_fetched=1_000_000 + i, fetch_seconds=1.5, apply_seconds=2.5, counts_json="{}"))


def test_the_member_is_cut_to_its_budget_oldest_runs_first_and_says_how_many_while_the_cost_still_covers_every_run(cut):
    _many_runs(60)
    full = D.diagnostics_member(1_000_000)
    (c,) = full["countries"]
    assert len(c["runs"]) == D.RUNS_KEPT and c["runs_not_shown"] == 60 - D.RUNS_KEPT and c["cost"]["bytes_fetched"]["n"] == 60
    small_budget = len(json.dumps(full, separators=(",", ":"))) - 600
    cutdown = D.diagnostics_member(small_budget)
    (k,) = cutdown["countries"]
    assert cutdown["dropped_to_fit"]["runs"] >= 1 and len(k["runs"]) < D.RUNS_KEPT
    assert k["runs"][0]["sequence"] == 1059, "the newest run is the last to go"
    assert k["cost"]["bytes_fetched"]["n"] == 60, "the cost is not cut with the list"
    assert len(json.dumps(cutdown, separators=(",", ":"))) <= small_budget
    assert D.diagnostics_member(100)["omitted"].startswith("max_bytes is below")


def test_with_no_room_for_a_countrys_rows_the_country_longest_without_a_file_goes_and_the_member_says_so(cut):
    _many_runs(3)
    full = D.diagnostics_member(1_000_000)
    bare = dict(full)
    bare["countries"] = [{**full["countries"][0], "runs": [], "gaps": []}]
    floor = len(json.dumps(bare, separators=(",", ":")))
    got = D.diagnostics_member(floor - 200)
    assert got.get("countries") == [] and got["countries_not_shown"] == 1 and got["dropped_to_fit"]["runs"] == 3
    assert len(json.dumps(got, separators=(",", ":"))) <= floor - 200


def test_the_member_never_raises_and_carries_no_path_or_address(cut, monkeypatch):
    got = D.diagnostics_member(20_000)
    text = json.dumps(got)
    assert "/" not in text.replace("manifest.json run.hardware", "") and "http" not in text

    def boom(*a, **k):
        raise OSError("/home/someone/secret.db is unreadable")

    monkeypatch.setattr(store, "lane_exists", boom)
    err = D.diagnostics_member(20_000)
    assert err["error"] == "OSError" and set(err) == {"error", "reason"} and "someone" not in json.dumps(err)


SENTINEL = "Secret Clinic Street 5"


def test_an_error_names_its_class_and_none_of_its_words_whatever_the_exception_is(cut, monkeypatch):
    """A column type's decoding error can quote a stored value, so the words are never emitted, for ANY exception class."""

    def boom(*a, **k):
        raise ValueError(f"tag name={SENTINEL}")

    monkeypatch.setattr(D, "_build", boom)
    got = D.diagnostics_member(20_000)
    assert got["error"] == "ValueError" and SENTINEL not in json.dumps(got)


def test_no_stored_text_of_the_country_reaches_the_member(cut):
    with store.lane_session("osm") as s:
        row = s.query(OsmCountry).one()
        row.name, row.error, row.extract_name, row.blob_json = SENTINEL, SENTINEL, SENTINEL, SENTINEL
    _many_runs(2)
    assert SENTINEL not in json.dumps(D.diagnostics_member(1_000_000))


def test_the_absent_lane_obeys_the_budget_too():
    assert D.diagnostics_member(20_000)["lane"] == "absent"
    tiny = D.diagnostics_member(100)
    assert tiny["over_budget"] is True and tiny["omitted"].startswith("max_bytes is below") and tiny["needs_at_least_bytes"] > 100


def test_a_lane_cut_before_the_runs_table_existed_keeps_its_position_and_says_what_is_missing(cut, osm_lane_dir):
    _run(osm_lane_dir, 101, {101: DAY1})
    with store.lane_session("osm") as s:
        s.execute(sa.text("DROP TABLE osm_diff_runs"))
    got = D.diagnostics_member(20_000)
    assert "error" not in got
    (c,) = got["countries"]
    assert c["diffs_recorded"] is None and c["cost"] is None and "older build" in c["cost_reason"] and c["runs"] == []
    assert c["position"]["from"] == "change file" and c["position"]["sequence"] == 101
    assert got["countries_without_updates"] == []


def test_a_figure_no_run_measured_is_null_with_a_reason_not_a_zero(cut):
    base = datetime(2025, 2, 1, tzinfo=UTC)
    with store.lane_session("osm") as s:
        s.add(OsmDiffRun(alpha3="ZZZ", sequence=1000, diff_timestamp=base, applied_at=base, bytes_fetched=None, fetch_seconds=None,
                         apply_seconds=None, counts_json="{}"))
    (c,) = D.diagnostics_member(20_000)["countries"]
    assert c["cost"]["bytes_fetched"] is None and c["cost"]["fetch_seconds"] is None and c["cost"]["apply_seconds"] is None
    assert set(c["cost"]["unmeasured"]) == {"bytes_fetched", "fetch_seconds", "apply_seconds"}


def test_a_country_that_never_ran_the_feed_says_why_its_cursor_is_null(cut, osm_lane_dir):
    (osm_lane_dir / "fresh").mkdir()
    A.rebaseline("ZZ", _extract(osm_lane_dir / "fresh", seq=SEQ0 + 200, when=T0 + timedelta(days=200)), reason="past retention", reader="python")
    with store.lane_session("osm") as s:
        s.execute(sa.text("DELETE FROM versioned_cursors"))
    (c,) = D.diagnostics_member(20_000)["countries"]
    assert c["cursor_token"] is None and "no cursor" in c["cursor_reason"]


def _many_gaps(n: int) -> None:
    base = datetime(2025, 2, 1, tzinfo=UTC)
    with store.lane_session("osm") as s:
        for i in range(n):
            s.add(VersionedGap(feed="osm-daily:ZZZ", detected_at=base + timedelta(days=i), from_token=str(100 + i), to_token=str(200 + i),
                               reason="retention"))


def test_gaps_are_cut_oldest_first_and_counted_once_the_runs_are_gone(cut):
    _many_gaps(10)
    full = D.diagnostics_member(1_000_000)
    (c,) = full["countries"]
    assert len(c["gaps"]) == D.GAPS_KEPT and c["gaps_total"] == 10 and c["gaps"][0]["from_token"] == "109"
    size = len(json.dumps(full, separators=(",", ":")))
    cutdown = D.diagnostics_member(size - 150)
    (k,) = cutdown["countries"]
    assert cutdown["dropped_to_fit"]["gaps"] >= 1 and cutdown["dropped_to_fit"]["runs"] == 0
    assert k["gaps_not_shown"] == cutdown["dropped_to_fit"]["gaps"] and len(k["gaps"]) == 10 - k["gaps_not_shown"]
    assert k["gaps"][0]["from_token"] == "109", "the newest gap is the last to go"
    assert k["gaps_total"] == 10 and k["rebaselines"] == 10, "the totals are not cut with the list"
    assert len(json.dumps(cutdown, separators=(",", ":"))) <= size - 150


def test_a_country_with_a_newer_gap_than_anothers_last_file_sorts_ahead_of_it(cut):
    _many_gaps(1)
    _many_runs(1)
    base = datetime(2025, 2, 1, tzinfo=UTC)
    with store.lane_session("osm") as s:
        s.add(OsmCountry(alpha2="YY", alpha3="YYY", status="complete"))
        s.add(OsmDiffRun(alpha3="YYY", sequence=5, diff_timestamp=base, applied_at=base + timedelta(days=400), bytes_fetched=1, fetch_seconds=1.0,
                         apply_seconds=1.0, counts_json="{}"))
        s.add(VersionedGap(feed="osm-daily:ZZZ", detected_at=base + timedelta(days=900), from_token="1", to_token="2", reason="budget"))
    assert [c["alpha3"] for c in D.diagnostics_member(1_000_000)["countries"]] == ["ZZZ", "YYY"]


def test_the_list_of_untouched_codes_is_cut_last_and_counted(cut):
    with store.lane_session("osm") as s:
        for i in range(40):
            s.add(OsmCountry(alpha2="A" + chr(65 + i % 26), alpha3="Q" + chr(65 + i // 26) + chr(65 + i % 26), status="complete"))
    full = D.diagnostics_member(1_000_000)
    assert len(full["countries_without_updates"]) == 41
    size = len(json.dumps(full, separators=(",", ":")))
    got = D.diagnostics_member(size - 100)
    assert "omitted" not in got and got["countries_without_updates_not_shown"] > 0
    assert len(got["countries_without_updates"]) + got["countries_without_updates_not_shown"] == 41
    assert len(json.dumps(got, separators=(",", ":"))) <= size - 100


def _tree(sizes):
    """Countries with ``n`` identical runs each (no gaps), to cut by hand."""
    run = {"sequence": 1, "bytes_fetched": 1234567, "fetch_seconds": 1.5, "apply_seconds": 2.5}
    return {"countries": [{"alpha3": a3, "runs": [dict(run) for _ in range(n)], "gaps": [], "runs_not_shown": 0, "gaps_not_shown": 0}
                          for a3, n in sizes], "countries_without_updates": [], "countries_without_updates_not_shown": 0,
            "countries_not_shown": 0, "dropped_to_fit": {"runs": 0, "gaps": 0}}


def test_the_heaviest_country_loses_its_runs_first_and_no_country_goes_while_another_still_holds_runs():
    out = _tree([("AAA", 2), ("BBB", 7), ("CCC", 3)])
    full = len(json.dumps(out, separators=(",", ":")))
    assert D._cut_to_fit(out, full - 160) is True
    by = {c["alpha3"]: len(c["runs"]) for c in out["countries"]}
    assert by["AAA"] == 2 and by["BBB"] < 7 and out["countries_not_shown"] == 0
    # a country is dropped only once EVERY remaining country is down to its bare row
    dropped = 0
    for budget in range(150, 900, 10):
        out = _tree([("AAA", 2), ("BBB", 7), ("CCC", 3)])
        D._cut_to_fit(out, budget)
        if out["countries_not_shown"]:
            dropped += 1
            assert all(not c["runs"] for c in out["countries"]), budget
    assert dropped, "the range never reached the point of dropping a country"


def test_a_fit_by_the_running_estimate_is_measured_again_before_it_is_believed():
    """Emptying a list removes no comma, and a counter gains a digit: the estimate alone can say fit while the real size is over."""
    for budget in range(300, 900, 7):
        out = _tree([("AAA", 9), ("BBB", 9), ("CCC", 9)])
        ok = D._cut_to_fit(out, budget)
        assert ok == (len(json.dumps(out, separators=(",", ":"))) <= budget)


def test_the_cut_measures_each_item_once_not_the_whole_output_per_pop(monkeypatch):
    """200 populated countries took 15 s when every pop re-measured the whole output; the count of measurements stays linear."""
    calls = []
    real = D._size
    monkeypatch.setattr(D, "_size", lambda v: calls.append(1) or real(v))
    out = _tree([(f"C{i:03d}", 7) for i in range(200)])
    assert D._cut_to_fit(out, 20_000) is True
    assert len(calls) < 6 * (200 * 7), len(calls)
    assert len(json.dumps(out, separators=(",", ":"))) <= 20_000


@pytest.mark.parametrize("table", ["versioned_gaps", "versioned_cursors"])
def test_a_lane_without_the_substrate_tables_still_reports_the_country_and_says_which_is_missing(cut, osm_lane_dir, table):
    _run(osm_lane_dir, 101, {101: DAY1})
    with store.lane_session("osm") as s:
        s.execute(sa.text(f"DROP TABLE {table}"))
    got = D.diagnostics_member(20_000)
    assert "error" not in got
    (c,) = got["countries"]
    if table == "versioned_gaps":
        assert c["gaps_total"] is None and "older build" in c["gaps_reason"]
    else:
        assert c["cursor_token"] is None and "older build" in c["cursor_reason"]
    assert c["diffs_recorded"] == 1


@pytest.mark.parametrize("bad", ["abc", None, float("nan")])
def test_a_budget_that_is_not_a_number_is_said_to_be_the_argument_not_the_lane(bad):
    got = D.diagnostics_member(bad)
    assert got["reason"] == "max_bytes is not a whole number" and got["error"] in {"ValueError", "TypeError"}


def test_an_omitted_answer_still_says_which_lane_state_it_cut_from(cut):
    assert D.diagnostics_member(5)["lane"] == "present" and D.diagnostics_member(5)["over_budget"] is True


def test_a_machine_that_reports_nothing_says_so_per_field(monkeypatch):
    scope_os(monkeypatch, D, cpu_count=lambda: None)  # as the module sees os; the runner's os is not touched (R351)
    monkeypatch.setattr(D, "platform", types.SimpleNamespace(system=lambda: "", machine=lambda: "x86_64"))
    got = D._machine()
    assert set(got["unreported"]) == {"os", "cpus"} and got["arch"]
