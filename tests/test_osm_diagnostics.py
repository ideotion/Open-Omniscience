"""The OSM lane's diagnostics member: what the daily change files did and cost, read back from the stored records (v0.6.0 B1, S06-01 S5).

Expected values are written out from the fixtures' own change files (their sizes) and sequence numbers, never computed by the member.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from src.osm import apply as A
from src.osm import diagnostics as D
from src.osm import ingest
from src.osm.lane_models import OsmDiffRun
from src.versioned import store
from tests import _osm_lane_helpers
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
    assert c["cost"]["bytes_fetched"] == {"n": 2, "total": float(len(DAY1) + len(DAY2)), "max": float(max(len(DAY1), len(DAY2)))}
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


def test_the_member_never_raises_and_carries_no_path_or_address(cut, monkeypatch):
    got = D.diagnostics_member(20_000)
    text = json.dumps(got)
    assert "/" not in text.replace("manifest.json run.hardware", "") and "http" not in text
    def boom(*a, **k):
        raise OSError("/home/someone/secret.db is unreadable")

    monkeypatch.setattr(store, "lane_exists", boom)
    err = D.diagnostics_member(20_000)
    assert set(err) == {"error"} and "someone" not in err["error"]


def test_a_hand_recut_is_not_counted_as_a_rebaseline(cut, osm_lane_dir):
    _run(osm_lane_dir, 101, {101: DAY1})
    ingest.ingest_country(cut, "ZZ", reader="python")  # the operator cuts again by hand: the cursor and the objects disagree
    _run(osm_lane_dir, 101, {101: DAY1})
    (c,) = D.diagnostics_member(20_000)["countries"]
    assert (c["rebaselines"], c["hand_recuts_seen"]) == (0, 1) and c["gaps"][0]["reason"] == "budget"
