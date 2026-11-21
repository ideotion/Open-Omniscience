"""Row 278 (0.6 gate row B, Q824): the OSM picker shows the daily change file cost MEASURED here once files are applied.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The picker's "Daily changes" column showed a from-memory estimate forever, though its own caveat says the first daily update
measures the real figure, and its cadence still said the apply "arrives in 0.6". Now each chosen country carries the median
compressed size of its applied change files (``osm_diff_runs.bytes_fetched``), how many carried one and the newest file's own
date, or ``None`` with the reason it has none: never a 0. The lane is read in one session that is closed before the picker
answers, and not opened at all when its file does not exist.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from src.osm import picker as P
from src.versioned import store
from tests import _osm_lane_helpers

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = Path(__file__).resolve().parent.parent


def _lane_with_runs(runs: list[tuple[str, int | None, datetime | None]]) -> None:
    """A lane file holding only ``osm_diff_runs`` rows (alpha3, bytes_fetched, diff_timestamp)."""
    from src.osm.lane_models import OsmDiffRun

    store.create_lane("osm")
    with store.lane_session("osm") as s:
        for i, (a3, nbytes, ts) in enumerate(runs, start=1):
            s.add(OsmDiffRun(alpha3=a3, sequence=100 + i, diff_timestamp=ts, bytes_fetched=nbytes))


def _day(d: int) -> datetime:
    return datetime(2026, 11, d, 21, 0, tzinfo=UTC)


def test_no_lane_file_is_not_opened_and_says_so(osm_lane_dir):
    assert not store.lane_exists("osm")
    got = P.measured_diff_costs(["FRA"])
    assert got == {"FRA": {"diff_measured": None, "diff_measured_reason": P.NOT_MEASURED_NO_LANE}}
    assert not store.lane_exists("osm"), "asking for the measured cost never creates the lane file"


def test_the_median_of_the_measured_files_with_n_and_the_newest_files_own_date(osm_lane_dir):
    _lane_with_runs(
        [
            ("FRA", 1000, _day(18)),
            ("FRA", 3000, _day(20)),
            ("FRA", 2000, _day(19)),
            (
                "FRA",
                None,
                _day(21),
            ),  # applied, size not measured: counted as applied, never as 0 bytes
            ("DEU", None, _day(20)),
        ]
    )
    got = P.measured_diff_costs(["FRA", "DEU", "BEL"])
    assert got["FRA"]["diff_measured_reason"] is None
    assert got["FRA"]["diff_measured"] == {
        "median_bytes": 2000,
        "files_measured": 3,
        "files_applied": 4,
        "through": "2026-11-21",
        "method": P.MEASURED_METHOD,
    }
    assert got["DEU"] == {"diff_measured": None, "diff_measured_reason": P.NOT_MEASURED_NO_SIZE}
    assert got["BEL"] == {"diff_measured": None, "diff_measured_reason": P.NOT_MEASURED_NO_RUN}
    # Nothing is left open: the rebuild's switch refuses while any connection to the lane is still open (row 271's failure).
    with store.held_for_swap("osm"):
        pass


def test_an_even_count_takes_the_middle_two_and_a_file_without_time_gives_no_date(osm_lane_dir):
    _lane_with_runs([("FRA", 1000, None), ("FRA", 2001, None)])
    m = P.measured_diff_costs(["FRA"])["FRA"]["diff_measured"]
    assert m["median_bytes"] == 1500 and m["files_measured"] == 2 and m["through"] is None


def test_an_old_lane_and_an_unreadable_lane_give_their_reason_never_zero(osm_lane_dir, monkeypatch):
    _lane_with_runs([("FRA", 1000, _day(20))])
    with store.lane_session("osm") as s:
        s.execute(sa.text("DROP TABLE osm_diff_runs"))
    assert P.measured_diff_costs(["FRA"])["FRA"] == {
        "diff_measured": None,
        "diff_measured_reason": P.NOT_MEASURED_OLD_LANE,
    }

    def boom(kind):
        raise RuntimeError("the lane could not be opened")

    monkeypatch.setattr(store, "lane_session", boom)
    assert P.measured_diff_costs(["FRA"])["FRA"] == {
        "diff_measured": None,
        "diff_measured_reason": P.NOT_MEASURED_UNREADABLE,
    }


def test_the_picker_carries_it_on_each_chosen_country_and_drops_the_stale_apply_field(
    osm_lane_dir, monkeypatch
):
    _lane_with_runs([("FRA", 4096, _day(20))])
    monkeypatch.setattr(P, "selected", lambda: ["fr", "de"])
    state = P.picker_state("fr")
    by_cc = {r["cc"]: r for r in state["selected"]}
    assert (
        by_cc["fr"]["diff_measured"]["median_bytes"] == 4096
        and by_cc["fr"]["diff_daily_estimate_bytes"] > 0
    )
    assert (
        by_cc["de"]["diff_measured"] is None
        and by_cc["de"]["diff_measured_reason"] == P.NOT_MEASURED_NO_RUN
    )
    assert "apply" not in state["diff"] and "0.6" not in state["diff"]["cadence"]
    assert "diff_measured" not in state["suggested"][0], (
        "only a chosen country is measured; suggestions keep the estimate"
    )
    with store.held_for_swap("osm"):
        pass


def test_every_new_string_ships_in_twelve_languages():
    import json

    strings = [
        P.CADENCE,
        P.MEASURED_METHOD,
        P.NOT_MEASURED_NO_LANE,
        P.NOT_MEASURED_NO_RUN,
        P.NOT_MEASURED_NO_SIZE,
        P.NOT_MEASURED_OLD_LANE,
        P.NOT_MEASURED_UNREADABLE,
        "Before the first daily update: about {size} a day (estimate).",
        "not measured yet",
        "measured here: {n} files, through {date}",
        "measured here: {n} files",
        "a file",
    ]
    for path in sorted((ROOT / "src" / "static" / "locales").glob("*.json")):
        loc = json.loads(path.read_text("utf-8"))
        for s in strings:
            assert s in loc and loc[s], (path.name, s)
            for ph in ("{size}", "{n}", "{date}"):
                assert (ph in s) == (ph in loc[s]), (path.name, s, ph)
        assert not any("Applying it arrives in 0.6" in k for k in loc), path.name


def test_the_cell_runs_as_real_code_under_node():
    proc = subprocess.run(
        ["node", str(ROOT / "tests" / "osm_picker_measured_row278_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all assertions passed" in proc.stdout
