"""The Living sources view of the OSM lane's daily change files: counts, the newest file's date and each re-baseline, dated (v0.6.0 B1, S06-01 S5, R427).

Expected values are written out from the fixtures' own sequence numbers and times, never computed by the block.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import timedelta

import pytest
import sqlalchemy as sa

from src.osm import apply as A
from src.osm import daily_view as V
from src.osm import ingest
from src.osm.lane_models import OsmCountry
from src.versioned import store
from tests import _osm_lane_helpers
from tests.test_osm_apply import DAY1, SEQ0, T0, Mirror, _extract

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def cut(osm_lane_dir):
    path = _extract(osm_lane_dir)
    assert ingest.ingest_country(path, "ZZ", reader="python").status == "complete"
    return path


def _update(osm_lane_dir):
    return A.update_country("ZZ", Mirror(101, {101: DAY1}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)


def _rebaseline(osm_lane_dir, days):
    (osm_lane_dir / f"fresh{days}").mkdir()
    A.rebaseline("ZZ", _extract(osm_lane_dir / f"fresh{days}", seq=SEQ0 + days, when=T0 + timedelta(days=days)), reason="past retention", reader="python")


def test_a_lane_that_never_ran_is_named_and_not_created(osm_lane_dir):
    assert V.daily_block() == {"measured": False, "reason": "lane-never-run"}
    assert not store.lane_exists("osm"), "reading the block must not create the lane file"


def test_a_cut_country_no_file_has_reached_reads_zero_files_not_missing_and_no_newest_date(cut):
    got = V.daily_block()
    assert got["measured"] is True
    assert (got["countries_cut"], got["countries_updated"], got["files_applied"]) == (1, 0, 0)
    assert got["newest_file_at"] is None and got["last_applied_at"] is None
    assert (got["rebaselines_total"], got["hand_recuts"], got["rebaselines"]) == (0, 0, [])
    assert "reasons" not in got


def test_an_applied_file_is_counted_and_dated_by_its_own_timestamp(cut, osm_lane_dir):
    assert _update(osm_lane_dir).outcome == "applied"
    got = V.daily_block()
    assert (got["countries_cut"], got["countries_updated"], got["files_applied"]) == (1, 1, 1)
    with store.lane_session("osm") as s:
        stamp = s.query(OsmCountry.diff_timestamp).scalar()
    assert got["newest_file_at"] == stamp.isoformat(), "the file's own date, not the day it was applied here"
    assert got["last_applied_at"] is not None


def test_a_rebaseline_is_a_dated_event_with_its_country_and_a_hand_recut_is_counted_apart(cut, osm_lane_dir):
    _update(osm_lane_dir)
    _rebaseline(osm_lane_dir, 200)
    got = V.daily_block()
    assert (got["rebaselines_total"], got["hand_recuts"], got["rebaselines_not_shown"]) == (1, 0, 0)
    (ev,) = got["rebaselines"]
    assert ev["alpha3"] == "ZZZ" and ev["detected_at"] and ev["to_time"] == (T0 + timedelta(days=200)).isoformat()
    assert set(ev) == {"alpha3", "detected_at", "from_time", "to_time"}, "nothing else leaves: no token, no free text"


def test_a_budget_gap_is_a_hand_recut_not_a_rebaseline(cut, osm_lane_dir):
    _update(osm_lane_dir)
    ingest.ingest_country(cut, "ZZ", reader="python")  # the operator re-cut from the same extract: the position is back to the extract's
    _update(osm_lane_dir)  # the next update finds the cursor and the objects disagreeing and publishes the gap
    got = V.daily_block()
    assert got["hand_recuts"] == 1, "one hand re-cut"
    assert got["rebaselines_total"] == 0 and got["rebaselines"] == [], "and it is not folded into the re-baselines"


def test_both_kinds_of_gap_together_stay_separate(cut, osm_lane_dir):
    _update(osm_lane_dir)
    ingest.ingest_country(cut, "ZZ", reader="python")
    _update(osm_lane_dir)
    _rebaseline(osm_lane_dir, 200)
    got = V.daily_block()
    assert (got["hand_recuts"], got["rebaselines_total"], len(got["rebaselines"])) == (1, 1, 1)


def test_events_are_newest_first_and_cut_with_the_cut_counted(cut, osm_lane_dir, monkeypatch):
    for days in (200, 400, 600):
        _rebaseline(osm_lane_dir, days)
    monkeypatch.setattr(V, "EVENTS_KEPT", 2)
    got = V.daily_block()
    assert got["rebaselines_total"] == 3 and got["rebaselines_not_shown"] == 1 and len(got["rebaselines"]) == 2
    times = [e["detected_at"] for e in got["rebaselines"]]
    assert times == sorted(times, reverse=True)


def test_a_lane_cut_before_the_run_and_gap_tables_says_why_and_never_reads_zero(cut):
    from src.osm.lane_models import OsmDiffRun
    from src.versioned.models import VersionedGap

    with store.lane_session("osm") as s:
        for model in (OsmDiffRun, VersionedGap):
            s.execute(sa.text(f"DROP TABLE {model.__tablename__}"))
    got = V.daily_block()
    assert got["measured"] is True and got["countries_cut"] == 1
    for key in ("files_applied", "last_applied_at", "rebaselines_total", "hand_recuts"):
        assert got[key] is None and key in got["reasons"], key
    assert got["rebaselines"] == []


def test_an_unreadable_lane_is_named_without_the_errors_words(cut, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret path /home/someone/x")

    monkeypatch.setattr(store, "lane_session", boom)
    got = V.daily_block()
    assert got["measured"] is False and got["reason"] == "unreadable"
    assert "secret" not in repr(got) and "/home" not in repr(got)


def test_the_block_makes_no_request_and_imports_no_socket_library():
    tree = ast.parse((ROOT / "src/osm/daily_view.py").read_text("utf-8"))
    names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & {"requests", "httpx", "urllib", "socket", "http"}


def test_the_overview_carries_the_block_on_the_osm_source_only():
    src = (ROOT / "src/api/living.py").read_text("utf-8")
    assert '"daily": _osm_daily()' in src
    assert src.count('"daily"') == 1
