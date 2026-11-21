"""Row 266 (0.6 gate row A): the operator's Wikidata election snapshot run, read back from the file they send.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Three things are pinned. The Diagnostics zip carries ``elections-floor.json`` again, held to one Field data piece with any
cut NAMED, and with no install path or address in it. K13's elections block reads the snapshot's age and staleness from
the one place that computes them (``calendar_report.with_snapshot``, row 258). And ``scripts/elections_readback.py`` prints
every figure the file has, says why for every one it has not, and never turns an absent figure into a 0.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "elections_readback.py"
PART = 200 * 1000  # the Field data button's piece size (app-diagnostics.js FIELD_PART_BYTES)
TODAY = date.today()


def _script():
    spec = importlib.util.spec_from_file_location("oo_elections_readback", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _script()


def _rows(n: int) -> list[dict]:
    from src.civic.coverage_floor import load_floor

    cs = sorted(load_floor()["countries"])
    return [
        {"country": cs[i % len(cs)], "office": f"National Legislative Assembly of the Republic {i}", "qid": f"Q{1000 + i}",
         "point_in_time": f"{TODAY.year + 1 + i % 6}-0{1 + i % 9}-01", "precision": "month"}
        for i in range(n)
    ]


@pytest.fixture()
def snapshot(tmp_path, monkeypatch):
    """Point the snapshot at tmp_path; the test writes it (or not) through the returned function."""
    from src.civic import calendar_report
    from src.events import catalog

    path = tmp_path / "elections_snapshot.json"
    monkeypatch.setattr(calendar_report, "SNAPSHOT_PATH", path)
    catalog.load_events.cache_clear()

    def write(as_of: date | None, rows: list[dict] | None = None) -> Path:
        if as_of is not None:
            path.write_text(json.dumps({"as_of": as_of.isoformat(), "rows": rows or []}), encoding="utf-8")
        catalog.load_events.cache_clear()
        return path

    try:
        yield write
    finally:
        catalog.load_events.cache_clear()


def _member(**kw) -> dict:
    from src.api.diagnostics.bundle import _elections_floor_member

    return _elections_floor_member(**kw)


def _wire(doc: dict) -> bytes:
    from src.api.diagnostics.bundle import _member_bytes

    return _member_bytes(doc)


# --- the member -----------------------------------------------------------------------------------------------------


def test_the_member_carries_the_snapshot_run_and_no_path_or_address(snapshot, tmp_path):
    snapshot(TODAY - timedelta(days=20), _rows(30))
    doc = _member()
    snap = doc["snapshot"]
    assert snap["state"] == "present" and snap["rows"] == 30
    assert (snap["age_days"], snap["stale"]) == (20, False)
    assert "cut" not in doc and doc["tier_report"]["countries"][0].get("entries") is not None
    data = _wire(doc)
    assert len(data) <= PART
    text = data.decode("utf-8")
    # a repo-relative name in the method text (configs/language_countries.yml) is the build's, not the install's
    for leak in (str(tmp_path), "elections_snapshot", "/home/", "/tmp/", "/root/", "/Users/", "file:"):
        assert leak not in text, f"{leak!r} reached the member"
    assert not re.search(r"https?://|\b\d{1,3}(\.\d{1,3}){3}\b|[A-Za-z]:\\\\", text), "an address or a path reached the member"


def test_a_large_snapshot_is_cut_to_one_piece_and_the_cut_is_named(snapshot):
    snapshot(TODAY - timedelta(days=5), _rows(2000))
    from src.api.diagnostics.system import elections_coverage_floor

    full = elections_coverage_floor()
    assert len(_wire(full)) > PART, "the fixture must be over one piece, or this test proves nothing"
    doc = _member()
    assert len(_wire(doc)) <= PART
    assert doc["cut"]["limit_bytes"] == PART and doc["cut"]["bytes_before"] == len(_wire(full))
    assert doc["cut"]["what"] == ["tier_report.countries[].entries (each replaced by entries_n, its count)"]
    rows = doc["tier_report"]["countries"]
    assert all("entries" not in r for r in rows)
    assert sum(r["entries_n"] for r in rows) == sum(len(r["entries"]) for r in full["tier_report"]["countries"])
    # never cut: the snapshot block, the floor's counts and its lists
    assert doc["snapshot"] == full["snapshot"] and doc["snapshot"]["rows"] == 2000
    for key in ("floor_countries", "covered", "covered_n", "missing", "missing_n", "tier_report"):
        assert key in doc
    assert doc["tier_report"]["counts"] == full["tier_report"]["counts"]


def test_when_the_entry_counts_still_do_not_fit_the_rows_go_and_that_is_named_too(snapshot):
    snapshot(TODAY - timedelta(days=5), _rows(10))
    doc = _member(limit=15_000)
    assert [w.split(" ")[0] for w in doc["cut"]["what"]] == ["tier_report.countries[].entries", "tier_report.countries"]
    assert "countries" not in doc["tier_report"] and doc["tier_report"]["countries_n"] == doc["floor_countries"]
    assert doc["snapshot"]["state"] == "present" and doc["tier_report"]["counts"]


def test_a_member_that_cannot_be_built_says_so(monkeypatch):
    from src.api.diagnostics import bundle

    def boom():
        raise RuntimeError("no catalogue")

    monkeypatch.setattr(bundle, "elections_coverage_floor", boom)
    doc = bundle._elections_floor_member()
    assert doc["available"] is False and "RuntimeError" in doc["error"]
    assert R.report(doc) == [f"elections-floor.json could not be built on that machine: {doc['error']}"]


def test_the_bundle_lists_the_member_and_the_route_maps_to_it():
    from src.api.diagnostics import bundle

    src = Path(bundle.__file__).read_text(encoding="utf-8")
    members = src.split("def _all_diagnostics_members", 1)[1].split("\ndef _", 1)[0]
    assert '("elections-floor.json", lambda: _elections_floor_member())' in members
    assert bundle._DIAG_COVERAGE_MAP["/elections-floor"] == "elections-floor.json"


# --- K13 reads the age from the one place ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("as_of", "age", "stale"),
    [(TODAY - timedelta(days=20), 20, False), (TODAY - timedelta(days=200), 200, True), (TODAY + timedelta(days=3), None, True)],
)
def test_k13_reports_the_snapshot_s_own_age_and_staleness(snapshot, as_of, age, stale):
    from src.events.catalog import layered_events
    from src.monitoring import kpi as K

    snapshot(as_of, _rows(3))
    snap = layered_events()[1]
    block = K._elections_block()
    assert (block["snapshot_age_days"], block["snapshot_stale"]) == (snap["age_days"], snap["stale"]) == (age, stale)
    assert block["snapshot_stale_after_days"] == snap["stale_after_days"]


def test_k13_has_no_age_when_there_is_no_snapshot(snapshot):
    from src.monitoring import kpi as K

    snapshot(None)
    block = K._elections_block()
    assert block["snapshot_state"] == "absent"
    assert (block["snapshot_age_days"], block["snapshot_stale"]) == (None, None)


def test_the_kpi_module_computes_no_snapshot_age_of_its_own():
    src = (ROOT / "src" / "monitoring" / "kpi.py").read_text(encoding="utf-8")
    assert '_age_days(snap.get("as_of"))' not in src


# --- the read-back --------------------------------------------------------------------------------------------------


def _route_file(tmp_path: Path) -> Path:
    from src.api.diagnostics.system import elections_coverage_floor

    out = tmp_path / "oo-field-20261121-1400-p8000-elections-floor.json"
    out.write_text(json.dumps(elections_coverage_floor()), encoding="utf-8")
    return out


def test_the_readback_prints_the_snapshot_run_and_the_floor(snapshot, tmp_path):
    snapshot(TODAY - timedelta(days=200), _rows(4))
    doc = R.load(_route_file(tmp_path))
    text = "\n".join(R.report(doc))
    assert f"snapshot: present, dated {(TODAY - timedelta(days=200)).isoformat()}" in text
    assert "age: 200 days, past the 90-day limit: STALE, run the snapshot again" in text
    assert "counts: 4 rows in the file · 4 added to the calendar · 0 shadowed by a curated entry" in text
    assert f"floor: {doc['floor_countries']:,} countries" in text
    assert f"{doc['covered_n']:,} covered · " in text and f"{doc['missing_n']:,} missing" in text
    assert "tier report: " in text and "cut to fit" not in text
    assert "%" not in text


def test_an_absent_snapshot_says_why_and_prints_no_figure(snapshot, tmp_path):
    snapshot(None)
    lines = R.report(R.load(_route_file(tmp_path)))
    (snap_line,) = [ln for ln in lines if ln.startswith("snapshot:")]
    assert snap_line.startswith("snapshot: absent: no Wikidata election snapshot on this machine")
    assert not any(ln.startswith(("age:", "counts:")) for ln in lines), "an absent snapshot was given figures"


@pytest.mark.parametrize(
    ("snap", "want"),
    [
        ({"state": "present", "as_of": "2026-11-01", "rows": 4}, "age: not recorded by this build (before row 258)"),
        ({"state": "present", "as_of": "2026-11-01", "age_days": None, "stale": True, "stale_after_days": 90},
         "age: not computable: the snapshot is dated after the day it was read"),
        ({"state": "present", "as_of": "2026-11-01", "age_days": 3}, "age: 3 days; staleness not recorded in this file"),
        ({"state": "present", "as_of": "2026-11-01"}, "rows in the file: not recorded in this file"),
        ({"state": "present", "as_of": "2026-11-01", "rows": "many"}, "rows in the file: not a count in this file ('many')"),
        ({"state": "unreadable"}, "snapshot: unreadable: a snapshot file is there"),
        (None, "snapshot: not recorded in this file"),
    ],
)
def test_an_absent_figure_is_printed_with_its_reason_never_as_zero(snap, want):
    lines = R.report({"snapshot": snap})
    text = "\n".join(lines)
    assert want in text
    assert "floor: no floor figures in this file" in text and "tier report: not recorded in this file" in text
    assert not re.search(r"(?<![\w.-])0 ", text), "an absent figure was printed as 0"


def test_the_member_is_read_out_of_a_diagnostics_zip_and_a_cut_is_printed(snapshot, tmp_path):
    snapshot(TODAY - timedelta(days=5), _rows(10))
    zpath = tmp_path / "oo-all-diagnostics.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("elections-floor.json", _wire(_member(limit=15_000)))
        zf.writestr("manifest.json", "{}")
    text = "\n".join(R.report(R.load(zpath)))
    assert "snapshot: present" in text
    assert "cut to fit 15,000 bytes (was " in text and "tier_report.countries (replaced by countries_n" in text


def test_a_zip_without_the_member_and_an_omitted_member_are_named(tmp_path):
    zpath = tmp_path / "old.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("manifest.json", "{}")
    with pytest.raises(ValueError, match="no elections-floor.json member"):
        R.load(zpath)
    omitted = {"omitted": True, "member": "elections-floor.json", "reason": "over the cap"}
    assert R.report(omitted) == ["elections-floor.json was left out of the archive: over the cap"]


def test_a_piece_set_is_joined_and_a_missing_piece_is_named_never_guessed(snapshot, tmp_path):
    snapshot(TODAY - timedelta(days=5), _rows(4))
    data = _route_file(tmp_path).read_bytes()
    cut = len(data) // 2
    p1 = tmp_path / "oo-field-x-elections-floor-part-001-of-002.json"
    p2 = tmp_path / "oo-field-x-elections-floor-part-002-of-002.json"
    p1.write_bytes(data[:cut])
    p2.write_bytes(data[cut:])
    assert R.load(p2)["snapshot"]["rows"] == 4
    p1.unlink()
    with pytest.raises(ValueError, match="pieces 1 of 2 missing"):
        R.load(p2)


def test_the_script_runs_from_the_command_line(snapshot, tmp_path, capsys):
    snapshot(TODAY - timedelta(days=5), _rows(2))
    path = _route_file(tmp_path)
    assert R.main([str(path)]) == 0
    assert "snapshot: present" in capsys.readouterr().out
    assert R.main([str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rows"] == 2
    bad = tmp_path / "bad.json"
    bad.write_bytes(b"{not json")
    assert R.main([str(bad)]) == 2
    assert "not a JSON file" in capsys.readouterr().err


def test_the_script_is_stdlib_only():
    src = SCRIPT.read_text(encoding="utf-8")
    imported = set(re.findall(r"^(?:from|import) (\w+)", src, re.M))
    assert imported <= {"__future__", "argparse", "importlib", "io", "json", "sys", "zipfile", "pathlib", "typing"}
    assert io  # the zip path is read in memory, never extracted to disk
