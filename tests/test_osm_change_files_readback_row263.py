"""Row 263 (0.6 gate row B): the OSM change-file cost the Field data button saves, and the script that reads it back.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The file is the Diagnostics zip's own ``osm-change-files.json`` member, saved from ``/api/osm/change-files``. The script must print what
each country's daily change files cost and never turn an absent figure into a 0, and it must print counts, country codes, sequence
numbers and dates only: no object, tag, coordinate, path or address.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from tests import _osm_lane_helpers
from tests.test_osm_apply import DAY1, Mirror, _extract
from tests.test_osm_diagnostics import DAY2

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "osm_change_files_readback.py"
osm_lane_dir = _osm_lane_helpers.osm_lane_dir


def _script():
    spec = importlib.util.spec_from_file_location("oo_osm_change_files_readback", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _script()


@pytest.fixture
def applied(osm_lane_dir):
    """ZZ cut, then two daily change files applied (the diagnostics member's own fixtures)."""
    from src.osm import apply as A
    from src.osm import ingest

    assert ingest.ingest_country(_extract(osm_lane_dir), "ZZ", reader="python").status == "complete"
    A.update_country("ZZ", Mirror(102, {101: DAY1, 102: DAY2}), workdir=osm_lane_dir / "w", kill_switch=lambda: False)
    return osm_lane_dir


def _route_file(tmp_path: Path) -> Path:
    from src.api.osm_lane import change_files

    out = tmp_path / "oo-field-20261121-1500-p8000-osm-change-files.json"
    out.write_text(json.dumps(change_files()), encoding="utf-8")
    return out


#: Everything in the reasons-only fixture below that is a figure is absent; only reasons are given.
REASONS_ONLY = {
    "lane": "present",
    "countries": [
        {
            "alpha3": "ZZZ", "status": "complete",
            "position": {"from": None, "sequence": None, "timestamp": None, "reason": "this country carries no recorded position (cut before positions were stored)"},
            "diffs_recorded": None, "last_applied_at": None, "gaps_total": None, "rebaselines": None, "hand_recuts_seen": None,
            "gaps": [], "gaps_not_shown": 0,
            "cost": None, "cost_reason": "this table is not in the lane (it was cut by an older build); re-cutting the country creates it",
            "gaps_reason": "this table is not in the lane (it was cut by an older build); re-cutting the country creates it",
            "cursor_token": None, "cursor_reason": "this table is not in the lane (it was cut by an older build); re-cutting the country creates it",
            "runs": [], "runs_not_shown": 0,
        },
        {
            "alpha3": "YYY", "status": "complete",
            "position": {"from": "extract", "sequence": None, "timestamp": None, "reason": "this country carries no recorded position (cut before positions were stored)"},
            "diffs_recorded": None, "gaps_total": None,
            "cost": {"bytes_fetched": None, "fetch_seconds": None, "apply_seconds": None, "method": "x",
                     "unmeasured": dict.fromkeys(("apply_seconds", "bytes_fetched", "fetch_seconds"), "no recorded change file carries this measurement")},
            "runs": [], "runs_not_shown": 0,
        },
    ],
    "countries_without_updates": [], "countries_without_updates_not_shown": 0, "countries_not_shown": 0,
    "dropped_to_fit": {"runs": 0, "gaps": 0},
    "street_view": {"state": "not measured", "reason": "no frame budget has been recorded on this machine"},
}


def test_two_applied_files_are_read_back_with_their_cost_and_nothing_but_counts_codes_and_dates(applied):
    text_in = _route_file(applied).read_text(encoding="utf-8")
    lines = R.report(R.load(applied / "oo-field-20261121-1500-p8000-osm-change-files.json"))
    text = "\n".join(lines)
    assert "ZZZ (complete): position 102 from the change file" in text
    assert "2 change files applied" in text
    total = len(DAY1) + len(DAY2)
    assert f"bytes fetched: 2 files measured, total {total:,}, mean per file {total / 2:,.3f}".rstrip("0").rstrip(".") in text
    assert "fetch: 2 files measured" in text and "apply: 2 files measured" in text
    assert re.search(r"file 102 of \d{4}-\d\d-\d\d", text) and re.search(r"file 101 of \d{4}-\d\d-\d\d", text)
    assert "gaps: 0 (re-baselines 0, hand re-cuts 0)" in text
    assert "cut to fit the member's budget: nothing" in text
    assert "not in the member's fixed words" not in text, "every reason the member writes is printed"
    for content in ("amenity", "bench", "0.12", "http", "/", "osm.pbf"):
        assert content not in text, f"{content!r} reached the read-back"
    assert "bench" not in text_in, "the Field data file itself carries no tag value"


def test_a_file_with_only_reasons_prints_every_reason_and_no_figure():
    """Condition (3) of row 263: no figure in, no figure out; every line says why instead."""
    text = "\n".join(R.report(REASONS_ONLY))
    assert "ZZZ (complete): position not recorded: this country carries no recorded position" in text
    assert "change files: not recorded: this table is not in the lane" in text
    assert "  cost: not measured: this table is not in the lane" in text
    assert "  gaps: not recorded: this table is not in the lane" in text
    for label in ("bytes fetched", "fetch", "apply"):
        assert f"  {label}: not measured: no recorded change file carries this measurement" in text
    assert "street view frame budget: not measured: no frame budget has been recorded" in text
    assert "not in the member's fixed words" not in text
    figures = [ln for ln in text.splitlines() if re.search(r"\d", ln) and not ln.startswith("2 countries")]
    assert figures == [], f"a figure was printed for a file that holds none: {figures}"


def test_some_files_without_a_measurement_are_said_not_averaged_away():
    row = {"alpha3": "ZZZ", "status": "complete", "position": {"from": "change file", "sequence": 9, "timestamp": "2025-01-12T00:00:00+00:00"},
           "diffs_recorded": 3, "gaps_total": 0, "rebaselines": 0, "hand_recuts_seen": 0,
           "cost": {"bytes_fetched": {"n": 3, "total": 300, "max": 120}, "fetch_seconds": {"n": 1, "total": 2.5, "max": 2.5},
                    "apply_seconds": None, "unmeasured": {"apply_seconds": "no recorded change file carries this measurement"}}}
    out = "\n".join(R.cost_lines(row))
    assert "bytes fetched: 3 files measured, total 300, mean per file 100, largest 120" in out
    assert "fetch: 1 files measured, total 2.5 s, mean per file 2.5 s, largest 2.5 s (2 of 3 files did not measure it)" in out
    assert "apply: not measured: no recorded change file carries this measurement" in out


def test_an_absent_lane_and_an_omitted_member_say_so_and_print_no_figure(osm_lane_dir, tmp_path):
    text = "\n".join(R.report(R.load(_route_file(tmp_path))))
    assert text == "the OSM lane was not read: no OpenStreetMap country has been cut on this install"
    omitted = R.report({"omitted": "max_bytes is below the member's fixed part", "over_budget": True, "needs_at_least_bytes": 412})
    assert omitted == ["the member was omitted: max_bytes is below the member's fixed part (needs at least 412 bytes)"]


def test_a_piece_set_is_joined_and_a_missing_piece_is_named_never_guessed(applied, tmp_path):
    data = _route_file(applied).read_bytes()
    cut = len(data) // 2
    p1 = tmp_path / "oo-field-x-osm-change-files-part-001-of-002.json"
    p2 = tmp_path / "oo-field-x-osm-change-files-part-002-of-002.json"
    p1.write_bytes(data[:cut])
    p2.write_bytes(data[cut:])
    assert R.load(p2)["lane"] == "present"
    p1.unlink()
    with pytest.raises(ValueError, match="pieces 1 of 2 missing"):
        R.load(p2)


def test_the_member_is_read_out_of_a_diagnostics_zip_and_a_zip_without_it_is_named(applied, tmp_path):
    member = _route_file(applied).read_bytes()
    z = tmp_path / "oo-diagnostics.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("osm-change-files.json", member)
    assert "2 change files applied" in "\n".join(R.report(R.load(z)))
    bare = tmp_path / "other.zip"
    with zipfile.ZipFile(bare, "w") as zf:
        zf.writestr("manifest.json", "{}")
    with pytest.raises(ValueError, match="a zip without osm-change-files.json"):
        R.load(bare)


def test_malformed_shapes_are_said_never_a_crash_and_free_text_is_not_printed():
    row = {"alpha3": "../etc", "status": "x y", "position": "nope", "diffs_recorded": True, "cost": {"bytes_fetched": {"n": "2"}},
           "gaps_total": "1", "runs": [{"sequence": "1", "diff_timestamp": "Main Street 1"}, "x"], "runs_not_shown": None}
    text = "\n".join(R.country_lines(row))
    assert text.startswith("? (?): position not recorded")
    assert "Main Street" not in text and "../etc" not in text
    assert "bytes fetched: not measured: absent from this file" in text and "gaps: not recorded" in text
    assert R.report({"countries": "x", "street_view": "y"})[-1] == "street view frame budget: absent from this file"
    leaky = {"alpha3": "ZZZ", "cost": None, "cost_reason": "see 12 Main Street, https://example.org/x"}
    assert "Main Street" not in "\n".join(R.country_lines(leaky)) and "not in the member's fixed words" in R.cost_lines(leaky)[0]


def test_the_script_runs_stdlib_only_from_the_command_line(applied, tmp_path):
    f = _route_file(applied)
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(f)], capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, out.stderr
    assert "2 change files applied" in out.stdout
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(bad)], capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 2 and "not a JSON file" in out.stderr
