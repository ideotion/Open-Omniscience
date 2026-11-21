"""Row 276 (0.6 gate row B): what each applied change file did to tags, counted in the Field data file and read back.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Gate row B closes on "a real day-over-day tag change ... from an applied diff (the diff's timestamp as the artifact)". The
``osm-change-files`` member now carries, per applied file and for the country, the COUNT of ``osm_tag_changes`` rows by change and
of objects by how they took part, joined on the file's own time and the country. Never a key, a value or an object id. A count the
lane cannot give is null with its reason. The member reads through its own lane session and leaves nothing open.

Expected values for DAY1 are written out from ``tests/test_osm_tag_rows.py``'s exact row list (20 rows), never computed by the member.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa

from src.osm import apply as A
from src.osm import diagnostics as D
from src.osm import ingest
from src.osm.lane_models import OsmDiffRun, OsmTagChange
from src.versioned import store
from tests import _osm_lane_helpers
from tests.test_osm_apply import DAY1, DAY2, Mirror, _extract

osm_lane_dir = _osm_lane_helpers.osm_lane_dir
ROOT = Path(__file__).resolve().parent.parent

#: DAY1's 20 rows (test_osm_tag_rows.py): added n30 amenity, w40 highway + name, r110 name + tourism; modified n5 opening_hours,
#: w12 name; removed 8 keys of n5, 2 of w12, 3 of n7. Objects: created n30 w40 r110, deleted n7, tags changed n5 w12.
DAY1_TAGS = {
    "rows": 20,
    "added": 5,
    "removed": 13,
    "modified": 2,
    "objects_created": 3,
    "objects_deleted": 1,
    "objects_left_class": 0,
    "objects_tags_changed": 2,
}


def _readback():
    spec = importlib.util.spec_from_file_location(
        "oo_osm_change_files_readback_276", ROOT / "scripts" / "osm_change_files_readback.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def applied(osm_lane_dir):
    assert ingest.ingest_country(_extract(osm_lane_dir), "ZZ", reader="python").status == "complete"
    rep = A.update_country(
        "ZZ",
        Mirror(102, {101: DAY1, 102: DAY2}),
        workdir=osm_lane_dir / "w",
        kill_switch=lambda: False,
    )
    assert rep.outcome == "applied", rep.reason
    return osm_lane_dir


def _table_counts(when) -> int:
    with store.lane_session("osm") as s:
        return s.execute(
            sa.select(sa.func.count())
            .select_from(OsmTagChange)
            .where(OsmTagChange.diff_timestamp == when, OsmTagChange.country_alpha3 == "ZZZ")
        ).scalar_one()


def test_each_applied_file_carries_its_tag_counts_joined_on_its_own_time(applied):
    (c,) = D.diagnostics_member(20_000)["countries"]
    by_seq = {r["sequence"]: r for r in c["runs"]}
    assert by_seq[101]["tag_changes"] == DAY1_TAGS
    with store.lane_session("osm") as s:
        t102 = s.query(OsmDiffRun).filter_by(alpha3="ZZZ", sequence=102).one().diff_timestamp
    day2 = by_seq[102]["tag_changes"]
    assert day2["rows"] == _table_counts(t102) > 0, (
        "the second day's rows are its own, not the first day's"
    )
    assert day2["rows"] == day2["added"] + day2["removed"] + day2["modified"]
    total = c["tag_changes_total"]
    assert total == {k: DAY1_TAGS[k] + day2[k] for k in DAY1_TAGS}, (
        "the country's total is every file's rows"
    )
    assert c["tag_rows_time_not_recorded"] == 0


def test_no_key_value_or_object_id_reaches_the_member_and_nothing_is_left_open(applied):
    text = json.dumps(D.diagnostics_member(20_000))
    for leak in (
        "amenity",
        "bench",
        "Fixture",
        "New Road",
        "opening_hours",
        "cafe.invalid",
        '"osm_id"',
        '"key"',
    ):
        assert leak not in text, f"{leak!r} reached the member"
    # The rebuild's own switch refuses while any connection to the lane is still open (row 271's failure): the member must leave none.
    with store.held_for_swap("osm"):
        pass


def test_rows_whose_file_stated_no_time_are_counted_for_the_country_and_given_to_no_file(applied):
    with store.lane_session("osm") as s:
        t101 = s.query(OsmDiffRun).filter_by(alpha3="ZZZ", sequence=101).one().diff_timestamp
        s.execute(
            sa.update(OsmTagChange)
            .where(OsmTagChange.diff_timestamp == t101, OsmTagChange.object_event == "deleted")
            .values(diff_timestamp=None)
        )
    (c,) = D.diagnostics_member(20_000)["countries"]
    run101 = next(r for r in c["runs"] if r["sequence"] == 101)
    assert run101["tag_changes"]["rows"] == 17 and run101["tag_changes"]["objects_deleted"] == 0
    assert c["tag_rows_time_not_recorded"] == 3
    assert (
        c["tag_changes_total"]["rows"]
        == 20 + next(r for r in c["runs"] if r["sequence"] == 102)["tag_changes"]["rows"]
    )


def test_two_files_with_one_time_and_a_file_with_none_are_null_with_a_reason_never_a_share(applied):
    with store.lane_session("osm") as s:
        runs = {r.sequence: r for r in s.query(OsmDiffRun).filter_by(alpha3="ZZZ")}
        runs[102].diff_timestamp = runs[101].diff_timestamp
    (c,) = D.diagnostics_member(20_000)["countries"]
    for r in c["runs"]:
        assert r["tag_changes"] is None and "same time" in r["tag_changes_reason"]
    with store.lane_session("osm") as s:
        for r in s.query(OsmDiffRun).filter_by(alpha3="ZZZ"):
            r.diff_timestamp = None
    (c,) = D.diagnostics_member(20_000)["countries"]
    assert all(
        r["tag_changes"] is None and "states no time" in r["tag_changes_reason"] for r in c["runs"]
    )


def test_a_lane_without_the_tag_table_says_so_never_zero(applied):
    with store.lane_session("osm") as s:
        s.execute(sa.text("DROP TABLE osm_tag_changes"))
    (c,) = D.diagnostics_member(20_000)["countries"]
    assert c["tag_changes_total"] is None and c["tag_changes_reason"] == D._OLD_LANE
    assert all(
        r["tag_changes"] is None and r["tag_changes_reason"] == D._OLD_LANE for r in c["runs"]
    )
    text = "\n".join(_readback().country_lines(c))
    assert (
        "all files, tag changes: not given: this table is not in the lane" in text
        and "key rows" not in text
    )


def test_the_read_back_prints_each_files_tag_counts_and_says_when_a_file_has_none(applied):
    R = _readback()
    text = "\n".join(R.report(D.diagnostics_member(20_000)))
    assert (
        "    tag changes: 20 key rows (added 5, removed 13, modified 2); objects created 3, deleted 1, left their class 0, tags changed 2"
        in text
    )
    assert "  all files, tag changes: " in text
    older = {"alpha3": "ZZZ", "runs": [{"sequence": 9}]}
    assert "tag changes: not in this file (an older build)" in "\n".join(R.country_lines(older))
